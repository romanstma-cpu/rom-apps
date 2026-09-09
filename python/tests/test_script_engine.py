from __future__ import annotations

import asyncio
import json
import time

import pytest

import crypto15m_trader
import db
import polymarket_api
import script_engine
from script_backtest import (
    market_to_js, sanitize_intent, sanitize_manage, sanitize_market_intent,
    sanitize_signal_action,
)

ENV = "mainnet"


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    dbfile = tmp_path / "scripts-test.db"
    monkeypatch.setattr(db, "db_path", lambda: dbfile)
    db.init_db()
    return dbfile


@pytest.fixture(autouse=True)
def _clean_engine_globals(monkeypatch):
    monkeypatch.setattr(script_engine, "_compiled", {}, raising=False)
    monkeypatch.setattr(script_engine, "_notified_fill", set(), raising=False)
    monkeypatch.setattr(script_engine, "_notified_settle", set(), raising=False)
    monkeypatch.setattr(script_engine, "_last_patch_t", {}, raising=False)
    monkeypatch.setattr(script_engine, "_market_cooldown", {}, raising=False)
    monkeypatch.setattr(script_engine, "_last_state_save", 0.0, raising=False)
    monkeypatch.setattr(
        script_engine, "_sig_marks", {"whale": None, "momentum": None},
        raising=False)
    monkeypatch.setattr(script_engine, "_hb", {}, raising=False)
    monkeypatch.setattr(script_engine, "_hb_last", {}, raising=False)
    monkeypatch.setattr(script_engine, "_market_cooldown", {}, raising=False)


@pytest.fixture
def placed(monkeypatch):
    calls: list[dict] = []

    async def _place(**kw):
        calls.append(kw)
        return {"order": {"order_id": f"oid-{len(calls)}", "status": "matched"}}

    monkeypatch.setattr(polymarket_api, "place_limit_order", _place)
    return calls


def _cfg(**over) -> dict:
    cfg = {
        "script_max_entry_cents": 97,
        "script_max_contracts": 20,
        "script_max_open": 2,
        "script_daily_loss_usd": 25.0,
        "script_max_enabled": 10,
        "crypto15m_order_size": 1,
        "fixed_trade_usd": 5.0,
    }
    cfg.update(over)
    return cfg


def _asset(**over) -> dict:
    a = {
        "asset": "BTC", "series": "BTC-updown", "ticker": "0xtick",
        "closeTime": "2026-07-24T12:15:00Z", "favoritePrice": 0.8,
        "upAsk": 0.60, "downAsk": 0.42, "yesBid": 0.58, "yesAsk": 0.61,
        "minsLeft": 4.0, "hasMarket": True,
    }
    a.update(over)
    return a


def _script(sid="s1abc", **over) -> dict:
    s = {"id": sid, "name": "T", "code": "def decide(ctx):\n    return None\n"}
    s.update(over)
    return s


@pytest.fixture
def emitted(monkeypatch):
    events: list[tuple[str, dict]] = []

    async def _emit(name, data):
        events.append((name, data))

    monkeypatch.setattr(script_engine, "_emit", _emit, raising=False)
    return events


def _mod(code: str = "def decide(ctx):\n    return None\n"):
    import script_sandbox
    return script_sandbox.CompiledScript("s1abc", code, state={})


def test_heartbeat_lists_only_the_hooks_the_script_defines():
    line = script_engine._heartbeat_line(
        {"ticks": 12, "decide": 84, "decide_intents": 0, "decide_market_hooked": 0},
        shadow=True, open_count=0, day_pnl=0.0)
    assert "decide ×84 → 0 intents" in line
    assert "decide_market" not in line
    assert "12 ticks" in line


def test_heartbeat_reports_orders_refusals_and_errors():
    line = script_engine._heartbeat_line(
        {"ticks": 3, "decide_market": 450, "decide_market_intents": 2,
         "placed": 1, "refused": 1, "errors": 2},
        shadow=False, open_count=1, day_pnl=-3.5)
    assert "decide_market ×450 → 2 intents" in line
    assert "1 order, 1 declined" in line
    assert "2 ERRORS" in line
    assert "1 open, today -3.50 USD" in line


def test_heartbeat_says_one_intent_not_one_intents():
    line = script_engine._heartbeat_line(
        {"ticks": 1, "decide": 1, "decide_intents": 1, "placed": 1,
         "errors": 1},
        shadow=False, open_count=0, day_pnl=0.0)
    assert "1 tick ·" in line and "1 ticks" not in line
    assert "→ 1 intent ·" in line
    assert "1 order ·" in line
    assert "1 ERROR ·" in line


def test_heartbeat_says_shadow_orders_when_the_script_is_in_shadow():
    line = script_engine._heartbeat_line(
        {"ticks": 1, "placed": 2}, shadow=True, open_count=2, day_pnl=0.0)
    assert "2 shadow orders" in line


def test_heartbeat_fires_on_the_first_tick_so_the_panel_is_never_empty(emitted):
    script_engine._hb_note("s1abc", "ticks")
    script_engine._hb_note("s1abc", "decide", 7)
    asyncio.run(script_engine._maybe_heartbeat(
        _script(), _mod(), shadow=True, open_count=0, day_pnl=0.0))
    assert [n for n, _ in emitted] == ["script:log"]
    assert emitted[0][1]["id"] == "s1abc"
    assert "decide ×7" in emitted[0][1]["lines"][0]


def test_heartbeat_rate_limits_to_one_line_per_interval(emitted):
    mod, s = _mod(), _script()
    asyncio.run(script_engine._maybe_heartbeat(
        s, mod, shadow=True, open_count=0, day_pnl=0.0))
    script_engine._hb_note("s1abc", "ticks", 5)
    asyncio.run(script_engine._maybe_heartbeat(
        s, mod, shadow=True, open_count=0, day_pnl=0.0))
    assert len(emitted) == 1
    assert script_engine._hb["s1abc"]["ticks"] == 5


def test_heartbeat_resets_its_counters_after_emitting(emitted):
    script_engine._hb_note("s1abc", "decide", 9)
    asyncio.run(script_engine._maybe_heartbeat(
        _script(), _mod(), shadow=True, open_count=0, day_pnl=0.0))
    assert script_engine._hb.get("s1abc") in (None, {})


def test_heartbeat_never_breaks_a_trading_pass(monkeypatch, emitted):
    async def _boom(name, data):
        raise RuntimeError("event bus down")

    monkeypatch.setattr(script_engine, "_emit", _boom, raising=False)
    asyncio.run(script_engine._maybe_heartbeat(
        _script(), _mod(), shadow=True, open_count=0, day_pnl=0.0))


def test_a_rails_refused_market_is_not_reoffered_immediately(fresh_db, placed,
                                                             monkeypatch):
    quotes: list[str] = []

    async def _quote(ticker, side):
        quotes.append(ticker)
        return {"ask_cents": 99, "bid_cents": 98}

    monkeypatch.setattr(polymarket_api, "get_quote", _quote)
    s, m = _script(dry_run=0), _market()
    intent = {"side": "yes", "price": "ask", "sizeUsd": 10.0}

    out = asyncio.run(script_engine._place_market_intent(
        s, m, intent, _cfg(script_max_entry_cents=97), ENV))
    assert out is None and placed == []
    assert script_engine._in_cooldown("s1abc", m["ticker"]) is True
    assert len(quotes) == 1


def test_the_cooldown_expires_so_a_moved_price_is_reconsidered(monkeypatch):
    script_engine._cool_off("s1abc", "0xmkt", "too expensive")
    assert script_engine._in_cooldown("s1abc", "0xmkt") is True
    script_engine._market_cooldown[("s1abc", "0xmkt")] = time.time() - 1
    assert script_engine._in_cooldown("s1abc", "0xmkt") is False
    assert ("s1abc", "0xmkt") not in script_engine._market_cooldown


def test_the_cooldown_is_per_script(monkeypatch):
    script_engine._cool_off("s1abc", "0xmkt", "too expensive")
    assert script_engine._in_cooldown("other", "0xmkt") is False


def test_forget_drops_the_cooldown_entries_for_that_script():
    script_engine._cool_off("s1abc", "0xa", "r")
    script_engine._cool_off("s1abc", "0xb", "r")
    script_engine._cool_off("keep", "0xc", "r")
    script_engine.forget("s1abc")
    assert list(script_engine._market_cooldown) == [("keep", "0xc")]


def test_forget_drops_heartbeat_state():
    script_engine._hb_note("s1abc", "ticks")
    script_engine._hb_last["s1abc"] = 1.0
    script_engine.forget("s1abc")
    assert "s1abc" not in script_engine._hb
    assert "s1abc" not in script_engine._hb_last


