"""Crypto 15m pricing model: prob, edge, fees, and the entry signal gate.

model_up_prob / model_edge_net_cents / _fee_cents price every crypto entry
and exit. They were untested. These tests characterise the contracts:
- None propagates (no silent numeric edge)
- bounds are clamped
- fees make the edge worse and are schedule-aware
- resignal_asset is a strict AND gate over window/threshold/cost/delta/hours
"""
from __future__ import annotations

import math

import pytest

import crypto15m as c


class TestNormCdf:
    def test_monotonic(self):
        assert c._norm_cdf(-3) < c._norm_cdf(0) < c._norm_cdf(3)

    def test_symmetric_around_half(self):
        assert abs(c._norm_cdf(-1) + c._norm_cdf(1) - 1.0) < 1e-9
        assert abs(c._norm_cdf(0) - 0.5) < 1e-9

    def test_bounds(self):
        assert 0 <= c._norm_cdf(-10) <= 1e-6
        assert c._norm_cdf(10) >= 1 - 1e-6


class TestFeeCents:
    def test_zero_when_disabled(self):
        assert c._fee_cents(50, {"enabled": False}) == 0.0

    def test_positive_when_enabled(self):
        f = c._fee_cents(50, {"enabled": True})
        assert f > 0

    def test_peaks_at_50_cents(self):
        # fee = rate * (p(1-p))^exp * 100 — maximal at p=0.5
        at_50 = c._fee_cents(50)
        at_10 = c._fee_cents(10)
        at_90 = c._fee_cents(90)
        assert at_50 > at_10
        assert at_50 > at_90

    def test_symmetric(self):
        assert abs(c._fee_cents(30) - c._fee_cents(70)) < 1e-9

    def test_custom_rate(self):
        assert c._fee_cents(50, {"rate": 0.14}) > c._fee_cents(50, {"rate": 0.07})

    def test_clamps_out_of_range(self):
        # price 0 or 100 clamps to 0.01/0.99 -> fee nonzero, no crash
        f0 = c._fee_cents(0)
        f100 = c._fee_cents(100)
        assert math.isfinite(f0) and math.isfinite(f100)
        assert f0 > 0 and f100 > 0

    def test_default_schedule_enabled(self):
        assert c._fee_cents(50, None) == c._fee_cents(50, {"enabled": True})


class TestModelUpProb:
    def test_none_any_input(self):
        assert c.model_up_prob(None, 100, 0.01, 5) is None
        assert c.model_up_prob(100, None, 0.01, 5) is None
        assert c.model_up_prob(100, 100, None, 5) is None
        assert c.model_up_prob(100, 100, 0.01, None) is None

    def test_at_strike_is_half(self):
        p = c.model_up_prob(100, 100, 0.02, 5)
        assert p is not None
        assert abs(p - 0.5) < 0.05  # mean == strike, t-total => 0.5

    def test_above_strike_higher(self):
        above = c.model_up_prob(105, 100, 0.02, 5)
        below = c.model_up_prob(95, 100, 0.02, 5)
        assert above is not None and below is not None
        assert above > below

    def test_higher_sigma_flattens(self):
        tight = c.model_up_prob(104, 100, 0.01, 5)
        loose = c.model_up_prob(104, 100, 0.10, 5)
        assert tight > loose

    def test_more_time_closer_to_half(self):
        short = c.model_up_prob(104, 100, 0.02, 1)
        long = c.model_up_prob(104, 100, 0.02, 60)
        assert abs(short - 0.5) > abs(long - 0.5)

    def test_bounds_are_clamped(self):
        p = c.model_up_prob(1e9, 0.0001, 1e-9, 0.05)
        assert p is not None and 0 <= p <= 1

    def test_nonpositive_inputs_none(self):
        assert c.model_up_prob(0, 100, 0.01, 5) is None
        assert c.model_up_prob(100, 0, 0.01, 5) is None
        assert c.model_up_prob(100, 100, 0, 5) is None


class TestModelEdgeNetCents:
    def test_none_prob(self):
        assert c.model_edge_net_cents(None, 0.5, 0.5) is None

    def test_both_quotes_available(self):
        e = c.model_edge_net_cents(0.6, 0.5, 0.5)
        assert e is not None
        # NO ask 0.51 would be -1; YES ask 0.49 would be +0.x with fee
        # up edge dominates: 60 - ask - fee
        assert e > 0

    def test_single_quote(self):
        e = c.model_edge_net_cents(0.6, 0.5, None)
        assert e is not None
        assert e > 0

    def test_fee_reduces_edge(self):
        # Fees are charged by default (None schedule == enabled);
        # an explicitly disabled schedule must give a bigger edge.
        no_fee = c.model_edge_net_cents(0.6, 0.55, 0.55, {"enabled": False})
        fee = c.model_edge_net_cents(0.6, 0.55, 0.55, {"enabled": True})
        assert no_fee is not None and fee is not None
        assert no_fee > fee

    def test_no_valid_quotes(self):
        assert c.model_edge_net_cents(0.6, None, None) is None
        assert c.model_edge_net_cents(0.6, 0, 0) is None
        assert c.model_edge_net_cents(0.6, -0.1, 1.5) is None

    def test_edge_reflects_prob_minus_ask(self):
        # up_prob 0.8, yes ask 0.7 => edge ≈ +10 (minus fee)
        e = c.model_edge_net_cents(0.8, 0.7, None, {"enabled": False})
        assert e is not None
        assert abs(e - 10.0) < 0.5


