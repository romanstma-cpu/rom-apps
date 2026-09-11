"""Escape-hatch drill: prove an operator can clear every blocking journal state.

`order_journal.blocker()` pauses submission for EVERY engine whenever any
intent sits in `sending`, `unknown`, `cancel_pending` or `accounting_pending`.
There is no automatic forget path, so before the live-validation harness is
allowed to place a real order we must be able to demonstrate the recovery
route end to end.

Everything here is network-free: `polymarket_api._request` is poisoned by an
autouse fixture and each test re-binds it to a scripted responder. The core
scenarios are written as `drill_*` coroutines taking a `DrillContext` so a
later harness stage can re-bind that context to a real authenticated account
and replay the identical assertions.
"""
import asyncio
import sqlite3
import pytest

import db
import order_journal as journal
import polymarket_api as api
import copy_trader
import crypto15m_trader
import trader
import us_account_stream as stream
from test_order_recovery import raw_order


async def _no_network(*a, **k):
    raise AssertionError('recovery drill attempted a real HTTP request')


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'db_path', lambda: str(tmp_path / 'drill.db'))
    db.init_db()
    journal.init()
    stream.consume_dirty()

    async def meta(_ticker):
        return {'min_size': 1, 'tick_size': .01}

    monkeypatch.setattr(api, '_request', _no_network)
    monkeypatch.setattr(api, 'get_market_meta', meta)


# --- reusable drill context ------------------------------------------------
#
# The live harness supplies the same four adapter calls against a real
# account; the drill bodies below never touch anything else.

class DrillContext:
    def __init__(self, place_order=None, recover=None, get_order=None, cancel_order=None):
        self.place_order = place_order or api.place_limit_order
        self.recover = recover or api.recover_order
        self.get_order = get_order or api.get_order
        self.cancel_order = cancel_order or api.cancel_order


async def submission_is_blocked(ctx, *, ticker='probe-market', local_id='probe'):
    """A fresh submission on an unrelated market must be refused outright."""
    try:
        await ctx.place_order(ticker=ticker, side='yes', action='buy', count=10,
                              price_cents=60, client_order_id=local_id)
    except journal.RecoveryRequired as exc:
        assert journal.get(local_id) is None, 'refused intent must not be journalled'
        return str(exc)
    raise AssertionError('a blocking journal row did not stop a new submission')


async def submission_is_allowed(ctx, *, ticker='probe-market', local_id='probe-ok'):
    resp = await ctx.place_order(ticker=ticker, side='yes', action='buy', count=10,
                                 price_cents=60, client_order_id=local_id)
    assert journal.get(local_id)['state'] == 'open'
    return resp


async def drill_blocked_state(ctx, local_id, expected_state):
    """Shared shape: the row is stuck, blocker() names it, submissions stop."""
    row = journal.get(local_id)
    assert row is not None and row['state'] == expected_state
    message = journal.blocker()
    assert message and local_id in message
    refusal = await submission_is_blocked(ctx)
    assert 'recovery' in refusal or 'paused' in refusal
    return message


async def drill_operator_recovery(ctx, local_id, exchange_order_id, expected_state='open'):
    """Operator supplies the real exchange ID; the adapter unblocks."""
    evidence = await ctx.recover(local_id, exchange_order_id)
    assert evidence['order_id'] == exchange_order_id
    assert evidence['state'] == expected_state
    assert journal.blocker() is None
    await submission_is_allowed(ctx)
    return evidence


async def drill_mismatched_recovery_refused(local_id, bad_raw):
    """The safety property: a wrong exchange order can never be attached."""
    before = journal.get(local_id)
    with pytest.raises(journal.RecoveryRequired):
        journal.attach_verified_order(local_id, bad_raw)
    after = journal.get(local_id)
    assert after['order_id'] is None
    assert after['state'] == before['state']
    assert journal.blocker(), 'a refused recovery must leave the adapter blocked'


# --- seeding helpers -------------------------------------------------------
#
# Each helper opens its own connection through journal/api; never call one
# inside an outer `with db.get_db()` or SQLite will deadlock the drill.

def responder(*orders, post_id='ex-new'):
    """Scripted `_request`: POST acknowledges, GET returns the next order."""
    seq = list(orders)

    async def request(method, path, **kwargs):
        if method == 'POST':
            return {'id': post_id} if path == '/v1/orders' else {}
        return {'order': seq.pop(0) if len(seq) > 1 else seq[0]}

    return request


