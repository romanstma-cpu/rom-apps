from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Optional

import db
import polymarket_api
import polymarket_auth
import trader

logger = logging.getLogger("rom.copy")

_last_halt_log_t = 0.0

_copy_cooldown: dict = {}
_COPY_COOLDOWN_SEC = 300
_COPY_MIN_CONTRACTS = 5

_exit_retry_at: dict = {}
_EXIT_RETRY_SEC = 20

_wallet_pos_cache: dict[str, tuple[float, list]] = {}
_WALLET_CACHE_STALE_SEC = 90.0
_WALLET_CACHE_UI_SEC = 10.0

last_open_count = 0


def _own_addresses() -> set:
    out = set()
    for fn in (polymarket_auth.trading_address, polymarket_auth.get_address,
               polymarket_auth.get_funder):
        try:
            a = (fn() or "").strip().lower()
            if a:
                out.add(a)
        except Exception:
            pass
    return out


def _short_addr(a: str) -> str:
    a = a or ""
    return f"{a[:6]}…{a[-4:]}" if len(a) >= 12 else a


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


def _today_copy_pnl(env: str) -> float:
    with db.get_db() as conn:
        return db.engine_today_pnl(conn, "copy", env)


def _lifetime_loss_tripped(cfg: dict, env: str) -> tuple[bool, str]:
    limit_usd = float(cfg.get("copy_lifetime_loss_limit_usd") or 0.0)
    try:
        limit_pct = max(0.0, min(1.0, float(cfg.get("copy_lifetime_loss_limit_pct", 0.0) or 0.0)))
    except (TypeError, ValueError):
        limit_pct = 0.0
    if limit_usd <= 0 and limit_pct <= 0:
        return False, ""
    with db.get_db() as conn:
        lifetime = db.lifetime_realized_pnl(conn, "copy", env)
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


def _our_open_copies(env: str) -> list[dict]:
    with db.get_db() as conn:
        rows = conn.execute(
            """SELECT * FROM bot_positions
               WHERE signal_source='copy' AND network=? AND resolved=0
                 AND status IN ('submitted','partial','filled')""",
            (env,),
        ).fetchall()
    return [dict(r) for r in rows]


def _seen_key(env: str) -> str:
    return f"copy_seen:{env}"


_SEEN_MAX = 5000


def _load_seen(env: str) -> dict:
    try:
        with db.get_db() as conn:
            raw = db.kv_get(conn, _seen_key(env))
        if raw:
            return dict.fromkeys(json.loads(raw))
    except Exception:
        pass
    return {}


def _save_seen(env: str, seen: dict) -> None:
    try:
        with db.get_db() as conn:
            db.kv_set(conn, _seen_key(env), json.dumps(list(seen)))
    except Exception:
        pass


def _qty_base_key(env: str) -> str:
    return f"copy_qty_base:{env}"


def _load_qty_base(env: str) -> dict:
    try:
        with db.get_db() as conn:
            raw = db.kv_get(conn, _qty_base_key(env))
        if raw:
            m = json.loads(raw)
            if isinstance(m, dict):
                return {str(k): float(v) for k, v in m.items()}
    except Exception:
        pass
    return {}


def _save_qty_base(env: str, m: dict) -> None:
    try:
        with db.get_db() as conn:
            db.kv_set(conn, _qty_base_key(env), json.dumps(m))
    except Exception:
        pass


def _filter_new_entries(followed: dict, env: str, cfg: dict) -> dict:
    seen = _load_seen(env)
    changed = False
    cur_wallets = {w.strip().lower() for w in (cfg.get("copy_wallets") or [])
                   if isinstance(w, str)}
    stale = [k for k in seen if k.split("|", 1)[0].strip().lower() not in cur_wallets]
    for k in stale:
        del seen[k]
        changed = True
    seen_wallets = {k.split("|", 1)[0] for k in seen}
    eligible: dict = {}
    for key, h in followed.items():
        ticker, side = h["ticker"], h["side"]
        is_new = False
        for w in h.get("wallets", []):
            hk = f"{w}|{ticker}|{side}"
            if w in seen_wallets and hk not in seen:
                is_new = True
            elif hk not in seen:
                seen[hk] = None
                changed = True
        if is_new:
            eligible[key] = h
    if len(seen) > _SEEN_MAX:
        for k in list(seen)[: len(seen) - _SEEN_MAX]:
            del seen[k]
        changed = True
    if changed:
        _save_seen(env, seen)
    return eligible


