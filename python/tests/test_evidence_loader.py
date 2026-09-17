import json

import pytest

import db
import evidence_loader
import main_recorder


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    dbfile = tmp_path / "evidence.db"
    monkeypatch.setattr(db, "db_path", lambda: dbfile)
    db.init_db()
    return dbfile


def test_large_evidence_store_is_bounded_per_kind_and_stays_chronological(fresh_db, monkeypatch):
    main_recorder.init()
    now = 2_000_000_000.0
    monkeypatch.setattr(evidence_loader, "ROW_LIMITS", {
        "signal": 3, "settlement": 2, "market": 1,
    })
    rows = []
    for kind, count in (("signal", 5), ("settlement", 4), ("market", 6)):
        for index in range(count):
            rows.append((now - 100 + index, kind, f"{kind}-{index}", json.dumps({"n": index})))
    with db.get_db() as conn:
        conn.executemany(
            "INSERT INTO main_replay_events(at,kind,ticker,payload) VALUES (?,?,?,?)",
            rows,
        )

    events, window = evidence_loader.load_recent_events(now)

    assert [event["at"] for event in events] == sorted(event["at"] for event in events)
    assert {kind: sum(event["kind"] == kind for event in events)
            for kind in evidence_loader.ROW_LIMITS} == evidence_loader.ROW_LIMITS
    assert window == {
        "availableRows": 15,
        "loadedRows": 6,
        "availableByKind": {"signal": 5, "settlement": 4, "market": 6},
        "loadedByKind": {"signal": 3, "settlement": 2, "market": 1},
        "truncated": True,
    }
    assert {event["ticker"] for event in events if event["kind"] == "signal"} == {
        "signal-2", "signal-3", "signal-4",
    }
