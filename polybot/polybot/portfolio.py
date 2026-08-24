"""Paper-trading ledger, persisted as JSON so runs can resume."""
from __future__ import annotations

import json
import time
from dataclasses import asdict
from pathlib import Path

from .models import Market, Position


class Portfolio:
    def __init__(self, starting_cash: float, path: str | None = None):
        self.cash = starting_cash
        self.positions: list[Position] = []
        self.closed: list[dict] = []
        self.path = Path(path) if path else None
        if self.path and self.path.exists():
            self._load()

    # -- persistence -------------------------------------------------
    def _load(self) -> None:
        data = json.loads(self.path.read_text())
        self.cash = data.get("cash", self.cash)
        self.closed = data.get("closed", [])
        self.positions = []
        for p in data.get("positions", []):
            mkt = Market(**p.pop("market"))
            self.positions.append(Position(market=mkt, **p))

    def save(self) -> None:
        if not self.path:
            return
        self.path.write_text(json.dumps({
            "cash": self.cash,
            "positions": [asdict(p) for p in self.positions],
            "closed": self.closed,
        }, indent=2))

    # -- trading -----------------------------------------------------
    def open(self, pos: Position) -> None:
        self.cash -= pos.cost
        self.positions.append(pos)
        self.save()

    def close(self, pos: Position, yes_mid: float, reason: str) -> float:
        pnl = pos.pnl(yes_mid)
        self.cash += pos.cost + pnl
        self.positions.remove(pos)
        self.closed.append({
            "question": pos.market.question, "side": pos.side,
            "strategy": pos.strategy, "entry": pos.entry_price,
            "exit": pos.held_token_price(yes_mid), "shares": pos.shares,
            "pnl": round(pnl, 2), "reason": reason, "closed_ts": time.time(),
        })
        self.save()
        return pnl

    def realized_pnl_since(self, since_ts: float) -> float:
        return sum(c["pnl"] for c in self.closed
                   if c.get("closed_ts", 0) >= since_ts)
