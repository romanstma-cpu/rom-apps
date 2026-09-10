from __future__ import annotations

import clob_ws


# --- parse_book: empty / missing levels ---------------------------------

def test_parse_book_empty_levels():
    msg = {"asset_id": "T", "bids": [], "asks": []}
    assert clob_ws.parse_book(msg) == ("T", None, None)


def test_parse_book_missing_bids_side():
    msg = {"asset_id": "T", "asks": [{"price": "0.60", "size": "10"}]}
    assert clob_ws.parse_book(msg) == ("T", None, 0.60)


def test_parse_book_missing_asks_side():
    msg = {"asset_id": "T", "bids": [{"price": "0.40", "size": "10"}]}
    assert clob_ws.parse_book(msg) == ("T", 0.40, None)


def test_parse_book_missing_both_level_keys():
    msg = {"asset_id": "T"}
    assert clob_ws.parse_book(msg) == ("T", None, None)


def test_parse_book_key_present_but_none_value():
    msg = {"asset_id": "T", "bids": None, "asks": None}
    assert clob_ws.parse_book(msg) == ("T", None, None)


# --- parse_book: levels out of price range ------------------------------

def test_parse_book_ignores_price_ge_1():
    # 1.5 is not a valid Polymarket probability: find the best level within
    # (0, 1) instead of returning the out-of-range level.
    msg = {
        "asset_id": "T",
        "bids": [{"price": "1.5", "size": "100"}, {"price": "0.55", "size": "1"}],
        "asks": [{"price": "0.60", "size": "1"}],
    }
    assert clob_ws.parse_book(msg) == ("T", 0.55, 0.60)


def test_parse_book_ignores_price_le_0():
    msg = {
        "asset_id": "T",
        "bids": [{"price": "0.40", "size": "1"}],
        "asks": [{"price": "0.0", "size": "100"}, {"price": "-1.0", "size": "100"},
                 {"price": "0.62", "size": "1"}],
    }
    assert clob_ws.parse_book(msg) == ("T", 0.40, 0.62)


def test_parse_book_all_levels_out_of_range():
    msg = {
        "asset_id": "T",
        "bids": [{"price": "1.5", "size": "1"}, {"price": "2.0", "size": "1"}],
        "asks": [{"price": "0.0", "size": "1"}, {"price": "-1.0", "size": "1"}],
    }
    assert clob_ws.parse_book(msg) == ("T", None, None)


# --- parse_price_changes: malformed entries -----------------------------

def test_parse_price_changes_skips_non_dict_entries():
    # None / non-dict members of price_changes must be skipped, not crash.
    msg = {"price_changes": [None, "junk", 42,
                             {"asset_id": "YES", "best_bid": "0.55",
                              "best_ask": "0.56"}]}
    assert clob_ws.parse_price_changes(msg) == [("YES", 0.55, 0.56)]


def test_parse_price_changes_skips_entry_without_asset_id():
    msg = {"price_changes": [
        {"best_bid": "0.55", "best_ask": "0.56"},
        {"asset_id": "YES", "best_bid": "0.55", "best_ask": "0.56"},
    ]}
    assert clob_ws.parse_price_changes(msg) == [("YES", 0.55, 0.56)]


def test_parse_price_changes_nonnumeric_side_is_none():
    msg = {"price_changes": [
        {"asset_id": "YES", "best_bid": "0.55", "best_ask": "garbage"},
        {"asset_id": "NO", "best_bid": "junk", "best_ask": "0.45"},
    ]}
    assert clob_ws.parse_price_changes(msg) == [("YES", 0.55, None),
                                                ("NO", None, 0.45)]


def test_parse_price_changes_empty_string_side_is_none():
    msg = {"price_changes": [{"asset_id": "YES", "best_bid": "", "best_ask": "0.56"}]}
    assert clob_ws.parse_price_changes(msg) == [("YES", None, 0.56)]


def test_parse_price_changes_out_of_range_values_passed_through():
    # The parser is a pass-through for numeric values; range enforcement
    # happens in the feed. Document the contract explicitly.
    msg = {"price_changes": [
        {"asset_id": "YES", "best_bid": "1.5", "best_ask": "-0.1"}]}
    assert clob_ws.parse_price_changes(msg) == [("YES", 1.5, -0.1)]


def test_parse_price_changes_missing_list_is_empty():
    assert clob_ws.parse_price_changes({"event_type": "price_change"}) == []
    assert clob_ws.parse_price_changes({"price_changes": []}) == []


