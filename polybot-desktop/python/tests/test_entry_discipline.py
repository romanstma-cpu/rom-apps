import asyncio
from datetime import datetime, timezone

import pytest

import trader
from conftest import US_FEE_APRIL, US_FEE_JULY
import db
from config import merge_with_defaults
from execution_quality import signal_problem


@pytest.mark.parametrize("field,value", [
    ("price", None), ("price", float("nan")), ("price", float("inf")),
    ("price", 0), ("price", 1), ("price", -0.2), ("price", True),
    ("confidence", float("nan")), ("confidence", float("inf")),
    ("confidence", 101), ("confidence", -1), ("confidence", "broken"),
    ("taker_side", "maybe"),
])
def test_bad_signals_cannot_rank_or_bypass_custom_rules(field, value):
    signal = {"price": 0.6, "confidence": 80, "taker_side": "yes", field: value}
    cfg = merge_with_defaults({"use_rules": True})
    assert signal_problem(signal, "whale")
    assert trader._compute_edge(signal, "whale") == float("-inf")
    assert trader.should_trade(signal, "whale", cfg)[0] is False
    # Must return before any database, quote request or order operation.
    assert asyncio.run(trader.execute_signal(signal, "whale", cfg, 1000)) is None


def test_supported_signal_remains_valid():
    assert signal_problem({"price": 0.6, "confidence": 80, "direction": "no"}, "momentum") is None


def test_failed_balance_refresh_stops_cycle_before_signal_selection(monkeypatch):
    cfg = merge_with_defaults({"enable_trading": True})
    monkeypatch.setattr(trader, "get_env", lambda: "mainnet")
    monkeypatch.setattr(trader, "_is_blocked_by_daily_risk", lambda *a: (False, ""))
    monkeypatch.setattr(trader, "_lifetime_loss_tripped_main", lambda *a: (False, ""))
    monkeypatch.setattr(trader, "can_open_new_entries", lambda *a: (True, ""))
    monkeypatch.setattr(trader, "_is_blocked_by_trading_hours", lambda *a: (False, ""))
    monkeypatch.setattr(trader, "_balance_cache", {})
    responses = iter([{"balance": 100000}, RuntimeError("offline")])

    async def balance():
        value = next(responses)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(trader, "get_balance", balance)
    asyncio.run(trader.refresh_balance(cfg, force=True))
    asyncio.run(trader.refresh_balance(cfg, force=True))
    assert asyncio.run(trader.scan_for_trades(cfg)) == []
    assert "Balance unavailable" in trader.last_cycle["skipReason"]


@pytest.mark.parametrize("second_side,second_confidence,healthy_after_entry,expected", [
    ("no", 80, True, 0), ("no", 10, True, 1), ("yes", 80, True, 2),
    ("yes", 80, False, 1),
])
def test_cycle_defers_only_eligible_direction_conflicts(tmp_path, monkeypatch, second_side, second_confidence, healthy_after_entry, expected):
    monkeypatch.setattr(db, "db_path", lambda: tmp_path / "signals.db")
    db.init_db()
    cfg = merge_with_defaults({"enable_trading": True, "trade_whales": True,
        "trade_momentum": False, "min_confidence_whale": 60,
        "min_entry_price_cents": 1, "max_entry_price_cents": 99})
    monkeypatch.setattr(trader, "get_env", lambda: "mainnet")
    monkeypatch.setattr(trader, "_is_blocked_by_daily_risk", lambda *a: (False, ""))
    monkeypatch.setattr(trader, "_lifetime_loss_tripped_main", lambda *a: (False, ""))
    monkeypatch.setattr(trader, "can_open_new_entries", lambda *a: (True, ""))
    monkeypatch.setattr(trader, "_is_blocked_by_trading_hours", lambda *a: (False, ""))
    health = iter([True, healthy_after_entry, healthy_after_entry])
    monkeypatch.setattr(trader, "last_balance_read_ok", lambda *a: next(health))
    signals = [{"id": 1, "ticker": "SAME", "price": 0.5, "confidence": 80, "taker_side": "yes"},
               {"id": 2, "ticker": "SAME", "price": 0.5, "confidence": second_confidence, "taker_side": second_side}]
    monkeypatch.setattr(db, "fetch_tradeable_whale_signals", lambda *a, **k: signals)
    calls = []

    async def balance(*a, **k):
        return 100000, 0

    async def execute(signal, *a, **k):
        calls.append(signal)
        return {"status": "submitted"}

    monkeypatch.setattr(trader, "refresh_balance", balance)
    monkeypatch.setattr(trader, "execute_signal", execute)
    asyncio.run(trader.scan_for_trades(cfg))
    assert len(calls) == expected
    if expected == 0:
        assert any("disagree" in reason for reason in trader.last_cycle["filterCounts"])
    if not healthy_after_entry:
        assert "remaining entries deferred" in trader.last_cycle["skipReason"]


