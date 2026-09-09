from __future__ import annotations

import argparse
import math
import os
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from typing import Optional

import fees_us

# LEGACY - international exchange schedule, kept only so saved user scripts
# calling ctx fee helpers keep producing the numbers they were written
# against. Polymarket US charges a single flat coefficient with no category
# variation (see fees_us). Nothing new should read this table.
CATEGORY_TAKER_FEE: dict[str, float] = {
    "crypto": 0.07,
    "sports": 0.03,
    "finance": 0.04,
    "politics": 0.04,
    "mentions": 0.04,
    "tech": 0.04,
    "economics": 0.05,
    "culture": 0.05,
    "weather": 0.05,
    "other": 0.05,
    "geopolitics": 0.0,
}
DEFAULT_FEE_RATE = CATEGORY_TAKER_FEE["crypto"]
DEFAULT_FEE_COEFF = DEFAULT_FEE_RATE


def polymarket_fee_per_contract(
    price: float, fee_coeff: Optional[float] = None, category: str = "",
) -> float:
    """LEGACY per-category fee. Use `us_fee_per_contract` for anything new.

    Retained under its original name because `script_engine` exposes it to
    user scripts; changing it would silently move every saved script's
    numbers. It does not model the US retail schedule.
    """
    p = max(0.0, min(1.0, float(price)))
    rate = (
        float(fee_coeff) if fee_coeff is not None
        else CATEGORY_TAKER_FEE.get((category or "").strip().lower(), DEFAULT_FEE_RATE)
    )
    return rate * p * (1.0 - p)


def us_fee_per_contract(
    price: float, at: float, fee_coeff: Optional[float] = None,
) -> float:
    """Polymarket US taker fee for one contract: theta * P * (1-P).

    `theta` comes from the schedule in force at `at`, so a backtest spanning
    the 1 July 2026 change prices each signal on the rate that actually
    applied to it. Signals older than the first published schedule fall back
    to the earliest known rate; `count_unpriced_signals` reports how many.
    Pass `fee_coeff` to force one rate for sensitivity analysis.
    """
    p = max(0.0, min(1.0, float(price)))
    theta = (
        float(fee_coeff) if fee_coeff is not None
        else float(fees_us.coefficient_at_or_earliest(at))
    )
    return theta * p * (1.0 - p)


def count_unpriced_signals(signals: list[dict]) -> int:
    """Signals recorded before any published US schedule, priced by fallback."""
    return sum(
        1 for s in signals
        if fees_us.predates_published_schedule(float(s.get("at") or 0.0))
    )


def net_pnl_per_contract(
    cost: float, correct: bool, at: float, fee_coeff: Optional[float] = None,
) -> float:
    gross = (1.0 - cost) if correct else (-cost)
    return gross - us_fee_per_contract(cost, at, fee_coeff)


def signal_cost(row: dict, source: str) -> float:
    price = float(row.get("price") or 0.0)
    if source == "whale":
        return max(0.0, min(1.0, price))
    direction = (row.get("direction") or "yes").lower()
    cost = price if direction == "yes" else (1.0 - price)
    return max(0.0, min(1.0, cost))


def _cluster_key(s: dict, idx: int):
    ev = s.get("event")
    return ev if ev else ("\0__solo__", idx)


def _event_t(nets: list[float], keys: list) -> tuple[int, float]:
    groups: dict = defaultdict(list)
    for net, k in zip(nets, keys):
        groups[k].append(net)
    means = [sum(v) / len(v) for v in groups.values()]
    ne = len(means)
    if ne < 2:
        return ne, 0.0
    m = sum(means) / ne
    var = sum((x - m) ** 2 for x in means) / (ne - 1)
    se = math.sqrt(var) / math.sqrt(ne)
    return ne, ((m / se) if se > 0 else 0.0)


