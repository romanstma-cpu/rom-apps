from datetime import datetime, timedelta, timezone

import practice_performance as pp


def rows(n, *, pnl=1.0, loss_every=0, cost=10.0, markets=None, days=10):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    out = []
    for i in range(n):
        created = start + timedelta(days=(days * i / max(1, n - 1)))
        value = -abs(pnl) if loss_every and (i + 1) % loss_every == 0 else pnl
        out.append({"id": i + 1, "ticker": f"T-{i}",
                    "event_key": f"M-{i % (markets or n)}", "cost_usd": cost,
                    "resolved": 1, "pnl_usd": value,
                    "created_at": created.isoformat(),
                    "resolved_at": (created + timedelta(hours=1)).isoformat()})
    return out


def test_small_samples_stay_unranked_and_name_the_missing_evidence():
    result = pp.evaluate_candidate("a", "A", "main", rows(8, markets=8, days=2))
    assert result["status"] == "collecting"
    assert result["score"] is None
    assert "settled fills" in result["reason"]
    assert "distinct markets" in result["reason"]
    assert "observation days" in result["reason"]


def test_qualified_candidate_reports_fees_inclusive_recorded_metrics():
    result = pp.evaluate_candidate("a", "A", "main", rows(30, loss_every=3))
    assert result["status"] == "qualified"
    assert result["resolved"] == 30
    assert result["wins"] == 20 and result["losses"] == 10
    assert result["pnlUsd"] == 10.0
    assert result["returnOnRiskPct"] == 3.33
    assert result["profitFactor"] == 2.0
    assert result["score"] is not None


def test_drawdown_uses_settlement_order_and_open_rows_are_not_scored():
    sample = rows(30)
    sample[10]["pnl_usd"] = -6.0
    sample.append({"id": 99, "ticker": "OPEN", "event_key": "OPEN",
                   "cost_usd": 100, "resolved": 0, "pnl_usd": None,
                   "created_at": "2026-01-12T00:00:00+00:00", "resolved_at": None})
    result = pp.evaluate_candidate("a", "A", "main", list(reversed(sample)))
    assert result["open"] == 1
    assert result["resolved"] == 30
    assert result["maxDrawdownUsd"] == 6.0


def test_report_ranks_only_qualified_candidates(tmp_path, monkeypatch):
    import db
    test_db = tmp_path / "practice-ranking.db"
    monkeypatch.setattr(db, "db_path", lambda: test_db)
    db.init_db()
    with db.get_db() as conn:
        for i, row in enumerate(rows(30, pnl=1.0), 1):
            conn.execute(
                """INSERT INTO bot_positions
                   (signal_source,signal_id,ticker,event_ticker,direction,
                    target_contracts,limit_price_cents,filled_contracts,cost_usd,
                    client_order_id,status,resolved,pnl_usd,network,created_at,resolved_at)
                   VALUES ('whale',?,?,?,?,10,50,10,10,?,'dry_run',1,?,'mainnet',?,?)""",
                (-i, row["ticker"], row["event_key"], "yes", f"paper-{i}",
                 row["pnl_usd"], row["created_at"], row["resolved_at"]))
        conn.execute("INSERT INTO user_scripts (id,name,code) VALUES ('s1','New script','')")
        report = pp.build_report(conn, "mainnet")
    assert report["status"] == "qualified"
    assert report["leadingKey"] == "main:whale"
    assert report["candidates"][0]["rank"] == 1
    script = next(item for item in report["candidates"] if item["key"] == "script:s1")
    assert script["rank"] is None and script["status"] == "collecting"
