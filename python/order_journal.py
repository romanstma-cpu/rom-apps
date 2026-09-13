"""Durable US order evidence. Absence from an API response is never a cancellation.

Local IDs are journal keys, not exchange idempotency keys. Unknown submissions
require an operator-supplied exchange order ID; matching by price/time is unsafe.
"""
import json
import math
import sqlite3
import time
import db
import fees_us

SCHEMA = """
CREATE TABLE IF NOT EXISTS us_order_intents (
 local_id TEXT PRIMARY KEY, order_id TEXT UNIQUE, ticker TEXT NOT NULL,
 side TEXT NOT NULL, action TEXT NOT NULL, quantity REAL NOT NULL,
 limit_price REAL NOT NULL, reserved_usd REAL NOT NULL,
 state TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL,
 filled REAL NOT NULL DEFAULT 0, avg_price REAL, fees_usd REAL, error TEXT
);
CREATE TABLE IF NOT EXISTS us_order_snapshots (
 order_id TEXT PRIMARY KEY, filled REAL NOT NULL, terminal INTEGER NOT NULL,
 payload TEXT NOT NULL, received_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS us_executions (
 order_id TEXT NOT NULL, execution_id TEXT NOT NULL, trade_id TEXT,
 quantity REAL NOT NULL, price REAL NOT NULL, fee_usd REAL,
 exchange_time TEXT, received_at REAL NOT NULL,
 PRIMARY KEY(order_id, execution_id)
);
CREATE TABLE IF NOT EXISTS us_exit_basis (
 position_id INTEGER PRIMARY KEY, quantity REAL NOT NULL, cost_usd REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS us_exit_orders (
 local_id TEXT PRIMARY KEY, position_id INTEGER NOT NULL, reason TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS us_entry_execution (
 local_id TEXT PRIMARY KEY, network TEXT NOT NULL, source TEXT NOT NULL,
 style TEXT NOT NULL, signal_cents REAL NOT NULL, bid_cents REAL NOT NULL,
 ask_cents REAL NOT NULL, response_ms REAL
);
CREATE INDEX IF NOT EXISTS us_intents_market_time
 ON us_order_intents(ticker, created_at);
CREATE INDEX IF NOT EXISTS us_entry_execution_group
 ON us_entry_execution(network, source, style, local_id);
"""


class RecoveryRequired(RuntimeError):
    pass


def init():
    with db.get_db() as c:
        c.executescript(SCHEMA)


def get(local_id):
    init()
    with db.get_db() as c:
        r = c.execute('SELECT * FROM us_order_intents WHERE local_id=?', (local_id,)).fetchone()
        return dict(r) if r else None


def unresolved():
    init()
    with db.get_db() as c:
        return [dict(r) for r in c.execute("SELECT * FROM us_order_intents WHERE state NOT IN ('filled','canceled','rejected')")]


BLOCKING_STATES = ('sending', 'unknown', 'cancel_pending', 'accounting_pending')


def blocker():
    init()
    with db.get_db() as c:
        r = c.execute("SELECT local_id FROM us_order_intents WHERE state IN ('sending','unknown','cancel_pending','accounting_pending') LIMIT 1").fetchone()
    return f'Order recovery required ({r[0]}); new orders paused' if r else None


def blocked_intents():
    """Every intent currently halting submissions, oldest first.

    `blocker()` names one row so an engine can refuse and move on. An operator
    needs all of them, plus the identifying detail to match each against the
    exchange's own order list -- the ticker, side, size and price they would
    search for -- because recovery requires supplying the real exchange id and
    `attach_verified_order` refuses a mismatch.
    """
    init()
    with db.get_db() as c:
        rows = c.execute(
            "SELECT local_id, order_id, ticker, side, action, quantity, limit_price,"
            " reserved_usd, state, created_at, error FROM us_order_intents"
            " WHERE state IN ('sending','unknown','cancel_pending','accounting_pending')"
            " ORDER BY created_at"
        ).fetchall()
    return [dict(r) for r in rows]