@pytest.mark.parametrize("raw,expect", [
    (None, None),
    ({"side": "up", "price": "ask"}, {"side": "up", "price": "ask"}),
    ({"side": "DOWN", "price": 42}, {"side": "down", "price": 42}),
])
def test_sanitize_intent_accepts_the_contract(raw, expect):
    out, err = sanitize_intent(raw)
    assert err is None
    assert out == expect


@pytest.mark.parametrize("raw", [
    "buy",
    {"price": "ask"},
    {"side": "sideways", "price": "ask"},
    {"side": "up", "price": 0},
    {"side": "up", "price": 100},
    {"side": "up", "price": "mid"},
    {"side": "up", "price": "ask", "size": 0},
    {"side": "up", "price": "ask", "size": "big"},
    {"side": "up", "price": "ask", "take_profit_pct": 0},
    {"side": "up", "price": "ask", "take_profit_pct": 99},
    {"side": "up", "price": "ask", "stop_loss_cents": 0},
    {"side": "up", "price": "ask", "stop_loss_cents": 100},
])
def test_sanitize_intent_rejects_malformed_intents(raw):
    out, err = sanitize_intent(raw)
    assert out is None and err


@pytest.mark.parametrize("field", ["take_profit_pct", "stop_loss_cents"])
def test_sanitize_intent_rejects_nan(field):
    out, err = sanitize_intent({"side": "up", "price": "ask", field: float("nan")})
    assert out is None and err


def test_sanitize_intent_truncates_the_reason():
    out, _ = sanitize_intent({"side": "up", "price": "ask", "reason": "x" * 500})
    assert len(out["reason"]) == 200


@pytest.mark.parametrize("raw,expect", [
    (None, None), ("hold", None),
    ("sell", {"action": "sell"}),
    ({"action": "sell"}, {"action": "sell"}),
    ({"action": "update", "stop_loss_cents": 0}, {"action": "update", "stop_loss_cents": 0}),
])
def test_sanitize_manage_accepts_the_contract(raw, expect):
    out, err = sanitize_manage(raw)
    assert err is None and out == expect


@pytest.mark.parametrize("raw", [
    "flatten", 42, {"action": "buy"},
    {"action": "update", "stop_loss_cents": 120},
    {"action": "update", "take_profit_pct": -1},
])
def test_sanitize_manage_rejects_malformed_actions(raw):
    out, err = sanitize_manage(raw)
    assert out is None and err


@pytest.mark.parametrize("raw,expect", [
    (None, None), (False, None), ({"follow": False}, None),
    (True, {"follow": True}),
    ({"follow": True, "sizeUsd": 10}, {"follow": True, "sizeUsd": 10.0}),
])
def test_sanitize_signal_action_accepts_the_contract(raw, expect):
    out, err = sanitize_signal_action(raw)
    assert err is None and out == expect


@pytest.mark.parametrize("raw", [
    "yes", {"follow": True, "sizeUsd": 0.5}, {"follow": True, "sizeUsd": 1e9},
    {"follow": True, "sizeUsd": float("nan")},
])
def test_sanitize_signal_action_rejects_malformed_returns(raw):
    out, err = sanitize_signal_action(raw)
    assert out is None and err


def test_entry_above_the_price_cap_is_refused(fresh_db, placed):
    cfg = _cfg(script_max_entry_cents=60)
    intent = {"side": "up", "price": 75}
    out = asyncio.run(
        script_engine._place_intent(_script(), _asset(), intent, cfg, ENV))
    assert out is None
    assert placed == [], "an over-cap limit must never reach the exchange"
    with db.get_db() as conn:
        rows = conn.execute("SELECT * FROM crypto15m_positions").fetchall()
    assert len(rows) == 1
    assert rows[0]["target_contracts"] == 0
    assert "script_max_entry_cents" in (rows[0]["error"] or "")


def test_entry_at_the_price_cap_is_allowed(fresh_db, placed):
    cfg = _cfg(script_max_entry_cents=60)
    intent = {"side": "up", "price": 60}
    asyncio.run(script_engine._place_intent(_script(), _asset(), intent, cfg, ENV))
    assert len(placed) == 1
    assert placed[0]["price_cents"] == 60


def test_crossing_the_ask_without_a_real_book_places_nothing(fresh_db, placed):
    intent = {"side": "up", "price": "ask"}
    out = asyncio.run(script_engine._place_intent(
        _script(), _asset(upAsk=None), intent, _cfg(), ENV))
    assert out is None and placed == []
    with db.get_db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM crypto15m_positions").fetchone()[0] == 0


def test_size_above_the_contract_cap_is_clamped(fresh_db, placed):
    cfg = _cfg(script_max_contracts=7)
    intent = {"side": "up", "price": 50, "size": 999}
    asyncio.run(script_engine._place_intent(_script(), _asset(), intent, cfg, ENV))
    assert len(placed) == 1
    assert placed[0]["count"] == 7


def test_contract_cap_below_the_exchange_minimum_is_never_exceeded(fresh_db, placed):
    cfg = _cfg(script_max_contracts=2)
    intent = {"side": "up", "price": 90, "size": 1}
    out = asyncio.run(script_engine._place_intent(_script(), _asset(), intent, cfg, ENV))
    assert out is None
    assert placed == [], "must not place an order larger than the user's cap"
    with db.get_db() as conn:
        row = dict(conn.execute("SELECT * FROM crypto15m_positions").fetchone())
    assert row["target_contracts"] == 0
    assert "script_max_contracts" in (row["error"] or "")


def test_min_notional_shortfall_refuses_when_it_would_break_the_cap(fresh_db, placed):
    cfg = _cfg(script_max_contracts=6)
    intent = {"side": "up", "price": 5, "size": 6}
    out = asyncio.run(script_engine._place_intent(_script(), _asset(), intent, cfg, ENV))
    assert out is None and placed == []
    with db.get_db() as conn:
        row = dict(conn.execute("SELECT * FROM crypto15m_positions").fetchone())
    assert row["target_contracts"] == 0


def test_backtest_contract_floor_matches_the_live_engine():
    import script_backtest
    assert script_backtest.MIN_CONTRACTS == crypto15m_trader._C15_MIN_CONTRACTS


def test_min_notional_is_met_when_the_cap_has_room(fresh_db, placed):
    cfg = _cfg(script_max_contracts=50)
    intent = {"side": "up", "price": 5, "size": 6}
    asyncio.run(script_engine._place_intent(_script(), _asset(), intent, cfg, ENV))
    assert len(placed) == 1
    assert placed[0]["count"] * 5 / 100.0 >= crypto15m_trader._MIN_ORDER_NOTIONAL_USD


def _shadow_rows(sid="s1abc"):
    with db.get_db() as conn:
        return db.list_script_shadow(conn, sid)


def test_shadow_entry_records_the_order_and_places_nothing(fresh_db, placed):
    s = _script(dry_run=1)
    intent = {"side": "up", "price": 55, "size": 9, "reason": "test entry"}
    out = asyncio.run(script_engine._place_intent(s, _asset(), intent, _cfg(), ENV))

    assert placed == [], "shadow mode must never reach the exchange"
    assert out is not None and out["shadow"] is True
    rows = _shadow_rows()
    assert len(rows) == 1
    assert rows[0]["contracts"] == 9
    assert rows[0]["entry_cents"] == 55
    assert rows[0]["side"] == "up"
    assert rows[0]["reason"] == "test entry"
    with db.get_db() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM crypto15m_positions").fetchone()[0] == 0


def test_shadow_runs_the_same_rails_as_live(fresh_db, placed):
    s = _script(dry_run=1)
    cfg = _cfg(script_max_entry_cents=50)
    out = asyncio.run(script_engine._place_intent(
        s, _asset(), {"side": "up", "price": 75}, cfg, ENV))
    assert out is None and placed == []
    rows = _shadow_rows()
    assert len(rows) == 1
    assert rows[0]["contracts"] == 0 and rows[0]["refused"] == 1
    assert "script_max_entry_cents" in rows[0]["note"]


def test_shadow_consumes_the_window_like_live(fresh_db):
    s = _script(dry_run=1)
    asyncio.run(script_engine._place_intent(
        s, _asset(), {"side": "up", "price": 55}, _cfg(), ENV))
    with db.get_db() as conn:
        assert script_engine._already_attempted(
            conn, "s1abc", "0xtick", shadow=True) is True
        assert script_engine._already_attempted(
            conn, "s1abc", "0xtick", shadow=False) is False


