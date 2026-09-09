from __future__ import annotations

import asyncio

import pytest

import trader
from config import merge_with_defaults


@pytest.fixture
def cfg() -> dict:
    return merge_with_defaults({})


def test_size_below_base_edge_uses_min_fraction(cfg):
    assert trader._compute_position_usd(1000.0, 3.0, cfg) == 20.0


def test_size_above_max_edge_capped_by_hard_max(cfg):
    assert trader._compute_position_usd(1000.0, 25.0, cfg) == 50.0


def test_size_interpolates_between_edges(cfg):
    assert trader._compute_position_usd(1000.0, 12.5, cfg) == pytest.approx(40.0)


def test_signal_cost_whale_uses_taker_side_price():
    direction, cents = trader._signal_cost_cents(
        {"taker_side": "no", "price": 0.62}, "whale"
    )
    assert (direction, cents) == ("no", 62)


def test_signal_cost_momentum_no_side_inverts_price():
    direction, cents = trader._signal_cost_cents(
        {"direction": "no", "price": 0.30}, "momentum"
    )
    assert (direction, cents) == ("no", 70)


def test_compute_edge_momentum_no_side():
    edge = trader._compute_edge(
        {"direction": "no", "price": 0.30, "confidence": 80.0}, "momentum"
    )
    assert edge == pytest.approx(10.0)


def test_should_trade_passes_clean_whale(cfg):
    sig = {"ticker": "X", "price": 0.60, "confidence": 70.0,
           "taker_side": "yes", "category": "sports"}
    ok, reason = trader.should_trade(sig, "whale", cfg)
    assert ok is True and reason == "ok"


def test_should_trade_blocks_when_source_disabled(cfg):
    cfg["trade_whales"] = False
    ok, reason = trader.should_trade({"price": 0.6, "confidence": 70.0,
                                      "taker_side": "yes"}, "whale", cfg)
    assert ok is False and reason == "whales disabled"


def test_should_trade_blocks_low_confidence(cfg):
    ok, reason = trader.should_trade(
        {"ticker": "X", "price": 0.60, "confidence": 50.0,
         "taker_side": "yes"}, "whale", cfg)
    assert ok is False and reason.startswith("conf ")


def test_should_trade_blocks_entry_above_max(cfg):
    ok, reason = trader.should_trade(
        {"ticker": "X", "price": 0.90, "confidence": 99.0,
         "taker_side": "yes"}, "whale", cfg)
    assert ok is False and reason == "entry 90c > 85c"


def _iso_in_days(days: float) -> str:
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_should_trade_resolution_days_gate(cfg):
    base = {"ticker": "X", "price": 0.60, "confidence": 70.0,
            "taker_side": "yes", "category": "sports"}

    assert trader.should_trade({**base, "close_time": _iso_in_days(120)}, "whale", cfg)[0] is True

    cfg["max_resolution_days"] = 30
    ok, reason = trader.should_trade({**base, "close_time": _iso_in_days(120)}, "whale", cfg)
    assert ok is False and "resolves" in reason
    assert trader.should_trade({**base, "close_time": _iso_in_days(10)}, "whale", cfg)[0] is True
    assert trader.should_trade({**base, "close_time": ""}, "whale", cfg)[0] is True
    assert trader.should_trade({**base, "close_time": "garbage"}, "whale", cfg)[0] is True
    assert trader.should_trade(base, "whale", cfg)[0] is True


def test_resolution_gate_applies_in_rules_mode(cfg):
    cfg["use_rules"] = True
    cfg["rules"] = []
    cfg["max_resolution_days"] = 30
    base = {"ticker": "X", "price": 0.60, "confidence": 70.0,
            "taker_side": "yes", "category": "sports"}
    ok, reason = trader.should_trade({**base, "close_time": _iso_in_days(120)}, "whale", cfg)
    assert ok is False and "resolves" in reason


def test_can_open_new_entries_gates_on_wallet_lock(monkeypatch):
    import instance_lock
    monkeypatch.setattr(trader, "trading_address", lambda env=None: "")
    assert trader.can_open_new_entries("mainnet")[0] is True

    monkeypatch.setattr(trader, "trading_address", lambda env=None: "0xWALLET")
    monkeypatch.setattr(instance_lock, "claim", lambda addr, **k: True)
    assert trader.can_open_new_entries("mainnet")[0] is True

    monkeypatch.setattr(instance_lock, "claim", lambda addr, **k: False)
    monkeypatch.setattr(instance_lock, "foreign_holder", lambda addr, **k: "9999")
    ok, reason = trader.can_open_new_entries("mainnet")
    assert ok is False and "already being traded" in reason


def test_days_until_close_parses_and_fails_soft():
    assert trader._days_until_close("") is None
    assert trader._days_until_close("nonsense") is None
    d = trader._days_until_close(_iso_in_days(10))
    assert d is not None and 9.8 < d < 10.1


