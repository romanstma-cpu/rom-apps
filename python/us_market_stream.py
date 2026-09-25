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
import momentum_window

logger=logging.getLogger(__name__)
_task=None
_wanted=set()
_books={}
_trades=deque(maxlen=5000)
_connected=False
_last_message_at=0.0
_last_book_at=0.0
_last_trade_at=0.0
_connected_at=0.0
_last_disconnect_at=0.0
_reconnects=0
_trade_stall_reconnects=0
_subscription_rejections=0
_last_subscription_error=''
_auth_paused=False
_scanner_wanted=set()
MAX_WATCHED_MARKETS=500

class _UniverseChanged(Exception):
    pass
# A connection can remain open while a subscription is no longer delivering
# market data. This is a health signal rather than a hard trading block: the
# quote path has a separately bounded REST fallback.
STREAM_STALE_AFTER_SECONDS=10.0
TRADE_STALE_AFTER_SECONDS=15*60.0
BOOK_ACTIVE_WITHIN_SECONDS=30.0

def observe(*tokens):
    # The US stream rejects oversized subscription sets.  Preserve the first
    # bounded scanner universe and ignore overflow instead of slowly growing
    # an invalid subscription after every market refresh or quote request.
    for token in tokens:
        slug=(token or '').split('::')[0]
        if slug in _wanted:
            continue
        if len(_wanted) >= MAX_WATCHED_MARKETS:
            break
        if slug:
            _wanted.add(slug)

def set_scanner_universe(tokens):
    """Replace the scanner subscription set after a catalog refresh.

    Ad-hoc quote observations are kept only while capacity remains. Expired
    scanner markets must not permanently occupy one of the 500 stream slots.
    """
    global _scanner_wanted
    selected = []
    for token in tokens:
        slug = (token or '').split('::')[0]
        if slug and slug not in selected:
            selected.append(slug)
        if len(selected) >= MAX_WATCHED_MARKETS:
            break
    new_scanner = set(selected)
    extras = sorted(_wanted - _scanner_wanted - new_scanner)
    _scanner_wanted = new_scanner
    _wanted.clear()
    _wanted.update(new_scanner)
    _wanted.update(extras[:MAX_WATCHED_MARKETS-len(_wanted)])

def start():
    global _task
    if not _auth_paused and (_task is None or _task.done()) and auth.credentials_present():
        _task=asyncio.create_task(_run())

def pause_for_auth():
    global _auth_paused
    _auth_paused=True

def resume_after_auth():
    global _auth_paused
    _auth_paused=False

async def stop():
    global _task, _connected, _connected_at
    if _task:
        _task.cancel()
        try: await _task
        except asyncio.CancelledError: pass
    _task=None; _connected=False; _connected_at=0.0
    _books.clear(); _trades.clear(); _wanted.clear(); _scanner_wanted.clear()
    momentum_window.tape.reset()

def ingest(message):
    global _last_message_at, _last_book_at, _last_trade_at, _last_subscription_error
    _last_message_at=time.monotonic()
    # A valid payload proves the active subscription is usable.  Preserve the
    # cumulative rejection count for diagnostics, but do not leave the engine
    # permanently blocked after the exchange has recovered.
    _last_subscription_error=''
    book=message.get('marketData')
    if book and book.get('marketSlug'):
        _last_book_at=time.monotonic()
        _books[book['marketSlug']]=(_last_book_at,book)
    if book and book.get('marketSlug'):
        main_recorder.book(book['marketSlug'],book)
    trade=message.get('trade')
    if not trade or not trade.get('marketSlug'): return
    try:
        px=float(trade['price']['value']); qty=float(trade['quantity']['value'])
    except (KeyError,ValueError,TypeError):
        return
    side=(trade.get('taker') or {}).get('side')
    if side not in ('ORDER_SIDE_BUY','ORDER_SIDE_SELL'): return
    if not (0<px<1) or not math.isfinite(qty) or qty<=0: return
    # Stable exchange payload fingerprint avoids duplicates after reconnect.
    tid=hashlib.sha256(json.dumps(trade,sort_keys=True).encode()).hexdigest()
    normalized={'trade_id':tid,'ticker':trade['marketSlug'],'slug':trade['marketSlug'],
                    'created_time':trade.get('tradeTime',''),'count_fp':qty,'yes_price_dollars':px,
                    'no_price_dollars':1-px,'taker_side':'yes' if side=='ORDER_SIDE_BUY' else 'no'}
    # Share the tape's timestamp and replay checks with the Large Trade queue.
    # A delayed print must not become a new signal merely because it arrived
    # over a live socket; the scanner otherwise timestamps it on insertion.
    if not momentum_window.tape.add(normalized,time.time()):
        return
    _last_trade_at=time.monotonic()
    main_recorder.record('trade',trade['marketSlug'],{'id':tid,'trade':trade})
    _trades.append(normalized)

def recent(limit): return list(_trades)[-limit:]

def trade_flow_stalled(now=None):
    """True when book traffic proves the socket is alive but trades went silent."""
    now=time.monotonic() if now is None else now
    baseline=max(_last_trade_at,_connected_at)
    return bool(
        _connected and _wanted and baseline
        and _last_book_at and now-_last_book_at<=BOOK_ACTIVE_WITHIN_SECONDS
        and now-baseline>TRADE_STALE_AFTER_SECONDS
    )

