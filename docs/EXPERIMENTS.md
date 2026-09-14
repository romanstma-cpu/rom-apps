# Experiments

## Experiment Cards

### EXP-001 — Practice-first activation
- Hypothesis: We believe new users will understand the safer route if the app
  presents Connect → Limits → Practice before live mode because the next action
  is visible at first use.
- Type: usability test
- Primary metric & threshold (pre-committed): at least 4 of 5 new users start
  practice before attempting live mode, without coaching.
- Guardrail metric: no participant reports that practice places exchange orders.
- Decision rule (pivot / persevere / iterate): persevere at 4/5; otherwise
  rewrite the first-use guidance and retest.
- Result & verdict: pending.

### EXP-002 — Live-order acknowledgement
- Hypothesis: We believe requiring a plain-language acknowledgment will reduce
  accidental live activation because the user must actively confirm the outcome.
- Type: usability test
- Primary metric & threshold (pre-committed): 5 of 5 testers can explain that
  live mode may place real orders before enabling it.
- Guardrail metric: live activation remains reachable after a single
  acknowledgement, without hidden steps.
- Decision rule (pivot / persevere / iterate): persevere if both thresholds
  hold; otherwise revise the acknowledgment copy.
- Result & verdict: pending.

## Experiment Backlog

| Idea | ICE (impact/confidence/ease) | Status |
|---|---|---|
| Guided first-use checklist with practice completion state | 9 / 7 / 7 | Shipped baseline; validate |
| WebSocket staleness and order-rejection circuit-breaker panel | 10 / 8 / 5 | Next |
| Sanitized crash-report export with consent | 7 / 6 / 6 | Planned |