def test_practice_trade_uses_live_entry_path_without_exchange_order(
    tmp_path, monkeypatch, fee_clock
):
    at = fee_clock(US_FEE_JULY)
    monkeypatch.setattr(db, "db_path", lambda: tmp_path / "paper.db")
    db.init_db()
    cfg = merge_with_defaults({"enable_trading": False, "main_paper_trading": True})
    monkeypatch.setattr(trader, "get_env", lambda: "mainnet")

    async def quote(*_a):
        return {"bid_cents": 59, "ask_cents": 60}

    async def meta(*_a):
        return {"min_size": 1}

    async def forbidden_order(**_kw):
        pytest.fail("practice mode must never call the order API")

    monkeypatch.setattr(trader, "get_quote", quote)
    monkeypatch.setattr(trader, "get_market_meta", meta)
    monkeypatch.setattr(trader, "place_limit_order", forbidden_order)
    signal = {"id": 42, "ticker": "PAPER", "event_ticker": "EV", "title": "Practice",
              "created_at": at.isoformat(),
              "category": "sports", "price": 0.60, "confidence": 80, "taker_side": "yes"}
    row = asyncio.run(trader.execute_signal(signal, "whale", cfg, 1000, paper=True))
    assert row["status"] == "dry_run"
    assert row["signal_id"] == -42
    assert row["filled_contracts"] == row["target_contracts"] > 0
    assert row["avg_fill_price_cents"] == 60
    # $50 budget at 60c reserves 62c per contract (60c + a 2c fee rounded up
    # per contract), so 80 fit. The recorded cost carries the *actual* fee,
    # which is not rounded up: 0.06 x 80 x 0.6 x 0.4 = $1.15.
    assert row["filled_contracts"] == 80
    assert row["cost_usd"] == pytest.approx(80 * 0.60 + 1.15)
    assert row["cost_usd"] <= cfg['hard_max_position_usd']
    with db.get_db() as conn:
        paper = db.paper_account_stats(conn, "mainnet", 1000)
        assert paper["open"] == 1
        assert paper["available_usd"] == pytest.approx(1000 - row["cost_usd"])
        assert db.already_paper_traded_signal_ids(conn, "whale", "mainnet") == {42}
        assert 42 not in db.already_traded_signal_ids(conn, "whale", "mainnet")


def test_practice_trade_charges_the_schedule_in_force_at_the_time(
    tmp_path, monkeypatch, fee_clock
):
    """The same trade must cost less under the April schedule than under July.

    Reserving rounds the per-contract fee up to a whole cent, so both
    schedules fit 80 contracts at 60c; only the recorded cost separates them.
    """
    def run(at):
        monkeypatch.setattr(db, "db_path", lambda: tmp_path / f"paper-{at:%Y%m}.db")
        db.init_db()
        cfg = merge_with_defaults({"enable_trading": False, "main_paper_trading": True})
        monkeypatch.setattr(trader, "get_env", lambda: "mainnet")

        async def quote(*_a):
            return {"bid_cents": 59, "ask_cents": 60}

        async def meta(*_a):
            return {"min_size": 1}

        monkeypatch.setattr(trader, "get_quote", quote)
        monkeypatch.setattr(trader, "get_market_meta", meta)
        signal = {"id": 42, "ticker": "PAPER", "event_ticker": "EV", "title": "Practice",
                  "created_at": at.isoformat(), "category": "sports",
                  "price": 0.60, "confidence": 80, "taker_side": "yes"}
        return asyncio.run(
            trader.execute_signal(signal, "whale", cfg, 1000, paper=True))

    april = run(fee_clock(US_FEE_APRIL))
    july = run(fee_clock(US_FEE_JULY))

    assert april["filled_contracts"] == july["filled_contracts"] == 80
    # 0.05 x 80 x 0.6 x 0.4 = $0.96  vs  0.06 x 80 x 0.6 x 0.4 = $1.15
    assert april["cost_usd"] == pytest.approx(80 * 0.60 + 0.96)
    assert july["cost_usd"] == pytest.approx(80 * 0.60 + 1.15)
    assert july["cost_usd"] > april["cost_usd"]


def test_practice_trade_settles_into_separate_paper_performance(
    tmp_path, monkeypatch, fee_clock
):
    test_practice_trade_uses_live_entry_path_without_exchange_order(
        tmp_path, monkeypatch, fee_clock)

    async def markets(_tickers):
        return {"PAPER": {"ticker": "PAPER", "result": "yes", "status": "settled"}}

    monkeypatch.setattr(trader, "fetch_markets_map", markets)
    rows = asyncio.run(trader.mark_resolved_positions({}))
    assert len(rows) == 1 and rows[0]["status"] == "dry_run"
    with db.get_db() as conn:
        paper = db.paper_account_stats(conn, "mainnet", 1000)
    assert paper["open"] == 0
    assert paper["resolved"] == 1
    assert paper["wins"] == 1
    assert paper["pnl_usd"] > 0
