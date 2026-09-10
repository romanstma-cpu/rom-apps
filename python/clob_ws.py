from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from typing import Optional

logger = logging.getLogger("clob_ws")

WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
_PING_INTERVAL = 10.0
_STALE_AFTER = 12.0
_RECONNECT_BASE = 1.0
_RECONNECT_MAX = 30.0


def _best_from_levels(levels, *, is_bid: bool) -> Optional[float]:
    prices = []
    for lvl in levels or []:
        try:
            sz = float(lvl.get("size", 0))
            if sz <= 0:
                continue
            p = float(lvl["price"])
            if not (0.0 < p < 1.0):
                continue
            prices.append(p)
        except (TypeError, ValueError, KeyError):
            continue
    if not prices:
        return None
    return max(prices) if is_bid else min(prices)


def parse_book(msg: dict) -> Optional[tuple[str, Optional[float], Optional[float]]]:
    aid = msg.get("asset_id")
    if not aid:
        return None
    bid = _best_from_levels(msg.get("bids"), is_bid=True)
    ask = _best_from_levels(msg.get("asks"), is_bid=False)
    return str(aid), bid, ask


def parse_price_changes(msg: dict) -> list[tuple[str, Optional[float], Optional[float]]]:
    out: list[tuple[str, Optional[float], Optional[float]]] = []
    for pc in msg.get("price_changes") or []:
        if not isinstance(pc, dict):
            continue
        aid = pc.get("asset_id")
        if not aid:
            continue

        def _f(k):
            v = pc.get(k)
            try:
                return float(v) if v is not None and v != "" else None
            except (TypeError, ValueError):
                return None

        out.append((str(aid), _f("best_bid"), _f("best_ask")))
    return out


def parse_last_trade(msg: dict) -> Optional[dict]:
    aid = msg.get("asset_id")
    try:
        price = float(msg.get("price"))
    except (TypeError, ValueError):
        return None
    if not aid or not (0.0 < price < 1.0):
        return None
    try:
        size = float(msg.get("size")) if msg.get("size") not in (None, "") else None
    except (TypeError, ValueError):
        size = None
    try:
        src_ms = int(msg.get("timestamp")) if msg.get("timestamp") else None
    except (TypeError, ValueError):
        src_ms = None
    return {
        "asset_id": str(aid), "price": price, "size": size,
        "side": (msg.get("side") or "").upper() or None,
        "source_ts_ms": src_ms, "ingest_ts": time.time(),
        "market": msg.get("market"), "tx": msg.get("transaction_hash"),
    }


def _iter_messages(raw: str) -> list[dict]:
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return []
    if isinstance(data, dict):
        return [data]
    if isinstance(data, list):
        return [m for m in data if isinstance(m, dict)]
    return []


