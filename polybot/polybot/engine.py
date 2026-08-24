"""The main polling loop: discover → snapshot → signal → risk → execute."""
from __future__ import annotations

import logging
import time
from collections import defaultdict, deque

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
        self._day_start = time.time() - (time.time() % 86400)
        self.paused = False
        self.events: deque[dict] = deque(maxlen=200)  # feed for the dashboard

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

    def tick(self) -> list[Signal]:
        """One pass over all markets. Returns signals acted on."""
        acted: list[Signal] = []
        for market in self.markets:
            snap = self.clob.snapshot(market.yes_token, market.volume_24h)
            if snap is None:
                continue
            hist = self.history[market.condition_id]
            hist.append(snap)
            self._manage_exits(market, snap)
            if self.paused or not self.risk.price_ok(snap):
                continue
            strategies = self.strategies_for(market.category)
            needs_tape = any(s.name == "whale_follow" for s in strategies)
            trades = (self.clob.recent_trades(market.condition_id)
                      if needs_tape else [])
            for strat in strategies:
                sig = strat.evaluate(market, list(hist), trades)
                if not sig:
                    continue
                realized = self.portfolio.realized_pnl_since(self._day_start)
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

    def _manage_exits(self, market: Market, snap: Snapshot) -> None:
        for pos in [p for p in self.portfolio.positions
                    if p.market.condition_id == market.condition_id]:
            reason = self.risk.should_exit(pos, snap.mid)
            if reason:
                pnl = self.executor.exit(pos, snap, reason)
                self._event("exit", f"{pos.side} {pos.market.question[:60]} "
                                    f"pnl ${pnl:+.2f} ({reason})")

    def run(self) -> None:
        self.discover()
        tick_n = 0
        log.info("engine started in %s mode, cash $%.2f",
                 self.cfg.mode, self.portfolio.cash)
        while True:
            try:
                if tick_n and tick_n % REDISCOVER_EVERY == 0:
                    self.discover()
                acted = self.tick()
                for sig in acted:
                    log.info("entered: %s", sig)
            except KeyboardInterrupt:
                log.info("stopping; ledger saved")
                self.portfolio.save()
                return
            except Exception:
                log.exception("tick failed; continuing")
            tick_n += 1
            time.sleep(float(self.cfg.get("poll_seconds", 15)))
