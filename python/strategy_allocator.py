"""Conservative source allocation from settled practice trades.

The allocator never changes practice sizing: practice remains the unbiased
challenger record. Live sizing can opt in to a multiplier derived from both a
recent and a longer evidence window. Existing account and exposure ceilings
remain authoritative after the multiplier is applied.
"""
from __future__ import annotations

import math
import random
import time
from datetime import datetime, timezone


SHORT_DAYS = 30
LONG_DAYS = 90
SHORT_MIN_EVENTS = 20
LONG_MIN_EVENTS = 40
SHORT_MIN_SPAN_DAYS = 7
LONG_MIN_SPAN_DAYS = 30
LOWER_QUANTILE = 0.10
BOOTSTRAP_SAMPLES = 600
MIN_MULTIPLIER = 0.25
MAX_MULTIPLIER = 1.50
SUPPORTED_SOURCES = ("whale", "momentum")
_plan_cache = {}


def _f(value, default=0.0):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return number if math.isfinite(number) else default


def _timestamp(value):
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    if "T" not in text and " " in text:
        text = text.replace(" ", "T", 1)
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc).timestamp()


def _events(rows, since):
    """Collapse repeated rows to one capital-weighted observation per event."""
    grouped = {}
    for row in rows:
        resolved_at = _timestamp(row.get("resolved_at"))
        if resolved_at is None or resolved_at < since:
            continue
        key = str(row.get("event_ticker") or row.get("ticker") or "").strip()
        cost = max(0.0, _f(row.get("cost_usd")))
        if not key or cost <= 0:
            continue
        item = grouped.setdefault(key, {"cost": 0.0, "pnl": 0.0, "at": resolved_at})
        item["cost"] += cost
        item["pnl"] += _f(row.get("pnl_usd"))
        item["at"] = min(item["at"], resolved_at)
    return list(grouped.values())


def _bootstrap_lower(events, seed):
    if not events:
        return None
    rng = random.Random(seed)
    n = len(events)
    estimates = []
    for _ in range(BOOTSTRAP_SAMPLES):
        cost = pnl = 0.0
        for _ in range(n):
            item = events[rng.randrange(n)]
            cost += item["cost"]
            pnl += item["pnl"]
        estimates.append(pnl / cost if cost > 0 else -1.0)
    estimates.sort()
    return estimates[max(0, math.floor((len(estimates) - 1) * LOWER_QUANTILE))]


def window_stats(rows, *, now, days, min_events, min_span_days, seed):
    events = _events(rows, now - days * 86400)
    count = len(events)
    risked = sum(item["cost"] for item in events)
    pnl = sum(item["pnl"] for item in events)
    span = ((max(item["at"] for item in events) - min(item["at"] for item in events)) / 86400
            if count >= 2 else 0.0)
    qualified = count >= min_events and span >= min_span_days
    lower = _bootstrap_lower(events, seed) if qualified else None
    missing = []
    if count < min_events:
        missing.append(f"{min_events-count} more independent events")
    if span < min_span_days:
        missing.append(f"{max(0.0, min_span_days-span):.1f} more observation days")
    return {
        "days": days, "events": count, "spanDays": round(span, 1),
        "pnlUsd": round(pnl, 2), "riskedUsd": round(risked, 2),
        "returnPct": None if risked <= 0 else round(pnl / risked * 100, 2),
        "lowerReturnPct": None if lower is None else round(lower * 100, 2),
        "qualified": qualified,
        "reason": "Qualified." if qualified else "Needs " + " and ".join(missing) + ".",
    }


def _candidate(source, rows, now):
    short = window_stats(rows, now=now, days=SHORT_DAYS,
                         min_events=SHORT_MIN_EVENTS,
                         min_span_days=SHORT_MIN_SPAN_DAYS,
                         seed=1103 if source == "whale" else 2207)
    long = window_stats(rows, now=now, days=LONG_DAYS,
                        min_events=LONG_MIN_EVENTS,
                        min_span_days=LONG_MIN_SPAN_DAYS,
                        seed=3301 if source == "whale" else 4409)
    qualified = short["qualified"] and long["qualified"]
    conservative = (min(short["lowerReturnPct"], long["lowerReturnPct"])
                    if qualified else None)
    return {
        "source": source, "name": source.title(), "status": "qualified" if qualified else "collecting",
        "reason": ("Recent and longer-window evidence both qualify."
                   if qualified else f"30-day: {short['reason']} 90-day: {long['reason']}"),
        "multiplier": 1.0, "conservativeReturnPct": conservative,
        "shortWindow": short, "longWindow": long,
    }


