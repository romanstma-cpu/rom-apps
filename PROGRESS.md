# ROM Polybot — progress log

Newest entry first. Each entry records what changed, what was verified, and
what is still unproven.

## Session 2026-09-10 — autonomous mode

### State at start

- Version 2.12.0, published and verified live on romapps.xyz.
- 1,091 Python tests passing; typecheck and production build clean.
- 8 of 9 Electron e2e suites passing; `paper-activity` failing since 2.8.

### Fixed: `paper-activity` e2e (the last failing test)

The spec waited for UI strings that no longer exist. Two stale assertions:

1. It waited for `'Practice mode — no exchange orders'`. That text is gone.
   Probing the running app showed the header now reads
   `Main: Blocked · Practice selected`, rendered by `WorkspaceStatus`.
2. It waited for `/auth failed/i` as a single match, but the credential reason
   is rendered in two cards, so Playwright's strict mode failed the locator.

Both were assertion drift, not product bugs — the app behaved correctly the
whole time. Fixed by asserting against the shipped `WorkspaceStatus` text and
taking `.first()` on the duplicated reason.

**Verified:** all 9 e2e suites now pass.

### Removed dead `src/components/TopBar.tsx`

Probing for the practice string revealed `TopBar` defines a near-duplicate of
`WorkspaceStatus` — including the stale `'Practice mode selected'` label — and
is imported by nothing. It was the reason the broken test looked plausible.
111 lines removed. (`ScriptEditor` looked unused by the same grep but is
lazy-loaded from `Scripts.tsx`; it stays.)

**Verified:** typecheck clean, all e2e suites still pass.

### Config parity: backend vs desktop store vs renderer type

Nothing compared the three places a config key must exist, so a key added to
Python and forgotten in TypeScript failed silently. Added
`python/tests/test_config_parity.py` comparing all three.

It immediately flagged `requireEntryDepth` and `exitPriceLossBudgetCents`, both
added in 2.12. Measured the real impact with a live Electron probe instead of
assuming: writes *do* persist (`patchConfig` spreads over current config), but
the renderer read `undefined` instead of `true`/`2`, so a bound control would
start empty.

Fixed those two, then worked down the whole backlog:

- 6 keys (`crypto15mPollSec`, `dbCleanupInterval`, `scriptHookTimeoutSec` and
  three crypto15m model knobs) turned out to be genuinely backend-only — absent
  from the store, the type and `src/` entirely. Classified, not "fixed".
- 17 real gaps (`sizingMode`, `takeProfitPct`, `lifetimeLossLimitUsd`, the copy
  and crypto15m limits) got desktop defaults matching the backend.

`UNDECLARED_IN_STORE` is now empty, with a test asserting it may only shrink.
Verified in a running app: all 166 renderer config keys have a defined value.

### Current state

- Python: 1,129 passing (+38 this session).
- TypeScript: typecheck and build clean.
- E2E: 9 of 9 passing.
- Working tree committed; version 2.12.0 (unreleased changes since publish).

### Next steps

Sections 1 and 2 of TODO.md are clear apart from two remaining test gaps
(`account_risk.group_key` with an unknown market, and the collection-stats RPC
shape). Next: those two, then section 3 (performance) — starting with whether
the `main_replay_events` prune query uses an index or scans the table.
