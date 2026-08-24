from __future__ import annotations

from typing import Sequence

from ..models import Market, Signal, Snapshot
from .base import Strategy


class SpreadScalp(Strategy):
    """On liquid markets with a wide spread, lean toward the heavier side of
    the book and aim to capture part of the spread."""
    name = "spread_scalp"

    def evaluate(self, market: Market, history: Sequence[Snapshot],
                 trades: list[dict]) -> Signal | None:
        min_spread = float(self.params.get("min_spread", 0.04))
        min_vol = float(self.params.get("min_volume_24h", 50000))
        if not history:
            return None
        snap = history[-1]
        if snap.spread < min_spread or snap.volume_24h < min_vol:
            return None
        if abs(snap.imbalance) < 0.2:
            return None
        side = "BUY" if snap.imbalance > 0 else "SELL"
        return self._signal(market, side,
                            f"spread {snap.spread:.3f}, book imbalance {snap.imbalance:+.2f}")
