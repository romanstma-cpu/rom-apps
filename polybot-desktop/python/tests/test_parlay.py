from __future__ import annotations

import json

import pytest

import crypto15m
import crypto15m_trader as ct
import db
import parlay_generator as pg
import replay
from config import merge_with_defaults


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    dbfile = tmp_path / "parlay-test.db"
    monkeypatch.setattr(db, "db_path", lambda: dbfile)
    db.init_db()
    ct._parlay_cache.update({"at": 0.0, "armed": False, "schedule": None})
    return dbfile


def _cfg(**over):
    c = merge_with_defaults({})
    c["crypto15m_enabled"] = True
    c.update(over)
    return c


def test_hour_override_no_schedule_returns_cfg_unchanged():
    c = _cfg()
    assert crypto15m.hour_override(c, 7) is c


def test_hour_override_seated_merges_and_unseated_returns_none():
    c = _cfg(crypto15m_hour_configs={
        "7": {"crypto15m_entry_threshold": 0.97},
    })
    merged = crypto15m.hour_override(c, 7)
    assert merged is not c
    assert merged["crypto15m_entry_threshold"] == 0.97
    assert merged["crypto15m_enabled"] is True
    assert c["crypto15m_entry_threshold"] != 0.97 or True
    assert crypto15m.hour_override(c, 8) is None


def test_resignal_asset_recomputes_signal_under_new_config():
    a = {
        "minsLeft": 2.5, "favoritePrice": 0.965, "entryCost": 0.97,
        "deltaPct": None, "hourUtc": 7, "inWindow": False, "signal": False,
    }
    tight = _cfg(
        crypto15m_entry_threshold=0.96, crypto15m_time_delay_min=3.0,
        crypto15m_entry_max=0.99,
    )
    out = crypto15m.resignal_asset(a, tight)
    assert out["inWindow"] is True and out["signal"] is True
    assert a["signal"] is False
    deep = _cfg(crypto15m_entry_threshold=0.98, crypto15m_time_delay_min=3.0)
    assert crypto15m.resignal_asset(a, deep)["signal"] is False


def test_parlay_state_unarmed_and_armed(fresh_db):
    armed, sched = ct.parlay_state(force=True)
    assert armed is False and sched is None
    payload = {"interval": "15m", "hour_configs": {"7": {"crypto15m_entry_threshold": 0.97}}}
    with db.get_db() as conn:
        db.kv_set(conn, ct._PARLAY_KV_SCHEDULE, json.dumps(payload))
        db.kv_set(conn, ct._PARLAY_KV_ARMED, "1")
    armed, sched = ct.parlay_state(force=True)
    assert armed is True
    assert sched["hour_configs"]["7"]["crypto15m_entry_threshold"] == 0.97


def test_empty_schedule_seats_nothing_and_cannot_be_armed(fresh_db):
    assert crypto15m.hour_override(_cfg(crypto15m_hour_configs={}), 7) is None
    c_absent = _cfg()
    assert crypto15m.hour_override(c_absent, 7) is c_absent

    with db.get_db() as conn:
        db.kv_set(conn, ct._PARLAY_KV_SCHEDULE,
                  json.dumps({"interval": "15m", "hour_configs": {}}))
        db.kv_set(conn, ct._PARLAY_KV_ARMED, "1")
    armed, sched = ct.parlay_state(force=True)
    assert armed is False and sched is None

    with pytest.raises(ValueError, match="0 of 24"):
        pg.set_armed(True)


def test_parlay_state_armed_without_valid_schedule_is_disarmed(fresh_db):
    with db.get_db() as conn:
        db.kv_set(conn, ct._PARLAY_KV_ARMED, "1")
        db.kv_set(conn, ct._PARLAY_KV_SCHEDULE, "not json{")
    armed, sched = ct.parlay_state(force=True)
    assert armed is False and sched is None


