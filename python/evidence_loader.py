"""Bounded database reads for the Evidence models.

The recorder can retain far more raw market snapshots than either model needs.
Load each evidence type independently so noisy quote history cannot crowd out
signals or settlements, then restore chronological order for leakage-safe fits.
"""
from __future__ import annotations

import json
import time

import db


LOOKBACK_SECONDS = 60 * 86400
ROW_LIMITS = {"signal": 40_000, "settlement": 40_000, "market": 20_000}


def load_recent_events(now: float | None = None):
    now = time.time() if now is None else now
    since = now - LOOKBACK_SECONDS
    records = []
    available = {}
    with db.get_db() as conn:
        for kind, limit in ROW_LIMITS.items():
            available[kind] = int(conn.execute(
                "SELECT COUNT(*) FROM main_replay_events WHERE at>=? AND kind=?",
                (since, kind),
            ).fetchone()[0])
            records.extend(conn.execute(
                "SELECT id,at,kind,ticker,payload FROM main_replay_events "
                "WHERE at>=? AND kind=? ORDER BY at DESC,id DESC LIMIT ?",
                (since, kind, limit),
            ).fetchall())

    records.sort(key=lambda row: (row["at"], row["id"]))
    events = [{**dict(row), "payload": json.loads(row["payload"])} for row in records]
    loaded = {kind: min(count, ROW_LIMITS[kind]) for kind, count in available.items()}
    return events, {
        "availableRows": sum(available.values()),
        "loadedRows": len(events),
        "availableByKind": available,
        "loadedByKind": loaded,
        "truncated": any(available[kind] > ROW_LIMITS[kind] for kind in ROW_LIMITS),
    }
