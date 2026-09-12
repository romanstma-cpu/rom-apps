# ROM Polybot 2.17.1

Fixes a settings-validation mismatch that rejected supported order styles and
could prevent full saved configurations from being restored.

- Accepts the app's existing `limit_cross`, `limit_mid` and `market` price styles.
- Continues rejecting time-in-force values such as `FOK` as invalid price styles.
- Adds a regression check against the entire shipped default configuration,
  including verification that no settings are silently dropped.
- Packaged startup checks now exercise order-style updates, full configuration
  restore and invalid-value rejection while trading remains disabled.

TypeScript checks, config regression tests, the production build, frozen-backend
self-test and packaged Windows checks passed. This release does not change
strategy signals, routing implementation or risk limits.

Native Apple Silicon and Intel builds also passed backend self-tests, packaged
settings-restore and startup checks, and disk-image verification.

Includes the execution feedback introduced in 2.17.0. No live profitability claim
is made. Mac builds are not Apple-notarized; consult https://support.apple.com/102445
and verify the published checksums before installing.
