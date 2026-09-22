# ROM PolyBot 2.35.3

- Re-validates Polymarket US credentials while the app runs and pauses live trading when the exchange rejects them.
- Stops authenticated streams while the account is disconnected instead of reconnecting endlessly.
- Bounds the live market subscription universe to the 500 markets the scanner can evaluate.
- Keeps the public market catalog refreshing so the engine can recover after reconnecting.

If the API page says **Not connected**, generate a fresh Key ID and Secret Key in the Polymarket US developer portal, then save them in ROM PolyBot.
