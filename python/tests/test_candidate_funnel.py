import candidate_funnel
import db
import json
import main_recorder


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


def test_persisted_funnel_read_is_bounded(tmp_path, monkeypatch):
    database = tmp_path / 'funnel.db'
    monkeypatch.setattr(db, 'db_path', lambda: database)
    monkeypatch.setattr(candidate_funnel, 'MAX_SIGNAL_ROWS', 3)
    db.init_db(); main_recorder.init()
    now = candidate_funnel.time.time()
    rows = []
    for index in range(8):
        payload = {
            'source': 'momentum',
            'signal': {'event_ticker': f'E{index}', 'ticker': f'M{index}'},
            'originalDecision': [True, 'ok'],
        }
        rows.append((now-index, 'signal', f'M{index}', json.dumps(payload)))
    with db.get_db() as conn:
        conn.executemany(
            'INSERT INTO main_replay_events(at,kind,ticker,payload) VALUES (?,?,?,?)',
            rows,
        )
        conn.execute(
            'INSERT INTO main_replay_events(at,kind,ticker,payload) VALUES (?,?,?,?)',
            (now, 'funnel_blocker', '', json.dumps({'reason': 'waiting'})),
        )
    report = candidate_funnel.load_report()
    assert report['observedEvents'] == 3
    assert report['latestRuntimeBlocker']['reason'] == 'waiting'
