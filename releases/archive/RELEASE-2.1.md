# ROM Polybot 2.1

The default workspace now focuses on Overview, Strategy, Positions, History and API connection. Specialist tools and detailed analytics remain available under Advanced tools. The strategy screen leads with position, portfolio and cash limits; presets and detailed parameters are collapsed until requested. Unconnected accounts display unavailable values instead of simulated performance.

## Main strategy execution

- Require a current two-sided quote; no fallback to the signal price after a quote error.
- Reject invalid, non-finite or crossed quotes, spreads above 3 cents, and asks more than 2 cents above the original signal.
- Crossing orders use the current ask instead of automatically paying an extra offset. The legacy market style also receives a bounded entry limit.
- Reduce the signal margin by adverse price movement and a 1-cent uncertainty buffer before testing eligibility and sizing the position. A cheaper quote does not inflate conviction.
- Existing account, cash, concentration and daily risk limits still apply.

These conservative constants are execution limits, not optimized or empirically validated parameters. The uncertainty buffer is not a fee schedule. Signal confidence remains heuristic and is not a calibrated probability. These changes do not establish a profitable strategy. Historical signal backtests do not contain the executable quote snapshots needed to reproduce the new execution checks; only forward observation can establish the impact on realized returns. Crypto and custom-script engines retain their separate execution paths.
