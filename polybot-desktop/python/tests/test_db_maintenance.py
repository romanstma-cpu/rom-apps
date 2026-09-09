from __future__ import annotations

from datetime import datetime, timezone

import pytest

import db


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    dbfile = tmp_path / "maint.db"
    monkeypatch.setattr(db, "db_path", lambda: dbfile)
    db.init_db()
    return dbfile


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


_OLD = "2000-01-01 00:00:00"


def _add_trade(c, tid: str, when: str) -> None:
    c.execute(
        "INSERT INTO trades (trade_id,ticker,event_ticker,count_fp,yes_price,"
        "no_price,taker_side,dollar_value,category,created_time) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (tid, "KX", "E", 1.0, 50, 50, "yes", 100.0, "crypto", when),
    )


def test_cleanup_prunes_old_keeps_recent(fresh_db):
    now = _now()
    with db.get_db() as c:
        _add_trade(c, "old1", _OLD)
        _add_trade(c, "old2", _OLD)
        _add_trade(c, "fresh", now)
        c.execute(
            "INSERT INTO market_snapshots (ticker,volume,volume_24h,open_interest,"
            "yes_bid,last_price,snapshot_at) VALUES (?,?,?,?,?,?,?)",
            ("KX", 100, 50, 10, 50, 50, _OLD),
        )
        c.execute(
            "INSERT INTO market_snapshots (ticker,volume,volume_24h,open_interest,"
            "yes_bid,last_price,snapshot_at) VALUES (?,?,?,?,?,?,?)",
            ("KX", 100, 50, 10, 50, 50, now),
        )

    deleted = db.cleanup_old_data()

    with db.get_db() as c:
        trades = [r["trade_id"] for r in c.execute("SELECT trade_id FROM trades")]
        snaps = c.execute("SELECT COUNT(*) FROM market_snapshots").fetchone()[0]
    assert trades == ["fresh"]
    assert snaps == 1
    assert deleted >= 3


def test_batched_delete_clears_a_large_backlog(fresh_db):
    import db as _db
    with db.get_db() as c:
        for i in range(250):
            _add_trade(c, f"t{i}", _OLD)
    n = _db._delete_batched("created_time < ?", (_now(),), "trades", batch=100)
    assert n == 250
    with db.get_db() as c:
        assert c.execute("SELECT COUNT(*) FROM trades").fetchone()[0] == 0


def test_run_maintenance_compacts_when_forced(fresh_db):
    with db.get_db() as c:
        for i in range(1000):
            _add_trade(c, f"t{i}", _OLD)
    summary = db.run_maintenance(force_vacuum=True)
    assert summary["vacuumed"] is True
    assert summary["deleted"] >= 1000
    with db.get_db() as c:
        assert c.execute("SELECT COUNT(*) FROM trades").fetchone()[0] == 0


def _seed_history(c) -> None:
    db.insert_bot_position(c, {
        "signal_source": "whale", "signal_id": "s1", "ticker": "KX-A",
        "direction": "yes", "target_contracts": 10, "limit_price_cents": 55,
        "client_order_id": "coid-a", "status": "filled",
    })
    db.insert_crypto15m_position(c, {
        "asset": "BTC", "series": "KXBTC15M", "ticker": "KXBTC15M-W1",
        "side": "up", "direction": "yes", "target_contracts": 5,
        "entry_limit_cents": 50, "client_order_id": "coid-c", "status": "filled",
    })
    db.start_bot_run(c, env="mainnet", cash_usd=100.0, portfolio_usd=0.0)
    db.insert_pnl_snapshot(
        c, cash_usd=100.0, portfolio_usd=0.0, realized_pnl_usd=5.0,
        wins=1, losses=0, open_positions=1, env="mainnet",
    )
    c.execute(
        "INSERT INTO daily_stats (day, network) VALUES (?,?)",
        ("2026-06-27", "mainnet"),
    )
    c.execute(
        "INSERT INTO order_events (position_id, kind, note) VALUES (?,?,?)",
        (1, "placed", "seeded"),
    )
    _add_trade(c, "keepme", _now())


def test_clear_trade_history_wipes_history_keeps_feed(fresh_db):
    with db.get_db() as c:
        _seed_history(c)

    summary = db.clear_trade_history()

    assert "_errors" not in summary
    with db.get_db() as c:
        for t in (
            "bot_positions", "crypto15m_positions", "bot_runs",
            "pnl_snapshots", "daily_stats", "order_events",
        ):
            assert c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == 0, t
        kept = [r["trade_id"] for r in c.execute("SELECT trade_id FROM trades")]
        assert kept == ["keepme"]
    assert summary["bot_positions"] == 1
    assert summary["crypto15m_positions"] == 1


