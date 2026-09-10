"""Account-wide risk: correlated exposure groups and peak-equity drawdown.

Per-event caps do not bound related outcomes across different events, and a
daily stop does not catch a slow multi-day decline. These cover both controls
plus the sizing budget they feed, including the states that must BLOCK rather
than permit risk when account evidence is missing.
"""
from __future__ import annotations

import itertools

import pytest

import account_risk
import db
import trader
from config import merge_with_defaults

ENV = "mainnet"
_ids = itertools.count(1)


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    dbfile = tmp_path / "account-risk.db"
    monkeypatch.setattr(db, "db_path", lambda: dbfile)
    db.init_db()
    return dbfile


@pytest.fixture
def cfg():
    c = merge_with_defaults({})
    c["network"] = ENV
    return c


def seed_market(ticker, *, series="", event=""):
    with db.get_db() as conn:
        db.upsert_market(conn, {
            "ticker": ticker, "event_ticker": event, "series_ticker": series,
            "slug": ticker, "title": ticker, "yes_sub_title": "",
            "category": "sports", "status": "open", "close_time": "",
            "volume": 100_000, "volume_24h": 50_000, "open_interest": 1_000,
            "yes_bid": 0.5, "yes_ask": 0.52, "last_price": 0.5,
            "result": "", "settlement_value": None,
        })


def seed_position(ticker, cost_usd, *, event="", status="filled"):
    n = next(_ids)
    with db.get_db() as conn:
        return db.insert_bot_position(conn, {
            "signal_source": "whale", "signal_id": n, "ticker": ticker,
            "event_ticker": event, "direction": "yes", "target_contracts": 10,
            "limit_price_cents": 50, "filled_contracts": 10,
            "cost_usd": cost_usd, "client_order_id": f"ar-{n}",
            "status": status, "network": ENV,
        })


def snapshot(total_usd, *, cash_usd=None):
    """Record an account equity snapshot the way the live poller does."""
    cash = total_usd if cash_usd is None else cash_usd
    with db.get_db() as conn:
        conn.execute(
            "INSERT INTO pnl_snapshots (network, cash_usd, portfolio_usd, total_usd)"
            " VALUES (?,?,?,?)",
            (ENV, cash, total_usd - cash, total_usd))


# --- correlated exposure groups -----------------------------------------

def test_markets_in_one_series_share_a_group(fresh_db):
    seed_market("A", series="TOURNEY", event="E1")
    seed_market("B", series="TOURNEY", event="E2")
    with db.get_db() as conn:
        assert account_risk.group_key(conn, "A", "E1") == "TOURNEY"
        assert account_risk.group_key(conn, "B", "E2") == "TOURNEY"


def test_group_falls_back_to_event_then_ticker(fresh_db):
    seed_market("C", series="", event="E3")
    with db.get_db() as conn:
        assert account_risk.group_key(conn, "C", "E3") == "E3"
        assert account_risk.group_key(conn, "UNKNOWN", "") == "UNKNOWN"


def test_unknown_market_still_groups_by_its_event(fresh_db):
    """A market absent from `markets` must not collapse into one shared group.

    Metadata can lag a fresh signal. Falling back to the event keeps related
    outcomes together; falling back to a constant would pool unrelated ones.
    """
    with db.get_db() as conn:
        assert account_risk.group_key(conn, "NEVER-SEEN", "EV-1") == "EV-1"
        assert account_risk.group_key(conn, "OTHER", "EV-2") == "EV-2"
        # With no event either, each ticker is its own group.
        assert account_risk.group_key(conn, "LONE-A", "") == "LONE-A"
        assert account_risk.group_key(conn, "LONE-B", "") == "LONE-B"


def test_unknown_market_budget_is_bounded_not_unlimited(fresh_db, cfg):
    """Missing metadata must not hand an entry an unbounded group budget."""
    cfg["max_group_exposure_fraction"] = 0.10
    seed_position("NEVER-SEEN", 60.0, event="EV-1")
    with db.get_db() as conn:
        budget = account_risk.group_budget_usd(
            conn, ENV, "NEVER-SEEN", "EV-1", 1000.0, cfg)
    assert budget == pytest.approx(40.0)


def test_blank_and_null_series_are_treated_as_absent(fresh_db):
    """An empty series column must fall through, not become a real group."""
    seed_market("BLANK", series="", event="EV-B")
    with db.get_db() as conn:
        conn.execute("UPDATE markets SET series_ticker=NULL WHERE ticker='BLANK'")
        assert account_risk.group_key(conn, "BLANK", "EV-B") == "EV-B"


def test_exposure_from_different_events_accumulates_in_one_group(fresh_db):
    seed_market("A", series="TOURNEY", event="E1")
    seed_market("B", series="TOURNEY", event="E2")
    seed_position("A", 30.0, event="E1")
    seed_position("B", 20.0, event="E2")
    with db.get_db() as conn:
        assert account_risk.group_exposure_usd(conn, ENV)["TOURNEY"] == pytest.approx(50.0)


def test_group_budget_shrinks_as_related_exposure_grows(fresh_db, cfg):
    cfg["max_group_exposure_fraction"] = 0.10
    seed_market("A", series="TOURNEY", event="E1")
    seed_market("B", series="TOURNEY", event="E2")
    seed_position("A", 60.0, event="E1")
    with db.get_db() as conn:
        budget = account_risk.group_budget_usd(conn, ENV, "B", "E2", 1000.0, cfg)
    assert budget == pytest.approx(40.0)


