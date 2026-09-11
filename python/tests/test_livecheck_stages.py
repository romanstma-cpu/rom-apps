"""Decision logic of the read-only live-validation stages.

The stages themselves need a real account and a live book. What can be pinned
down here is the arithmetic that turns an observation into a PASS, FAIL or
SKIP — and that matters more than usual, because a harness built to remove
false confidence must never manufacture it. The cases that would do so are the
ones covered hardest: a quiet market reported as a healthy clock, an
unobserved stream reported as a continuous one, a NO ladder whose sizes came
from the wrong side of the book.
"""
from __future__ import annotations

import pytest

import momentum_window
from livecheck.stages import stage2_streams as s2
from livecheck.stages import stage3_quotes as s3

BEHIND = s2.BEHIND_REASON


def delta(accepted=0, rejected=0, reasons=None, resets=0):
    return {'accepted': accepted, 'rejected': rejected,
            'reasons': reasons or {}, 'resets': resets}


# --- stage 2: the clock gate ----------------------------------------------

def test_a_quiet_market_is_a_skip_not_a_pass():
    """Zero receipts proves nothing about the clock, in either direction."""
    check = s2.evaluate_clock_skew(delta(), s2.summarize_offsets([]), 90)
    assert check.skipped is True
    assert check.ok is False          # never counted as a pass
    assert check.status == 'SKIP'
    assert 'quiet market' in check.detail


def test_any_receipt_behind_the_exchange_fails():
    # One rejected receipt in a thousand is still a host-clock fault: the
    # sampled share only reflects how long the stage happened to watch.
    check = s2.evaluate_clock_skew(
        delta(accepted=999, rejected=1, reasons={BEHIND: 1}),
        s2.summarize_offsets([-0.25] + [1.0] * 999), 90)
    assert check.ok is False and check.skipped is False
    assert '0.250s behind' in check.detail
    assert 'momentum will report nothing' in check.detail


def test_clean_receipts_pass_and_report_the_margin():
    check = s2.evaluate_clock_skew(
        delta(accepted=50, rejected=2, reasons={'older than 30s at receipt': 2}),
        s2.summarize_offsets([0.4, 1.2, 9.0]), 90)
    assert check.ok is True and check.skipped is False
    assert 'none for a clock behind' in check.detail


def test_offsets_separate_behind_from_merely_stale():
    stats = s2.summarize_offsets([-2.0, -0.001, 0.5, 12.0, 45.0], fresh=30)
    assert stats['behind'] == 2      # negative: local clock behind
    assert stats['stale'] == 1       # beyond FRESH: ordinary upper-bound reject
    assert stats['usable'] == 2
    assert stats['min_s'] == -2.0 and stats['max_s'] == 45.0


def test_offsets_ignore_unusable_samples():
    stats = s2.summarize_offsets([float('nan'), float('inf'), None, 'x', 1.0])
    assert stats['samples'] == 1 and stats['median_s'] == 1.0


def test_no_samples_reports_no_distribution():
    assert s2.summarize_offsets([])['samples'] == 0
    assert s2.summarize_offsets([])['min_s'] is None


# --- stage 2: warm-up reachability ----------------------------------------

def test_reconnecting_faster_than_the_window_can_never_warm_up():
    # us_market_stream resets the tape on every disconnect, so this is fatal
    # to momentum regardless of how much data flows.
    out = s2.warmup_reachability(resets=4, observed_seconds=600, window=300)
    assert out['reachable'] is False and out['mean_uptime_s'] == 150.0


def test_a_slow_reset_rate_still_allows_warm_up():
    out = s2.warmup_reachability(resets=1, observed_seconds=900, window=300)
    assert out['reachable'] is True and out['conclusive'] is True


def test_no_resets_in_a_short_window_is_not_conclusive():
    """Watching 60s without a drop does not prove 300s of continuity."""
    out = s2.warmup_reachability(resets=0, observed_seconds=60, window=300)
    assert out['reachable'] is True and out['conclusive'] is False
    assert s2.warmup_reachability(0, 300, window=300)['conclusive'] is True


# --- stage 2: timestamp parsing (mirrors momentum_window exactly) ---------

def test_a_naive_timestamp_is_named_as_its_own_failure():
    # momentum_window rejects these outright, so a feed that dropped its
    # offset would be a silent total failure rather than a degradation.
    at, problem = s2.parse_exchange_time('2026-07-10T12:00:00')
    assert at is None and problem == 'naive timestamp'


def test_a_zulu_timestamp_parses_to_the_same_instant_as_an_explicit_offset():
    zulu, problem_z = s2.parse_exchange_time('2026-07-10T12:00:00Z')
    offset, problem_o = s2.parse_exchange_time('2026-07-10T12:00:00+00:00')
    assert problem_z == '' and problem_o == ''
    assert zulu == offset


