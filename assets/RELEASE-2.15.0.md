# ROM Polybot 2.15.0

ROM Polybot 2.15.0 adds an evidence-aware ranking for strategies tested in
practice mode.

## Changed

- The Evidence page now compares settled practice results for the built-in
  Whale and Momentum strategies and each custom script.
- A strategy stays visibly **Collecting** until it has at least 30 settled
  fills across 20 distinct markets and 7 observation days. Small samples do
  not receive a rank.
- Qualified strategies are ranked with recorded return on capital at risk,
  sample-size shrinkage, and realized drawdown. The screen also shows net P&L,
  win/loss counts, average P&L, and the exact evidence still needed.
- Rankings use practice records only and cannot enable or place live orders.

## Verification

- 1,838 backend tests collected: 1,699 passed, 139 skipped, and 0 failed.
- All 15 Electron end-to-end suites passed against isolated profiles. The new
  ranking suite covers qualified and collecting states at desktop and narrow
  widths. None of the suites placed live orders.
- TypeScript checks, the production build, the strict interface audit, the
  frozen-backend self-test, the Windows installer build, and packaged Windows
  startup passed.
- Native Apple Silicon and Intel packages passed the frozen-backend self-test,
  packaged startup smoke test, and disk-image verification in GitHub Actions.

## Before you trade

Practice rankings describe recorded simulated outcomes. They do not prove that
the same orders would fill live or that a strategy will remain profitable.
Trading still starts paused, and this release has not been validated with the
publisher's live Polymarket US credentials.

The macOS builds aren't Apple-notarized. Follow
https://support.apple.com/102445 when macOS identifies the developer as
unknown. Don't bypass a damage or malware warning. Verify the downloaded DMG
against `POLYBOT-MAC-CHECKSUMS-2.15.0.txt`.