def _compute_copy_contracts(
    cfg: dict, *, price_cents: int, balance_usd: float, cap_usd: Optional[float] = None
) -> int:
    price = max(0.01, int(price_cents) / 100.0)
    bal = max(0.0, float(balance_usd or 0.0))
    mode = (cfg.get("copy_sizing_mode") or "fixed").lower()
    if mode == "balance_pct" and bal > 0:
        pct = max(0.0, min(1.0, float(cfg.get("copy_balance_pct", 0.02) or 0.0)))
        budget = bal * pct
    else:
        budget = float(cfg.get("copy_fixed_usd", 10.0) or 0.0)
    if bal > 0:
        budget = min(budget, bal * 0.98)
    if cap_usd is not None:
        budget = min(budget, max(0.0, cap_usd))
    return max(0, int(budget // price))


async def _followed_holdings(cfg: dict) -> tuple[dict, bool]:
    own = _own_addresses()
    wallets = [w for w in (cfg.get("copy_wallets") or [])
               if isinstance(w, str) and w.strip().lower() not in own]
    min_cost = float(cfg.get("copy_min_trade_usd") or 0.0)
    out: dict[tuple[str, str], dict] = {}
    all_ok = True
    for w in wallets:
        wl = w.strip().lower()
        try:
            positions = await polymarket_api.get_positions(limit=500, user=w)
            _wallet_pos_cache[wl] = (time.time(), positions)
        except Exception as e:
            cached = _wallet_pos_cache.get(wl)
            age = (time.time() - cached[0]) if cached else None
            if cached and age <= _WALLET_CACHE_STALE_SEC:
                positions = cached[1]
                logger.debug(
                    f"[copy] fetch positions for {_short_addr(w)} failed ({e}); "
                    f"using {age:.0f}s-old cached read"
                )
            elif cached:
                positions = cached[1]
                logger.warning(
                    f"[copy] {_short_addr(w)} read failing for {age:.0f}s; using "
                    "last-good holdings so exits keep running (a real sale by this "
                    "wallet will be mirrored once its read recovers)"
                )
            else:
                logger.warning(f"[copy] fetch positions for {_short_addr(w)} failed: {e}")
                all_ok = False
                continue
        for p in positions:
            try:
                qty = float(p.get("position_fp") or 0.0)
            except (TypeError, ValueError):
                qty = 0.0
            if qty == 0:
                continue
            ticker = p.get("ticker") or ""
            if not ticker:
                continue
            side = "yes" if qty > 0 else "no"
            cost = float(p.get("market_exposure_dollars") or 0.0)
            if cost < min_cost:
                continue
            cur = p.get("cur_price")
            try:
                price_cents = int(round(float(cur) * 100)) if cur else None
            except (TypeError, ValueError):
                price_cents = None
            key = (ticker, side)
            entry = out.get(key)
            if entry is None:
                out[key] = {
                    "ticker": ticker, "side": side,
                    "price_cents": price_cents,
                    "cost": cost,
                    "qty": abs(qty),
                    "title": p.get("title") or ticker,
                    "event_ticker": p.get("event_ticker") or "",
                    "wallets": [w],
                }
            else:
                entry["wallets"].append(w)
                entry["cost"] = max(entry["cost"], cost)
                entry["qty"] = float(entry.get("qty") or 0.0) + abs(qty)
                if entry.get("price_cents") is None and price_cents is not None:
                    entry["price_cents"] = price_cents
    return out, all_ok


async def _enter_copy(
    h: dict, cfg: dict, env: str, balance_usd: float, available_usd: Optional[float] = None
) -> Optional[dict]:
    ticker, side = h["ticker"], h["side"]
    max_cents = int(cfg.get("copy_entry_max_cents", 95) or 95)

    ask = None
    try:
        q = await polymarket_api.get_quote(ticker, side)
        ask = q.get("ask_cents")
    except Exception as e:
        logger.debug(f"[copy] entry quote {ticker}: {e}")
    limit_cents = int(ask) if ask else (h.get("price_cents") or max_cents)
    if limit_cents > max_cents:
        logger.info(
            f"[copy] skip {_short_addr(h['wallets'][0])} {ticker} {side}: "
            f"price {limit_cents}c > entry_max {max_cents}c"
        )
        return None
    limit_cents = max(1, min(99, limit_cents))

    contracts = _compute_copy_contracts(
        cfg, price_cents=limit_cents, balance_usd=balance_usd, cap_usd=available_usd
    )
    if contracts < _COPY_MIN_CONTRACTS:
        logger.info(
            f"[copy] skip {ticker} {side}: budget funds {contracts} contract(s) at "
            f"{limit_cents}c, below the {_COPY_MIN_CONTRACTS}-contract minimum"
        )
        return None

    coid = f"rom-copy-{uuid.uuid4().hex[:10]}"
    row = {
        "signal_source": "copy",
        "signal_id": abs(hash((ticker, side, coid))) % 2_000_000_000,
        "ticker": ticker, "event_ticker": h.get("event_ticker") or "",
        "title": h.get("title") or ticker, "category": "",
        "direction": side, "action": "buy",
        "target_contracts": contracts, "limit_price_cents": limit_cents,
        "client_order_id": coid, "confidence": 0.0, "edge_pts": 0.0,
        "signal_price": float(limit_cents), "network": env,
    }

    try:
        resp = await polymarket_api.place_limit_order(
            ticker=ticker, side=side, action="buy",
            count=contracts, price_cents=limit_cents, client_order_id=coid,
        )
    except Exception as e:
        row.update({"status": "error", "error": str(e)[:200]})
        with db.get_db() as conn:
            pid = db.insert_bot_position(conn, row)
            db.update_bot_position(conn, pid, resolved=1)
            conn.execute("UPDATE bot_positions SET resolved_at=datetime('now') WHERE id=?", (pid,))
            logger.error(f"[copy] enter order failed {ticker}: {e}")
            return db.fetch_position_by_id(conn, pid)

    order = (resp.get("order") if isinstance(resp, dict) else None) or resp or {}
    oid = order.get("order_id") if isinstance(order, dict) else None
    if not oid:
        row.update({"status": "error", "error": "no order_id from exchange"})
        with db.get_db() as conn:
            pid = db.insert_bot_position(conn, row)
            db.update_bot_position(conn, pid, resolved=1)
            conn.execute("UPDATE bot_positions SET resolved_at=datetime('now') WHERE id=?", (pid,))
            return db.fetch_position_by_id(conn, pid)
    row.update({"status": "submitted", "order_id": oid})
    with db.get_db() as conn:
        pid = db.insert_bot_position(conn, row)
        logger.info(
            f"[copy] enter {ticker} {side} x{contracts} @ {limit_cents}c "
            f"(following {_short_addr(h['wallets'][0])})"
        )
        return db.fetch_position_by_id(conn, pid)


async def _book_gone_copy(pos: dict) -> Optional[dict]:
    pid = pos["id"]
    cost = float(pos.get("cost_usd") or 0.0)
    try:
        activity = await polymarket_api.get_activity(limit=1000)
        info = trader._exit_proceeds(pos, activity)
    except Exception as e:
        logger.debug(f"[copy] gone-copy activity read failed: {e}")
        return None
    if info is None:
        return None
    prior_proceeds = float(pos.get("settlement_usd") or 0.0)
    prior_pnl = float(pos.get("pnl_usd") or 0.0)
    remaining_proceeds = max(0.0, round(float(info["proceeds"]) - prior_proceeds, 4))
    total_proceeds = round(prior_proceeds + remaining_proceeds, 4)
    pnl = round(prior_pnl + (remaining_proceeds - cost), 4)
    with db.get_db() as conn:
        db.update_bot_position(
            conn, pid, resolved=1, status="filled",
            outcome_correct=(1 if pnl > 0.05 else (0 if pnl < -0.05 else None)),
            settlement_usd=total_proceeds, pnl_usd=pnl,
        )
        conn.execute(
            "UPDATE bot_positions SET resolved_at=datetime('now'), closed_early=1 WHERE id=?",
            (pid,),
        )
        db.log_event(conn, pid, "copy-exit",
                     note=f"position no longer held ({info['kind']}); "
                          f"proceeds=${total_proceeds:.2f} pnl=${pnl:+.2f}")
        logger.info(f"[copy] exit {pos['ticker']} booked (no longer held) pnl=${pnl:+.2f}")
        return db.fetch_position_by_id(conn, pid)


async def _exit_copy(pos: dict, cfg: dict, held_qty: dict, holdings_ok: bool,
                     sell_qty: Optional[int] = None,
                     reason: str = "followed wallets exited") -> Optional[dict]:
    ticker, direction = pos["ticker"], pos["direction"]
    qty = int(pos.get("filled_contracts") or 0)
    cost = float(pos.get("cost_usd") or 0.0)
    pid = pos["id"]

    if pos.get("status") in ("submitted", "partial") and qty <= 0:
        oid = pos.get("order_id")
        if oid:
            try:
                await polymarket_api.cancel_order(oid)
            except Exception as e:
                logger.debug(f"[copy] cancel {ticker}: {e}")
        held_now = int(held_qty.get((ticker, direction)) or 0) if holdings_ok else 0
        if held_now > 0:
            qty = held_now
            if cost <= 0:
                cost = qty * float(pos.get("limit_price_cents") or 0) / 100.0
        elif holdings_ok:
            with db.get_db() as conn:
                db.update_bot_position(conn, pid, status="canceled", resolved=1,
                                       error="followed wallet exited before fill")
                conn.execute("UPDATE bot_positions SET resolved_at=datetime('now') WHERE id=?", (pid,))
                return db.fetch_position_by_id(conn, pid)
        else:
            return None

    if qty <= 0:
        return None

    if holdings_ok:
        held = held_qty.get((ticker, direction)) or 0
        if held <= 0:
            return await _book_gone_copy(pos)
        if held < qty:
            qty = int(held)

    sell_request = qty if sell_qty is None else max(0, min(int(sell_qty), qty))
    if sell_request <= 0:
        return None

    rkey = (ticker, direction)
    if time.time() - _exit_retry_at.get(rkey, 0.0) < _EXIT_RETRY_SEC:
        return None

    try:
        q = await polymarket_api.get_quote(ticker, direction)
        bid = q.get("bid_cents")
    except Exception:
        bid = None
    sell_px = max(1, min(99, int(bid) if bid else 1))
    if sell_qty is not None and sell_request * sell_px < 100:
        return None
    coid = f"rom-copyx-{pid}-{uuid.uuid4().hex[:6]}"
    _exit_retry_at[rkey] = time.time()
    trader.cap_dict_size(_exit_retry_at)
    try:
        resp = await polymarket_api.place_limit_order(
            ticker=ticker, side=direction, action="sell",
            count=sell_request, price_cents=sell_px, client_order_id=coid,
            order_type="FAK",
        )
    except Exception as e:
        logger.warning(f"[copy] exit sell {ticker} failed: {e}")
        return None
    order = (resp.get("order") if isinstance(resp, dict) else None) or {}
    sold, avg_cents = await trader._confirm_sell(order.get("order_id"), sell_request, sell_px)
    if sold <= 0:
        logger.warning(f"[copy] exit {ticker}: sell didn't fill; still holding {qty}")
        return None

    proceeds = sold * avg_cents / 100.0
    prior_pnl = float(pos.get("pnl_usd") or 0.0)
    prior_proceeds = float(pos.get("settlement_usd") or 0.0)
    if sold < qty:
        remaining = qty - sold
        sold_cost = cost * (sold / qty)
        slice_pnl = proceeds - sold_cost
        label = "copy-reduce" if sell_qty is not None else "copy-exit-partial"
        with db.get_db() as conn:
            db.update_bot_position(
                conn, pid, filled_contracts=remaining,
                cost_usd=round(cost - sold_cost, 4),
                pnl_usd=round(prior_pnl + slice_pnl, 4),
                settlement_usd=round(prior_proceeds + proceeds, 4),
            )
            db.log_event(conn, pid, label,
                         note=f"{reason}; sold {sold}/{qty} @ ~{avg_cents:.0f}c; "
                              f"{remaining} left; slice pnl=${slice_pnl:+.2f}")
            logger.info(f"[copy] {label} {ticker} sold {sold}/{qty} @ ~{avg_cents:.0f}c "
                        f"(slice pnl ${slice_pnl:+.2f})")
            return db.fetch_position_by_id(conn, pid)

    pnl = prior_pnl + (proceeds - cost)
    total_proceeds = prior_proceeds + proceeds
    with db.get_db() as conn:
        db.update_bot_position(
            conn, pid, resolved=1, status="filled",
            outcome_correct=(1 if pnl > 0.05 else (0 if pnl < -0.05 else None)),
            settlement_usd=round(total_proceeds, 4), pnl_usd=round(pnl, 4),
        )
        conn.execute("UPDATE bot_positions SET resolved_at=datetime('now'), closed_early=1 WHERE id=?", (pid,))
        db.log_event(conn, pid, "copy-exit",
                     note=f"{reason}; sold {sold} @ ~{avg_cents:.0f}c pnl=${pnl:+.2f}")
        logger.info(f"[copy] exit {ticker} sold {sold} @ ~{avg_cents:.0f}c pnl=${pnl:+.2f}")
        return db.fetch_position_by_id(conn, pid)


async def run_tick(cfg: dict, *, authed: bool) -> list[dict]:
    if not cfg.get("copy_enabled") or not (cfg.get("copy_wallets") or []):
        return []
    if not authed:
        return []
    env = trader.get_env()
    now = time.time()
    changed: list[dict] = []

    followed, follows_ok = await _followed_holdings(cfg)
    open_copies = _our_open_copies(env)
    open_keys = {(p["ticker"], p["direction"]) for p in open_copies}
    global last_open_count
    last_open_count = len(open_keys)
    qty_base: dict = _load_qty_base(env)
    qb_changed = False

    if not follows_ok:
        logger.warning("[copy] skipping exit pass — one or more wallet reads failed")
    to_exit = [] if not follows_ok else [
        p for p in open_copies if (p["ticker"], p["direction"]) not in followed
    ]
    reduce_jobs: list[tuple[dict, int, str, float]] = []
    if follows_ok and bool(cfg.get("copy_mirror_reductions", True)):
        try:
            thr = float(cfg.get("copy_reduce_threshold", 0.25) or 0.25)
        except (TypeError, ValueError):
            thr = 0.25
        thr = max(0.05, min(0.95, thr))
        for p in open_copies:
            key = (p["ticker"], p["direction"])
            if key not in followed:
                continue
            if p.get("status") != "filled" or int(p.get("filled_contracts") or 0) <= 0:
                continue
            kstr = f"{key[0]}|{key[1]}"
            cur_qty = float(followed[key].get("qty") or 0.0)
            base = qty_base.get(kstr)
            if base is None or float(base) <= 0:
                qty_base[kstr] = cur_qty
                qb_changed = True
                continue
            base = float(base)
            if cur_qty < base * (1.0 - thr):
                frac_gone = 1.0 - (cur_qty / base)
                sell = int(round(int(p.get("filled_contracts") or 0) * frac_gone))
                if sell >= 1:
                    reduce_jobs.append((p, sell, kstr, cur_qty))
    held_qty: dict = {}
    holdings_ok = False
    if to_exit or reduce_jobs:
        try:
            for p in await polymarket_api.get_positions():
                q = float(p.get("position_fp") or 0.0)
                if q:
                    held_qty[(p.get("ticker") or "", "yes" if q > 0 else "no")] = abs(q)
            holdings_ok = True
        except Exception as e:
            logger.debug(f"[copy] holdings fetch for exits failed: {e}")
    for pos in to_exit:
        key = (pos["ticker"], pos["direction"])
        try:
            row = await _exit_copy(pos, cfg, held_qty, holdings_ok)
            if row and row.get("resolved"):
                changed.append(row)
                open_keys.discard(key)
                _copy_cooldown[key] = now
                trader.cap_dict_size(_copy_cooldown)
            elif row:
                changed.append(row)
        except Exception as e:
            logger.warning(f"[copy] exit {pos['ticker']} failed: {e}")
    for pos, sell, kstr, cur_qty in reduce_jobs:
        try:
            row = await _exit_copy(
                pos, cfg, held_qty, holdings_ok, sell_qty=sell,
                reason=f"followed wallets cut to {cur_qty:.0f} shares",
            )
            if row:
                changed.append(row)
                qty_base[kstr] = cur_qty
                qb_changed = True
                if row.get("resolved"):
                    open_keys.discard((pos["ticker"], pos["direction"]))
        except Exception as e:
            logger.warning(f"[copy] reduce {pos['ticker']} failed: {e}")
    if qb_changed:
        _save_qty_base(env, qty_base)
        qb_changed = False

    global _last_halt_log_t
    blocked, why = trader._is_blocked_by_daily_risk(cfg, env)
    if blocked:
        if now - _last_halt_log_t >= 60:
            _last_halt_log_t = now
            logger.warning(f"[copy] {why}; no new copies")
        return changed
    loss_limit = float(cfg.get("copy_daily_loss_limit") or 0.0)
    if loss_limit < 0 and _today_copy_pnl(env) <= loss_limit:
        if now - _last_halt_log_t >= 60:
            _last_halt_log_t = now
            logger.warning(f"[copy] daily loss limit hit (today <= ${loss_limit:.0f}); no new copies")
        return changed
    _lt_trip, _lt_why = _lifetime_loss_tripped(cfg, env)
    if _lt_trip:
        if now - _last_halt_log_t >= 60:
            _last_halt_log_t = now
            logger.warning(f"[copy] {_lt_why}; no new copies")
        return changed

    max_conc = int(cfg.get("copy_max_concurrent", 10) or 10)
    open_count = len(open_keys)
    balance_usd = await _bankroll_usd(cfg, bool(authed))
    if balance_usd <= 0.0 and trader.last_balance_read_ok():
        return changed

    with db.get_db() as conn:
        exposure = db.current_total_exposure_usd(conn, env)
        filled_exposure = db.current_filled_exposure_usd(conn, env)
        held_rows = conn.execute(
            """SELECT ticker, direction FROM bot_positions
               WHERE resolved=0 AND status IN ('submitted','partial','filled')
                 AND network=?""",
            (env,),
        ).fetchall()
    held_keys = {(r["ticker"], r["direction"]) for r in held_rows}
    pending_notional = max(0.0, exposure - filled_exposure)
    total_bankroll = max(0.0, balance_usd) + max(0.0, filled_exposure)
    reserve = total_bankroll * float(cfg.get("min_cash_reserve_fraction", 0.0) or 0.0)
    max_exposure = total_bankroll * float(cfg.get("max_total_exposure_fraction", 1.0) or 1.0)
    spendable_cash = max(0.0, balance_usd) - pending_notional
    available_usd = min(max(0.0, spendable_cash - reserve), max(0.0, max_exposure - exposure))

    entry_set = _filter_new_entries(followed, env, cfg) if cfg.get("copy_only_new_entries", True) else followed

    _ok_open, _lock_why = trader.can_open_new_entries(env)
    if not _ok_open:
        logger.info(f"[copy] {_lock_why}")
        return changed

    allow_reentries = bool(cfg.get("copy_allow_reentries"))
    if follows_ok:
        for k in [k for k in qty_base if tuple(k.rsplit("|", 1)) not in followed]:
            del qty_base[k]
            qb_changed = True

    for key, h in entry_set.items():
        kstr = f"{key[0]}|{key[1]}"
        addon = False
        if key in open_keys or key in held_keys:
            if not allow_reentries or key not in open_keys:
                continue
            cur_qty = float(h.get("qty") or 0.0)
            base = qty_base.get(kstr)
            if base is None:
                qty_base[kstr] = cur_qty
                qb_changed = True
                continue
            px = float(h.get("price_cents") or 50) / 100.0
            added_usd = max(0.0, cur_qty - float(base)) * px
            if added_usd < max(1.0, float(cfg.get("copy_min_trade_usd") or 0.0)):
                continue
            addon = True
        if now - _copy_cooldown.get(key, 0.0) < _COPY_COOLDOWN_SEC:
            continue
        if not addon and open_count >= max_conc:
            continue
        try:
            row = await _enter_copy(h, cfg, env, balance_usd, available_usd)
            if row is None or row.get("status") == "error":
                _copy_cooldown[key] = now
                trader.cap_dict_size(_copy_cooldown)
            if row:
                changed.append(row)
                if not addon:
                    open_count += 1
                    open_keys.add(key)
                if row.get("status") in ("submitted", "filled", "partial"):
                    qty_base[kstr] = float(h.get("qty") or 0.0)
                    qb_changed = True
                    committed = float(row.get("cost_usd") or 0.0)
                    if committed <= 0:
                        committed = (int(row.get("target_contracts") or 0)
                                     * int(row.get("limit_price_cents") or 0) / 100.0)
                    balance_usd = max(0.0, balance_usd - committed)
                    available_usd = max(0.0, available_usd - committed)
        except Exception as e:
            _copy_cooldown[key] = now
            trader.cap_dict_size(_copy_cooldown)
            logger.warning(f"[copy] enter {h.get('ticker')} failed: {e}")

    if qb_changed:
        _save_qty_base(env, qty_base)
    return changed


async def status(cfg: dict, *, authed: bool = False) -> dict:
    env = trader.get_env()
    wallets = cfg.get("copy_wallets") or []

    wallet_info = []
    for w in wallets:
        n, value = 0, 0.0
        wl = (w or "").strip().lower()
        try:
            cached = _wallet_pos_cache.get(wl)
            if cached and time.time() - cached[0] <= _WALLET_CACHE_UI_SEC:
                positions = cached[1]
            else:
                positions = await polymarket_api.get_positions(limit=500, user=w)
                _wallet_pos_cache[wl] = (time.time(), positions)
            for p in positions:
                if float(p.get("position_fp") or 0.0) != 0.0:
                    n += 1
                    value += float(p.get("market_exposure_dollars") or 0.0)
        except Exception as e:
            logger.debug(f"[copy] status fetch {_short_addr(w)}: {e}")
        wallet_info.append({
            "address": w, "short": _short_addr(w),
            "positions": n, "valueUsd": round(value, 2),
        })

    open_copies = _our_open_copies(env)
    loss_limit = float(cfg.get("copy_daily_loss_limit") or 0.0)
    today_pnl = _today_copy_pnl(env)

    return {
        "enabled": bool(cfg.get("copy_enabled")),
        "authed": bool(authed),
        "trading": bool(cfg.get("copy_enabled")) and bool(authed),
        "wallets": wallet_info,
        "openCopies": len(open_copies),
        "todayPnlUsd": round(today_pnl, 2),
        "lossLimitHit": loss_limit < 0 and today_pnl <= loss_limit,
        "sizing": {
            "mode": (cfg.get("copy_sizing_mode") or "fixed"),
            "fixedUsd": float(cfg.get("copy_fixed_usd") or 0.0),
            "balancePct": float(cfg.get("copy_balance_pct") or 0.0),
        },
        "maxConcurrent": int(cfg.get("copy_max_concurrent") or 0),
        "entryMaxCents": int(cfg.get("copy_entry_max_cents") or 0),
    }
