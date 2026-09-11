# ROM Polybot — session progress

## Current state (2026-09-11, public-readiness wave)
- **Python:** 1668 pass, 139 skipped
- **E2E:** 10/10 suites pass  **Typecheck:** clean  **Drift:** clean
- **Branch:** claude/polymarket-bot-orchestrator-5f788e
- **Commits:** 050b835, 2783435, aca551e, 7f859ed, 6a5a700 + copy fixes

### UI audit (050b835)
All 19 pages driven with Playwright and measured, not read. Four switches
had no accessible name — unlimited daily new positions, sell out on daily
loss, restrict trading to a weekly window, and Scripts live, the master
switch for real orders. All four came from `Field` rendering its label as a
sibling. `SwitchProps` is now a union requiring `label` or `ariaLabel`, so an
unnamed switch fails typecheck. Legibility floor was 8px in Terminal's inline
stylesheet at roughly 2.8:1; every sub-10px declaration is now 10px on a
lighter token. Onboarding led with a $50 referral in a gradient card while
"automated trading can lose money" was an unstyled paragraph and ROM's own
referral interest was the smallest text on screen; risk now leads with equal
weight.

### Order recovery is reachable from the app (2783435)
A blocking journal row halts every engine with no timeout and no forget path,
and nothing in the renderer ever called the recovery IPC. `blocked_intents()`
feeds trading status; the panel sits at the top of Overview. Its e2e seeds a
real `sending` row into the backend's own SQLite and drives the whole chain —
window.rom is frozen by contextBridge, so a renderer stub would have proven
only a mock.

### Two risk controls made honest (aca551e)
UPGRADE-5's cap read `bot_positions` alone while calling itself account-wide;
GROUP_SQL now unions `crypto15m_positions`. UPGRADE-7 promised exit size is
bounded by displayed depth, but an empty ladder fell back to the whole
position; a touch without a ladder is not evidence of size. Both changes
tighten only. Still open and recorded: crypto15m and copy_trader count toward
the cap but do not consult it.

### Livecheck stages 1-4 (7f859ed, 6a5a700)
Stage 1 checks the response fields the adapter indexes, including whether an
empty account returns `{}` or omits `positions` — the difference between
working and a 502 on every poll. Stage 2 measures the clock-skew gate that can
silently kill momentum. Stage 3 checks the ladders sizing depends on,
including the NO mirror. Stage 4 builds the real payload, proves the journal
commit precedes the POST, and stops; it borrows the interlock and hands it
back, and 7 tests pin that it cannot send, cannot leave a blocking row, and
cannot touch the real database.

### Not done, deliberately
No stage has been run against a real account — that needs credentials and is
the user's call. Stage 5 (a single live order) is unbuilt by design.

---

## Current state (2026-09-10, live-validation wave — recon + repairs)
- **Python:** 1584 pass, 139 skipped (+49)
- **Typecheck:** clean  **E2E drift:** clean (54 locators, no drift)
- **Branch:** claude/polymarket-bot-orchestrator-5f788e
- **Commits:** 017e262, 0ad3f89, 7fa91c8, 89bda3b

### The baseline was never green off this machine (017e262)
`pytest-asyncio` was hand-installed into the local venv and absent from
`requirements-dev.txt`. Without it `@pytest.mark.asyncio` is an inert unknown
mark, so async tests do not skip — they fail. 29 of them, in
`test_order_recovery.py` and `test_us_polymarket_api.py`: the order-submission
and US API adapter coverage. CI installs from that file, so CI was red on these
too. Separately `test_db_migration.py` decoded `git show` with the locale codec;
cp1252 mangles the 2.8 SCHEMA block (20098 -> 20117 chars), so the pinned digest
matched only on UTF-8 hosts. Both fixed; 1535 green on a fresh venv.

### Momentum could fail silently and completely (0ad3f89)
`momentum_window` gates receipts on `0 <= now-at <= FRESH`. The lower bound is
zero, so a local clock even fractionally behind the exchange rejects every
trade. `Tape.add` returned bare False, `us_market_stream` discards the return,
and the trade still reached `_trades`, the DB and the recorder — so every other
health signal looked normal. The only symptom was an INFO line identical to a
quiet market. Gate left unchanged on request; rejections are now counted per
reason and surfaced in scanner's existing momentum log. Counters survive
`reset()` because a reset is itself one of the explanations.

### Upgrade 5's series grouping was dead code (7fa91c8)
All three producers hardcode `markets.series_ticker = ''`, so the group always
collapsed to the event — bounding what `max_positions_per_event` already bounds.
The series lives in `events`, which `account_risk` never queried. Now resolved
through a join, in live and replay. Can only tighten; default stays inert.

### The documented recovery hatch was unreachable (89bda3b)
35-test network-free drill proves every blocking journal state clears and that a
mismatched exchange order cannot be attached. Building it revealed `runOnce`
forwarded only `action` through ipc/preload/types, while `_h_runOnce` indexes
`p['localOrderId']` — the UI path would have raised KeyError. Fixed with an
action allowlist and validated rebuild at the boundary. `docs/RECOVERY-RUNBOOK.md`
is the operator procedure.

### Recon findings not yet acted on
Auth/REST, streaming and order-path surfaces were mapped read-only. Carried into
TODO: error bodies discarded by `PolymarketAPIError`, the group cap not seeing
`crypto15m_positions`, an unbounded exit fallback when `bid_levels` is empty,
`require_entry_depth` unvalidated, and `cancel_pending` written without the
FULL-sync discipline every other pre-network journal write uses.

---

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
