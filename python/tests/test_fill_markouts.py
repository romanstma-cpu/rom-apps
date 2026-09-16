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


def test_adverse_guard_requires_varied_evidence_and_blocks_clear_loss(tmp_path, monkeypatch):
    @contextmanager
    def connect():
        conn=sqlite3.connect(tmp_path/'guard.db');conn.row_factory=sqlite3.Row
        try:
            with conn: yield conn
        finally: conn.close()
    monkeypatch.setattr(db,'get_db',connect);order_journal.init()
    with connect() as conn:
        for i in range(30):
            local_id=f'g{i}'; ticker=f'market-{i%10}'; observed=NOW-(i//3)*86400
            conn.execute("INSERT INTO us_order_intents VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (local_id,'o'+local_id,ticker,'yes','buy',1,.60,0,'filled',observed-130,observed-120,1,.60,.01,None))
            conn.execute("INSERT INTO us_entry_execution VALUES (?,?,?,?,?,?,?,?)",
                         (local_id,'mainnet','whale','crossing',59,59,60,50))
            conn.execute("INSERT INTO us_fill_markouts VALUES (?,?,?,?,?,?,?,?)",
                         (local_id,120,observed,120,56,58,57,-3))
    result=fill_markouts.adverse_selection_feedback('mainnet','whale','crossing',60,now=NOW)
    assert result['blocked'] and result['samples']==30 and result['days']==10 and result['markets']==10
    assert result['upper95Cents']==-3


def test_adverse_guard_does_not_learn_from_one_market_or_other_group(tmp_path, monkeypatch):
    @contextmanager
    def connect():
        conn=sqlite3.connect(tmp_path/'guard-sparse.db');conn.row_factory=sqlite3.Row
        try:
            with conn: yield conn
        finally: conn.close()
    monkeypatch.setattr(db,'get_db',connect);order_journal.init()
    with connect() as conn:
        for i in range(30):
            local_id=f's{i}'; observed=NOW-(i%10)*86400
            conn.execute("INSERT INTO us_order_intents VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (local_id,'o'+local_id,'one-market','yes','buy',1,.60,0,'filled',observed-130,observed-120,1,.60,.01,None))
            conn.execute("INSERT INTO us_entry_execution VALUES (?,?,?,?,?,?,?,?)",
                         (local_id,'mainnet','momentum','crossing',59,59,60,50))
            conn.execute("INSERT INTO us_fill_markouts VALUES (?,?,?,?,?,?,?,?)",
                         (local_id,120,observed,120,56,58,57,-3))
    sparse=fill_markouts.adverse_selection_feedback('mainnet','momentum','crossing',60,now=NOW)
    other=fill_markouts.adverse_selection_feedback('mainnet','whale','crossing',60,now=NOW)
    assert not sparse['blocked'] and sparse['markets']==1
    assert not other['blocked'] and other['samples']==0


def test_guard_report_exposes_collection_progress(tmp_path, monkeypatch):
    @contextmanager
    def connect():
        conn=sqlite3.connect(tmp_path/'guard-report.db');conn.row_factory=sqlite3.Row
        try:
            with conn: yield conn
        finally: conn.close()
    monkeypatch.setattr(db,'get_db',connect);order_journal.init()
    with connect() as conn:
        conn.execute("INSERT INTO us_order_intents VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     ('r','or','market','yes','buy',1,.60,0,'filled',NOW-130,NOW-120,1,.60,.01,None))
        conn.execute("INSERT INTO us_entry_execution VALUES (?,?,?,?,?,?,?,?)",
                     ('r','mainnet','whale','crossing',59,59,60,50))
        conn.execute("INSERT INTO us_fill_markouts VALUES (?,?,?,?,?,?,?,?)",
                     ('r',120,NOW,120,59,61,60,0))
    report=fill_markouts.guard_report('mainnet',now=NOW)
    assert report[0]['source']=='whale' and report[0]['priceCents']==60
    assert report[0]['samples']==1 and not report[0]['blocked']
