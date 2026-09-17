"""Read-only promotion gate for the ML shadow system.

The gate combines frozen forward predictions with confirmed execution evidence.
It produces a rollout recommendation, but it has no order, sizing, wallet, or
routing dependency and cannot change live trading.
"""
from __future__ import annotations

import time


VERSION = 'ml-promotion-gate-v1'
MIN_FORWARD_PREDICTIONS = 200
MIN_OBSERVATION_DAYS = 21
MIN_FORWARD_TRADES = 80
MIN_BRIER_IMPROVEMENT_PCT = 5.0
MIN_WINDOWS_PASSED = 3
MAX_DRAWDOWN_PCT = 8.0
MIN_COMPLETED_ORDERS = 40
MIN_COST_SAMPLES = 20
MIN_FILL_RATE_PCT = 50.0
MAX_SIGNAL_SLIPPAGE_CENTS = 1.5
MIN_MARKOUT_SAMPLES = 30
MIN_MARKOUT_120_CENTS = -0.25
ROLLOUT_INFLUENCE_PCT = 10.0
ROLLOUT_ACCOUNT_RISK_CAP_PCT = 0.5


def _gate(gate_id, label, status, detail, actual=None, required=None):
    return {
        'id':gate_id,'label':label,'status':status,'detail':detail,
        'actual':actual,'required':required,
    }


def _minimum(gate_id,label,actual,required,unit=''):
    actual=float(actual or 0)
    status='pass' if actual>=required else 'collecting'
    suffix=f' {unit}' if unit else ''
    detail=(f'{actual:.1f}{suffix} recorded; minimum {required:g}{suffix}.'
            if unit else f'{int(actual)} recorded; minimum {int(required)}.')
    return _gate(gate_id,label,status,detail,actual,required)


def _metric(gate_id,label,actual,passes,detail,required=None):
    if actual is None:
        return _gate(gate_id,label,'collecting','The metric is not available yet.',None,required)
    return _gate(gate_id,label,'pass' if passes else 'fail',detail,actual,required)