def build_plan(conn, env, *, enabled_sources=None, now=None):
    now = time.time() if now is None else float(now)
    requested = SUPPORTED_SOURCES if enabled_sources is None else enabled_sources
    enabled = [source for source in requested
               if source in SUPPORTED_SOURCES]
    rows = conn.execute(
        """SELECT id,signal_source,ticker,event_ticker,category,cost_usd,pnl_usd,
                  created_at,resolved_at
             FROM bot_positions
            WHERE network=? AND status='dry_run' AND signal_id<0
              AND resolved=1 AND pnl_usd IS NOT NULL AND filled_contracts>0
              AND signal_source IN ('whale','momentum')""", (env,),
    ).fetchall()
    by_source = {source: [] for source in SUPPORTED_SOURCES}
    for raw in rows:
        row = dict(raw)
        if row.get("signal_source") in by_source:
            by_source[row["signal_source"]].append(row)
    candidates = [_candidate(source, by_source[source], now) for source in enabled]
    positive = [item for item in candidates
                if item["status"] == "qualified" and (item["conservativeReturnPct"] or 0) > 0]
    total_score = sum(item["conservativeReturnPct"] for item in positive)
    for item in candidates:
        if item["status"] != "qualified":
            continue
        if (item["conservativeReturnPct"] or 0) <= 0:
            item["multiplier"] = MIN_MULTIPLIER
            item["reason"] = "Conservative return is not positive in both windows; live size is reduced to 25%."
        elif total_score > 0:
            raw = item["conservativeReturnPct"] / total_score * max(1, len(enabled))
            item["multiplier"] = round(max(0.5, min(MAX_MULTIPLIER, raw)), 2)
            item["reason"] = "Positive in both windows; allocation reflects its share of conservative evidence."
    adjusted = sum(1 for item in candidates if item["multiplier"] != 1.0)
    qualified_count = sum(1 for item in candidates if item["status"] == "qualified")
    return {
        "status": "active" if qualified_count else "collecting",
        "reason": (f"{adjusted} source{'s' if adjusted != 1 else ''} receive an evidence adjustment."
                   if adjusted else
                   f"{qualified_count} source{'s' if qualified_count != 1 else ''} qualify; current evidence keeps base allocation."
                   if qualified_count else "No source has a qualified allocation adjustment yet."),
        "asOf": now, "enabled": enabled, "candidates": candidates,
        "limits": {"minimumMultiplier": MIN_MULTIPLIER,
                   "maximumMultiplier": MAX_MULTIPLIER},
        "method": ("Uses the lower 10th-percentile bootstrapped return from both 30-day and "
                   "90-day independent practice events. Missing evidence leaves sizing unchanged."),
    }


def source_multiplier(conn, env, source, *, enabled_sources=None, now=None):
    if source not in SUPPORTED_SOURCES:
        return 1.0, "Source is outside evidence allocation."
    plan = None
    if now is None:
        try:
            db_row = conn.execute("PRAGMA database_list").fetchone()
            db_identity = str(db_row["file"] if hasattr(db_row, "keys") else db_row[2])
        except Exception:
            db_identity = "active"
        source_key = ("<default>",) if enabled_sources is None else tuple(enabled_sources)
        key = (db_identity, env, source_key)
        cached = _plan_cache.get(key)
        current = time.monotonic()
        if cached and current - cached[0] < 300:
            plan = cached[1]
        else:
            plan = build_plan(conn, env, enabled_sources=enabled_sources)
            _plan_cache.clear()
            _plan_cache[key] = (current, plan)
    if plan is None:
        plan = build_plan(conn, env, enabled_sources=enabled_sources, now=now)
    item = next((row for row in plan["candidates"] if row["source"] == source), None)
    if not item:
        return 1.0, "Source is not enabled."
    return float(item["multiplier"]), item["reason"]
