"""Bounded, opt-in via mainRecordSignals, point-in-time evidence for US replay."""
from collections import deque
import json
import math
import threading
import time
import db

_enabled = False
_queue = deque()
_lock = threading.Lock()
_dropped = 0
_book_at = {}
_last_prune = 0
_last_blocker = ('', 0.0)
MAX_QUEUE = 20000
FEATURE_VERSION = 'candidate-book-v2'
SCHEMA = """
CREATE TABLE IF NOT EXISTS main_replay_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL, kind TEXT NOT NULL,
 ticker TEXT NOT NULL, payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS main_replay_time ON main_replay_events(at,id);
"""


def configure(enabled):
    global _enabled
    if bool(enabled) != _enabled:
        _book_at.clear()
    changed = bool(enabled) != _enabled
    _enabled = bool(enabled)
    if changed and _enabled:
        record('gap', '', {'reason': 'recording started or resumed'})


def record(kind, ticker, payload, *, at=None):
    global _dropped
    if not _enabled:
        return
    # Serialize now, before callers mutate their market or signal objects.
    event = (time.time() if at is None else at,kind,ticker,json.dumps(payload,allow_nan=False))
    with _lock:
        if len(_queue) >= MAX_QUEUE:
            _dropped += 1
        else:
            _queue.append(event)


def init():
    with db.get_db() as c:
        c.executescript(SCHEMA)


def flush():
    global _dropped, _last_prune
    with _lock:
        batch = list(_queue)
        _queue.clear()
        dropped, _dropped = _dropped, 0
    if not batch and not dropped:
        return
    if dropped:
        batch.append((time.time(),'gap','',json.dumps({'dropped':dropped})))
    try:
        init()
        with db.get_db() as c:
            c.executemany('INSERT INTO main_replay_events(at,kind,ticker,payload) VALUES (?,?,?,?)',batch)
            now = time.time()
            if now-_last_prune >= 60:
                c.execute('DELETE FROM main_replay_events WHERE at < ?', (now-60*86400,))
                c.execute('DELETE FROM main_replay_events WHERE id < COALESCE((SELECT id FROM main_replay_events ORDER BY at DESC, id DESC LIMIT 1 OFFSET 499999),0)')
                _last_prune = now
    except Exception:
        with _lock:
            _dropped += len(batch) + dropped
        raise


def load(since_days, *, end=None):
    init()
    end = time.time() if end is None else end
    with db.get_db() as c:
        rows = c.execute('SELECT id,at,kind,ticker,payload FROM main_replay_events WHERE at>=? AND at<=? ORDER BY at,id LIMIT 100001',
                         (end-since_days*86400,end)).fetchall()
    if len(rows) > 100000:
        raise ValueError('Replay exceeds 100,000 recorded events. Choose a shorter history window.')
    return [{**dict(r),'payload':json.loads(r['payload'])} for r in rows]


def _finite(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _depth(levels, count=3):
    total = 0.0
    for level in (levels or [])[:count]:
        try:
            size = float(level[1])
        except (TypeError, ValueError, IndexError):
            continue
        if math.isfinite(size) and size > 0:
            total += size
    return total


def feature_snapshot(row, source, quote, *, at=None):
    """Freeze candidate and side-aware book features without inventing values."""
    quote = quote or {}
    bid = _finite(quote.get('bid_cents'))
    ask = _finite(quote.get('ask_cents'))
    valid_book = bid is not None and ask is not None and 0 < bid <= ask < 100
    bid_depth = _depth(quote.get('bid_levels')) if valid_book else None
    ask_depth = _depth(quote.get('ask_levels')) if valid_book else None
    total_depth = (bid_depth + ask_depth) if valid_book else 0.0
    imbalance = ((bid_depth-ask_depth)/total_depth) if total_depth > 0 else None
    top_bid = _depth(quote.get('bid_levels'), 1) if valid_book else 0.0
    top_ask = _depth(quote.get('ask_levels'), 1) if valid_book else 0.0
    top_total = top_bid + top_ask
    microprice = ((ask*top_bid + bid*top_ask)/top_total) if valid_book and top_total > 0 else None
    return {
        'version': FEATURE_VERSION,
        'observedAt': time.time() if at is None else float(at),
        'bookStatus': 'available' if valid_book else 'unavailable',
        'bidCents': bid if valid_book else None,
        'askCents': ask if valid_book else None,
        'spreadCents': ask-bid if valid_book else None,
        'midpointCents': (bid+ask)/2 if valid_book else None,
        'bidDepth3': bid_depth,
        'askDepth3': ask_depth,
        'bookImbalance3': imbalance,
        'micropriceCents': microprice,
        'quoteSource': str(quote.get('quote_source') or 'unavailable'),
        'quoteAgeMs': _finite(quote.get('quote_age_ms')),
        'marketVolume': _finite(row.get('market_volume', row.get('volume_24h'))),
        'openInterest': _finite(row.get('open_interest')),
        'signalDollars': _finite(row.get('dollar_value', row.get('window_dollars'))),
        'flowCount': _finite(row.get('window_trades', row.get('count_fp'))),
        'priceChange': _finite(row.get('price_change')),
        'source': source,
    }


def signal(row, source, cfg, quote=None):
    import trader
    # Capture candidates before execution gates so a later test can reject them
    # differently without inventing records of previously unobserved markets.
    snapshot = feature_snapshot(row,source,quote)
    record('signal',row['ticker'],{'signal':row,'source':source,
           'features':snapshot,
           'originalDecision':trader.should_trade(row,source,cfg)})
    return snapshot


def blocker(reason, *, at=None):
    """Record the chosen engine-wide blocker without affecting execution."""
    global _last_blocker
    if not _enabled:
        return
    now = time.time() if at is None else float(at)
    reason = str(reason or 'unknown blocker')
    previous, previous_at = _last_blocker
    if reason == previous and now - previous_at < 300:
        return
    _last_blocker = (reason, now)
    record('funnel_blocker', '', {'reason': reason}, at=now)


def book(ticker, value):
    if not _enabled:
        return
    now = time.time()
    if now-_book_at.get(ticker,0) < 1:
        return
    _book_at[ticker] = now
    record('book',ticker,{'bids':value.get('bids',[])[:50],
                         'offers':value.get('offers',[])[:50]},at=now)
