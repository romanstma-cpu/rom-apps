"""Stage 2 -- stream health.

Nothing in this repository has ever opened a WebSocket. Every stream test
drives `us_market_stream.ingest()` with a hand-built dict, so the reconnect
loop, the subscribe envelope, the ping cadence and every field name the
payload is indexed by are assumptions. This stage is where they meet a server.

The headline measurement is clock skew. `momentum_window.Tape.add` gates every
receipt on `0 <= now-at <= FRESH`, and the lower bound is exactly zero: a host
clock even fractionally behind the exchange rejects the whole tape, and a tape
rejecting everything is indistinguishable from a market that is simply quiet.
Momentum then reports nothing, forever, with no error anywhere. So the stage
measures the offset two ways -- through the tape's own reject counters, and
directly against raw `tradeTime` values -- and reports the distribution, not
just a verdict, so the operator can see the real margin against the 30s bound.

The stream modules expose almost no observability: no connected flag, no
last-message time, no counters. Reading their private attributes (`_task`,
`_books`, `_dirty`) is therefore deliberate and is the only way to answer
these questions from outside. `us_account_stream.consume_dirty()` is never
called here -- it *clears* the flag that service.py relies on to trigger
reconciliation, so a livecheck that consumed it would suppress a real
reconciliation in the app. The flag is read, never taken.

Nothing here sends. The market and private subscriptions are read-only by
construction, and the one HTTP call is a public GET through the interlock.
"""
from __future__ import annotations

import asyncio
import logging
import math
import os
import statistics
import time
from collections import Counter
from datetime import datetime

import momentum_window
import polymarket_api as api
import us_account_stream
import us_market_stream

from ..model import Check, Stage

# How long to watch the tape. Long enough that a moderately busy market
# produces receipts, short enough that an operator will actually run this
# before a session. Both bounds matter, so the env override is clamped.
OBSERVE_ENV = 'ROM_LIVECHECK_OBSERVE_SECONDS'
DEFAULT_OBSERVE_SECONDS = 75.0
MIN_OBSERVE_SECONDS = 10.0
MAX_OBSERVE_SECONDS = 180.0

# If nothing at all has arrived by then, the remaining checks cannot conclude
# and waiting out the full window only wastes the operator's time.
FIRST_MESSAGE_BUDGET = 30.0

MARKET_COUNT = 25          # subscription batch is 100; one batch, busiest first
POLL_SECONDS = 0.25
MAX_TRADE_SAMPLES = 200    # shape evidence; the counters below cover volume
MAX_OFFSET_SAMPLES = 20000
MAX_BOOK_LEVELS = 20       # per book per side, enough to prove the level shape

# The reject reason momentum_window uses for a host clock behind the exchange.
# Spelled once, here, because the whole stage turns on matching it exactly.
BEHIND_REASON = 'local clock behind exchange'

SIDE_ENUMS = ('ORDER_SIDE_BUY', 'ORDER_SIDE_SELL')


# --------------------------------------------------------------------------
# Pure logic. Everything that decides a pass, a fail or a skip lives here so
# it can be tested against synthetic inputs without a socket.
# --------------------------------------------------------------------------

def resolve_observation_seconds(raw, default=DEFAULT_OBSERVE_SECONDS):
    """The observation window, from an env string, clamped to something sane."""
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(value):
        return default
    return min(MAX_OBSERVE_SECONDS, max(MIN_OBSERVE_SECONDS, value))


def parse_exchange_time(value):
    """Parse a `tradeTime` exactly the way `momentum_window.Tape.add` does.

    Returns `(epoch_seconds, problem)`; `problem` is '' when the stamp is
    usable. A naive stamp is called out separately because momentum rejects it
    outright -- a feed that dropped its offset would be a silent total failure,
    not a degradation.
    """
    try:
        stamp = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None, 'unparseable timestamp'
    if stamp.tzinfo is None:
        return None, 'naive timestamp'
    try:
        return stamp.timestamp(), ''
    except (OverflowError, OSError, ValueError):
        return None, 'unparseable timestamp'


