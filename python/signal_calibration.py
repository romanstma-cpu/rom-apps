"""Event-deduplicated, chronological calibration of heuristic main scores.

No external feeds, orders, model downloads or automatic strategy promotion.
Only Kelly sizing consumes qualified estimates; other sizing remains unchanged.
"""
import math
import time
from collections import Counter, defaultdict
from statistics import mean, stdev

import db
import fees_us
from execution_quality import signal_problem, signal_freshness_problem

VERSION = 'event-bins-v1'
MIN_TRAIN = 60
MIN_TEST = 40
EMBARGO = 86400
MAX_AGE = 30 * 86400
_cache = None


def features(signal, source):
    if source not in ('whale', 'momentum') or signal_problem(signal, source):
        raise ValueError('Unsupported calibration signal')
    side = (signal.get('taker_side' if source == 'whale' else 'direction') or 'yes').lower()
    price = float(signal['price'])
    if source == 'momentum' and side == 'no':
        price = 1-price
    score = float(signal['confidence'])/100
    # Momentum flow measurement changed with the trade-window rewrite, so its
    # scores are not comparable across versions and must never share a bucket.
    regime = str(signal.get('score_version') or 'legacy') if source == 'momentum' else ''
    # Coarse, fixed bins avoid tuning boundaries on the evaluation sample.
    key = (source, side, str(signal.get('category') or 'unknown').lower(),
           min(4, int(price*5)), int(score-price > .05), regime)
    return key, price, score


def samples(events, asof, *, include_pending=False):
    metadata = {}; pending = []; settled = {}; seen = set(); excluded = Counter()
    for event in sorted(events, key=lambda e: (e['at'], e.get('id', 0))):
        at = float(event['at'])
        if at >= asof:
            continue
        kind, ticker, payload = event['kind'], event['ticker'], event['payload']
        if kind == 'market':
            metadata[ticker] = payload
        elif kind == 'settlement':
            value = payload.get('yes_payout')
            if value in (0, 1) and not isinstance(value, bool):
                settled.setdefault(ticker, (at, float(value)))
            else:
                excluded['non_binary_settlement'] += 1
        elif kind == 'signal':
            signal = payload.get('signal', {}); source = payload.get('source')
            try:
                key, price, score = features(signal, source)
            except (ValueError, TypeError, KeyError):
                excluded['invalid_signal'] += 1; continue
            group = signal.get('event_ticker') or metadata.get(ticker, {}).get('event_ticker')
            if not group:
                excluded['missing_event_identifier'] += 1; continue
            if signal_freshness_problem(signal, 120, at):
                excluded['stale_signal'] += 1; continue
            identity = group
            if identity in seen:
                excluded['repeated_event'] += 1; continue
            # Deduplicate before checking outcome so unresolved early candidates
            # cannot be replaced by later, conveniently resolved candidates.
            seen.add(identity)
            pending.append(dict(key=key, price=price, score=score, at=at,
                                event=group, ticker=ticker))
    rows = []
    for row in pending:
        resolution = settled.get(row['ticker'])
        if not resolution or resolution[0] <= row['at']:
            excluded['unresolved_or_late_signal'] += 1; continue
        row['resolved_at'], yes = resolution
        row['outcome'] = yes if row['key'][1] == 'yes' else 1-yes
        rows.append(row)
    if include_pending:
        return rows, dict(excluded), pending
    return rows, dict(excluded)


def lower_bound(wins, n):
    # Wilson 95% lower endpoint on event counts; not a guarantee under dependence.
    p = wins/n; z = 1.96
    return (p+z*z/(2*n)-z*math.sqrt(p*(1-p)/n+z*z/(4*n*n)))/(1+z*z/n)


