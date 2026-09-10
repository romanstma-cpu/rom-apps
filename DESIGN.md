# ROM Polybot

Backtest owns portfolio evidence presentation. Reuse Card/Page, native scenario selection and existing charts. Missing book evidence shows an explanation without profit metrics. Changing a scenario invalidates previous results. Main equity includes conservatively marked open positions; cash, reservations and simulated fees remain visible. Do not describe heuristic entry scores as calibrated expected returns.

## Product direction
An approachable desktop trading terminal. Overview and Strategy prioritize reliable activity, mode selection and risk controls. Keep advanced tuning collapsed by default. Never infer execution from enabled configuration flags.

## Runtime tokens
tailwind.config.js owns colors, typography and spacing utilities: navy void #0B1019, surface #121A26, muted #A4B1C4, blue #6EA8FE, mint #40C9A2. Use existing Card, Page and button classes. Segoe UI handles labels and prose; tabular numerals handle money.

## Shared behavior

### Canonical UI Map

| Capability | Canonical owner | Source of truth | Allowed variants | Verification |
|---|---|---|---|---|
| Select/Listbox | common.tsx Select and existing native page selects | Runtime components and this document | native | Keyboard and popup checks |
| Date | MainEngine native time inputs | Saved trading offset | native | Trading-hours tests |
| Scrollbar | src/index.css | Global application stylesheet | native geometry | Electron layout checks |
| Form | API page inline validation and backend credential validator | Polymarket credential contract | API setup | Blank-field and connection checks |
| Toast | ToastProvider | Shared toast state | success/error | Public-readiness E2E |
EvidencePage owns calibration reporting through trading.calibration: loading, unavailable with retry, collecting, and qualified/not-qualified states. Keep existing Card/Page, Segoe UI, tabular numerals and runtime tokens. Historical qualification must not be styled as a profit guarantee. Show no invented percentages when data is missing. Refresh invalidates stale output and ignores results after navigation. MainEngine owns Kelly controls and explains that absent calibration blocks entries.

Native Select/Listbox popups are owned by the operating system through common.tsx and existing page selects. Native Date/time inputs in MainEngine use the operating-system editor. Locale is English/US; times follow the saved trading offset. These controls retain keyboard behavior and visible focus. Existing app scrollers remain the scroll owners.
StrategyActivityProvider owns main-strategy activity across Overview, sidebar, header and Strategy. Five-second polling, eight-second timeout, stale activity loses its active appearance. Backend status overrides configured mode. Scanning requires a recent decision cycle.

RiskLimits owns the saved/draft/conflict workflow. Start controls must block unsaved limits, missing connection and unavailable engine status. Pause stays available when enabled. MainEngine owns the single pair of mode actions; advanced tuning must not add alternate start paths. Existing ToastProvider owns errors and successful changes.

## Verification
Use isolated Electron profiles for UI checks, with mocked trading status and no real credentials or orders. Check offline, scanning, blocked, failed refresh, saved-limit gating and mode labels.

## 2.7 terminal refinement
Overview uses a restrained command panel, three aligned metrics and a separate activity card. Practice metrics must come from the practice ledger, with missing values shown as unknown. Mint indicates confirmed activity, not configuration alone. Respect reduced motion and visible keyboard focus.

LiveReview owns the main strategy's live-start review. Show current saved limits, focus the close control, support Escape, prevent duplicate submissions and disable confirmation immediately when connection readiness changes. Never imply limits guarantee a maximum loss or profit.

## 2.11 momentum evidence
Momentum flow is measured from bounded per-market trade windows, never from rolling 24-hour totals or scan-to-scan snapshot differences. An unavailable window is shown as warming up or stale, not as zero flow. Backtest reports window-measured momentum separately from older rows so the two are never presented as one comparable sample.

## 2.12 risk and execution honesty
MainEngine owns the related-outcome exposure cap and the peak-equity drawdown pause; both show zero as off, never as unlimited. Entry size is bounded by displayed book depth, so a quoted price must never be presented as executable for a size the book cannot support. Exits require a live quote: a missing bid holds the position and says so, and must never be described as a completed exit. Risk controls reduce the size of a bad outcome and must not be described as preventing loss or producing profit.
