# ROM Polybot 2.28.0

ROM Polybot 2.28.0 completes a production-hardening pass without loosening
trading or risk rules.

- Execution and market-data requests have separate capacity lanes.
- Trade Readiness now includes database, disk, stream, circuit and API health.
- Critical readiness failures prevent live mode from starting.
- Trace IDs connect RPC and strategy-cycle logs during diagnosis.
- The watchdog recovers even when dependency cleanup stalls.
- Public builds must pass the complete test suite, a 3× peak-capacity probe,
  packaged backend self-tests and platform-specific launch checks.

Trading starts paused. Use Practice first and review your limits and evidence
before enabling live orders. Improved live returns have not been demonstrated.