# --- parse_last_trade ---------------------------------------------------

def test_parse_last_trade_happy_path():
    row = clob_ws.parse_last_trade({
        "asset_id": "TOK", "price": "0.55", "size": "12",
        "side": "BUY", "timestamp": "1234", "market": "m", "transaction_hash": "0x1",
    })
    assert row is not None
    assert row["asset_id"] == "TOK"
    assert row["price"] == 0.55
    assert row["size"] == 12.0
    assert row["side"] == "BUY"
    assert row["source_ts_ms"] == 1234
    assert row["market"] == "m"
    assert row["tx"] == "0x1"


def test_parse_last_trade_missing_price_is_none():
    assert clob_ws.parse_last_trade({"asset_id": "TOK", "size": "12"}) is None


def test_parse_last_trade_missing_asset_id_is_none():
    row = clob_ws.parse_last_trade({"price": "0.55", "size": "12"})
    assert row is None


def test_parse_last_trade_missing_size_timestamp_side_are_none():
    row = clob_ws.parse_last_trade({"asset_id": "TOK", "price": "0.55"})
    assert row is not None
    assert row["size"] is None
    assert row["source_ts_ms"] is None
    assert row["side"] is None
    assert row["market"] is None
    assert row["tx"] is None


def test_parse_last_trade_price_out_of_range_is_none():
    assert clob_ws.parse_last_trade({"asset_id": "TOK", "price": "1.5"}) is None
    assert clob_ws.parse_last_trade({"asset_id": "TOK", "price": "0.0"}) is None
    assert clob_ws.parse_last_trade({"asset_id": "TOK", "price": "-0.2"}) is None


def test_parse_last_trade_nonnumeric_size_and_timestamp_become_none():
    row = clob_ws.parse_last_trade({
        "asset_id": "TOK", "price": "0.55", "size": "abc", "timestamp": "later",
    })
    assert row is not None
    assert row["size"] is None
    assert row["source_ts_ms"] is None


def test_parse_last_trade_empty_string_fields():
    row = clob_ws.parse_last_trade({
        "asset_id": "TOK", "price": "0.55", "size": "", "timestamp": "",
        "side": "",
    })
    assert row is not None
    assert row["size"] is None
    assert row["source_ts_ms"] is None
    assert row["side"] is None


def test_parse_last_trade_numeric_price_slot_accepted():
    assert clob_ws.parse_last_trade({"asset_id": "TOK", "price": 0.55}) is not None


# --- _iter_messages -----------------------------------------------------

def test_iter_messages_empty_string():
    assert clob_ws._iter_messages("") == []


def test_iter_messages_whitespace_only():
    assert clob_ws._iter_messages("   ") == []


def test_iter_messages_whitespace_wrapped_object():
    assert clob_ws._iter_messages(' {"a":1} \n') == [{"a": 1}]


def test_iter_messages_partial_json_single_quote():
    assert clob_ws._iter_messages('{"a":1') == []


def test_iter_messages_partial_json_truncated_array():
    assert clob_ws._iter_messages('[{"a":1},{"b":2}') == []


def test_iter_messages_empty_array():
    assert clob_ws._iter_messages("[]") == []




def test_iter_messages_list_mixed_types_keeps_dicts_only():
    assert clob_ws._iter_messages('[{"a":1},"x",5,{"b":2}]') == [{"a": 1}, {"b": 2}]


def test_iter_messages_primitive_root_ignored():
    assert clob_ws._iter_messages("42") == []
    assert clob_ws._iter_messages('"str"') == []
    assert clob_ws._iter_messages("true") == []


def test_iter_messages_non_string_input_is_empty():
    assert clob_ws._iter_messages(None) == []
    assert clob_ws._iter_messages(b"{\"a\":1}") == [{"a": 1}]


def test_iter_messages_bytes_input_decoded():
    assert clob_ws._iter_messages(b'{"a": 1}') == [{"a": 1}]


# --- feed dispatch for out-of-range book data ---------------------------

def test_dispatch_book_out_of_range_prices_dropped():
    f = clob_ws.ClobMarketFeed()
    f._dispatch({"event_type": "book", "asset_id": "T",
                 "bids": [{"price": "1.5", "size": "100"},
                          {"price": "0.40", "size": "1"}],
                 "asks": [{"price": "0.60", "size": "1"}]})
    assert f.get_quote_cents("T") == {"bid_cents": 40, "ask_cents": 60}