def test_should_trade_category_filter_excludes(cfg):
    cfg["allowed_categories"] = ["politics"]
    ok, reason = trader.should_trade(
        {"ticker": "X", "price": 0.60, "confidence": 70.0,
         "taker_side": "yes", "category": "sports"}, "whale", cfg)
    assert ok is False and "not in allowed set" in reason


def test_should_trade_empty_category_list_blocks_everything(cfg):
    cfg["allowed_categories"] = []
    ok, reason = trader.should_trade(
        {"ticker": "X", "price": 0.60, "confidence": 70.0,
         "taker_side": "yes", "category": "sports"}, "whale", cfg)
    assert ok is False and reason == "no categories enabled"


def test_should_trade_per_source_whale_category_blocks(cfg):
    cfg["allowed_whale_categories"] = ["crypto"]
    ok, reason = trader.should_trade(
        {"ticker": "X", "price": 0.60, "confidence": 70.0,
         "taker_side": "yes", "category": "sports"}, "whale", cfg)
    assert ok is False and "whale set" in reason


def test_should_trade_per_source_lets_each_source_keep_its_categories(cfg):
    cfg["allowed_whale_categories"] = ["crypto"]
    cfg["allowed_momentum_categories"] = ["sports"]
    ok, _ = trader.should_trade(
        {"ticker": "X", "price": 0.60, "confidence": 70.0,
         "taker_side": "yes", "category": "crypto"}, "whale", cfg)
    assert ok is True
    ok2, reason2 = trader.should_trade(
        {"ticker": "X", "price": 0.30, "confidence": 80.0, "direction": "no",
         "signal_type": "trade_cluster", "category": "crypto"}, "momentum", cfg)
    assert ok2 is False and "momentum set" in reason2


def test_should_trade_momentum_signal_type_not_allowed(cfg):
    sig = {"ticker": "X", "price": 0.30, "confidence": 80.0,
           "direction": "no", "signal_type": "price_move"}
    ok, reason = trader.should_trade(sig, "momentum", cfg)
    assert ok is False and "not allowed" in reason


def test_signal_rule_values_are_direction_adjusted():
    sig = {"price": 0.30, "confidence": 80.0, "direction": "no"}
    v = trader._signal_rule_values(sig, "momentum")
    assert v["confidence"] == 80.0
    assert v["costCents"] == 70
    assert v["edge"] == pytest.approx(10.0)


def test_use_rules_replaces_builtin_thresholds(cfg):
    cfg["use_rules"] = True
    cfg["rules"] = [{"field": "confidence", "op": ">=", "value": 60}]
    sig = {"ticker": "X", "price": 0.90, "confidence": 70.0,
           "taker_side": "yes", "category": "sports"}
    ok, reason = trader.should_trade(sig, "whale", cfg)
    assert ok is True and reason == "rules pass"


def test_use_rules_failing_condition_blocks(cfg):
    cfg["use_rules"] = True
    cfg["rules"] = [{"field": "edge", "op": ">=", "value": 30}]
    sig = {"ticker": "X", "price": 0.60, "confidence": 70.0, "taker_side": "yes"}
    ok, reason = trader.should_trade(sig, "whale", cfg)
    assert ok is False and reason.startswith("edge ")


def test_use_rules_empty_set_never_trades(cfg):
    cfg["use_rules"] = True
    cfg["rules"] = []
    sig = {"ticker": "X", "price": 0.60, "confidence": 99.0, "taker_side": "yes"}
    ok, reason = trader.should_trade(sig, "whale", cfg)
    assert ok is False and reason == "no entry rules set"


def test_use_rules_still_honors_structural_gates(cfg):
    cfg["use_rules"] = True
    cfg["rules"] = [{"field": "confidence", "op": ">=", "value": 1}]
    cfg["trade_whales"] = False
    sig = {"ticker": "X", "price": 0.60, "confidence": 70.0, "taker_side": "yes"}
    assert trader.should_trade(sig, "whale", cfg) == (False, "whales disabled")
    msig = {"ticker": "X", "price": 0.30, "confidence": 80.0,
            "direction": "no", "signal_type": "price_move"}
    ok, reason = trader.should_trade(msig, "momentum", cfg)
    assert ok is False and "not allowed" in reason


def test_limit_cross_does_not_pay_above_current_ask(cfg, monkeypatch):
    async def _q(_t, _side):
        return {"bid_cents": 59, "ask_cents": 62}
    monkeypatch.setattr(trader, "get_quote", _q)
    px = asyncio.run(trader._compute_limit_price_cents("X", "yes", 60, cfg))
    assert px == 62


