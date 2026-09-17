# ROM Polybot 2.30.0

## Current fees and stronger ML evidence

- Prices Polymarket US trades with the exchange-wide fee schedule effective September 17, 2026 while preserving the correct rates for historical backtests.
- Requires evidence from at least 20 independent resolution days before the ML model can qualify for promotion.
- Adds day-clustered confidence floors for Brier-score improvement, log-loss improvement, and fee-adjusted shadow return.
- Prevents correlated same-day outcomes from looking like independent proof.
- Expands the Evidence workspace with independent-day counts, confidence floors, and deterministic resample details.
- Keeps the model outside live order approval, routing, and sizing.

The models remain in shadow mode and cannot change live order decisions. Improved live returns have not been demonstrated.

The Windows installer and Apple Silicon app are unsigned. Verify downloads using the published SHA-256 checksums before opening them.
