from __future__ import annotations

import asyncio
import itertools

import pytest

import db
import trader


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    dbfile = tmp_path / "risk-test.db"
    monkeypatch.setattr(db, "db_path", lambda: dbfile)
    db.init_db()
    return dbfile


@pytest.fixture
def env_net(monkeypatch):
    monkeypatch.setattr(trader, "get_env", lambda: "mainnet")
    return "mainnet"


@pytest.fixture
def cfg():
    from config import merge_with_defaults
    c = merge_with_defaults({})
    c["network"] = "mainnet"
    return c


def run_async(coro):
    return asyncio.run(coro)


_ids = itertools.count(1)


def seed_position(**over) -> int:
    n = next(_ids)
    row = {
        "signal_source": over.get("signal_source", "whale"),
        "signal_id": over.get("signal_id", n),
        "ticker": over.get("ticker", f"TCK-{n}"),
        "event_ticker": over.get("event_ticker", ""),
        "direction": over.get("direction", "yes"),
        "target_contracts": over.get("target_contracts", 10),
        "limit_price_cents": over.get("limit_price_cents", 50),
        "filled_contracts": over.get("filled_contracts", 0),
        "cost_usd": over.get("cost_usd", 0.0),
        "client_order_id": over.get("client_order_id", f"rc-{n}"),
        "order_id": over.get("order_id"),
        "status": over.get("status", "filled"),
        "network": over.get("network", "mainnet"),
    }
    with db.get_db() as conn:
        return db.insert_bot_position(conn, row)


def fetch(pid: int) -> dict:
    with db.get_db() as conn:
        return db.fetch_position_by_id(conn, pid)


def test_daily_cap_ignores_terminal_failed_orders(fresh_db):
    seed_position(status="submitted")
    seed_position(status="partial", filled_contracts=3)
    seed_position(status="filled", filled_contracts=10, cost_usd=5.0)
    seed_position(status="canceled")
    seed_position(status="error")
    seed_position(status="gone")
    seed_position(status="expired")
    with db.get_db() as conn:
        assert db.count_new_positions_today(conn, "mainnet") == 3


def test_daily_cap_burst_of_cancels_does_not_halt_entries(fresh_db):
    for _ in range(50):
        seed_position(status="canceled")
    with db.get_db() as conn:
        assert db.count_new_positions_today(conn, "mainnet") == 0


def test_daily_cap_still_excludes_external_imports(fresh_db):
    seed_position(status="filled", filled_contracts=5, cost_usd=2.0)
    seed_position(status="filled", filled_contracts=5, cost_usd=2.0,
                  signal_source="external")
    with db.get_db() as conn:
        assert db.count_new_positions_today(conn, "mainnet") == 1


def test_daily_cap_counts_resolved_today_position(fresh_db):
    pid = seed_position(status="filled", filled_contracts=5, cost_usd=2.0)
    with db.get_db() as conn:
        db.update_bot_position(conn, pid, resolved=1)
        assert db.count_new_positions_today(conn, "mainnet") == 1


def test_daily_cap_env_scoped(fresh_db):
    seed_position(status="filled", network="mainnet")
    seed_position(status="filled", network="amoy")
    with db.get_db() as conn:
        assert db.count_new_positions_today(conn, "mainnet") == 1
        assert db.count_new_positions_today(conn) == 2


async def _no_positions(*_a, **_k):
    return []


def test_poll_collapses_target_when_partial_remainder_canceled(
    fresh_db, env_net, cfg, monkeypatch
):
    trader._poll_failures.clear()
    pid = seed_position(status="submitted", order_id="OID-CP",
                        target_contracts=5, limit_price_cents=60)

    async def _canceled_partial(_oid):
        return {"order": {
            "status": "CANCELED", "size_matched": "2", "original_size": "5",
            "price": "0.60",
        }}

    monkeypatch.setattr(trader, "get_positions", _no_positions)
    monkeypatch.setattr(trader, "get_order", _canceled_partial)

    run_async(trader.poll_open_orders(cfg))
    row = fetch(pid)
    assert row["status"] == "partial"
    assert row["target_contracts"] == 2
    assert row["filled_contracts"] == 2
    with db.get_db() as conn:
        assert db.current_total_exposure_usd(conn, "mainnet") == pytest.approx(1.20)


