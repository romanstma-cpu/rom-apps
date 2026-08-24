"""Core dataclasses shared across the bot."""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class Market:
    condition_id: str
    question: str
    category: str
    yes_token: str          # CLOB token id for the YES outcome
    no_token: str
    volume_24h: float = 0.0
    end_date: str = ""


@dataclass
class Snapshot:
    """One observation of a market at a point in time."""
    ts: float
    mid: float              # YES midpoint price, 0..1
    bid: float
    ask: float
    volume_24h: float
    imbalance: float = 0.0  # (bid_depth - ask_depth) / (bid_depth + ask_depth)

    @property
    def spread(self) -> float:
        return max(0.0, self.ask - self.bid)


@dataclass
class Signal:
    market: Market
    side: str               # "BUY" or "SELL" (of the YES token)
    strategy: str
    confidence: float       # 0..1, scales position size
    reason: str

    def __str__(self) -> str:
        return (f"[{self.strategy}] {self.side} conf={self.confidence:.2f} "
                f"{self.market.question[:60]!r} — {self.reason}")


@dataclass
class Position:
    market: Market
    side: str               # "BUY" means long YES, "SELL" means long NO
    entry_price: float      # price paid per share of the held token
    shares: float
    strategy: str
    opened_ts: float = field(default_factory=time.time)

    @property
    def cost(self) -> float:
        return self.entry_price * self.shares

    def held_token_price(self, yes_mid: float) -> float:
        return yes_mid if self.side == "BUY" else 1.0 - yes_mid

    def pnl(self, yes_mid: float) -> float:
        return (self.held_token_price(yes_mid) - self.entry_price) * self.shares

    def pnl_pct(self, yes_mid: float) -> float:
        return self.pnl(yes_mid) / self.cost if self.cost else 0.0
