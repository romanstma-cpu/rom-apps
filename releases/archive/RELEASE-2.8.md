# ROM Polybot 2.8

## Daily risk limits now reset at your local midnight

**This changes when your daily limits roll over. Read this before running live.**

The daily stop-loss, daily take-profit and daily new-position cap previously
reset at UTC midnight — 8pm US Eastern in summer, 7pm in winter — while the
trading-hours gate used your configured UTC offset. The two disagreed, and the
limits were the looser side of the disagreement.

Concretely, on a 9am–9pm ET session with a −$100 daily stop: a loss that tripped
the stop at 5pm ET released again at 8pm ET, because the day's P&L baseline was
re-taken from a snapshot recorded *after* the loss. The bot then traded the rest
of the session on a fresh budget, so the worst case for the day was −$200
against a limit labelled −$100. `max_daily_new_positions` doubled the same way,
and `flatten_on_daily_stop` could liquidate at 7:50pm and re-enter at 8:05pm.

Every daily boundary now derives from **UTC offset (minutes)**, the same setting
the trading-hours gate uses. It has moved to the top of the renamed **Trading
day** panel and is editable whether or not you restrict trading to a weekly
window, because it now applies either way.

### What happens on upgrade

Installs that still carry the old `0` default **and** never enabled trading
hours are migrated to the host machine's zone on first launch, and the change is
logged. A saved offset — including a deliberate `0` — is left alone. New
installs default to the host zone.

If you were relying on UTC rollover, set the offset back to 0.

## Kelly sizing mode

**Bet sizing** gains a third mode alongside `% of balance` and `Fixed contracts`.

The existing percent ramp sizes purely on edge, ignoring entry price. For a
binary contract the growth-optimal fraction is `(p − c) / (1 − c)`, where the
denominator is your loss per contract — and that varies ninefold across the
tradeable band. A 5-point edge at 90c risks 10c to win 90c; the same edge at 20c
risks 80c to win 20c. Sized identically, the second position carries roughly
nine times the variance.

Kelly mode sizes from edge *and* price. **Kelly multiplier** (default 25%)
scales the raw Kelly fraction — quarter-Kelly is the usual starting point, and
full Kelly is not recommended. The result is clamped by the existing size floor
and ceiling, and by the hard cap, reserve and exposure limits, which apply in
every mode as before. Non-positive edge sizes to zero rather than to the floor.

Kelly is growth-optimal only to the extent your confidence scores are
calibrated; sizing more aggressively on miscalibrated scores amplifies the
error. The Min-size edge and Max-size edge settings are not used in this mode.
Neither mode caps your loss.

Existing configurations are untouched — `percent` remains the default. Compare
the modes in the practice ledger before switching a live engine.

## Corrected US fee model

The backtest priced fees from a per-category table (crypto 0.07, sports 0.03,
geopolitics 0.0). That is an international schedule. Polymarket US charges a
single flat coefficient with no category variation, and it changed: **0.05, then
0.06 effective 1 July 2026**.

`fees_us` now resolves the coefficient from the schedule in force at a given
instant, so a backtest spanning 1 July prices each signal on the rate that
actually applied to it rather than on today's rate. `backtest.us_fee_per_contract`
replaces the category table across `backtest.py`, `replay.py`,
`script_backtest.py` and `research/`. Expect reported fees to move in both
directions: crypto strategies were being over-charged at 0.07, and anything
categorised `geopolitics` was being charged nothing at all.

One deliberate exception: **signals older than the first published schedule**
are priced at the earliest known coefficient, and the report says how many.
`fees_us.coefficient` still raises for such timestamps, so live trading can
never invent a rate; only the backtest fallback
(`coefficient_at_or_earliest`) is permissive.

`backtest.polymarket_fee_per_contract` keeps its old name and per-category
behaviour, but nothing calls it any more. It is retained only so the legacy
numbers stay inspectable; treat it as deprecated.

Tests that assert money now name the schedule they mean, via a `fee_clock`
fixture. Previously they inherited whatever schedule was current on the day they
ran, which is why three broke when 0.06 landed.

## BREAKING: script shadow-trading P&L changes

**If you have saved scripts, their practice results will not match what you saw
before this release.**

