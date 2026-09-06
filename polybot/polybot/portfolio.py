"""Paper-trading ledger, persisted as JSON so runs can resume."""
from __future__ import annotations

import json
import os
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
        # Write-then-rename: a crash mid-write must never leave a torn
        # ledger, because the loader would raise on it at the next start and
        # the record of every trade would be hostage to hand-editing JSON.
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps({
            "cash": self.cash,
            "positions": [asdict(p) for p in self.positions],
            "closed": self.closed,
        }, indent=2))
        os.replace(tmp, self.path)

    # -- trading -----------------------------------------------------
    def open(self, pos: Position) -> None:
        # basis, not cost: the entry fee leaves the bankroll at the same
        # moment the stake does.
        self.cash -= pos.basis
        self.positions.append(pos)
        self.save()

    def close(self, pos: Position, yes_mid: float, reason: str,
              exit_fee: float = 0.0) -> float:
        """Book a close and return the NET result.

        Gross and fees are both recorded, because "the idea was right and
        the fees ate it" and "the idea was wrong" are different lessons and
        a single net figure cannot tell them apart.
        """
        gross = pos.pnl(yes_mid)
        net = gross - pos.fees_paid - exit_fee
        # The entry fee already left cash at open; only the exit leg is new.
        self.cash += pos.cost + gross - exit_fee
        self.positions.remove(pos)
        self.closed.append({
            "question": pos.market.question, "side": pos.side,
            "strategy": pos.strategy, "entry": pos.entry_price,
            "exit": pos.held_token_price(yes_mid), "shares": pos.shares,
            "gross": round(gross, 4),
            "fees": round(pos.fees_paid + exit_fee, 4),
            "pnl": round(net, 4), "reason": reason, "closed_ts": time.time(),
        })
        self.save()
        return net

    def realized_pnl_since(self, since_ts: float) -> float:
        return sum(c["pnl"] for c in self.closed
                   if c.get("closed_ts", 0) >= since_ts)
