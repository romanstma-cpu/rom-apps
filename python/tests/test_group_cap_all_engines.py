"""UPGRADE-5's cap is account-wide only if every engine consults it.

`account_risk.GROUP_SQL` counts main-strategy and crypto15m positions, so all
three engines' fills *fill* the correlated-exposure group. Only `trader` ever
*read* the cap. crypto15m and copy_trader could therefore open past a limit
their own positions were helping to reach -- and crypto15m is the engine most
exposed to it, because every 15m window on one asset shares a series and moves
with the same spot price.

These tests are about the gate, not about sizing arithmetic: does an engine
refuse an entry when the group is full, does it shrink one when the group is
partly used, and does it stay out of the way when the control is switched off.
"""
from __future__ import annotations

import asyncio
import itertools
from datetime import datetime, timedelta, timezone

import pytest

import account_risk
import copy_trader
import crypto15m
import crypto15m_trader as ct
import db
import polymarket_api
import trader
from config import merge_with_defaults

ENV = "mainnet"
_ids = itertools.count(1)


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    dbfile = tmp_path / "groupcap.db"
    monkeypatch.setattr(db, "db_path", lambda: dbfile)
    db.init_db()
    ct._stop_retry_at.clear()
    copy_trader._copy_cooldown.clear()
    copy_trader._exit_retry_at.clear()
    return dbfile


@pytest.fixture
def env_net(monkeypatch):
    monkeypatch.setattr(trader, "get_env", lambda: ENV)
    return ENV


@pytest.fixture
def balance(monkeypatch):
    """$1,000 of buying power, read the way the engines read it."""
    async def _bal(_cfg, force=False):
        return 100_000, 0
    monkeypatch.setattr(trader, "refresh_balance", _bal)
    monkeypatch.setattr(trader, "last_balance_read_ok", lambda: True)
    return 1000.0


def run_async(coro):
    return asyncio.run(coro)


def seed_c15(series, cost_usd, *, ticker=None, status="filled"):
    n = next(_ids)
    with db.get_db() as conn:
        conn.execute(
            "INSERT INTO crypto15m_positions (asset, series, ticker, side, direction,"
            " target_contracts, filled_contracts, entry_limit_cents, cost_usd,"
            " client_order_id, status, resolved, network, dry_run)"
            " VALUES ('BTC',?,?,'up','yes',10,10,50,?,?,?,0,?,0)",
            (series, ticker or f"{series}-seed{n}", cost_usd, f"c15-{n}", status, ENV),
        )
        conn.commit()


def seed_market(ticker, series):
    with db.get_db() as conn:
        db.upsert_market(conn, {
            "ticker": ticker, "event_ticker": "", "series_ticker": series,
            "slug": ticker, "title": ticker, "yes_sub_title": "",
            "category": "crypto", "status": "open", "close_time": "",
            "volume": 100_000, "volume_24h": 50_000, "open_interest": 1_000,
            "yes_bid": 0.5, "yes_ask": 0.52, "last_price": 0.5,
            "result": "", "settlement_value": None,
        })


def seed_main_position(series, cost_usd, *, ticker=None):
    """Main-strategy exposure in `series`.

    Seeded through `bot_positions` rather than `crypto15m_positions` so the
    crypto15m engine sees a full group without also seeing one of its own
    assets already open -- the per-asset rule would block that entry for a
    different reason and the cap would never be reached.
    """
    tkr = ticker or f"{series}-MAIN{next(_ids)}"
    seed_market(tkr, series)
    n = next(_ids)
    with db.get_db() as conn:
        db.insert_bot_position(conn, {
            "signal_source": "whale", "signal_id": n, "ticker": tkr,
            "event_ticker": "", "direction": "yes", "target_contracts": 10,
            "limit_price_cents": 50, "filled_contracts": 10,
            "cost_usd": cost_usd, "client_order_id": f"gc-{n}",
            "status": "filled", "network": ENV,
        })
    return tkr


# --- the shared definition -------------------------------------------------
#
# All three engines already computed cash-plus-filled-cost separately. A cap
# is only account-wide if they keep computing the same number.

def test_the_cap_bankroll_is_cash_plus_filled_cost():
    assert account_risk.cap_bankroll_usd(600.0, 400.0) == 1000.0


@pytest.mark.parametrize("cash,filled,expected", [
    (-50.0, 400.0, 400.0),          # an overdrawn balance does not lend the cap money
    (600.0, -400.0, 600.0),
    (float("nan"), 400.0, 400.0),   # unreadable inputs contribute nothing
    (float("inf"), 400.0, 400.0),
    (None, None, 0.0),
])
def test_the_cap_bankroll_refuses_to_be_inflated(cash, filled, expected):
    assert account_risk.cap_bankroll_usd(cash, filled) == expected


def test_every_engine_measures_the_same_number(fresh_db, env_net):
    """The regression this helper exists to prevent: three formulas drifting."""
    with db.get_db() as conn:
        filled = db.current_filled_exposure_usd(conn, ENV)
    assert account_risk.cap_bankroll_usd(1000.0, filled) == \
        max(0.0, 1000.0) + max(0.0, filled)


