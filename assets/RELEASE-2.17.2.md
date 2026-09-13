# ROM Polybot 2.17.2

Execution feedback now filters orders in the database instead of loading every
order from the last 30 days for each candidate. New indexes select the relevant
market, source and route. The Evidence report still covers the full period.

The fee and poor-fill thresholds are unchanged. Regression tests verify matching
results, price-range boundaries, and preservation of existing orders when the
indexes are added. Equal timestamps now have a deterministic order.

In a local, in-memory synthetic test with 20,000 orders and 20 matches, the median
read took about 0.1 ms versus 85 ms for the full-history read. This measures the
database step only; it does not establish faster exchange execution or returns.

Backend validation: 1,726 tests passed and 139 skipped. The focused execution
tests also passed after the final ordering change.

Windows, Apple Silicon and Intel packages passed backend self-tests and packaged
startup/settings checks. Both Mac disk images passed native verification.

No real orders were placed for testing. Mac builds are not Apple-notarized;
review https://support.apple.com/102445 and verify the published checksums.
