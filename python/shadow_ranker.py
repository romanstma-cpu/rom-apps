"""Read-only logistic shadow model for recorded main-strategy candidates.

This module has no order, wallet, sizing, or routing imports. It trains on
settled, event-deduplicated observations and compares its fixed-shrinkage
probabilities with the market price on a later chronological holdout.
"""
from __future__ import annotations

import json
import math
import time
from collections import Counter
from statistics import mean

import db
import evidence_loader


VERSION = "logistic-shadow-v1"
MIN_TRAIN = 120
MIN_TEST = 60
MAX_TRAIN_ROWS = 2000
MAX_TEST_ROWS = 1000
EMBARGO = 86400
MAX_AGE = 60 * 86400
SHRINKAGE = 0.35
L2_PENALTY = 0.08
FEATURE_NAMES = (
    "market_logit",
    "heuristic_edge",
    "log_market_volume",
    "log_open_interest",
    "log_signal_dollars",
    "log_flow_count",
    "absolute_price_change",
    "days_to_close",
    "spread_cents",
    "log_bid_depth3",
    "log_ask_depth3",
    "book_imbalance3",
    "microprice_edge",
    "log_quote_age_ms",
    "source_momentum",
    "side_yes",
    "category_sports",
    "category_politics",
    "category_economics",
    "category_entertainment",
    "category_climate",
    "category_crypto",
)
_cache = None


def _number(value, default=0.0):
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def _clamp_probability(value):
    return min(0.995, max(0.005, _number(value, 0.5)))


def _side_probability(signal, source):
    side = str(signal.get("taker_side" if source == "whale" else "direction") or "yes").lower()
    market = _clamp_probability(signal.get("price", 0.5))
    if source == "momentum" and side == "no":
        market = 1.0 - market
    score = _clamp_probability(_number(signal.get("confidence"), 50.0) / 100.0)
    return side, market, score


def feature_values(signal, source, market=None, recorded=None):
    """Return a new, deterministic snapshot of bounded numeric features."""
    if source not in ("whale", "momentum"):
        raise ValueError("Unsupported shadow signal source")
    market = market or {}
    recorded = recorded or {}
    side, probability, score = _side_probability(signal, source)
    category = str(signal.get("category") or "world").lower()
    volume = _number(signal.get("market_volume", signal.get("volume_24h", 0)))
    interest = _number(signal.get("open_interest", 0))
    dollars = _number(signal.get("dollar_value", signal.get("window_dollars", 0)))
    flow_count = _number(signal.get("window_trades", signal.get("count_fp", 0)))
    price_change = abs(_number(signal.get("price_change", 0))) / 100.0
    days = _number(signal.get("days_to_close", market.get("days_to_close", 0)))
    values = {
        "market_logit": math.log(probability / (1.0 - probability)),
        "heuristic_edge": score - probability,
        "log_market_volume": math.log1p(max(0.0, volume)),
        "log_open_interest": math.log1p(max(0.0, interest)),
        "log_signal_dollars": math.log1p(max(0.0, dollars)),
        "log_flow_count": math.log1p(max(0.0, flow_count)),
        "absolute_price_change": min(1.0, price_change),
        "days_to_close": math.log1p(min(3650.0, max(0.0, days))),
        "spread_cents": min(20.0, max(0.0, _number(recorded.get("spreadCents"), 0))),
        "log_bid_depth3": math.log1p(max(0.0, _number(recorded.get("bidDepth3"), 0))),
        "log_ask_depth3": math.log1p(max(0.0, _number(recorded.get("askDepth3"), 0))),
        "book_imbalance3": min(1.0, max(-1.0, _number(recorded.get("bookImbalance3"), 0))),
        "microprice_edge": _number(recorded.get("micropriceCents"), probability*100)/100-probability,
        "log_quote_age_ms": math.log1p(max(0.0, _number(recorded.get("quoteAgeMs"), 0))),
        "source_momentum": float(source == "momentum"),
        "side_yes": float(side == "yes"),
    }
    for name in FEATURE_NAMES[16:]:
        values[name] = float(category == name.removeprefix("category_"))
    return {name: values[name] for name in FEATURE_NAMES}


