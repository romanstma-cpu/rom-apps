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