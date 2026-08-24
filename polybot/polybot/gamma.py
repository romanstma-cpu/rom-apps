"""Polymarket Gamma API client — market discovery by category."""
from __future__ import annotations

import json
import logging
import threading

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


def _parse_market(m: dict, category: str) -> Market | None:
    """Build a Market from a Gamma market object, or None if unusable."""
    tokens = _json_field(m, "clobTokenIds")
    if not tokens or len(tokens) != 2:
        return None
    # only binary Yes/No markets: the bot reasons in YES-token terms
    outcomes = [str(o).lower() for o in _json_field(m, "outcomes") or []]
    if outcomes and outcomes != ["yes", "no"]:
        return None
    if m.get("closed") or m.get("active") is False:
        return None
    condition_id = m.get("conditionId") or ""
    if not condition_id:
        return None
    return Market(
        condition_id=condition_id,
        question=m.get("question", ""),
        category=category,
        yes_token=str(tokens[0]),
        no_token=str(tokens[1]),
        volume_24h=float(m.get("volume24hr") or m.get("volumeNum") or 0),
        end_date=m.get("endDate", "") or "",
    )


class GammaClient:
    def __init__(self, session: requests.Session | None = None):
        self._local = threading.local()
        self._shared = session

    @property
    def http(self) -> requests.Session:
        if self._shared is not None:
            return self._shared
        if not hasattr(self._local, "session"):
            self._local.session = requests.Session()
        return self._local.session

    def _get(self, path: str, **params) -> list | dict:
        r = self.http.get(f"{GAMMA}{path}", params=params, timeout=20)
        r.raise_for_status()
        return r.json()

    def markets_for_category(self, category: str, limit: int = 20) -> list[Market]:
        """Most-active open markets in a category.

        Tag filtering lives on the /events endpoint, so that is the primary
        path: each event carries the markets that belong to it. Some category
        slugs are not event tags, so an empty result falls back to a tagged
        /markets query rather than silently watching nothing.
        """
        slug = category.lower()
        markets = self._from_events(slug, limit)
        if not markets:
            markets = self._from_markets(slug, limit)
        if not markets:
            log.warning("no open markets found for category %r — check the "
                        "slug against polymarket.com's category URLs", category)
        return markets[:limit]

    def _from_events(self, slug: str, limit: int) -> list[Market]:
        try:
            raw = self._get("/events", closed="false", active="true",
                            tag_slug=slug, limit=limit, order="volume24hr",
                            ascending="false")
        except requests.RequestException as exc:
            log.warning("Gamma /events failed for %s: %s", slug, exc)
            return []
        out: list[Market] = []
        for ev in raw if isinstance(raw, list) else []:
            for m in ev.get("markets") or []:
                parsed = _parse_market(m, slug)
                if parsed:
                    out.append(parsed)
        out.sort(key=lambda m: m.volume_24h, reverse=True)
        return out

    def _from_markets(self, slug: str, limit: int) -> list[Market]:
        try:
            raw = self._get("/markets", closed="false", active="true",
                            tag_slug=slug, limit=limit, order="volume24hr",
                            ascending="false")
        except requests.RequestException as exc:
            log.warning("Gamma /markets failed for %s: %s", slug, exc)
            return []
        out = [_parse_market(m, slug) for m in raw if isinstance(raw, list)]
        return [m for m in out if m]

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
