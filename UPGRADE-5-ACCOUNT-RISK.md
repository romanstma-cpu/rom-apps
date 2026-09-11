# Upgrade 5: account-wide risk controls

Existing limits were per-engine and per-event. Two gaps remained. Different events can share one underlying outcome — several markets in a tournament, or several releases of one economic series — so a per-event cap did not bound correlated risk. And the daily stop measured only the current trading day, so a slow decline across weeks never breached a single day badly enough to pause anything.

`python/account_risk.py` adds both controls. Neither liquidates a position; both block only new entries.

## Correlated exposure groups

An entry's group is the market's series when the recorded metadata supplies one, otherwise its event, otherwise the ticker itself. Open exposure is summed per group across submitted, partial, filled and unknown positions, so unfilled risk counts the same as filled risk. `max_group_exposure_fraction` bounds what one group may hold as a fraction of bankroll; the remaining allowance is passed into `entry_budget` alongside the existing position, exposure and cash-reserve limits, and the smallest limit wins.

The grouping is deliberately coarse. It cannot detect correlation between different series, and two unrelated series that move together will not be grouped. Portfolio replay applies the same rule so a backtest cannot show exposure that live trading would refuse.

**Correction, 2026-09-10.** As shipped, the series branch could never fire. `markets.series_ticker` is written from the market payload and no producer of that payload supplies a series, so every group fell back to the event and the cap bounded only what `max_positions_per_event` already bounded — the tournament case above was described but not implemented. The series is only carried by the events feed, so the group is now resolved as `markets.series_ticker`, then the market's row in `events`, then the event, then the ticker. Portfolio replay resolves the same chain rather than reading recorded metadata, which never contained a series; series membership is static, so reading it at replay time is not look-ahead. Installations with no events data, or with events carrying no series, are unaffected, and `max_group_exposure_fraction` still defaults to zero. The change can only tighten: merging event groups into one series group raises the exposure counted against an entry and so can only shrink its remaining allowance. See DECISIONS.md.

**Second correction, 2026-09-11.** The cap was account-wide in what it counted and per-engine in what it enforced. `GROUP_SQL` sums main-strategy and crypto15m positions, so all three engines' fills raised a group's usage — but only `trader` ever read the remaining allowance. crypto15m and copy_trader could open past a limit their own positions were helping to fill, and crypto15m is the engine most exposed to it: every 15-minute window on one asset shares a series and moves with the same spot price, which is precisely the correlation this control exists to bound. Both engines now consult the cap before sizing an entry and refuse one when the group is full.

Two details make that honest rather than nominal. A prospective crypto15m entry is keyed by `series or ticker`, matching how `GROUP_SQL` buckets the row that entry will become — routing it through `group_key` instead would consult `markets`, which crypto15m rows are not joined against, and could measure an entry against a different group's usage. And each engine reads group exposure once per tick and charges its own commitments against that reading as it goes, so several entries in one pass cannot each be granted the same correlated dollars. The bankroll a fraction is measured against is now defined once, in `cap_bankroll_usd`; all three engines had computed cash-plus-filled-cost separately, and a cap is only account-wide while they keep computing the same number.

This can only tighten. `max_group_exposure_fraction` still defaults to zero, which disables the control rather than reading as a cap of zero.

## Peak-equity drawdown

A high-water mark is recorded per environment and only ever rises. When equity falls from that peak by `max_drawdown_fraction`, new entries pause. A partial recovery still measures against the true peak rather than a fresh low, and `reset_hwm` re-anchors the mark for a deliberate bankroll change. Missing or unreadable equity blocks new entries instead of silently allowing them, matching the existing balance-unavailable rule.

The daily stop also changed: a breach supported by realized, settled results now blocks immediately. The 180-second persistence delay remains only for breaches that depend on unrealized marks, which can flicker.

Both fractions default to zero, so an existing installation keeps its current behaviour until the user opts in on the Strategy screen.

## Validation

18 tests cover group membership and fallbacks, exposure accumulated across separate events, pending orders counting toward a group, budget interaction with sizing, high-water behaviour under decline and partial recovery, missing-evidence blocking, disabled controls and configuration clamping. A further 25 cover the second correction: the shared bankroll definition, prospective-entry keying round-tripped against the row it becomes, refusal and size reduction in both engines, intra-tick accumulation, unrelated series left alone, and both engines unchanged while the control is off. 23 of the 25 were confirmed to fail against the previous source. No profitability improvement is claimed; these controls reduce the size of a bad outcome, they do not create an edge.
