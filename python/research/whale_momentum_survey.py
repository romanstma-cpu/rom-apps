from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
_APPDATA = os.environ.get("APPDATA") or (Path.home() / ".config")
os.environ.setdefault("ROM_POLYBOT_USERDATA", str(Path(_APPDATA) / "ROM PolyBot"))

import backtest as bt
import db as dbmod
import trader as trader_mod
from config import merge_with_defaults


def app_config() -> dict:
    p = Path(os.environ["ROM_POLYBOT_USERDATA"]) / "settings.json"
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        return merge_with_defaults(raw.get("config") or {})
    except (OSError, json.JSONDecodeError):
        return merge_with_defaults({})


def follower_pnl(sig: dict, source: str, slippage_c: float) -> tuple[float, float] | None:
    price = sig.get("price")
    if price is None:
        return None
    price = float(price)
    if source == "momentum" and (sig.get("direction") or "yes").lower() == "no":
        price = 1.0 - price
    if not (0.0 < price < 1.0):
        return None
    cost = min(0.99, price + slippage_c / 100.0)
    correct = bool(sig.get("outcome_correct"))
    return cost, bt.net_pnl_per_contract(cost, correct, bt.epoch_of(sig.get("created_at")))


def clustered_t(by_event: dict[str, list[float]]) -> float | None:
    means = [sum(v) / len(v) for v in by_event.values() if v]
    n = len(means)
    if n < 2:
        return None
    mu = sum(means) / n
    var = sum((x - mu) ** 2 for x in means) / (n - 1)
    if var <= 1e-12:
        return None
    return mu / math.sqrt(var / n)


def summarize(rows: list[tuple[dict, float]]) -> dict:
    if not rows:
        return {"n": 0}
    pnls = [p for _s, p in rows]
    by_event = defaultdict(list)
    for s, p in rows:
        by_event[str(s.get("event_ticker") or s.get("ticker") or "?")].append(p)
    t = clustered_t(by_event)
    return {
        "n": len(rows), "events": len(by_event),
        "win": sum(1 for p in pnls if p > 0) / len(pnls),
        "net_c": sum(pnls) / len(pnls) * 100.0,
        "t": t,
    }


def fmt(label: str, s: dict) -> str:
    if not s.get("n"):
        return f"  {label:<28} (no signals)"
    t = f"{s['t']:+.1f}" if s.get("t") is not None else "   -"
    return (f"  {label:<28} n={s['n']:>5} evts={s['events']:>4} "
            f"win={s['win']*100:>5.1f}% net={s['net_c']:>+7.2f}c/ct t={t}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--slippage", type=float, default=1.0)
    args = ap.parse_args()
    cfg = app_config()

    with dbmod.get_db() as conn:
        whales = [dict(r) for r in conn.execute(
            """SELECT * FROM whale_trades WHERE resolved=1
               AND outcome_correct IS NOT NULL
               AND created_at >= datetime('now', ?)""",
            (f"-{args.days} days",))]
        alerts = [dict(r) for r in conn.execute(
            """SELECT * FROM alerts WHERE resolved=1
               AND outcome_correct IS NOT NULL
               AND created_at >= datetime('now', ?)""",
            (f"-{args.days} days",))]

    for source, sigs in (("whale", whales), ("momentum", alerts)):
        print(f"\n===== {source.upper()} — {len(sigs)} resolved signals, "
              f"+{args.slippage:.0f}c slippage, fee-v2 by category =====")
        scored = []
        for s in sigs:
            r = follower_pnl(s, source, args.slippage)
            if r is not None:
                scored.append((s, r[1]))
        gated = []
        for s, p in scored:
            try:
                ok, _why = trader_mod.should_trade(s, source, cfg)
            except Exception:
                ok = False
            if ok:
                gated.append((s, p))

        by_cat = defaultdict(list)
        for s, p in scored:
            by_cat[str(s.get("category") or "?")].append((s, p))
        print("UNGATED by category:")
        for cat, rows in sorted(by_cat.items(), key=lambda kv: -len(kv[1])):
            print(fmt(cat, summarize(rows)))
        print(fmt("ALL (ungated)", summarize(scored)))
        print(f"GATED by current app config ({len(gated)} accepted):")
        by_cat_g = defaultdict(list)
        for s, p in gated:
            by_cat_g[str(s.get("category") or "?")].append((s, p))
        for cat, rows in sorted(by_cat_g.items(), key=lambda kv: -len(kv[1])):
            print(fmt(cat, summarize(rows)))
        print(fmt("ALL (gated)", summarize(gated)))

        print("UNGATED by category x week:")
        by_cw = defaultdict(list)
        for s, p in scored:
            wk = str(s.get("created_at") or "")[:10]
            try:
                import datetime as _dt
                d = _dt.date.fromisoformat(wk)
                key = f"{d.isocalendar()[0]}-W{d.isocalendar()[1]:02d}"
            except ValueError:
                key = "?"
            by_cw[(str(s.get("category") or "?"), key)].append((s, p))
        for (cat, wk), rows in sorted(by_cw.items()):
            if len(rows) >= 25:
                print(fmt(f"{cat} {wk}", summarize(rows)))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
