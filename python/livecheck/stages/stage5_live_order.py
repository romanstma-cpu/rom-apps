"""Stage 5 -- one real order, placed and cancelled under observation.

This is the only stage that sends. Everything the suite proves up to here is
the client agreeing with itself; this is the first time the exchange answers.

It is not reachable from the read-only runner, and importing it is not enough
to arm it: `run()` refuses unless `consent()` was granted by the dedicated
entry point after a human typed the confirmation. That is deliberate
belt-and-braces -- a stage that can spend money should not be one mistaken
`--stage` away.

## Why this cannot fill

Size is not the safety mechanism; a minimum-size marketable order still fills.
Price is. A BUY fills only when the limit reaches the best ask, so the order
is placed at 1c on a market whose ask sits far above it -- `MIN_SAFE_ASK_CENTS`
of headroom, re-checked immediately before sending. A 1c bid on a book asking
40c rests untouched and is cancelled seconds later.

The residual risk is honest and bounded: if the book collapsed to 1c inside
the few seconds between the check and the cancel, one contract fills for one
cent plus fees. That is the exposure, and it is stated rather than hidden.

## Why recovery is proven first

`place_limit_order` journals an intent before every POST, and any non-terminal
intent halts submissions from EVERY engine until an operator links it to its
real exchange order. This stage can therefore stop the user's bot. It refuses
to start unless the journal is already clean, and if it ends with anything
blocking it prints the exact recovery command rather than leaving the operator
to find the runbook.
"""
from __future__ import annotations

import asyncio
import time
import uuid

import order_journal
import polymarket_api as api

from ..model import Check, Stage

# Headroom between the resting price and the best ask. 1c against a 40c ask is
# not a near miss; this refuses anything that even resembles one.
MIN_SAFE_ASK_CENTS = 15
RESTING_PRICE_CENTS = 1
# A hard ceiling on what this stage can possibly spend, independent of every
# other calculation. If the arithmetic below is ever wrong, this is the stop.
MAX_NOTIONAL_USD = 1.00
CONFIRM_PHRASE = 'place one real order'

_consent = {'granted': False, 'at': 0.0}


class ConsentMissing(RuntimeError):
    """run() was reached without a human typing the confirmation."""


def consent(phrase):
    """Arm the stage. Only the dedicated entry point should call this."""
    if str(phrase).strip().lower() != CONFIRM_PHRASE:
        return False
    _consent.update(granted=True, at=time.time())
    return True


def revoke():
    _consent.update(granted=False, at=0.0)


def is_armed():
    return bool(_consent['granted'])


def choose_market(candidates):
    """The first market with enough headroom that a 1c buy cannot reach.

    `candidates` is an iterable of (ticker, quote, meta). Returns
    (ticker, quote, meta, reason_rejected_for_each) so the report can say why
    the others were passed over.
    """
    rejected = []
    for ticker, quote, meta in candidates:
        ask = quote.get('ask_cents')
        bid = quote.get('bid_cents')
        min_size = int(meta.get('min_size') or 1)
        if not isinstance(ask, int) or ask <= 0:
            rejected.append((ticker, 'no usable ask'))
            continue
        if ask < MIN_SAFE_ASK_CENTS:
            rejected.append((ticker, f'ask {ask}c is within {MIN_SAFE_ASK_CENTS}c of the resting price'))
            continue
        if bid is not None and isinstance(bid, int) and bid <= RESTING_PRICE_CENTS:
            # A book already bid at 1c means our order would sit at the touch
            # rather than far beneath it. Still cannot fill a buy, but it is
            # not the quiet corner of the book this stage wants.
            rejected.append((ticker, f'bid {bid}c is at the resting price'))
            continue
        if min_size * RESTING_PRICE_CENTS / 100.0 > MAX_NOTIONAL_USD:
            rejected.append((ticker, f'min size {min_size} exceeds the notional ceiling'))
            continue
        return ticker, quote, meta, rejected
    return None, None, None, rejected


def notional_usd(quantity, price_cents):
    return round(quantity * price_cents / 100.0, 4)


async def preflight():
    """Everything that must be true before anything is sent."""
    checks = []

    blocked = order_journal.blocked_intents()
    checks.append(Check(
        name='the order journal is clean before we start',
        ok=not blocked,
        detail=('no blocking intent' if not blocked else
                f'{len(blocked)} intent(s) already halting submissions: '
                f'{[b["local_id"] for b in blocked]} -- clear these first, this '
                'stage will not add to them'),
        data={'blocked': [b['local_id'] for b in blocked]}))
    if blocked:
        return checks, None

    try:
        balance = await api.get_balance()
    except Exception as exc:
        checks.append(Check(name='the account is readable', ok=False,
                            detail=f'{type(exc).__name__}: {exc}'))
        return checks, None
    checks.append(Check(name='the account is readable', ok=True,
                        detail=f"buying power {balance.get('balance')}c"))

    # Pick a market from live public data, then re-read its book so the
    # headroom check is as fresh as possible.
    candidates = []
    for market in (await api.fetch_markets(limit=40)) or []:
        ticker = market.get('ticker') or market.get('slug')
        if not ticker:
            continue
        try:
            quote = await api.get_quote(ticker, 'yes')
            meta = await api.get_market_meta(ticker)
        except Exception:
            continue
        if quote and meta:
            candidates.append((ticker, quote, meta))
        if len(candidates) >= 12:
            break
        await asyncio.sleep(0.2)

    ticker, quote, meta, rejected = choose_market(candidates)
    checks.append(Check(
        name=f'a market exists whose ask is at least {MIN_SAFE_ASK_CENTS}c above the resting price',
        ok=ticker is not None,
        detail=(f"{ticker}: ask {quote['ask_cents']}c vs a {RESTING_PRICE_CENTS}c order"
                if ticker else f'none of {len(candidates)} markets qualified'),
        data={'chosen': ticker, 'rejected': rejected[:6]}))
    if not ticker:
        return checks, None

    quantity = max(1, int(meta.get('min_size') or 1))
    notional = notional_usd(quantity, RESTING_PRICE_CENTS)
    checks.append(Check(
        name='the order is inside the notional ceiling',
        ok=notional <= MAX_NOTIONAL_USD,
        detail=f'{quantity} contract(s) at {RESTING_PRICE_CENTS}c = ${notional:.4f} '
               f'(ceiling ${MAX_NOTIONAL_USD:.2f})',
        data={'quantity': quantity, 'notional_usd': notional}))
    if notional > MAX_NOTIONAL_USD:
        return checks, None

    return checks, {'ticker': ticker, 'quantity': quantity,
                    'price_cents': RESTING_PRICE_CENTS, 'meta': meta, 'quote': quote}