def summarize(signals: list[dict], fee_coeff: Optional[float] = None) -> dict:
    n = len(signals)
    if n == 0:
        return {"n": 0, "wins": 0, "win_rate": 0.0, "gross_ev": 0.0,
                "fee_ev": 0.0, "net_ev": 0.0, "se": 0.0, "t": 0.0,
                "total_net": 0.0, "avg_cost": 0.0, "net_roi": 0.0,
                "n_events": 0, "t_event": 0.0}

    nets, grosses, fees, keys = [], [], [], []
    wins = 0
    for i, s in enumerate(signals):
        cost, correct = s["cost"], bool(s["correct"])
        if correct:
            wins += 1
        grosses.append((1.0 - cost) if correct else (-cost))
        at = float(s.get("at") or 0.0)
        fees.append(us_fee_per_contract(cost, at, fee_coeff))
        nets.append(net_pnl_per_contract(cost, correct, at, fee_coeff))
        keys.append(_cluster_key(s, i))

    mean_net = sum(nets) / n
    var = sum((x - mean_net) ** 2 for x in nets) / (n - 1) if n > 1 else 0.0
    sd = math.sqrt(var)
    se = sd / math.sqrt(n) if n > 0 else 0.0
    avg_cost = sum(s["cost"] for s in signals) / n
    n_events, t_event = _event_t(nets, keys)
    return {
        "n": n, "wins": wins, "win_rate": wins / n,
        "gross_ev": sum(grosses) / n,
        "fee_ev": sum(fees) / n,
        "net_ev": mean_net,
        "se": se,
        "t": (mean_net / se) if se > 0 else 0.0,
        "total_net": sum(nets),
        "avg_cost": avg_cost,
        "net_roi": (mean_net / avg_cost) if avg_cost > 0 else 0.0,
        "n_events": n_events, "t_event": t_event,
    }


def threshold_sweep(
    signals: list[dict], thresholds: list[float], fee_coeff: Optional[float] = None
) -> list[dict]:
    out = []
    for th in thresholds:
        sub = [s for s in signals if s["confidence"] >= th]
        out.append({"threshold": th, **summarize(sub, fee_coeff)})
    return out


PRICE_BUCKETS = [
    (0.00, 0.30, "<30c"), (0.30, 0.50, "30-50c"), (0.50, 0.70, "50-70c"),
    (0.70, 0.85, "70-85c"), (0.85, 1.01, "85c+"),
]


def _price_label(cost: float) -> str:
    for lo, hi, label in PRICE_BUCKETS:
        if lo <= cost < hi:
            return label
    return "?"


def summarize_fade(signals: list[dict], fee_coeff: Optional[float] = None) -> dict:
    faded = [{"cost": 1.0 - s["cost"], "correct": (not s["correct"]),
              "confidence": s["confidence"], "category": s.get("category", ""),
              "event": s.get("event", "")} for s in signals]
    return summarize(faded, fee_coeff)


def group_summaries(signals: list[dict], key, fee_coeff: Optional[float] = None) -> dict:
    groups: dict[str, list] = {}
    for s in signals:
        groups.setdefault(key(s), []).append(s)
    return {k: summarize(v, fee_coeff) for k, v in groups.items()}


def format_breakdown(signals: list[dict], fee_coeff: float) -> str:
    L = ["", "════════════ BREAKDOWN ════════════"]
    for src in ("whale", "momentum"):
        sub = [s for s in signals if s["source"] == src]
        if not sub:
            continue
        L.append("")
        L.append(f"── {src.upper()}  (n={len(sub)}) ──")
        L.append("  by entry price:            (t = per-EVENT)")
        pb = group_summaries(sub, lambda s: _price_label(s["cost"]), fee_coeff)
        for _, _, label in PRICE_BUCKETS:
            if label in pb:
                r = pb[label]
                L.append(f"    {label:<7} n={r['n']:<5} ev={r['n_events']:<4} win {r['win_rate']*100:4.0f}%  "
                         f"net {_money(r['net_ev'])} (t={r['t_event']:+.1f})")
        cb = group_summaries([s for s in sub if s["category"]], lambda s: s["category"], fee_coeff)
        if cb:
            L.append("  by category (top 6 by n):    (t = per-EVENT)")
            for cat, r in sorted(cb.items(), key=lambda kv: -kv[1]["n"])[:6]:
                L.append(f"    {cat:<13} n={r['n']:<5} ev={r['n_events']:<4} win {r['win_rate']*100:4.0f}%  "
                         f"net {_money(r['net_ev'])} (t={r['t_event']:+.1f})")
        follow = summarize(sub, fee_coeff)["net_ev"]
        fade = summarize_fade(sub, fee_coeff)
        L.append(f"  FADE (bet opposite): net {_money(fade['net_ev'])} (t/event={fade['t_event']:+.1f})   "
                 f"vs follow {_money(follow)}")
    return "\n".join(L)