def summarize_offsets(offsets, fresh=None):
    """Distribution of `local receipt time - exchange tradeTime`, in seconds.

    Negative samples are the fatal ones: each is a receipt momentum threw away
    because the local clock was behind the exchange. Stale samples are the
    ordinary upper-bound rejections.
    """
    fresh = momentum_window.FRESH if fresh is None else fresh
    values = []
    for raw in offsets:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            values.append(value)
    values.sort()
    if not values:
        return {'samples': 0, 'behind': 0, 'stale': 0, 'usable': 0,
                'min_s': None, 'median_s': None, 'max_s': None}
    behind = sum(1 for v in values if v < 0)
    stale = sum(1 for v in values if v > fresh)
    return {'samples': len(values),
            'behind': behind, 'stale': stale,
            'usable': len(values)-behind-stale,
            'min_s': round(values[0], 3),
            'median_s': round(statistics.median(values), 3),
            'max_s': round(values[-1], 3)}


def stats_delta(before, after):
    """What happened during the window, from two `tape.stats()` snapshots.

    The tape's counters are cumulative for the life of the process and survive
    `reset()` by design, so only a difference describes the window. `rows` and
    `tickers` are point-in-time depths, not counters, and are carried through
    unchanged rather than subtracted.
    """
    before_reasons = before.get('reasons') or {}
    reasons = {}
    for reason, count in (after.get('reasons') or {}).items():
        moved = count - before_reasons.get(reason, 0)
        if moved:
            reasons[reason] = moved
    return {'accepted': after.get('accepted', 0)-before.get('accepted', 0),
            'rejected': after.get('rejected', 0)-before.get('rejected', 0),
            'reasons': reasons,
            'resets': after.get('resets', 0)-before.get('resets', 0),
            'rows': after.get('rows', 0), 'tickers': after.get('tickers', 0)}


def evaluate_clock_skew(delta, offsets, observed_seconds):
    """The headline check: did the freshness gate accept what arrived?

    A quiet market must never look like a healthy clock, so zero receipts is a
    SKIP. Any receipt at all rejected for a clock behind the exchange is a
    FAIL, however small the share -- the fault is systemic, and the sampled
    share only reflects how long the stage happened to watch.
    """
    receipts = delta['accepted'] + delta['rejected']
    data = {'accepted': delta['accepted'], 'rejected': delta['rejected'],
            'reasons': delta['reasons'], 'receipts': receipts,
            'observed_seconds': round(observed_seconds, 1), 'offsets': offsets}
    if receipts == 0:
        return Check(
            name='freshness gate accepts live receipts',
            ok=False, skipped=True,
            detail=f'no trade receipts reached the tape in {observed_seconds:.0f}s; '
                   'a quiet market cannot prove the clock is right',
            data=data)

    behind = delta['reasons'].get(BEHIND_REASON, 0)
    share = behind/receipts
    data['behind'] = behind
    data['behind_share'] = round(share, 4)
    if behind:
        worst = offsets.get('min_s')
        measured = (f'{abs(worst):.3f}s behind the exchange at worst'
                    if worst is not None and worst < 0
                    else 'offset not separately measurable from this sample')
        return Check(
            name='freshness gate accepts live receipts',
            ok=False,
            detail=f'{behind}/{receipts} receipts ({share:.0%}) rejected as '
                   f'"{BEHIND_REASON}"; local clock is {measured}. '
                   'momentum_window gates on 0 <= now-at, so momentum will report '
                   'nothing on this host until the clock is corrected.',
            data=data)

    margin = offsets.get('min_s')
    margin_text = (f'closest receipt {margin:.3f}s past its tradeTime'
                   if margin is not None else 'offset not measured')
    return Check(
        name='freshness gate accepts live receipts',
        ok=True,
        detail=f'{delta["accepted"]} accepted, {delta["rejected"]} rejected in '
               f'{observed_seconds:.0f}s; none for a clock behind the exchange; '
               f'{margin_text}',
        data=data)


