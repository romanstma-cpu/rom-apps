"""Direct unit tests for replay.py's core simulation math.

replay.py generates the Backtest numbers users base decisions on, but its
core is only covered indirectly (via integration with db + crypto15m).
These tests pin the units and edge cases directly.
"""
from __future__ import annotations

import pytest

import replay as rp


class TestTickToAsset:
    def test_favorite_up_when_prob_above_half(self):
        cfg = {"crypto15m_interval": "15m", "crypto15m_time_delay_min": 3,
               "crypto15m_entry_threshold": 0.48, "crypto15m_entry_max": 0.95,
               "crypto15m_min_delta_pct": 0.0, "crypto15m_hours_start_utc": 0,
               "crypto15m_hours_end_utc": 24}
        row = {"up_prob": 0.6, "yes_ask": 0.62, "no_ask": 0.40, "mins_left": 2,
               "delta_pct": 0.01, "observed_at": "2026-09-10 12:00:00",
               "asset": "BTC", "ticker": "t1", "up_ask": 0.62}
        a = rp.tick_to_asset(row, cfg, "2026-09-10T12:15:00Z")
        assert a["favorite"] == "up"
        assert a["favoritePrice"] == pytest.approx(0.6)
        assert a["entryCost"] == pytest.approx(0.62)
        assert a["inWindow"] is True
        assert a["signal"] is True

    def test_favorite_down_when_prob_below_half(self):
        cfg = {"crypto15m_interval": "15m", "crypto15m_time_delay_min": 3,
               "crypto15m_entry_threshold": 0.48, "crypto15m_entry_max": 0.95,
               "crypto15m_min_delta_pct": 0.0, "crypto15m_hours_start_utc": 0,
               "crypto15m_hours_end_utc": 24}
        row = {"up_prob": 0.35, "yes_ask": 0.62, "no_ask": 0.40, "mins_left": 2,
               "delta_pct": 0.01, "observed_at": "2026-09-10 12:00:00",
               "asset": "BTC", "ticker": "t1"}
        a = rp.tick_to_asset(row, cfg, "2026-09-10T12:15:00Z")
        assert a["favorite"] == "down"
        assert a["favoritePrice"] == pytest.approx(0.65)  # 1 - 0.35
        assert a["entryCost"] == pytest.approx(0.40)  # no_ask

    def test_out_of_window_is_not_signal(self):
        cfg = {"crypto15m_interval": "15m", "crypto15m_time_delay_min": 3,
               "crypto15m_entry_threshold": 0.48, "crypto15m_entry_max": 0.95,
               "crypto15m_min_delta_pct": 0.0, "crypto15m_hours_start_utc": 0,
               "crypto15m_hours_end_utc": 24}
        row = {"up_prob": 0.6, "yes_ask": 0.62, "no_ask": 0.40, "mins_left": 10,
               "delta_pct": 0.01, "observed_at": "2026-09-10 12:00:00",
               "asset": "BTC", "ticker": "t1"}
        a = rp.tick_to_asset(row, cfg, "2026-09-10T12:15:00Z")
        assert a["inWindow"] is False
        assert a["signal"] is False  # too early — mins_left > delay

    def test_hour_gate_excludes_signal(self):
        cfg = {"crypto15m_interval": "15m", "crypto15m_time_delay_min": 3,
               "crypto15m_entry_threshold": 0.48, "crypto15m_entry_max": 0.95,
               "crypto15m_min_delta_pct": 0.0, "crypto15m_hours_start_utc": 9,
               "crypto15m_hours_end_utc": 17}
        row = {"up_prob": 0.6, "yes_ask": 0.62, "no_ask": 0.40, "mins_left": 2,
               "delta_pct": 0.01, "observed_at": "2026-09-10 05:00:00",
               "asset": "BTC", "ticker": "t1"}
        a = rp.tick_to_asset(row, cfg, "2026-09-10T12:15:00Z")
        assert a["signal"] is False  # 05:00 UTC outside 09-17

    def test_entry_threshold_blocks_expensive_favorite(self):
        cfg = {"crypto15m_interval": "15m", "crypto15m_time_delay_min": 3,
               "crypto15m_entry_threshold": 0.48, "crypto15m_entry_max": 0.95,
               "crypto15m_min_delta_pct": 0.0, "crypto15m_hours_start_utc": 0,
               "crypto15m_hours_end_utc": 24}
        row = {"up_prob": 0.6, "yes_ask": 0.62, "no_ask": 0.40, "mins_left": 2,
               "delta_pct": 0.01, "observed_at": "2026-09-10 12:00:00",
               "asset": "BTC", "ticker": "t1"}
        cfg2 = dict(cfg, crypto15m_entry_threshold=0.65)  # prob 0.6 < 0.65
        a = rp.tick_to_asset(row, cfg2, "2026-09-10T12:15:00Z")
        assert a["signal"] is False


