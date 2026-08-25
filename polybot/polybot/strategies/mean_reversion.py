from __future__ import annotations

import statistics
from typing import Sequence

from ..models import Market, Signal, Snapshot
from .base import Strategy


class MeanReversion(Strategy):
    """Fade moves that stretch far from the recent mean (z-score based)."""
    name = "mean_reversion"

    def evaluate(self, market: Market, history: Sequence[Snapshot],
                 trades: list[dict]) -> Signal | None:
        lookback = int(self.params.get("lookback", 40))
        z_thresh = float(self.params.get("zscore", 2.0))
        max_trend = float(self.params.get("max_trend", 0.15))
        if len(history) < lookback:
            return None
        mids = [s.mid for s in history[-lookback:]]
        # A price that has marched one way across the whole window is not an
        # overshoot, it is news being priced in — often a market resolving.
        # The first soak faded three of those; the market kept marching, and
        # every one stopped out. There is nothing to revert TO.
        if abs(mids[-1] - mids[0]) > max_trend:
            return None
        mean = statistics.fmean(mids)
        stdev = statistics.pstdev(mids)
        if stdev < 1e-4:
            return None
        z = (mids[-1] - mean) / stdev
        if abs(z) < z_thresh:
            return None
        side = "SELL" if z > 0 else "BUY"   # fade the extension
        return self._signal(market, side,
                            f"z-score {z:+.2f} vs {lookback}-tick mean {mean:.3f}")
