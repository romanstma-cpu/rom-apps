from __future__ import annotations

import asyncio
import json
import logging
import math
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

import crypto15m
import db
import polymarket_api
import rules as rules_engine
import trader

logger = logging.getLogger("crypto15m")

_block_reasons: dict[str, str] = {}
_halt_reason: str = ""

_stop_retry_at: dict = {}
_STOP_RETRY_SEC = 90

_CAL_CACHE: dict = {"at": 0.0, "ok": True, "n": 0, "rate": None, "lb": None}
_CAL_CHECK_SEC = 300.0
_CAL_WINDOW = 40
_CAL_MIN_N = 20
_CAL_PAUSE_LB = 0.85
_CAL_RESUME_LB = 0.88


def _wilson_lb(wins: int, n: int, z: float = 1.645) -> float:
    if n <= 0:
        return 0.0
    p = wins / n
    denom = 1.0 + z * z / n
    center = p + z * z / (2 * n)
    rad = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (center - rad) / denom)


def check_model_calibration(env: str, interval: str = "15m") -> dict:
    now = time.time()
    if now - _CAL_CACHE["at"] < _CAL_CHECK_SEC and _CAL_CACHE.get("interval") == interval:
        return dict(_CAL_CACHE)
    try:
        with db.get_db() as conn:
            rows = conn.execute(
                """SELECT t.ticker, t.model_prob, s.up_won
                   FROM crypto15m_ticks t
                   JOIN crypto15m_signals s
                     ON s.ticker = t.ticker AND s.network = t.network
                   WHERE s.resolved = 1 AND s.up_won IS NOT NULL
                     AND COALESCE(s.interval, '15m') = ?
                     AND t.network = ? AND t.model_prob IS NOT NULL
                     AND t.observed_at >= datetime('now', '-3 days')
                     AND t.mins_left <= 5 AND t.mins_left >= 0.5
                     AND (t.model_prob >= 0.97 OR t.model_prob <= 0.03)
                   ORDER BY t.observed_at""",
                (interval, env),
            ).fetchall()
    except Exception:
        return dict(_CAL_CACHE)
    last_by_ticker: dict = {}
    for r in rows:
        last_by_ticker[r["ticker"]] = r
    recent = list(last_by_ticker.values())[-_CAL_WINDOW:]
    n = len(recent)
    wins = sum(
        1 for r in recent
        if (float(r["model_prob"]) >= 0.5) == bool(r["up_won"])
    )
    lb = _wilson_lb(wins, n)
    prev_ok = bool(_CAL_CACHE.get("ok", True))
    if n < _CAL_MIN_N:
        ok = True
    elif prev_ok:
        ok = lb >= _CAL_PAUSE_LB
    else:
        ok = lb >= _CAL_RESUME_LB
    if prev_ok and not ok:
        logger.warning(
            f"[crypto15m] MODEL CALIBRATION DEGRADED: {wins}/{n} recent "
            f"sniper-band predictions hit (LB {lb:.3f} < {_CAL_PAUSE_LB}) — "
            f"auto-pausing model-mode entries"
        )
    elif not prev_ok and ok:
        logger.info(f"[crypto15m] model calibration recovered (LB {lb:.3f}) — resuming")
    _CAL_CACHE.update({
        "at": now, "ok": ok, "n": n, "interval": interval,
        "rate": round(wins / n, 4) if n else None, "lb": round(lb, 4),
    })
    return dict(_CAL_CACHE)


_PARLAY_KV_SCHEDULE = "crypto15m_parlay_schedule"
_PARLAY_KV_ARMED = "crypto15m_parlay_armed"
_parlay_cache: dict = {"at": 0.0, "armed": False, "schedule": None}
_PARLAY_REFRESH_SEC = 10.0


def parlay_state(force: bool = False) -> tuple[bool, Optional[dict]]:
    now = time.time()
    if not force and now - _parlay_cache["at"] < _PARLAY_REFRESH_SEC:
        return _parlay_cache["armed"], _parlay_cache["schedule"]
    try:
        with db.get_db() as conn:
            armed = db.kv_get(conn, _PARLAY_KV_ARMED) == "1"
            raw = db.kv_get(conn, _PARLAY_KV_SCHEDULE)
        sched = json.loads(raw) if raw else None
        hcs = sched.get("hour_configs") if isinstance(sched, dict) else None
        if not isinstance(sched, dict) or not isinstance(hcs, dict) or not hcs:
            sched = None
        _parlay_cache.update(
            {"at": now, "armed": bool(armed and sched), "schedule": sched}
        )
    except Exception as e:
        logger.debug(f"[crypto15m] parlay state read failed: {e}")
        _parlay_cache["at"] = now
    return _parlay_cache["armed"], _parlay_cache["schedule"]


_C15_MIN_CONTRACTS = 5

_underfunded_log_t: dict = {}
_UNDERFUNDED_LOG_SEC = 300

_MIN_ORDER_NOTIONAL_USD = 1.00

_PAIRED_CHASE_TOL_CENTS = 0


def _min_notional_ok(contracts: int, limit_cents: int) -> bool:
    return (int(contracts) * int(limit_cents)) / 100.0 >= _MIN_ORDER_NOTIONAL_USD


def _leg_landed(row: Optional[dict]) -> bool:
    return bool(row) and (row.get("status") in ("submitted", "filled", "partial"))


def direction_for_favorite(favorite: str) -> str:
    return "yes" if favorite == "up" else "no"


def _is_directional_rules(cfg: dict) -> bool:
    return bool(cfg.get("crypto15m_use_rules")) and bool(cfg.get("crypto15m_rules_no"))


def _directional_rules_side(asset: dict, cfg: dict) -> tuple[Optional[str], str]:
    ok_y, _ = evaluate_rules(asset, cfg.get("crypto15m_rules") or [])
    if ok_y:
        return "up", "yes-rules matched"
    ok_n, _ = evaluate_rules(asset, cfg.get("crypto15m_rules_no") or [])
    if ok_n:
        return "down", "no-rules matched"
    return None, "no directional rule matched"


def _entry_side(asset: dict, cfg: dict) -> str:
    if _is_directional_rules(cfg):
        return _directional_rules_side(asset, cfg)[0] or ""
    mode = (cfg.get("crypto15m_direction_mode") or "favorite").lower()
    if mode == "model":
        mp = asset.get("modelProb")
        if mp is None:
            return ""
        return "up" if float(mp) >= 0.5 else "down"
    fav = asset.get("favorite") or ""
    if mode == "contrarian":
        return "down" if fav == "up" else "up"
    return fav


def taker_order_type(cfg: dict) -> str:
    return "FAK" if cfg.get("crypto15m_taker_fak", True) else "GTC"


def entry_limit_cents(entry_cost: float, entry_diff: float) -> int:
    cents = round((float(entry_cost) + float(entry_diff)) * 100)
    return max(1, min(99, int(cents)))


def maker_limit_cents(side: str, yes_bid, yes_ask, entry_cost: float) -> int:
    bid = None
    if side == "up":
        bid = yes_bid
    elif side == "down" and yes_ask:
        bid = 1.0 - float(yes_ask)
    if not bid or bid <= 0:
        bid = max(0.01, float(entry_cost) - 0.01)
    return max(1, min(99, int(round(float(bid) * 100))))


def side_prob_from_market(market: Optional[dict], direction: str) -> Optional[float]:
    if not market:
        return None
    yes_bid = crypto15m._price_dollars(market, "yes_bid")
    yes_ask = crypto15m._price_dollars(market, "yes_ask")
    up = (yes_bid + yes_ask) / 2 if (yes_bid or yes_ask) else crypto15m._price_dollars(market, "last_price")
    up = max(0.0, min(1.0, up))
    return up if direction == "yes" else (1.0 - up)


def evaluate_rules(asset: dict, rules: list) -> tuple[bool, str]:
    return rules_engine.evaluate_rules(asset, rules)


_FM_MIN_PROB = 0.9985


def paired_tilt(edge_cents, cfg: dict) -> int:
    if edge_cents is None:
        return 0
    try:
        e = float(edge_cents)
    except (TypeError, ValueError):
        return 0
    t1 = float(cfg.get("crypto15m_paired_tilt1_cents", 3.0) or 3.0)
    t2 = float(cfg.get("crypto15m_paired_tilt2_cents", 6.0) or 6.0)
    t3 = float(cfg.get("crypto15m_paired_tilt3_cents", 10.0) or 10.0)
    if e >= t3:
        return 3
    if e >= t2:
        return 2
    if e >= t1:
        return 1
    return 0


def paired_sides(asset: dict) -> tuple[str, float, float]:
    mp = asset.get("modelProb")
    up_ask, down_ask = asset.get("upAsk"), asset.get("downAsk")
    if mp is None or not up_ask or not down_ask:
        return "", 0.0, 0.0
    mp = float(mp)
    fs = asset.get("feeSchedule")
    at = crypto15m.asset_fee_at(asset)
    up_c, down_c = float(up_ask) * 100.0, float(down_ask) * 100.0
    up_edge = mp * 100.0 - up_c - crypto15m._fee_cents(up_c, fs, at)
    down_edge = (1.0 - mp) * 100.0 - down_c - crypto15m._fee_cents(down_c, fs, at)
    if up_edge >= down_edge:
        return "up", up_edge, down_edge
    return "down", down_edge, up_edge


