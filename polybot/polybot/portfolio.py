"""Paper-trading ledger, persisted as JSON so runs can resume."""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import asdict
from pathlib import Path

from .models import Market, Position

log = logging.getLogger(__name__)


class Portfolio:
    def __init__(self, starting_cash: float, path: str | None = None):
        self.cash = starting_cash
        self.positions: list[Position] = []
        self.closed: list[dict] = []
        self._lock = threading.Lock()
        self.path = Path(path) if path else None
        if self.path and self.path.exists():
            self._load()

    # -- persistence -------------------------------------------------
    def _load(self) -> None:
        """Read the ledger. A truncated or hand-edited file must not stop the
        bot from starting: it is set aside and the run begins fresh."""
        try:
            data = json.loads(self.path.read_text())
            positions = []
            for p in data.get("positions", []):
                mkt = Market(**dict(p)["market"])
                positions.append(Position(
                    market=mkt, **{k: v for k, v in p.items() if k != "market"}))
        except (ValueError, TypeError, KeyError, OSError) as exc:
            broken = self.path.with_suffix(self.path.suffix + ".broken")
            log.warning("ledger %s unreadable (%s); moved to %s, starting fresh",
                        self.path, exc, broken)
            try:
                self.path.replace(broken)
            except OSError:
                pass
            return
        self.cash = data.get("cash", self.cash)
        self.closed = data.get("closed", [])
        self.positions = positions

    def save(self) -> None:
        """Write atomically — a crash mid-write must not truncate the ledger."""
        if not self.path:
            return
        with self._lock:
            payload = json.dumps({
                "cash": self.cash,
                "positions": [asdict(p) for p in self.positions],
                "closed": self.closed,
            }, indent=2)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(payload)
            os.replace(tmp, self.path)

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
