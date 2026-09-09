from __future__ import annotations

import argparse
import math
import os
import sqlite3
from collections import defaultdict

# US taker coefficient; see fees_us for the dated schedule.
FEE_RATE = 0.06


def fee_cents(ask_frac: float) -> float:
    p = max(0.0, min(1.0, ask_frac))
    return FEE_RATE * (p * (1.0 - p)) * 100.0


def default_db() -> str:
    return os.path.join(
        os.environ.get("APPDATA", os.path.expanduser("~")),
        "ROM PolyBot", "data", "rom-polybot.db",
    )


def load_rows(db: str, interval: str) -> list[dict]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    where = ["t.model_prob IS NOT NULL", "s.up_won IS NOT NULL"]
    params: list = []
    if interval != "all":
        where.append("COALESCE(t.interval,'15m') = ?")
        params.append(interval)
    sql = f"""
        SELECT t.ticker, t.asset, t.model_prob, t.up_ask, t.no_ask,
               t.mins_left, t.observed_at, s.up_won, s.close_time,
               COALESCE(t.interval,'15m') AS iv
        FROM crypto15m_ticks t
        JOIN crypto15m_signals s ON s.ticker = t.ticker
        WHERE {' AND '.join(where)}
        ORDER BY t.ticker, t.observed_at
    """
    rows = [dict(r) for r in con.execute(sql, params)]
    con.close()
    return rows


_BINS = [(0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.85),
         (0.85, 0.9), (0.9, 0.95), (0.95, 1.0001)]


def _clip(p: float) -> float:
    return max(1e-6, min(1.0 - 1e-6, p))


def calibration(rows: list[dict]) -> dict:
    per_mkt = defaultdict(int)
    for r in rows:
        per_mkt[r["ticker"]] += 1

    briers_u, lls_u = [], []
    briers_w, lls_w, wsum = 0.0, 0.0, 0.0
    buckets = {b: {"n": 0.0, "wins": 0.0, "pred": 0.0} for b in _BINS}

    for r in rows:
        mp = float(r["model_prob"])
        up_won = int(r["up_won"])
        conf = mp if mp >= 0.5 else 1.0 - mp
        fav_won = up_won if mp >= 0.5 else (1 - up_won)
        w = 1.0 / per_mkt[r["ticker"]]

        briers_u.append((conf - fav_won) ** 2)
        lls_u.append(-(fav_won * math.log(_clip(conf))
                       + (1 - fav_won) * math.log(_clip(1 - conf))))
        briers_w += w * (conf - fav_won) ** 2
        lls_w += w * -(fav_won * math.log(_clip(conf))
                       + (1 - fav_won) * math.log(_clip(1 - conf)))
        wsum += w

        for b in _BINS:
            if b[0] <= conf < b[1]:
                buckets[b]["n"] += w
                buckets[b]["wins"] += w * fav_won
                buckets[b]["pred"] += w * conf
                break

    n = len(rows)
    return {
        "n_ticks": n,
        "n_markets": len(per_mkt),
        "brier_pertick": sum(briers_u) / n if n else 0.0,
        "logloss_pertick": sum(lls_u) / n if n else 0.0,
        "brier_mktbal": briers_w / wsum if wsum else 0.0,
        "logloss_mktbal": lls_w / wsum if wsum else 0.0,
        "buckets": [
            {
                "lo": b[0], "hi": min(b[1], 1.0),
                "n": buckets[b]["n"],
                "pred": (buckets[b]["pred"] / buckets[b]["n"]) if buckets[b]["n"] else 0.0,
                "realized": (buckets[b]["wins"] / buckets[b]["n"]) if buckets[b]["n"] else 0.0,
            }
            for b in _BINS
        ],
    }


def _side_edges(mp: float, up_ask, no_ask) -> dict:
    out = {}
    if up_ask and 0 < up_ask < 1:
        out["up"] = (mp * 100.0 - up_ask * 100.0 - fee_cents(up_ask), float(up_ask))
    if no_ask and 0 < no_ask < 1:
        out["down"] = ((1 - mp) * 100.0 - no_ask * 100.0 - fee_cents(no_ask), float(no_ask))
    return out


