from __future__ import annotations

import asyncio
import itertools
from datetime import datetime, timezone

import pytest

import db
import polymarket_api
import trader
from conftest import US_FEE_JULY, quote_with_depth
from config import merge_with_defaults
from polymarket_api import PolymarketAPIError


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    dbfile = tmp_path / "rom-test.db"
    monkeypatch.setattr(db, "db_path", lambda: dbfile)
    db.init_db()
    return dbfile


@pytest.fixture
def env_net(monkeypatch):
    monkeypatch.setattr(trader, "get_env", lambda: "mainnet")
    return "mainnet"


@pytest.fixture
def cfg():
    c = merge_with_defaults({})
    c["network"] = "mainnet"
    return c


def run_async(coro):
    return asyncio.run(coro)


_ids = itertools.count(1)


def seed_position(**over) -> int:
    n = next(_ids)
    row = {
        "signal_source": over.get("signal_source", "whale"),
        "signal_id": over.get("signal_id", n),
        "ticker": over.get("ticker", f"TCK-{n}"),
        "event_ticker": over.get("event_ticker", ""),
        "direction": over.get("direction", "yes"),
        "target_contracts": over.get("target_contracts", 10),
        "limit_price_cents": over.get("limit_price_cents", 50),
        "filled_contracts": over.get("filled_contracts", 0),
        "cost_usd": over.get("cost_usd", 0.0),
        "client_order_id": over.get("client_order_id", f"co-{n}"),
        "order_id": over.get("order_id"),
        "status": over.get("status", "filled"),
        "network": over.get("network", "mainnet"),
    }
    with db.get_db() as conn:
        pid = db.insert_bot_position(conn, row)
        if "created_at_offset_sec" in over:
            conn.execute(
                "UPDATE bot_positions SET created_at=datetime('now', ?) WHERE id=?",
                (f"{int(over['created_at_offset_sec'])} seconds", pid),
            )
    return pid


def whale_signal(**over) -> dict:
    s = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "id": 1, "ticker": "WHALE-1", "event_ticker": "", "title": "t",
        "category": "sports", "price": 0.60, "confidence": 80.0,
        "taker_side": "yes",
    }
    s.update(over)
    return s


def count_rows() -> int:
    with db.get_db() as conn:
        return conn.execute("SELECT COUNT(*) FROM bot_positions").fetchone()[0]


@pytest.mark.parametrize('delay_kind', ['signal', 'quote'])
def test_expiry_during_metadata_wait_never_submits(fresh_db, env_net, cfg, monkeypatch, delay_kind):
    signal = whale_signal()
    cfg['enable_trading'] = True
    async def quote(*args):
        return quote_with_depth({'bid_cents':59, 'ask_cents':60})
    async def meta(*args):
        if delay_kind == 'signal':
            signal['created_at'] = '2000-01-01T00:00:00Z'
        else:
            monkeypatch.setattr(trader.time, 'monotonic', lambda: started + 6)
        return {'min_size':1}
    async def forbidden(**kwargs):
        pytest.fail('Expired execution must not submit')
    started = trader.time.monotonic()
    monkeypatch.setattr(trader, 'get_quote', quote)
    monkeypatch.setattr(trader, 'get_market_meta', meta)
    monkeypatch.setattr(trader, 'place_limit_order', forbidden)
    assert run_async(trader.execute_signal(signal, 'whale', cfg, 1000)) is None
    assert count_rows() == 0


def fetch(pid: int) -> dict:
    with db.get_db() as conn:
        return db.fetch_position_by_id(conn, pid)


async def _stub_no_quote(_ticker, _side=None):
    # Valid liquidity for tests focused on accounting/order persistence.
    return quote_with_depth({"bid_cents": 59, "ask_cents": 60})


@pytest.mark.parametrize('quote', [
    {'bid_cents': None, 'ask_cents': None},
    {'bid_cents': 50, 'ask_cents': 60},
    {'bid_cents': 62, 'ask_cents': 63},
])
def test_execution_quality_rejects_without_order_or_position(fresh_db, env_net, cfg, monkeypatch, quote):
    async def get_quote(*args):
        return quote
    async def forbidden(**kwargs):
        pytest.fail('Unsuitable liquidity must not reach order placement')
    monkeypatch.setattr(trader, 'get_quote', get_quote)
    monkeypatch.setattr(trader, 'place_limit_order', forbidden)
    cfg['enable_trading'] = True
    assert run_async(trader.execute_signal(whale_signal(), 'whale', cfg, 1000)) is None
    assert count_rows() == 0