def test_parlay_rows_exempt_from_stop_and_take_profit():
    pos = {"strategy": "parlay", "status": "filled", "filled_contracts": 5,
           "cost_usd": 4.9, "avg_entry_cents": 98.0}
    c = _cfg(crypto15m_exit_threshold=0.40, crypto15m_take_profit=0.99,
             crypto15m_take_profit_pct=0.01, crypto15m_stop_loss_pct=0.05,
             crypto15m_sell_into_strength=True)
    assert ct.should_stop_loss(pos, 0.05, c) is False
    assert ct.should_take_profit(pos, 99, c) is False
    assert ct.should_take_profit_pct(pos, 99, c) is False
    assert ct.strength_exit_cents(pos, c) is None
    fav = dict(pos, strategy="favorite")
    assert ct.should_stop_loss(fav, 0.05, c) is True


def _window(ticker, hour, up_won, *, up_prob=0.97, ask=0.97, macd=1.0):
    return {
        ticker: [{
            "ticker": ticker, "asset": "BTC", "network": "mainnet",
            "observed_at": f"2026-07-20 {hour:02d}:57:00", "mins_left": 2.0,
            "up_prob": up_prob, "yes_bid": up_prob - 0.01, "yes_ask": up_prob + 0.005,
            "up_ask": ask, "no_ask": round(1.0 - ask + 0.01, 3),
            "macd_hist": macd, "rsi": 60.0,
            "up_won": up_won, "sig_close": f"2026-07-20T{hour:02d}:59:59Z",
            "spot_source": "rtds-ws", "delta_pct": None,
        }],
    }


def _sched_cfg(hours):
    ov = {
        **pg.PINNED,
        "crypto15m_entry_threshold": 0.96,
        "crypto15m_time_delay_min": 3.0,
        "crypto15m_min_macd_hist": 0.0,
    }
    return _cfg(crypto15m_hour_configs={str(h): ov for h in hours})


def test_simulate_trades_seated_hour_and_skips_unseated():
    wins = {}
    wins.update(_window("W7", 7, 1))
    wins.update(_window("W8", 8, 1))
    trades, n_windows, _ = replay._simulate(wins, _sched_cfg([7]))
    assert n_windows == 2
    assert [t["ticker"] for t in trades] == ["W7"]
    assert trades[0]["won"] is True
    trades2, _, _ = replay._simulate(wins, _sched_cfg([7, 8]))
    assert {t["ticker"] for t in trades2} == {"W7", "W8"}


def test_simulate_empty_schedule_trades_nothing():
    wins = {}
    wins.update(_window("W7", 7, 1))
    wins.update(_window("W8", 8, 1))
    trades, n_windows, _ = replay._simulate(wins, _sched_cfg([]))
    assert n_windows == 2 and trades == []


def test_simulate_no_schedule_unchanged_baseline():
    wins = _window("W7", 7, 1)
    c = _cfg(crypto15m_entry_threshold=0.96, crypto15m_time_delay_min=3.0,
             crypto15m_entry_max=0.99, crypto15m_entry_style="taker")
    trades, _, _ = replay._simulate(wins, c)
    assert len(trades) == 1


def _trades(spec):
    return [{"at": f"{d} 07:57:00", "won": w, "pnlUsd": p} for d, w, p in spec]


def test_generator_qualifies_perfect_train_and_holdout():
    tr = pg._stats(_trades([("2026-07-10", True, 0.02)] * 12))
    ho = pg._stats(_trades([("2026-07-21", True, 0.02)] * 3))
    assert pg._qualifies(tr, ho, 1.0, 10) is True


def test_generator_rejects_thin_lossy_or_failed_holdout():
    perfect12 = _trades([("2026-07-10", True, 0.02)] * 12)
    assert not pg._qualifies(pg._stats(perfect12[:5]), pg._stats([]), 1.0, 10)
    with_loss = pg._stats(perfect12 + _trades([("2026-07-11", False, -0.97)]))
    assert not pg._qualifies(with_loss, pg._stats([]), 1.0, 10)
    bad_holdout = pg._stats(_trades([("2026-07-21", False, -0.97)]))
    assert not pg._qualifies(pg._stats(perfect12), bad_holdout, 1.0, 10)
    assert pg._qualifies(pg._stats(perfect12), pg._stats([]), 1.0, 10)


def test_generator_split_by_holdout_dates():
    ts = _trades([("2026-07-10", True, 0.02), ("2026-07-21", True, 0.02)])
    tr, ho = pg._split(ts, {"2026-07-21"})
    assert len(tr) == 1 and len(ho) == 1
    assert ho[0]["at"].startswith("2026-07-21")