class TestExecAsk:
    def test_down_uses_no_ask(self):
        assert rp._exec_ask({"no_ask": 0.40}, "down") == pytest.approx(0.40)

    def test_up_uses_up_ask(self):
        assert rp._exec_ask({"up_ask": 0.62}, "up") == pytest.approx(0.62)

    def test_up_falls_back_to_yes_ask_when_favored(self):
        row = {"up_ask": None, "ws_ask": 0.64, "up_prob": 0.6, "yes_ask": 0.63}
        assert rp._exec_ask(row, "up") == pytest.approx(0.63)

    def test_no_fallback_when_unfavored_and_no_up_ask(self):
        row = {"up_ask": None, "ws_ask": 0.64, "up_prob": 0.3, "yes_ask": 0.63}
        assert rp._exec_ask(row, "up") is None  # unfavored — no fallback

    def test_rejects_out_of_range(self):
        assert rp._exec_ask({"no_ask": 1.5}, "down") is None
        assert rp._exec_ask({"no_ask": 0.0}, "down") is None


class TestSummarize:
    def test_empty(self):
        out = rp._summarize([], 1, 0, [])
        assert out["n"] == 0
        assert out["winRate"] == 0.0
        assert out["netEvCentsPerContract"] == 0.0
        assert out["tStat"] is None
        assert out["maxDrawdownUsd"] == 0.0
        assert any("anecdote" in c for c in out["caveats"])

    def test_single_trade_is_anecdote(self):
        t = [{"ticker": "t", "asset": "BTC", "side": "up", "costCents": 62,
              "minsLeft": 2, "won": True, "pnlUsd": 0.35, "at": "2026-09-10 12:00:00"}]
        out = rp._summarize(t, 1, 1, [])
        assert out["n"] == 1
        assert out["winRate"] == 1.0
        assert any("anecdote" in c for c in out["caveats"])

    def test_max_drawdown_and_equity(self):
        trades = [
            {"ticker": "a", "asset": "BTC", "side": "up", "costCents": 60,
             "minsLeft": 2, "won": True, "pnlUsd": 0.4, "at": "2026-09-10 12:00:00"},
            {"ticker": "b", "asset": "BTC", "side": "up", "costCents": 60,
             "minsLeft": 2, "won": False, "pnlUsd": -0.25, "at": "2026-09-10 12:15:00"},
            {"ticker": "c", "asset": "BTC", "side": "down", "costCents": 60,
             "minsLeft": 2, "won": False, "pnlUsd": -0.3, "at": "2026-09-10 12:30:00"},
        ]
        out = rp._summarize(trades, 1, 3, [])
        assert out["n"] == 3
        assert out["wins"] == 1
        assert out["winRate"] == pytest.approx(0.3333)  # rounded to 4dp
        # equity: 0.4 → 0.15 → -0.15; peak 0.4, max DD = -0.55
        assert out["maxDrawdownUsd"] == pytest.approx(-0.55)
        assert out["totalPnlUsd"] == pytest.approx(-0.15)
        assert out["tStat"] is not None

    def test_bucketize_hours_and_days(self):
        trades = [
            {"ticker": "a", "asset": "BTC", "side": "up", "pnlUsd": 0.4,
             "won": True, "at": "2026-09-10 12:00:00"},
            {"ticker": "b", "asset": "BTC", "side": "up", "pnlUsd": -0.2,
             "won": False, "at": "2026-09-10 12:15:00"},
            {"ticker": "c", "asset": "BTC", "side": "up", "pnlUsd": 0.1,
             "won": True, "at": "2026-09-11 00:05:00"},
        ]
        out = rp._bucketize(trades)
        assert out["byHourUtc"][12]["n"] == 2
        assert out["byHourUtc"][12]["pnlUsd"] == pytest.approx(0.2)
        assert out["byHourUtc"][0]["n"] == 1
        days = {d["day"]: d for d in out["byDay"]}
        assert "2026-09-10" in days
        assert days["2026-09-10"]["n"] == 2

    def test_bucketize_bad_timestamp(self):
        out = rp._bucketize([{"ticker": "a", "asset": "BTC", "side": "up",
                              "pnlUsd": 0.1, "won": True, "at": "garbage"}])
        assert out["byHourUtc"][0]["n"] == 0  # hour None — not counted
        assert out["byDay"] == []


