from __future__ import annotations

import math
from datetime import datetime
from typing import Optional

import backtest as bt
import crypto15m
import crypto15m_trader
import db as dbmod

_DERIVABLE = {
    "hasMarket", "favorite", "favoritePrice", "entryCost", "minsLeft",
    "inWindow", "signal", "modelProb", "edgeNetCents", "spotLive",
    "upAsk", "downAsk", "yesBid", "yesAsk", "upProb", "downProb",
    "deltaPct", "deltaSignedPct", "sigma1m", "spotUsd", "strikeUsd",
    "macd", "macdSignal", "macdHist", "macdCross", "rsi", "hourUtc",
    "closeTime", "ticker", "asset", "series",
    "vwap1h", "ema12", "sma20", "sma50", "priceVsVwapPct",
    "ema12VsSma20Pct", "ema1VsSma5Pct", "velocity1mPct",
    "change5mPct", "change15mPct",
    "spreadCents", "modelEdgePts", "favoriteAskCents", "timeFracLeft",
}


def tick_to_asset(row: dict, cfg: dict, close_iso: str) -> dict:
    up_prob = row.get("up_prob")
    yes_bid, yes_ask = row.get("yes_bid"), row.get("yes_ask")
    no_ask = row.get("no_ask")
    fav = None
    fav_price = None
    if up_prob is not None:
        fav = "up" if float(up_prob) >= 0.5 else "down"
        fav_price = float(up_prob) if fav == "up" else 1.0 - float(up_prob)
    ml = row.get("mins_left")
    in_window = (
        ml is not None
        and float(ml) <= float(crypto15m._const(cfg, "time_delay_min"))
    )
    hour = None
    ts = row.get("observed_at") or ""
    try:
        hour = datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S").hour
    except Exception:
        pass
    entry_cost = None
    if fav == "up":
        entry_cost = yes_ask
    elif fav == "down":
        entry_cost = no_ask
    if entry_cost is None and fav_price is not None:
        entry_cost = fav_price
    dp = row.get("delta_pct")
    signal = bool(
        in_window
        and fav_price is not None
        and fav_price >= crypto15m._const(cfg, "entry_threshold")
        and (entry_cost is None or float(entry_cost) <= crypto15m._const(cfg, "entry_max"))
        and (dp is None or float(dp) >= crypto15m._const(cfg, "min_delta_pct"))
        and (hour is None or crypto15m.hours_ok(cfg, hour=hour))
    )
    src = str(row.get("spot_source") or "")
    up_ask = row.get("up_ask")
    if up_ask is None and fav == "up" and row.get("ws_ask") is not None:
        up_ask = yes_ask
    out = {
        "asset": row.get("asset"), "ticker": row.get("ticker"),
        "series": f"{row.get('asset')}-updown", "hasMarket": True,
        "closeTime": close_iso,
        "favorite": fav, "favoritePrice": fav_price, "entryCost": entry_cost,
        "minsLeft": float(ml) if ml is not None else None,
        "inWindow": in_window, "signal": signal, "hourUtc": hour,
        "modelProb": row.get("model_prob"),
        "edgeNetCents": row.get("edge_net_cents"),
        "spotLive": ("rtds-ws" in src) or ("coinbase-ws" in src),
        "upAsk": up_ask, "downAsk": no_ask,
        "yesBid": yes_bid, "yesAsk": yes_ask,
        "upProb": up_prob,
        "downProb": (1.0 - float(up_prob)) if up_prob is not None else None,
        "deltaPct": row.get("delta_pct"),
        "deltaSignedPct": row.get("delta_signed_pct"),
        "sigma1m": row.get("sigma1m"),
        "spotUsd": row.get("spot"), "strikeUsd": row.get("strike"),
        "macd": row.get("macd"), "macdSignal": row.get("macd_signal"),
        "macdHist": row.get("macd_hist"), "macdCross": row.get("macd_cross"),
        "rsi": row.get("rsi"),
        "vwap1h": row.get("vwap1h"), "ema12": row.get("ema12"),
        "sma20": row.get("sma20"), "sma50": row.get("sma50"),
        "priceVsVwapPct": row.get("price_vs_vwap_pct"),
        "ema12VsSma20Pct": row.get("ema12_vs_sma20_pct"),
        "ema1VsSma5Pct": row.get("ema1_vs_sma5_pct"),
        "velocity1mPct": row.get("velocity1m_pct"),
        "change5mPct": row.get("change5m_pct"),
        "change15mPct": row.get("change15m_pct"),
    }
    crypto15m.derive_script_fields(out, crypto15m._interval(cfg))
    return out


