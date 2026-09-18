import candidate_funnel


def event(source, identity, decision, at):
    return {
        'kind': 'signal', 'at': at,
        'payload': {
            'source': source,
            'signal': {'event_ticker': identity, 'ticker': f'{identity}-YES'},
            'originalDecision': decision,
        },
    }


def test_funnel_deduplicates_events_and_names_largest_blocker():
    rows = [
        event('whale', 'E1', [False, 'conf 51.0 < 60'], 10),
        event('whale', 'E1', [True, 'ok'], 20),
        event('whale', 'E2', [False, 'conf 52.0 < 60'], 30),
        event('momentum', 'E3', [False, "category 'other' not in allowed set"], 40),
        event('momentum', 'E4', [True, 'ok'], 50),
    ]
    report = candidate_funnel.build(rows, asof=100)
    assert report['observedEvents'] == 4
    assert report['eligibleEvents'] == 1
    assert report['blockedEvents'] == 3
    assert report['dominantBlocker'] == {
        'reason': 'Confidence threshold', 'count': 2, 'sharePct': 50.0,
    }
    assert report['sources'] == {'momentum': 2, 'whale': 2}


def test_funnel_reports_latest_runtime_blocker_without_counting_cycles():
    rows = [
        {'kind': 'funnel_blocker', 'at': 10, 'payload': {'reason': 'old'}},
        {'kind': 'funnel_blocker', 'at': 20, 'payload': {'reason': 'No qualified signal group yet'}},
    ]
    report = candidate_funnel.build(rows, asof=30)
    assert report['status'] == 'collecting'
    assert report['observedEvents'] == 0
    assert report['latestRuntimeBlocker'] == {
        'reason': 'No qualified signal group yet', 'at': 20.0,
    }


def test_funnel_groups_price_and_resolution_filters():
    rows = [
        event('whale', 'E1', [False, 'entry 22c < 30c'], 10),
        event('whale', 'E2', [False, 'resolves in ~80d > max 30d'], 20),
    ]
    report = candidate_funnel.build(rows, asof=30)
    assert {item['reason'] for item in report['blockers']} == {
        'Entry price range', 'Resolution horizon',
    }
