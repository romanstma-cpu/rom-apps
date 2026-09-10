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

## 2.7 terminal refinement
Overview uses a restrained command panel, three aligned metrics and a separate activity card. Practice metrics must come from the practice ledger, with missing values shown as unknown. Mint indicates confirmed activity, not configuration alone. Respect reduced motion and visible keyboard focus.

LiveReview owns the main strategy's live-start review. Show current saved limits, focus the close control, support Escape, prevent duplicate submissions and disable confirmation immediately when connection readiness changes. Never imply limits guarantee a maximum loss or profit.

## 2.11 momentum evidence
Momentum flow is measured from bounded per-market trade windows, never from rolling 24-hour totals or scan-to-scan snapshot differences. An unavailable window is shown as warming up or stale, not as zero flow. Backtest reports window-measured momentum separately from older rows so the two are never presented as one comparable sample.

## 2.12 risk and execution honesty
MainEngine owns the related-outcome exposure cap and the peak-equity drawdown pause; both show zero as off, never as unlimited. Entry size is bounded by displayed book depth, so a quoted price must never be presented as executable for a size the book cannot support. Exits require a live quote: a missing bid holds the position and says so, and must never be described as a completed exit. Risk controls reduce the size of a bad outcome and must not be described as preventing loss or producing profit.

## 2.13 infrastructure hardening

### Schema / insert parity
Every INSERT in db.py must reference columns present in the base SCHEMA (not columns added only by the ALTER migration loop). A parser-level regression (`test_db_migration.py::TestInsertColumnParity`) asserts this across every static INSERT, catching the whole class of schema drift bugs. Six columns were found missing and fixed (interval on crypto15m_signals/ticks; yes_sub_title on alerts; script_id on bot_positions; script_id/tp_pct/sl_cents on crypto15m_positions). The ALTER loop stays for legacy upgrade.

### IPC config validation
`config:update` and `config:replace` are validated at the Electron boundary by a per-key type map (~180 keys) before reaching the store or the Python backend. Rejects: NaN/Infinity (which survive JSON to Python and re-trigger the NaN-gate bug class), wrong-typed values, invalid enum values, non-string array elements. Unknown keys are dropped silently (forward-compatible). Rules objects get shape-only checks here; deep content validation stays in the Python backend. Test: `scripts/test-config-validate.mjs`.

### NaN / Inf guard in rule sanitization
`rules.py: sanitize_rules` rejects NaN/Inf values with `math.isfinite()` before float conversion. A NaN gate would silently disable every rule that references it because `float('NaN')` is always-false in comparisons. Verified by 19 tests in `test_rules.py`.

### DB migration test
Anchored to the real 2.8 shipped schema (extracted from git at test time, SHA-guarded). Verifies: upgrade runs cleanly, new columns exist, old rows survive, idempotency. Also verifies base-SCHEMA INSERT parity (see above).

### Categorize word-boundary fix
Short bare tokens (`nfl`, `eth`, `btc`, `sol`, `do`) wrapped in `\b...\b` regex while multi-word phrases keep substring match. Fixes false positives: "inflation" no longer classified as sports, "something" no longer classified as crypto. "oscar" singular added to ENTERTAINMENT_KEYWORDS.

### Keyboard shortcuts
Ctrl+1..9 jumps to pages (Overview, Strategy, Positions, Signals, History, Crypto, Backtest, Settings, API) via a global `keydown` handler in the Shell component.

### Responsive icon-rail sidebar
Below 768px the sidebar collapses to a 56px icon strip using a `useEffect` window-width listener. The sidebar background uses the `rom.sidebar` token (extracted from hard-coded `#0E1520`).

### OnboardingModal focus trap
Native React focus trap (no library): `querySelectorAll(FOCUSABLE)` + `keydown` handler cycles Tab/Shift+Tab within the modal. Restores previous focus on unmount. Locks body scroll via `overflow: hidden` on `document.body`. ARIA: `role="dialog"`, `aria-modal="true"`, `aria-label`.

### Kill switch
Dashboard shows a "Flatten All" banner with 2-step confirmation (arm → confirm). Calls `window.rom.trading.flatten()`. Lives only on Dashboard, not duplicated on Positions where "Cancel All" already exists.

### CSV export
Trade History page has an export button that writes all resolved positions (not just the visible 200) to a CSV blob via `Blob` + `URL.createObjectURL`.

## Verification
Use isolated Electron profiles for UI checks, with mocked trading status and no real credentials or orders. Check offline, scanning, blocked, failed refresh, saved-limit gating and mode labels. Run `npm run check:e2e-drift` to detect assertion drift (literal strings in e2e tests vs. real rendered text). Run `node scripts/test-config-validate.mjs` to verify IPC config validation. Run `pytest python/tests/` to verify schema parity and all backend logic.