class TestResignalAsset:
    BASE_CFG = {
        "crypto15m_time_delay_min": 8.0,
        "crypto15m_entry_threshold": 0.95,
        "crypto15m_entry_max": 0.98,
        "crypto15m_min_delta_pct": 0.0,
    }

    def _ok(self, **overrides):
        a = {
            "minsLeft": 5.0,
            "favoritePrice": 0.97,
            "entryCost": 0.50,
            "deltaPct": 1.0,
            "hourUtc": 12,
        }
        a.update(overrides)
        return a

    def test_all_conditions_pass(self):
        a = c.resignal_asset(self._ok(), self.BASE_CFG)
        assert a["signal"] is True
        assert a["inWindow"] is True

    def test_out_of_window_no_signal(self):
        a = c.resignal_asset(self._ok(minsLeft=9.0), self.BASE_CFG)
        assert a["inWindow"] is False
        assert a["signal"] is False

    def test_below_threshold_no_signal(self):
        a = c.resignal_asset(self._ok(favoritePrice=0.90), self.BASE_CFG)
        assert a["signal"] is False

    def test_entry_cost_above_max_no_signal(self):
        cfg = dict(self.BASE_CFG, crypto15m_entry_max=0.60)
        a = c.resignal_asset(self._ok(entryCost=0.80), cfg)
        assert a["signal"] is False

    def test_none_entry_cost_allowed(self):
        a = c.resignal_asset(self._ok(entryCost=None), self.BASE_CFG)
        assert a["signal"] is True

    def test_delta_below_min_no_signal(self):
        cfg = dict(self.BASE_CFG, crypto15m_min_delta_pct=0.5)
        a = c.resignal_asset(self._ok(deltaPct=0.1), cfg)
        assert a["signal"] is False

    def test_none_delta_allowed(self):
        cfg = dict(self.BASE_CFG, crypto15m_min_delta_pct=0.5)
        a = c.resignal_asset(self._ok(deltaPct=None), cfg)
        assert a["signal"] is True

    def test_hours_blocked_no_signal(self):
        cfg = dict(self.BASE_CFG, crypto15m_hours_start_utc=20, crypto15m_hours_end_utc=8)
        a = c.resignal_asset(self._ok(hourUtc=12), cfg)
        assert a["signal"] is False


class TestAssetEnabled:
    def test_no_asset_list_allows_all(self):
        assert c.asset_enabled({}, "btc") is True

    def test_empty_asset_list_blocks_all(self):
        assert c.asset_enabled({"crypto15m_assets": []}, "btc") is False

    def test_case_insensitive(self):
        cfg = {"crypto15m_assets": ["BTC"]}
        assert c.asset_enabled(cfg, "btc") is True
        assert c.asset_enabled(cfg, "eth") is False

    def test_case_insensitive_lookup(self):
        cfg = {"crypto15m_assets": ["BTC", "ETH"]}
        assert c.asset_enabled(cfg, "btc") is True
        assert c.asset_enabled(cfg, "eth") is True


class TestHoursOk:
    def test_default_all_hours(self):
        assert c.hours_ok({}) is True
        assert c.hours_ok({}, hour=0) is True
        assert c.hours_ok({}, hour=23) is True

    def test_midnight_to_8(self):
        cfg = {"crypto15m_hours_start_utc": 20, "crypto15m_hours_end_utc": 8}
        assert c.hours_ok(cfg, hour=23) is True
        assert c.hours_ok(cfg, hour=3) is True
        assert c.hours_ok(cfg, hour=12) is False

    def test_bad_config_defaults_true(self):
        assert c.hours_ok({"crypto15m_hours_start_utc": "x"}) is True


class TestHourOverride:
    def test_returns_cfg_when_no_configs(self):
        assert c.hour_override({}, hour=5) == {}

    def test_override_merges(self):
        cfg = {"crypto15m_hour_configs": {"5": {"crypto15m_entry_threshold": 0.99}}}
        merged = c.hour_override(cfg, hour=5)
        assert merged["crypto15m_entry_threshold"] == 0.99

    def test_missing_hour_returns_none(self):
        cfg = {"crypto15m_hour_configs": {"5": {}}}
        assert c.hour_override(cfg, hour=6) is None

    def test_hour_override_returns_cfg_when_no_configs_key(self):
        cfg = {"some_key": "some_value"}
        assert c.hour_override(cfg) == cfg