# ROM Polybot 2.14.4

ROM Polybot 2.14.4 tightens custom-strategy risk controls and finishes the
cross-platform interface work for Windows and macOS.

## Changed

- Custom scripts now use the account-wide related-outcome exposure cap for
  crypto, market, and signal entries. When a group has limited capacity left,
  Polybot reduces the order size; when the group is full, Polybot refuses the
  order. This control applies when **Maximum related-outcome exposure** is set
  above 0%.
- **Start at login** now works on macOS. The setting and credential-storage
  guidance use operating-system-neutral wording on Windows and Mac.
- Checkboxes and sliders meet the app's minimum interaction-size target. The
  rendered interface audit reports no undersized controls, overflow, contrast
  failures, unnamed controls, or renderer errors.

## Verification

- 1,834 backend tests collected: 1,695 passed, 139 skipped, and 0 failed.
- All 14 Electron end-to-end suites passed against isolated profiles. The
  suites didn't place live orders.
- TypeScript checks, the production build, the strict interface audit, the
  frozen-backend self-test, the Windows installer build, and packaged Windows
  startup passed.
- Native Apple Silicon and Intel packages passed the frozen-backend self-test,
  packaged startup smoke test, and disk-image verification in GitHub Actions.

## Before you trade

Start in practice mode and review your strategy and risk limits before you
enable live trading. This release has not been validated with the publisher's
live Polymarket US credentials and does not promise profitability.

The macOS builds aren't Apple-notarized. Follow
https://support.apple.com/102445 when macOS identifies the developer as
unknown. Don't bypass a damage or malware warning. Verify the downloaded DMG
against `POLYBOT-MAC-CHECKSUMS-2.14.4.txt`.
