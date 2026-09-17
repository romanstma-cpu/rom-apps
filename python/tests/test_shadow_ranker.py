from datetime import datetime, timezone
import inspect

import shadow_ranker
import trader


T = datetime(2026, 5, 1, tzinfo=timezone.utc).timestamp()


def evidence(count=360):
    events = []
    for i in range(count):
        at = T + i * 7200
        strong = i % 4 in (0, 1, 2)
        signal = {
            "ticker": f"M{i}",
            "event_ticker": f"E{i}",
            "category": "sports" if i % 2 else "politics",
            "price": 0.5,
            "confidence": 75 if strong else 25,
            "taker_side": "yes",
            "dollar_value": 20_000 if strong else 500,
            "market_volume": 100_000,
            "open_interest": 25_000,
            "days_to_close": 3,
            "created_at": datetime.fromtimestamp(at, timezone.utc).isoformat(),
        }
        events.append({"at": at, "kind": "signal", "ticker": f"M{i}",
                       "payload": {"source": "whale", "signal": signal}})
        events.append({"at": at + 3600, "kind": "settlement", "ticker": f"M{i}",
                       "payload": {"yes_payout": int(strong)}})
    return events


def test_feature_vector_is_frozen_deterministic_and_bounded():
    signal = evidence(1)[0]["payload"]["signal"]
    first = shadow_ranker.feature_values(signal, "whale")
    signal["dollar_value"] = 1
    second = shadow_ranker.feature_values(signal, "whale")
    assert first != second
    assert list(first) == list(shadow_ranker.FEATURE_NAMES)
    assert all(value == value and abs(value) < 100 for value in first.values())


def test_shadow_model_beats_market_on_untouched_chronological_holdout():
    result = shadow_ranker.fit(evidence(), T + 361 * 7200)
    report = result["report"]
    assert report["status"] == "promising"
    assert report["controlsLiveTrading"] is False
    assert report["testEvents"] >= shadow_ranker.MIN_TEST
    assert report["modelBrier"] < report["marketBrier"]
    assert report["modelLogLoss"] < report["marketLogLoss"]
    assert 0 < report["shrinkage"] < 1


def test_future_outcomes_do_not_change_a_past_shadow_report():
    events = evidence()
    cutoff = T + 240 * 7200
    expected = shadow_ranker.fit(events, cutoff)
    for event in events:
        if event["kind"] == "settlement" and event["at"] >= cutoff:
            event["payload"]["yes_payout"] = 1 - event["payload"]["yes_payout"]
    assert shadow_ranker.fit(events, cutoff) == expected


def test_repeated_events_and_unresolved_holdout_cannot_inflate_evidence():
    events = evidence()
    for event in events:
        if event["kind"] == "signal":
            event["payload"]["signal"]["event_ticker"] = "same-event"
    result = shadow_ranker.fit(events, T + 361 * 7200)
    assert result["report"]["settledSamples"] == 1
    assert result["report"]["status"] == "collecting"


def test_small_samples_remain_collecting_and_never_control_live_orders():
    report = shadow_ranker.fit(evidence(20), T + 30 * 7200)["report"]
    assert report["status"] == "collecting"
    assert report["controlsLiveTrading"] is False
    assert report["modelBrier"] is None


def test_live_trader_has_no_shadow_model_dependency():
    assert "shadow_ranker" not in inspect.getsource(trader)
