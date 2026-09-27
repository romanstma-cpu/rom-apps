# ROM PolyBot 2.35.0

## Trade-frequency diagnosis

- Adds an event-deduplicated candidate funnel to the Evidence screen.
- Shows how many recorded Large Trade and Momentum candidates cleared the signal gate.
- Groups rejected candidates by confidence, edge, category, resolution horizon, entry price, signal type, data quality, and custom rules.
- Shows the latest engine-wide blocker, including missing qualified calibration evidence, account-risk stops, unavailable balances, and recovery pauses.
- Keeps the report observational: it cannot lower a threshold, size a position, or place an order.

Repeated scans of the same event count once per signal source, preventing a busy market from inflating the apparent sample. Existing live admission, calibration, position-sizing, risk, and execution behavior are unchanged.

## Validation

- 2,002 Python tests pass.
- TypeScript type checking passes.
- Strict UI audit and Electron locator-drift checks pass.
- Capacity probe and production builds pass.
