import asyncio
import json
import sqlite3
import pytest
import db
import order_journal as journal
import polymarket_api as api
import trader
import us_account_stream as stream
from test_engine_integration import whale_signal, seed_position
from config import merge_with_defaults


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'db_path', lambda: tmp_path/'orders.db')
    db.init_db()
    journal.init()
    stream.consume_dirty()


def raw_order(**overrides):
    return {'id':'ex-1','marketSlug':'market','intent':'ORDER_INTENT_BUY_LONG',
            'state':'ORDER_STATE_PARTIALLY_FILLED','quantity':10,'cumQuantity':4,
            'price':{'value':'.6'},'avgPx':{'value':'.55'},
            'commissionNotionalTotalCollected':{'value':'.03'}, **overrides}


def begin():
    journal.begin('local','market','yes','buy',10,.6)
    journal.acknowledge('local','ex-1')


def test_partial_fill_preserves_remaining_reservation_and_exact_fees():
    begin()
    journal.record_order(raw_order())
    r=journal.get('local')
    assert r['state']=='open'
    assert r['filled']==4 and r['avg_price']==.55 and r['fees_usd']==.03
    assert r['reserved_usd']==pytest.approx(3.6)
    pid=seed_position(client_order_id='local',order_id='ex-1',status='submitted',ticker='market',limit_price_cents=60)
    with db.get_db() as c: pos=db.fetch_position_by_id(c,pid)
    updated=trader.sync_journal_position(pos,r)
    assert updated['cost_usd']==pytest.approx(2.23)
    with db.get_db() as c:
        assert db.current_total_exposure_usd(c,'mainnet')==pytest.approx(5.83)


@pytest.mark.parametrize('missing', ['avgPx','commissionNotionalTotalCollected'])
def test_missing_accounting_blocks_without_inventing_price(missing):
    begin()
    raw=raw_order(state='ORDER_STATE_FILLED',cumQuantity=10)
    raw.pop(missing)
    journal.record_order(raw)
    assert journal.get('local')['state']=='accounting_pending'
    assert journal.blocker()
    if missing=='avgPx':
        normalized=api._normalize_order(raw)
        assert normalized['price'] is None
        assert trader._parse_polymarket_order(normalized)['avg_cents'] is None


def test_duplicate_out_of_order_updates_do_not_double_count_or_reopen():
    begin()
    execution={'id':'fill-1','tradeId':'trade-1','order':raw_order(),
               'lastShares':'4','lastPx':{'value':'.55'},
               'commissionNotionalCollected':{'value':'.03'},'type':'EXECUTION_TYPE_PARTIAL_FILL'}
    message={'orderSubscriptionUpdate':{'execution':execution}}
    stream.ingest(message)
    stream.ingest(message)
    journal.record_order(raw_order(state='ORDER_STATE_CANCELED'))
    journal.record_order(raw_order(cumQuantity=2))
    stream.ingest(message)
    assert journal.get('local')['state']=='canceled'
    assert journal.get('local')['filled']==4
    assert journal.get('local')['reserved_usd']==0
    with db.get_db() as c:
        assert c.execute('SELECT count(*) FROM us_executions').fetchone()[0]==1
    assert stream.consume_dirty()


def test_execution_before_acknowledgement_is_replayed():
    journal.begin('local','market','yes','buy',10,.6)
    journal.record_order(raw_order(state='ORDER_STATE_FILLED',cumQuantity=10))
    journal.acknowledge('local','ex-1')
    assert journal.get('local')['state']=='filled'


def test_fractional_execution_retained_without_rounding_to_position():
    begin()
    journal.record_order(raw_order(cumQuantity='0.5'))
    assert journal.get('local')['filled']==.5
    assert journal.get('local')['state']=='accounting_pending'


