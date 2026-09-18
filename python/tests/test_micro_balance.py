import time

import pytest

import fees_us
import trader
from config import merge_with_defaults


def test_fifty_cent_account_can_afford_a_whole_contract():
    cfg = merge_with_defaults({})
    now = time.time()
    budget = trader.entry_budget(
        .50, 0, 0, 10, 25, cfg, allocation_multiplier=.25, fee_time=now)
    assert budget == pytest.approx(fees_us.reserved_cost(1, .25, now))
    count = fees_us.affordable_contracts(budget, .25, time.time())
    assert count == 1
    assert fees_us.reserved_cost(count, .25, time.time()) <= budget
    assert fees_us.affordable_contracts(budget, .50, time.time()) == 0


def test_four_dollar_account_can_fund_one_high_price_contract_after_fees():
    cfg = merge_with_defaults({})
    now = time.time()
    budget = trader.entry_budget(4, 0, 0, 10, 85, cfg, fee_time=now)
    assert budget == pytest.approx(fees_us.reserved_cost(1, .85, now))
    assert fees_us.affordable_contracts(budget, .85, now) == 1
    assert budget < 1


def test_micro_contract_floor_cannot_override_a_user_hard_cap():
    cfg = merge_with_defaults({'hardMaxPositionUsd': .50})
    now = time.time()
    budget = trader.entry_budget(4, 0, 0, 10, 85, cfg, fee_time=now)
    assert budget == .50
    assert fees_us.affordable_contracts(budget, .85, now) == 0


def test_practice_bankroll_accepts_four_dollars_and_keeps_a_fifty_cent_floor():
    assert merge_with_defaults({'mainPaperBankrollUsd': 4})['main_paper_bankroll_usd'] == 4
    assert merge_with_defaults({'mainPaperBankrollUsd': .25})['main_paper_bankroll_usd'] == .50


@pytest.mark.parametrize('override,expected', [
    ({'hardMaxPositionUsd': .10}, .10),
    ({'maxTotalExposureFraction': .20}, .10),
    ({'minCashReserveFraction': .90}, .05),
    ({'hardMaxPositionUsd': 0}, 0),
])
def test_small_account_never_overrides_explicit_limits(override, expected):
    cfg = merge_with_defaults(override)
    assert trader.entry_budget(.50, 0, 0, 10, 25, cfg) == pytest.approx(expected)


def test_group_limit_and_zero_allocation_remain_authoritative():
    cfg = merge_with_defaults({})
    assert trader.entry_budget(.50, 0, 0, 10, 25, cfg, group_budget_usd=.05) == .05
    assert trader.entry_budget(.50, 0, 0, 10, 25, cfg, allocation_multiplier=0) == 0


def test_regular_account_sizes_follow_actual_balance():
    cfg = merge_with_defaults({'hardMaxPositionUsd': 1000})
    small = trader.entry_budget(100, 0, 0, 10, 25, cfg)
    large = trader.entry_budget(200, 0, 0, 10, 25, cfg)
    assert large == pytest.approx(small * 2)
