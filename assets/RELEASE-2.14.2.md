# ROM Polybot 2.14.2

Three releases rolled into one: risk enforcement (2.14.0–2.14.1) and a full interface pass (2.14.2).

**The correlated-exposure cap now binds every engine.** The account-wide group-exposure query counted all three engines' fills, but only the main strategy ever read the remaining allowance. crypto15m and copy_trader could open past a limit their own positions were helping to reach. Both engines now refuse an entry into a full group and size one down to what the group has left. 25 new tests, 23 confirmed to fail against the previous source.

**Interface measured, then fixed.** Every page was driven in the packaged app at 1440px and 420px and measured for contrast, type scale, spacing, hit targets, accessible names, and overflow. Findings:

- Sub-11px text raised to 11px across 18 files (171 strings).
- Terminal contrast ramp fixed — two steps were at 2.8:1 and 1.9:1; now four steps that each clear 4.5:1.
- `loss` and `indigo` fill colours gained text-weight shades at 106 call sites.
- Type, spacing and radius scales unified across the app.
- Duplicate timestamps stripped from the trade log — the backend echoed a full timestamp inside the message that was already shown on the left.
- Guide rewritten to a capped measure with the content a new operator needs.
- Four unlabelled controls fixed via a shared Field component; Scripts toggle enlarged to 44×24.

**Three backend failure modes closed.** `cancel_pending` journaling now uses the same `synchronous=FULL` and `BEGIN IMMEDIATE` discipline as every other pre-network write. Attaching an exchange id already owned by another intent raises `RecoveryRequired` instead of a raw `IntegrityError`. `require_entry_depth` is now validated against the clamp list.

1,831 backend tests (0 failures), TypeScript check clean, 13/13 e2e suites green, 58 locators with no string drift. The design-system probe ships as `npm run check:ui`. No real trades were placed and no profitability improvement is claimed. The Windows installer is unsigned.