async def seed_sending(monkeypatch, local_id='local', ticker='market'):
    """Process died between the durable pre-POST commit and the response.

    A hard kill performs no further writes, so the journal keeps the exact row
    `begin()` committed. `state()` is stubbed out to represent the writes the
    dead process never made; the in-flight assertion proves the row really is
    already on disk, on an independent connection, before the POST.
    """
    seen = []

    async def request(*a, **k):
        seen.append(journal.get(local_id)['state'])
        raise TimeoutError()

    live_state = journal.state
    monkeypatch.setattr(api, '_request', request)
    monkeypatch.setattr(journal, 'state', lambda *a, **k: None)
    try:
        with pytest.raises(TimeoutError):
            await api.place_limit_order(ticker=ticker, side='yes', action='buy', count=10,
                                        price_cents=60, client_order_id=local_id)
    finally:
        monkeypatch.setattr(journal, 'state', live_state)
        monkeypatch.setattr(api, '_request', _no_network)
    journal.init()  # Reload from disk: recovery never trusts process memory.
    assert seen == ['sending']
    return local_id


async def seed_unknown(monkeypatch, local_id='local', ticker='market'):
    """Timeout or ambiguous response: the adapter itself marks the row unknown."""
    async def request(*a, **k):
        raise TimeoutError()

    monkeypatch.setattr(api, '_request', request)
    try:
        with pytest.raises(TimeoutError):
            await api.place_limit_order(ticker=ticker, side='yes', action='buy', count=10,
                                        price_cents=60, client_order_id=local_id)
    finally:
        monkeypatch.setattr(api, '_request', _no_network)
    journal.init()
    assert journal.get(local_id)['state'] == 'unknown'
    assert journal.get(local_id)['order_id'] is None
    return local_id


def seed_acknowledged(local_id='local', ticker='market'):
    journal.begin(local_id, ticker, 'yes', 'buy', 10, .6)
    journal.acknowledge(local_id, 'ex-1')
    return local_id


def recovery_context(monkeypatch, order=None):
    """Re-bind the drill context to a scripted exchange for the recovery leg."""
    monkeypatch.setattr(api, '_request', responder(order or raw_order()))
    return DrillContext()


# --- 1 & 2: sending and unknown -------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize('seed,expected', [(seed_sending, 'sending'), (seed_unknown, 'unknown')])
async def test_stuck_submission_blocks_then_recovers(monkeypatch, seed, expected):
    local_id = await seed(monkeypatch)
    assert journal.get(local_id)['order_id'] is None
    assert journal.get(local_id)['reserved_usd'] > 0

    blocked = DrillContext()  # _request is still the poison: nothing may escape.
    await drill_blocked_state(blocked, local_id, expected)

    # reconcile_order_journal deliberately cannot help: no order_id to look up.
    await trader.reconcile_order_journal()
    assert journal.get(local_id)['state'] == expected
    assert journal.blocker()

    ctx = recovery_context(monkeypatch)
    await drill_operator_recovery(ctx, local_id, 'ex-1')
    row = journal.get(local_id)
    assert row['filled'] == 4 and row['avg_price'] == .55


@pytest.mark.asyncio
async def test_recovered_order_carries_through_to_terminal_evidence(monkeypatch):
    local_id = await seed_unknown(monkeypatch)
    ctx = recovery_context(monkeypatch, raw_order(state='ORDER_STATE_FILLED', cumQuantity=10))
    await drill_operator_recovery(ctx, local_id, 'ex-1', expected_state='filled')
    assert journal.get(local_id)['reserved_usd'] == 0


# --- 3: cancel_pending -----------------------------------------------------

@pytest.mark.asyncio
async def test_cancel_pending_blocks_until_terminal_evidence(monkeypatch):
    seed_acknowledged()
    monkeypatch.setattr(api, '_request', responder(raw_order()))
    ctx = DrillContext()
    with pytest.raises(journal.RecoveryRequired):
        await ctx.cancel_order('ex-1')
    await drill_blocked_state(ctx, 'local', 'cancel_pending')
    assert journal.get('local')['reserved_usd'] > 0

    # The clear is evidence, not a flag: re-fetch once the exchange is terminal.
    monkeypatch.setattr(api, '_request', responder(raw_order(state='ORDER_STATE_CANCELED')))
    await ctx.get_order('ex-1')
    assert journal.get('local')['state'] == 'canceled'
    assert journal.blocker() is None
    await submission_is_allowed(ctx)


