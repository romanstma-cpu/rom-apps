import inspect

import ml_promotion


def forward(**patch):
    report = {
        'resolvedPredictions': 240,
        'observationSpanDays': 35,
        'independentDays': 30,
        'forwardTrades': 110,
        'brierImprovementPct': 8.0,
        'brierImprovementLowerPct': 2.0,
        'modelLogLoss': .55,
        'marketLogLoss': .62,
        'logLossImprovementLowerPct': 1.5,
        'windowsEvaluated': 4,
        'windowsPassed': 4,
        'lowerConfidenceReturnPct': 2.5,
        'maxDrawdownPct': 4.0,
    }
    report.update(patch)
    return report


def execution_shadow(**patch):
    report = {
        'fillModel': {'status': 'promising', 'reason': 'Fill model beat baseline.'},
        'adverseModel': {'status': 'promising', 'reason': 'Adverse model beat baseline.'},
    }
    report.update(patch)
    return report


def execution_quality(**patch):
    report = {
        'completed': 60,
        'costSamples': 45,
        'fillRatePct': 78.0,
        'signalSlippageCents': .4,
        'markouts': [{'horizonSec': 120, 'samples': 45, 'avgMarkoutCents': .1}],
        'adverseGuards': [],
    }
    report.update(patch)
    return report


def test_complete_positive_evidence_is_eligible_but_cannot_activate():
    report = ml_promotion.evaluate(forward(), execution_shadow(), execution_quality(), 123)
    assert report['status'] == 'eligible'
    assert report['passedGates'] == report['totalGates']
    assert report['recommendedInfluencePct'] == 10
    assert report['recommendedAccountRiskCapPct'] == .5
    assert report['activationAvailable'] is False
    assert report['controlsLiveTrading'] is False


def test_incomplete_evidence_stays_collecting_even_if_early_metrics_are_bad():
    report = ml_promotion.evaluate(
        forward(resolvedPredictions=20, observationSpanDays=2, forwardTrades=4,
                brierImprovementPct=-20, windowsEvaluated=0, windowsPassed=0),
        execution_shadow(fillModel={'status': 'collecting', 'reason': 'More fills needed.'}),
        execution_quality(completed=3, costSamples=2, markouts=[]),
    )
    assert report['status'] == 'collecting'
    assert report['recommendedInfluencePct'] == 0
    assert any(gate['status'] == 'collecting' for gate in report['gates'])


def test_correlated_same_day_results_cannot_pass_the_promotion_gate():
    report = ml_promotion.evaluate(
        forward(independentDays=1, brierImprovementLowerPct=None,
                logLossImprovementLowerPct=None, lowerConfidenceReturnPct=None),
        execution_shadow(), execution_quality(),
    )
    assert report['status'] == 'collecting'
    collecting = {gate['id'] for gate in report['gates'] if gate['status'] == 'collecting'}
    assert {'independent-days', 'brier-confidence', 'log-loss-confidence',
            'net-return'} <= collecting


def test_negative_clustered_score_bounds_reject_an_apparent_point_win():
    report = ml_promotion.evaluate(
        forward(brierImprovementPct=8, brierImprovementLowerPct=-1,
                modelLogLoss=.55, marketLogLoss=.62,
                logLossImprovementLowerPct=-.5),
        execution_shadow(), execution_quality(),
    )
    assert report['status'] == 'rejected'
    failed = {gate['id'] for gate in report['gates'] if gate['status'] == 'fail'}
    assert {'brier-confidence', 'log-loss-confidence'} <= failed


def test_complete_but_unprofitable_evidence_is_rejected():
    report = ml_promotion.evaluate(
        forward(brierImprovementPct=1, modelLogLoss=.7, marketLogLoss=.6,
                lowerConfidenceReturnPct=-3, maxDrawdownPct=12, windowsPassed=1),
        execution_shadow(), execution_quality(),
    )
    assert report['status'] == 'rejected'
    assert report['recommendedInfluencePct'] == 0
    failed = {gate['id'] for gate in report['gates'] if gate['status'] == 'fail'}
    assert {'brier', 'log-loss', 'stability', 'net-return', 'drawdown'} <= failed


def test_execution_circuit_breaker_prevents_eligibility():
    report = ml_promotion.evaluate(
        forward(), execution_shadow(),
        execution_quality(adverseGuards=[{'blocked': True}]),
    )
    assert report['status'] == 'rejected'
    assert any(gate['id'] == 'adverse-guards' and gate['status'] == 'fail'
               for gate in report['gates'])


def test_promotion_module_has_no_live_trader_dependency():
    source = inspect.getsource(ml_promotion)
    assert 'import trader' not in source
    assert 'import order_journal' not in source
