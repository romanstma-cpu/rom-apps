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

- [ ] **Keyboard shortcuts**
  Add Ctrl+1-9 to switch between pages (Dashboard, MainEngine, Positions, etc.)
  and Ctrl+K for the command palette. Scope: `src/App.tsx`, new hook.
  Test: `npm run typecheck`. Rollback: revert commit.

- [ ] **Responsive mobile layout**
  Collapsible sidebar for screens < 768px. Scope: `src/components/Sidebar.tsx`.
  Test: manual resize in dev mode. Rollback: revert commit.

- [ ] **Consolidate stale RELEASE-*.md files**
  Keep only RELEASE-2.12.md; move older to a `releases/archive/` directory.
  Test: `git status` clean. Rollback: revert commit.

- [ ] **Re-run full e2e suite**
  Verify all 9 suites pass after the session's changes. Scope: all e2e/*.mjs.
  Test: each suite exits 0. Rollback: N/A.

## Later

- [ ] **Dark mode toggle (if theme is not already dark-only)**
  Check if app supports light mode. If not, document why. Scope: `src/index.css`.
  Test: visual. Rollback: revert commit.

## Done

- [x] Kill switch banner on Dashboard (2-step confirm → trading.flatten)
- [x] CSV export of trade history (all resolved, not just 200 in view)
- [x] Onboarding walkthrough — already a full modal (disclaimer + referral);
      no work needed
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