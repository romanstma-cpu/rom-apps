from __future__ import annotations

import asyncio

import pytest

import polymarket_api as api


def _fake_gamma(total: int, page_cap: int = 100):
    calls: list[int] = []

    async def _get(method, url, params=None, **_kw):
        params = params or {}
        offset = int(params.get("offset") or 0)
        want = int(params.get("limit") or page_cap)
        n = max(0, min(page_cap, want, total - offset))
        calls.append(offset)
        return {"markets": [{
            "conditionId": f"0x{offset + i:064x}",
            "question": f"market {offset + i}",
            "outcomes": '["Yes","No"]',
            "outcomePrices": '["0.5","0.5"]',
            "clobTokenIds": f'["{offset+i}a","{offset+i}b"]',
            "slug": f"market-{offset + i}",
        } for i in range(n)]}

    return _get, calls


def test_page_cap_below_requested_limit_still_paginates(monkeypatch):
    get, calls = _fake_gamma(total=350)
    monkeypatch.setattr(api, "_request", get)

    rows = asyncio.run(api.fetch_markets(limit=500))
    assert len(rows) == 100
    assert calls == [0]


def test_fetch_all_open_markets_reaches_past_the_first_page(monkeypatch):
    get, _calls = _fake_gamma(total=350)
    monkeypatch.setattr(api, "_request", get)

    out = asyncio.run(api.fetch_all_open_markets(max_pages=10))
    assert len(out) == 350, f"expected every market, got {len(out)}"


def test_pagination_stops_on_a_short_final_page(monkeypatch):
    get, calls = _fake_gamma(total=250)
    monkeypatch.setattr(api, "_request", get)

    out = asyncio.run(api.fetch_all_open_markets(max_pages=10))
    assert len(out) == 250
    assert calls == [0, 100, 200]


def test_max_pages_still_bounds_the_walk(monkeypatch):
    get, _calls = _fake_gamma(total=10_000)
    monkeypatch.setattr(api, "_request", get)

    out = asyncio.run(api.fetch_all_open_markets(max_pages=3))
    assert len(out) == 300


def test_exactly_one_full_page_then_empty(monkeypatch):
    get, calls = _fake_gamma(total=100)
    monkeypatch.setattr(api, "_request", get)

    out = asyncio.run(api.fetch_all_open_markets(max_pages=5))
    assert len(out) == 100
    assert calls == [0, 100]


def test_requested_limit_is_clamped_to_the_real_page_ceiling(monkeypatch):
    seen: dict = {}

    async def _get(method, url, params=None, **_kw):
        seen.update(params or {})
        return {"markets": []}

    monkeypatch.setattr(api, "_request", _get)
    asyncio.run(api.fetch_markets(limit=500))
    assert seen["limit"] == 100


@pytest.mark.parametrize("total,expected", [(0, 0), (1, 1), (99, 99), (100, 100)])
def test_small_result_sets(monkeypatch, total, expected):
    get, _ = _fake_gamma(total=total)
    monkeypatch.setattr(api, "_request", get)
    assert len(asyncio.run(api.fetch_all_open_markets(max_pages=5))) == expected
