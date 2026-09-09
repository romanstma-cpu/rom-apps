# Upgrade 1: US order accounting and recovery

Scope: durable submission and cancellation handling in the shared US adapter;
main-strategy entry/exit reconciliation. Strategy scoring, market selection,
backtesting and sizing parameters are unchanged. No authenticated orders were
placed during development.

## What changed

- The main strategy writes its position intent before awaiting submission. The
  shared US adapter commits its own journal with SQLite FULL synchronization
  before POST, covering submissions from other engines as well.
- Sending, unknown, cancel-pending and incomplete-accounting journal entries
  block further adapter submissions. An interrupted process retains this state.
- Every local order ID is single-use. It is not sent as an undocumented exchange
  idempotency field. No submission is retried automatically.
- A 400/401/403/422 rejection releases the intent. Timeouts, missing IDs and
  uncertain responses retain it. Repeated 404s do not mean canceled.
- Cancellation is confirmed by reading the order again. A fill racing a cancel
  remains a fill; pending cancellations retain the reservation.
- Authenticated private order updates store deduplicated executions with prices,
  quantities and fees. Cumulative order snapshots recover disconnect gaps through
  REST. Balance/position events trigger existing account reconciliation.
- A missing average fill price is not replaced by the limit price. Missing
  cumulative fees and fractional fills stop automatic accounting instead of
  silently inventing costs or rounding quantities. The legacy trading engines
  still use whole contracts; fractional execution requires operator attention.
- Main entry costs include reported entry fees. Partial fills retain the
  reservation for unfilled contracts. Main exits use immutable original basis
  and cumulative net proceeds, so duplicate or late fills cannot book twice.
- History reset is blocked while journaled risk remains open or unresolved.

## Recovery

Known exchange IDs reconcile automatically through REST and private updates.
With no exchange ID, the bot remains paused: time/price similarity and absence
from open orders are not proof that a submission failed.

For support-assisted recovery, inspect the journal and exchange order history.
The existing backend `runOnce` handler accepts `action: recoverOrder`,
`localOrderId`, and `exchangeOrderId`. It fetches the order using the account's
authenticated REST API and validates market, intent, quantity and limit price
before linking it. The operator must choose the correct exchange order; matching
fields alone cannot prove identity. An order with no identifiable exchange
record needs exchange confirmation; there is deliberately no automatic
"forget unknown order" path.

Journal tables in the existing profile database:
`us_order_intents`, `us_order_snapshots`, `us_executions`, `us_exit_basis`,
`us_exit_orders`. No credentials are stored in these tables. Unknown fee fields
remain unknown. The execution archive starts with this version; it is not a
complete historical exchange feed. Manual external trades and advanced engines'
legacy P&L paths are not claimed to be fully covered by main-strategy accounting.

## Validation

Isolated temporary databases and mocked exchange responses cover durable
pre-submit writes, process cancellation, timeouts, missing acknowledgements,
single-use IDs, definitive rejection, partial fills, duplicate/out-of-order
events, execution-before-ack, fractional fills, missing prices/fees, cancel/fill
races, repeated 404s, recovery by authenticated ID, late exit fills, mixed
partial-exit/settlement P&L and reset protection.

This upgrade does not establish profitability. Live authenticated behavior still
requires a separately authorized, tightly bounded exchange acceptance test.

Protocol references checked September 9, 2026:
- https://docs.polymarket.us/api-reference/orders/create-order
- https://docs.polymarket.us/api-reference/websocket/private
