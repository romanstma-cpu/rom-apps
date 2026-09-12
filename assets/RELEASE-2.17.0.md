# ROM Polybot 2.17.0

This release adds execution feedback for live main-strategy entries.

## Changes

- The Evidence page shows confirmed fill quantity, recorded submission timing,
  signal-to-fill price changes, and fees per contract over the last 30 days.
- New entries record their signal price and submission quote alongside the
  durable order journal. Repeated exchange updates do not duplicate fills.
- Entry margins now include the fee reserve. With sufficient live evidence,
  higher observed fees can reduce order size or prevent an entry. Kelly's
  existing fee allowance is not charged twice.
- Consistently poor fills can pause a market/source/route/price group after
  at least 20 completed orders across 10 days. Evidence expires after 30 days.
  Open, uncertain and rejected submissions do not count as completed no-fills.
- Crossing/resting describes the quote at submission, not an exchange-confirmed
  maker/taker role. Order routing and position exits remain unchanged.

## Verification

- 1,724 backend tests passed; 139 skipped.
- All 17 end-to-end suites passed in isolated profiles without real orders.
- TypeScript, config validation, the 25-screen UI audit, production build,
  frozen-backend self-test and packaged Windows startup passed.
- Native Apple Silicon and Intel packages passed their frozen-backend self-test,
  packaged startup check and disk-image verification.

## Limits

Only newly instrumented live main-strategy entries build this execution record.
Practice fills are excluded. Sparse history leaves learned adjustments inactive;
the scheduled fee reserve still applies. These changes have not demonstrated
improved live profitability, and no real orders were placed for validation.

The Mac packages are not Apple-notarized. Review Apple's opening guidance at
https://support.apple.com/102445 and verify downloads using the published hashes.
