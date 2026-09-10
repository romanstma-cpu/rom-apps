# Upgrade 2: chronological US portfolio replay

The main Backtest now replays recorded books, candidate signals, market metadata and observed settlements in receipt-time order. The old signal-only study remains available as `replay_main_signal_study` for research, but is no longer the main backtest endpoint.

Shared live entry gates and sizing enforce spread/chase limits, signal age, trading hours, cash reserve, exposure and position/event/day caps. Simulated orders arrive after latency, consume displayed depth, retain partial fills and reserve remaining cash until cancellation acknowledgement. Open positions remain in equity and drawdown; settlement proceeds become available only when recorded.

`fees_us.py` applies the dated US schedules, with cent rounding per simulated price-level fill. Practice fills include these fees, and live order reservations allow for fee fragmentation. July 1, 2026 onward uses taker theta 0.06. Source: https://docs.polymarket.us/fees . Historical dates before the supported schedules are rejected by portfolio replay, rather than silently assigned a current fee.

Backtest offers base (250 ms, full depth), delayed (1 s, half depth) and stress (2 s, quarter depth, 1 cent adverse slippage) scenarios. Limits are never exceeded to force a simulated fill. This feature does not change the signal model or establish profitability.

## Recording and limits

Main data collection records evidence while connected. No live orders are needed. Books are sampled at most once per second per market; recording gaps invalidate cached liquidity. Storage retains up to 60 days or 500,000 events, whichever is smaller. One replay accepts at most 100,000 events; shorten the window when necessary. Old signal-only history cannot reconstruct books. Missing or stale exit depth values the unpriced remainder at zero, which can overstate drawdown. No queue priority, hidden liquidity, maker/tier rebates, API rejection probability or other engines are simulated.

## Validation and next evaluation

Build verification: 1,016 Python tests pass; TypeScript checking, production build, frozen-backend selftest and Electron public-readiness checks pass. Packaged Electron backtest verification exercises the real RPC with an empty database, then synthetic portfolio/empty-state fixtures and scenario invalidation. Installer 2.9.0 installed locally with settings SHA-256 unchanged. The public website remains on 2.8.0.

2.9 installer SHA-256: `9F1522D9BFDBEEE2F7A01ABA24B923FE77C42ACF2A7305896BD49F46615C5290`.

Automated fixtures cover hand-calculated fee-inclusive settlement P&L, duplicate settlement, partial fill/cancel, pending position caps, no look-ahead, passive non-fills, recording gaps, open-position valuation, stale depth, missing metadata and stress assumptions. Recorder tests use an isolated database. UI verification uses an isolated profile with synthetic results and no credentials.

Collect forward evidence before evaluating profitability. Freeze a baseline configuration; compare each proposed change on the same chronological data and all three scenarios. Use earlier dates for tuning and a held-out later period for evaluation. Report net portfolio return, drawdown, turnover, fees, open risk and independent settled events; inspect rejected entries and missing-depth frequency. Do not promote a change based on in-sample win rate or a small cluster of related signals. Follow with paper observation before any separately authorized live test.
