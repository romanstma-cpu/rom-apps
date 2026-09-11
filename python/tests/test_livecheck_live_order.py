"""Stage 5 — the only stage that can spend money.

Everything here is a safety property. The tests are written around the ways
this could go wrong rather than the way it goes right: reached without
consent, reached through the ordinary runner, aimed at a market where a 1c buy
could actually fill, started while the journal is already halted, or finished
leaving the engines blocked.

No test in this file may reach the network. `place_limit_order`, `get_order`
and `cancel_order` are replaced in every test, and the ones that assert
"nothing was sent" fail loudly if they are called at all.
"""
from __future__ import annotations

import asyncio

import pytest

import db
import order_journal
import polymarket_api as api
from livecheck import runner
from livecheck.stages import stage5_live_order as s5

SAFE_ASK = s5.MIN_SAFE_ASK_CENTS + 25
META = {'min_size': 1, 'tick_size': 0.01}


@pytest.fixture(autouse=True)
def never_armed():
    """Consent must never leak between tests, or from a test into a real run."""
    s5.revoke()
    yield
    s5.revoke()


@pytest.fixture
def journal(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'db_path', lambda: tmp_path / 'live.db')
    db.init_db()
    order_journal.init()


def quote(ask, bid=None):
    return {'ask_cents': ask, 'bid_cents': bid if bid is not None else max(1, ask - 2),
            'ask_levels': [[ask, 50]], 'bid_levels': [[max(1, ask - 2), 50]]}


def wire(monkeypatch, *, ask=SAFE_ASK, placed=None, order_status='open',
         balance=None, must_not_send=False):
    """Replace every network-touching call. Nothing here reaches a server."""
    sent = placed if placed is not None else []

    async def _balance():
        return balance if balance is not None else {'balance': 5000, 'portfolio_value': 0}

    async def _markets(limit=100, **kw):
        return [{'ticker': 'live-probe', 'slug': 'live-probe'}]

    async def _quote(ticker, side=None):
        return quote(ask)

    async def _meta(ticker):
        return dict(META)

    async def _place(**kwargs):
        if must_not_send:
            pytest.fail(f'stage 5 sent an order when it must not: {kwargs}')
        sent.append(kwargs)
        return {'order': {'order_id': 'EX-1', 'status': 'open'}}

    async def _get_order(order_id):
        return {'order': {'order_id': order_id, 'status': order_status, 'filled': 0}}

    async def _cancel(order_id):
        sent.append({'cancelled': order_id})
        return True

    monkeypatch.setattr(api, 'get_balance', _balance)
    monkeypatch.setattr(api, 'fetch_markets', _markets)
    monkeypatch.setattr(api, 'get_quote', _quote)
    monkeypatch.setattr(api, 'get_market_meta', _meta)
    monkeypatch.setattr(api, 'place_limit_order', _place)
    monkeypatch.setattr(api, 'get_order', _get_order)
    monkeypatch.setattr(api, 'cancel_order', _cancel)
    return sent


# --- consent ---------------------------------------------------------------

def test_run_refuses_without_consent(journal, monkeypatch):
    wire(monkeypatch, must_not_send=True)
    with pytest.raises(s5.ConsentMissing):
        asyncio.run(s5.run())


def test_only_the_exact_phrase_arms_it():
    for wrong in ('', 'yes', 'place one real order please', 'PLACE ONE REAL ORDERS'):
        assert s5.consent(wrong) is False
        assert s5.is_armed() is False
    assert s5.consent(s5.CONFIRM_PHRASE.upper()) is True   # case-insensitive
    assert s5.is_armed() is True


def test_consent_can_be_revoked():
    s5.consent(s5.CONFIRM_PHRASE)
    s5.revoke()
    assert s5.is_armed() is False


# --- unreachable from the ordinary runner ---------------------------------

def test_the_read_only_runner_excludes_it_from_all(capsys):
    stages = runner._load_stages()
    live = [s for s in stages if not s.read_only]
    assert [s.number for s in live] == [5], 'stage 5 must be the only live stage'


def test_naming_it_explicitly_is_refused_with_somewhere_to_go(monkeypatch, capsys):
    monkeypatch.setenv('ROM_POLYBOT_USERDATA', 'x')
    args = type('A', (), {'all': False, 'stage': 5, 'json': None, 'keep_going': False})()
    code = asyncio.run(runner.main_async(args))
    assert code == 2
    assert 'livecheck.live_order' in capsys.readouterr().err


# --- market choice: the thing that makes a fill impossible ----------------

def test_a_market_whose_ask_is_close_to_the_resting_price_is_refused():
    near = s5.MIN_SAFE_ASK_CENTS - 1
    ticker, _, _, rejected = s5.choose_market([('m', quote(near), META)])
    assert ticker is None
    assert 'within' in rejected[0][1]


def test_a_market_with_no_usable_ask_is_refused():
    ticker, _, _, rejected = s5.choose_market([('m', {'ask_cents': None}, META)])
    assert ticker is None and rejected[0][1] == 'no usable ask'


def test_a_book_already_bid_at_the_resting_price_is_passed_over():
    ticker, _, _, rejected = s5.choose_market(
        [('m', quote(SAFE_ASK, bid=s5.RESTING_PRICE_CENTS), META)])
    assert ticker is None and 'bid' in rejected[0][1]


def test_a_minimum_size_above_the_notional_ceiling_is_refused():
    huge = {'min_size': int(s5.MAX_NOTIONAL_USD * 100 / s5.RESTING_PRICE_CENTS) + 10}
    ticker, _, _, rejected = s5.choose_market([('m', quote(SAFE_ASK), huge)])
    assert ticker is None and 'notional ceiling' in rejected[0][1]


