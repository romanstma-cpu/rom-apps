from __future__ import annotations

import asyncio

import pytest

import crypto15m
import crypto15m_trader as c15t
import db
import indicators
import replay
import rtds_ws
import spot_ws
from config import merge_with_defaults


def test_model_up_prob_sides_and_bounds():
    assert crypto15m.model_up_prob(101.0, 100.0, 0.001, 5.0) > 0.5
    assert crypto15m.model_up_prob(99.0, 100.0, 0.001, 5.0) < 0.5
    assert crypto15m.model_up_prob(100.0, 100.0, 0.001, 5.0) == pytest.approx(0.5)


def test_model_sharpens_as_close_approaches():
    p_hourly = crypto15m.model_up_prob(100.5, 100.0, 0.001, 55.0)
    p_15m = crypto15m.model_up_prob(100.5, 100.0, 0.001, 10.0)
    p_5m = crypto15m.model_up_prob(100.5, 100.0, 0.001, 2.0)
    p_final = crypto15m.model_up_prob(100.5, 100.0, 0.001, 0.3)
    assert p_hourly < p_15m < p_5m < p_final
    assert p_final > 0.99


def test_model_up_prob_missing_inputs_none():
    assert crypto15m.model_up_prob(None, 100.0, 0.001, 5.0) is None
    assert crypto15m.model_up_prob(100.0, None, 0.001, 5.0) is None
    assert crypto15m.model_up_prob(100.0, 100.0, None, 5.0) is None
    assert crypto15m.model_up_prob(100.0, 100.0, 0.001, None) is None
    assert crypto15m.model_up_prob(100.0, 100.0, 0.0, 5.0) is None


def test_fee_cents_is_fee_v2_curve():
    assert crypto15m._fee_cents(90.0) == pytest.approx(0.63)
    assert crypto15m._fee_cents(50.0) == pytest.approx(1.75)
    assert crypto15m._fee_cents(50.0, {"enabled": True, "rate": 0.25, "exponent": 2.0}) \
        == pytest.approx(0.25 * 0.25 ** 2 * 100.0)
    assert crypto15m._fee_cents(50.0, {"enabled": False}) == 0.0


def test_model_edge_picks_the_better_side_net_of_fee():
    e = crypto15m.model_edge_net_cents(0.98, 0.90, 0.15)
    assert e == pytest.approx(7.37, abs=0.01)
    e2 = crypto15m.model_edge_net_cents(0.02, 0.15, 0.90)
    assert e2 == pytest.approx(7.37, abs=0.01)
    assert crypto15m.model_edge_net_cents(None, 0.9, 0.1) is None
    assert crypto15m.model_edge_net_cents(0.98, None, None) is None


def test_sigma1m_needs_history_and_measures_vol():
    assert indicators.sigma1m([100.0] * 10) is None
    flat = indicators.sigma1m([100.0] * 40)
    assert flat == pytest.approx(0.0)
    wiggly = indicators.sigma1m([100.0 + (i % 2) for i in range(40)])
    assert wiggly and wiggly > 0.001


def _model_cfg(**over) -> dict:
    base = {
        "crypto15mEnabled": True,
        "crypto15mDirectionMode": "model",
        "crypto15mModelAutopause": False,
        "crypto15mModelMinProb": 0.97,
        "crypto15mModelMinEdgeCents": 2.0,
        "crypto15mTimeDelayMin": 8,
    }
    base.update(over)
    return merge_with_defaults(base)


def _asset(**over) -> dict:
    a = {
        "asset": "BTC", "hasMarket": True, "favorite": "up",
        "minsLeft": 5.0, "inWindow": True, "modelProb": 0.99,
        "edgeNetCents": 5.0, "upAsk": 0.90, "downAsk": 0.12,
        "spotLive": True,
    }
    a.update(over)
    return a


def test_entry_side_follows_model():
    cfg = _model_cfg()
    assert c15t._entry_side(_asset(modelProb=0.99), cfg) == "up"
    assert c15t._entry_side(_asset(modelProb=0.01), cfg) == "down"
    assert c15t._entry_side(_asset(modelProb=None), cfg) == ""


def test_model_entry_ok_at_high_prob_and_edge():
    ok, why = c15t.should_enter(_asset(), _model_cfg(), has_open=False, open_count=0)
    assert ok, why