def test_shadow_signal_follow_records_and_places_nothing(fresh_db, placed, monkeypatch):
    async def _quote(_ticker, _side):
        return {"bid_cents": 40, "ask_cents": 42}
    monkeypatch.setattr(polymarket_api, "get_quote", _quote)

    s = _script(dry_run=1)
    sig = {"id": 11, "ticker": "mk-signal", "taker_side": "yes",
           "title": "Some market", "category": "sports"}
    out = asyncio.run(script_engine._place_signal_follow(
        s, sig, "whale", {"follow": True, "sizeUsd": 10}, _cfg(), ENV))

    assert placed == [] and out is not None and out["shadow"] is True
    rows = _shadow_rows()
    assert len(rows) == 1
    assert rows[0]["source"] == "signal"
    assert rows[0]["signal_source"] == "whale"
    assert rows[0]["signal_id"] == 11
    assert rows[0]["entry_cents"] == 42
    with db.get_db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM bot_positions").fetchone()[0] == 0


def test_shadow_orders_settle_from_the_recorded_window_outcome(fresh_db):
    s = _script(dry_run=1)
    asyncio.run(script_engine._place_intent(
        s, _asset(), {"side": "up", "price": 60, "size": 10}, _cfg(), ENV))
    with db.get_db() as conn:
        conn.execute(
            """INSERT INTO crypto15m_signals (ticker, asset, resolved, up_won)
               VALUES (?,?,1,1)""", ("0xtick", "BTC"))

    asyncio.run(script_engine._settle_shadow_orders())

    row = _shadow_rows()[0]
    assert row["resolved"] == 1
    assert row["outcome_correct"] == 1
    assert 0 < row["pnl_usd"] < 4.0


def test_shadow_settlement_charges_fees_on_a_loss(fresh_db):
    s = _script(dry_run=1)
    asyncio.run(script_engine._place_intent(
        s, _asset(), {"side": "up", "price": 60, "size": 10}, _cfg(), ENV))
    with db.get_db() as conn:
        conn.execute(
            """INSERT INTO crypto15m_signals (ticker, asset, resolved, up_won)
               VALUES (?,?,1,0)""", ("0xtick", "BTC"))

    asyncio.run(script_engine._settle_shadow_orders())

    row = _shadow_rows()[0]
    assert row["outcome_correct"] == 0
    assert row["pnl_usd"] < -6.0


def test_market_shadow_orders_settle_from_the_recorded_market_result(fresh_db):
    with db.get_db() as conn:
        db.insert_script_shadow(conn, {
            "script_id": "s1abc", "source": "signal",
            "signal_source": "market", "signal_id": None,
            "asset": "sports", "ticker": "0xmkt", "side": "yes",
            "contracts": 10, "entry_cents": 60, "order_type": "GTC",
            "reason": "test", "close_time": "", "network": ENV,
        })
        conn.execute(
            "INSERT INTO markets (ticker, status, result) VALUES (?,?,?)",
            ("0xmkt", "settled", "yes"))
        assert db.count_open_script_shadow(conn, "s1abc", ENV) == 1

    asyncio.run(script_engine._settle_shadow_orders())

    row = _shadow_rows()[0]
    assert row["resolved"] == 1 and row["outcome_correct"] == 1
    assert 0 < row["pnl_usd"] < 4.0
    with db.get_db() as conn:
        assert db.count_open_script_shadow(conn, "s1abc", ENV) == 0


def test_market_shadow_loss_settles_from_settlement_value(fresh_db):
    with db.get_db() as conn:
        db.insert_script_shadow(conn, {
            "script_id": "s1abc", "source": "signal",
            "signal_source": "market", "signal_id": None,
            "asset": "sports", "ticker": "0xmkt2", "side": "yes",
            "contracts": 10, "entry_cents": 60, "order_type": "GTC",
            "reason": "test", "close_time": "", "network": ENV,
        })
        conn.execute(
            """INSERT INTO markets (ticker, status, result, settlement_value)
               VALUES (?,?,?,?)""", ("0xmkt2", "settled", "", 0.0))

    asyncio.run(script_engine._settle_shadow_orders())

    row = _shadow_rows()[0]
    assert row["resolved"] == 1 and row["outcome_correct"] == 0
    assert row["pnl_usd"] < -6.0


def test_stale_shadow_orders_stop_consuming_the_open_cap(fresh_db):
    with db.get_db() as conn:
        db.insert_script_shadow(conn, {
            "script_id": "s1abc", "source": "signal",
            "signal_source": "market", "signal_id": None,
            "asset": "sports", "ticker": "0xstale", "side": "yes",
            "contracts": 10, "entry_cents": 60, "order_type": "GTC",
            "reason": "test", "close_time": "", "network": ENV,
        })
        assert db.count_open_script_shadow(conn, "s1abc", ENV) == 1
        conn.execute(
            """UPDATE script_shadow_orders
               SET created_at = datetime('now', ?) WHERE ticker='0xstale'""",
            (f"-{db.SHADOW_STALE_DAYS + 1} days",))
        assert db.count_open_script_shadow(conn, "s1abc", ENV) == 0


def test_unresolved_windows_leave_shadow_orders_open(fresh_db):
    import datetime
    recent = (datetime.datetime.now(datetime.timezone.utc)
              - datetime.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    s = _script(dry_run=1)
    asyncio.run(script_engine._place_intent(
        s, _asset(closeTime=recent), {"side": "up", "price": 60}, _cfg(), ENV))
    asyncio.run(script_engine._settle_shadow_orders())
    assert _shadow_rows()[0]["resolved"] == 0


def test_a_long_stale_shadow_order_is_retired_rather_than_left_open(fresh_db):
    s = _script(dry_run=1)
    asyncio.run(script_engine._place_intent(
        s, _asset(closeTime="2026-07-01T00:00:00Z"),
        {"side": "up", "price": 60}, _cfg(), ENV))
    asyncio.run(script_engine._settle_shadow_orders())
    row = _shadow_rows()[0]
    assert row["resolved"] == 1
    assert row["outcome_correct"] is None and row["pnl_usd"] is None
    with db.get_db() as conn:
        assert db.count_open_script_shadow(conn, "s1abc", ENV) == 0


def test_shadow_pnl_and_open_count_drive_the_same_breakers(fresh_db):
    s = _script(dry_run=1)
    asyncio.run(script_engine._place_intent(
        s, _asset(), {"side": "up", "price": 60, "size": 10}, _cfg(), ENV))
    with db.get_db() as conn:
        assert db.count_open_script_shadow(conn, "s1abc", ENV) == 1
        conn.execute(
            """INSERT INTO crypto15m_signals (ticker, asset, resolved, up_won)
               VALUES (?,?,1,0)""", ("0xtick", "BTC"))
    asyncio.run(script_engine._settle_shadow_orders())
    with db.get_db() as conn:
        assert db.count_open_script_shadow(conn, "s1abc", ENV) == 0
        assert db.script_shadow_daily_pnl(conn, "s1abc", ENV) < 0
        stats = db.script_shadow_stats(conn, ENV)
    assert stats["s1abc"]["n"] == 1 and stats["s1abc"]["losses"] == 1


def test_refusal_rows_are_excluded_from_shadow_stats(fresh_db):
    s = _script(dry_run=1)
    asyncio.run(script_engine._place_intent(
        s, _asset(), {"side": "up", "price": 99},
        _cfg(script_max_entry_cents=50), ENV))
    with db.get_db() as conn:
        assert db.script_shadow_stats(conn, ENV) == {}
        assert db.count_open_script_shadow(conn, "s1abc", ENV) == 0


def test_new_scripts_start_in_shadow(fresh_db):
    _install_script("sNew", "def decide(ctx):\n    return None\n")
    with db.get_db() as conn:
        assert db.get_user_script(conn, "sNew")["dry_run"] == 1


def test_arming_a_script_persists(fresh_db):
    _install_script("sArm", "def decide(ctx):\n    return None\n")
    with db.get_db() as conn:
        db.update_user_script(conn, "sArm", dry_run=0)
        assert db.get_user_script(conn, "sArm")["dry_run"] == 0


def _market(**over) -> dict:
    m = {
        "ticker": "0xmkt", "event_ticker": "ev1", "title": "Will X happen?",
        "category": "politics", "slug": "will-x-happen", "status": "active",
        "close_time": "2026-12-01T00:00:00Z", "volume": 250000.0,
        "volume_24h": 9000.0, "open_interest": 4000.0,
        "yes_bid": 0.40, "yes_ask": 0.44, "last_price": 0.42,
        "prev_price": 0.39,
    }
    m.update(over)
    return m


def test_market_ctx_exposes_both_sides_and_derived_fields():
    js = market_to_js(_market())
    assert js["yesAsk"] == 0.44 and js["yesBid"] == 0.40
    assert js["noAsk"] == pytest.approx(0.60)
    assert js["noBid"] == pytest.approx(0.56)
    assert js["yesMid"] == pytest.approx(0.42)
    assert js["spreadCents"] == pytest.approx(4.0)
    assert js["priceChange"] == pytest.approx(0.03)
    assert js["title"] == "Will X happen?"


def test_market_ctx_rejects_out_of_range_prices_as_none():
    js = market_to_js(_market(yes_bid=0.0, yes_ask=1.0, last_price=0.0))
    assert js["yesBid"] is None and js["yesAsk"] is None
    assert js["yesMid"] is None and js["spreadCents"] is None


@pytest.mark.parametrize("raw,expect", [
    (None, None),
    ({"side": "yes", "price": "ask"}, {"side": "yes", "price": "ask"}),
    ({"side": "NO", "price": 30}, {"side": "no", "price": 30}),
])
def test_sanitize_market_intent_accepts_the_contract(raw, expect):
    out, err = sanitize_market_intent(raw)
    assert err is None and out == expect


@pytest.mark.parametrize("raw", [
    "buy", {"price": "ask"},
    {"side": "up", "price": "ask"},
    {"side": "yes", "price": 0},
    {"side": "yes", "price": 100},
    {"side": "yes", "price": "ask", "size": 0},
    {"side": "yes", "price": "ask", "sizeUsd": 0.5},
    {"side": "yes", "price": "ask", "sizeUsd": float("nan")},
])
def test_sanitize_market_intent_rejects_malformed_intents(raw):
    out, err = sanitize_market_intent(raw)
    assert out is None and err


def test_market_universe_excludes_crypto_updown_windows(fresh_db):
    with db.get_db() as conn:
        db.upsert_market(conn, {
            "ticker": "0xbig", "title": "Will X happen?", "slug": "will-x",
            "status": "active", "volume": 500000.0, "category": "politics",
        })
        db.upsert_market(conn, {
            "ticker": "0xupdown", "title": "Bitcoin Up or Down?",
            "slug": "btc-updown-15m-1750000000", "status": "active",
            "volume": 900000.0, "category": "crypto",
        })
    tickers = [m["ticker"] for m in
               script_engine._market_universe(_cfg(script_market_limit=10,
                                                   script_market_min_volume=0))]
    assert "0xbig" in tickers
    assert "0xupdown" not in tickers


def _hours_from_now(h: float) -> str:
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) + timedelta(hours=h)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def test_market_universe_drops_markets_that_already_closed(fresh_db):
    with db.get_db() as conn:
        db.upsert_market(conn, {
            "ticker": "0xdead", "title": "Yesterday's game", "slug": "dead",
            "status": "open", "volume_24h": 9_000_000.0, "category": "sports",
            "close_time": _hours_from_now(-3),
        })
        db.upsert_market(conn, {
            "ticker": "0xlive", "title": "Tonight's game", "slug": "live",
            "status": "open", "volume_24h": 1000.0, "category": "sports",
            "close_time": _hours_from_now(4),
        })
    tickers = [m["ticker"] for m in script_engine._market_universe(
        _cfg(script_market_limit=10, script_market_min_volume=0))]
    assert tickers == ["0xlive"]


