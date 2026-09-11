"""Polymarket US retail adapter. No international wallet APIs or order retries."""
from __future__ import annotations
import asyncio
import json
import math
import time
import uuid
import order_journal
import main_recorder
from urllib.parse import quote
import httpx
import polymarket_auth as auth
from categorize import categorize_by_keywords

PUBLIC_BASE = 'https://gateway.polymarket.us'
PRIVATE_BASE = 'https://api.polymarket.us'
_client = None
_meta = {}
_crypto_market_cache = (0.0, [])
_crypto_market_task = None

ERROR_DETAIL_CHARS = 500

class PolymarketAPIError(Exception):
    def __init__(self, status_code, message, *, detail=''):
        self.status_code = status_code
        self.status = status_code
        self.reason = message
        self.detail = detail or ''
        # `.body` stays the one string callers log, now carrying the server's
        # own explanation after the reason phrase. Locally raised errors pass
        # no detail and read exactly as before.
        self.body = f'{message}: {detail}' if detail else message
        super().__init__(f'Polymarket US ({status_code}): {self.body}')


def _error_detail(response):
    """The server's own words for a rejection, so it can be diagnosed.

    `reason_phrase` alone flattens every rejection to 'Unprocessable Entity',
    which says nothing about which field the exchange objected to. The body is
    returned verbatim, whitespace-collapsed and truncated: no key of a US error
    payload has ever been observed here, so picking one to surface would be a
    guess about a contract we have not seen.
    """
    try:
        raw = response.text
    except (UnicodeDecodeError, ValueError, httpx.ResponseNotRead):
        return f'<{len(response.content)} undecodable bytes>'
    text = ' '.join(raw.split())
    if len(text) > ERROR_DETAIL_CHARS:
        return text[:ERROR_DETAIL_CHARS] + '...'
    return text

def geoblock_active(): return False
def register_recycle_hook(fn): pass

async def close_clients():
    global _client
    import us_market_stream
    import us_account_stream
    await us_account_stream.stop()
    await us_market_stream.stop()
    if _client is not None: await _client.aclose()
    _client = None

async def _request(method, path, *, private=False, params=None, body=None):
    global _client
    if not path.startswith('/v1/'): raise ValueError('Expected a US API v1 path')
    if _client is None: _client=httpx.AsyncClient(timeout=20, follow_redirects=False)
    headers=auth.l2_headers(method,path) if private else {}
    response=await _client.request(method, (PRIVATE_BASE if private else PUBLIC_BASE)+path,
                                   headers=headers, params=params, json=body)
    if response.status_code >= 300:
        raise PolymarketAPIError(response.status_code, response.reason_phrase,
                                 detail=_error_detail(response))
    return response.json() if response.content else {}

def _money(value, default=0.0):
    if isinstance(value,dict): value=value.get('value')
    if value is None: return default
    result=float(value)
    if not math.isfinite(result): raise ValueError('Non-finite API amount')
    return result

def _list(value):
    if isinstance(value,str):
        try: return json.loads(value)
        except ValueError: return []
    return value if isinstance(value,list) else []

