# ROM Polybot

## Product direction
An approachable desktop trading terminal. Overview and Strategy prioritize reliable activity, mode selection and risk controls. Keep advanced tuning collapsed by default. Never infer execution from enabled configuration flags.

## Runtime tokens
tailwind.config.js owns colors, typography and spacing utilities: navy void #0B1019, surface #121A26, muted #A4B1C4, blue #6EA8FE, mint #40C9A2. Use existing Card, Page and button classes. Segoe UI handles labels and prose; tabular numerals handle money.

## Shared behavior
StrategyActivityProvider owns main-strategy activity across Overview, sidebar, header and Strategy. Five-second polling, eight-second timeout, stale activity loses its active appearance. Backend status overrides configured mode. Scanning requires a recent decision cycle.

RiskLimits owns the saved/draft/conflict workflow. Start controls must block unsaved limits, missing connection and unavailable engine status. Pause stays available when enabled. MainEngine owns the single pair of mode actions; advanced tuning must not add alternate start paths. Existing ToastProvider owns errors and successful changes.

## Verification
Use isolated Electron profiles for UI checks, with mocked trading status and no real credentials or orders. Check offline, scanning, blocked, failed refresh, saved-limit gating and mode labels.

## 2.7 terminal refinement
Overview uses a restrained command panel, three aligned metrics and a separate activity card. Practice metrics must come from the practice ledger, with missing values shown as unknown. Mint indicates confirmed activity, not configuration alone. Respect reduced motion and visible keyboard focus.

LiveReview owns the main strategy's live-start review. Show current saved limits, focus the close control, support Escape, prevent duplicate submissions and disable confirmation immediately when connection readiness changes. Never imply limits guarantee a maximum loss or profit.
