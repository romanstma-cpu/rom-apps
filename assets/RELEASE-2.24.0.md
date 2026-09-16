# ROM PolyBot 2.24.0

## Safer live execution

- Shows a **degraded** price-stream state when a connected, subscribed WebSocket stops delivering data. Old stream books are never used; the app uses a fresh REST quote when available.
- Keeps the existing circuit breaker for repeated quote or order failures, with a clear status in Trade Readiness and Main Engine.
- Detects significant computer clock drift before presenting an API connection as failed.
- Paces Polymarket US requests and retries safe read requests with bounded backoff.

## Better risk and routing

- Measures drawdown from transfer-adjusted account equity so deposits and withdrawals do not look like trading profit or loss.
- Adds safety alerts for paused execution, order recovery, authentication, and drawdown conditions.
- Makes the entry spread limit and chase limit configurable, while keeping depth, fee, and risk checks in force.

No strategy can guarantee profit. Start in Practice mode and review all live-risk settings before enabling live orders.
