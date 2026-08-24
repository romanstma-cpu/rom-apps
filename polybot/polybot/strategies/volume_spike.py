from __future__ import annotations

import statistics
from typing import Sequence

from ..models import Market, Signal, Snapshot
from .base import Strategy


class VolumeSpike(Strategy):
    """Enter in the direction of price when 24h volume jumps versus its
    recent baseline — sudden attention usually precedes a move."""
    name = "volume_spike"

    def evaluate(self, market: Market, history: Sequence[Snapshot],
                 trades: list[dict]) -> Signal | None:
        lookback = int(self.params.get("lookback", 40))
        ratio = float(self.params.get("spike_ratio", 3.0))
        if len(history) < lookback:
            return None
        window = history[-lookback:]
        deltas = [max(0.0, b.volume_24h - a.volume_24h)
                  for a, b in zip(window, window[1:])]
        if len(deltas) < 4:
            return None
        recent = deltas[-1]
        baseline = statistics.fmean(deltas[:-1])
        if baseline <= 0 or recent < baseline * ratio:
            return None
        drift = window[-1].mid - window[-5].mid
        if abs(drift) < 0.005:
            return None
        side = "BUY" if drift > 0 else "SELL"
        return self._signal(market, side,
                            f"volume delta {recent:,.0f} = {recent / baseline:.1f}x baseline")