def _samples(events, asof):
    metadata = {}
    settlements = {}
    candidates = []
    seen = set()
    excluded = Counter()
    for event in sorted(events, key=lambda item: (item["at"], item.get("id", 0))):
        at = _number(event.get("at"), -1)
        if at < 0 or at >= asof:
            continue
        kind = event.get("kind")
        ticker = event.get("ticker")
        payload = event.get("payload") or {}
        if kind == "market":
            metadata[ticker] = dict(payload)
            continue
        if kind == "settlement":
            payout = payload.get("yes_payout")
            if payout in (0, 1) and not isinstance(payout, bool):
                settlements.setdefault(ticker, (at, float(payout)))
            else:
                excluded["non_binary_settlement"] += 1
            continue
        if kind != "signal":
            continue
        signal = payload.get("signal") or {}
        source = payload.get("source")
        event_id = signal.get("event_ticker") or metadata.get(ticker, {}).get("event_ticker")
        if not event_id:
            excluded["missing_event_identifier"] += 1
            continue
        if event_id in seen:
            excluded["repeated_event"] += 1
            continue
        seen.add(event_id)
        try:
            side, price, _score = _side_probability(signal, source)
            features = feature_values(signal, source, metadata.get(ticker), payload.get("features"))
        except (TypeError, ValueError):
            excluded["invalid_signal"] += 1
            continue
        candidates.append({"at": at, "ticker": ticker, "event": event_id,
                           "side": side, "price": price, "features": features})

    settled = []
    for row in candidates:
        resolution = settlements.get(row["ticker"])
        if not resolution or resolution[0] <= row["at"]:
            excluded["unresolved_or_late_signal"] += 1
            continue
        yes = resolution[1]
        settled.append({**row, "resolved_at": resolution[0],
                        "outcome": yes if row["side"] == "yes" else 1.0 - yes})
    return settled, candidates, dict(excluded)


def _sigmoid(value):
    if value >= 0:
        exp = math.exp(-min(value, 40.0))
        return 1.0 / (1.0 + exp)
    exp = math.exp(max(value, -40.0))
    return exp / (1.0 + exp)


def _prepare(train):
    columns = [[row["features"][name] for row in train] for name in FEATURE_NAMES]
    centers = [mean(column) for column in columns]
    scales = []
    for center, column in zip(centers, columns):
        variance = mean((value - center) ** 2 for value in column)
        scales.append(max(math.sqrt(variance), 1e-6))
    return centers, scales


def _vector(row, centers, scales):
    return [(row["features"][name] - center) / scale
            for name, center, scale in zip(FEATURE_NAMES, centers, scales)]


def _train(train):
    centers, scales = _prepare(train)
    vectors = [_vector(row, centers, scales) for row in train]
    weights = [0.0] * (len(FEATURE_NAMES) + 1)
    rate = 0.08
    for step in range(900):
        gradients = [0.0] * len(weights)
        for values, row in zip(vectors, train):
            error = _sigmoid(weights[0] + sum(w * x for w, x in zip(weights[1:], values))) - row["outcome"]
            gradients[0] += error
            for index, value in enumerate(values, 1):
                gradients[index] += error * value
        count = len(train)
        weights[0] -= rate * gradients[0] / count
        for index in range(1, len(weights)):
            weights[index] -= rate * (gradients[index] / count + L2_PENALTY * weights[index])
        if step and step % 300 == 0:
            rate *= 0.65
    return {"weights": weights, "centers": centers, "scales": scales}


def _predict(row, model):
    values = _vector(row, model["centers"], model["scales"])
    raw = _sigmoid(model["weights"][0] + sum(
        weight * value for weight, value in zip(model["weights"][1:], values)
    ))
    return row["price"] + SHRINKAGE * (raw - row["price"])


