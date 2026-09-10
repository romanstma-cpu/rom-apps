"""Main recorder edge cases: queue overflow, flush failure, book throttling.

The recorder is the durability layer for replay evidence. Its failure mode
under load is dropping events and recording a 'gap' marker — that marker is
what downstream replay uses to avoid treating gaps as absence of signal.
"""
from __future__ import annotations

import json
import time

import pytest

import db
import main_recorder


@pytest.fixture(autouse=True)
def isolated_recorder(tmp_path, monkeypatch):
    """Fresh scratch DB + isolated module state per test."""
    dbfile = tmp_path / "test-recorder-edge.db"
    monkeypatch.setattr(db, "db_path", lambda: dbfile)
    db.init_db()
    main_recorder.init()
    monkeypatch.setattr(main_recorder, "_queue", main_recorder.deque())
    monkeypatch.setattr(main_recorder, "_dropped", 0)
    monkeypatch.setattr(main_recorder, "_book_at", {})
    monkeypatch.setattr(main_recorder, "_last_prune", 0)
    monkeypatch.setattr(main_recorder, "_enabled", True)
    yield dbfile


class TestQueueOverflow:
    def test_overflow_records_gap_marker(self, monkeypatch):
        # Shrink the queue so a handful of events overflows it.
        monkeypatch.setattr(main_recorder, "MAX_QUEUE", 2)
        main_recorder.record("trade", "t1", {"id": 1})
        main_recorder.record("trade", "t2", {"id": 2})
        main_recorder.record("trade", "t3", {"id": 3})  # would overflow
        assert main_recorder._dropped == 1

        main_recorder.flush()
        with db.get_db() as c:
            rows = c.execute(
                "SELECT kind, payload FROM main_replay_events ORDER BY id"
            ).fetchall()
        kinds = [r["kind"] for r in rows]
        assert kinds.count("trade") == 2
        assert kinds.count("gap") == 1
        gap = next(r for r in rows if r["kind"] == "gap")
        assert json.loads(gap["payload"])["dropped"] == 1

    def test_flush_failure_counts_events_as_dropped(self, monkeypatch):
        """If the DB write throws, the batch cannot be retried (bounded
        queue already drained); the loss is counted in _dropped and will
        surface as a 'gap' marker on the next successful flush."""
        main_recorder.record("trade", "t1", {"id": 1})
        main_recorder.record("trade", "t2", {"id": 2})

        def boom():
            raise RuntimeError("db down")

        monkeypatch.setattr(db, "get_db", boom)
        with pytest.raises(RuntimeError):
            main_recorder.flush()

        # The 2 events could not be written; they are counted as dropped.
        assert main_recorder._dropped == 2
        # Queue drained, so nothing to retry.
        with main_recorder._lock:
            assert len(main_recorder._queue) == 0

    def test_flush_gap_marker_after_failure(self, monkeypatch):
        """A failed flush then a successful one records a gap marker with
        the dropped count, preserving the loss for replay integrity."""
        main_recorder.record("trade", "t1", {"id": 1})

        def boom():
            raise RuntimeError("db down")

        real_get_db = db.get_db
        monkeypatch.setattr(db, "get_db", boom)
        with pytest.raises(RuntimeError):
            main_recorder.flush()  # 1 trade lost here -> _dropped = 1
        monkeypatch.setattr(db, "get_db", real_get_db)

        main_recorder.flush()  # successful, writes gap marker
        with db.get_db() as c:
            rows = c.execute(
                "SELECT kind, payload FROM main_replay_events ORDER BY id"
            ).fetchall()
        assert [r["kind"] for r in rows] == ["gap"]
        assert json.loads(rows[0]["payload"])["dropped"] == 1

    def test_disabled_recorder_drops_everything(self, monkeypatch):
        monkeypatch.setattr(main_recorder, "_enabled", False)
        main_recorder.record("trade", "t1", {"id": 1})
        main_recorder.flush()
        with db.get_db() as c:
            n = c.execute("SELECT COUNT(*) FROM main_replay_events").fetchone()[0]
        assert n == 0


class TestBookThrottle:
    def test_book_events_throttled_to_1_per_second(self, monkeypatch):
        calls = []
        monkeypatch.setattr(main_recorder, "record", lambda *a, **k: calls.append(a))
        main_recorder.book("t1", {"bids": [], "offers": []})
        main_recorder.book("t1", {"bids": [], "offers": []})
        assert len(calls) == 1

    def test_different_tickers_not_throttled(self, monkeypatch):
        calls = []
        monkeypatch.setattr(main_recorder, "record", lambda *a, **k: calls.append(a))
        book = {"bids": [], "offers": []}
        main_recorder.book("t1", book)
        main_recorder.book("t2", book)
        assert len(calls) == 2


class TestLoad:
    def test_load_parses_payload_and_orders(self):
        main_recorder.record("trade", "t1", {"id": 1, "price": 2})
        main_recorder.record("trade", "t1", {"id": 2, "price": 3})
        main_recorder.flush()
        rows = main_recorder.load(1)
        assert len(rows) == 2
        assert rows[0]["payload"] == {"id": 1, "price": 2}
        assert rows[1]["payload"]["id"] == 2

    def test_load_honors_since_days(self):
        main_recorder.record("trade", "t1", {"id": 1}, at=time.time())
        main_recorder.flush()
        rows = main_recorder.load(1)
        assert len(rows) == 1
        rows = main_recorder.load(1, end=time.time() - 10)  # window in past
        assert len(rows) == 0

    def test_load_raises_on_oversized_window(self):
        with db.get_db() as c:
            c.executemany(
                "INSERT INTO main_replay_events(at,kind,ticker,payload) VALUES (?,?,?,?)",
                [(time.time(), "trade", "t", '{"id": %d}' % i) for i in range(100002)],
            )
        with pytest.raises(ValueError, match="100,000"):
            main_recorder.load(1)