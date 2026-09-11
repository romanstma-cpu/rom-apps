# ROM Polybot 2.14.2 review

A point release over 2.14.1. One interface pass and three backend failure
modes closed. Use this record to assess the changes and their verification
before installing. It does not certify profitability, and this release has not
been exercised against a live exchange account.

2.14.2 contains everything in 2.14.1, 2.14.0 and 2.13.1.

## Changes

### The interface was measured, then fixed

Every page was driven in the packaged app at 1440px and 420px and measured for
what actually renders — contrast against real composited backdrops, type and
spacing scales, hit-target size, accessible names, overflow. The findings, not
taste, decided the work. The probe ships as `npm run check:ui` so this stays
measurable.

**Legibility.** Small de-emphasized labels were set at 10px in 18 files — 171
strings across the Terminal, Crypto, Strategy and other pages. The hierarchy
was right; the floor was below comfortable reading size. Everything sub-11px
is now 11px. The Terminal's 15/22/25/31px one-off sizes are 16/24/30, and a
28px metric elsewhere is 30px, so one type scale covers the app.

**Contrast.** The Terminal defines its own text ramp and two steps of it
failed clearly: `--dim` at 2.8:1 and `--dimmer` at 1.9:1 against their own
panels, covering 33 strings including every log timestamp. The ramp is now
four steps that each clear 4.5:1 against every backdrop in that view.
Separately `loss` and `indigo` are fill values that were also used as text, at
4.2:1 and 2.4:1; they keep their fill meaning and gain `lossText` and
`indigoText` shades that pass, applied at 106 call sites.

**Fit.** Raising the type floor consumed horizontal room that very wide letter
spacing (.22em–.30em) no longer had, so stat chips wrapped mid-word and a
panel qualifier clipped at the edge. Spacing is pulled back, headings hold one
line, and a qualifier ellipsizes rather than overflowing. Terminal spacing and
radii were a parallel scale of 5/7/9/11/14 and 3/7/9/20/50px; both now snap to
4/8/12/16.

**The trade log was unreadable, for a specific reason.** Each row printed the
time on the left and the backend echoed a full `[YYYY-MM-DD HH:MM:SS]` inside
the message, so the same timestamp appeared twice and the duplicate consumed
the characters the message needed — the actual text was truncated away. The
echoed copy is stripped; the full untouched line remains as the row's tooltip.

**Empty and unlabelled states.** "Last 10 fills" rendered ten grey boxes
before any fill existed, which reads as not-yet-loaded rather than empty; it
now says there are none. The sidebar showed a bare 20px dash with nothing
naming it; it is labelled Account value.

**Accessible names.** Four controls had none: a practice-bankroll field, two
trading-window time inputs and a confidence slider. A shared `Field` now mints
an id and points its `<label>` at the control it wraps, which also removed two
duplicate local copies of that component. The switch that arms real orders on
the Scripts page was a 36×20 target, below the 24px floor; it is now 44×24.

**The Guide** was a single card filling under half the page, with body lines
running about 140 characters — roughly double a comfortable measure. It is
rewritten to a capped measure with the content a new operator needs: the four
connection steps, why to start in practice, what each page is for, what
happens when an order cannot be confirmed, and what the software does not
promise.

### Three backend failure modes closed

`cancel_pending` was written before the cancel POST without the
`synchronous=FULL` and `BEGIN IMMEDIATE` discipline every other pre-network
journal write uses, so power loss at that moment could leave the intent at
`open`. Attaching an exchange id already owned by another intent raised a raw
`sqlite3.IntegrityError` — correctly refused and nothing written, but opaque;
it now raises `RecoveryRequired`. `require_entry_depth` was read as a bare
`cfg.get(..., True)` and appeared in no clamp list, so any falsy stored value
silently disabled the Upgrade 6 depth gate; it is now validated.

## Verification

- Backend: 1,831 tests collected, 1,692 passed, 139 skipped, 0 failures.
- Interface measurements across 19 pages at 1440px and 420px: contrast
  failures, sub-11px text, off-scale type, off-scale spacing, off-scale radii,
  unnamed controls and horizontal overflow all measure **zero**. No renderer
  console errors on any page.
- TypeScript check (both projects), production build, frozen-backend
  self-test, and Windows installer build passed.
- 13/13 Electron e2e suites green against the packaged app; 58 locators, no
  string drift.

One correction worth recording. The first interface audit reported 60+
unlabelled inputs. That was wrong: it tested `textContent`, which is always
empty for an `<input>`, so every field named by a wrapping `<label>` looked
broken. Measured against `el.labels`, the real count was four. The probe was
fixed before any of those sixty were "corrected", and the same mistake means
the "zero unnamed controls" line in the 2.14.0 review was narrower than it
sounded — that check only covered `<button>`.

The remaining non-zero measurement is interactive targets under 24px. Most are
inputs sitting inside clickable label cards, where the card is the real target
and the measurement reads the inner element; the one that mattered, the
live-orders switch, was fixed.

Tests use isolated profiles and place no real orders. **Live exchange
execution remains unverified.** No livecheck stage has yet run against a real
Polymarket US account; stage 5 preflight was run and stopped at the credential
check, as designed.

## Installer

The installer is `release/ROM PolyBot-Setup-2.14.2.exe` (92.2 MB). Close
your running app before installing.

SHA-256: `E534DB4393A294BC978ECB49F04FDAB2D81B495BDB9A786AC60FA02A8010DCC5`

Verify before installing:

    certutil -hashfile "ROM PolyBot-Setup-2.14.2.exe" SHA256

## Before you install this one

Two releases have now changed trading behaviour in code that has never run
against a live account: exits hold where they previously placed an order
(2.14.0), and two engines decline entries they previously took (2.14.1). Both
tighten rather than loosen, and both are backed by tests confirmed to fail
against the previous source — but tests and mocks are the only evidence either
has. The livecheck harness exists to close that gap and has not been run with
credentials. Treat 2.14.2 as ready for testing, not as validated against the
exchange.
