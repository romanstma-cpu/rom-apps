# ROM Polybot 2.27.0

ROM Polybot 2.27.0 adds entry last-look protection.

- Fetches a fresh market quote immediately before every live main-strategy submission.
- Skips an entry if its required price worsened after sizing.
- Skips a crossing entry if the displayed liquidity required for its size disappeared.
- Accepts price improvement without raising the original order limit.

This release reduces stale-price and vanished-liquidity entry risk. It does not guarantee fills or improved returns. The Windows installer is unsigned and the Apple Silicon installer is not Apple-notarized. Verify each download against its published SHA-256 file.
