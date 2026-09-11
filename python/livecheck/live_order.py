r"""Stage 5's entry point: place one real order, then cancel it.

Separate from `livecheck.runner` on purpose. The read-only stages should be
runnable without thinking; this one should not be reachable by a typo in
`--stage`, so it is a different command that has to be chosen.

    # look, send nothing -- run this first, every time
    .venv/Scripts/python.exe -m livecheck.live_order --preflight-only

    # send one order and cancel it
    .venv/Scripts/python.exe -m livecheck.live_order

Set ROM_POLYBOT_USERDATA to the app's data directory first (on Windows,
%APPDATA%\ROM PolyBot) so credentials and the order journal are the real ones.
Close the desktop app before running: the backend holds the same journal, and
two writers is not a situation worth testing with real money.

What it does, in order: refuse unless the journal is clean, read the account,
find a market whose ask is far above 1c, re-check that book at the last
moment, place one minimum-size buy at 1c, read it back, cancel it, confirm the
cancel, and verify nothing is left halting the engines.

What it costs if everything works: nothing. The order rests far below the ask
and is cancelled seconds later. What it costs in the worst case: the book
collapses to 1c inside those seconds and one contract fills for one cent plus
fees.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

import order_journal
import polymarket_api as api

from . import safety
from .stages import stage5_live_order as stage5


def _line(check):
    return f'  [{check.status}] {check.name}' + (f' -- {check.detail}' if check.detail else '')


def _banner(plan):
    notional = stage5.notional_usd(plan['quantity'], plan['price_cents'])
    ask = plan['quote'].get('ask_cents')
    return f"""
  market      {plan['ticker']}
  order       BUY YES {plan['quantity']} contract(s) at {plan['price_cents']}c, GTC
  book now    ask {ask}c  (your order rests {ask - plan['price_cents']}c below it)
  cost if it rests   $0.00 -- it is cancelled seconds later
  cost if it fills   ${notional:.4f} plus fees, for {plan['quantity']} contract(s)
"""


async def _amain(args):
    if not os.environ.get('ROM_POLYBOT_USERDATA'):
        print('ROM_POLYBOT_USERDATA is not set; refusing to guess which account '
              'and which journal to use.', file=sys.stderr)
        return 2

    # Preflight is read-only, but it should not be read-only merely because
    # the control flow happens to return before the send. Arm the same
    # interlock the read-only stages run under, so a mutation here is refused
    # rather than relying on this function's shape staying correct.
    print('Preflight (nothing is sent during this):')
    disarm = safety.arm()
    try:
        checks, plan = await stage5.preflight()
    finally:
        disarm()
    for check in checks:
        print(_line(check))

    if plan is None:
        print('\nPreflight did not clear. Nothing was sent.')
        await api.close_clients()
        return 1

    print('\nThis will place a REAL order on your account:')
    print(_banner(plan))

    if args.preflight_only:
        print('--preflight-only: stopping here. Nothing was sent.')
        await api.close_clients()
        return 0

    typed = args.confirm
    if typed is None:
        if not sys.stdin.isatty():
            print(f'Refusing to send without confirmation. Re-run interactively, '
                  f'or pass --confirm "{stage5.CONFIRM_PHRASE}".', file=sys.stderr)
            await api.close_clients()
            return 2
        print(f'Type exactly:  {stage5.CONFIRM_PHRASE}')
        try:
            typed = input('> ')
        except (EOFError, KeyboardInterrupt):
            print('\nAborted. Nothing was sent.')
            await api.close_clients()
            return 1

    if not stage5.consent(typed):
        print('That did not match. Nothing was sent.', file=sys.stderr)
        await api.close_clients()
        return 1

    print('\nSending...\n')
    try:
        results = await stage5.run()
    finally:
        stage5.revoke()   # one confirmation, one order
        await api.close_clients()

    for check in results:
        print(_line(check))

    blocked = order_journal.blocked_intents()
    ok = all(c.ok or c.skipped for c in results) and not blocked

    if blocked:
        # The one outcome the operator must not have to go looking for.
        print('\n' + '!' * 68)
        print('SUBMISSIONS ARE HALTED. An intent could not be resolved:')
        for b in blocked:
            print(f"  local_id={b['local_id']}  state={b['state']}  "
                  f"{b['ticker']} {b['action']} {b['side']} "
                  f"{b['quantity']} @ {int(b['limit_price'] * 100)}c")
        print('\nFind the matching order on Polymarket US, then either use the')
        print('recovery panel on the app\'s Overview page, or run:')
        for b in blocked:
            print(f'  runOnce recoverOrder localOrderId={b["local_id"]} '
                  f'exchangeOrderId=<the real id>')
        print('\ndocs/RECOVERY-RUNBOOK.md has the full procedure.')
        print('!' * 68)

    if args.json:
        with open(args.json, 'w', encoding='utf-8') as fh:
            json.dump({'checks': [{'name': c.name, 'status': c.status,
                                   'detail': c.detail, 'data': c.data}
                                  for c in results],
                       'blocked': [dict(b) for b in blocked]},
                      fh, indent=2, default=str)
        print(f'\nreport written to {args.json}')

    print('\n' + ('PASS -- one order placed and cancelled, journal clean'
                  if ok else 'FAIL -- read the checks above'))
    return 0 if ok else 1


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Place one real minimum-size order and cancel it.')
    parser.add_argument('--preflight-only', action='store_true',
                        help='run every safety check and stop before sending')
    parser.add_argument('--confirm', metavar='PHRASE',
                        help='the confirmation phrase, for non-interactive use')
    parser.add_argument('--json', help='write a machine-readable report here')
    return asyncio.run(_amain(parser.parse_args(argv)))


if __name__ == '__main__':
    raise SystemExit(main())
