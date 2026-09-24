"""Late recorded candidates can acquire public outcomes without orders."""
import asyncio
import time
from datetime import datetime, timedelta, timezone

import db
import main_recorder
import polymarket_api
import scanner


def test_late_candidate_followup_is_bounded_and_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "db_path", lambda: tmp_path / "followup.db")
    db.init_db()
    main_recorder.init()
    monkeypatch.setattr(main_recorder, "_queue", main_recorder.deque())
    monkeypatch.setattr(main_recorder, "_enabled", True)
    monkeypatch.setattr(main_recorder, "_last_prune", 0)
    monkeypatch.setattr(scanner, "_signal_settlement_retry_at", {})
    now = time.time()
    with db.get_db() as conn:
        conn.executemany(
            "INSERT INTO main_replay_events(at,kind,ticker,payload) VALUES (?,?,?,?)",
            [(now - 40 * 86400, "signal", "LATE", '{}'),
             (now - 40 * 86400, "signal", "FUTURE", '{}')],
        )
        db.upsert_market(conn, {
            "ticker": "FUTURE",
            "close_time": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        })

    calls = []
    settled = [False]

    async def fetch_market(ticker):
        calls.append(ticker)
        if not settled[0]:
            return {"status": "closed", "result": ""}
        main_recorder.record("settlement", ticker, {"yes_payout": 1})
        return {"status": "settled", "result": "yes"}

    monkeypatch.setattr(scanner.polymarket_api, "fetch_market", fetch_market)
    assert asyncio.run(scanner.resolve_recorded_signal_settlements(limit=1, now=now)) == 0
    assert calls == ["LATE"]
    # An exchange closure is not a binary outcome. Wait for a later confirmed
    # settlement, then avoid polling that ticker again after it is recorded.
    scanner._signal_settlement_retry_at.clear()
    settled[0] = True
    assert asyncio.run(scanner.resolve_recorded_signal_settlements(limit=1, now=now)) == 1
    assert asyncio.run(scanner.resolve_recorded_signal_settlements(limit=1, now=now)) == 0
    assert calls == ["LATE", "LATE"]
    with db.get_db() as conn:
        rows = conn.execute(
            "SELECT payload FROM main_replay_events WHERE kind='settlement'"
        ).fetchall()
    assert len(rows) == 1


def test_followup_records_binary_public_settlement_without_account_funds(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "db_path", lambda: tmp_path / "public-followup.db")
    db.init_db()
    main_recorder.init()
    monkeypatch.setattr(main_recorder, "_queue", main_recorder.deque())
    monkeypatch.setattr(main_recorder, "_enabled", True)
    monkeypatch.setattr(scanner, "_signal_settlement_retry_at", {})
    now = time.time()
    with db.get_db() as conn:
        conn.execute(
            "INSERT INTO main_replay_events(at,kind,ticker,payload) VALUES (?,?,?,?)",
            (now - 40 * 86400, "signal", "PUBLIC", '{}'),
        )

    calls = []

    async def public_request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        if path == "/v1/markets":
            return {"markets": [{"slug": "PUBLIC", "closed": True}]}
        if path == "/v1/markets/PUBLIC/settlement":
            return {"settlement": {"value": "1"}}
        raise AssertionError(f"Unexpected endpoint: {path}")

    monkeypatch.setattr(polymarket_api, "_request", public_request)
    assert asyncio.run(scanner.resolve_recorded_signal_settlements(now=now)) == 1
    assert [path for _, path, _ in calls] == [
        "/v1/markets", "/v1/markets/PUBLIC/settlement",
    ]
    assert all(not kwargs.get("private") for _, _, kwargs in calls)
    with db.get_db() as conn:
        row = conn.execute(
            "SELECT payload FROM main_replay_events WHERE kind='settlement' AND ticker='PUBLIC'"
        ).fetchone()
    assert row is not None
    assert '"yes_payout": 1.0' in row['payload']
