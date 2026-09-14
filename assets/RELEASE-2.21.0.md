# ROM PolyBot 2.21.0

## Safer live sizing

- Whale and Momentum sources now begin at 25% live size until they have a settled, independent practice record across both the recent and longer evidence windows.
- A source with a non-positive conservative settled-practice result remains at 25% size. Qualified positive evidence restores normal size; the optional Evidence Allocation setting can still promote it above normal size.

## Better execution fit

- Qualifying live entries now receive a market-quality adjustment based on observable spread, movement since signal, estimated execution fees, and displayed depth.
- The adjustment only reduces size on weaker but still valid books. Existing quote, depth, fee, exposure, and loss-limit protections remain in force.

These controls are execution and risk-management safeguards. They do not predict returns or guarantee profitability.