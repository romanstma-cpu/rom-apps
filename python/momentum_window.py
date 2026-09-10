"""Bounded receipt-aware trade windows; never infer flow from rolling 24h totals."""
from collections import deque
from datetime import datetime
import math

WINDOW = 300
FRESH = 30
MAX_TRADES = 50000
SCORE_VERSION = 'momentum-window-v2'
HORIZON = 2*WINDOW+FRESH


class Tape:
    def __init__(self):
        self.reset()

    def reset(self):
        self.rows = deque()
        self.by_ticker = {}
        self.ids = set()
        self.started = {}
        self.last_receive = None

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
                return False
            at = stamp.timestamp()
            price = float(trade['yes_price_dollars']); qty = float(trade['count_fp'])
            tid = str(trade['trade_id']); ticker = str(trade['ticker']); side = trade['taker_side']
            if not tid or not ticker or side not in ('yes', 'no'):
                return False
            if not all(math.isfinite(v) for v in (at, now, price, qty)) or not 0 < price < 1 or qty <= 0:
                return False
            if not 0 <= now-at <= FRESH:
                return False
        except (KeyError, ValueError, TypeError, OverflowError):
            return False
        if self.last_receive is not None and now < self.last_receive:
            self.reset()  # wall-clock rollback invalidates the observation horizon
        self.last_receive = now
        self._prune(now)
        if tid in self.ids:
            return False
        if len(self.rows) >= MAX_TRADES:
            self.reset()  # overflow cannot silently produce an incomplete baseline
            self.last_receive = now
        self.started.setdefault(ticker, now)
        self.ids.add(tid)
        row = dict(id=tid, ticker=ticker, at=at, received=now,
                   price=price, qty=qty, side=side)
        self.rows.append(row)
        self.by_ticker.setdefault(ticker, deque()).append(row)
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