def test_model_entry_blocked_below_min_prob():
    ok, why = c15t.should_enter(_asset(modelProb=0.90), _model_cfg(),
                                has_open=False, open_count=0)
    assert not ok and "model 0.9" in why


def test_model_entry_blocked_on_thin_edge():
    ok, why = c15t.should_enter(_asset(upAsk=0.975), _model_cfg(),
                                has_open=False, open_count=0)
    assert not ok and "net edge" in why


def test_model_entry_edge_is_traded_side_not_best_side():
    a = _asset(modelProb=0.97, upAsk=0.96, downAsk=0.01, edgeNetCents=2.9)
    ok, why = c15t.should_enter(a, _model_cfg(), has_open=False, open_count=0)
    assert not ok and "net edge" in why


def test_model_entry_blocked_when_model_unavailable():
    ok, why = c15t.should_enter(_asset(modelProb=None), _model_cfg(),
                                has_open=False, open_count=0)
    assert not ok and "model unavailable" in why


def test_model_certain_down_zero_prob_is_not_dropped():
    ok, why = c15t.should_enter(_asset(modelProb=0.0, downAsk=0.90, upAsk=0.05),
                                _model_cfg(), has_open=False, open_count=0)
    assert ok, why


def test_perfect_record_never_pauses_and_can_resume():
    for n in range(c15t._CAL_MIN_N, c15t._CAL_WINDOW + 1):
        assert c15t._wilson_lb(n, n) >= c15t._CAL_PAUSE_LB, f"perfect {n}/{n} would pause"
    assert c15t._wilson_lb(c15t._CAL_WINDOW, c15t._CAL_WINDOW) >= c15t._CAL_RESUME_LB
    assert c15t._wilson_lb(c15t._CAL_WINDOW - 1, c15t._CAL_WINDOW) >= c15t._CAL_RESUME_LB
    assert c15t._wilson_lb(38, 40) < c15t._CAL_RESUME_LB
    assert c15t._wilson_lb(36, 40) < c15t._CAL_PAUSE_LB


def test_window_open_rejected_when_first_seen_late():
    crypto15m._window_open.clear()
    start = 1_790_000_000
    assert crypto15m._track_window_open("BTC", start, 62508.6, start + 44.0) is None
    assert crypto15m._track_window_open("BTC", start, 62540.0, start + 120.0) is None


def test_window_open_captured_within_grace_then_sticky():
    crypto15m._window_open.clear()
    start = 1_790_000_000
    assert crypto15m._track_window_open("BTC", start, 62540.0, start + 5.0) == 62540.0
    assert crypto15m._track_window_open("BTC", start, 63000.0, start + 200.0) == 62540.0
    crypto15m._window_open.clear()


def test_window_open_recovered_from_oracle_ring_even_when_market_lists_late():
    crypto15m._window_open.clear()
    start = 1_790_000_000
    ring = crypto15m.rtds_ws._client.samples["BTC"]
    ring.clear()
    for i in range(-5, 30):
        ring.append((start + i, 62540.0 + i))
    try:
        got = crypto15m._track_window_open("BTC", start, 62999.0, start + 28.0)
        assert got == pytest.approx(62540.0)
    finally:
        ring.clear()
        crypto15m._window_open.clear()


def test_sample_at_tolerance_and_miss():
    c = rtds_ws._Client()
    c.samples["BTC"].append((1_000_000, 100.0))
    c.samples["BTC"].append((1_000_010, 110.0))
    assert c.sample_at("BTC", 1_000_000) == pytest.approx(100.0)
    assert c.sample_at("BTC", 1_000_002) == pytest.approx(100.0)
    assert c.sample_at("BTC", 1_000_005) is None
    assert c.sample_at("BTC", 1_000_009) == pytest.approx(110.0)
    assert c.sample_at("ETH", 1_000_000) is None


def test_divergence_guard_blocks_too_good_midwindow_edge():
    a = _asset(modelProb=0.999, upAsk=0.50, downAsk=0.52, edgeNetCents=48.0,
               minsLeft=3.0)
    ok, why = c15t.should_enter(a, _model_cfg(), has_open=False, open_count=0)
    assert not ok and "disagrees" in why
    ok2, why2 = c15t.should_enter(
        a, _model_cfg(crypto15mModelMaxBookGapCents=0), has_open=False, open_count=0)
    assert ok2, why2


