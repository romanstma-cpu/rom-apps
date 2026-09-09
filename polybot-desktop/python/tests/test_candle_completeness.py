from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

import crypto15m
import indicators


class _FakeResp:
    def __init__(self, rows):
        self._rows = rows

    def raise_for_status(self):
        return None

    def json(self):
        return self._rows


class _FakeClient:
    def __init__(self, rows):
        self._rows = rows

    async def post(self, *_a, **_k):
        return _FakeResp(self._rows)


def _candles(closes, *, last_in_progress: bool):
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    minute = (now_ms // 60_000) * 60_000
    rows = []
    n = len(closes)
    for i, c in enumerate(closes):
        t = minute - (n - 1 - i) * 60_000
        rows.append({"t": t, "T": t + 59_999, "c": str(c), "v": "1"})
    if not last_in_progress:
        for r in rows:
            r["t"] -= 60_000
            r["T"] -= 60_000
    return rows


def _closes(rows):
    got, _vol = asyncio.run(
        crypto15m._fetch_closes("BTC", _FakeClient(rows), 10))
    return got


def test_in_progress_candle_is_dropped():
    rows = _candles([100.0, 101.0, 102.0], last_in_progress=True)
    assert _closes(rows) == [100.0, 101.0]


def test_completed_candles_are_all_kept():
    rows = _candles([100.0, 101.0, 102.0], last_in_progress=False)
    assert _closes(rows) == [100.0, 101.0, 102.0]


def test_velocity_reflects_a_FULL_minute_not_a_partial_one():
    rows = _candles([64385.0, 64381.0, 64381.0], last_in_progress=True)
    vals = _closes(rows)
    v = indicators.pct_change(vals, 1)
    assert v is not None
    assert v == pytest.approx(-0.0062, abs=5e-4), v
    naive = indicators.pct_change([64385.0, 64381.0, 64381.0], 1)
    assert naive == pytest.approx(0.0)


def test_rows_without_a_close_time_are_not_discarded():
    rows = [{"t": 0, "c": "100", "v": "1"}, {"t": 60_000, "c": "101", "v": "1"}]
    assert _closes(rows) == [100.0, 101.0]


def test_all_candles_in_progress_yields_empty_not_a_crash():
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    rows = [{"t": now_ms, "T": now_ms + 59_999, "c": "100", "v": "1"}]
    assert _closes(rows) == []


def test_volumes_stay_aligned_with_closes():
    rows = _candles([100.0, 101.0, 102.0], last_in_progress=True)
    closes, volumes = asyncio.run(
        crypto15m._fetch_closes("BTC", _FakeClient(rows), 10))
    assert len(closes) == len(volumes) == 2
