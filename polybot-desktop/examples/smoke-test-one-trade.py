# rom-script v1
# name: Smoke Test - One Real Trade
# description: Places ONE real, minimum-size crypto trade to prove the script engine works end to end, then stops.

# THIS IS NOT A STRATEGY. It has no edge and is not trying to have one.
# Its only job is to prove the pipeline works on a live account:
#
#     enable -> tick -> decide() -> rails -> real order -> fill -> settle -> P&L
#
# It exists to verify that a script trades with the MAIN and CRYPTO engines
# switched OFF — i.e. that "Scripts live" alone is enough.
#
# IT SPENDS REAL MONEY. Expect to lose the stake more often than not: it buys
# a ~20-35c side, so it wins roughly 20-35% of the time. Budget it as the cost
# of a test, not as a bet. Delete or disable it once it has fired once.
#
# ─────────────────────────────────────────────────────────────────────────
# WHY 20-35c — the arithmetic of a small balance
#
# Polymarket rejects orders under 5 contracts, AND marketable buys under $1
# notional. Together those set the real minimum spend:
#
#     ask    contracts   cost     why
#     ---------------------------------------------------------------
#      5c       20      $1.00     min-notional inflates size to reach $1
#     15c        7      $1.05     "
#     20c        5      $1.00     floor size AND exactly $1 - the sweet spot
#     35c        5      $1.75     floor size
#     65c        5      $3.25     floor size
#     85c        5      $4.25     floor size - too expensive on a small balance
#
# Below ~5c the $1 rule needs >20 contracts, which breaches the default Max
# size rail, so the entry is REFUSED rather than silently upsized past your
# cap. 20-35c is therefore the cheapest band that both clears the exchange
# minimums and keeps the stake near $1.
#
# ─────────────────────────────────────────────────────────────────────────
# SETTINGS (Scripts page, top bar)
#   Scripts live      ON            <- the only switch that should be on
#   Max open/script   1             <- belt and braces; the script self-limits
#   Daily loss stop   3             <- belt and braces on a small balance
#   Max entry / size  leave default (97c / 20)
#
# The main engine and the 15m Crypto engine can both stay OFF. That is the
# point of the test. The Crypto tab's INTERVAL still selects which window
# series exists (5m / 15m / hourly) — set it to 15m for a 15-minute test.
#
# It holds to settlement (no take-profit, no stop-loss), so the whole
# lifecycle completes within one window and the result lands in History.

BAND_MIN = 0.20          # cheapest ask we will cross (also the $1-notional point)
BAND_MAX = 0.35          # dearest ask we will cross (5 contracts = $1.75)
CONTRACTS = 5            # the exchange floor - never more
MAX_ATTEMPTS = 1         # ONE intent, full stop - see the note below
MIN_MINS_LEFT = 1.5      # don't fire into the final minute (the engine blocks it)
CASH_BUFFER = 0.25       # leave this much unspent so a fee can never bounce


# WHY MAX_ATTEMPTS IS THE GUARD THAT MATTERS (learned the hard way,
# 2026-08-03: this script fired TWICE and spent $3.14 instead of ~$1.50)
#
#   `state["attempts"]` is incremented SYNCHRONOUSLY inside decide(), so it is
#   the only counter that can stop a second entry in the SAME tick. The engine
#   offers every coin in one pass, so two entries land ~1 second apart.
#
#   The other two guards cannot help there:
#     - `state["filled"]` is set by on_fill(), which does not run until a LATER
#       tick once the fill is detected. Both orders are long gone by then.
#     - `Max open/script` is a rail you have to set correctly by hand; at its
#       default of 2 it permits exactly the double-entry seen above.
#
#   So the script guarantees "one trade" itself rather than trusting a setting.


def on_start(state):
    # Runs once when the script loads (and again after any code edit).
    state.setdefault("attempts", 0)
    state.setdefault("filled", 0)
    log("smoke test armed - will place ONE real order of "
        f"{CONTRACTS} contracts in the {BAND_MIN:.0%}-{BAND_MAX:.0%} band")


def decide(ctx):
    # ── stop conditions, checked before anything else ────────────────────
    if state.get("filled"):
        return None                       # already proved the point
    if state.get("attempts", 0) >= MAX_ATTEMPTS:
        return None                       # don't grind the balance away

    mins = ctx["minsLeft"]
    if mins is None or mins < MIN_MINS_LEFT:
        return None

    # ── affordability, which the ENGINE does not check for scripts ───────
    # The built-in crypto engine skips when the balance can't fund an order;
    # the script path does not, so an unaffordable intent would be sent and
    # rejected by the exchange, landing as a confusing `error` row. Check here.
    bal = ctx["portfolio"]["balanceUsd"]

    # ── pick whichever side has a REAL book inside the band ──────────────
    # upAsk/downAsk are the live order book. None means there is no executable
    # quote on that side this tick - crossing it would do nothing useful.
    for side, ask in (("up", ctx["upAsk"]), ("down", ctx["downAsk"])):
        if ask is None or not (BAND_MIN <= ask <= BAND_MAX):
            continue

        cost = CONTRACTS * ask
        if bal is not None and cost > bal - CASH_BUFFER:
            log(f"skip {ctx['asset']} {side} @ {ask:.2f}: needs ${cost:.2f}, "
                f"balance ${bal:.2f}")
            continue

        state["attempts"] = state.get("attempts", 0) + 1
        log(f"ATTEMPT {state['attempts']}/{MAX_ATTEMPTS}: {ctx['asset']} {side} "
            f"x{CONTRACTS} @ ~{ask:.2f} (~${cost:.2f}), {mins:.1f}m left")
        return {
            "side": side,
            "price": "ask",               # taker: cross the real book now
            "size": CONTRACTS,
            # No take_profit_pct / stop_loss_cents => hold to settlement, so
            # the test completes inside one window.
            "reason": f"smoke test @ {ask:.2f}",
        }
    return None


def on_fill(position, state):
    state["filled"] = state.get("filled", 0) + 1
    log(f"FILLED: {position['contracts']} x {position['asset']} "
        f"{position['side']} @ {position['avgEntryCents']}c "
        "- the script engine placed a real order. Test passed.")


def on_settle(position, state):
    outcome = "WON" if position["won"] else "lost"
    log(f"SETTLED {outcome}: {position['asset']} {position['side']}, "
        f"P&L ${position['pnlUsd']:.2f}. Disable this script now.")
