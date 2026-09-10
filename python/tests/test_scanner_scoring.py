"""Scanner scoring heuristics: purity, bounds, direction, and clamping.

These functions gate what the bot trades, so their input/output contracts
deserve characterisation tests even though the constants are heuristic.
"""
from __future__ import annotations

import pytest

import scanner
from scanner import (
    _parse_days_to_close,
    compute_momentum_confidence,
    compute_whale_score,
)


class TestWhaleScore:
    def test_returns_float_in_valid_range_for_any_input(self):
        for price in (0.01, 0.35, 0.5, 0.65, 0.8, 0.9, 0.99):
            for side in ("yes", "no"):
                score = compute_whale_score(100, price, side)
                assert 0 <= score <= 100
                assert isinstance(score, (float, int))

    def test_clamped_to_ceil_97(self):
        score = compute_whale_score(1e9, 0.95, "yes", market_volume=1e9, open_interest=1e9)
        assert score <= 97.0

    def test_clamped_to_floor_5(self):
        score = compute_whale_score(1, 0.99, "yes", category="")
        assert score >= 5.0

    def test_yes_taker_gains_more_on_high_price_than_no(self):
        yes = compute_whale_score(5000, 0.85, "yes")
        no = compute_whale_score(5000, 0.85, "no")
        assert yes > no

    def test_no_taker_gains_more_around_50(self):
        no = compute_whale_score(5000, 0.5, "no")
        yes = compute_whale_score(5000, 0.5, "yes")
        assert no > yes

    def test_dollar_value_adds_edge(self):
        small = compute_whale_score(100, 0.5, "yes")
        big = compute_whale_score(30_000, 0.5, "yes")
        assert big >= small

    def test_volume_tier_adds_edge(self):
        thin = compute_whale_score(100, 0.5, "yes", market_volume=500)
        thick = compute_whale_score(100, 0.5, "yes", market_volume=300_000)
        assert thick > thin

    def test_days_to_close_window_bonus(self):
        soon = compute_whale_score(100, 0.5, "yes", days_to_close=0.5)
        far = compute_whale_score(100, 0.5, "yes", days_to_close=90)
        assert soon > far

    def test_none_days_to_close_is_neutral(self):
        base = compute_whale_score(100, 0.5, "yes", days_to_close=None)
        assert 5 <= base <= 100


class TestMomentumConfidence:
    BASE = dict(
        volume_spike_ratio=2.5,
        price_change_abs=0.05,
        trade_cluster_count=5,
        trade_cluster_dollars=600,
        market_volume=20_000,
        open_interest=5_000,
        days_to_close=3.0,
        price=0.40,
        direction="yes",
        signal_type="trade_cluster",
    )

    def test_default_shape(self):
        s = compute_momentum_confidence(**self.BASE)
        assert isinstance(s, float)
        assert 0 <= s <= 100

    def test_no_direction_uses_yes_price_implied(self):
        base = self.BASE
        yes = compute_momentum_confidence(**{**base, "price": 0.40, "direction": "yes"})
        no = compute_momentum_confidence(**{**base, "price": 0.40, "direction": "no"})
        # Both imply 40%; NO at 0.40 implies 60%, so scores should differ
        assert abs(no - yes) > 1

    def test_low_price_no_gets_trade_cluster_bonus(self):
        base = self.BASE
        # Price 0.10 → implied win prob is HIGH for NO (90%), so NO
        # should outscore YES at the same cheap price.
        low_no = compute_momentum_confidence(**{**base, "price": 0.10, "direction": "no"})
        low_yes = compute_momentum_confidence(**{**base, "price": 0.10, "direction": "yes"})
        assert low_no > low_yes

    def test_symmetric_high_price_yes_bonus(self):
        base = self.BASE
        high_yes = compute_momentum_confidence(**{**base, "price": 0.90, "direction": "yes"})
        high_no = compute_momentum_confidence(**{**base, "price": 0.90, "direction": "no"})
        assert high_yes > high_no

    def test_confidence_rises_with_favorability(self):
        base = self.BASE
        # Favorability = implied win prob. YES at 0.90 >> YES at 0.10.
        yes_fav = compute_momentum_confidence(**{**base, "price": 0.90, "direction": "yes"})
        yes_ugly = compute_momentum_confidence(**{**base, "price": 0.10, "direction": "yes"})
        assert yes_fav > yes_ugly

    def test_cluster_count_tier(self):
        base = self.BASE
        c1 = compute_momentum_confidence(**{**base, "trade_cluster_count": 2})
        c2 = compute_momentum_confidence(**{**base, "trade_cluster_count": 20})
        assert c2 >= c1

    def test_dollars_tier(self):
        base = self.BASE
        d1 = compute_momentum_confidence(**{**base, "trade_cluster_dollars": 100})
        d2 = compute_momentum_confidence(**{**base, "trade_cluster_dollars": 6000})
        assert d2 >= d1

    def test_volume_spike_tier(self):
        base = self.BASE
        v1 = compute_momentum_confidence(**{**base, "volume_spike_ratio": 1.0})
        v2 = compute_momentum_confidence(**{**base, "volume_spike_ratio": 6.0})
        assert v2 >= v1

    def test_price_move_tier(self):
        base = self.BASE
        p1 = compute_momentum_confidence(**{**base, "price_change_abs": 0.02})
        p2 = compute_momentum_confidence(**{**base, "price_change_abs": 0.20})
        assert p2 >= p1

    def test_clamped_bounds(self):
        base = self.BASE
        s = compute_momentum_confidence(**{**base, "price": 0.99, "direction": "yes",
                                           "volume_spike_ratio": 1e9, "price_change_abs": 1.0,
                                           "trade_cluster_count": 1e9, "trade_cluster_dollars": 1e9,
                                           "market_volume": 1e9, "open_interest": 1e9})
        assert s <= 97.0


class TestParseDaysToClose:
    def test_iso_with_microseconds(self):
        from datetime import datetime, timedelta, timezone
        future = datetime.now(timezone.utc) + timedelta(days=2)
        d = _parse_days_to_close(future.strftime("%Y-%m-%dT%H:%M:%S.%fZ"))
        assert d is not None and 1.5 < d < 2.5

    def test_iso_no_microseconds(self):
        from datetime import datetime, timedelta, timezone
        future = datetime.now(timezone.utc) + timedelta(hours=12)
        d = _parse_days_to_close(future.strftime("%Y-%m-%dT%H:%M:%SZ"))
        assert d is not None and 0.3 < d < 0.7

    def test_iso_with_offset(self):
        d = _parse_days_to_close("2099-01-01T00:00:00+00:00")
        assert d is not None and d > 0

    def test_empty_and_garbage(self):
        assert _parse_days_to_close("") is None
        assert _parse_days_to_close("not-a-date") is None
        assert _parse_days_to_close(None) is None

    def test_past_clamped_to_zero(self):
        from datetime import datetime, timedelta, timezone
        past = datetime.now(timezone.utc) - timedelta(days=1)
        d = _parse_days_to_close(past.strftime("%Y-%m-%dT%H:%M:%SZ"))
        assert d == 0.0