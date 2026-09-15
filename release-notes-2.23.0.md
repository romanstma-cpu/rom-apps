# ROM PolyBot 2.23.0

## Evidence-prioritized market selection

- When several live Whale or Momentum candidates compete for limited account capacity, Polybot now considers sources with qualified positive settled-practice evidence first.
- New, unqualified, or conservatively non-positive sources remain at 25% starter priority and size while starter gating is enabled.
- Practice ordering stays unchanged so challenger results remain comparable, and Kelly mode retains its calibrated net-capital-return ranking.
- The rolling evidence plan is cached for five minutes so candidate selection does not repeat its bootstrap calculation every scan.

The selector requires the existing independent-event thresholds across both 30-day and 90-day windows. Missing evidence does not claim an edge. Historical practice results do not guarantee live fills or future profit.