def test_limit_cross_caps_at_max_entry(cfg, monkeypatch):
    cfg["max_entry_price_cents"] = 65
    async def _q(_t, _side):
        return {"bid_cents": 61, "ask_cents": 64}
    monkeypatch.setattr(trader, "get_quote", _q)
    px = asyncio.run(trader._compute_limit_price_cents("X", "yes", 62, cfg))
    assert px == 64


def test_limit_cross_returns_ask_above_cap_so_caller_skips(cfg, monkeypatch):
    cfg["max_entry_price_cents"] = 60
    async def _q(_t, _side):
        return {"bid_cents": 70, "ask_cents": 72}
    monkeypatch.setattr(trader, "get_quote", _q)
    px = asyncio.run(trader._compute_limit_price_cents("X", "yes", 71, cfg))
    assert px == 72


def test_limit_mid_uses_midpoint(cfg, monkeypatch):
    cfg["order_style"] = "limit_mid"
    async def _q(_t, _side):
        return {"bid_cents": 59, "ask_cents": 62}
    monkeypatch.setattr(trader, "get_quote", _q)
    px = asyncio.run(trader._compute_limit_price_cents("X", "yes", 60, cfg))
    assert px == 60


def test_pricing_refuses_missing_quote(cfg, monkeypatch):
    async def _q(_t, _side):
        return {"bid_cents": None, "ask_cents": None}
    monkeypatch.setattr(trader, "get_quote", _q)
    with pytest.raises(ValueError, match="two-sided"):
        asyncio.run(trader._compute_limit_price_cents("X", "yes", 60, cfg))


def test_market_style_is_bounded_at_current_ask(cfg, monkeypatch):
    async def _q(_t, _side):
        return {"bid_cents": 59, "ask_cents": 61}
    monkeypatch.setattr(trader, "get_quote", _q)
    cfg["order_style"] = "market"
    cfg["max_entry_price_cents"] = 85
    px = asyncio.run(trader._compute_limit_price_cents("X", "yes", 60, cfg))
    assert px == 61
    cfg["max_entry_price_cents"] = 99
    px = asyncio.run(trader._compute_limit_price_cents("X", "yes", 60, cfg))
    assert px == 61


def test_parse_polymarket_order_matched():
    parsed = trader._parse_polymarket_order({
        "status": "MATCHED", "size_matched": "5", "original_size": "5",
        "price": "0.60",
    })
    assert parsed["filled"] == 5
    assert parsed["cost_cents"] == 300
    assert parsed["avg_cents"] == 60.0
    assert parsed["status"] == "executed"
    assert parsed["remaining"] == 0
    assert parsed["place_count"] == 5


def test_parse_polymarket_order_resting_reports_remaining():
    parsed = trader._parse_polymarket_order({
        "status": "ORDER_STATUS_LIVE", "size_matched": "0",
        "original_size": "1", "price": "0.45",
    })
    assert parsed["filled"] == 0
    assert parsed["remaining"] == 1
    assert parsed["place_count"] == 1
    assert parsed["status"] == "resting"


def test_parse_polymarket_order_canceled():
    parsed = trader._parse_polymarket_order({
        "status": "CANCELED", "size_matched": "0", "original_size": "3",
        "price": "0.50",
    })
    assert parsed["status"] == "canceled"
    assert parsed["filled"] == 0


def test_parse_polymarket_fill_live_fp_dollars_shape():
    fill = {
        "count_fp": "1.00", "count": None,
        "side": "no", "action": "buy",
        "yes_price_dollars": "0.0100", "no_price_dollars": "0.9900",
        "order_id": "abc",
    }
    parsed = trader._parse_polymarket_fill(fill, default_side="no")
    assert parsed["count"] == 1
    assert parsed["side"] == "no"
    assert parsed["price_cents"] == 99


def test_parse_polymarket_fill_uses_price_cents():
    fill = {"count_fp": "3", "price_cents": 60, "side": "", "action": "buy"}
    parsed = trader._parse_polymarket_fill(fill, default_side="yes")
    assert parsed["count"] == 3
    assert parsed["side"] == "yes"
    assert parsed["price_cents"] == 60


def test_parse_polymarket_fill_out_of_range_price_is_none():
    fill = {"count_fp": "1.00", "side": "yes", "yes_price_dollars": "1.0000"}
    assert trader._parse_polymarket_fill(fill, "yes")["price_cents"] is None


def test_parse_polymarket_position_negative_qty_is_no_side():
    parsed = trader._parse_polymarket_position({
        "position_fp": -4, "market_exposure_dollars": 2.0,
    })
    assert parsed["filled"] == 4
    assert parsed["side"] == "no"
    assert parsed["cost_cents"] == 200


def test_db_status_executed_is_filled():
    parsed = {"status": "executed", "filled": 5}
    assert trader._db_status_from_order(parsed, target=5) == "filled"


def test_db_status_canceled_with_partial_fill():
    parsed = {"status": "canceled", "filled": 2}
    assert trader._db_status_from_order(parsed, target=5) == "partial"