@pytest.mark.asyncio
async def test_cancel_pending_also_clears_by_retrying_the_cancel(monkeypatch):
    seed_acknowledged()
    monkeypatch.setattr(api, '_request', responder(raw_order()))
    ctx = DrillContext()
    with pytest.raises(journal.RecoveryRequired):
        await ctx.cancel_order('ex-1')
    assert journal.get('local')['state'] == 'cancel_pending'

    monkeypatch.setattr(api, '_request', responder(raw_order(state='ORDER_STATE_CANCELED')))
    assert (await ctx.cancel_order('ex-1'))['canceled'] == ['ex-1']
    assert journal.blocker() is None


# --- 4: accounting_pending -------------------------------------------------

ACCOUNTING_ROUTES = {
    'missing_avg_price': dict(state='ORDER_STATE_FILLED', cumQuantity=10, avgPx=None),
    'missing_commission': dict(state='ORDER_STATE_FILLED', cumQuantity=10,
                               commissionNotionalTotalCollected=None),
    'fractional_fill': dict(cumQuantity='0.5'),
    'overfill': dict(state='ORDER_STATE_FILLED', cumQuantity=12),
    'filled_with_zero_quantity': dict(state='ORDER_STATE_FILLED', cumQuantity=0),
}


def _route(name):
    raw = raw_order()
    for key, value in ACCOUNTING_ROUTES[name].items():
        if value is None:
            raw.pop(key, None)
        else:
            raw[key] = value
    return raw


@pytest.mark.asyncio
@pytest.mark.parametrize('route', sorted(ACCOUNTING_ROUTES))
async def test_accounting_pending_routes_all_block(monkeypatch, route):
    seed_acknowledged()
    journal.record_order(_route(route))
    ctx = DrillContext()
    await drill_blocked_state(ctx, 'local', 'accounting_pending')
    assert journal.get('local')['reserved_usd'] > 0, 'blocked risk stays reserved'


@pytest.mark.asyncio
@pytest.mark.parametrize('route', ['missing_avg_price', 'missing_commission'])
async def test_accounting_pending_clears_on_corrected_evidence(monkeypatch, route):
    seed_acknowledged()
    journal.record_order(_route(route))
    assert journal.get('local')['state'] == 'accounting_pending'

    complete = raw_order(state='ORDER_STATE_FILLED', cumQuantity=10)
    monkeypatch.setattr(api, '_request', responder(complete))
    ctx = DrillContext()
    await ctx.get_order('ex-1')
    row = journal.get('local')
    assert row['state'] == 'filled' and row['avg_price'] == .55 and row['fees_usd'] == .03
    assert row['reserved_usd'] == 0
    assert journal.blocker() is None
    await submission_is_allowed(ctx)


@pytest.mark.asyncio
async def test_fractional_fill_cannot_be_cleared_by_re_fetching(monkeypatch):
    """Documented dead end: only integer contracts can re-enter the ledger.

    Re-fetching a genuinely fractional fill re-affirms the same evidence, so
    the adapter stays blocked. The runbook routes this case to a human.
    """
    seed_acknowledged()
    journal.record_order(_route('fractional_fill'))
    monkeypatch.setattr(api, '_request', responder(_route('fractional_fill')))
    await api.get_order('ex-1')
    assert journal.get('local')['state'] == 'accounting_pending'
    assert journal.blocker()


# --- 5: mismatched recovery is refused -------------------------------------

MISMATCHES = {
    'missing_id': dict(id=None),
    'wrong_market': dict(marketSlug='some-other-market'),
    'wrong_intent_action': dict(intent='ORDER_INTENT_SELL_LONG'),
    'wrong_intent_side': dict(intent='ORDER_INTENT_BUY_SHORT'),
    'wrong_quantity': dict(quantity=11),
    'missing_price': dict(price=None),
    'wrong_price': dict(price={'value': '.61'}),
}


