from __future__ import annotations

import time
from typing import Sequence

from ..models import Market, Signal, Snapshot
from .base import Strategy


def _trade_age_seconds(t: dict) -> float | None:
    """Age of a tape entry, tolerating seconds/milliseconds and strings."""
    raw = t.get("timestamp")
    try:
        ts = float(raw)
    except (TypeError, ValueError):
        return None
    if ts > 1e12:   # milliseconds
        ts /= 1000.0
    return time.time() - ts


class WhaleFollow(Strategy):
    """Mirror unusually large recent trades from the public tape."""
    name = "whale_follow"

    def __init__(self, params: dict):
        super().__init__(params)
        self._seen: set[str] = set()

    def evaluate(self, market: Market, history: Sequence[Snapshot],
                 trades: list[dict]) -> Signal | None:
        min_usd = float(self.params.get("min_trade_usd", 5000))
        max_age = float(self.params.get("max_age_seconds", 300))
        if len(self._seen) > 20000:   # bound memory on long runs
            self._seen.clear()
        for t in trades:
            key = t.get("transactionHash") or f"{t.get('timestamp')}:{t.get('size')}"
            if key in self._seen:
                continue
            self._seen.add(key)
            # The tape reaches back hours; the very first scan after startup
            # used to mirror a whale from that morning as if it just traded.
            # A whale is a signal while the market is still reacting, not
            # after it has finished doing so.
            age = _trade_age_seconds(t)
            if age is None or age > max_age:
                continue
            usd = float(t.get("size") or 0) * float(t.get("price") or 0)
            if usd < min_usd:
                continue
            taker_side = (t.get("side") or "").upper()      # BUY/SELL of tokens
            outcome = (t.get("outcome") or "").lower()
            if taker_side not in ("BUY", "SELL"):
                continue
            # normalize to YES-token terms
            side = taker_side if outcome != "no" else (
                "SELL" if taker_side == "BUY" else "BUY")
            return self._signal(market, side,
                                f"whale {taker_side} {outcome or 'yes'} ~${usd:,.0f}")
        return None
