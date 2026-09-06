"""Taker fees — the arithmetic, and the book that fetches the rate."""
import pytest
import requests

from polybot.fees import DEFAULT_RATE, FeeBook, round_trip_fee, taker_fee


# -- the formula ----------------------------------------------------

def test_taker_fee_matches_the_published_formula():
    # fee = shares x rate x price x (1 - price)
    assert taker_fee(100, 0.50, 0.05) == pytest.approx(100 * 0.05 * 0.5 * 0.5)


def test_fee_is_heaviest_at_mid_price():
    # p(1-p) peaks at 0.50, which is exactly where the price band puts most
    # of the tradable book — the expensive case is the common one.
    assert taker_fee(100, 0.50, 0.05) > taker_fee(100, 0.20, 0.05)
    assert taker_fee(100, 0.50, 0.05) > taker_fee(100, 0.80, 0.05)
    assert taker_fee(100, 0.05, 0.05) < taker_fee(100, 0.50, 0.05) / 4


def test_fee_is_symmetric_about_a_half():
    # A YES at 0.30 and a NO at 0.30 cost the same to trade.
    assert taker_fee(100, 0.30, 0.05) == pytest.approx(
        taker_fee(100, 0.70, 0.05))


def test_a_malformed_book_can_never_pay_the_bot_to_trade():
    # A crossed or garbage book must not produce a negative fee that shows
    # up in the ledger as income.
    assert taker_fee(100, 1.40, 0.05) == 0.0
    assert taker_fee(100, -0.20, 0.05) == 0.0
    assert taker_fee(-5, 0.50, 0.05) == 0.0
    assert taker_fee(100, 0.50, 0.0) == 0.0


def test_round_trip_charges_both_legs():
    assert round_trip_fee(100, 0.40, 0.55, 0.05) == pytest.approx(
        taker_fee(100, 0.40, 0.05) + taker_fee(100, 0.55, 0.05))


def test_the_round_trip_is_what_moves_the_breakeven_win_rate():
    """The number that justifies this whole module.

    A $25 stake at 0.35 with a +20% take-profit and a -12% stop: fee-blind,
    that system breaks even at 12/(20+12) = 37.5% wins. Charged on both
    legs it needs closer to six wins in ten, and no strategy verdict
    printed before this was modelled accounted for the difference.
    """
    stake, entry, rate = 25.0, 0.35, 0.05
    shares = stake / entry
    target = entry * 1.20
    fee_pct = round_trip_fee(shares, entry, target, rate) / stake
    assert 0.05 < fee_pct < 0.09          # ~6.8% of stake across both legs

    win, loss = 0.20 - fee_pct, 0.12 + fee_pct
    breakeven = loss / (win + loss)
    assert breakeven > 0.55               # versus 0.375 with fees ignored


# -- the rate book --------------------------------------------------

class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeSession:
    """Stands in for a requests.Session and counts what was asked of it."""

    def __init__(self, payload=None, fail=False):
        self.payload = payload
        self.fail = fail
        self.calls = 0

    def get(self, url, timeout=None):
        self.calls += 1
        if self.fail:
            raise requests.RequestException("exchange unreachable")
        return FakeResponse(self.payload)


def test_rate_comes_from_the_exchange_not_a_constant():
    http = FakeSession({"fd": {"r": 0.03, "e": 1, "to": True}})
    assert FeeBook(session=http).rate_for("0xabc") == 0.03


def test_a_rate_is_fetched_once_and_remembered():
    http = FakeSession({"fd": {"r": 0.05, "e": 1, "to": True}})
    book = FeeBook(session=http)
    for _ in range(5):
        book.rate_for("0xabc")
    assert http.calls == 1


def test_fees_switched_off_for_a_market_mean_zero_not_the_default():
    # e == 0 is the exchange saying this market is free. Falling back to
    # the default rate here would invent a cost that is not charged.
    http = FakeSession({"fd": {"r": 0.05, "e": 0, "to": True}})
    assert FeeBook(session=http).rate_for("0xabc") == 0.0


def test_an_unreachable_exchange_falls_back_to_the_default_rate():
    http = FakeSession(fail=True)
    book = FeeBook(session=http, default_rate=0.05)
    assert book.rate_for("0xabc") == 0.05


def test_a_failed_lookup_is_throttled_not_retried_every_tick():
    # The engine ticks in seconds. Without a throttle an outage turns into
    # a request storm against the API that is already failing.
    http = FakeSession(fail=True)
    book = FeeBook(session=http, retry_after=300.0)
    for _ in range(50):
        book.rate_for("0xabc")
    assert http.calls == 1


def test_the_throttle_expires_so_a_recovered_exchange_is_noticed():
    http = FakeSession(fail=True)
    book = FeeBook(session=http, retry_after=0.0)
    book.rate_for("0xabc")
    book.rate_for("0xabc")
    assert http.calls == 2


def test_a_disabled_book_charges_nothing_and_asks_nothing():
    http = FakeSession({"fd": {"r": 0.05, "e": 1, "to": True}})
    book = FeeBook(session=http, enabled=False)
    assert book.rate_for("0xabc") == 0.0
    assert http.calls == 0


def test_a_malformed_fee_block_does_not_crash_the_engine():
    for payload in ({}, {"fd": None}, {"fd": {"e": 1, "r": "nonsense"}}):
        book = FeeBook(session=FakeSession(payload), default_rate=DEFAULT_RATE)
        assert book.rate_for("0xabc") == DEFAULT_RATE
