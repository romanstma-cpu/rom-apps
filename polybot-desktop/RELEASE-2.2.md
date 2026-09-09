# ROM Polybot 2.2

Risk limits now use an explicit Save/Discard workflow. A risk-limit draft cannot start the main engine until saved or discarded. Conflicting updates are detected instead of silently overwriting newer values. The daily loss stop is available with the other essential limits.

The new Evidence page summarizes completed, filled main-strategy trades from the application's loaded 500-position history. It reports recorded P&L, average result, realized drawdown, event counts and profit factor. It excludes simulated orders, unfilled orders, open positions and invalid records. It does not claim lifetime account coverage, exchange reconciliation or future profitability.

Historical simulation opens on the main strategy by default. Changing the strategy or time window clears the old result and invalidates outstanding responses, preventing mislabeled results.

The 2.1 main-strategy quote controls remain in place. Signal confidence is still heuristic, and historical simulations do not recreate live quote checks or actual fills. These improvements do not establish a profitable trading strategy.
