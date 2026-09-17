# Improve code quality plan

## Current slice: ML shadow ranker

- Status: complete
- Change point: read-only analysis of recorded main-strategy signals and settlements
- Safety boundary: the shadow model is not imported by `trader.py` and cannot approve, reject, size, or route an order
- Test point: pure chronological fitting in `python/tests/test_shadow_ranker.py`, plus the existing live-edge tests in `python/tests/test_signal_calibration.py`
- Technique: sprout module with one read-only service/UI integration seam
- Dependencies: Python standard library only
- Rollback: remove the report handler and shadow module; the existing calibration and trading paths remain intact

## Completion checks

- [x] Pin deterministic feature extraction and time-safe event joins
- [x] Pin event deduplication and unresolved-holdout behavior
- [x] Compare model metrics with untouched market-price holdout metrics
- [x] Expose a clearly labeled shadow-only Evidence report
- [x] Run focused Python tests, the full Python suite, TypeScript typecheck, and production build

## Current slice: feature recorder v2 and execution shadow models

- Status: complete
- Change point: candidate evidence snapshots and read-only execution-quality analysis
- Safety boundary: no new output is imported by `trader.py` or `execution_learning.py`
- Test point: `python/tests/test_feature_recorder_v2.py` and `python/tests/test_execution_shadow.py`
- Dependencies: Python standard library only

## Completion checks

- [x] Freeze BBO, three-level depth, imbalance, microprice, quote age, and liquidity context
- [x] Store the same feature schema beside confirmed live entry attempts
- [x] Evaluate fill and 120-second adverse-movement models chronologically
- [x] Expose a shadow-only execution-model report in Evidence
- [x] Run focused and full verification plus frozen-backend self-test

## Current slice: precommitted forward validation

- Status: complete
- Change point: append-only shadow predictions and later settlement scoring
- Safety boundary: predictions are read-only research evidence and remain outside `trader.py`
- Test point: `python/tests/test_shadow_forward.py`
- Dependencies: Python standard library only

## Completion checks

- [x] Freeze model and market probabilities before settlement
- [x] Deduplicate to the first prediction per event and model version
- [x] Reject settlements that precede the prediction or occur after the report cutoff
- [x] Compare forward Brier score and log loss with the market baseline
- [x] Show the forward scorecard in Evidence and verify the packaged backend
