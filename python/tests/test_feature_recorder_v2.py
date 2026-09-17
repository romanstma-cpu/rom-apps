import json
import math

import db
import main_recorder
import order_journal


def test_candidate_snapshot_captures_side_aware_book_shape():
    quote = {
        "bid_cents": 58,
        "ask_cents": 60,
        "bid_levels": [[58, 20], [57, 10], [56, 5]],
        "ask_levels": [[60, 5], [61, 5], [62, 10]],
        "quote_source": "websocket",
        "quote_age_ms": 125,
    }
    signal = {
        "ticker": "M1", "event_ticker": "E1", "price": .59,
        "confidence": 67, "market_volume": 100_000,
        "open_interest": 25_000, "dollar_value": 5_000,
    }
    snapshot = main_recorder.feature_snapshot(signal, "whale", quote, at=1000)
    assert snapshot["version"] == main_recorder.FEATURE_VERSION
    assert snapshot["bidCents"] == 58 and snapshot["askCents"] == 60
    assert snapshot["spreadCents"] == 2 and snapshot["midpointCents"] == 59
    assert snapshot["bidDepth3"] == 35 and snapshot["askDepth3"] == 20
    assert snapshot["bookImbalance3"] == (35 - 20) / 55
    assert snapshot["micropriceCents"] == (60 * 20 + 58 * 5) / 25
    assert snapshot["quoteSource"] == "websocket" and snapshot["quoteAgeMs"] == 125
    assert snapshot["marketVolume"] == 100_000
    assert all(not isinstance(value, float) or math.isfinite(value) for value in snapshot.values())


def test_missing_quote_records_unavailable_snapshot_without_inventing_book():
    snapshot = main_recorder.feature_snapshot(
        {"ticker": "M1", "price": .5, "confidence": 60}, "momentum", None, at=10,
    )
    assert snapshot["bookStatus"] == "unavailable"
    assert snapshot["bidCents"] is None and snapshot["askCents"] is None
    assert snapshot["spreadCents"] is None and snapshot["bookImbalance3"] is None


def test_live_entry_feature_snapshot_is_persisted_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "db_path", lambda: tmp_path / "features.db")
    db.init_db()
    snapshot = main_recorder.feature_snapshot(
        {"ticker": "M1", "price": .6, "confidence": 70}, "whale",
        {"bid_cents": 59, "ask_cents": 60,
         "bid_levels": [[59, 20]], "ask_levels": [[60, 10]]}, at=10,
    )
    order_journal.begin(
        "local-1", "M1", "yes", "buy", 2, .60,
        execution_context={"network": "mainnet", "source": "whale", "style": "crossing",
                           "signal_cents": 60, "bid_cents": 59, "ask_cents": 60,
                           "features": snapshot},
    )
    with db.get_db() as conn:
        row = conn.execute("SELECT payload FROM us_entry_features WHERE local_id='local-1'").fetchone()
    assert json.loads(row["payload"]) == snapshot