async def run():
    if not is_armed():
        raise ConsentMissing(
            'stage 5 places a real order and was reached without consent; '
            'run it through python -m livecheck.live_order')

    checks, plan = await preflight()
    if plan is None:
        checks.append(Check(name='no order was sent', ok=True,
                            detail='preflight did not clear; nothing was submitted'))
        return checks

    # Re-read the book immediately before sending. The earlier check chose the
    # market; this one is the gate.
    try:
        fresh = await api.get_quote(plan['ticker'], 'yes')
    except Exception as exc:
        checks.append(Check(name='the book is re-checked immediately before sending',
                            ok=False, detail=f'{type(exc).__name__}: {exc}'))
        return checks
    ask = fresh.get('ask_cents')
    safe = isinstance(ask, int) and ask >= MIN_SAFE_ASK_CENTS
    checks.append(Check(
        name='the book is re-checked immediately before sending',
        ok=safe,
        detail=f'ask {ask}c at the moment of sending '
               f'({"clear" if safe else "TOO CLOSE -- aborting"})',
        data={'ask_cents': ask}))
    if not safe:
        checks.append(Check(name='no order was sent', ok=True,
                            detail='the book moved against the safety margin'))
        return checks

    local_id = f'rom-livecheck5-{uuid.uuid4().hex[:8]}'
    order_id = None
    try:
        response = await api.place_limit_order(
            ticker=plan['ticker'], side='yes', action='buy',
            count=plan['quantity'], price_cents=plan['price_cents'],
            client_order_id=local_id, order_type='GTC')
        order_id = (response or {}).get('order', {}).get('order_id')
        checks.append(Check(
            name='the exchange accepted a real order',
            ok=bool(order_id),
            detail=f'order_id={order_id} local_id={local_id}',
            data={'order_id': order_id, 'local_id': local_id,
                  'ticker': plan['ticker'], 'quantity': plan['quantity'],
                  'price_cents': plan['price_cents']}))
    except api.PolymarketAPIError as exc:
        checks.append(Check(
            name='the exchange accepted a real order', ok=False,
            detail=f'HTTP {exc.status}: {exc.body}',
            data={'status': exc.status, 'detail': exc.detail, 'local_id': local_id}))
    except Exception as exc:
        checks.append(Check(
            name='the exchange accepted a real order', ok=False,
            detail=f'{type(exc).__name__}: {exc}', data={'local_id': local_id}))

    if order_id:
        try:
            read_back = (await api.get_order(order_id)).get('order') or {}
            status = read_back.get('status')
            filled = read_back.get('filled') or 0
            checks.append(Check(
                name='the order is readable and resting unfilled',
                ok=str(status) not in ('filled', 'matched') and not filled,
                detail=f'status={status} filled={filled}',
                data=read_back))
        except Exception as exc:
            checks.append(Check(name='the order is readable and resting unfilled',
                                ok=False, detail=f'{type(exc).__name__}: {exc}'))

        try:
            await api.cancel_order(order_id)
            checks.append(Check(name='the order cancels and the cancel is confirmed',
                                ok=True, detail='cancel confirmed by re-reading the order'))
        except order_journal.RecoveryRequired as exc:
            checks.append(Check(
                name='the order cancels and the cancel is confirmed', ok=False,
                detail=f'cancel not confirmed: {exc}',
                data={'order_id': order_id, 'local_id': local_id}))
        except Exception as exc:
            checks.append(Check(name='the order cancels and the cancel is confirmed',
                                ok=False, detail=f'{type(exc).__name__}: {exc}',
                                data={'order_id': order_id, 'local_id': local_id}))

    leftover = order_journal.blocked_intents()
    checks.append(Check(
        name='the journal is left clean',
        ok=not leftover,
        detail=('nothing is blocking submissions' if not leftover else
                'SUBMISSIONS ARE HALTED. Link the intent to its exchange order: '
                + '; '.join(f"local_id={b['local_id']} ({b['state']})" for b in leftover)
                + ' -- see docs/RECOVERY-RUNBOOK.md'),
        data={'blocked': [dict(b) for b in leftover]}))
    return checks


STAGE = Stage(number=5, name='one real order, placed and cancelled',
              run=run, read_only=False)
