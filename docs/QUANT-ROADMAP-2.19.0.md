# ROM PolyBot quantitative roadmap — 2.19.0

This plan targets net return after fees, rebates, slippage, failed fills, and
capital lockup. No item is treated as profitable until it passes the stated
out-of-sample and forward gates.

## Audit findings and priority

0. **Qualified live edge gate — implemented after 2.24.0.**
   Every live Whale and Momentum entry now requires a recent calibration bucket
   that passed chronological holdout accuracy and after-cost return checks.
   The rule applies to percent, fixed-contract, and Kelly sizing. Practice keeps
   observing all otherwise eligible candidates so evidence collection does not
   stop when live entries are blocked.

1. **Maker-first execution and WebSocket routing — implemented in 2.19.0.**
   The main engine crossed the spread by default and fetched its decision book
   over REST even while the US market WebSocket already held a fresh full-depth
   book. This paid taker fees and added latency. `maker_join` now improves or
   joins the bid without crossing, submits with `participateDontInitiate=true`,
   rechecks the exact price immediately before POST, and cancels an unfilled
   remainder after a short TTL. A WebSocket book at most two seconds old is
   used first; REST remains the fail-safe. Rebates are recorded when confirmed
   but are never assumed for sizing.

2. **Adverse-selection and inventory controller — next.**
   A passive fill can be a warning that informed flow moved through the quote.
   Add per-market inventory targets, skew quotes away from accumulated risk,
   cancel when microprice or short-horizon trade imbalance moves against the
   quote, and cool down after a toxic fill. Start with one-sided signal-backed
   quotes; do not quote both sides until self-match prevention and exchange
   position semantics are verified live.

3. **Incentive-aware market selection.**
   Read `/v1/incentives`, estimate reward per unit of displayed size from
   confirmed earnings, and rank only after normal expected P&L. Never count an
   advertised pool as certain income. Require at least 20 terminal attempts on
   10 days before learned fill rates can influence selection.

4. **US mutually-exclusive-event optimization.**
   Model the exchange's mutually exclusive collateral return at the portfolio
   level and compare complete event payoff vectors. Trade a basket only when
   every outcome remains positive after fees, quote latency, and a one-tick
   stress. This is the US analogue relevant to the requested NegRisk work;
   it is not the international wallet/CLOB NegRisk mechanism.

5. **Cross-venue arbitrage observation, then execution.**
   Build read-only normalized contracts for each venue, with explicit mapping
   confidence, resolution-rule equivalence, executable depth, withdrawal and
   funding costs, and venue-specific legal/account eligibility. Promote a pair
   to paper trading only at 100% contract-rule match. Live execution requires
   credentials and pre-funded capital on both venues; a price difference alone
   is not arbitrage.

6. **Quote replacement and batched routing.**
   After maker behavior is measured, use `/v1/order/{id}/modify` to retain a
   competitive quote subject to a maximum replace rate. Use batches only for
   atomic strategy intent; exchange responses must still be confirmed through
   the private WebSocket because echoed IDs do not prove individual success.

7. **Portfolio circuit breakers.**
   Extend current daily, lifetime, group-exposure, and high-water controls with
   rolling execution-loss, WebSocket-gap, rejection-rate, and quote-staleness
   breakers. A trip cancels resting orders first and blocks new entries; forced
   liquidation remains an explicit setting because crossing a thin book can
   increase loss.

## 2.19.0 implementation parameters

```json
{
  "orderStyle": "maker_join",
  "makerOrderExpirationSec": 12,
  "tradeScanInterval": 5,
  "positionPollInterval": 30,
  "sizingMode": "kelly",
  "kellyFraction": 0.25,
  "maxTotalExposureFraction": 0.50,
  "maxGroupExposureFraction": 0.15,
  "maxDrawdownFraction": 0.15,
  "minCashReserveFraction": 0.10,
  "stopLossOnDay": -25,
  "lifetimeLossLimitPct": 0.20,
  "flattenOnDailyStop": false,
  "requireEntryDepth": true
}
```

The first three values are the new-install execution defaults where applicable.
The remaining values are the conservative pilot profile, not silently applied
to existing users. Kelly mode will wait until its calibration group has enough
qualified held-out evidence.

## Backtest and paper-trade gates

Run a chronological comparison with identical signals and risk limits:

- Route A: `limit_cross`, dated taker fees, recorded depth and 250/500/1000 ms
  latency stress.
- Route B: `maker_join`, 6/12/20 second TTL, 250/500/1000 ms latency, 25/50/100%
  displayed-depth stress, no assumed maker rebate, and a fill only after the
  recorded market trades through the quote. Queue position remains unknown.
- Split by market, source, category, price band, spread, time to close, and UTC
  day. Deduplicate by event and keep all tuning before the final time split.
- Primary metric: net return on capital. Guardrails: max drawdown, worst day,
  fill rate, post-fill 5/30/120-second markout, cancellation rate, and capital
  hours per filled trade.

Promotion requires at least 200 terminal maker attempts over 20 trading days,
50 fills, a positive day-block-bootstrap lower bound for net return, positive
results in both chronological halves, and no worse drawdown than crossing.
Then run a separate 14-day paper/one-contract forward sample. Scale only after
confirmed fills show positive net P&L and non-negative 30-second markout. Start
at 10% of the intended cap, then 25%, 50%, and 100%, with a new review at each
stage.

## Code-level changes

- `python/us_market_stream.py`: exposes freshness-bounded full books.
- `python/polymarket_api.py`: adds WebSocket-first quote routing and post-only
  order payloads.
- `python/execution_quality.py`: adds a non-crossing maker price policy.
- `python/trader.py`: adds conservative fee treatment, final quote validation,
  maker telemetry, and short maker-order expiry.
- `python/service.py`: polls quickly enough to enforce the maker TTL even when
  the private WebSocket is quiet.
- Desktop config and Main Engine UI expose the route and TTL with validation.

Official assumptions rechecked 17 September 2026: Polymarket US documents a 0.0695
taker coefficient, a -0.0125 maker coefficient, exchange-enforced
`participateDontInitiate`, a 20-request-per-second retail limit, authenticated
market/private WebSockets, and mutually-exclusive collateral return. Recheck
those documents before every production fee or margin change.
