import asyncio
import sqlite3
from contextlib import contextmanager

import pytest
import db
import execution_learning as learning
import order_journal as journal
import polymarket_api as api

NOW = 1789257600.0
CONTEXT = dict(network='mainnet', source='whale', style='crossing',
               signal_cents=59, bid_cents=59, ask_cents=60)


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    @contextmanager
    def connect():
        conn = sqlite3.connect(tmp_path/'execution.db')
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()
    monkeypatch.setattr(db, 'get_db', connect)
    journal.init()
    return connect


def add(ledger, i, *, filled=0, state='canceled', fees=0, day=None, network='mainnet'):
    at = NOW-(day if day is not None else i//2)*86400-100
    with ledger() as c:
        c.execute("INSERT INTO us_order_intents VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (str(i), 'o'+str(i), 'market', 'yes', 'buy', 10, .6, 0,
                   state, at, at+1, filled, .6 if filled else None, fees, None))
        c.execute("INSERT INTO us_entry_execution VALUES (?,?,?,?,?,?,?,?)",
                  (str(i), network, 'whale', 'crossing', 59, 59, 60, 100+i))


def feedback():
    return learning.entry_feedback('mainnet','market','whale','crossing',60,now=NOW)


def test_empty_history_keeps_scheduled_fee_and_no_block(ledger):
    assert feedback() == pytest.approx(dict(blocked=False,feeCents=2,extraFeeCents=0,samples=0))
    stats=learning.summarize([])
    assert stats['fillRatePct'] is None and stats['responseP95Ms'] is None


