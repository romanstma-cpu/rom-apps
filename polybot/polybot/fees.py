"""Polymarket taker fees — the cost the paper ledger used to pretend away.

Polybot crosses the book on entry and again on exit, so it is a taker on
both legs and pays the fee on both. Polymarket charges:

    fee = shares x rate x price x (1 - price)

Makers are never charged. The price term matters more than it looks: p(1-p)
peaks at 0.50 and collapses toward either end, so the fee is most expensive
in exactly the mid-price range where markets.min_price / max_price put all
of this bot's trading.

Why this module exists at all: with a +20% take-profit and a -12% stop, a
fee-blind ledger implies breakeven at a 37.5% win rate. Charging the real
round trip moves that to roughly 59%. Every strategy verdict the bot could
print was wrong in a known direction until this was modelled.

The rate is per market and comes from the exchange rather than a constant,
because Polymarket has changed its fee regime more than once — the on-chain
history shows NegRisk fills carrying no fee at all while CTF Exchange fills
of the same era carry one. Hardcoding a rate would be the same class of
mistake as charging nothing.
"""
from __future__ import annotations

import logging
import time

import requests

from .http import make_session

log = logging.getLogger(__name__)
CLOB = "https://clob.polymarket.com"
# Observed as fd.r on both a sports and an economics market. Only used when
# the exchange cannot be reached, and it errs toward charging rather than
# toward a flattering ledger.
DEFAULT_RATE = 0.05


def taker_fee(shares: float, price: float, rate: float) -> float:
    """USD fee for taking `shares` at `price` under `rate`.

    Price is clamped to [0, 1] so a malformed book cannot turn the fee
    negative and quietly pay the bot to trade.
    """
    if rate <= 0 or shares <= 0:
        return 0.0
    p = min(max(price, 0.0), 1.0)
    return shares * rate * p * (1.0 - p)


def round_trip_fee(shares: float, entry_price: float, exit_price: float,
                   rate: float) -> float:
    """Both legs of a completed trade."""
    return (taker_fee(shares, entry_price, rate)
            + taker_fee(shares, exit_price, rate))


class FeeBook:
    """Per-market taker rates, asked of the exchange once and remembered.

    Set enabled=False only to reproduce the old fee-blind numbers for
    comparison — never to make a run look better.
    """

    def __init__(self, session: requests.Session | None = None,
                 default_rate: float = DEFAULT_RATE, enabled: bool = True,
                 retry_after: float = 300.0):
        self.http = session or make_session()
        self.default_rate = float(default_rate)
        self.enabled = bool(enabled)
        self.retry_after = float(retry_after)
        self._rates: dict[str, float] = {}
        self._retry_at: dict[str, float] = {}

    def rate_for(self, condition_id: str) -> float:
        """The taker rate for a market, asked once and remembered.

        A miss is remembered too, for `retry_after` seconds. Without that
        throttle every tick would re-ask for every market the exchange
        could not answer for — the engine polls in seconds, so an outage
        would turn into a request storm against the API that is already
        struggling, and each attempt drags a retrying session with it.
        """
        if not self.enabled:
            return 0.0
        if condition_id in self._rates:
            return self._rates[condition_id]
        if self._retry_at.get(condition_id, 0.0) > time.monotonic():
            return self.default_rate
        rate = self._fetch(condition_id)
        if rate is None:
            self._retry_at[condition_id] = time.monotonic() + self.retry_after
            return self.default_rate
        self._rates[condition_id] = rate
        self._retry_at.pop(condition_id, None)
        return rate

    def cached_rate(self, condition_id: str) -> float:
        """The known rate, or the fallback — never a network call.

        For callers that must not block: the dashboard serves from its own
        HTTP thread, and a fee lookup stalling there would freeze the page
        the operator is using to decide whether to hit pause.
        """
        if not self.enabled:
            return 0.0
        return self._rates.get(condition_id, self.default_rate)

    def _fetch(self, condition_id: str) -> float | None:
        try:
            r = self.http.get(f"{CLOB}/clob-markets/{condition_id}", timeout=20)
            r.raise_for_status()
            body = r.json()
        except (requests.RequestException, ValueError) as exc:
            log.debug("fee lookup failed for %s: %s", condition_id, exc)
            return None
        details = body.get("fd") if isinstance(body, dict) else None
        if not isinstance(details, dict):
            return None
        # e == 0 means fees are switched off for this market entirely.
        if not details.get("e"):
            return 0.0
        try:
            return max(0.0, float(details.get("r")))
        except (TypeError, ValueError):
            return None
