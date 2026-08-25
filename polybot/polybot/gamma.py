"""Polymarket Gamma API client — market discovery by category."""
from __future__ import annotations

import json
import logging

import requests

from .models import Market

log = logging.getLogger(__name__)
GAMMA = "https://gamma-api.polymarket.com"


def _json_field(m: dict, key: str) -> list | None:
    """Gamma returns some list fields as JSON-encoded strings."""
    val = m.get(key)
    if isinstance(val, str):
        try:
            val = json.loads(val)
        except ValueError:
            return None
    return val if isinstance(val, list) else None


def parse_market(m: dict, category: str) -> Market | None:
    """One Gamma market row → Market, or None if it is not a clean binary.

    The outcomes list must literally be ["yes", "no"]: clobTokenIds are in
    outcome order, so a market that omits its outcomes could hand us the NO
    token as tokens[0] and every trade on it would be inverted. Refusing the
    ambiguous row costs one market; trading it inverted costs money.
    """
    tokens = _json_field(m, "clobTokenIds")
    if not tokens or len(tokens) != 2:
        return None
    outcomes = [str(o).lower() for o in _json_field(m, "outcomes") or []]
    if outcomes != ["yes", "no"]:
        return None
    events = m.get("events")
    event_slug = ""
    if isinstance(events, list) and events and isinstance(events[0], dict):
        event_slug = str(events[0].get("slug") or "")
    return Market(
        condition_id=m.get("conditionId", ""),
        question=m.get("question", ""),
        category=category,
        yes_token=tokens[0],
        no_token=tokens[1],
        volume_24h=float(m.get("volume24hr") or 0),
        end_date=m.get("endDate", "") or "",
        event_slug=event_slug,
    )


class GammaClient:
    def __init__(self, session: requests.Session | None = None):
        self.http = session or requests.Session()

    def _get(self, path: str, **params) -> list | dict:
        r = self.http.get(f"{GAMMA}{path}", params=params, timeout=20)
        r.raise_for_status()
        return r.json()

    def markets_for_category(self, category: str, limit: int = 20) -> list[Market]:
        """Most-active open markets tagged with a category slug."""
        try:
            raw = self._get(
                "/markets", closed="false", active="true",
                tag_slug=category.lower(), limit=limit,
                order="volume24hr", ascending="false",
            )
        except requests.RequestException as exc:
            log.warning("Gamma request failed for %s: %s", category, exc)
            return []
        out: list[Market] = []
        for m in raw if isinstance(raw, list) else []:
            parsed = parse_market(m, category)
            if parsed:
                out.append(parsed)
        return out

    def resolution(self, condition_id: str) -> tuple[bool, float | None]:
        """Whether a market has closed, and the YES outcome price if so.

        Used to settle positions whose order book has disappeared: a market
        that resolves stops serving a book, and without this check the
        position would sit at its last mark forever with the cash locked.
        Returns (False, None) on any doubt — holding is recoverable, booking
        a wrong settlement is not.
        """
        try:
            raw = self._get("/markets", condition_ids=condition_id)
        except requests.RequestException as exc:
            log.debug("resolution check failed for %s: %s", condition_id, exc)
            return False, None
        rows = raw if isinstance(raw, list) else []
        if not rows or not isinstance(rows[0], dict):
            return False, None
        m = rows[0]
        if not m.get("closed"):
            return False, None
        prices = _json_field(m, "outcomePrices")
        if not prices or len(prices) != 2:
            return True, None
        try:
            yes_price = float(prices[0])
        except (TypeError, ValueError):
            return True, None
        # A resolved binary settles at 0 or 1; anything else means the
        # market is closed but not yet resolved, so keep waiting.
        if yes_price not in (0.0, 1.0):
            return True, None
        return True, yes_price

    def discover(self, categories: list[str], exclude: list[str],
                 limit_per_category: int, min_volume_24h: float) -> list[Market]:
        seen: set[str] = set()
        markets: list[Market] = []
        for cat in categories:
            if cat in exclude:
                continue
            for m in self.markets_for_category(cat, limit_per_category):
                if m.condition_id in seen or m.volume_24h < min_volume_24h:
                    continue
                seen.add(m.condition_id)
                markets.append(m)
        return markets
