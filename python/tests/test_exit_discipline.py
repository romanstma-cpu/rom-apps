"""Exits must be priced from a live quote, never dumped blind.

The previous liquidation path fell back to a 1c sell limit whenever a bid was
unavailable, which turns a temporary data gap into a near-total realized loss
on a position that may still be worth most of its cost. An exit now requires
an executable quote and concedes at most a configured budget below the touch.
"""
from __future__ import annotations

import asyncio
import itertools

import pytest

import db
import trader
from conftest import quote_with_depth
from config import merge_with_defaults

_ids = itertools.count(9000)


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    dbfile = tmp_path / "exit-discipline.db"
    monkeypatch.setattr(db, "db_path", lambda: dbfile)
    db.init_db()
    monkeypatch.setattr(trader, "get_env", lambda: "mainnet")
    return dbfile


@pytest.fixture
def cfg():
    c = merge_with_defaults({})
    c["network"] = "mainnet"
    return c


def seed_filled(**over) -> int:
    n = next(_ids)
    row = {
        "signal_source": "whale", "signal_id": n, "ticker": over.get("ticker", "EXIT"),
        "event_ticker": "EV", "direction": over.get("direction", "yes"),
        "target_contracts": 10, "limit_price_cents": 50,
        "filled_contracts": over.get("filled_contracts", 10),
        "cost_usd": over.get("cost_usd", 5.0),
        "client_order_id": f"ex-{n}", "status": "filled", "network": "mainnet",
    }
    with db.get_db() as conn:
        return db.insert_bot_position(conn, row)


def install(monkeypatch, *, quote, orders_allowed=True, sold_at=None):
    """Install exit stubs and record every order the code attempts."""
    placed: list[dict] = []

    async def _quote(_ticker, _side=None):
        if isinstance(quote, Exception):
            raise quote
        return quote

    async def _place(**kw):
        if not orders_allowed:
            pytest.fail(f"exit must not place an order here: {kw}")
        placed.append(kw)
        return {"order": {"order_id": "OID", "status": "matched"}}

    async def _confirm(_oid, qty, px):
        return qty, float(px if sold_at is None else sold_at)

    async def _cancel(_oid):
        return True

    monkeypatch.setattr(trader, "get_quote", _quote)
    monkeypatch.setattr(trader, "place_limit_order", _place)
    monkeypatch.setattr(trader, "_confirm_sell", _confirm)
    monkeypatch.setattr(trader, "cancel_order", _cancel)
    return placed


def liquidate(pid, cfg, reason="flatten"):
    with db.get_db() as conn:
        pos = db.fetch_position_by_id(conn, pid)
    return asyncio.run(trader._liquidate_position(pos, cfg, reason=reason))


def test_missing_bid_never_sells_at_one_cent(fresh_db, cfg, monkeypatch):
    """The regression this upgrade exists to remove."""
    pid = seed_filled()
    install(monkeypatch,
            quote=quote_with_depth({"bid_cents": None, "ask_cents": None}),
            orders_allowed=False)
    sold, proceeds = liquidate(pid, cfg)
    assert (sold, proceeds) == (0, 0.0)
    with db.get_db() as conn:
        assert db.fetch_position_by_id(conn, pid)["filled_contracts"] == 10


def test_quote_failure_keeps_the_position(fresh_db, cfg, monkeypatch):
    pid = seed_filled()
    install(monkeypatch, quote=RuntimeError("book unavailable"), orders_allowed=False)
    assert liquidate(pid, cfg) == (0, 0.0)


def test_zero_bid_is_not_a_tradable_price(fresh_db, cfg, monkeypatch):
    pid = seed_filled()
    install(monkeypatch,
            quote=quote_with_depth({"bid_cents": 0, "ask_cents": 1}),
            orders_allowed=False)
    assert liquidate(pid, cfg) == (0, 0.0)


def test_exit_concedes_only_the_configured_budget(fresh_db, cfg, monkeypatch):
    cfg["exit_price_loss_budget_cents"] = 2
    pid = seed_filled()
    placed = install(monkeypatch,
                     quote=quote_with_depth({"bid_cents": 80, "ask_cents": 82}))
    liquidate(pid, cfg)
    assert placed and placed[0]["price_cents"] == 78


def test_zero_budget_sells_at_the_touch(fresh_db, cfg, monkeypatch):
    cfg["exit_price_loss_budget_cents"] = 0
    pid = seed_filled()
    placed = install(monkeypatch,
                     quote=quote_with_depth({"bid_cents": 80, "ask_cents": 82}))
    liquidate(pid, cfg)
    assert placed and placed[0]["price_cents"] == 80


def test_exit_size_is_bounded_by_displayed_bid_depth(fresh_db, cfg, monkeypatch):
    cfg["exit_price_loss_budget_cents"] = 0
    pid = seed_filled(filled_contracts=10)
    placed = install(monkeypatch, quote={
        "bid_cents": 80, "ask_cents": 82,
        "bid_levels": [[80, 4]], "ask_levels": [[82, 100]],
    })
    liquidate(pid, cfg)
    assert placed and placed[0]["count"] == 4


def test_no_bid_depth_holds_rather_than_sells(fresh_db, cfg, monkeypatch):
    cfg["exit_price_loss_budget_cents"] = 0
    pid = seed_filled()
    install(monkeypatch, quote={
        "bid_cents": 80, "ask_cents": 82,
        "bid_levels": [[80, 0]], "ask_levels": [[82, 100]],
    }, orders_allowed=False)
    assert liquidate(pid, cfg) == (0, 0.0)


def test_a_sound_quote_still_exits_normally(fresh_db, cfg, monkeypatch):
    cfg["exit_price_loss_budget_cents"] = 0
    pid = seed_filled(cost_usd=5.0, filled_contracts=10)
    install(monkeypatch, quote=quote_with_depth({"bid_cents": 80, "ask_cents": 82}))
    sold, proceeds = liquidate(pid, cfg)
    assert sold == 10
    assert proceeds == pytest.approx(8.0)


def test_budget_never_prices_below_one_cent(fresh_db, cfg, monkeypatch):
    cfg["exit_price_loss_budget_cents"] = 50
    pid = seed_filled()
    placed = install(monkeypatch,
                     quote=quote_with_depth({"bid_cents": 3, "ask_cents": 5}))
    liquidate(pid, cfg)
    assert placed and placed[0]["price_cents"] >= 1


def test_invalid_budget_setting_falls_back_to_the_default(fresh_db, cfg, monkeypatch):
    cfg["exit_price_loss_budget_cents"] = "not a number"
    pid = seed_filled()
    placed = install(monkeypatch,
                     quote=quote_with_depth({"bid_cents": 80, "ask_cents": 82}))
    liquidate(pid, cfg)
    assert placed and placed[0]["price_cents"] == 78
