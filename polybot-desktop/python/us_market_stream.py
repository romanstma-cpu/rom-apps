"""Authenticated US market books and trade tape, shared by scanners and crypto."""
import asyncio
from collections import deque
import hashlib
import json
import logging
import time
import math
import websockets
import polymarket_auth as auth
import main_recorder

logger=logging.getLogger(__name__)
_task=None
_wanted=set()
_books={}
_trades=deque(maxlen=5000)

def observe(*tokens):
    _wanted.update(t.split('::')[0] for t in tokens if t)

def start():
    global _task
    if (_task is None or _task.done()) and auth.credentials_present():
        _task=asyncio.create_task(_run())

async def stop():
    global _task
    if _task:
        _task.cancel()
        try: await _task
        except asyncio.CancelledError: pass
    _task=None
    _books.clear(); _trades.clear(); _wanted.clear()

def ingest(message):
    book=message.get('marketData')
    if book and book.get('marketSlug'): _books[book['marketSlug']]=(time.monotonic(),book)
    if book and book.get('marketSlug'):
        main_recorder.book(book['marketSlug'],book)
    trade=message.get('trade')
    if not trade or not trade.get('marketSlug'): return
    px=float(trade['price']['value']); qty=float(trade['quantity']['value'])
    side=(trade.get('taker') or {}).get('side')
    if side not in ('ORDER_SIDE_BUY','ORDER_SIDE_SELL'): return
    if not (0<=px<=1) or qty<=0: return
    # Stable exchange payload fingerprint avoids duplicates after reconnect.
    tid=hashlib.sha256(json.dumps(trade,sort_keys=True).encode()).hexdigest()
    main_recorder.record('trade',trade['marketSlug'],{'id':tid,'trade':trade})
    _trades.append({'trade_id':tid,'ticker':trade['marketSlug'],'slug':trade['marketSlug'],
                    'created_time':trade['tradeTime'],'count_fp':qty,'yes_price_dollars':px,
                    'no_price_dollars':1-px,'taker_side':'yes' if side=='ORDER_SIDE_BUY' else 'no'})

def recent(limit): return list(_trades)[-limit:]
def get_quote_cents(token):
    slug,_,side=token.rpartition('::')
    cached=_books.get(slug)
    if not cached or time.monotonic()-cached[0]>15: return None
    book=cached[1]
    bids=[float(x['px']['value']) for x in book.get('bids',[]) if float(x['qty'])>0]
    asks=[float(x['px']['value']) for x in book.get('offers',[]) if float(x['qty'])>0]
    bid=max(bids) if bids else None; ask=min(asks) if asks else None
    if side=='no': bid,ask=(1-ask if ask is not None else None),(1-bid if bid is not None else None)
    return {'bid_cents':math.floor(bid*100+1e-8) if bid is not None else None,'ask_cents':math.ceil(ask*100-1e-8) if ask is not None else None}

async def _run():
    while auth.credentials_present():
        try:
            async with websockets.connect('wss://api.polymarket.us/v1/ws/markets',
                    extra_headers=auth.l2_headers('GET','/v1/ws/markets'),ping_interval=20,ping_timeout=20) as ws:
                subscribed=set()
                while True:
                    missing=sorted(_wanted-subscribed)
                    for offset in range(0,len(missing),100):
                        batch=missing[offset:offset+100]
                        for kind in ('MARKET_DATA','TRADE'):
                            await ws.send(json.dumps({'subscribe':{'requestId':f'{kind}-{len(subscribed)+offset}',
                                'subscriptionType':'SUBSCRIPTION_TYPE_'+kind,'marketSlugs':batch}}))
                    subscribed.update(missing)
                    try:
                        message=json.loads(await asyncio.wait_for(ws.recv(),timeout=2))
                        if 'error' in message: logger.warning('US market subscription rejected')
                        else: ingest(message)
                    except asyncio.TimeoutError: pass
        except asyncio.CancelledError: raise
        except Exception as exc:
            main_recorder.record('gap','',{'reason':'market stream disconnected'})
            logger.warning('US market stream disconnected: %s',type(exc).__name__)
            await asyncio.sleep(5)
