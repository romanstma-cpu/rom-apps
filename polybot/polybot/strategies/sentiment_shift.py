from __future__ import annotations

import statistics
from typing import Sequence

from ..models import Market, Signal, Snapshot
from .base import Strategy


class SentimentShift(Strategy):
    """Trade sharp changes in order-book imbalance — a proxy for shifting
    market sentiment before it fully prints in price."""
    name = "sentiment_shift"

    def evaluate(self, market: Market, history: Sequence[Snapshot],
                 trades: list[dict]) -> Signal | None:
        lookback = int(self.params.get("lookback", 20))
        delta_thresh = float(self.params.get("imbalance_delta", 0.3))
        if len(history) < lookback:
            return None
        window = history[-lookback:]
        baseline = statistics.fmean(s.imbalance for s in window[:-3])
        recent = statistics.fmean(s.imbalance for s in window[-3:])
        delta = recent - baseline
        if abs(delta) < delta_thresh:
            return None
        side = "BUY" if delta > 0 else "SELL"
        return self._signal(market, side,
                            f"book imbalance shifted {delta:+.2f} "
                            f"({baseline:+.2f} → {recent:+.2f})")
