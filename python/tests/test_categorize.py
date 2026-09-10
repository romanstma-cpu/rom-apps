"""Categorize: keyword-based market classification and micro-market filtering.

The category gate determines confidence score adjustments (CATEGORY_EDGE),
and is_micro_market blocks 5m/15m "up or down" markets from the main
scanner. Both are pure functions with no side effects.
"""
from __future__ import annotations

import pytest

from categorize import (
    CATEGORY_EDGE,
    categorize_by_keywords,
    is_micro_market,
)


class TestCategorizeByKeywords:
    def test_slug_prefix_matches_sports(self):
        assert categorize_by_keywords("", slug="nba-lebron-points") == "sports"
        assert categorize_by_keywords("", slug="nfl-totals") == "sports"
        assert categorize_by_keywords("", slug="f1-monaco-gp") == "sports"

    def test_slug_substring_matches_sports(self):
        assert categorize_by_keywords("", slug="wimbledon-2026") == "sports"
        assert categorize_by_keywords("", slug="world-cup-semifinal") == "sports"

    def test_politics_keywords(self):
        for kw in ["election", "trump", "biden", "congress", "supreme court"]:
            assert categorize_by_keywords(f"Will {kw} happen?") == "politics"

    def test_economics_keywords(self):
        for kw in ["fed ", "inflation", "gdp", "tariff", "nasdaq", "earnings"]:
            assert categorize_by_keywords(f"Will {kw} rise?") == "economics"

    def test_crypto_keywords(self):
        for kw in ["bitcoin", "btc", "ethereum", "solana", "defi"]:
            assert categorize_by_keywords(f"Will {kw} surpass?") == "crypto"

    def test_climate_keywords(self):
        for kw in ["hurricane", "temperature", "earthquake", "wildfire"]:
            assert categorize_by_keywords(f"Will a {kw} hit?") == "climate"

    def test_entertainment_keywords(self):
        for kw in ["oscar", "netflix", "grammy", "box office"]:
            assert categorize_by_keywords(f"Will {kw} dominate?") == "entertainment"

    def test_empty_returns_world(self):
        assert categorize_by_keywords("") == "world"
        assert categorize_by_keywords("", slug="random-slug") == "world"

    def test_no_match_returns_world(self):
        assert categorize_by_keywords("Something completely unrelated") == "world"

    def test_title_beats_no_slug_match(self):
        # Title match takes precedence over slug prefix for non-sports
        assert categorize_by_keywords("Bitcoin price prediction", slug="x") == "crypto"

    def test_slug_takes_priority_over_title(self):
        # Sports slug should win even if title has a politics keyword
        assert categorize_by_keywords("Who will win the election?", slug="nba-finals") == "sports"

    def test_case_insensitive(self):
        assert categorize_by_keywords("BITCOIN HALVING") == "crypto"
        assert categorize_by_keywords("Oscars 2026") == "entertainment"


class TestCategoryEdge:
    def test_all_keys_present(self):
        for cat in ("sports", "crypto", "world", "politics", "economics",
                     "entertainment", "climate"):
            assert cat in CATEGORY_EDGE

    def test_crypto_highest_edge(self):
        assert CATEGORY_EDGE["crypto"] > CATEGORY_EDGE["sports"]
        assert CATEGORY_EDGE["crypto"] > CATEGORY_EDGE["politics"]

    def test_world_is_negative(self):
        assert CATEGORY_EDGE["world"] < 0


class TestIsMicroMarket:
    def test_updown_5m(self):
        assert is_micro_market("btc-usd-updown-5m-12345") is True

    def test_updown_15m(self):
        assert is_micro_market("eth-usd-updown-15m-67890") is True

    def test_up_or_down(self):
        assert is_micro_market("btc-usd-up-or-down-1hr") is True

    def test_normal_market_not_micro(self):
        assert is_micro_market("will-bitcoin-hit-100k") is False

    def test_empty_slug(self):
        assert is_micro_market("") is False
        assert is_micro_market(None) is False

    def test_case_insensitive(self):
        assert is_micro_market("BTC-USD-UPDOWN-5M-123") is True

    def test_partial_match_not_enough(self):
        assert is_micro_market("updown") is False  # needs full pattern


class TestWordBoundaryRegressions:
    """False positives caught by characterization tests and fixed with \b."""

    def test_inflation_is_not_nfl_sports(self):
        assert categorize_by_keywords("Will inflation rise?") == "economics"

    def test_something_is_not_eth_crypto(self):
        assert categorize_by_keywords("Something completely unrelated") == "world"

    def test_oscar_singular_is_entertainment(self):
        assert categorize_by_keywords("Will oscar win best actor?") == "entertainment"

    def test_real_nfl_still_sports(self):
        assert categorize_by_keywords("Will the NFL season start?") == "sports"

    def test_real_btc_still_crypto(self):
        assert categorize_by_keywords("BTC price prediction") == "crypto"
        assert categorize_by_keywords("Ethereum and Bitcoin both rallying") == "crypto"

    def test_blockchain_is_crypto(self):
        assert categorize_by_keywords("Blockchain scaling debate") == "crypto"

    def test_eth_whole_word_still_crypto(self):
        assert categorize_by_keywords("Ethereum (ETH) upgrade") == "crypto"