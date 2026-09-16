"""Collect post-fill quote movement for confirmed live main-strategy entries.

Markout is side-aware midpoint minus the confirmed average buy price. Positive
values mean the market moved in the position's favor. Collection is descriptive
only: it cannot loosen a gate or change an order until the evidence is reviewed.
"""
from __future__ import annotations

import math
import time

import db
import order_journal

HORIZONS = (30, 120, 300)
GUARD_HORIZON_SEC = 120
GUARD_MIN_SAMPLES = 30
GUARD_MIN_DAYS = 10
GUARD_MIN_MARKETS = 8
GUARD_BAD_CENTS = -0.5
GUARD_CLIP_CENTS = 10.0


async def fetch_quote(ticker: str, side: str) -> dict:
    # Keep the authenticated API import out of report-only/test processes.
    import polymarket_api
    return await polymarket_api.get_fast_quote(ticker, side)


def due(network: str, *, now: float | None = None, limit: int = 12) -> list[dict]:
    now = time.time() if now is None else now
    order_journal.init()
    with db.get_db() as conn:
        rows = conn.execute(
            """SELECT j.local_id, j.ticker, j.side, j.filled, j.avg_price,
                      j.updated_at AS fill_seen_at, h.horizon_sec
               FROM us_order_intents j
               JOIN us_entry_execution e USING(local_id)
               JOIN (SELECT 30 horizon_sec UNION ALL SELECT 120 UNION ALL SELECT 300) h
               LEFT JOIN us_fill_markouts m
                 ON m.local_id=j.local_id AND m.horizon_sec=h.horizon_sec
              WHERE e.network=? AND j.action='buy' AND j.filled>0
                AND j.avg_price IS NOT NULL AND j.state IN ('filled','canceled')
                AND m.local_id IS NULL AND ?-j.updated_at>=h.horizon_sec
              ORDER BY j.updated_at+h.horizon_sec, j.local_id
              LIMIT ?""",
            (network, now, int(limit)),
        ).fetchall()
    return [dict(row) for row in rows]


def record(row: dict, quote: dict, *, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    bid, ask = quote.get('bid_cents'), quote.get('ask_cents')
    values = (bid, ask, row.get('avg_price'), row.get('fill_seen_at'))
    if any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in values):
        return False
    if not (0 < bid <= ask < 100):
        return False
    mid = (float(bid) + float(ask)) / 2
    markout = mid - float(row['avg_price']) * 100
    with db.get_db() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO us_fill_markouts
                 (local_id,horizon_sec,observed_at,age_sec,bid_cents,ask_cents,mid_cents,markout_cents)
               VALUES (?,?,?,?,?,?,?,?)""",
            (row['local_id'], int(row['horizon_sec']), now,
             max(0.0, now-float(row['fill_seen_at'])), float(bid), float(ask), mid, markout),
        )
        return bool(conn.execute('SELECT changes()').fetchone()[0])


async def collect(network: str, *, now: float | None = None, limit: int = 12) -> int:
    now = time.time() if now is None else now
    rows = due(network, now=now, limit=limit)
    quotes: dict[tuple[str, str], dict | None] = {}
    saved = 0
    for row in rows:
        key = (row['ticker'], row['side'])
        if key not in quotes:
            try:
                quotes[key] = await fetch_quote(*key)
            except Exception:
                quotes[key] = None
        if quotes[key] is not None and record(row, quotes[key], now=now):
            saved += 1
    return saved


def summary(network: str, *, now: float | None = None) -> list[dict]:
    now = time.time() if now is None else now
    order_journal.init()
    with db.get_db() as conn:
        rows = conn.execute(
            """SELECT m.horizon_sec, COUNT(*) samples,
                      SUM(j.filled) contracts,
                      SUM(m.markout_cents*j.filled)/SUM(j.filled) avg_markout_cents,
                      SUM(CASE WHEN m.markout_cents<0 THEN 1 ELSE 0 END)*100.0/COUNT(*) adverse_pct
                 FROM us_fill_markouts m
                 JOIN us_order_intents j USING(local_id)
                 JOIN us_entry_execution e USING(local_id)
                WHERE e.network=? AND m.observed_at>=?
                GROUP BY m.horizon_sec ORDER BY m.horizon_sec""",
            (network, now-30*86400),
        ).fetchall()
    by_horizon = {int(row['horizon_sec']): dict(row) for row in rows}
    return [{
        'horizonSec': horizon,
        'samples': int(by_horizon.get(horizon, {}).get('samples') or 0),
        'contracts': float(by_horizon.get(horizon, {}).get('contracts') or 0),
        'avgMarkoutCents': (float(by_horizon[horizon]['avg_markout_cents'])
                            if horizon in by_horizon else None),
        'adversePct': (float(by_horizon[horizon]['adverse_pct'])
                       if horizon in by_horizon else None),
    } for horizon in HORIZONS]


def adverse_selection_feedback(
    network: str, source: str, style: str, price_cents: float, *, now: float | None = None
) -> dict:
    """Block only when varied recent evidence is confidently unfavorable.

    The guard pools comparable entries across markets because a single event
    rarely supplies an independent sample. Each order receives equal weight,
    extreme news moves are clipped, and the upper 95% mean bound must still be
    worse than ``GUARD_BAD_CENTS``. This can only reduce new entry activity.
    """
    now = time.time() if now is None else now
    order_journal.init()
    with db.get_db() as conn:
        rows = [dict(row) for row in conn.execute(
            """SELECT m.markout_cents, m.observed_at, j.ticker
                 FROM us_fill_markouts m
                 JOIN us_order_intents j USING(local_id)
                 JOIN us_entry_execution e USING(local_id)
                WHERE e.network=? AND e.source=? AND e.style=?
                  AND m.horizon_sec=? AND m.observed_at>=?
                  AND ABS(j.limit_price*100-?)<=5
                ORDER BY m.observed_at, m.local_id""",
            (network, source, style, GUARD_HORIZON_SEC, now-30*86400, price_cents),
        ).fetchall()]
    grouped: dict[tuple[str, int], list[float]] = {}
    for row in rows:
        key = (row['ticker'], int(row['observed_at']//86400))
        grouped.setdefault(key, []).append(float(row['markout_cents']))
    days = {day for _, day in grouped}
    markets = {row['ticker'] for row in rows}
    ready = (len(grouped) >= GUARD_MIN_SAMPLES and len(days) >= GUARD_MIN_DAYS
             and len(markets) >= GUARD_MIN_MARKETS)
    if not ready:
        return {'blocked': False, 'samples': len(grouped), 'days': len(days),
                'markets': len(markets), 'meanCents': None, 'upper95Cents': None}
    values = [max(-GUARD_CLIP_CENTS, min(GUARD_CLIP_CENTS, sum(group)/len(group)))
              for group in grouped.values()]
    mean = sum(values)/len(values)
    variance = sum((value-mean)**2 for value in values)/(len(values)-1)
    upper = mean + 1.96*math.sqrt(variance/len(values))
    return {'blocked': upper < GUARD_BAD_CENTS, 'samples': len(grouped),
            'days': len(days), 'markets': len(markets),
            'meanCents': mean, 'upper95Cents': upper}
