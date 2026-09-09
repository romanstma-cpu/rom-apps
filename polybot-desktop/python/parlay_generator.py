from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone

import config as cfgmod
import db
import replay

logger = logging.getLogger("parlay")

PINNED: dict = {
    "crypto15m_direction_mode": "favorite",
    "crypto15m_use_rules": False,
    "crypto15m_paired_mode": False,
    "crypto15m_imbalance_gate": False,
    "crypto15m_min_rsi": 0.0,
    "crypto15m_min_delta_pct": 0.0,
    "crypto15m_entry_style": "taker",
    "crypto15m_entry_max": 0.99,
    "crypto15m_exit_threshold": 0.0,
    "crypto15m_stop_loss_pct": 0.0,
    "crypto15m_take_profit": 0.0,
    "crypto15m_take_profit_pct": 0.0,
    "crypto15m_sell_into_strength": False,
    "crypto15m_hours_start_utc": 0,
    "crypto15m_hours_end_utc": 24,
}

FLOOR_GRID = [0.94, 0.95, 0.96, 0.97, 0.98]
DELAY_GRID = [2.0, 3.0, 5.0]
MACD_GRID = [0.0, 1e-9]

DEFAULT_MIN_TRADES = 10
DEFAULT_MIN_WIN_RATE = 1.0
DEFAULT_HOLDOUT_DAYS = 6


def _stats(trades: list[dict]) -> dict:
    n = len(trades)
    wins = sum(1 for t in trades if t["won"])
    pnl = sum(t["pnlUsd"] for t in trades)
    return {
        "n": n, "wins": wins, "losses": n - wins,
        "winRate": round(wins / n, 4) if n else 0.0,
        "pnlUsd": round(pnl, 2),
    }


def _qualifies(train: dict, hold: dict, mwr: float, min_trades: int) -> bool:
    if train["n"] < min_trades:
        return False
    if train["winRate"] < mwr or train["pnlUsd"] <= 0:
        return False
    if hold["n"] > 0 and (hold["winRate"] < mwr or hold["pnlUsd"] < 0):
        return False
    return True


def _split(trades: list[dict], hold_dates: set[str]) -> tuple[list[dict], list[dict]]:
    tr = [t for t in trades if str(t.get("at") or "")[:10] not in hold_dates]
    ho = [t for t in trades if str(t.get("at") or "")[:10] in hold_dates]
    return tr, ho


def generate(
    *, env: str = "mainnet", interval: str = "15m", since_days: int = 60,
    holdout_days: int = DEFAULT_HOLDOUT_DAYS,
    min_win_rate: float = DEFAULT_MIN_WIN_RATE,
    min_trades: int = DEFAULT_MIN_TRADES,
) -> dict:
    by_window = replay.load_windows(env=env, interval=interval, since_days=since_days)
    if not by_window:
        raise RuntimeError(
            f"no resolved {interval} windows recorded in the last {since_days} days"
        )
    all_dates = sorted({
        str(t.get("observed_at") or "")[:10]
        for ticks in by_window.values() for t in ticks
    } - {""})
    hold_dates = set(all_dates[-holdout_days:]) if holdout_days > 0 else set()
    train_dates = [d for d in all_dates if d not in hold_dates]
    if not train_dates:
        raise RuntimeError("holdout_days consumes every recorded date — nothing to train on")

    by_hour: dict[int, dict[str, list[dict]]] = {h: {} for h in range(24)}
    for tk, ticks in by_window.items():
        for h in {replay._tick_hour(t) for t in ticks}:
            if h is not None:
                by_hour[h][tk] = ticks

    base = dict(cfgmod.DEFAULT_CONFIG)
    base["crypto15m_enabled"] = True
    base["crypto15m_interval"] = interval

    hour_configs: dict[str, dict] = {}
    hour_stats: dict[str, dict] = {}
    for h in range(24):
        best = None
        n_cands = 0
        for floor in FLOOR_GRID:
            for delay in DELAY_GRID:
                for macd in MACD_GRID:
                    ov = {
                        **PINNED,
                        "crypto15m_entry_threshold": floor,
                        "crypto15m_time_delay_min": delay,
                        "crypto15m_min_macd_hist": macd,
                    }
                    cand = {**base, "crypto15m_hour_configs": {str(h): ov}}
                    trades, _nw, _lm = replay._simulate(by_hour[h], cand)
                    tr, ho = _split(trades, hold_dates)
                    st, sh = _stats(tr), _stats(ho)
                    if not _qualifies(st, sh, min_win_rate, min_trades):
                        continue
                    n_cands += 1
                    key = (st["pnlUsd"], st["n"])
                    if best is None or key > best["key"]:
                        best = {"key": key, "override": ov, "train": st, "holdout": sh}
        if best is not None:
            hour_configs[str(h)] = best["override"]
            hour_stats[str(h)] = {
                "floor": best["override"]["crypto15m_entry_threshold"],
                "delayMin": best["override"]["crypto15m_time_delay_min"],
                "macdGate": best["override"]["crypto15m_min_macd_hist"] > 0,
                "qualifiers": n_cands,
                "train": best["train"], "holdout": best["holdout"],
            }
        if best is not None:
            logger.info(
                f"hour {h:02d}: seated floor={best['override']['crypto15m_entry_threshold']} "
                f"delay={best['override']['crypto15m_time_delay_min']} "
                f"macd={'on' if best['override']['crypto15m_min_macd_hist'] > 0 else 'off'} "
                f"train={best['train']['n']}t/{best['train']['winRate']:.2%} "
                f"{best['train']['pnlUsd']:+.2f}$"
            )
        else:
            logger.info(f"hour {h:02d}: unseated (no qualifying config)")

    stitched = {**base, "crypto15m_hour_configs": hour_configs}
    v_trades, n_windows, _ = replay._simulate(by_window, stitched)
    v_tr, v_ho = _split(v_trades, hold_dates)

    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "env": env, "interval": interval,
        "since_days": since_days,
        "data_dates": {"first": all_dates[0], "last": all_dates[-1], "count": len(all_dates)},
        "holdout_days": holdout_days, "holdout_dates": sorted(hold_dates),
        "min_win_rate": min_win_rate, "min_trades": min_trades,
        "grid": {"floors": FLOOR_GRID, "delaysMin": DELAY_GRID, "macd": MACD_GRID},
        "hour_configs": hour_configs,
        "hours": hour_stats,
        "validation": {
            "windows": n_windows,
            "train": _stats(v_tr), "holdout": _stats(v_ho), "all": _stats(v_trades),
        },
        "notes": [
            "Hours searched pooled across coins (per-coin-hour needs ~60 days to beat noise).",
            "Fills at recorded real-book asks, taker fee-v2; depth not recorded — optimistic at scale.",
            "Hold-to-settlement by construction; the live engine exempts parlay rows from stop/TP.",
            "P&L figures are per single contract per trade.",
        ],
    }


