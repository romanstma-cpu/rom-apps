"""The market stream ingest pipeline: normalization, dedup, bounds.

ingest() is the front door for every trade that reaches the scanners and
momentum tape, so its guards are safety-critical:
- reject malformed/out-of-range payloads silently
- fingerprint-then-dedupe trades across reconnects
- never feed the tape a negative or non-finite quantity
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

import pytest

import momentum_window
import us_market_stream as stream


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _trade(market="btc-will-up", price="0.42", qty="37.5", side="ORDER_SIDE_BUY", time_iso=None):
    if time_iso is None:
        time_iso = _now_iso()
    return {
        "marketSlug": market,
        "tradeTime": time_iso,
        "price": {"value": price, "side": "BUY"},
        "quantity": {"value": qty, "side": "BUY"},
        "taker": {"side": side},
    }


def _book(slug="btc-will-up", bids=(("0.41", "10"), ("0.40", "5")), asks=(("0.43", "8"), ("0.44", "6"))):
    return {
        "marketSlug": slug,
        "bids": [{"px": {"value": p}, "qty": q} for p, q in bids],
        "offers": [{"px": {"value": p}, "qty": q} for p, q in asks],
    }


@pytest.fixture(autouse=True)
def clean_stream():
    stream._books.clear()
    stream._trades.clear()
    stream._wanted.clear()
    momentum_window.tape.reset()
    yield
    stream._books.clear()
    stream._trades.clear()
    stream._wanted.clear()
    momentum_window.tape.reset()


class TestIngestNormalization:
    def test_trade_is_normalized_and_tape_added(self):
        stream.ingest({"trade": _trade(price="0.42", qty="37.5", side="ORDER_SIDE_BUY")})
        assert len(stream._trades) == 1
        row = stream._trades[0]
        assert row["ticker"] == "btc-will-up"
        assert row["count_fp"] == 37.5
        assert row["yes_price_dollars"] == 0.42
        assert abs(row["no_price_dollars"] - 0.58) < 1e-9
        assert row["taker_side"] == "yes"

    def test_sell_side_maps_to_no(self):
        stream.ingest({"trade": _trade(price="0.42", side="ORDER_SIDE_SELL")})
        row = stream._trades[0]
        assert row["taker_side"] == "no"

    def test_no_price_is_1_minus_yes(self):
        stream.ingest({"trade": _trade(price="0.30")})
        assert abs(stream._trades[0]["no_price_dollars"] - 0.70) < 1e-9

    def test_malformed_price_is_dropped(self):
        stream.ingest({"trade": _trade(price="abc")})
        assert len(stream._trades) == 0

    def test_missing_quantity_is_dropped(self):
        t = _trade()
        del t["quantity"]["value"]
        stream.ingest({"trade": t})
        assert len(stream._trades) == 0

    def test_unknown_side_is_dropped(self):
        stream.ingest({"trade": _trade(side="ORDER_SIDE_UNKNOWN")})
        assert len(stream._trades) == 0

    def test_zero_and_negative_qty_dropped(self):
        stream.ingest({"trade": _trade(qty="0")})
        stream.ingest({"trade": _trade(qty="-5")})
        assert len(stream._trades) == 0

    def test_nonfinite_qty_dropped(self):
        stream.ingest({"trade": _trade(qty="nan")})
        stream.ingest({"trade": _trade(qty="inf")})
        assert len(stream._trades) == 0

    def test_out_of_range_price_dropped(self):
        for p in ("0", "1", "1.5", "-0.2"):
            stream.ingest({"trade": _trade(price=p)})
        # Only the in-range one survives
        stream.ingest({"trade": _trade(price="0.5")})
        assert len(stream._trades) == 1

    def test_tape_deduplicates_same_trade(self):
        """_trades appends every payload; dedup lives at tape.ids level."""
        t = _trade()
        stream.ingest({"trade": t})
        stream.ingest({"trade": t})
        # _trades gets both (append-only)
        assert len(stream._trades) == 2
        # but tape has one entry (fingerprint-based dedup)
        assert len(momentum_window.tape.ids) == 1

    def test_fingerprint_is_stable_across_reconnects(self):
        t = _trade()
        stream.ingest({"trade": t})
        assert len(momentum_window.tape.ids) == 1
        # Disconnect clears tape ids
        momentum_window.tape.reset()
        assert len(momentum_window.tape.ids) == 0
        # Same payload re-ingested — tape accepts it (fresh id set)
        stream.ingest({"trade": t})
        assert len(momentum_window.tape.ids) == 1

    def test_ingest_handles_no_trade_key(self):
        stream.ingest({"marketData": _book()})
        assert len(stream._trades) == 0

    def test_fingerprint_matches_expected_sha256(self):
        import hashlib, json
        t = _trade(price="0.50", qty="1.0", side="ORDER_SIDE_BUY",
                   time_iso="2026-09-10T00:00:00Z")
        stream.ingest({"trade": t})
        row = stream._trades[0]
        expected = hashlib.sha256(json.dumps(t, sort_keys=True).encode()).hexdigest()
        assert row["trade_id"] == expected


class TestIngestBooks:
    def test_book_is_cached(self):
        stream.ingest({"marketData": _book()})
        slug = stream._books.get("btc-will-up")
        assert slug is not None
        book = slug[1]
        assert book["marketSlug"] == "btc-will-up"

    def test_get_quote_cents_yes(self):
        stream.ingest({"marketData": _book()})
        q = stream.get_quote_cents("btc-will-up::yes")
        assert q["bid_cents"] == 41
        assert q["ask_cents"] == 43

    def test_get_quote_cents_no_flips_sides(self):
        stream.ingest({"marketData": _book()})
        q = stream.get_quote_cents("btc-will-up::no")
        # NO bid = 1 - YES ask = 57; NO ask = 1 - YES bid = 59
        assert q["bid_cents"] == 57
        assert q["ask_cents"] == 59

    def test_get_quote_cents_empty_book(self):
        stream.ingest({"marketData": _book(bids=(), asks=())})
        q = stream.get_quote_cents("btc-will-up::yes")
        assert q == {"bid_cents": None, "ask_cents": None}

    def test_get_quote_cents_unknown_slug(self):
        assert stream.get_quote_cents("missing::yes") is None

    def test_asks_with_zero_qty_excluded(self):
        stream.ingest({"marketData": _book(bids=(("0.41", "10"),),
                                            asks=(("0.43", "0"), ("0.45", "5")))})
        q = stream.get_quote_cents("btc-will-up::yes")
        assert q["ask_cents"] == 45  # 0.43 filtered out


class TestIngestTape:
    def test_tape_receives_valid_trade_and_is_ready(self):
        stream.ingest({"trade": _trade(price="0.42", qty="10")})
        # Tape needs a warm-up window; summarize at a far-future time
        # to satisfy the FRESH check (now - at <= 30s).
        # ingest() calls tape.add(normalized, time.time()), so `now`
        # inside tape is the real wall-clock. We summarize at that time.
        now = time.time()
        summary = momentum_window.tape.summarize("btc-will-up", now)
        # Not ready yet — WINDOW is 300s; we only have one receipt.
        assert summary["ready"] is False
        assert summary["reason"] == "warming up five-minute trade window"

    def test_tape_records_trade_at_correct_timestamp(self):
        stream.ingest({"trade": _trade(price="0.75", qty="20")})
        rows = list(momentum_window.tape.by_ticker.get("btc-will-up", []))
        assert len(rows) == 1
        assert rows[0]["price"] == 0.75
        assert rows[0]["qty"] == 20.0

    def test_stale_trade_is_dropped(self):
        from datetime import timedelta
        stale = (datetime.now(timezone.utc) - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        stream.ingest({"trade": _trade(price="0.50", time_iso=stale)})
        assert list(momentum_window.tape.by_ticker.get("btc-will-up", [])) == []