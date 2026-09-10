# ROM Polybot 2.3

The main strategy defers a market when otherwise eligible signals in the same scan disagree on direction. Signals that fail the configured filters cannot veto an eligible signal. This is an abstention rule, not a learned forecast or a guarantee of better returns.

New entries stop after a failed balance refresh, including a failure between candidates. Cached balance values remain available for display but cannot authorize the next entry.

Market minimums cannot increase an order above the strategy's selected size. Invalid prices, directions and confidence values are rejected before ranking, rule evaluation and execution.

The Strategy page explains these checks in a collapsed section. Existing quote checks, saved settings and manual trading controls are preserved. Changes apply to the main strategy; Crypto, Copy and Scripts have separate engines.

Validation uses synthetic signals and isolated test databases, not live orders. Profitability has not been established; heuristic confidence is not a calibrated probability.
