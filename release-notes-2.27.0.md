# ROM Polybot 2.27.0

## Entry last-look protection

- Fetches a fresh market quote immediately before every live main-strategy order.
- Cancels an entry when the required price worsened after sizing.
- Cancels a crossing entry when the displayed liquidity needed for its size disappeared.
- Accepts price improvement without raising the original order limit.
- Records the freshest bid and ask with the execution evidence.

This release reduces stale-price and vanished-liquidity entry risk. It does not guarantee fills or improved returns. Existing edge qualification, position sizing, exposure limits, and circuit breakers remain in force.

The Windows installer is unsigned and the Apple Silicon installer is not Apple-notarized. Verify downloads against the published SHA-256 files.
