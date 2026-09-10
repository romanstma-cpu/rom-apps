# ROM Polybot — session progress

## Current state (2026-09-09 22:18 CDT)
- **Python:** 1318 pass, 139 skipped
- **E2E:** 23/23 pass (all 9 suites green)
- **Typecheck:** clean
- **Branch:** main
- **Latest commit:** be99c38 (schema/insert column drift fix)

## Session accomplishments

### Critical bug fixed (would have crashed crypto15m pipeline on schema-only builds)
`crypto15m_signals`/`crypto15m_ticks` INSERTs referenced `interval` which
existed only via ALTER, not base SCHEMA. Same for 4 more columns across 3
tables. Added to CREATE; parser-level TestInsertColumnParity regression
guards the whole class.

### Bug fixes (verified in test)
| Bug | Root cause | Fix |
|-----|-----------|-----|
| "inflation" classified as sports | substring `nfl` matched | `\b` word-boundary for short tokens |
| "oscar" classified as world | only plural `oscars` in keyword list | added singular `oscar` |
| "something" classified as crypto | substring `eth` matched | `\b` word-boundary for short tokens |
| sanitize_rules passes NaN gates | `float("NaN")` is always-false | `math.isfinite()` early-reject |
| Config parity: `requireEntryDepth` missing | absent from store defaults and TS type | added to both |
| Config parity: `exitPriceLossBudgetCents` missing | absent from store defaults and TS type | added to both |

### Test coverage (167 new tests)
- `test_scanner_scoring.py` (20): whale score, liquidity, purity, direction
- `test_us_market_stream.py` (22): normalization, dedup, bounds, tape
- `test_us_account_stream.py` (18): dirty flag, error, order routing
- `test_categorize.py` (29): keyword classification, edge cases
- `test_rules.py` (19): rule evaluation, sanitize, NaN/Inf
- `test_crypto15m_model.py` (42): pricing model, edge, fees, CDF
- `test_main_recorder.py` (9): age/count prune, dedup, bulk insert
- `test_db_migration.py` (6): upgrade from 2.8 schema, schema drift

### Performance
- `main_recorder.py`: indexed count-based prune (avoids full SCAN)
- `db.py`: `save_snapshots_bulk()` — single INSERT for all markets
- `scanner.py`: rewired to use bulk insert

### UX / Accessibility
- Kill switch: Dashboard "Flatten All" with 2-step confirmation
- CSV export: Trade History page export button
- Keyboard shortcuts: Ctrl+1..9 for page navigation
- Responsive sidebar: icon-rail below 768px
- Focus trap: OnboardingModal with proper Tab cycling and body scroll lock
- `aria-modal`, `role="dialog"`, `aria-label` on onboarding

### Cleanup
- Removed dead `TopBar.tsx` (111 lines, zero imports)
- Archived stale RELEASE-2.1..2.8.md to `releases/archive/`
- Config parity: 6 backend-only keys classified, 17 undeclared keys tracked

## Left to do
- `check:e2e-drift` npm script still exists (useful guard, keep)
- Consider adding focus trap to other modals (Accounts, Settings panels)
- Dark-mode audit for hard-coded hex values
- DESIGN.md refresh after feature work settles
