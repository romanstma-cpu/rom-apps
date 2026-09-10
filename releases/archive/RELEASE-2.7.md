# ROM Polybot 2.7

- Refined terminal overview with a clearer setup path, aligned account metrics and mode-aware practice balances.
- Added an in-app live-start review showing saved risk limits, keyboard navigation and connection-loss protection.
- Reject signals that expire while waiting for execution data, and reject entry quotes older than five seconds after retrieval begins.
- Include the simulated execution-cost allowance when sizing practice entries and checking minimum order sizes against the position budget.

Execution safeguards do not establish a profitable strategy. The local trade ledger had no completed trade sample for evaluating returns. Live authenticated trading remains unverified. Practice results are simulations and can differ from actual fills and fees.

Windows installer is unsigned. Verify its SHA-256 checksum before installation. New installations start with live trading disabled.
