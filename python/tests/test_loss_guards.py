from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone

import pytest

import copy_trader
import crypto15m_trader as ct
import db
from config import merge_with_defaults


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    dbfile = tmp_path / "guards.db"
    monkeypatch.setattr(db, "db_path", lambda: dbfile)
    db.init_db()
    return dbfile


ENV = "mainnet"


def _now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def seed_c15(pnl=None, *, cost=0.0, status="settled", open_today=False,
             entry_cents=90, contracts=5):
    uid = uuid.uuid4().hex[:12]
    with db.get_db() as conn:
        pid = db.insert_crypto15m_position(conn, {
            "asset": "BTC", "series": "KXBTC15M", "ticker": f"T-{uid}",
            "side": "up", "direction": "yes", "target_contracts": contracts,
            "filled_contracts": contracts, "entry_limit_cents": entry_cents,
            "cost_usd": cost, "client_order_id": f"c-{uid}",
            "status": status, "network": ENV,
        })
        if pnl is not None:
            db.update_crypto15m_position(
                conn, pid, resolved=1, pnl_usd=pnl,
                outcome_correct=1 if pnl > 0 else 0,
            )
            conn.execute(
                "UPDATE crypto15m_positions SET resolved_at=datetime('now') WHERE id=?",
                (pid,),
            )
    return pid


def seed_copy(pnl=None, *, cost=0.0, status="filled"):
    uid = uuid.uuid4().hex[:12]
    with db.get_db() as conn:
        pid = db.insert_bot_position(conn, {
            "signal_source": "copy", "signal_id": abs(hash(uid)) % 1_000_000,
            "ticker": f"CT-{uid}", "direction": "yes", "target_contracts": 5,
            "limit_price_cents": 50, "filled_contracts": 5, "cost_usd": cost,
            "client_order_id": f"cp-{uid}", "status": status, "network": ENV,
        })
        if pnl is not None:
            db.update_bot_position(
                conn, pid, resolved=1, pnl_usd=pnl, resolved_at=_now_str(),
            )
    return pid


def base_cfg(**over):
    c = merge_with_defaults({})
    c["network"] = ENV
    c["start_bankroll_usd"] = 100.0
    c.update(over)
    return c


