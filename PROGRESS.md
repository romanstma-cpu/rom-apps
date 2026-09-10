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

### Current state

- Python: 1,091 passing.
- TypeScript: typecheck and build clean.
- E2E: 9 of 9 passing.
- Working tree committed; version 2.12.0 (unreleased changes since publish).

### Next steps

Working down TODO.md section 1, then section 2. Immediate next task: audit the
remaining e2e specs for other assertions that no longer match shipped UI, since
this class of drift hid a real gap for four versions.
