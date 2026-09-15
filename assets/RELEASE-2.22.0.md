# ROM PolyBot 2.22.0

## Clearer trading workspace

- The Overview screen now presents the strategy as a readable four-stage pipeline: signals, live quote, risk checks and order routing.
- Refined navigation, responsive spacing, typography and terminal styling make the app easier to scan without adding decorative market claims.
- The Strategy page now explains real-account sizing and the separate practice balance in plain language.

## Balance-aware entries

- Polybot refreshes available funds before every scan and stops using the old $5 account floor.
- Small percent-sized accounts can allocate up to $0.50 when a whole contract fits.
- Existing cash reserve, position, portfolio, related-outcome, fee, order-book depth and exchange-minimum limits remain authoritative.

A $0.50 balance does not guarantee an eligible order. The current market price, whole-contract minimum, available depth, fees and saved risk limits must all permit it. Strategy scores are heuristics and improved returns have not been demonstrated.