def test_poll_keeps_target_for_resting_partial(fresh_db, env_net, cfg, monkeypatch):
    trader._poll_failures.clear()
    pid = seed_position(status="submitted", order_id="OID-RP",
                        target_contracts=5, limit_price_cents=60)

    async def _resting_partial(_oid):
        return {"order": {
            "status": "LIVE", "size_matched": "2", "original_size": "5",
            "price": "0.60",
        }}

    monkeypatch.setattr(trader, "get_positions", _no_positions)
    monkeypatch.setattr(trader, "get_order", _resting_partial)

    run_async(trader.poll_open_orders(cfg))
    row = fetch(pid)
    assert row["status"] == "partial"
    assert row["target_contracts"] == 5


def test_crypto15m_strategy_stats_groups_and_sums(fresh_db):
    def _c15(strategy, pnl, fees=0.0, exit_fees=0.0, n=[0]):
        n[0] += 1
        with db.get_db() as conn:
            pid = db.insert_crypto15m_position(conn, {
                "asset": "BTC", "series": "S", "ticker": f"T-{n[0]}",
                "side": "up", "direction": "yes", "target_contracts": 5,
                "filled_contracts": 5, "entry_limit_cents": 60,
                "client_order_id": f"cs-{n[0]}", "status": "settled",
                "network": "mainnet", "strategy": strategy,
            })
            db.update_crypto15m_position(
                conn, pid, resolved=1, pnl_usd=pnl,
                fees_usd=fees, exit_fees_usd=exit_fees,
            )

    _c15("favorite", 2.0, fees=0.10)
    _c15("favorite", -1.0, exit_fees=0.05)
    _c15("rules", 3.0)
    _c15(None, 1.0)

    with db.get_db() as conn:
        rows = {r["strategy"]: r for r in db.crypto15m_strategy_stats(conn, "mainnet")}

    assert rows["favorite"]["n"] == 2
    assert rows["favorite"]["wins"] == 1 and rows["favorite"]["losses"] == 1
    assert rows["favorite"]["pnl_usd"] == pytest.approx(1.0)
    assert rows["favorite"]["fees_usd"] == pytest.approx(0.15)
    assert rows["rules"]["pnl_usd"] == pytest.approx(3.0)
    assert rows["directional"]["n"] == 1

# --- Trading-day boundary ----------------------------------------------
#
# Daily risk limits must roll over at the user's local midnight, not at UTC
# midnight. UTC midnight is 8pm ET, so a stop-loss hit at 5pm ET used to
# release three hours later while the user was still trading.

from datetime import datetime, timedelta, timezone  # noqa: E402

ET = -240  # US Eastern in summer, in minutes from UTC


@pytest.fixture
def frozen_clock(monkeypatch):
    """Pin db's notion of 'now' so day boundaries are deterministic."""
    def freeze(when: datetime) -> None:
        class _Frozen(datetime):
            @classmethod
            def now(cls, tz=None):
                return when.astimezone(tz) if tz else when.replace(tzinfo=None)
        monkeypatch.setattr(db, "datetime", _Frozen)
    return freeze


