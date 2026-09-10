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

- [ ] **Kill switch UI**
  Add a prominent "Kill Switch" button to Dashboard and Positions that calls
  `trader.flatten_open_positions` immediately. Requires a confirmation dialog
  and a 5s countdown before executing. Scope: `src/pages/Dashboard.tsx`,
  `src/pages/Positions.tsx`, `python/service.py` (new RPC handler).
  Test: manual e2e — button shows, confirmation works, positions flatten.
  Rollback: revert commit.

- [ ] **Onboarding walkthrough**
  Fill `src/pages/Onboarding.tsx` (currently 6 lines) with a 4-step wizard:
  1) Connect API keys, 2) Set risk limits, 3) Start practice mode, 4) Go live.
  Link from `MainEngine.tsx` when `profiles` count is 0. Scope: `src/pages/Onboarding.tsx`,
  `src/pages/MainEngine.tsx`. Test: `npm run typecheck`. Rollback: revert commit.

- [ ] **Guide page**
  Fill `src/pages/Guide.tsx` (currently 2 lines) with a quick-reference page
  explaining each screen, the signal lifecycle, and where to find settings.
  Scope: `src/pages/Guide.tsx`. Test: `npm run typecheck`. Rollback: revert commit.

- [ ] **Re-run full e2e suite**
  Verify all 9 suites pass after the session's changes. Scope: all e2e/*.mjs.
  Test: each suite exits 0. Rollback: N/A.

## Later

- [ ] **Keyboard shortcuts**
  Add Ctrl+1-9 to switch between pages (Dashboard, MainEngine, Positions, etc.)
  and Ctrl+K for the command palette. Scope: `src/App.tsx`, new hook.
  Test: `npm run typecheck`. Rollback: revert commit.

- [ ] **Responsive mobile layout**
  Collapsible sidebar for screens < 768px. Scope: `src/components/Sidebar.tsx`.
  Test: manual resize in dev mode. Rollback: revert commit.

- [ ] **Dark mode toggle (if theme is not already dark-only)**
  Check if app supports light mode. If not, document why. Scope: `src/index.css`.
  Test: visual. Rollback: revert commit.

- [ ] **Export trade history as CSV**
  Button on History page to download filtered results. Scope: `src/pages/History.tsx`.
  Test: `npm run typecheck`. Rollback: revert commit.

- [ ] **Consolidate stale RELEASE-*.md files**
  Keep only RELEASE-2.12.md; move older to a `releases/archive/` directory.
  Test: `git status` clean. Rollback: revert commit.

## Done

- [x] paper-activity e2e fixed (asserts against WorkspaceStatus)
- [x] Dead TopBar component removed
- [x] Config parity tests + all 17 UI defaults fixed
- [x] Backend-only config keys classified
- [x] Replay pruning indexed + save_snapshots_bulk batched
- [x] group_key edge cases tested
- [x] collection_stats RPC shape test added
- [x] main_recorder tests (age/count prune, dedup, index save)
- [x] Script sandbox recursion test added
