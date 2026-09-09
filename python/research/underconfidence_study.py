from __future__ import annotations

import argparse
import asyncio
import gzip
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import httpx

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"

CFG = {
    "politics": {
        "tag": "politics",
        "fee_rate": 0.04,
        "horizons_h": [12, 24, 48, 168, 720],
        "min_volume": 5000.0,
    },
    "sports": {
        "tag": "sports",
        "fee_rate": 0.05,
        "horizons_h": [24, 72, 168, 336],
        "min_volume": 2000.0,
    },
}

FIDS = [60, 120, 240, 480, 720, 1440]


def _epoch(iso: str) -> float | None:
    try:
        return datetime.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S").replace(
            tzinfo=timezone.utc).timestamp()
    except (ValueError, TypeError):
        return None


async def _get(client: httpx.AsyncClient, url: str, params: dict,
               tries: int = 4) -> httpx.Response | None:
    for i in range(tries):
        try:
            r = await client.get(url, params=params, timeout=25.0)
            if r.status_code == 429:
                await asyncio.sleep(1.5 * (i + 1))
                continue
            if r.status_code >= 500:
                await asyncio.sleep(0.8 * (i + 1))
                continue
            return r
        except Exception:
            await asyncio.sleep(0.8 * (i + 1))
    return None


def _month_windows(start: str, end: str) -> list[tuple[str, str]]:
    out = []
    y, m = int(start[:4]), int(start[5:7])
    ey, em = int(end[:4]), int(end[5:7])
    while (y, m) <= (ey, em):
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        out.append((f"{y:04d}-{m:02d}-01", f"{ny:04d}-{nm:02d}-01"))
        y, m = ny, nm
    return out


async def fetch_markets(client: httpx.AsyncClient, cat: str, max_markets: int,
                        date_min: str, date_max: str) -> list[dict]:
    cfg = CFG[cat]
    seen: dict[str, dict] = {}
    for lo, hi in _month_windows(date_min, date_max):
        offset = 0
        while True:
            r = await _get(client, f"{GAMMA}/events", {
                "tag_slug": cfg["tag"], "closed": "true", "limit": 100,
                "offset": offset, "order": "endDate", "ascending": "false",
                "end_date_min": lo, "end_date_max": hi,
            })
            if r is None or r.status_code != 200:
                break
            evs = r.json()
            if not evs:
                break
            for e in evs:
                for m in e.get("markets") or []:
                    cid = m.get("conditionId")
                    if not cid or cid in seen or not m.get("closed"):
                        continue
                    if not m.get("enableOrderBook") or not m.get("clobTokenIds"):
                        continue
                    try:
                        outcomes = json.loads(m.get("outcomes") or "[]")
                        prices = json.loads(m.get("outcomePrices") or "[]")
                    except json.JSONDecodeError:
                        continue
                    if outcomes[:1] != ["Yes"] or sorted(prices) != ["0", "1"]:
                        continue
                    if float(m.get("volumeNum") or 0.0) < cfg["min_volume"]:
                        continue
                    end_ts = _epoch(m.get("endDate") or "")
                    start_ts = _epoch(m.get("startDate") or "") or 0.0
                    if not end_ts:
                        continue
                    try:
                        yes_token = json.loads(m["clobTokenIds"])[0]
                    except (json.JSONDecodeError, IndexError):
                        continue
                    seen[cid] = {
                        "cid": cid, "event_id": str(e.get("id")),
                        "q": (m.get("question") or "")[:120],
                        "yes_token": yes_token,
                        "end_ts": end_ts, "start_ts": start_ts,
                        "yes_won": prices[0] == "1",
                        "volume": float(m.get("volumeNum") or 0.0),
                        "neg_risk": bool(m.get("negRisk")),
                    }
            offset += 100
            if offset >= 3000:
                break
        if len(seen) >= max_markets:
            break
    out = sorted(seen.values(), key=lambda x: -x["end_ts"])[:max_markets]
    return out


