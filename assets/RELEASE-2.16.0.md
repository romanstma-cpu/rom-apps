# ROM Polybot 2.16.0

ROM Polybot 2.16.0 turns recorded practice evidence into an optional,
conservative live-sizing adjustment for the main strategy.

## Changed

- Strategy now includes **Evidence-based allocation** for Whale and Momentum
  signals. It is off by default and applies only to new live main-strategy
  entries when enabled.
- Each source must qualify in both a 30-day window and a 90-day window.
  Repeated positions from the same event are combined so correlated rows do
  not inflate the sample.
- The allocator uses the lower 10th-percentile bootstrapped return from
  practice outcomes. Missing evidence leaves sizing unchanged. Qualified weak
  evidence reduces live size to 0.25x; stronger evidence can receive up to
  1.50x.
- Existing per-position, cash-reserve, portfolio-exposure, related-outcome,
  and market-depth limits remain final ceilings after allocation.
- Practice sizing never uses the allocator, preserving an unbiased comparison
  record. The live-start review states whether evidence allocation is on.

## Verification

- 1,844 backend tests collected: 1,705 passed, 139 skipped, and 0 failed.
- All 16 Electron end-to-end suites passed against isolated profiles. The new
  suite verifies the allocation report, opt-in persistence, narrow layout, and
  that using the control does not enable live trading.
- TypeScript checks, config-boundary validation, the production build, strict
  interface audits, the frozen-backend self-test, the Windows installer build,
  and packaged Windows startup passed.
- Native Apple Silicon and Intel packages passed the frozen-backend self-test,
  packaged startup smoke test, and disk-image verification in GitHub Actions.

## Before you trade

Practice evidence is simulated and may not match live fill quality. Allocation
multipliers do not predict returns or guarantee profitability. Trading starts
paused, evidence allocation starts off, and this release has not been
validated with the publisher's live Polymarket US credentials.

The macOS builds aren't Apple-notarized. Follow
https://support.apple.com/102445 when macOS identifies the developer as
unknown. Don't bypass a damage or malware warning. Verify the downloaded DMG
against `POLYBOT-MAC-CHECKSUMS-2.16.0.txt`.
