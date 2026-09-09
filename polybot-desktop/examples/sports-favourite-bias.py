# rom-script v1
# name: Sports Favourite Bias
# description: Buys deep favourites on sports markets and holds to settlement, exploiting the favourite-longshot bias.

# RUNS ON ITS OWN
#   This uses decide_market(), which is fed from the app's market table — kept
#   in sync unconditionally, so neither the main engine nor the 15m Crypto
#   engine has to be switched on. "Scripts live" gates REAL orders; in shadow
#   it starts building a ledger the moment you enable it.
#
# WHAT THIS IS
#   Betting markets have a well-documented favourite-longshot bias: longshots
#   are overbet and favourites underbet. This buys the favourite side of sports
#   markets when it is priced 90-99c and holds to settlement. It needs NO
#   forecast of who wins — the edge comes from the market's own pricing, not
#   from being smarter than it.
#
# THE EVIDENCE (research/PM_SPORTS_BIAS.md, measured 2026-07-25)
#   36,407 Polymarket sports markets with settled winners:
#     90-99c favourites : n=768  win 95.3%  EV +1.28c/contract  (at a 0.5c spread)
#      1-10c longshots  : n=895  win  5.5%  EV -2.24c/contract
#   The effect appears on BOTH tails in the direction theory predicts, which is
#   why it reads as a real bias rather than a data-mined artifact. 3 of 4
#   quarters positive; the largest (n=447) at +2.05c.
#
#   Calibration across 34,710 markets is otherwise within ~1 percentage point
#   in every price band — this is the ONE place the market is systematically
#   off. Do not expect to find edge anywhere else in the price curve.
#
# WHY IT MUST HOLD TO SETTLEMENT
#   A round trip on Polymarket costs 1.4-4.5c (1c spread + two taker fees).
#   Settlement is FREE. An edge of ~1.3c/contract cannot survive being traded
#   in and out — it only exists if you hold. Hence no take_profit_pct and no
#   stop_loss_cents: the engine's exit ladder skips its own knobs entirely for
#   script positions, so returning neither means hold-to-settlement.
#
# THE ASSUMPTION THAT CAN KILL IT
#   The edge dies above a ~1.5c spread:
#       spread paid   0.0c    1.0c    1.5c    2.0c
#       EV/contract  +1.75c  +0.82c  +0.36c  -0.09c
#   Live spreads measured 1c median, but on a thin off-season sample (n=3 in
#   band). That is why SPREAD_MAX_CENTS below is a hard gate rather than a
#   preference — if the book is wide, the edge is already gone.
#
# KNOWN LIMITATION — read before arming
#   The archive measured prices 15 and 60 minutes before game start. This
#   script sees markets continuously and will buy whenever the price is in
#   band, possibly days out, where the bias is unmeasured. MIN_VOLUME is a
#   crude proxy for "close to the event" (interest builds near tip-off). If
#   you can, watch the shadow ledger for entries taken far from settlement
#   and judge whether they behave like the archive.

# BANKROLL — this strategy is expensive per entry BY CONSTRUCTION
#   It buys 90-99c favourites, and every order is at least 5 contracts, so the
#   cheapest possible entry is 5 x 90c = $4.50 and a 99c entry is $4.95. There
#   is no way to take this trade for less; the edge lives at the top of the
#   price curve. SIZE_USD below is what you actually want per entry (~$10 =
#   ~11 contracts at 90c).
#
#   On an account that cannot fund $4.50 the engine now REFUSES these entries
#   before the exchange call rather than letting them bounce, so an underfunded
#   run shows up as refusals in the ledger. Shadow costs nothing and needs no
#   balance — that is the right way to run this until the account can cover it.

FAV_MIN = 0.90            # below this the bias is not reliably present
FAV_MAX = 0.99            # at 99c the max possible gain is 1c — not worth the risk
MIN_VOLUME_24H = 5000.0   # traded TODAY — a live game, not a dormant listing
MAX_HOURS_TO_CLOSE = 36.0  # see note; the bias was measured on imminent games
SIZE_USD = 10.0           # dollars per entry; the rails cap this

# WHY THE CLOSE-TIME GATE MATTERS MORE THAN IT LOOKS
#   Measured on the live board (2026-07-25): most sports markets sitting in the
#   90-99c band are NOT pre-game moneylines. They are long-dated futures
#   ("will the Pacers win the 2027 NBA Finals" at 2c => the NO side is 98c) and
#   spread/handicap derivatives. Buying those and "holding to settlement" means
#   locking capital up for MONTHS at a ~1c edge — a completely different trade
#   from the one the archive measured, which priced games 15-60 minutes before
#   tip-off. Without this gate the strategy quietly becomes a long-duration
#   bond with terrible carry.

# Derivative markets — spreads, totals, alternate lines. The archive measured
# straight game winners only, so these are out of sample.
_EXCLUDE = ("-spread-", "-over-", "-under-", "-total-", "-handicap-", "-pt5")

# NOTE ON THE SPREAD GATE
#   The edge dies above a ~1.5c spread, so that check is essential — but it
#   canNOT be done here. The market rows a script sees come from Gamma's list
#   endpoint, which returns ONE price that is stored as both bid and ask, so
#   `spreadCents` is None (it used to compute a fake, constant 0.0c). The real
#   two-sided book only exists at submit time, so the engine enforces it there
#   via the "Max spread" rail at the top of the Scripts page (default 2c). Set
#   it to 1-2c for this strategy.
#
#   The submit-time quote is also what sizes the order: the engine bounds the
#   notional so a fill below the limit cannot take more contracts than the
#   Max size rail allows. Before that fix a stale quote bought 40% extra size
#   on a live account (2026-08-03).


def decide_market(market):
    if market["category"] != "sports":
        return None

    # 24h volume, not lifetime: a long-dated novelty market can show millions
    # in lifetime volume while nothing trades today.
    if market["volume24h"] < MIN_VOLUME_24H:
        return None

    # Imminent games only — see the note above.
    hrs = market["hoursToClose"]
    if hrs is None or hrs <= 0 or hrs > MAX_HOURS_TO_CLOSE:
        return None

    slug = market["slug"]
    for bad in _EXCLUDE:
        if bad in slug:
            return None

    # Buy whichever side is the deep favourite. Exactly one side can be
    # >= 90c, so there is no ambiguity about which to take.
    yes_ask = market["yesAsk"]
    no_ask = market["noAsk"]

    if yes_ask is not None and FAV_MIN <= yes_ask <= FAV_MAX:
        side, ask = "yes", yes_ask
    elif no_ask is not None and FAV_MIN <= no_ask <= FAV_MAX:
        side, ask = "no", no_ask
    else:
        return None

    return {
        "side": side,
        "price": "ask",          # taker; the live book is re-checked at submit
        "sizeUsd": SIZE_USD,
        # No exit fields => held to settlement. See note above.
        "reason": f"fav {ask:.2f}",
    }
