import math
import os
import sqlite3
from collections import defaultdict
from pathlib import Path

DB = Path(os.environ.get("PMXT_DB")
          or Path(__file__).resolve().parent / "data" / "pmxt_btc15m.db")
# US taker coefficient; see fees_us for the dated schedule.
FEE_RATE = 0.06
WINDOW_S = 900
CAPS = [0.30, 0.40, 0.50, 0.65, 0.80, 0.95]
MODELS = ("baseline", "combined")

con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
candles = dict(con.execute("SELECT minute, close FROM candles"))


def velocity(ts):
    m = (ts // 60) * 60
    a, b = candles.get(m - 60), candles.get(m)
    if a is None or b is None or a <= 0:
        return None
    return (b - a) / a * 100.0


fills = {(c, m): [] for c in CAPS for m in MODELS}
n_windows = 0

wins = con.execute(
    "SELECT open_epoch, up_won FROM meta WHERE missing=0 AND up_won IS NOT NULL"
).fetchall()

for open_epoch, up_won in wins:
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
        if a0 is None or a0 < 0.01:
            continue
        won = bool(up_won) if side == "up" else not up_won

        def pnl(cost):
            fee = FEE_RATE * cost * (1.0 - cost)
            return (1.0 - cost - fee) if won else (-cost - fee)

        stable = all(
            (ask[side].get(ts - k) is not None
             and abs(ask[side][ts - k] - a0) < 1e-4) for k in (5, 10, 15))
        a1 = ask[side].get(ts + 5)
        lat_ok = a1 is not None and a1 <= a0 + 0.01

        for cap in CAPS:
            if a0 > cap:
                continue
            if (cap, "baseline") not in entered:
                entered.add((cap, "baseline"))
                fills[(cap, "baseline")].append((open_epoch, pnl(a0)))
            if (cap, "combined") not in entered and stable and lat_ok:
                entered.add((cap, "combined"))
                fills[(cap, "combined")].append((open_epoch, pnl(a1)))

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


print(f"\n===== ask-cap sweep over {n_windows:,} real BTC 15m windows =====")
for model in MODELS:
    print(f"\n{model} fill model")
    print(f"  {'cap':>5} {'n':>6} {'win%':>6} {'net c/ct':>9} {'t':>6} "
          f"{'$/trade @5ct':>13} {'total $':>9}")
    for cap in CAPS:
        n, w, net, t = stats([p for _e, p in fills[(cap, model)]])
        per_trade = net / 100.0 * 5
        print(f"  {cap:>5.2f} {n:>6} {w:>6.1f} {net:>9.2f} {t:>6.1f} "
              f"{per_trade:>13.3f} {per_trade * n:>9.2f}")

print("\n=== the disputed 65c–80c band, in isolation (baseline) ===")
band = []
for open_epoch, p in fills[(0.80, "baseline")]:
    pass
in65 = {e for e, _ in fills[(0.65, "baseline")]}
band = [p for e, p in fills[(0.80, "baseline")] if e not in in65]
n, w, net, t = stats(band)
print(f"  windows entered at 65c<ask<=80c only: n={n}  win%={w:.1f}  "
      f"net={net:+.2f}c/ct  t={t:.1f}")
