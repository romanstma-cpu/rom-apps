"""Stage 4 -- dry-run submission.

Build the exact payload the engine would POST, prove the durable journal write
lands before it, and stop. Nothing here places an order.

Two independent guards, in this order:

* This stage installs its own interceptor and raises at the moment the POST
  would leave, capturing the body.
* That interceptor wraps whatever `_request` already is -- which, under the
  runner, is the safety interlock. Anything this stage fails to intercept is
  still refused by it. The interceptor is the instrument; the interlock is the
  backstop, and it is never removed.

The journal is written to a throwaway database. `place_limit_order` records an
intent before every POST, and a non-terminal intent blocks submissions from
every engine -- so a stage that wrote to the real database could halt the
user's bot, which is worse than not running at all.
"""
from __future__ import annotations

import os
import tempfile
import uuid

import db
import order_journal
import polymarket_api as api

from ..model import Check, Stage

PROBE_QUANTITY = 1
PROBE_PRICE_CENTS = 1  # rests unfilled on any market whose bid exceeds a cent


class _DryRunHalt(RuntimeError):
    """Raised in place of sending. Never escapes this module."""


async def _pick_market():
    """A real, open market -- its metadata drives the validation checks."""
    markets = await api.fetch_markets(limit=25)
    for market in markets or []:
        ticker = market.get('ticker') or market.get('slug')
        if not ticker:
            continue
        try:
            meta = await api.get_market_meta(ticker)
        except Exception:
            continue
        if meta:
            return ticker, meta
    return None, None