def _first_qualifying_trade(ticks: list[dict], thresh: float, late_mins: float | None):
    for r in ticks:
        if late_mins is not None and (r["mins_left"] is None or float(r["mins_left"]) > late_mins):
            continue
        edges = _side_edges(float(r["model_prob"]), r["up_ask"], r["no_ask"])
        if not edges:
            continue
        side, (edge, cost) = max(edges.items(), key=lambda kv: kv[1][0])
        if edge < thresh:
            continue
        up_won = int(r["up_won"])
        won = (side == "up" and up_won == 1) or (side == "down" and up_won == 0)
        cost_c = cost * 100.0
        fee_c = fee_cents(cost)
        pnl_c = (100.0 - cost_c - fee_c) if won else (-cost_c - fee_c)
        return {
            "ticker": r["ticker"], "asset": r["asset"], "side": side,
            "cost_c": cost_c, "edge_c": edge, "won": won, "pnl_c": pnl_c,
            "mins_left": r["mins_left"], "close_time": r["close_time"],
        }
    return None


def edge_pnl(rows: list[dict], thresh: float, late_mins: float | None) -> dict:
    by_mkt: dict[str, list] = defaultdict(list)
    for r in rows:
        by_mkt[r["ticker"]].append(r)
    trades = []
    for ticks in by_mkt.values():
        t = _first_qualifying_trade(ticks, thresh, late_mins)
        if t:
            trades.append(t)
    n = len(trades)
    total = sum(t["pnl_c"] for t in trades)
    wins = sum(1 for t in trades if t["won"])
    ml = [t["mins_left"] for t in trades if t["mins_left"] is not None]
    return {
        "thresh": thresh, "n_trades": n, "n_markets": len(by_mkt),
        "win_rate": (wins / n) if n else 0.0,
        "total_pnl_usd": total / 100.0,
        "avg_pnl_c": (total / n) if n else 0.0,
        "avg_entry_mins_left": (sum(ml) / len(ml)) if ml else None,
        "trades": trades,
    }


def walkforward(rows: list[dict], thresh: float, folds: int, late_mins) -> list[dict]:
    mkt_close = {}
    for r in rows:
        mkt_close.setdefault(r["ticker"], r["close_time"] or r["observed_at"])
    ordered = sorted(mkt_close, key=lambda t: str(mkt_close[t]))
    if len(ordered) < folds:
        return []
    size = len(ordered) // folds
    out = []
    for k in range(folds):
        lo = k * size
        hi = len(ordered) if k == folds - 1 else (k + 1) * size
        keep = set(ordered[lo:hi])
        sub = [r for r in rows if r["ticker"] in keep]
        res = edge_pnl(sub, thresh, late_mins)
        res["fold"] = k
        res["window"] = f"{str(mkt_close[ordered[lo]])[:10]}..{str(mkt_close[ordered[hi-1]])[:10]}"
        out.append(res)
    return out


def money(x: float) -> str:
    return f"{'+' if x >= 0 else '-'}${abs(x):.2f}"


