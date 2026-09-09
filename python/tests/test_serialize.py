from __future__ import annotations

import service


def test_naive_sqlite_string_gets_t_and_z():
    assert service._iso_utc("2024-01-02 03:04:05") == "2024-01-02T03:04:05Z"


def test_already_zulu_is_left_alone():
    assert service._iso_utc("2024-01-02T03:04:05Z") == "2024-01-02T03:04:05Z"


def test_offset_timestamp_is_not_double_tagged():
    s = "2024-01-02T03:04:05+00:00"
    assert service._iso_utc(s) == s


def test_empty_and_none_pass_through():
    assert service._iso_utc("") == ""
    assert service._iso_utc(None) is None


def test_live_pnl_open_position_gains():
    r = {"resolved": 0, "filled_contracts": 10, "cost_usd": 6.0,
         "mark_price_cents": 80.0}
    assert service._live_pnl_usd(r) == 2.0


def test_live_pnl_open_position_loss():
    r = {"resolved": 0, "filled_contracts": 10, "cost_usd": 6.0,
         "mark_price_cents": 30.0}
    assert service._live_pnl_usd(r) == -3.0


def test_live_pnl_none_when_resolved():
    r = {"resolved": 1, "filled_contracts": 10, "cost_usd": 6.0,
         "mark_price_cents": 80.0}
    assert service._live_pnl_usd(r) is None


def test_live_pnl_none_without_mark_or_fill():
    assert service._live_pnl_usd(
        {"resolved": 0, "filled_contracts": 10, "cost_usd": 6.0,
         "mark_price_cents": None}) is None
    assert service._live_pnl_usd(
        {"resolved": 0, "filled_contracts": 0, "cost_usd": 0.0,
         "mark_price_cents": 80.0}) is None


def test_position_serializer_exposes_live_pnl_fields():
    r = {
        "id": 1, "signal_source": "external", "signal_id": 1, "ticker": "T",
        "direction": "yes", "target_contracts": 10, "limit_price_cents": 60,
        "filled_contracts": 10, "cost_usd": 6.0, "status": "filled",
        "resolved": 0, "mark_price_cents": 75.0, "network": "mainnet",
    }
    js = service._position_row_to_js(r)
    assert js["markPriceCents"] == 75.0
    assert js["livePnlUsd"] == 1.5
