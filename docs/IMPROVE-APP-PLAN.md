# Improve App Plan

## Context

Started 2026-09-14 for ROM Polybot's public-launch safety and reliability
update. The customer job and first-use path are based on a product/code audit;
they still need validation with public users and support evidence.

## Phase Status

| Phase | Skill | Status | Artifact | Date |
|---|---|---|---|---|
| 1 | jobs-to-be-done | awaiting-evidence | CUSTOMER.md | 2026-09-14 |
| 2 | ux-heuristics | done | DESIGN.md, EXPERIMENTS.md | 2026-09-14 |
| 3 | design-everyday-things | done | DESIGN.md, EXPERIMENTS.md | 2026-09-14 |
| 4 | refactoring-ui | pending | DESIGN.md, EXPERIMENTS.md | |
| 5 | microinteractions | pending | DESIGN.md, EXPERIMENTS.md | |
| 6 | made-to-stick | pending | POSITIONING.md, EXPERIMENTS.md | |
| 7 | influence-psychology | skipped: no paywall or in-app upgrade flow | POSITIONING.md, EXPERIMENTS.md | 2026-09-14 |
| 8 | high-perf-browser | pending | DESIGN.md, EXPERIMENTS.md | |
| 9 | steve-jobs-design-review | pending | PRODUCT.md, DESIGN.md, EXPERIMENTS.md | |

Statuses: pending · in-progress · awaiting-evidence · done · deferred: <reason> · skipped: <reason>

## Key Decisions

| Date | Phase | Decision | Rationale |
|---|---|---|---|
| 2026-09-14 | 1 | Treat the first live-trading decision as the highest-risk public flow. | A user can connect real credentials and enable automated orders. |
| 2026-09-14 | 2-3 | Emergency stop pauses the main strategy before a cancellation request. | A liquidation-only control that leaves entry automation armed can create new exposure during an incident. |
| 2026-09-14 | 2-3 | Existing holdings are not sold by Emergency stop. | Selling is irreversible and depends on market liquidity; it requires a separate reviewed action. |

## Next Actions

- [ ] Run five first-use sessions and validate the job statement with real user language. (ROM, before broad public promotion)
- [x] Add execution-health circuit breakers for WebSocket gaps, order rejections, and stale quotes. (ROM, completed 2026-09-16: stale or disconnected WebSocket books cannot be quoted; the UI reports a silent connected stream as degraded while bounded REST quote fallback remains available; repeated quote/order failures pause live entries.)
- [ ] Measure first Practice start, completed practice cycle, and live-enable reversal rate without collecting sensitive credentials. (ROM, public-launch telemetry decision)
- [ ] Complete the cold public-user walkthrough and support/error-state review. (ROM, before paid launch)