def run(db: str, interval: str, folds: int, late_mins, thresholds: list[float]) -> None:
    rows = load_rows(db, interval)
    print("=" * 72)
    print(f"SHADOW PRICER — Phase 0 eval   (interval={interval})")
    print(f"db: {db}")
    if not rows:
        print("\nNo rows with both model_prob and a settled up_won. Nothing to score.")
        print("(Model prob is None until sigma1m warms up ~31 one-min closes, and")
        print(" strike is None on mid-window restarts — both propagate None.)")
        return
    spans = [r["observed_at"] for r in rows if r["observed_at"]]
    ivs = defaultdict(int)
    for r in rows:
        ivs[r["iv"]] += 1
    base_fav = 0
    per_mkt_first = {}
    for r in rows:
        per_mkt_first.setdefault(r["ticker"], r)
    for r in per_mkt_first.values():
        mp = float(r["model_prob"])
        fav_won = int(r["up_won"]) if mp >= 0.5 else (1 - int(r["up_won"]))
        base_fav += fav_won
    print(f"ticks scored: {len(rows):,}   markets: {len(per_mkt_first):,}")
    print(f"span: {min(spans)[:19]} .. {max(spans)[:19]}")
    print("interval mix (ticks): " + ", ".join(f"{k}={v:,}" for k, v in sorted(ivs.items())))
    print(f"favorite base rate (per market, model side): {base_fav/len(per_mkt_first):.3f}")

    c = calibration(rows)
    print("\n── 1. GAUSSIAN MODEL CALIBRATION ──────────────────────────────")
    print(f"  Brier   per-tick {c['brier_pertick']:.5f}   market-balanced {c['brier_mktbal']:.5f}")
    print(f"  LogLoss per-tick {c['logloss_pertick']:.5f}   market-balanced {c['logloss_mktbal']:.5f}")
    print("  favorite-confidence calibration (market-balanced):")
    print("    predicted band |   n(mkt-wt) |  mean pred |  realized |   gap")
    for b in c["buckets"]:
        if b["n"] < 0.5:
            continue
        gap = b["realized"] - b["pred"]
        print(f"    {b['lo']*100:4.0f}-{b['hi']*100:3.0f}%     | {b['n']:10.1f} | "
              f"{b['pred']*100:8.1f}% | {b['realized']*100:7.1f}% | {gap*100:+5.1f}pp")

    print("\n── 2. MODEL-vs-REAL-BOOK EDGE -> HELD-TO-SETTLEMENT P&L ────────")
    lm_label = "any tick in window" if late_mins is None else f"only mins_left<= {late_mins}"
    print(f"  one entry per market, filled at the real ask ({lm_label}); v2 taker fee charged")
    print("  min edge |  trades |  win% |   total P&L |  avg/ct |  entry min-left")
    for x in thresholds:
        e = edge_pnl(rows, x, late_mins)
        ml = e["avg_entry_mins_left"]
        print(f"   >= {x:4.1f}c | {e['n_trades']:6d}  | {e['win_rate']*100:4.0f}% | "
              f"{money(e['total_pnl_usd']):>10} | {e['avg_pnl_c']:+6.2f}c | "
              f"{('%.1f'%ml) if ml is not None else '  -'}")

    wf_thresh = thresholds[len(thresholds) // 2]
    wf = walkforward(rows, wf_thresh, folds, late_mins)
    print(f"\n── 3. WALK-FORWARD (edge >= {wf_thresh:.1f}c, {folds} sequential folds) ──")
    if not wf:
        print(f"  too few markets ({len(per_mkt_first)}) for {folds} folds.")
    else:
        print("  fold | window              | trades | win% |   total P&L | avg/ct")
        pos = 0
        for f in wf:
            if f["total_pnl_usd"] > 0:
                pos += 1
            print(f"   {f['fold']:2d}  | {f['window']:19} | {f['n_trades']:5d}  | "
                  f"{f['win_rate']*100:4.0f}% | {money(f['total_pnl_usd']):>10} | {f['avg_pnl_c']:+6.2f}c")
        print(f"  folds profitable: {pos}/{len(wf)}  "
              f"(persistence check — a real edge stays green across folds, not one lucky window)")

    print("\nCaveats: fills at the recorded real ask, held to settlement; NO slippage,")
    print("NO missed-fill modelling, NO calibration auto-pause -> live is a CEILING on")
    print("these numbers. In/out-of-sample is the fold table; a single total is in-sample.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=default_db())
    ap.add_argument("--interval", default="all", choices=["all", "15m", "5m", "hourly"])
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--late-mins", type=float, default=None,
                    help="restrict entries to ticks with mins_left <= this (default: whole window)")
    ap.add_argument("--thresholds", default="0,1,2,3,5,8",
                    help="comma-separated min-edge cents grid for the P&L sweep")
    a = ap.parse_args()
    thr = [float(x) for x in a.thresholds.split(",") if x.strip() != ""]
    run(a.db, a.interval, a.folds, a.late_mins, thr)


if __name__ == "__main__":
    main()
