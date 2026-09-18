"""Explain where recorded main-strategy candidates leave the trade funnel.

This report is observational only. It reads append-only replay evidence and
cannot change configuration, candidate selection, sizing, or order placement.
"""
from __future__ import annotations

from collections import Counter
import time

import main_recorder


LOOKBACK_DAYS = 30


def _reason_group(reason: str) -> str:
    value = (reason or '').lower()
    if value == 'ok':
        return 'Eligible at signal gate'
    if 'disabled' in value or value.endswith(' off'):
        return 'Strategy disabled'
    if value.startswith('conf '):
        return 'Confidence threshold'
    if value.startswith('edge '):
        return 'Edge threshold'
    if 'categor' in value:
        return 'Category filter'
    if 'resolves in' in value:
        return 'Resolution horizon'
    if value.startswith('entry '):
        return 'Entry price range'
    if 'signal_type' in value:
        return 'Signal type filter'
    if any(term in value for term in ('missing', 'invalid', 'stale', 'future')):
        return 'Signal data quality'
    if 'rule' in value:
        return 'Custom rules'
    return 'Other signal filter'


def build(events: list[dict], *, asof: float | None = None) -> dict:
    asof = time.time() if asof is None else float(asof)
    first_by_event = {}
    latest_blocker = None
    for event in events:
        kind = event.get('kind')
        payload = event.get('payload') or {}
        if kind == 'funnel_blocker':
            observed = float(event.get('at') or 0)
            if latest_blocker is None or observed >= latest_blocker['at']:
                latest_blocker = {
                    'reason': str(payload.get('reason') or 'Unknown blocker'),
                    'at': observed,
                }
            continue
        if kind != 'signal':
            continue
        signal = payload.get('signal') or {}
        source = str(payload.get('source') or 'unknown')
        identity = str(signal.get('event_ticker') or signal.get('ticker') or '')
        if not identity:
            continue
        key = (source, identity)
        observed = float(event.get('at') or 0)
        if key not in first_by_event or observed < float(first_by_event[key].get('at') or 0):
            first_by_event[key] = event

    reasons = Counter()
    sources = Counter()
    observed_times = []
    eligible = 0
    for event in first_by_event.values():
        payload = event.get('payload') or {}
        decision = payload.get('originalDecision') or [False, 'Decision unavailable']
        accepted = bool(decision[0]) if isinstance(decision, (list, tuple)) and decision else False
        reason = str(decision[1] if isinstance(decision, (list, tuple)) and len(decision) > 1 else 'Decision unavailable')
        reasons[_reason_group('ok' if accepted else reason)] += 1
        sources[str(payload.get('source') or 'unknown')] += 1
        observed_times.append(float(event.get('at') or 0))
        eligible += int(accepted)

    total = len(first_by_event)
    blocked = total - eligible
    blocker_rows = [
        {'reason': name, 'count': count,
         'sharePct': 100 * count / total if total else 0.0}
        for name, count in reasons.most_common()
        if name != 'Eligible at signal gate'
    ]
    dominant = blocker_rows[0] if blocker_rows else None
    if not total:
        status = 'collecting'
        summary = 'No event-deduplicated signal candidates have been recorded yet.'
    elif blocked == 0:
        status = 'open'
        summary = ('Recorded candidates are clearing the signal gate; inspect '
                   'the latest runtime blocker for later-stage limits.')
    else:
        status = 'constrained'
        summary = (f"{dominant['reason']} is the largest recorded signal-stage blocker."
                   if dominant else 'Recorded candidates are being filtered.')
    return {
        'status': status,
        'reason': summary,
        'asOf': asof,
        'lookbackDays': LOOKBACK_DAYS,
        'observedEvents': total,
        'eligibleEvents': eligible,
        'blockedEvents': blocked,
        'observationSpanDays': ((max(observed_times) - min(observed_times)) / 86400
                                if len(observed_times) > 1 else 0.0),
        'dominantBlocker': dominant,
        'blockers': blocker_rows[:8],
        'sources': dict(sorted(sources.items())),
        'latestRuntimeBlocker': latest_blocker,
        'controlsLiveTrading': False,
    }


def load_report() -> dict:
    now = time.time()
    return build(main_recorder.load(LOOKBACK_DAYS, end=now), asof=now)