def verdict(overall: dict, sweep: list[dict]) -> str:
    if overall["n"] < 30:
        return ("INCONCLUSIVE — too few resolved signals (need ~100+). "
                "Run the bot longer to accumulate data.")
    if overall.get("n_events", overall["n"]) < 10:
        return (f"INCONCLUSIVE — {overall['n']} signals but only "
                f"{overall.get('n_events', 0)} distinct events. The edge rests on too "
                f"few independent outcomes to trust; need ~30+ events.")
    best = max(
        (r for r in sweep if r["n"] >= 30 and r.get("n_events", 0) >= 10),
        key=lambda r: r["net_ev"], default=None,
    )
    if overall["net_ev"] > 0 and overall["t_event"] > 2:
        return (f"POSITIVE net-of-fee edge, significant across {overall['n_events']} "
                f"events (per-event t={overall['t_event']:+.1f}). Worth hardening.")
    if best and best["net_ev"] > 0 and best["t_event"] > 2:
        return (f"Net edge appears only when filtered to confidence >= {best['threshold']:.0f} "
                f"(net +${best['net_ev']:.4f}/contract, per-event t={best['t_event']:.1f}). "
                f"Tighten the gate — but beware in-sample overfitting to that threshold.")
    if overall["net_ev"] > 0:
        return (f"Marginally positive but WITHIN NOISE (per-event t={overall['t_event']:+.1f}, "
                f"need >2). The per-signal t={overall['t']:+.1f} looks better only because it "
                f"over-counts clustered signals as independent. Not distinguishable from zero.")
    return ("NEGATIVE after fees. The signals do not have a net-of-fee edge as configured — "
            "fix the strategy/fees before trading real money.")


def epoch_of(value, default: float = 0.0) -> float:
    """Parse a stored timestamp to epoch seconds, tolerating both formats.

    Rows are written either as SQLite `datetime('now')` ("YYYY-MM-DD HH:MM:SS")
    or as ISO-8601 with a trailing Z; both are UTC.
    """
    text = str(value or "").strip()
    if not text:
        return default
    from datetime import datetime as _dt, timezone as _tz
    normalised = text.replace("Z", "+00:00").replace(" ", "T", 1)
    try:
        stamp = _dt.fromisoformat(normalised)
    except ValueError:
        return default
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=_tz.utc)
    return stamp.timestamp()


def tick_epoch(row: Optional[dict], default: float = 0.0) -> float:
    """Epoch seconds for a recorded market tick, for picking its fee schedule."""
    return epoch_of((row or {}).get("observed_at"), default)


def load_resolved_signals(conn: sqlite3.Connection) -> list[dict]:
    conn.row_factory = sqlite3.Row
    out: list[dict] = []
    for src, table in (("whale", "whale_trades"), ("momentum", "alerts")):
        try:
            rows = conn.execute(
                f"SELECT * FROM {table} "
                f"WHERE resolved=1 AND outcome_correct IS NOT NULL"
            ).fetchall()
        except sqlite3.OperationalError:
            continue
        for raw in rows:
            r = dict(raw)
            entered = epoch_of(r.get("created_at"))
            out.append({
                "source": src,
                "confidence": float(r.get("confidence") or 0.0),
                "cost": signal_cost(r, src),
                "correct": int(r["outcome_correct"]) == 1,
                "category": r.get("category") or "",
                "event": r.get("event_ticker") or r.get("title") or "",
                "ticker": r.get("ticker") or "",
                # Fee schedule is chosen by entry time; the portfolio
                # simulator also needs to know when capital came back.
                "at": entered,
                "resolved_at": epoch_of(r.get("resolved_at"), entered),
            })
    return out


