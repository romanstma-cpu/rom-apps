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

- [ ] **No livecheck stage has been run against a real account**
  Stages 0-4 are read-only and stage 5 places one cancellable order. All are
  built and tested against mocks; none has spoken to Polymarket US. Preflight
  was run and stopped at the credential check, as designed. This needs the
  user's credentials and is theirs to execute:
  `python -m livecheck.live_order --preflight-only` first, then `--all` on the
  read-only runner, then the live order.
    Scope: operator action. Test: the harness reports. Rollback: n/a.

## Later

- [ ] **`require_entry_depth` is unvalidated config**
  Not in any clamp list in `_validate_config`; read as a bare
  `cfg.get(..., True)`. Any falsy stored value silently disables the whole
  Upgrade 6 depth gate.
- [ ] **`cancel_pending` write skips the FULL-sync discipline**
  `polymarket_api.py:316` writes it before the cancel POST without
  `synchronous=FULL` or `BEGIN IMMEDIATE`, unlike every other pre-network
  journal write. Power loss there could leave the intent at `open`.
- [ ] **Attaching an already-owned exchange id raises `sqlite3.IntegrityError`**
  Correctly refused and nothing written, but the message is opaque. Should be
  `RecoveryRequired`.
- [ ] **Undocumented hard-coded execution limits**
  `execution_quality.entry_price` enforces a 3c max spread and 2c max chase.
  No config key, no doc, no settings surface.
- [ ] **`use_rules=True` silently drops the entry price floor to 1c**
  `trader.py:570`. Undocumented interaction with `min_entry_price_cents`.
- [ ] **Stream modules expose no health state**
  No reconnect count, message count or connected flag on the two authenticated
  US streams; `stats()` on activity/rtds/spot has zero callers. Blocks the
  stream-health harness stage.

## Done

- [x] **crypto15m and copy_trader now consult the group cap.** Their exposure
      was already counted; neither read the allowance, so both could open past
      a limit their own fills were filling. Both now refuse a full group and
      size down a partly-used one, keyed to the bucket their own row lands in
      and charging intra-tick commitments as they go. `cap_bankroll_usd` gives
      the three engines one definition of the bankroll a fraction divides.
      25 tests, 23 confirmed failing against the previous source.
- [x] **Config parity: `signalDisplay`/`ledger` shape drift check — closed, not
      needed.** The drift-guard concern is already covered by the existing
      config-parity suite (backend->store, backend->type, store-backlog shrink,
      validator coverage). The named keys do not exist in any of the three
      config sources; grep returned zero hits and the only "display"/"ledger"
      occurrences are prose. No keys to add, no drift to guard (0967d00).
- [x] Livecheck stages 1-5: account reads, stream health (clock-skew gate),
      quote/depth fidelity, dry-run submission, and one real cancellable order
      behind a typed confirmation. 51 tests on the decision and safety logic
- [x] `PolymarketAPIError` carries the server's own explanation (reason +
      detail, truncated), so a live rejection names the field it objected to
- [x] Order recovery panel on Overview + blocked_intents in trading status;
      15-case e2e seeding a real journal row through the whole chain
- [x] Group cap counts crypto15m exposure (union in GROUP_SQL); 10 tests
- [x] Exit holds instead of offering the whole position when a quote reports a
      touch with no depth ladder; 2 tests, fail-before/pass-after verified
- [x] UI audit: 4 unnamed risk switches named (enforced in the type), 8px
      legibility floor raised to 10px, onboarding leads with risk not the offer
- [x] Test suite reproducible off this machine: pytest-asyncio pinned in
      requirements-dev.txt (29 async tests were failing, incl. in CI);
      test_db_migration decodes git output as UTF-8, not cp1252
- [x] Momentum rejection accounting: per-reason counters surfaced in scanner's
      momentum log; clock-behind separated from staleness; gate unchanged
- [x] Series grouping repaired in account_risk + portfolio_replay via the
      events join; 4 tests fail-before/pass-after
- [x] Order recovery drill (35 network-free tests) + operator runbook
- [x] runOnce IPC carries recoverOrder with an action allowlist and validated
      payload rebuild; backend fails legibly instead of KeyError
- [x] E2E regression guard for the module-scope hook startup crash (a782084)
- [x] Focus traps for BossFight/Scripts/Settings/FlexStatsCard overlays (d6fb3e8)
- [x] Positions list virtualized (f105792)
- [x] Config parity drift test across backend/type/validator (4022417)
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
- [x] Dark-mode audit: sidebar bg-[#0E1520] -> rom.sidebar token
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
- [x] Kill switch banner on Dashboard (2-step confirm -> trading.flatten)
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