def _tick_epoch(row: dict) -> Optional[float]:
    ts = str(row.get("observed_at") or "")
    try:
        return datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S").timestamp()
    except ValueError:
        return None


def _exec_ask(row: dict, side: str) -> Optional[float]:
    if side == "down":
        v = row.get("no_ask")
    else:
        v = row.get("up_ask")
        if v is None and row.get("ws_ask") is not None:
            up_prob = row.get("up_prob")
            if up_prob is not None and float(up_prob) >= 0.5:
                v = row.get("yes_ask")
    if v is None:
        return None
    v = float(v)
    return v if 0.0 < v < 1.0 else None


def _quote_stable_secs(ticks: list[dict], i: int, side: str) -> float:
    a0 = _exec_ask(ticks[i], side)
    t_i = _tick_epoch(ticks[i])
    if a0 is None or t_i is None:
        return 0.0
    stable_since = t_i
    for j in range(i - 1, -1, -1):
        aj = _exec_ask(ticks[j], side)
        t_j = _tick_epoch(ticks[j])
        if aj is None or t_j is None or abs(aj - a0) > 1e-4:
            break
        stable_since = t_j
    return t_i - stable_since


def _latency_fill(
    ticks: list[dict], i: int, side: str, a0: float,
    latency_secs: float, tol: float,
) -> Optional[tuple[float, int]]:
    t_i = _tick_epoch(ticks[i])
    if t_i is None:
        return None
    for j in range(i + 1, len(ticks)):
        t_j = _tick_epoch(ticks[j])
        if t_j is None or (t_j - t_i) < latency_secs:
            continue
        a1 = _exec_ask(ticks[j], side)
        if a1 is None or a1 > a0 + tol:
            return None
        return a1, j
    return None


def _missing_rule_fields(cfg: dict) -> list[str]:
    if not cfg.get("crypto15m_use_rules"):
        return []
    fields = {str(c.get("field")) for c in (cfg.get("crypto15m_rules") or [])}
    return sorted(fields - _DERIVABLE)


def _tp_exit_pnl_ct(
    ticks: list[dict], entry_idx: int, side: str, cost: float, cfg: dict
) -> Optional[float]:
    tp_price = crypto15m._const(cfg, "take_profit")
    tpp = crypto15m._const(cfg, "take_profit_pct")
    if tp_price <= 0 and tpp <= 0:
        return None
    entry_fee = bt.us_fee_per_contract(cost, bt.tick_epoch(ticks[entry_idx]))
    for t2 in ticks[entry_idx + 1:]:
        if side == "up":
            bid = t2.get("yes_bid")
        else:
            ya = t2.get("yes_ask")
            bid = (1.0 - float(ya)) if ya is not None else None
        if bid is None:
            continue
        bid = float(bid)
        if not (0.0 < bid < 1.0):
            continue
        hit = (tp_price > 0 and bid >= tp_price) or (tpp > 0 and bid >= cost * (1.0 + tpp))
        if hit:
            exit_fee = bt.us_fee_per_contract(bid, bt.tick_epoch(t2))
            return (bid - cost) - entry_fee - exit_fee
    return None


def _tick_hour(row: dict) -> Optional[int]:
    ts = str(row.get("observed_at") or "")
    try:
        return int(ts[11:13])
    except (ValueError, IndexError):
        return None