def test_unparseable_timestamps_are_reported_not_raised():
    for bad in ('', None, 'yesterday', 12345):
        _, problem = s2.parse_exchange_time(bad)
        assert problem in ('unparseable timestamp', 'naive timestamp')


def test_parser_matches_the_gate_it_stands_in_for():
    """Whatever this parser accepts, Tape.add must accept too."""
    stamp = '2026-07-10T12:00:00+00:00'
    at, problem = s2.parse_exchange_time(stamp)
    assert problem == ''
    tape = momentum_window.Tape()
    accepted = tape.add({
        'trade_id': 't1', 'ticker': 'M1', 'created_time': stamp,
        'count_fp': 10, 'yes_price_dollars': 0.4, 'taker_side': 'yes',
    }, at + 1)
    assert accepted is True


# --- stage 3: the NO mirror ------------------------------------------------

def test_a_correct_mirror_reports_nothing():
    yes = {'bid_cents': 40, 'ask_cents': 42,
           'bid_levels': [[40, 100], [39, 50]], 'ask_levels': [[42, 80]]}
    no = {'ask_cents': 60, 'bid_cents': 58,
          'ask_levels': [[60, 100], [61, 50]], 'bid_levels': [[58, 80]]}
    assert s3.mirror_problems(yes, no) == []


def test_a_price_that_does_not_sum_to_100_is_caught():
    yes = {'bid_cents': 40, 'ask_cents': 42, 'bid_levels': [[40, 100]], 'ask_levels': []}
    no = {'ask_cents': 59, 'bid_cents': None, 'ask_levels': [[59, 100]], 'bid_levels': []}
    problems = s3.mirror_problems(yes, no)
    assert any('expected 100' in p for p in problems)


def test_size_taken_from_the_wrong_side_is_caught():
    # The sign error that would mis-size every NO trade: prices mirror, sizes
    # came from the opposite ladder.
    yes = {'bid_cents': 40, 'ask_cents': 42,
           'bid_levels': [[40, 100]], 'ask_levels': [[42, 7]]}
    no = {'ask_cents': 60, 'bid_cents': 58,
          'ask_levels': [[60, 7]], 'bid_levels': [[58, 100]]}
    problems = s3.mirror_problems(yes, no)
    assert any('wrong side of the book' in p for p in problems)


def test_a_one_sided_yes_book_makes_one_no_side_absent_legitimately():
    yes = {'bid_cents': 40, 'ask_cents': None, 'bid_levels': [[40, 10]], 'ask_levels': []}
    no = {'ask_cents': 60, 'bid_cents': None, 'ask_levels': [[60, 10]], 'bid_levels': []}
    assert s3.mirror_problems(yes, no) == []


# --- stage 3: ladder shape -------------------------------------------------

def test_an_inverted_ladder_is_caught_in_both_directions():
    assert s3.ordering_problems([[42, 1], [41, 1], [43, 1]], descending=False)
    assert s3.ordering_problems([[40, 1], [41, 1]], descending=True)


def test_repeated_prices_are_allowed():
    # The venue ticks finer than a cent, so raw levels legitimately collapse.
    assert s3.ordering_problems([[42, 1], [42, 5], [43, 2]], descending=False) == []


def test_zero_and_malformed_sizes_are_reported():
    bad = s3.zero_size_levels([[40, 10], [41, 0], [42, -3], [43, None], [44, True]])
    assert [level[0] for level in bad] == [41, 42, 43, 44]


def test_levels_the_depth_maths_would_ignore_are_reported():
    assert s3.out_of_band_levels([[0, 5], [100, 5], [50, 5]]) == [[0, 5], [100, 5]]


def test_depth_cost_rises_with_size_and_never_beats_the_touch():
    problems, samples = s3.depth_cost_problems([[42, 10], [43, 20], [44, 30]])
    assert problems == []
    costs = [s['vwap_cents'] for s in samples if s.get('vwap_cents') is not None]
    assert costs == sorted(costs)          # monotonically non-decreasing
    assert all(c >= 42 for c in costs)     # never better than the advertised touch


def test_an_empty_ladder_yields_no_claims():
    assert s3.depth_cost_problems([]) == ([], [])


# --- stage 3: what the hardcoded spread rule admits ------------------------

def test_spread_stats_report_what_the_three_cent_rule_admits():
    stats = s3.spread_stats([1, 2, 3, 4, 10], limit_cents=3)
    assert stats['count'] == 5 and stats['admitted'] == 3
    assert stats['admitted_fraction'] == 0.6
    assert stats['min'] == 1 and stats['max'] == 10


def test_no_spreads_sampled_reports_a_bare_count():
    assert s3.spread_stats([]) == {'count': 0}