def evaluate_direct_offset(offsets):
    """The same question asked without the tape, straight off raw messages.

    Independent of momentum's accounting on purpose: if the tape says one thing
    and the raw stamps say another, the bug is in the client, not the clock.
    """
    data = dict(offsets)
    if not offsets['samples']:
        return Check(
            name='exchange clock vs local clock',
            ok=False, skipped=True,
            detail='no trade carried a parseable tradeTime; offset unmeasured',
            data=data)

    median = offsets['median_s']
    fresh = momentum_window.FRESH
    spread = (f"min {offsets['min_s']}s / median {median}s / "
              f"max {offsets['max_s']}s over {offsets['samples']} trades")
    if median < 0:
        return Check(
            name='exchange clock vs local clock',
            ok=False,
            detail=f'{spread}; the typical trade arrives before its own tradeTime, '
                   f'so the local clock is ~{abs(median):.3f}s behind the exchange',
            data=data)
    if median > fresh:
        return Check(
            name='exchange clock vs local clock',
            ok=False,
            detail=f'{spread}; the typical trade is already older than the {fresh}s '
                   'freshness bound when it arrives',
            data=data)
    return Check(
        name='exchange clock vs local clock',
        ok=True,
        detail=f'{spread}; {median:.3f}s past the zero bound and '
               f'{fresh-median:.3f}s of headroom under the {fresh}s bound '
               f'({offsets["behind"]} behind, {offsets["stale"]} stale)',
        data=data)


def warmup_reachability(resets, observed_seconds, window=None):
    """Can a 300s warm-up ever complete at this reset rate? Arithmetic only.

    `us_market_stream` calls `tape.reset()` on every disconnect, and
    `Tape.summarize` refuses to report until a ticker has been observed for
    WINDOW seconds without one. A stream that drops more often than that can
    never produce a signal, no matter how much data flows through it.
    """
    window = momentum_window.WINDOW if window is None else window
    observed = max(0.0, float(observed_seconds))
    resets = max(0, int(resets))
    if resets == 0:
        # No reset seen. That does not prove continuity past the window we
        # watched, so say so rather than implying a stronger result.
        return {'resets': 0, 'observed_seconds': round(observed, 1),
                'mean_uptime_s': round(observed, 1), 'window_s': window,
                'reachable': True, 'conclusive': observed >= window}
    mean = observed/resets
    return {'resets': resets, 'observed_seconds': round(observed, 1),
            'mean_uptime_s': round(mean, 1), 'window_s': window,
            'reachable': mean >= window, 'conclusive': True}


def evaluate_warmup(resets, observed_seconds, window=None):
    """Turn the reset arithmetic into a verdict on whether momentum can arm."""
    report = warmup_reachability(resets, observed_seconds, window)
    window_s = report['window_s']
    if not report['reachable']:
        return Check(
            name='stream stays up long enough for momentum warm-up',
            ok=False,
            detail=f"{report['resets']} tape reset(s) in "
                   f"{report['observed_seconds']:.0f}s -- one every "
                   f"{report['mean_uptime_s']:.0f}s on average, under the {window_s}s "
                   'warm-up momentum needs. Every disconnect calls tape.reset(), '
                   'so at this rate no market can ever arm a signal.',
            data=report)
    if not report['conclusive']:
        return Check(
            name='stream stays up long enough for momentum warm-up',
            ok=True,
            detail=f"no tape reset in {report['observed_seconds']:.0f}s; nothing "
                   f'contradicts the {window_s}s warm-up, though this window is too '
                   'short to prove continuity across a full one',
            data=report)
    return Check(
        name='stream stays up long enough for momentum warm-up',
        ok=True,
        detail=f"{report['resets']} reset(s) in {report['observed_seconds']:.0f}s; "
               f"mean uptime {report['mean_uptime_s']:.0f}s clears the {window_s}s "
               'warm-up',
        data=report)


