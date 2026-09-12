"""Evidence-aware ranking for recorded practice strategies.

The report compares only settled, recorded practice fills. It never mixes in
live trades or historical backtests, and it keeps small samples unranked.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone


MIN_RESOLVED = 30
MIN_INDEPENDENT_MARKETS = 20
MIN_SPAN_DAYS = 7.0


def _f(value, default=0.0):
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def _dt(value):
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    if "T" not in text and " " in text:
        text = text.replace(" ", "T", 1)
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc)


def evaluate_candidate(key: str, name: str, kind: str, rows: list[dict]) -> dict:
    open_count = sum(1 for row in rows if not bool(row.get("resolved")))
    settled = [row for row in rows if bool(row.get("resolved"))
               and row.get("pnl_usd") is not None
               and _dt(row.get("resolved_at")) is not None]
    settled.sort(key=lambda row: (_dt(row.get("resolved_at")), int(row.get("id") or 0)))

    pnl = sum(_f(row.get("pnl_usd")) for row in settled)
    risked = sum(max(0.0, _f(row.get("cost_usd"))) for row in settled)
    wins = sum(1 for row in settled if _f(row.get("pnl_usd")) > 0)
    losses = sum(1 for row in settled if _f(row.get("pnl_usd")) < 0)
    gross_profit = sum(max(0.0, _f(row.get("pnl_usd"))) for row in settled)
    gross_loss = sum(max(0.0, -_f(row.get("pnl_usd"))) for row in settled)

    equity = peak = max_drawdown = 0.0
    for row in settled:
        equity += _f(row.get("pnl_usd"))
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)

    markets = {str(row.get("event_key") or row.get("ticker") or "").strip()
               for row in settled}
    markets.discard("")
    dates = [_dt(row.get("created_at")) for row in settled]
    dates = [stamp for stamp in dates if stamp is not None]
    span_days = ((max(dates) - min(dates)).total_seconds() / 86400.0
                 if len(dates) >= 2 else 0.0)
    n = len(settled)
    missing = []
    if n < MIN_RESOLVED:
        missing.append(f"{MIN_RESOLVED - n} more settled fills")
    if len(markets) < MIN_INDEPENDENT_MARKETS:
        missing.append(f"{MIN_INDEPENDENT_MARKETS - len(markets)} more distinct markets")
    if span_days < MIN_SPAN_DAYS:
        missing.append(f"{max(0.0, MIN_SPAN_DAYS - span_days):.1f} more observation days")

    return_on_risk = (pnl / risked * 100.0) if risked > 0 else None
    drawdown_on_risk = (max_drawdown / risked * 100.0) if risked > 0 else None
    qualified = not missing
    shrinkage = n / (n + MIN_RESOLVED) if n else 0.0
    score = ((return_on_risk or 0.0) * shrinkage
             - (drawdown_on_risk or 0.0) * 0.5) if qualified else None
    return {
        "key": key, "name": name, "kind": kind, "rank": None,
        "status": "qualified" if qualified else "collecting",
        "reason": ("Enough recorded practice evidence for comparison."
                   if qualified else "Needs " + ", ".join(missing) + "."),
        "resolved": n, "open": open_count, "wins": wins, "losses": losses,
        "breakEven": n - wins - losses, "distinctMarkets": len(markets),
        "spanDays": round(span_days, 1), "pnlUsd": round(pnl, 2),
        "riskedUsd": round(risked, 2),
        "returnOnRiskPct": None if return_on_risk is None else round(return_on_risk, 2),
        "averagePnlUsd": None if not n else round(pnl / n, 4),
        "maxDrawdownUsd": round(max_drawdown, 2),
        "profitFactor": None if gross_loss <= 0 else round(gross_profit / gross_loss, 3),
        "score": None if score is None else round(score, 3),
    }


def build_report(conn, env: str) -> dict:
    groups: dict[str, dict] = {
        "main:whale": {"name": "Main · Whale", "kind": "main", "rows": []},
        "main:momentum": {"name": "Main · Momentum", "kind": "main", "rows": []},
    }
    paper = conn.execute(
        """SELECT id, signal_source, ticker, event_ticker, cost_usd, resolved,
                  pnl_usd, created_at, resolved_at
             FROM bot_positions
            WHERE network=? AND status='dry_run' AND signal_id<0
              AND filled_contracts>0""", (env,)).fetchall()
    for raw in paper:
        row = dict(raw)
        source = str(row.get("signal_source") or "other")
        key = f"main:{source}"
        group = groups.setdefault(key, {
            "name": f"Main · {source.replace('_', ' ').title()}",
            "kind": "main", "rows": [],
        })
        row["event_key"] = row.get("event_ticker") or row.get("ticker")
        group["rows"].append(row)

    scripts = conn.execute("SELECT id, name FROM user_scripts ORDER BY created_at").fetchall()
    for raw in scripts:
        script = dict(raw)
        groups[f"script:{script['id']}"] = {
            "name": str(script.get("name") or "Untitled script"),
            "kind": "script", "rows": [],
        }
    shadows = conn.execute(
        """SELECT id, script_id, ticker, contracts, entry_cents, resolved,
                  pnl_usd, created_at, resolved_at
             FROM script_shadow_orders
            WHERE network=? AND contracts>0 AND refused=0""", (env,)).fetchall()
    for raw in shadows:
        row = dict(raw)
        sid = str(row.get("script_id") or "")
        key = f"script:{sid}"
        group = groups.setdefault(key, {
            "name": "Removed script", "kind": "script", "rows": [],
        })
        row["cost_usd"] = int(row.get("contracts") or 0) * _f(row.get("entry_cents")) / 100.0
        row["event_key"] = row.get("ticker")
        group["rows"].append(row)

    candidates = [evaluate_candidate(key, value["name"], value["kind"], value["rows"])
                  for key, value in groups.items()]
    candidates.sort(key=lambda item: (
        item["status"] != "qualified",
        -(item["score"] if item["score"] is not None else -10**9),
        -item["resolved"], item["name"].lower(),
    ))
    rank = 0
    for item in candidates:
        if item["status"] == "qualified":
            rank += 1
            item["rank"] = rank
    total = sum(item["resolved"] for item in candidates)
    return {
        "status": "qualified" if rank else "collecting",
        "reason": (f"{rank} practice strateg{'y' if rank == 1 else 'ies'} has enough "
                   "evidence for a risk-adjusted comparison."
                   if rank else "No practice strategy has enough independent evidence to rank yet."),
        "asOf": datetime.now(timezone.utc).timestamp(),
        "resolvedSamples": total, "qualifiedStrategies": rank,
        "leadingKey": candidates[0]["key"] if rank else None,
        "thresholds": {"resolved": MIN_RESOLVED,
                       "distinctMarkets": MIN_INDEPENDENT_MARKETS,
                       "spanDays": MIN_SPAN_DAYS},
        "method": ("Score = return on recorded capital at risk, reduced for small samples, "
                   "minus half the realized drawdown rate. It ranks observed practice results, "
                   "not expected future returns."),
        "candidates": candidates,
    }
