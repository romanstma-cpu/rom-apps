import math
import os
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

DB = Path(os.environ.get("PMXT_DB")
          or Path(__file__).resolve().parent / "data" / "pmxt_btc15m.db")
# US taker coefficient; see fees_us for the dated schedule.
FEE_RATE = 0.06
WINDOW_S = 900
BANDS = [(0.01, 0.10), (0.10, 0.20), (0.20, 0.30), (0.30, 0.40),
         (0.40, 0.50), (0.50, 0.65), (0.65, 0.80), (0.80, 0.95)]

con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
candles = dict(con.execute("SELECT minute, close FROM candles"))


def velocity(ts):
    m = (ts // 60) * 60
    a, b = candles.get(m - 60), candles.get(m)
    if a is None or b is None or a <= 0:
        return None
    return (b - a) / a * 100.0


def band_of(a):
    for lo, hi in BANDS:
        if lo <= a < hi:
            return (lo, hi)
    return None


fills = defaultdict(list)
n_windows = 0

for open_epoch, up_won in con.execute(
        "SELECT open_epoch, up_won FROM meta WHERE missing=0 AND up_won IS NOT NULL"):
    rows = con.execute(
        "SELECT ts, side, best_ask FROM ticks WHERE open_epoch=? ORDER BY ts",
        (open_epoch,)).fetchall()
    if not rows:
        continue
    n_windows += 1
    ask = {"up": {}, "down": {}}
    for ts, side, ba in rows:
        if ba is not None and 0.0 < ba < 1.0:
            ask[side][ts] = ba
    close_epoch = open_epoch + WINDOW_S
    entered = set()
    for ts in sorted(set(ask["up"]) | set(ask["down"])):
        if ts >= close_epoch - 60:
            break
        v = velocity(ts)
        if v is None:
            continue
        side = "up" if v > 0.1 else ("down" if v < -0.1 else None)
        if side is None:
            continue
        a0 = ask[side].get(ts)
        if a0 is None or a0 < 0.01:
            continue
        b = band_of(a0)
        if b is None:
            continue
        won = bool(up_won) if side == "up" else not up_won

        def pnl(cost):
            fee = FEE_RATE * cost * (1.0 - cost)
            return (1.0 - cost - fee) if won else (-cost - fee)

        if (b, "baseline") not in entered:
            entered.add((b, "baseline"))
            fills[(b, "baseline")].append((open_epoch, pnl(a0)))
        if (b, "combined") not in entered:
            stable = all((ask[side].get(ts - k) is not None
                          and abs(ask[side][ts - k] - a0) < 1e-4) for k in (5, 10, 15))
            a1 = ask[side].get(ts + 5)
            if stable and a1 is not None and a1 <= a0 + 0.01:
                entered.add((b, "combined"))
                fills[(b, "combined")].append((open_epoch, pnl(a1)))
con.close()


def stats(pnls):
    n = len(pnls)
    if n < 2:
        return n, 0.0, 0.0, float("nan")
    mean = sum(pnls) / n
    w = sum(1 for p in pnls if p > 0) / n
    var = sum((p - mean) ** 2 for p in pnls) / (n - 1)
    t = mean / math.sqrt(var / n) if var > 1e-12 else float("nan")
    return n, w * 100, mean * 100, t


for model in ("baseline", "combined"):
    print(f"\n===== ISOLATED bands — {model} ({n_windows:,} windows) =====")
    print(f"  {'band':>12} {'n':>6} {'win%':>6} {'net c/ct':>9} {'t':>6}  weekly net (c/ct)")
    for b in BANDS:
        rows = fills[(b, model)]
        n, w, net, t = stats([p for _e, p in rows])
        if n == 0:
            continue
        by_week = defaultdict(list)
        for e, p in rows:
            wk = datetime.fromtimestamp(e, tz=timezone.utc).isocalendar()
            by_week[f"W{wk[1]:02d}"].append(p)
        wk_means = [(k, sum(v) / len(v) * 100, len(v)) for k, v in sorted(by_week.items())]
        pos = sum(1 for _k, m, _n in wk_means if m > 0)
        trail = " ".join(f"{m:+.0f}" for _k, m, _n in wk_means)
        print(f"  {b[0]:.2f}-{b[1]:.2f} {n:>6} {w:>6.1f} {net:>9.2f} {t:>6.1f}  "
              f"[{pos}/{len(wk_means)} wks +] {trail}")
