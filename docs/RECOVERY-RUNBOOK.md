# Order recovery runbook

Read this when the bot has stopped submitting orders and the logs or UI say:

```
Order recovery required (<local_id>); new orders paused
```

or an engine refuses a trade with:

```
An earlier order requires recovery; new orders paused
```

Nothing is broken automatically. The order journal has a row it cannot prove
the outcome of, so it has halted **all** submission — main strategy, crypto15m,
copy trader and scripts alike. It stays halted until a human supplies the
missing evidence. There is no timeout and no automatic forget path. That is
deliberate: the alternative is double-submitting real money into the same
market.

Everything below is proven in `python/tests/test_recovery_drill.py`. If you want
to rehearse before touching the live account, run:

```
cd python && .venv/Scripts/python.exe -m pytest tests/test_recovery_drill.py
```

---

## 0. Do not do these

- Do not delete or `UPDATE` rows in `us_order_intents` to "clear" the block.
  The reserved cash/contracts behind the row are the only record that the
  exchange may already be holding your money.
- Do not restart the app hoping it clears. Restarting re-reads the same row.
- Do not re-run the strategy with a new client order ID. The gate is journal-
  wide; it will refuse, and if you bypass it you may buy the same market twice.
- Do not guess an exchange order ID from price and timestamp. The adapter will
  reject a mismatch, but a *coincidentally* matching wrong order would be
  attached, and you would then account against a stranger's fill.

## 1. Find the stuck row

The database is `<userdata>/data/rom-polybot.db`, where `<userdata>` is
`$ROM_POLYBOT_USERDATA` if set, otherwise the `python/data` directory next to
the backend.

```sql
SELECT local_id, order_id, ticker, side, action, quantity, limit_price,
       state, reserved_usd, datetime(created_at,'unixepoch') AS created, error
FROM us_order_intents
WHERE state IN ('sending','unknown','cancel_pending','accounting_pending');
```

Only four states block. Write down `local_id`, `ticker`, `side`, `action`,
`quantity` and `limit_price` — you need them to verify any candidate exchange
order.

## 2. Pick the procedure by state

| State | What happened | Is `order_id` set? | Procedure |
|---|---|---|---|
| `sending` | The process died between the durable pre-POST commit and the exchange's reply. The order may or may not exist. | No | §3 then §4 |
| `unknown` | Timeout, connection drop, or a 2xx without an order ID. The order may or may not exist. | Usually no | §3 then §4 (if `order_id` *is* set, §5 first) |
| `cancel_pending` | A cancel was sent but the exchange had not yet reported a terminal state. | Yes | §5 |
| `accounting_pending` | The order is terminal but the evidence cannot be booked: missing `avgPx`, missing commission, a fractional fill, `cumQuantity` above the ordered quantity, or `FILLED` with zero quantity. | Yes | §5, then §6 if it will not clear |

## 3. Find the real exchange order ID

Try these in order. Stop at the first that gives you an ID.

**a. The local snapshot table.** If the account websocket saw the order before
the process died, the exchange ID is already on your disk even though the
intent never got it:

```sql
SELECT s.order_id, s.filled, s.terminal, s.payload
FROM us_order_snapshots s
LEFT JOIN us_order_intents i ON i.order_id = s.order_id
WHERE i.local_id IS NULL
ORDER BY s.received_at DESC LIMIT 20;
```

Read `payload` (JSON) and confirm `marketSlug`, `intent`, `quantity` and
`price` match the row from §1.

**b. The backend log.** Search the log around the timestamp in `created` for
the market slug and for an order ID in the POST response.

**c. The Polymarket US account order history.** Sign in to the account the bot
trades with and open its order history for that market. This codebase has no
"list my orders" endpoint, so this is a manual read. Match on market slug,
side, quantity, limit price and time.

**If none of the three yields an order** — the order history for that market
shows nothing at or after `created`, and the snapshot table has nothing — then
the POST never reached the exchange. See §6; this case still requires a
deliberate human decision, not a shortcut.

### Verify before you attach

The adapter re-fetches the order over authenticated REST and refuses the attach
unless **all** of these match the local intent:

