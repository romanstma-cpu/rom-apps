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
#
# The series is read from `markets` first and from the market's row in `events`
# second. Only the events feed carries a series today; the market column is kept
# first so a populated one would win. With neither, the group falls back to the
# event and then the ticker, exactly as before.
#
# Both engines are counted. The control is named account-wide, but it read
# `bot_positions` alone, so exposure the crypto15m engine already held was
# invisible to a main-strategy entry measured against the same series.
# crypto15m carries its own `series` column, so its rows group natively.
# Counting them can only raise a group's total, never lower it, so an entry
# sees an allowance that is the same or smaller than before.
GROUP_SQL = """SELECT grp, SUM(usd) AS usd FROM (
                 SELECT COALESCE(NULLIF(m.series_ticker,''),
                                 NULLIF(e.series_ticker,''),
                                 NULLIF(p.event_ticker,''),
                                 p.ticker) AS grp,
                        CASE WHEN p.cost_usd>0 THEN p.cost_usd
                             ELSE p.filled_contracts*p.limit_price_cents/100.0 END AS usd
                 FROM bot_positions p LEFT JOIN markets m ON m.ticker=p.ticker
                      LEFT JOIN events e ON p.event_ticker<>'' AND e.event_ticker=p.event_ticker
                 WHERE p.resolved=0 AND p.status IN ('submitted','partial','filled','unknown')
                   AND p.network=?
                 UNION ALL
                 SELECT COALESCE(NULLIF(c.series,''), c.ticker) AS grp,
                        CASE WHEN c.cost_usd>0 THEN c.cost_usd
                             ELSE c.filled_contracts*c.entry_limit_cents/100.0 END AS usd
                 FROM crypto15m_positions c
                 WHERE c.resolved=0 AND c.status IN ('submitted','filled','exiting')
                   AND c.network=? AND COALESCE(c.dry_run,0)=0
               ) GROUP BY grp"""


def _f(value, default=0.0):
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def series_ticker(conn, ticker, event_ticker):
    """The series this market belongs to, or '' when none is recorded.

    `markets.series_ticker` is checked first and the market's event row second,
    matching GROUP_SQL. A market absent from both simply has no series.
    """
    row = conn.execute('SELECT series_ticker FROM markets WHERE ticker=?', (ticker,)).fetchone()
    series = str(row['series_ticker'] or '') if row else ''
    if series:
        return series
    event = str(event_ticker or '')
    if not event:
        return ''
    row = conn.execute('SELECT series_ticker FROM events WHERE event_ticker=?', (event,)).fetchone()
    return str(row['series_ticker'] or '') if row else ''


def event_series_map(conn):
    """event_ticker -> series_ticker for every event that records a series."""
    rows = conn.execute("SELECT event_ticker, series_ticker FROM events"
                        " WHERE COALESCE(event_ticker,'')<>''"
                        " AND COALESCE(series_ticker,'')<>''")
    return {str(r['event_ticker']): str(r['series_ticker']) for r in rows}


def group_key(conn, ticker, event_ticker):
    """The correlated-exposure group a prospective entry would join."""
    return series_ticker(conn, ticker, event_ticker) or str(event_ticker or '') or str(ticker or '')


def group_exposure_usd(conn, env):
    return {str(r['grp']): _f(r['usd']) for r in conn.execute(GROUP_SQL, (env, env)) if r['grp']}


def cap_bankroll_usd(balance_usd, filled_exposure_usd):
    """The one quantity a group fraction is measured against.

    An account-wide cap is only account-wide if every engine divides the same
    number. Every live-entry engine computes cash-plus-filled-cost
    identically and separately; naming it here is what stops them drifting
    apart later and turning one configured fraction into three different
    dollar limits.
    """
    return max(0.0, _f(balance_usd)) + max(0.0, _f(filled_exposure_usd))


def crypto15m_group_key(series, ticker):
    """The group a crypto15m entry will land in.

    GROUP_SQL buckets those rows by COALESCE(NULLIF(series,''), ticker) and
    does NOT consult `markets`, so a prospective crypto15m entry must be keyed
    the same way. Routing it through `group_key` instead would look the ticker
    up in `markets` and could measure the entry against a different bucket
    from the one its own position lands in.
    """
    return str(series or '').strip() or str(ticker or '').strip()


def group_budget_for_key(conn, env, key, bankroll_usd, cfg, used=None):
    """Dollars still available to an already-resolved group key.

    `used` lets a caller entering several positions in one pass read exposure
    once and account for what it has just committed, instead of re-querying
    and re-approving the same dollars for every entry in the batch. `conn` is
    only read when `used` is omitted, and may be None otherwise.
    """
    fraction = _f(cfg.get('max_group_exposure_fraction'), 0.0)
    bankroll = _f(bankroll_usd)
    if fraction <= 0 or bankroll <= 0:
        return float('inf')
    if used is None:
        used = group_exposure_usd(conn, env)
    return max(0.0, bankroll*fraction-_f(used.get(str(key), 0.0)))


def group_budget_usd(conn, env, ticker, event_ticker, bankroll_usd, cfg):
    """Dollars this entry may still add to its correlated group.

    Returns 0 when the group is full. A non-positive configured fraction
    disables the control rather than blocking every entry.
    """
    return group_budget_for_key(
        conn, env, group_key(conn, ticker, event_ticker), bankroll_usd, cfg)


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
