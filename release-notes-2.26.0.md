# ROM Polybot 2.26.0

## Better execution evidence

- Records side-aware post-fill price movement at 30, 120, and 300 seconds after confirmed live main-strategy fills.
- Adds an adverse-selection guard for comparable Whale and Momentum entries. It can pause new entries only after 30 independent market-day observations across at least 10 days and 8 markets show a clearly unfavorable 120-second result.
- Extreme post-fill moves are clipped for the confidence calculation, and repeated fills in the same market on one day count as one observation.
- The Evidence screen now shows post-fill movement and the collection or pause state for every guard cohort.

The guard never enlarges an order or bypasses existing safety controls. It cannot establish future profitability. Start in Practice mode, review the Evidence screen, and use only capital you can afford to lose.

The Windows installer is unsigned and the Apple Silicon installer is not Apple-notarized. Verify downloads against the published SHA-256 files.