def _normalize_market(raw):
    slug=raw.get('slug')
    if not slug: return None
    prices=_list(raw.get('outcomePrices'))
    last=_money(prices[0]) if prices else 0.0
    bid=_money(raw.get('bestBidQuote'),last); ask=_money(raw.get('bestAskQuote'),last)
    tick=_money(raw.get('orderPriceMinTickSize'),.01)
    meta={'slug':slug,'event_slug':raw.get('eventSlug',''), 'question':raw.get('question') or raw.get('title') or slug,
          'yes_token':slug+'::yes','no_token':slug+'::no','tick_size':tick,
          'min_size':_money(raw.get('minimumTradeQty'),1), 'neg_risk':False,'outcomes':_list(raw.get('outcomes'))}
    _meta[slug]=meta
    main_recorder.record('market',slug,{'min_size':meta['min_size'],'tick_size':tick,
        'event_ticker':meta['event_slug'],'close_time':raw.get('endDate',''),
        'active':bool(raw.get('active',True)) and not raw.get('closed',False)})
    return {'ticker':slug,'condition_id':slug,'event_ticker':meta['event_slug'],'series_ticker':'',
            'title':meta['question'],'yes_sub_title':meta['outcomes'][0] if meta['outcomes'] else 'Yes',
            'category':raw.get('category') or categorize_by_keywords(meta['question'],slug),
            'status':'closed' if raw.get('closed') else ('open' if raw.get('active',True) else 'inactive'),
            'close_time':raw.get('endDate',''),'slug':slug,'yes_token':meta['yes_token'],'no_token':meta['no_token'],
            'tick_size':tick,'neg_risk':False,'fee_schedule':None,
            'volume_fp':_money(raw.get('volume')),'volume_24h_fp':_money(raw.get('volume24hr')),
            'open_interest_fp':0,'yes_bid_dollars':bid,'yes_ask_dollars':ask,'last_price_dollars':last,
            'no_price_dollars':1-last,'result':'','settlement_value_dollars':None}

async def fetch_markets(limit=100, offset=0, **kwargs):
    data=await _request('GET','/v1/markets',params={'limit':min(100,limit),'offset':offset,'active':'true','closed':'false'})
    return [m for r in data.get('markets',[]) if (m:=_normalize_market(r))]

async def fetch_all_open_markets(max_pages=10):
    rows=[]
    for page in range(max_pages):
        batch=await fetch_markets(offset=page*100); rows.extend(batch)
        if len(batch)<100: break
    import us_market_stream
    us_market_stream.observe(*(m['ticker'] for m in rows))
    us_market_stream.start()
    return rows

async def fetch_market(ticker):
    data=await _request('GET','/v1/markets',params={'slug':ticker,'limit':1})
    rows=data.get('markets',[])
    market=_normalize_market(rows[0]) if rows else None
    if market and market['status']=='closed':
        try:
            result=await _request('GET','/v1/markets/'+quote(ticker,safe='')+'/settlement')
            if result.get('settlement') is not None:
                payout=_money(result['settlement'])
                if 0<=payout<=1:
                    main_recorder.record('settlement',ticker,{'yes_payout':payout})
                    market.update(status='settled',settlement_value_dollars=payout,
                                  result='yes' if payout==1 else ('no' if payout==0 else ''))
        except PolymarketAPIError as exc:
            if exc.status!=404: raise
    return market

async def fetch_markets_map(tickers,concurrency=8):
    sem=asyncio.Semaphore(concurrency)
    async def one(t):
        async with sem: return t, await fetch_market(t)
    return {t:m for t,m in await asyncio.gather(*(one(t) for t in set(tickers))) if m}

async def get_market_meta(ticker):
    if ticker not in _meta: await fetch_market(ticker)
    return _meta.get(ticker)

async def fetch_events(limit=100, offset=0, **kwargs):
    data=await _request('GET','/v1/events',params={'limit':limit,'offset':offset,'active':'true','closed':'false'})
    return [{**e,'event_ticker':e.get('slug',''),'series_ticker':e.get('seriesSlug','')} for e in data.get('events',[])], None

async def fetch_series(series_ticker): return await _request('GET','/v1/series/'+quote(series_ticker,safe=''))
async def web_market_url(ticker, **kwargs): return 'https://polymarket.us/event/'+quote(ticker,safe='')

async def _book(ticker):
    data=await _request('GET','/v1/markets/'+quote(ticker,safe='')+'/book')
    main_recorder.book(ticker,data.get('marketData',{}))
    return data.get('marketData',{})

async def get_quote(ticker,side):
    if side not in ('yes','no'): raise ValueError('Side must be yes or no')
    book=await _book(ticker)
    return quote_from_book(book,side)