# --- keying a prospective entry to the bucket it will land in --------------

@pytest.mark.parametrize("series,ticker,expected", [
    ("KXBTC15M", "KXBTC15M-T1", "KXBTC15M"),
    ("", "KXBTC15M-T1", "KXBTC15M-T1"),      # GROUP_SQL falls back to the ticker
    (None, "KXBTC15M-T1", "KXBTC15M-T1"),
    ("  KXBTC15M  ", "T1", "KXBTC15M"),
])
def test_crypto15m_group_key_matches_group_sql(series, ticker, expected):
    assert account_risk.crypto15m_group_key(series, ticker) == expected


def test_the_prospective_key_finds_the_row_it_will_join(fresh_db, env_net):
    """Round-trip: key an entry, then confirm its own fill lands in that key.

    If these ever disagree the cap measures one group's entry against another
    group's usage, which is worse than having no cap at all.
    """
    seed_c15("KXBTC15M", 40.0, ticker="KXBTC15M-T1")
    key = account_risk.crypto15m_group_key("KXBTC15M", "KXBTC15M-T1")
    with db.get_db() as conn:
        assert account_risk.group_exposure_usd(conn, ENV)[key] == 40.0


def test_a_seriesless_row_is_keyed_by_ticker_at_both_ends(fresh_db, env_net):
    seed_c15("", 25.0, ticker="ORPHAN-T9")
    key = account_risk.crypto15m_group_key("", "ORPHAN-T9")
    with db.get_db() as conn:
        assert account_risk.group_exposure_usd(conn, ENV)[key] == 25.0


# --- budget arithmetic -----------------------------------------------------

def test_a_supplied_usage_map_is_honoured(fresh_db, env_net):
    cfg = merge_with_defaults({"max_group_exposure_fraction": 0.10})
    budget = account_risk.group_budget_for_key(
        None, ENV, "G", 1000.0, cfg, used={"G": 30.0})
    assert budget == pytest.approx(70.0)


def test_a_full_group_yields_no_budget(fresh_db, env_net):
    cfg = merge_with_defaults({"max_group_exposure_fraction": 0.10})
    assert account_risk.group_budget_for_key(
        None, ENV, "G", 1000.0, cfg, used={"G": 250.0}) == 0.0


@pytest.mark.parametrize("fraction,bankroll", [(0.0, 1000.0), (-0.5, 1000.0), (0.10, 0.0)])
def test_the_control_off_means_unlimited_not_blocked(fraction, bankroll):
    """A disabled cap must not read as a cap of zero."""
    cfg = merge_with_defaults({"max_group_exposure_fraction": fraction})
    assert account_risk.group_budget_for_key(
        None, ENV, "G", bankroll, cfg, used={"G": 999.0}) == float("inf")


# --- crypto15m: the engine that could open past its own exposure -----------

def c15_cfg(**over):
    c = merge_with_defaults({})
    c.update({
        "network": ENV, "crypto15m_enabled": True, "crypto15m_order_size": 1,
        "crypto15m_entry_style": "taker", "crypto15m_sizing_mode": "balance_pct",
        "crypto15m_balance_pct": 1.0, "max_group_exposure_fraction": 0.10,
    })
    c.update(over)
    return c


def c15_asset(asset="BTC", *, series=None, ticker=None):
    close = (datetime.now(timezone.utc) + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "asset": asset, "series": series if series is not None else f"KX{asset}15M",
        "spotUsd": 100.0, "open15mUsd": 100.0, "deltaUsd": 0.5, "hasMarket": True,
        "ticker": ticker or f"KX{asset}15M-T1", "closeTime": close, "minsLeft": 5.0,
        "upProb": 0.9, "downProb": 0.1, "favorite": "up", "favoritePrice": 0.86,
        "entryCost": 0.86, "yesBid": 0.85, "yesAsk": 0.87,
        "inWindow": True, "signal": True, "openMarketCount": 1, "error": None,
    }


def patch_c15(monkeypatch, assets):
    async def _snap(_cfg):
        return {"assets": assets, "constants": {}, "fetchedAt": "",
                "spotOk": True, "spotSource": "stub"}
    orders = []

    async def _place(**kw):
        orders.append(kw)
        return {"order": {"order_id": f"ord-{len(orders)}", "status": "resting"}}

    monkeypatch.setattr(crypto15m, "snapshot", _snap)
    monkeypatch.setattr(polymarket_api, "place_limit_order", _place)
    return orders


def test_crypto15m_refuses_an_entry_into_a_full_group(fresh_db, env_net, balance, monkeypatch):
    """The hole: the group was already over its limit and it opened anyway.

    $120 held in the series against $1,000 cash: the cap is 10% of
    $1,120 = $112, so the group is $8 past full before this tick starts.
    """
    seed_main_position("KXBTC15M", 120.0)
    orders = patch_c15(monkeypatch, [c15_asset("BTC")])
    run_async(ct.run_tick(c15_cfg(), authed=True))
    assert orders == []
    with db.get_db() as conn:
        assert db.count_open_crypto15m(conn, ENV) == 0


