"""Gamma row parsing — token order safety and event extraction."""
from polybot.gamma import parse_market

BASE = {
    "conditionId": "0xc1",
    "question": "Will it?",
    "clobTokenIds": '["tok-yes", "tok-no"]',
    "outcomes": '["Yes", "No"]',
    "volume24hr": 1234.5,
    "endDate": "2026-12-31T00:00:00Z",
    "events": [{"slug": "fed-decision-september", "title": "Fed Decision"}],
}


def test_parse_market_happy_path():
    m = parse_market(BASE, "politics")
    assert m is not None
    assert m.yes_token == "tok-yes" and m.no_token == "tok-no"
    assert m.event_slug == "fed-decision-september"
    assert m.event_key == "fed-decision-september"
    assert m.volume_24h == 1234.5


def test_parse_market_rejects_missing_outcomes():
    # clobTokenIds are in outcome order; without outcomes we cannot know
    # which token is YES, and guessing wrong inverts every trade.
    assert parse_market({**BASE, "outcomes": None}, "p") is None
    assert parse_market({k: v for k, v in BASE.items() if k != "outcomes"},
                        "p") is None


def test_parse_market_rejects_non_binary():
    assert parse_market({**BASE, "outcomes": '["Up", "Down"]'}, "p") is None
    assert parse_market({**BASE, "clobTokenIds": '["a", "b", "c"]'}, "p") is None


def test_parse_market_without_event_uses_condition_id():
    m = parse_market({**BASE, "events": []}, "p")
    assert m is not None and m.event_slug == ""
    assert m.event_key == "0xc1"