def load_windows(env: str = "mainnet", interval: str = "15m",
                 since_days: int = 60) -> dict[str, list[dict]]:
    with dbmod.get_db() as conn:
        rows = conn.execute(
            """SELECT t.*, s.up_won, s.close_time AS sig_close
               FROM crypto15m_ticks t
               JOIN crypto15m_signals s
                 ON s.ticker = t.ticker AND s.network = t.network
               WHERE s.resolved = 1 AND s.up_won IS NOT NULL
                 AND t.network = ?
                 AND COALESCE(s.interval, '15m') = ?
                 AND t.observed_at >= datetime('now', ?)
               ORDER BY t.ticker, t.observed_at""",
            (env, interval, f"-{int(since_days)} days"),
        ).fetchall()
    by_window: dict[str, list[dict]] = {}
    for r in rows:
        by_window.setdefault(r["ticker"], []).append(dict(r))
    return by_window


def _simulate(
    by_window: dict[str, list[dict]], cfg: dict, *, contracts: int = 1,
    stable_secs: float = 0.0, latency_secs: float = 0.0, slip_tol: float = 0.0,
) -> tuple[list[dict], int, int]:
    has_sched = isinstance(cfg.get("crypto15m_hour_configs"), dict)
    trades: list[dict] = []
    n_windows = 0
    latency_misses = 0
    for ticker, ticks in by_window.items():
        if not crypto15m.asset_enabled(cfg, str(ticks[0].get("asset") or "")):
            continue
        n_windows += 1
        up_won = int(ticks[0].get("up_won") or 0)
        close_iso = str(ticks[0].get("sig_close") or "")
        for i, t in enumerate(ticks):
            eff = cfg
            if has_sched:
                eff = crypto15m.hour_override(cfg, _tick_hour(t))
                if eff is None:
                    continue
            asset = tick_to_asset(t, eff, close_iso)
            try:
                ok, _why = crypto15m_trader.should_enter(
                    asset, eff, has_open=False, open_count=0,
                )
            except Exception:
                ok = False
            if not ok:
                continue
            if eff.get("crypto15m_paired_mode"):
                dom, dom_edge, _he = crypto15m_trader.paired_sides(asset)
                tilt = crypto15m_trader.paired_tilt(dom_edge, eff)
                if not dom or tilt < 1:
                    continue
                if stable_secs > 0 and (
                    _quote_stable_secs(ticks, i, "up") < stable_secs
                    or _quote_stable_secs(ticks, i, "down") < stable_secs
                ):
                    continue
                up_cost = float(asset["upAsk"])
                down_cost = float(asset["downAsk"])
                if latency_secs > 0:
                    f_up = _latency_fill(ticks, i, "up", up_cost, latency_secs, slip_tol)
                    f_down = _latency_fill(ticks, i, "down", down_cost, latency_secs, slip_tol)
                    if f_up is None or f_down is None:
                        latency_misses += 1
                        continue
                    up_cost, down_cost = f_up[0], f_down[0]
                dom_cost, hedge_cost = (
                    (up_cost, down_cost) if dom == "up" else (down_cost, up_cost)
                )
                dom_won = up_won if dom == "up" else (1 - up_won)
                _at = bt.tick_epoch(t)
                dom_fee = bt.us_fee_per_contract(dom_cost, _at)
                hedge_fee = bt.us_fee_per_contract(hedge_cost, _at)
                dom_pnl = (1.0 - dom_cost - dom_fee) if dom_won else (-dom_cost - dom_fee)
                hedge_pnl = (-hedge_cost - hedge_fee) if dom_won else (1.0 - hedge_cost - hedge_fee)
                pnl_unit = tilt * dom_pnl + hedge_pnl
                trades.append({
                    "ticker": ticker, "asset": asset["asset"], "side": dom,
                    "costCents": round((up_cost + down_cost) * 100, 1),
                    "minsLeft": asset["minsLeft"], "won": bool(dom_won),
                    "pnlUsd": round(pnl_unit * contracts, 4),
                    "at": t.get("observed_at"), "tilt": tilt,
                })
                break
            side = crypto15m_trader._entry_side(asset, eff)
            if side not in ("up", "down"):
                continue
            cost = asset["upAsk"] if side == "up" else asset["downAsk"]
            if not cost or not (0.0 < float(cost) < 1.0):
                continue
            cost = float(cost)
            if stable_secs > 0 and _quote_stable_secs(ticks, i, side) < stable_secs:
                continue
            fill_idx = i
            if latency_secs > 0:
                filled = _latency_fill(ticks, i, side, cost, latency_secs, slip_tol)
                if filled is None:
                    latency_misses += 1
                    continue
                cost, fill_idx = filled
            fee = bt.us_fee_per_contract(cost, bt.tick_epoch(t))
            won = up_won if side == "up" else (1 - up_won)
            pnl_ct = (1.0 - cost - fee) if won else (-cost - fee)
            exit_reason = "settlement"
            tp_ct = _tp_exit_pnl_ct(ticks, fill_idx, side, cost, eff)
            if tp_ct is not None:
                pnl_ct = tp_ct
                won = tp_ct > 0
                exit_reason = "take_profit"
            trades.append({
                "ticker": ticker, "asset": asset["asset"], "side": side,
                "costCents": round(cost * 100, 1),
                "minsLeft": asset["minsLeft"], "won": bool(won),
                "pnlUsd": round(pnl_ct * contracts, 4),
                "exitReason": exit_reason,
                "at": t.get("observed_at"),
            })
            break
    return trades, n_windows, latency_misses


