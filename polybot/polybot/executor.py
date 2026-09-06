"""Order execution: paper fills at the touch, or live via py-clob-client."""
from __future__ import annotations

import logging

from .config import Config
from .fees import FeeBook, taker_fee
from .models import Position, Signal, Snapshot
from .portfolio import Portfolio

log = logging.getLogger(__name__)


class PaperExecutor:
    """Simulated fills: buys lift the ask, sells hit the bid (worst case).

    Both legs are charged the real Polymarket taker fee. A simulation that
    skips the fee is not a cheaper simulation, it is a wrong one — it
    reports a win rate the exchange would never have paid out.
    """

    def __init__(self, portfolio: Portfolio, fees: FeeBook | None = None):
        self.portfolio = portfolio
        # A disabled book charges nothing and touches no network; the engine
        # always hands in a live one.
        self.fees = fees if fees is not None else FeeBook(enabled=False)

    def enter(self, signal: Signal, snap: Snapshot, usd: float) -> Position | None:
        # long YES fills at the YES ask; long NO at (1 - bid) of YES
        price = snap.ask if signal.side == "BUY" else 1.0 - snap.bid
        if price <= 0 or price >= 1:
            return None
        shares = round(usd / price, 2)
        fee = taker_fee(shares, price,
                        self.fees.rate_for(signal.market.condition_id))
        # The fee is charged on top of the stake, so the bankroll has to
        # cover both or the fill could not have happened.
        if usd + fee > self.portfolio.cash:
            return None
        pos = Position(market=signal.market, side=signal.side,
                       entry_price=round(price, 4), shares=shares,
                       strategy=signal.strategy, fees_paid=round(fee, 4))
        self.portfolio.open(pos)
        log.info("PAPER ENTER %s %.2f sh @ %.3f ($%.2f, fee $%.2f) %s",
                 signal.side, pos.shares, price, usd, fee,
                 signal.market.question[:60])
        return pos

    def exit(self, pos: Position, snap: Snapshot, reason: str) -> float:
        # exit long YES at the bid; long NO at (1 - ask) of YES
        yes_exit = snap.bid if pos.side == "BUY" else snap.ask
        fee = taker_fee(pos.shares, pos.held_token_price(yes_exit),
                        self.fees.rate_for(pos.market.condition_id))
        pnl = self.portfolio.close(pos, yes_exit, reason, exit_fee=fee)
        log.info("PAPER EXIT  %s net $%.2f (fee $%.2f, %s) %s", pos.side,
                 pnl, fee, reason, pos.market.question[:60])
        return pnl


class LiveExecutor:
    """Real orders through py-clob-client. Imported lazily so paper mode
    never needs the dependency or any keys."""

    def __init__(self, cfg: Config, portfolio: Portfolio,
                 fees: FeeBook | None = None):
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
        self.fees = fees if fees is not None else FeeBook()

    def enter(self, signal: Signal, snap: Snapshot, usd: float) -> Position | None:
        token = (signal.market.yes_token if signal.side == "BUY"
                 else signal.market.no_token)
        order = self.client.create_market_order(
            self._MarketOrderArgs(token_id=token, amount=usd, side="BUY"))
        resp = self.client.post_order(order, self._OrderType.FOK)
        if not resp or not resp.get("success"):
            log.warning("live order rejected: %s", resp)
            return None
        # Ledger approximation: the FOK response does not carry the average
        # fill price, so the local ledger books the snapshot touch. Real
        # fills can be slightly worse in a moving book — treat the local
        # P&L as an estimate and the exchange history as the record.
        price = snap.ask if signal.side == "BUY" else 1.0 - snap.bid
        shares = round(usd / price, 2)
        fee = taker_fee(shares, price,
                        self.fees.rate_for(signal.market.condition_id))
        pos = Position(market=signal.market, side=signal.side,
                       entry_price=round(price, 4), shares=shares,
                       strategy=signal.strategy, fees_paid=round(fee, 4))
        self.portfolio.open(pos)
        log.info("LIVE ENTER %s $%.2f %s", signal.side, usd,
                 signal.market.question[:60])
        return pos

    def exit(self, pos: Position, snap: Snapshot, reason: str) -> float | None:
        """Close a live position. None means the exchange refused.

        The old version returned 0.0 on a rejected order, which the caller
        could not tell apart from a genuine break-even close: the engine
        logged an exit, started the re-entry cooldown, and showed the
        position as gone while it was still open and still exposed. A
        refusal has to be its own answer.
        """
        token = (pos.market.yes_token if pos.side == "BUY"
                 else pos.market.no_token)
        order = self.client.create_market_order(
            self._MarketOrderArgs(token_id=token, amount=pos.shares,
                                  side="SELL"))
        resp = self.client.post_order(order, self._OrderType.FOK)
        if not resp or not resp.get("success"):
            log.warning("live exit rejected, position still open: %s", resp)
            return None
        yes_exit = snap.bid if pos.side == "BUY" else snap.ask
        fee = taker_fee(pos.shares, pos.held_token_price(yes_exit),
                        self.fees.rate_for(pos.market.condition_id))
        pnl = self.portfolio.close(pos, yes_exit, reason, exit_fee=fee)
        log.info("LIVE EXIT %s net $%.2f (%s)", pos.side, pnl, reason)
        return pnl