def quote_from_book(book,side):
    """Best prices plus the resting size behind them.

    ``ask_levels`` are the executable buy levels in improving order, so a
    caller can price a specific order size instead of assuming the touch
    absorbs it. Sizes are contract quantities at that price.
    """
    bid_rows=sorted(((_money(x['px']),_money(x.get('qty'))) for x in book.get('bids',[])
                     if _money(x.get('qty'))>0),reverse=True)
    ask_rows=sorted((_money(x['px']),_money(x.get('qty'))) for x in book.get('offers',[])
                    if _money(x.get('qty'))>0)
    if side=='no':
        # NO is the mirror of YES: buying NO consumes the YES bid ladder.
        bid_rows,ask_rows=([(1-p,q) for p,q in ask_rows],[(1-p,q) for p,q in bid_rows])
    bid=bid_rows[0][0] if bid_rows else None; ask=ask_rows[0][0] if ask_rows else None
    return {'bid_cents':math.floor(bid*100+1e-8) if bid is not None else None,
            'ask_cents':math.ceil(ask*100-1e-8) if ask is not None else None,
            'ask_levels':[[math.ceil(p*100-1e-8),q] for p,q in ask_rows],
            'bid_levels':[[math.floor(p*100+1e-8),q] for p,q in bid_rows]}

async def get_orderbook(ticker):
    b=await _book(ticker)
    return {'yes':[[round(_money(x['px'])*100),_money(x['qty'])] for x in b.get('bids',[])],
            'no':[[round((1-_money(x['px']))*100),_money(x['qty'])] for x in b.get('offers',[])]}

async def book_imbalance(token_id,levels=3):
    ticker,_,side=token_id.rpartition('::'); b=await get_orderbook(ticker)
    yes=sum(x[1] for x in sorted(b['yes'],reverse=True)[:levels]); no=sum(x[1] for x in sorted(b['no'],reverse=True)[:levels])
    return ((yes-no)/(yes+no))*(1 if side=='yes' else -1) if yes+no else None

async def updown_arb_edge(ticker):
    yes,no=await asyncio.gather(get_quote(ticker,'yes'),get_quote(ticker,'no'))
    y,n=yes['ask_cents'],no['ask_cents']
    if y is None or n is None: return None
    return {'upAsk':y/100,'downAsk':n/100,'sum':(y+n)/100,'edgeCents':100-y-n}

async def fetch_crypto_updown(asset, interval='15m', *,fast=False):
    global _crypto_market_cache, _crypto_market_task
    import re
    from datetime import datetime,timezone
    seconds={'5m':300,'15m':900,'1h':3600,'4h':14400}.get(interval)
    if seconds is None: return []
    pattern=re.compile(r'^'+re.escape(asset.lower())+r'-updown-'+re.escape(interval)+r'-(\d+)$')
    if time.monotonic()-_crypto_market_cache[0]>30:
        if _crypto_market_task is None or _crypto_market_task.done():
            _crypto_market_task=asyncio.create_task(fetch_all_open_markets())
        _crypto_market_cache=(time.monotonic(),await _crypto_market_task)
    rows=[]
    for m in _crypto_market_cache[1]:
        match=pattern.match(m['slug'])
        if not match: continue
        start=int(match[1])
        rows.append({**m,'window_start_epoch':start,'window_close_epoch':start+seconds,'interval_sec':seconds,
                     'close_time':datetime.fromtimestamp(start+seconds,timezone.utc).isoformat()})
    return rows

async def fetch_recent_trades(limit=1000):
    import us_market_stream
    us_market_stream.start()
    return us_market_stream.recent(limit)

async def get_balance():
    data=await _request('GET','/v1/account/balances',private=True)
    usd=next((b for b in data.get('balances',[]) if b.get('currency')=='USD'),None)
    if usd is None or 'buyingPower' not in usd: raise PolymarketAPIError(502,'USD buying power missing')
    return {'balance':round(_money(usd['buyingPower'])*100),'portfolio_value':round(_money(usd.get('assetNotional'))*100)}

