# ROM Polybot — session progress

## Current state (2026-09-10)
- **Python:** 1337 pass, 139 skipped
- **E2E:** 23/23 pass (all 9 suites green)
- **Typecheck:** clean
- **Branch:** main
- **Latest commit:** 03c9513 (replay core tests)

## Session accomplishments

### Security
- New `electron/system/config-validate.ts`: per-key type validation for all
  ~180 TraderConfig keys; wired into config:update/config:replace IPC.
  Rejects NaN/Infinity, wrong-typed values, invalid enums, bad arrays.
  Unknown keys dropped (forward-compatible). Test: scripts/test-config-validate.mjs.

### Critical bug fixed (would have crashed crypto15m pipeline on schema-only builds)
`crypto15m_signals`/`crypto15m_ticks` INSERTs referenced `interval` which
existed only via ALTER, not base SCHEMA. Same for 4 more columns across 3
tables. Added to CREATE; parser-level TestInsertColumnParity regression
guards the whole class.

### Test coverage (new this session)
- `test_replay_core.py` (19): simulation math — side selection, gates,
  exec-ask fallback, equity/drawdown, bucketing, window semantics
- `test_db_migration.py` (10): 2.8→current upgrade, INSERT column parity
- `test_rules.py` (19): NaN/Inf sanitize guard
- `test_categorize.py` (29): word-boundary + oscar singular (3 bugs found)

### UX / Accessibility / Docs
- OnboardingModal focus trap (Tab cycle, body scroll lock, ARIA)
- Sidebar `bg-[#0E1520]` → `rom.sidebar` token (dark-mode audit)
- DESIGN.md refreshed through 2.13 infra hardening
- Kill switch, CSV export, Ctrl+1..9 shortcuts (earlier in session)

## Left to do
- Focus trap for remaining modals (Settings/Accounts if full-screen)
- Consider ditching `volume_farm.py` TEMP tool or documenting it
