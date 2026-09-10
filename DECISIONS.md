# Decisions

Assumptions made while working without confirmation. Each entry states the
ambiguity, the choice, and why it is the safest reasonable option.

## 2026-09-10 — price the live crypto fee from the dated US schedule

`crypto15m._fee_cents` hard-coded `FEE_RATE_CRYPTO = 0.07`, an international
rate, and it gates live crypto15m entries through the net-edge calculation.
`polymarket_api` passes `fee_schedule: None`, so the fallback was always the
operative value.

Left alone in 2.8 because the error is conservative — overstating cost makes
the engine demand more edge than it needs — and correcting it makes the engine
take *more* trades, which is risk-increasing. Now corrected on request: the
coefficient comes from `fees_us` at the schedule in force, so backtests and
live agree instead of differing by a penny per contract. An explicit
`schedule` rate still overrides, for what-if analysis.

Replayed ticks carry `observedAt` into the asset dict so a backtest charges
the schedule that applied then, not today's.

## 2026-09-10 — restate old script practice P&L rather than annotate it

Practice fills settled before the US fee correction used a per-category table
charging crypto 0.07 and geopolitics nothing. Two options: mark those rows so
the UI can show which schedule each used, or recompute them.

Chose recompute. The old figures are not merely stale, they are impossible —
no Polymarket US trade was ever charged those rates, and geopolitics was never
free. A practice record exists to answer "would this script have made money?",
and a mixed record answers it two different ways at once. Entry price,
contracts, outcome and placement time all survive on the row, so the correct
figure is fully reconstructible rather than estimated.

`db._restate_shadow_pnl_on_us_fees` runs once, guarded by a key in `app_kv`,
skips unresolved and never-settled rows, leaves already-correct rows alone,
and logs how many moved. It is a rewrite of recorded history, so it is
deliberately loud rather than silent.

## 2026-09-10 — assert e2e against `WorkspaceStatus`, not `TopBar`

`paper-activity.e2e.mjs` waited for a practice-mode string that exists only in
`TopBar.tsx`, a component nothing imports. Two readings were possible: the test
was right and `TopBar` should have been wired up, or the test was stale.

Chose stale-test. `WorkspaceStatus` is the component actually rendered, is
referenced by the layout, and carries the newer copy; `TopBar` still used
labels from an earlier design. Reviving dead UI to satisfy a test would change
shipped behaviour, which is the riskier of the two.

## 2026-09-10 — delete `TopBar.tsx` rather than leave it dormant

It could have been kept in case someone intended to restore it. Deleting is
reversible through git history, whereas leaving a second, subtly different
status component invites exactly the confusion that kept a test broken for four
releases.

## 2026-09-10 — keep `db.get_previous_snapshots_bulk` for now

The 2.11 momentum rewrite removed its only caller. It is a public-looking DB
helper, so it is queued in TODO.md for a deliberate check rather than removed
alongside an unrelated change.

## 2026-09-10 — kill switch lives on Dashboard only

Positions already has "Cancel All" for open orders. Flatten (sell everything)
is the more dangerous action, so it gets a prominent persistent banner on
Dashboard while any position is open. Keeping it off Positions avoids
duplicating a destructive control in a dense toolbar.

## 2026-09-10 — word-boundary fix for categorize short tokens

"inflation" was misclassified as sports (contains "nfl"), "something" as crypto
(contains "eth"). Short bare tokens (`nfl`, `eth`, `btc`, `sol`, `do`) now use
`\b...\b` regex matching while multi-word phrases keep substring match. This
preserves backward compatibility for "NFL Sunday" style phrases while fixing
false positives in everyday English.

## 2026-09-10 — keep ALTER loop + add columns to CREATE (schema drift)

The migration ALTER loop is the app's upgrade path and stays. But a fresh
DB executes SCHEMA first, and six columns referenced by INSERTs existed
only via ALTER. Added them to the CREATE statements as well — the coupling
is now explicit in SCHEMA, satisfying both fresh installs and the migrate
path (which still ALTERs for legacy DBs).

## 2026-09-10 — NaN guard in sanitize_rules

`float("NaN")` is valid Python but always-false in all comparisons (including
`> 0`). A NaN gate would silently disable every rule that references it. The
fix rejects NaN/Inf with `math.isfinite()` before float conversion.

## 2026-09-10 — OnboardingModal focus trap (pure React, no library)

No focus-trap npm package was added. The hook uses native
`querySelectorAll(FOCUSABLE)` and `keydown` handler to cycle Tab/Shift+Tab
within the modal, restore focus on unmount, and lock body scroll. Keeps the
dependency tree flat.

## 2026-09-10 — schema/insert column drift fix

`crypto15m_signals`/`crypto15m_ticks` INSERTs referenced an `interval`
column that existed only via the ALTER migration loop, not the base SCHEMA
CREATE. Same latent drift in `alerts.yes_sub_title`,
`bot_positions.script_id`, `crypto15m_positions.script_id/tp_pct/sl_cents`.
Production masked it (init_db runs SCHEMA then ALTERs, so the column got
added), but any code path building purely from SCHEMA crashed with
'no such column'. Fixed by adding the columns to the CREATE statements;
ALTER loop kept for legacy upgrade. Added TestInsertColumnParity, a
parser-level regression that asserts every static INSERT in db.py
references only base-SCHEMA columns — this whole bug class is now caught
at the source.

## 2026-09-10 — IPC config validation at the Electron boundary

`config:update`/`config:replace` forwarded renderer values to the store
unchecked. The backend validates deeply, but a compromised/buggy renderer
could send NaN/Inf (which survive JSON to Python and re-trigger the NaN
bug class), wrong-typed values, or arbitrary nested objects. Added
`electron/system/config-validate.ts`: a per-key type map (~180 keys) with
enum/array/nullable handling; unknown keys are dropped (forward-compatible)
rather than fatal. Wired into both IPC handlers; invalid payloads throw
before reaching the store. Decision: rules objects get shape-only checks
here (array of objects), deep validation stays in the Python backend — no
logic duplication.