def test_consistent_zero_fills_block_but_burst_does_not(ledger):
    for i in range(20): add(ledger,i,day=0)
    assert not feedback()['blocked']
    with ledger() as c:
        for i in range(20):
            c.execute('UPDATE us_order_intents SET created_at=? WHERE local_id=?', (NOW-(i//2)*86400-100,str(i)))
    assert feedback()['blocked']


@pytest.mark.parametrize('state',['open','unknown','cancel_pending','accounting_pending','rejected'])
def test_unconfirmed_and_rejected_orders_cannot_teach_no_fill(ledger,state):
    for i in range(20): add(ledger,i,state=state)
    assert not feedback()['blocked'] and feedback()['samples']==0


def test_partial_fills_count_actual_quantity_and_fees(ledger):
    add(ledger,1,filled=3,fees=.09)
    add(ledger,2)
    stats=learning.summarize(learning.observations('mainnet',now=NOW))
    assert stats['fillRatePct']==15
    assert stats['signalSlippageCents']==pytest.approx(1)
    assert stats['feeCentsPerContract']==pytest.approx(3)
    assert stats['unfilled']==1


def test_future_expired_and_other_network_evidence_excluded(ledger):
    add(ledger,1,day=-1)
    add(ledger,2,day=31)
    add(ledger,3,network='other')
    add(ledger,4)
    with ledger() as c: c.execute("UPDATE us_order_intents SET updated_at=? WHERE local_id='4'",(NOW+1,))
    assert learning.observations('mainnet',now=NOW)==[]


def test_fee_learning_never_lowers_schedule_and_requires_days(ledger):
    for i in range(20): add(ledger,i,filled=5,fees=.2)
    assert feedback()['extraFeeCents']==pytest.approx(2)
    assert not feedback()['blocked']
    with ledger() as c: c.execute('UPDATE us_order_intents SET fees_usd=-.05')
    assert feedback()['extraFeeCents']==0
    with ledger() as c: c.execute('UPDATE us_order_intents SET fees_usd=.2, created_at=?',(NOW-100,))
    assert feedback()['extraFeeCents']==0


def test_missing_fees_and_other_routes_do_not_teach_cost(ledger):
    for i in range(20): add(ledger,i,filled=5,fees=None)
    assert feedback()['extraFeeCents']==0
    with ledger() as c:
        c.execute('UPDATE us_order_intents SET fees_usd=.2')
        c.execute("UPDATE us_entry_execution SET style='resting'")
    assert feedback()['samples']==0


def test_scoped_query_matches_previous_filter_without_loading_other_groups(ledger):
    for i in range(24): add(ledger,i,filled=5,fees=.2)
    with ledger() as c:
        c.execute("UPDATE us_order_intents SET ticker='other' WHERE local_id='0'")
        c.execute("UPDATE us_entry_execution SET source='momentum' WHERE local_id='1'")
        c.execute("UPDATE us_entry_execution SET style='resting' WHERE local_id='2'")
        c.execute("UPDATE us_order_intents SET limit_price=.66 WHERE local_id='3'")
        c.execute("UPDATE us_order_intents SET limit_price=.65 WHERE local_id='4'")
        c.execute("UPDATE us_order_intents SET limit_price=.55 WHERE local_id='5'")
    all_rows=learning.observations('mainnet',now=NOW)
    expected=[r for r in all_rows if r['ticker']=='market' and r['source']=='whale'
              and r['style']=='crossing' and abs(r['limit_price']*100-60)<=5]
    scoped=learning.observations('mainnet',now=NOW,
        entry_group=('market','whale','crossing',60))
    assert scoped==expected
    assert len(scoped)==20
    assert feedback()['extraFeeCents']==pytest.approx(2)


def test_journal_index_upgrade_preserves_existing_orders(ledger):
    add(ledger,1,filled=3,fees=.06)
    before=learning.observations('mainnet',now=NOW)
    with ledger() as c:
        c.execute('DROP INDEX us_intents_market_time')
        c.execute('DROP INDEX us_entry_execution_group')
    journal.init()
    journal.init()
    assert learning.observations('mainnet',now=NOW)==before


def test_invalid_context_rolls_back_intent(ledger):
    with pytest.raises(ValueError):
        journal.begin('bad','market','yes','buy',10,.6,execution_context={**CONTEXT,'ask_cents':float('nan')})
    assert journal.get('bad') is None


def test_duplicate_snapshots_do_not_duplicate_fill_statistics(ledger):
    journal.begin('a','market','yes','buy',10,.6,execution_context=CONTEXT)
    journal.acknowledge('a','oa')
    raw=dict(id='oa',cumQuantity=3,avgPx='.60',commissionNotionalTotalCollected='.06',
             state='ORDER_STATE_CANCELED',intent='ORDER_INTENT_BUY_LONG')
    journal.record_order(raw)
    journal.record_order(raw)
    stats=learning.summarize(learning.observations('mainnet'))
    assert stats['attempts']==1 and stats['completed']==1 and stats['fillRatePct']==30


@pytest.mark.parametrize('fail',[False,True])
def test_submission_records_context_and_latency_without_retry(ledger,monkeypatch,fail):
    calls=[]
    async def meta(_): return {'min_size':1,'tick_size':.01}
    async def request(*args,**kwargs):
        calls.append(args)
        assert journal.get('submission')['state']=='sending'
        with ledger() as c:
            assert c.execute('SELECT signal_cents FROM us_entry_execution').fetchone()[0]==59
        if fail: raise TimeoutError('uncertain')
        return {'id':'ack'}
    monkeypatch.setattr(api,'get_market_meta',meta)
    monkeypatch.setattr(api,'_request',request)
    async def submit():
        return await api.place_limit_order(ticker='market',side='yes',action='buy',count=10,
            price_cents=60,client_order_id='submission',execution_context=CONTEXT)
    if fail:
        with pytest.raises(TimeoutError): asyncio.run(submit())
    else: asyncio.run(submit())
    assert len(calls)==1
    assert journal.get('submission')['state']==('unknown' if fail else 'open')
    with ledger() as c:
        assert c.execute('SELECT response_ms FROM us_entry_execution').fetchone()[0]>=0