def test_deteriorated_margin_rejects_before_sizing(fresh_db, env_net, cfg, monkeypatch):
    async def quote(*args):
        return quote_with_depth({'bid_cents': 60, 'ask_cents': 62})
    async def forbidden(**kwargs):
        pytest.fail('Exhausted signal margin must not reach order placement')
    monkeypatch.setattr(trader, 'get_quote', quote)
    monkeypatch.setattr(trader, 'place_limit_order', forbidden)
    cfg['enable_trading'] = True
    cfg['min_edge_pts_whale'] = 4
    # Original score margin is 6; movement (2) and uncertainty (1) leave 3.
    assert run_async(trader.execute_signal(whale_signal(confidence=66), 'whale', cfg, 1000)) is None
    assert count_rows() == 0


def test_execute_skips_when_max_open_positions_hit(fresh_db, env_net, cfg):
    cfg["max_open_positions"] = 1
    seed_position(status="filled")
    result = run_async(
        trader.execute_signal(whale_signal(id=100, ticker="NEW"), "whale", cfg, 1000.0)
    )
    assert result is None
    assert count_rows() == 1


def test_execute_skips_when_daily_cap_hit(fresh_db, env_net, cfg):
    cfg["max_open_positions"] = 100
    cfg["unlimited_daily_new_positions"] = False
    cfg["max_daily_new_positions"] = 2
    seed_position(status="filled")
    seed_position(status="filled")
    result = run_async(
        trader.execute_signal(whale_signal(id=101, ticker="NEW"), "whale", cfg, 1000.0)
    )
    assert result is None
    assert count_rows() == 2


def test_execute_skips_second_position_in_same_event(fresh_db, env_net, cfg):
    cfg["max_positions_per_event"] = 1
    seed_position(status="filled", event_ticker="EVT-A", ticker="A-1")
    result = run_async(
        trader.execute_signal(
            whale_signal(id=102, ticker="A-2", event_ticker="EVT-A"),
            "whale", cfg, 1000.0,
        )
    )
    assert result is None


def test_per_event_cap_enforced_for_n_greater_than_one(fresh_db, env_net, cfg, monkeypatch):
    cfg["max_positions_per_event"] = 2
    monkeypatch.setattr(trader, "get_quote", _stub_no_quote)

    async def _place(**_kw):
        return {"order": {"order_id": "o", "status": "live"}}
    monkeypatch.setattr(trader, "place_limit_order", _place)
    cfg["enable_trading"] = True

    seed_position(status="filled", event_ticker="EVT-B", ticker="B-1")
    seed_position(status="filled", event_ticker="EVT-B", ticker="B-2")
    result = run_async(
        trader.execute_signal(
            whale_signal(id=110, ticker="B-3", event_ticker="EVT-B"),
            "whale", cfg, 1000.0,
        )
    )
    assert result is None


def test_execute_skips_duplicate_market_and_side(fresh_db, env_net, cfg):
    seed_position(status="filled", ticker="DUP", direction="yes")
    result = run_async(
        trader.execute_signal(
            whale_signal(id=103, ticker="DUP", taker_side="yes"), "whale", cfg, 1000.0
        )
    )
    assert result is None


def test_execute_skips_when_exposure_leaves_under_one_dollar(fresh_db, env_net, cfg):
    seed_position(status="filled", ticker="EXP-SEED", cost_usd=749.50)
    result = run_async(
        trader.execute_signal(
            whale_signal(id=104, ticker="EXP-NEW"), "whale", cfg, 1000.0
        )
    )
    assert result is None
    assert count_rows() == 1