def resolve_db_path(arg_db: Optional[str]) -> Path:
    if arg_db:
        return Path(arg_db)
    env = os.environ.get("ROM_POLYBOT_USERDATA")
    if env:
        return Path(env) / "data" / "rom-polybot.db"
    appdata = os.environ.get("APPDATA")
    if appdata:
        p = Path(appdata) / "ROM PolyBot" / "data" / "rom-polybot.db"
        if p.exists():
            return p
    return Path(__file__).resolve().parent / "data" / "rom-polybot.db"


def build_report(signals: list[dict], fee_coeff: float) -> dict:
    thresholds = [50, 55, 60, 65, 70, 75, 80, 85, 90]
    overall = summarize(signals, fee_coeff)
    by_source = {
        src: summarize([s for s in signals if s["source"] == src], fee_coeff)
        for src in ("whale", "momentum")
    }
    sweep = threshold_sweep(signals, thresholds, fee_coeff)
    return {
        "overall": overall, "by_source": by_source, "sweep": sweep,
        "verdict": verdict(overall, sweep), "fee_coeff": fee_coeff,
        "unpriced_signals": count_unpriced_signals(signals),
        "notes": [
            "Models entry → hold-to-settlement only. Per-position take-profit "
            "(take_profit_pct) is NOT simulated here: main-bot markets record a "
            "single entry price per signal with no post-entry price series, so "
            "there's no way to know when a bid would have crossed the target. The "
            "crypto backtest (replay) DOES model take-profit from recorded ticks; "
            "for the main bot, watch live exit_reason='take_profit' rows in History.",
        ],
    }


def _money(x: float) -> str:
    return f"{'+' if x >= 0 else '-'}${abs(x):.4f}"


def format_report(report: dict, source_label: str) -> str:
    o = report["overall"]
    L = []
    L.append("═══ ROM PolyBot — fee-aware signal backtest ═══")
    L.append(f"source: {source_label}")
    _fc = report.get("fee_coeff")
    L.append(
        "fee model: Polymarket US taker fee, θ × P·(1−P)"
        + (f" (forced θ {float(_fc):.4f})" if _fc is not None
           else " (θ from the schedule in force at each signal: "
                "0.05, then 0.06 from 1 Jul 2026)")
    )
    _unpriced = report.get("unpriced_signals") or 0
    if _unpriced:
        L.append(
            f"  note: {_unpriced} signal(s) predate the first published US "
            f"schedule and were priced at the earliest known θ (0.05)."
        )
    n_w = sum(1 for k in ('whale',) for _ in [0]) if False else report['by_source']['whale']['n']
    n_m = report['by_source']['momentum']['n']
    L.append(f"resolved signals: {o['n']}  (whale {n_w}, momentum {n_m})")
    L.append("")
    if o["n"] == 0:
        L.append("No resolved signals found. Run the bot (even in demo/dry-run) long")
        L.append("enough for signals to settle, then re-run this backtest.")
        return "\n".join(L)

    L.append("OVERALL (1 contract per signal)")
    L.append(f"  win rate            {o['win_rate']*100:5.1f}%")
    L.append(f"  gross edge/contract {_money(o['gross_ev'])}")
    L.append(f"  fees/contract       {_money(-o['fee_ev'])}")
    L.append(f"  NET edge/contract   {_money(o['net_ev'])}")
    L.append(f"  significance        per-EVENT t = {o['t_event']:+.1f}  "
             f"({o['n_events']} events)   [per-signal t = {o['t']:+.1f}, over-counts]")
    L.append(f"  net ROI on cost     {o['net_roi']*100:+.1f}%")
    L.append(f"  total net P&L       {_money(o['total_net'])}")
    L.append("  → trust the per-EVENT t: signals on one market settle together,")
    L.append("    so they are not independent bets. Per-signal t runs high on noise.")
    L.append("")
    L.append("BY SOURCE")
    for src in ("whale", "momentum"):
        s = report["by_source"][src]
        if s["n"] == 0:
            L.append(f"  {src:<9} (none)")
            continue
        L.append(f"  {src:<9} n={s['n']:<5} ev={s['n_events']:<4} win {s['win_rate']*100:4.0f}%  "
                 f"net {_money(s['net_ev'])}  t/event {s['t_event']:+.1f}  "
                 f"(t/sig {s['t']:+.1f})")
    L.append("")
    L.append("CONFIDENCE THRESHOLD SWEEP")
    L.append("  conf≥   n     events  win    net/contract   t/event  (t/sig)")
    for r in report["sweep"]:
        if r["n"] == 0:
            continue
        L.append(f"  {r['threshold']:>4.0f}   {r['n']:<6}{r['n_events']:<7} {r['win_rate']*100:4.0f}%   "
                 f"{_money(r['net_ev']):>9}    {r['t_event']:+.1f}     ({r['t']:+.1f})")
    L.append("")
    L.append(f"VERDICT: {report['verdict']}")
    for note in report.get("notes", []):
        L.append("")
        L.append(f"NOTE: {note}")
    return "\n".join(L)