def predict(signal, source, recorded, result):
    """Score one current candidate with an already fitted shadow result."""
    model = result.get('model') if isinstance(result, dict) else None
    if model is None:
        return None
    side, price, _score = _side_probability(signal, source)
    row = {'price': price, 'side': side,
           'features': feature_values(signal, source, recorded=recorded)}
    return _predict(row, model)


def _log_loss(probability, outcome):
    probability = min(1 - 1e-6, max(1e-6, probability))
    return -outcome * math.log(probability) - (1 - outcome) * math.log(1 - probability)


def fit(events, asof):
    rows, candidates, excluded = _samples(events, asof)
    report = {
        "version": VERSION,
        "status": "collecting",
        "reason": "Collect more distinct settled events before evaluating the shadow model.",
        "asOf": asof,
        "settledSamples": len(rows),
        "distinctEvents": len(candidates),
        "trainEvents": 0,
        "testEvents": 0,
        "modelBrier": None,
        "marketBrier": None,
        "modelLogLoss": None,
        "marketLogLoss": None,
        "brierImprovementPct": None,
        "shrinkage": SHRINKAGE,
        "controlsLiveTrading": False,
        "excluded": excluded,
        "featureNames": list(FEATURE_NAMES),
        "minimums": {"trainEvents": MIN_TRAIN, "testEvents": MIN_TEST},
    }
    result = {"report": report, "model": None, "asof": asof}
    eligible = sorted((row for row in candidates if row["at"] < asof - EMBARGO),
                      key=lambda row: row["at"])
    if len(eligible) < MIN_TRAIN + MIN_TEST:
        return result
    cutoff = eligible[int(len(eligible) * 0.7)]["at"]
    test_candidates = [row for row in eligible if row["at"] >= cutoff]
    test_events = {row["event"] for row in test_candidates}
    available_train = [row for row in rows
                       if row["event"] not in test_events and row["resolved_at"] < cutoff - EMBARGO]
    available_test = [row for row in rows if row["event"] in test_events]
    train = available_train[-MAX_TRAIN_ROWS:]
    test = available_test[:MAX_TEST_ROWS]
    report.update(trainEvents=len(train), testEvents=len(test), splitAt=cutoff)
    if (len(train) < MIN_TRAIN or len(test) < MIN_TEST
            or len(available_test) != len(test_candidates)):
        report["reason"] = "The chronological holdout is incomplete or still below the minimum evidence threshold."
        return result
    if asof - max(row["resolved_at"] for row in test) > MAX_AGE:
        report.update(status="stale", reason="The latest settled holdout is too old to evaluate current behavior.")
        return result

    model = _train(train)
    predictions = [_predict(row, model) for row in test]
    model_brier = mean((prediction - row["outcome"]) ** 2
                       for prediction, row in zip(predictions, test))
    market_brier = mean((row["price"] - row["outcome"]) ** 2 for row in test)
    model_log_loss = mean(_log_loss(prediction, row["outcome"])
                          for prediction, row in zip(predictions, test))
    market_log_loss = mean(_log_loss(row["price"], row["outcome"]) for row in test)
    improvement = 100.0 * (market_brier - model_brier) / market_brier if market_brier else 0.0
    promising = model_brier < market_brier and model_log_loss < market_log_loss
    report.update(
        status="promising" if promising else "not_better",
        reason=(
            "The shadow model beat the market-price baseline on the untouched holdout. It still does not control live trading."
            if promising else
            "The shadow model did not beat the market-price baseline on the untouched holdout."
        ),
        modelBrier=model_brier,
        marketBrier=market_brier,
        modelLogLoss=model_log_loss,
        marketLogLoss=market_log_loss,
        brierImprovementPct=improvement,
    )
    result["model"] = model
    return result


def load_model():
    global _cache
    now = time.time()
    key = str(db.db_path())
    if _cache and _cache[0] == key and 0 <= now - _cache[1] < 300:
        return _cache[2]
    import main_recorder
    main_recorder.init()
    events, window = evidence_loader.load_recent_events(now)
    result = fit(events, now)
    result["report"]["evidenceWindow"] = window
    _cache = (key, now, result)
    return result