def replay(cfg: dict, *, env: str = "mainnet", since_days: int = 60) -> dict:
    cfg = dict(cfg)
    cfg["crypto15m_enabled"] = True
    cfg["crypto15m_model_autopause"] = False
    contracts = max(1, int(cfg.get("crypto15m_order_size") or 1))
    stable_secs = float(cfg.get("replay_min_quote_stable_secs") or 0.0)
    latency_secs = float(cfg.get("replay_latency_secs") or 0.0)
    slip_tol = float(cfg.get("replay_latency_slip_tol_cents", 1.0) or 0.0) / 100.0
    latency_misses = 0
    interval = crypto15m._interval(cfg)
    by_window = load_windows(env=env, interval=interval, since_days=since_days)
    trades, n_windows, latency_misses = _simulate(
        by_window, cfg, contracts=contracts, stable_secs=stable_secs,
        latency_secs=latency_secs, slip_tol=slip_tol,
    )

    caveats = [
        f"Replayed the {interval} window series only (the interval this config trades); data recorded while the app watched other intervals is excluded.",
        "Entries fill at the recorded ask (taker, US fee θ·P·(1−P) at the schedule in force then — θ 0.06 since 1 Jul 2026); real fills can be worse and marketable orders sometimes miss entirely.",
        "Only ticks with a REAL captured book are fillable — Gamma-fallback prices (CLOB WS cold) are treated as no quote, exactly like live.",
        "Top-of-book depth is not recorded — fills assume the full order size was available at the ask (fine at probe size, optimistic at scale).",
    ]
    _hcs = cfg.get("crypto15m_hour_configs")
    if isinstance(_hcs, dict) and _hcs:
        caveats.insert(0, (
            f"Per-hour schedule active: {len(_hcs)} of 24 UTC hours seated "
            "(each under its own generated config); unseated hours are "
            "untraded by design."
        ))
    elif isinstance(_hcs, dict):
        caveats.insert(0, (
            "Per-hour schedule active but EMPTY: 0 of 24 UTC hours seated, so "
            "this schedule trades nothing. Any zero result below is the empty "
            "schedule, not the strategy."
        ))
    if stable_secs > 0:
        caveats.append(
            f"Quote-stability filter ON: entries only where the side's ask sat "
            f"unchanged ≥{stable_secs:g}s across recorded ticks (a lower bound — "
            "ticks are ~4-25s apart, so genuinely-fresh fillable quotes are also "
            "excluded; treat as the conservative end)."
        )
    else:
        caveats.append(
            "Quote-stability filter OFF: entries can fill at asks that had JUST "
            "moved — on an independent 5m corpus that convention manufactured a "
            "large phantom edge from stale quotes (replay_min_quote_stable_secs "
            "to test)."
        )
    if latency_secs > 0:
        caveats.append(
            f"Signal-to-fill latency ON: fills at the first tick ≥{latency_secs:g}s "
            f"after the signal, missed when the ask ran >{slip_tol*100:.1f}¢ past "
            f"the signal price ({latency_misses} misses; the gate keeps retrying "
            "later ticks, matching the live loop)."
        )
    else:
        caveats.append(
            "Signal-to-fill latency OFF: fills at the signal tick itself; live "
            "submit-to-match is ~0.3-1.5s (replay_latency_secs to test)."
        )
    if cfg.get("crypto15m_paired_mode"):
        caveats.append(
            "Paired mode assumes BOTH legs fill at the recorded asks; live, a "
            "missed hedge leaves a naked single-side position."
        )
    caveats += [
        "Single-side take-profit exits (price target + percent-above-cost) ARE simulated at the recorded bid (entry + exit taker fees charged); stop-loss and paired-leg take-profit exits are NOT — those still hold to settlement.",
        f"Ticks are ~4-25s apart over {since_days} days of app uptime only; the gate could have fired between ticks.",
        "In-sample: any threshold tuned against this panel is fit to the past. Watch it run detection-only before arming.",
        "Live model-calibration auto-pause is NOT simulated — live trading can pause where this replay keeps trading.",
        "Final-minute sniper (model mode) needs a per-asset live WS spot. Ticks recorded before 2026-07-06 stored only the snapshot-wide feed tag, so their final-minute snipes may be over-admitted vs live; newer ticks record per-asset liveness.",
    ]
    missing = _missing_rule_fields(cfg)
    if missing:
        caveats.insert(0, (
            "Rules reference fields not recorded in ticks — those conditions "
            f"never match in replay (0 trades is expected): {', '.join(missing)}"
        ))
    if n_windows == 0:
        caveats.insert(0, (
            f"No resolved {interval} windows recorded in the last {since_days} "
            "days — the recorder only captures the interval selected on the "
            "Crypto tab, so switch to it there and let data accumulate first."
        ))
    out = _summarize(trades, contracts, n_windows, caveats)
    out["interval"] = interval
    out["fillModel"] = {
        "minQuoteStableSecs": stable_secs,
        "latencySecs": latency_secs,
        "latencySlipTolCents": slip_tol * 100.0,
        "latencyMisses": latency_misses,
    }
    return out


