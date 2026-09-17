# ROM PolyBot 2.29.0

## Machine-learning evidence lab

- Records versioned pre-trade market features, including spread, depth, imbalance, microprice, quote age, and signal context.
- Adds a leakage-resistant shadow ranker with chronological holdout, an embargo, event deduplication, regularization, and conservative probability shrinkage.
- Adds shadow execution models for fill probability and 120-second adverse selection.
- Adds an append-only forward prediction ledger that scores only later-settled outcomes against the market baseline.
- Shows model readiness and evidence quality in the Evidence workspace.

The models run in shadow mode and cannot change live order decisions. They must earn promotion through forward evidence first. Improved live returns have not been demonstrated.

The Windows installer is unsigned. Verify it using the published SHA-256 checksum before opening it.
