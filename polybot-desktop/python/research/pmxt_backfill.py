from __future__ import annotations

import argparse
import asyncio
import json
import math
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DATA_DIR = Path(__file__).with_name("data")
DB_PATH = DATA_DIR / "pmxt_btc15m.db"
ARCHIVE = "https://r2v2.pmxt.dev/polymarket_orderbook_{}.parquet"
GAMMA = "https://gamma-api.polymarket.com"
ASSET = "btc"
WINDOW_S = 900
GRID_S = 5
# US taker coefficient; see fees_us for the dated schedule.
FEE_RATE = 0.06


def db() -> sqlite3.Connection:
    DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS meta (
        open_epoch INTEGER PRIMARY KEY, cid TEXT, up_token TEXT, down_token TEXT,
        up_won INTEGER, slug TEXT, missing INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS ticks (
        open_epoch INTEGER, ts INTEGER, side TEXT,  -- 'up'/'down'
        best_bid REAL, best_ask REAL,
        PRIMARY KEY (open_epoch, ts, side));
    CREATE TABLE IF NOT EXISTS hours_done (hour TEXT PRIMARY KEY, status TEXT);
    CREATE TABLE IF NOT EXISTS candles (minute INTEGER PRIMARY KEY, close REAL);
    """)
    return conn


async def fetch_meta(conn: sqlite3.Connection, epochs: list[int]) -> None:
    have = {r[0] for r in conn.execute("SELECT open_epoch FROM meta")}
    todo = [e for e in epochs if e not in have]
    if not todo:
        return
    sem = asyncio.Semaphore(10)

    async def one(client: httpx.AsyncClient, ep: int):
        slug = f"{ASSET}-updown-15m-{ep}"
        async with sem:
            for attempt in range(3):
                try:
                    r = await client.get(f"{GAMMA}/markets",
                                         params={"slug": slug, "closed": "true"},
                                         timeout=20.0)
                    if r.status_code == 429:
                        await asyncio.sleep(1.5 * (attempt + 1))
                        continue
                    arr = r.json() if r.status_code == 200 else []
                    break
                except Exception:
                    await asyncio.sleep(1.0)
                    arr = []
        if not arr:
            return (ep, None, None, None, None, slug, 1)
        m = arr[0]
        try:
            outcomes = json.loads(m.get("outcomes") or "[]")
            prices = json.loads(m.get("outcomePrices") or "[]")
            tokens = json.loads(m.get("clobTokenIds") or "[]")
        except json.JSONDecodeError:
            return (ep, None, None, None, None, slug, 1)
        if outcomes[:1] != ["Up"] or sorted(prices) != ["0", "1"] or len(tokens) != 2:
            return (ep, None, None, None, None, slug, 1)
        return (ep, m.get("conditionId"), tokens[0], tokens[1],
                1 if prices[0] == "1" else 0, slug, 0)

    async with httpx.AsyncClient() as client:
        for i in range(0, len(todo), 200):
            rows = await asyncio.gather(*[one(client, e) for e in todo[i:i + 200]])
            conn.executemany(
                "INSERT OR REPLACE INTO meta VALUES (?,?,?,?,?,?,?)",
                [(r[0], r[1], r[2], r[3], r[4], r[5], r[6]) for r in rows])
            conn.commit()
            print(f"  meta {min(i+200, len(todo))}/{len(todo)}")


def backfill_hours(conn: sqlite3.Connection, start: str, end: str) -> None:
    import duckdb
    duck = duckdb.connect()
    duck.execute("INSTALL httpfs; LOAD httpfs;")
    d0 = datetime.fromisoformat(start).replace(tzinfo=timezone.utc)
    d1 = datetime.fromisoformat(end).replace(tzinfo=timezone.utc)
    cur = d0
    hours = []
    while cur <= d1 + timedelta(days=1) - timedelta(hours=1):
        hours.append(cur)
        cur += timedelta(hours=1)
    done = {r[0] for r in conn.execute("SELECT hour FROM hours_done WHERE status IN ('ok','empty','missing')")}
    hours = [h for h in hours if h.strftime("%Y-%m-%dT%H") not in done]
    print(f"{len(hours)} hour-files to process")

    for h in hours:
        tag = h.strftime("%Y-%m-%dT%H")
        epochs = [int(h.timestamp()) + k * WINDOW_S for k in range(4)]
        metas = {e: conn.execute(
            "SELECT cid, up_token, down_token FROM meta WHERE open_epoch=? AND missing=0",
            (e,)).fetchone() for e in epochs}
        metas = {e: m for e, m in metas.items() if m}
        if not metas:
            conn.execute("INSERT OR REPLACE INTO hours_done VALUES (?,?)", (tag, "nometa"))
            conn.commit()
            continue
        cids = [m[0] for m in metas.values()]
        tok_side = {}
        tok_window = {}
        for e, (cid, up, down) in metas.items():
            tok_side[up], tok_side[down] = "up", "down"
            tok_window[up] = tok_window[down] = e
        url = ARCHIVE.format(tag)
        q = f"""
        SELECT asset_id,
               (epoch(timestamp)::BIGINT / {GRID_S}) * {GRID_S} AS ts,
               arg_max(best_bid, timestamp) AS bb,
               arg_max(best_ask, timestamp) AS ba
        FROM read_parquet('{url}')
        WHERE market::VARCHAR IN ({','.join("'" + c + "'" for c in cids)})
          AND event_type = 'price_change'
          AND best_ask IS NOT NULL
        GROUP BY 1, 2
        """
        try:
            rows = duck.execute(q).fetchall()
        except Exception as ex:
            status = "missing" if ("404" in str(ex) or "HTTP" in str(ex)) else "error"
            print(f"  {tag}: {status} ({str(ex)[:90]})")
            conn.execute("INSERT OR REPLACE INTO hours_done VALUES (?,?)", (tag, status))
            conn.commit()
            continue
        ins = []
        for asset_id, ts, bb, ba in rows:
            side = tok_side.get(asset_id)
            if side is None:
                continue
            ins.append((tok_window[asset_id], int(ts), side,
                        float(bb) if bb is not None else None,
                        float(ba) if ba is not None else None))
        conn.executemany("INSERT OR REPLACE INTO ticks VALUES (?,?,?,?,?)", ins)
        conn.execute("INSERT OR REPLACE INTO hours_done VALUES (?,?)",
                     (tag, "ok" if ins else "empty"))
        conn.commit()
        print(f"  {tag}: {len(ins)} grid rows across {len(metas)} windows")


async def fetch_candles(conn: sqlite3.Connection, start: str, end: str) -> None:
    from crypto15m_backfill import _fetch_series_coinbase
    d0 = datetime.fromisoformat(start).replace(tzinfo=timezone.utc) - timedelta(days=1, hours=1)
    d1 = datetime.fromisoformat(end).replace(tzinfo=timezone.utc) + timedelta(days=1)
    have = conn.execute("SELECT COUNT(*) FROM candles WHERE minute BETWEEN ? AND ?",
                        (int(d0.timestamp()), int(d1.timestamp()))).fetchone()[0]
    want = int((d1 - d0).total_seconds() / 60)
    if have >= want * 0.95:
        print(f"candles already present ({have}/{want})")
        return
    async with httpx.AsyncClient() as client:
        series = await _fetch_series_coinbase(
            "BTC", client, int(d0.timestamp() * 1000), int(d1.timestamp() * 1000))
    conn.executemany("INSERT OR REPLACE INTO candles VALUES (?,?)",
                     [(t, cv[0]) for t, cv in series.items()])
    conn.commit()
    print(f"candles stored: {len(series)}")


def simulate(conn: sqlite3.Connection) -> None:
    candles = dict(conn.execute("SELECT minute, close FROM candles"))

    def velocity(ts: int) -> float | None:
        m = (ts // 60) * 60
        a, b = candles.get(m - 60), candles.get(m)
        if a is None or b is None or a <= 0:
            return None
        return (b - a) / a * 100.0

    def regime(open_epoch: int) -> str:
        a = candles.get(((open_epoch - 86400) // 60) * 60)
        b = candles.get((open_epoch // 60) * 60)
        if a is None or b is None:
            return "?"
        r = (b - a) / a * 100.0
        return "UP" if r > 1.0 else ("DOWN" if r < -1.0 else "FLAT")

    wins = conn.execute(
        "SELECT open_epoch, up_won FROM meta WHERE missing=0 AND up_won IS NOT NULL").fetchall()
    fills = {
        "baseline": [], "stable15s": [], "latency5s": [], "combined": [],
    }
    meta_reg: dict[int, str] = {}
    n_windows = 0
    for open_epoch, up_won in wins:
        t_rows = conn.execute(
            "SELECT ts, side, best_ask FROM ticks WHERE open_epoch=? ORDER BY ts",
            (open_epoch,)).fetchall()
        if not t_rows:
            continue
        n_windows += 1
        meta_reg[open_epoch] = regime(open_epoch)
        ask: dict[str, dict[int, float]] = {"up": {}, "down": {}}
        for ts, side, ba in t_rows:
            if ba is not None and 0.0 < ba < 1.0:
                ask[side][ts] = ba
        close_epoch = open_epoch + WINDOW_S
        entered: set[str] = set()
        grid = sorted(set(ask["up"]) | set(ask["down"]))
        for ts in grid:
            if ts >= close_epoch - 60:
                break
            v = velocity(ts)
            if v is None:
                continue
            side = "up" if v > 0.1 else ("down" if v < -0.1 else None)
            if side is None:
                continue
            a0 = ask[side].get(ts)
            if a0 is None or not (0.01 <= a0 <= 0.80):
                continue
            won = bool(up_won) if side == "up" else not up_won
            def pnl(cost: float) -> float:
                fee = FEE_RATE * cost * (1.0 - cost)
                return (1.0 - cost - fee) if won else (-cost - fee)
            if "baseline" not in entered:
                entered.add("baseline")
                fills["baseline"].append((open_epoch, pnl(a0)))
            if "stable15s" not in entered:
                back = [ask[side].get(ts - k) for k in (5, 10, 15)]
                if all(b is not None and abs(b - a0) < 1e-4 for b in back):
                    entered.add("stable15s")
                    fills["stable15s"].append((open_epoch, pnl(a0)))
            if "latency5s" not in entered:
                a1 = ask[side].get(ts + 5)
                if a1 is not None and a1 <= a0 + 0.01:
                    entered.add("latency5s")
                    fills["latency5s"].append((open_epoch, pnl(a1)))
            if "combined" not in entered and "stable15s" in entered:
                a1 = ask[side].get(ts + 5)
                if a1 is not None and a1 <= a0 + 0.01:
                    entered.add("combined")
                    fills["combined"].append((open_epoch, pnl(a1)))
            if len(entered) == 4:
                break

    print(f"\n===== PMXT OOS momentum validation — {n_windows} BTC 15m windows "
          f"with book data =====")
    print(f"{'fill model':<12} {'n':>6} {'win%':>6} {'net c/ct':>9} {'t':>6}")
    for name, rows in fills.items():
        if not rows:
            print(f"{name:<12} {'0':>6}")
            continue
        pnls = [p for _e, p in rows]
        n = len(pnls)
        mean = sum(pnls) / n
        w = sum(1 for p in pnls if p > 0) / n
        var = sum((p - mean) ** 2 for p in pnls) / max(1, n - 1)
        t = mean / math.sqrt(var / n) if var > 1e-12 else float("nan")
        print(f"{name:<12} {n:>6} {w*100:>6.1f} {mean*100:>9.2f} {t:>6.1f}")
        by_reg = defaultdict(list)
        by_week = defaultdict(list)
        for e, p in rows:
            by_reg[meta_reg.get(e, "?")].append(p)
            wk = datetime.fromtimestamp(e, tz=timezone.utc).isocalendar()
            by_week[f"{wk[0]}-W{wk[1]:02d}"].append(p)
        if name == "baseline" or name == "combined":
            for reg, ps in sorted(by_reg.items()):
                m2 = sum(ps) / len(ps)
                v2 = sum((p - m2) ** 2 for p in ps) / max(1, len(ps) - 1)
                t2 = m2 / math.sqrt(v2 / len(ps)) if v2 > 1e-12 and len(ps) > 1 else float("nan")
                print(f"    regime {reg:<5} n={len(ps):>5} net={m2*100:>+7.2f}c t={t2:>5.1f}")
            for wkk, ps in sorted(by_week.items()):
                print(f"    {wkk}: n={len(ps):>4} net={sum(ps)/len(ps)*100:>+7.2f}c")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backfill")
    b.add_argument("--start", required=True)
    b.add_argument("--end", required=True)
    sub.add_parser("simulate")
    args = ap.parse_args()
    conn = db()
    if args.cmd == "backfill":
        d0 = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
        d1 = datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc) + timedelta(days=1)
        epochs = list(range(int(d0.timestamp()), int(d1.timestamp()), WINDOW_S))
        print(f"{len(epochs)} windows in range; resolving meta ...")
        asyncio.run(fetch_meta(conn, epochs))
        asyncio.run(fetch_candles(conn, args.start, args.end))
        backfill_hours(conn, args.start, args.end)
    else:
        simulate(conn)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