@pytest.mark.asyncio
@pytest.mark.parametrize('case', sorted(MISMATCHES))
async def test_operator_cannot_attach_a_mismatched_order(monkeypatch, case):
    local_id = await seed_unknown(monkeypatch)
    bad = raw_order()
    for key, value in MISMATCHES[case].items():
        if value is None:
            bad.pop(key, None)
        else:
            bad[key] = value
    await drill_mismatched_recovery_refused(local_id, bad)

    # And the same refusal travels through the operator-facing adapter call.
    monkeypatch.setattr(api, '_request', responder(bad))
    with pytest.raises(journal.RecoveryRequired):
        await api.recover_order(local_id, bad.get('id', 'ex-1'))
    assert journal.get(local_id)['order_id'] is None

    # The correct order still attaches afterwards: refusal is not a dead end.
    monkeypatch.setattr(api, '_request', responder(raw_order()))
    await drill_operator_recovery(DrillContext(), local_id, 'ex-1')


@pytest.mark.asyncio
async def test_no_side_price_is_mirrored_before_comparison(monkeypatch):
    """A 'no' intent at 60c matches an exchange SHORT order priced at .40."""
    journal.begin('local', 'market', 'no', 'buy', 10, .6)
    journal.state('local', 'unknown')
    short = raw_order(intent='ORDER_INTENT_BUY_SHORT', price={'value': '.4'},
                      avgPx={'value': '.45'}, outcomeSide='OUTCOME_SIDE_NO')
    await drill_mismatched_recovery_refused('local', {**short, 'price': {'value': '.6'}})
    journal.attach_verified_order('local', short)
    row = journal.get('local')
    assert row['state'] == 'open' and row['order_id'] == 'ex-1'
    assert row['avg_price'] == pytest.approx(.55)  # mirrored back to the yes frame


@pytest.mark.asyncio
async def test_recovery_refused_once_an_order_id_is_already_attached(monkeypatch):
    seed_acknowledged()
    journal.state('local', 'unknown')
    with pytest.raises(journal.RecoveryRequired):
        journal.attach_verified_order('local', raw_order(id='ex-2'))
    assert journal.get('local')['order_id'] == 'ex-1'


@pytest.mark.asyncio
@pytest.mark.parametrize('state', ['open', 'cancel_pending', 'accounting_pending',
                                   'filled', 'canceled', 'rejected'])
async def test_recovery_refused_for_states_not_awaiting_an_id(state):
    journal.begin('local', 'market', 'yes', 'buy', 10, .6)
    journal.state('local', state)
    with pytest.raises(journal.RecoveryRequired):
        journal.attach_verified_order('local', raw_order())
    assert journal.get('local')['order_id'] is None


@pytest.mark.asyncio
async def test_recovery_refused_for_an_unknown_local_id():
    with pytest.raises(journal.RecoveryRequired):
        journal.attach_verified_order('never-existed', raw_order())


# --- 6: the block is adapter-wide, not per-engine --------------------------

ENGINE_SUBMITTERS = {
    'main_strategy': lambda: trader.place_limit_order,
    'crypto15m': lambda: crypto15m_trader.polymarket_api.place_limit_order,
    'copy_trader': lambda: copy_trader.polymarket_api.place_limit_order,
}


def test_every_engine_submits_through_the_single_journalled_adapter():
    for name, resolve in ENGINE_SUBMITTERS.items():
        assert resolve() is api.place_limit_order, name


@pytest.mark.asyncio
@pytest.mark.parametrize('stuck_engine,probing_engine',
                         [('copy_trader', 'crypto15m'), ('crypto15m', 'main_strategy'),
                          ('main_strategy', 'copy_trader')])
async def test_one_engine_stuck_row_blocks_the_others(monkeypatch, stuck_engine, probing_engine):
    await seed_unknown(monkeypatch, local_id=f'{stuck_engine}-order',
                       ticker=f'{stuck_engine}-market')
    submit = ENGINE_SUBMITTERS[probing_engine]()
    with pytest.raises(journal.RecoveryRequired):
        await submit(ticker=f'{probing_engine}-market', side='yes', action='buy',
                     count=10, price_cents=60, client_order_id=f'{probing_engine}-order')
    assert journal.get(f'{probing_engine}-order') is None

    monkeypatch.setattr(api, '_request',
                        responder(raw_order(marketSlug=f'{stuck_engine}-market')))
    await api.recover_order(f'{stuck_engine}-order', 'ex-1')
    assert journal.blocker() is None

    monkeypatch.setattr(api, '_request', responder(raw_order(id='ex-9')))
    await submit(ticker=f'{probing_engine}-market', side='yes', action='buy',
                 count=10, price_cents=60, client_order_id=f'{probing_engine}-order')
    assert journal.get(f'{probing_engine}-order')['state'] == 'open'