def should_enter(asset: dict, cfg: dict, *, has_open: bool, open_count: int) -> tuple[bool, str]:
    if not cfg.get("crypto15m_enabled"):
        return False, "disabled"
    if has_open:
        return False, "already open"
    max_conc = int(cfg.get("crypto15m_max_concurrent", len(crypto15m.SERIES)))
    if open_count >= max_conc:
        return False, "max concurrent"
    if not asset.get("hasMarket"):
        return False, "no market"
    if asset.get("favorite") not in ("up", "down"):
        return False, "no favorite"
    mode = (cfg.get("crypto15m_direction_mode") or "favorite").lower()
    if mode != "model" and (cfg.get("crypto15m_entry_style") or "maker").lower() == "maker":
        cancel_min = float(cfg.get("crypto15m_maker_cancel_min", 0.0) or 0.0)
        mins_left = asset.get("minsLeft")
        if cancel_min > 0 and mins_left is not None and float(mins_left) <= cancel_min:
            return False, "inside maker cancel lead"
    if not crypto15m.hours_ok(cfg, hour=asset.get("hourUtc")):
        return False, "outside trading hours"
    if cfg.get("crypto15m_paired_mode"):
        if asset.get("modelProb") is None:
            return False, "model unavailable (needs indicators + spot feed)"
        dom, dom_edge, _hedge_edge = paired_sides(asset)
        if not dom:
            return False, "paired: need live asks on BOTH sides"
        ml = asset.get("minsLeft")
        if ml is not None and float(ml) < 1.0:
            return False, "paired: final minute (single-leg risk — model mode owns this band)"
        if not asset.get("inWindow"):
            return False, "outside entry window"
        up_c = float(asset["upAsk"]) * 100.0
        down_c = float(asset["downAsk"]) * 100.0
        combined = up_c + down_c
        max_comb = float(cfg.get("crypto15m_paired_max_combined_cents", 99.0) or 99.0)
        if combined > max_comb:
            return False, f"paired: combined {combined:.1f}c > {max_comb:.0f}c cap"
        tilt = paired_tilt(dom_edge, cfg)
        if tilt < 1:
            t1 = float(cfg.get("crypto15m_paired_tilt1_cents", 3.0) or 3.0)
            return False, f"paired: edge {dom_edge:.1f}c below the {t1:.0f}c tilt floor"
        gap = float(cfg.get("crypto15m_model_max_book_gap_cents", 25.0) or 0.0)
        if gap > 0 and dom_edge > gap:
            return False, (
                f"paired: model disagrees with a live book by {dom_edge:.0f}c "
                f"(> {gap:.0f}c cap) — distrusting the model input"
            )
        return True, "ok"
    if cfg.get("crypto15m_use_rules"):
        ml = asset.get("minsLeft")
        if ml is not None and float(ml) < 1.0:
            return False, "final minute (custom rules are blocked here — model mode only)"
        if _is_directional_rules(cfg):
            side, why = _directional_rules_side(asset, cfg)
            if side is None:
                return False, why
        else:
            ok, why = evaluate_rules(asset, cfg.get("crypto15m_rules") or [])
            if not ok:
                return ok, why
        rside = _entry_side(asset, cfg)
        rask = asset.get("upAsk") if rside == "up" else (
            asset.get("downAsk") if rside == "down" else None
        )
        if rask and float(rask) > crypto15m._const(cfg, "entry_max"):
            return False, f"ask {float(rask)*100:.0f}c above the entry cap"
        return True, "ok"
    if mode == "model":
        mp = asset.get("modelProb")
        if mp is None:
            return False, "model unavailable (needs indicators + spot feed)"
        mp = float(mp)
        p_side = mp if mp >= 0.5 else 1.0 - mp
        if cfg.get("crypto15m_model_autopause", True):
            cal = check_model_calibration(trader.get_env(), crypto15m._interval(cfg))
            if not cal.get("ok", True):
                return False, (
                    f"model calibration degraded ({cal.get('rate') or 0:.0%} hit over "
                    f"last {cal.get('n', 0)} windows) — auto-paused"
                )
        ml = asset.get("minsLeft")
        final_minute = ml is not None and 0.0 < float(ml) < 1.0
        if final_minute:
            if not cfg.get("crypto15m_model_final_minute", True):
                return False, "final minute (disabled)"
            if not asset.get("spotLive"):
                return False, "final minute needs a live WS spot (asset not covered / feed cold)"
            if float(ml) < 0.1:
                return False, "too close to the close for an order round-trip"
            if p_side < _FM_MIN_PROB:
                return False, f"model {p_side:.4f} < {_FM_MIN_PROB} (3-sigma gate)"
        elif not asset.get("inWindow"):
            return False, "outside entry window"
        else:
            min_p = float(cfg.get("crypto15m_model_min_prob", 0.97) or 0.97)
            if p_side < min_p:
                return False, f"model {p_side:.3f} < {min_p:.2f}"
        ask = asset.get("upAsk") if mp >= 0.5 else asset.get("downAsk")
        if not ask or not (0.0 < float(ask) <= crypto15m._const(cfg, "entry_max")):
            return False, "no executable ask under the entry cap"
        ask_c = float(ask) * 100.0
        edge = round(
            p_side * 100.0 - ask_c - crypto15m._fee_cents(
                ask_c, asset.get("feeSchedule"), crypto15m.asset_fee_at(asset)),
            2,
        )
        min_e = float(cfg.get("crypto15m_model_min_edge_cents", 2.0) or 0.0)
        if edge < min_e:
            return False, f"net edge {edge}c < {min_e:.1f}c (traded side)"
        gap = float(cfg.get("crypto15m_model_max_book_gap_cents", 25.0) or 0.0)
        if final_minute:
            gap = float(cfg.get("crypto15m_model_fm_max_book_gap_cents", 75.0) or 0.0)
        if gap > 0 and edge > gap:
            return False, (
                f"model disagrees with a live book by {edge:.0f}c "
                f"(> {gap:.0f}c cap{' in the final minute' if final_minute else ''}) "
                f"— distrusting the model input"
            )
        return True, "ok"
    _ml = asset.get("minsLeft")
    if _ml is not None and float(_ml) < 1.0:
        return False, "final minute (favorite entries blocked — model mode owns this band)"
    if not asset.get("signal"):
        return False, "no signal"
    if cfg.get("crypto15m_imbalance_gate"):
        imb = asset.get("bookImbalance")
        if imb is None:
            return False, "imbalance gate: no book data"
        mn = float(cfg.get("crypto15m_imbalance_gate_min", 0.2) or 0.0)
        direction = direction_for_favorite(_entry_side(asset, cfg))
        if direction == "yes" and imb < mn:
            return False, f"imbalance {imb:+.2f} < +{mn:.2f}"
        if direction == "no" and imb > -mn:
            return False, f"imbalance {imb:+.2f} > -{mn:.2f}"
    direction = direction_for_favorite(_entry_side(asset, cfg))
    min_rsi = float(cfg.get("crypto15m_min_rsi", 0) or 0.0)
    if min_rsi > 0:
        rsi_v = asset.get("rsi")
        if rsi_v is None:
            return False, "RSI gate: no indicator data"
        rsi_v = float(rsi_v)
        if direction == "yes" and rsi_v < min_rsi:
            return False, f"RSI {rsi_v:.0f} < {min_rsi:.0f}"
        if direction == "no" and rsi_v > (100.0 - min_rsi):
            return False, f"RSI {rsi_v:.0f} > {100.0 - min_rsi:.0f}"
    min_macd = float(cfg.get("crypto15m_min_macd_hist", 0) or 0.0)
    if min_macd > 0:
        mh = asset.get("macdHist")
        if mh is None:
            return False, "MACD gate: no indicator data"
        mh = float(mh)
        if direction == "yes" and mh < min_macd:
            return False, f"MACD hist {mh:+.4f} < +{min_macd:.4f}"
        if direction == "no" and mh > -min_macd:
            return False, f"MACD hist {mh:+.4f} > -{min_macd:.4f}"
    return True, "ok"


def should_stop_loss(position: dict, side_prob: Optional[float], cfg: dict) -> bool:
    if side_prob is None:
        return False
    if (position.get("strategy") or "").startswith("paired"):
        return False
    if (position.get("strategy") or "") == "parlay":
        return False
    if position.get("status") != "filled":
        return False
    if int(position.get("filled_contracts") or 0) <= 0:
        return False
    if position.get("script_id"):
        slc = position.get("sl_cents")
        return bool(slc) and (side_prob * 100.0) <= float(slc)
    if side_prob < crypto15m._const(cfg, "exit_threshold"):
        return True
    slp = _clamp01(crypto15m._const(cfg, "stop_loss_pct"))
    if slp > 0:
        filled = int(position.get("filled_contracts") or 0)
        cost = float(position.get("cost_usd") or 0.0)
        if cost > 0 and filled > 0:
            cur_value = filled * float(side_prob)
            if (cost - cur_value) / cost >= slp:
                return True
    return False


def strength_exit_cents(position: dict, cfg: dict) -> Optional[int]:
    if not cfg.get("crypto15m_sell_into_strength"):
        return None
    if position.get("script_id"):
        return None
    if (position.get("strategy") or "") == "parlay":
        return None
    if position.get("status") != "filled":
        return None
    if int(position.get("filled_contracts") or 0) <= 0:
        return None
    try:
        tgt = float(cfg.get("crypto15m_sell_strength_cents", 80.0) or 80.0)
    except (TypeError, ValueError):
        return None
    tgt = int(round(max(50.0, min(99.0, tgt))))
    entry_c = float(position.get("avg_entry_cents") or 0.0)
    if entry_c <= 0 or tgt < entry_c + 2.0:
        return None
    return tgt


def should_take_profit(position: dict, bid_cents: Optional[int], cfg: dict) -> bool:
    if position.get("script_id"):
        return False
    if (position.get("strategy") or "") == "parlay":
        return False
    target = crypto15m._const(cfg, "take_profit")
    if target <= 0 or bid_cents is None:
        return False
    if position.get("status") != "filled":
        return False
    if int(position.get("filled_contracts") or 0) <= 0:
        return False
    return (bid_cents / 100.0) >= target


def should_take_profit_pct(position: dict, bid_cents: Optional[int], cfg: dict) -> bool:
    if (position.get("strategy") or "") == "parlay":
        return False
    if position.get("script_id"):
        try:
            tpp = max(0.0, float(position.get("tp_pct") or 0.0))
        except (TypeError, ValueError):
            tpp = 0.0
    else:
        tpp = _clamp01(crypto15m._const(cfg, "take_profit_pct"))
    if tpp <= 0 or bid_cents is None:
        return False
    if position.get("status") != "filled":
        return False
    filled = int(position.get("filled_contracts") or 0)
    cost = float(position.get("cost_usd") or 0.0)
    if filled <= 0 or cost <= 0:
        return False
    cur_value = filled * (bid_cents / 100.0)
    return (cur_value - cost) / cost >= tpp


def _clamp01(v) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    if f != f:
        return 0.0
    return max(0.0, min(1.0, f))


_FIXED_SIZE_MAX_BALANCE_FRAC = 0.25

_STREAK_LOOKBACK_ROWS = 40


def streak_multiplier(cfg: dict, env: str) -> float:
    if not cfg.get("crypto15m_streak_sizing"):
        return 1.0
    loss_pct = float(cfg.get("crypto15m_streak_loss_pct", 20.0) or 0.0)
    win_pct = float(cfg.get("crypto15m_streak_win_pct", 0.0) or 0.0)
    cap = max(1.0, float(cfg.get("crypto15m_streak_max_mult", 4.0) or 4.0))
    try:
        with db.get_db() as conn:
            rows = conn.execute(
                "SELECT pnl_usd FROM crypto15m_positions "
                "WHERE resolved=1 AND network=? AND pnl_usd IS NOT NULL "
                "AND dry_run=0 "
                "ORDER BY resolved_at DESC, id DESC LIMIT ?",
                (env, _STREAK_LOOKBACK_ROWS),
            ).fetchall()
    except Exception as e:
        logger.warning(f"[crypto15m] streak read failed, sizing flat: {e}")
        return 1.0
    streak = 0
    won: Optional[bool] = None
    for r in rows:
        pnl = float(r[0])
        if pnl == 0.0:
            break
        w = pnl > 0
        if won is None:
            won = w
        elif w != won:
            break
        streak += 1
    if streak == 0 or won is None:
        return 1.0
    step = win_pct if won else loss_pct
    mult = (1.0 + step / 100.0) ** streak
    return max(0.1, min(cap, mult))