def seed_snapshot(at: datetime, total: float, env: str = "mainnet") -> None:
    with db.get_db() as conn:
        conn.execute(
            """INSERT INTO pnl_snapshots
                 (network, cash_usd, portfolio_usd, total_usd,
                  realized_pnl_usd, wins, losses, open_positions, at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (env, total, 0.0, total, 0.0, 0, 0, 0,
             at.strftime("%Y-%m-%d %H:%M:%S")),
        )


def shift_position_to(pid: int, when: datetime) -> None:
    with db.get_db() as conn:
        conn.execute(
            "UPDATE bot_positions SET created_at=? WHERE id=?",
            (when.strftime("%Y-%m-%d %H:%M:%S"), pid),
        )


def test_day_start_is_local_midnight_expressed_in_utc(frozen_clock):
    # 00:30 UTC on Sep 9 is 8:30pm ET on Sep 8; the ET day began at 04:00 UTC
    # on Sep 8, four hours before UTC's own rollover.
    frozen_clock(datetime(2026, 9, 9, 0, 30, tzinfo=timezone.utc))
    assert db.day_start_utc(0) == "2026-09-09 00:00:00"
    assert db.day_start_utc(ET) == "2026-09-08 04:00:00"
    assert db.day_key(0) == "2026-09-09"
    assert db.day_key(ET) == "2026-09-08"


def test_day_start_round_trips_to_local_midnight_for_any_offset(frozen_clock):
    at = datetime(2026, 9, 9, 13, 17, tzinfo=timezone.utc)
    frozen_clock(at)
    for off in (0, -300, -240, -480, 60, 330, 720):
        start = datetime.strptime(
            db.day_start_utc(off), "%Y-%m-%d %H:%M:%S"
        ).replace(tzinfo=timezone.utc)
        local = start + timedelta(minutes=off)
        assert (local.hour, local.minute, local.second) == (0, 0, 0)
        assert timedelta(0) <= (at - start) < timedelta(days=1)


def test_zero_offset_preserves_the_previous_utc_behaviour(frozen_clock):
    frozen_clock(datetime(2026, 9, 9, 13, 17, tzinfo=timezone.utc))
    assert db.day_start_utc(0) == "2026-09-09 00:00:00"
    assert db.day_key(0) == "2026-09-09"


def test_daily_stop_baseline_survives_utc_rollover(fresh_db, frozen_clock):
    """The regression: a loss booked at 5pm ET must still count at 8:30pm ET."""
    frozen_clock(datetime(2026, 9, 9, 0, 30, tzinfo=timezone.utc))
    # 5pm ET Sep 8 (21:00 UTC Sep 8): bankroll $1000, before the loss.
    seed_snapshot(datetime(2026, 9, 8, 21, 0), 1000.0)
    # 8:30pm ET Sep 8 (00:30 UTC Sep 9): down $100, UTC day has just rolled.
    seed_snapshot(datetime(2026, 9, 9, 0, 30), 900.0)

    with db.get_db() as conn:
        # Old behaviour: baseline resets to the post-loss snapshot, so the
        # day looks flat and the stop-loss silently releases.
        utc_first = db.first_snapshot_of_today(conn, "mainnet", 0)
        assert float(utc_first["total_usd"]) == 900.0
        # Fixed: the ET day started at 04:00 UTC Sep 8, so the $100 loss holds.
        et_first = db.first_snapshot_of_today(conn, "mainnet", ET)
        assert float(et_first["total_usd"]) == 1000.0


def test_daily_stop_stays_tripped_across_the_rollover(
    fresh_db, frozen_clock, cfg, env_net
):
    """End to end: _is_blocked_by_daily_risk must not release at 8pm ET."""
    frozen_clock(datetime(2026, 9, 9, 0, 30, tzinfo=timezone.utc))
    seed_snapshot(datetime(2026, 9, 8, 21, 0), 1000.0)
    seed_snapshot(datetime(2026, 9, 9, 0, 30), 900.0)
    cfg["stop_loss_on_day"] = -50.0
    trader._day_risk_breach.clear()

    cfg["trading_timezone_offset_min"] = 0
    blocked_utc, _ = trader._is_blocked_by_daily_risk(cfg, env_net)
    assert not blocked_utc, "UTC boundary hides the loss (the old bug)"

    cfg["trading_timezone_offset_min"] = ET
    trader._day_risk_breach.clear()
    # The guard debounces for three minutes before it trips.
    trader._is_blocked_by_daily_risk(cfg, env_net)
    trader._day_risk_breach[(env_net, "sl")] -= trader._DAY_RISK_PERSIST_SEC + 1
    blocked_et, reason = trader._is_blocked_by_daily_risk(cfg, env_net)
    assert blocked_et
    assert "stop-loss" in reason
    trader._day_risk_breach.clear()


def test_daily_cap_counts_evening_entries_from_the_same_local_day(
    fresh_db, frozen_clock
):
    frozen_clock(datetime(2026, 9, 9, 0, 30, tzinfo=timezone.utc))
    before = seed_position(status="filled")   # 5pm ET Sep 8
    after = seed_position(status="filled")    # 8:30pm ET Sep 8
    shift_position_to(before, datetime(2026, 9, 8, 21, 0))
    shift_position_to(after, datetime(2026, 9, 9, 0, 30))
    with db.get_db() as conn:
        # Old behaviour: the cap silently doubles at 8pm ET.
        assert db.count_new_positions_today(conn, "mainnet", 0) == 1
        # Fixed: both entries belong to the same ET trading day.
        assert db.count_new_positions_today(conn, "mainnet", ET) == 2


def test_daily_cap_excludes_the_previous_local_day(fresh_db, frozen_clock):
    frozen_clock(datetime(2026, 9, 9, 0, 30, tzinfo=timezone.utc))
    pid = seed_position(status="filled")
    shift_position_to(pid, datetime(2026, 9, 8, 3, 59))  # 1 min before ET day
    with db.get_db() as conn:
        assert db.count_new_positions_today(conn, "mainnet", ET) == 0


def test_paper_daily_cap_uses_the_same_boundary(fresh_db, frozen_clock):
    frozen_clock(datetime(2026, 9, 9, 0, 30, tzinfo=timezone.utc))
    pid = seed_position(status="dry_run", signal_id=-1)
    shift_position_to(pid, datetime(2026, 9, 8, 21, 0))
    with db.get_db() as conn:
        assert db.count_new_paper_positions_today(conn, "mainnet", 0) == 0
        assert db.count_new_paper_positions_today(conn, "mainnet", ET) == 1


def test_transfer_key_matches_between_write_and_read(fresh_db, frozen_clock):
    frozen_clock(datetime(2026, 9, 9, 0, 30, tzinfo=timezone.utc))
    seed_snapshot(datetime(2026, 9, 8, 21, 0), 100.0)
    with db.get_db() as conn:
        moved = db.note_transfer_if_unexplainable(
            conn, "mainnet", 500.0, offset_min=ET)
        assert moved == pytest.approx(400.0)
        # Written under the ET day key, so it must read back under the same one.
        assert db.transfer_adjustment_today(
            conn, "mainnet", ET) == pytest.approx(400.0)
        # And must not leak into the UTC-keyed day.
        assert db.transfer_adjustment_today(conn, "mainnet", 0) == 0.0


def test_trading_day_offset_reads_config():
    from config import merge_with_defaults
    assert trader.trading_day_offset_min(merge_with_defaults({})) == 0
    c = merge_with_defaults({"trading_timezone_offset_min": ET})
    assert trader.trading_day_offset_min(c) == ET
    assert trader.trading_day_offset_min({"trading_timezone_offset_min": None}) == 0
    assert trader.trading_day_offset_min({"trading_timezone_offset_min": "x"}) == 0
    assert trader.trading_day_offset_min({}) == 0


def test_risk_guards_and_trading_hours_share_one_offset():
    """Both gates must derive the trading day from the same setting."""
    from config import merge_with_defaults
    c = merge_with_defaults({
        "trading_hours_enabled": True,
        "trading_timezone_offset_min": ET,
        "trading_days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
        "trading_hours_start": "00:00",
        "trading_hours_end": "23:59",
    })
    assert not trader._is_blocked_by_trading_hours(c)[0]
    assert trader.trading_day_offset_min(c) == ET