def evaluate_first_message(elapsed_s, budget_s, messages, warnings, task_started=True):
    """Did the socket open and say anything, and how fast."""
    data = {'messages': messages, 'budget_s': budget_s,
            'first_message_s': None if elapsed_s is None else round(elapsed_s, 3),
            'warnings': list(warnings)[:5]}
    if not task_started:
        return Check(
            name='market stream connects and delivers a message',
            ok=False, skipped=True,
            detail='us_market_stream.start() created no task; credentials are absent',
            data=data)
    if elapsed_s is None:
        reason = f"; last stream warning: {warnings[-1]}" if warnings else ''
        return Check(
            name='market stream connects and delivers a message',
            ok=False,
            detail=f'nothing arrived within {budget_s:.0f}s{reason}',
            data=data)
    return Check(
        name='market stream connects and delivers a message',
        ok=True,
        detail=f'first message in {elapsed_s*1000:.0f}ms, {messages} messages total'
               + (f'; {len(warnings)} reconnect warning(s)' if warnings else ''),
        data=data)


def evaluate_account_stream(task_alive, dirty, warnings, waited_s):
    """Did the private stream reach a subscribed state?

    `_dirty` is set in two places -- right after the subscribe frames go out,
    and again in the reconnect handler -- so the flag alone cannot tell a
    healthy subscription from a failing loop. The warning log is what separates
    them. The flag is read here and deliberately not consumed: service.py owns
    it, and taking it would cancel a reconciliation the app still needs.
    """
    data = {'task_alive': bool(task_alive), 'dirty': bool(dirty),
            'waited_s': round(waited_s, 1), 'warnings': list(warnings)[:5]}
    if not task_alive:
        return Check(
            name='account stream connects and subscribes',
            ok=False,
            detail='us_account_stream._task is gone or finished; the private loop '
                   'is not running' + (f'; last warning: {warnings[-1]}' if warnings else ''),
            data=data)
    if warnings:
        return Check(
            name='account stream connects and subscribes',
            ok=False,
            detail=f'{len(warnings)} reconnect warning(s) in {waited_s:.0f}s; '
                   f'last: {warnings[-1]}',
            data=data)
    if not dirty:
        return Check(
            name='account stream connects and subscribes',
            ok=False,
            detail=f'no subscribe completed within {waited_s:.0f}s: _dirty is still '
                   'false, which it would not be past the subscribe frames',
            data=data)
    return Check(
        name='account stream connects and subscribes',
        ok=True,
        detail=f'task alive and subscribed within {waited_s:.0f}s, no reconnects '
               '(_dirty read, not consumed)',
        data=data)


def evaluate_payload_shape(samples, total=None):
    """Do the fields `us_market_stream.ingest` indexes actually arrive?

    `marketSlug`, `tradeTime`, `price.value`, `quantity.value` and a
    `taker.side` of ORDER_SIDE_BUY/ORDER_SIDE_SELL. A naive `tradeTime` gets
    its own line in the detail: momentum rejects it outright, and the failure
    is silent everywhere else.
    """
    total = len(samples) if total is None else total
    problems = Counter()
    tz_aware = 0
    for trade in samples:
        trade = trade or {}
        if not trade.get('marketSlug'):
            problems['marketSlug missing'] += 1
        _, problem = parse_exchange_time(trade.get('tradeTime'))
        if problem:
            problems[f'tradeTime {problem}'] += 1
        else:
            tz_aware += 1
        side = (trade.get('taker') or {}).get('side')
        if side not in SIDE_ENUMS:
            problems[f'taker.side={side!r} outside {SIDE_ENUMS}'] += 1
        for field in ('price', 'quantity'):
            value = (trade.get(field) or {})
            try:
                float(value['value'])
            except (KeyError, TypeError, ValueError):
                problems[f'{field}.value missing or non-numeric'] += 1
    data = {'sampled': len(samples), 'trades_seen': total,
            'tz_aware': tz_aware, 'problems': dict(problems)}
    if not samples:
        return Check(
            name='trade payload carries the fields the client indexes',
            ok=False, skipped=True,
            detail='no trade message arrived; payload shape unverified',
            data=data)
    if problems:
        naive = problems.get('tradeTime naive timestamp', 0)
        lead = (f'{naive}/{len(samples)} tradeTime values carry no timezone offset -- '
                'momentum_window rejects those outright; ') if naive else ''
        return Check(
            name='trade payload carries the fields the client indexes',
            ok=False,
            detail=lead + ', '.join(f'{reason} x{count}'
                                    for reason, count in problems.most_common(4)),
            data=data)
    return Check(
        name='trade payload carries the fields the client indexes',
        ok=True,
        detail=f'{len(samples)} sampled trades carry marketSlug, tz-aware tradeTime, '
               'price.value, quantity.value and a known taker.side enum',
        data=data)


