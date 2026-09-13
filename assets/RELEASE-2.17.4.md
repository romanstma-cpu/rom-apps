# ROM Polybot 2.17.4

Improves accounting while an entry-order cancellation awaits confirmation.

- Newly confirmed whole-contract fills update the position quantity, average
  price, fees and cost immediately, even while cancellation remains pending.
- The order retains its recovery status. Recording a fill does not imply that
  the remaining quantity was canceled or permit new entries.
- Incomplete accounting, fractional fills and quantities above the order size
  retain an accounting block and the existing reservation. Cancellation-pending
  status no longer overrides that accounting protection.
- Repeated updates do not duplicate fills, and older snapshots cannot reduce
  the confirmed quantity. Positions with recorded exits keep their existing
  protection against entry snapshots restoring sold quantities.

Verification: 1,737 backend tests passed and 139 skipped, including additional
fills during cancellation, idempotent updates and incomplete accounting.
All exchange responses in these tests were mocked; no real orders were placed.

Windows and both native Mac packages passed backend self-tests and packaged
startup/settings checks. The Mac disk images passed native verification.

Mac builds are not Apple-notarized. Review https://support.apple.com/102445 and
verify the published checksums before installing. No claim of improved live
profitability is made.
