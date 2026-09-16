import asyncio
import sqlite3
from contextlib import contextmanager

import db
import fill_markouts
import order_journal

NOW = 1_800_000_000.0


def test_collects_due_side_aware_markouts_once(tmp_path, monkeypatch):
    @contextmanager
    def connect():
        conn = sqlite3.connect(tmp_path/'markouts.db')
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()
    monkeypatch.setattr(db, 'get_db', connect)
    order_journal.init()
    with connect() as conn:
        conn.execute("INSERT INTO us_order_intents VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     ('a','oa','mkt','no','buy',4,.60,0,'filled',NOW-200,NOW-180,4,.60,.04,None))
        conn.execute("INSERT INTO us_entry_execution VALUES (?,?,?,?,?,?,?,?)",
                     ('a','mainnet','whale','crossing',59,59,60,50))
    calls=[]
    async def quote(ticker,side):
        calls.append((ticker,side))
        return {'bid_cents':61,'ask_cents':63}
    monkeypatch.setattr(fill_markouts,'fetch_quote',quote)
    assert asyncio.run(fill_markouts.collect('mainnet',now=NOW)) == 2
    assert calls == [('mkt','no')]
    assert asyncio.run(fill_markouts.collect('mainnet',now=NOW)) == 0
    report=fill_markouts.summary('mainnet',now=NOW)
    assert [(r['horizonSec'],r['samples'],r['avgMarkoutCents']) for r in report] == [
        (30,1,2.0),(120,1,2.0),(300,0,None)]


def test_invalid_or_crossed_quote_is_not_recorded(tmp_path, monkeypatch):
    @contextmanager
    def connect():
        conn=sqlite3.connect(tmp_path/'bad.db');conn.row_factory=sqlite3.Row
        try:
            with conn: yield conn
        finally: conn.close()
    monkeypatch.setattr(db,'get_db',connect);order_journal.init()
    row={'local_id':'a','horizon_sec':30,'avg_price':.6,'fill_seen_at':NOW-40}
    assert not fill_markouts.record(row,{'bid_cents':62,'ask_cents':61},now=NOW)
    assert not fill_markouts.record(row,{'bid_cents':None,'ask_cents':61},now=NOW)