async def ensure_api_creds(): await get_balance()
async def check_trading_ready():
    balance=await get_balance()
    return {'ok':balance['balance']>0,'address':auth.get_address(),'balanceUsd':balance['balance']/100,
            'issues':[] if balance['balance']>0 else ['No available USD buying power']}

async def get_positions(limit=1000, *, settlement_status=None,paginate=True,user=None):
    if user and user!=auth.trading_address(): raise PolymarketAPIError(400,'Wallet copy trading is unavailable on Polymarket US')
    out=[]; cursor=None; seen=set()
    while True:
        params={'limit':min(limit,100)}
        if cursor: params['cursor']=cursor
        data=await _request('GET','/v1/portfolio/positions',private=True,params=params)
        if not isinstance(data.get('positions'),dict):
            raise PolymarketAPIError(502,'Positions missing from response')
        for slug,p in data.get('positions',{}).items():
            qty=_money(p.get('netPositionDecimal',p.get('netPosition')))
            if not qty: continue
            meta=p.get('marketMetadata') or {}
            out.append({'ticker':slug,'event_ticker':meta.get('eventSlug',''),'title':meta.get('title',slug),
                        'category':'','position_fp':qty,'market_exposure_dollars':abs(_money(p.get('cost'))),
                        'fees_paid_dollars':0,'redeemable':bool(p.get('expired')),'cur_price':None})
        cursor=data.get('nextCursor')
        if not paginate or data.get('eof') or not cursor: break
        if cursor in seen: raise PolymarketAPIError(502,'Repeated positions cursor')
        seen.add(cursor)
    return out

async def get_settled_positions(limit=1000): return [p for p in await get_positions(limit) if p['redeemable']]

async def get_activity(limit=500, *,user=None):
    if user and user!=auth.trading_address(): raise PolymarketAPIError(400,'Wallet activity is unavailable on Polymarket US')
    # US activity omits outcome/action; reconcile fills from order records instead.
    return []

def _normalize_order(raw):
    outcome=raw.get('outcomeSide') or ('OUTCOME_SIDE_NO' if 'SHORT' in raw.get('intent','') else 'OUTCOME_SIDE_YES')
    px=order_journal.number(raw.get('avgPx'))
    if outcome=='OUTCOME_SIDE_NO' and px is not None: px=1-px
    status={'ORDER_STATE_NEW':'live','ORDER_STATE_PENDING_NEW':'pending','ORDER_STATE_PARTIALLY_FILLED':'live',
            'ORDER_STATE_FILLED':'matched','ORDER_STATE_CANCELED':'canceled','ORDER_STATE_REJECTED':'canceled',
            'ORDER_STATE_EXPIRED':'canceled'}.get(raw.get('state',''),'pending')
    return {**raw,'order_id':raw.get('id',''),'original_size':raw.get('quantity',0),
            'size_matched':raw.get('cumQuantity',0),'price':px,'status':status,
            'execution_price_known':px is not None,
            'fees_usd':order_journal.number(raw.get('commissionNotionalTotalCollected'))}

async def get_order(order_id):
    data=await _request('GET','/v1/order/'+quote(order_id,safe=''),private=True)
    raw=data.get('order')
    if not isinstance(raw,dict): raise PolymarketAPIError(502,'Order missing from response')
    order_journal.record_order(raw)
    return {'order':_normalize_order(raw)}

async def get_fills_for_order(order_id,limit=200):
    # One aggregate fill represents the cumulative exchange execution, not a trade ID.
    order=(await get_order(order_id))['order']
    count=_money(order.get('size_matched'))
    if count<=0: return []
    if not order.get('execution_price_known'):
        raise PolymarketAPIError(502,'Execution price unavailable; reconciliation required')
    side='no' if 'SHORT' in order.get('intent','') or order.get('outcomeSide')=='OUTCOME_SIDE_NO' else 'yes'
    action='sell' if 'SELL' in order.get('intent','') or order.get('action')=='ORDER_ACTION_SELL' else 'buy'
    return [{'order_id':order_id,'count_fp':count,'price_cents':round(order['price']*100),
             'side':side,'action':action}]
