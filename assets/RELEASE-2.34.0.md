Micro-bankroll trading update

- Supports live percent sizing with balances below $5 by reserving the actual fee-adjusted cost of one whole contract.
- A $4 bankroll can place a one-contract order when it fits the user’s cash reserve, exposure, hard cap, market depth, and the market’s minimum quantity.
- Removes the arbitrary $5 minimum from portfolio replay.
- Practice bankrolls now support values down to $0.50 for realistic low-balance testing.
- Clarifies the automatic small-balance behavior in the sizing UI.

This does not force an order that violates an exchange minimum or a saved risk limit. Validated by the complete release gate and packaged-backend self-test.