def test_resting_orders_do_not_inflate_exposure_cap(fresh_db, env_net, cfg, monkeypatch):
    cfg["enable_trading"] = True
    cfg["max_total_exposure_fraction"] = 0.75
    cfg["max_open_positions"] = 50
    cfg["unlimited_daily_new_positions"] = True
    monkeypatch.setattr(trader, "get_quote", _stub_no_quote)

    placed: list[dict] = []

    async def _place(**kw):
        placed.append(kw)
        return {"order": {"order_id": f"OID-{len(placed)}", "status": "resting"}}
    monkeypatch.setattr(trader, "place_limit_order", _place)

    seed_position(status="submitted", ticker="REST", event_ticker="EVT-REST",
                  target_contracts=140, limit_price_cents=50, cost_usd=0.0,
                  order_id="OID-SEED")

    row = run_async(trader.execute_signal(
        whale_signal(id=300, ticker="NEW", event_ticker="EVT-NEW"),
        "whale", cfg, 100.0,
    ))
    assert row is not None and row["status"] == "submitted"
    new_notional = row["target_contracts"] * row["limit_price_cents"] / 100.0
    assert new_notional <= 6.0, f"new order ${new_notional:.2f} blew past the headroom"
    with db.get_db() as conn:
        total_exposure = db.current_total_exposure_usd(conn, "mainnet")
    assert total_exposure <= 76.0, f"exposure ${total_exposure:.2f} exceeded 0.75*cash"


def test_flatten_on_daily_stop_sells_when_enabled(fresh_db, env_net, cfg, monkeypatch):
    cfg["flatten_on_daily_stop"] = True
    cfg["enable_trading"] = True
    cfg["stop_loss_on_day"] = -10.0
    seed_position(status="filled", cost_usd=5.0, filled_contracts=10)
    called = {"n": 0}

    async def _fake_flatten(_cfg):
        called["n"] += 1
        return {"canceled": 0, "sold": 10, "proceedsUsd": 0.0}
    monkeypatch.setattr(trader, "flatten_open_positions", _fake_flatten)
    monkeypatch.setattr(trader, "_today_pnl_balance_delta", lambda env, offset_min=0: -20.0)
    monkeypatch.setattr(trader, "_DAY_RISK_PERSIST_SEC", 0.0)
    trader._day_risk_breach.clear()

    run_async(trader._maybe_flatten_on_daily_stop(cfg, "mainnet"))
    assert called["n"] == 1
    trader._day_risk_breach.clear()


def _install_sell_stubs(monkeypatch, *, bid_cents):
    async def _quote(_ticker, _side=None):
        return quote_with_depth({"bid_cents": bid_cents, "ask_cents": (bid_cents or 0) + 1})

    async def _place(**_kw):
        return {"order": {"order_id": "OID-TP", "status": "matched"}}

    async def _confirm(_oid, qty, px):
        return qty, float(px)

    async def _cancel(_oid):
        return True
    monkeypatch.setattr(trader, "get_quote", _quote)
    monkeypatch.setattr(trader, "place_limit_order", _place)
    monkeypatch.setattr(trader, "_confirm_sell", _confirm)
    monkeypatch.setattr(trader, "cancel_order", _cancel)


def test_take_profit_sweep_sells_winner_and_books_reason(fresh_db, env_net, cfg, monkeypatch):
    cfg["take_profit_pct"] = 0.20
    # Price the exit at the touch so this test measures the sweep, not the
    # concession budget (covered in test_exit_discipline).
    cfg["exit_price_loss_budget_cents"] = 0
    pid = seed_position(status="filled", cost_usd=5.0, filled_contracts=10, direction="yes")
    _install_sell_stubs(monkeypatch, bid_cents=80)

    closed = run_async(trader.take_profit_sweep(cfg))
    assert len(closed) == 1
    row = fetch(pid)
    assert row["resolved"] == 1 and row["closed_early"] == 1
    assert row["exit_reason"] == "take_profit"
    assert row["settlement_usd"] == pytest.approx(8.0)
    assert row["pnl_usd"] == pytest.approx(3.0)


def test_take_profit_sweep_holds_position_below_target(fresh_db, env_net, cfg, monkeypatch):
    cfg["take_profit_pct"] = 0.20
    pid = seed_position(status="filled", cost_usd=9.0, filled_contracts=10, direction="yes")
    _install_sell_stubs(monkeypatch, bid_cents=91)

    closed = run_async(trader.take_profit_sweep(cfg))
    assert closed == []
    row = fetch(pid)
    assert row["resolved"] == 0 and row["closed_early"] == 0
    assert row["exit_reason"] is None


def test_take_profit_sweep_is_noop_when_disabled(fresh_db, env_net, cfg, monkeypatch):
    cfg["take_profit_pct"] = 0.0
    seed_position(status="filled", cost_usd=5.0, filled_contracts=10)
    _install_sell_stubs(monkeypatch, bid_cents=99)
    assert run_async(trader.take_profit_sweep(cfg)) == []


