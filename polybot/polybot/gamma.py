"""Polymarket Gamma API client — market discovery by category."""
from __future__ import annotations

import json
import logging

import requests

from .models import Market

log = logging.getLogger(__name__)
GAMMA = "https://gamma-api.polymarket.com"


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
            tokens = m.get("clobTokenIds")
            if isinstance(tokens, str):
                try:
                    tokens = json.loads(tokens)
                except ValueError:
                    tokens = None
            if not tokens or len(tokens) < 2:
                continue
            out.append(Market(
                condition_id=m.get("conditionId", ""),
                question=m.get("question", ""),
                category=category,
                yes_token=tokens[0],
                no_token=tokens[1],
                volume_24h=float(m.get("volume24hr") or 0),
                end_date=m.get("endDate", "") or "",
            ))
        return out

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
