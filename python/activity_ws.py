from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import time
from collections import deque
from typing import Optional

logger = logging.getLogger("activity_ws")

try:
    import websockets  # type: ignore
    _WS_IMPORT_OK = True
except Exception:  # pragma: no cover - websockets missing
    websockets = None  # type: ignore
    _WS_IMPORT_OK = False

_URL = os.environ.get("ROM_ACTIVITY_WS_URL") or "wss://ws-live-data.polymarket.com"
_DISABLED = os.environ.get("ROM_ACTIVITY_WS", "1").strip().lower() in (
    "0", "off", "false", "no",
)

_PING_INTERVAL_SEC = 5.0
_SILENT_TIMEOUT_SEC = 60.0
_RECONNECT_MAX_SEC = 60.0
_HITS_MAX = 200


class _Client:
    def __init__(self) -> None:
        self.connected: bool = False
        self._stop: bool = False
        self._task: Optional[asyncio.Task] = None
        self._ws = None
        self.last_msg_t: float = 0.0
        self.last_hit_t: float = 0.0
        self.watch: set[str] = set()
        self.hits: deque = deque(maxlen=_HITS_MAX)


    def start(self) -> None:
        if _DISABLED or not _WS_IMPORT_OK:
            if not _WS_IMPORT_OK and not _DISABLED:
                logger.warning("activity_ws: `websockets` not installed — copy stays on polling")
            return
        self._stop = False
        loop = asyncio.get_event_loop()
        if self._task is None or self._task.done():
            self._task = loop.create_task(self._run(), name="activity_ws")
            logger.info("activity_ws: starting (polymarket rtds / trade tape)")

    async def stop(self) -> None:
        self._stop = True
        ws = self._ws
        self._ws = None
        if ws is not None:
            try:
                await ws.close()
            except Exception:
                pass
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        self._task = None
        self.connected = False

    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def set_watch(self, wallets) -> None:
        try:
            self.watch = {
                str(w).strip().lower() for w in (wallets or [])
                if isinstance(w, str) and str(w).strip()
            }
        except Exception:
            self.watch = set()


    async def _run(self) -> None:
        attempt = 0
        while not self._stop:
            try:
                await self._connect_once()
                attempt = 0
            except asyncio.CancelledError:
                raise
            except Exception as e:
                attempt = min(attempt + 1, 16)
                backoff = min(2.0 ** attempt, _RECONNECT_MAX_SEC)
                backoff *= random.uniform(0.75, 1.25)
                logger.warning(
                    f"activity_ws: disconnected ({type(e).__name__}: {e}); "
                    f"reconnect in {backoff:.0f}s"
                )
                self.connected = False
                try:
                    await asyncio.sleep(backoff)
                except asyncio.CancelledError:
                    raise

    async def _connect_once(self) -> None:
        import ws_ssl
        kwargs = dict(ping_interval=None, close_timeout=5, max_size=2 ** 22,
                      ssl=ws_ssl.client_context())
        async with websockets.connect(_URL, **kwargs) as ws:
            self._ws = ws
            self.connected = True
            self.last_msg_t = time.time()
            await ws.send(json.dumps({
                "action": "subscribe",
                "subscriptions": [{"topic": "activity", "type": "trades"}],
            }))
            logger.info(f"activity_ws: connected → {_URL}")
            last_ping = time.time()
            while not self._stop:
                if time.time() - last_ping >= _PING_INTERVAL_SEC:
                    try:
                        await ws.send("PING")
                    except Exception:
                        return
                    last_ping = time.time()
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                except asyncio.TimeoutError:
                    if time.time() - self.last_msg_t > _SILENT_TIMEOUT_SEC:
                        logger.warning("activity_ws: silent link — forcing reconnect")
                        return
                    continue
                self.last_msg_t = time.time()
                if raw == "PONG":
                    continue
                try:
                    self.handle_message(json.loads(raw))
                except Exception as e:
                    logger.debug(f"activity_ws: handle error: {e}")
        self.connected = False
        self._ws = None


    def handle_message(self, m) -> None:
        if not isinstance(m, dict):
            return
        p = m.get("payload")
        items = p if isinstance(p, list) else [p]
        for it in items:
            if not isinstance(it, dict):
                continue
            w = str(it.get("proxyWallet") or "").strip().lower()
            side = str(it.get("side") or "").upper()
            if not w or side not in ("BUY", "SELL") or w not in self.watch:
                continue
            self.last_hit_t = time.time()
            self.hits.append({
                "wallet": w, "side": side,
                "size": it.get("size"), "price": it.get("price"),
                "conditionId": it.get("conditionId"),
                "slug": it.get("slug") or it.get("eventSlug") or "",
                "outcome": it.get("outcome"),
                "at": self.last_hit_t,
            })


    def has_hits(self) -> bool:
        return len(self.hits) > 0

    def drain_hits(self) -> list[dict]:
        out = list(self.hits)
        self.hits.clear()
        return out

    def stats(self) -> dict:
        return {
            "enabled": not _DISABLED and _WS_IMPORT_OK,
            "connected": self.connected,
            "watching": len(self.watch),
            "lastMsgAgeSec": round(max(0.0, time.time() - self.last_msg_t), 1)
            if self.connected else None,
            "lastHitAgeSec": round(max(0.0, time.time() - self.last_hit_t), 1)
            if self.last_hit_t else None,
        }


_client = _Client()


def start() -> None:
    _client.start()


async def stop() -> None:
    await _client.stop()


def is_connected() -> bool:
    return _client.connected


def is_running() -> bool:
    return _client.is_running()


def set_watch(wallets) -> None:
    _client.set_watch(wallets)


def has_hits() -> bool:
    return _client.has_hits()


def drain_hits() -> list[dict]:
    return _client.drain_hits()


def stats() -> dict:
    return _client.stats()
