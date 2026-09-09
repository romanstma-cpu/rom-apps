# rom-script v1
# name: BTC Price Momentum
# description: Buys the moving side of the BTC up/down window on a 1-minute velocity impulse, while the ask is still cheap.

# Ported from probe_btc_momentum.py, the standalone live probe (approved
# 2026-07-15, ask band tightened 2026-07-17). Same entry logic, but running
# inside the app it gains the money rails, shadow mode, the backtester, and —
# crucially — it no longer requires the Electron app to be CLOSED to avoid
# double-trading the same account.
#
# RUNS ON ITS OWN. Neither the main engine nor the 15m Crypto engine has to be
# switched on: the script engine fetches its own market snapshot (which brings
# the live order-book feed up itself) and manages its own positions to
# settlement. "Scripts live" gates REAL orders; in shadow it ticks the moment
# you enable it, with every other engine off.
#
# THE EDGE — read research/MOMENTUM_OOS.md before touching these numbers.
#   The probe's original justification for the 65c cap was 20 live fills
#   (>65c lost $5.78 over 11, <50c made $9.76 over 4) plus a "+28.50c/ct,
#   t=6.6" replay figure that exists only in a comment with no artifact and
#   no stated sample size.
#
#   Out-of-sample over 4,751 real BTC 15m windows from the PMXT book archive
#   (2026-07-25), that justification does NOT hold up — but neither does
#   removing the cap. The 65-80c band is +10.48c/ct if you assume you fill at
#   the ask you saw, and -0.12c/ct (t=-0.0) once you require the quote to
#   have survived 15s and still be there 5s later. So the cap is roughly
#   NEUTRAL, not the load-bearing filter it was described as.
#
#   The wider lesson from that run: under optimistic fills every price band
#   looks profitable and 20-40c looks spectacular (+20c/ct, t>10, positive in
#   9 of 9 weeks) — but ~95% of those entries vanish under an honest fill
#   test. The apparent edge lives in quotes that don't persist. Only the
#   1-10c band survives with both size and significance (+5.22c/ct, t=3.0,
#   n=266).
#
#   The archive is top-of-book only, so it cannot tell us whether size was
#   available at those cheap asks. That is exactly what a SHADOW run settles.
#   Until then these bands are unchanged from the validated live probe.
#
# HOLD TO SETTLEMENT — deliberately no take_profit_pct and no
# stop_loss_cents. This is not an oversight. The engine-wide
# exit_threshold=0.40 once fired on 3 of the first 6 live momentum fills
# (2026-07-16), one of them 19 SECONDS after entry, triggered by the lagging
# Gamma mid while the real book sat 20c higher. The backtest never modeled
# those exits, so trading them would not be trading what was validated.
# Returning no exit fields is what makes this safe: the engine's exit ladder
# skips its own knobs entirely for script positions and honours only what an
# intent sets.
#
# NOTE ON SIDE SELECTION: the standalone probe had to run in "contrarian"
# direction_mode purely to dodge the built-in 95c favourite floor (Gate 1b),
# which killed these cheap-side entries as "favourite flipped". Scripts don't
# go through that gate at all, so no such workaround is needed here.
#
# SETTINGS THIS EXPECTS (Scripts page rails):
#   Max entry     >= 65c   (the band below is the real limit)
#   Max size      >= 5     (Polymarket's 5-share per-order minimum)
#   Max open      = 5      (the probe ran max 5 concurrent; default is 2)
#   Daily loss    = 20     (the probe's -$20 stop)
# The window length follows the app's configured crypto interval (the probe
# was validated on 15m) — a script cannot pick the series itself.
#
# BANKROLL. Every entry is at least 5 contracts, and marketable buys under $1
# notional are rejected, so one entry costs ~$1.00 at 20c and ~$3.25 at the 65c
# cap. Running the probe's 5 concurrent positions needs roughly $16 to do it
# properly. Below that the engine now REFUSES unaffordable entries (rather
# than sending them to bounce), so a thin balance shows up as refusals in the
# ledger instead of trades — shadow it until the account can fund the band.

VELOCITY_THRESHOLD = 0.1     # percent move over the last minute
ASK_MIN = 0.01               # never "buy" a phantom 0c quote
ASK_MAX = 0.65               # the hard-won cap — see above
ORDER_SIZE = 5               # contracts; the rails cap this, and the engine
                             # sizes UP when $1 min-notional needs more


def decide(ctx):
    # BTC only. The probe was validated on BTC alone; the other coins have
    # their own volatility profiles and were never part of that sample.
    #
    # Kept as an in-script check on purpose. Each script also has its own
    # `Coins:` scope on the Scripts page, which would do the same thing — but
    # the guard travels with the code, so exporting or sharing this script
    # can't lose it. (What it is NOT is the 15m Crypto tab's asset
    # checkboxes; those no longer touch scripts at all.)
    if ctx["asset"] != "BTC":
        return None

    vel = ctx["velocity1mPct"]
    if vel is None:
        return None                      # no spot feed this tick

    if vel > VELOCITY_THRESHOLD:
        side = "up"
        ask = ctx["upAsk"]
    elif vel < -VELOCITY_THRESHOLD:
        side = "down"
        ask = ctx["downAsk"]
    else:
        return None                      # no impulse

    # upAsk/downAsk are REAL order-book asks. None means there is no live book
    # on that side right now — never trade a phantom quote.
    if ask is None:
        return None
    if not (ASK_MIN <= ask <= ASK_MAX):
        return None                      # outside the profitable band

    return {
        "side": side,
        "price": "ask",                  # taker: cross the real book now
        "size": ORDER_SIZE,
        # No take_profit_pct / stop_loss_cents => hold to settlement.
        "reason": f"vel1m {vel:+.2f}% @ {ask:.2f}",
    }