# Just after the first published US fee schedule, so ~6 months of demo
# signals span the 1 July coefficient change.
DEMO_START = 1775260800.0   # 2026-04-04T00:00:00Z


def demo_signals(n: int = 4000, seed: int = 42) -> list[dict]:
    import random
    rng = random.Random(seed)
    out = []
    at = DEMO_START
    for i in range(n):
        src = "whale" if rng.random() < 0.6 else "momentum"
        cost = rng.uniform(0.18, 0.88)
        edge = rng.gauss(0.012, 0.035)
        true_prob = max(0.02, min(0.98, cost + edge))
        correct = rng.random() < true_prob
        confidence = max(5.0, min(97.0, true_prob * 100 + rng.gauss(0, 6)))
        at += rng.uniform(600.0, 7200.0)
        out.append({"source": src, "confidence": confidence, "cost": cost,
                    "correct": correct, "category": "",
                    "event": f"DEMO-EV-{i}", "ticker": f"DEMO-{i}",
                    "at": at, "resolved_at": at + rng.uniform(3600.0, 5 * 86400.0)})
    return out


def load_crypto15m_signals(conn: sqlite3.Connection, interval: str = "15m") -> list[dict]:
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """SELECT * FROM crypto15m_signals
               WHERE resolved=1 AND up_won IS NOT NULL
                 AND COALESCE(interval, '15m') = ?""",
            (interval,),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    out: list[dict] = []
    for raw in rows:
        r = dict(raw)
        fav = (r.get("favorite") or "").lower()
        if fav not in ("up", "down"):
            continue
        up_won = int(r["up_won"]) == 1
        fav_won = (fav == "up" and up_won) or (fav == "down" and not up_won)
        try:
            fav_price = float(r.get("favorite_price") or 0.0)
        except (TypeError, ValueError):
            fav_price = 0.0
        try:
            entry_cost = float(r.get("entry_cost") or fav_price)
        except (TypeError, ValueError):
            entry_cost = fav_price
        dp = r.get("delta_pct")

        def _num(key):
            v = r.get(key)
            try:
                return float(v) if v is not None else None
            except (TypeError, ValueError):
                return None

        out.append({
            "favorite": fav,
            "favorite_price": max(0.0, min(1.0, fav_price)),
            "entry_cost": max(0.0, min(1.0, entry_cost)),
            "fav_won": fav_won,
            "delta_pct": float(dp) if dp is not None else None,
            "mins_left": float(r["mins_left"]) if r.get("mins_left") is not None else None,
            "macd_hist": _num("macd_hist"),
            "macd_cross": _num("macd_cross"),
            "rsi": _num("rsi"),
        })
    return out


def crypto15m_eval(
    signals: list[dict], *, mode: str = "favorite", min_fav: float = 0.0,
    max_fav: float = 1.0, min_delta_pct: float = 0.0,
    fee_coeff: Optional[float] = None,
) -> dict:
    built: list[dict] = []
    for s in signals:
        fp = s["favorite_price"]
        if fp < min_fav or fp > max_fav:
            continue
        if min_delta_pct > 0:
            dp = s["delta_pct"]
            if dp is None or dp * 100.0 < min_delta_pct:
                continue
        if mode == "contrarian":
            spread = max(0.0, float(s["entry_cost"]) - fp) if s.get("entry_cost") else 0.0
            cost = max(0.0, min(1.0, (1.0 - fp) + spread))
            correct = not s["fav_won"]
        else:
            cost = s["entry_cost"]
            correct = s["fav_won"]
        built.append({"cost": cost, "correct": correct, "confidence": fp * 100.0})
    return summarize(built, fee_coeff)