async def fetch_history(client: httpx.AsyncClient, mkt: dict,
                        sem: asyncio.Semaphore) -> list[dict]:
    life_min = max(1.0, (mkt["end_ts"] - (mkt["start_ts"] or mkt["end_ts"] - 90 * 86400)) / 60.0)
    start_idx = 0
    for i, f in enumerate(FIDS):
        if life_min / f <= 900:
            start_idx = i
            break
    else:
        start_idx = len(FIDS) - 1
    async with sem:
        for fid in FIDS[start_idx:]:
            r = await _get(client, f"{CLOB}/prices-history",
                           {"market": mkt["yes_token"], "interval": "max",
                            "fidelity": fid})
            if r is None or r.status_code != 200:
                continue
            h = (r.json() or {}).get("history") or []
            if h:
                mkt["fid"] = fid
                return h
    return []


def horizon_rows(mkt: dict, hist: list[dict], horizons_h: list[int]) -> list[dict]:
    if not hist:
        return []
    fid = mkt.get("fid") or 1440
    tol = max(fid * 60 * 0.75, 7200.0)
    ts = [pt["t"] for pt in hist]
    rows = []
    for h in horizons_h:
        target = mkt["end_ts"] - h * 3600.0
        lo, hi = 0, len(ts) - 1
        while lo < hi:
            mid = (lo + hi) // 2
            if ts[mid] < target:
                lo = mid + 1
            else:
                hi = mid
        best = min(
            (i for i in (lo - 1, lo, lo + 1) if 0 <= i < len(ts)),
            key=lambda i: abs(ts[i] - target),
        )
        if abs(ts[best] - target) > tol:
            continue
        p = float(hist[best]["p"])
        if not (0.005 <= p <= 0.995):
            continue
        rows.append({
            "cid": mkt["cid"], "event": mkt["event_id"], "h": h,
            "yes_price": p, "yes_won": mkt["yes_won"],
            "end_ts": mkt["end_ts"], "volume": mkt["volume"],
            "neg_risk": mkt["neg_risk"],
        })
    return rows


def fee_ct(price: float, rate: float) -> float:
    return rate * price * (1.0 - price)


def clustered_t(pnls_by_event: dict[str, list[float]]) -> float | None:
    means = [sum(v) / len(v) for v in pnls_by_event.values() if v]
    n = len(means)
    if n < 2:
        return None
    mu = sum(means) / n
    var = sum((x - mu) ** 2 for x in means) / (n - 1)
    if var <= 1e-12:
        return None
    return mu / math.sqrt(var / n)


def report(rows: list[dict], cat: str) -> dict:
    rate = CFG[cat]["fee_rate"]
    out: dict = {"category": cat, "n_rows": len(rows), "horizons": {}}
    for h in CFG[cat]["horizons_h"]:
        hr = [r for r in rows if r["h"] == h]
        if not hr:
            continue
        calib = []
        for b in range(0, 10):
            lo, hi = b / 10.0, (b + 1) / 10.0
            br = [r for r in hr if lo <= r["yes_price"] < hi]
            if len(br) >= 20:
                calib.append({
                    "bucket": f"{lo:.2f}-{hi:.2f}", "n": len(br),
                    "avg_price": round(sum(r["yes_price"] for r in br) / len(br), 4),
                    "win_rate": round(sum(r["yes_won"] for r in br) / len(br), 4),
                })
        fav = []
        for lo_c, hi_c in [(0.50, 0.55), (0.55, 0.60), (0.60, 0.70),
                           (0.70, 0.80), (0.80, 0.90), (0.90, 0.97)]:
            br, pnls, by_event = [], [], defaultdict(list)
            for r in hr:
                fp = max(r["yes_price"], 1.0 - r["yes_price"])
                if not (lo_c <= fp < hi_c):
                    continue
                fav_won = r["yes_won"] if r["yes_price"] >= 0.5 else (not r["yes_won"])
                pnl = (1.0 - fp if fav_won else -fp) - fee_ct(fp, rate)
                br.append(r)
                pnls.append(pnl)
                by_event[r["event"]].append(pnl)
            if len(br) < 20:
                continue
            fav.append({
                "bucket": f"{lo_c:.2f}-{hi_c:.2f}", "n": len(br),
                "events": len(by_event),
                "win_rate": round(sum(1 for p in pnls if p > 0) / len(pnls), 4),
                "net_cents_per_ct": round(sum(pnls) / len(pnls) * 100, 2),
                "t_clustered": (lambda t: round(t, 2) if t is not None else None)(
                    clustered_t(by_event)),
            })
        halves = defaultdict(lambda: defaultdict(list))
        for r in hr:
            fp = max(r["yes_price"], 1.0 - r["yes_price"])
            if not (0.55 <= fp < 0.80):
                continue
            fav_won = r["yes_won"] if r["yes_price"] >= 0.5 else (not r["yes_won"])
            pnl = (1.0 - fp if fav_won else -fp) - fee_ct(fp, rate)
            d = datetime.fromtimestamp(r["end_ts"], tz=timezone.utc)
            key = f"{d.year}H{1 if d.month <= 6 else 2}"
            halves[key][r["event"]].append(pnl)
        persist = []
        for key in sorted(halves):
            ev = halves[key]
            allp = [p for v in ev.values() for p in v]
            t = clustered_t(ev)
            persist.append({
                "half": key, "n": len(allp), "events": len(ev),
                "net_cents_per_ct": round(sum(allp) / len(allp) * 100, 2),
                "t_clustered": round(t, 2) if t is not None else None,
            })
        out["horizons"][f"{h}h"] = {"calibration": calib, "favorite_rule": fav,
                                    "persistence_0.55-0.80": persist}
    return out


