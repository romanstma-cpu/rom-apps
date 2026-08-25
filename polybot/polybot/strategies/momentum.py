from __future__ import annotations

from typing import Sequence

from ..models import Market, Signal, Snapshot
from .base import Strategy


class Momentum(Strategy):
    """Buy YES into sustained upward moves, buy NO into downward moves."""
    name = "momentum"

    def evaluate(self, market: Market, history: Sequence[Snapshot],
                 trades: list[dict]) -> Signal | None:
        lookback = int(self.params.get("lookback", 12))
        min_move = float(self.params.get("min_move", 0.03))
        require_trades = bool(self.params.get("require_trades", True))
        if len(history) < lookback:
            return None
        window = history[-lookback:]
        move = window[-1].mid - window[0].mid
        if abs(move) < min_move:
            return None
        # Quotes can move with nobody trading — a market maker repositioning
        # reads as momentum on the mid. The Kalshi sibling measured this gate
        # nearly halving its per-trade loss. Volume figures refresh at
        # discovery cadence (about a minute), which the window spans.
        if require_trades and window[-1].volume_24h <= window[0].volume_24h:
            return None
        # require the move to be mostly one-directional, not a single jump
        ups = sum(1 for a, b in zip(window, window[1:]) if b.mid > a.mid)
        downs = len(window) - 1 - ups
        if move > 0 and ups <= downs:
            return None
        if move < 0 and downs <= ups:
            return None
        side = "BUY" if move > 0 else "SELL"
        return self._signal(market, side,
                            f"mid moved {move:+.3f} over {lookback} ticks")
