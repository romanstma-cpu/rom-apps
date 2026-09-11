# ROM Polybot 2.14.0 review

Use this record to assess the update and its verification before installing it. The review checks the changes and affected workflows; it does not certify profitability, and this release has not been exercised against a live exchange account.

## What this supersedes

2.14.0 contains everything in 2.13.1. That release shipped while this work was
in progress on a separate branch, and it was merged in before the installer was
built: focus traps for the BossFight, Scripts, Settings and FlexStatsCard
overlays, Positions list virtualization, the module-scope hook startup crash
fix and its regression guard, the config parity drift test, and the CSV export
and kill-switch e2e suites. If you are on 2.13.1, none of it is lost.

## Changes

### Two risk controls now do what their documentation says

- **Exits no longer sell into an unpriced book.** `_liquidate_position` sized an exit with `affordable_at_depth(...) if bid_levels else remaining`, so a quote reporting a touch with no depth ladder offered the entire remaining position with nothing showing behind the bid. UPGRADE-7 states exit size is bounded by displayed bid depth; a touch without a ladder is not evidence of size and is now treated as no depth. **This is a behaviour change**: a position can now be held where an order would previously have been placed. It was unreachable through the real US adapter, which returns no bid when there are no bid rows, but it was live against any quote source reporting a touch without levels.
- **The correlated-exposure cap counts both engines.** UPGRADE-5 is titled "account-wide" but its exposure query read `bot_positions` alone, so exposure already held by the crypto15m engine was invisible to a main-strategy entry measured against the same series. `crypto15m_positions` rows are now counted. Counting more exposure can only shrink an entry's allowance, never grow it. Still outstanding: crypto15m and copy_trader count toward the cap but do not consult it.

### A halted order journal can be cleared from inside the app

A non-terminal order intent halts submissions from every engine, deliberately, with no timeout and no automatic forget path. Recovery was reachable only by shutting the app down and writing JSON-RPC to the backend's stdin. Overview now shows a recovery panel naming each halted intent, what its state means, and the identifying detail needed to match it against the exchange's order list. The `runOnce` IPC carries the recovery arguments it previously dropped, validated against an allowlist at the boundary; the backend fails legibly instead of raising `KeyError`.

### Momentum can no longer fail silently

`momentum_window` gates every trade receipt on `0 <= now-at`. The lower bound is zero, so a local clock behind the exchange by any amount rejects every receipt and momentum reports nothing — while the trade still reaches the trade list, the database and the replay recorder, leaving every other health signal normal. **The gate is unchanged.** Rejections are now counted by reason, with a host-clock fault separated from ordinary staleness, and surfaced in the scanner's existing momentum log.

### Rejections carry the exchange's own words

`PolymarketAPIError` was built from `reason_phrase` and discarded the response body, so a rejected order recorded "Unprocessable Entity" and nothing else. The server's explanation is now kept, truncated, alongside the reason.

### Accessibility and legibility

Four switches had no accessible name and announced only as "switch, off": unlimited daily new positions, sell out on daily loss, restrict trading to a weekly window, and Scripts live — the master switch for real orders. All four came from `Field` rendering its label as a sibling of the control. `SwitchProps` now requires either a label or an explicit `ariaLabel`, so an unnamed switch fails the type check. The smallest rendered text was 8px in a low-contrast token; every sub-10px declaration is now 10px.

Onboarding presented a $50 referral offer in a highlighted card with an icon and a full-width button, while "automated trading can lose money" was an unstyled paragraph beneath it and ROM's own referral interest was the smallest text in the dialog. The risk disclosure now has equal visual weight and comes first.

### Live-validation harness (new, not yet run against an account)

`python/livecheck` is an operator tool that runs from the source checkout and
its virtual environment, not from the installed app -- it is deliberately not
bundled into the frozen backend, because it needs your credentials and needs
the desktop app closed so two writers do not share the order journal. It adds a
staged read-only harness: credential proof, account read surface, stream health including the clock-skew measurement above, quote and depth fidelity, and a dry-run submission that builds the real payload and proves the journal commit precedes the POST without sending. Stages run under an interlock that refuses any non-GET at the HTTP chokepoint. A sixth stage places one real minimum-size order and cancels it; it is excluded from the read-only runner by construction, requires a typed confirmation through a separate entry point, and refuses to start unless the order journal is clean.

### Test reproducibility

`pytest-asyncio` was installed by hand in one developer environment and absent from `requirements-dev.txt`, so a clean checkout — including CI — silently lost 29 async tests covering order recovery and the US API adapter. A schema-digest test decoded git output with the locale codec and matched only on UTF-8 hosts.

## Verification

- Backend: 1,804 tests collected, 1,665 passed, 139 skipped, 0 failures, on a
  freshly provisioned virtual environment.
- TypeScript check (both projects), production build, frozen-backend self-test,
  and Windows installer build passed.
- Config-boundary validation and E2E string-drift checks passed (58 locators
  across 14 specs, no drift).
- Electron suites passed: arming, public readiness, strategy clarity, paper
  activity, risk drafts, referrals, portfolio replay, calibration, terminal
  review, order recovery, CSV export, kill-switch feedback, and the
  startup-crash regression guard.
- The order-recovery suite seeds a real blocking intent into the backend's own
  database and drives the whole chain rather than stubbing the renderer.
- UI audit drove all 19 pages in the packaged app and measured what renders:
  zero unnamed controls, smallest font 10px, no horizontal overflow at 1440px
  or 420px, no renderer console errors on any page.
- Two exit-discipline cases and four series-grouping cases were confirmed to
  fail against the previous source and pass after, by restoring the old code
  and re-running.

One caveat on the numbers: `test_loop_watchdog_restarts_stalled_loop` is
timing-sensitive and failed once under full-suite load, then passed in
isolation and on re-runs of the whole suite. It predates this release and
neither it nor the watchdog it covers was touched here. It is a flake, not a
regression, and it is worth stabilising rather than leaving to chance.

Tests use isolated profiles and place no real orders. **Live exchange execution
remains unverified.** Stage 5 preflight was run and stopped at the credential
check, as designed; no order has been placed by this project against any
account.

## Superseded by 2.14.1

2.14.0 was built but never published. Its installer has been replaced in
`release/` by 2.14.1, which contains everything here plus the account-wide
group-cap fix. The checksum below still describes the 2.14.0 binary correctly;
that binary is simply no longer on disk. Read REVIEW-2.14.1.md instead.

## Installer

The installer is `release/ROM PolyBot-Setup-2.14.0.exe` (92.2 MB). Close your
running app before installing. This build was produced from the merged tree, so
it contains 2.13.1 in full.

SHA-256: `47F27319A45FCF55B55EC897F3D42E1FB9EA776E06D5FCE9C441DED53BB8940B`.

Verify before installing:

    certutil -hashfile "ROM PolyBot-Setup-2.14.0.exe" SHA256

## Before you install this one

This release changes trading behaviour that has never run against a live
account. The exit path now *holds* a position where it would previously have
placed an order — that is the intended fix, but it is a behaviour change, and
the only evidence for it is unit tests and mocks. The livecheck harness exists
precisely to close that gap and has not yet been run with credentials. Treat
2.14.0 as ready for testing, not as validated against the exchange.