- `marketSlug` equals `ticker`
- `intent` equals `ORDER_INTENT_<ACTION>_<LONG if side=yes else SHORT>`
- `quantity` equals the intent quantity exactly
- `price` equals `limit_price`, mirrored (`1 - price`) for a `no` side
- the order has a non-empty `id`

A mismatch on any one of them raises `RecoveryRequired` and changes nothing.
That refusal is the safety property; if you hit it, you have the wrong order —
go back to §3, do not loosen anything.

## 4. Attach the order (`sending` / `unknown`)

The backend speaks line-delimited JSON-RPC on stdin. The exact payload:

```json
{"id":"recover-1","method":"runOnce","params":{"action":"recoverOrder","localOrderId":"<local_id>","exchangeOrderId":"<exchange order id>"}}
```

**Note on getting it in.** The Electron bridge (`electron/ipc.ts`,
`backend:runOnce`) forwards only `action` and drops the other two fields, so
the desktop UI cannot send this today. Drive it against the backend's stdin
instead:

1. Quit the desktop app completely (it holds the instance lock and owns the
   backend's stdin).
2. Start the backend by hand from the repo root:
   `python/.venv/Scripts/python.exe python/service.py`
   (run it from the `python` directory, or with the same working directory the
   app uses, so it opens the same database).
3. Wait for the `backend:authChanged` event with `"authOk":true` on stdout.
   Without it the REST fetch cannot authenticate and the attach will fail.
4. Paste the JSON line above and press Enter.

A success looks like:

```json
{"id":"recover-1","result":{"summary":"Order linked and reconciled","state":"open"}}
```

`state` will be `open`, `filled` or `canceled` depending on what the exchange
reported. Any of those is fine — all three are non-blocking.

An error reply of `RecoveryRequired: Exchange order does not match the selected
local intent` means the ID is wrong: nothing was written, go back to §3.

An error reply mentioning `IntegrityError: UNIQUE constraint failed:
us_order_intents.order_id` means that exchange order is already attached to a
*different* local intent. Nothing was written. You are looking at the wrong
exchange order, or at the wrong `local_id`.

## 5. Clear by re-fetching evidence (`cancel_pending` / `accounting_pending`)

These rows already have an `order_id`, so no attach is needed. They clear when
the exchange reports evidence the journal can book. Ask for it:

```json
{"id":"poll-1","method":"runOnce","params":{"action":"pollOrders"}}
```

- `cancel_pending` clears as soon as the exchange reports a terminal state
  (`CANCELED`, `FILLED`, `REJECTED`, `EXPIRED`). Until then the reservation is
  held on purpose — the order may still fill. If the order is genuinely still
  live, cancel it again from the UI and poll; the second confirmed cancel
  clears the row.
- `accounting_pending` clears when a complete terminal record arrives: an
  integer `cumQuantity` no greater than the ordered quantity, plus both `avgPx`
  and `commissionNotionalTotalCollected`. A transiently missing field usually
  fills in on the next poll.

## 6. When it will not clear

Two cases need a decision rather than a retry.

**Fractional fill.** If `cumQuantity` is genuinely fractional (e.g. 0.5), the
position ledger cannot represent it and polling will keep returning the same
evidence. The row stays `accounting_pending` forever by design. Escalate: the
position has to be squared manually on the exchange and the ledger corrected
deliberately. Do not round it.

**The order never existed.** If §3 exhausted every source and the exchange
shows no such order, the POST never landed. There is still no automatic path:
`reconcile_order_journal` skips intents with no `order_id` on purpose. Confirm
twice, at least several minutes apart, that the account's order history and
positions for that market are unchanged since `created` — a late-arriving order
is the failure mode this rule exists to prevent — then resolve the row
deliberately and record what you did and why in `DECISIONS.md`.

## 7. Confirm the unblock

```sql
SELECT local_id, state FROM us_order_intents
WHERE state IN ('sending','unknown','cancel_pending','accounting_pending');
```

Zero rows means submission is open again. There may be more than one stuck
row; `blocker()` reports only the first it finds, so re-run this query after
every fix rather than trusting a single clear message.

Then restart the desktop app and check that the trading status no longer
reports a recovery pause. The first successful new order is the real
confirmation.
