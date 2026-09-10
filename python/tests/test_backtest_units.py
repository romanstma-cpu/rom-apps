"""Focused unit tests for the pure Backtest helper functions.

Picks up where test_backtest.py / test_fees_us.py / test_portfolio_backtest.py
leave off: this file pins the date/time parsing (epoch_of / tick_epoch, both
recording formats), the exact US fee boundaries (per-price values, the
unrounded-vs-rounded-cents split, and the theta switch at
2026-07-01T04:00:00Z), the remaining signal_cost clamps, and the pure sizing /
accounting helpers in portfolio_backtest (_pricing_at, _day_index,
_edge_points, _limit_cents, _max_drawdown).

All values below are hard numbers derived from the source constants in
fees_us.SCHEDULES: theta = 0.05 from 2026-04-03T19:00:00Z, theta = 0.06 from
2026-07-01T04:00:00Z, fee = theta * P * (1 - P) per contract. The US schedule
is a flat per-window theta - there is no price-tiering; the only "tiers" are
the two date-bounded coefficients.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import backtest as bt
import fees_us
import portfolio_backtest as pb

APRIL_START = datetime(2026, 4, 3, 19, tzinfo=timezone.utc)   # earliest schedule
JULY_SWITCH = datetime(2026, 7, 1, 4, tzinfo=timezone.utc)    # theta 0.06 from here
SECOND = timedelta(seconds=1)


# --- the schedule itself -------------------------------------------------


def test_us_schedule_is_flat_theta_with_two_dated_windows():
    # No price-tiering on the US schedule; the only switch is the dated
    # coefficient change. Pin the published windows to the exact instants.
    assert [(float(start), float(v)) for start, v in fees_us.SCHEDULES] == [
        (APRIL_START.timestamp(), 0.05),
        (JULY_SWITCH.timestamp(), 0.06),
    ]


# --- us_fee_per_contract: exact boundaries -------------------------------


def test_us_fee_switches_exactly_at_the_july_boundary():
    before = (JULY_SWITCH - SECOND).timestamp()
    at = JULY_SWITCH.timestamp()
    after = (JULY_SWITCH + SECOND).timestamp()
    # theta 0.05 / 4 at P=0.50 -> 0.0125; 0.06 / 4 -> 0.015 from the switch.
    assert bt.us_fee_per_contract(0.50, before) == pytest.approx(0.0125)
    assert bt.us_fee_per_contract(0.50, at) == pytest.approx(0.0150)
    assert bt.us_fee_per_contract(0.50, after) == pytest.approx(0.0150)


def test_us_fee_april_window_hard_numbers():
    at = (APRIL_START + timedelta(days=1)).timestamp()
    assert bt.us_fee_per_contract(0.50, at) == pytest.approx(0.0125)  # 0.05/4
    assert bt.us_fee_per_contract(0.90, at) == pytest.approx(0.0045)  # 0.05*0.9*0.1


@pytest.mark.parametrize("price,expected", [
    (0.01, 0.000594),   # 0.06 * 0.01 * 0.99
    (0.10, 0.005400),   # 0.06 * 0.10 * 0.90
    (0.25, 0.011250),   # 0.06 * 0.25 * 0.75
    (0.50, 0.015000),   # 0.06 * 0.50 * 0.50
    (0.60, 0.014400),   # 0.06 * 0.60 * 0.40
    (0.75, 0.011250),   # 0.06 * 0.75 * 0.25
    (0.90, 0.005400),   # 0.06 * 0.90 * 0.10
    (0.99, 0.000594),   # 0.06 * 0.99 * 0.01
])
def test_us_fee_hard_numbers_at_common_prices(price, expected):
    assert bt.us_fee_per_contract(price, JULY_SWITCH.timestamp()) == pytest.approx(expected)


def test_us_fee_is_symmetric_around_the_midpoint():
    at = JULY_SWITCH.timestamp()
    for p in (0.05, 0.2, 0.35, 0.9):
        assert bt.us_fee_per_contract(p, at) == pytest.approx(
            bt.us_fee_per_contract(1.0 - p, at))


def test_us_fee_clamps_out_of_range_prices():
    at = JULY_SWITCH.timestamp()
    assert bt.us_fee_per_contract(-0.25, at) == pytest.approx(0.0)
    assert bt.us_fee_per_contract(1.25, at) == pytest.approx(0.0)
    assert bt.us_fee_per_contract(0.0, at) == pytest.approx(0.0)
    assert bt.us_fee_per_contract(1.0, at) == pytest.approx(0.0)


def test_us_fee_fallback_uses_the_earliest_theta():
    # Signals older than any published schedule price at theta 0.05
    # (test_backtest covers P=0.5; pin a second price point here).
    assert bt.us_fee_per_contract(0.90, 0.0) == pytest.approx(0.0045)
    assert bt.us_fee_per_contract(0.90, 1.0) == pytest.approx(0.0045)


def test_us_fee_is_unrounded_while_fees_us_rounds_to_cents():
    """Per-contract backtests use the exact theta*P*(1-P); order charging in
    fees_us rounds to cents (HALF_EVEN). Both must stay in agreement."""
    at = JULY_SWITCH.timestamp()
    theta06 = float(fees_us.SCHEDULES[1][1])
    assert bt.us_fee_per_contract(0.60, at) == pytest.approx(theta06 * 0.6 * 0.4)  # 0.0144
    assert fees_us.fee(1, 0.60, at) == pytest.approx(0.01)
    assert fees_us.fee(10, 0.60, at) == pytest.approx(0.14)  # 0.144 -> HALF_EVEN
    assert bt.us_fee_per_contract(0.60, at) > fees_us.fee(1, 0.60, at)


def test_affordable_contracts_fifty_dollar_budget_at_half_dollar():
    # $50 budget, 52c reserved per contract (50c + 2c fee rounded UP), so
    # 96 fit and the 97th breaks the budget; the 96-fill costs 49.44.
    at = JULY_SWITCH.timestamp()
    assert fees_us.affordable_contracts(50.0, 0.50, at) == 96
    assert fees_us.reserved_cost(96, 0.50, at) <= 50.0
    assert fees_us.reserved_cost(97, 0.50, at) > 50.0
    assert 96 * 0.50 + fees_us.fee(96, 0.50, at) == pytest.approx(49.44)


# --- outcome settlement math --------------------------------------------


def test_net_pnl_at_the_switch_boundary():
    before = (JULY_SWITCH - SECOND).timestamp()
    at = JULY_SWITCH.timestamp()
    # gross 0.50 - fee (0.0125 April / 0.015 July)
    assert bt.net_pnl_per_contract(0.50, True, before) == pytest.approx(0.4875)
    assert bt.net_pnl_per_contract(0.50, True, at) == pytest.approx(0.4850)


def test_net_pnl_loss_charges_the_fee_on_top():
    at = JULY_SWITCH.timestamp()
    assert bt.net_pnl_per_contract(0.50, False, at) == pytest.approx(-0.5150)


def test_net_pnl_holds_the_identity_unrounded_fee():
    at = JULY_SWITCH.timestamp()
    theta06 = float(fees_us.SCHEDULES[1][1])
    for cost in (0.15, 0.4, 0.63, 0.88):
        fee = theta06 * cost * (1.0 - cost)
        assert bt.net_pnl_per_contract(cost, True, at) == pytest.approx(1.0 - cost - fee)
        assert bt.net_pnl_per_contract(cost, False, at) == pytest.approx(-cost - fee)


# --- signal_cost clamps --------------------------------------------------


def test_signal_cost_clamps_whale_price():
    assert bt.signal_cost({"price": 1.40}, "whale") == pytest.approx(1.0)
    assert bt.signal_cost({"price": -0.20}, "whale") == pytest.approx(0.0)
    assert bt.signal_cost({"price": 0.62}, "whale") == pytest.approx(0.62)


def test_signal_cost_momentum_inverts_clamps_and_respects_case():
    assert bt.signal_cost({"price": 0.95, "direction": "No"}, "momentum") == pytest.approx(0.05)
    assert bt.signal_cost({"price": 1.40, "direction": "no"}, "momentum") == pytest.approx(0.0)
    assert bt.signal_cost({"price": -0.20, "direction": "yes"}, "momentum") == pytest.approx(0.0)
    # Missing direction defaults to betting YES.
    assert bt.signal_cost({"price": 0.30}, "momentum") == pytest.approx(0.30)


def test_signal_cost_missing_price_is_zero():
    assert bt.signal_cost({}, "whale") == pytest.approx(0.0)
    assert bt.signal_cost({"direction": "no"}, "momentum") == pytest.approx(1.0)


# --- date / time parsing -------------------------------------------------


def test_epoch_of_sqlite_space_format_is_utc():
    # SQLite datetime('now') writes "YYYY-MM-DD HH:MM:SS"; naive means UTC.
    assert bt.epoch_of("2026-07-01 04:00:00") == pytest.approx(JULY_SWITCH.timestamp())


def test_epoch_of_iso_z_format():
    assert bt.epoch_of("2026-07-01T04:00:00Z") == pytest.approx(JULY_SWITCH.timestamp())


def test_epoch_of_both_recorded_formats_agree():
    sqlite = bt.epoch_of("2026-07-01 04:00:00")
    iso = bt.epoch_of("2026-07-01T04:00:00Z")
    assert sqlite == pytest.approx(iso)
    assert iso == pytest.approx(fees_us.SCHEDULES[1][0])  # the actual switch instant


def test_epoch_of_iso_with_explicit_offset():
    assert bt.epoch_of("2026-07-01T04:00:00+00:00") == pytest.approx(JULY_SWITCH.timestamp())
    # A +02:00 stamp is two hours earlier in UTC.
    local = datetime(2026, 7, 1, 4, tzinfo=timezone(timedelta(hours=2)))
    assert bt.epoch_of("2026-07-01T04:00:00+02:00") == pytest.approx(local.timestamp())


def test_epoch_of_fractional_seconds():
    assert bt.epoch_of("2026-07-01T04:00:00.25Z") == pytest.approx(
        JULY_SWITCH.timestamp() + 0.25)


def test_epoch_of_whitespace_is_trimmed():
    assert bt.epoch_of("  2026-07-01 04:00:00  ") == pytest.approx(JULY_SWITCH.timestamp())


def test_epoch_of_garbage_returns_default():
    assert bt.epoch_of(None) == 0.0
    assert bt.epoch_of("") == 0.0
    assert bt.epoch_of("not-a-date") == 0.0
    assert bt.epoch_of(123.0) == 0.0  # epoch floats are not stored timestamps


def test_epoch_of_custom_default():
    assert bt.epoch_of(None, default=7.5) == 7.5
    assert bt.epoch_of("garbage", default=9.0) == 9.0


def test_tick_epoch_reads_observed_at_both_formats():
    sqlite = bt.tick_epoch({"observed_at": "2026-07-01 04:00:00"})
    iso = bt.tick_epoch({"observed_at": "2026-07-01T04:00:00Z"})
    assert sqlite == pytest.approx(JULY_SWITCH.timestamp())
    assert iso == pytest.approx(sqlite)


def test_tick_epoch_missing_or_bad_stamp_defaults():
    assert bt.tick_epoch({}) == 0.0
    assert bt.tick_epoch(None) == 0.0
    assert bt.tick_epoch({"observed_at": None}) == 0.0
    assert bt.tick_epoch({"observed_at": "junk"}) == 0.0
    assert bt.tick_epoch({}, default=11.0) == 11.0


# --- portfolio_backtest pure helpers -------------------------------------


def test_pricing_at_clamps_into_the_published_range():
    assert pb._pricing_at(0.0) == pytest.approx(fees_us.EARLIEST_START)
    assert pb._pricing_at(1.0) == pytest.approx(fees_us.EARLIEST_START)
    mid = JULY_SWITCH.timestamp()
    assert pb._pricing_at(mid) == pytest.approx(mid)
    assert isinstance(pb._pricing_at("1.0"), float) or pb._pricing_at(1.0) > 0


def test_day_index_utc_offset_zero():
    assert pb._day_index(0.0, 0) == 0
    assert pb._day_index(86399.9, 0) == 0
    assert pb._day_index(86400.0, 0) == 1


def test_day_index_honours_the_et_offset():
    # offset -240: the trading day starts at 04:00 UTC.
    assert pb._day_index(14400 - 1, -240) == -1   # 03:59:59 UTC -> previous ET day
    assert pb._day_index(14400, -240) == 0        # 04:00:00 UTC -> day start
    assert pb._day_index(14400 + 86400, -240) == 1


def test_edge_points_matches_trader_clamping():
    # implied probability clamped to [5, 95] before the edge is computed.
    assert pb._edge_points(70.0, 0.50) == pytest.approx(20.0)
    assert pb._edge_points(70.0, 0.97) == pytest.approx(-25.0)  # 70 - 95
    assert pb._edge_points(70.0, 0.02) == pytest.approx(65.0)   # 70 - 5
    assert pb._edge_points(50.0, 0.50) == pytest.approx(0.0)


def test_limit_cents_rounds_and_clamps():
    assert pb._limit_cents(0.50) == 50
    assert pb._limit_cents(0.869) == 87
    assert pb._limit_cents(0.004) == 1    # round to 0 -> floor of 1
    assert pb._limit_cents(0.999) == 99   # round to 100 -> cap of 99
    assert pb._limit_cents(1.50) == 99
    assert pb._limit_cents(-0.50) == 1


def test_max_drawdown_peak_to_trough():
    curve = [(0.0, 100.0), (1.0, 150.0), (2.0, 90.0)]
    assert pb._max_drawdown(curve) == pytest.approx(0.4)  # (150-90)/150
    multi = [(0.0, 50.0), (1.0, 200.0), (2.0, 120.0), (3.0, 180.0)]
    assert pb._max_drawdown(multi) == pytest.approx(0.4)


def test_max_drawdown_empty_and_monotonic():
    assert pb._max_drawdown([]) == 0.0
    assert pb._max_drawdown([(0.0, 100.0)]) == 0.0
    assert pb._max_drawdown([(0.0, 100.0), (1.0, 120.0)]) == 0.0
    assert pb._max_drawdown([(0.0, 100.0), (1.0, 80.0)]) == pytest.approx(0.2)
    assert pb._max_drawdown([(0.0, 0.0), (1.0, 50.0), (2.0, 25.0)]) == pytest.approx(0.5)