def test_recent_balance_transition_flags_fresh_fills_and_settlements(fresh_db, env_net):
    with db.get_db() as conn:
        assert db.recent_balance_transition(conn, "mainnet") is False
    seed_position(status="filled", cost_usd=3.0, filled_contracts=5)
    with db.get_db() as conn:
        assert db.recent_balance_transition(conn, "mainnet") is True
        conn.execute("UPDATE bot_positions SET created_at = datetime('now', '-10 minutes')")
        assert db.recent_balance_transition(conn, "mainnet") is False
        conn.execute("UPDATE bot_positions SET resolved_at = datetime('now')")
        assert db.recent_balance_transition(conn, "mainnet") is True
        conn.execute("UPDATE bot_positions SET resolved_at = datetime('now', '-10 minutes')")
        assert db.recent_balance_transition(conn, "mainnet") is False


def test_daily_stop_ignores_transient_settlement_gap(fresh_db, env_net, cfg, monkeypatch):
    monkeypatch.setattr(trader, "_DAY_RISK_PERSIST_SEC", 180.0)
    trader._day_risk_breach.clear()
    monkeypatch.setattr(trader, "_today_pnl_balance_delta", lambda env, offset_min=0: -20.0)
    risk_cfg = {"stop_loss_on_day": -10.0, "take_profit_on_day": 0}
    assert trader._is_blocked_by_daily_risk(risk_cfg, "mainnet")[0] is False
    trader._day_risk_breach[("mainnet", "sl")] = trader.time.monotonic() - 181.0
    blocked, why = trader._is_blocked_by_daily_risk(risk_cfg, "mainnet")
    assert blocked is True and "stop-loss" in why
    monkeypatch.setattr(trader, "_today_pnl_balance_delta", lambda env, offset_min=0: +0.3)
    assert trader._is_blocked_by_daily_risk(risk_cfg, "mainnet")[0] is False
    assert trader._day_risk_breach[("mainnet", "sl")] is None
    trader._day_risk_breach.clear()


def test_flatten_on_daily_stop_noop_when_toggle_off(fresh_db, env_net, cfg, monkeypatch):
    cfg["flatten_on_daily_stop"] = False
    cfg["enable_trading"] = True
    cfg["stop_loss_on_day"] = -10.0
    seed_position(status="filled", cost_usd=5.0, filled_contracts=10)
    called = {"n": 0}

    async def _fake_flatten(_cfg):
        called["n"] += 1
        return {}
    monkeypatch.setattr(trader, "flatten_open_positions", _fake_flatten)
    monkeypatch.setattr(trader, "_today_pnl_balance_delta", lambda env, offset_min=0: -20.0)

    run_async(trader._maybe_flatten_on_daily_stop(cfg, "mainnet"))
    assert called["n"] == 0


def test_flatten_not_triggered_by_take_profit(fresh_db, env_net, cfg, monkeypatch):
    cfg["flatten_on_daily_stop"] = True
    cfg["enable_trading"] = True
    cfg["stop_loss_on_day"] = -1000.0
    seed_position(status="filled", cost_usd=5.0, filled_contracts=10)
    called = {"n": 0}

    async def _fake_flatten(_cfg):
        called["n"] += 1
        return {}
    monkeypatch.setattr(trader, "flatten_open_positions", _fake_flatten)
    monkeypatch.setattr(trader, "_today_pnl_balance_delta", lambda env, offset_min=0: +50.0)

    run_async(trader._maybe_flatten_on_daily_stop(cfg, "mainnet"))
    assert called["n"] == 0


def test_execute_real_order_records_order_id(
    fresh_db, env_net, cfg, monkeypatch, fee_clock
):
    at = fee_clock(US_FEE_JULY)
    cfg["enable_trading"] = True
    monkeypatch.setattr(trader, "get_quote", _stub_no_quote)

    calls: list[dict] = []

    async def _place(**kw):
        calls.append(kw)
        return {"order": {"order_id": "OID-1", "status": "resting"}}

    monkeypatch.setattr(trader, "place_limit_order", _place)

    row = run_async(
        trader.execute_signal(
            whale_signal(id=201, ticker="LIVE", created_at=at.isoformat()),
            "whale", cfg, 1000.0)
    )
    assert row["status"] == "submitted"
    assert row["order_id"] == "OID-1"
    assert len(calls) == 1
    # $50 cap at the live 60c ask. Each contract reserves 62c - the 60c ask
    # plus the US taker fee rounded up to a whole cent - so 80 fit, not 83.
    assert calls[0]["count"] == 80
    assert calls[0]["price_cents"] == 60
    assert calls[0]["side"] == "yes"
    assert calls[0]["action"] == "buy"


