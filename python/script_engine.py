from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Callable, Optional

from datetime import datetime, timezone

import categorize
import crypto15m
import crypto15m_trader
import db
import polymarket_api
import polymarket_auth
import script_sandbox
import trader
from script_backtest import (
    market_to_js, parse_asset_scope, sanitize_intent, sanitize_manage,
    sanitize_market_intent, sanitize_signal_action, script_allows_asset,
    signal_to_js,
)

logger = logging.getLogger("rom.script_engine")

_SUPERVISE_KEYS: dict[str, str] = {
    "enable_trading": "bool",
    "trade_whales": "bool",
    "trade_momentum": "bool",
    "crypto15m_enabled": "bool",
    "copy_enabled": "bool",
    "crypto15m_direction_mode": "mode",
    "crypto15m_entry_threshold": "float",
    "crypto15m_entry_max": "float",
    "crypto15m_min_delta_pct": "float",
    "crypto15m_time_delay_min": "float",
}
_SUPERVISE_MIN_INTERVAL_S = 30.0
_last_patch_t: dict[str, float] = {}

_sig_marks: dict[str, Optional[int]] = {"whale": None, "momentum": None}

HOOK_TIMEOUT_S = 1.0
COMPILE_TIMEOUT_S = 4.0
MARKET_SCAN_BUDGET_S = 2.0
STATE_SAVE_EVERY_S = 60.0
STATE_MAX_BYTES = 64 * 1024

HEARTBEAT_SEC = 60.0
_hb: dict[str, dict[str, int]] = {}
_hb_last: dict[str, float] = {}

_compiled: dict[str, script_sandbox.CompiledScript] = {}
_notified_fill: set[str] = set()
_notified_settle: set[str] = set()
_state_oversize_warned: set[str] = set()
_last_starved: list[str] = []
_last_state_save = 0.0

_status: dict[str, dict] = {}
_enabled_hooks: set[str] = set()
_enabled_hooks_at = 0.0
_HOOKS_TTL_S = 120.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stat(sid: str) -> dict:
    return _status.setdefault(sid, {
        "ticks": 0, "intents": 0, "orders": 0,
        "lastTickAt": None, "lastIntentAt": None, "lastOrderAt": None,
        "gate": None,
    })


def _gate(sid: str, reason: Optional[str]) -> None:
    _stat(sid)["gate"] = reason


def status_for(sid: str) -> dict:
    return dict(_status.get(sid) or _stat(sid))


def needs_signal_feed() -> bool:
    if not _enabled_hooks or time.time() - _enabled_hooks_at > _HOOKS_TTL_S:
        return False
    return "decide_signal" in _enabled_hooks


_emit: Optional[Callable] = None


def set_event_callback(cb: Callable) -> None:
    global _emit
    _emit = cb


async def _emit_event(name: str, data: Any) -> None:
    if _emit is None:
        return
    try:
        await _emit(name, data)
    except Exception:
        pass


def _disable(sid: str, reason: str) -> None:
    try:
        with db.get_db() as conn:
            db.update_user_script(conn, sid, enabled=0, last_error=reason[:500])
        logger.warning(f"[scripts] disabled {sid[:8]}: {reason}")
    except Exception as e:
        logger.error(f"[scripts] failed to persist disable for {sid[:8]}: {e}")


def _get_compiled(row: dict, cfg: dict) -> Optional[script_sandbox.CompiledScript]:
    sid = str(row["id"])
    want = script_sandbox.code_hash(str(row.get("code") or ""))
    cur = _compiled.get(sid)
    if cur is not None and cur.hash == want:
        return cur
    saved_state: dict = {}
    try:
        saved_state = json.loads(row.get("state_json") or "{}")
        if not isinstance(saved_state, dict):
            saved_state = {}
    except Exception:
        saved_state = {}
    try:
        mod = _run_bounded(
            lambda: script_sandbox.CompiledScript(
                sid, str(row.get("code") or ""), state=saved_state),
            _compile_timeout(cfg), f"script-{sid[:8]}-compile")
        _call_hook(mod, "on_start", cfg, mod.state)
    except (Exception, script_sandbox.ScriptBudgetExceeded) as e:
        _compiled.pop(sid, None)
        _disable(sid, f"compile/on_start failed: {e}")
        return None
    _compiled[sid] = mod
    return mod


def _run_bounded(fn: Callable[[], Any], timeout_s: float, name: str) -> Any:
    import threading
    result: dict[str, Any] = {}

    def _run() -> None:
        try:
            result["value"] = fn()
        except BaseException as e:  # noqa: BLE001 — ScriptError/Budget/anything
            result["error"] = e

    t = threading.Thread(target=_run, daemon=True, name=name)
    t.start()
    t.join(timeout_s)
    if t.is_alive():
        raise script_sandbox.ScriptBudgetExceeded(
            f"{name} still running after {timeout_s:.2f}s (thread abandoned)")
    if "error" in result:
        raise result["error"]
    return result.get("value")


def _hook_timeout(cfg: dict) -> float:
    try:
        return max(0.05, min(30.0, float(cfg.get("script_hook_timeout_sec")
                                         or HOOK_TIMEOUT_S)))
    except (TypeError, ValueError):
        return HOOK_TIMEOUT_S


def _compile_timeout(cfg: dict) -> float:
    return max(COMPILE_TIMEOUT_S, _hook_timeout(cfg) * 4.0)


def _call_hook(mod: script_sandbox.CompiledScript, hook: str, cfg: dict,
               *args: Any) -> Any:
    return _run_bounded(
        lambda: mod.call(hook, *args),
        _hook_timeout(cfg), f"script-{mod.script_id[:8]}-{hook}")


def _script_daily_pnl(conn, sid: str, env: str) -> float:
    total = 0.0
    for table, stamp in (("crypto15m_positions", "COALESCE(resolved_at, last_updated)"),
                         ("bot_positions", "COALESCE(resolved_at, last_updated)")):
        try:
            row = conn.execute(
                f"""SELECT COALESCE(SUM(pnl_usd), 0) FROM {table}
                    WHERE script_id=? AND network=? AND resolved=1
                      AND date({stamp}) = date('now')""",
                (sid, env),
            ).fetchone()
            total += float(row[0] or 0.0)
        except Exception:
            pass
    return total


def _count_open_for_script(conn, sid: str, env: str) -> int:
    n = 0
    for table in ("crypto15m_positions", "bot_positions"):
        try:
            n += conn.execute(
                f"""SELECT COUNT(*) FROM {table}
                    WHERE script_id=? AND network=? AND resolved=0""",
                (sid, env),
            ).fetchone()[0]
        except Exception:
            pass
    return n


def _open_crypto_for_script(conn, sid: str, env: str) -> list[dict]:
    rows = conn.execute(
        """SELECT * FROM crypto15m_positions
           WHERE script_id=? AND network=? AND resolved=0""",
        (sid, env),
    ).fetchall()
    return [dict(r) for r in rows]


