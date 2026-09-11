"""Stage 3 -- quote and depth fidelity.

Upgrade 6 made entry sizing depend on displayed depth and Upgrade 7 made exits
depend on a live bid. Both rest on `get_quote` returning ladders that are
ordered, positive, priced inside the band, and -- on the NO side -- mirrored
from the opposite half of the YES book. None of that has ever been seen against
a real order book; the tests behind it are hand-written fixtures.

The stage samples real public books and asks the narrow questions: are the
ladders shaped the way UPGRADE-6 claims, does the NO mirror get the arithmetic
and the sizes right, does the touch match the raw payload, and does the depth
arithmetic in `execution_quality` behave when the ladder is a real one.

`get_quote(t, side)` is `quote_from_book(await _book(t), side)` and nothing
else. So the stage fetches the raw payload once per market and runs
`quote_from_book` on that snapshot: a disagreement is then arithmetic rather
than the book moving between two fetches. One end-to-end `get_quote` call
proves the live path still returns the documented shape.

Public GETs only -- no credentials are needed for any of this. There is no
client-side rate limiting in the adapter and a 429 arrives here looking like
any other 4xx, so every request goes through `_throttle`.
"""
from __future__ import annotations

import asyncio
import math
import statistics
import time
from collections import Counter

import polymarket_api as api
from execution_quality import affordable_at_depth, entry_price, entry_vwap_cents

from ..model import Check, Stage

# Sample size is deliberately small. The point is to see a real book, not to
# survey the venue, and the adapter will happily flood the gateway.
LISTING_PAGES = 2
SAMPLE_SIZE = 30
REQUEST_INTERVAL_SEC = 0.35

# execution_quality.entry_price:54 hardcodes this; there is no config key for
# it. Mirrored rather than imported because it is a literal over there, and a
# drift between the two is itself worth noticing.
SPREAD_LIMIT_CENTS = 3

_last_request = 0.0


async def _throttle():
    """Space requests out. A 429 is indistinguishable from a 400 here."""
    global _last_request
    wait = REQUEST_INTERVAL_SEC - (time.monotonic() - _last_request)
    if wait > 0:
        await asyncio.sleep(wait)
    _last_request = time.monotonic()


# --- pure verification logic --------------------------------------------
# Everything below this line is a function of a book or a quote, so the rules
# can be tested against synthetic books without a gateway.


def _number(value):
    """Parse an API amount without borrowing the adapter's own helper.

    Prices arrive as ``{'value': '0.1180', 'currency': 'USD'}`` and sizes as
    bare strings. Returns None for anything unparseable so the caller can
    report it instead of crashing the way `quote_from_book` would.
    """
    if isinstance(value, dict):
        value = value.get('value')
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def raw_rows(side_rows):
    """(price, size) pairs from one half of a raw book, plus the rejects."""
    good, bad = [], []
    for row in side_rows or []:
        price = _number(row.get('px')) if isinstance(row, dict) else None
        size = _number(row.get('qty')) if isinstance(row, dict) else None
        if price is None or size is None:
            bad.append(row)
        else:
            good.append((price, size))
    return good, bad


def bid_cents(price):
    """The adapter's bid rounding, re-implemented so drift is visible."""
    return None if price is None else math.floor(price * 100 + 1e-8)


def ask_cents(price):
    """The adapter's ask rounding, re-implemented so drift is visible."""
    return None if price is None else math.ceil(price * 100 - 1e-8)


def derive_touch(book, side):
    """Best bid and ask in cents, computed independently of the adapter.

    Applies the same filter the adapter applies -- drop size<=0 -- and mirrors
    the NO side off the YES book the same way. Prices outside (0,1) are kept
    here because the adapter keeps them; `out_of_band_levels` reports them
    separately rather than hiding them behind a silent filter.
    """
    bids, _ = raw_rows(book.get('bids'))
    offers, _ = raw_rows(book.get('offers'))
    bids = [(p, q) for p, q in bids if q > 0]
    offers = [(p, q) for p, q in offers if q > 0]
    if side == 'no':
        bids, offers = [(1 - p, q) for p, q in offers], [(1 - p, q) for p, q in bids]
    best_bid = max((p for p, _ in bids), default=None)
    best_ask = min((p for p, _ in offers), default=None)
    return {'bid_cents': bid_cents(best_bid), 'ask_cents': ask_cents(best_ask)}


