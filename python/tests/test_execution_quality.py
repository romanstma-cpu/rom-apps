import asyncio
import pytest
import execution_quality
from execution_quality import entry_price, remaining_signal_margin
from config import merge_with_defaults
import trader
from execution_quality import signal_freshness_problem
from datetime import datetime, timezone


@pytest.mark.parametrize('stamp,expected', [
    ('1970-01-01T00:15:00+00:00', None),
    ('1970-01-01 00:15:00', None),
    ('1970-01-01T01:15:00+01:00', None),
    ('1970-01-01T00:10:00Z', 'expired'),
    ('1970-01-01T00:20:00Z', 'future'),
    (None, 'invalid'), ('bad', 'invalid'),
])
def test_execution_age_is_timezone_aware_and_fail_closed(stamp, expected):
    result = signal_freshness_problem({'created_at': stamp}, 120, 1000)
    if expected:
        assert expected in result
    else:
        assert result is None


@pytest.mark.parametrize('quote', [
    {}, {'bid_cents': None, 'ask_cents': 60},
    {'bid_cents': 60, 'ask_cents': None},
    {'bid_cents': 61, 'ask_cents': 60},
    {'bid_cents': 55, 'ask_cents': 60},
    {'bid_cents': float('nan'), 'ask_cents': 60},
    {'bid_cents': 59, 'ask_cents': float('inf')},
    {'bid_cents': 0, 'ask_cents': 2},
])
def test_bad_liquidity_is_rejected(quote):
    with pytest.raises(ValueError):
        entry_price(quote, 60, {})


def test_price_chasing_is_rejected():
    with pytest.raises(ValueError, match='moved'):
        entry_price({'bid_cents': 62, 'ask_cents': 63}, 60, {})


def test_margin_shrinks_without_rewarding_price_drops():
    assert remaining_signal_margin(8, 60, 62) == 5
    assert remaining_signal_margin(8, 60, 58) == 7


# --- the spread and chase limits are configurable, not literals ------------
#
# Both were bare numbers inside entry_price with no config key and no settings
# surface, and livecheck hand-copied the spread one. These pin the defaults
# (so the shipped behaviour is unchanged) and the overrides.

def test_defaults_match_the_limits_that_were_hardcoded():
    assert execution_quality.MAX_SPREAD_CENTS == 3
    assert execution_quality.MAX_CHASE_CENTS == 2
    # A 3c spread passes and a 4c spread does not, with no config supplied.
    assert entry_price({'bid_cents': 57, 'ask_cents': 60}, 60, {}) == 60
    with pytest.raises(ValueError, match='3-cent'):
        entry_price({'bid_cents': 56, 'ask_cents': 60}, 60, {})


def test_a_wider_spread_limit_admits_a_wider_book():
    quote = {'bid_cents': 50, 'ask_cents': 60}
    with pytest.raises(ValueError, match='Spread'):
        entry_price(quote, 60, {})
    assert entry_price(quote, 60, {'max_entry_spread_cents': 10}) == 60


def test_a_tighter_spread_limit_refuses_a_book_the_default_allowed():
    quote = {'bid_cents': 58, 'ask_cents': 60}
    assert entry_price(quote, 60, {}) == 60
    with pytest.raises(ValueError, match='1-cent'):
        entry_price(quote, 60, {'max_entry_spread_cents': 1})


def test_zero_spread_limit_takes_only_a_locked_book():
    assert entry_price({'bid_cents': 60, 'ask_cents': 60}, 60,
                       {'max_entry_spread_cents': 0}) == 60
    with pytest.raises(ValueError, match='0-cent'):
        entry_price({'bid_cents': 59, 'ask_cents': 60}, 60,
                    {'max_entry_spread_cents': 0})


def test_the_chase_limit_is_configurable_in_both_directions():
    quote = {'bid_cents': 62, 'ask_cents': 63}
    with pytest.raises(ValueError, match='moved'):
        entry_price(quote, 60, {})
    assert entry_price(quote, 60, {'max_entry_chase_cents': 5}) == 63
    with pytest.raises(ValueError, match='moved more than 0'):
        entry_price({'bid_cents': 60, 'ask_cents': 61}, 60,
                    {'max_entry_chase_cents': 0})


@pytest.mark.parametrize('value', [None, 'wide', float('nan'), True, -1])
def test_an_unusable_override_falls_back_to_the_documented_default(value):
    """A bad stored value must not silently disable an execution guard."""
    with pytest.raises(ValueError, match='3-cent'):
        entry_price({'bid_cents': 56, 'ask_cents': 60}, 60,
                    {'max_entry_spread_cents': value})


def test_config_clamps_the_new_cent_limits():
    c = merge_with_defaults({'maxEntrySpreadCents': 999, 'maxEntryChaseCents': -5})
    assert 0 <= c['max_entry_spread_cents'] <= 99
    assert 0 <= c['max_entry_chase_cents'] <= 99


def test_livecheck_reads_the_same_constant_it_used_to_copy():
    from livecheck.stages import stage3_quotes
    assert stage3_quotes.SPREAD_LIMIT_CENTS == execution_quality.MAX_SPREAD_CENTS


def test_quote_network_failure_is_not_replaced_with_signal_price(monkeypatch):
    async def failed(*args):
        raise TimeoutError('venue unavailable')
    monkeypatch.setattr(trader, 'get_quote', failed)
    with pytest.raises(TimeoutError):
        asyncio.run(trader._compute_limit_price_cents('X', 'yes', 60, {}))