def _already_attempted(conn, sid: str, ticker: str, *,
                       shadow: bool = False) -> bool:
    if shadow:
        return db.shadow_already_attempted(conn, sid, ticker)
    return conn.execute(
        "SELECT 1 FROM crypto15m_positions WHERE script_id=? AND ticker=? LIMIT 1",
        (sid, ticker),
    ).fetchone() is not None


def _shadow_fee(cost: float, created_at: str | None) -> float:
    """US taker fee for a shadow fill, priced at the schedule in force then.

    Previously this used the legacy per-category table, which charged crypto
    0.07 and geopolitics nothing at all. Rows settled under that table were
    restated once by `db._restate_shadow_pnl_on_us_fees`, so a script's
    practice record is priced on one schedule throughout.
    """
    import backtest as bt
    return bt.us_fee_per_contract(cost, bt.epoch_of(created_at))


async def _settle_shadow_orders() -> None:
    try:
        with db.get_db() as conn:
            pending = [str(r[0]) for r in conn.execute(
                """SELECT DISTINCT ticker FROM script_shadow_orders
                   WHERE resolved=0 AND contracts > 0
                     AND signal_source='market' AND ticker IS NOT NULL
                     AND close_time != ''
                     AND close_time < strftime('%Y-%m-%dT%H:%M:%SZ','now')
                   LIMIT 60""").fetchall()]
        results: dict[str, str] = {}
        if pending:
            markets = await polymarket_api.fetch_markets_map(pending)
            for tk, m in (markets or {}).items():
                status = str((m or {}).get("status") or "").lower()
                res = str((m or {}).get("result") or "").lower()
                if status in ("determined", "finalized", "settled") and res in ("yes", "no"):
                    results[str(tk)] = res
        with db.get_db() as conn:
            n = db.resolve_script_shadow(conn, _shadow_fee, market_results=results)
        if n:
            logger.info(f"[scripts] settled {n} shadow order(s)")
    except Exception as e:
        logger.debug(f"[scripts] shadow settle: {e}")


def _record_refusal(sid: str, a: dict, side: str, env: str, reason: str,
                    *, shadow: bool = False) -> None:
    if shadow:
        with db.get_db() as conn:
            db.insert_script_shadow(conn, {
                "script_id": sid, "source": "crypto", "asset": a.get("asset"),
                "ticker": a.get("ticker"), "side": side, "contracts": 0,
                "entry_cents": 0, "refused": 1, "note": reason[:300],
                "close_time": a.get("closeTime") or "", "network": env,
            })
        return
    with db.get_db() as conn:
        pid = db.insert_crypto15m_position(conn, {
            "asset": a["asset"], "series": a.get("series") or "",
            "ticker": a["ticker"], "side": side,
            "direction": crypto15m_trader.direction_for_favorite(side),
            "target_contracts": 0, "entry_limit_cents": 1,
            "client_order_id": f"rom-scr-{uuid.uuid4().hex[:12]}",
            "close_time": a.get("closeTime") or "", "confidence": 0.0,
            "network": env, "status": "canceled", "dry_run": 0,
            "error": reason, "strategy": f"script:{sid[:8]}",
            "script_id": sid,
        })
        crypto15m_trader._mark_resolved(conn, pid, status="canceled",
                                        exit_reason="script_refused")


_CASH_BUFFER_USD = 0.25


def _notional_capped(contracts: int, limit_cents: int, ask_cents: int,
                     size_cap: int) -> int:
    if ask_cents <= 0 or limit_cents <= 0 or contracts <= 0:
        return contracts
    affordable = (size_cap * ask_cents) // limit_cents
    return max(1, min(contracts, int(affordable)))