def test_market_universe_keeps_rows_with_no_close_time(fresh_db):
    with db.get_db() as conn:
        db.upsert_market(conn, {
            "ticker": "0xundated", "title": "T", "slug": "undated",
            "status": "open", "volume_24h": 5000.0, "category": "politics",
        })
    tickers = [m["ticker"] for m in script_engine._market_universe(
        _cfg(script_market_limit=10, script_market_min_volume=0))]
    assert tickers == ["0xundated"]


def test_market_universe_reserves_half_the_budget_for_imminent_markets(fresh_db):
    with db.get_db() as conn:
        for i in range(10):
            db.upsert_market(conn, {
                "ticker": f"0xfut{i}", "title": "Futures", "slug": f"fut{i}",
                "status": "open", "volume_24h": 1_000_000.0 - i,
                "category": "politics", "close_time": _hours_from_now(24 * 90),
            })
        for i in range(10):
            db.upsert_market(conn, {
                "ticker": f"0xsoon{i}", "title": "Tonight", "slug": f"soon{i}",
                "status": "open", "volume_24h": 6000.0 - i,
                "category": "sports", "close_time": _hours_from_now(5),
            })
    tickers = [m["ticker"] for m in script_engine._market_universe(
        _cfg(script_market_limit=6, script_market_min_volume=0))]
    assert len(tickers) == 6
    assert tickers[:3] == ["0xsoon0", "0xsoon1", "0xsoon2"]
    assert tickers[3:] == ["0xfut0", "0xfut1", "0xfut2"]


def test_market_universe_spends_the_whole_budget_when_nothing_closes_soon(fresh_db):
    with db.get_db() as conn:
        for i in range(6):
            db.upsert_market(conn, {
                "ticker": f"0xfut{i}", "title": "Futures", "slug": f"fut{i}",
                "status": "open", "volume_24h": 1_000_000.0 - i,
                "category": "politics", "close_time": _hours_from_now(24 * 90),
            })
    tickers = [m["ticker"] for m in script_engine._market_universe(
        _cfg(script_market_limit=4, script_market_min_volume=0))]
    assert tickers == ["0xfut0", "0xfut1", "0xfut2", "0xfut3"]


def test_market_universe_never_repeats_a_market_across_the_two_slices(fresh_db):
    with db.get_db() as conn:
        db.upsert_market(conn, {
            "ticker": "0xboth", "title": "Big game tonight", "slug": "both",
            "status": "open", "volume_24h": 5_000_000.0, "category": "sports",
            "close_time": _hours_from_now(2),
        })
        db.upsert_market(conn, {
            "ticker": "0xother", "title": "Other", "slug": "other",
            "status": "open", "volume_24h": 1000.0, "category": "politics",
            "close_time": _hours_from_now(24 * 90),
        })
    tickers = [m["ticker"] for m in script_engine._market_universe(
        _cfg(script_market_limit=10, script_market_min_volume=0))]
    assert tickers.count("0xboth") == 1
    assert sorted(tickers) == ["0xboth", "0xother"]


def test_market_universe_is_off_when_the_limit_is_zero(fresh_db):
    with db.get_db() as conn:
        db.upsert_market(conn, {
            "ticker": "0xbig", "title": "T", "slug": "t", "status": "active",
            "volume": 500000.0, "category": "politics",
        })
    assert script_engine._market_universe(_cfg(script_market_limit=0)) == []


def test_market_entry_places_through_the_rails(fresh_db, placed):
    s = _script(dry_run=0)
    intent = {"side": "yes", "price": 44, "size": 12, "reason": "cheap yes"}
    out = asyncio.run(script_engine._place_market_intent(
        s, _market(), intent, _cfg(), ENV))
    assert out is not None
    assert len(placed) == 1
    assert placed[0]["ticker"] == "0xmkt"
    assert placed[0]["side"] == "yes"
    assert placed[0]["count"] == 12
    assert placed[0]["price_cents"] == 44
    with db.get_db() as conn:
        row = dict(conn.execute("SELECT * FROM bot_positions").fetchone())
    assert row["script_id"] == "s1abc"
    assert row["direction"] == "yes"


def test_failed_market_entry_is_recorded_and_not_resubmitted(fresh_db, monkeypatch):
    calls: list[dict] = []

    async def _boom(**kw):
        calls.append(kw)
        raise polymarket_api.PolymarketAPIError(400, "not enough balance")

    monkeypatch.setattr(polymarket_api, "place_limit_order", _boom)
    s = _script(dry_run=0)
    intent = {"side": "yes", "price": 44, "size": 12, "reason": "cheap yes"}
    out = asyncio.run(script_engine._place_market_intent(
        s, _market(), intent, _cfg(), ENV))

    assert out is None and len(calls) == 1
    with db.get_db() as conn:
        row = dict(conn.execute("SELECT * FROM bot_positions").fetchone())
        assert script_engine._market_already_attempted(conn, "s1abc", "0xmkt")
    assert row["status"] == "error"
    assert "not enough balance" in (row["error"] or "")
    assert row["script_id"] == "s1abc"
    assert script_engine._in_cooldown("s1abc", "0xmkt") is True


