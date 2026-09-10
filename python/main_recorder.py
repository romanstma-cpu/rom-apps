"""Bounded, opt-in via mainRecordSignals, point-in-time evidence for US replay."""
from collections import deque
import json
import threading
import time
import db

_enabled = False
_queue = deque()
_lock = threading.Lock()
_dropped = 0
_book_at = {}
_last_prune = 0
MAX_QUEUE = 20000
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
                c.execute('DELETE FROM main_replay_events WHERE id < COALESCE((SELECT id FROM main_replay_events ORDER BY id DESC LIMIT 1 OFFSET 499999),0)')
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


def signal(row, source, cfg):
    import trader
    # Capture candidates before execution gates so a later test can reject them
    # differently without inventing records of previously unobserved markets.
    record('signal',row['ticker'],{'signal':row,'source':source,
           'originalDecision':trader.should_trade(row,source,cfg)})


def book(ticker, value):
    if not _enabled:
        return
    now = time.time()
    if now-_book_at.get(ticker,0) < 1:
        return
    _book_at[ticker] = now
    record('book',ticker,{'bids':value.get('bids',[])[:50],
                         'offers':value.get('offers',[])[:50]},at=now)
