# ROM Polybot 2.8

- Saves order intent before submission; uncertain responses retain their risk reservation.
- Blocks duplicate submissions and confirms cancellations against exchange order state.
- Records execution quantities, prices and fees, with reconciliation after disconnects.
- Reconciles main-strategy partial sales and late fills without counting proceeds twice.
- Missing execution prices, fees or unsupported fractional fills require recovery instead of invented accounting.
- 809 backend tests, desktop checks and the bundled-backend selftest passed. No real trades were placed.

Strategy scoring is unchanged. Profitability and live authenticated trading remain unverified. The Windows installer is unsigned.
