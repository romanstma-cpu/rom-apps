from __future__ import annotations

from typing import Sequence

from ..models import Market, Signal, Snapshot
from .base import Strategy


class SpreadScalp(Strategy):
    """On liquid markets with a wide spread, lean toward the heavier side of
    the book.

    Honest economics note: entries here are taker orders, so this strategy
    PAYS the wide spread it targets — it starts every trade the full spread
    down and profits only if the book-imbalance direction plays out by more
    than that. True spread capture needs resting limit orders, which the
    executor does not place yet. Note also that the wide-spread books this
    strategy wants are exactly what the markets.max_spread gate refuses —
    enabling this means raising that limit deliberately, eyes open. Ships
    disabled by default."""
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