@pytest.mark.asyncio
@pytest.mark.parametrize('failure',['timeout','missing_id','crash'])
async def test_submission_failure_is_durable_and_cannot_repeat(monkeypatch,failure):
    calls=[]
    async def meta(*a):return {'min_size':1,'tick_size':.01}
    async def request(*args,**kwargs):
        calls.append(args)
        # Intent is already committed on an independent database connection.
        assert journal.get('local')['state']=='sending'
        if failure=='timeout':raise TimeoutError()
        if failure=='crash':raise asyncio.CancelledError()
        return {}
    monkeypatch.setattr(api,'get_market_meta',meta)
    monkeypatch.setattr(api,'_request',request)
    with pytest.raises((TimeoutError,api.PolymarketAPIError,asyncio.CancelledError)):
        await api.place_limit_order(ticker='market',side='yes',action='buy',count=10,price_cents=60,client_order_id='local')
    journal.init() # Reinitialization simulates recovery from disk, not process memory.
    assert journal.get('local')['state']=='unknown'
    assert journal.get('local')['reserved_usd']==6
    with pytest.raises(journal.RecoveryRequired):
        await api.place_limit_order(ticker='other',side='yes',action='buy',count=10,price_cents=60,client_order_id='new')
    assert len(calls)==1


@pytest.mark.asyncio
async def test_definitive_rejection_releases_intent_without_resubmitting_id(monkeypatch):
    async def meta(*a):return {'min_size':1,'tick_size':.01}
    async def request(*a,**k):raise api.PolymarketAPIError(422,'Rejected')
    monkeypatch.setattr(api,'get_market_meta',meta)
    monkeypatch.setattr(api,'_request',request)
    with pytest.raises(api.PolymarketAPIError):
        await api.place_limit_order(ticker='market',side='yes',action='buy',count=10,price_cents=60,client_order_id='local')
    assert journal.get('local')['state']=='rejected'
    assert journal.get('local')['reserved_usd']==0
    assert journal.blocker() is None
    with pytest.raises(journal.RecoveryRequired):journal.begin('local','market','yes','buy',10,.6)


@pytest.mark.asyncio
async def test_cancel_race_retains_final_fill_and_actual_price(monkeypatch):
    begin()
    gets=0
    async def request(method,path,**kwargs):
        nonlocal gets
        if method=='POST':return {}
        gets+=1
        return {'order':raw_order(cumQuantity=4 if gets==1 else 10,
                                 state='ORDER_STATE_PARTIALLY_FILLED' if gets==1 else 'ORDER_STATE_FILLED')}
    monkeypatch.setattr(api,'_request',request)
    await api.cancel_order('ex-1')
    assert journal.get('local')['state']=='filled'
    assert journal.get('local')['filled']==10
    assert journal.get('local')['avg_price']==.55


@pytest.mark.asyncio
async def test_cancel_ack_without_terminal_state_keeps_reservation(monkeypatch):
    begin()
    async def request(method,path,**kwargs):return {} if method=='POST' else {'order':raw_order()}
    monkeypatch.setattr(api,'_request',request)
    with pytest.raises(journal.RecoveryRequired):await api.cancel_order('ex-1')
    assert journal.get('local')['state']=='cancel_pending'
    assert journal.get('local')['reserved_usd']>0


@pytest.mark.asyncio
async def test_repeated_404_never_releases_known_order(monkeypatch):
    begin()
    async def missing(*args):raise api.PolymarketAPIError(404,'Not found')
    monkeypatch.setattr(trader,'get_order',missing)
    for _ in range(8):await trader.reconcile_order_journal()
    assert journal.get('local')['state']=='unknown'
    assert journal.get('local')['reserved_usd']==6


@pytest.mark.asyncio
async def test_operator_recovery_requires_authenticated_matching_order(monkeypatch):
    journal.begin('local','market','yes','buy',10,.6)
    journal.state('local','unknown')
    async def request(*a,**k):return {'order':raw_order(marketSlug='wrong')}
    monkeypatch.setattr(api,'_request',request)
    with pytest.raises(journal.RecoveryRequired):await api.recover_order('local','ex-1')
    assert journal.get('local')['order_id'] is None
    async def request(*a,**k):return {'order':raw_order()}
    monkeypatch.setattr(api,'_request',request)
    assert (await api.recover_order('local','ex-1'))['state']=='open'


