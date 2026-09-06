"""Polymarket Gamma API client — market discovery by category."""
from __future__ import annotations

import json
import logging

import requests

from .http import make_session
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


def parse_market(m: dict, category: str,
                 event_slug: str | None = None) -> Market | None:
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
    if event_slug is None:
        # Discovery now reads markets out of their event, so the slug is
        # handed in and authoritative. This fallback covers a bare market
        # row, where the event is at best nested one deep and often absent.
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
        self.http = session or make_session()

    def _get(self, path: str, **params) -> list | dict:
        r = self.http.get(f"{GAMMA}{path}", params=params, timeout=20)
        r.raise_for_status()
        return r.json()

    def events_for_tag(self, tag_slug: str, limit: int) -> list[dict]:
        """Open events carrying a tag, most-traded first.

        /markets accepts tag_slug and silently ignores it. A real tag, a
        different real tag and an invented one all return the same global
        most-active list, so every "category" this bot thought it watched
        was that one list wearing whichever label queried it first — which
        is how a market about an Iranian blockade ended up filed under
        crypto, and why per-category caps and overrides never bound
        anything. /events honours the filter, and each event carries its
        own markets, so sibling grouping becomes exact instead of a guess
        at a slug.
        """
        try:
            raw = self._get(
                "/events", closed="false", active="true",
                tag_slug=tag_slug.lower(), limit=limit,
                order="volume24hr", ascending="false",
            )
        except requests.RequestException as exc:
            log.warning("Gamma events request failed for %s: %s", tag_slug, exc)
            return []
        return [e for e in (raw if isinstance(raw, list) else [])
                if isinstance(e, dict)]

    def markets_for_category(self, category: str, limit: int = 20,
                             events_limit: int = 12, max_per_event: int = 4,
                             min_volume_24h: float = 0.0) -> list[Market]:
        """Most-active open binaries in a category, capped per event.

        The per-event cap is not cosmetic. One event can carry 128 markets —
        every candidate in a presidential race — and six politics events
        returned 322 markets when this was measured. Uncapped, one crowded
        event fills the entire watch list with mutually exclusive outcomes
        of a single question, which risk.max_per_event would then refuse to
        trade anyway: a universe that looks full and is one bet wide.
        """
        out: list[Market] = []
        for event in self.events_for_tag(category, events_limit):
            slug = str(event.get("slug") or "")
            rows = event.get("markets")
            picked: list[Market] = []
            for row in rows if isinstance(rows, list) else []:
                if not isinstance(row, dict) or row.get("closed"):
                    continue
                parsed = parse_market(row, category, event_slug=slug)
                if parsed and parsed.volume_24h >= min_volume_24h:
                    picked.append(parsed)
            picked.sort(key=lambda m: m.volume_24h, reverse=True)
            out.extend(picked[:max_per_event])
        out.sort(key=lambda m: m.volume_24h, reverse=True)
        return out[:limit]

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
                 limit_per_category: int, min_volume_24h: float,
                 events_per_category: int = 12,
                 max_markets_per_event: int = 4) -> list[Market]:
        """The watch list: each category's most-traded open binaries.

        Dedup across categories is now a genuine overlap — a market really
        can carry both `politics` and `geopolitics`. It used to be the
        mechanism that let the first category in the list claim the entire
        universe and stamp its name on everything in it.
        """
        seen: set[str] = set()
        markets: list[Market] = []
        for cat in categories:
            if cat in exclude:
                continue
            for m in self.markets_for_category(
                    cat, limit=limit_per_category,
                    events_limit=events_per_category,
                    max_per_event=max_markets_per_event,
                    min_volume_24h=min_volume_24h):
                if m.condition_id in seen:
                    continue
                seen.add(m.condition_id)
                markets.append(m)
        return markets