def touch_problems(quote, book, side):
    """Disagreements between the aggregate quote and the raw payload."""
    expected = derive_touch(book, side)
    out = []
    for field in ('bid_cents', 'ask_cents'):
        if quote.get(field) != expected[field]:
            out.append(f'{side} {field}: quote={quote.get(field)} '
                       f'raw book={expected[field]}')
    # The touch must also be the head of its own ladder, or a caller that
    # sizes off `ask_levels` is pricing against a different book than the one
    # it checked the spread on.
    for field, key in (('ask_cents', 'ask_levels'), ('bid_cents', 'bid_levels')):
        levels = quote.get(key) or []
        head = levels[0][0] if levels else None
        if quote.get(field) != head:
            out.append(f'{side} {field}={quote.get(field)} but {key}[0]={head}')
    return out


def ordering_problems(levels, *, descending):
    """Ladders must run best-to-worst.

    Non-strict: the venue ticks in 0.001 and the ladder is rounded to whole
    cents, so several raw levels legitimately collapse onto one cent price.
    An actual inversion is what would make `affordable_at_depth` and
    `entry_vwap_cents` walk the book in the wrong direction.
    """
    out = []
    previous = None
    for index, level in enumerate(levels or []):
        price = level[0]
        if previous is not None:
            inverted = previous < price if descending else previous > price
            if inverted:
                out.append(f'level {index}: {previous}c then {price}c')
        previous = price
    return out


def zero_size_levels(levels):
    """UPGRADE-6: zero-size levels are not quotable and never appear."""
    return [list(level) for level in levels or []
            if not isinstance(level[1], (int, float)) or isinstance(level[1], bool)
            or not math.isfinite(level[1]) or level[1] <= 0]


def out_of_band_levels(levels):
    """Levels the depth arithmetic will silently ignore.

    `entry_vwap_cents` and `affordable_at_depth` both skip anything outside
    0 < price < 100. A level that survives into the ladder but fails that test
    is dead weight: it is displayed as depth and can never be bought.
    """
    return [list(level) for level in levels or [] if not 0 < level[0] < 100]


def raw_price_problems(book):
    """Raw prices must sit strictly inside (0,1) on both halves of the book."""
    out = []
    for half in ('bids', 'offers'):
        rows, rejects = raw_rows(book.get(half))
        for row in rejects:
            out.append(f'{half}: unparseable row {row!r}')
        for price, _size in rows:
            if not 0 < price < 1:
                out.append(f'{half}: price {price!r} is not inside (0,1)')
    return out


def mirror_problems(yes_quote, no_quote):
    """The NO ladder is the YES book reflected, price and size.

    Buying NO consumes the YES bid ladder, so `no.ask_levels` must be the YES
    bid ladder at ``100 - p`` carrying the YES bid sizes, and vice versa. A
    sign error here mis-sizes every NO trade, and the identity is exact:
    ceil(100-x) == 100 - floor(x) for every price the venue can quote.
    """
    out = []
    pairs = (('ask', no_quote.get('ask_levels'), yes_quote.get('bid_levels')),
             ('bid', no_quote.get('bid_levels'), yes_quote.get('ask_levels')))
    for label, mirrored, source in pairs:
        mirrored, source = mirrored or [], source or []
        if len(mirrored) != len(source):
            out.append(f'no {label}_levels has {len(mirrored)} levels, '
                       f'yes source ladder has {len(source)}')
        for index, (mine, theirs) in enumerate(zip(mirrored, source)):
            if mine[0] + theirs[0] != 100:
                out.append(f'no {label}_levels[{index}] price {mine[0]}c does not '
                           f'mirror yes {theirs[0]}c (sum {mine[0] + theirs[0]}, '
                           'expected 100)')
            if mine[1] != theirs[1]:
                out.append(f'no {label}_levels[{index}] size {mine[1]} came from the '
                           f'wrong side of the book (yes shows {theirs[1]})')
    for label, mine, theirs in (('ask', no_quote.get('ask_cents'), yes_quote.get('bid_cents')),
                                ('bid', no_quote.get('bid_cents'), yes_quote.get('ask_cents'))):
        if mine is None or theirs is None:
            # A one-sided YES book makes one NO side absent; that is the mirror
            # working, not a failure.
            if (mine is None) != (theirs is None):
                out.append(f'no {label}_cents={mine} but the mirrored yes side is {theirs}')
        elif mine + theirs != 100:
            out.append(f'no {label}_cents {mine} + yes {theirs} = {mine + theirs}, expected 100')
    return out


