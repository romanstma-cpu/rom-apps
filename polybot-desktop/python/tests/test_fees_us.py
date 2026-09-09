from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

import fees_us

APRIL_START = datetime(2026, 4, 3, 19, tzinfo=timezone.utc)
JULY_START = datetime(2026, 7, 1, 4, tzinfo=timezone.utc)
SECOND = timedelta(seconds=1)


# --- schedule selection -------------------------------------------------


def test_coefficient_picks_the_schedule_in_force():
    assert fees_us.coefficient(APRIL_START.timestamp()) == Decimal("0.05")
    assert fees_us.coefficient(JULY_START.timestamp()) == Decimal("0.06")


def test_coefficient_switches_exactly_at_the_july_boundary():
    assert fees_us.coefficient((JULY_START - SECOND).timestamp()) == Decimal("0.05")
    assert fees_us.coefficient(JULY_START.timestamp()) == Decimal("0.06")


def test_coefficient_holds_the_latest_schedule_going_forward():
    far = datetime(2030, 1, 1, tzinfo=timezone.utc)
    assert fees_us.coefficient(far.timestamp()) == Decimal("0.06")


def test_coefficient_refuses_timestamps_before_the_first_known_schedule():
    """Better to fail loudly than to backfill a rate that was never published."""
    with pytest.raises(ValueError, match="No verified US fee schedule"):
        fees_us.coefficient((APRIL_START - SECOND).timestamp())


def test_schedules_are_ordered_so_reversed_lookup_is_correct():
    starts = [start for start, _ in fees_us.SCHEDULES]
    assert starts == sorted(starts)


# --- fee arithmetic -----------------------------------------------------


def test_fee_matches_the_published_formula():
    at = JULY_START.timestamp()
    # 0.06 x 80 x 0.6 x 0.4 = 1.152 -> 1.15
    assert fees_us.fee(80, 0.6, at) == pytest.approx(1.15)
    # 0.05 x 80 x 0.6 x 0.4 = 0.96
    assert fees_us.fee(80, 0.6, APRIL_START.timestamp()) == pytest.approx(0.96)


def test_fee_is_zero_at_the_price_extremes():
    at = JULY_START.timestamp()
    assert fees_us.fee(100, 0.0, at) == 0.0
    assert fees_us.fee(100, 1.0, at) == 0.0


def test_fee_peaks_at_a_coin_flip():
    at = JULY_START.timestamp()
    mid = fees_us.fee(100, 0.5, at)
    assert mid > fees_us.fee(100, 0.3, at)
    assert mid > fees_us.fee(100, 0.7, at)


def test_fee_is_symmetric_around_the_midpoint():
    at = JULY_START.timestamp()
    assert fees_us.fee(50, 0.25, at) == fees_us.fee(50, 0.75, at)


def test_maker_rebate_is_a_credit_and_ignores_the_schedule():
    april = fees_us.fee(100, 0.5, APRIL_START.timestamp(), maker=True)
    july = fees_us.fee(100, 0.5, JULY_START.timestamp(), maker=True)
    assert april < 0 and april == july


@pytest.mark.parametrize("quantity,price", [
    (-1, 0.5), (10, -0.01), (10, 1.01), (float("nan"), 0.5), (10, float("inf")),
])
def test_fee_rejects_impossible_inputs(quantity, price):
    with pytest.raises(ValueError):
        fees_us.fee(quantity, price, JULY_START.timestamp())


# --- reservation --------------------------------------------------------


def test_reserved_cost_rounds_the_unit_fee_up():
    at = JULY_START.timestamp()
    # 0.06 x 0.6 x 0.4 = 0.0144 -> reserved as a full 2c
    assert fees_us.reserved_cost(1, 0.6, at) == pytest.approx(0.62)
    assert fees_us.reserved_cost(10, 0.6, at) == pytest.approx(6.20)


@pytest.mark.parametrize("price", [0.01, 0.1, 0.25, 0.4, 0.5, 0.6, 0.75, 0.9, 0.99])
@pytest.mark.parametrize("quantity", [1, 2, 7, 33, 80, 500])
@pytest.mark.parametrize("at", [APRIL_START, JULY_START])
def test_reservation_never_under_reserves(price, quantity, at):
    """The whole point of rounding up: a fragmented fill must still be covered.

    Each execution is charged its own rounded fee, so the reserve has to hold
    against the worst case of every contract filling separately.
    """
    ts = at.timestamp()
    reserved = fees_us.reserved_cost(quantity, price, ts)
    actual = quantity * price + fees_us.fee(quantity, price, ts)
    worst_case_split = quantity * (price + fees_us.fee(1, price, ts))
    assert reserved >= actual - 1e-9
    assert reserved >= worst_case_split - 1e-9


def test_july_reserves_at_least_as_much_as_april():
    for price in (0.1, 0.3, 0.5, 0.7, 0.9):
        april = fees_us.reserved_cost(100, price, APRIL_START.timestamp())
        july = fees_us.reserved_cost(100, price, JULY_START.timestamp())
        assert july >= april


# --- budgeting ----------------------------------------------------------


def test_affordable_contracts_never_exceeds_the_budget():
    at = JULY_START.timestamp()
    for budget in (1.0, 10.0, 49.99, 50.0, 137.5):
        for price in (0.05, 0.2, 0.5, 0.8, 0.95):
            n = fees_us.affordable_contracts(budget, price, at)
            assert fees_us.reserved_cost(n, price, at) <= budget + 1e-9
            assert fees_us.reserved_cost(n + 1, price, at) > budget


def test_affordable_contracts_at_the_fifty_dollar_cap():
    at = JULY_START.timestamp()
    # 62c reserved per contract against a $50 budget.
    assert fees_us.affordable_contracts(50.0, 0.6, at) == 80


def test_affordable_contracts_floors_at_zero():
    at = JULY_START.timestamp()
    assert fees_us.affordable_contracts(0.0, 0.6, at) == 0
    assert fees_us.affordable_contracts(-5.0, 0.6, at) == 0
    assert fees_us.affordable_contracts(0.5, 0.6, at) == 0


def test_a_dearer_schedule_buys_no_more_contracts():
    for price in (0.2, 0.5, 0.8):
        april = fees_us.affordable_contracts(100.0, price, APRIL_START.timestamp())
        july = fees_us.affordable_contracts(100.0, price, JULY_START.timestamp())
        assert july <= april


# --- historical fallback ------------------------------------------------


def test_fallback_uses_the_earliest_schedule_for_older_data():
    before = (APRIL_START - SECOND).timestamp()
    assert fees_us.coefficient_at_or_earliest(before) == Decimal("0.05")
    assert fees_us.predates_published_schedule(before) is True


def test_fallback_agrees_with_the_strict_lookup_inside_known_windows():
    for at in (APRIL_START, JULY_START, datetime(2027, 1, 1, tzinfo=timezone.utc)):
        ts = at.timestamp()
        assert fees_us.coefficient_at_or_earliest(ts) == fees_us.coefficient(ts)
        assert fees_us.predates_published_schedule(ts) is False


def test_strict_lookup_still_refuses_older_data():
    """The fallback is for backtests only; live pricing must stay strict."""
    with pytest.raises(ValueError):
        fees_us.coefficient((APRIL_START - SECOND).timestamp())