def test_init_db_restores_backup_on_corruption(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(db, "_data_dir", lambda: data_dir)
    monkeypatch.setattr(db, "_vault_dir", lambda: None)

    bdir = data_dir / "backups"
    bdir.mkdir()
    backup = bdir / "research-20260101.db"
    con = sqlite3.connect(str(backup))
    con.executescript(db.SCHEMA)
    con.execute("INSERT INTO app_kv (k, v) VALUES ('canary', 'restored')")
    con.commit()
    con.close()

    (data_dir / "rom-polybot.db").write_bytes(b"\x00 definitely not sqlite " * 16)

    monkeypatch.setattr(db, "_restore_checked", True, raising=False)

    db.init_db()

    with db.get_db() as conn:
        row = conn.execute("SELECT v FROM app_kv WHERE k='canary'").fetchone()
    assert row is not None and row[0] == "restored", "backup was not restored"
    assert list(data_dir.glob("rom-polybot.db.corrupt-*"))


def test_crypto15m_lifetime_guard_trips_at_pct(fresh_db):
    seed_c15(-40.0)
    seed_c15(-20.0)
    cfg = base_cfg(crypto15m_lifetime_loss_limit_pct=0.5)
    tripped, why = ct._lifetime_loss_tripped(cfg, ENV)
    assert tripped and "lifetime loss limit" in why


def test_crypto15m_lifetime_guard_ok_below_cap(fresh_db):
    seed_c15(-30.0)
    cfg = base_cfg(crypto15m_lifetime_loss_limit_pct=0.5)
    assert ct._lifetime_loss_tripped(cfg, ENV) == (False, "")


def test_crypto15m_lifetime_guard_usd_override(fresh_db):
    seed_c15(-15.0)
    cfg = base_cfg(crypto15m_lifetime_loss_limit_pct=0.5,
                   crypto15m_lifetime_loss_limit_usd=10.0)
    tripped, _ = ct._lifetime_loss_tripped(cfg, ENV)
    assert tripped


def test_crypto15m_lifetime_guard_disabled(fresh_db):
    seed_c15(-500.0)
    cfg = base_cfg(crypto15m_lifetime_loss_limit_pct=0.0,
                   crypto15m_lifetime_loss_limit_usd=0.0)
    assert ct._lifetime_loss_tripped(cfg, ENV) == (False, "")


def test_crypto15m_lifetime_guard_needs_bankroll_for_pct(fresh_db):
    seed_c15(-500.0)
    cfg = base_cfg(crypto15m_lifetime_loss_limit_pct=0.5)
    cfg["start_bankroll_usd"] = 0.0
    assert ct._lifetime_loss_tripped(cfg, ENV) == (False, "")


def test_copy_lifetime_guard_trips(fresh_db):
    seed_copy(-60.0)
    cfg = base_cfg(copy_lifetime_loss_limit_pct=0.5)
    tripped, why = copy_trader._lifetime_loss_tripped(cfg, ENV)
    assert tripped and "lifetime loss limit" in why


def test_lifetime_counter_survives_clear_trade_history(fresh_db):
    seed_c15(-60.0)
    cfg = base_cfg(crypto15m_lifetime_loss_limit_pct=0.5)
    assert ct._lifetime_loss_tripped(cfg, ENV)[0]

    db.clear_trade_history()

    with db.get_db() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM crypto15m_positions").fetchone()[0] == 0
        assert db.lifetime_realized_pnl(conn, "crypto15m", ENV) == pytest.approx(-60.0)
    assert ct._lifetime_loss_tripped(cfg, ENV)[0]


def test_lifetime_counter_survives_factory_reset(fresh_db):
    seed_copy(-80.0)
    with db.get_db() as conn:
        assert db.lifetime_realized_pnl(conn, "copy", ENV) == pytest.approx(-80.0)

    db.factory_reset()

    with db.get_db() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM bot_positions").fetchone()[0] == 0
        assert db.lifetime_realized_pnl(conn, "copy", ENV) == pytest.approx(-80.0)


def test_banking_is_cumulative_across_repeated_wipes(fresh_db):
    seed_c15(-30.0)
    db.clear_trade_history()
    seed_c15(-25.0)
    db.clear_trade_history()
    with db.get_db() as conn:
        assert db.lifetime_realized_pnl(conn, "crypto15m", ENV) == pytest.approx(-55.0)


def test_daily_pnl_survives_wipe(fresh_db):
    seed_copy(-40.0)
    with db.get_db() as conn:
        assert db.engine_today_pnl(conn, "copy", ENV) == pytest.approx(-40.0)

    db.clear_trade_history()

    with db.get_db() as conn:
        assert db.engine_today_pnl(conn, "copy", ENV) == pytest.approx(-40.0)


def test_crypto15m_today_pnl_survives_wipe(fresh_db):
    seed_c15(-35.0)
    with db.get_db() as conn:
        assert db.crypto15m_today_pnl(conn, ENV) == pytest.approx(-35.0)
    db.clear_trade_history()
    with db.get_db() as conn:
        assert db.crypto15m_today_pnl(conn, ENV) == pytest.approx(-35.0)


def test_today_open_cost_counts_open_positions(fresh_db):
    seed_c15(open_today=True, status="filled", cost=30.0)
    seed_c15(open_today=True, status="filled", cost=12.0)
    seed_c15(-5.0)
    with db.get_db() as conn:
        assert db.crypto15m_today_open_cost(conn, ENV) == pytest.approx(42.0)


def test_today_open_cost_values_resting_notional(fresh_db):
    seed_c15(open_today=True, status="submitted", cost=0.0,
             entry_cents=80, contracts=5)
    with db.get_db() as conn:
        assert db.crypto15m_today_open_cost(conn, ENV) == pytest.approx(4.0)


def test_fixed_sizing_caps_single_entry_fraction(fresh_db):
    cfg = base_cfg(crypto15m_sizing_mode="fixed", crypto15m_max_loss_pct=0.0)
    n = ct.compute_entry_contracts(
        cfg, entry_limit_cents=90, balance_usd=10.0, order_size=1000)
    assert n == 2


def test_fixed_sizing_small_order_unchanged(fresh_db):
    cfg = base_cfg(crypto15m_sizing_mode="fixed", crypto15m_max_loss_pct=0.0)
    n = ct.compute_entry_contracts(
        cfg, entry_limit_cents=90, balance_usd=1000.0, order_size=5)
    assert n == 5


def test_balance_pct_mode_exempt_from_backstop(fresh_db):
    cfg = base_cfg(crypto15m_sizing_mode="balance_pct",
                   crypto15m_balance_pct=0.5, crypto15m_max_loss_pct=0.0)
    n = ct.compute_entry_contracts(
        cfg, entry_limit_cents=50, balance_usd=100.0, order_size=1)
    assert n == 100


def test_explicit_max_loss_still_applies(fresh_db):
    cfg = base_cfg(crypto15m_sizing_mode="fixed", crypto15m_max_loss_pct=0.10)
    n = ct.compute_entry_contracts(
        cfg, entry_limit_cents=50, balance_usd=100.0, order_size=1000)
    assert n == 20


def seed_main(pnl, *, source="whale"):
    uid = uuid.uuid4().hex[:12]
    with db.get_db() as conn:
        pid = db.insert_bot_position(conn, {
            "signal_source": source, "signal_id": abs(hash(uid)) % 1_000_000,
            "ticker": f"MT-{uid}", "direction": "yes", "target_contracts": 5,
            "limit_price_cents": 50, "filled_contracts": 5, "cost_usd": 2.5,
            "client_order_id": f"mn-{uid}", "status": "filled", "network": ENV,
        })
        db.update_bot_position(
            conn, pid, resolved=1, pnl_usd=pnl, resolved_at=_now_str(),
        )
    return pid


def test_main_lifetime_guard_trips_at_pct(fresh_db):
    import trader
    seed_main(-40.0)
    seed_main(-20.0)
    cfg = base_cfg(lifetime_loss_limit_pct=0.5)
    tripped, why = trader._lifetime_loss_tripped_main(cfg, ENV)
    assert tripped and "lifetime loss limit" in why


def test_main_lifetime_guard_ignores_external_and_copy_rows(fresh_db):
    import trader
    seed_main(-500.0, source="external")
    seed_copy(-500.0)
    cfg = base_cfg(lifetime_loss_limit_pct=0.5)
    assert trader._lifetime_loss_tripped_main(cfg, ENV) == (False, "")


def test_main_lifetime_guard_survives_history_wipe(fresh_db):
    import trader
    seed_main(-60.0)
    with db.get_db() as conn:
        db.bank_realized_pnl_before_wipe(conn)
        conn.execute("DELETE FROM bot_positions")
    cfg = base_cfg(lifetime_loss_limit_pct=0.5)
    tripped, _ = trader._lifetime_loss_tripped_main(cfg, ENV)
    assert tripped


def test_main_lifetime_guard_disabled(fresh_db):
    import trader
    seed_main(-500.0)
    cfg = base_cfg(lifetime_loss_limit_pct=0.0, lifetime_loss_limit_usd=0.0)
    assert trader._lifetime_loss_tripped_main(cfg, ENV) == (False, "")


def test_transfer_adjustment_total_sums_all_days(fresh_db):
    with db.get_db() as conn:
        db.kv_set(conn, f"transfers:{ENV}:2026-07-01", repr(-200.0))
        db.kv_set(conn, f"transfers:{ENV}:2026-07-05", repr(50.0))
        db.kv_set(conn, f"transfers:{ENV}:2026-07-10", repr(-25.0))
        db.kv_set(conn, "transfers:othernet:2026-07-10", repr(-999.0))
        assert db.transfer_adjustment_total(conn, ENV) == pytest.approx(-175.0)


def test_transfer_adjustment_total_empty_and_garbage(fresh_db):
    with db.get_db() as conn:
        assert db.transfer_adjustment_total(conn, ENV) == 0.0
        db.kv_set(conn, f"transfers:{ENV}:2026-07-01", "not-a-number")
        db.kv_set(conn, f"transfers:{ENV}:2026-07-02", repr(-10.0))
        assert db.transfer_adjustment_total(conn, ENV) == pytest.approx(-10.0)


def test_transfer_recorded_per_run_and_adjusts_session(fresh_db):
    with db.get_db() as conn:
        db.insert_pnl_snapshot(conn, cash_usd=500.0, portfolio_usd=0.0,
                               realized_pnl_usd=0.0, wins=0, losses=0,
                               open_positions=0, env=ENV)
        run_id = db.start_bot_run(conn, env=ENV, cash_usd=500.0, portfolio_usd=0.0)
        moved = db.note_transfer_if_unexplainable(conn, ENV, 300.0, run_id=run_id)
        assert moved == pytest.approx(-200.0)
        assert db.transfer_adjustment_run(conn, ENV, run_id) == pytest.approx(-200.0)
        assert db.transfer_adjustment_today(conn, ENV) == pytest.approx(-200.0)
        db.insert_pnl_snapshot(conn, cash_usd=300.0, portfolio_usd=0.0,
                               realized_pnl_usd=0.0, wins=0, losses=0,
                               open_positions=0, env=ENV)
        moved = db.note_transfer_if_unexplainable(conn, ENV, 250.0, run_id=run_id)
        assert moved == pytest.approx(-50.0)
        assert db.transfer_adjustment_run(conn, ENV, run_id) == pytest.approx(-250.0)
        assert db.transfer_adjustment_run(conn, ENV, run_id + 1) == 0.0
        assert db.transfer_adjustment_run(conn, ENV, 0) == 0.0
