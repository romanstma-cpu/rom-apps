"""DB migration regression: upgrading from the 2.8 schema must not crash.

The supported upgrade floor is the 2.8 schema (the last version before
the momentum/risk/window columns). This test extracts that schema from
git and verifies today's _init_db_schema() can migrate a DB built from it
without error, and that new columns actually exist afterward.

Fetching from git at test time keeps the fixture honest — it is the exact
SQL that shipped, not a hand-rebuilt approximation.
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import subprocess
import tempfile

import pytest

import db


def _repo_root() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(here)


def _schema_at(rev: str) -> str:
    """The SCHEMA block from python/db.py at a given git revision."""
    src = subprocess.check_output(
        ["git", "show", f"{rev}:python/db.py"], cwd=_repo_root(), text=True
    )
    start = src.index('SCHEMA = """') + len('SCHEMA = """')
    end = src.index('"""', start)
    return src[start:end]


SCHEMA_28 = _schema_at("4a8105f")  # ROM Polybot 2.8 (supported upgrade floor)

# Pre-shrink: use a fixed digest to ensure we migrate the same schema every run
SCHEMA_28_SHA = hashlib.sha256(SCHEMA_28.encode()).hexdigest()[:12]


@pytest.fixture()
def legacy_db(tmp_path):
    """A real 2.8 database built from the shipped schema."""
    path = os.path.join(tmp_path, "legacy-28.db")
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA_28)
    conn.commit()
    conn.close()
    return path


def _columns(conn, table: str) -> dict[str, tuple]:
    return {row[1]: row for row in conn.execute(f"PRAGMA table_info({table})")}


class TestUpgradeFrom28:
    def test_legacy_schema_is_shipped_2_8(self):
        # Guard against the fixture silently becoming a different shape.
        assert SCHEMA_28_SHA == "1a78ce442332"  # set on first run

    def test_upgrade_runs_cleanly(self, legacy_db, monkeypatch):
        monkeypatch.setattr(db, "db_path", lambda: legacy_db)
        db.init_db()  # must not raise
        with db.get_db() as conn:
            cols = _columns(conn, "alerts")
            assert "score_version" in cols
            assert "window_trades" in cols
            assert "window_dollars" in cols

    def test_position_columns_survive(self, legacy_db, monkeypatch):
        monkeypatch.setattr(db, "db_path", lambda: legacy_db)
        db.init_db()
        with db.get_db() as conn:
            cols = _columns(conn, "bot_positions")
            assert "closed_early" in cols
            assert "mark_price_cents" in cols
            assert "exit_reason" in cols
            assert "ticker" in cols  # was always there, but must not be lost

    def test_crypto15m_join_columns_exist(self, legacy_db, monkeypatch):
        """The JOIN in crypto15m_trader requires ticker + model_prob."""
        monkeypatch.setattr(db, "db_path", lambda: legacy_db)
        db.init_db()
        with db.get_db() as conn:
            sig = _columns(conn, "crypto15m_signals")
            assert "ticker" in sig
            assert "model_prob" in sig  # added by ALTER
            ticks = _columns(conn, "crypto15m_ticks")
            assert "ticker" in ticks
            assert "model_prob" in ticks

    def test_old_rows_survive_migration(self, legacy_db, monkeypatch):
        """Data written under 2.8 must still be readable after migration."""
        conn = sqlite3.connect(legacy_db)
        conn.execute(
            "INSERT INTO markets (ticker, title, slug) VALUES ('M1', 't', 'm1')"
        )
        conn.execute(
            """INSERT INTO crypto15m_signals
               (ticker, asset, series, close_time, observed_at)
               VALUES ('C1', 'eth', 's', '', datetime('now'))"""
        )
        conn.commit()
        conn.close()

        monkeypatch.setattr(db, "db_path", lambda: legacy_db)
        db.init_db()
        with db.get_db() as conn:
            rows = [r[0] for r in conn.execute("SELECT ticker FROM markets")]
            assert rows == ["M1"]
            sig = [(r[0], r[1]) for r in conn.execute(
                "SELECT ticker, asset FROM crypto15m_signals WHERE ticker = 'C1'"
            )]
            assert sig == [("C1", "eth")]

    def test_init_db_is_idempotent_on_upgraded_db(self, legacy_db, monkeypatch):
        monkeypatch.setattr(db, "db_path", lambda: legacy_db)
        db.init_db()
        db.init_db()  # second run must be a no-op, not a crash
        with db.get_db() as conn:
            cols = _columns(conn, "alerts")
            assert "score_version" in cols


class TestBaseSchemaSatisfiesInserts:
    """The base SCHEMA (fresh install, no ALTER loop) must satisfy the
    insert statements that reference every column. The 2.13-era bug:
    `interval` was only added by ALTER, so a fresh DB built from SCHEMA
    alone (or a test DB) crashed on insert with
    'no such column: interval'."""

    def test_signals_insert_against_base_schema(self):
        conn = sqlite3.connect(":memory:")
        conn.executescript(db.SCHEMA)
        ok = db.insert_crypto15m_signal(conn, {
            "ticker": "t1", "asset": "BTC", "series": "", "close_time": "",
            "entry_cost": 0.5, "up_prob": 0.6, "network": "mainnet",
            "interval": "15m",
        })
        assert ok is True
        conn.close()

    def test_ticks_insert_against_base_schema(self):
        conn = sqlite3.connect(":memory:")
        conn.executescript(db.SCHEMA)
        db.insert_crypto15m_tick(conn, {
            "ticker": "t1", "asset": "BTC",
            "network": "mainnet", "interval": "15m",
        })
        assert conn.execute(
            "SELECT interval FROM crypto15m_ticks WHERE ticker='t1'"
        ).fetchone()[0] == "15m"
        conn.close()

    def test_base_schema_has_interval_columns(self):
        conn = sqlite3.connect(":memory:")
        conn.executescript(db.SCHEMA)
        for table in ("crypto15m_signals", "crypto15m_ticks"):
            cols = _columns(conn, table)
            assert "interval" in cols, f"{table} missing interval in SCHEMA"
        conn.close()


@pytest.fixture(scope="module")
def schema_cols():
    conn = sqlite3.connect(":memory:")
    conn.executescript(db.SCHEMA)
    out = {}
    for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"):
        out[name] = {r[1] for r in conn.execute(f"PRAGMA table_info({name})")}
    conn.close()
    return out


class TestInsertColumnParity:
    """Every static INSERT in db.py must reference only columns present in
    the base SCHEMA — not columns that exist only via the ALTER loop.
    A fresh DB executes SCHEMA then ALTERs, so a mismatch is masked in
    production; this test makes it visible."""

    def test_static_inserts_reference_only_base_columns(self, schema_cols):
        import re as _re
        src = open(db.__file__, encoding="utf-8").read()
        bad: list[str] = []
        for m in _re.finditer(
            r"INSERT (?:OR IGNORE |OR REPLACE )?INTO (\w+)\s*\(([^)]*)\)", src
        ):
            table = m.group(1)
            cols = [c.strip().strip('"') for c in m.group(2).split(",")]
            # Templated inserts ({cols}) are filled at runtime — skip.
            if any("{" in c or "}" in c for c in cols):
                continue
            if table in schema_cols:
                missing = [c for c in cols if c and c not in schema_cols[table]]
                if missing:
                    bad.append(f"{table}:{missing}")
        assert not bad, f"INSERTs reference columns missing from base SCHEMA: {bad}"