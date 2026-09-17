"""Read-only fill and adverse-movement challenger models.

The report consumes confirmed order evidence. Nothing in this module is used
by order admission, routing, sizing, or the existing adverse-selection guard.
"""
from __future__ import annotations

import json
import math
import time
from statistics import mean

import db
import order_journal


VERSION = 'execution-logistic-shadow-v1'
MIN_FILL_TRAIN = 100
MIN_FILL_TEST = 40
MIN_ADVERSE_TRAIN = 60
MIN_ADVERSE_TEST = 30
EMBARGO = 86400
SHRINKAGE = 0.5
MAX_TRAIN_ROWS = 2000
MAX_TEST_ROWS = 1000
FEATURE_NAMES = (
    'limit_price', 'spread_cents', 'signal_move_cents', 'log_quantity',
    'log_bid_depth3', 'log_ask_depth3', 'book_imbalance3',
    'log_quote_age_ms', 'log_response_ms', 'style_maker', 'style_resting',
    'source_momentum',
)
_cache = None


def _number(value, default=0.0):
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError, OverflowError):
        return default


def feature_values(row):
    recorded = row.get('features') or {}
    bid = _number(row.get('bid_cents'))
    ask = _number(row.get('ask_cents'))
    values = {
        'limit_price': min(.99, max(.01, _number(row.get('limit_price'), .5))),
        'spread_cents': min(20.0, max(0.0, ask-bid)),
        'signal_move_cents': min(20.0, max(-20.0, _number(row.get('limit_price'))*100-_number(row.get('signal_cents')))),
        'log_quantity': math.log1p(max(0.0, _number(row.get('quantity')))),
        'log_bid_depth3': math.log1p(max(0.0, _number(recorded.get('bidDepth3')))),
        'log_ask_depth3': math.log1p(max(0.0, _number(recorded.get('askDepth3')))),
        'book_imbalance3': min(1.0, max(-1.0, _number(recorded.get('bookImbalance3')))),
        'log_quote_age_ms': math.log1p(max(0.0, _number(recorded.get('quoteAgeMs')))),
        'log_response_ms': math.log1p(max(0.0, _number(row.get('response_ms')))),
        'style_maker': float(row.get('style') == 'maker'),
        'style_resting': float(row.get('style') == 'resting'),
        'source_momentum': float(row.get('source') == 'momentum'),
    }
    return [values[name] for name in FEATURE_NAMES]


def _sigmoid(value):
    if value >= 0:
        exp = math.exp(-min(value, 40.0))
        return 1/(1+exp)
    exp = math.exp(max(value, -40.0))
    return exp/(1+exp)


def _train(rows, label):
    matrix = [feature_values(row) for row in rows]
    centers = [mean(column) for column in zip(*matrix)]
    scales = []
    for index, center in enumerate(centers):
        variance = mean((values[index]-center)**2 for values in matrix)
        scales.append(max(math.sqrt(variance), 1e-6))
    vectors = [[(value-center)/scale for value,center,scale in zip(values,centers,scales)]
               for values in matrix]
    weights = [0.0]*(len(FEATURE_NAMES)+1)
    rate = .08
    for step in range(700):
        gradients = [0.0]*len(weights)
        for values,row in zip(vectors,rows):
            error = _sigmoid(weights[0]+sum(w*x for w,x in zip(weights[1:],values)))-row[label]
            gradients[0] += error
            for index,value in enumerate(values,1):
                gradients[index] += error*value
        weights[0] -= rate*gradients[0]/len(rows)
        for index in range(1,len(weights)):
            weights[index] -= rate*(gradients[index]/len(rows)+.08*weights[index])
        if step and step%250 == 0:
            rate *= .65
    return weights,centers,scales


def _predict(row, model, baseline):
    weights,centers,scales = model
    values = feature_values(row)
    vector = [(value-center)/scale for value,center,scale in zip(values,centers,scales)]
    raw = _sigmoid(weights[0]+sum(w*x for w,x in zip(weights[1:],vector)))
    return baseline+SHRINKAGE*(raw-baseline)


def _loss(probability, outcome):
    probability = min(1-1e-6,max(1e-6,probability))
    return -outcome*math.log(probability)-(1-outcome)*math.log(1-probability)


def _empty(reason):
    return {'status':'collecting','reason':reason,'trainEvents':0,'testEvents':0,
            'modelBrier':None,'baselineBrier':None,'modelLogLoss':None,
            'baselineLogLoss':None,'baselineRate':None}