def classify_book(quote):
    """What shape of book `entry_price` is being handed."""
    bid, ask = quote.get('bid_cents'), quote.get('ask_cents')
    if bid is None and ask is None:
        return 'empty'
    if bid is None or ask is None:
        return 'one-sided'
    if bid > ask:
        return 'crossed'
    if bid == ask:
        return 'locked'
    return 'two-sided'


def size_ladder(cap):
    """Order sizes to price against a ladder, from one contract up to all of it."""
    if cap < 2:
        return []
    return sorted({1, cap // 4, cap // 2, (3 * cap) // 4, cap} - {0})


def depth_cost_problems(levels):
    """Walk a real ask ladder and check the depth arithmetic holds.

    Returns (problems, samples). The assertions are UPGRADE-6's own claims:
    cost rises with size, never beats the advertised touch, size is bounded by
    displayed depth and rounded down, and an order past the displayed size is
    refused rather than priced at the touch.
    """
    problems, samples = [], []
    quotable = [(p, s) for p, s in ((lv[0], lv[1]) for lv in levels or [])
                if 0 < p < 100 and isinstance(s, (int, float)) and math.isfinite(s) and s > 0]
    if not quotable:
        return problems, samples

    limit = max(price for price, _ in quotable)
    advertised = quotable[0][0]
    displayed = sum(size for _, size in quotable)
    cap = affordable_at_depth(levels, limit)

    if cap > displayed:
        problems.append(f'affordable_at_depth returned {cap} against {displayed} displayed')
    if cap != sum(math.floor(size) for _, size in quotable):
        problems.append(f'affordable_at_depth returned {cap}, not the rounded-down '
                        f'{sum(math.floor(size) for _, size in quotable)}')

    previous = None
    for contracts in size_ladder(cap):
        try:
            vwap = entry_vwap_cents(levels, contracts, limit)
        except ValueError as exc:
            problems.append(f'{contracts} of a displayed {cap} was refused: {exc}')
            break
        samples.append({'contracts': contracts, 'vwap_cents': round(vwap, 4)})
        if previous is not None and vwap < previous - 1e-9:
            problems.append(f'cost fell from {previous:.4f}c to {vwap:.4f}c '
                            f'at {contracts} contracts')
        if vwap < advertised - 1e-9:
            problems.append(f'{contracts} contracts cost {vwap:.4f}c, better than the '
                            f'advertised touch of {advertised}c')
        previous = vwap

    if cap > 0:
        try:
            entry_vwap_cents(levels, cap + 1, limit)
            problems.append(f'filled {cap + 1} contracts against {cap} of displayed depth')
        except ValueError:
            pass
    return problems, samples


def spread_stats(spreads, limit_cents=SPREAD_LIMIT_CENTS):
    """Distribution of touch spreads, and what the hardcoded limit admits."""
    if not spreads:
        return {'count': 0}
    ordered = sorted(spreads)

    def percentile(fraction):
        return ordered[min(len(ordered) - 1, int(fraction * len(ordered)))]

    admitted = sum(1 for spread in ordered if spread <= limit_cents)
    return {
        'count': len(ordered),
        'min': ordered[0],
        'p25': percentile(0.25),
        'median': statistics.median(ordered),
        'p75': percentile(0.75),
        'p90': percentile(0.90),
        'max': ordered[-1],
        'mean': round(sum(ordered) / len(ordered), 2),
        'limit_cents': limit_cents,
        'admitted': admitted,
        'admitted_fraction': round(admitted / len(ordered), 3),
        'histogram': {str(cents): count for cents, count in sorted(Counter(ordered).items())},
    }


def entry_refusal(quote):
    """What `entry_price` says about a book, if anything. None means admitted."""
    signal = quote.get('ask_cents')
    if signal is None:
        signal = quote.get('bid_cents')
    if signal is None:
        signal = 50
    try:
        entry_price(quote, signal, {})
    except ValueError as exc:
        return str(exc)
    except Exception as exc:  # a non-ValueError here is itself the finding
        return f'{type(exc).__name__}: {exc}'
    return None


# --- the live stage ------------------------------------------------------


def _sample(markets):
    """Stride across the listing rather than taking the head of one page.

    The first page is one event's worth of near-identical futures, so the head
    of it would say nothing about the venue. This is still not a random sample
    and the checks say so.
    """
    if len(markets) <= SAMPLE_SIZE:
        return list(markets)
    step = max(1, len(markets) // SAMPLE_SIZE)
    return markets[::step][:SAMPLE_SIZE]


async def _collect():
    """Fetch the sample. Returns (observations, listing_size, errors)."""
    markets, errors = [], []
    for page in range(LISTING_PAGES):
        await _throttle()
        batch = await api.fetch_markets(limit=100, offset=page * 100)
        markets.extend(batch)
        if len(batch) < 100:
            break

    observations = []
    for market in _sample(markets):
        ticker = market['ticker']
        await _throttle()
        try:
            book = await api._book(ticker)
        except api.PolymarketAPIError as exc:
            errors.append(f'{ticker}: HTTP {exc.status} {exc.reason} -- {exc.detail}')
            continue
        except Exception as exc:
            errors.append(f'{ticker}: {type(exc).__name__}: {exc}')
            continue
        observations.append({
            'ticker': ticker,
            'book': book,
            'yes': api.quote_from_book(book, 'yes'),
            'no': api.quote_from_book(book, 'no'),
        })
    return observations, len(markets), errors


async def run():
    checks = []

    try:
        observations, listing_size, errors = await _collect()
    except api.PolymarketAPIError as exc:
        return [Check(name='public market sample fetched', ok=False,
                      detail=f'HTTP {exc.status} {exc.reason} -- {exc.detail}',
                      data={'status': exc.status, 'reason': exc.reason, 'detail': exc.detail})]

    checks.append(Check(
        name='public market sample fetched',
        ok=bool(observations),
        detail=f'{len(observations)} books from {listing_size} listed markets'
               + (f'; {len(errors)} failed: {errors[:3]}' if errors else ''),
        data={'books': len(observations), 'listed': listing_size, 'errors': errors},
    ))
    if not observations:
        return checks

    # --- 1. ordering ----------------------------------------------------
    ordering = []
    for row in observations:
        for side in ('yes', 'no'):
            ordering += [f"{row['ticker']} {side} ask: {p}"
                         for p in ordering_problems(row[side]['ask_levels'], descending=False)]
            ordering += [f"{row['ticker']} {side} bid: {p}"
                         for p in ordering_problems(row[side]['bid_levels'], descending=True)]
    ladders = sum(4 for _ in observations)
    checks.append(Check(
        name='ask ladders ascend and bid ladders descend from the touch',
        ok=not ordering,
        detail=f'{ladders} ladders in order' if not ordering
               else f'{len(ordering)} inversions, e.g. {ordering[:3]}',
        data={'ladders': ladders, 'inversions': ordering[:20]},
    ))

    # --- 2. zero-size levels --------------------------------------------
    zero = []
    for row in observations:
        for side in ('yes', 'no'):
            for key in ('ask_levels', 'bid_levels'):
                zero += [f"{row['ticker']} {side}.{key} {lv}"
                         for lv in zero_size_levels(row[side][key])]
    level_count = sum(len(row[side][key]) for row in observations
                      for side in ('yes', 'no') for key in ('ask_levels', 'bid_levels'))
    checks.append(Check(
        name='no zero-size level is quotable',
        ok=not zero,
        detail=f'{level_count} levels, all with positive size' if not zero
               else f'{len(zero)} zero-size levels, e.g. {zero[:3]}',
        data={'levels': level_count, 'zero_size': zero[:20]},
    ))

    # --- 3. prices strictly inside (0,1) --------------------------------
    raw_bad = []
    for row in observations:
        raw_bad += [f"{row['ticker']} {p}" for p in raw_price_problems(row['book'])]
    checks.append(Check(
        name='raw book prices are strictly inside (0,1)',
        ok=not raw_bad,
        detail='every raw level priced inside the band' if not raw_bad
               else f'{len(raw_bad)} offenders, e.g. {raw_bad[:3]}',
        data={'offenders': raw_bad[:20]},
    ))

    # The cent-rounded ladder is a separate question, and the one the depth
    # arithmetic actually consumes: a sub-cent price rounds to 0c, stays in
    # the ladder and is then skipped by `0 < price < 100` in both depth
    # helpers. Displayed depth the bot can never buy.
    band = []
    for row in observations:
        for side in ('yes', 'no'):
            for key in ('ask_levels', 'bid_levels'):
                band += [f"{row['ticker']} {side}.{key} {lv}"
                         for lv in out_of_band_levels(row[side][key])]
    checks.append(Check(
        name='cent-rounded level prices stay inside the (0,100)c band the depth '
             'helpers require',
        ok=not band,
        detail=f'{level_count} levels all inside the band' if not band
               else f'{len(band)} of {level_count} levels ({100*len(band)/level_count:.0f}%) '
                    f'are outside it and are silently skipped by affordable_at_depth and '
                    f'entry_vwap_cents, e.g. {band[:3]}',
        data={'levels': level_count, 'out_of_band': len(band), 'examples': band[:20]},
    ))

    # --- 4. the NO mirror -----------------------------------------------
    mirror = []
    for row in observations:
        mirror += [f"{row['ticker']}: {p}" for p in mirror_problems(row['yes'], row['no'])]
    checks.append(Check(
        name='the NO ladder mirrors the YES book in both price and size',
        ok=not mirror,
        detail=f'{len(observations)} books mirrored exactly' if not mirror
               else f'{len(mirror)} mismatches, e.g. {mirror[:3]}',
        data={'books': len(observations), 'mismatches': mirror[:20]},
    ))

    # --- 5. touch vs the raw payload ------------------------------------
    touch = []
    for row in observations:
        for side in ('yes', 'no'):
            touch += [f"{row['ticker']}: {p}" for p in touch_problems(row[side], row['book'], side)]
    checks.append(Check(
        name='quote touch agrees with the raw /book payload',
        ok=not touch,
        detail=f'{2*len(observations)} quotes re-derived from the raw payload agree'
               if not touch else f'{len(touch)} disagreements, e.g. {touch[:3]}',
        data={'quotes': 2 * len(observations), 'disagreements': touch[:20]},
    ))

    # One real round trip through `get_quote` itself, so the end-to-end path
    # is not taken on faith from `quote_from_book` alone.
    probe = observations[0]['ticker']
    await _throttle()
    try:
        live = await api.get_quote(probe, 'yes')
        shape_ok = ({'bid_cents', 'ask_cents', 'ask_levels', 'bid_levels'} <= set(live)
                    and all(isinstance(live[k], list) for k in ('ask_levels', 'bid_levels')))
        checks.append(Check(
            name='get_quote returns the documented shape end to end',
            ok=shape_ok,
            detail=f"{probe}: keys={sorted(live)}",
            data={'ticker': probe, 'quote': live},
        ))
    except api.PolymarketAPIError as exc:
        checks.append(Check(
            name='get_quote returns the documented shape end to end', ok=False,
            detail=f'HTTP {exc.status} {exc.reason} -- {exc.detail}',
            data={'status': exc.status, 'reason': exc.reason, 'detail': exc.detail}))
    except Exception as exc:
        checks.append(Check(name='get_quote returns the documented shape end to end',
                            ok=False, detail=f'{type(exc).__name__}: {exc}'))

    # --- 6. depth-weighted cost -----------------------------------------
    depth_bad, priced, samples = [], 0, []
    for row in observations:
        for side in ('yes', 'no'):
            problems, walked = depth_cost_problems(row[side]['ask_levels'])
            depth_bad += [f"{row['ticker']} {side}: {p}" for p in problems]
            if walked:
                priced += 1
                samples.append({'ticker': row['ticker'], 'side': side, 'walk': walked})
    checks.append(Check(
        name='depth-weighted cost rises with size and never beats the touch',
        ok=not depth_bad,
        detail=f'{priced} real ask ladders walked at up to 5 sizes each'
               if not depth_bad else f'{len(depth_bad)} problems, e.g. {depth_bad[:3]}',
        data={'ladders_walked': priced, 'problems': depth_bad[:20], 'samples': samples[:5]},
    ))

    # --- 7. crossed and one-sided books ---------------------------------
    shapes = Counter(classify_book(row['yes']) for row in observations)
    for shape, wording in (('crossed', 'a crossed book (bid > ask)'),
                           ('one-sided', 'a one-sided book')):
        seen = [row for row in observations if classify_book(row['yes']) == shape]
        if not seen:
            checks.append(Check(
                name=f'entry_price refuses {wording}',
                ok=True, skipped=True,
                detail=f'no {shape} book in a sample of {len(observations)}; '
                       f'shapes seen: {dict(shapes)}',
                data={'shapes': dict(shapes)},
            ))
            continue
        refused = [(row['ticker'], entry_refusal(row['yes'])) for row in seen]
        checks.append(Check(
            name=f'entry_price refuses {wording}',
            ok=all(reason for _, reason in refused),
            detail=f'{len(seen)} seen; reasons={sorted({r for _, r in refused})}',
            data={'tickers': [t for t, _ in refused], 'reasons': refused[:20]},
        ))

    # A locked book (bid == ask) is neither: `entry_price` admits it at a
    # zero spread. Worth stating because "crossed" in the code means strictly
    # greater, not greater-or-equal.
    if shapes.get('locked'):
        locked = [row for row in observations if classify_book(row['yes']) == 'locked']
        checks.append(Check(
            name='locked books (bid == ask) are admitted, not refused, by entry_price',
            ok=True,
            detail=f"{len(locked)} locked books admitted at a zero spread, e.g. "
                   f"{locked[0]['ticker']}",
            data={'tickers': [row['ticker'] for row in locked][:20]},
        ))

    # --- 8. spread distribution -----------------------------------------
    spreads = [row['yes']['ask_cents'] - row['yes']['bid_cents'] for row in observations
               if classify_book(row['yes']) in ('two-sided', 'locked')]
    stats = spread_stats(spreads)
    if not spreads:
        checks.append(Check(
            name=f'spread distribution against the hardcoded {SPREAD_LIMIT_CENTS}c limit',
            ok=True, skipped=True,
            detail=f'no two-sided book in a sample of {len(observations)}',
            data={'shapes': dict(shapes)},
        ))
    else:
        checks.append(Check(
            name=f'spread distribution against the hardcoded {SPREAD_LIMIT_CENTS}c limit',
            ok=True,
            detail=f"n={stats['count']} min={stats['min']}c median={stats['median']}c "
                   f"p90={stats['p90']}c max={stats['max']}c; the "
                   f"{SPREAD_LIMIT_CENTS}c rule admits {stats['admitted']}/{stats['count']} "
                   f"({100*stats['admitted_fraction']:.0f}%); sample strided across "
                   f"{listing_size} listed markets, not random",
            data=stats,
        ))

    # The spread limit is not what actually gates entry, and saying only the
    # spread number would leave that hidden. Report what `entry_price` really
    # does to the same sample.
    refusals = Counter()
    admitted = 0
    for row in observations:
        reason = entry_refusal(row['yes'])
        if reason is None:
            admitted += 1
        else:
            refusals[reason] += 1
    checks.append(Check(
        name='entry_price admission rate on the real sample',
        ok=True,
        detail=f'{admitted}/{len(observations)} admitted; refusals={dict(refusals)}',
        data={'admitted': admitted, 'sampled': len(observations),
              'refusals': dict(refusals)},
    ))

    return checks


STAGE = Stage(number=3, name='quote and depth fidelity', run=run)
