# Upgrade 3: evidence-backed signal calibration

The main scanner's confidence value is a heuristic score, not a measured probability. Previously Kelly sizing subtracted market price from that score and treated the result as an expected edge. Main execution now requires a qualified calibration bucket before using Kelly, in both practice and live mode. Missing data, unsupported groups, failures, stale models and future-dated models block the entry. Existing percent and contract modes retain their heuristic gates and sizing; they are not represented as calibrated.

## Model and validation

`python/signal_calibration.py` uses only recorded signal, market and observed settlement evidence. It takes the first fresh signal per event identifier, before looking for its outcome. Missing event identifiers and non-binary settlements are excluded. NO outcomes and whale/momentum price conventions are handled explicitly.

Fixed groups: source, side, category, 20-cent price band and heuristic margin above/below five points. Estimate each probability from training event wins with 20 pseudo-observations at the training mean market price. The conservative estimate is the smaller of that estimate and a Wilson 95% lower endpoint on actual training events.

Chronological 70/30 split; whole events stay together. Training settlements must have been observed at least one day before the first test signal. A group needs at least 60 training and 40 later test events, a 14-day observation span, and test outcomes within 30 days. It must beat the market-price baseline by at least 0.005 Brier score, beat its log loss, not underperform raw-score Brier, and have positive mean paired Brier improvement after a 1.96 standard-error haircut. No refit on the test outcomes. The estimator is evaluated as of a supplied time; replay cannot train on future evidence.

These thresholds are conservative engineering gates, not a formal guarantee: events can remain dependent, bucket selection involves multiple comparisons, and sampling/market drift can bias results. Event IDs reduce repeated-signal inflation but do not establish statistical independence. Reliability statistics describe probabilities, not executable returns. Further information: https://scikit-learn.org/stable/modules/calibration.html .

## Execution

The split is selected from all observed event candidates older than one day, including unresolved candidates. A bucket cannot qualify while any event in its holdout cohort remains unresolved. This prevents dropping slower-settling losses from the evaluation sample.

Kelly uses the conservative probability minus the fee-reserved entry cost and a further one-cent uncertainty haircut. Existing entry-score filters still apply, so calibration cannot bypass an earlier rejection. Reservations, size ceilings, hard caps and all existing risk gates remain in force. The minimum-size floor no longer increases a small Kelly recommendation. Models are cached for five minutes per database; entries reject models older than ten minutes. No new strategy is enabled and no credentials or orders are used by fitting.

The Evidence screen shows sample counts and whether any groups qualify. It supports loading, empty/collecting, failed requests with retry and qualified states. A qualified group does not imply all signals qualify. MainEngine's Kelly explanation and controls match the new behavior. Legacy CLI signal-only studies remain research tools and do not implement this execution gate; use the main recorded-book replay for Kelly evaluation.

## Forward evaluation

Validation: 1,030 Python tests pass, including synthetic calibration, event deduplication, missing holdout outcomes, chronological leakage, NO contracts, fee-adjusted margins and blocked Kelly entries. TypeScript checking, production packaging, frozen-backend selftest, strict UI audit and Electron tests pass. The packaged-app calibration check covers the real RPC plus loading, empty, failure/retry, keyboard and a 1000px viewport. Existing public-readiness and portfolio replay checks still pass. The UI audit also prompted small fixes for accessible blank API-field validation and standards-based scrollbars.

The local recorder currently has zero settled event samples: no group qualifies and no profitability claim can be made. Version 2.10.0 is installed locally; the public website download remains 2.8.0. Installer SHA-256: `B2F1EFE8EF1EEE0E7278928444B0A1F328398E5357A50CFBE9A9C6881186B704`.

Keep collection running without enabling live trading. Review per-group train/test counts, Brier comparisons and observed holdout rates from `signal_calibration.load_model()['report']`. Do not relax the sample thresholds to force a result. Compare frozen settings in base/delayed/stress portfolio replay; exclude model-training events from performance claims. Follow with a later forward paper period before considering live use. No increase in profitability is claimed from synthetic tests.