def _bucketize(trades: list[dict]) -> dict:
    by_hour = {h: {"n": 0, "wins": 0, "pnlUsd": 0.0} for h in range(24)}
    by_day: dict[str, dict] = {}
    for t in trades:
        ts = str(t.get("at") or "")
        try:
            hour = int(ts[11:13])
        except (ValueError, IndexError):
            hour = None
        day = ts[:10] if len(ts) >= 10 else None
        if hour is not None:
            b = by_hour[hour]
            b["n"] += 1
            b["wins"] += 1 if t["won"] else 0
            b["pnlUsd"] = round(b["pnlUsd"] + t["pnlUsd"], 4)
        if day:
            d = by_day.setdefault(day, {"n": 0, "wins": 0, "pnlUsd": 0.0})
            d["n"] += 1
            d["wins"] += 1 if t["won"] else 0
            d["pnlUsd"] = round(d["pnlUsd"] + t["pnlUsd"], 4)
    return {
        "byHourUtc": [{"hour": h, **by_hour[h]} for h in range(24)],
        "byDay": [{"day": d, **v} for d, v in sorted(by_day.items())],
    }


def _summarize(trades: list[dict], contracts: int, n_windows: int,
               caveats: list[str]) -> dict:
    trades = sorted(trades, key=lambda t: str(t.get("at") or ""))
    n = len(trades)
    wins = sum(1 for t in trades if t["won"])
    total = sum(t["pnlUsd"] for t in trades)
    denom = sum(int(t.get("contracts", contracts) or contracts) for t in trades)
    ev_ct = (total / denom * 100.0) if denom else 0.0
    by_asset: dict[str, dict] = {}
    for t in trades:
        a = by_asset.setdefault(t.get("asset") or "?", {"n": 0, "wins": 0, "pnlUsd": 0.0})
        a["n"] += 1
        a["wins"] += 1 if t["won"] else 0
        a["pnlUsd"] = round(a["pnlUsd"] + t["pnlUsd"], 4)
    equity, run = [], 0.0
    for t in trades:
        run += t["pnlUsd"]
        equity.append({"at": t.get("at"), "value": round(run, 4)})
    max_dd, peak = 0.0, 0.0
    for e in equity:
        peak = max(peak, e["value"])
        max_dd = min(max_dd, e["value"] - peak)
    if n < 30:
        caveats = [f"Only {n} trades — far too few for a verdict; treat as anecdote."] + list(caveats)
    t_stat = None
    if n >= 2:
        mean = total / n
        var = sum((t["pnlUsd"] - mean) ** 2 for t in trades) / (n - 1)
        if var > 1e-9:
            t_stat = round(max(-20.0, min(20.0, mean / (math.sqrt(var) / math.sqrt(n)))), 3)
    return {
        "n": n, "wins": wins,
        "winRate": round(wins / n, 4) if n else 0.0,
        "netEvCentsPerContract": round(ev_ct, 2),
        "totalPnlUsd": round(total, 2),
        "tStat": t_stat,
        "maxDrawdownUsd": round(max_dd, 2),
        "contracts": contracts,
        "windowsScanned": n_windows,
        "byAsset": by_asset,
        "equity": equity[-400:],
        "trades": trades[-50:],
        "caveats": caveats,
        **_bucketize(trades),
    }