def test_db_status_resting_unfilled_is_submitted():
    parsed = {"status": "resting", "filled": 0}
    assert trader._db_status_from_order(parsed, target=5) == "submitted"


def test_yes_payout_result_yes_is_one():
    assert trader._market_yes_payout({"result": "yes"}) == 1.0


def test_yes_payout_result_no_is_zero():
    assert trader._market_yes_payout({"result": "no"}) == 0.0


def test_yes_payout_unsettled_market_is_none():
    assert trader._market_yes_payout({"status": "open", "result": ""}) is None


def test_yes_payout_uses_settlement_value_dollars():
    m = {"status": "settled", "result": "", "settlement_value_dollars": 0.5}
    assert trader._market_yes_payout(m) == 0.5


def test_yes_payout_settlement_value_is_dollars():
    m = {"status": "finalized", "result": "", "settlement_value": 0.75}
    assert trader._market_yes_payout(m) == 0.75


def test_yes_payout_out_of_range_settlement_is_rejected():
    m = {"status": "finalized", "result": "", "settlement_value": 75}
    assert trader._market_yes_payout(m) is None


def test_yes_payout_none_market_is_none():
    assert trader._market_yes_payout(None) is None


# --- Kelly sizing mode -------------------------------------------------


@pytest.fixture
def kelly_cfg() -> dict:
    return merge_with_defaults({
        "sizing_mode": "kelly",
        "kelly_fraction": 1.0,
        "min_size_fraction": 0.0,
        "max_size_fraction": 1.0,
        "hard_max_position_usd": 1e9,
    })


def test_kelly_matches_closed_form(kelly_cfg):
    # f* = (p - c) / (1 - c); 5pts of edge at 90c risks 10c to win 90c.
    assert trader._compute_target_usd(1000.0, 5.0, 90, kelly_cfg) == pytest.approx(500.0)
    assert trader._compute_target_usd(1000.0, 5.0, 50, kelly_cfg) == pytest.approx(100.0)
    assert trader._compute_target_usd(1000.0, 5.0, 20, kelly_cfg) == pytest.approx(62.5)


def test_kelly_is_price_sensitive_where_percent_is_not(cfg, kelly_cfg):
    # The percent ramp returns the same dollars regardless of entry price.
    assert (trader._compute_target_usd(1000.0, 5.0, 90, cfg)
            == trader._compute_target_usd(1000.0, 5.0, 20, cfg))
    # Kelly does not.
    assert (trader._compute_target_usd(1000.0, 5.0, 90, kelly_cfg)
            > trader._compute_target_usd(1000.0, 5.0, 20, kelly_cfg))


def test_kelly_multiplier_scales_linearly(kelly_cfg):
    full = trader._compute_target_usd(1000.0, 5.0, 50, kelly_cfg)
    kelly_cfg["kelly_fraction"] = 0.25
    assert trader._compute_target_usd(1000.0, 5.0, 50, kelly_cfg) == pytest.approx(full * 0.25)


def test_kelly_declines_non_positive_edge(kelly_cfg):
    assert trader._compute_target_usd(1000.0, 0.0, 50, kelly_cfg) == 0.0
    assert trader._compute_target_usd(1000.0, -3.0, 50, kelly_cfg) == 0.0
    assert trader._compute_target_usd(1000.0, float("-inf"), 50, kelly_cfg) == 0.0


def test_kelly_respects_clamps_and_hard_cap():
    c = merge_with_defaults({
        "sizing_mode": "kelly", "kelly_fraction": 1.0,
        "min_size_fraction": 0.02, "max_size_fraction": 0.06,
        "hard_max_position_usd": 50.0,
    })
    # Raw Kelly here is 50% of bankroll; the ceiling and hard cap must bind.
    assert trader._compute_target_usd(1000.0, 5.0, 90, c) == 50.0
    # A sliver of edge still clears the configured floor.
    assert trader._compute_target_usd(1000.0, 0.1, 20, c) == pytest.approx(20.0)


def test_kelly_mode_leaves_other_modes_untouched(cfg):
    assert cfg["sizing_mode"] == "percent"
    assert trader._compute_target_usd(1000.0, 12.5, 50, cfg) == pytest.approx(40.0)


def test_unknown_sizing_mode_falls_back_to_percent():
    c = merge_with_defaults({"sizing_mode": "martingale"})
    assert c["sizing_mode"] == "percent"


def test_kelly_fraction_is_clamped_to_full_kelly():
    assert merge_with_defaults({"kelly_fraction": 4.0})["kelly_fraction"] == 1.0
    assert merge_with_defaults({"kelly_fraction": 0.0})["kelly_fraction"] == 0.01
    assert merge_with_defaults({"kellyFraction": 0.5})["kelly_fraction"] == 0.5
