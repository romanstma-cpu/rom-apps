import json

import db
import shadow_forward


T = 1_900_000_000.0


def prediction(index, model=.7, market=.5, side='yes'):
    return {
        'ticker': f'M{index}', 'event_ticker': f'E{index}', 'source': 'whale',
        'side': side, 'observed_at': T+index*3600, 'model_version': 'test-v1',
        'feature_version': 'candidate-book-v2', 'market_probability': market,
        'model_probability': model,
    }


def events(count=80):
    output=[]
    for i in range(count):
        won=i%5!=0
        output.append({'at':T+i*3600+1800,'kind':'settlement','ticker':f'M{i}',
                       'payload':{'yes_payout':int(won)}})
    return output


def test_forward_report_scores_only_predictions_frozen_before_resolution():
    predictions=[prediction(i,model=.78 if i%5 else .22) for i in range(80)]
    report=shadow_forward.evaluate(predictions,events(),T+81*3600)
    assert report['status']=='promising'
    assert report['resolvedPredictions']==80
    assert report['modelBrier']<report['marketBrier']
    assert report['controlsLiveTrading'] is False
    assert report['forwardTrades']==64
    assert report['netReturnPct']>0
    assert report['lowerConfidenceReturnPct']>0
    assert report['maxDrawdownPct']==0
    assert report['windowsEvaluated']==4 and report['windowsPassed']==4


def test_future_and_early_settlements_are_excluded():
    predictions=[prediction(0),prediction(1)]
    evidence=[
        {'at':T-1,'kind':'settlement','ticker':'M0','payload':{'yes_payout':1}},
        {'at':T+10_000,'kind':'settlement','ticker':'M1','payload':{'yes_payout':1}},
    ]
    report=shadow_forward.evaluate(predictions,evidence,T+5000)
    assert report['resolvedPredictions']==0 and report['pendingPredictions']==2


def test_same_day_markets_count_as_one_independent_resolution_cluster():
    predictions=[]; evidence=[]
    for i in range(60):
        observed=T+i*10
        predictions.append({**prediction(i,model=.8,market=.5),'observed_at':observed})
        evidence.append({'at':T+1000+i,'kind':'settlement','ticker':f'M{i}',
                         'payload':{'yes_payout':1}})
    report=shadow_forward.evaluate(predictions,evidence,T+2000)
    assert report['independentDays']==1
    assert report['brierImprovementLowerPct'] is None
    assert report['logLossImprovementLowerPct'] is None
    assert report['lowerConfidenceReturnPct'] is None


def test_day_clustered_bounds_are_reproducible_with_independent_days():
    predictions=[]; evidence=[]
    for day in range(20):
        for offset in range(3):
            i=day*3+offset
            observed=T+day*86400+offset*60
            predictions.append({**prediction(i,model=.8,market=.5),'observed_at':observed})
            evidence.append({'at':observed+600,'kind':'settlement','ticker':f'M{i}',
                             'payload':{'yes_payout':1}})
    first=shadow_forward.evaluate(predictions,evidence,T+21*86400)
    second=shadow_forward.evaluate(predictions,evidence,T+21*86400)
    assert first['independentDays']==20
    assert first['brierImprovementLowerPct']>0
    assert first['logLossImprovementLowerPct']>0
    assert first['lowerConfidenceReturnPct']>0
    assert first['brierImprovementLowerPct']==second['brierImprovementLowerPct']
    assert first['lowerConfidenceReturnPct']==second['lowerConfidenceReturnPct']


def test_prediction_ledger_keeps_first_model_call_per_event(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'db_path',lambda:tmp_path/'forward.db')
    db.init_db(); shadow_forward.init()
    first=prediction(0); second={**first,'model_probability':.99,'observed_at':T+1}
    assert shadow_forward.record(first)
    assert not shadow_forward.record(second)
    with db.get_db() as conn:
        row=conn.execute('SELECT payload FROM ml_shadow_predictions').fetchone()
    assert json.loads(row['payload'])['model_probability']==.7
