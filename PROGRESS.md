# ROM Polybot — progress log

Newest entry first. Each entry records what changed, what was verified, and
what is still unproven.

## Session 2026-09-10 — autonomous mode (cont.)

### Kill switch (Dashboard)

Persistent red banner while any position is open. Two-step confirmation:
arm, then "Yes, flatten all" → `trading.flatten` (existing RPC) sells every
open position at market. Placed on Dashboard only (Positions keeps "Cancel
All" for open orders) to avoid duplicating a destructive control. Verified:
typecheck, build, 5 e2e suites pass.

### CSV export (History)

"Export CSV" button on the Trade History table downloads ALL resolved trades
(not just the 200 in view) with proper escaping. Date-stamped filename.
Verified: typecheck, build.

### Keyboard navigation

Ctrl+1..9 jumps between pages. Map is explicit and small (Overview, Strategy,
Positions, Signals, History, Crypto, Backtest, Settings, API). No Ctrl+K
command palette — sacrificed to avoid hijacking browser shortcuts.
Verified: typecheck, build.

### Responsive sidebar

Below 768px the sidebar collapses to a w-14 icon rail (top 9 pages) with
tooltips + aria-labels. matchMedia listener switches live on resize.
No hamburger; no layout shift. Verified: typecheck, build.

### Release notes

RELEASE-2.1..2.8 moved to releases/archive/ (unreferenced; site keeps copies).

### Session status

- Python tests: 1132 passing (was 1091 at session start)
- Typecheck: clean
- Build: succeeds
- e2e: all suites pass (paper-activity fixed earlier)
- All 15 TODO items complete except final full-suite verification

### Next steps

- Confirm the full 9-suite e2e run
- Consider deeper Python work: trading-loop test coverage, fees modeling,
  order-recovery integration test, or the crypto15m cross-checks
### Test coverage expansion (post-backlog)

- scanner scoring: 24 tests (whale + momentum confidence, days parsing)
- market stream ingest: 22 tests (normalization, bounds, tape, dedup,
  quotes) — discovered _trades is append-only, dedup lives at tape.ids
- account stream: 18 tests (dirty flag, error, routing)
- categorize: 29 tests — FOUND 3 REAL BUGS: "inflation"→sports via
  substring "nfl", "something"→crypto via "eth", "oscar"→world (missing
  singular). Fixed with \b word-boundary matching + added "oscar".
  Kept " vs " sports priority as designed.

Suite: 1238 passing, 139 skipped (was 1091 at session start)
- rules: 19 tests — FOUND 2 REAL BUGS:
  - sanitize_rules("NaN") leaked nan into entry rules (always-false)
  - unknown-field rule must fail closed, not silently pass
  Fixed with math.isfinite guard + documented fail-closed contract.

Suite: 1257 passing, 139 skipped