@pytest.mark.asyncio
async def test_concurrent_engine_submissions_cannot_both_pass_the_gate(monkeypatch):
    """Two engines racing: at most one intent is ever journalled as sending."""
    async def request(*a, **k):
        await asyncio.sleep(0)
        raise TimeoutError()

    monkeypatch.setattr(api, '_request', request)
    results = await asyncio.gather(
        api.place_limit_order(ticker='a-market', side='yes', action='buy', count=10,
                              price_cents=60, client_order_id='engine-a'),
        api.place_limit_order(ticker='b-market', side='yes', action='buy', count=10,
                              price_cents=60, client_order_id='engine-b'),
        return_exceptions=True)
    assert all(isinstance(r, BaseException) for r in results)
    journalled = [r for r in journal.unresolved()]
    assert len(journalled) == 1
    assert any(isinstance(r, journal.RecoveryRequired) for r in results)


@pytest.mark.asyncio
async def test_exchange_id_already_owned_by_another_intent_is_not_stolen(monkeypatch):
    """Two intents may never point at one exchange order.

    The UNIQUE constraint on `us_order_intents.order_id` is the last line of
    defence and it surfaces as sqlite3.IntegrityError rather than
    RecoveryRequired. The attach is refused, which is what matters; the
    runbook tells the operator what that error means.
    """
    seed_acknowledged('first', 'market-a')
    journal.begin('second', 'market-b', 'yes', 'buy', 10, .6)
    journal.state('second', 'unknown')
    with pytest.raises((journal.RecoveryRequired, sqlite3.IntegrityError)):
        journal.attach_verified_order('second', raw_order(marketSlug='market-b'))
    assert journal.get('second')['order_id'] is None
    assert journal.get('first')['order_id'] == 'ex-1'


# --- what the operator UI is shown ----------------------------------------
#
# blocker() names one row so an engine can refuse and move on. The recovery
# panel needs every halted intent plus the detail an operator matches against
# the exchange's order list, so blocked_intents() is its own contract.

def _seed_intent(local_id, state, ticker='m', created=1000.0, order_id=None):
    with db.get_db() as c:
        c.execute(
            "INSERT INTO us_order_intents (local_id, order_id, ticker, side, action,"
            " quantity, limit_price, reserved_usd, state, created_at, updated_at)"
            " VALUES (?,?,?,'yes','buy',3,0.42,1.29,?,?,?)",
            (local_id, order_id, ticker, state, created, created),
        )


@pytest.mark.parametrize('state', list(journal.BLOCKING_STATES))
def test_every_blocking_state_is_reported(state):
    journal.init()
    _seed_intent('x', state)
    assert [r['local_id'] for r in journal.blocked_intents()] == ['x']
    assert journal.blocker() is not None


@pytest.mark.parametrize('state', ['filled', 'canceled', 'rejected'])
def test_terminal_states_are_not_reported(state):
    journal.init()
    _seed_intent('x', state)
    assert journal.blocked_intents() == []
    assert journal.blocker() is None


def test_open_intents_do_not_halt_the_operator_panel():
    # `open` blocks only a matching ticker/side/action, not the whole adapter,
    # so it must not appear as something needing recovery.
    journal.init()
    _seed_intent('x', 'open', order_id='ex-1')
    assert journal.blocked_intents() == []


def test_reported_oldest_first_with_the_fields_an_operator_needs():
    journal.init()
    _seed_intent('newer', 'unknown', ticker='m2', created=2000.0)
    _seed_intent('older', 'sending', ticker='m1', created=1000.0)
    rows = journal.blocked_intents()
    assert [r['local_id'] for r in rows] == ['older', 'newer']
    assert set(rows[0]) == {
        'local_id', 'order_id', 'ticker', 'side', 'action', 'quantity',
        'limit_price', 'reserved_usd', 'state', 'created_at', 'error',
    }
    assert rows[0]['ticker'] == 'm1' and rows[0]['quantity'] == 3
