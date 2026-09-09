import asyncio
import pytest
from execution_quality import entry_price, remaining_signal_margin
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


def test_quote_network_failure_is_not_replaced_with_signal_price(monkeypatch):
    async def failed(*args):
        raise TimeoutError('venue unavailable')
    monkeypatch.setattr(trader, 'get_quote', failed)
    with pytest.raises(TimeoutError):
        asyncio.run(trader._compute_limit_price_cents('X', 'yes', 60, {}))
