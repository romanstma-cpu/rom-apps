import asyncio
from datetime import datetime, timezone

import pytest
import signal_calibration as calibration
import trader
from config import merge_with_defaults
from test_portfolio_replay import config, evidence, event
from portfolio_replay import replay

T = datetime(2026, 7, 10, tzinfo=timezone.utc).timestamp()


def dataset(n=400, rate=.8):
    events=[]
    for i in range(n):
        at=T+i*7200
        signal=dict(id=i,ticker=f'M{i}',event_ticker=f'E{i}',category='sports',
                    confidence=98,price=.5,taker_side='yes',created_at=datetime.fromtimestamp(at,timezone.utc).isoformat())
        events.append(dict(at=at,kind='signal',ticker=f'M{i}',payload={'source':'whale','signal':signal}))
        events.append(dict(at=at+3600,kind='settlement',ticker=f'M{i}',payload={'yes_payout':int(i%10 < rate*10)}))
    return events


def test_realistic_empirical_estimate_qualifies_against_overconfident_score():
    model=calibration.fit(dataset(),T+401*7200)
    assert model['report']['qualifiedBuckets']==1
    item=next(iter(model['bins'].values()))
    assert .75 < item['probability'] < .82
    assert item['lowerProbability'] < item['probability'] < .98
    assert item['brier'] < item['marketBrier'] and item['brier'] < item['scoreBrier']
    assert model['report']['trainEvents']+model['report']['testEvents']<400  # embargo purges recent labels


def test_unchanged_market_accuracy_does_not_qualify():
    assert not calibration.fit(dataset(rate=.5),T+401*7200)['bins']


def test_repeated_event_cannot_inflate_training_or_test_count():
    events=dataset()
    for item in events:
        if item['kind']=='signal': item['payload']['signal']['event_ticker']='same-event'
    model=calibration.fit(events,T+401*7200)
    assert model['report']['eventSamples']==1
    assert not model['bins']


def test_future_evidence_does_not_change_past_model():
    events=dataset()
    cutoff=T+180*7200
    expected=calibration.fit(events,cutoff)
    for item in events:
        if item['at']>=cutoff and item['kind']=='settlement':item['payload']['yes_payout']=0
    assert calibration.fit(events,cutoff)==expected


def test_delayed_settlements_do_not_leak_into_training():
    events=dataset()
    for item in events:
        if item['kind']=='settlement':item['at']=T+400*7200
    model=calibration.fit(events,T+401*7200)
    assert model['report']['trainEvents']==0
    assert not model['bins']


def test_stale_evidence_fails_qualification():
    assert not calibration.fit(dataset(),T+401*7200+31*86400)['bins']


def test_unresolved_holdout_events_cannot_be_silently_dropped():
    events=[e for e in dataset() if not (e['kind']=='settlement' and e['ticker']=='M300')]
    assert not calibration.fit(events,T+401*7200)['bins']


def test_metadata_is_not_taken_from_future():
    events=dataset(1)
    del events[0]['payload']['signal']['event_ticker']
    events.append(dict(at=T+20,kind='market',ticker='M0',payload={'event_ticker':'E0'}))
    assert calibration.fit(events,T+5000)['report']['eventSamples']==0


def test_whale_no_and_momentum_no_have_correct_cost_conventions():
    signal=dict(price=.3,confidence=80,taker_side='no',direction='no')
    assert calibration.features(signal,'whale')[1]==.3
    assert calibration.features(signal,'momentum')[1]==.7


def test_no_outcome_is_inverted_and_void_is_excluded():
    events=dataset(2)
    events[0]['payload']['signal']['taker_side']='no'
    events[3]['payload']['yes_payout']=.5
    rows,_=calibration.samples(events,T+20000)
    assert len(rows)==1 and rows[0]['outcome']==0


def test_net_margin_uses_conservative_probability_fees_and_haircut():
    model=calibration.fit(dataset(),T+401*7200)
    signal=dataset(1)[0]['payload']['signal']
    edge=calibration.calibrated_edge(signal,'whale',50,model['asof'],model)
    bucket=next(iter(model['bins'].values()))
    assert edge==pytest.approx((bucket['lowerProbability']-.52)*100-1)
    with pytest.raises(ValueError,match='future'):calibration.calibrated_edge(signal,'whale',50,model['asof']-1,model)
    with pytest.raises(ValueError,match='stale'):calibration.calibrated_edge(signal,'whale',50,model['asof']+601,model)
    signal['category']='politics'
    with pytest.raises(ValueError,match='qualified'):calibration.calibrated_edge(signal,'whale',50,model['asof'],model)


def test_live_kelly_cannot_use_raw_score_when_model_missing(monkeypatch):
    model=calibration.fit([],trader.time.time())
    monkeypatch.setattr(calibration,'load_model',lambda:model)
    signal=dataset(1)[0]['payload']['signal']
    signal['created_at']=datetime.now(timezone.utc).isoformat()
    # Must return before touching positions or submitting orders.
    monkeypatch.setattr(trader.db,'get_db',lambda:pytest.fail('Unqualified Kelly touched positions'))
    assert asyncio.run(trader.execute_signal(signal,'whale',merge_with_defaults({'sizing_mode':'kelly'}),1000)) is None


def test_replay_kelly_does_not_train_on_later_settlement():
    result=replay(config(sizing_mode='kelly'),evidence()+[event('settlement',{'yes_payout':1},3)])
    assert result['submittedOrders']==0
    assert result['rejections']['Kelly calibration unavailable']==1


def test_minimum_size_never_increases_kelly_risk():
    cfg=merge_with_defaults({'sizing_mode':'kelly','min_size_fraction':.1,'kelly_fraction':1})
    assert trader._compute_target_usd(1000,.1,20,cfg)==pytest.approx(1.25)