def test_execute_api_error_is_persisted_as_error_row(fresh_db, env_net, cfg, monkeypatch):
    cfg["dry_run"] = False
    cfg["enable_trading"] = True
    monkeypatch.setattr(trader, "get_quote", _stub_no_quote)

    async def _place(**_kw):
        raise PolymarketAPIError(400, {"error": "insufficient_balance"})

    monkeypatch.setattr(trader, "place_limit_order", _place)

    row = run_async(
        trader.execute_signal(whale_signal(id=202, ticker="BAD"), "whale", cfg, 1000.0)
    )
    assert row["status"] == "error"
    assert "HTTP 400" in row["error"]
    assert row["order_id"] is None


def test_execute_does_not_inflate_strategy_size_for_market_minimum(fresh_db, env_net, cfg, monkeypatch):
    cfg["dry_run"] = False
    cfg["enable_trading"] = True
    monkeypatch.setattr(trader, "get_quote", _stub_no_quote)

    async def _meta(_ticker):
        return {"min_size": 5}
    monkeypatch.setattr(trader, "get_market_meta", _meta)

    calls: list[dict] = []

    async def _place(**kw):
        calls.append(kw)
        return {"order": {"order_id": "OID-9", "status": "resting"}}
    monkeypatch.setattr(trader, "place_limit_order", _place)

    row = run_async(
        trader.execute_signal(whale_signal(id=210, ticker="SMALL"), "whale", cfg, 50.0)
    )
    assert calls == []
    assert row is None
    assert count_rows() == 0


def test_execute_skips_when_market_minimum_exceeds_budget(fresh_db, env_net, cfg, monkeypatch):
    cfg["dry_run"] = False
    cfg["enable_trading"] = True
    monkeypatch.setattr(trader, "get_quote", _stub_no_quote)

    async def _meta(_ticker):
        return {"min_size": 100}
    monkeypatch.setattr(trader, "get_market_meta", _meta)

    def _boom(**_kw):
        raise AssertionError("must not place a sub-min order over budget")
    monkeypatch.setattr(trader, "place_limit_order", _boom)

    row = run_async(
        trader.execute_signal(whale_signal(id=211, ticker="PRICEY"), "whale", cfg, 50.0)
    )
    assert row is None
    assert count_rows() == 0


def test_execute_skips_when_live_cross_exceeds_entry_cap(fresh_db, env_net, cfg, monkeypatch):
    cfg["dry_run"] = False
    cfg["enable_trading"] = True

    async def _moved_quote(_ticker, _side=None):
        return quote_with_depth({"bid_cents": 90, "ask_cents": 95})

    monkeypatch.setattr(trader, "get_quote", _moved_quote)

    def _boom(**_kw):
        raise AssertionError("place_limit_order must not be called above the cap")

    monkeypatch.setattr(trader, "place_limit_order", _boom)

    row = run_async(
        trader.execute_signal(whale_signal(id=203, ticker="MOVED"), "whale", cfg, 1000.0)
    )
    assert row is None
    assert count_rows() == 0


def test_poll_marks_order_filled_from_order_endpoint(fresh_db, env_net, cfg, monkeypatch):
    trader._poll_failures.clear()
    pid = seed_position(status="submitted", order_id="OID-9",
                        target_contracts=5, cost_usd=0.0)

    async def _no_positions(*_a, **_k):
        return []

    async def _get_order(_oid):
        return {"order": {
            "status": "MATCHED", "size_matched": "5", "original_size": "5",
            "price": "0.60",
        }}

    monkeypatch.setattr(trader, "get_positions", _no_positions)
    monkeypatch.setattr(trader, "get_order", _get_order)

    updated = run_async(trader.poll_open_orders(cfg))
    assert len(updated) == 1
    row = fetch(pid)
    assert row["status"] == "filled"
    assert row["filled_contracts"] == 5
    assert row["cost_usd"] == pytest.approx(3.0)
    assert row["avg_fill_price_cents"] == pytest.approx(60.0)


