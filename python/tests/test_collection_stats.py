"""The collection-stats RPC must keep the shape the Backtest screen reads.

This payload regressed once already: `alertsWindowed` was added to the Python
handler and the TypeScript type separately, and nothing checked the two agreed.
The screen renders `coll.main.alertsWindowed.toLocaleString()`, so a missing or
renamed field is a runtime error in the renderer, not a caught type error.

These tests call the real handler against a real database and compare the
result against the CollectionStats interface in shared/types.ts.
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest

import db
import momentum_window
import polymarket_auth
import service

REPO = Path(__file__).resolve().parents[2]
TYPES = REPO / "shared" / "types.ts"
ENV = "mainnet"


@pytest.fixture
def stats_db(tmp_path, monkeypatch):
    dbfile = tmp_path / "collection-stats.db"
    monkeypatch.setattr(db, "db_path", lambda: dbfile)
    monkeypatch.setattr(polymarket_auth, "get_env", lambda: ENV)
    db.init_db()
    return dbfile


def call() -> dict:
    return asyncio.run(service._h_collection_stats({}))


def declared_fields(interface: str, block: str) -> set[str]:
    """Top-level field names of a nested block in a TS interface.

    Only the outer level counts: `recent` is an array of row objects whose own
    fields are nested one level deeper and are not part of this contract.
    """
    source = TYPES.read_text(encoding="utf-8")
    start = source.index(f"interface {interface}")
    body = source[start:source.index("\n}\n", start)]
    opening = re.search(rf"\b{block}:\s*\{{", body)
    assert opening, f"{block} not found in {interface}"

    depth = 0
    fields: set[str] = set()
    index = opening.end() - 1
    for match in re.finditer(r"[{}]|(\w+)\??:", body[index:]):
        token = match.group(0)
        if token == "{":
            depth += 1
        elif token == "}":
            depth -= 1
            if depth == 0:
                break
        elif depth == 1 and match.group(1):
            fields.add(match.group(1))
    return fields


def test_handler_returns_the_documented_top_level_sections(stats_db):
    result = call()
    assert set(result) == {"c15", "main", "collecting"}


def test_main_section_matches_the_typescript_interface(stats_db):
    """Every field the renderer may read must exist in the payload."""
    expected = declared_fields("CollectionStats", "main")
    actual = set(call()["main"])
    missing = sorted(expected - actual)
    assert not missing, (
        f"CollectionStats.main declares these fields but the RPC omits them: "
        f"{missing}"
    )


def test_c15_section_matches_the_typescript_interface(stats_db):
    expected = declared_fields("CollectionStats", "c15")
    actual = set(call()["c15"])
    missing = sorted(expected - actual)
    assert not missing, f"CollectionStats.c15 omits: {missing}"


def test_counts_are_zero_on_an_empty_database_not_null(stats_db):
    """The screen formats these with toLocaleString; null would throw."""
    main = call()["main"]
    for field in ("whales", "whalesResolved", "alerts", "alertsResolved",
                  "alertsWindowed"):
        assert main[field] == 0, f"{field} should be 0 on an empty database"
        assert isinstance(main[field], int)


def test_windowed_count_separates_measurement_regimes(stats_db):
    """Legacy 24h-derived alerts must not be counted as window-measured."""
    with db.get_db() as conn:
        conn.execute(
            "INSERT INTO alerts (ticker, signal_type, direction, price, confidence)"
            " VALUES ('OLD','trade_cluster','yes',0.4,55)")
        db.insert_alert(conn, {
            "ticker": "NEW", "signal_type": "trade_cluster", "direction": "no",
            "price": 0.62, "confidence": 61,
            "score_version": momentum_window.SCORE_VERSION,
            "window_trades": 6, "window_dollars": 1596.0, "observed_at": 1.0e9,
        })
    main = call()["main"]
    assert main["alerts"] == 2
    assert main["alertsWindowed"] == 1


def test_recent_rows_are_serializable_dictionaries(stats_db):
    """The payload crosses an IPC boundary; sqlite Row objects do not."""
    result = call()
    for section in ("c15", "main"):
        for row in result[section]["recent"]:
            assert isinstance(row, dict), f"{section}.recent holds a non-dict"


def test_resolved_counts_survive_a_null_sum(stats_db):
    """SUM() over no rows returns NULL; the handler must coerce it."""
    with db.get_db() as conn:
        conn.execute(
            "INSERT INTO alerts (ticker, signal_type, direction, price, confidence)"
            " VALUES ('X','trade_cluster','yes',0.4,55)")
    main = call()["main"]
    assert main["alertsResolved"] == 0