def test_market_entry_without_an_order_id_is_recorded_as_an_error(fresh_db, monkeypatch):
    async def _no_id(**_kw):
        return {"order": {"order_id": "", "status": ""}}

    monkeypatch.setattr(polymarket_api, "place_limit_order", _no_id)
    out = asyncio.run(script_engine._place_market_intent(
        _script(dry_run=0), _market(), {"side": "yes", "price": 44, "size": 12},
        _cfg(), ENV))
    assert out is None
    with db.get_db() as conn:
        row = dict(conn.execute("SELECT * FROM bot_positions").fetchone())
    assert row["status"] == "error" and "no order_id" in (row["error"] or "")


def test_market_entry_respects_the_price_cap(fresh_db, placed):
    s = _script(dry_run=0)
    out = asyncio.run(script_engine._place_market_intent(
        s, _market(), {"side": "yes", "price": 90},
        _cfg(script_max_entry_cents=60), ENV))
    assert out is None and placed == []


def test_market_entry_respects_the_size_cap(fresh_db, placed):
    s = _script(dry_run=0)
    asyncio.run(script_engine._place_market_intent(
        s, _market(), {"side": "yes", "price": 44, "size": 999},
        _cfg(script_max_contracts=6), ENV))
    assert placed[0]["count"] == 6


def test_market_entry_refuses_when_the_cap_is_below_the_exchange_floor(fresh_db, placed):
    s = _script(dry_run=0)
    out = asyncio.run(script_engine._place_market_intent(
        s, _market(), {"side": "yes", "price": 44, "size": 1},
        _cfg(script_max_contracts=2), ENV))
    assert out is None and placed == []


def test_market_entry_sizes_from_dollars(fresh_db, placed):
    s = _script(dry_run=0)
    asyncio.run(script_engine._place_market_intent(
        s, _market(), {"side": "no", "price": 50, "sizeUsd": 10}, _cfg(), ENV))
    assert placed[0]["count"] == 20
    assert placed[0]["side"] == "no"


def test_market_entry_needs_a_real_book_to_cross(fresh_db, placed, monkeypatch):
    async def _no_book(_t, _s):
        return {"bid_cents": None, "ask_cents": None}
    monkeypatch.setattr(polymarket_api, "get_quote", _no_book)
    s = _script(dry_run=0)
    out = asyncio.run(script_engine._place_market_intent(
        s, _market(), {"side": "yes", "price": "ask"}, _cfg(), ENV))
    assert out is None and placed == []


def test_market_entry_crosses_the_live_ask(fresh_db, placed, monkeypatch):
    async def _book(_t, _s):
        return {"bid_cents": 40, "ask_cents": 47}
    monkeypatch.setattr(polymarket_api, "get_quote", _book)
    s = _script(dry_run=0)
    asyncio.run(script_engine._place_market_intent(
        s, _market(), {"side": "yes", "price": "ask", "size": 10}, _cfg(), ENV))
    assert placed[0]["price_cents"] == 47


def test_shadow_market_entry_records_and_places_nothing(fresh_db, placed):
    s = _script(dry_run=1)
    out = asyncio.run(script_engine._place_market_intent(
        s, _market(), {"side": "yes", "price": 44, "size": 10}, _cfg(), ENV))
    assert placed == [] and out is not None and out["shadow"] is True
    rows = _shadow_rows()
    assert len(rows) == 1 and rows[0]["ticker"] == "0xmkt"
    with db.get_db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM bot_positions").fetchone()[0] == 0


def test_one_entry_per_market_per_script(fresh_db, placed):
    s = _script(dry_run=0)
    asyncio.run(script_engine._place_market_intent(
        s, _market(), {"side": "yes", "price": 44, "size": 10}, _cfg(), ENV))
    with db.get_db() as conn:
        assert script_engine._market_already_attempted(conn, "s1abc", "0xmkt") is True
        assert script_engine._market_already_attempted(conn, "s1abc", "other") is False


def test_two_scripts_can_follow_the_same_market(fresh_db, placed):
    for sid in ("scriptA", "scriptB"):
        out = asyncio.run(script_engine._place_market_intent(
            _script(sid, dry_run=0), _market(),
            {"side": "yes", "price": 44, "size": 10}, _cfg(), ENV))
        assert out is not None, f"{sid} failed to record its position"
    with db.get_db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM bot_positions").fetchone()[0] == 2


def test_supervise_rejects_keys_outside_the_whitelist():
    patch, notes = script_engine._sanitize_supervise(
        {"set": {"start_bankroll_usd": 1e9, "enable_trading": False}})
    assert patch == {"enable_trading": False}
    assert any("start_bankroll_usd" in n for n in notes)


def test_supervise_may_disable_engines_but_never_enable_them():
    patch, notes = script_engine._sanitize_supervise({"set": {"enable_trading": True}})
    assert patch == {}
    assert any("not on" in n for n in notes)


def test_supervise_validates_value_types():
    patch, notes = script_engine._sanitize_supervise({"set": {
        "crypto15m_direction_mode": "sideways",
        "crypto15m_entry_threshold": float("inf"),
        "crypto15m_entry_max": "not a number",
    }})
    assert patch == {}
    assert len(notes) == 3


def test_supervise_accepts_a_well_formed_patch():
    patch, notes = script_engine._sanitize_supervise({"set": {
        "crypto15m_direction_mode": "contrarian",
        "crypto15m_entry_threshold": 0.62,
    }})
    assert patch == {"crypto15m_direction_mode": "contrarian",
                     "crypto15m_entry_threshold": 0.62}
    assert notes == []


@pytest.mark.parametrize("raw", [None, "off", {"nope": 1}, 42])
def test_supervise_rejects_a_malformed_return(raw):
    patch, _ = script_engine._sanitize_supervise(raw)
    assert patch == {}


def test_supervise_does_not_run_in_shadow_mode(emitted):
    mod = _mod(
        "def decide(ctx):\n    return None\n"
        "def supervise(app):\n"
        "    return {'set': {'crypto15m_entry_threshold': 0.62}}\n"
    )
    s = _script(dry_run=1)
    cfg = {"crypto15m_entry_threshold": 0.95}

    asyncio.run(script_engine._run_supervise(s, mod, cfg, {"hourUtc": 3},
                                             shadow=True))
    assert [e for e in emitted if e[0] == "script:configPatch"] == []

    asyncio.run(script_engine._run_supervise(_script(dry_run=0), mod, cfg,
                                             {"hourUtc": 3}, shadow=False))
    patches = [e for e in emitted if e[0] == "script:configPatch"]
    assert len(patches) == 1
    assert patches[0][1]["patch"] == {"crypto15mEntryThreshold": 0.62}


def test_heartbeat_says_supervise_was_skipped_in_shadow():
    line = script_engine._heartbeat_line(
        {"ticks": 4, "supervise_skipped_shadow": 4},
        shadow=True, open_count=0, day_pnl=0.0)
    assert "supervise skipped (shadow)" in line


def _add_crypto_pos(sid, *, pnl=None, resolved=0, filled=0, status="filled"):
    with db.get_db() as conn:
        pid = db.insert_crypto15m_position(conn, {
            "asset": "BTC", "series": "s", "ticker": f"tk{sid}{pnl}{filled}",
            "side": "up", "direction": "yes", "target_contracts": 10,
            "entry_limit_cents": 50, "client_order_id": f"c{sid}{pnl}{filled}",
            "close_time": "", "confidence": 0.0, "network": ENV,
            "status": status, "script_id": sid, "strategy": f"script:{sid}",
        })
        fields = {"filled_contracts": filled}
        if resolved:
            fields.update({"resolved": 1, "pnl_usd": pnl, "status": status})
        db.update_crypto15m_position(conn, pid, **fields)
        return pid


def test_daily_pnl_and_open_count_span_both_position_tables(fresh_db):
    _add_crypto_pos("sA", pnl=-4.0, resolved=1, status="settled")
    _add_crypto_pos("sA", pnl=1.5, resolved=1, status="settled")
    _add_crypto_pos("sA", resolved=0, filled=10)
    with db.get_db() as conn:
        db.insert_bot_position(conn, {
            "signal_source": "script:sA:whale", "signal_id": 1,
            "ticker": "mk1", "event_ticker": "", "title": "t", "category": "",
            "direction": "yes", "action": "buy", "target_contracts": 5,
            "limit_price_cents": 50, "client_order_id": "cx", "confidence": 0.0,
            "edge_pts": 0.0, "signal_price": 50.0, "network": ENV,
            "script_id": "sA", "status": "submitted",
        })
        assert script_engine._script_daily_pnl(conn, "sA", ENV) == pytest.approx(-2.5)
        assert script_engine._count_open_for_script(conn, "sA", ENV) == 2