def evaluate_book_shape(books, max_levels=MAX_BOOK_LEVELS):
    """Do books arrive, and do their levels have the `px.value`/`qty` shape?

    `get_quote_cents` reads `float(level['px']['value'])` and `float(level['qty'])`
    with no guard, so a level that nests `qty` the way it nests `px` raises
    rather than quoting. Worth knowing before a scanner finds out.
    """
    problems = Counter()
    levels = 0
    for book in books.values():
        for field in ('bids', 'offers'):
            for level in (book.get(field) or [])[:max_levels]:
                levels += 1
                level = level or {}
                px = level.get('px')
                if not isinstance(px, dict):
                    problems[f'{field}[].px is not an object'] += 1
                else:
                    try:
                        float(px['value'])
                    except (KeyError, TypeError, ValueError):
                        problems[f'{field}[].px.value missing or non-numeric'] += 1
                qty = level.get('qty')
                if isinstance(qty, dict):
                    problems[f'{field}[].qty is an object, not the scalar '
                             'get_quote_cents floats'] += 1
                else:
                    try:
                        float(qty)
                    except (TypeError, ValueError):
                        problems[f'{field}[].qty missing or non-numeric'] += 1
    data = {'books': len(books), 'levels_sampled': levels,
            'problems': dict(problems)}
    if not books:
        return Check(
            name='order books arrive with the expected level shape',
            ok=False,
            detail='no marketData message populated _books, so no scanner could quote',
            data=data)
    if not levels:
        return Check(
            name='order books arrive with the expected level shape',
            ok=False, skipped=True,
            detail=f'{len(books)} book(s) arrived but every side was empty; level '
                   'shape unverified',
            data=data)
    if problems:
        return Check(
            name='order books arrive with the expected level shape',
            ok=False,
            detail=', '.join(f'{reason} x{count}'
                             for reason, count in problems.most_common(4)),
            data=data)
    return Check(
        name='order books arrive with the expected level shape',
        ok=True,
        detail=f'{len(books)} book(s), {levels} levels, all carrying px.value and a '
               'scalar qty',
        data=data)


# --------------------------------------------------------------------------
# Live plumbing.
# --------------------------------------------------------------------------

class _Tap:
    """Counts and samples what the stream received, then hands it on.

    The real `ingest` is called for every message, so the tape and the book
    cache fill exactly as they do in production -- this observes, it does not
    substitute. The stream modules expose no counters of their own, so this is
    the only way to see message volume and timing from outside.
    """

    def __init__(self, inner):
        self.inner = inner
        self.messages = 0
        self.trades = 0
        self.books = 0
        self.first_at = None          # monotonic, set on the first message
        self.offsets = []             # local receipt - exchange tradeTime
        self.trade_samples = []

    def __call__(self, message):
        received = time.time()
        self.messages += 1
        if self.first_at is None:
            self.first_at = time.monotonic()
        message = message if isinstance(message, dict) else {}
        if message.get('marketData'):
            self.books += 1
        trade = message.get('trade')
        if trade:
            self.trades += 1
            if len(self.trade_samples) < MAX_TRADE_SAMPLES:
                self.trade_samples.append(trade)
            at, problem = parse_exchange_time(trade.get('tradeTime'))
            if not problem and len(self.offsets) < MAX_OFFSET_SAMPLES:
                self.offsets.append(received-at)
        return self.inner(message)


class _LogCapture(logging.Handler):
    """Disconnect and rejection reasons, which the modules only ever log."""

    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.messages = []

    def emit(self, record):
        try:
            self.messages.append(record.getMessage())
        except Exception:
            pass