def test_the_first_market_with_enough_headroom_is_chosen():
    ticker, chosen, _, rejected = s5.choose_market([
        ('too-tight', quote(s5.MIN_SAFE_ASK_CENTS - 1), META),
        ('good', quote(SAFE_ASK), META),
    ])
    assert ticker == 'good' and chosen['ask_cents'] == SAFE_ASK
    assert len(rejected) == 1


def test_the_notional_is_a_hard_ceiling_not_a_guideline():
    assert s5.notional_usd(1, 1) == 0.01
    assert s5.notional_usd(1, 1) <= s5.MAX_NOTIONAL_USD


# --- preflight refuses in the states that matter --------------------------

def test_it_will_not_start_while_the_journal_is_already_halted(journal, monkeypatch):
    order_journal.begin('stuck', 'm', 'yes', 'buy', 1, 0.42)
    wire(monkeypatch, must_not_send=True)
    s5.consent(s5.CONFIRM_PHRASE)
    checks = asyncio.run(s5.run())
    names = {c.name: c for c in checks}
    assert names['the order journal is clean before we start'].ok is False
    assert names['no order was sent'].ok is True


def test_an_unreadable_account_stops_before_sending(journal, monkeypatch):
    wire(monkeypatch, must_not_send=True)

    async def _boom():
        raise api.PolymarketAPIError(401, 'Unauthorized', detail='bad key')
    monkeypatch.setattr(api, 'get_balance', _boom)
    s5.consent(s5.CONFIRM_PHRASE)
    checks = {c.name: c for c in asyncio.run(s5.run())}
    assert checks['the account is readable'].ok is False
    assert checks['no order was sent'].ok is True


def test_no_qualifying_market_means_nothing_is_sent(journal, monkeypatch):
    wire(monkeypatch, ask=2, must_not_send=True)   # every book too close to 1c
    s5.consent(s5.CONFIRM_PHRASE)
    checks = {c.name: c for c in asyncio.run(s5.run())}
    assert checks['no order was sent'].ok is True


def test_the_book_moving_at_the_last_moment_aborts_the_send(journal, monkeypatch):
    """Preflight picks a safe market; the final re-read finds it collapsed."""
    wire(monkeypatch, must_not_send=True)
    calls = {'n': 0}

    async def _quote(ticker, side=None):
        calls['n'] += 1
        # Call 1 is preflight choosing the market; call 2 is the re-read at the
        # moment of sending. The book collapses between them.
        return quote(SAFE_ASK) if calls['n'] <= 1 else quote(2)
    monkeypatch.setattr(api, 'get_quote', _quote)

    s5.consent(s5.CONFIRM_PHRASE)
    checks = {c.name: c for c in asyncio.run(s5.run())}
    assert checks['the book is re-checked immediately before sending'].ok is False
    assert checks['no order was sent'].ok is True


# --- the happy path, end to end against mocks -----------------------------

def test_it_places_reads_back_cancels_and_leaves_the_journal_clean(journal, monkeypatch):
    sent = wire(monkeypatch)
    s5.consent(s5.CONFIRM_PHRASE)
    checks = {c.name: c for c in asyncio.run(s5.run())}

    assert checks['the exchange accepted a real order'].ok is True
    assert checks['the order is readable and resting unfilled'].ok is True
    assert checks['the order cancels and the cancel is confirmed'].ok is True
    assert checks['the journal is left clean'].ok is True

    placed = [c for c in sent if 'cancelled' not in c]
    assert len(placed) == 1, 'exactly one order, never more'
    assert placed[0]['count'] == 1
    assert placed[0]['price_cents'] == s5.RESTING_PRICE_CENTS
    assert placed[0]['action'] == 'buy' and placed[0]['side'] == 'yes'
    assert [c for c in sent if 'cancelled' in c] == [{'cancelled': 'EX-1'}]


def test_an_order_that_came_back_filled_is_reported_not_hidden(journal, monkeypatch):
    wire(monkeypatch, order_status='filled')
    s5.consent(s5.CONFIRM_PHRASE)
    checks = {c.name: c for c in asyncio.run(s5.run())}
    assert checks['the order is readable and resting unfilled'].ok is False


def test_a_failed_cancel_is_reported_and_names_the_ids(journal, monkeypatch):
    wire(monkeypatch)

    async def _cancel(order_id):
        raise order_journal.RecoveryRequired('not yet confirmed')
    monkeypatch.setattr(api, 'cancel_order', _cancel)

    s5.consent(s5.CONFIRM_PHRASE)
    checks = {c.name: c for c in asyncio.run(s5.run())}
    failed = checks['the order cancels and the cancel is confirmed']
    assert failed.ok is False
    assert failed.data['order_id'] == 'EX-1' and failed.data['local_id']


def test_a_rejection_reports_the_servers_own_words(journal, monkeypatch):
    wire(monkeypatch)

    async def _place(**kwargs):
        raise api.PolymarketAPIError(422, 'Unprocessable Entity',
                                     detail='price below minimum tick')
    monkeypatch.setattr(api, 'place_limit_order', _place)

    s5.consent(s5.CONFIRM_PHRASE)
    checks = {c.name: c for c in asyncio.run(s5.run())}
    rejected = checks['the exchange accepted a real order']
    assert rejected.ok is False
    assert 'price below minimum tick' in rejected.detail
