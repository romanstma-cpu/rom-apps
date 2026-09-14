# ROM Polybot 2.19.0

## Maker-first execution

The main strategy now includes `maker-join`. It improves or joins the best bid
without crossing the current offer, sends the Polymarket US
`participateDontInitiate` flag, and is therefore rejected by the exchange if it
would immediately take liquidity. New installations select this route by
default. Existing saved order-style choices remain unchanged.

Maker entries are rechecked immediately before submission and an unfilled
remainder is canceled after 12 seconds by default. Partial fills remain fully
accounted for while cancellation is confirmed. The app records confirmed maker
fees or rebates, but it does not assume a rebate when sizing a trade.

Practice mode cannot know maker queue position, so its one-shot fills continue
to use conservative taker pricing and dated fees. Portfolio replay requires a
later recorded book to trade through a passive quote and still assumes no maker
rebate.

## Faster market data

The main order path now consumes a full authenticated US WebSocket book when it
is at most two seconds old and falls back to the REST book after reconnects or
during warm-up. The new-install trade scan cadence is five seconds. The private
WebSocket still drives order/fill reconciliation, with bounded REST polling as
a disconnect and maker-expiry fallback.

## Validation

- Full Python backend suite passed, including maker pricing, post-only payload,
  WebSocket freshness, final quote recheck, conservative replay, accounting,
  risk, and recovery tests.
- TypeScript checks, configuration-boundary tests, production frontend build,
  UI audit, packaged backend self-test, packaged Windows startup/settings smoke,
  calibration UI, and portfolio-replay UI passed.
- The native Apple Silicon build runs the backend self-test and packaged app
  smoke test in GitHub Actions, and its disk image is verified before release.
- The Windows installer SHA-256 is published separately. Mac hashes are copied
  from the native release artifacts.

## Profitability status and rollout

This release does not demonstrate improved historical or live returns.
Maker-first routing should reduce entry cost on filled orders, but it can also
lower fill rate and create adverse-selection risk.

Before increasing size, compare crossing with maker TTLs of 6, 12, and 20
seconds under 250/500/1000 ms latency and 25/50/100% depth stress. Track net
return on capital, maximum drawdown, fill rate, cancellation rate, capital
hours, and 5/30/120-second post-fill markout. Require at least 200 terminal
maker attempts across 20 trading days, 50 fills, positive results in both time
halves, and a positive day-block-bootstrap lower bound. Then complete a separate
14-day one-contract forward sample.

The detailed priority roadmap and exact pilot configuration are included in
the desktop source at `docs/QUANT-ROADMAP-2.19.0.md`.

## Platform notes

ROM Polybot requires Polymarket US API credentials. Windows is 64-bit. Mac
Apple Silicon builds require macOS 15 or later and are not Apple-notarized; follow Apple's
documented opening guidance and verify the published hashes.
