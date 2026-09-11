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

- [ ] **crypto15m and copy_trader do not consult the group cap**
  Their exposure is now COUNTED (account_risk unions crypto15m_positions), but
  neither engine calls `group_budget_usd`, so they can still open past the cap.
  Blocked on a decision: crypto15m sizes from `_bankroll_usd`, a different
  quantity from the balance main measures fractions against, so which bankroll
  a group fraction means must be settled first.
    Scope: crypto15m_trader.py, copy_trader.py. Test: py:test. Rollback: revert.

- [ ] **Livecheck stages 1 and 4 are unwritten; 2 and 3 are unverified**
  stage2_streams.py and stage3_quotes.py exist untracked from an interrupted
  run and import cleanly, but have no tests and have not been reviewed.
  Stage 1 (account read surface) and stage 4 (dry-run submission) do not exist.
    Scope: python/livecheck/**. Test: py:test + import. Rollback: delete.

- [ ] **Automated e2e coverage for CSV export and kill switch path**
  History CSV export and the Dashboard kill-switch flow are covered by
  manual/terminal e2e but not as standalone suites. Add `e2e/history-csv.e2e.mjs`
  and fold kill-switch feedback assertions into the paper-activity suite.
    Scope: e2e/* only. Test: node e2e/<file>.e2e.mjs. Rollback: revert.

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
- [ ] **Focus trap for remaining modals**
  OnboardingModal, NameDialog done. Apply the same pattern to RiskLimits
  and Accounts full-screen overlays if they ever become dialogs.
- [ ] **Window icon .ico regeneration**
  The installer bundles an icon; confirm the generated .ico matches the
  current ROM branding (visual check, not code).

## Done

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