def test_divergence_guard_exempts_final_minute():
    a = _asset(modelProb=0.9990, upAsk=0.50, downAsk=0.52, edgeNetCents=48.0,
               minsLeft=0.5, spotLive=True)
    ok, why = c15t.should_enter(a, _model_cfg(), has_open=False, open_count=0)
    assert ok, why


def test_divergence_guard_blocks_paired_too():
    a = _asset(modelProb=0.95, upAsk=0.50, downAsk=0.48)
    ok, why = c15t.should_enter(a, _paired_cfg(), has_open=False, open_count=0)
    assert not ok and "disagrees" in why


def test_paired_tilt_ladder():
    cfg = merge_with_defaults({})
    assert c15t.paired_tilt(None, cfg) == 0
    assert c15t.paired_tilt(2.9, cfg) == 0
    assert c15t.paired_tilt(3.0, cfg) == 1
    assert c15t.paired_tilt(5.9, cfg) == 1
    assert c15t.paired_tilt(6.0, cfg) == 2
    assert c15t.paired_tilt(10.0, cfg) == 3
    assert c15t.paired_tilt(25.0, cfg) == 3


def test_paired_sides_picks_the_underpriced_side():
    dom, edge, hedge_edge = c15t.paired_sides(
        _asset(modelProb=0.60, upAsk=0.50, downAsk=0.48))
    assert dom == "up"
    assert edge == pytest.approx(60 - 50 - 1.75, abs=0.01)
    dom2, edge2, _ = c15t.paired_sides(
        _asset(modelProb=0.60, upAsk=0.70, downAsk=0.28))
    assert dom2 == "down"
    assert edge2 == pytest.approx(40 - 28 - 1.4112, abs=0.01)
    assert c15t.paired_sides(_asset(modelProb=None))[0] == ""
    assert c15t.paired_sides(_asset(downAsk=None))[0] == ""


def _paired_cfg(**over):
    base = {"crypto15mPairedMode": True}
    base.update(over)
    return _model_cfg(**base)


def test_paired_entry_ok_and_skips_min_prob_gate():
    a = _asset(modelProb=0.60, upAsk=0.50, downAsk=0.48)
    ok, why = c15t.should_enter(a, _paired_cfg(), has_open=False, open_count=0)
    assert ok, why


def test_paired_entry_blocked_over_combined_cap():
    a = _asset(modelProb=0.60, upAsk=0.52, downAsk=0.49)
    ok, why = c15t.should_enter(a, _paired_cfg(), has_open=False, open_count=0)
    assert not ok and "combined" in why


def test_paired_entry_blocked_below_tilt_floor():
    a = _asset(modelProb=0.50, upAsk=0.50, downAsk=0.48)
    ok, why = c15t.should_enter(a, _paired_cfg(), has_open=False, open_count=0)
    assert not ok and "tilt floor" in why


def test_paired_entry_blocked_in_final_minute_and_without_both_asks():
    a = _asset(modelProb=0.60, upAsk=0.50, downAsk=0.48, minsLeft=0.5)
    ok, why = c15t.should_enter(a, _paired_cfg(), has_open=False, open_count=0)
    assert not ok and "final minute" in why
    a2 = _asset(modelProb=0.60, upAsk=0.50, downAsk=None)
    ok2, why2 = c15t.should_enter(a2, _paired_cfg(), has_open=False, open_count=0)
    assert not ok2 and "BOTH sides" in why2


def test_strength_exit_eligibility():
    cfg_on = merge_with_defaults({"crypto15mSellIntoStrength": True,
                                  "crypto15mSellStrengthCents": 80})
    pos = {"status": "filled", "filled_contracts": 10, "avg_entry_cents": 50.0}
    assert c15t.strength_exit_cents(pos, cfg_on) == 80
    assert c15t.strength_exit_cents(dict(pos, avg_entry_cents=95.0), cfg_on) is None
    assert c15t.strength_exit_cents(dict(pos, avg_entry_cents=79.0), cfg_on) is None
    assert c15t.strength_exit_cents(pos, merge_with_defaults({})) is None
    assert c15t.strength_exit_cents(dict(pos, status="exiting"), cfg_on) is None
    assert c15t.strength_exit_cents(dict(pos, filled_contracts=0), cfg_on) is None


