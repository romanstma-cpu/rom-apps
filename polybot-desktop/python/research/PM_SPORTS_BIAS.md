# Favourite-longshot bias on Polymarket sports (2026-07-25)

Evidence behind `examples/sports-favourite-bias.py`.

## Data

`ROM Scout`'s tracker DB (`data/romscout.sqlite`, 54 MB) — not its models,
which are not the asset here:

- **36,407** Polymarket sports markets, **35,784 settled** with a winner
- **128,718** price snapshots stamped at T-1440 / T-360 / T-60 / T-15 minutes
  before game start
- span 2024-04-16 → 2026-07-16
- by sport: tennis 19,039 · soccer 4,323 · mlb 4,203 · nba 3,043 · nhl 2,479 ·
  nfl 1,449 · ncaaf 714 · wnba 467 · ncaab 67

## The market is otherwise very well priced

Calibration at T-60, n=34,710. Implied vs actual win rate:

| band | n | implied | actual | gap |
|---|---|---|---|---|
| 20-30c | 4,437 | 25.0% | 25.2% | +0.2 |
| 40-50c | 6,640 | 45.0% | 45.5% | +0.5 |
| 60-70c | 3,861 | 65.0% | 64.8% | −0.2 |
| 80-90c | 1,648 | 85.0% | 85.9% | +0.9 |

Within ~1 percentage point everywhere. **A better forecasting model will not
find edge here** — which is what ROM Scout's own docs concede when they say
the devigged closing line beats every v1 model. Do not go looking for alpha in
the middle of this curve.

## Nor is there exploitable pre-game drift

| interval | n | mean move | mean abs move | ≥5c moves |
|---|---|---|---|---|
| T-1440 → T-60 | 22,548 | −0.42c | 3.90c | 18.3% |
| T-360 → T-60 | 33,523 | −0.02c | 1.79c | 5.3% |
| T-60 → T-15 | 35,170 | +0.02c | 1.07c | 3.0% |

Prices are a martingale into tip-off. There is no systematic direction to
predict, so "spot the market about to move" has nothing to grip.

## The one real anomaly

Charged the ask (mid + 0.5c spread) and the Polymarket taker fee
`0.07·P·(1−P)`:

| band | offset | n | win% | EV/contract |
|---|---|---|---|---|
| 90-99c | T-60 | 768 | 95.3% | **+1.28c** |
| 90-99c | T-15 | 795 | 95.5% | **+1.38c** |
| 80-90c | T-60 | 1,648 | 85.9% | +0.03c |
| 1-10c | T-60 | 895 | 5.5% | **−2.24c** |

Favourites underpriced, longshots overpriced — **both tails in the direction
theory predicts.** That symmetry is the reason to treat this as a real bias
rather than a mined artifact.

Per sport (T-60, 80-99c): tennis n=2,059 +0.48c · nba n=193 +3.41c ·
ncaaf n=68 −4.93c.

## Fragility — read this before changing anything

| spread paid | 0.0c | 0.5c | 1.0c | 1.5c | 2.0c | 2.5c |
|---|---|---|---|---|---|---|
| EV/contract | +1.75c | +1.28c | +0.82c | +0.36c | **−0.09c** | −0.53c |

The edge dies just above a 1.5c spread. Live measurement on 2026-07-25 found a
**1c median spread** across 21 sports books (favourites n=3, median 1c, ask
depth ~11.5k shares within 1c) — but that was an off-season week and the
in-band sample was tiny. **Re-measure in season before arming.**

Stability by quarter (0.5c spread, 90-99c, T-60):

| quarter | n | win% | EV/ct |
|---|---|---|---|
| 2025-Q4 | 47 | 89.4% | −4.59c |
| 2026-Q1 | 99 | 94.9% | +0.31c |
| 2026-Q2 | 447 | 96.0% | +2.05c |
| 2026-Q3 | 138 | 95.7% | +1.67c |

3 of 4 positive; the negative quarter is the smallest sample.

## Caveats

- Prices are mids from `pm_price_snapshots`; the ask is modelled as mid + half
  the measured spread, not observed directly per trade.
- No depth in the archive — size availability at the touch is unverified
  beyond the live spot-check.
- Measured at **T-60 / T-15 only**. The script sees markets continuously and
  may enter days out, where the bias is unmeasured. `MIN_VOLUME` is a crude
  proxy for proximity to the event.
- Reproduce with the scratch scripts used on 2026-07-25 (calibration, drift,
  stability, live spread) — they read the Scout DB read-only.

## Why this is NOT the crypto deep-favourite trade

The same structural bet on Polymarket **crypto** 15m windows is *negative* in
every band (measured separately against the PMXT archive: 0.95-0.98c band
−0.57c/ct, 0.98-0.99c −0.73c/ct at t=−3.1). Venue and market type matter more
than the shape of the bet. Do not generalise this result to crypto windows.
