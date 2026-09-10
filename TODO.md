# ROM Polybot — backlog

Prioritized per the autonomous operating rules: bugs and failing tests first,
then missing tests, performance, security, accessibility, UX, refactors, docs.

Rules for this file: one line per task, newest priority at the top of its
section. Move finished items to PROGRESS.md rather than deleting them.

## In progress

- [ ] Optimize `main_recorder.py` prune query to use covering index `(at, id)`
- [ ] Optimize `scanner.py` momentum scanner to only evaluate markets with active tape entries

## 1. Bugs and failing tests

- [x] `e2e/paper-activity.e2e.mjs` failing since 2.8 on stale UI strings
- [x] Audit remaining e2e specs for assertions that no longer match shipped UI
      (added `npm run check:e2e-drift`; 49 locators checked, all valid)
- [x] `python/db.py: get_previous_snapshots_bulk` unreferenced — removed

## 2. Missing tests

- [x] Config parity test added (`test_config_parity.py`). Verified 166 keys
      across backend, electron settings-store, and shared types.
- [x] `account_risk.group_key` covered for absent markets, null/blank series,
      and bounded budget under missing metadata
- [x] Collection-stats RPC shape covered and verified against `shared/types.ts`
      (`test_collection_stats.py`)

## 3. Performance

- [ ] `main_replay_events` prune query: use `ORDER BY at DESC, id DESC` to utilize covering index `main_replay_time`
- [ ] `scan_momentum`: avoid scanning all DB markets if tape has no fresh trades for them

## 4. Security

- [ ] Confirm no credential or secret can reach a log line at INFO/WARN
- [ ] `script_sandbox` review: verify the runaway guard bounds CPU/memory

## 5. Accessibility

- [ ] Audit icon-only buttons across pages to ensure `aria-label` or `title` is present
- [ ] Verify focus-visible outline on newly added form inputs

## 6. UX/UI

- [ ] Surface account-wide drawdown pause state in `WorkspaceStatus` when entries are blocked
- [ ] Group related-outcome exposure and drawdown pause controls cleanly in Strategy settings

## 7. Refactor

- [x] Remove dead `src/components/TopBar.tsx` (duplicate of WorkspaceStatus)
- [ ] Refactor `trader.py: execute_signal` sizing/depth check into modular helper

## 8. Docs

- [ ] Update README.md with 2.11/2.12 features (momentum windows, account risk, entry depth, exit discipline)
- [ ] Backfill DECISIONS.md with recent architectural choices