def replay_main(cfg: dict, *, since_days: int = 60,
                slippage_cents: float = 1.0) -> dict:
    import trader as trader_mod
    contracts = 5
    fixed_usd = float(cfg.get("fixed_trade_usd") or 5.0)
    trades: list[dict] = []
    scanned = 0
    with dbmod.get_db() as conn:
        whales = conn.execute(
            """SELECT * FROM whale_trades WHERE resolved=1
               AND outcome_correct IS NOT NULL
               AND created_at >= datetime('now', ?)""",
            (f"-{int(since_days)} days",),
        ).fetchall()
        alerts = conn.execute(
            """SELECT * FROM alerts WHERE resolved=1
               AND outcome_correct IS NOT NULL
               AND created_at >= datetime('now', ?)""",
            (f"-{int(since_days)} days",),
        ).fetchall()

    def _sim(sig: dict, source: str, price, won: bool) -> None:
        if price is None or not (0.0 < float(price) < 1.0):
            return
        cost = min(0.99, float(price) + slippage_cents / 100.0)
        n_ct = max(1, int(round(fixed_usd / max(cost, 0.01))))
        fee = bt.us_fee_per_contract(cost, bt.epoch_of(sig.get("created_at")))
        pnl_ct = (1.0 - cost - fee) if won else (-cost - fee)
        trades.append({
            "ticker": sig.get("ticker"), "asset": sig.get("category") or source,
            "side": sig.get("taker_side") or sig.get("direction") or "?",
            "costCents": round(cost * 100, 1), "minsLeft": None,
            "won": bool(won), "pnlUsd": round(pnl_ct * n_ct, 4),
            "contracts": n_ct,
            "at": sig.get("created_at"),
        })

    for r in whales:
        sig = dict(r)
        scanned += 1
        try:
            ok, _why = trader_mod.should_trade(sig, "whale", cfg)
        except Exception:
            ok = False
        if not ok:
            continue
        _sim(sig, "whale", sig.get("price"), bool(sig.get("outcome_correct")))
    for r in alerts:
        sig = dict(r)
        scanned += 1
        try:
            ok, _why = trader_mod.should_trade(sig, "momentum", cfg)
        except Exception:
            ok = False
        if not ok:
            continue
        price = sig.get("price")
        if (sig.get("direction") or "yes").lower() == "no" and price is not None:
            price = 1.0 - float(price)
        _sim(sig, "momentum", price, bool(sig.get("outcome_correct")))

    caveats = [
        f"Follower economics: entry at the signal price +{slippage_cents:.0f}c slippage — live fills on fast markets can be worse.",
        "One simulated trade per accepted signal; live caps (max open, per-event, daily) are NOT applied, so hot events stack correlated trades.",
        "Whale outcomes cluster (one game prints many whale signals) — day/hour buckets share that clustering.",
        "In-sample: signals were only recorded while the app was running.",
    ]
    return _summarize(trades, contracts, scanned, caveats)