def test_one_entry_attempt_per_market_window(fresh_db):
    _add_crypto_pos("sB")
    with db.get_db() as conn:
        assert script_engine._already_attempted(conn, "sB", "tksBNone0") is True
        assert script_engine._already_attempted(conn, "sB", "other") is False


def test_a_refusal_row_consumes_the_window(fresh_db):
    script_engine._record_refusal("sC", _asset(), "up", ENV, "nope")
    with db.get_db() as conn:
        assert script_engine._already_attempted(conn, "sC", "0xtick") is True


def _install_script(sid, code, **over):
    with db.get_db() as conn:
        row = {"id": sid, "name": "n", "description": "", "code": code,
               "notes": ""}
        db.upsert_user_script(conn, row)
        if over:
            db.update_user_script(conn, sid, **over)


def test_state_round_trips_through_the_database(fresh_db):
    _install_script("sD", "def decide(ctx):\n    return None\n")
    with db.get_db() as conn:
        row = db.get_user_script(conn, "sD")
    mod = script_engine._get_compiled(row, {})
    mod.state["memory"] = {"BTC": 3}
    script_engine._save_states()
    with db.get_db() as conn:
        saved = db.get_user_script(conn, "sD")["state_json"]
    assert json.loads(saved) == {"memory": {"BTC": 3}}


def test_oversized_state_never_overwrites_good_state_with_broken_json(fresh_db):
    _install_script("sE", "def decide(ctx):\n    return None\n")
    with db.get_db() as conn:
        row = db.get_user_script(conn, "sE")
    mod = script_engine._get_compiled(row, {})
    mod.state["ok"] = 1
    script_engine._save_states()

    mod.state["huge"] = "x" * (128 * 1024)
    script_engine._last_state_save = 0.0
    script_engine._save_states()

    with db.get_db() as conn:
        saved = db.get_user_script(conn, "sE")["state_json"]
    assert json.loads(saved) == {"ok": 1}


def test_non_serializable_state_is_dropped_not_fatal(fresh_db):
    _install_script("sF", "def decide(ctx):\n    return None\n")
    with db.get_db() as conn:
        row = db.get_user_script(conn, "sF")
    mod = script_engine._get_compiled(row, {})
    mod.state["bad"] = {1, 2, 3}
    script_engine._save_states()
    with db.get_db() as conn:
        assert json.loads(db.get_user_script(conn, "sF")["state_json"]) == {}


def test_compile_failure_disables_the_script_and_records_why(fresh_db):
    _install_script("sG", "def decide(ctx)\n    return None\n", enabled=1)
    with db.get_db() as conn:
        row = db.get_user_script(conn, "sG")
    assert script_engine._get_compiled(row, {}) is None
    with db.get_db() as conn:
        after = db.get_user_script(conn, "sG")
    assert after["enabled"] == 0
    assert "syntax error" in (after["last_error"] or "").lower()


def test_a_script_that_imports_the_stdlib_compiles_fine(fresh_db):
    _install_script(
        "sG2", "import json\ndef decide(ctx):\n    return None\n", enabled=1)
    with db.get_db() as conn:
        row = db.get_user_script(conn, "sG2")
    assert script_engine._get_compiled(row, {}) is not None
    with db.get_db() as conn:
        assert db.get_user_script(conn, "sG2")["enabled"] == 1


def test_a_hook_that_hangs_is_abandoned_not_awaited_forever(fresh_db):
    with pytest.raises(script_engine.script_sandbox.ScriptBudgetExceeded):
        script_engine._run_bounded(lambda: __import__("time").sleep(5),
                                   0.2, "hang-test")


def test_on_fill_and_on_settle_fire_for_crypto_positions(fresh_db):
    code = (
        "def decide(ctx):\n    return None\n"
        "def on_fill(position, state):\n"
        "    state['filled'] = state.get('filled', 0) + 1\n"
        "def on_settle(position, state):\n"
        "    state['settled'] = state.get('settled', 0) + 1\n"
    )
    _install_script("sH", code, enabled=1)
    with db.get_db() as conn:
        row = db.get_user_script(conn, "sH")
    mod = script_engine._get_compiled(row, {})
    _add_crypto_pos("sH", filled=10, resolved=1, pnl=2.0, status="settled")

    asyncio.run(script_engine._notify_lifecycle({"sH": dict(row, enabled=1)}, ENV, {}))
    assert mod.state.get("filled") == 1
    assert mod.state.get("settled") == 1

    asyncio.run(script_engine._notify_lifecycle({"sH": dict(row, enabled=1)}, ENV, {}))
    assert mod.state.get("filled") == 1
    assert mod.state.get("settled") == 1


def test_fill_notifications_are_not_confused_across_the_two_tables(fresh_db):
    code = (
        "def decide(ctx):\n    return None\n"
        "def on_fill(position, state):\n"
        "    state['seen'] = state.get('seen', 0) + 1\n"
    )
    _install_script("sJ", code, enabled=1)
    with db.get_db() as conn:
        row = db.get_user_script(conn, "sJ")
        mod = script_engine._get_compiled(row, {})
        pid = db.insert_bot_position(conn, {
            "signal_source": "script:sJ:whale", "signal_id": 3,
            "ticker": "mk3", "event_ticker": "", "title": "t", "category": "",
            "direction": "yes", "action": "buy", "target_contracts": 5,
            "limit_price_cents": 50, "client_order_id": "cz", "confidence": 0.0,
            "edge_pts": 0.0, "signal_price": 50.0, "network": ENV,
            "script_id": "sJ", "status": "filled",
        })
        db.update_bot_position(conn, pid, filled_contracts=5, status="filled")
    crypto_id = _add_crypto_pos("sJ", filled=10)
    assert crypto_id == pid == 1, "test needs colliding ids to be meaningful"

    asyncio.run(script_engine._notify_lifecycle({"sJ": dict(row, enabled=1)}, ENV, {}))
    assert mod.state.get("seen") == 2, "both positions must be reported"


def test_forget_releases_a_deleted_scripts_module(fresh_db):
    _install_script("sK", "def decide(ctx):\n    return None\n")
    with db.get_db() as conn:
        row = db.get_user_script(conn, "sK")
    assert script_engine._get_compiled(row, {}) is not None
    assert "sK" in script_engine._compiled
    script_engine.forget("sK")
    assert "sK" not in script_engine._compiled


def test_on_fill_fires_for_signal_follow_positions_too(fresh_db):
    code = (
        "def decide_signal(signal):\n    return None\n"
        "def on_fill(position, state):\n"
        "    state['filled'] = state.get('filled', 0) + 1\n"
    )
    _install_script("sI", code, enabled=1)
    with db.get_db() as conn:
        row = db.get_user_script(conn, "sI")
        mod = script_engine._get_compiled(row, {})
        pid = db.insert_bot_position(conn, {
            "signal_source": "script:sI:whale", "signal_id": 7,
            "ticker": "mk9", "event_ticker": "", "title": "t", "category": "",
            "direction": "yes", "action": "buy", "target_contracts": 5,
            "limit_price_cents": 50, "client_order_id": "cy", "confidence": 0.0,
            "edge_pts": 0.0, "signal_price": 50.0, "network": ENV,
            "script_id": "sI", "status": "filled",
        })
        db.update_bot_position(conn, pid, filled_contracts=5, status="filled")

    asyncio.run(script_engine._notify_lifecycle({"sI": dict(row, enabled=1)}, ENV, {}))
    assert mod.state.get("filled") == 1


def _all_engines_off() -> dict:
    return {
        "enable_trading": False,
        "crypto15m_enabled": False,
        "copy_enabled": False,
        "trade_whales": False,
        "trade_momentum": False,
        "main_record_signals": False,
        "crypto15m_assets": ["BTC"],
        "scripts_live_enabled": False,
        "script_max_entry_cents": 97,
        "script_max_contracts": 20,
        "script_max_open": 5,
        "script_daily_loss_usd": 25.0,
        "script_max_enabled": 10,
        "crypto15m_order_size": 1,
        "script_market_limit": 0,
    }


def _snapshot_of(*assets: str) -> dict:
    return {"assets": [{
        "asset": a, "series": f"{a}-updown", "ticker": f"0x{a.lower()}",
        "closeTime": "2026-08-02T12:15:00Z", "hasMarket": True,
        "favorite": "up", "favoritePrice": 0.9, "minsLeft": 2.0,
        "upAsk": 0.90, "downAsk": 0.12, "yesBid": 0.89, "yesAsk": 0.91,
    } for a in assets]}


