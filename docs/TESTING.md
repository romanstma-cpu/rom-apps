# Testing map

## Safety net for the ML shadow ranker

| Behavior | Test point | Failure prevented |
| --- | --- | --- |
| Frozen feature extraction | `python/tests/test_shadow_ranker.py` | Mutable or invalid model inputs |
| Chronological train/test split | `python/tests/test_shadow_ranker.py` | Future outcome leakage |
| Event deduplication | `python/tests/test_shadow_ranker.py` | Correlated candidates inflating confidence |
| Minimum evidence gate | `python/tests/test_shadow_ranker.py` | Small samples presented as useful models |
| Existing live edge admission | `python/tests/test_signal_calibration.py` | Shadow output influencing live orders |

The shadow model must remain outside `python/trader.py`. Its only production
entry point is a read-only report requested from the Evidence screen.

## Safety net for feature recorder v2 and execution challengers

| Behavior | Test point | Failure prevented |
| --- | --- | --- |
| Side-aware BBO and L2 feature math | `python/tests/test_feature_recorder_v2.py` | Incorrect spread, imbalance, depth, or microprice evidence |
| Missing-book handling | `python/tests/test_feature_recorder_v2.py` | Invented liquidity entering a model |
| Durable order feature snapshot | `python/tests/test_feature_recorder_v2.py` | Fill labels losing their point-in-time inputs |
| Chronological fill evaluation | `python/tests/test_execution_shadow.py` | Training outcomes leaking into later evaluation |
| Chronological adverse-markout evaluation | `python/tests/test_execution_shadow.py` | Toxic-fill labels influencing their own prediction |
| Existing order and risk behavior | `python/tests/test_engine_integration.py` and full suite | Shadow analysis altering production trading |

## Safety net for precommitted forward validation

| Behavior | Test point | Failure prevented |
| --- | --- | --- |
| First prediction remains immutable | `python/tests/test_shadow_forward.py` | Later retraining rewriting history |
| Settlement must follow prediction | `python/tests/test_shadow_forward.py` | Outcome leakage |
| Report cutoff is respected | `python/tests/test_shadow_forward.py` | Future information entering a past report |
| Market baseline uses identical observations | `python/tests/test_shadow_forward.py` | Biased model-versus-market comparison |
| Same-day markets form one evidence cluster | `python/tests/test_shadow_forward.py` | Correlated resolutions overstating confidence |
| Cluster bootstrap is deterministic | `python/tests/test_shadow_forward.py` | Promotion changing between identical report loads |

## Safety net for the ML promotion gate

| Behavior | Test point | Failure prevented |
| --- | --- | --- |
| Incomplete evidence remains collecting | `python/tests/test_ml_promotion.py` | Early results unlocking model influence |
| Completed weak evidence is rejected | `python/tests/test_ml_promotion.py` | Accuracy or return failures being hidden by sample size |
| Execution circuit breakers veto promotion | `python/tests/test_ml_promotion.py` | A statistically useful model overriding toxic fills |
| Eligible rollout remains locked | `python/tests/test_ml_promotion.py` | Promotion status changing live orders automatically |
| Fee-adjusted return and fixed-risk drawdown | `python/tests/test_shadow_forward.py` | Accuracy gains being mistaken for tradable profit |
| Positive point scores require positive clustered bounds | `python/tests/test_ml_promotion.py` | Noisy apparent wins passing promotion |
| Dated fee boundaries | `python/tests/test_fees_us.py` and `python/tests/test_backtest_units.py` | Live and historical costs using a stale exchange schedule |

Promotion requires every forward-performance and execution-quality gate. The
report can recommend a capped review, but it must remain outside
`python/trader.py` until a separately reviewed activation change is made.
