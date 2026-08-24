"""The main polling loop: discover → snapshot → signal → risk → execute."""
from __future__ import annotations

import logging
import threading
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
from .validate import validate

log = logging.getLogger(__name__)
REDISCOVER_EVERY = 40  # ticks between market re-discovery


class Engine:
    def __init__(self, cfg: Config):
        for note in validate(cfg) or []:
            log.warning("%s", note)
        self.cfg = cfg
        self.gamma = GammaClient()
        self.clob = ClobClient()
        self.risk = RiskManager(cfg)
        paper_cfg = cfg.get("paper", {})
        live_mode = cfg.mode == "live"
        # Separate ledgers per mode. Sharing one would let paper positions
        # issue real sell orders the first time live mode starts.
        ledger = (cfg.get("live", {}).get("ledger_path", "live_ledger.json")
                  if live_mode else
                  paper_cfg.get("ledger_path", "paper_ledger.json"))
        self.portfolio = Portfolio(
            starting_cash=float(paper_cfg.get("starting_cash", 1000)),
            path=ledger,
        )
        if live_mode:
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
        self._stop = threading.Event()
        # equity samples for the dashboard curve: (ts, cash + value of holdings)
        self.equity: deque[tuple[float, float]] = deque(maxlen=500)
        self.events: deque[dict] = deque(maxlen=200)  # feed for the dashboard

    def _sample_equity(self) -> None:
        held = 0.0
        for p in list(self.portfolio.positions):
            hist = self.history.get(p.market.condition_id)
            mark = p.held_token_price(hist[-1].mid) if hist else p.entry_price
            held += mark * p.shares
        self.equity.append((time.time(), round(self.portfolio.cash + held, 2)))

    @staticmethod
    def _today_start() -> float:
        return time.time() - (time.time() % 86400)

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

    def _snapshots(self) -> list[tuple[Market, Snapshot]]:
        """Fetch order-book snapshots for all watched markets in parallel."""
        with ThreadPoolExecutor(max_workers=8) as pool:
            snaps = pool.map(
                lambda m: (m, self.clob.snapshot(m.yes_token, m.volume_24h)),
                self.markets)
            return [(m, s) for m, s in snaps if s is not None]

    def tick(self) -> list[Signal]:
        """One pass over all markets. Returns signals acted on."""
        acted: list[Signal] = []
        for market, snap in self._snapshots():
            hist = self.history[market.condition_id]
            hist.append(snap)
            self._manage_exits(market, snap)
            if self.paused or not self.risk.price_ok(snap):
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
        self._sample_equity()
        return acted

    def _manage_exits(self, market: Market, snap: Snapshot) -> None:
        for pos in [p for p in self.portfolio.positions
                    if p.market.condition_id == market.condition_id]:
            reason = self.risk.should_exit(pos, snap.mid)
            if reason:
                pnl = self.executor.exit(pos, snap, reason)
                if pnl is None:      # exit rejected — still holding it
                    continue
                self._last_exit[pos.market.condition_id] = time.time()
                self._event("exit", f"{pos.side} {pos.market.question[:60]} "
                                    f"pnl ${pnl:+.2f} ({reason})")

    def stop(self) -> None:
        """Ask the run loop to finish the current tick and exit."""
        self._stop.set()

    def run(self) -> None:
        tick_n = 0
        log.info("engine started in %s mode, cash $%.2f",
                 self.cfg.mode, self.portfolio.cash)
        try:
            self.discover()
            while not self._stop.is_set():
                try:
                    if tick_n and tick_n % REDISCOVER_EVERY == 0:
                        self.discover()
                    for sig in self.tick():
                        log.info("entered: %s", sig)
                except Exception:
                    log.exception("tick failed; continuing")
                tick_n += 1
                # interruptible sleep: stop() wakes it immediately
                self._stop.wait(float(self.cfg.get("poll_seconds", 15)))
        except KeyboardInterrupt:
            pass
        finally:
            self.portfolio.save()
            log.info("engine stopped; ledger saved")
