# ROM Polybot 2.20.0

## Public-launch safety update

- Live trading now requires an explicit acknowledgment of real-order and loss
  risk after the user reviews their saved limits.
- A new top-bar **Emergency stop** pauses the main strategy first and then
  requests cancellation of its pending orders. It does not liquidate existing
  holdings; exits remain a separate, reviewed action.
- First-use guidance now follows Connect API → Set limits → Run practice before
  live orders are enabled.
- The Logs page can export a sanitized support report. API keys, secret keys,
  passphrases, bearer tokens, authorization values, and Discord webhook URLs
  are redacted before the report is written. Users should still review any
  report before sharing it.

## Validation

- TypeScript type checks and production build passed.
- Public live-review, Emergency stop, and existing liquidation safety tests
  passed without live credentials or real orders.
- Full Python suite passed: 1,753 passed, 140 skipped.

## Scope

The Emergency stop controls the main whale/momentum strategy only. Separate
crypto, copy, and script engines remain separately armed and must be stopped
from their own controls.