def test_clear_trade_history_on_empty_db_is_noop(fresh_db):
    summary = db.clear_trade_history()
    assert "_errors" not in summary
    assert all(v == 0 for v in summary.values())


def test_factory_reset_wipes_crypto15m_positions(fresh_db):
    with db.get_db() as c:
        db.insert_crypto15m_position(c, {
            "asset": "BTC", "series": "KXBTC15M", "ticker": "T",
            "side": "up", "direction": "yes", "target_contracts": 5,
            "entry_limit_cents": 80, "client_order_id": "c1", "status": "filled",
            "network": "mainnet",
        })
    summary = db.factory_reset()
    assert summary.get("crypto15m_positions") == 1
    with db.get_db() as c:
        assert c.execute("SELECT COUNT(*) FROM crypto15m_positions").fetchone()[0] == 0


def test_unresolved_alerts_and_whales_age_out(fresh_db):
    with db.get_db() as conn:
        conn.execute(
            """INSERT INTO alerts (ticker, title, signal_type, direction, price,
                                   confidence, resolved, created_at)
               VALUES ('OLD-A', 't', 'trade_cluster', 'yes', 0.4, 60, 0,
                       datetime('now', '-60 days'))"""
        )
        conn.execute(
            """INSERT INTO whale_trades (trade_id, ticker, title, taker_side,
                                         count_fp, price, dollar_value, confidence,
                                         resolved, created_at)
               VALUES ('OLD-W', 'OLD-W-T', 't', 'yes', 100, 0.5, 5000, 70, 0,
                       datetime('now', '-60 days'))"""
        )
        conn.execute(
            """INSERT INTO alerts (ticker, title, signal_type, direction, price,
                                   confidence, resolved)
               VALUES ('NEW-A', 't', 'trade_cluster', 'yes', 0.4, 60, 0)"""
        )

    db.cleanup_old_data()

    with db.get_db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM alerts WHERE ticker='OLD-A'").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM whale_trades WHERE trade_id='OLD-W'").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM alerts WHERE ticker='NEW-A'").fetchone()[0] == 1


def test_events_table_is_pruned(fresh_db):
    with db.get_db() as conn:
        conn.execute(
            """INSERT INTO events (event_ticker, title, last_updated)
               VALUES ('OLD-EV', 'old', datetime('now', '-45 days'))"""
        )
        conn.execute(
            """INSERT INTO events (event_ticker, title, last_updated)
               VALUES ('NEW-EV', 'new', datetime('now'))"""
        )
    db.cleanup_old_data()
    with db.get_db() as conn:
        rows = {r[0] for r in conn.execute("SELECT event_ticker FROM events").fetchall()}
    assert rows == {"NEW-EV"}


def test_order_events_are_pruned(fresh_db):
    with db.get_db() as conn:
        conn.execute(
            """INSERT INTO order_events (position_id, kind, created_at)
               VALUES (1, 'poll', datetime('now', '-45 days'))"""
        )
        conn.execute(
            "INSERT INTO order_events (position_id, kind) VALUES (2, 'poll')"
        )
    db.cleanup_old_data()
    with db.get_db() as conn:
        rows = [r[0] for r in conn.execute("SELECT position_id FROM order_events").fetchall()]
    assert rows == [2]


def test_pnl_snapshots_query_downsamples(fresh_db):
    with db.get_db() as conn:
        for i in range(500):
            conn.execute(
                """INSERT INTO pnl_snapshots (at, network, cash_usd,
                                              portfolio_usd, total_usd)
                   VALUES (datetime('now', ?), 'mainnet', 100, 0, ?)""",
                (f"-{500 - i} minutes", 100.0 + i),
            )
    with db.get_db() as conn:
        rows = db.get_pnl_snapshots(conn, since_hours=24, env="mainnet", max_points=100)
    assert 0 < len(rows) <= 101
    assert rows[-1]["total_usd"] == pytest.approx(599.0)
    with db.get_db() as conn:
        rows_1h = db.get_pnl_snapshots(conn, since_hours=1, env="mainnet", max_points=0)
    assert 55 <= len(rows_1h) <= 62


def test_backup_research_creates_and_reuses_daily_copy(fresh_db):
    dest = db.backup_research()
    assert dest is not None
    import os
    assert os.path.exists(dest)
    assert db.backup_research() == dest


