"""Momentum must measure fresh, per-market trade flow — never rolling 24h totals.

These cover the trade window itself and the scanner path that consumes it:
stale prints, duplicates after reconnect, out-of-order receipts, warm-up,
coverage gaps and the price/volume baselines that a signal is allowed to use.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

import db
import momentum_window
import scanner
from config import merge_with_defaults

T = datetime(2026, 7, 10, 12, tzinfo=timezone.utc).timestamp()


def iso(at: float) -> str:
    return datetime.fromtimestamp(at, timezone.utc).isoformat().replace("+00:00", "Z")


def trade(tid, ticker="M1", at=T, price=0.40, qty=100, side="yes"):
    return {
        "trade_id": str(tid), "ticker": ticker, "slug": ticker,
        "created_time": iso(at), "count_fp": qty,
        "yes_price_dollars": price, "no_price_dollars": 1 - price,
        "taker_side": side,
    }


@pytest.fixture
def tape():
    t = momentum_window.Tape()
    yield t
    t.reset()


# --- the window itself --------------------------------------------------

def test_old_prints_are_rejected_so_they_cannot_look_like_fresh_pressure(tape):
    assert tape.add(trade(1, at=T), T) is True
    assert tape.add(trade(2, at=T - 3600), T) is False


def test_future_dated_trade_is_rejected(tape):
    assert tape.add(trade(1, at=T + 60), T) is False


def test_duplicate_trade_id_after_reconnect_is_counted_once(tape):
    assert tape.add(trade(1), T) is True
    assert tape.add(trade(1), T + 1) is False


def test_window_is_not_ready_before_a_full_five_minutes(tape):
    tape.add(trade(1), T)
    assert tape.summarize("M1", T + momentum_window.WINDOW - 1)["ready"] is False


def test_window_requires_a_trade_in_the_last_thirty_seconds(tape):
    tape.add(trade(1, at=T), T)
    ready_at = T + momentum_window.WINDOW + 1
    tape.add(trade(2, at=ready_at - 5), ready_at - 5)
    assert tape.summarize("M1", ready_at)["ready"] is True
    # No further prints: the same window goes stale rather than reusing old flow.
    assert tape.summarize("M1", ready_at + momentum_window.FRESH + 1)["ready"] is False


def test_flow_is_isolated_per_market(tape):
    now = T
    for i in range(6):
        tape.add(trade(f"a{i}", ticker="BUSY", at=now, qty=500), now)
    tape.add(trade("b0", ticker="QUIET", at=now, qty=1), now)
    later = now + momentum_window.WINDOW + 1
    tape.add(trade("a9", ticker="BUSY", at=later, qty=500), later)
    tape.add(trade("b9", ticker="QUIET", at=later, qty=1), later)
    busy = tape.summarize("BUSY", later)
    quiet = tape.summarize("QUIET", later)
    assert busy["current_dollars"] > quiet["current_dollars"]
    assert quiet["trade_count"] == 1


def test_direction_requires_a_dominant_share_of_dollar_flow(tape):
    now = T
    for i in range(4):
        tape.add(trade(f"y{i}", at=now, qty=100, side="yes"), now)
        tape.add(trade(f"n{i}", at=now, qty=100, side="no"), now)
    later = now + momentum_window.WINDOW + 1
    tape.add(trade("y9", at=later, qty=100, side="yes"), later)
    tape.add(trade("n9", at=later, qty=100, side="no"), later)
    assert tape.summarize("M1", later)["direction"] is None


def test_volume_ratio_needs_a_full_prior_window_not_a_partial_one(tape):
    now = T
    tape.add(trade("a", at=now, qty=400), now)
    ready = now + momentum_window.WINDOW + 1
    tape.add(trade("b", at=ready, qty=400), ready)
    # Only one window of coverage exists, so no ratio may be claimed.
    assert tape.summarize("M1", ready)["volume_ratio"] is None


def test_price_change_needs_a_comparable_baseline_print(tape):
    now = T
    tape.add(trade("a", at=now, price=0.30), now)
    ready = now + 2 * momentum_window.WINDOW + 1
    tape.add(trade("b", at=ready, price=0.60), ready)
    # The old print aged out of the comparison horizon: no invented move.
    assert tape.summarize("M1", ready)["price_change"] is None


def test_clock_rollback_discards_the_observation_horizon(tape):
    tape.add(trade(1), T)
    tape.add(trade(2, at=T - 10), T - 10)
    assert tape.summarize("M1", T + momentum_window.WINDOW + 1)["ready"] is False


def test_expired_receipts_release_their_window_start(tape):
    """A gap in coverage must not pass as a continuously observed window."""
    tape.add(trade(1, at=T), T)
    gap = T + 10 * momentum_window.WINDOW
    tape.add(trade(2, at=gap, qty=100), gap)
    # Only one fresh print exists after the gap; warm-up restarts from it.
    assert tape.summarize("M1", gap + 1)["ready"] is False
    assert tape.started["M1"] == gap


def test_overflow_resets_rather_than_reporting_a_partial_baseline(tape, monkeypatch):
    monkeypatch.setattr(momentum_window, "MAX_TRADES", 5)
    for i in range(6):
        tape.add(trade(i, at=T), T)
    assert len(tape.rows) <= 5


# --- the scanner path ---------------------------------------------------

def _market(ticker="M1", **over):
    row = {
        "ticker": ticker, "slug": ticker, "event_ticker": "E1", "title": "Test market",
        "yes_sub_title": "", "category": "sports", "status": "open",
        "close_time": "", "volume": 250_000, "volume_24h": 100_000,
        "open_interest": 20_000, "yes_bid": 0.40, "last_price": 0.40,
    }
    row.update(over)
    return row


@pytest.fixture
def wired(monkeypatch):
    """Scanner with a live market row and no network."""
    momentum_window.tape.reset()
    with db.get_db() as conn:
        conn.execute("DELETE FROM alerts")
        db.upsert_market(conn, _market())

    async def _no_trades(limit=1000):
        return []

    monkeypatch.setattr(scanner.polymarket_api, "fetch_recent_trades", _no_trades)
    yield
    momentum_window.tape.reset()


def _run(cfg=None):
    cfg = merge_with_defaults(cfg or {"allowedMomentumSignalTypes": ["trade_cluster"]})
    return asyncio.run(scanner.scan_momentum(cfg))


def _fill_cluster(ticker="M1", side="no", price=0.60):
    """Enough fresh one-sided dollar flow to clear the cluster thresholds.

    Priced so the contrarian gate admits the signal: a NO signal needs a yes
    price at or above 50c, matching the scanner's live entry rules.
    """
    now = T
    for i in range(6):
        momentum_window.tape.add(
            trade(f"seed{i}", ticker=ticker, at=now, qty=600, side=side, price=price), now)
    later = now + momentum_window.WINDOW + 1
    for i in range(6):
        momentum_window.tape.add(
            trade(f"live{i}", ticker=ticker, at=later, qty=600, side=side, price=price), later)
    return later


def test_scanner_emits_nothing_while_the_window_is_warming(wired):
    count, alerts = _run()
    assert (count, alerts) == (0, [])


def test_scanner_emits_a_cluster_alert_from_window_flow(wired, monkeypatch):
    at = _fill_cluster()
    monkeypatch.setattr(scanner.time, "time", lambda: at)
    count, alerts = _run()
    assert count == 1
    assert alerts[0]["signal_type"] == "trade_cluster"
    assert alerts[0]["direction"] == "no"


def test_alert_records_the_window_measurement_that_produced_it(wired, monkeypatch):
    at = _fill_cluster()
    monkeypatch.setattr(scanner.time, "time", lambda: at)
    _count, alerts = _run()
    row = alerts[0]
    assert row["score_version"] == momentum_window.SCORE_VERSION
    assert row["window_trades"] == 6
    assert row["window_dollars"] > 0
    assert row["observed_at"] == pytest.approx(at, abs=1)


def test_a_market_with_no_recent_trades_produces_no_alert(wired, monkeypatch):
    """A high 24h volume alone must never stand in for fresh pressure."""
    at = _fill_cluster()
    stale = at + 10 * momentum_window.WINDOW
    monkeypatch.setattr(scanner.time, "time", lambda: stale)
    assert _run() == (0, [])


def test_calibration_never_pools_legacy_and_window_momentum_scores():
    import signal_calibration as calibration

    base = dict(price=.3, confidence=80, direction="no", category="sports")
    legacy, _p, _s = calibration.features(base, "momentum")
    fresh, _p, _s = calibration.features(
        {**base, "score_version": momentum_window.SCORE_VERSION}, "momentum")
    assert legacy != fresh