def test_poll_retains_unknown_order_after_repeated_404(fresh_db, env_net, cfg, monkeypatch):
    trader._poll_failures.clear()
    pid = seed_position(status="submitted", order_id="OID-10",
                        target_contracts=5)

    async def _no_positions(*_a, **_k):
        return []

    async def _get_order_404(_oid):
        raise PolymarketAPIError(404, "not found")

    monkeypatch.setattr(trader, "get_positions", _no_positions)
    monkeypatch.setattr(trader, "get_order", _get_order_404)

    run_async(trader.poll_open_orders(cfg))
    assert fetch(pid)["status"] == "submitted"

    for _ in range(5):
        run_async(trader.poll_open_orders(cfg))
    assert fetch(pid)["status"] == "unknown"
    with db.get_db() as conn:
        assert db.current_total_exposure_usd(conn, 'mainnet') > 0


def test_poll_cancel_ack_without_confirmation_retains_stale_order(fresh_db, env_net, cfg, monkeypatch):
    trader._poll_failures.clear()
    cfg["order_expiration_sec"] = 90
    pid = seed_position(status="submitted", order_id="OID-11",
                        target_contracts=5, created_at_offset_sec=-200)

    async def _no_positions(*_a, **_k):
        return []

    async def _resting(_oid):
        return {"order": {
            "status": "LIVE", "size_matched": "0", "original_size": "5",
            "price": "0.50",
        }}

    cancels: list[str] = []

    async def _cancel(oid):
        cancels.append(oid)
        return {}

    monkeypatch.setattr(trader, "get_positions", _no_positions)
    monkeypatch.setattr(trader, "get_order", _resting)
    monkeypatch.setattr(trader, "cancel_order", _cancel)

    run_async(trader.poll_open_orders(cfg))
    assert cancels == ["OID-11"]
    assert fetch(pid)["status"] == "submitted"


def _settled_market(result: str):
    async def _fetch(_ticker):
        return {"result": result, "status": "finalized"}
    return _fetch


def test_resolve_winning_yes_position(fresh_db, env_net, cfg, monkeypatch):
    pid = seed_position(status="filled", ticker="RES-WIN", direction="yes",
                        filled_contracts=10, cost_usd=6.0)
    monkeypatch.setattr(polymarket_api, "fetch_market", _settled_market("yes"))

    updated = run_async(trader.mark_resolved_positions(cfg))
    assert len(updated) == 1
    row = fetch(pid)
    assert bool(row["resolved"]) is True
    assert row["outcome_correct"] == 1
    assert row["settlement_usd"] == pytest.approx(10.0)
    assert row["pnl_usd"] == pytest.approx(4.0)


def test_resolve_losing_no_position(fresh_db, env_net, cfg, monkeypatch):
    pid = seed_position(status="filled", ticker="RES-LOSS", direction="no",
                        filled_contracts=10, cost_usd=4.0)
    monkeypatch.setattr(polymarket_api, "fetch_market", _settled_market("yes"))

    run_async(trader.mark_resolved_positions(cfg))
    row = fetch(pid)
    assert row["outcome_correct"] == 0
    assert row["settlement_usd"] == pytest.approx(0.0)
    assert row["pnl_usd"] == pytest.approx(-4.0)


def test_resolve_no_fill_row_closes_at_zero_with_null_outcome(fresh_db, env_net, cfg):
    pid = seed_position(status="canceled", ticker="RES-NOFILL",
                        filled_contracts=0, cost_usd=0.0)
    run_async(trader.mark_resolved_positions(cfg))
    row = fetch(pid)
    assert bool(row["resolved"]) is True
    assert row["outcome_correct"] is None
    assert row["pnl_usd"] == pytest.approx(0.0)


def test_resolve_clamps_pnl_to_physical_bounds(fresh_db, env_net, cfg, monkeypatch):
    pid = seed_position(status="filled", ticker="CLAMP", direction="yes",
                        filled_contracts=10, cost_usd=6.0)
    monkeypatch.setattr(polymarket_api, "fetch_market", _settled_market("yes"))
    monkeypatch.setattr(trader, "_market_yes_payout", lambda _m: 5.0)

    run_async(trader.mark_resolved_positions(cfg))
    row = fetch(pid)
    assert row["pnl_usd"] == pytest.approx(4.0)
    assert row["settlement_usd"] == pytest.approx(10.0)


