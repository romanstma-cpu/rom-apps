from __future__ import annotations

import statistics
from typing import Sequence

from ..models import Market, Signal, Snapshot
from .base import Strategy


class TrendContinuation(Strategy):
    """Join an established long-window trend when the short window pulls
    back toward it (buy the dip in an uptrend, fade the pop in a downtrend)."""
    name = "trend_continuation"

    def evaluate(self, market: Market, history: Sequence[Snapshot],
                 trades: list[dict]) -> Signal | None:
        short = int(self.params.get("short_lookback", 12))
        long = int(self.params.get("long_lookback", 60))
        min_trend = float(self.params.get("min_trend", 0.02))
        if len(history) < long:
            return None
        long_move = history[-1].mid - history[-long].mid
        if abs(long_move) < min_trend:
            return None
        short_mids = [s.mid for s in history[-short:]]
        short_mean = statistics.fmean(short_mids)
        # pullback: current price sits on the wrong side of the short mean
        if long_move > 0 and history[-1].mid < short_mean:
            return self._signal(market, "BUY",
                                f"uptrend {long_move:+.3f}/{long} ticks, pullback entry")
        if long_move < 0 and history[-1].mid > short_mean:
            return self._signal(market, "SELL",
                                f"downtrend {long_move:+.3f}/{long} ticks, pullback entry")
        return None
