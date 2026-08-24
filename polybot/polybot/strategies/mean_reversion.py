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
        if len(history) < lookback:
            return None
        mids = [s.mid for s in history[-lookback:]]
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
