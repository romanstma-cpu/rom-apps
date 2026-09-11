"""Stage 0 -- credential proof.

The narrowest possible question: does the store hold usable credentials, does
this client sign the way it thinks it does, and does the server accept that
signature? One authenticated GET, nothing else.

This harness never reads or handles a secret. It exercises the app's own
credential path and asserts on what that path reports.
"""
from __future__ import annotations

import time

import polymarket_api as api
import polymarket_auth as auth

from ..model import Check, Stage


async def run():
    checks = []

    status = auth.credentials_status_all()
    checks.append(Check(
        name='credential store reports a configured key',
        ok=bool(auth.credentials_present()),
        detail=f'status={status}',
        data={'status': status},
    ))
    if not auth.credentials_present():
        return checks

    checks.append(Check(
        name='secret is encrypted at rest',
        ok=not auth.key_stored_unencrypted(),
        detail='plaintext fallback in use -- DPAPI and keychain both unavailable'
               if auth.key_stored_unencrypted() else 'DPAPI or keychain',
    ))

    # Signing is local, so a failure here is ours and is worth separating from
    # a server rejection below.
    try:
        headers = auth.l2_headers('GET', '/v1/account/balances')
        signed_ok = {'X-PM-Access-Key', 'X-PM-Timestamp', 'X-PM-Signature'} <= set(headers)
        detail = f"timestamp={headers.get('X-PM-Timestamp')}"
    except Exception as exc:
        signed_ok, detail, headers = False, f'{type(exc).__name__}: {exc}', {}
    checks.append(Check(name='client can sign a request', ok=signed_ok, detail=detail))
    if not signed_ok:
        return checks

    # The signed message is timestamp+METHOD+path in milliseconds. Nothing in
    # the repo compensates for clock skew and the server's tolerance is
    # undocumented, so record the offset even when the call succeeds -- it is
    # the first place to look if authentication starts failing intermittently.
    local_skew_ms = int(time.time()*1000) - int(headers['X-PM-Timestamp'])
    checks.append(Check(
        name='signing timestamp tracks local clock',
        ok=abs(local_skew_ms) < 2000,
        detail=f'{local_skew_ms}ms between signing and measuring',
        data={'local_skew_ms': local_skew_ms},
    ))

    started = time.monotonic()
    try:
        balance = await api.get_balance()
        elapsed_ms = int((time.monotonic()-started)*1000)
        checks.append(Check(
            name='server accepts the signature (GET /v1/account/balances)',
            ok=True,
            detail=f'{elapsed_ms}ms',
            data={'latency_ms': elapsed_ms, 'keys': sorted(balance)},
        ))
        checks.append(Check(
            name='balance response carries buying power',
            ok='balance' in balance,
            detail=f"fields={sorted(balance)}",
            data=balance,
        ))
    except api.PolymarketAPIError as exc:
        # Now that rejections carry the server's own words, report them.
        checks.append(Check(
            name='server accepts the signature (GET /v1/account/balances)',
            ok=False,
            detail=f'HTTP {exc.status}: {exc.body}',
            data={'status': exc.status, 'reason': exc.reason, 'detail': exc.detail},
        ))
    except Exception as exc:
        checks.append(Check(
            name='server accepts the signature (GET /v1/account/balances)',
            ok=False,
            detail=f'{type(exc).__name__}: {exc}',
        ))
    return checks


STAGE = Stage(number=0, name='credential proof', run=run)
