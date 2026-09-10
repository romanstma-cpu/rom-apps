"""Bounded receipt-aware trade windows; never infer flow from rolling 24h totals."""
from collections import Counter, deque
from datetime import datetime
import math

WINDOW = 300
FRESH = 30
MAX_TRADES = 50000
SCORE_VERSION = 'momentum-window-v2'
HORIZON = 2*WINDOW+FRESH


class Tape:
    def __init__(self):
        # Diagnostic counters are cumulative for the life of the process and
        # deliberately survive reset(). They exist to explain why the tape is
        # empty, and a reset -- a disconnect, a clock rollback, an overflow --
        # is itself one of the explanations, so clearing them on reset would
        # erase the evidence at exactly the moment it starts to matter.
        self.rejects = Counter()
        self.accepted = 0
        self.resets = 0
        self._reset_state()

    def reset(self):
        self.resets += 1
        self._reset_state()

    def _reset_state(self):
        self.rows = deque()
        self.by_ticker = {}
        self.ids = set()
        self.started = {}
        self.last_receive = None

    def _reject(self, reason):
        self.rejects[reason] += 1
        return False

    def stats(self):
        """Why the tape looks the way it does. Counters are process-cumulative."""
        return {'accepted': self.accepted,
                'rejected': sum(self.rejects.values()),
                'reasons': dict(self.rejects.most_common()),
                'resets': self.resets,
                'rows': len(self.rows),
                'tickers': len(self.by_ticker)}

    def _prune(self, now):
        # Receipts leave in insertion order, so each per-ticker deque shares the
        # global head. Dropping a ticker's last receipt also drops its window
        # start: an unobserved gap must not pass as continuous coverage.
        cutoff = now-HORIZON
        while self.rows and self.rows[0]['received'] < cutoff:
            row = self.rows.popleft()
            self.ids.discard(row['id'])
            bucket = self.by_ticker.get(row['ticker'])
            if bucket is None:
                continue
            if bucket and bucket[0] is row:
                bucket.popleft()
            if not bucket:
                self.by_ticker.pop(row['ticker'], None)
                self.started.pop(row['ticker'], None)

    def add(self, trade, now):
        try:
            stamp = datetime.fromisoformat(str(trade['created_time']).replace('Z', '+00:00'))
            if stamp.tzinfo is None:
                return self._reject('naive timestamp')
            at = stamp.timestamp()
            price = float(trade['yes_price_dollars']); qty = float(trade['count_fp'])
            tid = str(trade['trade_id']); ticker = str(trade['ticker']); side = trade['taker_side']
            if not tid or not ticker or side not in ('yes', 'no'):
                return self._reject('bad identity fields')
            if not all(math.isfinite(v) for v in (at, now, price, qty)) or not 0 < price < 1 or qty <= 0:
                return self._reject('bad numeric values')
            # Same gate as before, split only so the two sides are counted
            # apart. A negative skew means the local clock is behind the
            # exchange, which rejects every receipt wholesale and leaves a tape
            # indistinguishable from a quiet market. That case gets its own
            # counter because it is a host-clock fault, not a market condition.
            skew = now-at
            if skew < 0:
                return self._reject('local clock behind exchange')
            if skew > FRESH:
                return self._reject('older than %ds at receipt' % FRESH)
        except (KeyError, ValueError, TypeError, OverflowError):
            return self._reject('malformed payload')
        if self.last_receive is not None and now < self.last_receive:
            self.reset()  # wall-clock rollback invalidates the observation horizon
        self.last_receive = now
        self._prune(now)
        if tid in self.ids:
            return self._reject('duplicate receipt')
        if len(self.rows) >= MAX_TRADES:
            self.reset()  # overflow cannot silently produce an incomplete baseline
            self.last_receive = now
        self.started.setdefault(ticker, now)
        self.ids.add(tid)
        row = dict(id=tid, ticker=ticker, at=at, received=now,
                   price=price, qty=qty, side=side)
        self.rows.append(row)
        self.by_ticker.setdefault(ticker, deque()).append(row)
        self.accepted += 1
        return True

    def summarize(self, ticker, now):
        start = self.started.get(ticker)
        if start is None or now < start or now-start < WINDOW:
            return {'ready': False, 'reason': 'warming up five-minute trade window'}
        rows = sorted((r for r in self.by_ticker.get(ticker, ())
                       if now-2*WINDOW <= r['at'] <= now),
                      key=lambda r: (r['at'], r['received'], r['id']))
        current = [r for r in rows if r['at'] > now-WINDOW]
        previous = [r for r in rows if r['at'] <= now-WINDOW]
        if not current or now-current[-1]['at'] > FRESH:
            return {'ready': False, 'reason': 'no fresh trade in the last 30 seconds'}
        counts = {side: sum(r['side'] == side for r in current) for side in ('yes', 'no')}
        dollars = {side: sum(r['qty']*(r['price'] if side == 'yes' else 1-r['price'])
                             for r in current if r['side'] == side) for side in ('yes', 'no')}
        total = sum(dollars.values())
        direction = None
        for side, other in (('yes', 'no'), ('no', 'yes')):
            if counts[side] > counts[other] and dollars[side] > dollars[other] and dollars[side] >= .65*total:
                direction = side
        baseline = previous[-1] if previous and now-WINDOW-previous[-1]['at'] <= 60 else None
        change = current[-1]['price']-baseline['price'] if baseline else None
        previous_dollars = sum(r['qty']*(r['price'] if r['side'] == 'yes' else 1-r['price']) for r in previous)
        ratio = total/previous_dollars if now-start >= 2*WINDOW and previous_dollars >= 50 else None
        return dict(ready=True, price=current[-1]['price'], price_change=change,
                    volume_ratio=ratio, direction=direction,
                    cluster_count=counts.get(direction, 0), cluster_dollars=dollars.get(direction, 0),
                    current_dollars=total, previous_dollars=previous_dollars,
                    trade_count=len(current), newest_at=current[-1]['at'])


tape = Tape()
