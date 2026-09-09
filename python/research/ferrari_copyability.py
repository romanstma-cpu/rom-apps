from __future__ import annotations

import asyncio
import gzip
import json
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import httpx

WALLET = "0xfe787d2da716d60e8acff57fb87eb13cd4d10319"
DATA = "https://data-api.polymarket.com"
CLOB = "https://clob.polymarket.com"

CATS = [
    ("nba", "basketball"), ("wnba", "basketball"), ("basketball", "basketball"),
    ("nfl", "football"), ("mlb", "baseball"), ("nhl", "hockey"),
    ("atp", "tennis"), ("wta", "tennis"), ("tennis", "tennis"), ("open", "tennis"),
    ("ufc", "mma"), ("boxing", "mma"),
    ("fc", "soccer"), ("cup", "soccer"), ("liga", "soccer"), ("league", "soccer"),
    ("united", "soccer"), ("city", "soccer"), ("madrid", "soccer"),
    ("vs", "other-sport"),
]


def _cat(title: str, slug: str) -> str:
    s = f"{title} {slug}".lower()
    for kw, cat in CATS:
        if kw in s:
            return cat
    return "other"


async def _get(client: httpx.AsyncClient, url: str, params: dict,
               tries: int = 4):
    for i in range(tries):
        try:
            r = await client.get(url, params=params, timeout=25.0)
            if r.status_code == 429 or r.status_code >= 500:
                await asyncio.sleep(1.2 * (i + 1))
                continue
            return r
        except Exception:
            await asyncio.sleep(1.2 * (i + 1))
    return None


async def fetch_all(client: httpx.AsyncClient, path: str, base: dict,
                    cap: int = 10000) -> list[dict]:
    out: list[dict] = []
    offset = 0
    while offset < cap:
        r = await _get(client, f"{DATA}{path}",
                       {**base, "limit": 500, "offset": offset})
        if r is None or r.status_code != 200:
            break
        batch = r.json()
        if not isinstance(batch, list) or not batch:
            break
        out.extend(batch)
        if len(batch) < 500:
            break
        offset += 500
    return out


async def drift_after_fill(client: httpx.AsyncClient, sem: asyncio.Semaphore,
                           tr: dict) -> dict | None:
    async with sem:
        r = await _get(client, f"{CLOB}/prices-history",
                       {"market": tr["asset"], "interval": "max",
                        "fidelity": 10})
    if r is None or r.status_code != 200:
        return None
    h = (r.json() or {}).get("history") or []
    if not h:
        return None
    ts = [p["t"] for p in h]

    def at(target: float, tol: float = 600.0):
        best, bd = None, None
        lo, hi = 0, len(ts) - 1
        while lo < hi:
            mid = (lo + hi) // 2
            if ts[mid] < target:
                lo = mid + 1
            else:
                hi = mid
        for i in (lo - 1, lo, lo + 1):
            if 0 <= i < len(ts):
                d = abs(ts[i] - target)
                if bd is None or d < bd:
                    best, bd = float(h[i]["p"]), d
        return best if bd is not None and bd <= tol else None

    t0 = float(tr["timestamp"])
    p5, p15 = at(t0 + 300), at(t0 + 900)
    if p5 is None and p15 is None:
        return None
    return {"price": float(tr["price"]), "p5": p5, "p15": p15,
            "cat": _cat(tr.get("title") or "", tr.get("slug") or "")}


def pct(x, q):
    return round(statistics.quantiles(x, n=100)[q - 1], 4) if len(x) >= 10 else None


