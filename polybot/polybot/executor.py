"""Order execution: paper fills at the touch, or live via py-clob-client."""
from __future__ import annotations

import logging

from .config import Config
from .models import Position, Signal, Snapshot
from .portfolio import Portfolio

log = logging.getLogger(__name__)


class PaperExecutor:
    """Simulated fills: buys lift the ask, sells hit the bid (worst case)."""

    def __init__(self, portfolio: Portfolio):
        self.portfolio = portfolio

    def enter(self, signal: Signal, snap: Snapshot, usd: float) -> Position | None:
        # long YES fills at the YES ask; long NO at (1 - bid) of YES
        price = snap.ask if signal.side == "BUY" else 1.0 - snap.bid
        if price <= 0 or price >= 1 or usd > self.portfolio.cash:
            return None
        pos = Position(market=signal.market, side=signal.side,
                       entry_price=round(price, 4),
                       shares=round(usd / price, 2),
                       strategy=signal.strategy)
        self.portfolio.open(pos)
        log.info("PAPER ENTER %s %.2f sh @ %.3f ($%.2f) %s", signal.side,
                 pos.shares, price, usd, signal.market.question[:60])
        return pos

    def exit(self, pos: Position, snap: Snapshot, reason: str) -> float:
        # exit long YES at the bid; long NO at (1 - ask) of YES
        yes_exit = snap.bid if pos.side == "BUY" else snap.ask
        pnl = self.portfolio.close(pos, yes_exit, reason)
        log.info("PAPER EXIT  %s pnl $%.2f (%s) %s", pos.side, pnl, reason,
                 pos.market.question[:60])
        return pnl


class LiveExecutor:
    """Real orders through py-clob-client. Imported lazily so paper mode
    never needs the dependency or any keys."""

    def __init__(self, cfg: Config, portfolio: Portfolio):
        try:
            from py_clob_client.client import ClobClient as PyClob
            from py_clob_client.clob_types import MarketOrderArgs, OrderType
        except ImportError as exc:
            raise RuntimeError(
                "live mode needs py-clob-client — run: pip install "
                "py-clob-client (or set mode: paper)") from exc
        self._MarketOrderArgs = MarketOrderArgs
        self._OrderType = OrderType
        live = cfg.get("live", {})
        self.client = PyClob(
            live.get("clob_host", "https://clob.polymarket.com"),
            key=Config.env("POLYBOT_PRIVATE_KEY", required=True),
            chain_id=int(live.get("chain_id", 137)),
            funder=Config.env("POLYBOT_FUNDER"),
            signature_type=2 if Config.env("POLYBOT_FUNDER") else 0,
        )
        self.client.set_api_creds(self.client.create_or_derive_api_creds())
        self.portfolio = portfolio  # mirrors live fills for local tracking

    def enter(self, signal: Signal, snap: Snapshot, usd: float) -> Position | None:
        token = (signal.market.yes_token if signal.side == "BUY"
                 else signal.market.no_token)
        order = self.client.create_market_order(
            self._MarketOrderArgs(token_id=token, amount=usd, side="BUY"))
        resp = self.client.post_order(order, self._OrderType.FOK)
        if not resp or not resp.get("success"):
            log.warning("live order rejected: %s", resp)
            return None
        price = snap.ask if signal.side == "BUY" else 1.0 - snap.bid
        pos = Position(market=signal.market, side=signal.side,
                       entry_price=round(price, 4),
                       shares=round(usd / price, 2), strategy=signal.strategy)
        self.portfolio.open(pos)
        log.info("LIVE ENTER %s $%.2f %s", signal.side, usd,
                 signal.market.question[:60])
        return pos

    def exit(self, pos: Position, snap: Snapshot, reason: str) -> float:
        token = (pos.market.yes_token if pos.side == "BUY"
                 else pos.market.no_token)
        order = self.client.create_market_order(
            self._MarketOrderArgs(token_id=token, amount=pos.shares,
                                  side="SELL"))
        resp = self.client.post_order(order, self._OrderType.FOK)
        if not resp or not resp.get("success"):
            log.warning("live exit rejected: %s", resp)
            return 0.0
        yes_exit = snap.bid if pos.side == "BUY" else snap.ask
        pnl = self.portfolio.close(pos, yes_exit, reason)
        log.info("LIVE EXIT %s pnl $%.2f (%s)", pos.side, pnl, reason)
        return pnl