@pytest.mark.asyncio
async def test_main_intent_exists_during_post_and_survives_cancellation(monkeypatch):
    cfg=merge_with_defaults({'enable_trading':True})
    async def quote(*a):return {'bid_cents':59,'ask_cents':60}
    async def meta(*a):return {'min_size':1}
    async def post(**kw):
        with db.get_db() as c:
            assert db.count_open_bot_positions(c,'mainnet')==1
            assert db.current_total_exposure_usd(c,'mainnet')>0
        raise asyncio.CancelledError()
    monkeypatch.setattr(trader,'get_quote',quote)
    monkeypatch.setattr(trader,'get_market_meta',meta)
    monkeypatch.setattr(trader,'place_limit_order',post)
    with pytest.raises(asyncio.CancelledError):await trader.execute_signal(whale_signal(),'whale',cfg,1000)
    with db.get_db() as c:
        assert db.get_pending_bot_positions(c)[0]['status']=='unknown'
        assert db.exists_position_in_market(c,'WHALE-1','yes','mainnet')


def test_exit_recovery_applies_partial_and_late_final_fill_once():
    pid=seed_position(ticker='market',filled_contracts=10,cost_usd=5,status='filled')
    journal.begin('sell','market','yes','sell',10,.8,position_id=pid,exit_reason='take_profit')
    journal.acknowledge('sell','ex-1')
    raw=raw_order(intent='ORDER_INTENT_SELL_LONG',price={'value':'.8'},avgPx={'value':'.8'})
    journal.record_order(raw)
    journal.apply_exit_fills()
    journal.apply_exit_fills()
    with db.get_db() as c:
        p=db.fetch_position_by_id(c,pid)
    assert p['filled_contracts']==6 and p['cost_usd']==3
    assert p['status']=='unknown' # Leaves still open: cannot issue another sell.
    assert journal.exit_totals(pid)['realized']==pytest.approx(1.17)
    journal.state('sell','unknown','Disconnected')
    journal.init()
    journal.record_order({**raw,'cumQuantity':10,'state':'ORDER_STATE_FILLED',
                          'commissionNotionalTotalCollected':{'value':'.08'}})
    journal.apply_exit_fills()
    assert journal.apply_exit_fills()==[]
    with db.get_db() as c:p=db.fetch_position_by_id(c,pid)
    assert p['resolved']==1 and p['filled_contracts']==0
    assert p['settlement_usd']==pytest.approx(7.92)
    assert p['pnl_usd']==pytest.approx(2.92)


@pytest.mark.asyncio
async def test_partial_exit_then_settlement_includes_realized_proceeds(monkeypatch):
    pid=seed_position(ticker='market',filled_contracts=10,cost_usd=5,status='filled')
    journal.begin('sell','market','yes','sell',10,.8,position_id=pid)
    journal.acknowledge('sell','ex-1')
    journal.record_order(raw_order(intent='ORDER_INTENT_SELL_LONG',state='ORDER_STATE_CANCELED',
                                  price={'value':'.8'},avgPx={'value':'.8'}))
    journal.apply_exit_fills()
    async def market(*a,**k):return {'market':{'status':'settled','result':'yes','settlement_value_dollars':1}}
    monkeypatch.setattr(trader,'fetch_markets_map',market)
    await trader.mark_resolved_positions(merge_with_defaults({}))
    with db.get_db() as c:p=db.fetch_position_by_id(c,pid)
    assert p['pnl_usd']==pytest.approx(4.17) # 3.17 proceeds + 6 settlement - 5 original basis
    assert p['settlement_usd']==pytest.approx(9.17)
    assert journal.apply_exit_fills()==[]


@pytest.mark.asyncio
async def test_unknown_known_id_recovers_from_rest(monkeypatch):
    begin()
    journal.state('local','unknown')
    async def request(*a,**k):return {'order':raw_order(state='ORDER_STATE_FILLED',cumQuantity=10)}
    monkeypatch.setattr(api,'_request',request)
    monkeypatch.setattr(trader,'get_order',api.get_order)
    await trader.reconcile_order_journal()
    assert journal.get('local')['state']=='filled'
    assert journal.blocker() is None


@pytest.mark.parametrize('reset',[db.clear_trade_history,db.factory_reset])
def test_history_reset_cannot_erase_pending_order_risk(reset):
    begin()
    with pytest.raises(ValueError,match='reconciliation'):
        reset()
    assert journal.get('local')['reserved_usd']==6
