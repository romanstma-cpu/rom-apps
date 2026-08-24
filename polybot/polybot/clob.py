"""Polymarket CLOB public data client — books, midpoints, trade tape."""
from __future__ import annotations

import logging
import time

import requests

from .models import Snapshot

log = logging.getLogger(__name__)
CLOB = "https://clob.polymarket.com"
DATA_API = "https://data-api.polymarket.com"


class ClobClient:
    def __init__(self, session: requests.Session | None = None):
        self.http = session or requests.Session()

    def _get(self, base: str, path: str, **params):
        r = self.http.get(f"{base}{path}", params=params, timeout=20)
        r.raise_for_status()
        return r.json()

    def snapshot(self, token_id: str, volume_24h: float = 0.0) -> Snapshot | None:
        """Build a Snapshot from the order book of the YES token."""
        try:
            book = self._get(CLOB, "/book", token_id=token_id)
        except requests.RequestException as exc:
            log.debug("book fetch failed for %s: %s", token_id, exc)
            return None
        bids = book.get("bids") or []
        asks = book.get("asks") or []
        if not bids or not asks:
            return None
        best_bid = max(float(b["price"]) for b in bids)
        best_ask = min(float(a["price"]) for a in asks)
        bid_depth = sum(float(b["price"]) * float(b["size"]) for b in bids)
        ask_depth = sum(float(a["price"]) * float(a["size"]) for a in asks)
        total = bid_depth + ask_depth
        return Snapshot(
            ts=time.time(),
            mid=round((best_bid + best_ask) / 2, 4),
            bid=best_bid,
            ask=best_ask,
            volume_24h=volume_24h,
            imbalance=(bid_depth - ask_depth) / total if total else 0.0,
        )

    def recent_trades(self, condition_id: str, limit: int = 50) -> list[dict]:
        """Public trade tape for a market (data API; no auth needed)."""
        try:
            raw = self._get(DATA_API, "/trades", market=condition_id,
                            limit=limit)
        except requests.RequestException as exc:
            log.debug("trades fetch failed for %s: %s", condition_id, exc)
            return []
        return raw if isinstance(raw, list) else []