async def _place_intent(s: dict, a: dict, intent: dict, cfg: dict,
                        env: str, balance_usd: Optional[float] = None) -> Optional[dict]:
    sid = str(s["id"])
    shadow = bool(s.get("dry_run"))
    side = intent["side"]
    direction = crypto15m_trader.direction_for_favorite(side)
    ticker = a.get("ticker")
    max_cents = int(cfg.get("script_max_entry_cents") or 97)

    if intent["price"] == "ask":
        ask = None
        try:
            q = await polymarket_api.get_quote(ticker, direction)
            qa = q.get("ask_cents")
            if qa and 1 <= int(qa) <= 99:
                ask = int(qa) / 100.0
        except Exception as e:
            logger.debug(f"[scripts] entry re-quote {ticker}: {e}")
        if ask is None:
            snap_ask = a.get("upAsk") if side == "up" else a.get("downAsk")
            if not (shadow and snap_ask and 0.0 < float(snap_ask) < 1.0):
                return None
            ask = float(snap_ask)
        limit_cents = min(max_cents + 1, int(round(float(ask) * 100)) + 1)
        order_type = "FAK"
        ask_cents = max(1, int(round(float(ask) * 100)))
    else:
        limit_cents = int(intent["price"])
        order_type = "GTC"
        ask_cents = limit_cents

    if limit_cents > max_cents:
        _record_refusal(sid, a, side, env,
                        f"entry {limit_cents}c > script_max_entry_cents {max_cents}c", shadow=shadow)
        return None

    size_cap = max(1, int(cfg.get("script_max_contracts") or 20))
    contracts = min(
        int(intent.get("size") or max(1, int(cfg.get("crypto15m_order_size", 1)))),
        size_cap,
    )
    floor = crypto15m_trader._C15_MIN_CONTRACTS
    if floor > size_cap:
        _record_refusal(sid, a, side, env,
                        f"exchange minimum {floor} contracts > "
                        f"script_max_contracts {size_cap}", shadow=shadow)
        return None
    if contracts < floor:
        contracts = floor
    if not crypto15m_trader._min_notional_ok(contracts, limit_cents):
        needed = int(-(-100 // max(1, limit_cents)))
        if needed > size_cap:
            _record_refusal(sid, a, side, env,
                            f"${1} min-notional needs {needed} contracts at "
                            f"{limit_cents}c > script_max_contracts {size_cap}", shadow=shadow)
            return None
        contracts = max(contracts, needed)

    contracts = _notional_capped(contracts, limit_cents, ask_cents, size_cap)

    cost = contracts * limit_cents / 100.0
    if (not shadow and balance_usd is not None
            and cost > balance_usd - _CASH_BUFFER_USD):
        _record_refusal(
            sid, a, side, env,
            f"needs ${cost:.2f} but the balance is ${balance_usd:.2f} "
            f"(keeping ${_CASH_BUFFER_USD:.2f} for fees)", shadow=shadow)
        return None

    if shadow:
        with db.get_db() as conn:
            shid = db.insert_script_shadow(conn, {
                "script_id": sid, "source": "crypto", "asset": a.get("asset"),
                "ticker": ticker, "side": side, "contracts": contracts,
                "entry_cents": limit_cents, "order_type": order_type,
                "reason": str(intent.get("reason") or "")[:200],
                "tp_pct": intent.get("take_profit_pct"),
                "sl_cents": intent.get("stop_loss_cents"),
                "close_time": a.get("closeTime") or "", "network": env,
            })
        logger.info(
            f"[scripts] {sid[:8]} SHADOW entry {a['asset']} {direction} "
            f"x{contracts} @ {limit_cents}c "
            f"({intent.get('reason') or 'no reason'})")
        return {"id": shid, "shadow": True, "ticker": ticker,
                "asset": a.get("asset"), "side": side,
                "target_contracts": contracts}

    coid = f"rom-scr-{a['asset']}-{uuid.uuid4().hex[:8]}"
    row = {
        "asset": a["asset"], "series": a.get("series") or "",
        "ticker": ticker, "side": side, "direction": direction,
        "target_contracts": contracts, "entry_limit_cents": limit_cents,
        "client_order_id": coid, "close_time": a.get("closeTime") or "",
        "confidence": float(a.get("favoritePrice") or 0.0) * 100.0,
        "network": env, "strategy": f"script:{sid[:8]}", "script_id": sid,
        "tp_pct": intent.get("take_profit_pct"),
        "sl_cents": intent.get("stop_loss_cents"),
    }
    try:
        resp = await polymarket_api.place_limit_order(
            ticker=ticker, side=direction, action="buy",
            count=contracts, price_cents=limit_cents,
            client_order_id=coid, order_type=order_type,
        )
    except Exception as e:
        row.update({"status": "error", "error": str(e)[:200], "dry_run": 0})
        with db.get_db() as conn:
            pid = db.insert_crypto15m_position(conn, row)
            crypto15m_trader._mark_resolved(conn, pid, status="error")
        logger.error(f"[scripts] {sid[:8]} entry failed {a['asset']}: {e}")
        return None

    order = (resp.get("order") if isinstance(resp, dict) else None) or resp or {}
    oid = order.get("order_id") if isinstance(order, dict) else None
    ostatus = ((order.get("status") if isinstance(order, dict) else "") or "").lower()
    if not oid and ostatus in ("unmatched", "killed"):
        _record_refusal(sid, a, side, env, "FAK crossed no liquidity (0 fill)")
        return None
    if not oid:
        row.update({"status": "error", "error": "no order_id from exchange",
                    "dry_run": 0})
        with db.get_db() as conn:
            pid = db.insert_crypto15m_position(conn, row)
            crypto15m_trader._mark_resolved(conn, pid, status="error")
        return None
    row.update({"status": "submitted", "order_id": oid, "dry_run": 0})
    with db.get_db() as conn:
        pid = db.insert_crypto15m_position(conn, row)
        logger.info(
            f"[scripts] {sid[:8]} entry {a['asset']} {direction} "
            f"x{contracts} @ {limit_cents}c ({intent.get('reason') or 'no reason'})"
        )
        return db.fetch_crypto15m_by_id(conn, pid)


def _pos_lite(r: dict) -> dict:
    avg = r.get("avg_entry_cents")
    if avg is None:
        avg = r.get("avg_fill_price_cents")
    return {
        "id": r.get("id"), "ticker": r.get("ticker"), "asset": r.get("asset"),
        "side": r.get("side") or r.get("direction"),
        "contracts": r.get("filled_contracts") or 0,
        "avgEntryCents": avg,
        "status": r.get("status"), "pnlUsd": r.get("pnl_usd"),
        "exitReason": r.get("exit_reason"), "won": r.get("outcome_correct"),
    }


def _snake_to_camel(k: str) -> str:
    parts = k.split("_")
    return parts[0] + "".join(p.title() for p in parts[1:])


def _sanitize_supervise(raw) -> tuple[dict, list[str]]:
    if raw is None:
        return {}, []
    if not isinstance(raw, dict) or not isinstance(raw.get("set"), dict):
        return {}, ["supervise() must return None or {\"set\": {key: value}}"]
    patch: dict = {}
    notes: list[str] = []
    for k, v in raw["set"].items():
        kind = _SUPERVISE_KEYS.get(str(k))
        if kind is None:
            notes.append(f"key '{k}' is not supervisable (ignored)")
            continue
        try:
            if kind == "bool":
                if bool(v):
                    notes.append(f"'{k}': scripts may turn engines off, not on "
                                 "(ignored)")
                    continue
                patch[str(k)] = False
            elif kind == "float":
                fv = float(v)
                if fv != fv or fv in (float("inf"), float("-inf")):
                    notes.append(f"'{k}': non-finite value (ignored)")
                    continue
                patch[str(k)] = fv
            elif kind == "mode":
                mv = str(v).lower()
                if mv not in ("favorite", "contrarian", "model"):
                    notes.append(f"'{k}' must be favorite|contrarian|model (ignored)")
                    continue
                patch[str(k)] = mv
        except (TypeError, ValueError):
            notes.append(f"'{k}' got a non-{kind} value (ignored)")
    return patch, notes


async def _run_supervise(s: dict, mod: script_sandbox.CompiledScript,
                         cfg: dict, app: dict, *, shadow: bool = False) -> None:
    sid = str(s["id"])
    if shadow:
        _hb_note(sid, "supervise_skipped_shadow")
        return
    raw = _call_hook(mod, "supervise", cfg, dict(app))
    patch, notes = _sanitize_supervise(raw)
    for n in notes:
        logger.info(f"[scripts] {sid[:8]} supervise: {n}")
    if not patch:
        return
    patch = {k: v for k, v in patch.items() if cfg.get(k) != v}
    if not patch:
        return
    if time.time() - _last_patch_t.get(sid, 0.0) < _SUPERVISE_MIN_INTERVAL_S:
        return
    _last_patch_t[sid] = time.time()
    camel = {_snake_to_camel(k): v for k, v in patch.items()}
    logger.warning(
        f"[scripts] {s.get('name')} ({sid[:8]}) SUPERVISOR config change: {patch}"
    )
    await _emit_event("script:configPatch", {
        "id": sid, "name": s.get("name"), "patch": camel,
    })


async def _manage_pass(s: dict, mod: script_sandbox.CompiledScript, cfg: dict,
                       env: str, assets_by_ticker: dict, portfolio: dict) -> None:
    sid = str(s["id"])
    with db.get_db() as conn:
        rows = _open_crypto_for_script(conn, sid, env)
    for pos in rows:
        if pos.get("status") != "filled" or int(pos.get("filled_contracts") or 0) <= 0:
            continue
        a = assets_by_ticker.get(str(pos.get("ticker")))
        ctx = dict(a) if a else {
            "ticker": pos.get("ticker"), "asset": pos.get("asset"),
            "hasMarket": False, "minsLeft": None,
        }
        ctx["portfolio"] = portfolio
        bid_cents = None
        if a:
            if pos.get("side") == "up":
                yb = a.get("yesBid")
                bid_cents = round(float(yb) * 100, 1) if yb else None
            else:
                ya = a.get("yesAsk")
                bid_cents = round((1.0 - float(ya)) * 100, 1) if ya else None
        entry_c = float(pos.get("avg_entry_cents") or pos.get("entry_limit_cents") or 0)
        pos_lite = {
            "ticker": pos.get("ticker"), "asset": pos.get("asset"),
            "side": pos.get("side"),
            "contracts": int(pos.get("filled_contracts") or 0),
            "avgEntryCents": entry_c, "curBidCents": bid_cents,
            "minsLeft": ctx.get("minsLeft"),
            "tpPct": pos.get("tp_pct"), "slCents": pos.get("sl_cents"),
            "unrealizedPct": round((bid_cents - entry_c) / entry_c, 4)
            if bid_cents is not None and entry_c > 0 else None,
        }
        _hb_note(sid, "manage")
        act_raw = _call_hook(mod, "manage", cfg, pos_lite, ctx)
        act, err = sanitize_manage(act_raw)
        if err:
            raise script_sandbox.ScriptError(f"manage(): {err}")
        if act is None:
            continue
        _hb_note(sid, "manage_intents")
        if act["action"] == "sell":
            exit_cents = await crypto15m_trader._best_bid_cents(
                pos.get("ticker"), pos.get("direction"))
            if exit_cents is None and bid_cents is not None:
                exit_cents = int(bid_cents)
            if exit_cents is None:
                logger.info(f"[scripts] {sid[:8]} manage sell {pos.get('asset')}: "
                            "no bid anywhere — retry next tick")
                continue
            await crypto15m_trader._place_exit_sell(
                pos, cfg, exit_cents=int(exit_cents), reason="script_exit")
        else:
            fields = {}
            if "take_profit_pct" in act:
                fields["tp_pct"] = act["take_profit_pct"] or None
            if "stop_loss_cents" in act:
                fields["sl_cents"] = act["stop_loss_cents"] or None
            if fields:
                with db.get_db() as conn:
                    db.update_crypto15m_position(conn, int(pos["id"]), **fields)


def _fetch_new_signals(env: str) -> list[tuple[dict, str]]:
    out: list[tuple[dict, str]] = []
    try:
        with db.get_db() as conn:
            for table, source in (("whale_trades", "whale"), ("alerts", "momentum")):
                mark = _sig_marks[source]
                if mark is None:
                    row = conn.execute(f"SELECT MAX(id) FROM {table}").fetchone()
                    _sig_marks[source] = int(row[0] or 0)
                    continue
                rows = conn.execute(
                    f"""SELECT * FROM {table} WHERE id > ?
                        ORDER BY id ASC LIMIT 50""",
                    (mark,),
                ).fetchall()
                for r in rows:
                    d = dict(r)
                    _sig_marks[source] = max(_sig_marks[source] or 0, int(d["id"]))
                    out.append((d, source))
    except Exception as e:
        logger.debug(f"[scripts] signal fetch: {e}")
    return out


async def _place_signal_follow(s: dict, sig: dict, source: str, act: dict,
                               cfg: dict, env: str,
                               balance_usd: Optional[float] = None) -> Optional[dict]:
    sid = str(s["id"])
    ticker = str(sig.get("ticker") or "")
    direction = str(sig.get("taker_side") or sig.get("direction") or "").lower()
    if not ticker or direction not in ("yes", "no"):
        return None
    max_cents = int(cfg.get("script_max_entry_cents") or 97)
    ask = None
    try:
        q = await polymarket_api.get_quote(ticker, direction)
        ask = q.get("ask_cents")
    except Exception as e:
        logger.debug(f"[scripts] signal quote {ticker}: {e}")
    if not ask or not (1 <= int(ask) <= 99):
        return None
    limit_cents = int(ask)
    if limit_cents > max_cents:
        return None
    spend = float(act.get("sizeUsd") or cfg.get("fixed_trade_usd") or 5.0)
    size_cap = max(1, int(cfg.get("script_max_contracts") or 20))
    floor = crypto15m_trader._C15_MIN_CONTRACTS
    if floor > size_cap:
        logger.info(
            f"[scripts] {sid[:8]} skips {source} signal {ticker}: exchange "
            f"minimum {floor} contracts > script_max_contracts {size_cap}")
        return None
    contracts = int(spend // (limit_cents / 100.0))
    contracts = min(max(contracts, floor), size_cap)
    contracts = _notional_capped(contracts, limit_cents, int(ask), size_cap)

    cost = contracts * limit_cents / 100.0
    if (not bool(s.get("dry_run")) and balance_usd is not None
            and cost > balance_usd - _CASH_BUFFER_USD):
        logger.info(
            f"[scripts] {sid[:8]} skips {source} signal {ticker}: needs "
            f"${cost:.2f} but the balance is ${balance_usd:.2f}")
        return None

    if bool(s.get("dry_run")):
        with db.get_db() as conn:
            shid = db.insert_script_shadow(conn, {
                "script_id": sid, "source": "signal", "signal_source": source,
                "signal_id": int(sig.get("id") or 0),
                "asset": sig.get("category") or source, "ticker": ticker,
                "side": direction, "contracts": contracts,
                "entry_cents": limit_cents, "order_type": "GTC",
                "reason": str(sig.get("title") or "")[:200], "network": env,
            })
        logger.info(
            f"[scripts] {sid[:8]} SHADOW follows {source} signal: {ticker} "
            f"{direction} x{contracts} @ {limit_cents}c")
        return {"id": shid, "shadow": True, "ticker": ticker,
                "direction": direction, "target_contracts": contracts}

    coid = f"rom-scrs-{uuid.uuid4().hex[:10]}"
    row = {
        "signal_source": f"script:{sid[:8]}:{source}",
        "signal_id": int(sig.get("id") or 0),
        "ticker": ticker, "event_ticker": sig.get("event_ticker") or "",
        "title": sig.get("title") or ticker,
        "category": sig.get("category") or "",
        "direction": direction, "action": "buy",
        "target_contracts": contracts, "limit_price_cents": limit_cents,
        "client_order_id": coid, "confidence": 0.0, "edge_pts": 0.0,
        "signal_price": float(limit_cents), "network": env,
        "script_id": sid,
    }
    try:
        resp = await polymarket_api.place_limit_order(
            ticker=ticker, side=direction, action="buy",
            count=contracts, price_cents=limit_cents, client_order_id=coid,
        )
    except Exception as e:
        logger.error(f"[scripts] {sid[:8]} signal follow {ticker} failed: {e}")
        return None
    order = (resp.get("order") if isinstance(resp, dict) else None) or resp or {}
    oid = order.get("order_id") if isinstance(order, dict) else None
    if not oid:
        return None
    row.update({"status": "submitted", "order_id": oid})
    try:
        with db.get_db() as conn:
            pid = db.insert_bot_position(conn, row)
            logger.info(
                f"[scripts] {sid[:8]} follows {source} signal: {ticker} "
                f"{direction} x{contracts} @ {limit_cents}c"
            )
            return db.fetch_position_by_id(conn, pid)
    except Exception as e:
        logger.critical(
            f"[scripts] {sid[:8]} signal order {oid} PLACED but not recorded "
            f"({ticker} {direction} x{contracts} @ {limit_cents}c): {e}"
        )
        return None


_SOON_HOURS = 48


def _market_universe(cfg: dict) -> list[dict]:
    limit = int(cfg.get("script_market_limit") or 0)
    if limit <= 0:
        return []
    min_vol = float(cfg.get("script_market_min_volume") or 0.0)
    live = """SELECT * FROM markets
              WHERE status IN ('active','open') AND volume_24h >= ?
                AND (close_time = ''
                     OR close_time > strftime('%Y-%m-%dT%H:%M:%SZ', 'now')) """
    soon_budget = limit // 2
    try:
        with db.get_db() as conn:
            busiest = [dict(r) for r in conn.execute(
                live + "ORDER BY volume_24h DESC LIMIT ?",
                (min_vol, max(limit * 4, 50)),
            ).fetchall()]
            closing = [dict(r) for r in conn.execute(
                live + """AND close_time != ''
                          AND close_time <= strftime('%Y-%m-%dT%H:%M:%SZ',
                                                     'now', ?)
                          ORDER BY volume_24h DESC LIMIT ?""",
                (min_vol, f"+{_SOON_HOURS} hours", max(soon_budget * 4, 50)),
            ).fetchall()] if soon_budget else []
    except Exception as e:
        logger.debug(f"[scripts] market universe: {e}")
        return []

    out: list[dict] = []
    seen: set[str] = set()

    def _take(rows: list[dict], upto: int) -> None:
        for r in rows:
            if len(out) >= upto:
                return
            ticker = str(r.get("ticker") or "")
            if ticker in seen:
                continue
            if categorize.is_micro_market(r.get("slug") or ""):
                continue
            seen.add(ticker)
            out.append(r)

    _take(closing, soon_budget)
    _take(busiest, limit)
    return out


_market_cooldown: dict[tuple[str, str], float] = {}
MARKET_REFUSAL_COOLDOWN_S = 600.0


def _cool_off(sid: str, ticker: str, reason: str) -> None:
    _market_cooldown[(sid, ticker)] = time.time() + MARKET_REFUSAL_COOLDOWN_S
    logger.info(
        f"[scripts] {sid[:8]} refuses market {ticker}: {reason} — not "
        f"reconsidered for {MARKET_REFUSAL_COOLDOWN_S / 60:.0f}m")


def _fail_market_entry(sid: str, ticker: str, row: dict, err: str,
                       env: str) -> None:
    _market_cooldown[(sid, ticker)] = time.time() + MARKET_REFUSAL_COOLDOWN_S
    logger.error(f"[scripts] {sid[:8]} market entry {ticker} failed: {err}")
    try:
        with db.get_db() as conn:
            pid = db.insert_bot_position(
                conn, {**row, "status": "error", "error": err[:200]})
            db.log_event(conn, pid, "error", note=err[:200])
    except Exception as e:  # noqa: BLE001 — never let bookkeeping raise into the loop
        logger.error(f"[scripts] {sid[:8]} could not record {ticker} failure: {e}")


def _in_cooldown(sid: str, ticker: str) -> bool:
    until = _market_cooldown.get((sid, ticker))
    if until is None:
        return False
    if time.time() >= until:
        del _market_cooldown[(sid, ticker)]
        return False
    return True


def _market_already_attempted(conn, sid: str, ticker: str, *,
                              shadow: bool = False) -> bool:
    if shadow:
        return db.shadow_already_attempted(conn, sid, ticker)
    return conn.execute(
        """SELECT 1 FROM bot_positions
           WHERE script_id=? AND ticker=? LIMIT 1""",
        (sid, ticker),
    ).fetchone() is not None


async def _place_market_intent(s: dict, m: dict, intent: dict, cfg: dict,
                               env: str,
                               balance_usd: Optional[float] = None) -> Optional[dict]:
    sid = str(s["id"])
    shadow = bool(s.get("dry_run"))
    ticker = str(m.get("ticker") or "")
    side = intent["side"]
    if not ticker:
        return None
    max_cents = int(cfg.get("script_max_entry_cents") or 97)
    size_cap = max(1, int(cfg.get("script_max_contracts") or 20))
    floor = crypto15m_trader._C15_MIN_CONTRACTS
    if floor > size_cap:
        _cool_off(sid, ticker, f"exchange minimum {floor} contracts > "
                               f"script_max_contracts {size_cap}")
        return None

    if intent["price"] == "ask":
        try:
            q = await polymarket_api.get_quote(ticker, side)
            ask = q.get("ask_cents")
            bid = q.get("bid_cents")
        except Exception as e:
            logger.debug(f"[scripts] market quote {ticker}: {e}")
            return None
        if not ask or not (1 <= int(ask) <= 99):
            return None
        max_spread = float(cfg.get("script_market_max_spread_cents") or 0.0)
        if max_spread > 0 and bid:
            spread = int(ask) - int(bid)
            if spread > max_spread:
                _cool_off(sid, ticker,
                          f"spread {spread}c > script_market_max_spread_cents "
                          f"{max_spread:g}c")
                return None
        limit_cents = int(ask)
        ask_cents = int(ask)
    else:
        limit_cents = int(intent["price"])
        ask_cents = limit_cents
    if limit_cents > max_cents:
        _cool_off(sid, ticker, f"entry {limit_cents}c > "
                               f"script_max_entry_cents {max_cents}c")
        return None

    if intent.get("size") is not None:
        contracts = int(intent["size"])
    else:
        spend = float(intent.get("sizeUsd") or cfg.get("fixed_trade_usd") or 5.0)
        contracts = int(spend // (limit_cents / 100.0))
    contracts = min(max(contracts, floor), size_cap)
    if (contracts * limit_cents) / 100.0 < crypto15m_trader._MIN_ORDER_NOTIONAL_USD:
        needed = int(-(-100 // max(1, limit_cents)))
        if needed > size_cap:
            _cool_off(sid, ticker,
                      f"$1 min-notional needs {needed} contracts > "
                      f"script_max_contracts {size_cap}")
            return None
        contracts = max(contracts, needed)

    contracts = _notional_capped(contracts, limit_cents, ask_cents, size_cap)

    cost = contracts * limit_cents / 100.0
    if (not shadow and balance_usd is not None
            and cost > balance_usd - _CASH_BUFFER_USD):
        _cool_off(sid, ticker,
                  f"needs ${cost:.2f} but the balance is ${balance_usd:.2f}")
        return None

    if shadow:
        with db.get_db() as conn:
            shid = db.insert_script_shadow(conn, {
                "script_id": sid, "source": "signal",
                "signal_source": "market", "signal_id": None,
                "asset": m.get("category") or "", "ticker": ticker,
                "side": side, "contracts": contracts,
                "entry_cents": limit_cents, "order_type": "GTC",
                "reason": str(intent.get("reason") or "")[:200],
                "close_time": m.get("close_time") or "", "network": env,
            })
        logger.info(
            f"[scripts] {sid[:8]} SHADOW market entry {ticker} {side} "
            f"x{contracts} @ {limit_cents}c "
            f"({intent.get('reason') or 'no reason'})")
        return {"id": shid, "shadow": True, "ticker": ticker, "side": side,
                "target_contracts": contracts}

    coid = f"rom-scrm-{uuid.uuid4().hex[:10]}"
    row = {
        "signal_source": f"script:{sid[:8]}:market",
        "signal_id": abs(hash(ticker)) % (10 ** 9),
        "ticker": ticker, "event_ticker": m.get("event_ticker") or "",
        "title": m.get("title") or ticker,
        "category": m.get("category") or "",
        "direction": side, "action": "buy",
        "target_contracts": contracts, "limit_price_cents": limit_cents,
        "client_order_id": coid, "confidence": 0.0, "edge_pts": 0.0,
        "signal_price": float(limit_cents), "network": env,
        "script_id": sid,
    }
    try:
        resp = await polymarket_api.place_limit_order(
            ticker=ticker, side=side, action="buy",
            count=contracts, price_cents=limit_cents, client_order_id=coid,
        )
    except Exception as e:
        _fail_market_entry(sid, ticker, row, f"{type(e).__name__}: {e}", env)
        return None
    order = (resp.get("order") if isinstance(resp, dict) else None) or resp or {}
    oid = order.get("order_id") if isinstance(order, dict) else None
    if not oid:
        _fail_market_entry(sid, ticker, row, "no order_id from exchange", env)
        return None
    row.update({"status": "submitted", "order_id": oid})
    try:
        with db.get_db() as conn:
            pid = db.insert_bot_position(conn, row)
            logger.info(
                f"[scripts] {sid[:8]} market entry {ticker} {side} "
                f"x{contracts} @ {limit_cents}c "
                f"({intent.get('reason') or 'no reason'})")
            return db.fetch_position_by_id(conn, pid)
    except Exception as e:
        logger.critical(
            f"[scripts] {sid[:8]} market order {oid} PLACED but not recorded "
            f"({ticker} {side} x{contracts} @ {limit_cents}c): {e}")
        return None


async def _notify_lifecycle(scripts_by_id: dict[str, dict], env: str,
                            cfg: dict) -> None:
    rows: list[tuple[str, dict]] = []
    for table, tag in (("crypto15m_positions", "c"), ("bot_positions", "b")):
        try:
            with db.get_db() as conn:
                found = conn.execute(
                    f"""SELECT * FROM {table}
                       WHERE script_id IS NOT NULL AND network=?
                         AND (
                           (resolved=0 AND filled_contracts > 0)
                           OR (resolved=1 AND datetime(COALESCE(resolved_at, last_updated))
                               >= datetime('now', '-1 hour'))
                         )""",
                    (env,),
                ).fetchall()
            rows.extend((tag, dict(r)) for r in found)
        except Exception as e:
            logger.debug(f"[scripts] lifecycle scan {table}: {e}")
    for tag, r in rows:
        sid = str(r.get("script_id") or "")
        s = scripts_by_id.get(sid)
        if not s or not s.get("enabled"):
            continue
        mod = _compiled.get(sid)
        if mod is None:
            continue
        key = f"{tag}{int(r.get('id') or 0)}"
        try:
            if (r.get("filled_contracts") or 0) > 0 and key not in _notified_fill:
                _notified_fill.add(key)
                _call_hook(mod, "on_fill", cfg, _pos_lite(r), mod.state)
            if r.get("resolved") and key not in _notified_settle:
                _notified_settle.add(key)
                _call_hook(mod, "on_settle", cfg, _pos_lite(r), mod.state)
        except script_sandbox.SCRIPT_FAILURES as e:
            _disable(sid, str(e))
            await _emit_event("script:status",
                             {"id": sid, "enabled": False, "lastError": str(e)})
    if len(_notified_fill) > 5000:
        _notified_fill.clear()
    if len(_notified_settle) > 5000:
        _notified_settle.clear()


def forget(sid: str) -> None:
    _compiled.pop(sid, None)
    _last_patch_t.pop(sid, None)
    _state_oversize_warned.discard(sid)
    _hb.pop(sid, None)
    _hb_last.pop(sid, None)
    _status.pop(sid, None)
    for key in [k for k in _market_cooldown if k[0] == sid]:
        del _market_cooldown[key]


def _save_states() -> None:
    global _last_state_save
    if time.time() - _last_state_save < STATE_SAVE_EVERY_S:
        return
    _last_state_save = time.time()
    for sid, mod in list(_compiled.items()):
        try:
            blob = json.dumps(mod.state)
            if len(blob) > STATE_MAX_BYTES:
                if sid not in _state_oversize_warned:
                    _state_oversize_warned.add(sid)
                    logger.warning(
                        f"[scripts] {sid[:8]} state is {len(blob) // 1024}KB "
                        f"(limit {STATE_MAX_BYTES // 1024}KB) — not persisted; "
                        "it will not survive a restart until you trim it")
                continue
            _state_oversize_warned.discard(sid)
            with db.get_db() as conn:
                db.update_user_script(conn, sid, state_json=blob)
        except (TypeError, ValueError):
            pass
        except Exception as e:
            logger.debug(f"[scripts] state save {sid[:8]}: {e}")


async def _drain_logs(sid: str, mod: script_sandbox.CompiledScript) -> None:
    lines = mod.drain_logs()
    if lines:
        await _emit_event("script:log", {"id": sid, "lines": lines[-40:]})


def _hb_note(sid: str, key: str, n: int = 1) -> None:
    d = _hb.setdefault(sid, {})
    d[key] = d.get(key, 0) + n
    if key.endswith("_intents"):
        st = _stat(sid)
        st["intents"] += n
        st["lastIntentAt"] = _now_iso()
    elif key == "placed":
        st = _stat(sid)
        st["orders"] += n
        st["lastOrderAt"] = _now_iso()


def _heartbeat_line(hb: dict[str, int], *, shadow: bool, open_count: int,
                    day_pnl: float) -> str:
    def _n(count: int, singular: str) -> str:
        return f"{count:,} {singular}" + ("" if count == 1 else "s")

    parts = [_n(hb.get("ticks", 0), "tick")]
    for hook in ("decide", "decide_market", "decide_signal", "manage"):
        calls = hb.get(hook, 0)
        if not calls and not hb.get(f"{hook}_hooked"):
            continue
        got = hb.get(f"{hook}_intents", 0)
        noun = "action" if hook == "manage" else "intent"
        parts.append(f"{hook} ×{calls:,} → {_n(got, noun)}")
    placed = hb.get("placed", 0)
    refused = hb.get("refused", 0)
    seg = _n(placed, "shadow order" if shadow else "order")
    if refused:
        seg += f", {refused:,} declined"
    parts.append(seg)
    if hb.get("supervise_skipped_shadow"):
        parts.append("supervise skipped (shadow)")
    errs = hb.get("errors", 0)
    if errs:
        parts.append(f"{errs:,} ERROR" + ("" if errs == 1 else "S"))
    parts.append(f"{open_count} open, today {day_pnl:+.2f} USD")
    stamp = datetime.now().strftime("%H:%M:%S")
    return f"[{stamp}] " + " · ".join(parts)


async def _maybe_heartbeat(s: dict, mod: script_sandbox.CompiledScript, *,
                           shadow: bool, open_count: int,
                           day_pnl: float) -> None:
    sid = str(s["id"])
    try:
        now = time.time()
        if now - _hb_last.get(sid, 0.0) < HEARTBEAT_SEC:
            return
        _hb_last[sid] = now
        hb = _hb.pop(sid, {})
        for hook in ("decide", "decide_market", "decide_signal", "manage"):
            if hook in mod.hooks:
                hb.setdefault(f"{hook}_hooked", 1)
        line = _heartbeat_line(hb, shadow=shadow, open_count=open_count,
                               day_pnl=day_pnl)
        name = str(s.get("name") or sid[:8])
        logger.info(f"[scripts] {name} ({sid[:8]}) {line}")
        await _emit_event("script:log", {"id": sid, "lines": [line]})
    except Exception as e:
        logger.debug(f"[scripts] heartbeat {sid[:8]}: {e}")


async def run_tick(cfg: dict, *, authed: bool) -> None:
    if not authed:
        _enabled_hooks.clear()
        return
    with db.get_db() as conn:
        scripts = db.list_user_scripts(conn)
    enabled = [s for s in scripts if s.get("enabled")]
    live_ok = bool(cfg.get("scripts_live_enabled"))
    if not live_ok:
        for s in enabled:
            if not s.get("dry_run"):
                _gate(str(s["id"]), "master_off")
        enabled = [s for s in enabled if s.get("dry_run")]
    max_enabled = int(cfg.get("script_max_enabled") or 10)
    if len(enabled) > max_enabled:
        global _last_starved
        dropped = [str(s.get("name") or s["id"]) for s in enabled[max_enabled:]]
        if dropped != _last_starved:
            _last_starved = dropped
            logger.warning(
                f"[scripts] {len(dropped)} enabled script(s) over the "
                f"script_max_enabled cap ({max_enabled}) are NOT running: "
                f"{', '.join(dropped)} — disable one or raise the cap")
        for s in enabled[max_enabled:]:
            _gate(str(s["id"]), "over_cap")
        enabled = enabled[:max_enabled]
    elif _last_starved:
        _last_starved = []
    if not enabled:
        _enabled_hooks.clear()
        return
    env = polymarket_auth.get_env()
    scripts_by_id = {str(s["id"]): s for s in scripts}

    try:
        await _notify_lifecycle(scripts_by_id, env, cfg)
    except Exception as e:
        logger.debug(f"[scripts] lifecycle notify: {e}")

    await _settle_shadow_orders()

    compiled: list[tuple[dict, script_sandbox.CompiledScript]] = []
    for s in enabled:
        mod = _get_compiled(s, cfg)
        if mod is None:
            _gate(str(s["id"]), "compile_failed")
            await _emit_event("script:status", {
                "id": str(s["id"]), "enabled": False,
                "lastError": "compile failed (see script page)"})
            continue
        compiled.append((s, mod))
    if not compiled:
        _enabled_hooks.clear()
        return

    global _enabled_hooks_at
    _enabled_hooks.clear()
    for _s, _m in compiled:
        _enabled_hooks.update(_m.hooks)
    _enabled_hooks_at = time.time()

    wants_crypto = bool(_enabled_hooks & {"decide", "manage"})
    assets: list[dict] = []
    if wants_crypto:
        snap = await crypto15m.snapshot(cfg)
        assets = [a for a in (snap.get("assets") or [])
                  if a.get("hasMarket") and a.get("ticker")]
    assets_by_ticker = {str(a.get("ticker")): a for a in assets}
    new_signals = _fetch_new_signals(env) if "decide_signal" in _enabled_hooks else []
    _markets_cache: list[dict] | None = None

    def markets_for_tick() -> list[dict]:
        nonlocal _markets_cache
        if _markets_cache is None:
            _markets_cache = _market_universe(cfg)
        return _markets_cache
    balance_usd = None
    try:
        cents, _port = await trader.refresh_balance(cfg, force=False)
        if cents > 0 or trader.last_balance_read_ok():
            balance_usd = round(cents / 100.0, 2)
    except Exception:
        pass

    for s, mod in compiled:
        sid = str(s["id"])
        shadow = bool(s.get("dry_run"))
        scope = parse_asset_scope(s.get("assets"))
        try:
            with db.get_db() as conn:
                if shadow:
                    day_pnl = db.script_shadow_daily_pnl(conn, sid, env)
                    open_count = db.count_open_script_shadow(conn, sid, env)
                    open_crypto = []
                else:
                    day_pnl = _script_daily_pnl(conn, sid, env)
                    open_count = _count_open_for_script(conn, sid, env)
                    open_crypto = _open_crypto_for_script(conn, sid, env)
            _lc = cfg.get("script_daily_loss_usd")
            loss_cap = float(_lc) if _lc is not None else 25.0
            if loss_cap > 0 and day_pnl <= -loss_cap:
                reason = (f"daily loss cap hit ({day_pnl:.2f} <= "
                          f"-{loss_cap:.2f} USD) — re-enable tomorrow or raise the cap")
                _disable(sid, reason)
                await _emit_event("script:status",
                                 {"id": sid, "enabled": False, "lastError": reason})
                continue
        except Exception as e:
            logger.debug(f"[scripts] risk query {sid[:8]}: {e}")
            continue

        _hb_note(sid, "ticks")
        st = _stat(sid)
        st["ticks"] += 1
        st["lastTickAt"] = _now_iso()
        st["gate"] = None
        portfolio = {
            "balanceUsd": balance_usd,
            "openCount": open_count,
            "openPositions": [_pos_lite(p) for p in open_crypto],
            "todayPnlUsd": round(day_pnl, 2),
        }

        try:
            if "manage" in mod.hooks and open_crypto:
                await _manage_pass(s, mod, cfg, env, assets_by_ticker, portfolio)
        except script_sandbox.SCRIPT_FAILURES as e:
            _disable(sid, str(e))
            await _emit_event("script:status",
                             {"id": sid, "enabled": False, "lastError": str(e)})
            await _drain_logs(sid, mod)
            continue

        max_open = int(cfg.get("script_max_open") or 2)
        died = False
        if "decide" in mod.hooks:
            for a in assets:
                if open_count >= max_open:
                    break
                if not script_allows_asset(scope, str(a.get("asset") or "")):
                    continue
                try:
                    with db.get_db() as conn:
                        if _already_attempted(conn, sid, str(a.get("ticker")),
                                              shadow=shadow):
                            continue
                except Exception:
                    continue
                ctx = dict(a)
                ctx["portfolio"] = portfolio
                try:
                    _hb_note(sid, "decide")
                    raw = _call_hook(mod, "decide", cfg, ctx)
                except script_sandbox.SCRIPT_FAILURES as e:
                    _hb_note(sid, "errors")
                    _disable(sid, str(e))
                    await _emit_event("script:status",
                                     {"id": sid, "enabled": False, "lastError": str(e)})
                    died = True
                    break
                if raw is None:
                    continue
                _hb_note(sid, "decide_intents")
                intent, err = sanitize_intent(raw)
                if err:
                    _disable(sid, f"malformed intent: {err}")
                    await _emit_event("script:status",
                                     {"id": sid, "enabled": False,
                                      "lastError": f"malformed intent: {err}"})
                    died = True
                    break
                try:
                    placed = await _place_intent(s, a, intent, cfg, env, balance_usd)
                except Exception as e:
                    _hb_note(sid, "errors")
                    logger.error(f"[scripts] place {sid[:8]} {a.get('asset')}: {e}")
                    continue
                if placed is not None:
                    _hb_note(sid, "placed")
                    open_count += 1
                else:
                    _hb_note(sid, "refused")
        if died:
            await _drain_logs(sid, mod)
            continue

        if "decide_market" in mod.hooks:
            scan_deadline = time.monotonic() + MARKET_SCAN_BUDGET_S
            scanned = 0
            for m in markets_for_tick():
                if open_count >= max_open:
                    break
                if time.monotonic() > scan_deadline:
                    logger.info(
                        f"[scripts] {sid[:8]} decide_market scan hit its "
                        f"{MARKET_SCAN_BUDGET_S:g}s budget after {scanned} "
                        "markets — remainder deferred to the next tick")
                    break
                scanned += 1
                if _in_cooldown(sid, str(m.get("ticker"))):
                    continue
                try:
                    with db.get_db() as conn:
                        if _market_already_attempted(
                                conn, sid, str(m.get("ticker")), shadow=shadow):
                            continue
                except Exception:
                    continue
                mctx = market_to_js(m)
                mctx["portfolio"] = portfolio
                try:
                    _hb_note(sid, "decide_market")
                    raw = _call_hook(mod, "decide_market", cfg, mctx)
                except script_sandbox.SCRIPT_FAILURES as e:
                    _hb_note(sid, "errors")
                    _disable(sid, str(e))
                    await _emit_event("script:status",
                                     {"id": sid, "enabled": False, "lastError": str(e)})
                    died = True
                    break
                if raw is None:
                    continue
                _hb_note(sid, "decide_market_intents")
                intent, err = sanitize_market_intent(raw)
                if err:
                    _disable(sid, f"malformed decide_market intent: {err}")
                    await _emit_event("script:status",
                                     {"id": sid, "enabled": False,
                                      "lastError": f"malformed decide_market intent: {err}"})
                    died = True
                    break
                try:
                    placed = await _place_market_intent(s, m, intent, cfg, env, balance_usd)
                except Exception as e:
                    _hb_note(sid, "errors")
                    logger.error(
                        f"[scripts] market place {sid[:8]} {m.get('ticker')}: {e}")
                    continue
                if placed is not None:
                    _hb_note(sid, "placed")
                    open_count += 1
                else:
                    _hb_note(sid, "refused")
        if died:
            await _drain_logs(sid, mod)
            continue

        if "decide_signal" in mod.hooks and new_signals:
            for sig, source in new_signals:
                if open_count >= max_open:
                    break
                try:
                    _hb_note(sid, "decide_signal")
                    raw = _call_hook(mod, "decide_signal", cfg, signal_to_js(sig, source))
                except script_sandbox.SCRIPT_FAILURES as e:
                    _hb_note(sid, "errors")
                    _disable(sid, str(e))
                    await _emit_event("script:status",
                                     {"id": sid, "enabled": False, "lastError": str(e)})
                    died = True
                    break
                act, err = sanitize_signal_action(raw)
                if err:
                    _hb_note(sid, "errors")
                    _disable(sid, f"malformed decide_signal return: {err}")
                    died = True
                    break
                if act is None:
                    continue
                _hb_note(sid, "decide_signal_intents")
                try:
                    placed = await _place_signal_follow(s, sig, source, act, cfg, env, balance_usd)
                except Exception as e:
                    _hb_note(sid, "errors")
                    logger.error(f"[scripts] signal follow {sid[:8]}: {e}")
                    continue
                if placed is not None:
                    _hb_note(sid, "placed")
                    open_count += 1
                else:
                    _hb_note(sid, "refused")
        if died:
            await _drain_logs(sid, mod)
            continue

        try:
            if "supervise" in mod.hooks and shadow:
                _hb_note(sid, "supervise_skipped_shadow")
            elif "supervise" in mod.hooks:
                app = {
                    "hourUtc": datetime.now(timezone.utc).hour,
                    "balanceUsd": balance_usd,
                    "scriptTodayPnlUsd": round(day_pnl, 2),
                    "engines": {
                        "mainTrading": bool(cfg.get("enable_trading")),
                        "whales": bool(cfg.get("trade_whales")),
                        "momentum": bool(cfg.get("trade_momentum")),
                        "crypto15m": bool(cfg.get("crypto15m_enabled")),
                        "copy": bool(cfg.get("copy_enabled")),
                    },
                    "config": {k: cfg.get(k) for k in _SUPERVISE_KEYS},
                    "assets": [{
                        "asset": a.get("asset"), "minsLeft": a.get("minsLeft"),
                        "sigma1m": a.get("sigma1m"), "modelProb": a.get("modelProb"),
                        "favoritePrice": a.get("favoritePrice"),
                    } for a in assets],
                }
                await _run_supervise(s, mod, cfg, app, shadow=shadow)
        except script_sandbox.SCRIPT_FAILURES as e:
            _hb_note(sid, "errors")
            _disable(sid, str(e))
            await _emit_event("script:status",
                             {"id": sid, "enabled": False, "lastError": str(e)})

        await _drain_logs(sid, mod)
        await _maybe_heartbeat(s, mod, shadow=shadow, open_count=open_count,
                               day_pnl=day_pnl)
    _save_states()