def save_schedule(schedule: dict) -> None:
    import crypto15m_trader
    with db.get_db() as conn:
        db.kv_set(conn, crypto15m_trader._PARLAY_KV_SCHEDULE, json.dumps(schedule))
    crypto15m_trader.parlay_state(force=True)


def set_armed(armed: bool) -> None:
    import crypto15m_trader
    if armed:
        with db.get_db() as conn:
            raw = db.kv_get(conn, crypto15m_trader._PARLAY_KV_SCHEDULE)
        try:
            sched = json.loads(raw) if raw else None
        except ValueError:
            sched = None
        hcs = sched.get("hour_configs") if isinstance(sched, dict) else None
        if not isinstance(hcs, dict) or not hcs:
            raise ValueError(
                "refusing to arm: the stored schedule seats 0 of 24 hours "
                "(generate one that clears the win-rate bar first)"
            )
    with db.get_db() as conn:
        db.kv_set(conn, crypto15m_trader._PARLAY_KV_ARMED, "1" if armed else "0")
    crypto15m_trader.parlay_state(force=True)


def _print_summary(s: dict) -> None:
    print(f"\nParlay schedule — {s['interval']} {s['env']}, "
          f"{s['data_dates']['count']} recorded dates "
          f"({s['data_dates']['first']} → {s['data_dates']['last']}), "
          f"holdout = last {s['holdout_days']} dates")
    print(f"bar: win-rate ≥ {s['min_win_rate']:.0%} on train AND holdout, "
          f"≥ {s['min_trades']} train trades, train P&L > 0\n")
    for h in range(24):
        hs = s["hours"].get(str(h))
        if not hs:
            print(f"  h{h:02d}  —")
            continue
        tr, ho = hs["train"], hs["holdout"]
        print(
            f"  h{h:02d}  floor {hs['floor']:.2f}  ≤{hs['delayMin']:.0f}m  "
            f"macd {'on ' if hs['macdGate'] else 'off'}  "
            f"train {tr['n']:3d}t {tr['winRate']:7.2%} {tr['pnlUsd']:+7.2f}$  "
            f"holdout {ho['n']:3d}t {ho['winRate']:7.2%} {ho['pnlUsd']:+6.2f}$"
        )
    v = s["validation"]
    print(f"\nstitched — train:   {v['train']['n']}t  {v['train']['winRate']:.2%}  "
          f"{v['train']['pnlUsd']:+.2f}$/ct")
    print(f"stitched — HOLDOUT: {v['holdout']['n']}t  {v['holdout']['winRate']:.2%}  "
          f"{v['holdout']['pnlUsd']:+.2f}$/ct")
    print(f"stitched — all:     {v['all']['n']}t  {v['all']['winRate']:.2%}  "
          f"{v['all']['pnlUsd']:+.2f}$/ct   ({v['windows']} windows scanned)")


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate the per-hour parlay schedule")
    ap.add_argument("--env", default="mainnet")
    ap.add_argument("--interval", default="15m", choices=["5m", "15m", "hourly"])
    ap.add_argument("--since-days", type=int, default=60)
    ap.add_argument("--holdout-days", type=int, default=DEFAULT_HOLDOUT_DAYS)
    ap.add_argument("--min-win-rate", type=float, default=DEFAULT_MIN_WIN_RATE)
    ap.add_argument("--min-trades", type=int, default=DEFAULT_MIN_TRADES)
    ap.add_argument("--save", action="store_true",
                    help="store the schedule in the app DB (does NOT arm it)")
    ap.add_argument("--arm", choices=["on", "off"],
                    help="arm/disarm the stored schedule for live trading")
    ap.add_argument("--arm-only", choices=["on", "off"],
                    help="ONLY flip the armed flag on the already-stored "
                         "schedule (no regeneration) — the quick disarm switch")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.arm_only:
        set_armed(args.arm_only == "on")
        print(f"parlay {'ARMED' if args.arm_only == 'on' else 'disarmed'} "
              "(stored schedule unchanged)")
        return

    sched = generate(
        env=args.env, interval=args.interval, since_days=args.since_days,
        holdout_days=args.holdout_days, min_win_rate=args.min_win_rate,
        min_trades=args.min_trades,
    )
    _print_summary(sched)
    if args.save:
        save_schedule(sched)
        print("\nsaved to app_kv (crypto15m_parlay_schedule)")
    if args.arm:
        set_armed(args.arm == "on")
        print(f"parlay {'ARMED' if args.arm == 'on' else 'disarmed'}")


if __name__ == "__main__":
    main()
