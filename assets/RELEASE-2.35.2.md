# ROM PolyBot 2.35.2

This release repairs the Polymarket US market intake path and makes feed failures visible before live trading.

- Keeps valid tradable markets when the US reference API omits rolling-volume fields.
- Limits live WebSocket subscriptions to the 500-market scanner universe.
- Shows rejected subscriptions and empty market feeds as a blocking readiness issue.
- Preserves quote, spread, evidence, position-size, and risk controls.

Available for Windows 10/11 and Apple Silicon Macs running macOS 15 or later.