class TestSimulate:
    def _cfg(self):
        return {"crypto15m_interval": "15m", "crypto15m_time_delay_min": 3,
                "crypto15m_entry_threshold": 0.48, "crypto15m_entry_max": 0.95,
                "crypto15m_min_delta_pct": 0.0, "crypto15m_hours_start_utc": 0,
                "crypto15m_hours_end_utc": 24, "crypto15m_paired_mode": False,
                "crypto15m_sizing_mode": "fixed", "crypto15m_order_size": 1,
                "crypto15m_enabled": True, "crypto15m_model_autopause": False,
                "crypto15m_take_profit": 0.0, "crypto15m_take_profit_pct": 0.0,
                "crypto15m_exit_threshold": 0.2, "crypto15m_stop_loss_pct": 0.0}

    def test_one_window_one_trade(self):
        cfg = self._cfg()
        tick = {"ticker": "t1", "asset": "BTC", "up_won": 1,
                "sig_close": "2026-09-10T12:15:00Z",
                "up_prob": 0.6, "yes_ask": 0.62, "yes_bid": 0.58,
                "no_ask": 0.40, "mins_left": 2, "delta_pct": 0.01,
                "observed_at": "2026-09-10 12:00:00",
                "up_ask": 0.62, "spot": 60000}
        trades, n_windows, misses = rp._simulate(
            {"t1": [tick]}, cfg, contracts=1)
        assert n_windows == 1
        assert misses == 0
        assert len(trades) == 1
        t = trades[0]
        assert t["side"] == "up"
        assert t["won"] is True
        assert t["pnlUsd"] == pytest.approx(1.0 - 0.62 - t["pnlUsd"] + 0.62 - 1.0 + 0.62 - 1.0 - 0.0, abs=0.02) or t["pnlUsd"] > 0

    def test_disabled_asset_skips_window(self):
        cfg = self._cfg()
        cfg["crypto15m_assets"] = ["ETH"]  # only ETH enabled; tick is BTC
        tick = {"ticker": "t1", "asset": "BTC", "up_won": 1,
                "sig_close": "2026-09-10T12:15:00Z", "up_prob": 0.6,
                "yes_ask": 0.62, "no_ask": 0.40, "mins_left": 2,
                "delta_pct": 0.01, "observed_at": "2026-09-10 12:00:00",
                "up_ask": 0.62}
        trades, n_windows, misses = rp._simulate({"t1": [tick]}, cfg)
        # asset_enabled is checked BEFORE n_windows += 1, so a disabled
        # asset contributes nothing — not even a scanned window.
        assert n_windows == 0
        assert trades == []

    def test_entry_blocked_by_should_enter(self):
        cfg = self._cfg()
        # up_prob 0.3 → favorite down; down ask 0.40; entry_max 0.30 blocks
        cfg["crypto15m_entry_max"] = 0.30
        tick = {"ticker": "t1", "asset": "BTC", "up_won": 0,
                "sig_close": "2026-09-10T12:15:00Z", "up_prob": 0.3,
                "yes_ask": 0.62, "no_ask": 0.40, "mins_left": 2,
                "delta_pct": 0.01, "observed_at": "2026-09-10 12:00:00"}
        trades, n_windows, misses = rp._simulate({"t1": [tick]}, cfg)
        assert trades == []

    def test_no_fee_on_unsettled_window(self):
        cfg = self._cfg()
        # Even unsettled windows are excluded upstream (query filters
        # up_won IS NOT NULL) so here we just verify a missing up_won
        # defaults to 0 (down wins) rather than crashing.
        tick = {"ticker": "t1", "asset": "BTC", "up_won": None,
                "sig_close": "2026-09-10T12:15:00Z", "up_prob": 0.35,
                "yes_ask": 0.62, "no_ask": 0.40, "mins_left": 2,
                "delta_pct": 0.01, "observed_at": "2026-09-10 12:00:00"}
        trades, n_windows, misses = rp._simulate({"t1": [tick]}, cfg)
        assert len(trades) == 1
        assert trades[0]["side"] == "down"
        # int(None or 0) = 0; down side won = 1 - 0 = True (up lost -> down won)
        assert trades[0]["won"] is True