class ClobMarketFeed:
    def __init__(self) -> None:
        self._books: dict[str, dict] = {}
        self._tokens: dict[str, float] = {}
        self._task: Optional[asyncio.Task] = None
        self._resub = asyncio.Event()
        self._stop = False
        self._trades: list[dict] = []
        self._new_markets: list[dict] = []
        self._resolutions: list[dict] = []
    _TRADES_MAX = 5000
    _EVENTS_MAX = 500


    def get_quote_cents(self, token_id: Optional[str], max_age: float = _STALE_AFTER) -> Optional[dict]:
        if not token_id:
            return None
        b = self._books.get(str(token_id))
        if not b:
            return None
        if (time.monotonic() - b["ts"]) > max_age:
            return None
        bid, ask = b.get("bid"), b.get("ask")
        return {
            "bid_cents": int(round(bid * 100)) if bid is not None else None,
            "ask_cents": int(round(ask * 100)) if ask is not None else None,
        }

    def _set(self, aid: str, bid: Optional[float], ask: Optional[float]) -> None:
        cur = self._books.get(aid) or {}
        self._books[aid] = {
            "bid": bid if bid is not None else cur.get("bid"),
            "ask": ask if ask is not None else cur.get("ask"),
            "ts": time.monotonic(),
        }

    def _dispatch(self, msg: dict) -> None:
        et = msg.get("event_type") or msg.get("type")
        if et == "book":
            parsed = parse_book(msg)
            if parsed:
                aid, bid, ask = parsed
                self._set(aid, bid, ask)
        elif et == "price_change":
            for aid, bid, ask in parse_price_changes(msg):
                self._set(aid, bid, ask)
        elif et == "best_bid_ask":
            aid = msg.get("asset_id")
            if aid:
                def _f(k):
                    try:
                        v = msg.get(k)
                        return float(v) if v not in (None, "") else None
                    except (TypeError, ValueError):
                        return None
                self._set(str(aid), _f("best_bid"), _f("best_ask"))
        elif et == "last_trade_price":
            row = parse_last_trade(msg)
            if row:
                self._trades.append(row)
                if len(self._trades) > self._TRADES_MAX:
                    del self._trades[: len(self._trades) - self._TRADES_MAX]
        elif et == "new_market":
            self._new_markets.append(msg)
            if len(self._new_markets) > self._EVENTS_MAX:
                del self._new_markets[: len(self._new_markets) - self._EVENTS_MAX]
        elif et == "market_resolved":
            self._resolutions.append(msg)
            if len(self._resolutions) > self._EVENTS_MAX:
                del self._resolutions[: len(self._resolutions) - self._EVENTS_MAX]


    def drain_trades(self) -> list[dict]:
        out, self._trades = self._trades, []
        return out

    def drain_new_markets(self) -> list[dict]:
        out, self._new_markets = self._new_markets, []
        return out

    def drain_resolutions(self) -> list[dict]:
        out, self._resolutions = self._resolutions, []
        return out


    _TOKEN_TTL = 2 * 3600.0

    def observe(self, *token_ids: Optional[str]) -> None:
        now = time.monotonic()
        grew = False
        for t in token_ids:
            if not t:
                continue
            t = str(t)
            if t not in self._tokens:
                grew = True
            self._tokens[t] = now
        expired = [t for t, ts in self._tokens.items() if now - ts > self._TOKEN_TTL]
        for t in expired:
            del self._tokens[t]
            self._books.pop(t, None)
        if grew or expired:
            if len(self._books) > 64:
                for aid in list(self._books):
                    if aid not in self._tokens:
                        self._books.pop(aid, None)
            self._resub.set()


    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stop = False
            self._task = asyncio.ensure_future(self._run())

    async def stop(self) -> None:
        self._stop = True
        self._resub.set()
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None

    async def _run(self) -> None:
        import websockets
        import ws_ssl

        backoff = _RECONNECT_BASE
        while not self._stop:
            if not self._tokens:
                await asyncio.sleep(0.5)
                continue
            try:
                async with websockets.connect(
                    WS_URL, ping_interval=None, open_timeout=10, close_timeout=5,
                    ssl=ws_ssl.client_context(),
                ) as ws:
                    await ws.send(json.dumps({
                        "assets_ids": sorted(self._tokens), "type": "market",
                        "custom_feature_enabled": True,
                    }))
                    self._resub.clear()
                    backoff = _RECONNECT_BASE
                    ping = asyncio.ensure_future(self._ping_loop(ws))
                    try:
                        await self._recv_loop(ws)
                    finally:
                        ping.cancel()
                        with contextlib.suppress(asyncio.CancelledError, Exception):
                            await ping
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.debug(f"clob_ws connection error: {e}")
            if self._stop:
                break
            await asyncio.sleep(backoff)
            backoff = min(_RECONNECT_MAX, backoff * 2)

    async def _recv_loop(self, ws) -> None:
        while not self._stop:
            if self._resub.is_set():
                self._resub.clear()
                return
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=_PING_INTERVAL * 2)
            except asyncio.TimeoutError:
                return
            if raw == "PONG" or not isinstance(raw, (str, bytes)):
                continue
            for msg in _iter_messages(raw if isinstance(raw, str) else raw.decode()):
                self._dispatch(msg)

    async def _ping_loop(self, ws) -> None:
        while not self._stop:
            await asyncio.sleep(_PING_INTERVAL)
            with contextlib.suppress(Exception):
                await ws.send("PING")


feed = ClobMarketFeed()
