"""Tests for main_recorder event storage, pruning, and indexing."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import pytest

import db
import main_recorder


@pytest.fixture
def fresh_recorder_db(tmp_path, monkeypatch):
    dbfile = tmp_path / "test-recorder.db"
    monkeypatch.setattr(db, "db_path", lambda: dbfile)
    db.init_db()
    main_recorder.init()
    monkeypatch.setattr(main_recorder, "_queue", main_recorder.deque())
    monkeypatch.setattr(main_recorder, "_dropped", 0)
    monkeypatch.setattr(main_recorder, "_book_at", {})
    monkeypatch.setattr(main_recorder, "_last_prune", 0)
    monkeypatch.setattr(main_recorder, "_enabled", True)
    return dbfile


def test_record_and_flush_persists_events(fresh_recorder_db, monkeypatch):
    now = time.time()
    monkeypatch.setattr(main_recorder.time, "time", lambda: now)

    main_recorder.record("trade", "TCK1", {"price": 0.5, "qty": 10}, at=now)
    main_recorder.record("market", "TCK1", {"status": "open"}, at=now + 1)
    main_recorder.flush()

    events = main_recorder.load(1, end=now + 10)
    assert len(events) == 2
    assert events[0]["kind"] == "trade"
    assert events[0]["ticker"] == "TCK1"
    assert events[0]["payload"]["price"] == 0.5
    assert events[1]["kind"] == "market"


def test_book_recording_throttles_to_one_second(fresh_recorder_db, monkeypatch):
    now = time.time()
    monkeypatch.setattr(main_recorder.time, "time", lambda: now)
    main_recorder.book("TCK1", {"bids": [{"px": {"value": ".5"}, "qty": "100"}]})
    assert len(main_recorder._queue) == 1

    # Immediate next book within 1s should be throttled out
    main_recorder.book("TCK1", {"bids": [{"px": {"value": ".51"}, "qty": "100"}]})
    assert len(main_recorder._queue) == 1

    # Book after 1.5s should record
    monkeypatch.setattr(main_recorder.time, "time", lambda: now + 1.5)
    main_recorder.book("TCK1", {"bids": [{"px": {"value": ".52"}, "qty": "100"}]})
    assert len(main_recorder._queue) == 2


def test_prune_query_plan_uses_covering_index(fresh_recorder_db):
    """Verify that pruning utilizes the main_replay_time index."""
    with db.get_db() as c:
        q = "SELECT id FROM main_replay_events ORDER BY at DESC, id DESC LIMIT 1 OFFSET 499999"
        plan = [tuple(r) for r in c.execute("EXPLAIN QUERY PLAN " + q)]
        assert any("USING COVERING INDEX main_replay_time" in r[3] for r in plan)


def test_age_and_count_pruning(fresh_recorder_db, monkeypatch):
    now = time.time()
    monkeypatch.setattr(main_recorder.time, "time", lambda: now)

    # Insert events: some very old (>60 days), some fresh
    with db.get_db() as c:
        old_batch = [(now - 70 * 86400 + i, "book", "OLD", '{"val": 1}') for i in range(10)]
        fresh_batch = [(now - 10 * 86400 + i, "book", "FRESH", '{"val": 2}') for i in range(5)]
        c.executemany("INSERT INTO main_replay_events(at,kind,ticker,payload) VALUES (?,?,?,?)", old_batch + fresh_batch)

    # Record 1 event to ensure queue is non-empty so flush() executes
    main_recorder.record("market", "TRIGGER", {"status": "open"}, at=now)
    main_recorder.flush()

    with db.get_db() as c:
        rows = c.execute("SELECT ticker FROM main_replay_events").fetchall()
        tickers = [r[0] for r in rows]
        assert "OLD" not in tickers
        assert "FRESH" in tickers
        assert "TRIGGER" in tickers
        assert len(tickers) == 6
