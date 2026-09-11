from datetime import datetime, timezone

import pytest
import db
import main_recorder
from config import merge_with_defaults
from portfolio_replay import replay, iso

T = datetime(2026, 8, 1, tzinfo=timezone.utc).timestamp()


def event(kind, payload, at=0, ticker='A'):
    return dict(at=T+at, kind=kind, ticker=ticker, payload=payload)


def book(ask=.60, qty=10, at=0, ticker='A'):
    return event('book', {'bids': [{'px': ask-.01, 'qty': 100}],
                          'offers': [{'px': ask, 'qty': qty}]}, at, ticker)


def evidence(ticker='A', event_id='E', side='yes'):
    return [event('market', dict(active=True, min_size=1, tick_size=.01, event_ticker=event_id), ticker=ticker),
            book(ticker=ticker),
            event('signal', {'source': 'whale', 'signal': dict(id=ticker, ticker=ticker,
                  confidence=90, price=.60, taker_side=side, created_at=iso(T))}, ticker=ticker)]


def staged(ticker, event_id, at):
    """Evidence for a market whose signal arrives in a later scan."""
    return [event('market', dict(active=True, min_size=1, tick_size=.01,
                                 event_ticker=event_id), at, ticker),
            book(ticker=ticker, at=at),
            event('signal', {'source': 'whale', 'signal': dict(id=ticker, ticker=ticker,
                  confidence=90, price=.60, taker_side='yes', created_at=iso(T+at))},
                  at, ticker)]


def config(**patch):
    return merge_with_defaults(dict(main_paper_bankroll_usd=100, min_size_fraction=.1,
        max_size_fraction=.1, hard_max_position_usd=6.2, min_cash_reserve_fraction=0,
        trade_scan_interval=5, position_poll_interval=5, order_expiration_sec=1, **patch))


def test_hand_calculated_settlement_and_no_duplicate_payout():
    events=evidence()+[event('settlement', {'yes_payout': 1}, 3), event('settlement', {'yes_payout': 1}, 4)]
    result=replay(config(), events)
    assert result['n']==1
    assert result['trades'][0]['contracts']==10
    assert result['feesUsd']==.14
    assert result['totalPnlUsd']==3.86
    assert result['cashUsd']==103.86
    assert result['openPositions']==result['pendingOrders']==0


def test_partial_fill_cancels_remainder_and_keeps_actual_basis():
    events=evidence(); events[1]=book(qty=3)
    result=replay(config(), events+[event('settlement', {'yes_payout': 0}, 3)])
    assert result['trades'][0]['contracts']==3
    assert result['totalPnlUsd']==-1.84
    assert result['reservedUsd']==0


def test_future_book_cannot_fill_before_order_arrival():
    result=replay(config(), evidence()+[book(.70, at=.1),event('settlement', {'yes_payout':1}, 3)])
    assert result['filledOrders']==0
    assert result['totalPnlUsd']==0


def test_passive_touch_is_not_a_fill():
    result=replay(config(order_style='limit_mid'), evidence()+[event('trade', {}, 3)])
    assert result['filledOrders']==0


def test_gap_invalidates_cached_liquidity():
    result=replay(config(), evidence()+[event('gap', {}, .1), event('trade', {}, 3)])
    assert result['filledOrders']==0


def test_open_position_is_included_in_equity_after_exit_fees():
    result=replay(config(), evidence()+[event('trade', {}, 1)])
    assert result['n']==0 and result['openPositions']==1
    assert result['totalPnlUsd']==-.39  # 6.14 entry; 5.90 less .15 exit fee
    assert result['maxDrawdownUsd']==-.39


def test_no_stale_book_liquidation_value():
    result=replay(config(), evidence()+[event('trade', {}, 8)])
    assert result['totalPnlUsd']==-6.14
    assert result['valuationGapSamples']>0


@pytest.mark.parametrize('patch,reason', [
    ({}, 'event concentration cap'),
    ({'max_positions_per_event':10,'max_open_positions':1},'open position cap'),
    ({'max_positions_per_event':10,'max_daily_new_positions':1},'daily position cap'),
])
def test_caps_include_pending_positions(patch, reason):
    result=replay(config(**patch), evidence()+evidence('B')+[event('trade', {}, 1)], latency_ms=2000)
    assert result['submittedOrders']==1
    assert result['rejections'][reason]>=1
    assert result['reservedUsd']==6.2


def test_replay_groups_separate_events_of_one_series_like_live():
    """Replay must refuse what live would refuse.

    Live resolves an entry's group through the events table, so a backtest that
    grouped these two markets by event alone would report exposure live would
    have blocked. Series membership is static, so reading it while replaying
    older evidence is not look-ahead.
    """
    evidence_both = (evidence('A', event_id='E1')+staged('B', 'E2', 10)
                     +[event('trade', {}, 1)])
    cfg = config(max_positions_per_event=10, max_group_exposure_fraction=.05)
    grouped = replay(cfg, evidence_both, series={'E1': 'TOURNEY', 'E2': 'TOURNEY'})
    # One series, one allowance: the second market gets no room of its own.
    assert grouped['submittedOrders'] == 1
    assert sum(grouped['rejections'].get(reason, 0) for reason in
               ('related-outcome exposure cap', 'cash or exposure budget')) >= 1
    # Without a recorded series the two events stay separate groups, unchanged.
    apart = replay(cfg, evidence_both, series={})
    assert apart['submittedOrders'] == 2
    assert 'related-outcome exposure cap' not in apart['rejections']
    assert grouped['equityUsd'] <= apart['equityUsd'] or grouped['openPositions'] < apart['openPositions']


def test_replay_group_lookup_is_skipped_while_the_cap_is_off():
    """The default configuration must not consult the metadata store at all."""
    events = evidence('A', event_id='E1')+evidence('B', event_id='E2')+[event('trade', {}, 1)]
    cfg = config(max_positions_per_event=10)
    assert cfg['max_group_exposure_fraction'] == 0.0
    result = replay(cfg, events)  # no `series` injected; must not read the db
    assert result['submittedOrders'] == 2
    assert 'related-outcome exposure cap' not in result['rejections']


def test_missing_metadata_and_missing_evidence_are_not_successful_backtests():
    result=replay(config(), evidence()[1:]+[event('trade', {}, 1)])
    assert result['filledOrders']==0
    assert result['rejections']['missing or inactive market metadata']>0
    assert replay(config(), [])['dataStatus']=='insufficient_data'


def test_stress_reduces_depth_and_preserves_limit():
    result=replay(config(), evidence()+[event('trade', {}, 1)], depth_fraction=.25)
    assert result['filledOrders']==1 and result['openPositions']==1
    assert result['cashUsd']==98.77
    assert replay(config(), evidence()+[event('trade', {}, 1)], slippage_cents=1)['filledOrders']==0


def test_recorder_copies_payload_and_flushes_to_isolated_database(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'db_path', lambda: tmp_path/'replay.db')
    monkeypatch.setattr(main_recorder, '_queue', main_recorder.deque())
    monkeypatch.setattr(main_recorder, '_dropped', 0)
    monkeypatch.setattr(main_recorder, '_enabled', True)
    payload={'value': 1}
    main_recorder.record('trade','A',payload,at=T)
    payload['value']=2
    main_recorder.flush()
    rows=main_recorder.load(1,end=T+1)
    assert rows[0]['payload']=={'value':1}


def test_bad_assumption_rejected():
    with pytest.raises(ValueError): replay(config(), [], depth_fraction=2)