def begin(local_id, ticker, side, action, quantity, price, position_id=None, exit_reason='exit', execution_context=None):
    init()
    with db.get_db() as c:
        # FULL makes the committed intent durable before network submission.
        c.execute('PRAGMA synchronous=FULL')
        c.execute('BEGIN IMMEDIATE')
        if c.execute('SELECT 1 FROM us_order_intents WHERE local_id=?', (local_id,)).fetchone():
            raise RecoveryRequired('This local order ID has already been used; reconcile it instead of resubmitting')
        if c.execute("SELECT 1 FROM us_order_intents WHERE state IN ('sending','unknown','cancel_pending','accounting_pending') LIMIT 1").fetchone():
            raise RecoveryRequired('An earlier order requires recovery; new orders paused')
        if c.execute("SELECT 1 FROM us_order_intents WHERE ticker=? AND side=? AND action=? AND state='open'", (ticker, side, action)).fetchone():
            raise RecoveryRequired('An order for this market and side is still open')
        now = time.time()
        c.execute('INSERT INTO us_order_intents (local_id,ticker,side,action,quantity,limit_price,reserved_usd,state,created_at,updated_at) VALUES (?,?,?,?,?,?,?,\'sending\',?,?)',
                  (local_id,ticker,side,action,quantity,price,fees_us.reserved_cost(quantity,price,now) if action=='buy' else 0,now,now))
        if execution_context is not None:
            context = execution_context
            if action != 'buy' or context['style'] not in ('crossing', 'resting'):
                raise ValueError('Invalid entry execution context')
            for key in ('signal_cents', 'bid_cents', 'ask_cents'):
                if not math.isfinite(context[key]) or not 0 < context[key] < 100:
                    raise ValueError('Invalid execution benchmark')
            c.execute('INSERT INTO us_entry_execution VALUES (?,?,?,?,?,?,?,NULL)',
                      (local_id,context['network'],context['source'],context['style'],
                       context['signal_cents'],context['bid_cents'],context['ask_cents']))
        if position_id is not None:
            pos = c.execute('SELECT * FROM bot_positions WHERE id=?', (position_id,)).fetchone()
            if (action != 'sell' or not pos or pos['resolved'] or pos['ticker'] != ticker
                    or pos['direction'] != side or quantity > pos['filled_contracts']):
                raise RecoveryRequired('Exit quantity or position does not match the ledger')
            c.execute('INSERT OR IGNORE INTO us_exit_basis VALUES (?,?,?)',
                      (position_id,pos['filled_contracts'],pos['cost_usd']))
            c.execute('INSERT INTO us_exit_orders VALUES (?,?,?)', (local_id,position_id,exit_reason))


def state(local_id, value, error=None, order_id=None):
    with db.get_db() as c:
        c.execute('PRAGMA synchronous=FULL')
        c.execute('UPDATE us_order_intents SET state=?,error=?,order_id=COALESCE(?,order_id),updated_at=? WHERE local_id=?',
                  (value,error,order_id,time.time(),local_id))
        if value == 'rejected':
            c.execute('UPDATE us_order_intents SET reserved_usd=0 WHERE local_id=?', (local_id,))


def number(v):
    if isinstance(v, dict):
        v = v.get('value')
    if v is None or v == '':
        return None
    x = float(v)
    if not math.isfinite(x):
        raise ValueError('Non-finite order evidence')
    return x


def record_order(raw):
    """Store cumulative exchange evidence idempotently, never invent a fill price."""
    oid = raw.get('id')
    if not oid:
        return
    filled = number(raw.get('cumQuantity'))
    if filled is None or filled < 0:
        return
    terminal = raw.get('state') in ('ORDER_STATE_FILLED','ORDER_STATE_CANCELED','ORDER_STATE_REJECTED','ORDER_STATE_EXPIRED')
    avg = number(raw.get('avgPx'))
    fees = number(raw.get('commissionNotionalTotalCollected'))
    no = raw.get('outcomeSide') == 'OUTCOME_SIDE_NO' or 'SHORT' in raw.get('intent','')
    if avg is not None:
        if not 0 <= avg <= 1:
            raise ValueError('Invalid execution price')
        avg = 1-avg if no else avg
    init()
    with db.get_db() as c:
        c.execute('BEGIN IMMEDIATE')
        old = c.execute('SELECT * FROM us_order_snapshots WHERE order_id=?', (oid,)).fetchone()
        if old and (filled < old['filled'] or (filled == old['filled'] and old['terminal'] and not terminal)):
            return
        c.execute('INSERT OR REPLACE INTO us_order_snapshots VALUES (?,?,?,?,?)',
                  (oid,filled,int(terminal),json.dumps(raw),time.time()))
        row = c.execute('SELECT * FROM us_order_intents WHERE order_id=?', (oid,)).fetchone()
        if not row:
            return
        # Fractional fills are retained exactly; the legacy position engine cannot
        # safely trade them, so require reconciliation instead of rounding them.
        accounting_ok = filled == 0 or (avg is not None and fees is not None and filled.is_integer())
        status = ('filled' if raw.get('state') == 'ORDER_STATE_FILLED' else 'canceled') if terminal else 'open'
        if not accounting_ok or filled > row['quantity'] or (raw.get('state')=='ORDER_STATE_FILLED' and filled==0):
            status = 'accounting_pending'
        if row['state'] == 'cancel_pending' and not terminal:
            status = 'cancel_pending'
        remaining = max(0, row['quantity']-filled)
        reserved = 0 if (terminal and accounting_ok) or row['action'] != 'buy' else fees_us.reserved_cost(remaining,row['limit_price'],time.time())
        if status == 'accounting_pending':
            reserved = max(reserved, row['reserved_usd'])
        c.execute('UPDATE us_order_intents SET state=?,filled=?,avg_price=?,fees_usd=?,reserved_usd=?,updated_at=? WHERE order_id=?',
                  (status,filled,avg,fees,reserved,time.time(),oid))


