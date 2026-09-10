# Upgrade 7: exit discipline

The liquidation path fell back to a **1c sell limit whenever a usable bid was unavailable**. Flatten-on-daily-stop and the take-profit sweep both route through it, so a temporary quote gap could dump a position still worth most of its cost for almost nothing. The fallback was unconditional: a thrown request, a missing bid and a zero bid all produced the same 1c order.

## What an exit now requires

An exit is priced only from a live quote. If the quote request fails, returns no bid, or returns a bid outside a tradable range, the position is held and the reason logged — the code never sells blind. The sweep and flatten paths inherit this without change.

When a quote is available, the exit concedes at most `exit_price_loss_budget_cents` below the touch (default 2c) rather than accepting whatever price clears. Order size is bounded by displayed bid depth at that price, so an exit does not assume the touch absorbs the whole position; the remainder stays open for a later attempt instead of resting far below the market. The price floor of 1c still applies, so a large configured budget cannot produce a nonsensical order.

Holding a position is now a possible outcome of a liquidation request. Callers already treat a zero-sold result as "still holding", and daily-stop flattening logs what remains rather than reporting a clean exit.

## Validation

10 tests cover the removed fallback directly: a missing bid, a failed quote request and a zero bid each keep the position and place no order at all. Others cover the concession budget at its default and at zero, size bounded by displayed bid depth, holding when no bid depth exists, a normal exit still completing, the 1c floor under an oversized budget, and an invalid budget setting falling back to the default.

The take-profit sweep test now states its concession explicitly rather than assuming touch pricing.

No profitability improvement is claimed. This removes a way to lose money to a data gap; it does not improve exit timing. Forecast-based exits and time-based exits remain unimplemented — they need calibrated probabilities, which upgrade 3 gates behind recorded evidence that does not yet exist locally.