def _macd_aligns(s: dict) -> Optional[bool]:
    mh = s.get("macd_hist")
    if mh is None or mh == 0:
        return None
    return (s.get("favorite") == "up") == (mh > 0)


def crypto15m_macd_breakdown(
    signals: list[dict], fee_coeff: Optional[float] = None
) -> dict:
    classifiable = [s for s in signals if _macd_aligns(s) is not None]
    agree = [s for s in classifiable if _macd_aligns(s) is True]
    conflict = [s for s in classifiable if _macd_aligns(s) is False]
    return {
        "nWithMacd": len(classifiable),
        "agree": crypto15m_eval(agree, mode="favorite", fee_coeff=fee_coeff),
        "conflict": crypto15m_eval(conflict, mode="favorite", fee_coeff=fee_coeff),
    }


_FAV_THRESHOLDS = [50, 60, 70, 80, 85, 90, 95]
_DELTA_THRESHOLDS = [0.0, 0.05, 0.10, 0.20, 0.40]
_FAV_BANDS = [(50, 70), (70, 80), (80, 85), (85, 90), (90, 95), (95, 100)]


def crypto15m_report(signals: list[dict], fee_coeff: Optional[float] = None) -> dict:
    favorite = {"mode": "favorite", **crypto15m_eval(signals, mode="favorite", fee_coeff=fee_coeff)}
    contrarian = {"mode": "contrarian", **crypto15m_eval(signals, mode="contrarian", fee_coeff=fee_coeff)}
    fav_sweep = [
        {"threshold": th, "mode": "favorite",
         **crypto15m_eval(signals, mode="favorite", min_fav=th / 100.0, fee_coeff=fee_coeff)}
        for th in _FAV_THRESHOLDS
    ]
    delta_sweep = [
        {"minDeltaPct": d, "mode": "favorite",
         **crypto15m_eval(signals, mode="favorite", min_delta_pct=d, fee_coeff=fee_coeff)}
        for d in _DELTA_THRESHOLDS
    ]
    band_sweep = [
        {"minFav": lo, "maxFav": hi, "mode": "favorite",
         **crypto15m_eval(signals, mode="favorite", min_fav=lo / 100.0,
                          max_fav=hi / 100.0, fee_coeff=fee_coeff)}
        for lo, hi in _FAV_BANDS
    ]
    candidates = [favorite, contrarian, *fav_sweep, *delta_sweep, *band_sweep]
    eligible = [c for c in candidates if c.get("n", 0) >= 30]
    best = max(eligible, key=lambda c: c["net_ev"], default=None)
    n_variants = len(eligible)
    return {
        "n": len(signals),
        "favorite": favorite,
        "contrarian": contrarian,
        "favoriteSweep": fav_sweep,
        "deltaSweep": delta_sweep,
        "bandSweep": band_sweep,
        "macdBreakdown": crypto15m_macd_breakdown(signals, fee_coeff=fee_coeff),
        "best": best,
        "fee_coeff": fee_coeff,
        "verdict": _crypto15m_verdict(len(signals), favorite, contrarian, best, n_variants),
    }


def _bonferroni_t(k: int) -> float:
    for kk, z in ((1, 1.96), (2, 2.24), (3, 2.39), (5, 2.58),
                  (8, 2.73), (12, 2.87), (20, 3.02), (30, 3.14)):
        if k <= kk:
            return z
    return 3.3


