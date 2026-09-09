from __future__ import annotations

import pytest

import config as cfgmod
import trader


def _signal(category: str) -> dict:
    return {
        "category": category, "ticker": "0xt", "confidence": 99.0,
        "edge_pts": 99.0, "price": 0.5, "close_time": "",
        "signal_type": "trade_cluster", "dollar_value": 10_000.0,
    }


def _cfg(**camel) -> dict:
    return cfgmod.merge_with_defaults(dict(camel))


def test_camel_keys_from_the_ui_map_to_the_snake_keys_the_trader_reads():
    merged = _cfg(
        allowedCategories=["sports", "crypto"],
        allowedWhaleCategories=["crypto"],
        allowedMomentumCategories=["sports"],
    )
    assert merged["allowed_categories"] == ["sports", "crypto"]
    assert merged["allowed_whale_categories"] == ["crypto"]
    assert merged["allowed_momentum_categories"] == ["sports"]


def test_global_filter_is_enforced():
    cfg = _cfg(allowedCategories=["crypto"])
    ok, why = trader.should_trade(_signal("sports"), "whale", cfg)
    assert ok is False
    assert "not in allowed set" in why


def test_global_filter_allows_a_listed_category():
    cfg = _cfg(allowedCategories=["sports"])
    ok, _why = trader.should_trade(_signal("sports"), "whale", cfg)
    assert ok is True


def test_global_none_means_no_filter():
    cfg = _cfg(allowedCategories=None)
    ok, _why = trader.should_trade(_signal("politics"), "whale", cfg)
    assert ok is True


def test_global_empty_list_means_trade_nothing():
    cfg = _cfg(allowedCategories=[])
    ok, why = trader.should_trade(_signal("crypto"), "whale", cfg)
    assert ok is False
    assert "no categories enabled" in why


def test_per_source_list_narrows_within_the_global_one():
    cfg = _cfg(
        allowedCategories=["sports", "crypto"],
        allowedWhaleCategories=["crypto"],
    )
    ok, why = trader.should_trade(_signal("sports"), "whale", cfg)
    assert ok is False
    assert "not in whale set" in why, why
    ok2, _ = trader.should_trade(_signal("crypto"), "whale", cfg)
    assert ok2 is True


def test_per_source_none_adds_no_restriction():
    cfg = _cfg(
        allowedCategories=["sports", "crypto"],
        allowedWhaleCategories=None,
    )
    ok, _why = trader.should_trade(_signal("sports"), "whale", cfg)
    assert ok is True


def test_per_source_empty_list_halts_that_engine():
    cfg = _cfg(allowedWhaleCategories=[])
    ok, why = trader.should_trade(_signal("crypto"), "whale", cfg)
    assert ok is False
    assert "no whale categories enabled" in why


def test_convergence_shares_the_whale_list():
    cfg = _cfg(tradeConvergence=True, allowedWhaleCategories=["crypto"])
    ok, why = trader.should_trade(_signal("sports"), "convergence", cfg)
    assert ok is False
    assert "not in convergence set" in why or "not in whale set" in why


def test_momentum_uses_its_own_list_not_the_whale_one():
    cfg = _cfg(
        allowedCategories=["sports"],
        allowedWhaleCategories=["crypto"],
        allowedMomentumCategories=None,
    )
    ok, _why = trader.should_trade(_signal("sports"), "momentum", cfg)
    assert ok is True


@pytest.mark.parametrize("source", ["whale", "momentum"])
def test_global_and_per_source_compose_with_AND(source):
    key = ("allowedWhaleCategories" if source == "whale"
           else "allowedMomentumCategories")
    cfg = _cfg(**{"allowedCategories": ["crypto"], key: ["sports"]})
    ok, _ = trader.should_trade(_signal("sports"), source, cfg)
    assert ok is False
    ok2, _ = trader.should_trade(_signal("crypto"), source, cfg)
    assert ok2 is False
