# ROM Polybot 2.17.3

Fixes entry-order expiry after a partial fill. Previously, automatic expiry only
canceled orders with zero fills, leaving a partially filled order's remaining
quantity resting beyond the configured deadline.

Expiry now requests cancellation when an open journaled entry has any unfilled
quantity. Confirmed fills remain in the position. If an order finishes filling
during cancellation, exchange evidence determines the final quantity and cost.
An unconfirmed cancellation stays pending with funds reserved.

The configured expiry duration is unchanged. Disabling expiry still disables
automatic expiry, and orders before their deadline remain open.

Verification: 1,731 backend tests passed and 139 skipped, including cancellation
races, unconfirmed cancellation, disabled expiry and not-yet-expired orders.
The Windows production build, backend self-test and packaged startup passed.
Tests used mocked exchange responses; no real orders were placed.

Native Apple Silicon and Intel packages also passed backend self-tests,
packaged startup/settings checks and disk-image verification.

Mac builds are not Apple-notarized. Review https://support.apple.com/102445 and
verify the published checksums before installing. This fix is not evidence of
improved live profitability.