def print_report(rep: dict) -> None:
    print(f"\n===== {rep['category'].upper()} — {rep['n_rows']} horizon rows =====")
    for hname, blk in rep["horizons"].items():
        print(f"\n--- horizon T-{hname} ---")
        print("  calibration (YES side):        bucket        n   avg_p   win%")
        for c in blk["calibration"]:
            print(f"    {c['bucket']:>12} {c['n']:>6} {c['avg_price']:>7.3f} "
                  f"{c['win_rate']*100:>6.1f}")
        print("  favorite rule (net of fees):   bucket        n   evts  win%  net c/ct     t")
        for f in blk["favorite_rule"]:
            t = f"{f['t_clustered']:.1f}" if f["t_clustered"] is not None else "-"
            print(f"    {f['bucket']:>12} {f['n']:>6} {f['events']:>6} "
                  f"{f['win_rate']*100:>5.1f} {f['net_cents_per_ct']:>9.2f} {t:>5}")
        print("  persistence (0.55-0.80 favorites):")
        for p in blk["persistence_0.55-0.80"]:
            t = f"{p['t_clustered']:.1f}" if p["t_clustered"] is not None else "-"
            print(f"    {p['half']}: n={p['n']} events={p['events']} "
                  f"net={p['net_cents_per_ct']:+.2f}c/ct t={t}")


async def run(cat: str, max_markets: int, date_min: str, date_max: str,
              out_path: Path) -> None:
    limits = httpx.Limits(max_connections=16)
    async with httpx.AsyncClient(limits=limits) as client:
        print(f"[{cat}] enumerating closed markets {date_min}..{date_max} ...")
        mkts = await fetch_markets(client, cat, max_markets, date_min, date_max)
        print(f"[{cat}] {len(mkts)} resolved binary markets ≥ "
              f"${CFG[cat]['min_volume']:.0f} vol; fetching price histories ...")
        sem = asyncio.Semaphore(12)
        rows: list[dict] = []
        done = 0
        no_hist = 0

        async def one(m: dict) -> None:
            nonlocal done, no_hist
            hist = await fetch_history(client, m, sem)
            if not hist:
                no_hist += 1
            rows.extend(horizon_rows(m, hist, CFG[cat]["horizons_h"]))
            done += 1
            if done % 400 == 0:
                print(f"[{cat}] {done}/{len(mkts)} markets, {len(rows)} rows, "
                      f"{no_hist} without history")

        await asyncio.gather(*[one(m) for m in mkts])
        print(f"[{cat}] done: {len(rows)} rows from {len(mkts)} markets "
              f"({no_hist} had no usable history)")
    rep = report(rows, cat)
    print_report(rep)
    with gzip.open(out_path, "wt", encoding="utf-8") as f:
        json.dump({"report": rep, "rows": rows}, f)
    print(f"[{cat}] wrote {out_path}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--category", choices=list(CFG), required=True)
    ap.add_argument("--max-markets", type=int, default=5000)
    ap.add_argument("--date-min", default="2025-01-01")
    ap.add_argument("--date-max", default="2026-07-10")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    out = Path(args.out) if args.out else Path(__file__).with_name(
        f"underconfidence_{args.category}.json.gz")
    asyncio.run(run(args.category, args.max_markets, args.date_min,
                    args.date_max, out))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
