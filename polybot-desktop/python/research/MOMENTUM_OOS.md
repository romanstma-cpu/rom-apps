# BTC 15m momentum — out-of-sample findings (2026-07-25)

Reproducible record of what the PMXT archive actually says about the BTC 15m
price-momentum strategy (`velocity1mPct > ±0.1` → buy that side).

Written down because the previous headline number for this strategy —
*"+28.50c/ct at 0.65 vs +27.95c at 0.80, t=6.6"*, quoted in
`probe_btc_momentum.py` — exists **only in a code comment**. There is no
artifact, no stated sample size, and no way to reproduce it, so it could not
be evaluated. Don't let these numbers end up the same way.

## Data

`research/data/pmxt_btc15m.db`, built by `pmxt_backfill.py` from the public
PMXT archive (`r2v2.pmxt.dev`, CC-BY 4.0):

- **4,751** BTC 15m windows with book data, every one with a settled outcome
- **10.8M** top-of-book ticks (`best_bid` / `best_ask`, ~5s grid)
- **80,340** 1-minute BTC closes (the `velocity1mPct` source)
- ~2026-04-29 → 2026-07-08 (9 ISO weeks, W25/W26 missing)

Fees modeled at the real taker curve `0.07 * P * (1-P)`. One entry per window.
The final minute of each window is blocked, matching live.

## Reproduce

```bash
cd python
.venv/Scripts/python.exe research/pmxt_backfill.py simulate            # headline
.venv/Scripts/python.exe research/momentum_cap_sweep.py                # cumulative caps
.venv/Scripts/python.exe research/momentum_band_stability.py           # isolated bands + weekly
```

## Fill models (this is the whole story)

- **baseline** — fill at the ask observed on the tick the signal fires.
- **combined** — fill only if that ask was *unchanged for the previous 15s*
  AND was *still within 1c 5s later*; fill at the later price.

`combined` is the honest one. It approximates "was this quote actually
there long enough to hit."

## Result

Isolated price bands (not cumulative caps — a cap mixes bands and lets one
strong band carry everything under it):

| ask band | baseline n | baseline net | honest n | honest net | honest t | weeks + |
|---|---|---|---|---|---|---|
| 0.01–0.10 | 449 | +11.19c | **266** | **+5.22c** | **3.0** | 7/9 |
| 0.10–0.20 | 505 | +18.29c | 49 | +4.33c | 0.8 | 5/9 |
| 0.20–0.30 | 610 | +20.64c | 35 | +17.59c | 2.1 | 8/9 |
| 0.30–0.40 | 752 | +22.02c | 28 | +10.13c | 1.1 | 6/8 |
| 0.40–0.50 | 1427 | +7.75c | 315 | **-2.76c** | -1.0 | 2/9 |
| 0.50–0.65 | 2352 | +3.01c | 714 | +0.98c | 0.5 | 6/9 |
| 0.65–0.80 | 1471 | +10.48c | 67 | -0.12c | -0.0 | 5/9 |
| 0.80–0.95 | 1288 | +4.91c | 149 | +3.83c | 2.0 | 6/9 |

**Under baseline fills every band is positive and 0.20–0.40 looks
spectacular (+20c/ct, t>10, 9/9 weeks). Under honest fills ~95% of those
entries disappear** — 1,362 baseline entries in 0.20–0.40 become 63. The
edge was concentrated in quotes that don't persist.

What survives with both meaningful n and significance: the **1–10c** band
(+5.22c/ct, t=3.0, n=266) and marginally the **80–95c** band (+3.83c/ct,
t=2.0, n=149). The 40–50c band is outright negative.

## Conclusions

1. **The 65c ask cap is not supported, but nor is removing it.** It was fit
   to 20 live fills. Out-of-sample the 65–80c band is +10.48c/ct under
   baseline fills but **-0.12c/ct (t=-0.0) under honest fills** — i.e. the
   cap is roughly neutral. Leave it; don't cite the old justification.
2. **Do not retune on the baseline model.** It is optimistic in exactly the
   region that looks most attractive.
3. **The archive cannot settle this.** It is top-of-book only, with no
   depth, so it cannot tell whether size was available at those cheap asks —
   which is precisely what the honest-fill haircut is warning about. Only a
   live shadow run can.
4. **Watch the daily-stop interaction.** The most robust variant (1–10c) has
   an ~8.6% win rate. At ~5c entries the $1 min-notional forces ~20
   contracts, so a run of ~20 losses is both likely and enough to trip a
   -$20 daily stop. A strategy can be +EV and still be shut off by its own
   breaker.

## Status

No parameter changes made. `examples/btc-momentum.py` is a faithful port of
the live probe and should be run in **shadow** first — shadow uses real live
asks and real outcomes, which is the only thing that resolves (3).
