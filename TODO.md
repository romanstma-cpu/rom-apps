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

- [ ] **Docs: DESIGN.md refresh for 2.13 changes**
  Update the architecture doc with the new kill switch, CSV export,
  keyboard shortcuts, responsive sidebar, focus trap, config validation,
  schema/insert column drift fix, and the crypto15m interval column fix.
  Scope: DESIGN.md only. Test: renders correctly. Rollback: revert.

## Later

- [ ] **Focus trap for remaining modals**
  OnboardingModal is done. Apply the same pattern to Settings panels
  and Accounts modals if they ever become full-screen overlays.

## Done

- [x] Dark-mode audit: sidebar bg-[#0E1520] → rom.sidebar token
- [x] Security: IPC config validation (config-validate.ts + test;
      config:update/replace reject bad shapes, NaN/Inf, wrong enums)
- [x] Accessibility: OnboardingModal focus trap (Tab cycle, body scroll lock)
- [x] DB migration test: 2.8 schema to current — verified upgrade path
- [x] Schema/insert column drift fix: interval + 4 columns in base SCHEMA,
      TestInsertColumnParity regression
- [x] Test coverage: scanner scoring (20), market stream (22), account
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