@pytest.fixture
def engine_stubs(monkeypatch):
    import crypto15m
    import polymarket_api
    import polymarket_auth
    import trader

    async def _snap(_cfg):
        return _snapshot_of("BTC", "ETH", "SOL")

    async def _bal(_cfg, force=False):
        return (10_000, {})

    async def _quote(_ticker, _side):
        return {"ask_cents": 90, "bid_cents": 88}

    monkeypatch.setattr(polymarket_api, "get_quote", _quote)
    monkeypatch.setattr(crypto15m, "snapshot", _snap)
    monkeypatch.setattr(trader, "refresh_balance", _bal)
    monkeypatch.setattr(trader, "last_balance_read_ok", lambda: True)
    monkeypatch.setattr(polymarket_auth, "get_env", lambda: ENV)
    monkeypatch.setattr(script_engine, "_status", {}, raising=False)
    monkeypatch.setattr(script_engine, "_enabled_hooks", set(), raising=False)


def test_a_shadow_script_trades_with_every_other_engine_off(fresh_db, engine_stubs):
    _install_script("indep", (
        "def decide(ctx):\n"
        "    log('saw ' + ctx['asset'])\n"
        "    return {'side': 'up', 'price': 'ask', 'reason': 'test'}\n"
    ), enabled=1, dry_run=1)

    asyncio.run(script_engine.run_tick(_all_engines_off(), authed=True))

    with db.get_db() as conn:
        rows = db.list_script_shadow(conn, "indep", 50)
    seen = sorted(r["asset"] for r in rows if not r["refused"])
    assert seen == ["BTC", "ETH", "SOL"], seen

    st = script_engine.status_for("indep")
    assert st["ticks"] == 1 and st["orders"] == 3, st


def test_a_scoped_script_sees_only_its_own_coins(fresh_db, engine_stubs):
    _install_script("scoped", (
        "def decide(ctx):\n"
        "    return {'side': 'up', 'price': 'ask'}\n"
    ), enabled=1, dry_run=1)
    with db.get_db() as conn:
        db.update_user_script(conn, "scoped", assets=json.dumps(["ETH"]))

    asyncio.run(script_engine.run_tick(_all_engines_off(), authed=True))

    with db.get_db() as conn:
        rows = db.list_script_shadow(conn, "scoped", 50)
    assert sorted(r["asset"] for r in rows if not r["refused"]) == ["ETH"]


def test_an_armed_script_is_parked_when_the_master_switch_is_off(
        fresh_db, engine_stubs, monkeypatch):
    import polymarket_api

    async def _boom(**kw):
        raise AssertionError("armed script reached the exchange with the "
                             "master switch off")

    monkeypatch.setattr(polymarket_api, "place_limit_order", _boom)
    _install_script("armed", (
        "def decide(ctx):\n"
        "    return {'side': 'up', 'price': 'ask'}\n"
    ), enabled=1, dry_run=0)

    asyncio.run(script_engine.run_tick(_all_engines_off(), authed=True))

    with db.get_db() as conn:
        assert db.list_script_shadow(conn, "armed", 50) == []
        assert conn.execute(
            "SELECT COUNT(*) FROM crypto15m_positions WHERE script_id='armed'"
        ).fetchone()[0] == 0
    assert script_engine.status_for("armed")["gate"] == "master_off"


def test_the_master_switch_lets_the_same_script_trade(fresh_db, engine_stubs,
                                                      placed):
    _install_script("armed2", (
        "def decide(ctx):\n"
        "    return {'side': 'up', 'price': 'ask'}\n"
    ), enabled=1, dry_run=0)

    cfg = _all_engines_off()
    cfg["scripts_live_enabled"] = True
    asyncio.run(script_engine.run_tick(cfg, authed=True))

    assert len(placed) == 3, placed
    with db.get_db() as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM crypto15m_positions WHERE script_id='armed2'"
        ).fetchone()[0]
    assert n == 3


def test_a_signal_script_keeps_the_collector_alive_with_the_main_engine_off(
        fresh_db, engine_stubs):
    _install_script("sig", (
        "def decide_signal(signal):\n"
        "    return None\n"
    ), enabled=1, dry_run=1)

    cfg = _all_engines_off()
    assert not cfg["main_record_signals"] and not cfg["enable_trading"]
    asyncio.run(script_engine.run_tick(cfg, authed=True))

    assert script_engine.needs_signal_feed() is True


def test_a_crypto_only_script_does_not_ask_for_the_signal_feed(
        fresh_db, engine_stubs):
    _install_script("cry", (
        "def decide(ctx):\n    return None\n"
    ), enabled=1, dry_run=1)
    asyncio.run(script_engine.run_tick(_all_engines_off(), authed=True))
    assert script_engine.needs_signal_feed() is False


def test_no_crypto_hook_means_no_crypto_snapshot_fanout(fresh_db, engine_stubs,
                                                        monkeypatch):
    import crypto15m
    calls = []

    async def _snap(_cfg):
        calls.append(1)
        return _snapshot_of("BTC")

    monkeypatch.setattr(crypto15m, "snapshot", _snap)
    _install_script("sigonly", (
        "def decide_signal(signal):\n    return None\n"
    ), enabled=1, dry_run=1)

    asyncio.run(script_engine.run_tick(_all_engines_off(), authed=True))
    assert calls == []


def test_notional_cap_keeps_a_fill_inside_the_size_rail():
    cap = script_engine._notional_capped
    n = cap(20, 21, 20, 20)
    assert n == 19, n
    assert n * 21 // 20 <= 20


def test_notional_cap_is_a_no_op_on_a_tight_cross():
    cap = script_engine._notional_capped
    for req, lim, ask in ((5, 21, 20), (5, 32, 31), (10, 51, 50)):
        assert cap(req, lim, ask, 20) == req, (req, lim, ask)


def test_notional_cap_survives_a_missing_quote():
    cap = script_engine._notional_capped
    assert cap(5, 31, 0, 20) == 5
    assert cap(5, 99, 1, 20) >= 1


def test_the_live_entry_path_requotes_before_crossing(fresh_db, engine_stubs,
                                                      placed, monkeypatch):
    import polymarket_api

    async def _quote(_ticker, _side):
        return {"ask_cents": 30, "bid_cents": 28}

    monkeypatch.setattr(polymarket_api, "get_quote", _quote)
    _install_script("rq", (
        "def decide(ctx):\n"
        "    return {'side': 'up', 'price': 'ask', 'size': 5}\n"
    ), enabled=1, dry_run=0)

    cfg = _all_engines_off()
    cfg["scripts_live_enabled"] = True
    asyncio.run(script_engine.run_tick(cfg, authed=True))

    assert placed, "nothing was placed"
    assert all(o["price_cents"] == 31 for o in placed), placed


def test_a_live_entry_is_refused_when_the_balance_cannot_fund_it(
        fresh_db, engine_stubs, placed, monkeypatch):
    import trader

    async def _broke(_cfg, force=False):
        return (97, {})

    monkeypatch.setattr(trader, "refresh_balance", _broke)
    _install_script("poor", (
        "def decide(ctx):\n"
        "    return {'side': 'up', 'price': 'ask', 'size': 5}\n"
    ), enabled=1, dry_run=0)

    cfg = _all_engines_off()
    cfg["scripts_live_enabled"] = True
    asyncio.run(script_engine.run_tick(cfg, authed=True))

    assert placed == [], f"an unaffordable order reached the exchange: {placed}"
    with db.get_db() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT status, error FROM crypto15m_positions WHERE script_id='poor'")]
    assert rows, "the refusal was not recorded at all"
    assert all(r["status"] == "canceled" for r in rows), rows
    assert any("balance" in (r["error"] or "") for r in rows), rows


def test_an_affordable_entry_still_goes_through(fresh_db, engine_stubs, placed,
                                                monkeypatch):
    import trader

    async def _ok(_cfg, force=False):
        return (2_000, {})

    monkeypatch.setattr(trader, "refresh_balance", _ok)
    _install_script("funded", (
        "def decide(ctx):\n"
        "    return {'side': 'up', 'price': 'ask', 'size': 5}\n"
    ), enabled=1, dry_run=0)

    cfg = _all_engines_off()
    cfg["scripts_live_enabled"] = True
    asyncio.run(script_engine.run_tick(cfg, authed=True))
    assert placed, "a funded order was refused"


def test_shadow_ignores_the_balance(fresh_db, engine_stubs, monkeypatch):
    import trader

    async def _broke(_cfg, force=False):
        return (0, {})

    monkeypatch.setattr(trader, "refresh_balance", _broke)
    _install_script("shad", (
        "def decide(ctx):\n"
        "    return {'side': 'up', 'price': 'ask', 'size': 5}\n"
    ), enabled=1, dry_run=1)

    asyncio.run(script_engine.run_tick(_all_engines_off(), authed=True))

    with db.get_db() as conn:
        rows = db.list_script_shadow(conn, "shad", 20)
    assert [r for r in rows if not r["refused"]], "shadow was blocked by balance"


