# ROM Polybot — backlog

Prioritized per the autonomous operating rules: bugs and failing tests first,
then missing tests, performance, security, accessibility, UX, refactors, docs.

Rules for this file: one line per task, newest priority at the top of its
section. Move finished items to PROGRESS.md rather than deleting them.

## In progress

_(none — picked up from the top of the list below)_

## 1. Bugs and failing tests

- [x] `e2e/paper-activity.e2e.mjs` failing since 2.8 on stale UI strings
- [x] Audit remaining e2e specs for assertions that no longer match shipped UI
      (added `npm run check:e2e-drift`; 49 locators checked, all valid)
- [ ] `python/db.py: get_previous_snapshots_bulk` is now unreferenced — confirm
      no external caller, then remove with its test

## 2. Missing tests

- [ ] No test asserts the *whole* config round-trips through the electron
      settings store; a key added to Python but not `settings-store.ts` is
      silently dropped
- [x] `account_risk.group_key` covered for absent markets, null/blank series,
      and bounded budget under missing metadata
- [ ] No coverage for `service.py` collection-stats RPC shape (regressed once
      already when `alertsWindowed` was added)

## 3. Performance

- [ ] `scan_momentum` re-reads every active market each cycle; profile whether
      the tape summary can be computed once per ticker per cycle
- [ ] `main_replay_events` grows to 500k rows; check the prune query uses an
      index rather than a table scan

## 4. Security

- [ ] Confirm no credential or wallet address can reach a log line at INFO
- [ ] `script_sandbox` review: verify the runaway guard still bounds CPU on the
      current Python version

## 5. Accessibility

- [ ] Verify every icon-only control has an accessible name (Sidebar share
      button has one; audit the rest)
- [ ] Check focus-visible styling survives the 2.12 field additions

## 6. UX/UI

- [ ] Strategy screen now has five risk fields in one grid; consider grouping
      the two new caps under a labelled subsection
- [ ] Surface the drawdown pause state in the header when it blocks entries

## 7. Refactor

- [x] Remove dead `src/components/TopBar.tsx` (duplicate of WorkspaceStatus)
- [ ] `trader.execute_signal` is ~200 lines; extract the sizing/depth block

## 8. Docs

- [ ] README does not mention the 2.11/2.12 risk controls
- [ ] DECISIONS.md needs backfilling for assumptions made before it existed
