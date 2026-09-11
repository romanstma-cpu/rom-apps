"""Stage 1 -- account read surface.

Every response shape in `polymarket_api` is an assumption. No test in this
repo has seen a real server: the mock transports return payloads the suite
invented, so what is verified today is that the client agrees with itself.

This stage reads the authenticated endpoints and checks the specific fields
the code indexes, because a missing key is a live KeyError or a spurious 502
waiting for the first real account.
"""
from __future__ import annotations

import asyncio
import time

import polymarket_api as api

from ..model import Check, Stage

# `get_positions` raises PolymarketAPIError(502,'Positions missing from
# response') unless `data['positions']` is a dict. Whether an account holding
# nothing returns `{}` or omits the key entirely is unknown, and the two differ
# by a hard failure on every poll.
POSITION_FIELDS = ('netPositionDecimal', 'netPosition', 'marketMetadata', 'cost', 'expired')
METADATA_FIELDS = ('eventSlug', 'title')

THROTTLE_S = 0.4  # there is no client-side rate limiting and no 429 handling


def _api_failure(name, exc):
    """Report a rejection in the server's own words, now that we keep them."""
    if isinstance(exc, api.PolymarketAPIError):
        return Check(name=name, ok=False,
                     detail=f'HTTP {exc.status}: {exc.body}',
                     data={'status': exc.status, 'reason': exc.reason,
                           'detail': exc.detail})
    return Check(name=name, ok=False, detail=f'{type(exc).__name__}: {exc}')


async def _balance_checks():
    checks = []
    try:
        balance = await api.get_balance()
    except Exception as exc:
        return [_api_failure('GET /v1/account/balances returns USD buying power', exc)]

    checks.append(Check(
        name='GET /v1/account/balances returns USD buying power',
        ok='balance' in balance,
        detail=f"balance={balance.get('balance')}c "
               f"portfolio={balance.get('portfolio_value')}c",
        data=balance))
    # assetNotional is read with a default, so its absence is silent: the
    # portfolio figure simply reads zero forever.
    checks.append(Check(
        name='balances carry assetNotional (portfolio value)',
        ok=bool(balance.get('portfolio_value')),
        skipped=not balance.get('balance'),
        detail='portfolio_value is 0 -- either an empty account or '
               'assetNotional is absent from the response',
        data={'portfolio_value': balance.get('portfolio_value')}))
    return checks


async def _positions_checks():
    checks = []

    # One request, no pagination: the narrowest probe of the shape contract.
    try:
        raw = await api._request('GET', '/v1/portfolio/positions',
                                 private=True, params={'limit': 1})
    except Exception as exc:
        return [_api_failure('GET /v1/portfolio/positions responds', exc)]

    positions = raw.get('positions')
    empty_account = isinstance(positions, dict) and not positions
    checks.append(Check(
        name="'positions' is a dict even when the account holds nothing",
        ok=isinstance(positions, dict),
        detail=('present and empty -- the adapter is safe on a new account'
                if empty_account else
                f'type={type(positions).__name__}; the adapter raises 502 on '
                'anything but a dict, so a new account would fail every poll'),
        data={'type': type(positions).__name__,
              'keys': sorted(raw)[:12],
              'count': len(positions) if isinstance(positions, dict) else None}))

    checks.append(Check(
        name='pagination fields are present',
        ok=('nextCursor' in raw) or bool(raw.get('eof')),
        skipped=empty_account,
        detail=f"nextCursor={'yes' if raw.get('nextCursor') else 'no'} "
               f"eof={raw.get('eof')}",
        data={'nextCursor_present': 'nextCursor' in raw, 'eof': raw.get('eof')}))

    # Field-level shape: the highest-value check in this stage. A key the code
    # indexes but the server never sends is a live failure, not a cosmetic gap.
    sample = None
    if isinstance(positions, dict) and positions:
        sample = next(iter(positions.values()))
    if sample is None:
        checks.append(Check(
            name='position rows carry the fields the adapter reads',
            ok=False, skipped=True,
            detail='no open positions on this account to inspect'))
    else:
        qty_ok = any(f in sample for f in ('netPositionDecimal', 'netPosition'))
        missing = [f for f in POSITION_FIELDS if f not in sample]
        meta = sample.get('marketMetadata') or {}
        missing_meta = [f for f in METADATA_FIELDS if f not in meta]
        checks.append(Check(
            name='position rows carry the fields the adapter reads',
            ok=qty_ok and not missing_meta,
            detail=(f'absent from the row: {missing or "none"}; '
                    f'absent from marketMetadata: {missing_meta or "none"}'
                    + ('' if qty_ok else
                       '; NEITHER netPositionDecimal NOR netPosition present, '
                       'so every position would be skipped as zero-size')),
            data={'row_keys': sorted(sample), 'metadata_keys': sorted(meta)}))

    await asyncio.sleep(THROTTLE_S)
    try:
        parsed = await api.get_positions(limit=100)
        checks.append(Check(
            name='get_positions parses the live response',
            ok=True,
            detail=f'{len(parsed)} open position(s) after normalisation',
            data={'count': len(parsed),
                  'tickers': [p['ticker'] for p in parsed[:5]]}))
    except Exception as exc:
        checks.append(_api_failure('get_positions parses the live response', exc))

    await asyncio.sleep(THROTTLE_S)
    try:
        settled = await api.get_settled_positions()
        checks.append(Check(
            name='get_settled_positions resolves',
            ok=True, skipped=not settled,
            detail=f'{len(settled)} redeemable position(s)',
            data={'count': len(settled)}))
    except Exception as exc:
        checks.append(_api_failure('get_settled_positions resolves', exc))
    return checks


async def _readiness_check():
    try:
        ready = await api.check_trading_ready()
    except Exception as exc:
        return _api_failure('check_trading_ready reports a usable account', exc)
    return Check(
        name='check_trading_ready reports a usable account',
        ok=bool(ready.get('ok')),
        detail=f"ok={ready.get('ok')} balanceUsd={ready.get('balanceUsd')} "
               f"issues={ready.get('issues')}",
        # `address` is the credential key id; it identifies the account and is
        # deliberately not recorded in the report.
        data={'ok': ready.get('ok'), 'balanceUsd': ready.get('balanceUsd'),
              'issues': ready.get('issues')})


async def _stub_checks():
    """Two functions return [] without asking the server.

    A stage that treated those as passing live reads would be inventing
    coverage, so they are asserted to still be stubs instead.
    """
    checks = []
    activity = await api.get_activity(limit=5)
    checks.append(Check(
        name='get_activity is still a local stub, not live evidence',
        ok=activity == [],
        detail='returns [] without a request; anything else means this now '
               'reaches the server and needs its own checks',
        data={'returned': activity}))
    fills = await api.get_fills_since(time.time() - 3600)
    checks.append(Check(
        name='get_fills_since is still a local stub, not live evidence',
        ok=fills == [],
        detail='returns [] without a request',
        data={'returned': fills}))
    return checks


async def run():
    checks = []
    checks += await _balance_checks()
    await asyncio.sleep(THROTTLE_S)
    checks += await _positions_checks()
    await asyncio.sleep(THROTTLE_S)
    checks.append(await _readiness_check())
    checks += await _stub_checks()
    return checks


STAGE = Stage(number=1, name='account read surface', run=run)
