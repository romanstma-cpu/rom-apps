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

- [x] **Config parity: `signalDisplay`/`ledger` shape drift check**
  The drift-guard concern this item describes is already covered by the
  existing configparity test suite (backend→store, backend→type, store-backlog
  shrink, validator coverage), which runs and passes. The named keys
  `signalDisplay`/`ledger` do not exist as config keys in any of the three
  config sources (backend DEFAULT_CONFIG, shared/types.ts TraderConfig, or the
  validator FIELD_TYPES map) — grep across all three returned zero hits, and the
  only "display"/"ledger" occurrences are prose (a `require_entry_depth` comment
  and History/Scripts copy). No keys to add, no drift to guard; item closed.

## Later

- [ ] **Focus trap for remaining dialogs**
  OnboardingModal, NameDialog done. `BossFight.tsx` (line 186),
  `Scripts.tsx` (637, 702), `Settings.tsx` (183), `FlexStatsCard.tsx` (162)
  still have fixed inset-0 overlays without the trap. Apply same pattern.
- [ ] **Performance: virtualize Positions table**
  Positions page renders all rows; add windowing when >200 in the active
  filter. Scope: src/pages/Positions.tsx. Test: e2e positions suite.
  Rollback: revert.

## Done

- [x] E2E: automated CSV export (history-csv.e2e.mjs) + kill-switch feedback
      (kill-switch.e2e.mjs) — committed f02d53e
- [x] Focus trap audit — Accounts uses shared NameDialog (already trapped);
      RiskLimits has no overlays. No changes needed (agent verified)
- [x] Window icon verification — resources/rom.ico is pixel-perfect LANCZOS
      downscale of rom.png; installer/exe embed matching icon; no change needed
- [x] 2.13.0 published to romapps.xyz (site commit 1a8334a); live installer
      byte-identical, checksum 200
- [x] Design+a11y wave: modal focus traps, dashboard kill-switch honesty,
      overview hero (61426ec)
- [x] Indicator/clob/copy-trader edge cases + 183 tests (a42283b)
- [x] Backtest pure-helper units (af06eda)
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