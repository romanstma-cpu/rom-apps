"""Command line interface: run | scan | portfolio."""
from __future__ import annotations

import argparse
import logging

from .config import Config
from .engine import Engine


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S")


def cmd_run(engine: Engine) -> None:
    engine.run()


def cmd_scan(engine: Engine) -> None:
    """One pass: print watched markets, current prices, and any signals."""
    engine.discover()
    print(f"{'category':<10} {'mid':>6} {'spread':>7} {'24h vol':>12}  question")
    for m in engine.markets:
        snap = engine.clob.snapshot(m.yes_token, m.volume_24h)
        if not snap:
            continue
        engine.history[m.condition_id].append(snap)
        print(f"{m.category:<10} {snap.mid:>6.3f} {snap.spread:>7.3f} "
              f"{m.volume_24h:>12,.0f}  {m.question[:70]}")
        for strat in engine.strategies_for(m.category):
            trades = (engine.clob.recent_trades(m.condition_id)
                      if strat.name == "whale_follow" else [])
            sig = strat.evaluate(m, list(engine.history[m.condition_id]), trades)
            if sig:
                print(f"    -> {sig}")


def cmd_portfolio(engine: Engine) -> None:
    p = engine.portfolio
    print(f"cash: ${p.cash:,.2f}   open positions: {len(p.positions)}")
    for pos in p.positions:
        snap = engine.clob.snapshot(pos.market.yes_token)
        mark = snap.mid if snap else pos.entry_price
        print(f"  {pos.side:<4} {pos.strategy:<16} entry {pos.entry_price:.3f} "
              f"pnl ${pos.pnl(mark):+.2f}  {pos.market.question[:60]}")
    if p.closed:
        total = sum(c['pnl'] for c in p.closed)
        print(f"closed trades: {len(p.closed)}, realized pnl ${total:+,.2f}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="polybot",
                                 description="Open Polymarket trading bot")
    ap.add_argument("command", choices=["run", "scan", "portfolio"])
    ap.add_argument("-c", "--config", help="path to config yaml")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    _setup_logging(args.verbose)
    cfg = Config.load(args.config)
    engine = Engine(cfg)
    {"run": cmd_run, "scan": cmd_scan, "portfolio": cmd_portfolio}[args.command](engine)


if __name__ == "__main__":
    main()
