"""Risk manager: gates entries, decides exits."""
from __future__ import annotations

import time

from .models import Position, Signal, Snapshot


class RiskManager:
    def __init__(self, cfg):
        self.cfg = cfg

    def _risk(self, category: str) -> dict:
        return self.cfg.for_category(category).get("risk", {})

    def price_ok(self, snap: Snapshot) -> bool:
        m = self.cfg.get("markets", {})
        return (float(m.get("min_price", 0.05)) <= snap.mid
                <= float(m.get("max_price", 0.95)))

    def spread_ok(self, snap: Snapshot) -> bool:
        """Entries are takers, so the spread is paid in full on the way in.

        A 6-cent book means every entry starts roughly 6% down at mid — deep
        enough that the stop-loss gets tripped by the entry itself plus a
        little noise, before the idea was ever tested.
        """
        m = self.cfg.get("markets", {})
        return snap.spread <= float(m.get("max_spread", 0.05))

    def exits_reachable(self, side: str, snap: Snapshot, category: str) -> tuple[bool, str]:
        """Whether the percentage exits actually exist on the price line.

        Prediction-market prices live in [0, 1], and percentage exits ignore
        that. The first soak proved both failure modes in one evening: buys
        at 7c carried a 12% stop that was a single tick away — every one
        stopped out on quote noise — while NO positions entered at 95c
        carried a +20% take-profit above $1.00, a target that cannot exist,
        leaving dead capital that could only lose. An entry whose stop is
        inside the noise or whose target is through the ceiling is not a
        trade, it is a coin with one side.
        """
        risk = self._risk(category)
        # Price of the token actually held: the YES ask for a buy, the NO
        # ask (one minus the YES bid) for a sell.
        held = snap.ask if side == "BUY" else 1.0 - snap.bid
        stop_move = held * abs(float(risk.get("stop_loss_pct", 0.12)))
        if stop_move < float(risk.get("min_stop_move", 0.02)):
            return False, (f"stop {stop_move:.3f} inside tick noise at {held:.3f}")
        target = held * (1.0 + float(risk.get("take_profit_pct", 0.20)))
        if target >= 0.99:
            return False, (f"take-profit {target:.3f} beyond the $1 ceiling from {held:.3f}")
        return True, "ok"

    def entry_size(self, signal: Signal) -> float:
        """USD to commit for this signal; 0 means rejected."""
        risk = self._risk(signal.market.category)
        return round(float(risk.get("stake_usd", 25)) *
                     max(0.1, min(1.0, signal.confidence)), 2)

    def allow_entry(self, signal: Signal, positions: list[Position],
                    realized_pnl_today: float) -> tuple[bool, str]:
        risk = self._risk(signal.market.category)
        if realized_pnl_today <= -abs(float(risk.get("daily_loss_stop_usd", 1e12))):
            return False, "daily loss stop hit"
        if len(positions) >= int(risk.get("max_open_positions", 10)):
            return False, "max open positions"
        in_cat = [p for p in positions
                  if p.market.category == signal.market.category]
        if len(in_cat) >= int(risk.get("max_per_category", 99)):
            return False, f"max positions in {signal.market.category}"
        # Sibling markets only: the same-market case is what the pyramiding
        # and per-market size rules below are for.
        in_event = [p for p in positions
                    if p.market.event_key == signal.market.event_key
                    and p.market.condition_id != signal.market.condition_id]
        if len(in_event) + 1 > int(risk.get("max_per_event", 1)):
            # Sibling markets of one event are mutually exclusive outcomes of
            # the same question — the four "Fed decision" markets move as one.
            # Stacking them is a single bet at multiplied size, and one
            # resolution closes them all together. (Lesson imported from the
            # Kalshi bot, where sibling strikes produced loss cascades that
            # kept tripping the loss brakes.)
            return False, "already holding this event"
        in_market = [p for p in positions
                     if p.market.condition_id == signal.market.condition_id]
        if in_market and not bool(risk.get("allow_pyramiding", False)):
            return False, "already holding this market"
        exposure = sum(p.cost for p in in_market)
        if exposure + self.entry_size(signal) > float(risk.get("max_position_usd", 100)):
            return False, "max position size in market"
        return True, "ok"

    def should_exit(self, pos: Position, yes_mid: float) -> str | None:
        """Return a reason string if the position should be closed."""
        risk = self._risk(pos.market.category)
        pnl_pct = pos.pnl_pct(yes_mid)
        if pnl_pct >= float(risk.get("take_profit_pct", 0.20)):
            return f"take profit {pnl_pct:+.1%}"
        if pnl_pct <= -abs(float(risk.get("stop_loss_pct", 0.12))):
            return f"stop loss {pnl_pct:+.1%}"
        max_hold = float(risk.get("max_hold_hours", 48)) * 3600
        if time.time() - pos.opened_ts > max_hold:
            return f"max hold time ({pnl_pct:+.1%})"
        return None