def test_crypto15m_sizes_an_entry_down_to_what_the_group_allows(
        fresh_db, env_net, balance, monkeypatch):
    # $60 held against $1,000 cash: cap is 10% of $1,060 = $106, so $46 left.
    seed_main_position("KXBTC15M", 60.0)
    orders = patch_c15(monkeypatch, [c15_asset("BTC")])
    run_async(ct.run_tick(c15_cfg(), authed=True))

    assert len(orders) == 1
    notional = orders[0]["count"] * orders[0]["price_cents"] / 100.0
    assert 0 < notional <= 46.0


def test_crypto15m_does_not_grant_one_group_the_same_dollars_twice(
        fresh_db, env_net, balance, monkeypatch):
    """Two windows of one series in a single tick share one allowance."""
    orders = patch_c15(monkeypatch, [
        c15_asset("BTC", series="KXCRYPTO", ticker="KXCRYPTO-T1"),
        c15_asset("ETH", series="KXCRYPTO", ticker="KXCRYPTO-T2"),
    ])
    run_async(ct.run_tick(c15_cfg(), authed=True))

    # Cap is 10% of $1,000 with nothing held yet. Whether that funds one entry
    # or two, the pair must not exceed it between them.
    assert orders, "expected at least one entry"
    spent = sum(o["count"] * o["price_cents"] / 100.0 for o in orders)
    assert spent <= 100.0, "the second entry re-spent the first entry's dollars"


def test_crypto15m_does_not_block_an_unrelated_series(
        fresh_db, env_net, balance, monkeypatch):
    """The cap is per correlated group, not a second account-wide throttle."""
    seed_main_position("KXBTC15M", 120.0)
    orders = patch_c15(monkeypatch, [
        c15_asset("BTC"),                                    # full group
        c15_asset("ETH", series="KXETH15M", ticker="KXETH15M-T1"),
    ])
    run_async(ct.run_tick(c15_cfg(), authed=True))
    assert len(orders) == 1
    assert orders[0]["ticker"] == "KXETH15M-T1"


def test_crypto15m_is_unchanged_when_the_control_is_off(
        fresh_db, env_net, balance, monkeypatch):
    """Default config is fraction 0.0; this must remain a no-op."""
    seed_main_position("KXBTC15M", 120.0)
    orders = patch_c15(monkeypatch, [c15_asset("BTC")])
    run_async(ct.run_tick(c15_cfg(max_group_exposure_fraction=0.0), authed=True))
    assert len(orders) == 1


# --- copy_trader -----------------------------------------------------------

def copy_cfg(**over):
    c = merge_with_defaults({})
    c.update({
        "network": ENV, "copy_enabled": True, "copy_wallets": ["0x" + "a" * 40],
        "copy_sizing_mode": "fixed", "copy_fixed_usd": 10.0,
        "copy_min_trade_usd": 25.0, "copy_only_new_entries": False,
        "max_group_exposure_fraction": 0.10,
    })
    c.update(over)
    return c


def patch_copy(monkeypatch, holdings, *, ask=50):
    async def _gp(limit=500, user=None, **kw):
        return holdings
    orders = []

    async def _place(**kw):
        orders.append(kw)
        return {"order": {"order_id": f"ord-{len(orders)}", "status": "resting"}}

    async def _quote(_t, _s):
        return {"ask_cents": ask, "bid_cents": ask - 2}

    monkeypatch.setattr(polymarket_api, "get_positions", _gp)
    monkeypatch.setattr(polymarket_api, "place_limit_order", _place)
    monkeypatch.setattr(polymarket_api, "get_quote", _quote)
    return orders


def their_pos(ticker, *, qty=10.0, price=0.5, cost=50.0, event=""):
    return {"ticker": ticker, "position_fp": qty, "market_exposure_dollars": cost,
            "cur_price": price, "title": ticker, "event_ticker": event}


def test_copy_refuses_a_copy_into_a_full_group(
        fresh_db, env_net, balance, monkeypatch):
    seed_market("T-A", "KXBTC15M")
    seed_c15("KXBTC15M", 100.0)          # group full at 10% of $1,000
    orders = patch_copy(monkeypatch, [their_pos("T-A")])
    run_async(copy_trader.run_tick(copy_cfg(), authed=True))
    assert orders == []


def test_copy_is_unchanged_when_the_control_is_off(
        fresh_db, env_net, balance, monkeypatch):
    seed_market("T-A", "KXBTC15M")
    seed_c15("KXBTC15M", 100.0)
    orders = patch_copy(monkeypatch, [their_pos("T-A")])
    run_async(copy_trader.run_tick(copy_cfg(max_group_exposure_fraction=0.0), authed=True))
    assert len(orders) == 1