def record_execution(execution):
    raw = execution.get('order') or {}
    qty = number(execution.get('lastShares'))
    px = number(execution.get('lastPx'))
    if execution.get('type') in ('EXECUTION_TYPE_PARTIAL_FILL','EXECUTION_TYPE_FILL') and qty is not None and qty > 0 and px is not None:
        if not 0 <= px <= 1:
            raise ValueError('Invalid execution price')
        if raw.get('outcomeSide') == 'OUTCOME_SIDE_NO' or 'SHORT' in raw.get('intent',''):
            px = 1-px
        if raw.get('id') and execution.get('id'):
            init()
            with db.get_db() as c:
                c.execute('INSERT OR IGNORE INTO us_executions VALUES (?,?,?,?,?,?,?,?)',
                          (raw['id'],execution['id'],execution.get('tradeId'),qty,px,
                           number(execution.get('commissionNotionalCollected')),execution.get('transactTime'),time.time()))
    record_order(raw)


def acknowledge(local_id, order_id):
    state(local_id, 'open', order_id=order_id)
    # A websocket execution may arrive before the HTTP acknowledgement.
    with db.get_db() as c:
        r = c.execute('SELECT payload FROM us_order_snapshots WHERE order_id=?', (order_id,)).fetchone()
    if r:
        record_order(json.loads(r[0]))


def attach_verified_order(local_id, raw):
    """Operator chooses an exchange ID; callers must fetch it through authenticated REST."""
    row = get(local_id)
    if not row or row['order_id'] or row['state'] not in ('unknown','sending'):
        raise RecoveryRequired('Intent is not awaiting an exchange order ID')
    expected = 'ORDER_INTENT_'+row['action'].upper()+('_LONG' if row['side']=='yes' else '_SHORT')
    price = number(raw.get('price'))
    if row['side'] == 'no' and price is not None:
        price = 1-price
    if (not raw.get('id') or raw.get('marketSlug') != row['ticker'] or raw.get('intent') != expected
            or number(raw.get('quantity')) != row['quantity'] or price is None or abs(price-row['limit_price']) > 1e-8):
        raise RecoveryRequired('Exchange order does not match the selected local intent')
    try:
        acknowledge(local_id, raw['id'])
    except sqlite3.IntegrityError:
        # ORDER_ID is UNIQUE: the exchange order is already attached to a
        # different local intent. Nothing was written (the update rolled back);
        # surface it as a recovery decision, not an opaque database error.
        raise RecoveryRequired('Exchange order id is already attached to another local order; reconcile before retrying') from None
    record_order(raw)


def exit_totals(position_id):
    init()
    with db.get_db() as c:
        return _exit_totals(c, position_id)


def _exit_totals(c, position_id):
    basis = c.execute('SELECT * FROM us_exit_basis WHERE position_id=?', (position_id,)).fetchone()
    if not basis:
        return None
    rows = c.execute('SELECT i.*,e.reason FROM us_order_intents i JOIN us_exit_orders e USING(local_id) WHERE e.position_id=?', (position_id,)).fetchall()
    known = [r for r in rows if r['filled'] > 0 and r['avg_price'] is not None and r['fees_usd'] is not None]
    qty = sum(r['filled'] for r in known)
    proceeds = sum(r['filled']*r['avg_price']-r['fees_usd'] for r in known)
    uncertain = any(r['state'] not in ('filled','canceled','rejected') for r in rows)
    return {'quantity':qty,'proceeds':proceeds,'basis':dict(basis),'uncertain':uncertain,
            'realized':proceeds-basis['cost_usd']*qty/basis['quantity'],
            'reason':rows[-1]['reason'] if rows else 'exit'}


def apply_exit_fills():
    """Recompute from cumulative evidence and immutable basis, never add twice."""
    init()
    changed=[]
    with db.get_db() as c:
        c.execute('BEGIN IMMEDIATE')
        for basis in c.execute('SELECT * FROM us_exit_basis').fetchall():
            pos = c.execute('SELECT * FROM bot_positions WHERE id=?', (basis['position_id'],)).fetchone()
            if not pos or (pos['resolved'] and not pos['closed_early']):
                continue
            total = _exit_totals(c, pos['id'])
            sold = total['quantity']
            if sold > basis['quantity'] or not float(sold).is_integer():
                db.update_bot_position(c,pos['id'],status='unknown',error='Exit quantity requires reconciliation')
                continue
            left = basis['quantity']-sold
            fields = {'filled_contracts':int(left), 'target_contracts':int(left),
                      'cost_usd':basis['cost_usd']*left/basis['quantity'],
                      'status':'unknown' if total['uncertain'] else 'filled',
                      'error':'Exit order awaiting reconciliation' if total['uncertain'] else None}
            if left == 0 and not total['uncertain']:
                fields.update(resolved=1,closed_early=1,settlement_usd=total['proceeds'],
                              pnl_usd=total['realized'],exit_reason=total['reason'],
                              outcome_correct=int(total['realized']>0))
            if all(pos[k] == v for k,v in fields.items()):
                continue
            db.update_bot_position(c,pos['id'],**fields)
            if fields.get('resolved'):
                c.execute("UPDATE bot_positions SET resolved_at=datetime('now') WHERE id=?", (pos['id'],))
            db.log_event(c,pos['id'],'exit_reconcile',note='Recomputed from cumulative execution evidence including fees')
            changed.append(db.fetch_position_by_id(c,pos['id']))
    return changed
