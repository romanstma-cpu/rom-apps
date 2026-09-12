"""Conservative execution feedback from confirmed live entry orders only.

Routing is classified at submission, not claimed to be an exchange maker flag.
Uncertain/open orders never become failed fills. Feedback expires after 30 days.
"""
import math
import time

import db
import fees_us
import order_journal


def observations(network, *, now=None):
    now = time.time() if now is None else now
    order_journal.init()
    with db.get_db() as conn:
        return [dict(row) for row in conn.execute("""
            SELECT m.*, j.ticker, j.quantity, j.limit_price, j.state,
                   j.filled, j.avg_price, j.fees_usd, j.created_at, j.updated_at
            FROM us_entry_execution m JOIN us_order_intents j USING(local_id)
            WHERE m.network=? AND j.action='buy'
              AND j.created_at>=? AND j.created_at<=? AND j.updated_at<=?
            ORDER BY j.created_at
        """, (network, now-30*86400, now, now)).fetchall()]


def summarize(rows):
    terminal = [r for r in rows if r['state'] in ('filled', 'canceled')]
    filled = [r for r in terminal if r['filled'] > 0 and r['avg_price'] is not None
              and r['fees_usd'] is not None]
    quantity = sum(r['quantity'] for r in terminal)
    actual = sum(r['filled'] for r in terminal)
    latency = sorted(r['response_ms'] for r in rows if r['response_ms'] is not None)
    return {
        'attempts': len(rows), 'completed': len(terminal),
        'pending': sum(r['state'] not in ('filled', 'canceled', 'rejected') for r in rows),
        'rejected': sum(r['state'] == 'rejected' for r in rows),
        'unfilled': sum(r['filled'] == 0 for r in terminal),
        'fillRatePct': 100*actual/quantity if quantity else None,
        'responseP95Ms': latency[math.ceil(.95*len(latency))-1] if latency else None,
        'costSamples': len(filled),
        'signalSlippageCents': (sum((r['avg_price']*100-r['signal_cents'])*r['filled']
                                   for r in filled)/sum(r['filled'] for r in filled)) if filled else None,
        'feeCentsPerContract': (100*sum(r['fees_usd'] for r in filled)
                                /sum(r['filled'] for r in filled)) if filled else None,
    }


def entry_feedback(network, ticker, source, style, price_cents, *, now=None):
    """Never increase risk or loosen existing gates based on learned evidence."""
    now = time.time() if now is None else now
    rows = [r for r in observations(network, now=now)
            if r['ticker'] == ticker and r['source'] == source and r['style'] == style
            and abs(r['limit_price']*100-price_cents) <= 5]
    terminal = [r for r in rows if r['state'] in ('filled', 'canceled')]
    # One observation per UTC day prevents a burst of correlated attempts from
    # qualifying a market. Any fill makes that day successful (conservative).
    days = {}
    for row in terminal:
        day = int(row['created_at']//86400)
        days[day] = days.get(day, False) or row['filled'] > 0
    blocked = False
    if len(days) >= 10 and len(terminal) >= 20:
        n, p, z = len(days), sum(days.values())/len(days), 1.96
        upper = (p+z*z/(2*n)+z*math.sqrt(p*(1-p)/n+z*z/(4*n*n)))/(1+z*z/n)
        blocked = upper < .5
    costs = [100*r['fees_usd']/r['filled'] for r in terminal
             if r['filled'] > 0 and r['fees_usd'] is not None]
    scheduled = 100*(fees_us.reserved_cost(1, price_cents/100, now)-price_cents/100)
    # Use the upper observed fee tail only after multiple days and fills.
    cost_days = {int(r['created_at']//86400) for r in terminal
                 if r['filled'] > 0 and r['fees_usd'] is not None}
    learned = sorted(costs)[math.ceil(.9*len(costs))-1] if len(costs)>=20 and len(cost_days)>=10 else 0
    return {'blocked': blocked, 'feeCents': max(scheduled, learned),
            'extraFeeCents': max(0, learned-scheduled), 'samples': len(terminal)}


def report(network):
    rows = observations(network)
    return {'windowDays': 30, **summarize(rows),
            'routes': [{'style': style, **summarize([r for r in rows if r['style']==style])}
                       for style in ('crossing', 'resting')]}