Script shadow (practice) fills were settled with the same international
per-category table, via `script_engine._shadow_fee`. They now use the
date-aware US schedule, priced at the moment each shadow order was placed.

What changes, per contract at price P:

| Category | Was | Now (since 1 Jul 2026) |
|---|---|---|
| crypto | 0.07 x P(1-P) | 0.06 x P(1-P) |
| sports | 0.03 x P(1-P) | 0.06 x P(1-P) |
| finance, politics, tech | 0.04 x P(1-P) | 0.06 x P(1-P) |
| **geopolitics** | **0.00 — free** | 0.06 x P(1-P) |
| uncategorised | 0.05 x P(1-P) | 0.06 x P(1-P) |

Research scripts under `research/` moved to 0.06 in the same pass.

Crypto scripts get slightly cheaper. Everything else gets dearer, and
**geopolitics scripts were previously charged no fee at all** — any script whose
practice record looked profitable on geopolitics markets was being flattered by
a fee schedule that does not exist on Polymarket US.

The `ctx` documentation shown in the script editor has been corrected; it
previously told authors the fee was `0.07 x P x (1 - P)`.

Already-settled shadow rows keep the P&L they were written with — this is not a
retroactive rewrite of your history. Only orders settled from this release
forward use the new schedule, so a script's practice record may straddle both.
Re-run the script backtest if you want a clean comparison.

## Known inconsistency: the live crypto engine still assumes 0.07

`crypto15m._fee_cents` — which computes the net edge that gates **live**
crypto15m entries — still uses `FEE_RATE_CRYPTO = 0.07`. It takes a
`fee_schedule` override, but `polymarket_api` hardcodes `fee_schedule: None`,
so 0.07 is always the operative value.

This was left alone deliberately. The error is conservative: at 0.07 the engine
overstates its own cost, so it demands more edge than it needs and passes on
some marginally profitable entries. Correcting it to 0.06 would make the live
engine take **more** trades, which is a risk-increasing change that deserves its
own decision rather than riding along with a fee-accounting release.

The practical consequence until it is changed: crypto15m backtests
(`replay.py`, `script_backtest.py`) now price at 0.06 while the live engine
gates at 0.07, so a backtest will show slightly more entries than live takes.

## Portfolio backtest

`python backtest.py --portfolio` simulates an actual account instead of
averaging one contract per signal.

The per-contract report answers "does this signal have an edge?" It cannot
answer "would this account have made money?", because it ignores a finite
bankroll, position sizing, capital locked in open positions, and the caps that
stop the bot taking every signal it likes. The simulator replays resolved
signals chronologically through the **live** sizing path
(`trader._compute_target_usd`, so percent / contracts / Kelly all behave as
configured), charges the US fee in force at each entry, and enforces max open
positions, per-event caps, the daily new-position cap on your configured
trading day, the exposure cap and the cash reserve.

It reads the trading config from the app's own `settings.json`, and names the
file in the report so you know whose settings produced the numbers.

The output most worth reading is **why signals were not taken**. A large
"at max open positions" count means the strategy found more edge than the
account could act on — a per-contract backtest shows none of that.

```bash
python backtest.py --portfolio --bankroll 2000 --min-confidence 70
```

Limits are printed with every run, not buried here: entry is at the recorded
signal price with no order book or partial fills; positions are held to
settlement, so take-profit and stop-loss are not simulated; equity is carried at
cost between entry and settlement, so drawdown reflects realised settlements
only; and the daily and lifetime loss guards are not modelled. Past settlement
outcomes are not a forecast.

## Verification

New coverage: 11 frozen-clock tests for the trading-day boundary (pinning the
8:30pm ET / 00:30 UTC case that previously reset the stop-loss) and 8 for Kelly
sizing against the closed form. All pass. Renderer and Electron TypeScript both
typecheck.

1002 Python tests pass, up from 828. The three fee tests that were failing are
fixed: they now pin a schedule rather than inheriting the current one. New
suites cover `fees_us` (schedule boundaries, the never-under-reserve invariant,
the historical fallback), the portfolio simulator (each cap binding, capital
recycling, sizing modes, skip attribution), and shadow settlement under both
schedules (including that geopolitics is no longer fee-free).
