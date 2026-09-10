"""Account-wide risk: correlated exposure groups and an equity high-water mark.

Existing limits are per-engine and per-event. Two gaps remain:

* Different events can share the same underlying outcome (one tournament, one
  economic release), so per-event caps do not bound correlated risk.
* Daily stop-loss measures the current trading day only. A slow drawdown never
  breaches a single day badly enough to pause trading.

Both controls block only NEW entries. Nothing here liquidates a position, and
an unknown or unreadable account state blocks rather than permits risk.
"""
import math
import time

import db

HWM_KEY = 'risk:hwm:'
# Related-outcome grouping is deliberately coarse. It groups by the market's
# series (all markets of one tournament or recurring release) and falls back to
# the event. It cannot detect correlation between different series.
GROUP_SQL = """SELECT COALESCE(NULLIF(m.series_ticker,''),
                               NULLIF(p.event_ticker,''),
                               p.ticker) AS grp,
                      SUM(CASE WHEN p.cost_usd>0 THEN p.cost_usd
                               ELSE p.filled_contracts*p.limit_price_cents/100.0 END) AS usd
               FROM bot_positions p LEFT JOIN markets m ON m.ticker=p.ticker
               WHERE p.resolved=0 AND p.status IN ('submitted','partial','filled','unknown')
                 AND p.network=? GROUP BY grp"""


def _f(value, default=0.0):
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def group_key(conn, ticker, event_ticker):
    """The correlated-exposure group a prospective entry would join."""
    row = conn.execute('SELECT series_ticker FROM markets WHERE ticker=?', (ticker,)).fetchone()
    series = str(row['series_ticker'] or '') if row else ''
    return series or str(event_ticker or '') or str(ticker or '')


def group_exposure_usd(conn, env):
    return {str(r['grp']): _f(r['usd']) for r in conn.execute(GROUP_SQL, (env,)) if r['grp']}


def group_budget_usd(conn, env, ticker, event_ticker, bankroll_usd, cfg):
    """Dollars this entry may still add to its correlated group.

    Returns 0 when the group is full. A non-positive configured fraction
    disables the control rather than blocking every entry.
    """
    fraction = _f(cfg.get('max_group_exposure_fraction'), 0.0)
    bankroll = _f(bankroll_usd)
    if fraction <= 0 or bankroll <= 0:
        return float('inf')
    key = group_key(conn, ticker, event_ticker)
    used = group_exposure_usd(conn, env).get(key, 0.0)
    return max(0.0, bankroll*fraction-used)


def equity_usd(conn, env):
    """Account equity: cash plus open cost. None when it cannot be read."""
    snap = db.latest_snapshot(conn, env)
    if not snap:
        return None
    total = snap.get('total_usd')
    if total is None:
        return None
    value = _f(total, float('nan'))
    return None if math.isnan(value) else value


def read_hwm(conn, env):
    return _f(db.kv_get(conn, HWM_KEY+env), 0.0)


def update_hwm(conn, env, equity):
    """Raise the recorded peak. The mark never falls on its own."""
    if equity is None or not math.isfinite(equity):
        return read_hwm(conn, env)
    peak = max(read_hwm(conn, env), equity)
    db.kv_set(conn, HWM_KEY+env, repr(peak))
    return peak


def reset_hwm(conn, env, equity=None):
    """Re-anchor the peak, for a deliberate bankroll change."""
    db.kv_set(conn, HWM_KEY+env, repr(_f(equity, 0.0)))


def drawdown_block(cfg, env, *, now=None):
    """Pause new entries after a confirmed fall from peak equity.

    A missing or unreadable equity reading blocks new risk instead of
    silently allowing it, matching the existing balance-unavailable rule.
    """
    fraction = _f(cfg.get('max_drawdown_fraction'), 0.0)
    if fraction <= 0:
        return False, ''
    with db.get_db() as conn:
        equity = equity_usd(conn, env)
        if equity is None:
            return True, ('Account equity has not been recorded yet; '
                          'new entries stay paused until a balance snapshot exists.')
        peak = update_hwm(conn, env, equity)
    if peak <= 0:
        return False, ''
    drop = peak-equity
    if drop <= 0:
        return False, ''
    if drop/peak >= fraction:
        return True, (f'drawdown limit reached — new entries paused '
                      f'(equity ${equity:,.2f} is ${drop:,.2f} below the '
                      f'${peak:,.2f} peak, limit {fraction*100:.1f}%)')
    return False, ''
