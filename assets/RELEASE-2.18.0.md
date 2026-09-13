# ROM Polybot 2.18.0

Strengthens the evidence-based Kelly strategy. Percent and contract sizing modes
retain their existing signal selection, and this release does not switch sizing
modes or enable live trading.

## Strategy changes

- Prediction accuracy alone no longer qualifies a score group. The trades that
  its training estimate would select must also pass net-return holdout checks.
- The settlement simulation charges two cents of adverse entry movement,
  conservative scheduled fees and another cent of uncertainty. It does not
  assume maker rebates or claim that a quoted order would actually fill.
- Qualification needs at least 40 selected holdout trades across seven UTC days,
  a positive lower bootstrap estimate using day blocks, and positive net P&L in
  both chronological halves. Existing training, embargo, event deduplication,
  complete-holdout, recency and prediction-quality requirements remain.
- Live Kelly scans and historical replay prioritize qualified candidates by
  conservative stressed return on capital instead of raw confidence minus price.
  Fresh quotes, depth, fees, exposure limits and sizing are still checked at entry.

The bootstrap estimate is a historical filter, not a guaranteed confidence bound
under changing or dependent markets. The simulated check assumes holding one
contract per selected event to settlement; it does not validate early exits,
portfolio drawdown or actual live fills.

## Validation

- 1,743 backend tests passed and 139 skipped.
- Tests reject gains erased by costs, recent deterioration, sparse samples,
  stale/future models and an accuracy-improving model whose selected trades lose.
- TypeScript, the production build, packaged Windows startup, calibration UI
  checks and portfolio replay UI checks passed without real orders.
- Fee assumptions were checked against https://docs.polymarket.us/fees.
- Native Apple Silicon and Intel builds passed backend self-tests, packaged
  startup/settings checks and disk-image verification.

## Before using real money

Collect main-strategy signals and subsequent settlements. Keep parameters fixed
while evaluating later periods, then compare portfolio replay across multiple
periods, including losing periods and adverse execution scenarios. Track fill
rate, net returns and drawdown in a separate forward sample before increasing size.
This release has not demonstrated improved live returns.
Kelly remains blocked for groups without qualified evidence.

Mac packages are not Apple-notarized. Review https://support.apple.com/102445 and
verify the published checksums before installing.