def test_strength_exit_target_clamped():
    pos = {"status": "filled", "filled_contracts": 10, "avg_entry_cents": 20.0}
    cfg = merge_with_defaults({"crypto15mSellIntoStrength": True,
                               "crypto15mSellStrengthCents": 300})
    assert c15t.strength_exit_cents(pos, cfg) == 99


def test_min_notional_guard():
    assert not c15t._min_notional_ok(5, 3)
    assert not c15t._min_notional_ok(10, 7)
    assert not c15t._min_notional_ok(5, 19)
    assert c15t._min_notional_ok(5, 20)
    assert c15t._min_notional_ok(5, 50)


def test_paired_legs_exempt_from_stop_loss():
    pos = {"status": "filled", "filled_contracts": 10, "strategy": "paired_hedge",
           "cost_usd": 4.8}
    assert not c15t.should_stop_loss(pos, 0.05, merge_with_defaults({}))
    pos_single = dict(pos, strategy="model")
    assert c15t.should_stop_loss(pos_single, 0.05, merge_with_defaults({}))


def test_final_minute_needs_live_ws_spot():
    a = _asset(minsLeft=0.5, modelProb=0.999, spotLive=False)
    ok, why = c15t.should_enter(a, _model_cfg(), has_open=False, open_count=0)
    assert not ok and "live WS spot" in why


def test_final_minute_three_sigma_gate():
    a = _asset(minsLeft=0.5, modelProb=0.99)
    ok, why = c15t.should_enter(a, _model_cfg(), has_open=False, open_count=0)
    assert not ok and "3-sigma" in why
    a2 = _asset(minsLeft=0.5, modelProb=0.9990)
    ok2, why2 = c15t.should_enter(a2, _model_cfg(), has_open=False, open_count=0)
    assert ok2, why2


def test_final_minute_runway_guard():
    a = _asset(minsLeft=0.05, modelProb=0.9999)
    ok, why = c15t.should_enter(a, _model_cfg(), has_open=False, open_count=0)
    assert not ok and "round-trip" in why


def test_final_minute_disabled_by_config():
    a = _asset(minsLeft=0.5, modelProb=0.9999)
    cfg = _model_cfg(crypto15mModelFinalMinute=False)
    ok, why = c15t.should_enter(a, cfg, has_open=False, open_count=0)
    assert not ok and "final minute" in why


def test_rules_blocked_in_final_minute():
    cfg = merge_with_defaults({
        "crypto15mEnabled": True, "crypto15mUseRules": True,
        "crypto15mRules": [{"field": "minsLeft", "op": "<=", "value": 15}],
    })
    a = _asset(minsLeft=0.5)
    ok, why = c15t.should_enter(a, cfg, has_open=False, open_count=0)
    assert not ok and "model mode only" in why


def test_non_model_modes_still_blocked_from_final_minute_entries():
    cfg = merge_with_defaults({"crypto15mEnabled": True})
    a = _asset(minsLeft=0.5)
    a["signal"] = False
    ok, why = c15t.should_enter(a, cfg, has_open=False, open_count=0)
    assert not ok


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    dbfile = tmp_path / "model-test.db"
    monkeypatch.setattr(db, "db_path", lambda: dbfile)
    db.init_db()
    return dbfile


def _seed_windows(n_wins: int, n_losses: int) -> None:
    with db.get_db() as conn:
        for i in range(n_wins + n_losses):
            tk = f"W{i}"
            won = i < n_wins
            conn.execute(
                """INSERT INTO crypto15m_signals
                   (ticker, asset, resolved, up_won, network, close_time)
                   VALUES (?, 'BTC', 1, ?, 'mainnet', '2026-01-01T00:00:00Z')""",
                (tk, 1 if won else 0),
            )
            conn.execute(
                """INSERT INTO crypto15m_ticks
                   (ticker, asset, mins_left, model_prob, network)
                   VALUES (?, 'BTC', 2.0, 0.99, 'mainnet')""",
                (tk,),
            )


