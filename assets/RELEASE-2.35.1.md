# ROM PolyBot 2.35.1

## Version and update visibility

- Settings now displays the exact version of the executable currently running.
- **Check for updates** compares that version with the latest public ROM PolyBot release.
- When an update exists, Settings links directly to the official GitHub release.
- The version panel explains that it identifies the active executable when Windows contains more than one installation.

## Large evidence stores

- The candidate-funnel report now reads a bounded signal sample and the latest runtime blocker independently.
- An overnight database with heavy market traffic can no longer overflow this Evidence report.
- Calibration continues using its existing bounded, per-evidence loader.

## Small bankroll verification

- The current engine was verified against the user's saved database with a $3.15 balance.
- New entries are blocked only below one cent; normal sizing, exchange minimums, available buying power, calibration, and account-risk controls still apply.

## Validation

- 2,003 Python tests pass.
- TypeScript checking, the strict UI audit, capacity probe, and production builds pass.
- The packaged backend passes its native dependency and signing self-test.
