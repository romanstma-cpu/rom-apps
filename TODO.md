# ROM Polybot — backlog

Prioritized per the autonomous operating rules: bugs and failing tests first,
then missing tests, performance, security, accessibility, UX, refactors, docs.

Rules for this file:
- Max 15 active items
- Three sections only: now / later / done
- Done items removed after commit
- Every item states scope, test, and rollback

---

## Now

- [ ] **Perf: replay load chunking**
  `main_recorder.load` caps at 100k events and raises. Streaming readers
  (Backtest page) would benefit from a chunked iterator. Scope:
  `python/main_recorder.py` — add `iter_load` returning an iterator that
  pages through rows with keyset pagination. Test: unit test with 150k
  rows, assert all reachable. Rollback: revert commit.

- [ ] **Security: bind IPC validation**
  Electron `ipcMain.handle('trading:flatten', ...)` and other handlers
  take no validation; ensure the preload `contextIsolation` stays on and
  that `trading:flatten` requires paper-mode off. Scope: `electron/ipc.ts`.
  Test: manual + e2e. Rollback: revert commit.

- [ ] **Accessibility: focus trap in OnboardingModal**
  The modal has no focus trap; Tab can escape behind the scrim. Add one.
  Scope: `src/pages/Onboarding.tsx`. Test: keyboard nav e2e. Rollback: revert.

## Later

- [ ] **Docs: DESIGN.md refresh for 2.13 changes**
  After feature work settles, update the architecture doc with the new
  kill switch, CSV export, shortcuts, rail sidebar.

- [ ] **Dark-mode audit**
  Confirm every page uses `bg-rom-*` tokens (no hard-coded hex).

## Done

- [x] Test coverage: scanner scoring (24), market stream (22), account
      stream (18), categorize (29) — found+fixed 3 real bugs
- [x] Test coverage: rules (19) — found+fixed NaN leak
- [x] Test coverage: crypto15m pricing (42)
- [x] Test coverage: main_recorder edge cases (9)
- [x] Kill switch banner on Dashboard (2-step confirm → trading.flatten)
- [x] CSV export of trade history (all resolved, not just 200 in view)
- [x] Keyboard navigation (Ctrl+1..9)
- [x] Responsive icon-rail sidebar (< 768px)
- [x] Onboarding walkthrough — already a full modal; no work needed
- [x] Guide page — already has real content; no work needed
- [x] paper-activity e2e fixed (asserts against WorkspaceStatus)
- [x] Dead TopBar component removed
- [x] Config parity tests + all 17 UI defaults fixed
- [x] Backend-only config keys classified
- [x] Replay pruning indexed + save_snapshots_bulk batched
- [x] group_key edge cases tested
- [x] collection_stats RPC shape test added
- [x] main_recorder tests (age/count prune, dedup, index save)
- [x] Script sandbox recursion test added