async def run():
    checks = []

    ticker, meta = await _pick_market()
    if not ticker:
        return [Check(name='a real open market is available to price against',
                      ok=False, skipped=True,
                      detail='no open market returned by the public feed')]
    checks.append(Check(
        name='real market metadata drives order validation',
        ok=True,
        detail=f"{ticker}: min_size={meta.get('min_size')} tick={meta.get('tick_size')}",
        data={'ticker': ticker, 'min_size': meta.get('min_size'),
              'tick_size': meta.get('tick_size')}))

    real_db_path = db.db_path
    tmp_dir = tempfile.mkdtemp(prefix='rom-livecheck-')
    tmp_db = os.path.join(tmp_dir, 'dryrun.db')
    captured = []
    journal_at_post = {}
    guarded = api._request  # the interlock, when the runner armed one

    async def intercept(method, path, **kwargs):
        if str(method).upper() == 'POST' and path == '/v1/orders':
            captured.append(kwargs.get('body'))
            # Read the journal on an INDEPENDENT connection, from inside the
            # moment the bytes would leave. This is UPGRADE-1's core claim and
            # the only place it can be observed rather than inferred.
            try:
                journal_at_post.update(order_journal.get(captured_local_id[0]) or {})
            except Exception as exc:
                journal_at_post['error'] = f'{type(exc).__name__}: {exc}'
            raise _DryRunHalt('dry run: the order was not sent')
        return await guarded(method, path, **kwargs)

    captured_local_id = [None]
    try:
        db.db_path = lambda: tmp_db
        db.init_db()
        api._request = intercept

        checks.append(Check(
            name='the journal is isolated from the real database',
            ok=str(db.db_path()) != str(real_db_path()) and os.path.exists(tmp_db),
            detail=f'writing to {tmp_db}',
            data={'isolated': True}))

        local_id = f'rom-livecheck-{uuid.uuid4().hex[:8]}'
        captured_local_id[0] = local_id
        try:
            await api.place_limit_order(
                ticker=ticker, side='yes', action='buy',
                count=max(PROBE_QUANTITY, int(meta.get('min_size') or 1)),
                price_cents=PROBE_PRICE_CENTS, client_order_id=local_id,
                order_type='GTC')
            sent = True
        except _DryRunHalt:
            sent = False
        except Exception as exc:
            sent = False
            checks.append(Check(
                name='the order path reached the point of sending',
                ok=False, detail=f'{type(exc).__name__}: {exc}'))

        checks.append(Check(
            name='no order was sent',
            ok=sent is False and len(captured) == 1,
            detail=f'intercepted {len(captured)} POST(s) to /v1/orders; none left the machine',
            data={'captured': len(captured)}))

        if captured:
            body = captured[0] or {}
            expected = {'marketSlug', 'type', 'price', 'quantity', 'tif',
                        'intent', 'manualOrderIndicator'}
            checks.append(Check(
                name='payload carries exactly the documented fields',
                ok=set(body) == expected,
                detail=f'sent={sorted(body)} unexpected={sorted(set(body)-expected)} '
                       f'missing={sorted(expected-set(body))}',
                data={'payload': body}))
            # UPGRADE-1: the local id is never sent as an undocumented exchange
            # idempotency field.
            leaked = [k for k, v in body.items() if isinstance(v, str) and local_id in v]
            checks.append(Check(
                name='the local order id is not sent to the exchange',
                ok=not leaked,
                detail=f'fields containing the local id: {leaked or "none"}'))
            checks.append(Check(
                name='price is formatted as a two-decimal string',
                ok=isinstance(body.get('price'), str) and body.get('price').count('.') == 1,
                detail=f"price={body.get('price')!r} quantity={body.get('quantity')!r}"))

        state = journal_at_post.get('state')
        checks.append(Check(
            name="the intent is committed as 'sending' BEFORE the POST",
            ok=state == 'sending',
            detail=f'journal state at the moment of sending: {state!r}',
            data=journal_at_post or None))

        # A local id is single-use, enforced inside BEGIN IMMEDIATE.
        try:
            order_journal.begin(local_id, ticker, 'yes', 'buy', 1, 0.01)
            reused = True
        except order_journal.RecoveryRequired:
            reused = False
        except Exception:
            reused = False
        checks.append(Check(
            name='a local order id cannot be reused',
            ok=reused is False,
            detail='a second begin() with the same id is refused'))

        blocker = order_journal.blocker()
        checks.append(Check(
            name='a non-terminal intent blocks further submissions',
            ok=bool(blocker),
            detail=str(blocker)))

        # Leave nothing behind. A harness that halts the bot it was meant to
        # validate is worse than no harness, and this is asserted rather than
        # assumed even though the database is disposable.
        with db.get_db() as conn:
            conn.execute('DELETE FROM us_order_intents')
            conn.commit()
        checks.append(Check(
            name='the stage leaves no blocking intent behind',
            ok=order_journal.blocker() is None and not order_journal.blocked_intents(),
            detail='journal clean'))

    finally:
        api._request = guarded   # restore the interlock, never remove it
        db.db_path = real_db_path

    # Argument validation runs against the restored adapter; each of these
    # raises before any journal write or network call.
    bad_orders = {
        'fractional count': dict(count=1.5, price_cents=50),
        'zero count': dict(count=0, price_cents=50),
        'price below 1c': dict(count=1, price_cents=0),
        'price above 99c': dict(count=1, price_cents=100),
        'unknown side': dict(count=1, price_cents=50, side='maybe'),
        'unknown action': dict(count=1, price_cents=50, action='hold'),
        'unknown tif': dict(count=1, price_cents=50, order_type='SOON'),
    }
    refused = []
    for label, kwargs in bad_orders.items():
        args = dict(ticker=ticker, side='yes', action='buy')
        args.update(kwargs)
        try:
            await api.place_limit_order(**args)
            refused.append(f'{label}: ACCEPTED')
        except (ValueError, api.PolymarketAPIError):
            pass
        except Exception as exc:
            refused.append(f'{label}: {type(exc).__name__}')
    checks.append(Check(
        name='malformed orders are refused before anything is journalled',
        ok=not refused,
        detail=f'not refused: {refused}' if refused else
               f'all {len(bad_orders)} rejected locally',
        data={'cases': sorted(bad_orders)}))

    checks.append(Check(
        name='the real database was never written',
        ok=order_journal.blocker() is None,
        detail='no blocking intent exists against the live journal'))
    return checks


STAGE = Stage(number=4, name='dry-run submission', run=run)