def _crypto15m_verdict(n: int, favorite: dict, contrarian: dict,
                       best: dict | None, n_variants: int = 1) -> str:
    if n < 30:
        return (f"COLLECTING DATA — {n} settled 15m signals so far (need ~100+). "
                "Leave the app open; the recorder logs every quarter automatically.")
    t_bar = _bonferroni_t(n_variants)
    if best and best["net_ev"] > 0 and best["t"] > t_bar:
        mode = best.get("mode", "favorite")
        th = best.get("threshold")
        dd = best.get("minDeltaPct")
        lo, hi = best.get("minFav"), best.get("maxFav")
        if th:
            tag = f"favorite-follow ≥ {th}¢"
        elif dd:
            tag = f"favorite-follow, Δ ≥ {dd}%"
        elif lo is not None and hi is not None:
            tag = f"favorite-follow {lo}–{hi}¢"
        else:
            tag = "favorite-follow" if mode == "favorite" else "contrarian-fade"
        return (f"Net edge found: {tag} → +{best['net_ev']*100:.1f}¢/contract "
                f"(t={best['t']:.1f} > {t_bar:.1f} bar, best of {n_variants} "
                f"variants, n={best['n']}). Still in-sample — paper-trade it.")
    if max(favorite["net_ev"], contrarian["net_ev"]) > 0:
        return (f"Marginally positive but WITHIN NOISE (best of {n_variants} "
                f"variants clears no t > {t_bar:.1f} bar). Keep collecting — "
                "not yet distinguishable from zero.")
    return ("NEGATIVE after fees so far. No 15m variant shows a net edge on your "
            "data yet — keep collecting and try the delta filter.")


def format_crypto15m_report(report: dict, source_label: str) -> str:
    fc = report.get("fee_coeff")
    L = ["═══ ROM PolyBot — 15-minute crypto backtest ═══",
         f"source: {source_label}",
         "fee model: taker fee rate × P·(1−P) "
         + (f"(forced rate {float(fc):.4f})" if fc is not None else "(US schedule in force at each signal)"),
         f"settled 15m signals: {report['n']}", ""]
    if report["n"] == 0:
        L.append("No settled 15m signals yet. Leave the app open — the recorder logs")
        L.append("each quarter's favorite + outcome automatically, then re-run this.")
        return "\n".join(L)

    def line(label: str, r: dict) -> str:
        return (f"  {label:<22} n={r['n']:<5} win {r['win_rate']*100:4.0f}%  "
                f"net {_money(r['net_ev'])}/contract (t={r['t']:+.1f})")

    L.append("OVERALL (1 contract per signal)")
    L.append(line("favorite-follow", report["favorite"]))
    L.append(line("contrarian-fade", report["contrarian"]))
    L.append("")
    L.append("FAVORITE-FOLLOW by minimum favorite price")
    L.append("  fav≥   n      win    net/contract   t")
    for r in report["favoriteSweep"]:
        if r["n"] == 0:
            continue
        L.append(f"  {r['threshold']:>4}¢  {r['n']:<6} {r['win_rate']*100:4.0f}%   "
                 f"{_money(r['net_ev']):>9}     {r['t']:+.1f}")
    L.append("")
    L.append("FAVORITE-FOLLOW by favorite-price band (disjoint)")
    L.append("  band      n      win    net/contract   t")
    for r in report["bandSweep"]:
        if r["n"] == 0:
            continue
        L.append(f"  {r['minFav']:>2}-{r['maxFav']:<3}¢  {r['n']:<6} {r['win_rate']*100:4.0f}%   "
                 f"{_money(r['net_ev']):>9}     {r['t']:+.1f}")
    L.append("")
    L.append("FAVORITE-FOLLOW by minimum underlying delta")
    L.append("  Δ≥     n      win    net/contract   t")
    for r in report["deltaSweep"]:
        if r["n"] == 0:
            continue
        L.append(f"  {r['minDeltaPct']:>4}%  {r['n']:<6} {r['win_rate']*100:4.0f}%   "
                 f"{_money(r['net_ev']):>9}     {r['t']:+.1f}")
    mb = report.get("macdBreakdown")
    if mb and mb.get("nWithMacd"):
        L.append("")
        L.append(f"FAVORITE-FOLLOW by underlying MACD ({mb['nWithMacd']} signals w/ MACD)")
        L.append("  MACD vs side   n      win    net/contract   t")
        for label, r in (("agrees", mb["agree"]), ("conflicts", mb["conflict"])):
            if r["n"] == 0:
                continue
            L.append(f"  {label:<12}  {r['n']:<6} {r['win_rate']*100:4.0f}%   "
                     f"{_money(r['net_ev']):>9}     {r['t']:+.1f}")
    L.append("")
    L.append(f"VERDICT: {report['verdict']}")
    return "\n".join(L)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="Fee-aware ROM PolyBot signal backtest")
    ap.add_argument("--db", help="path to rom-polybot.db (default: auto-detect)")
    ap.add_argument("--fee", type=float, default=None,
                    help="force a single taker-fee coefficient for everything "
                         "(default: the US schedule in force at each signal)")
    ap.add_argument("--portfolio", action="store_true",
                    help="simulate a real account (bankroll, sizing, concurrency "
                         "and daily caps) instead of averaging one contract per signal")
    ap.add_argument("--bankroll", type=float, default=1000.0,
                    help="starting bankroll for --portfolio (default: 1000)")
    ap.add_argument("--min-confidence", type=float, default=0.0,
                    help="only enter signals at or above this confidence "
                         "when running --portfolio")
    ap.add_argument("--demo", action="store_true",
                    help="run on synthetic data instead of your DB")
    ap.add_argument("--breakdown", action="store_true",
                    help="also break down by entry-price, category, and a fade check")
    ap.add_argument("--c15", action="store_true",
                    help="backtest the recurring crypto up/down strategy (crypto15m_signals)")
    ap.add_argument("--interval", choices=("5m", "15m", "hourly"), default="15m",
                    help="which recorded window series --c15 reports on (default 15m); "
                         "rows are stamped with the interval they were recorded from")
    args = ap.parse_args()

    if args.c15:
        db_path = resolve_db_path(args.db)
        if not db_path.exists():
            print(f"DB not found at: {db_path}")
            return 1
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            sigs = load_crypto15m_signals(conn, interval=args.interval)
        finally:
            conn.close()
        print(format_crypto15m_report(crypto15m_report(sigs, args.fee), str(db_path)))
        return 0

    if args.demo:
        print("⚠  SYNTHETIC DEMO DATA — not your real signals.\n")
        signals = demo_signals()
        if args.portfolio:
            print(_portfolio_output(signals, "synthetic demo (4000 signals)", args))
            return 0
        report = build_report(signals, args.fee)
        print(format_report(report, "synthetic demo (4000 signals)"))
        if args.breakdown:
            print(format_breakdown(signals, args.fee))
        return 0

    db_path = resolve_db_path(args.db)
    if not db_path.exists():
        print(f"DB not found at: {db_path}")
        print("Pass --db <path>, or run `python backtest.py --demo` to see the format.")
        return 1
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        signals = load_resolved_signals(conn)
    finally:
        conn.close()
    if args.portfolio:
        print(_portfolio_output(signals, str(db_path), args))
        return 0
    report = build_report(signals, args.fee)
    print(format_report(report, str(db_path)))
    if args.breakdown:
        print(format_breakdown(signals, args.fee))
    return 0


