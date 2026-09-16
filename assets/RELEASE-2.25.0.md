# ROM PolyBot 2.25.0

ROM Polybot 2.25.0 adds a qualified-edge safety gate for live main-strategy orders.

- Live Whale and Momentum entries require a recent signal group that passed chronological holdout accuracy and after-cost return checks.
- The gate applies to percent, fixed-contract, and Kelly sizing.
- Practice continues collecting otherwise eligible candidates so evidence can grow while live entries wait.
- Qualified candidates are ranked by conservative after-cost edge.
- Evidence and Strategy screens explain the live-entry requirement and current qualification progress.

This release does not claim guaranteed or improved returns. Signal groups can stop qualifying when evidence becomes stale or market behavior changes. Existing position limits, exposure limits, cash reserve, execution checks, and emergency controls still apply.

The Windows installer is unsigned and the Apple Silicon installer is not Apple-notarized. Verify downloads against the published SHA-256 files.
