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

- [ ] **`PolymarketAPIError` throws away the server's reason**
  `polymarket_api.py:48` builds the error from `reason_phrase`, never
  `response.text`, so a rejection records "Unprocessable Entity" and the
  exchange's actual explanation is lost. Blocks diagnosing the first live
  order — fix before any Stage 5 run.
    Scope: polymarket_api.py + test. Test: py:test. Rollback: revert.

- [ ] **No UI surface for order recovery**
  The IPC now carries `recoverOrder` and the backend validates it, but nothing
  in the renderer calls it. An operator still needs a console. Smallest honest
  fix: a recovery panel wherever the journal blocker is surfaced.
    Scope: src/pages + shared/types. Test: e2e. Rollback: revert.

- [ ] **Group cap cannot see `crypto15m_positions`**
  Upgrade 5 is titled "account-wide" but `GROUP_SQL` reads `bot_positions`
  only, and neither `crypto15m_trader` nor `copy_trader` calls
  `group_budget_usd`. Cross-engine correlated risk is unbounded.
    Scope: account_risk.py + callers. Test: py:test. Rollback: revert.

- [ ] **Exit can offer the whole position with no depth evidence**
  `trader.py:2347` — `supported = affordable_at_depth(...) if bid_levels else
  remaining`. UPGRADE-7 states size is bounded by displayed bid depth.
  Unreachable through the real adapter today, but contrary to the stated
  invariant and live against any quote source reporting a touch without levels.
    Scope: trader.py + test. Test: py:test. Rollback: revert.

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
