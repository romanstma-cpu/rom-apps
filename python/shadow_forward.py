"""Append-only forward predictions scored only after later settlement."""
from __future__ import annotations

import json
import math
import time
from statistics import mean

import db


MIN_FORWARD = 50
MAX_AGE = 90 * 86400
SCHEMA = """
CREATE TABLE IF NOT EXISTS ml_shadow_predictions (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 observed_at REAL NOT NULL,
 ticker TEXT NOT NULL,
 event_ticker TEXT NOT NULL,
 model_version TEXT NOT NULL,
 payload TEXT NOT NULL,
 UNIQUE(event_ticker, model_version)
);
CREATE INDEX IF NOT EXISTS ml_shadow_predictions_time
 ON ml_shadow_predictions(observed_at,id);
"""


def init():
    with db.get_db() as conn:
        conn.executescript(SCHEMA)


def record(prediction):
    required=('observed_at','ticker','event_ticker','model_version',
              'market_probability','model_probability','side')
    if any(prediction.get(key) in (None,'') for key in required):
        return False
    market=float(prediction['market_probability']); model=float(prediction['model_probability'])
    if not all(math.isfinite(value) and 0<value<1 for value in (market,model)):
        return False
    init()
    with db.get_db() as conn:
        conn.execute(
            'INSERT OR IGNORE INTO ml_shadow_predictions '
            '(observed_at,ticker,event_ticker,model_version,payload) VALUES (?,?,?,?,?)',
            (float(prediction['observed_at']),str(prediction['ticker']),
             str(prediction['event_ticker']),str(prediction['model_version']),
             json.dumps(prediction,allow_nan=False,sort_keys=True)),
        )
        return bool(conn.execute('SELECT changes()').fetchone()[0])


def capture(signal, source, features):
    """Freeze a candidate prediction; absence of a fitted model is expected."""
    import shadow_ranker
    result=shadow_ranker.load_model()
    probability=shadow_ranker.predict(signal,source,features,result)
    if probability is None:
        return False
    side,market,_score=shadow_ranker._side_probability(signal,source)
    prediction={
        'ticker':str(signal.get('ticker') or ''),
        'event_ticker':str(signal.get('event_ticker') or ''),
        'source':source,'side':side,
        'observed_at':float(features.get('observedAt') or time.time()),
        'model_version':str(result['report']['version']),
        'feature_version':str(features.get('version') or ''),
        'market_probability':market,'model_probability':probability,
    }
    return record(prediction)


def _log_loss(probability,outcome):
    probability=min(1-1e-6,max(1e-6,probability))
    return -outcome*math.log(probability)-(1-outcome)*math.log(1-probability)


def evaluate(predictions,events,asof):
    settlements={}
    for event in sorted(events,key=lambda item:(item.get('at',0),item.get('id',0))):
        if event.get('kind')!='settlement' or not 0<=float(event.get('at',-1))<asof:
            continue
        payout=(event.get('payload') or {}).get('yes_payout')
        if payout in (0,1) and not isinstance(payout,bool):
            settlements.setdefault(str(event.get('ticker') or ''),[]).append(
                (float(event['at']),float(payout)))
    seen=set(); resolved=[]; pending=0
    for source in sorted(predictions,key=lambda row:(row.get('observed_at',0),row.get('event_ticker',''))):
        at=float(source.get('observed_at',-1))
        if at<0 or at>=asof:
            continue
        key=(str(source.get('event_ticker') or ''),str(source.get('model_version') or ''))
        if not key[0] or key in seen:
            continue
        seen.add(key)
        later=next((item for item in settlements.get(str(source.get('ticker') or ''),[]) if item[0]>at),None)
        if later is None:
            pending+=1; continue
        outcome=later[1] if str(source.get('side') or 'yes')=='yes' else 1-later[1]
        resolved.append({**source,'outcome':outcome,'resolved_at':later[0]})
    report={'status':'collecting','reason':'Collect more precommitted predictions and later settlements.',
            'asOf':asof,'resolvedPredictions':len(resolved),'pendingPredictions':pending,
            'modelBrier':None,'marketBrier':None,'modelLogLoss':None,'marketLogLoss':None,
            'brierImprovementPct':None,'controlsLiveTrading':False,'minimumResolved':MIN_FORWARD}
    if len(resolved)<MIN_FORWARD:
        return report
    model_brier=mean((float(row['model_probability'])-row['outcome'])**2 for row in resolved)
    market_brier=mean((float(row['market_probability'])-row['outcome'])**2 for row in resolved)
    model_log=mean(_log_loss(float(row['model_probability']),row['outcome']) for row in resolved)
    market_log=mean(_log_loss(float(row['market_probability']),row['outcome']) for row in resolved)
    promising=model_brier<market_brier and model_log<market_log
    report.update(status='promising' if promising else 'not_better',
                  reason=('Precommitted model predictions beat the market baseline.' if promising
                          else 'Precommitted predictions have not beaten the market baseline.'),
                  modelBrier=model_brier,marketBrier=market_brier,
                  modelLogLoss=model_log,marketLogLoss=market_log,
                  brierImprovementPct=(100*(market_brier-model_brier)/market_brier
                                       if market_brier else 0.0))
    return report


def load_report():
    import main_recorder
    now=time.time(); init(); main_recorder.init()
    with db.get_db() as conn:
        prediction_rows=conn.execute(
            'SELECT payload FROM ml_shadow_predictions WHERE observed_at>=? ORDER BY observed_at,id',
            (now-MAX_AGE,)).fetchall()
        event_rows=conn.execute(
            "SELECT id,at,kind,ticker,payload FROM main_replay_events "
            "WHERE at>=? AND kind='settlement' ORDER BY at,id",(now-MAX_AGE,)).fetchall()
    predictions=[]
    for row in prediction_rows:
        try: predictions.append(json.loads(row['payload']))
        except (TypeError,ValueError): pass
    events=[]
    for row in event_rows:
        try: events.append({**dict(row),'payload':json.loads(row['payload'])})
        except (TypeError,ValueError): pass
    return evaluate(predictions,events,now)