async def get_fills_since(after_ts_unix,limit=200): return []

async def place_limit_order(*,ticker,side,action,count,price_cents,client_order_id=None,order_type='GTC',position_id=None,exit_reason='exit'):
    if side not in ('yes','no') or action not in ('buy','sell'): raise ValueError('Invalid order side/action')
    if isinstance(count,bool) or not isinstance(count,int) or count<=0: raise ValueError('Order count must be a positive integer')
    if not isinstance(price_cents,int) or not 1<=price_cents<=99: raise ValueError('Price must be 1..99 cents')
    tif={'GTC':'GOOD_TILL_CANCEL','FOK':'FILL_OR_KILL','FAK':'IMMEDIATE_OR_CANCEL','IOC':'IMMEDIATE_OR_CANCEL'}
    if order_type not in tif: raise ValueError('Unsupported order time in force')
    meta=await get_market_meta(ticker)
    if not meta: raise PolymarketAPIError(404,'Market not found on Polymarket US')
    if count<meta['min_size']: raise ValueError('Order below market minimum quantity')
    price=(price_cents if side=='yes' else 100-price_cents)/100
    tick=meta['tick_size']
    if tick<=0 or abs(price/tick-round(price/tick))>1e-7: raise ValueError('Price does not match market tick size')
    payload={'marketSlug':ticker,'type':'ORDER_TYPE_LIMIT','price':{'value':f'{price:.2f}','currency':'USD'},
             'quantity':count,'tif':'TIME_IN_FORCE_'+tif[order_type],
             'intent':'ORDER_INTENT_'+action.upper()+('_LONG' if side=='yes' else '_SHORT'),
             'manualOrderIndicator':'MANUAL_ORDER_INDICATOR_AUTOMATIC'}
    local_id=client_order_id or 'rom-'+uuid.uuid4().hex
    # The retail US endpoint does not document a client idempotency field.
    # Persist locally before POST and never retry an uncertain submission.
    order_journal.begin(local_id,ticker,side,action,count,price_cents/100,position_id,exit_reason)
    try:
        response=await _request('POST','/v1/orders',private=True,body=payload)
        oid=response.get('id')
        if not oid: raise PolymarketAPIError(502,'Order acknowledgement missing ID; reconcile before retrying')
        order_journal.acknowledge(local_id,oid)
        for execution in response.get('executions',[]):
            order_journal.record_execution(execution)
    except BaseException as exc:
        rejected=isinstance(exc,PolymarketAPIError) and exc.status in (400,401,403,422)
        order_journal.state(local_id,'rejected' if rejected else 'unknown',type(exc).__name__)
        raise
    return {'order':{'order_id':oid,'status':'pending'},'raw':response}

async def cancel_order(order_id):
    order=(await get_order(order_id))['order']
    with order_journal.db.get_db() as c:
        c.execute("UPDATE us_order_intents SET state='cancel_pending' WHERE order_id=? AND state NOT IN ('filled','canceled','rejected')",(order_id,))
    await _request('POST','/v1/order/'+quote(order_id,safe='')+'/cancel',private=True,body={'marketSlug':order['marketSlug']})
    confirmed=(await get_order(order_id))['order']
    if confirmed['status'] not in ('canceled','matched'):
        raise order_journal.RecoveryRequired('Cancellation is not yet confirmed; order remains reserved')
    return {'canceled':[order_id]}


async def recover_order(local_id, exchange_order_id):
    data=await _request('GET','/v1/order/'+quote(exchange_order_id,safe=''),private=True)
    raw=data.get('order') or {}
    order_journal.attach_verified_order(local_id,raw)
    return order_journal.get(local_id)
