from datetime import datetime, timedelta, timezone

import strategy_allocator as allocator


NOW = datetime(2026, 9, 1, tzinfo=timezone.utc)


def sample(source, n, *, roi, span_days=60, start_id=1):
    rows = []
    for i in range(n):
        at = NOW - timedelta(days=span_days * i / max(1, n - 1))
        rows.append({
            "id": start_id + i, "signal_source": source, "ticker": f"T-{source}-{start_id+i}",
            "event_ticker": f"E-{source}-{start_id+i}", "category": "politics",
            "cost_usd": 10, "pnl_usd": 10 * roi,
            "created_at": (at - timedelta(hours=1)).isoformat(),
            "resolved_at": at.isoformat(),
        })
    return rows


class Conn:
    def __init__(self, rows): self.rows = rows
    def execute(self, _sql, _args): return Cursor(self.rows)


class Cursor:
    def __init__(self, rows): self.rows = rows
    def fetchall(self): return self.rows


def test_small_samples_leave_live_sizing_unchanged():
    plan = allocator.build_plan(Conn(sample("whale", 10, roi=.2)), "mainnet", now=NOW.timestamp())
    whale = next(row for row in plan["candidates"] if row["source"] == "whale")
    assert whale["status"] == "collecting"
    assert whale["multiplier"] == 1.0


def test_repeated_rows_collapse_to_independent_events():
    rows = sample("whale", 20, roi=.2, span_days=28)
    rows += [{**row, "id": row["id"] + 1000} for row in rows]
    stats = allocator.window_stats(rows, now=NOW.timestamp(), days=30,
                                   min_events=20, min_span_days=7, seed=1)
    assert stats["events"] == 20


def test_positive_leader_gains_and_negative_source_is_cut():
    rows = sample("whale", 50, roi=.20) + sample("momentum", 50, roi=-.10, start_id=100)
    plan = allocator.build_plan(Conn(rows), "mainnet", now=NOW.timestamp())
    by_source = {row["source"]: row for row in plan["candidates"]}
    assert by_source["whale"]["status"] == "qualified"
    assert by_source["whale"]["multiplier"] == 1.5
    assert by_source["momentum"]["multiplier"] == .25


def test_mixed_recent_and_long_term_results_do_not_promote_a_source():
    old = sample("whale", 30, roi=.25, span_days=80)
    recent = sample("whale", 22, roi=-.20, span_days=20, start_id=100)
    plan = allocator.build_plan(Conn(old + recent), "mainnet", enabled_sources=["whale"],
                                now=NOW.timestamp())
    whale = plan["candidates"][0]
    assert whale["status"] == "qualified"
    assert whale["conservativeReturnPct"] < 0
    assert whale["multiplier"] == .25


def test_unsupported_source_never_receives_an_adjustment():
    assert allocator.source_multiplier(Conn([]), "mainnet", "convergence")[0] == 1.0


def test_allocation_multiplies_strategy_target_but_never_risk_caps():
    import trader
    from config import merge_with_defaults
    cfg = merge_with_defaults({"hardMaxPositionUsd": 40, "maxTotalExposureFraction": .75})
    base = trader.entry_budget(1000, 0, 0, 10, 50, cfg)
    raised = trader.entry_budget(1000, 0, 0, 10, 50, cfg, allocation_multiplier=1.5)
    reduced = trader.entry_budget(1000, 0, 0, 10, 50, cfg, allocation_multiplier=.25)
    assert reduced == base * .25
    assert base < raised <= cfg["hard_max_position_usd"]