def _mk_shadow(sid, ticker, side, *, cents=90, contracts=10, close_time):
    with db.get_db() as conn:
        return db.insert_script_shadow(conn, {
            "script_id": sid, "source": "signal", "signal_source": "market",
            "signal_id": None, "asset": "sports", "ticker": ticker,
            "side": side, "contracts": contracts, "entry_cents": cents,
            "order_type": "GTC", "close_time": close_time, "network": ENV,
        })


def _fee(_cost, _created_at):
    return 0.0


def test_market_shadow_settles_from_the_live_api_not_the_local_table(fresh_db):
    _mk_shadow("mk", "0xgone", "yes", close_time="2026-07-27T03:00:00Z")
    with db.get_db() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM markets WHERE ticker='0xgone'").fetchone()[0] == 0
        n = db.resolve_script_shadow(conn, _fee,
                                     market_results={"0xgone": "yes"})
    assert n == 1
    with db.get_db() as conn:
        r = dict(conn.execute(
            "SELECT * FROM script_shadow_orders WHERE ticker='0xgone'").fetchone())
    assert r["resolved"] == 1 and r["outcome_correct"] == 1
    assert r["pnl_usd"] > 0, r["pnl_usd"]


def test_a_losing_market_shadow_books_the_loss(fresh_db):
    _mk_shadow("mk", "0xlose", "no", close_time="2026-07-27T03:00:00Z")
    with db.get_db() as conn:
        db.resolve_script_shadow(conn, _fee, market_results={"0xlose": "yes"})
        r = dict(conn.execute(
            "SELECT * FROM script_shadow_orders WHERE ticker='0xlose'").fetchone())
    assert r["resolved"] == 1 and r["outcome_correct"] == 0
    assert r["pnl_usd"] < 0, r["pnl_usd"]


def test_an_unresolvable_row_is_retired_so_it_stops_eating_the_cap(fresh_db):
    _mk_shadow("mk", "0xstuck", "yes", close_time="2026-07-01T00:00:00Z")
    with db.get_db() as conn:
        n = db.resolve_script_shadow(conn, _fee, market_results={}, stale_days=7)
    assert n == 1
    with db.get_db() as conn:
        r = dict(conn.execute(
            "SELECT * FROM script_shadow_orders WHERE ticker='0xstuck'").fetchone())
    assert r["resolved"] == 1
    assert r["outcome_correct"] is None and r["pnl_usd"] is None
    assert "never became available" in (r["note"] or "")
    with db.get_db() as conn:
        assert db.count_open_script_shadow(conn, "mk", ENV) == 0


def test_a_recent_unresolved_row_is_left_alone(fresh_db):
    import datetime
    soon = (datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    _mk_shadow("mk", "0xfresh", "yes", close_time=soon)
    with db.get_db() as conn:
        assert db.resolve_script_shadow(conn, _fee, market_results={},
                                        stale_days=7) == 0
        assert db.count_open_script_shadow(conn, "mk", ENV) == 1


def test_stuck_rows_no_longer_retire_a_script(fresh_db):
    for i in range(5):
        _mk_shadow("blocked", f"0xold{i}", "yes",
                   close_time="2026-07-01T00:00:00Z")
    with db.get_db() as conn:
        assert db.count_open_script_shadow(conn, "blocked", ENV) == 5
        db.resolve_script_shadow(conn, _fee, market_results={}, stale_days=7)
        assert db.count_open_script_shadow(conn, "blocked", ENV) == 0


def test_crypto_shadow_settlement_is_unaffected(fresh_db):
    with db.get_db() as conn:
        db.insert_script_shadow(conn, {
            "script_id": "cy", "source": "crypto", "asset": "BTC",
            "ticker": "0xwin", "side": "up", "contracts": 5,
            "entry_cents": 40, "close_time": "2026-07-27T03:00:00Z",
            "network": ENV,
        })
        conn.execute(
            """INSERT INTO crypto15m_signals
                 (asset, ticker, network, resolved, up_won)
               VALUES ('BTC', '0xwin', ?, 1, 1)""", (ENV,))
        n = db.resolve_script_shadow(conn, _fee)
    assert n == 1
    with db.get_db() as conn:
        r = dict(conn.execute(
            "SELECT * FROM script_shadow_orders WHERE ticker='0xwin'").fetchone())
    assert r["outcome_correct"] == 1 and r["pnl_usd"] > 0


# --- shadow settlement uses the corrected US fee schedule ----------------


def _seed_market_shadow(ticker, created_at, *, side="yes", result="yes",
                        entry_cents=60, contracts=10, asset="sports"):
    with db.get_db() as conn:
        db.insert_script_shadow(conn, {
            "script_id": "s1abc", "source": "signal",
            "signal_source": "market", "signal_id": None,
            "asset": asset, "ticker": ticker, "side": side,
            "contracts": contracts, "entry_cents": entry_cents,
            "order_type": "GTC", "reason": "test", "close_time": "",
            "network": ENV,
        })
        conn.execute(
            "UPDATE script_shadow_orders SET created_at=? WHERE ticker=?",
            (created_at, ticker))
        conn.execute(
            "INSERT INTO markets (ticker, status, result) VALUES (?,?,?)",
            (ticker, "settled", result))


def test_shadow_fee_uses_the_schedule_in_force_when_the_order_was_placed(fresh_db):
    """A July order is charged 0.06; an April order the same size pays 0.05."""
    import backtest as bt
    for created_at, theta in (("2026-05-01 12:00:00", 0.05),
                              ("2026-08-01 12:00:00", 0.06)):
        with db.get_db() as conn:
            conn.execute("DELETE FROM script_shadow_orders")
            conn.execute("DELETE FROM markets")
        _seed_market_shadow("0xsched", created_at, result="no")  # a loss
        asyncio.run(script_engine._settle_shadow_orders())
        row = _shadow_rows()[0]
        expected = 10 * (-0.60 - theta * 0.6 * 0.4)
        assert row["outcome_correct"] == 0
        assert row["pnl_usd"] == pytest.approx(expected, abs=1e-4)
        assert bt.us_fee_per_contract(0.60, bt.epoch_of(created_at)) == \
            pytest.approx(theta * 0.6 * 0.4)


def test_shadow_fee_is_dearer_after_the_july_change(fresh_db):
    _seed_market_shadow("0xapr", "2026-05-01 12:00:00", result="no")
    _seed_market_shadow("0xjul", "2026-08-01 12:00:00", result="no")
    asyncio.run(script_engine._settle_shadow_orders())
    rows = {r["ticker"]: r for r in _shadow_rows()}
    assert rows["0xjul"]["pnl_usd"] < rows["0xapr"]["pnl_usd"]


def test_shadow_fee_no_longer_exempts_geopolitics(fresh_db):
    """The legacy table charged geopolitics nothing; the US schedule is flat."""
    _seed_market_shadow("0xgeo", "2026-08-01 12:00:00",
                        result="no", asset="geopolitics")
    asyncio.run(script_engine._settle_shadow_orders())
    row = _shadow_rows()[0]
    # Strictly worse than the bare -$6.00 stake: a fee was actually charged.
    assert row["pnl_usd"] < -6.0
    assert row["pnl_usd"] == pytest.approx(10 * (-0.60 - 0.06 * 0.6 * 0.4), abs=1e-4)


def test_shadow_fee_does_not_vary_by_category(fresh_db):
    """crypto 0.07 vs sports 0.03 was an international schedule, not a US one."""
    _seed_market_shadow("0xa", "2026-08-01 12:00:00", result="no", asset="crypto")
    _seed_market_shadow("0xb", "2026-08-01 12:00:00", result="no", asset="sports")
    asyncio.run(script_engine._settle_shadow_orders())
    rows = {r["ticker"]: r for r in _shadow_rows()}
    assert rows["0xa"]["pnl_usd"] == pytest.approx(rows["0xb"]["pnl_usd"])


def test_shadow_fee_survives_a_missing_timestamp(fresh_db):
    """Older rows must still settle rather than raising inside the callback."""
    _seed_market_shadow("0xold", "", result="no")
    asyncio.run(script_engine._settle_shadow_orders())
    row = _shadow_rows()[0]
    assert row["resolved"] == 1
    # Priced at the earliest published coefficient, not zero.
    assert row["pnl_usd"] == pytest.approx(10 * (-0.60 - 0.05 * 0.6 * 0.4), abs=1e-4)
