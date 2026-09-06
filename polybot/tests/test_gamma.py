"""Gamma row parsing and event-based discovery."""
import requests

from polybot.gamma import GammaClient, parse_market

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


# -- discovery over /events -----------------------------------------

def row(cid, vol, closed=False, question="Will it?"):
    return {"conditionId": cid, "question": question,
            "clobTokenIds": f'["{cid}-yes", "{cid}-no"]',
            "outcomes": '["Yes", "No"]', "volume24hr": vol,
            "endDate": "2026-12-31T00:00:00Z", "closed": closed}


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeSession:
    """Records the request Gamma was actually asked to serve."""

    def __init__(self, payload, fail=False):
        self.payload = payload
        self.fail = fail
        self.requests = []

    def get(self, url, params=None, timeout=None):
        self.requests.append((url, params))
        if self.fail:
            raise requests.RequestException("connection aborted")
        return FakeResponse(self.payload)


EVENTS = [
    {"slug": "fed-decision-september",
     "markets": [row("a", 900), row("b", 500), row("c", 300),
                 row("d", 100), row("e", 50)]},
    {"slug": "next-french-president",
     "markets": [row("f", 800), row("g", 20)]},
]


def test_discovery_asks_events_not_markets():
    # /markets accepts tag_slug and ignores it: a real tag, a different real
    # tag and an invented one all return the same global list. Only /events
    # honours the filter, so asking the wrong endpoint is the whole bug.
    http = FakeSession(EVENTS)
    GammaClient(session=http).markets_for_category("politics")
    url, params = http.requests[0]
    assert url.endswith("/events")
    assert params["tag_slug"] == "politics"


def test_per_event_cap_keeps_the_most_traded_of_a_crowded_event():
    # One event can carry 128 markets. Uncapped, a single race fills the
    # watch list with mutually exclusive outcomes of one question.
    http = FakeSession(EVENTS)
    got = GammaClient(session=http).markets_for_category(
        "politics", max_per_event=2)
    # two per event, then the whole list ranked by volume: c, d and e are
    # dropped because their event already spent its allowance on a and b.
    assert [m.condition_id for m in got] == ["a", "f", "b", "g"]


def test_markets_carry_their_events_slug_so_siblings_group_exactly():
    http = FakeSession(EVENTS)
    got = GammaClient(session=http).markets_for_category("politics")
    by_id = {m.condition_id: m for m in got}
    assert by_id["a"].event_slug == "fed-decision-september"
    assert by_id["a"].event_key == by_id["b"].event_key   # siblings
    assert by_id["a"].event_key != by_id["f"].event_key


def test_category_is_the_tag_that_was_actually_filtered_on():
    http = FakeSession(EVENTS)
    got = GammaClient(session=http).markets_for_category("politics")
    assert {m.category for m in got} == {"politics"}


def test_illiquid_and_closed_markets_are_dropped():
    http = FakeSession([{"slug": "e1",
                         "markets": [row("live", 900), row("thin", 10),
                                     row("done", 900, closed=True)]}])
    got = GammaClient(session=http).markets_for_category(
        "politics", min_volume_24h=100)
    assert [m.condition_id for m in got] == ["live"]


def test_a_failed_category_yields_nothing_and_does_not_raise():
    # The soak logged this on almost every cycle. It must degrade to an
    # empty category, never take the whole discovery pass down with it.
    http = FakeSession(EVENTS, fail=True)
    assert GammaClient(session=http).markets_for_category("politics") == []


def test_discover_dedupes_across_categories_and_keeps_the_limit():
    http = FakeSession(EVENTS)
    got = GammaClient(session=http).discover(
        categories=["politics", "world"], exclude=["world"],
        limit_per_category=3, min_volume_24h=0)
    assert [m.condition_id for m in got] == ["a", "f", "b"]