def _live_pos(ticker: str, qty: float = 10.0, cost_cents: int = 600,
              cur_price: float = 0.0) -> dict:
    return {"ticker": ticker, "position": qty, "market_exposure": cost_cents,
            "title": ticker, "event_ticker": "", "category": "",
            "cur_price": cur_price}


def _open_market():
    async def _fetch(_ticker):
        return {"result": "", "status": "open", "settlement_value_dollars": None}
    return _fetch


def test_reconcile_skips_importing_settled_residual(fresh_db, env_net, monkeypatch):
    async def _live(limit=1000):
        return [_live_pos("SETTLED-1")]
    monkeypatch.setattr(trader, "get_positions", _live)
    monkeypatch.setattr(trader, "fetch_market", _settled_market("no"))

    summary, changed = run_async(trader.reconcile_positions_with_polymarket())

    assert summary["imported_unknowns"] == 0
    assert changed == []
    with db.get_db() as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM bot_positions WHERE ticker='SETTLED-1'"
        ).fetchone()[0]
    assert n == 0


def test_resolved_guard_blocks_reimport_after_24h(fresh_db, env_net):
    seed_position(signal_source="external", ticker="OLD-15M", direction="yes",
                  status="filled", network=env_net)
    with db.get_db() as conn:
        conn.execute(
            "UPDATE bot_positions SET resolved=1, pnl_usd=-22.2, "
            "resolved_at=datetime('now','-3 days') WHERE ticker='OLD-15M'"
        )
        conn.commit()
        assert db.recent_resolved_position_exists(
            conn, "OLD-15M", "yes", env_net, within_hours=24) is False
        assert db.recent_resolved_position_exists(
            conn, "OLD-15M", "yes", env_net) is True


def test_reconcile_imports_open_external_position(fresh_db, env_net, monkeypatch):
    async def _live(limit=1000):
        return [_live_pos("OPEN-1", qty=10, cost_cents=600, cur_price=0.80)]
    monkeypatch.setattr(trader, "get_positions", _live)
    monkeypatch.setattr(trader, "fetch_market", _open_market())

    summary, changed = run_async(trader.reconcile_positions_with_polymarket())

    assert summary["imported_unknowns"] == 1
    with db.get_db() as conn:
        row = conn.execute(
            "SELECT signal_source, status, resolved, mark_price_cents "
            "FROM bot_positions WHERE ticker='OPEN-1'"
        ).fetchone()
    assert row is not None
    assert row["signal_source"] == "external"
    assert row["status"] == "filled"
    assert int(row["resolved"]) == 0
    assert row["mark_price_cents"] == 80.0


def test_reconcile_skips_crypto15m_owned_position(fresh_db, env_net, monkeypatch):
    with db.get_db() as conn:
        db.insert_crypto15m_position(conn, {
            "asset": "BTC", "series": "KXBTC15M", "ticker": "C15-OWNED",
            "side": "up", "direction": "yes", "target_contracts": 10,
            "filled_contracts": 10, "entry_limit_cents": 80, "cost_usd": 8.0,
            "client_order_id": "c15-1", "status": "filled", "network": "mainnet",
        })

    async def _live(limit=1000):
        return [_live_pos("C15-OWNED", qty=10, cur_price=0.85)]
    monkeypatch.setattr(trader, "get_positions", _live)
    monkeypatch.setattr(trader, "fetch_market", _open_market())

    summary, changed = run_async(trader.reconcile_positions_with_polymarket())

    assert summary["imported_unknowns"] == 0
    with db.get_db() as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM bot_positions WHERE ticker='C15-OWNED'"
        ).fetchone()[0]
    assert n == 0


def test_refresh_balance_caches_and_force_refreshes(monkeypatch):
    trader._balance_cache.clear()
    seq = iter([
        {"balance": 1000, "portfolio_value": 100},
        {"balance": 1200, "portfolio_value": 150},
    ])

    async def fake_balance():
        return next(seq)

    monkeypatch.setattr(trader, "get_balance", fake_balance)
    monkeypatch.setattr(trader, "get_env", lambda: "mainnet")
    cfg = {"balance_poll_interval": 60}

    assert run_async(trader.refresh_balance(cfg, force=True)) == (1000, 100)
    assert run_async(trader.refresh_balance(cfg, force=False)) == (1000, 100)
    assert run_async(trader.refresh_balance(cfg, force=True)) == (1200, 150)


