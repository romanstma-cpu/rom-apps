# Upgrade 4: momentum timing and trade windows

Momentum previously inferred pressure from two inputs that cannot distinguish fresh trading from old activity. Volume spikes compared consecutive rolling 24-hour totals, so a scan-to-scan difference reflected whenever the scanner last ran rather than a measured interval. Trade clusters read the latest 1,000 trades across all subscribed markets with no time cutoff: on a busy market that is seconds of history, on a quiet one it can include hours-old prints. A signal's creation time could therefore look fresh while the trades beneath it were stale.

Both inputs are replaced by `python/momentum_window.py`, a bounded per-market tape of deduplicated trade receipts fed by the authenticated US market stream.

## Measurement

Each receipt carries exchange event time and local receive time separately. A trade enters the tape only when its exchange timestamp is within 30 seconds of receipt, so backfilled or delayed prints cannot register as current pressure. Trade identity is a stable payload fingerprint, so reconnect replays are counted once.

A market reports flow only after 300 seconds of continuous observation and only while a trade has arrived in the last 30 seconds. Direction requires a majority of both trade count and dollar flow, plus at least 65% of window dollars on one side; a balanced tape reports no direction rather than defaulting to the price move. The volume ratio compares the current window against the preceding one and is reported only when a full prior window exists and its baseline exceeds $50. Price change requires a baseline print within 60 seconds of the prior window edge.

Absent inputs are treated as unavailable, not as zero: no ratio means no volume-spike signal, and no baseline print means no price-move signal. Stream disconnects, wall-clock rollback and tape overflow all reset the horizon, and a market whose receipts age out loses its window start so a coverage gap restarts warm-up instead of passing as continuous observation.

## Scanner and evidence

`scan_momentum` no longer reads snapshot differences or the cross-market trade list. It summarizes the tape per market and skips markets whose window is not ready, logging the aggregate reasons. Existing thresholds, category gates, the contrarian filter and the alert cooldown are unchanged, so this narrows which signals qualify rather than widening entry.

Alerts record `score_version`, the window trade count, window dollars and the observed trade time. Calibration buckets include that version, so window-measured momentum can never pool with rows scored from 24-hour totals; legacy evidence stays in its own group and does not qualify Kelly sizing through the new measurement. Backtest reports the windowed subset separately when older rows are present.

Whale scanning, trade persistence and the durable trade history are unchanged — the stream call still runs so other features keep their data.

## Validation

1,047 Python tests pass, including 17 new cases covering stale and future-dated prints, duplicate receipts after reconnect, per-market isolation, warm-up, staleness, dominance thresholds, absent ratio and baseline, clock rollback, coverage gaps, overflow and the calibration split. TypeScript checking and the production build pass. An end-to-end check drives the real `us_market_stream.ingest` normalizer into the tape so a payload schema drift cannot pass silently, and a database check verifies the `alerts` migration and collection SQL on a restored database.

No profitability improvement is claimed. This upgrade removes a source of false signals and makes momentum evidence comparable; it does not establish an edge. Because the measurement changed, previously collected momentum rows are not comparable to new ones, and forward collection must rebuild the sample before any momentum bucket can qualify. Keep collection running without enabling live trading, then compare frozen settings across base, delayed and stress portfolio replay.