def test_wilson_lb_basic():
    assert c15t._wilson_lb(0, 0) == 0.0
    assert c15t._wilson_lb(40, 40) > 0.9
    assert c15t._wilson_lb(20, 40) < 0.5


def test_calibration_pauses_on_degraded_hit_rate(fresh_db):
    c15t._CAL_CACHE.update({"at": 0.0, "ok": True})
    _seed_windows(n_wins=25, n_losses=15)
    cal = c15t.check_model_calibration("mainnet")
    assert cal["ok"] is False
    assert cal["n"] == 40


def test_calibration_ok_with_high_hit_rate(fresh_db):
    c15t._CAL_CACHE.update({"at": 0.0, "ok": True})
    _seed_windows(n_wins=40, n_losses=0)
    cal = c15t.check_model_calibration("mainnet")
    assert cal["ok"] is True


def test_calibration_insufficient_evidence_never_pauses(fresh_db):
    c15t._CAL_CACHE.update({"at": 0.0, "ok": True})
    _seed_windows(n_wins=2, n_losses=8)
    cal = c15t.check_model_calibration("mainnet")
    assert cal["ok"] is True


def test_model_entry_blocked_when_calibration_paused(fresh_db):
    c15t._CAL_CACHE.update({"at": 0.0, "ok": True})
    _seed_windows(n_wins=25, n_losses=15)
    cfg = _model_cfg(crypto15mModelAutopause=True)
    ok, why = c15t.should_enter(_asset(), cfg, has_open=False, open_count=0)
    assert not ok and "calibration degraded" in why
    c15t._CAL_CACHE.update({"at": 0.0, "ok": True})


def test_spot_ws_parses_ticker_and_serves_fresh():
    c = spot_ws._Client()
    c.connected = True
    c.handle_message({
        "channel": "ticker",
        "events": [{"tickers": [{"product_id": "BTC-USD", "price": "50123.5"}]}],
    })
    assert c.spot("BTC") == pytest.approx(50123.5)
    assert c.fresh_spots() == {"BTC": pytest.approx(50123.5)}
    c.handle_message({
        "channel": "ticker",
        "events": [{"tickers": [{"product_id": "PEPE-USD", "price": "1"},
                                {"product_id": "ETH-USD", "price": "junk"}]}],
    })
    assert c.spot("PEPE") is None
    assert c.spot("ETH") is None


def test_spot_ws_staleness_gate():
    c = spot_ws._Client()
    c.connected = True
    c.prices["BTC"] = (0.0, 50000.0)
    assert c.spot("BTC") is None
    assert c.fresh_spots() == {}


def test_spot_ws_sampler_one_print_per_second_and_window_partial():
    c = spot_ws._Client()
    now = 1_000_000.0
    c.prices["BTC"] = (now, 100.0)
    c._sample_once(now)
    c._sample_once(now + 0.4)
    c.prices["BTC"] = (now + 1, 101.0)
    c._sample_once(now + 1.0)
    assert len(c.samples["BTC"]) == 2
    close = now + 30
    total, count = c.window_partial("BTC", close, now=now + 2)
    assert count == 2 and total == pytest.approx(201.0)
    total2, count2 = c.window_partial("BTC", now - 120, now=now + 2)
    assert count2 == 0


def _rtds_update(symbol: str, value, ts_ms: int = 1_783_117_568_000) -> dict:
    return {
        "topic": "crypto_prices_chainlink", "type": "update",
        "timestamp": ts_ms + 948,
        "payload": {"symbol": symbol, "value": value, "timestamp": ts_ms,
                    "full_accuracy_value": "62597344603030672500000"},
    }


def test_rtds_ws_parses_update_and_serves_fresh():
    c = rtds_ws._Client()
    c.connected = True
    c.handle_message(_rtds_update("btc/usd", 62597.34))
    c.handle_message(_rtds_update("hype/usd", 41.02))
    assert c.spot("BTC") == pytest.approx(62597.34)
    assert c.spot("HYPE") == pytest.approx(41.02)
    assert set(c.fresh_spots()) == {"BTC", "HYPE"}