def fit(events, asof):
    rows, excluded, pending = samples(events, asof, include_pending=True)
    report = dict(version=VERSION, asOf=asof, status='collecting',
                  eventSamples=len(rows), qualifiedBuckets=0, trainEvents=0,
                  testEvents=0, excluded=excluded, buckets=[],
                  reason='Collect more distinct settled events. Heuristic scores are not win probabilities.')
    model = dict(report=report, bins={}, asof=asof)
    # Split observed candidates, not just resolved or fast-settling markets.
    # Require a fully resolved holdout cohort per bucket, with a one-day lag.
    cohort = sorted((r for r in pending if r['at'] < asof-EMBARGO), key=lambda r:r['at'])
    if len(cohort) < MIN_TRAIN+MIN_TEST:
        return model
    cutoff = cohort[int(len(cohort)*.7)]['at']
    # Purge entire events across all sources when any candidate is in holdout.
    test_cohort = [r for r in cohort if r['at'] >= cutoff]
    test_groups = {r['event'] for r in test_cohort}
    train = [r for r in rows if r['event'] not in test_groups and r['resolved_at'] < cutoff-EMBARGO]
    test = [r for r in rows if r['event'] in test_groups]
    report.update(trainEvents=len(train), testEvents=len(test), splitAt=cutoff)
    bins = defaultdict(list); tests = defaultdict(list)
    for row in train: bins[row['key']].append(row)
    for row in test: tests[row['key']].append(row)
    for key, group in bins.items():
        evaluation = tests[key]; n = len(group); m = len(evaluation)
        expected = sum(r['key']==key for r in test_cohort)
        if n < MIN_TRAIN or m < MIN_TEST or m != expected:
            continue
        wins = sum(r['outcome'] for r in group)
        probability = (wins+20*mean(r['price'] for r in group))/(n+20)
        lower = min(probability, lower_bound(wins, n))
        brier = mean((probability-r['outcome'])**2 for r in evaluation)
        market_brier = mean((r['price']-r['outcome'])**2 for r in evaluation)
        score_brier = mean((r['score']-r['outcome'])**2 for r in evaluation)
        gains = [(r['price']-r['outcome'])**2-(probability-r['outcome'])**2 for r in evaluation]
        gain_lower = mean(gains)-1.96*stdev(gains)/math.sqrt(m)
        def logloss(p, y):
            p = max(1e-6, min(1-1e-6, p))
            return -y*math.log(p)-(1-y)*math.log(1-p)
        log_loss = mean(logloss(probability, r['outcome']) for r in evaluation)
        market_log_loss = mean(logloss(r['price'], r['outcome']) for r in evaluation)
        recent = asof-max(r['resolved_at'] for r in evaluation) <= MAX_AGE
        span = max(r['at'] for r in evaluation)-min(r['at'] for r in group)
        qualified = (recent and span >= 14*86400 and market_brier-brier >= .005
                     and gain_lower > 0 and brier <= score_brier and log_loss < market_log_loss)
        item = dict(source=key[0], side=key[1], category=key[2], priceBand=key[3],
                    scoreBand=key[4], scoreVersion=key[5], trainEvents=n, testEvents=m,
                    probability=probability,
                    lowerProbability=lower, observedTestRate=mean(r['outcome'] for r in evaluation),
                    brier=brier, marketBrier=market_brier, scoreBrier=score_brier,
                    gainLower=gain_lower, qualified=qualified)
        report['buckets'].append(item)
        if qualified:
            model['bins'][key] = item
    report['qualifiedBuckets'] = len(model['bins'])
    if model['bins']:
        report.update(status='qualified', reason='Some score groups passed historical checks. Estimates remain uncertain; this is not proof of profitable execution.')
    else:
        report.update(status='not_qualified', reason='No score group has enough recent holdout evidence to outperform market prices. Kelly entries stay blocked.')
    return model


def load_model():
    global _cache
    now = time.time(); key = str(db.db_path())
    if _cache and _cache[0] == key and 0 <= now-_cache[1] < 300:
        return _cache[2]
    import main_recorder
    main_recorder.init()
    import json
    with db.get_db() as conn:
        rows = conn.execute("SELECT id,at,kind,ticker,payload FROM main_replay_events WHERE at>=? AND kind IN ('signal','market','settlement') ORDER BY at,id LIMIT 100001", (now-60*86400,)).fetchall()
    if len(rows) > 100000:
        raise ValueError('Calibration evidence exceeds the processing limit')
    events = [{**dict(r), 'payload':json.loads(r['payload'])} for r in rows]
    model = fit(events, now)
    _cache = (key, now, model)
    return model


def calibrated_edge(signal, source, limit_cents, at, model):
    key, _, _ = features(signal, source)
    if model['asof'] > at or at-model['asof'] > 600:
        raise ValueError('Calibration model is stale or contains future evidence')
    bucket = model['bins'].get(key)
    if not bucket:
        raise ValueError('Kelly requires a qualified calibration group; collect settled event evidence')
    # Per-contract reserve includes adverse cent rounding. Margin is net of
    # fees and another cent of uncertainty; size uses the conservative bound.
    cost = fees_us.reserved_cost(1, limit_cents/100, at)
    return (bucket['lowerProbability']-cost)*100-1
