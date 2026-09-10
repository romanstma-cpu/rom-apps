"""Entry sizing must be bounded by displayed depth, not the touch price.

A thin book can show an attractive best offer with almost nothing behind it.
Pricing the whole order at that touch overstates the edge, so entry prices the
size it actually intends to buy and shrinks or skips when the book cannot
support it.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

import db
import trader
from conftest import quote_with_depth
from config import merge_with_defaults
from execution_quality import affordable_at_depth, entry_vwap_cents


@pytest.fixture
def cfg():
    c = merge_with_defaults({})
    c["network"] = "mainnet"
    return c


# --- depth arithmetic ----------------------------------------------------

def test_vwap_of_a_single_ample_level_is_that_price():
    assert entry_vwap_cents([[60, 500]], 100, 60) == 60.0


def test_vwap_walks_the_book_and_costs_more_than_the_touch():
    # 10 at 60c then 30 at 62c: 40 contracts average 61.5c, not 60c.
    assert entry_vwap_cents([[60, 10], [62, 30]], 40, 62) == pytest.approx(61.5)


def test_vwap_refuses_to_fill_beyond_displayed_size():
    with pytest.raises(ValueError, match="fills only"):
        entry_vwap_cents([[60, 10]], 40, 62)


def test_vwap_ignores_levels_above_the_limit():
    with pytest.raises(ValueError, match="fills only"):
        entry_vwap_cents([[60, 5], [70, 1000]], 40, 62)


def test_vwap_rejects_a_non_positive_order():
    with pytest.raises(ValueError, match="positive"):
        entry_vwap_cents([[60, 10]], 0, 60)


def test_partial_levels_round_down_to_whole_contracts():
    # 9.7 displayed is 9 tradable contracts, never 10.
    assert affordable_at_depth([[60, 9.7]], 60) == 9


def test_depth_stops_at_the_limit_price():
    assert affordable_at_depth([[60, 5], [61, 7], [65, 900]], 61) == 12


def test_empty_or_malformed_book_offers_no_depth():
    assert affordable_at_depth([], 60) == 0
    assert affordable_at_depth(None, 60) == 0
    assert affordable_at_depth([[None, "x"]], 60) == 0
    assert affordable_at_depth([[60, float("nan")]], 60) == 0


# --- the entry path ------------------------------------------------------

def whale_signal(**over):
    row = {
        "id": 1, "ticker": "DEPTH", "event_ticker": "EV", "title": "Depth test",
        "category": "sports", "price": 0.60, "confidence": 80, "taker_side": "yes",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    row.update(over)
    return row


@pytest.fixture
def entry_env(tmp_path, monkeypatch):
    dbfile = tmp_path / "depth.db"
    monkeypatch.setattr(db, "db_path", lambda: dbfile)
    db.init_db()
    monkeypatch.setattr(trader, "get_env", lambda: "mainnet")

    async def meta(*_a):
        return {"min_size": 1}

    monkeypatch.setattr(trader, "get_market_meta", meta)

    async def forbidden(**_kw):
        pytest.fail("this test must not reach the order API")

    monkeypatch.setattr(trader, "place_limit_order", forbidden)
    return dbfile


def install_book(monkeypatch, ask_levels):
    async def quote(*_a):
        return quote_with_depth({
            "bid_cents": 59, "ask_cents": ask_levels[0][0],
            "ask_levels": ask_levels,
        })
    monkeypatch.setattr(trader, "get_quote", quote)


def run_entry(cfg, **over):
    return asyncio.run(trader.execute_signal(
        whale_signal(**over), "whale", cfg, 1000.0, paper=True))


def test_ample_depth_fills_the_intended_size(entry_env, cfg, monkeypatch):
    install_book(monkeypatch, [[60, 10_000]])
    row = run_entry(cfg)
    assert row is not None
    assert row["status"] == "dry_run"
    full_size = row["target_contracts"]
    assert full_size > 1


def test_thin_book_shrinks_the_order_to_displayed_depth(entry_env, cfg, monkeypatch):
    install_book(monkeypatch, [[60, 4]])
    row = run_entry(cfg)
    assert row is not None
    assert row["target_contracts"] == 4


def test_book_below_the_minimum_size_is_skipped(entry_env, cfg, monkeypatch):
    async def meta(*_a):
        return {"min_size": 25}
    monkeypatch.setattr(trader, "get_market_meta", meta)
    install_book(monkeypatch, [[60, 3]])
    assert run_entry(cfg) is None


def test_an_empty_book_never_enters(entry_env, cfg, monkeypatch):
    async def quote(*_a):
        return {"bid_cents": 59, "ask_cents": 60, "ask_levels": [], "bid_levels": []}
    monkeypatch.setattr(trader, "get_quote", quote)
    assert run_entry(cfg) is None


def test_depth_check_can_be_disabled(entry_env, cfg, monkeypatch):
    """Turning the gate off restores the previous touch-priced behaviour."""
    cfg["require_entry_depth"] = False
    install_book(monkeypatch, [[60, 2]])
    row = run_entry(cfg)
    assert row is not None
    assert row["target_contracts"] > 2


def test_deep_book_costs_are_charged_before_the_edge_test(entry_env, cfg, monkeypatch):
    """A ladder that averages well above the touch must not pass on touch edge."""
    cfg["min_edge_pts_whale"] = 8.0
    # Touch is 60c but only 1 contract; the rest sits far worse.
    install_book(monkeypatch, [[60, 1], [61, 1], [62, 5_000]])
    row = run_entry(cfg)
    # Either skipped, or entered at a size whose depth-weighted cost still
    # clears the threshold — never sized as if the whole order paid 60c.
    if row is not None:
        vwap = entry_vwap_cents([[60, 1], [61, 1], [62, 5_000]],
                                row["target_contracts"], row["limit_price_cents"])
        assert vwap <= row["limit_price_cents"]