def evaluate(forward,execution_shadow,execution_quality,asof=None):
    """Return a deterministic decision from already-computed evidence reports."""
    forward=forward or {}; execution_shadow=execution_shadow or {}; execution_quality=execution_quality or {}
    gates=[]
    gates.append(_minimum('forward-sample','Resolved forward predictions',
                          forward.get('resolvedPredictions'),MIN_FORWARD_PREDICTIONS))
    gates.append(_minimum('observation-span','Forward observation span',
                          forward.get('observationSpanDays'),MIN_OBSERVATION_DAYS,'days'))
    gates.append(_minimum('forward-trades','Positive-edge shadow trades',
                          forward.get('forwardTrades'),MIN_FORWARD_TRADES))

    improvement=forward.get('brierImprovementPct')
    gates.append(_metric(
        'brier','Brier improvement versus market',improvement,
        improvement is not None and improvement>=MIN_BRIER_IMPROVEMENT_PCT,
        ('Model improvement is '
         f'{float(improvement):.1f}%; minimum {MIN_BRIER_IMPROVEMENT_PCT:.1f}%.'
         if improvement is not None else ''),MIN_BRIER_IMPROVEMENT_PCT,
    ))
    model_log=forward.get('modelLogLoss'); market_log=forward.get('marketLogLoss')
    gates.append(_metric(
        'log-loss','Log loss versus market',model_log,
        model_log is not None and market_log is not None and model_log<market_log,
        (f'Model {float(model_log):.4f}; market {float(market_log):.4f}.'
         if model_log is not None and market_log is not None else ''),market_log,
    ))
    windows=int(forward.get('windowsEvaluated') or 0)
    passed=int(forward.get('windowsPassed') or 0)
    window_status=('collecting' if windows<4 else ('pass' if passed>=MIN_WINDOWS_PASSED else 'fail'))
    gates.append(_gate('stability','Chronological consistency',window_status,
                       f'{passed} of {windows or 4} fixed windows beat both baselines.',
                       passed,MIN_WINDOWS_PASSED))

    lower_return=forward.get('lowerConfidenceReturnPct')
    gates.append(_metric(
        'net-return','Fee-adjusted return confidence',lower_return,
        lower_return is not None and lower_return>0,
        (f'One-sided 95% lower bound is {float(lower_return):.2f}% after scheduled fees.'
         if lower_return is not None else ''),0.0,
    ))
    drawdown=forward.get('maxDrawdownPct')
    gates.append(_metric(
        'drawdown','Shadow drawdown',drawdown,
        drawdown is not None and drawdown<=MAX_DRAWDOWN_PCT,
        (f'{float(drawdown):.2f}% at fixed 1% simulated risk; maximum {MAX_DRAWDOWN_PCT:.1f}%.'
         if drawdown is not None else ''),MAX_DRAWDOWN_PCT,
    ))

    for key,label in (('fillModel','Fill challenger'),('adverseModel','Adverse-selection challenger')):
        model=execution_shadow.get(key) or {}; state=model.get('status')
        status='pass' if state=='promising' else ('fail' if state=='not_better' else 'collecting')
        gates.append(_gate(f'execution-{key}',label,status,
                           model.get('reason') or 'Execution evidence is still collecting.',state,'promising'))

    gates.append(_minimum('completed-orders','Completed live entry orders',
                          execution_quality.get('completed'),MIN_COMPLETED_ORDERS))
    gates.append(_minimum('cost-samples','Confirmed execution-cost samples',
                          execution_quality.get('costSamples'),MIN_COST_SAMPLES))
    fill_rate=execution_quality.get('fillRatePct')
    gates.append(_metric(
        'fill-rate','Live quantity fill rate',fill_rate,
        fill_rate is not None and fill_rate>=MIN_FILL_RATE_PCT,
        (f'{float(fill_rate):.1f}%; minimum {MIN_FILL_RATE_PCT:.1f}%.'
         if fill_rate is not None else ''),MIN_FILL_RATE_PCT,
    ))
    slippage=execution_quality.get('signalSlippageCents')
    gates.append(_metric(
        'slippage','Signal-to-fill price change',slippage,
        slippage is not None and slippage<=MAX_SIGNAL_SLIPPAGE_CENTS,
        (f'{float(slippage):.2f} cents; maximum {MAX_SIGNAL_SLIPPAGE_CENTS:.2f} cents.'
         if slippage is not None else ''),MAX_SIGNAL_SLIPPAGE_CENTS,
    ))
    markout=next((item for item in execution_quality.get('markouts',[])
                  if int(item.get('horizonSec') or 0)==120),None)
    markout_samples=int((markout or {}).get('samples') or 0)
    if markout_samples<MIN_MARKOUT_SAMPLES:
        gates.append(_gate('markout-120','120-second post-fill movement','collecting',
                           f'{markout_samples} samples; minimum {MIN_MARKOUT_SAMPLES}.',
                           markout_samples,MIN_MARKOUT_SAMPLES))
    else:
        average=(markout or {}).get('avgMarkoutCents')
        gates.append(_metric(
            'markout-120','120-second post-fill movement',average,
            average is not None and average>=MIN_MARKOUT_120_CENTS,
            (f'Average side-aware movement is {float(average):.2f} cents; '
             f'minimum {MIN_MARKOUT_120_CENTS:.2f} cents.' if average is not None else ''),
            MIN_MARKOUT_120_CENTS,
        ))
    blocked=sum(bool(item.get('blocked')) for item in execution_quality.get('adverseGuards',[]))
    gates.append(_gate('adverse-guards','Adverse-selection circuit breakers',
                       'pass' if blocked==0 else 'fail',
                       ('No execution group is blocked.' if blocked==0 else
                        f'{blocked} execution group(s) are currently blocked.'),blocked,0))

    collecting=any(item['status']=='collecting' for item in gates)
    failed=[item for item in gates if item['status']=='fail']
    if collecting:
        status='collecting'
        reason='Collecting the forward and live-execution evidence required for a promotion decision.'
    elif failed:
        status='rejected'
        reason='The model is not eligible because one or more completed evidence gates failed.'
    else:
        status='eligible'
        reason='All promotion gates passed. A small monitored rollout may be reviewed, but remains disabled.'
    return {
        'version':VERSION,'status':status,'reason':reason,
        'asOf':float(time.time() if asof is None else asof),
        'gates':gates,'passedGates':sum(item['status']=='pass' for item in gates),
        'totalGates':len(gates),
        'blockingReasons':[item['detail'] for item in gates if item['status']!='pass'],
        'recommendedInfluencePct':ROLLOUT_INFLUENCE_PCT if status=='eligible' else 0.0,
        'recommendedAccountRiskCapPct':ROLLOUT_ACCOUNT_RISK_CAP_PCT if status=='eligible' else 0.0,
        'activationAvailable':False,'controlsLiveTrading':False,
        'automaticRollback':[
            'Disable influence if rolling Brier or log loss no longer beats the market baseline.',
            'Disable influence if shadow drawdown exceeds 8%.',
            'Disable influence if an adverse-selection circuit breaker trips.',
        ],
    }


def load_report(network):
    import execution_learning
    import execution_shadow
    import shadow_forward
    return evaluate(
        shadow_forward.load_report(),
        execution_shadow.load_report(network),
        execution_learning.report(network),
    )