def _evaluate(rows, label, minimum_train, minimum_test, asof):
    eligible = sorted((row for row in rows if row['at'] < asof-EMBARGO),key=lambda row:row['at'])
    if len(eligible) < minimum_train+minimum_test:
        return _empty('Collect more terminal orders with confirmed labels.')
    cutoff = eligible[int(len(eligible)*.7)]['at']
    train = [row for row in eligible if row['at'] < cutoff-EMBARGO][-MAX_TRAIN_ROWS:]
    test = [row for row in eligible if row['at'] >= cutoff][:MAX_TEST_ROWS]
    if len(train) < minimum_train or len(test) < minimum_test:
        result = _empty('The chronological train or test window is still too small.')
        result.update(trainEvents=len(train),testEvents=len(test))
        return result
    baseline = min(.995,max(.005,mean(row[label] for row in train)))
    model = _train(train,label)
    predictions = [_predict(row,model,baseline) for row in test]
    model_brier = mean((prediction-row[label])**2 for prediction,row in zip(predictions,test))
    baseline_brier = mean((baseline-row[label])**2 for row in test)
    model_log = mean(_loss(prediction,row[label]) for prediction,row in zip(predictions,test))
    baseline_log = mean(_loss(baseline,row[label]) for row in test)
    promising = model_brier < baseline_brier and model_log < baseline_log
    return {'status':'promising' if promising else 'not_better',
            'reason':('Beat the constant-rate baseline on later orders.' if promising
                      else 'Did not beat the constant-rate baseline on later orders.'),
            'trainEvents':len(train),'testEvents':len(test),'modelBrier':model_brier,
            'baselineBrier':baseline_brier,'modelLogLoss':model_log,
            'baselineLogLoss':baseline_log,'baselineRate':baseline}


def fit(rows, asof):
    usable=[]; seen=set()
    for source in sorted(rows,key=lambda row:(row.get('at',0),row.get('local_id',''))):
        at=_number(source.get('at'),-1); local_id=str(source.get('local_id') or '')
        if at<0 or at>=asof or not local_id or local_id in seen:
            continue
        seen.add(local_id)
        row={**source,'at':at,'filled':int(bool(source.get('filled')))}
        if source.get('adverse') is not None:
            row['adverse']=int(bool(source.get('adverse')))
        usable.append(row)
    fill_model=_evaluate(usable,'filled',MIN_FILL_TRAIN,MIN_FILL_TEST,asof)
    adverse_rows=[row for row in usable if 'adverse' in row]
    adverse_model=_evaluate(adverse_rows,'adverse',MIN_ADVERSE_TRAIN,MIN_ADVERSE_TEST,asof)
    statuses=(fill_model['status'],adverse_model['status'])
    status='promising' if statuses==('promising','promising') else ('collecting' if 'collecting' in statuses else 'not_better')
    report={'version':VERSION,'status':status,'asOf':asof,'orders':len(usable),
            'markoutSamples':len(adverse_rows),'controlsLiveTrading':False,
            'featureNames':list(FEATURE_NAMES),'fillModel':fill_model,
            'adverseModel':adverse_model,
            'reason':('Both execution challengers beat their later baselines.' if status=='promising'
                      else 'Execution challengers remain in evidence-only shadow mode.')}
    return {'report':report,'asof':asof}


def load_report(network):
    global _cache
    now=time.time(); key=(str(db.db_path()),network)
    if _cache and _cache[0]==key and 0<=now-_cache[1]<300:
        return _cache[2]
    order_journal.init()
    with db.get_db() as conn:
        records=conn.execute(
            """SELECT i.local_id,i.ticker,i.quantity,i.limit_price,i.created_at at,
                      i.filled,e.source,e.style,e.signal_cents,e.bid_cents,e.ask_cents,
                      e.response_ms,f.payload,m.markout_cents
                 FROM us_order_intents i
                 JOIN us_entry_execution e USING(local_id)
                 LEFT JOIN us_entry_features f USING(local_id)
                 LEFT JOIN us_fill_markouts m ON m.local_id=i.local_id AND m.horizon_sec=120
                WHERE e.network=? AND i.action='buy' AND i.created_at>=?
                  AND i.state IN ('filled','canceled','rejected')
                ORDER BY i.created_at,i.local_id""",(network,now-60*86400)).fetchall()
    rows=[]
    for record in records:
        row=dict(record); payload=row.pop('payload',None); markout=row.pop('markout_cents',None)
        try:
            decoded=json.loads(payload) if payload else {}
            row['features']=decoded if isinstance(decoded,dict) else {}
        except (TypeError,ValueError): row['features']={}
        row['filled']=int(_number(row.get('filled'))>0)
        if markout is not None: row['adverse']=int(_number(markout)<0)
        rows.append(row)
    result=fit(rows,now); _cache=(key,now,result)
    return result['report']
