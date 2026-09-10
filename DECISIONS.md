# Decisions

Assumptions made while working without confirmation. Each entry states the
ambiguity, the choice, and why it is the safest reasonable option.

## 2026-09-10 — assert e2e against `WorkspaceStatus`, not `TopBar`

`paper-activity.e2e.mjs` waited for a practice-mode string that exists only in
`TopBar.tsx`, a component nothing imports. Two readings were possible: the test
was right and `TopBar` should have been wired up, or the test was stale.

Chose stale-test. `WorkspaceStatus` is the component actually rendered, is
referenced by the layout, and carries the newer copy; `TopBar` still used
labels from an earlier design. Reviving dead UI to satisfy a test would change
shipped behaviour, which is the riskier of the two.

## 2026-09-10 — delete `TopBar.tsx` rather than leave it dormant

It could have been kept in case someone intended to restore it. Deleting is
reversible through git history, whereas leaving a second, subtly different
status component invites exactly the confusion that kept a test broken for four
releases.

## 2026-09-10 — keep `db.get_previous_snapshots_bulk` for now

The 2.11 momentum rewrite removed its only caller. It is a public-looking DB
helper, so it is queued in TODO.md for a deliberate check rather than removed
alongside an unrelated change.

## 2026-09-10 — kill switch lives on Dashboard only

Positions already has "Cancel All" for open orders. Flatten (sell everything)
is the more dangerous action, so it gets a prominent persistent banner on
Dashboard while any position is open. Keeping it off Positions avoids
duplicating a destructive control in a dense toolbar.

## 2026-09-10 — word-boundary fix for categorize short tokens

"inflation" was misclassified as sports (contains "nfl"), "something" as crypto
(contains "eth"). Short bare tokens (`nfl`, `eth`, `btc`, `sol`, `do`) now use
`\b...\b` regex matching while multi-word phrases keep substring match. This
preserves backward compatibility for "NFL Sunday" style phrases while fixing
false positives in everyday English.

## 2026-09-10 — NaN guard in sanitize_rules

`float("NaN")` is valid Python but always-false in all comparisons (including
`> 0`). A NaN gate would silently disable every rule that references it. The
fix rejects NaN/Inf with `math.isfinite()` before float conversion.

## 2026-09-10 — OnboardingModal focus trap (pure React, no library)

No focus-trap npm package was added. The hook uses native
`querySelectorAll(FOCUSABLE)` and `keydown` handler to cycle Tab/Shift+Tab
within the modal, restore focus on unmount, and lock body scroll. Keeps the
dependency tree flat.