def compute_entry_contracts(
    cfg: dict, *, entry_limit_cents: int, balance_usd: float, order_size: int,
    balance_known: bool = False, streak_mult: float = 1.0,
) -> int:
    price = max(0.01, int(entry_limit_cents) / 100.0)
    bal = max(0.0, float(balance_usd or 0.0))
    if balance_known and bal <= 0.0:
        return 0
    mode = (cfg.get("crypto15m_sizing_mode") or "fixed").lower()

    if mode == "balance_pct" and bal > 0:
        pct = _clamp01(cfg.get("crypto15m_balance_pct", 0.02))
        contracts = int((bal * pct) // price)
    else:
        contracts = max(1, int(order_size))

    if streak_mult != 1.0 and contracts > 0:
        contracts = max(1, int(contracts * streak_mult))

    max_loss = _clamp01(cfg.get("crypto15m_max_loss_pct", 0.0))
    if max_loss > 0 and bal > 0:
        contracts = min(contracts, int((bal * max_loss) // price))
    elif mode != "balance_pct" and bal > 0:
        contracts = min(contracts, int((bal * _FIXED_SIZE_MAX_BALANCE_FRAC) // price))

    if bal > 0:
        contracts = min(contracts, int((bal * 0.98) // price))

    return max(0, contracts)


async def _bankroll_usd(cfg: dict, authed: bool) -> float:
    if authed:
        try:
            cents, _port = await trader.refresh_balance(cfg, force=False)
            if cents > 0:
                return cents / 100.0
            if trader.last_balance_read_ok():
                return 0.0
        except Exception:
            pass
    return max(0.0, float(cfg.get("start_bankroll_usd", 0.0) or 0.0))


def _iso(s):
    if not s or not isinstance(s, str):
        return s
    s = s.strip()
    if not s:
        return s
    if s.endswith("Z") or "+" in s[10:]:
        return s.replace(" ", "T")
    return s.replace(" ", "T") + "Z"


def _pos_to_js(r: dict) -> dict:
    def _f(k):
        return float(r[k]) if r.get(k) is not None else None
    close_ep = crypto15m._parse_close_epoch(r.get("close_time") or "")
    settling = bool(
        r.get("status") == "filled" and not r.get("resolved")
        and close_ep is not None
        and datetime.now(timezone.utc).timestamp() >= close_ep
    )
    return {
        "id": int(r["id"]),
        "asset": r["asset"], "series": r.get("series") or "",
        "ticker": r.get("ticker") or "",
        "side": r.get("side") or "", "direction": r.get("direction") or "",
        "targetContracts": int(r.get("target_contracts") or 0),
        "filledContracts": int(r.get("filled_contracts") or 0),
        "entryLimitCents": int(r.get("entry_limit_cents") or 0),
        "avgEntryCents": _f("avg_entry_cents"),
        "costUsd": float(r.get("cost_usd") or 0.0),
        "status": r.get("status") or "",
        "exitReason": r.get("exit_reason"),
        "exitLimitCents": int(r["exit_limit_cents"]) if r.get("exit_limit_cents") is not None else None,
        "proceedsUsd": _f("proceeds_usd"),
        "confidence": float(r.get("confidence") or 0.0),
        "entryDeltaUsd": _f("entry_delta_usd"),
        "outcomeCorrect": int(r["outcome_correct"]) if r.get("outcome_correct") is not None else None,
        "settlementUsd": _f("settlement_usd"),
        "pnlUsd": _f("pnl_usd"),
        "resolved": bool(r.get("resolved") or 0),
        "settling": settling,
        "dryRun": bool(r.get("dry_run") or 0),
        "closeTime": _iso(r.get("close_time")) or "",
        "network": r.get("network") or "mainnet",
        "createdAt": _iso(r.get("created_at")) or "",
        "resolvedAt": _iso(r.get("resolved_at")),
        "error": r.get("error"),
        "strategy": r.get("strategy") or "",
        "feesUsd": float(r.get("fees_usd") or 0.0) + float(r.get("exit_fees_usd") or 0.0),
    }


async def _open_entry(a: dict, cfg: dict, env: str, balance_usd: float) -> Optional[dict]:
    mode = (cfg.get("crypto15m_direction_mode") or "favorite").lower()
    favorite = a.get("favorite")
    fav_price = float(a.get("favoritePrice") or 0.0)
    side = _entry_side(a, cfg)
    if mode == "model":
        mp = a.get("modelProb")
        if mp is None or side not in ("up", "down"):
            return None
        side_ask = a.get("upAsk") if side == "up" else a.get("downAsk")
        entry_cost = float(side_ask or a.get("entryCost") or fav_price or 0.5)
        conf = (float(mp) if side == "up" else 1.0 - float(mp)) * 100.0
    elif mode == "contrarian":
        entry_cost = max(0.01, 1.0 - fav_price)
        conf = entry_cost * 100.0
    else:
        entry_cost = float(a.get("entryCost") or fav_price)
        conf = fav_price * 100.0
    direction = direction_for_favorite(side)
    style = "taker" if mode == "model" else (cfg.get("crypto15m_entry_style") or "maker").lower()
    ticker = a.get("ticker")
    coid = f"rom-c15-{a['asset']}-{uuid.uuid4().hex[:8]}"
    if style == "maker":
        limit_cents = maker_limit_cents(side, a.get("yesBid"), a.get("yesAsk"), entry_cost)
    else:
        limit_cents = entry_limit_cents(entry_cost, crypto15m._const(cfg, "entry_diff"))

    max_cents = int(round(crypto15m._const(cfg, "entry_max") * 100))

    def _skip_entry(reason: str, exit_reason: str = "above_cap") -> None:
        logger.info(f"[crypto15m] skip {a.get('asset')}: {reason}")
        with db.get_db() as conn:
            pid = db.insert_crypto15m_position(conn, {
                "asset": a["asset"], "series": a["series"], "ticker": ticker,
                "side": side, "direction": direction, "target_contracts": 0,
                "entry_limit_cents": limit_cents, "client_order_id": coid,
                "close_time": a.get("closeTime") or "", "confidence": conf,
                "network": env, "status": "canceled", "dry_run": 0,
                "error": reason,
            })
            _mark_resolved(conn, pid, status="canceled", exit_reason=exit_reason)

    real_bid = real_ask = None
    try:
        rq = await polymarket_api.get_quote(ticker, direction)
        real_bid, real_ask = rq.get("bid_cents"), rq.get("ask_cents")
    except Exception as e:
        logger.debug(f"[crypto15m] entry quote {a.get('asset')}: {e}")
    if real_ask and real_ask > max_cents:
        _skip_entry(
            f"real ask {real_ask}c > entry_max {max_cents}c "
            f"(already-decided; snapshot showed {limit_cents}c)"
        )
        return None
    if mode not in ("contrarian", "model") and not _is_directional_rules(cfg):
        thr_cents = int(round(crypto15m._const(cfg, "entry_threshold") * 100))
        if real_bid is not None and real_ask is not None:
            live_fav = (real_bid + real_ask) // 2
        else:
            live_fav = real_ask if real_ask is not None else real_bid
        if live_fav is not None and live_fav < thr_cents:
            _skip_entry(
                f"{side} now ~{live_fav}c < entry_threshold {thr_cents}c "
                f"(favorite flipped/crashed since snapshot)",
                exit_reason="favorite_flipped",
            )
            return None
    if style == "maker" and real_bid and 1 <= real_bid <= 99:
        limit_cents = real_bid
    elif style != "maker" and real_ask and 1 <= real_ask <= 99:
        markup = max(0, int(round(crypto15m._const(cfg, "entry_diff") * 100)))
        limit_cents = min(max_cents, real_ask + markup)

    if limit_cents > max_cents:
        _skip_entry(
            f"entry {limit_cents}c > entry_max {max_cents}c"
            + ("" if real_ask else " (no live ask; snapshot price)")
        )
        return None

    streak_mult = streak_multiplier(cfg, env)
    if streak_mult != 1.0:
        logger.info(
            f"[crypto15m] streak sizing x{streak_mult:.2f} on {a.get('asset')} "
            f"(from settled win/loss run)"
        )
    order_size = compute_entry_contracts(
        cfg,
        entry_limit_cents=limit_cents,
        balance_usd=balance_usd,
        order_size=max(1, int(cfg.get("crypto15m_order_size", 1))),
        balance_known=trader.last_balance_read_ok(),
        streak_mult=streak_mult,
    )
    if order_size < 1:
        logger.info(
            f"[crypto15m] skip {a.get('asset')}: sizing yielded 0 contracts "
            f"(risk budget too small at {limit_cents}c)"
        )
        return None
    if balance_usd > 0 and order_size < _C15_MIN_CONTRACTS:
        _asset = str(a.get("asset"))
        if time.time() - _underfunded_log_t.get(_asset, 0.0) >= _UNDERFUNDED_LOG_SEC:
            _underfunded_log_t[_asset] = time.time()
            logger.info(
                f"[crypto15m] skip {a.get('asset')}: balance funds only {order_size} "
                f"contract(s) at {limit_cents}c, below the {_C15_MIN_CONTRACTS}-contract "
                f"market minimum (add funds or lower other risk caps)"
            )
        return None
    if balance_usd > 0 and not _min_notional_ok(order_size, limit_cents):
        if cfg.get("crypto15m_autosize_to_min_notional") and limit_cents > 0:
            bumped = int(math.ceil(100.0 / float(limit_cents)))
            if _min_notional_ok(bumped, limit_cents):
                logger.info(
                    f"[crypto15m] {a.get('asset')}: sized up {order_size}->{bumped} "
                    f"contracts at {limit_cents}c to clear the $1 order minimum"
                )
                order_size = bumped
        if not _min_notional_ok(order_size, limit_cents):
            logger.info(
                f"[crypto15m] skip {a.get('asset')}: {order_size}x{limit_cents}c is under "
                f"the exchange's $1 marketable-order minimum"
            )
            return None
    if mode == "model":
        ce = crypto15m._parse_close_epoch(a.get("closeTime") or "")
        if ce is not None and (ce - datetime.now(timezone.utc).timestamp()) < 10.0:
            _skip_entry("under 10s to close — no order round-trip runway",
                        exit_reason="too_late")
            return None

    ml = a.get("minsLeft")
    strategy = "rules" if cfg.get("crypto15m_use_rules") else mode
    if mode == "model" and ml is not None and float(ml) < 1.0:
        strategy = "model_fm"
    if cfg.get("_parlay"):
        strategy = "parlay"
    row = {
        "asset": a["asset"], "series": a["series"], "ticker": ticker,
        "side": side, "direction": direction,
        "target_contracts": order_size, "entry_limit_cents": limit_cents,
        "client_order_id": coid, "close_time": a.get("closeTime") or "",
        "confidence": conf, "strategy": strategy,
        "entry_delta_usd": a.get("deltaUsd"), "network": env,
    }

    entry_ot = "GTC" if style == "maker" else taker_order_type(cfg)
    try:
        resp = await polymarket_api.place_limit_order(
            ticker=ticker, side=direction, action="buy",
            count=order_size, price_cents=limit_cents, client_order_id=coid,
            order_type=entry_ot,
        )
    except Exception as e:
        row.update({"status": "error", "error": str(e)[:200], "dry_run": False})
        with db.get_db() as conn:
            pid = db.insert_crypto15m_position(conn, row)
            _mark_resolved(conn, pid, status="error")
            logger.error(f"[crypto15m] entry order failed {a['asset']}: {e}")
            return db.fetch_crypto15m_by_id(conn, pid)

    order = (resp.get("order") if isinstance(resp, dict) else None) or resp or {}
    oid = order.get("order_id") if isinstance(order, dict) else None
    ostatus = (order.get("status") if isinstance(order, dict) else "") or ""
    if not oid and ostatus.lower() in ("unmatched", "killed"):
        _skip_entry("FAK crossed no liquidity (0 fill)", exit_reason="no_liquidity")
        return None
    if not oid:
        row.update({"status": "error", "error": "no order_id from exchange", "dry_run": False})
        with db.get_db() as conn:
            pid = db.insert_crypto15m_position(conn, row)
            _mark_resolved(conn, pid, status="error")
            logger.error(f"[crypto15m] entry {a['asset']}: no order_id returned; marked error")
            return db.fetch_crypto15m_by_id(conn, pid)
    row.update({"status": "submitted", "order_id": oid, "dry_run": False})
    with db.get_db() as conn:
        pid = db.insert_crypto15m_position(conn, row)
        logger.info(f"[live] entry {a['asset']} {direction} x{order_size} @ {limit_cents}c")
        return db.fetch_crypto15m_by_id(conn, pid)


async def _place_paired_leg(
    a: dict, cfg: dict, env: str, *, side: str, contracts: int,
    limit_cents: int, strategy: str, confidence: float,
) -> Optional[dict]:
    direction = direction_for_favorite(side)
    ticker = a.get("ticker")
    coid = f"rom-c15p-{a['asset']}-{uuid.uuid4().hex[:8]}"
    row = {
        "asset": a["asset"], "series": a["series"], "ticker": ticker,
        "side": side, "direction": direction,
        "target_contracts": contracts, "entry_limit_cents": limit_cents,
        "client_order_id": coid, "close_time": a.get("closeTime") or "",
        "confidence": confidence, "strategy": strategy,
        "entry_delta_usd": a.get("deltaUsd"), "network": env,
    }
    try:
        resp = await polymarket_api.place_limit_order(
            ticker=ticker, side=direction, action="buy",
            count=contracts, price_cents=limit_cents, client_order_id=coid,
            order_type="FAK",
        )
    except Exception as e:
        row.update({"status": "error", "error": str(e)[:200], "dry_run": False})
        with db.get_db() as conn:
            pid = db.insert_crypto15m_position(conn, row)
            _mark_resolved(conn, pid, status="error")
            logger.error(f"[crypto15m] paired {strategy} leg failed {a['asset']}: {e}")
            return db.fetch_crypto15m_by_id(conn, pid)
    order = (resp.get("order") if isinstance(resp, dict) else None) or resp or {}
    oid = order.get("order_id") if isinstance(order, dict) else None
    ostatus = (order.get("status") if isinstance(order, dict) else "") or ""
    if not oid:
        status = "canceled" if ostatus.lower() in ("unmatched", "killed") else "error"
        err = ("FAK crossed no liquidity (0 fill)" if status == "canceled"
               else "no order_id from exchange")
        row.update({"status": status, "error": err, "dry_run": False})
        with db.get_db() as conn:
            pid = db.insert_crypto15m_position(conn, row)
            _mark_resolved(conn, pid, status=status,
                           exit_reason="no_liquidity" if status == "canceled" else None)
            logger.info(f"[crypto15m] paired {strategy} leg {a['asset']}: {err}")
            return db.fetch_crypto15m_by_id(conn, pid)
    row.update({"status": "submitted", "order_id": oid, "dry_run": False})
    with db.get_db() as conn:
        pid = db.insert_crypto15m_position(conn, row)
        logger.info(
            f"[live] paired {strategy} {a['asset']} {direction} x{contracts} @ {limit_cents}c"
        )
        return db.fetch_crypto15m_by_id(conn, pid)


async def _chase_missing_leg(
    a: dict, cfg: dict, env: str, *, side: str, contracts: int,
    filled_leg_limit: int, max_comb: float, markup: int, max_cents: int,
    strategy: str, confidence: float,
) -> Optional[dict]:
    ticker = a.get("ticker")
    try:
        q = await polymarket_api.get_quote(ticker, "yes" if side == "up" else "no")
    except Exception as e:
        logger.debug(f"[crypto15m] paired chase quote {a.get('asset')}: {e}")
        return None
    ask = (q or {}).get("ask_cents")
    if not ask or not (0 < ask <= max_cents):
        return None
    chase_limit = min(max_cents, int(ask) + 2 * markup)
    if filled_leg_limit + chase_limit > max_comb + _PAIRED_CHASE_TOL_CENTS:
        logger.info(
            f"[crypto15m] paired {a.get('asset')}: skip {side} chase — combined "
            f"{filled_leg_limit}+{chase_limit}c over cap+{_PAIRED_CHASE_TOL_CENTS}c; "
            f"leaving the filled leg single-side"
        )
        return None
    if not _min_notional_ok(contracts, chase_limit):
        return None
    logger.info(
        f"[crypto15m] paired {a.get('asset')}: chasing missed {side} leg "
        f"x{contracts} @ {chase_limit}c (re-quoted)"
    )
    return await _place_paired_leg(
        a, cfg, env, side=side, contracts=contracts, limit_cents=chase_limit,
        strategy=strategy, confidence=confidence,
    )


async def _open_paired_entry(
    a: dict, cfg: dict, env: str, balance_usd: float
) -> list[dict]:
    mp = a.get("modelProb")
    ticker = a.get("ticker")
    if mp is None or not ticker:
        return []
    mp = float(mp)
    fs = a.get("feeSchedule")
    try:
        yes_q = await polymarket_api.get_quote(ticker, "yes")
        no_q = await polymarket_api.get_quote(ticker, "no")
    except Exception as e:
        logger.debug(f"[crypto15m] paired quote {a.get('asset')}: {e}")
        return []
    up_ask, down_ask = (yes_q or {}).get("ask_cents"), (no_q or {}).get("ask_cents")
    if not up_ask or not down_ask or not (0 < up_ask <= 99) or not (0 < down_ask <= 99):
        return []
    combined = float(up_ask + down_ask)
    max_comb = float(cfg.get("crypto15m_paired_max_combined_cents", 99.0) or 99.0)
    if combined > max_comb:
        logger.info(
            f"[crypto15m] paired skip {a.get('asset')}: live combined "
            f"{combined:.0f}c > {max_comb:.0f}c cap (snapshot was cheaper)"
        )
        return []
    _at = crypto15m.asset_fee_at(a)
    up_edge = mp * 100.0 - up_ask - crypto15m._fee_cents(up_ask, fs, _at)
    down_edge = (1.0 - mp) * 100.0 - down_ask - crypto15m._fee_cents(down_ask, fs, _at)
    dom_side = "up" if up_edge >= down_edge else "down"
    dom_edge = max(up_edge, down_edge)
    tilt = paired_tilt(dom_edge, cfg)
    if tilt < 1:
        logger.info(
            f"[crypto15m] paired skip {a.get('asset')}: live edge "
            f"{dom_edge:.1f}c fell below the tilt floor"
        )
        return []
    _gap = float(cfg.get("crypto15m_model_max_book_gap_cents", 25.0) or 0.0)
    if _gap > 0 and dom_edge > _gap:
        logger.info(
            f"[crypto15m] paired skip {a.get('asset')}: live edge {dom_edge:.0f}c "
            f"exceeds the {_gap:.0f}c divergence cap — distrusting the model input"
        )
        return []
    dom_ask, hedge_ask = (up_ask, down_ask) if dom_side == "up" else (down_ask, up_ask)
    hedge_side = "down" if dom_side == "up" else "up"
    max_cents = int(round(crypto15m._const(cfg, "entry_max") * 100))
    markup = max(0, int(round(crypto15m._const(cfg, "entry_diff") * 100)))
    dom_limit = min(max_cents, int(dom_ask) + markup)
    hedge_limit = min(max_cents, int(hedge_ask) + markup)
    if dom_ask > max_cents or hedge_ask > max_cents:
        logger.info(f"[crypto15m] paired skip {a.get('asset')}: a leg is above entry_max")
        return []
    over = dom_limit + hedge_limit - int(max_comb)
    if over > 0:
        shave = min(over, dom_limit - int(dom_ask))
        dom_limit -= shave
        over -= shave
    if over > 0:
        shave = min(over, hedge_limit - int(hedge_ask))
        hedge_limit -= shave
        over -= shave
    if dom_limit + hedge_limit > max_comb:
        logger.info(
            f"[crypto15m] paired skip {a.get('asset')}: worst-case paid "
            f"{dom_limit}+{hedge_limit}c exceeds the {max_comb:.0f}c cap (markup incl.)"
        )
        return []
    unit_cents = tilt * dom_limit + hedge_limit
    streak_mult = streak_multiplier(cfg, env)
    if streak_mult != 1.0:
        logger.info(
            f"[crypto15m] streak sizing x{streak_mult:.2f} on paired "
            f"{a.get('asset')} (from settled win/loss run)"
        )
    units = compute_entry_contracts(
        cfg, entry_limit_cents=unit_cents, balance_usd=balance_usd,
        order_size=max(1, int(cfg.get("crypto15m_order_size", 1))),
        balance_known=trader.last_balance_read_ok(),
        streak_mult=streak_mult,
    )
    dom_n, hedge_n = units * tilt, units
    if units < 1:
        logger.info(
            f"[crypto15m] paired skip {a.get('asset')}: sizing yielded 0 units "
            f"(pair costs {unit_cents}c/unit)"
        )
        return []
    if balance_usd > 0 and (dom_n < _C15_MIN_CONTRACTS or hedge_n < _C15_MIN_CONTRACTS):
        logger.info(
            f"[crypto15m] paired skip {a.get('asset')}: legs {dom_n}/{hedge_n} below "
            f"the {_C15_MIN_CONTRACTS}-contract market minimum"
        )
        return []
    if balance_usd > 0 and (
        not _min_notional_ok(dom_n, dom_limit) or not _min_notional_ok(hedge_n, hedge_limit)
    ):
        logger.info(
            f"[crypto15m] paired skip {a.get('asset')}: a leg is under the exchange's "
            f"$1 marketable-order minimum ({dom_n}x{dom_limit}c / {hedge_n}x{hedge_limit}c)"
        )
        return []
    ce = crypto15m._parse_close_epoch(a.get("closeTime") or "")
    if ce is not None and (ce - datetime.now(timezone.utc).timestamp()) < 20.0:
        logger.info(f"[crypto15m] paired skip {a.get('asset')}: under 20s to close")
        return []

    dom_conf = (mp if dom_side == "up" else 1.0 - mp) * 100.0
    dom_row, hedge_row = await asyncio.gather(
        _place_paired_leg(
            a, cfg, env, side=dom_side, contracts=dom_n, limit_cents=dom_limit,
            strategy="paired", confidence=dom_conf,
        ),
        _place_paired_leg(
            a, cfg, env, side=hedge_side, contracts=hedge_n, limit_cents=hedge_limit,
            strategy="paired_hedge", confidence=100.0 - dom_conf,
        ),
    )
    rows = [r for r in (dom_row, hedge_row) if r]
    dom_ok, hedge_ok = _leg_landed(dom_row), _leg_landed(hedge_row)
    if dom_ok != hedge_ok:
        if dom_ok:
            chase = await _chase_missing_leg(
                a, cfg, env, side=hedge_side, contracts=hedge_n,
                filled_leg_limit=dom_limit, max_comb=max_comb, markup=markup,
                max_cents=max_cents, strategy="paired_hedge",
                confidence=100.0 - dom_conf,
            )
        else:
            chase = await _chase_missing_leg(
                a, cfg, env, side=dom_side, contracts=dom_n,
                filled_leg_limit=hedge_limit, max_comb=max_comb, markup=markup,
                max_cents=max_cents, strategy="paired", confidence=dom_conf,
            )
        if chase:
            rows.append(chase)
        if not _leg_landed(chase):
            logger.warning(
                f"[crypto15m] paired {a.get('asset')}: one leg missed and the "
                f"chase didn't restore it — holding a naked single leg"
            )
    return rows


_V2_CRYPTO_FEE_BPS = 700.0


def _order_fee_usd(order: dict, filled: int, price_cents: float | None) -> float:
    try:
        if not filled or not price_cents:
            return 0.0
        bps = float((order or {}).get("fee_rate_bps") or 0)
        if bps <= 0:
            bps = _V2_CRYPTO_FEE_BPS
        p = max(0.0, min(1.0, float(price_cents) / 100.0))
        return round(bps / 10_000.0 * p * (1.0 - p) * int(filled), 6)
    except (TypeError, ValueError):
        return 0.0


def _fees_paid_usd(pos: dict, *extra) -> float:
    total = float(pos.get("fees_usd") or 0.0) + float(pos.get("exit_fees_usd") or 0.0)
    for f in extra:
        total += float(f or 0.0)
    return total


def _mark_resolved(conn, pid: int, **fields) -> None:
    db.update_crypto15m_position(conn, pid, resolved=1, **fields)
    conn.execute(
        "UPDATE crypto15m_positions SET resolved_at=datetime('now') WHERE id=?", (pid,)
    )


async def _real_fill_cents(
    order_id: Optional[str], fallback_cents: Optional[float], filled: int,
) -> tuple[Optional[float], Optional[float]]:
    fills = []
    if order_id:
        try:
            fills = await polymarket_api.get_fills_for_order(order_id)
        except Exception as e:
            logger.debug(f"[crypto15m] fills lookup {order_id}: {e}")
    tot, qty = 0.0, 0
    for f in fills or []:
        pf = trader._parse_polymarket_fill(f)
        c, n = pf.get("price_cents"), int(pf.get("count") or 0)
        if c and n > 0:
            tot += float(c) * n
            qty += n
    if qty > 0 and filled > 0:
        avg = tot / qty
        return avg, round(avg / 100.0 * filled, 6)
    if fallback_cents is None or filled <= 0:
        return None, None
    return float(fallback_cents), round(float(fallback_cents) / 100.0 * filled, 6)


async def _poll_entry(pos: dict, cfg: dict) -> Optional[dict]:
    pid, kid = pos["id"], pos.get("order_id")
    if not kid:
        return None
    target = int(pos.get("target_contracts") or 0)
    limit_c = int(pos.get("entry_limit_cents") or 0)
    parsed = None
    try:
        resp = await polymarket_api.get_order(kid)
        order = (resp.get("order") if isinstance(resp, dict) else resp) or {}
        parsed = trader._parse_polymarket_order(order)
    except polymarket_api.PolymarketAPIError as e:
        if e.status == 404 and target > 0:
            held = await _onchain_held(pos.get("ticker"), pos.get("direction"))
            booked = min(held, target) if held >= 1 else 0
            avg_c = cost_usd = None
            if booked:
                avg_c, cost_usd = await _real_fill_cents(kid, float(limit_c), booked)
            with db.get_db() as conn:
                if booked:
                    db.update_crypto15m_position(
                        conn, pid, status="filled",
                        filled_contracts=booked,
                        cost_usd=cost_usd,
                        avg_entry_cents=avg_c,
                        fees_usd=_order_fee_usd({}, booked, avg_c),
                    )
                    logger.info(
                        f"[crypto15m] entry 404 → wallet holds {pos.get('asset')} "
                        f"x{booked} @ {avg_c:.0f}c "
                        f"({'real fills' if avg_c != float(limit_c) else 'limit fallback'}, "
                        f"limit {limit_c}c)"
                    )
                else:
                    _mark_resolved(conn, pid, status="canceled", exit_reason="unfilled_expired")
                    logger.info(
                        f"[crypto15m] entry 404, nothing held {pos.get('asset')} — "
                        f"unfilled (reconcile recovers a lagged fill if it landed)"
                    )
                return db.fetch_crypto15m_by_id(conn, pid)
        logger.debug(f"[crypto15m] entry poll {kid}: {e}")
    except Exception as e:
        logger.debug(f"[crypto15m] entry poll {kid}: {e}")

    filled = int(parsed.get("filled") or 0) if parsed else 0
    remaining = int(parsed.get("remaining") or 0) if parsed else 0

    if filled > 0 and remaining <= 0:
        avg_c, cost_usd = await _real_fill_cents(kid, parsed["avg_cents"], filled)
        with db.get_db() as conn:
            db.update_crypto15m_position(
                conn, pid, status="filled",
                filled_contracts=filled,
                cost_usd=cost_usd,
                avg_entry_cents=avg_c,
                fees_usd=_order_fee_usd(order, filled, avg_c),
            )
            return db.fetch_crypto15m_by_id(conn, pid)

    if filled > 0 and filled != int(pos.get("filled_contracts") or 0):
        avg_c, cost_usd = await _real_fill_cents(kid, parsed["avg_cents"], filled)
        with db.get_db() as conn:
            db.update_crypto15m_position(
                conn, pid,
                filled_contracts=filled,
                cost_usd=cost_usd,
                avg_entry_cents=avg_c,
                fees_usd=_order_fee_usd(order, filled, avg_c),
            )

    fast = _maker_fill_timed_out(pos, cfg)
    if fast or _entry_expired(pos, cfg):
        if fast:
            logger.info(
                f"[crypto15m] fast-escalate {pos.get('asset')}: maker unfilled "
                f"after {cfg.get('crypto15m_maker_fill_sec')}s -> crossing to taker"
            )
        try:
            await polymarket_api.cancel_order(kid)
        except Exception as e:
            logger.debug(f"[crypto15m] escalate cancel {kid}: {e}")
        m_filled, m_cost_cents, m_avg = filled, None, None
        cancel_confirmed = False
        try:
            resp2 = await polymarket_api.get_order(kid)
            order2 = (resp2.get("order") if isinstance(resp2, dict) else resp2) or {}
            p2 = trader._parse_polymarket_order(order2)
            if int(p2.get("filled") or 0) >= m_filled:
                m_filled = int(p2["filled"])
                m_cost_cents = int(p2["cost_cents"])
                m_avg = p2["avg_cents"]
            st = (p2.get("status") or "").lower()
            cancel_confirmed = (
                st in ("canceled", "cancelled")
                or int(p2.get("remaining") or 0) <= 0
            )
        except polymarket_api.PolymarketAPIError as e:
            if e.status == 404:
                cancel_confirmed = True
            else:
                logger.debug(f"[crypto15m] escalate re-read {kid}: {e}")
        except Exception:
            pass

        held = await _onchain_held(pos.get("ticker"), pos.get("direction"))
        if held > m_filled:
            m_filled = held
            m_cost_cents = held * limit_c
            m_avg = float(limit_c)

        remaining = target - m_filled

        if remaining > 0 and not cancel_confirmed and not _market_closed(pos):
            logger.info(
                f"[crypto15m] escalate deferred {pos.get('asset')}: maker cancel "
                f"unconfirmed (still resting); retry next tick"
            )
            return None

        t_filled, t_cost_cents = 0, 0
        if (remaining > 0 and cfg.get("crypto15m_maker_escalate", True)
                and not pos.get("script_id")
                and not _market_closed(pos)):
            tk = await _escalate_to_taker(pos, cfg, remaining)
            if tk:
                t_filled = int(tk.get("filled") or 0)
                t_cost_cents = int(tk.get("cost_cents") or 0)

        total_filled = m_filled + t_filled
        with db.get_db() as conn:
            if total_filled > 0:
                upd = {"status": "filled", "filled_contracts": total_filled}
                cost_cents = (m_cost_cents or 0) + t_cost_cents
                if cost_cents > 0:
                    upd["cost_usd"] = cost_cents / 100.0
                    upd["avg_entry_cents"] = cost_cents / total_filled
                elif m_avg is not None:
                    upd["avg_entry_cents"] = m_avg
                db.update_crypto15m_position(conn, pid, **upd)
            else:
                _mark_resolved(conn, pid, status="canceled", exit_reason="unfilled_expired")
            return db.fetch_crypto15m_by_id(conn, pid)
    return None


async def _onchain_held(ticker: Optional[str], direction: Optional[str]) -> int:
    if not ticker:
        return 0
    try:
        positions = await polymarket_api.get_positions(limit=500)
    except Exception:
        return 0
    for p in positions:
        if p.get("ticker") != ticker:
            continue
        qty = float(p.get("position_fp") or 0.0)
        if direction == "yes" and qty > 0:
            return int(round(qty))
        if direction == "no" and qty < 0:
            return int(round(abs(qty)))
    return 0


def _age_seconds(ts) -> Optional[float]:
    if not ts:
        return None
    s = str(ts).replace("T", " ").split(".")[0]
    try:
        dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None
    return (datetime.now(timezone.utc) - dt).total_seconds()


def _maker_fill_timed_out(pos: dict, cfg: dict) -> bool:
    wait = float(cfg.get("crypto15m_maker_fill_sec", 0) or 0)
    if wait <= 0:
        return False
    age = _age_seconds(pos.get("created_at"))
    return age is not None and age >= wait


def _entry_expired(pos: dict, cfg: dict) -> bool:
    close_epoch = crypto15m._parse_close_epoch(pos.get("close_time") or "")
    if close_epoch is None:
        return False
    lead = max(0.0, float(cfg.get("crypto15m_maker_cancel_min", 0.0) or 0.0)) * 60.0
    return datetime.now(timezone.utc).timestamp() >= close_epoch - lead


def _market_closed(pos: dict) -> bool:
    close_epoch = crypto15m._parse_close_epoch(pos.get("close_time") or "")
    if close_epoch is None:
        return False
    return datetime.now(timezone.utc).timestamp() >= close_epoch


async def _escalate_to_taker(pos: dict, cfg: dict, remaining: int) -> Optional[dict]:
    ticker, direction = pos.get("ticker"), pos.get("direction")
    if not ticker:
        return None
    try:
        q = await polymarket_api.get_quote(ticker, direction)
        ask = q.get("ask_cents")
    except Exception as e:
        logger.debug(f"[crypto15m] escalate quote failed {pos.get('asset')}: {e}")
        ask = None
    if not ask or ask < 1:
        return None
    cross = min(99, int(ask))
    max_cents = int(round(crypto15m._const(cfg, "entry_max") * 100))
    if cross > max_cents:
        logger.info(
            f"[crypto15m] skip escalate {pos.get('asset')}: ask {cross}c > entry_max {max_cents}c"
        )
        return None
    if (cfg.get("crypto15m_direction_mode") or "favorite").lower() != "contrarian":
        thr_cents = int(round(crypto15m._const(cfg, "entry_threshold") * 100))
        if cross < thr_cents:
            logger.info(
                f"[crypto15m] skip escalate {pos.get('asset')}: ask {cross}c < "
                f"entry_threshold {thr_cents}c (favorite crashed since entry)"
            )
            return None
    coid = f"{pos.get('client_order_id')}-tk"
    try:
        resp = await polymarket_api.place_limit_order(
            ticker=ticker, side=direction, action="buy",
            count=remaining, price_cents=cross, client_order_id=coid,
            order_type=taker_order_type(cfg),
        )
    except Exception as e:
        logger.warning(f"[crypto15m] escalate place failed {pos.get('asset')}: {e}")
        return None
    order = (resp.get("order") if isinstance(resp, dict) else None) or resp or {}
    oid = order.get("order_id") if isinstance(order, dict) else None

    def _filled(n: int) -> dict:
        return {
            "filled": n, "cost_cents": n * cross, "avg_cents": float(cross),
            "status": "executed", "place_count": n, "remaining": 0,
        }

    if oid:
        for _ in range(3):
            try:
                r2 = await polymarket_api.get_order(oid)
                o2 = (r2.get("order") if isinstance(r2, dict) else r2) or {}
                parsed = trader._parse_polymarket_order(o2)
                f = int(parsed.get("filled") or 0)
                if f > 0:
                    logger.info(f"[live] escalate fill {pos.get('asset')} x{f} @ ~{cross}c")
                    return parsed
                if parsed.get("status") in ("canceled", "cancelled"):
                    return parsed
            except polymarket_api.PolymarketAPIError as e:
                if e.status == 404:
                    logger.info(f"[live] escalate fill {pos.get('asset')} x{remaining} @ ~{cross}c (matched)")
                    return _filled(remaining)
            except Exception as e:
                logger.debug(f"[crypto15m] escalate poll {pos.get('asset')}: {e}")
            await asyncio.sleep(0.6)
    if "match" in str(order.get("status") or "").lower():
        logger.info(f"[live] escalate fill {pos.get('asset')} x{remaining} @ ~{cross}c (placed=matched)")
        return _filled(remaining)
    return None


async def _best_bid_cents(ticker: Optional[str], direction: Optional[str]) -> Optional[int]:
    if not ticker or not direction:
        return None
    try:
        book = await polymarket_api.get_orderbook(ticker)
    except Exception:
        return None
    bids = book.get(direction) or []
    cents = [int(b[0]) for b in bids if b and b[0] is not None]
    return max(cents) if cents else None


async def _place_exit_sell(
    pos: dict, cfg: dict, *, exit_cents: int, reason: str
) -> Optional[dict]:
    pid, ticker, direction = pos["id"], pos["ticker"], pos["direction"]
    filled = int(pos.get("filled_contracts") or 0)
    exit_cents = max(1, min(99, int(exit_cents)))

    coid = f"rom-c15x-{pos['asset']}-{uuid.uuid4().hex[:8]}"
    try:
        resp = await polymarket_api.place_limit_order(
            ticker=ticker, side=direction, action="sell",
            count=filled, price_cents=exit_cents, client_order_id=coid,
        )
    except Exception as e:
        with db.get_db() as conn:
            db.update_crypto15m_position(conn, pid, error=f"{reason} sell failed: {str(e)[:160]}")
            return db.fetch_crypto15m_by_id(conn, pid)

    order = (resp.get("order") if isinstance(resp, dict) else None) or resp or {}
    with db.get_db() as conn:
        db.update_crypto15m_position(
            conn, pid, status="exiting", exit_reason=reason,
            exit_client_order_id=coid,
            exit_order_id=order.get("order_id") if isinstance(order, dict) else None,
            exit_limit_cents=exit_cents,
        )
        logger.info(
            f"[live] {reason.replace('_', '-').upper()} sell "
            f"{pos['asset']} x{filled} @ {exit_cents}c"
        )
        return db.fetch_crypto15m_by_id(conn, pid)


async def _place_stop_loss(pos: dict, market: Optional[dict], cfg: dict) -> Optional[dict]:
    direction = pos["direction"]
    exit_cents = await _best_bid_cents(pos["ticker"], direction)
    if exit_cents is None:
        sp = side_prob_from_market(market, direction) or 0.0
        exit_cents = int(round(sp * 100)) - 2
    return await _place_exit_sell(pos, cfg, exit_cents=exit_cents, reason="stop_loss")


async def _book_exit_from_chain(pos: dict) -> Optional[dict]:
    pid = pos["id"]
    filled = int(pos.get("filled_contracts") or 0)
    already = int(pos.get("exit_filled_contracts") or 0)
    held = await _onchain_held(pos.get("ticker"), pos.get("direction"))
    sold_total = max(already, filled - held)
    if sold_total <= 0:
        return None
    exit_cents = int(pos.get("exit_limit_cents") or 0)
    proceeds = sold_total * exit_cents / 100.0
    with db.get_db() as conn:
        if held <= 0:
            exit_fee = _order_fee_usd({}, sold_total, float(exit_cents))
            pnl = proceeds - float(pos.get("cost_usd") or 0.0) - _fees_paid_usd(pos, exit_fee)
            _mark_resolved(
                conn, pid, status="exited",
                exit_filled_contracts=sold_total, proceeds_usd=proceeds,
                exit_fees_usd=round(float(pos.get("exit_fees_usd") or 0.0) + exit_fee, 6),
                pnl_usd=pnl, outcome_correct=1 if pnl > 0 else 0,
            )
            logger.info(
                f"[crypto15m] exit 404 -> wallet flat; booked {pos.get('asset')} "
                f"sold x{sold_total} @ ~{exit_cents}c pnl=${pnl:+.2f}"
            )
        else:
            db.update_crypto15m_position(
                conn, pid, exit_filled_contracts=sold_total, proceeds_usd=proceeds,
            )
        return db.fetch_crypto15m_by_id(conn, pid)


async def _poll_exit(pos: dict) -> Optional[dict]:
    pid, kid = pos["id"], pos.get("exit_order_id")
    if not kid:
        return None
    try:
        resp = await polymarket_api.get_order(kid)
        order = (resp.get("order") if isinstance(resp, dict) else resp) or {}
        parsed = trader._parse_polymarket_order(order)
    except polymarket_api.PolymarketAPIError as e:
        if e.status == 404:
            return await _book_exit_from_chain(pos)
        logger.debug(f"[crypto15m] exit poll {kid}: {e}")
        return None
    except Exception as e:
        logger.debug(f"[crypto15m] exit poll {kid}: {e}")
        return None
    sold = int(parsed.get("filled") or 0)
    remaining = int(parsed.get("remaining") or 0)
    proceeds = parsed["cost_cents"] / 100.0

    if sold > 0 and remaining <= 0:
        exit_fee = _order_fee_usd(order, sold, parsed["avg_cents"])
        pnl = (proceeds - float(pos.get("cost_usd") or 0.0)
               - float(pos.get("fees_usd") or 0.0) - exit_fee)
        with db.get_db() as conn:
            _mark_resolved(
                conn, pid, status="exited",
                exit_filled_contracts=sold, proceeds_usd=proceeds,
                exit_fees_usd=exit_fee,
                pnl_usd=pnl, outcome_correct=1 if pnl > 0 else 0,
            )
            return db.fetch_crypto15m_by_id(conn, pid)

    if sold > 0 and sold != int(pos.get("exit_filled_contracts") or 0):
        with db.get_db() as conn:
            db.update_crypto15m_position(
                conn, pid, exit_filled_contracts=sold, proceeds_usd=proceeds,
            )
    return None


async def _settle_if_closed(pos: dict) -> Optional[dict]:
    try:
        market = await polymarket_api.fetch_market(pos["ticker"])
    except Exception:
        return None
    payout = trader._market_yes_payout(market) if market else None
    if payout is None:
        return None

    kid = pos.get("exit_order_id")
    if kid:
        try:
            await polymarket_api.cancel_order(kid)
        except Exception:
            pass

    filled = int(pos.get("filled_contracts") or 0)
    cost_usd = float(pos.get("cost_usd") or 0.0)
    sold = int(pos.get("exit_filled_contracts") or 0)
    partial_proceeds = float(pos.get("proceeds_usd") or 0.0)
    residual = max(0, filled - sold)
    our = payout if pos["direction"] == "yes" else (1.0 - payout)
    settlement = residual * our
    synth_exit_fee = 0.0
    if sold > 0 and not float(pos.get("exit_fees_usd") or 0.0):
        synth_exit_fee = _order_fee_usd({}, sold, partial_proceeds / sold * 100.0)
    pnl = partial_proceeds + settlement - cost_usd - _fees_paid_usd(pos, synth_exit_fee)
    correct = 1 if our >= 0.99 else (0 if our <= 0.01 else (1 if pnl > 0.01 else 0))
    with db.get_db() as conn:
        fields = dict(
            exit_reason=pos.get("exit_reason") or "settlement",
            outcome_correct=correct, settlement_usd=settlement, pnl_usd=pnl,
        )
        if synth_exit_fee:
            fields["exit_fees_usd"] = round(synth_exit_fee, 6)
        _mark_resolved(conn, pos["id"], status="settled", **fields)
        logger.info(f"[crypto15m] exiting->settled {pos['asset']} pnl=${pnl:+.2f} (sell never filled)")
        return db.fetch_crypto15m_by_id(conn, pos["id"])


async def _resolved_payout_from_chain(pos: dict) -> Optional[float]:
    try:
        positions = await polymarket_api.get_positions()
    except Exception:
        return None
    direction = pos.get("direction")
    for p in positions:
        if (p.get("ticker") or "") != pos.get("ticker"):
            continue
        if not p.get("redeemable"):
            continue
        held_side = "yes" if float(p.get("position_fp") or 0) > 0 else "no"
        if held_side != direction:
            continue
        held = max(0.0, min(1.0, float(p.get("cur_price") or 0.0)))
        if 0.01 < held < 0.99:
            return None
        return held if direction == "yes" else (1.0 - held)
    return None


async def _manage_position(pos: dict, cfg: dict, env: str) -> Optional[dict]:
    if pos.get("dry_run"):
        with db.get_db() as conn:
            _mark_resolved(conn, pos["id"], status="canceled", exit_reason="paper_removed")
            return db.fetch_crypto15m_by_id(conn, pos["id"])

    status = pos.get("status")

    if status == "submitted":
        return await _poll_entry(pos, cfg)
    if status == "exiting":
        row = await _poll_exit(pos)
        if row:
            return row
        return await _settle_if_closed(pos)
    if status == "error" and int(pos.get("filled_contracts") or 0) <= 0:
        with db.get_db() as conn:
            _mark_resolved(conn, pos["id"], status="error")
            return db.fetch_crypto15m_by_id(conn, pos["id"])
    if status != "filled":
        return None

    pid = pos["id"]
    direction = pos["direction"]
    filled = int(pos.get("filled_contracts") or 0)
    cost_usd = float(pos.get("cost_usd") or 0.0)

    try:
        market = await polymarket_api.fetch_market(pos["ticker"])
    except Exception:
        market = None

    payout = trader._market_yes_payout(market) if market else None
    if payout is None:
        payout = await _resolved_payout_from_chain(pos)
    if payout is not None:
        our = payout if direction == "yes" else (1.0 - payout)
        settlement = filled * our
        pnl = settlement - cost_usd - _fees_paid_usd(pos)
        correct = 1 if our >= 0.99 else (0 if our <= 0.01 else (1 if pnl > 0.01 else 0))
        with db.get_db() as conn:
            _mark_resolved(
                conn, pid, status="settled",
                exit_reason=(pos.get("exit_reason") or "settlement"),
                outcome_correct=correct, settlement_usd=settlement, pnl_usd=pnl,
            )
            return db.fetch_crypto15m_by_id(conn, pid)

    strength_c = strength_exit_cents(pos, cfg)
    if strength_c is not None:
        return await _place_exit_sell(
            pos, cfg, exit_cents=strength_c, reason="sell_strength"
        )

    if (crypto15m._const(cfg, "take_profit") > 0
            or crypto15m._const(cfg, "take_profit_pct") > 0
            or pos.get("tp_pct")):
        bid_cents = await _best_bid_cents(pos["ticker"], direction)
        if (should_take_profit(pos, bid_cents, cfg)
                or should_take_profit_pct(pos, bid_cents, cfg)):
            return await _place_exit_sell(
                pos, cfg, exit_cents=bid_cents, reason="take_profit"
            )

    side_prob = side_prob_from_market(market, direction)
    if should_stop_loss(pos, side_prob, cfg):
        if time.time() - _stop_retry_at.get(pid, 0.0) < _STOP_RETRY_SEC:
            return None
        _stop_retry_at[pid] = time.time()
        trader.cap_dict_size(_stop_retry_at)
        return await _place_stop_loss(pos, market, cfg)

    return None


async def reconcile_filled_from_chain(
    cfg: dict, env: str, *, lookback_sql: str = "-45 minutes"
) -> list[dict]:
    try:
        with db.get_db() as conn:
            candidates = db.crypto15m_reconcile_candidates(conn, env, lookback_sql)
    except Exception as e:
        logger.debug(f"[crypto15m] reconcile candidate query failed: {e}")
        return []
    if not candidates:
        return []

    try:
        positions = await polymarket_api.get_positions(limit=500)
    except Exception as e:
        logger.debug(f"[crypto15m] reconcile positions fetch failed: {e}")
        return []
    by_ticker: dict[str, dict] = {}
    for p in positions:
        tk = p.get("ticker")
        if tk:
            by_ticker[tk] = p

    fixed: list[dict] = []
    for pos in candidates:
        ticker = pos.get("ticker")
        direction = pos.get("direction")
        if not ticker:
            continue
        wp = by_ticker.get(ticker)
        if not wp:
            continue
        qty = float(wp.get("position_fp") or 0.0)
        held = qty if direction == "yes" else -qty
        if held < 1:
            continue

        try:
            with db.get_db() as conn:
                counts = db.crypto15m_ticker_counts(conn, ticker, env)
        except Exception:
            continue
        if counts["total"] != 1 or counts["filled_rows"] > 0:
            logger.warning(
                f"[crypto15m] reconcile: {pos.get('asset')} holds {held:.0f} on "
                f"{ticker[:12]}… but {counts['total']} rows / {counts['filled_rows']} "
                f"already filled — skipping to avoid double-count (review manually)"
            )
            continue

        held_n = int(round(held))
        exposure = float(wp.get("market_exposure_dollars") or 0.0)
        cost_usd = round(exposure, 4)
        avg_cents = max(1, min(99, int(round((exposure / held) * 100)))) if held > 0 else None
        token_price = max(0.0, min(1.0, float(wp.get("cur_price") or 0.0)))
        redeemable = bool(wp.get("redeemable"))

        with db.get_db() as conn:
            if not redeemable:
                db.update_crypto15m_position(
                    conn, pos["id"], status="filled", resolved=0, resolved_at=None,
                    exit_reason=None, error=None,
                    filled_contracts=held_n, cost_usd=cost_usd, avg_entry_cents=avg_cents,
                )
                logger.warning(
                    f"[crypto15m] reconcile RECOVERED {pos.get('asset')} {direction} "
                    f"x{held_n} @ ~{avg_cents}c (was {pos.get('status')}/"
                    f"{pos.get('exit_reason')}; now managed to settlement)"
                )
            else:
                entry_fee = _order_fee_usd({}, held_n, float(avg_cents or 0))
                settlement = held_n * token_price
                pnl = settlement - cost_usd - entry_fee
                correct = (1 if token_price >= 0.99
                           else (0 if token_price <= 0.01 else (1 if pnl > 0.01 else 0)))
                db.update_crypto15m_position(
                    conn, pos["id"], status="settled", resolved=1,
                    exit_reason="settlement_reconciled", error=None,
                    filled_contracts=held_n, cost_usd=cost_usd, avg_entry_cents=avg_cents,
                    fees_usd=round(entry_fee, 6),
                    settlement_usd=round(settlement, 4), pnl_usd=round(pnl, 4),
                    outcome_correct=correct,
                )
                conn.execute(
                    "UPDATE crypto15m_positions SET resolved_at=datetime('now') "
                    "WHERE id=? AND resolved_at IS NULL",
                    (pos["id"],),
                )
                logger.warning(
                    f"[crypto15m] reconcile BOOKED {pos.get('asset')} {direction} "
                    f"x{held_n} cost=${cost_usd:.2f} pnl=${pnl:+.2f} "
                    f"(was {pos.get('status')}/{pos.get('exit_reason')}; filled but mis-marked)"
                )
            row = db.fetch_crypto15m_by_id(conn, pos["id"])
            if row:
                fixed.append(row)
    return fixed


_last_heartbeat_t = 0.0
_last_halt_log_t = 0.0
_last_lifetime_halt_log_t = 0.0
_last_reconcile_t = 0.0
_last_reconcile_ok_t = 0.0


def _lifetime_loss_tripped(cfg: dict, env: str) -> tuple[bool, str]:
    limit_usd = float(cfg.get("crypto15m_lifetime_loss_limit_usd") or 0.0)
    limit_pct = _clamp01(cfg.get("crypto15m_lifetime_loss_limit_pct", 0.0))
    if limit_usd <= 0 and limit_pct <= 0:
        return False, ""
    with db.get_db() as conn:
        lifetime = db.lifetime_realized_pnl(conn, "crypto15m", env)
        if limit_usd > 0:
            cap = limit_usd
        else:
            bankroll = db.effective_start_bankroll(
                conn, env, cfg.get("start_bankroll_usd", 0.0))
            if bankroll <= 0:
                return False, ""
            cap = bankroll * limit_pct
    loss = -lifetime
    if cap > 0 and loss >= cap:
        return True, (
            f"lifetime loss limit reached — engine paused; adjust settings to "
            f"resume (cumulative ${lifetime:+.2f}, loss ${loss:.2f} >= "
            f"cap ${cap:.2f})"
        )
    return False, ""

_auto_off_cb = None


def set_auto_off_callback(cb) -> None:
    global _auto_off_cb
    _auto_off_cb = cb


def _heartbeat(open_count: int) -> None:
    global _last_heartbeat_t
    import time as _t
    now = _t.time()
    if now - _last_heartbeat_t >= 60:
        _last_heartbeat_t = now
        logger.info(f"[crypto15m] executor alive (open positions: {open_count})")


async def run_tick(cfg: dict, *, authed: bool) -> list[dict]:
    if not authed:
        return []
    enabled = bool(cfg.get("crypto15m_enabled"))
    env = trader.get_env()

    global _last_reconcile_t, _last_reconcile_ok_t
    import time as _t
    if _t.time() - _last_reconcile_t >= 60:
        _last_reconcile_t = _t.time()
        if _last_reconcile_ok_t > 0:
            gap_min = max(360.0, (_t.time() - _last_reconcile_ok_t) / 60.0 + 15.0)
        else:
            gap_min = 48 * 60.0
        lookback = f"-{min(int(gap_min), 48 * 60)} minutes"
        try:
            await reconcile_filled_from_chain(cfg, env, lookback_sql=lookback)
            _last_reconcile_ok_t = _t.time()
        except Exception as e:
            logger.warning(f"[crypto15m] reconcile pass failed: {e}")

    with db.get_db() as conn:
        open_positions = db.get_open_crypto15m(conn, env)

    if not enabled and not open_positions:
        return []

    open_by_asset = {p["asset"]: p for p in open_positions}
    open_count = len(open_positions)
    _heartbeat(open_count)

    updated: list[dict] = []

    for pos in open_positions:
        try:
            row = await _manage_position(pos, cfg, env)
            if row:
                updated.append(row)
        except Exception as e:
            logger.warning(f"[crypto15m] manage {pos.get('asset')} failed: {e}")

    global _halt_reason
    loss_limit = float(cfg.get("crypto15m_daily_loss_limit") or 0.0)
    if loss_limit < 0:
        with db.get_db() as conn:
            today_pnl = db.crypto15m_today_pnl(conn, env)
            today_open = db.crypto15m_today_open_cost(conn, env)
        today_figure = today_pnl - today_open
        if today_figure <= loss_limit:
            global _last_halt_log_t
            _halt_reason = (
                f"Daily loss limit hit (today realized ${today_pnl:+.2f} + open "
                f"exposure ${today_open:.2f} = ${today_figure:+.2f} ≤ "
                f"${loss_limit:+.2f}) — new entries paused until UTC midnight. "
                f"Adjust 'Daily loss limit' to resume sooner."
            )
            tnow = datetime.now(timezone.utc).timestamp()
            if tnow - _last_halt_log_t >= 60:
                _last_halt_log_t = tnow
                logger.warning(
                    f"[crypto15m] daily loss limit hit (today realized "
                    f"${today_pnl:+.2f} + open exposure ${today_open:.2f} => "
                    f"${today_figure:+.2f} <= ${loss_limit:+.2f}) — pausing NEW "
                    f"entries for the day"
                )
            return updated

    _lt_trip, _lt_why = _lifetime_loss_tripped(cfg, env)
    if _lt_trip:
        global _last_lifetime_halt_log_t
        _halt_reason = (
            f"{_lt_why} Raise or disable 'Lifetime loss limit' in the risk "
            f"settings below to resume."
        )
        tnow = datetime.now(timezone.utc).timestamp()
        if tnow - _last_lifetime_halt_log_t >= 60:
            _last_lifetime_halt_log_t = tnow
            logger.warning(f"[crypto15m] {_lt_why}")
        return updated
    _halt_reason = ""

    bl_key = f"c15_tp_baseline:{env}"
    tp_total = float(cfg.get("crypto15m_take_profit_total") or 0.0)
    if enabled and tp_total > 0:
        with db.get_db() as conn:
            realized = db.crypto15m_stats(conn, env)["realizedPnlUsd"]
            bl_raw = db.kv_get(conn, bl_key)
            if bl_raw is None:
                db.kv_set(conn, bl_key, repr(realized))
                baseline = realized
                logger.info(
                    f"[crypto15m] overall take-profit armed: +${tp_total:.2f} "
                    f"from baseline ${realized:+.2f}"
                )
            else:
                try:
                    baseline = float(bl_raw)
                except (TypeError, ValueError):
                    baseline = realized
        gained = realized - baseline
        if gained >= tp_total:
            with db.get_db() as conn:
                db.kv_delete(conn, bl_key)
            cfg["crypto15m_enabled"] = False
            logger.info(
                f"[crypto15m] overall take-profit HIT (gained ${gained:+.2f} "
                f">= ${tp_total:.2f}) — turning the crypto engine OFF"
            )
            if _auto_off_cb is not None:
                try:
                    await _auto_off_cb(
                        {"reason": "take_profit_total", "gained": gained, "target": tp_total}
                    )
                except Exception as e:
                    logger.debug(f"[crypto15m] auto-off callback failed: {e}")
            return updated
    elif tp_total <= 0:
        with db.get_db() as conn:
            if db.kv_get(conn, bl_key) is not None:
                db.kv_delete(conn, bl_key)

    if not enabled:
        return updated

    try:
        snap = await crypto15m.snapshot(cfg)
    except Exception as e:
        logger.warning(f"[crypto15m] snapshot unavailable this tick; managed open positions only: {e}")
        snap = {"assets": []}
    assets = {a["asset"]: a for a in snap.get("assets", [])}

    _block_reasons.clear()

    with db.get_db() as conn:
        attempted_tickers = db.crypto15m_attempted_tickers(conn, env)

    balance_usd = await _bankroll_usd(cfg, bool(authed))
    with db.get_db() as conn:
        _exposure = db.current_total_exposure_usd(conn, env)
        _filled_exposure = db.current_filled_exposure_usd(conn, env)
    _pending_notional = max(0.0, _exposure - _filled_exposure)
    _total_bankroll = max(0.0, balance_usd) + max(0.0, _filled_exposure)
    _reserve = _total_bankroll * float(cfg.get("min_cash_reserve_fraction", 0.0) or 0.0)
    _max_exposure = _total_bankroll * float(cfg.get("max_total_exposure_fraction", 1.0) or 1.0)
    _spendable_cash = max(0.0, balance_usd) - _pending_notional
    budget_usd = min(max(0.0, _spendable_cash - _reserve), max(0.0, _max_exposure - _exposure))

    _ok_open, _lock_why = trader.can_open_new_entries(env)
    if not _ok_open:
        logger.info(f"[crypto15m] {_lock_why}")
        return updated

    parlay_armed, parlay_sched = parlay_state()
    parlay_cfg = None
    parlay_block = ""
    if parlay_armed and parlay_sched:
        want_iv = str(parlay_sched.get("interval") or "15m")
        have_iv = crypto15m._interval(cfg)
        if have_iv != want_iv:
            parlay_block = (
                f"parlay: schedule is for {want_iv} windows; Crypto tab is on {have_iv}"
            )
        else:
            parlay_cfg = {**cfg, "crypto15m_hour_configs": parlay_sched["hour_configs"]}

    for sym, a in assets.items():
        if sym in open_by_asset:
            continue
        if not crypto15m.asset_enabled(cfg, sym):
            continue
        if a.get("ticker") in attempted_tickers:
            continue
        eff_cfg = cfg
        if parlay_armed and parlay_cfg is None:
            _block_reasons[a.get("asset") or sym or "?"] = parlay_block
            continue
        if parlay_cfg is not None:
            merged = crypto15m.hour_override(parlay_cfg, a.get("hourUtc"))
            if merged is None:
                _block_reasons[a.get("asset") or sym or "?"] = "parlay: hour not in schedule"
                continue
            merged["_parlay"] = True
            eff_cfg = merged
            a = crypto15m.resignal_asset(a, eff_cfg)
        ok, _why = should_enter(a, eff_cfg, has_open=False, open_count=open_count)
        if not ok:
            _block_reasons[a.get("asset") or sym or "?"] = _why
            continue
        try:
            if eff_cfg.get("crypto15m_paired_mode"):
                rows = await _open_paired_entry(a, eff_cfg, env, budget_usd)
            else:
                one = await _open_entry(a, eff_cfg, env, budget_usd)
                rows = [one] if one else []
            if rows:
                open_count += 1
            for row in rows:
                updated.append(row)
                if row.get("status") in ("submitted", "filled", "partial"):
                    committed = float(row.get("cost_usd") or 0.0)
                    if committed <= 0:
                        committed = (int(row.get("target_contracts") or 0)
                                     * int(row.get("entry_limit_cents") or 0) / 100.0)
                    budget_usd = max(0.0, budget_usd - committed)
        except Exception as e:
            logger.warning(f"[crypto15m] entry {sym} failed: {e}")

    return updated


async def _sizing_preview(cfg: dict, authed: bool) -> dict:
    mode = (cfg.get("crypto15m_sizing_mode") or "fixed").lower()
    balance_pct = _clamp01(cfg.get("crypto15m_balance_pct", 0.02))
    max_loss_pct = _clamp01(cfg.get("crypto15m_max_loss_pct", 0.0))
    order_size = max(1, int(cfg.get("crypto15m_order_size", 1)))
    bal = await _bankroll_usd(cfg, bool(authed))

    thr = crypto15m._const(cfg, "entry_threshold")
    base = (1.0 - thr) if (cfg.get("crypto15m_direction_mode") == "contrarian") else thr
    if (cfg.get("crypto15m_entry_style") or "maker") == "maker":
        est_price_cents = max(1, min(99, int(round(base * 100)) - 1))
    else:
        est_price_cents = entry_limit_cents(base, crypto15m._const(cfg, "entry_diff"))
    streak_mult = streak_multiplier(cfg, trader.get_env())
    est_contracts = compute_entry_contracts(
        cfg, entry_limit_cents=est_price_cents, balance_usd=bal, order_size=order_size,
        streak_mult=streak_mult,
    )
    est_cost = est_contracts * est_price_cents / 100.0

    note = ""
    if mode == "balance_pct" and bal <= 0:
        note = "No balance yet — using fixed order size. Connect Polymarket or set a start bankroll to size by %."
    elif max_loss_pct > 0 and bal > 0 and est_contracts < 1:
        note = f"Max-loss budget too small to fund a contract at ~{est_price_cents}c."

    return {
        "mode": mode,
        "balancePct": balance_pct,
        "maxLossPct": max_loss_pct,
        "balanceUsd": bal,
        "estPriceCents": est_price_cents,
        "estContracts": est_contracts,
        "estCostUsd": est_cost,
        "streakMult": streak_mult,
        "note": note,
    }


async def status(cfg: dict, *, authed: bool = False) -> dict:
    env = trader.get_env()
    with db.get_db() as conn:
        open_rows = db.get_open_crypto15m(conn, env)
        recent = db.recent_crypto15m(conn, env, limit=40)
        stats = db.crypto15m_stats(conn, env)
        by_strategy = db.crypto15m_strategy_stats(conn, env)
    p_armed, p_sched = parlay_state()
    parlay_js = {"armed": p_armed, "hasSchedule": bool(p_sched)}
    if p_sched:
        try:
            parlay_js["hours"] = sorted(
                int(h) for h in (p_sched.get("hour_configs") or {})
            )
        except (TypeError, ValueError):
            parlay_js["hours"] = []
        parlay_js["generatedAt"] = p_sched.get("generated_at")
    return {
        "enabled": bool(cfg.get("crypto15m_enabled")),
        "trading": bool(cfg.get("crypto15m_enabled")) and bool(authed),
        "authed": bool(authed),
        "parlay": parlay_js,
        "haltReason": _halt_reason,
        "blockReasons": dict(_block_reasons),
        "byStrategy": by_strategy,
        "modelCalibration": dict(_CAL_CACHE),
        "orderSize": int(cfg.get("crypto15m_order_size", 1)),
        "maxConcurrent": int(cfg.get("crypto15m_max_concurrent", len(crypto15m.SERIES))),
        "sizing": await _sizing_preview(cfg, authed),
        "env": env,
        "stats": stats,
        "open": [_pos_to_js(r) for r in open_rows],
        "recent": [_pos_to_js(r) for r in recent],
    }
