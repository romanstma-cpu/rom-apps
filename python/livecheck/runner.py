r"""Live-validation harness: staged, read-only proof that the bot can trade.

The suite proves the client's own logic. It has never spoken to a Polymarket US
server, so every response shape, error body, signature acceptance and stream
cadence in this codebase is an assumption. These stages test the assumptions
against the real account, in order, with the dangerous step excluded.

Stages 0-4 are read-only and run under `safety.arm()`, which refuses any
non-GET request at the HTTP chokepoint. Nothing here can place or cancel an
order. A live-order stage, if it is ever added, must declare read_only=False
and be selected explicitly -- it will never run as part of `--all`.

Usage, from the python/ directory:

    .venv/Scripts/python.exe -m livecheck.runner --all
    .venv/Scripts/python.exe -m livecheck.runner --stage 2 --json report.json

Credentials are read through the app's own store; this harness never handles a
key itself. Point ROM_POLYBOT_USERDATA at the app's data directory first --
on Windows that is %APPDATA%\ROM PolyBot.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time

import polymarket_api
import polymarket_auth as auth

from . import safety
from .model import StageResult

# Populated by livecheck.stages; imported lazily so a broken stage module
# cannot stop the runner from reporting the others.
def _load_stages():
    from .stages import ALL_STAGES, BROKEN
    for name, why in BROKEN.items():
        print(f'WARN  stage module {name} did not load: {why}', file=sys.stderr)
    return ALL_STAGES


def _fmt(result: StageResult) -> str:
    head = f"{'ok  ' if result.ok else 'FAIL'}  stage {result.stage.number}: {result.stage.name}"
    lines = [head]
    if result.error:
        lines.append(f"        error: {result.error}")
    for c in result.checks:
        lines.append(f"        [{c.status}] {c.name}" + (f" -- {c.detail}" if c.detail else ''))
    return '\n'.join(lines)


async def _run_stage(stage) -> StageResult:
    result = StageResult(stage=stage)
    try:
        result.checks = list(await stage.run())
    except safety.MutationRefused as exc:
        # Never swallow this. A read-only stage that tried to mutate is a bug
        # in the harness, and the run stops so it cannot be papered over.
        raise
    except Exception as exc:
        result.error = f'{type(exc).__name__}: {exc}'
    return result


async def main_async(args) -> int:
    if not os.environ.get('ROM_POLYBOT_USERDATA'):
        print('ROM_POLYBOT_USERDATA is not set; refusing to guess where your '
              'credentials live.', file=sys.stderr)
        return 2

    stages = _load_stages()
    if args.stage is not None:
        stages = [s for s in stages if s.number == args.stage]
        if not stages:
            print(f'No stage {args.stage}', file=sys.stderr)
            return 2

    # A stage that can place an order is never reachable from here. `--all`
    # excludes it by construction rather than refusing the whole run, and
    # naming it explicitly is refused with somewhere to go: it must be an
    # separate, deliberate command, not one character different from a
    # read-only one.
    live = [s for s in stages if not s.read_only]
    if args.stage is not None and live:
        print(f'Stage {args.stage} can place a real order and will not run from '
              'this entry point.',
              file=sys.stderr)
        print('Use:  python -m livecheck.live_order --help', file=sys.stderr)
        return 2
    if live:
        for stage in live:
            print(f'skip  stage {stage.number}: {stage.name} '
                  '(places real orders; run it deliberately via '
                  'python -m livecheck.live_order)')
        stages = [s for s in stages if s.read_only]

    disarm = safety.arm()
    started = time.time()
    results = []
    try:
        for stage in stages:
            if stage.requires_auth and not auth.credentials_present():
                print(f'skip  stage {stage.number}: {stage.name} '
                      '(no credentials configured)')
                continue
            result = await _run_stage(stage)
            results.append(result)
            print(_fmt(result))
            if not result.ok and not args.keep_going:
                print('\nStopping: a later stage assumes this one passed. '
                      'Re-run with --keep-going to see everything.')
                break
    finally:
        disarm()
        await polymarket_api.close_clients()

    passed = sum(1 for r in results if r.ok)
    print(f'\n{passed}/{len(results)} stages ok in {time.time()-started:.1f}s')

    if args.json:
        payload = {
            'ran_at': started,
            'stages': [{
                'number': r.stage.number, 'name': r.stage.name, 'ok': r.ok,
                'error': r.error,
                'checks': [{'name': c.name, 'status': c.status,
                            'detail': c.detail, 'data': c.data}
                           for c in r.checks],
            } for r in results],
        }
        with open(args.json, 'w', encoding='utf-8') as fh:
            json.dump(payload, fh, indent=2, default=str)
        print(f'report written to {args.json}')

    return 0 if all(r.ok for r in results) else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--all', action='store_true', help='run every read-only stage')
    parser.add_argument('--stage', type=int, help='run one stage by number')
    parser.add_argument('--json', help='write a machine-readable report here')
    parser.add_argument('--keep-going', action='store_true',
                        help='continue after a stage fails')
    args = parser.parse_args(argv)
    if not args.all and args.stage is None:
        parser.error('pass --all or --stage N')
    return asyncio.run(main_async(args))


if __name__ == '__main__':
    raise SystemExit(main())
