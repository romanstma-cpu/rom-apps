# Upgrade 5: account-wide risk controls

Existing limits were per-engine and per-event. Two gaps remained. Different events can share one underlying outcome — several markets in a tournament, or several releases of one economic series — so a per-event cap did not bound correlated risk. And the daily stop measured only the current trading day, so a slow decline across weeks never breached a single day badly enough to pause anything.

`python/account_risk.py` adds both controls. Neither liquidates a position; both block only new entries.

## Correlated exposure groups

An entry's group is the market's series when the recorded metadata supplies one, otherwise its event, otherwise the ticker itself. Open exposure is summed per group across submitted, partial, filled and unknown positions, so unfilled risk counts the same as filled risk. `max_group_exposure_fraction` bounds what one group may hold as a fraction of bankroll; the remaining allowance is passed into `entry_budget` alongside the existing position, exposure and cash-reserve limits, and the smallest limit wins.

The grouping is deliberately coarse. It cannot detect correlation between different series, and two unrelated series that move together will not be grouped. Portfolio replay applies the same rule from recorded metadata so a backtest cannot show exposure that live trading would refuse.

## Peak-equity drawdown

A high-water mark is recorded per environment and only ever rises. When equity falls from that peak by `max_drawdown_fraction`, new entries pause. A partial recovery still measures against the true peak rather than a fresh low, and `reset_hwm` re-anchors the mark for a deliberate bankroll change. Missing or unreadable equity blocks new entries instead of silently allowing them, matching the existing balance-unavailable rule.

The daily stop also changed: a breach supported by realized, settled results now blocks immediately. The 180-second persistence delay remains only for breaches that depend on unrealized marks, which can flicker.

Both fractions default to zero, so an existing installation keeps its current behaviour until the user opts in on the Strategy screen.

## Validation

18 tests cover group membership and fallbacks, exposure accumulated across separate events, pending orders counting toward a group, budget interaction with sizing, high-water behaviour under decline and partial recovery, missing-evidence blocking, disabled controls and configuration clamping. No profitability improvement is claimed; these controls reduce the size of a bad outcome, they do not create an edge.