def load_saved_config() -> tuple[dict, Optional[Path]]:
    """Read the trading config the desktop app saved, else fall back to defaults.

    The backend normally receives config over IPC, so the CLI has to read the
    same settings.json the app writes. Returns the path it used so the report
    can say whose settings produced the numbers.
    """
    import json

    from config import merge_with_defaults

    candidates = []
    env = os.environ.get("ROM_POLYBOT_USERDATA")
    if env:
        candidates.append(Path(env) / "settings.json")
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidates.append(Path(appdata) / "ROM PolyBot" / "settings.json")
    for path in candidates:
        try:
            if not path.exists():
                continue
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        return merge_with_defaults((raw or {}).get("config") or {}), path
    return merge_with_defaults({}), None


def _portfolio_output(signals: list[dict], source_label: str, args) -> str:
    """Run and render the portfolio simulation against the saved trading config."""
    import portfolio_backtest

    cfg, cfg_path = load_saved_config()
    result = portfolio_backtest.simulate(
        signals, cfg, start_bankroll_usd=args.bankroll,
        min_confidence=args.min_confidence,
    )
    return portfolio_backtest.format_portfolio_report(
        result, cfg, source_label,
        config_label=str(cfg_path) if cfg_path else "built-in defaults",
    )


if __name__ == "__main__":
    raise SystemExit(main())