def test_factory_reset_takes_backup_first(fresh_db):
    import os
    with db.get_db() as c:
        db.insert_crypto15m_position(c, {
            "asset": "BTC", "series": "KXBTC15M", "ticker": "T-BAK",
            "side": "up", "direction": "yes", "target_contracts": 5,
            "entry_limit_cents": 80, "client_order_id": "cb", "status": "filled",
            "network": "mainnet",
        })
    db.factory_reset()
    bdir = os.path.join(os.path.dirname(str(db.db_path())), "backups")
    backups = [f for f in os.listdir(bdir) if f.startswith("research-")]
    assert backups, "factory_reset must snapshot the DB before wiping"
    import sqlite3 as _sq
    bconn = _sq.connect(os.path.join(bdir, backups[0]))
    try:
        n = bconn.execute(
            "SELECT COUNT(*) FROM crypto15m_positions WHERE ticker='T-BAK'"
        ).fetchone()[0]
    finally:
        bconn.close()
    assert n == 1


def _make_marker_db(path) -> None:
    import sqlite3 as _sq
    conn = _sq.connect(str(path))
    try:
        conn.execute("CREATE TABLE marker (v TEXT)")
        conn.execute("INSERT INTO marker VALUES ('survived')")
        conn.commit()
    finally:
        conn.close()


def _marker_survived(path) -> bool:
    import sqlite3 as _sq
    conn = _sq.connect(str(path))
    try:
        return conn.execute("SELECT v FROM marker").fetchone()[0] == "survived"
    finally:
        conn.close()


def test_db_restores_from_local_backups_when_missing(tmp_path, monkeypatch):
    ud = tmp_path / "userdata"
    monkeypatch.setenv("ROM_POLYBOT_USERDATA", str(ud))
    monkeypatch.setenv("ROM_POLYBOT_VAULT", str(tmp_path / "vault"))
    bdir = ud / "data" / "backups"
    bdir.mkdir(parents=True)
    _make_marker_db(bdir / "research-20990101.db")
    monkeypatch.setattr(db, "_restore_checked", False)
    p = db.db_path()
    assert p.exists() and _marker_survived(p)


def test_db_restores_from_vault_after_full_userdata_wipe(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    monkeypatch.setenv("ROM_POLYBOT_VAULT", str(vault))
    monkeypatch.setenv("ROM_POLYBOT_USERDATA", str(tmp_path / "old-userdata"))
    snap = tmp_path / "research-20990101.db"
    _make_marker_db(snap)
    db._mirror_to_vault(str(snap))
    assert (vault / "default" / "research-latest.db").exists()
    monkeypatch.setenv("ROM_POLYBOT_USERDATA", str(tmp_path / "new-userdata"))
    monkeypatch.setattr(db, "_restore_checked", False)
    p = db.db_path()
    assert p.exists() and _marker_survived(p)


def test_db_restore_prefers_newest_local_backup_over_vault(tmp_path, monkeypatch):
    ud = tmp_path / "userdata"
    vault = tmp_path / "vault"
    monkeypatch.setenv("ROM_POLYBOT_USERDATA", str(ud))
    monkeypatch.setenv("ROM_POLYBOT_VAULT", str(vault))
    bdir = ud / "data" / "backups"
    bdir.mkdir(parents=True)
    _make_marker_db(bdir / "research-20990101.db")
    (vault / "default").mkdir(parents=True)
    import sqlite3 as _sq
    conn = _sq.connect(str(vault / "default" / "research-latest.db"))
    conn.execute("CREATE TABLE marker (v TEXT)")
    conn.execute("INSERT INTO marker VALUES ('vault-older')")
    conn.commit()
    conn.close()
    monkeypatch.setattr(db, "_restore_checked", False)
    p = db.db_path()
    assert _marker_survived(p)


def test_no_restore_when_db_already_exists(tmp_path, monkeypatch):
    ud = tmp_path / "userdata"
    monkeypatch.setenv("ROM_POLYBOT_USERDATA", str(ud))
    monkeypatch.setenv("ROM_POLYBOT_VAULT", str(tmp_path / "vault"))
    (ud / "data").mkdir(parents=True)
    live = ud / "data" / "rom-polybot.db"
    _make_marker_db(live)
    bdir = ud / "data" / "backups"
    bdir.mkdir(parents=True)
    import sqlite3 as _sq
    conn = _sq.connect(str(bdir / "research-20990101.db"))
    conn.execute("CREATE TABLE marker (v TEXT)")
    conn.execute("INSERT INTO marker VALUES ('backup-must-not-clobber')")
    conn.commit()
    conn.close()
    monkeypatch.setattr(db, "_restore_checked", False)
    assert _marker_survived(db.db_path())