def health():
    """Connection context for operators; REST remains the quote fallback."""
    now=time.monotonic()
    age=max(0.0,now-_last_message_at) if _last_message_at else None
    trade_age=max(0.0,now-_last_trade_at) if _last_trade_at else None
    book_age=max(0.0,now-_last_book_at) if _last_book_at else None
    trade_stalled=trade_flow_stalled(now)
    stale=bool(_connected and _wanted and (age is None or age>STREAM_STALE_AFTER_SECONDS))
    if _auth_paused:
        state='blocked'
    elif _last_subscription_error:
        state='blocked'
    elif stale:
        state='degraded'
    elif _connected:
        state='connected'
    elif _task is not None and not _task.done():
        state='reconnecting'
    elif auth.credentials_present():
        state='starting'
    else:
        state='stopped'
    return {
        'state':state, 'connected':bool(_connected), 'stale':stale,
        'lastMessageAgeSeconds':round(age,1) if age is not None else None,
        'staleAfterSeconds':STREAM_STALE_AFTER_SECONDS,
        'lastDisconnectAt':_last_disconnect_at or None,
        'reconnects':_reconnects, 'watchedMarkets':len(_wanted),
        'lastTradeAgeSeconds':round(trade_age,1) if trade_age is not None else None,
        'lastBookAgeSeconds':round(book_age,1) if book_age is not None else None,
        'tradeFlowStalled':trade_stalled,
        'tradeStallReconnects':_trade_stall_reconnects,
        'bufferedTrades':len(_trades),
        'subscriptionRejections':_subscription_rejections,
        'lastSubscriptionError':_last_subscription_error,
    }

def get_book(slug, max_age=2.0):
    """Return a fresh full-depth book or ``None``.

    Callers choose their own freshness budget. Trading decisions use a much
    tighter budget than display/scanner consumers and fall back to REST when
    the stream is warming up or reconnecting.
    """
    cached = _books.get((slug or '').split('::')[0])
    if not cached or time.monotonic()-cached[0] > max(0.0, float(max_age)):
        return None
    return cached[1]


def get_book_with_age(slug, max_age=2.0):
    """Return a fresh book and its local receipt age in milliseconds."""
    cached = _books.get((slug or '').split('::')[0])
    if not cached:
        return None
    age = max(0.0, time.monotonic()-cached[0])
    if age > max(0.0, float(max_age)):
        return None
    return cached[1], age*1000.0

def get_quote_cents(token):
    slug,_,side=token.rpartition('::')
    book=get_book(slug,15)
    if not book: return None
    bids=[float(x['px']['value']) for x in book.get('bids',[]) if float(x['qty'])>0]
    asks=[float(x['px']['value']) for x in book.get('offers',[]) if float(x['qty'])>0]
    bid=max(bids) if bids else None; ask=min(asks) if asks else None
    if side=='no': bid,ask=(1-ask if ask is not None else None),(1-bid if bid is not None else None)
    return {'bid_cents':math.floor(bid*100+1e-8) if bid is not None else None,'ask_cents':math.ceil(ask*100-1e-8) if ask is not None else None}

async def _run():
    global _connected, _connected_at, _last_disconnect_at, _reconnects, _trade_stall_reconnects
    global _subscription_rejections, _last_subscription_error
    while auth.credentials_present():
        try:
            async with websockets.connect('wss://api.polymarket.us/v1/ws/markets',
                    extra_headers=auth.l2_headers('GET','/v1/ws/markets'),ping_interval=20,ping_timeout=20) as ws:
                _connected=True
                _connected_at=time.monotonic()
                subscribed=set()
                while True:
                    if subscribed - _wanted:
                        # The protocol has no unsubscribe in this client. A
                        # clean reconnect replaces the old subscription set.
                        raise _UniverseChanged()
                    missing=sorted(_wanted-subscribed)
                    # One market data plus one trade subscription is opened per
                    # batch.  Keep the feed aligned with scanner.sync_markets'
                    # 500-market universe (five batches / ten subscriptions).
                    pending=missing[:MAX_WATCHED_MARKETS]
                    for offset in range(0,len(pending),100):
                        batch=pending[offset:offset+100]
                        for kind in ('MARKET_DATA','TRADE'):
                            await ws.send(json.dumps({'subscribe':{'requestId':f'{kind}-{len(subscribed)+offset}',
                                'subscriptionType':'SUBSCRIPTION_TYPE_'+kind,'marketSlugs':batch}}))
                    # Only mark batches that were actually sent.  Marking the
                    # entire missing set made overflow markets look subscribed
                    # even though no request for them left the process.
                    subscribed.update(pending)
                    try:
                        message=json.loads(await asyncio.wait_for(ws.recv(),timeout=2))
                        if 'error' in message:
                            _subscription_rejections += 1
                            detail=' '.join(json.dumps(message.get('error'), sort_keys=True).split())[:240]
                            _last_subscription_error=detail or 'Polymarket US rejected a market-data subscription'
                            logger.warning('US market subscription rejected: %s', _last_subscription_error)
                        else:
                            ingest(message)
                            if trade_flow_stalled():
                                _trade_stall_reconnects+=1
                                main_recorder.record('gap','',{'reason':'trade subscription stalled'})
                                raise RuntimeError('trade subscription stalled while books remained active')
                    except asyncio.TimeoutError: pass
        except _UniverseChanged:
            _connected=False
            _last_disconnect_at=time.monotonic()
            main_recorder.record('gap','',{'reason':'market universe refreshed'})
        except asyncio.CancelledError: raise
        except Exception as exc:
            _connected=False
            _last_disconnect_at=time.monotonic()
            _reconnects+=1
            momentum_window.tape.reset()
            main_recorder.record('gap','',{'reason':'market stream disconnected'})
            logger.warning('US market stream disconnected: %s',type(exc).__name__)
            await asyncio.sleep(5)
        finally:
            _connected=False; _connected_at=0.0
