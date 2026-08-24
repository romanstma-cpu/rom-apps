"""Strategy interface. A strategy looks at a market's snapshot history
(and optionally its trade tape) and may emit a Signal."""
from __future__ import annotations

from typing import Sequence

from ..models import Market, Signal, Snapshot


class Strategy:
    name = "base"

    def __init__(self, params: dict):
        self.params = params

    @property
    def confidence(self) -> float:
        return float(self.params.get("confidence", 0.5))

    def evaluate(self, market: Market, history: Sequence[Snapshot],
                 trades: list[dict]) -> Signal | None:
        raise NotImplementedError

    def _signal(self, market: Market, side: str, reason: str,
                confidence: float | None = None) -> Signal:
        return Signal(market=market, side=side, strategy=self.name,
                      confidence=confidence if confidence is not None
                      else self.confidence, reason=reason)