def test_refresh_balance_keeps_last_portfolio_when_value_read_fails(monkeypatch):
    trader._balance_cache.clear()
    seq = iter([
        {"balance": 5597, "portfolio_value": 454},
        {"balance": 5135, "portfolio_value": None},
    ])

    async def fake_balance():
        return next(seq)

    monkeypatch.setattr(trader, "get_balance", fake_balance)
    monkeypatch.setattr(trader, "get_env", lambda: "mainnet")
    cfg = {"balance_poll_interval": 0}

    assert run_async(trader.refresh_balance(cfg, force=True)) == (5597, 454)
    assert run_async(trader.refresh_balance(cfg, force=True)) == (5135, 454)


def test_exposure_counts_committed_notional_of_submitted_orders(fresh_db, env_net):
    seed_position(status="submitted", cost_usd=0.0, target_contracts=10, limit_price_cents=50)
    seed_position(status="filled", cost_usd=4.0, target_contracts=10, limit_price_cents=60)
    with db.get_db() as conn:
        exp = db.current_total_exposure_usd(conn, "mainnet")
    assert exp == pytest.approx(9.0)


def test_flatten_sells_open_positions_and_books_pnl(fresh_db, env_net, cfg, monkeypatch):
    pid = seed_position(status="filled", direction="yes", filled_contracts=10,
                        cost_usd=5.0, limit_price_cents=50, order_id="o-buy")

    async def _quote(_ticker, _side):
        return quote_with_depth({"bid_cents": 70, "ask_cents": 72})

    async def _place(**kw):
        assert kw["action"] == "sell" and kw["count"] == 10
        return {"order": {"order_id": "sell-1", "status": "live"}}

    async def _get_order(_oid):
        return {"order": {"size_matched": "10", "original_size": "10",
                          "price": "0.70", "status": "MATCHED"}}

    monkeypatch.setattr(trader, "get_quote", _quote)
    monkeypatch.setattr(trader, "place_limit_order", _place)
    monkeypatch.setattr(trader, "get_order", _get_order)

    res = run_async(trader.flatten_open_positions(cfg))

    assert res["sold"] == 10
    with db.get_db() as conn:
        r = dict(conn.execute("SELECT * FROM bot_positions WHERE id=?", (pid,)).fetchone())
    assert r["resolved"] == 1 and r["closed_early"] == 1
    assert r["pnl_usd"] == pytest.approx(2.0)
    assert r["settlement_usd"] == pytest.approx(7.0)


def test_cancel_all_resting_cancels_tracked_orders(fresh_db, env_net, cfg, monkeypatch):
    resting = seed_position(status="submitted", order_id="OID-A", target_contracts=5)
    partial = seed_position(status="partial", order_id="OID-B",
                            target_contracts=8, filled_contracts=3)
    filled = seed_position(status="filled", order_id="OID-C", filled_contracts=10)
    no_oid = seed_position(status="submitted", order_id=None, target_contracts=4)
    resolved = seed_position(status="submitted", order_id="OID-D", target_contracts=6)
    with db.get_db() as conn:
        conn.execute("UPDATE bot_positions SET resolved=1 WHERE id=?", (resolved,))

    cancels: list[str] = []

    async def _cancel(oid):
        cancels.append(oid)
        return {}

    monkeypatch.setattr(trader, "cancel_order", _cancel)

    n = run_async(trader.cancel_all_resting_orders("shutdown"))

    assert n == 2
    assert sorted(cancels) == ["OID-A", "OID-B"]
    assert fetch(resting)["status"] == "canceled"
    assert fetch(partial)["status"] == "canceled"
    assert fetch(resting)["error"] == "shutdown"
    assert fetch(filled)["status"] == "filled"
    assert fetch(no_oid)["status"] == "submitted"
    assert fetch(resolved)["status"] == "submitted"


def test_cancel_all_resting_survives_api_error_without_losing_fill(
    fresh_db, env_net, cfg, monkeypatch,
):
    a = seed_position(status="submitted", order_id="OID-A", target_contracts=5)
    b = seed_position(status="submitted", order_id="OID-B", target_contracts=5)

    async def _cancel(oid):
        if oid == "OID-A":
            raise PolymarketAPIError(404, "not found")
        return {}

    monkeypatch.setattr(trader, "cancel_order", _cancel)

    n = run_async(trader.cancel_all_resting_orders("shutdown"))

    assert n == 1
    assert fetch(a)["status"] == "submitted"
    assert fetch(b)["status"] == "canceled"