def test_full_group_leaves_no_budget(fresh_db, cfg):
    cfg["max_group_exposure_fraction"] = 0.05
    seed_market("A", series="TOURNEY", event="E1")
    seed_market("B", series="TOURNEY", event="E2")
    seed_position("A", 50.0, event="E1")
    with db.get_db() as conn:
        assert account_risk.group_budget_usd(conn, ENV, "B", "E2", 1000.0, cfg) == 0.0


def test_unrelated_group_is_unaffected(fresh_db, cfg):
    cfg["max_group_exposure_fraction"] = 0.05
    seed_market("A", series="TOURNEY", event="E1")
    seed_market("Z", series="OTHER", event="E9")
    seed_position("A", 50.0, event="E1")
    with db.get_db() as conn:
        assert account_risk.group_budget_usd(conn, ENV, "Z", "E9", 1000.0, cfg) == 50.0


def test_zero_fraction_disables_the_group_control(fresh_db, cfg):
    cfg["max_group_exposure_fraction"] = 0.0
    seed_market("A", series="TOURNEY", event="E1")
    seed_position("A", 500.0, event="E1")
    with db.get_db() as conn:
        assert account_risk.group_budget_usd(
            conn, ENV, "A", "E1", 1000.0, cfg) == float("inf")


def test_pending_orders_count_toward_group_exposure(fresh_db, cfg):
    """Unfilled risk is still risk; it must not be free to double up."""
    cfg["max_group_exposure_fraction"] = 0.10
    seed_market("A", series="TOURNEY", event="E1")
    seed_market("B", series="TOURNEY", event="E2")
    seed_position("A", 0.0, event="E1", status="submitted")
    with db.get_db() as conn:
        budget = account_risk.group_budget_usd(conn, ENV, "B", "E2", 1000.0, cfg)
    # The submitted order reserves 10 contracts at 50c.
    assert budget == pytest.approx(95.0)


def test_entry_budget_is_capped_by_the_group_allowance(cfg):
    cfg["max_group_exposure_fraction"] = 0.10
    wide = trader.entry_budget(1000.0, 0.0, 0.0, 20.0, 50, cfg)
    tight = trader.entry_budget(1000.0, 0.0, 0.0, 20.0, 50, cfg, group_budget_usd=7.0)
    assert tight == pytest.approx(7.0)
    assert tight < wide


def test_entry_budget_without_a_group_is_unchanged(cfg):
    assert trader.entry_budget(1000.0, 0.0, 0.0, 20.0, 50, cfg) == \
        trader.entry_budget(1000.0, 0.0, 0.0, 20.0, 50, cfg, group_budget_usd=None)


# --- peak-equity drawdown ------------------------------------------------

def test_high_water_mark_rises_but_never_falls(fresh_db):
    with db.get_db() as conn:
        assert account_risk.update_hwm(conn, ENV, 100.0) == 100.0
        assert account_risk.update_hwm(conn, ENV, 150.0) == 150.0
        assert account_risk.update_hwm(conn, ENV, 90.0) == 150.0
        assert account_risk.read_hwm(conn, ENV) == 150.0


def test_drawdown_below_the_limit_allows_entries(fresh_db, cfg):
    cfg["max_drawdown_fraction"] = 0.05
    snapshot(1000.0)
    assert account_risk.drawdown_block(cfg, ENV)[0] is False
    snapshot(980.0)  # 2% below peak
    assert account_risk.drawdown_block(cfg, ENV)[0] is False


def test_drawdown_past_the_limit_blocks_new_entries(fresh_db, cfg):
    cfg["max_drawdown_fraction"] = 0.05
    snapshot(1000.0)
    account_risk.drawdown_block(cfg, ENV)
    snapshot(940.0)  # 6% below peak
    blocked, reason = account_risk.drawdown_block(cfg, ENV)
    assert blocked is True
    assert "drawdown limit reached" in reason


def test_recovering_equity_does_not_lower_the_peak(fresh_db, cfg):
    """A dip and partial recovery still measures against the true peak."""
    cfg["max_drawdown_fraction"] = 0.05
    snapshot(1000.0)
    account_risk.drawdown_block(cfg, ENV)
    snapshot(900.0)
    account_risk.drawdown_block(cfg, ENV)
    snapshot(950.0)  # recovered, but still 5% below the 1000 peak
    assert account_risk.drawdown_block(cfg, ENV)[0] is True


def test_missing_equity_evidence_blocks_rather_than_permits(fresh_db, cfg):
    cfg["max_drawdown_fraction"] = 0.05
    blocked, reason = account_risk.drawdown_block(cfg, ENV)
    assert blocked is True
    assert "has not been recorded" in reason


def test_zero_fraction_disables_the_drawdown_control(fresh_db, cfg):
    cfg["max_drawdown_fraction"] = 0.0
    assert account_risk.drawdown_block(cfg, ENV) == (False, "")


def test_reset_reanchors_the_peak_for_a_deliberate_change(fresh_db, cfg):
    cfg["max_drawdown_fraction"] = 0.05
    snapshot(1000.0)
    account_risk.drawdown_block(cfg, ENV)
    with db.get_db() as conn:
        account_risk.reset_hwm(conn, ENV, 500.0)
    snapshot(500.0)
    assert account_risk.drawdown_block(cfg, ENV)[0] is False


def test_config_clamps_the_new_fractions_into_range():
    c = merge_with_defaults({
        "maxGroupExposureFraction": 5.0, "maxDrawdownFraction": -2.0})
    assert 0.0 <= c["max_group_exposure_fraction"] <= 1.0
    assert 0.0 <= c["max_drawdown_fraction"] <= 1.0
