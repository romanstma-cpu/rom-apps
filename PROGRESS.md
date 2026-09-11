# ROM Polybot — session progress

## Current state (2026-09-10, after agent fan-out wave)
- **Python:** 1535 pass, 139 skipped (+198)
- **E2E:** 23/23 pass (all 9 suites green)
- **Typecheck:** clean
- **Build:** succeeds
- **Branch:** main
- **Latest commits:** 61426ec (design+a11y), a42283b (indicator/clob/copy-trader edge tests)

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

### Source edge-case fixes (agent wave + supervisor verification)
- `indicators.py`: `_floats` rejects NaN/Inf via `math.isfinite` (was `f==f`);
  `ema_series` computes length from filtered floats, not the raw list
- `clob_ws.py`: `_best_from_levels` skips out-of-range prices (<=0 or >=1)
  and malformed price_change entries
- `copy_trader.py`: `_compute_copy_contracts` integer-cents math replaces
  float floor-division (10.0 // 0.10 == 99 off-by-one at penny prices)

### Test coverage (new this session)
- `test_replay_core.py` (19): simulation math — side selection, gates,
  exec-ask fallback, equity/drawdown, bucketing, window semantics
- `test_db_migration.py` (10): 2.8→current upgrade, INSERT column parity
- `test_rules.py` (19): NaN/Inf sanitize guard
- `test_categorize.py` (29): word-boundary + oscar singular (3 bugs found)
- `test_backtest_units.py` (47): fee schedule boundaries (0.05/0.06 theta,
  2026-07-01 switch), settlement math, epoch parsing, sizing, portfolio
  helpers — committed af06eda
- `test_indicator_edges.py` (62): ema/macd/rsi/sma/vwap/pct NaN+empty edges
- `test_clob_ws_edges.py`: parse_book/parse_price_changes malformed inputs
- `test_copy_trader_logic.py` (49): contract sizing, lifetime-loss tripping
  (USD+pct), today pnl, seen-key persistence roundtrip, bankroll fallback

### Design + accessibility (agent wave, committed 61426ec)
- `common.tsx` NameDialog: useFocusTrap (Tab cycle, body scroll lock, focus
  restore), role=dialog/aria-modal/aria-label
- `Dashboard.tsx`: kill switch checks ActionResult.ok, persistent role=status
  result, honest copy (exits depend on depth/quotes; does not pause strategy),
  disables Cancel while busy, fixes stray backslash in restart JSX
- `Overview.tsx`: latest-decision-cycle panel, API-auth indicator, mono/
  tabular metrics, responsive stack
- `MainActivity.tsx`: leading-entry-filter bars as a section
- `App.tsx`: global Ctrl+digit shortcuts skip inputs/composition/open dialogs
- `index.css`: terminal-command-detailed + responsive metrics
- `Onboarding.tsx`: "API setup" capitalization
- `DESIGN.md`: verification notes for the above

### Supervisor verification & fixes on agent output
- Repaired `test_copy_trader_logic.py` fixtures: `insert_bot_position` does
  NOT write pnl_usd/resolved; seeds now call `_seed_pnl_copy` which sets them
  via UPDATE; fixed nested-connection "database is locked" (no outer `with`
  around seed helper); corrected `_filter_new_entries` test expectation
  (new wallet baselines, not eligible — matches source design)
- Fixed 4 `test_indicator_edges.py` expectations that asserted stale
  behavior (period-1 EMA returns the value; VWAP with NaN dropped below
  window returns None, not a mean)
- Verified `ActionResult.ok` contract for Dashboard restart/flatten changes

## 2.13 release prep (external, uncommitted)
- `package.json` 2.12.0 → 2.13.0, `REVIEW-2.13.0.md`, `e2e/terminal-review.e2e.mjs`
  left uncommitted for the release flow
## 2.13.0 published (2026-09-10)
- Installer `release/ROM PolyBot-Setup-2.13.0.exe` (91.5 MB, SHA-256
  7696E9E8...) published to romapps.xyz; index.html + code-signing-policy.html
  updated; validator PASS; live checksum 200; live installer byte-identical.
- Site commit 1a8334a on rom-apps repo.

## Backlog agent wave (2nd wave, 2026-09-10)
- E2E: history-csv.e2e.mjs (Blob CSV intercept, resolved-only assert) and
  kill-switch.e2e.mjs (rejected + zero-fill honest feedback) — fixed
  selectors: Trade-history tab has count badge, Dashboard is under
  Advanced tools. Committed f02d53e.
- A11y: audited Accounts/RiskLimits — no new overlays (Accounts uses
  trapped NameDialog; RiskLimits is inline form). No change needed.
- Icon: verified resources/rom.ico is pixel-perfect from rom.png; installer
  + exe embed matching icon. No change needed.
