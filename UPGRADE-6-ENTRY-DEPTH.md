# Upgrade 6: executable depth at entry

Entry checks validated the touch price but never asked how much size rested behind it. A thin book can show an attractive best offer with almost nothing available, and pricing the whole order at that offer overstates the edge. The quote adapter also discarded all size information, so no caller could have checked.

## Depth-bearing quotes

`get_quote` now returns `ask_levels` and `bid_levels` alongside the best prices: price and resting contract size per level, ordered from best to worst. NO is still the mirror of YES, so buying NO consumes the YES bid ladder and its size comes from that side. Zero-size levels are not quotable and never appear.

## Entry sizing

After the risk budget and any market minimum produce an intended size, entry prices that exact quantity against displayed depth:

* Size is reduced to what the book actually shows at or under the limit. It is never increased, and displayed size is rounded down to whole contracts.
* A book that cannot support the minimum tradable size is skipped rather than partially entered.
* The depth-weighted average cost is charged against the signal margin, and the entry is rejected if that margin falls below the execution threshold. An order whose touch looks profitable but whose ladder does not is refused.

Displayed depth is evidence, not a guarantee — resting size can disappear before an order arrives, and queue position is not modelled. `require_entry_depth` defaults to on and can be turned off to restore the previous touch-priced behaviour.

## Validation

14 tests cover depth arithmetic (single level, walking a ladder, refusing to fill beyond displayed size, ignoring levels above the limit, rounding partial sizes down, malformed books) and the entry path (ample depth, shrinking to a thin book, skipping below minimum size, an empty book, the disabled gate, and depth-weighted cost charged before the edge test). Three quote-adapter tests cover level ordering, the NO mirror and zero-size levels.

Existing test quotes were updated to carry depth, matching the live adapter; a `quote_with_depth` helper backfills ample depth for tests whose subject is something else. No profitability improvement is claimed. This narrows which opportunities qualify and makes reported entry cost honest; it does not establish an edge.
