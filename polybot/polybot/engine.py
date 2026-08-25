"""The main polling loop: discover → snapshot → signal → risk → execute."""
from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor

from .clob import ClobClient
from .config import Config
from .executor import LiveExecutor, PaperExecutor
from .gamma import GammaClient
from .models import Market, Signal, Snapshot
from .portfolio import Portfolio
from .risk import RiskManager
from .strategies import build_enabled

log = logging.getLogger(__name__)
REDISCOVER_EVERY = 40  # ticks between market re-discovery


class Engine:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.gamma = GammaClient()
        self.clob = ClobClient()
        self.risk = RiskManager(cfg)
        paper_cfg = cfg.get("paper", {})
        self.portfolio = Portfolio(
            starting_cash=float(paper_cfg.get("starting_cash", 1000)),
            path=paper_cfg.get("ledger_path", "paper_ledger.json"),
        )
        if cfg.mode == "live":
            self.executor = LiveExecutor(cfg, self.portfolio)
        else:
            self.executor = PaperExecutor(self.portfolio)
        self.history: dict[str, deque[Snapshot]] = defaultdict(
            lambda: deque(maxlen=int(cfg.get("history_size", 240))))
        # per-category strategy instances (overrides may differ per category)
        self._strategies_by_cat: dict[str, list] = {}
        self.markets: list[Market] = []
        self.paused = False
        self._last_exit: dict[str, float] = {}  # condition_id -> ts
        self.events: deque[dict] = deque(maxlen=200)  # feed for the dashboard

    @staticmethod
    def _today_start() -> float:
        """Start of the local calendar day — "daily loss stop" should mean
        the user's day, not UTC's, or the allowance resets mid-evening."""
        lt = time.localtime()
        return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday,
                            0, 0, 0, 0, 0, -1))

    def _event(self, kind: str, text: str) -> None:
        self.events.append({"ts": time.time(), "kind": kind, "text": text})

    def strategies_for(self, category: str) -> list:
        if category not in self._strategies_by_cat:
            merged = self.cfg.for_category(category).get("strategies", {})
            self._strategies_by_cat[category] = build_enabled(merged)
        return self._strategies_by_cat[category]

    def discover(self) -> None:
        m = self.cfg.get("markets", {})
        self.markets = self.gamma.discover(
            categories=m.get("categories", []),
            exclude=m.get("exclude_categories", []),
            limit_per_category=int(m.get("limit_per_category", 20)),
            min_volume_24h=float(m.get("min_volume_24h", 0)),
        )
        log.info("watching %d markets across %s", len(self.markets),
                 ", ".join(m.get("categories", [])))
        # prune history of markets we no longer watch or hold
        keep = ({mk.condition_id for mk in self.markets} |
                {p.market.condition_id for p in self.portfolio.positions})
        for cid in [c for c in self.history if c not in keep]:
            del self.history[cid]

    def _tick_universe(self) -> list[Market]:
        """Watched markets plus anything held that discovery has dropped.

        Discovery ranks by volume, so a held market is guaranteed to fall
        out of the watch list eventually — by resolving if nothing else.
        Without this union its position would never be exit-managed again:
        no snapshot, no stop, no take-profit, cash locked at a stale mark.
        """
        watched = {m.condition_id for m in self.markets}
        held = [p.market for p in self.portfolio.positions
                if p.market.condition_id not in watched]
        # one entry per market even with several positions in it
        extra: dict[str, Market] = {m.condition_id: m for m in held}
        return self.markets + list(extra.values())

    def _snapshots(self) -> list[tuple[Market, Snapshot | None]]:
        """Order-book snapshots for the whole tick universe, in parallel.

        Markets whose book has vanished come back with None so the caller
        can tell "no data this tick" apart from "not fetched at all" — a
        held market with no book may have resolved and needs settling.
        """
        with ThreadPoolExecutor(max_workers=8) as pool:
            snaps = pool.map(
                lambda m: (m, self.clob.snapshot(m.yes_token, m.volume_24h)),
                self._tick_universe())
            return list(snaps)

    def tick(self) -> list[Signal]:
        """One pass over all markets. Returns signals acted on."""
        acted: list[Signal] = []
        watched = {m.condition_id for m in self.markets}
        for market, snap in self._snapshots():
            if snap is None:
                # No book. For a held market that can mean it resolved —
                # check and settle rather than carrying it blind forever.
                self._maybe_settle(market)
                continue
            hist = self.history[market.condition_id]
            hist.append(snap)
            self._manage_exits(market, snap)
            if (self.paused
                    or market.condition_id not in watched
                    or not self.risk.price_ok(snap)
                    or not self.risk.spread_ok(snap)):
                continue
            cooldown = 60 * float(self.cfg.for_category(market.category)
                                  .get("risk", {})
                                  .get("reentry_cooldown_minutes", 30))
            if time.time() - self._last_exit.get(market.condition_id, 0) < cooldown:
                continue
            strategies = self.strategies_for(market.category)
            needs_tape = any(s.name == "whale_follow" for s in strategies)
            trades = (self.clob.recent_trades(market.condition_id)
                      if needs_tape else [])
            for strat in strategies:
                sig = strat.evaluate(market, list(hist), trades)
                if not sig:
                    continue
                reachable, why_not = self.risk.exits_reachable(
                    sig.side, snap, market.category)
                if not reachable:
                    log.debug("skip %s: %s", sig, why_not)
                    continue
                realized = self.portfolio.realized_pnl_since(self._today_start())
                ok, why = self.risk.allow_entry(
                    sig, self.portfolio.positions, realized)
                if not ok:
                    log.debug("skip %s: %s", sig, why)
                    continue
                usd = self.risk.entry_size(sig)
                if self.executor.enter(sig, snap, usd):
                    acted.append(sig)
                    self._event("enter", str(sig))
                break  # at most one entry per market per tick
        return acted

    def _maybe_settle(self, market: Market) -> None:
        """Settle positions in a market whose order book has disappeared.

        Gamma is the referee: only a market it reports closed with a 0-or-1
        YES price gets booked, at that price with no exit spread (resolution
        pays face value). Anything ambiguous is held for the next tick —
        holding is recoverable, a wrong settlement is not. Live-mode token
        redemption happens on-chain outside this bot; the ledger entry here
        mirrors what that redemption pays.
        """
        held = [p for p in self.portfolio.positions
                if p.market.condition_id == market.condition_id]
        if not held:
            return
        closed, yes_price = self.gamma.resolution(market.condition_id)
        if not closed or yes_price is None:
            return
        for pos in held:
            pnl = self.portfolio.close(pos, yes_price, f"settled YES={yes_price:.0f}")
            self._last_exit[market.condition_id] = time.time()
            self._event("exit", f"{pos.side} {market.question[:60]} "
                                f"pnl ${pnl:+.2f} (settled)")
            log.info("SETTLED %s %s pnl $%+.2f", pos.side,
                     market.question[:60], pnl)

    def _manage_exits(self, market: Market, snap: Snapshot) -> None:
        for pos in [p for p in self.portfolio.positions
                    if p.market.condition_id == market.condition_id]:
            reason = self.risk.should_exit(pos, snap.mid)
            if reason:
                pnl = self.executor.exit(pos, snap, reason)
                self._last_exit[pos.market.condition_id] = time.time()
                self._event("exit", f"{pos.side} {pos.market.question[:60]} "
                                    f"pnl ${pnl:+.2f} ({reason})")

    def run(self) -> None:
        self.discover()
        tick_n = 0
        log.info("engine started in %s mode, cash $%.2f",
                 self.cfg.mode, self.portfolio.cash)
        while True:
            # Ctrl-C nearly always lands in the sleep (it is most of a
            # tick's wall time), so the sleep must sit inside the same
            # handler as the work — a clean stop, never a traceback.
            try:
                try:
                    if tick_n and tick_n % REDISCOVER_EVERY == 0:
                        self.discover()
                    acted = self.tick()
                    for sig in acted:
                        log.info("entered: %s", sig)
                except Exception:
                    log.exception("tick failed; continuing")
                tick_n += 1
                time.sleep(float(self.cfg.get("poll_seconds", 15)))
            except KeyboardInterrupt:
                log.info("stopping; ledger saved")
                self.portfolio.save()
                return
