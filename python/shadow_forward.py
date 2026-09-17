"""Append-only forward predictions scored only after later settlement."""
from __future__ import annotations

import json
import math
import random
import time
from collections import defaultdict
from statistics import mean

import db
import fees_us


MIN_FORWARD = 50
MAX_AGE = 90 * 86400
MIN_MODEL_EDGE = 0.04
SIMULATION_RISK_FRACTION = 0.01
CONSISTENCY_WINDOWS = 4
BOOTSTRAP_REPLICATES = 2000
CONFIDENCE_LEVEL_PCT = 95.0
BOOTSTRAP_SEED = 0x524F4D
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


def _window_consistency(resolved):
    """Score fixed chronological windows without choosing the best period."""
    if len(resolved) < CONSISTENCY_WINDOWS * 10:
        return 0, 0
    passed = 0
    for index in range(CONSISTENCY_WINDOWS):
        start = len(resolved) * index // CONSISTENCY_WINDOWS
        end = len(resolved) * (index + 1) // CONSISTENCY_WINDOWS
        window = resolved[start:end]
        model_brier = mean((float(row['model_probability'])-row['outcome'])**2
                           for row in window)
        market_brier = mean((float(row['market_probability'])-row['outcome'])**2
                            for row in window)
        model_log = mean(_log_loss(float(row['model_probability']),row['outcome'])
                         for row in window)
        market_log = mean(_log_loss(float(row['market_probability']),row['outcome'])
                          for row in window)
        passed += int(model_brier < market_brier and model_log < market_log)
    return CONSISTENCY_WINDOWS, passed


def _trade_result(row):
    market=float(row['market_probability'])
    model=float(row['model_probability'])
    if model-market < MIN_MODEL_EDGE:
        return None
    try:
        cost=fees_us.reserved_cost(1,market,float(row['observed_at']))
    except (TypeError,ValueError):
        return None
    if not math.isfinite(cost) or cost <= 0:
        return None
    return cost,float(row['outcome'])-cost


def _trade_stats(resolved):
    """Simulate only precommitted positive-edge selections at fixed risk."""
    total_cost=0.0; total_pnl=0.0; trades=0
    equity=1.0; peak=1.0; max_drawdown=0.0
    for row in resolved:
        result=_trade_result(row)
        if result is None:
            continue
        cost,pnl=result
        unit_return=pnl/cost
        trades+=1; total_cost+=cost; total_pnl+=pnl
        equity=max(0.0,equity*(1+SIMULATION_RISK_FRACTION*unit_return))
        peak=max(peak,equity)
        max_drawdown=max(max_drawdown,(peak-equity)/peak if peak else 0.0)
    return {
        'forwardTrades':trades,
        'netReturnPct':100*total_pnl/total_cost if total_cost else None,
        'maxDrawdownPct':100*max_drawdown if trades else None,
        'minimumModelEdgePct':100*MIN_MODEL_EDGE,
        'simulationRiskPct':100*SIMULATION_RISK_FRACTION,
    }


def _percentile(values,probability):
    ordered=sorted(values)
    if not ordered:
        return None
    position=(len(ordered)-1)*probability
    lower=math.floor(position); upper=math.ceil(position)
    if lower==upper:
        return ordered[lower]
    weight=position-lower
    return ordered[lower]*(1-weight)+ordered[upper]*weight


def _clustered_confidence(resolved):
    """One-sided confidence bounds with resolution-day cluster resampling.

    Markets resolved on the same UTC day can share news and liquidity regimes,
    so a whole day is sampled as one unit instead of treating every market as
    independent. A fixed seed makes the promotion decision reproducible.
    """
    groups=defaultdict(lambda:{
        'count':0,'model_brier':0.0,'market_brier':0.0,
        'model_log':0.0,'market_log':0.0,'trade_cost':0.0,'trade_pnl':0.0,
    })
    for row in resolved:
        group=groups[int(float(row['resolved_at'])//86400)]
        outcome=row['outcome']; model=float(row['model_probability'])
        market=float(row['market_probability'])
        group['count']+=1
        group['model_brier']+=(model-outcome)**2
        group['market_brier']+=(market-outcome)**2
        group['model_log']+=_log_loss(model,outcome)
        group['market_log']+=_log_loss(market,outcome)
        trade=_trade_result(row)
        if trade is not None:
            group['trade_cost']+=trade[0]
            group['trade_pnl']+=trade[1]
    days=sorted(groups)
    output={
        'independentDays':len(days),
        'bootstrapReplicates':BOOTSTRAP_REPLICATES,
        'confidenceLevelPct':CONFIDENCE_LEVEL_PCT,
        'brierImprovementLowerPct':None,
        'logLossImprovementPct':None,
        'logLossImprovementLowerPct':None,
        'lowerConfidenceReturnPct':None,
    }
    if len(days)<2:
        return output
    rng=random.Random(BOOTSTRAP_SEED)
    brier_changes=[]; log_changes=[]; returns=[]
    for _ in range(BOOTSTRAP_REPLICATES):
        sample=[groups[rng.choice(days)] for _day in days]
        count=sum(group['count'] for group in sample)
        model_brier=sum(group['model_brier'] for group in sample)/count
        market_brier=sum(group['market_brier'] for group in sample)/count
        if market_brier>0:
            brier_changes.append(100*(market_brier-model_brier)/market_brier)
        model_log=sum(group['model_log'] for group in sample)/count
        market_log=sum(group['market_log'] for group in sample)/count
        if market_log>0:
            log_changes.append(100*(market_log-model_log)/market_log)
        total_cost=sum(group['trade_cost'] for group in sample)
        if total_cost:
            returns.append(100*sum(group['trade_pnl'] for group in sample)/total_cost)
    tail=(100-CONFIDENCE_LEVEL_PCT)/100
    model_log=mean(_log_loss(float(row['model_probability']),row['outcome'])
                   for row in resolved)
    market_log=mean(_log_loss(float(row['market_probability']),row['outcome'])
                    for row in resolved)
    output.update(
        brierImprovementLowerPct=_percentile(brier_changes,tail),
        logLossImprovementPct=(100*(market_log-model_log)/market_log
                               if market_log else None),
        logLossImprovementLowerPct=_percentile(log_changes,tail),
        lowerConfidenceReturnPct=_percentile(returns,tail),
    )
    return output


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
            'brierImprovementPct':None,'controlsLiveTrading':False,'minimumResolved':MIN_FORWARD,
            'observationSpanDays':(max(0.0,(max(row['resolved_at'] for row in resolved)
                                             -min(float(row['observed_at']) for row in resolved))/86400)
                                   if resolved else 0.0),
            'windowsEvaluated':0,'windowsPassed':0,
            **_trade_stats(resolved),**_clustered_confidence(resolved)}
    report['windowsEvaluated'],report['windowsPassed']=_window_consistency(resolved)
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
    import shadow_ranker
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
        try:
            prediction=json.loads(row['payload'])
            if prediction.get('model_version')==shadow_ranker.VERSION:
                predictions.append(prediction)
        except (TypeError,ValueError): pass
    events=[]
    for row in event_rows:
        try: events.append({**dict(row),'payload':json.loads(row['payload'])})
        except (TypeError,ValueError): pass
    return evaluate(predictions,events,now)