def test_rtds_ws_ignores_junk_history_and_unknown_symbols():
    c = rtds_ws._Client()
    c.connected = True
    c.handle_message(_rtds_update("pepe/usd", 1.0))
    c.handle_message(_rtds_update("btc/usd", "junk"))
    c.handle_message(_rtds_update("btc/usd", -5))
    c.handle_message({"topic": "crypto_prices_chainlink",
                      "payload": {"data": [{"timestamp": 1, "value": 2.0}]}})
    c.handle_message({"topic": "comments", "type": "update",
                      "payload": {"symbol": "btc/usd", "value": 1.0}})
    c.handle_message("PONG")
    assert c.fresh_spots() == {}


def test_rtds_ws_staleness_gate_and_disconnected_serves_nothing():
    c = rtds_ws._Client()
    c.connected = True
    c.prices["BTC"] = (0.0, 50000.0)
    assert c.spot("BTC") is None
    assert c.fresh_spots() == {}
    c2 = rtds_ws._Client()
    c2.prices["BTC"] = (__import__("time").time(), 50000.0)
    c2.connected = False
    assert c2.fresh_spots() == {}


def test_rtds_ws_samples_one_print_per_second():
    c = rtds_ws._Client()
    c.connected = True
    c.handle_message(_rtds_update("btc/usd", 100.0))
    c.handle_message(_rtds_update("btc/usd", 100.5))
    assert len(c.samples["BTC"]) == 1
    assert c.samples["BTC"][-1][1] == pytest.approx(100.0)


def test_overlay_prefers_rtds_then_coinbase_then_rest(monkeypatch):
    monkeypatch.setattr(crypto15m.rtds_ws, "fresh_spots",
                        lambda: {"BTC": 62000.0})
    monkeypatch.setattr(crypto15m.spot_ws, "fresh_spots",
                        lambda: {"BTC": 61990.0, "ETH": 1759.0})
    crypto15m._spot_cache.update(
        at=1e15,
        spots={"BTC": 61900.0, "ETH": 1750.0, "BNB": 600.0},
        source="cryptocompare",
    )
    spots, src = asyncio.run(crypto15m.fetch_spots())
    assert spots["BTC"] == pytest.approx(62000.0)
    assert spots["ETH"] == pytest.approx(1759.0)
    assert spots["BNB"] == pytest.approx(600.0)
    assert src == "rtds-ws+coinbase-ws+cryptocompare"
    crypto15m._spot_cache.update(at=0.0, spots={}, source="")


def _seed_replay_window(ticker: str, up_won: int, *, model_prob=0.99,
                        edge=5.0, yes_ask=0.90, mins_left=4.0,
                        spot_source="coinbase-ws", up_ask=None) -> None:
    if up_ask is None:
        up_ask = yes_ask
    elif up_ask == "gamma":
        up_ask = None
    with db.get_db() as conn:
        conn.execute(
            """INSERT INTO crypto15m_signals
               (ticker, asset, resolved, up_won, network, close_time)
               VALUES (?, 'BTC', 1, ?, 'mainnet', '2026-01-01T00:15:00Z')""",
            (ticker, up_won),
        )
        conn.execute(
            """INSERT INTO crypto15m_ticks
               (ticker, asset, mins_left, yes_bid, yes_ask, up_prob, no_ask,
                model_prob, edge_net_cents, spot_source, up_ask, network)
               VALUES (?, 'BTC', ?, ?, ?, 0.9, ?, ?, ?, ?, ?, 'mainnet')""",
            (ticker, mins_left, yes_ask - 0.02, yes_ask, 1.0 - yes_ask + 0.02,
             model_prob, edge, spot_source, up_ask),
        )


def test_replay_model_mode_trades_and_nets_fees(fresh_db):
    cfg = _model_cfg()
    _seed_replay_window("RW1", up_won=1)
    _seed_replay_window("RW2", up_won=0)
    res = replay.replay(cfg, env="mainnet", since_days=60)
    assert res["windowsScanned"] == 2
    assert res["n"] == 2
    assert res["wins"] == 1
    per_ct = 0.0937 - 0.9063
    assert res["totalPnlUsd"] == pytest.approx(per_ct * res["contracts"], abs=0.02)