async def _pick_slugs(count=MARKET_COUNT):
    """The busiest open markets, so a short window has a chance of trades.

    A public GET through the interlock. Subscribing to quiet markets would turn
    every conclusion below into a SKIP for no reason.
    """
    markets = await api.fetch_markets(limit=100)
    open_markets = [m for m in markets if m.get('status') == 'open' and m.get('ticker')]
    open_markets.sort(key=lambda m: float(m.get('volume_24h_fp') or 0), reverse=True)
    return [m['ticker'] for m in open_markets[:count]]


async def _observe(tap, started, observe_seconds):
    """Watch both streams for the window. Every wait here is bounded.

    Returns `(account_dirty_at, observed_seconds)`.
    """
    deadline = started+observe_seconds
    account_dirty_at = None
    while True:
        now = time.monotonic()
        if account_dirty_at is None and us_account_stream._dirty:
            # Read, never consume: consume_dirty() would clear the flag that
            # service.py uses to trigger reconciliation.
            account_dirty_at = now
        if now >= deadline:
            break
        if tap.first_at is None and now-started > FIRST_MESSAGE_BUDGET:
            break  # nothing is coming; the rest cannot conclude either
        await asyncio.sleep(POLL_SECONDS)
    return account_dirty_at, time.monotonic()-started


async def run():
    checks = []
    observe_seconds = resolve_observation_seconds(os.environ.get(OBSERVE_ENV))

    try:
        slugs = await _pick_slugs()
    except Exception as exc:
        return [Check(name='public market list for subscription', ok=False,
                      detail=f'{type(exc).__name__}: {exc}')]
    if not slugs:
        return [Check(name='public market list for subscription', ok=False,
                      detail='no open markets returned; nothing to subscribe to')]
    checks.append(Check(
        name='public market list for subscription', ok=True,
        detail=f'{len(slugs)} open markets, busiest by 24h volume first',
        data={'markets': len(slugs), 'sample': slugs[:3]}))

    market_log, account_log = _LogCapture(), _LogCapture()
    market_logger = logging.getLogger('us_market_stream')
    account_logger = logging.getLogger('us_account_stream')
    inner_ingest = us_market_stream.ingest
    tap = _Tap(inner_ingest)

    market_logger.addHandler(market_log)
    account_logger.addHandler(account_log)
    us_market_stream.ingest = tap
    before = momentum_window.tape.stats()
    started = time.monotonic()
    try:
        us_market_stream.observe(*slugs)
        us_market_stream.start()
        # `_dirty` is false in a fresh runner process and is put back to false
        # by the stop() below, so a transition to true during the window is the
        # account stream's own doing and nobody else's.
        us_account_stream.start()
        market_started = us_market_stream._task is not None
        account_dirty_at, observed = await _observe(tap, started, observe_seconds)

        # Snapshot everything before teardown: stop() calls tape.reset() and
        # clears _books, which would erase exactly what is being measured.
        after = momentum_window.tape.stats()
        books = {slug: cached[1] for slug, cached
                 in list(us_market_stream._books.items()) if cached}
        account_task = us_account_stream._task
        account_alive = account_task is not None and not account_task.done()
        account_dirty = bool(us_account_stream._dirty)
    finally:
        # Always, whatever happened: a socket left open here leaks into every
        # later stage and keeps writing into the shared tape.
        await us_market_stream.stop()
        await us_account_stream.stop()
        us_market_stream.ingest = inner_ingest
        market_logger.removeHandler(market_log)
        account_logger.removeHandler(account_log)

    first_message_s = None if tap.first_at is None else tap.first_at-started
    offsets = summarize_offsets(tap.offsets)
    delta = stats_delta(before, after)

    checks.append(evaluate_first_message(first_message_s,
                                         min(FIRST_MESSAGE_BUDGET, observe_seconds),
                                         tap.messages, market_log.messages,
                                         task_started=market_started))
    checks.append(evaluate_clock_skew(delta, offsets, observed))
    checks.append(evaluate_direct_offset(offsets))
    checks.append(evaluate_warmup(delta['resets'], observed))
    checks.append(evaluate_account_stream(account_alive, account_dirty,
                                          account_log.messages, observed))
    checks.append(evaluate_payload_shape(tap.trade_samples, tap.trades))
    checks.append(evaluate_book_shape(books))
    return checks


STAGE = Stage(number=2, name='stream health', run=run)
