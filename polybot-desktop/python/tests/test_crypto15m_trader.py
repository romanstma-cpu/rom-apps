from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

import crypto15m
import crypto15m_trader as ct
import db
import polymarket_api
import trader
from config import merge_with_defaults


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    dbfile = tmp_path / "c15-test.db"
    monkeypatch.setattr(db, "db_path", lambda: dbfile)
    db.init_db()
    ct._stop_retry_at.clear()
    return dbfile


@pytest.fixture
def env_net(monkeypatch):
    monkeypatch.setattr(trader, "get_env", lambda: "mainnet")
    return "mainnet"


@pytest.fixture
def cfg():
    c = merge_with_defaults({})
    c["network"] = "mainnet"
    c["crypto15m_enabled"] = True
    c["crypto15m_order_size"] = 1
    c["crypto15m_entry_style"] = "taker"
    return c


def run_async(coro):
    return asyncio.run(coro)


def signal_asset(asset="BTC", favorite="up", entry_cost=0.86, signal=True, ticker="KXBTC15M-T1"):
    close = (datetime.now(timezone.utc) + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    up = 0.9 if favorite == "up" else 0.1
    return {
        "asset": asset, "series": f"KX{asset}15M", "spotUsd": 100.0,
        "open15mUsd": 100.0, "deltaUsd": 0.5, "hasMarket": True,
        "ticker": ticker, "closeTime": close, "minsLeft": 5.0,
        "upProb": up, "downProb": 1 - up,
        "favorite": favorite, "favoritePrice": 0.86, "entryCost": entry_cost,
        "yesBid": 0.85, "yesAsk": 0.87,
        "inWindow": True, "signal": signal, "openMarketCount": 1, "error": None,
    }


def _stub_snapshot(assets):
    async def _snap(_cfg):
        return {"assets": assets, "constants": {}, "fetchedAt": "",
                "spotOk": True, "spotSource": "stub"}
    return _snap


def test_direction_for_favorite():
    assert ct.direction_for_favorite("up") == "yes"
    assert ct.direction_for_favorite("down") == "no"


def test_entry_limit_cents_marks_up_and_clamps():
    assert ct.entry_limit_cents(0.86, 0.02) == 88
    assert ct.entry_limit_cents(0.98, 0.02) == 99


def test_side_prob_from_market_respects_direction():
    m = {"yes_bid_dollars": 0.29, "yes_ask_dollars": 0.31}
    assert ct.side_prob_from_market(m, "yes") == pytest.approx(0.30)
    assert ct.side_prob_from_market(m, "no") == pytest.approx(0.70)
    assert ct.side_prob_from_market(None, "yes") is None


def test_should_enter_gate_matrix(cfg):
    a = signal_asset()
    assert ct.should_enter(a, cfg, has_open=False, open_count=0) == (True, "ok")
    assert ct.should_enter(a, cfg, has_open=True, open_count=0)[0] is False
    assert ct.should_enter(a, cfg, has_open=False, open_count=7)[0] is False
    assert ct.should_enter(signal_asset(signal=False), cfg, has_open=False, open_count=0) == (False, "no signal")

    off = dict(cfg)
    off["crypto15m_enabled"] = False
    assert ct.should_enter(a, off, has_open=False, open_count=0) == (False, "disabled")


def test_rsi_gate_is_direction_aware(cfg):
    cfg["crypto15m_min_rsi"] = 55.0
    up = signal_asset(favorite="up")
    assert ct.should_enter(up, cfg, has_open=False, open_count=0)[0] is False
    assert ct.should_enter({**up, "rsi": 50.0}, cfg, has_open=False, open_count=0)[0] is False
    assert ct.should_enter({**up, "rsi": 60.0}, cfg, has_open=False, open_count=0) == (True, "ok")
    dn = signal_asset(favorite="down")
    assert ct.should_enter({**dn, "rsi": 40.0}, cfg, has_open=False, open_count=0) == (True, "ok")
    assert ct.should_enter({**dn, "rsi": 60.0}, cfg, has_open=False, open_count=0)[0] is False
    cfg["crypto15m_min_rsi"] = 0.0
    assert ct.should_enter({**up, "rsi": 5.0}, cfg, has_open=False, open_count=0) == (True, "ok")


def test_macd_gate_is_direction_aware_on_histogram(cfg):
    cfg["crypto15m_min_macd_hist"] = 0.5
    up = signal_asset(favorite="up")
    assert ct.should_enter(up, cfg, has_open=False, open_count=0)[0] is False
    assert ct.should_enter({**up, "macdHist": 0.2}, cfg, has_open=False, open_count=0)[0] is False
    assert ct.should_enter({**up, "macdHist": 1.0}, cfg, has_open=False, open_count=0) == (True, "ok")
    dn = signal_asset(favorite="down")
    assert ct.should_enter({**dn, "macdHist": -1.0}, cfg, has_open=False, open_count=0) == (True, "ok")
    assert ct.should_enter({**dn, "macdHist": -0.2}, cfg, has_open=False, open_count=0)[0] is False


def test_momentum_gate_validation_forces_detector_and_clamps():
    c = merge_with_defaults({
        "crypto15mMinRsi": 150, "crypto15mMinMacdHist": 0.5,
        "crypto15mIndicatorDetect": False,
    })
    assert c["crypto15m_min_rsi"] == 100.0
    assert c["crypto15m_min_macd_hist"] == 0.5
    assert c["crypto15m_indicator_detect"] is True
    from config import C15_RULE_FIELDS
    assert "macdHist" in C15_RULE_FIELDS and "macd" in C15_RULE_FIELDS


def test_evaluate_rules_and_of_conditions():
    a = signal_asset()
    assert ct.evaluate_rules(a, []) == (False, "no entry rules set")
    assert ct.evaluate_rules(a, [{"field": "favoritePrice", "op": ">=", "value": 0.8}])[0] is True
    ok, why = ct.evaluate_rules(a, [{"field": "favoritePrice", "op": ">=", "value": 0.9}])
    assert ok is False and "favoritePrice" in why
    assert ct.evaluate_rules(a, [
        {"field": "favoritePrice", "op": ">=", "value": 0.8},
        {"field": "minsLeft", "op": "<=", "value": 3},
    ])[0] is False
    assert ct.evaluate_rules(a, [
        {"field": "favoritePrice", "op": ">=", "value": 0.8},
        {"field": "minsLeft", "op": "<=", "value": 8},
    ])[0] is True


def test_evaluate_rules_handles_missing_and_malformed():
    a = signal_asset()
    assert ct.evaluate_rules(a, [{"field": "arbEdgeCents", "op": ">=", "value": 2}]) == (
        False, "arbEdgeCents unavailable")
    assert ct.evaluate_rules(a, [
        {"field": "favoritePrice"},
        {"field": "favoritePrice", "op": ">=", "value": 0.8},
    ])[0] is True


def test_should_enter_uses_rules_and_ignores_signal_flag(cfg):
    c = dict(cfg)
    c["crypto15m_use_rules"] = True
    c["crypto15m_rules"] = [{"field": "favoritePrice", "op": ">=", "value": 0.8}]
    a = signal_asset(signal=False)
    assert ct.should_enter(a, c, has_open=False, open_count=0)[0] is True
    nofav = signal_asset(signal=False)
    nofav["favorite"] = None
    assert ct.should_enter(nofav, c, has_open=False, open_count=0) == (False, "no favorite")
    c["crypto15m_rules"] = []
    assert ct.should_enter(a, c, has_open=False, open_count=0) == (False, "no entry rules set")


def test_should_stop_loss(cfg):
    pos = {"status": "filled", "filled_contracts": 1}
    assert ct.should_stop_loss(pos, 0.30, cfg) is True
    assert ct.should_stop_loss(pos, 0.55, cfg) is False
    assert ct.should_stop_loss(pos, None, cfg) is False
    assert ct.should_stop_loss({"status": "submitted", "filled_contracts": 1}, 0.1, cfg) is False


def test_should_stop_loss_pct(cfg):
    pos = {"status": "filled", "filled_contracts": 10, "cost_usd": 8.00}

    cfg["crypto15m_stop_loss_pct"] = 0.0
    assert ct.should_stop_loss(pos, 0.45, cfg) is False

    cfg["crypto15m_stop_loss_pct"] = 0.20
    assert ct.should_stop_loss(pos, 0.65, cfg) is False
    assert ct.should_stop_loss(pos, 0.63, cfg) is True
    assert ct.should_stop_loss(pos, 0.60, cfg) is True

    cfg["crypto15m_stop_loss_pct"] = 0.0
    assert ct.should_stop_loss(pos, 0.30, cfg) is True

    cfg["crypto15m_stop_loss_pct"] = 0.20
    assert ct.should_stop_loss(pos, None, cfg) is False
    assert ct.should_stop_loss(
        {"status": "filled", "filled_contracts": 0, "cost_usd": 8.0}, 0.60, cfg) is False

    assert merge_with_defaults({"crypto15m_stop_loss_pct": 9})["crypto15m_stop_loss_pct"] == 1.0


def test_stop_loss_pct_applies_across_timeframes(cfg):
    pos = {"status": "filled", "filled_contracts": 10, "cost_usd": 8.00}
    cfg["crypto15m_stop_loss_pct"] = 0.20
    for interval in ("5m", "15m", "hourly"):
        cfg["crypto15m_interval"] = interval
        assert ct.should_stop_loss(pos, 0.60, cfg) is True, interval


def test_should_take_profit_pct(cfg):
    pos = {"status": "filled", "filled_contracts": 10, "cost_usd": 5.00}

    cfg["crypto15m_take_profit_pct"] = 0.0
    assert ct.should_take_profit_pct(pos, 70, cfg) is False

    cfg["crypto15m_take_profit_pct"] = 0.20
    assert ct.should_take_profit_pct(pos, 55, cfg) is False
    assert ct.should_take_profit_pct(pos, 60, cfg) is True
    assert ct.should_take_profit_pct(pos, 66, cfg) is True

    assert ct.should_take_profit_pct(pos, None, cfg) is False
    assert ct.should_take_profit_pct(
        {"status": "submitted", "filled_contracts": 10, "cost_usd": 5.0}, 90, cfg) is False
    assert ct.should_take_profit_pct(
        {"status": "filled", "filled_contracts": 0, "cost_usd": 5.0}, 90, cfg) is False
    assert ct.should_take_profit_pct(
        {"status": "filled", "filled_contracts": 10, "cost_usd": 0.0}, 90, cfg) is False

    assert merge_with_defaults({"crypto15m_take_profit_pct": 9})["crypto15m_take_profit_pct"] == 1.0


def test_take_profit_pct_applies_across_timeframes(cfg):
    pos = {"status": "filled", "filled_contracts": 10, "cost_usd": 5.00}
    cfg["crypto15m_take_profit_pct"] = 0.20
    for interval in ("5m", "15m", "hourly"):
        cfg["crypto15m_interval"] = interval
        assert ct.should_take_profit_pct(pos, 66, cfg) is True, interval


def test_directional_rules_pick_side(cfg):
    cfg["crypto15m_use_rules"] = True
    cfg["crypto15m_rules"] = [{"field": "change5mPct", "op": ">", "value": 0.1}]
    cfg["crypto15m_rules_no"] = [{"field": "change5mPct", "op": "<", "value": -0.1}]
    assert ct._is_directional_rules(cfg) is True

    up = {"change5mPct": 0.3}
    down = {"change5mPct": -0.3}
    flat = {"change5mPct": 0.0}
    assert ct._directional_rules_side(up, cfg)[0] == "up"
    assert ct._directional_rules_side(down, cfg)[0] == "down"
    assert ct._directional_rules_side(flat, cfg)[0] is None
    assert ct._entry_side(up, cfg) == "up"
    assert ct._entry_side(down, cfg) == "down"


def test_directional_rules_gate_should_enter(cfg):
    cfg["crypto15m_enabled"] = True
    cfg["crypto15m_use_rules"] = True
    cfg["crypto15m_rules"] = [{"field": "change5mPct", "op": ">", "value": 0.1}]
    cfg["crypto15m_rules_no"] = [{"field": "change5mPct", "op": "<", "value": -0.1}]
    base = {"hasMarket": True, "favorite": "up", "minsLeft": 5.0,
            "upAsk": 0.55, "downAsk": 0.55, "hourUtc": 12}
    ok_up, _ = ct.should_enter({**base, "change5mPct": 0.3}, cfg, has_open=False, open_count=0)
    ok_dn, _ = ct.should_enter({**base, "change5mPct": -0.3}, cfg, has_open=False, open_count=0)
    ok_no, why = ct.should_enter({**base, "change5mPct": 0.0}, cfg, has_open=False, open_count=0)
    assert ok_up is True and ok_dn is True
    assert ok_no is False and "directional" in why


def test_turbine_import_maps_archetypes():
    import turbine_import as ti
    s = {"name": "T", "asset": "BTC", "archetype": "vwap_momentum",
         "indicators": {"lookbackMin": 5, "changePct": 0.1}, "priceBand": [0.25, 0.75], "size": 3}
    cfg = ti.import_strategy(s)
    assert cfg["crypto15m_use_rules"] is True
    assert cfg["crypto15m_assets"] == ["BTC"] and cfg["crypto15m_order_size"] == 3
    fields = {c["field"] for c in cfg["crypto15m_rules"]}
    assert {"priceVsVwapPct", "change5mPct", "upAsk"} <= fields
    assert ti.import_strategy({"archetype": "panic_fade"}) is None
    imp, _ = ti.import_all()
    assert len(imp) >= 25


def test_compute_entry_contracts_fixed(cfg):
    cfg["crypto15m_sizing_mode"] = "fixed"
    cfg["crypto15m_order_size"] = 3
    assert ct.compute_entry_contracts(cfg, entry_limit_cents=88, balance_usd=0, order_size=3) == 3
    assert ct.compute_entry_contracts(cfg, entry_limit_cents=88, balance_usd=1000, order_size=3) == 3


def test_compute_entry_contracts_balance_pct(cfg):
    cfg["crypto15m_sizing_mode"] = "balance_pct"
    cfg["crypto15m_balance_pct"] = 0.10
    assert ct.compute_entry_contracts(cfg, entry_limit_cents=50, balance_usd=100, order_size=1) == 20
    assert ct.compute_entry_contracts(cfg, entry_limit_cents=50, balance_usd=0, order_size=4) == 4


def test_compute_entry_contracts_max_loss_cap(cfg):
    cfg["crypto15m_sizing_mode"] = "fixed"
    cfg["crypto15m_max_loss_pct"] = 0.05
    assert ct.compute_entry_contracts(cfg, entry_limit_cents=50, balance_usd=100, order_size=100) == 10
    assert ct.compute_entry_contracts(cfg, entry_limit_cents=90, balance_usd=10, order_size=5) == 0


def test_compute_entry_contracts_affordability_clamp(cfg):
    cfg["crypto15m_sizing_mode"] = "fixed"
    cfg["crypto15m_max_loss_pct"] = 0.0
    assert ct.compute_entry_contracts(
        cfg, entry_limit_cents=99, balance_usd=11.76, order_size=15) == 2
    assert ct.compute_entry_contracts(
        cfg, entry_limit_cents=95, balance_usd=0.50, order_size=15) == 0
    assert ct.compute_entry_contracts(
        cfg, entry_limit_cents=80, balance_usd=1000, order_size=15) == 15
    assert ct.compute_entry_contracts(
        cfg, entry_limit_cents=99, balance_usd=0, order_size=15) == 15


def _capture_orders(monkeypatch):
    calls = []

    async def _place(**kw):
        calls.append(kw)
        return {"order": {"order_id": "ord-1", "status": "resting"}}

    monkeypatch.setattr(polymarket_api, "place_limit_order", _place)
    return calls


def test_disabled_does_nothing(fresh_db, env_net, cfg, monkeypatch):
    cfg["crypto15m_enabled"] = False
    monkeypatch.setattr(crypto15m, "snapshot", _stub_snapshot([signal_asset()]))
    out = run_async(ct.run_tick(cfg, authed=True))
    assert out == []
    with db.get_db() as conn:
        assert db.count_open_crypto15m(conn, "mainnet") == 0


def test_no_trade_without_auth(fresh_db, env_net, cfg, monkeypatch):
    monkeypatch.setattr(crypto15m, "snapshot", _stub_snapshot([signal_asset()]))
    calls = _capture_orders(monkeypatch)
    out = run_async(ct.run_tick(cfg, authed=False))
    assert out == []
    assert calls == []
    with db.get_db() as conn:
        assert db.count_open_crypto15m(conn, "mainnet") == 0


def test_live_entry_places_real_order(fresh_db, env_net, cfg, monkeypatch):
    monkeypatch.setattr(crypto15m, "snapshot", _stub_snapshot([signal_asset()]))
    calls = _capture_orders(monkeypatch)
    run_async(ct.run_tick(cfg, authed=True))
    assert len(calls) == 1 and calls[0]["action"] == "buy"
    with db.get_db() as conn:
        r = db.get_open_crypto15m(conn, "mainnet")[0]
    assert r["asset"] == "BTC" and r["direction"] == "yes"
    assert r["status"] == "submitted"
    assert r["dry_run"] == 0
    assert r["entry_limit_cents"] == 88
    assert r["order_id"] == "ord-1"


def test_taker_order_type_default_and_toggle():
    assert ct.taker_order_type({}) == "FAK"
    assert ct.taker_order_type({"crypto15m_taker_fak": True}) == "FAK"
    assert ct.taker_order_type({"crypto15m_taker_fak": False}) == "GTC"


def test_taker_entry_uses_fak(fresh_db, env_net, cfg, monkeypatch):
    monkeypatch.setattr(crypto15m, "snapshot", _stub_snapshot([signal_asset()]))
    calls = _capture_orders(monkeypatch)
    run_async(ct.run_tick(cfg, authed=True))
    assert calls and calls[0]["order_type"] == "FAK"


def test_maker_entry_stays_gtc(fresh_db, env_net, cfg, monkeypatch):
    cfg["crypto15m_entry_style"] = "maker"
    monkeypatch.setattr(crypto15m, "snapshot", _stub_snapshot([signal_asset()]))
    calls = _capture_orders(monkeypatch)
    run_async(ct.run_tick(cfg, authed=True))
    assert calls and calls[0]["order_type"] == "GTC"


def test_taker_fak_disabled_reverts_to_gtc(fresh_db, env_net, cfg, monkeypatch):
    cfg["crypto15m_taker_fak"] = False
    monkeypatch.setattr(crypto15m, "snapshot", _stub_snapshot([signal_asset()]))
    calls = _capture_orders(monkeypatch)
    run_async(ct.run_tick(cfg, authed=True))
    assert calls and calls[0]["order_type"] == "GTC"


def test_independent_of_main_bot(fresh_db, env_net, cfg, monkeypatch):
    cfg["enable_trading"] = False
    monkeypatch.setattr(crypto15m, "snapshot", _stub_snapshot([signal_asset()]))
    calls = _capture_orders(monkeypatch)
    run_async(ct.run_tick(cfg, authed=True))
    assert len(calls) == 1
    with db.get_db() as conn:
        assert db.count_open_crypto15m(conn, "mainnet") == 1


def test_one_position_per_asset(fresh_db, env_net, cfg, monkeypatch):
    monkeypatch.setattr(crypto15m, "snapshot", _stub_snapshot([signal_asset()]))
    _capture_orders(monkeypatch)

    async def _open(_ticker):
        return {"yes_bid_dollars": 0.85, "yes_ask_dollars": 0.87, "status": "open", "result": ""}
    monkeypatch.setattr(polymarket_api, "fetch_market", _open)

    run_async(ct.run_tick(cfg, authed=True))
    run_async(ct.run_tick(cfg, authed=True))
    with db.get_db() as conn:
        assert db.count_open_crypto15m(conn, "mainnet") == 1


def test_contrarian_mode_buys_the_underdog(fresh_db, env_net, cfg, monkeypatch):
    cfg["crypto15m_direction_mode"] = "contrarian"
    monkeypatch.setattr(crypto15m, "snapshot", _stub_snapshot([signal_asset(favorite="up")]))
    calls = _capture_orders(monkeypatch)
    run_async(ct.run_tick(cfg, authed=True))
    assert calls[0]["side"] == "no" and calls[0]["price_cents"] == 16
    with db.get_db() as conn:
        r = db.get_open_crypto15m(conn, "mainnet")[0]
    assert r["side"] == "down"
    assert r["direction"] == "no"
    assert r["entry_limit_cents"] == 16


def test_status_reports_enabled_and_authed(fresh_db, env_net, cfg, monkeypatch):
    async def _bal(_cfg, force=False):
        return 10_000, 0
    monkeypatch.setattr(trader, "refresh_balance", _bal)

    st = run_async(ct.status(cfg, authed=True))
    assert st["enabled"] is True
    assert st["trading"] is True
    assert st["authed"] is True

    st = run_async(ct.status(cfg, authed=False))
    assert st["enabled"] is True
    assert st["trading"] is False
    assert st["authed"] is False


def test_failed_entry_resolves_immediately_and_blocks_retry(fresh_db, env_net, cfg, monkeypatch):
    cfg["crypto15m_live"] = True

    async def _paused(**kw):
        raise RuntimeError("HTTP 409: exchange is paused")
    monkeypatch.setattr(polymarket_api, "place_limit_order", _paused)
    monkeypatch.setattr(crypto15m, "snapshot", _stub_snapshot([signal_asset()]))

    run_async(ct.run_tick(cfg, authed=True))
    with db.get_db() as conn:
        assert db.count_open_crypto15m(conn, "mainnet") == 0
        r = dict(conn.execute("SELECT * FROM crypto15m_positions").fetchone())
    assert r["status"] == "error"
    assert r["resolved"] == 1

    run_async(ct.run_tick(cfg, authed=True))
    with db.get_db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM crypto15m_positions").fetchone()[0] == 1

    monkeypatch.setattr(crypto15m, "snapshot", _stub_snapshot([signal_asset(ticker="KXBTC15M-T2")]))
    run_async(ct.run_tick(cfg, authed=True))
    with db.get_db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM crypto15m_positions").fetchone()[0] == 2


def test_exiting_position_settles_when_sell_never_fills(fresh_db, env_net, cfg, monkeypatch):
    pid = _seed_c15(
        asset="BTC", ticker="KXBTC15M-T1", direction="yes",
        status="exiting", filled_contracts=1, cost_usd=0.88,
        entry_limit_cents=88, exit_reason="stop_loss", exit_order_id="ord-x1",
    )["id"]

    canceled = []

    async def _order_unfilled(_kid):
        return {"order": {"fill_count_fp": "0", "remaining_count_fp": "1"}}

    async def _cancel(kid):
        canceled.append(kid)

    async def _settled_no(_ticker):
        return {"result": "no", "status": "finalized"}

    monkeypatch.setattr(polymarket_api, "get_order", _order_unfilled)
    monkeypatch.setattr(polymarket_api, "cancel_order", _cancel)
    monkeypatch.setattr(polymarket_api, "fetch_market", _settled_no)
    monkeypatch.setattr(crypto15m, "snapshot", _stub_snapshot([]))

    run_async(ct.run_tick(cfg, authed=True))
    with db.get_db() as conn:
        assert db.count_open_crypto15m(conn, "mainnet") == 0
        r = dict(conn.execute("SELECT * FROM crypto15m_positions WHERE id=?", (pid,)).fetchone())
    assert r["status"] == "settled"
    assert r["resolved"] == 1
    assert r["exit_reason"] == "stop_loss"
    assert r["outcome_correct"] == 0
    assert r["pnl_usd"] == pytest.approx(-0.88)
    assert canceled == ["ord-x1"]


def test_legacy_stuck_error_row_is_swept(fresh_db, env_net, cfg, monkeypatch):
    with db.get_db() as conn:
        pid = db.insert_crypto15m_position(conn, {
            "asset": "BNB", "series": "KXBNB15M", "ticker": "KXBNB15M-OLD",
            "side": "up", "direction": "yes", "target_contracts": 12,
            "entry_limit_cents": 90, "client_order_id": "c1",
            "close_time": "2026-06-10T15:15:00Z", "confidence": 90,
            "network": "mainnet", "status": "error", "dry_run": False,
        })
    monkeypatch.setattr(crypto15m, "snapshot", _stub_snapshot([]))
    run_async(ct.run_tick(cfg, authed=True))
    with db.get_db() as conn:
        r = dict(conn.execute("SELECT * FROM crypto15m_positions WHERE id=?", (pid,)).fetchone())
    assert r["resolved"] == 1
    assert r["status"] == "error"


def test_maker_limit_cents_joins_the_bid():
    assert ct.maker_limit_cents("up", 0.85, 0.87, 0.87) == 85
    assert ct.maker_limit_cents("down", 0.85, 0.87, 0.15) == 13
    assert ct.maker_limit_cents("up", None, None, 0.87) == 86
    assert ct.maker_limit_cents("up", None, None, 0.01) == 1


def test_live_maker_escalates_to_taker(fresh_db, env_net, cfg, monkeypatch):
    cfg["crypto15m_entry_style"] = "maker"
    cfg["crypto15m_entry_threshold"] = 0.5
    cfg["crypto15m_maker_cancel_min"] = 15.0
    cfg["crypto15m_maker_escalate"] = True
    close = (datetime.now(timezone.utc) + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    _seed_c15(asset="BTC", ticker="KXBTC15M-L1", status="submitted", dry_run=False,
              target_contracts=2, entry_limit_cents=85, close_time=close, order_id="maker-1")

    state = {"canceled": False}

    async def _get_order(oid):
        if oid == "maker-1":
            if state["canceled"]:
                return _order(0, 0, 0.0, status="canceled")
            return _order(0, 2, 0.0, status="resting")
        return _order(2, 0, 1.76, status="executed")

    async def _quote(_ticker, _side):
        return {"bid_cents": 86, "ask_cents": 88}

    async def _cancel(_oid):
        state["canceled"] = True
        return {"ok": True}

    place_calls = []

    async def _place(**kw):
        place_calls.append(kw)
        return {"order": {"order_id": "taker-1", "status": "executed"}}

    monkeypatch.setattr(polymarket_api, "get_order", _get_order)
    monkeypatch.setattr(polymarket_api, "get_quote", _quote)
    monkeypatch.setattr(polymarket_api, "cancel_order", _cancel)
    monkeypatch.setattr(polymarket_api, "place_limit_order", _place)
    monkeypatch.setattr(crypto15m, "snapshot", _stub_snapshot([]))

    run_async(ct.run_tick(cfg, authed=True))
    assert len(place_calls) == 1
    assert place_calls[0]["price_cents"] == 88 and place_calls[0]["count"] == 2
    with db.get_db() as conn:
        r = dict(conn.execute("SELECT * FROM crypto15m_positions WHERE asset='BTC'").fetchone())
    assert r["status"] == "filled" and r["resolved"] == 0
    assert r["filled_contracts"] == 2
    assert r["cost_usd"] == pytest.approx(1.76)


def test_live_fast_escalate_before_cancel_lead(fresh_db, env_net, cfg, monkeypatch):
    cfg["crypto15m_entry_style"] = "maker"
    cfg["crypto15m_live"] = True
    cfg["crypto15m_maker_cancel_min"] = 1.0
    cfg["crypto15m_maker_escalate"] = True
    cfg["crypto15m_maker_fill_sec"] = 20.0
    cfg["crypto15m_entry_threshold"] = 0.5
    cfg["crypto15m_entry_max"] = 0.93
    close = (datetime.now(timezone.utc) + timedelta(minutes=14)).strftime("%Y-%m-%dT%H:%M:%SZ")
    _seed_c15(asset="BTC", ticker="KXBTC15M-FAST", status="submitted", dry_run=False,
              target_contracts=2, entry_limit_cents=78, close_time=close, order_id="maker-2")
    with db.get_db() as conn:
        conn.execute(
            "UPDATE crypto15m_positions SET created_at=datetime('now','-60 seconds') WHERE ticker=?",
            ("KXBTC15M-FAST",))

    state = {"canceled": False}

    async def _get_order(oid):
        if oid == "maker-2":
            if state["canceled"]:
                return _order(0, 0, 0.0, status="canceled")
            return _order(0, 2, 0.0, status="resting")
        return _order(2, 0, 1.60, status="executed")

    async def _quote(_ticker, _side):
        return {"bid_cents": 78, "ask_cents": 80}

    async def _cancel(_oid):
        state["canceled"] = True
        return {"ok": True}

    place_calls = []

    async def _place(**kw):
        place_calls.append(kw)
        return {"order": {"order_id": "taker-2", "status": "executed"}}

    monkeypatch.setattr(polymarket_api, "get_order", _get_order)
    monkeypatch.setattr(polymarket_api, "get_quote", _quote)
    monkeypatch.setattr(polymarket_api, "cancel_order", _cancel)
    monkeypatch.setattr(polymarket_api, "place_limit_order", _place)
    monkeypatch.setattr(crypto15m, "snapshot", _stub_snapshot([]))

    run_async(ct.run_tick(cfg, authed=True))
    assert len(place_calls) == 1
    assert place_calls[0]["price_cents"] == 80 and place_calls[0]["count"] == 2
    with db.get_db() as conn:
        r = dict(conn.execute("SELECT * FROM crypto15m_positions WHERE asset='BTC'").fetchone())
    assert r["status"] == "filled" and r["resolved"] == 0
    assert r["filled_contracts"] == 2
    assert r["cost_usd"] == pytest.approx(1.60)


def test_live_escalate_404_books_as_filled_not_stranded(fresh_db, env_net, cfg, monkeypatch):
    cfg["crypto15m_entry_style"] = "maker"
    cfg["crypto15m_live"] = True
    cfg["crypto15m_entry_threshold"] = 0.5
    cfg["crypto15m_maker_cancel_min"] = 15.0
    cfg["crypto15m_maker_escalate"] = True
    cfg["crypto15m_entry_max"] = 0.95
    close = (datetime.now(timezone.utc) + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    _seed_c15(asset="BTC", ticker="KXBTC15M-404", status="submitted", dry_run=False,
              target_contracts=10, entry_limit_cents=80, close_time=close, order_id="maker-x")

    state = {"canceled": False}

    async def _get_order(oid):
        if oid == "maker-x":
            if state["canceled"]:
                return _order(0, 0, 0.0, status="canceled")
            return _order(0, 10, 0.0, status="resting")
        raise polymarket_api.PolymarketAPIError(404, "not found")

    async def _quote(_t, _s):
        return {"bid_cents": 86, "ask_cents": 88}

    async def _cancel(_o):
        state["canceled"] = True
        return {"ok": True}

    async def _place(**kw):
        return {"order": {"order_id": "taker-x", "status": "live"}}

    monkeypatch.setattr(polymarket_api, "get_order", _get_order)
    monkeypatch.setattr(polymarket_api, "get_quote", _quote)
    monkeypatch.setattr(polymarket_api, "cancel_order", _cancel)
    monkeypatch.setattr(polymarket_api, "place_limit_order", _place)
    monkeypatch.setattr(crypto15m, "snapshot", _stub_snapshot([]))

    run_async(ct.run_tick(cfg, authed=True))
    with db.get_db() as conn:
        r = dict(conn.execute("SELECT * FROM crypto15m_positions WHERE asset='BTC'").fetchone())
    assert r["status"] == "filled" and r["resolved"] == 0
    assert r["filled_contracts"] == 10
    assert r["cost_usd"] == pytest.approx(8.80)


def test_maker_full_fill_404_does_not_double_buy(fresh_db, env_net, cfg, monkeypatch):
    cfg["crypto15m_entry_style"] = "maker"
    cfg["crypto15m_maker_cancel_min"] = 15.0
    cfg["crypto15m_maker_escalate"] = True
    cfg["crypto15m_maker_fill_sec"] = 1.0
    close = (datetime.now(timezone.utc) + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    _seed_c15(asset="BTC", ticker="KXBTC15M-FF", status="submitted", dry_run=False,
              target_contracts=10, entry_limit_cents=80, close_time=close, order_id="maker-ff")
    with db.get_db() as conn:
        conn.execute("UPDATE crypto15m_positions SET created_at=datetime('now','-60 seconds') WHERE ticker=?",
                     ("KXBTC15M-FF",))

    async def _get_order(_oid):
        raise polymarket_api.PolymarketAPIError(404, "fully matched")

    async def _positions(limit=500, user=None, **kw):
        return [{"ticker": "KXBTC15M-FF", "position_fp": 10.0, "market_exposure_dollars": 8.0}]

    place_calls = []

    async def _place(**kw):
        place_calls.append(kw)
        return {"order": {"order_id": "x", "status": "live"}}

    monkeypatch.setattr(polymarket_api, "get_order", _get_order)
    monkeypatch.setattr(polymarket_api, "get_positions", _positions)
    monkeypatch.setattr(polymarket_api, "place_limit_order", _place)
    monkeypatch.setattr(crypto15m, "snapshot", _stub_snapshot([]))

    run_async(ct.run_tick(cfg, authed=True))
    assert place_calls == []
    with db.get_db() as conn:
        r = dict(conn.execute("SELECT * FROM crypto15m_positions WHERE asset='BTC'").fetchone())
    assert r["status"] == "filled" and r["resolved"] == 0
    assert r["filled_contracts"] == 10
    assert r["cost_usd"] == pytest.approx(8.0)


def test_entry_404_with_no_holding_marks_unfilled_not_phantom(fresh_db, env_net, cfg, monkeypatch):
    cfg["crypto15m_entry_style"] = "maker"
    cfg["crypto15m_maker_cancel_min"] = 15.0
    cfg["crypto15m_maker_escalate"] = False
    close = (datetime.now(timezone.utc) + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    _seed_c15(asset="BTC", ticker="KXBTC15M-NF", status="submitted", dry_run=False,
              target_contracts=10, entry_limit_cents=80, close_time=close, order_id="maker-nf")

    async def _get_order(_oid):
        raise polymarket_api.PolymarketAPIError(404, "not found")

    async def _positions(limit=500, user=None, **kw):
        return []

    place_calls = []

    async def _place(**kw):
        place_calls.append(kw)
        return {"order": {"order_id": "x", "status": "live"}}

    monkeypatch.setattr(polymarket_api, "get_order", _get_order)
    monkeypatch.setattr(polymarket_api, "get_positions", _positions)
    monkeypatch.setattr(polymarket_api, "place_limit_order", _place)
    monkeypatch.setattr(crypto15m, "snapshot", _stub_snapshot([]))

    run_async(ct.run_tick(cfg, authed=True))
    assert place_calls == []
    with db.get_db() as conn:
        r = dict(conn.execute("SELECT * FROM crypto15m_positions WHERE asset='BTC'").fetchone())
    assert r["status"] == "canceled" and r["resolved"] == 1
    assert int(r["filled_contracts"] or 0) == 0
    assert r["pnl_usd"] is None
    assert r["exit_reason"] == "unfilled_expired"


def test_escalate_respects_onchain_holding(fresh_db, env_net, cfg, monkeypatch):
    cfg["crypto15m_entry_style"] = "maker"
    cfg["crypto15m_maker_cancel_min"] = 15.0
    cfg["crypto15m_maker_escalate"] = True
    cfg["crypto15m_maker_fill_sec"] = 1.0
    close = (datetime.now(timezone.utc) + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    _seed_c15(asset="BTC", ticker="KXBTC15M-RACE", status="submitted", dry_run=False,
              target_contracts=10, entry_limit_cents=80, close_time=close, order_id="maker-r")
    with db.get_db() as conn:
        conn.execute("UPDATE crypto15m_positions SET created_at=datetime('now','-60 seconds') WHERE ticker=?",
                     ("KXBTC15M-RACE",))

    async def _get_order(_oid):
        return _order(0, 10, 0.0, status="resting")

    async def _cancel(_o):
        return {"ok": True}

    async def _positions(limit=500, user=None, **kw):
        return [{"ticker": "KXBTC15M-RACE", "position_fp": 10.0, "market_exposure_dollars": 8.0}]

    place_calls = []

    async def _place(**kw):
        place_calls.append(kw)
        return {"order": {"order_id": "t", "status": "live"}}

    async def _quote(_t, _s):
        return {"bid_cents": 86, "ask_cents": 88}

    monkeypatch.setattr(polymarket_api, "get_order", _get_order)
    monkeypatch.setattr(polymarket_api, "cancel_order", _cancel)
    monkeypatch.setattr(polymarket_api, "get_positions", _positions)
    monkeypatch.setattr(polymarket_api, "place_limit_order", _place)
    monkeypatch.setattr(polymarket_api, "get_quote", _quote)
    monkeypatch.setattr(crypto15m, "snapshot", _stub_snapshot([]))

    run_async(ct.run_tick(cfg, authed=True))
    assert place_calls == []
    with db.get_db() as conn:
        r = dict(conn.execute("SELECT * FROM crypto15m_positions WHERE asset='BTC'").fetchone())
    assert r["status"] == "filled"
    assert r["filled_contracts"] == 10
    assert r["cost_usd"] == pytest.approx(8.0)


def test_escalate_defers_when_cancel_unconfirmed(fresh_db, env_net, cfg, monkeypatch):
    cfg["crypto15m_entry_style"] = "maker"
    cfg["crypto15m_maker_cancel_min"] = 15.0
    cfg["crypto15m_maker_escalate"] = True
    cfg["crypto15m_maker_fill_sec"] = 1.0
    close = (datetime.now(timezone.utc) + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    _seed_c15(asset="BTC", ticker="KXBTC15M-STUCK", status="submitted", dry_run=False,
              target_contracts=10, entry_limit_cents=80, close_time=close, order_id="maker-s")
    with db.get_db() as conn:
        conn.execute("UPDATE crypto15m_positions SET created_at=datetime('now','-60 seconds') WHERE ticker=?",
                     ("KXBTC15M-STUCK",))

    async def _get_order(_oid):
        return _order(0, 10, 0.0, status="resting")

    async def _cancel(_o):
        return {"ok": False}

    async def _positions(limit=500, user=None, **kw):
        return []

    place_calls = []

    async def _place(**kw):
        place_calls.append(kw)
        return {"order": {"order_id": "t", "status": "live"}}

    async def _quote(_t, _s):
        return {"bid_cents": 78, "ask_cents": 80}

    monkeypatch.setattr(polymarket_api, "get_order", _get_order)
    monkeypatch.setattr(polymarket_api, "cancel_order", _cancel)
    monkeypatch.setattr(polymarket_api, "get_positions", _positions)
    monkeypatch.setattr(polymarket_api, "place_limit_order", _place)
    monkeypatch.setattr(polymarket_api, "get_quote", _quote)
    monkeypatch.setattr(crypto15m, "snapshot", _stub_snapshot([]))

    run_async(ct.run_tick(cfg, authed=True))
    assert place_calls == []
    with db.get_db() as conn:
        r = dict(conn.execute("SELECT * FROM crypto15m_positions WHERE asset='BTC'").fetchone())
    assert r["status"] == "submitted" and r["resolved"] == 0


def test_rules_still_respect_trading_hours(cfg, monkeypatch):
    cfg["crypto15m_use_rules"] = True
    cfg["crypto15m_rules"] = []
    monkeypatch.setattr(crypto15m, "hours_ok", lambda _cfg, hour=None: False)
    ok, why = ct.should_enter(signal_asset(), cfg, has_open=False, open_count=0)
    assert ok is False and "hours" in why


def test_no_maker_entry_inside_cancel_lead(cfg):
    cfg["crypto15m_entry_style"] = "maker"
    cfg["crypto15m_maker_cancel_min"] = 6.0
    a = signal_asset()
    ok, why = ct.should_enter(a, cfg, has_open=False, open_count=0)
    assert ok is False and "cancel lead" in why
    cfg["crypto15m_entry_style"] = "taker"
    assert ct.should_enter(a, cfg, has_open=False, open_count=0)[0] is True
    cfg["crypto15m_entry_style"] = "maker"
    cfg["crypto15m_maker_cancel_min"] = 1.0
    assert ct.should_enter(a, cfg, has_open=False, open_count=0)[0] is True


def test_no_reentry_on_already_attempted_market(fresh_db, env_net, cfg, monkeypatch):
    cfg["crypto15m_entry_style"] = "taker"
    seeded = _seed_c15(asset="BTC", ticker="KXBTC15M-W1", status="canceled",
                       exit_reason="unfilled_expired", dry_run=True)
    with db.get_db() as conn:
        db.update_crypto15m_position(conn, seeded["id"], resolved=1)
        assert "KXBTC15M-W1" in db.crypto15m_attempted_tickers(conn, "mainnet")
    monkeypatch.setattr(crypto15m, "snapshot",
                        _stub_snapshot([signal_asset(ticker="KXBTC15M-W1")]))
    run_async(ct.run_tick(cfg, authed=False))
    with db.get_db() as conn:
        n = conn.execute(
            "SELECT COUNT(*) c FROM crypto15m_positions WHERE ticker='KXBTC15M-W1'"
        ).fetchone()["c"]
    assert n == 1


def test_attempted_tickers_age_capped(fresh_db):
    old = _seed_c15(ticker="KXBTC15M-OLD", status="canceled", dry_run=True)
    _seed_c15(asset="ETH", series="KXETH15M", ticker="KXETH15M-NEW",
              status="canceled", dry_run=True)
    with db.get_db() as conn:
        conn.execute(
            "UPDATE crypto15m_positions SET created_at=datetime('now','-7 hours') WHERE id=?",
            (old["id"],),
        )
        got = db.crypto15m_attempted_tickers(conn, "mainnet")
    assert "KXETH15M-NEW" in got
    assert "KXBTC15M-OLD" not in got


def test_stop_loss_retry_throttled(fresh_db, env_net, cfg, monkeypatch):
    pos = {"id": 777, "ticker": "KXBTC15M-SL", "direction": "yes", "asset": "BTC",
           "status": "filled", "filled_contracts": 10, "cost_usd": 8.0, "dry_run": 0}

    async def _mkt(_ticker):
        return {"yes_bid_dollars": 0.28, "yes_ask_dollars": 0.32, "status": "open", "result": ""}
    monkeypatch.setattr(polymarket_api, "fetch_market", _mkt)

    async def _no_chain(_pos):
        return None
    monkeypatch.setattr(ct, "_resolved_payout_from_chain", _no_chain)

    async def _no_bid(_ticker, _direction):
        return None
    monkeypatch.setattr(ct, "_best_bid_cents", _no_bid)

    calls = []

    async def _fake_stop(p, market, c):
        calls.append(p["id"])
        return None
    monkeypatch.setattr(ct, "_place_stop_loss", _fake_stop)

    run_async(ct._manage_position(pos, cfg, "mainnet"))
    assert calls == [777]
    run_async(ct._manage_position(pos, cfg, "mainnet"))
    assert calls == [777]
    ct._stop_retry_at[777] -= ct._STOP_RETRY_SEC + 1
    run_async(ct._manage_position(pos, cfg, "mainnet"))
    assert calls == [777, 777]


def test_live_maker_entry_places_resting_order_at_bid(fresh_db, env_net, cfg, monkeypatch):
    cfg["crypto15m_entry_style"] = "maker"
    cfg["crypto15m_live"] = True
    monkeypatch.setattr(crypto15m, "snapshot", _stub_snapshot([signal_asset()]))
    calls = _capture_orders(monkeypatch)

    run_async(ct.run_tick(cfg, authed=True))

    assert len(calls) == 1
    assert calls[0]["price_cents"] == 85
    assert calls[0]["action"] == "buy"


def test_live_entry_skips_when_real_ask_above_cap(fresh_db, env_net, cfg, monkeypatch):
    cfg["crypto15m_entry_style"] = "maker"
    cfg["crypto15m_live"] = True
    cfg["crypto15m_entry_max"] = 0.95
    monkeypatch.setattr(crypto15m, "snapshot", _stub_snapshot([signal_asset()]))
    calls = _capture_orders(monkeypatch)

    async def _hot(_t, _s):
        return {"bid_cents": 95, "ask_cents": 97}

    monkeypatch.setattr(polymarket_api, "get_quote", _hot)
    run_async(ct.run_tick(cfg, authed=True))

    assert len(calls) == 0
    with db.get_db() as conn:
        r = dict(conn.execute("SELECT * FROM crypto15m_positions WHERE asset='BTC'").fetchone())
    assert r["status"] == "canceled" and r["resolved"] == 1
    assert r["exit_reason"] == "above_cap"


def test_live_maker_entry_skips_when_real_bid_above_cap_no_ask(fresh_db, env_net, cfg, monkeypatch):
    cfg["crypto15m_entry_style"] = "maker"
    cfg["crypto15m_live"] = True
    cfg["crypto15m_entry_max"] = 0.95
    monkeypatch.setattr(crypto15m, "snapshot", _stub_snapshot([signal_asset()]))
    calls = _capture_orders(monkeypatch)

    async def _one_sided(_t, _s):
        return {"bid_cents": 97, "ask_cents": None}

    monkeypatch.setattr(polymarket_api, "get_quote", _one_sided)
    run_async(ct.run_tick(cfg, authed=True))

    assert len(calls) == 0
    with db.get_db() as conn:
        r = dict(conn.execute("SELECT * FROM crypto15m_positions WHERE asset='BTC'").fetchone())
    assert r["status"] == "canceled" and r["resolved"] == 1
    assert r["exit_reason"] == "above_cap"


def test_live_maker_entry_places_when_real_bid_within_cap(fresh_db, env_net, cfg, monkeypatch):
    cfg["crypto15m_entry_style"] = "maker"
    cfg["crypto15m_live"] = True
    cfg["crypto15m_entry_max"] = 0.95
    monkeypatch.setattr(crypto15m, "snapshot", _stub_snapshot([signal_asset()]))
    calls = _capture_orders(monkeypatch)

    async def _at_cap(_t, _s):
        return {"bid_cents": 95, "ask_cents": None}

    monkeypatch.setattr(polymarket_api, "get_quote", _at_cap)
    run_async(ct.run_tick(cfg, authed=True))

    assert len(calls) == 1
    assert calls[0]["price_cents"] == 95


def test_favorite_floor_skips_crashed_favorite(fresh_db, env_net, cfg, monkeypatch):
    cfg["crypto15m_entry_style"] = "maker"
    cfg["crypto15m_live"] = True
    cfg["crypto15m_direction_mode"] = "favorite"
    cfg["crypto15m_entry_threshold"] = 0.60
    cfg["crypto15m_entry_max"] = 0.98
    monkeypatch.setattr(crypto15m, "snapshot", _stub_snapshot([signal_asset(favorite="up")]))
    calls = _capture_orders(monkeypatch)

    async def _crashed(_t, _s):
        return {"bid_cents": 4, "ask_cents": 6}

    monkeypatch.setattr(polymarket_api, "get_quote", _crashed)
    run_async(ct.run_tick(cfg, authed=True))

    assert calls == []
    with db.get_db() as conn:
        r = dict(conn.execute("SELECT * FROM crypto15m_positions WHERE asset='BTC'").fetchone())
    assert r["status"] == "canceled" and r["resolved"] == 1
    assert r["exit_reason"] == "favorite_flipped"


def test_favorite_floor_exempts_contrarian(fresh_db, env_net, cfg, monkeypatch):
    cfg["crypto15m_entry_style"] = "maker"
    cfg["crypto15m_live"] = True
    cfg["crypto15m_direction_mode"] = "contrarian"
    cfg["crypto15m_entry_threshold"] = 0.60
    cfg["crypto15m_entry_max"] = 0.98
    monkeypatch.setattr(crypto15m, "snapshot", _stub_snapshot([signal_asset(favorite="up")]))
    calls = _capture_orders(monkeypatch)

    async def _cheap(_t, _s):
        return {"bid_cents": 5, "ask_cents": 7}

    monkeypatch.setattr(polymarket_api, "get_quote", _cheap)
    run_async(ct.run_tick(cfg, authed=True))

    assert len(calls) == 1
    assert calls[0]["side"] == "no"


def test_escalate_skips_when_favorite_crashed(fresh_db, env_net, cfg, monkeypatch):
    cfg["crypto15m_entry_style"] = "maker"
    cfg["crypto15m_live"] = True
    cfg["crypto15m_direction_mode"] = "favorite"
    cfg["crypto15m_entry_threshold"] = 0.60
    cfg["crypto15m_maker_cancel_min"] = 15.0
    cfg["crypto15m_maker_escalate"] = True
    close = (datetime.now(timezone.utc) + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    _seed_c15(asset="BTC", ticker="KXBTC15M-CR", status="submitted", dry_run=False,
              target_contracts=10, entry_limit_cents=70, close_time=close, order_id="maker-cr")

    state = {"canceled": False}

    async def _get_order(_oid):
        return _order(0, 0, 0.0, status="canceled") if state["canceled"] \
            else _order(0, 10, 0.0, status="resting")

    async def _cancel(_o):
        state["canceled"] = True
        return {"ok": True}

    async def _positions(limit=500, user=None, **kw):
        return []

    async def _quote(_t, _s):
        return {"bid_cents": 4, "ask_cents": 6}

    place_calls = []

    async def _place(**kw):
        place_calls.append(kw)
        return {"order": {"order_id": "t"}}

    monkeypatch.setattr(polymarket_api, "get_order", _get_order)
    monkeypatch.setattr(polymarket_api, "cancel_order", _cancel)
    monkeypatch.setattr(polymarket_api, "get_positions", _positions)
    monkeypatch.setattr(polymarket_api, "get_quote", _quote)
    monkeypatch.setattr(polymarket_api, "place_limit_order", _place)
    monkeypatch.setattr(crypto15m, "snapshot", _stub_snapshot([]))

    run_async(ct.run_tick(cfg, authed=True))
    assert place_calls == []
    with db.get_db() as conn:
        r = dict(conn.execute("SELECT * FROM crypto15m_positions WHERE asset='BTC'").fetchone())
    assert r["status"] == "canceled" and r["resolved"] == 1
    assert r["exit_reason"] == "unfilled_expired"


def test_live_entries_never_oversubscribe_the_balance(fresh_db, env_net, cfg, monkeypatch):
    cfg["crypto15m_entry_style"] = "maker"
    cfg["crypto15m_live"] = True
    cfg["crypto15m_sizing_mode"] = "fixed"
    cfg["crypto15m_order_size"] = 15
    cfg["crypto15m_max_loss_pct"] = 0.0

    async def _bal(_cfg, force=False):
        return 6000, 0
    monkeypatch.setattr(trader, "refresh_balance", _bal)

    monkeypatch.setattr(crypto15m, "snapshot", _stub_snapshot([
        signal_asset(asset="BTC", ticker="KXBTC15M-T1"),
        signal_asset(asset="ETH", ticker="KXETH15M-T1"),
    ]))
    calls = _capture_orders(monkeypatch)

    run_async(ct.run_tick(cfg, authed=True))

    assert calls, "expected at least one entry"
    assert calls[0]["count"] < 15
    committed = sum(c["count"] * c["price_cents"] / 100.0 for c in calls)
    assert committed <= 60.0 + 1e-6
    if len(calls) == 2:
        assert calls[1]["count"] <= calls[0]["count"]


_c15_seq = 0


def _seed_c15(**over) -> dict:
    global _c15_seq
    _c15_seq += 1
    n = _c15_seq
    row = {
        "asset": over.get("asset", "BTC"),
        "series": over.get("series", "KXBTC15M"),
        "ticker": over.get("ticker", f"KXBTC15M-T{n}"),
        "side": over.get("side", "up"),
        "direction": over.get("direction", "yes"),
        "target_contracts": over.get("target_contracts", 10),
        "filled_contracts": over.get("filled_contracts", 0),
        "cost_usd": over.get("cost_usd", 0.0),
        "entry_limit_cents": over.get("entry_limit_cents", 88),
        "client_order_id": f"co-{n}",
        "order_id": over.get("order_id"),
        "status": over.get("status", "submitted"),
        "exit_reason": over.get("exit_reason"),
        "close_time": over.get("close_time", ""),
        "network": over.get("network", "mainnet"),
        "dry_run": over.get("dry_run", False),
    }
    post = {k: over[k] for k in
            ("exit_order_id", "exit_filled_contracts", "proceeds_usd",
             "avg_entry_cents", "exit_limit_cents")
            if k in over}
    with db.get_db() as conn:
        pid = db.insert_crypto15m_position(conn, row)
        if post:
            db.update_crypto15m_position(conn, pid, **post)
        return db.fetch_crypto15m_by_id(conn, pid)


def _order(filled, remaining, cost_dollars, status="resting") -> dict:
    f = float(filled)
    price = (float(cost_dollars) / f) if f else 0.0
    clob_status = {"resting": "LIVE", "executed": "MATCHED"}.get(status, status)
    return {"order": {
        "size_matched": str(filled),
        "original_size": str(int(filled) + int(remaining)),
        "price": f"{price:.6f}",
        "status": clob_status,
    }}


def _future():
    return (datetime.now(timezone.utc) + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _past():
    return (datetime.now(timezone.utc) - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_partial_entry_keeps_polling_then_completes(fresh_db, env_net, cfg, monkeypatch):
    pos = _seed_c15(status="submitted", order_id="OID-E",
                    target_contracts=10, filled_contracts=0, close_time=_future())

    async def _get3(_kid):
        return _order(3, 7, 2.64)
    monkeypatch.setattr(polymarket_api, "get_order", _get3)

    out = run_async(ct._poll_entry(pos, cfg))
    assert out is None
    with db.get_db() as conn:
        r = db.fetch_crypto15m_by_id(conn, pos["id"])
    assert r["status"] == "submitted" and r["resolved"] == 0
    assert r["filled_contracts"] == 3
    assert r["cost_usd"] == pytest.approx(2.64)

    async def _get10(_kid):
        return _order(10, 0, 8.80, status="executed")
    monkeypatch.setattr(polymarket_api, "get_order", _get10)
    with db.get_db() as conn:
        r = db.fetch_crypto15m_by_id(conn, pos["id"])
    out = run_async(ct._poll_entry(r, cfg))
    assert out["status"] == "filled"
    assert out["filled_contracts"] == 10
    assert out["cost_usd"] == pytest.approx(8.80)


def test_partial_entry_then_expiry_keeps_filled_portion(fresh_db, env_net, cfg, monkeypatch):
    pos = _seed_c15(status="submitted", order_id="OID-E", target_contracts=10,
                    filled_contracts=3, cost_usd=2.64, close_time=_past())
    canceled = {"v": False}

    async def _cancel(_kid):
        canceled["v"] = True

    async def _get(_kid):
        return _order(3, 7, 2.64)
    monkeypatch.setattr(polymarket_api, "cancel_order", _cancel)
    monkeypatch.setattr(polymarket_api, "get_order", _get)

    out = run_async(ct._poll_entry(pos, cfg))
    assert canceled["v"] is True
    assert out["status"] == "filled"
    assert out["filled_contracts"] == 3
    assert out["resolved"] == 0
    assert out["exit_reason"] is None


def test_unfilled_entry_then_expiry_still_cancels(fresh_db, env_net, cfg, monkeypatch):
    pos = _seed_c15(status="submitted", order_id="OID-E",
                    target_contracts=10, filled_contracts=0, close_time=_past())

    async def _cancel(_kid):
        pass

    async def _get(_kid):
        return _order(0, 10, 0)
    monkeypatch.setattr(polymarket_api, "cancel_order", _cancel)
    monkeypatch.setattr(polymarket_api, "get_order", _get)

    out = run_async(ct._poll_entry(pos, cfg))
    assert out["status"] == "canceled"
    assert out["resolved"] == 1
    assert out["exit_reason"] == "unfilled_expired"


def test_exit_404_books_sale_not_settle_as_held(fresh_db, env_net, cfg, monkeypatch):
    pos = _seed_c15(status="exiting", direction="yes", target_contracts=10,
                    filled_contracts=10, cost_usd=8.00, exit_reason="stop_loss",
                    exit_order_id="OID-X", exit_limit_cents=20, exit_filled_contracts=0)

    async def _boom(_kid):
        raise polymarket_api.PolymarketAPIError(404, "order not found (fully matched)")

    async def _no_positions(*a, **k):
        return []

    monkeypatch.setattr(polymarket_api, "get_order", _boom)
    monkeypatch.setattr(polymarket_api, "get_positions", _no_positions)

    out = run_async(ct._poll_exit(pos))
    assert out is not None and out["status"] == "exited"
    assert out["exit_filled_contracts"] == 10
    assert out["proceeds_usd"] == pytest.approx(2.0)
    assert out["pnl_usd"] == pytest.approx(-6.0 - 0.112)
    assert out["outcome_correct"] == 0


def test_partial_stop_loss_sell_stays_exiting(fresh_db, env_net, cfg, monkeypatch):
    pos = _seed_c15(status="exiting", direction="yes", target_contracts=10,
                    filled_contracts=10, cost_usd=8.80,
                    exit_order_id="OID-X", exit_filled_contracts=0)

    async def _get(_kid):
        return _order(3, 7, 0.93)
    monkeypatch.setattr(polymarket_api, "get_order", _get)

    out = run_async(ct._poll_exit(pos))
    assert out is None
    with db.get_db() as conn:
        r = db.fetch_crypto15m_by_id(conn, pos["id"])
    assert r["status"] == "exiting" and r["resolved"] == 0
    assert r["exit_filled_contracts"] == 3
    assert r["proceeds_usd"] == pytest.approx(0.93)


def test_partial_stop_then_settlement_accounts_for_sold_portion(fresh_db, env_net, cfg, monkeypatch):
    pos = _seed_c15(status="exiting", direction="yes", target_contracts=10,
                    filled_contracts=10, cost_usd=8.80, exit_reason="stop_loss",
                    exit_order_id="OID-X", exit_filled_contracts=3, proceeds_usd=0.93)

    async def _settled(_ticker):
        return {"result": "yes", "status": "finalized"}
    monkeypatch.setattr(polymarket_api, "fetch_market", _settled)

    out = run_async(ct._settle_if_closed(pos))
    assert out["status"] == "settled" and out["resolved"] == 1
    assert out["settlement_usd"] == pytest.approx(7.0)
    assert out["pnl_usd"] == pytest.approx(0.93 + 7.0 - 8.80 - 0.044919)
    assert out["outcome_correct"] == 1


def test_hours_ok_default_is_always_on(cfg):
    for h in range(24):
        assert crypto15m.hours_ok(cfg, hour=h) is True


def test_hours_ok_simple_window(cfg):
    cfg["crypto15m_hours_start_utc"] = 6
    cfg["crypto15m_hours_end_utc"] = 12
    assert crypto15m.hours_ok(cfg, hour=6) is True
    assert crypto15m.hours_ok(cfg, hour=11) is True
    assert crypto15m.hours_ok(cfg, hour=12) is False
    assert crypto15m.hours_ok(cfg, hour=23) is False


def test_hours_ok_overnight_wrap(cfg):
    cfg["crypto15m_hours_start_utc"] = 22
    cfg["crypto15m_hours_end_utc"] = 6
    assert crypto15m.hours_ok(cfg, hour=23) is True
    assert crypto15m.hours_ok(cfg, hour=2) is True
    assert crypto15m.hours_ok(cfg, hour=6) is False
    assert crypto15m.hours_ok(cfg, hour=12) is False


def test_apply_cross_asset_agreement_and_bias():
    now = datetime(2026, 6, 26, 13, 30, tzinfo=timezone.utc).timestamp()
    assets = [
        {"asset": "BTC", "hasMarket": True, "favorite": "up"},
        {"asset": "ETH", "hasMarket": True, "favorite": "up"},
        {"asset": "SOL", "hasMarket": True, "favorite": "up"},
        {"asset": "XRP", "hasMarket": True, "favorite": "down"},
        {"asset": "DOGE", "hasMarket": False, "favorite": None},
    ]
    crypto15m._apply_cross_asset(assets, now)
    btc, xrp, doge = assets[0], assets[3], assets[4]
    assert btc["marketBias"] == 0.5 and xrp["marketBias"] == 0.5
    assert btc["hourUtc"] == 13
    assert btc["peersAgree"] == pytest.approx(0.6667, abs=1e-3)
    assert xrp["peersAgree"] == 0.0
    assert doge["peersAgree"] is None and doge["hourUtc"] == 13


def test_apply_cross_asset_singleton_has_no_peers():
    now = datetime(2026, 6, 26, 5, 0, tzinfo=timezone.utc).timestamp()
    assets = [{"asset": "BTC", "hasMarket": True, "favorite": "up"}]
    crypto15m._apply_cross_asset(assets, now)
    assert assets[0]["peersAgree"] is None
    assert assets[0]["marketBias"] == 1.0
    assert assets[0]["hourUtc"] == 5


def test_should_enter_rules_can_gate_on_correlation_and_timing(cfg):
    cfg["crypto15m_use_rules"] = True
    cfg["crypto15m_rules"] = [
        {"field": "peersAgree", "op": ">=", "value": 0.6},
        {"field": "hourUtc", "op": ">=", "value": 13},
    ]
    a = signal_asset()
    a.update({"peersAgree": 0.8, "hourUtc": 14})
    assert ct.should_enter(a, cfg, has_open=False, open_count=0)[0] is True
    a2 = signal_asset()
    a2.update({"peersAgree": 0.2, "hourUtc": 14})
    assert ct.should_enter(a2, cfg, has_open=False, open_count=0)[0] is False


def test_crypto15m_daily_loss_limit_halts_new_entries(fresh_db, env_net, cfg, monkeypatch):
    cfg["crypto15m_live"] = True
    cfg["crypto15m_daily_loss_limit"] = -50.0
    p = _seed_c15(asset="ETH", ticker="KXETH15M-LOSS", status="settled",
                  dry_run=False, filled_contracts=15, target_contracts=15)
    with db.get_db() as conn:
        conn.execute(
            "UPDATE crypto15m_positions SET resolved=1, pnl_usd=-60.0, "
            "resolved_at=datetime('now') WHERE id=?", (p["id"],))
    monkeypatch.setattr(crypto15m, "snapshot", _stub_snapshot([signal_asset()]))
    calls = _capture_orders(monkeypatch)

    run_async(ct.run_tick(cfg, authed=True))

    assert len(calls) == 0
    with db.get_db() as conn:
        n = conn.execute("SELECT COUNT(*) FROM crypto15m_positions WHERE asset='BTC'").fetchone()[0]
    assert n == 0


def test_crypto15m_daily_loss_limit_off_allows_entries(fresh_db, env_net, cfg, monkeypatch):
    cfg["crypto15m_live"] = True
    cfg["crypto15m_daily_loss_limit"] = 0.0
    p = _seed_c15(asset="ETH", ticker="KXETH15M-LOSS2", status="settled",
                  dry_run=False, filled_contracts=15, target_contracts=15)
    with db.get_db() as conn:
        conn.execute(
            "UPDATE crypto15m_positions SET resolved=1, pnl_usd=-200.0, "
            "resolved_at=datetime('now') WHERE id=?", (p["id"],))
    monkeypatch.setattr(crypto15m, "snapshot", _stub_snapshot([signal_asset()]))
    calls = _capture_orders(monkeypatch)
    run_async(ct.run_tick(cfg, authed=True))
    assert len(calls) == 1


def test_should_take_profit(cfg):
    cfg["crypto15m_take_profit"] = 0.95
    pos = {"status": "filled", "filled_contracts": 1}
    assert ct.should_take_profit(pos, 96, cfg) is True
    assert ct.should_take_profit(pos, 95, cfg) is True
    assert ct.should_take_profit(pos, 94, cfg) is False
    assert ct.should_take_profit(pos, None, cfg) is False
    assert ct.should_take_profit({"status": "submitted", "filled_contracts": 1}, 99, cfg) is False
    cfg["crypto15m_take_profit"] = 0.0
    assert ct.should_take_profit(pos, 99, cfg) is False


def test_take_profit_cashes_out_at_bid(fresh_db, env_net, cfg, monkeypatch):
    cfg["crypto15m_take_profit"] = 0.95
    pid = _seed_c15(asset="BTC", ticker="KXBTC15M-TP", direction="yes",
                    status="filled", filled_contracts=1, cost_usd=0.86,
                    entry_limit_cents=86)["id"]

    async def _open(_ticker):
        return {"yes_bid_dollars": 0.96, "yes_ask_dollars": 0.97, "status": "open", "result": ""}

    async def _book(_ticker):
        return {"yes": [[96, 50], [95, 100]], "no": [[3, 50]]}

    async def _positions():
        return []

    monkeypatch.setattr(polymarket_api, "fetch_market", _open)
    monkeypatch.setattr(polymarket_api, "get_orderbook", _book)
    monkeypatch.setattr(polymarket_api, "get_positions", _positions)
    monkeypatch.setattr(crypto15m, "snapshot", _stub_snapshot([]))
    calls = _capture_orders(monkeypatch)

    run_async(ct.run_tick(cfg, authed=True))

    assert len(calls) == 1
    assert calls[0]["action"] == "sell" and calls[0]["side"] == "yes"
    assert calls[0]["price_cents"] == 96
    with db.get_db() as conn:
        r = db.fetch_crypto15m_by_id(conn, pid)
    assert r["status"] == "exiting"
    assert r["exit_reason"] == "take_profit"


def test_settlement_beats_take_profit(fresh_db, env_net, cfg, monkeypatch):
    cfg["crypto15m_take_profit"] = 0.95
    pid = _seed_c15(asset="BTC", ticker="KXBTC15M-TPS", direction="yes",
                    status="filled", filled_contracts=1, cost_usd=0.86)["id"]

    async def _settled_yes(_ticker):
        return {"result": "yes", "status": "finalized"}

    async def _book(_ticker):
        return {"yes": [[96, 50]], "no": []}

    monkeypatch.setattr(polymarket_api, "fetch_market", _settled_yes)
    monkeypatch.setattr(polymarket_api, "get_orderbook", _book)
    monkeypatch.setattr(crypto15m, "snapshot", _stub_snapshot([]))
    calls = _capture_orders(monkeypatch)

    run_async(ct.run_tick(cfg, authed=True))

    assert calls == []
    with db.get_db() as conn:
        r = db.fetch_crypto15m_by_id(conn, pid)
    assert r["status"] == "settled"
    assert r["exit_reason"] != "take_profit"


def test_run_tick_manages_open_when_disabled(fresh_db, env_net, cfg, monkeypatch):
    cfg["crypto15m_enabled"] = False
    pid = _seed_c15(asset="BTC", ticker="KXBTC15M-OFF", direction="yes",
                    status="filled", filled_contracts=1, cost_usd=0.40)["id"]

    async def _settled_yes(_ticker):
        return {"result": "yes", "status": "finalized"}

    monkeypatch.setattr(polymarket_api, "fetch_market", _settled_yes)
    monkeypatch.setattr(crypto15m, "snapshot", _stub_snapshot([signal_asset()]))
    calls = _capture_orders(monkeypatch)

    run_async(ct.run_tick(cfg, authed=True))

    assert calls == []
    with db.get_db() as conn:
        r = db.fetch_crypto15m_by_id(conn, pid)
    assert r["status"] == "settled" and r["resolved"] == 1


def test_overall_take_profit_arms_baseline(fresh_db, env_net, cfg, monkeypatch):
    cfg["crypto15m_take_profit_total"] = 50.0
    p = _seed_c15(asset="ETH", ticker="KXETH15M-ARM", status="settled",
                  filled_contracts=15, target_contracts=15)
    with db.get_db() as conn:
        conn.execute("UPDATE crypto15m_positions SET resolved=1, pnl_usd=30.0, "
                     "resolved_at=datetime('now') WHERE id=?", (p["id"],))
    monkeypatch.setattr(crypto15m, "snapshot", _stub_snapshot([signal_asset()]))
    _capture_orders(monkeypatch)

    run_async(ct.run_tick(cfg, authed=True))

    assert cfg["crypto15m_enabled"] is True
    with db.get_db() as conn:
        assert float(db.kv_get(conn, "c15_tp_baseline:mainnet")) == pytest.approx(30.0)


def test_overall_take_profit_fires_and_disables(fresh_db, env_net, cfg, monkeypatch):
    cfg["crypto15m_take_profit_total"] = 50.0
    with db.get_db() as conn:
        db.kv_set(conn, "c15_tp_baseline:mainnet", "0.0")
    p = _seed_c15(asset="ETH", ticker="KXETH15M-TP", status="settled",
                  filled_contracts=15, target_contracts=15)
    with db.get_db() as conn:
        conn.execute("UPDATE crypto15m_positions SET resolved=1, outcome_correct=1, "
                     "pnl_usd=60.0, resolved_at=datetime('now') WHERE id=?", (p["id"],))

    fired: dict = {}

    async def _cb(info):
        fired.update(info)
    monkeypatch.setattr(ct, "_auto_off_cb", _cb)
    monkeypatch.setattr(crypto15m, "snapshot", _stub_snapshot([signal_asset()]))
    calls = _capture_orders(monkeypatch)

    run_async(ct.run_tick(cfg, authed=True))

    assert cfg["crypto15m_enabled"] is False
    assert calls == []
    assert fired.get("reason") == "take_profit_total"
    assert fired.get("gained") == pytest.approx(60.0)
    with db.get_db() as conn:
        assert db.kv_get(conn, "c15_tp_baseline:mainnet") is None


def test_overall_take_profit_disabled_clears_stale_baseline(fresh_db, env_net, cfg, monkeypatch):
    cfg["crypto15m_take_profit_total"] = 0.0
    with db.get_db() as conn:
        db.kv_set(conn, "c15_tp_baseline:mainnet", "12.5")
    monkeypatch.setattr(crypto15m, "snapshot", _stub_snapshot([]))
    _capture_orders(monkeypatch)

    run_async(ct.run_tick(cfg, authed=True))

    with db.get_db() as conn:
        assert db.kv_get(conn, "c15_tp_baseline:mainnet") is None


def _paired_asset(ticker="KXBTC15M-P1", model_prob=0.62):
    close = (datetime.now(timezone.utc) + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"asset": "BTC", "series": "KXBTC15M", "ticker": ticker,
            "closeTime": close, "modelProb": model_prob, "feeSchedule": None,
            "deltaUsd": 0.0, "minsLeft": 5.0}


def _paired_cfg(cfg):
    cfg = dict(cfg)
    cfg["crypto15m_paired_mode"] = True
    cfg["crypto15m_paired_max_combined_cents"] = 100.0
    cfg["crypto15m_order_size"] = 2
    return cfg


def _mock_quotes(monkeypatch, *, yes_ask, no_asks):
    state = {"no": 0}

    async def _q(_ticker, side):
        if side == "yes":
            return {"ask_cents": yes_ask, "bid_cents": yes_ask - 1}
        i = min(state["no"], len(no_asks) - 1)
        state["no"] += 1
        return {"ask_cents": no_asks[i], "bid_cents": no_asks[i] - 1}

    monkeypatch.setattr(polymarket_api, "get_quote", _q)


def _mock_place(monkeypatch, *, fills):
    calls = []

    async def _place(**kw):
        calls.append(kw)
        if fills(kw["side"], kw["price_cents"]):
            return {"order": {"order_id": f"ord-{len(calls)}", "status": "matched"}}
        return {"order": {"status": "killed"}}

    monkeypatch.setattr(polymarket_api, "place_limit_order", _place)
    return calls


def test_paired_places_both_legs_concurrently(fresh_db, env_net, cfg, monkeypatch):
    cfg = _paired_cfg(cfg)
    _mock_quotes(monkeypatch, yes_ask=44, no_asks=[50])
    calls = _mock_place(monkeypatch, fills=lambda side, px: True)
    rows = run_async(ct._open_paired_entry(_paired_asset(), cfg, "mainnet", 0.0))
    assert sorted(c["side"] for c in calls) == ["no", "yes"]
    assert sum(1 for r in rows if ct._leg_landed(r)) == 2


def test_paired_chases_missed_hedge(fresh_db, env_net, cfg, monkeypatch):
    cfg = _paired_cfg(cfg)
    _mock_quotes(monkeypatch, yes_ask=40, no_asks=[50, 53])
    calls = _mock_place(monkeypatch, fills=lambda side, px: side == "yes" or px >= 55)
    rows = run_async(ct._open_paired_entry(_paired_asset(), cfg, "mainnet", 0.0))
    no_calls = [c for c in calls if c["side"] == "no"]
    assert len(no_calls) == 2
    assert no_calls[0]["price_cents"] == 52 and no_calls[1]["price_cents"] >= 55
    landed = [r for r in rows if ct._leg_landed(r)]
    assert any(r["strategy"] == "paired" for r in landed)
    assert any(r["strategy"] == "paired_hedge" for r in landed)


def test_paired_naked_dominant_when_chase_too_expensive(fresh_db, env_net, cfg, monkeypatch):
    cfg = _paired_cfg(cfg)
    _mock_quotes(monkeypatch, yes_ask=44, no_asks=[50, 53])
    calls = _mock_place(monkeypatch, fills=lambda side, px: side == "yes")
    rows = run_async(ct._open_paired_entry(_paired_asset(), cfg, "mainnet", 0.0))
    assert len([c for c in calls if c["side"] == "no"]) == 1
    landed = [r for r in rows if ct._leg_landed(r)]
    assert len(landed) == 1 and landed[0]["strategy"] == "paired"


def _seed_settled_pnls(pnls, network="mainnet", dry_run=False):
    for pnl in pnls:
        p = _seed_c15(status="settled", network=network, dry_run=dry_run,
                      filled_contracts=5, target_contracts=5)
        with db.get_db() as conn:
            conn.execute(
                "UPDATE crypto15m_positions SET resolved=1, pnl_usd=?, "
                "resolved_at=datetime('now') WHERE id=?", (pnl, p["id"]))


def _streak_cfg(cfg, **over):
    cfg["crypto15m_streak_sizing"] = True
    cfg["crypto15m_streak_loss_pct"] = over.get("loss_pct", 20.0)
    cfg["crypto15m_streak_win_pct"] = over.get("win_pct", 0.0)
    cfg["crypto15m_streak_max_mult"] = over.get("max_mult", 4.0)
    return cfg


def test_streak_multiplier_off_by_default(fresh_db, env_net, cfg):
    _seed_settled_pnls([-5.0, -5.0, -5.0])
    assert ct.streak_multiplier(cfg, "mainnet") == 1.0


def test_streak_multiplier_no_history(fresh_db, env_net, cfg):
    assert ct.streak_multiplier(_streak_cfg(cfg), "mainnet") == 1.0


def test_streak_multiplier_loss_ramp_compounds(fresh_db, env_net, cfg):
    _seed_settled_pnls([4.0, -5.0, -5.0])
    m = ct.streak_multiplier(_streak_cfg(cfg), "mainnet")
    assert m == pytest.approx(1.2 ** 2)


def test_streak_multiplier_capped(fresh_db, env_net, cfg):
    _seed_settled_pnls([-5.0] * 12)
    m = ct.streak_multiplier(_streak_cfg(cfg), "mainnet")
    assert m == pytest.approx(4.0)


def test_streak_multiplier_win_resets_to_base(fresh_db, env_net, cfg):
    _seed_settled_pnls([-5.0, -5.0, -5.0, 4.0])
    m = ct.streak_multiplier(_streak_cfg(cfg), "mainnet")
    assert m == 1.0


def test_streak_multiplier_win_press(fresh_db, env_net, cfg):
    _seed_settled_pnls([-5.0, 4.0, 4.0])
    m = ct.streak_multiplier(_streak_cfg(cfg, win_pct=25.0), "mainnet")
    assert m == pytest.approx(1.25 ** 2)


def test_streak_multiplier_scratch_breaks_run(fresh_db, env_net, cfg):
    _seed_settled_pnls([-5.0, -5.0, 0.0])
    assert ct.streak_multiplier(_streak_cfg(cfg), "mainnet") == 1.0


def test_streak_multiplier_scoped_to_network_and_live(fresh_db, env_net, cfg):
    _seed_settled_pnls([-5.0, -5.0], network="testnet")
    _seed_settled_pnls([-5.0, -5.0], dry_run=True)
    assert ct.streak_multiplier(_streak_cfg(cfg), "mainnet") == 1.0


def test_compute_entry_contracts_streak_scales_fixed(cfg):
    cfg["crypto15m_sizing_mode"] = "fixed"
    n = ct.compute_entry_contracts(
        cfg, entry_limit_cents=50, balance_usd=1000, order_size=5, streak_mult=1.44)
    assert n == 7
    n = ct.compute_entry_contracts(
        cfg, entry_limit_cents=50, balance_usd=1000, order_size=5, streak_mult=0.1)
    assert n == 1


def test_compute_entry_contracts_streak_respects_risk_caps(cfg):
    cfg["crypto15m_sizing_mode"] = "fixed"
    cfg["crypto15m_max_loss_pct"] = 0.05
    n = ct.compute_entry_contracts(
        cfg, entry_limit_cents=50, balance_usd=100, order_size=8, streak_mult=4.0)
    assert n == 10