def test_replay_paired_mode_two_legs_net_of_fees(fresh_db):
    with db.get_db() as conn:
        conn.execute(
            """INSERT INTO crypto15m_signals
               (ticker, asset, resolved, up_won, network, close_time)
               VALUES ('PW1', 'BTC', 1, 1, 'mainnet', '2026-01-01T00:15:00Z')""",
        )
        conn.execute(
            """INSERT INTO crypto15m_ticks
               (ticker, asset, mins_left, yes_bid, yes_ask, up_prob, no_ask,
                model_prob, edge_net_cents, spot_source, up_ask, network)
               VALUES ('PW1', 'BTC', 4.0, 0.48, 0.50, 0.52, 0.48,
                       0.60, 8.25, 'rtds-ws', 0.50, 'mainnet')""",
        )
    cfg = _paired_cfg()
    res = replay.replay(cfg, env="mainnet", since_days=60)
    assert res["n"] == 1 and res["wins"] == 1
    # The fee schedule is chosen from the tick's observed_at, which the insert
    # defaults to now, so derive theta instead of freezing a constant here.
    # This test is about charging BOTH legs; test_fees_us covers the rate.
    import backtest as bt
    with db.get_db() as conn:
        at = bt.epoch_of(conn.execute(
            "SELECT observed_at FROM crypto15m_ticks WHERE ticker='PW1'"
        ).fetchone()[0])
    dom_pnl = 1.0 - 0.50 - bt.us_fee_per_contract(0.50, at)
    hedge_pnl = -0.48 - bt.us_fee_per_contract(0.48, at)
    unit = 2 * dom_pnl + hedge_pnl
    assert res["totalPnlUsd"] == pytest.approx(unit * res["contracts"], abs=0.02)
    assert any("BOTH legs" in c for c in res["caveats"])


def test_replay_one_trade_per_window(fresh_db):
    cfg = _model_cfg()
    _seed_replay_window("RW3", up_won=1)
    with db.get_db() as conn:
        conn.execute(
            """INSERT INTO crypto15m_ticks
               (ticker, asset, mins_left, yes_ask, up_prob, model_prob,
                edge_net_cents, spot_source, up_ask, network)
               VALUES ('RW3', 'BTC', 3.0, 0.91, 0.9, 0.99, 5.0,
                       'coinbase-ws', 0.91, 'mainnet')""",
        )
    res = replay.replay(cfg, env="mainnet", since_days=60)
    assert res["n"] == 1


def test_replay_refuses_phantom_gamma_book(fresh_db):
    cfg = _model_cfg()
    _seed_replay_window("RW6", up_won=1, up_ask="gamma")
    res = replay.replay(cfg, env="mainnet", since_days=60)
    assert res["n"] == 0 and res["windowsScanned"] == 1


def test_replay_gate_blocks_low_prob(fresh_db):
    cfg = _model_cfg()
    _seed_replay_window("RW4", up_won=1, model_prob=0.80)
    res = replay.replay(cfg, env="mainnet", since_days=60)
    assert res["n"] == 0 and res["windowsScanned"] == 1


def test_replay_missing_rule_fields_fail_closed_with_caveat(fresh_db):
    cfg = merge_with_defaults({
        "crypto15mEnabled": True, "crypto15mUseRules": True,
        "crypto15mRules": [{"field": "bookImbalance", "op": ">=", "value": 0.5}],
    })
    _seed_replay_window("RW5", up_won=1)
    res = replay.replay(cfg, env="mainnet", since_days=60)
    assert res["n"] == 0
    assert any("bookImbalance" in c for c in res["caveats"])


def test_fm_extreme_divergence_refused():
    ok, why = c15t.should_enter(
        _asset(minsLeft=0.5, modelProb=0.001, downAsk=0.01, upAsk=0.99),
        _model_cfg(),
        has_open=False, open_count=0,
    )
    assert not ok and "final minute" in why and "distrusting" in why


def test_fm_documented_gap_range_still_allowed():
    ok, why = c15t.should_enter(
        _asset(minsLeft=0.5, modelProb=0.999, upAsk=0.40),
        _model_cfg(),
        has_open=False, open_count=0,
    )
    assert ok, why


def test_fm_gap_cap_configurable_off():
    ok, why = c15t.should_enter(
        _asset(minsLeft=0.5, modelProb=0.001, downAsk=0.01, upAsk=0.99),
        _model_cfg(crypto15mModelFmMaxBookGapCents=0),
        has_open=False, open_count=0,
    )
    assert ok, why
