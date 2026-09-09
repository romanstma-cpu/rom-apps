from __future__ import annotations

import pytest

import clob_ws
import db


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    dbfile = tmp_path / "rom-test.db"
    monkeypatch.setattr(db, "db_path", lambda: dbfile)
    db.init_db()
    return dbfile


_TRADE_MSG = {
    "market": "0xad7e09575fadd3690db355cae99e8afcb06c2bdcdae614f0b8f5906cc2d986bc",
    "asset_id": "8667464274195964807900973680021329856225115137139120716846084",
    "price": "0.24", "size": "6.208332", "fee_rate_bps": "0", "side": "BUY",
    "timestamp": "1784202740329", "event_type": "last_trade_price",
    "transaction_hash": "0x10cf6ecd8291993ff66a4582cc30591bb198",
}


def test_parse_last_trade_live_shape():
    row = clob_ws.parse_last_trade(_TRADE_MSG)
    assert row is not None
    assert row["price"] == pytest.approx(0.24)
    assert row["size"] == pytest.approx(6.208332)
    assert row["side"] == "BUY"
    assert row["source_ts_ms"] == 1784202740329
    assert row["ingest_ts"] > 0


def test_parse_last_trade_rejects_garbage():
    assert clob_ws.parse_last_trade({}) is None
    assert clob_ws.parse_last_trade({"asset_id": "x", "price": "abc"}) is None
    assert clob_ws.parse_last_trade({"asset_id": "x", "price": "1.5"}) is None
    row = clob_ws.parse_last_trade({"asset_id": "x", "price": "0.5"})
    assert row is not None and row["size"] is None and row["side"] is None


def test_dispatch_buffers_and_drain_clears():
    feed = clob_ws.ClobMarketFeed()
    feed._dispatch(dict(_TRADE_MSG))
    feed._dispatch({"event_type": "new_market", "market": "0xabc", "slug": "s"})
    feed._dispatch({"event_type": "market_resolved", "market": "0xabc"})
    assert len(feed._trades) == 1
    assert feed.drain_trades()[0]["side"] == "BUY"
    assert feed.drain_trades() == []
    assert len(feed.drain_new_markets()) == 1
    assert len(feed.drain_resolutions()) == 1


def test_trade_buffer_is_bounded():
    feed = clob_ws.ClobMarketFeed()
    for i in range(feed._TRADES_MAX + 50):
        feed._dispatch({**_TRADE_MSG, "timestamp": str(i)})
    assert len(feed._trades) == feed._TRADES_MAX
    assert feed._trades[-1]["source_ts_ms"] == feed._TRADES_MAX + 49


def test_best_bid_ask_updates_quote_cache():
    feed = clob_ws.ClobMarketFeed()
    feed._dispatch({"event_type": "best_bid_ask", "asset_id": "tok1",
                    "best_bid": "0.23", "best_ask": "0.24",
                    "timestamp": "1784202740154"})
    q = feed.get_quote_cents("tok1")
    assert q == {"bid_cents": 23, "ask_cents": 24}


def test_clob_trades_db_roundtrip(fresh_db):
    rows = [clob_ws.parse_last_trade(_TRADE_MSG),
            clob_ws.parse_last_trade({"asset_id": "y", "price": "0.61"})]
    with db.get_db() as conn:
        n = db.insert_clob_trades(conn, rows, network="mainnet")
    assert n == 2
    with db.get_db() as conn:
        got = conn.execute(
            "SELECT asset_id, price, side, source_ts_ms, network "
            "FROM clob_trades ORDER BY id").fetchall()
    assert len(got) == 2
    assert got[0]["price"] == pytest.approx(0.24)
    assert got[0]["side"] == "BUY"
    assert got[0]["network"] == "mainnet"
    assert got[1]["source_ts_ms"] is None


def test_insert_clob_trades_skips_invalid(fresh_db):
    with db.get_db() as conn:
        db.insert_clob_trades(conn, [{"asset_id": None, "price": 0.5},
                                     {"asset_id": "ok", "price": 0.5}])
    with db.get_db() as conn:
        n = conn.execute("SELECT COUNT(*) c FROM clob_trades").fetchone()["c"]
    assert n == 1
