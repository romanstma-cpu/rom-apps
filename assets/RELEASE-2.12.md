# ROM Polybot 2.12

Four strategy upgrades, focused on removing false signals and unbounded loss modes.

**Momentum timing (2.11).** Flow is measured from bounded per-market trade windows with deduplicated receipts, warm-up and a freshness requirement. Rolling 24-hour volume differences and untimed cross-market trade lists no longer produce signals, so old prints can no longer look like fresh buying or selling pressure. An unavailable window reports as warming up or stale, never as zero flow.

**Account-wide risk.** A related-outcome exposure cap bounds markets that share a series or event, which per-event caps miss. A peak-equity high-water mark pauses new entries after a confirmed drawdown, and a partial recovery still measures against the true peak. A daily stop supported by realized, settled results now blocks immediately instead of waiting out a persistence delay. Both new limits default to off.

**Executable depth at entry.** Quotes now carry the resting size behind each price. Entry sizes against displayed depth, shrinks to what the book actually shows, skips markets that cannot support the minimum tradable size, and charges the depth-weighted cost against the signal margin before the entry test.

**Exit discipline.** Removed a 1-cent sell fallback that could dump a position whenever a bid was unavailable. Exits now require a live quote, concede at most a configured budget below the touch, and are bounded by displayed bid depth. A missing quote holds the position and says so.

1,091 backend tests, TypeScript checking, the production build, the bundled-backend selftest and six Electron UI suites passed. No real trades were placed.

Strategy scoring is otherwise unchanged, and no profitability improvement is claimed: these changes reduce loss modes and make reported execution honest. Because momentum measurement changed, previously collected momentum evidence is not comparable to new evidence and is calibrated separately. Profitability and live authenticated trading remain unverified. The Windows installer is unsigned.
