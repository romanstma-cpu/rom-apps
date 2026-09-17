from __future__ import annotations

import asyncio

import db
import main_recorder
import service
from config import merge_with_defaults


async def _c15_status(*_args, **_kwargs):
    return {"enabled": False, "trading": False, "blockReasons": {}}


def test_trading_status_reports_practice_and_loss_limit_readiness(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "db_path", lambda: tmp_path / "readiness.db")
    db.init_db()
    main_recorder.init()
    cfg = merge_with_defaults({"enable_trading": False, "main_paper_trading": False})
    monkeypatch.setattr(service.STATE, "cfg", cfg)
    monkeypatch.setattr(service.STATE, "paused", False)
    monkeypatch.setattr(service.STATE, "auth_ok", False)
    monkeypatch.setattr(service.trader, "get_env", lambda: "mainnet")
    monkeypatch.setattr(service.crypto15m_trader, "status", _c15_status)
    monkeypatch.setattr(service.order_journal, "blocked_intents", lambda: [])
    monkeypatch.setattr(service.trader, "last_cycle", {
        "skipReason": "no candidates: category filters",
        "filterCounts": {"category politics disabled": 2},
        "candidates": 2,
        "placed": 0,
        "at": 1,
    })
    with db.get_db() as conn:
        now = service.time.time()
        conn.executemany(
            "INSERT INTO main_replay_events(at,kind,ticker,payload) VALUES (?,?,?,?)",
            [(now, "trade", "T", "{}"), (now, "signal", "T", "{}")],
        )

    before = asyncio.run(service._h_trading_status({}))
    assert before["practiceReadiness"] == {
        "completedPracticeTrades": 0,
        "hasCompletedPractice": False,
        "hasLossLimit": True,
        "lossLimitSummary": "daily $50, lifetime 50%",
    }
    assert before["opportunityFunnel"]["tradeEvents"] == 1
    assert before["opportunityFunnel"]["signalEvents"] == 1
    assert before["opportunityFunnel"]["candidates"] == 2
    assert before["opportunityFunnel"]["filtered"] == 2
    assert before["opportunityFunnel"]["primaryBlock"] == "no candidates: category filters"

    with db.get_db() as conn:
        position_id = db.insert_bot_position(conn, {
            "signal_source": "whale", "signal_id": -1, "ticker": "PRACTICE",
            "direction": "yes", "target_contracts": 1, "limit_price_cents": 50,
            "filled_contracts": 1, "cost_usd": 0.5, "client_order_id": "practice-ready-1",
            "status": "dry_run", "network": "mainnet",
        })
        conn.execute("UPDATE bot_positions SET resolved=1, outcome_correct=1 WHERE id=?", (position_id,))

    after = asyncio.run(service._h_trading_status({}))
    assert after["practiceReadiness"]["completedPracticeTrades"] == 1
    assert after["practiceReadiness"]["hasCompletedPractice"] is True
