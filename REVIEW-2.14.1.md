# ROM Polybot 2.14.1 review

A point release over 2.14.0 carrying one risk fix. Use this record to assess
the change and its verification before installing. It does not certify
profitability, and this release has not been exercised against a live exchange
account.

2.14.1 contains everything in 2.14.0 and 2.13.1. If you already have the
2.14.0 installer, its binary predates the fix below and should be replaced
rather than kept alongside this one.

## The change

### The correlated-exposure cap now binds every engine, not just one

UPGRADE-5 is titled "account-wide risk controls". Its exposure query counts
main-strategy *and* crypto15m positions, so all three engines' fills raise a
correlated group's usage. Only `trader` ever read the remaining allowance.
crypto15m and copy_trader could therefore open past a limit their own fills
were helping to reach.

crypto15m is the sharp end of that. Every 15-minute window on one asset shares
a series and moves with the same spot price, which is precisely the
correlation this control exists to bound — and it was the engine least bound
by it. A run of same-asset windows could accumulate well past the configured
group fraction while every other risk signal read normal.

Both engines now refuse an entry into a full group and size one down to what
the group has left.

Three details decide whether that is real or merely nominal:

- **A prospective crypto15m entry is keyed `series or ticker`,** matching how
  the exposure query buckets the row that entry becomes. The existing
  `group_key` helper would consult the `markets` table, which crypto15m rows
  are not joined against; using it here could measure an entry against a
  different group's usage, which is worse than having no cap.
- **Group exposure is read once per tick and charged as entries commit,** so
  several entries in one pass cannot each be granted the same correlated
  dollars.
- **`cap_bankroll_usd` is now the single definition of the bankroll a fraction
  divides.** All three engines already computed cash-plus-filled-cost
  separately and identically. A cap is account-wide only while they keep
  computing the same number, and three copies is how that stops being true.

The backlog recorded this as blocked on deciding which bankroll a group
fraction means. That turned out to be a question about the *sizing* path, not
the cap path: the cap quantity was already agreed in all three engines and
only needed naming.

**This can only tighten.** Counting the same exposure against more callers can
shrink an entry's allowance, never grow it. `max_group_exposure_fraction`
still defaults to `0.0`, which disables the control rather than reading as a
cap of zero — two tests pin that no-op, one per engine.

## Verification

- Backend: 1,829 tests collected, 1,690 passed, 139 skipped, 0 failures.
- 25 new tests cover the shared bankroll definition and its refusal to be
  inflated by negative or non-finite inputs; prospective-entry keying
  round-tripped against the row it becomes; refusal and size reduction in both
  engines; intra-tick accumulation; an unrelated series left alone; and both
  engines unchanged while the control is off.
- **23 of those 25 were confirmed to fail against the previous source**, by
  restoring the old files and re-running. The two that pass in both states are
  the control-off cases, which assert unchanged behaviour by design. The
  clearest failure was a copy_trader case where the old code placed a real
  20-contract order into a group already past its limit.
- TypeScript check (both projects), production build, frozen-backend
  self-test, and Windows installer build passed.
- Config-boundary validation and E2E string-drift checks passed.
- Electron suites passed against the packaged app.

Tests use isolated profiles and place no real orders. **Live exchange
execution remains unverified.** No livecheck stage has yet run against a real
Polymarket US account; stage 5 preflight was run and stopped at the credential
check, as designed.

## Installer

The installer is `release/ROM PolyBot-Setup-2.14.1.exe` (92.2 MB). Close
your running app before installing.

SHA-256: `84795A6337DF5EE462005AE82CCDB1747AABA22CFE132ACEA09984E57124EAE5`

Verify before installing:

    certutil -hashfile "ROM PolyBot-Setup-2.14.1.exe" SHA256

## Before you install this one

2.14.0 changed trading behaviour that has never run against a live account —
the exit path now *holds* a position where it would previously have placed an
order. This release adds a second behaviour change in the same untested area:
two engines will now decline entries they previously took. Both changes are
intended and both tighten rather than loosen, but the only evidence for either
is unit tests and mocks. The livecheck harness exists to close that gap and
has not been run with credentials. Treat 2.14.1 as ready for testing, not as
validated against the exchange.