async def run() -> None:
    limits = httpx.Limits(max_connections=14)
    async with httpx.AsyncClient(limits=limits) as client:
        print("fetching trades ...")
        trades = await fetch_all(client, "/trades", {"user": WALLET})
        print("fetching positions ...")
        positions = await fetch_all(client, "/positions",
                                    {"user": WALLET, "sortBy": "CURRENT"})
        if not trades:
            print("no trades returned — endpoint/wallet issue")
            return
        trades.sort(key=lambda t: t["timestamp"])
        t0 = datetime.fromtimestamp(trades[0]["timestamp"], tz=timezone.utc)
        t1 = datetime.fromtimestamp(trades[-1]["timestamp"], tz=timezone.utc)
        span_d = max(0.01, (trades[-1]["timestamp"] - trades[0]["timestamp"]) / 86400)
        buys = [t for t in trades if t["side"] == "BUY"]
        sells = [t for t in trades if t["side"] == "SELL"]
        print(f"\n=== FERRARICHAMPIONS2026 activity ===")
        print(f"trades fetched: {len(trades)} (API window {t0:%Y-%m-%d} .. {t1:%Y-%m-%d}, "
              f"{span_d:.1f} days — capped at 10k, oldest may be truncated)")
        print(f"buys {len(buys)} / sells {len(sells)}; "
              f"{len(trades)/span_d:.0f} trades/day")
        by_cat = defaultdict(lambda: [0, 0.0])
        for t in buys:
            c = _cat(t.get("title") or "", t.get("slug") or "")
            by_cat[c][0] += 1
            by_cat[c][1] += float(t["size"]) * float(t["price"])
        print("buy mix by category (n, $notional):")
        for c, (n, usd) in sorted(by_cat.items(), key=lambda kv: -kv[1][1]):
            print(f"  {c:<12} {n:>6}  ${usd:>12,.0f}")
        bp = [float(t["price"]) for t in buys]
        print(f"buy price distribution: p25={pct(bp,25)} median={pct(bp,50)} "
              f"p75={pct(bp,75)}")

        by_cid = defaultdict(list)
        for t in trades:
            by_cid[t["conditionId"]].append(t["timestamp"])
        lags = []
        for tss in by_cid.values():
            tss.sort()
            lags += [b - a for a, b in zip(tss, tss[1:]) if 0 < b - a < 86400]
        if lags:
            print(f"same-market consecutive-trade lag: median={statistics.median(lags):.0f}s "
                  f"p25={pct(lags,25)}s p75={pct(lags,75)}s (n={len(lags)})")

        resolved = [p for p in positions if p.get("redeemable") or
                    (p.get("curPrice") in (0, 1) and not p.get("negativeRisk"))]
        realized = sum(float(p.get("cashPnl") or 0) for p in positions)
        print(f"\npositions fetched: {len(positions)}; cashPnl sum ${realized:,.0f} "
              f"(positions endpoint window)")

        sample = [t for t in buys if 0.03 <= float(t["price"]) <= 0.97][-250:]
        print(f"\ndrift test on {len(sample)} recent buys ...")
        sem = asyncio.Semaphore(10)
        drifts = [d for d in await asyncio.gather(
            *[drift_after_fill(client, sem, t) for t in sample]) if d]
        d5 = [d["p5"] - d["price"] for d in drifts if d["p5"] is not None]
        d15 = [d["p15"] - d["price"] for d in drifts if d["p15"] is not None]
        print(f"post-fill drift (follower buys the same side LATER):")
        if d5:
            print(f"  +5m : n={len(d5)}  median={statistics.median(d5)*100:+.1f}c  "
                  f"p25={pct(d5,25)*100:+.1f}c p75={pct(d5,75)*100:+.1f}c  "
                  f"share >+2c worse: {sum(1 for x in d5 if x > 0.02)/len(d5)*100:.0f}%")
        if d15:
            print(f"  +15m: n={len(d15)}  median={statistics.median(d15)*100:+.1f}c  "
                  f"p25={pct(d15,25)*100:+.1f}c p75={pct(d15,75)*100:+.1f}c  "
                  f"share >+2c worse: {sum(1 for x in d15 if x > 0.02)/len(d15)*100:.0f}%")

        out = Path(__file__).with_name("ferrari_copyability.json.gz")
        with gzip.open(out, "wt", encoding="utf-8") as f:
            json.dump({"trades_n": len(trades), "buys": len(buys),
                       "by_cat": {k: v for k, v in by_cat.items()},
                       "drifts": drifts,
                       "positions_cash_pnl": realized}, f)
        print(f"wrote {out}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(run())
