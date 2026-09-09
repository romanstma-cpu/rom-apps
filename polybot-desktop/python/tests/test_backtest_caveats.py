from __future__ import annotations

import pytest

import script_backtest

CFG = {"crypto15m_interval": "15m", "script_max_entry_cents": 97,
       "script_max_contracts": 20, "crypto15m_order_size": 1}

WINDOW_SCRIPT = "def decide(ctx):\n    return None\n"
MARKET_SCRIPT = "def decide_market(market):\n    return None\n"
SIGNAL_SCRIPT = "def decide_signal(signal):\n    return None\n"
SUPERVISE_SCRIPT = "def supervise(app):\n    return None\n"


def _run(code, tmp_path, monkeypatch):
    import db

    dbfile = tmp_path / "bt.db"
    monkeypatch.setattr(db, "db_path", lambda: dbfile)
    db.init_db()
    return script_backtest.run(dict(CFG), code,
                               env="mainnet", since_days=30)


def _caveats(res) -> str:
    return " || ".join(res.get("caveats") or [])


@pytest.mark.parametrize("code,hook", [
    (MARKET_SCRIPT, "decide_market"),
    (SIGNAL_SCRIPT, "decide_signal"),
    (SUPERVISE_SCRIPT, "supervise"),
])
def test_non_window_scripts_say_NOT_BACKTESTABLE(code, hook, tmp_path, monkeypatch):
    res = _run(code, tmp_path, monkeypatch)
    text = _caveats(res)
    assert "NOT BACKTESTABLE" in text, text
    assert hook in text, text
    assert "let data accumulate" not in text, text


def test_the_not_backtestable_caveat_comes_first(tmp_path, monkeypatch):
    res = _run(MARKET_SCRIPT, tmp_path, monkeypatch)
    assert "NOT BACKTESTABLE" in (res.get("caveats") or [""])[0]


def test_it_points_at_shadow_mode_as_the_alternative(tmp_path, monkeypatch):
    res = _run(MARKET_SCRIPT, tmp_path, monkeypatch)
    assert "SHADOW" in _caveats(res).upper()


def test_a_decide_script_on_an_empty_db_still_blames_the_data(tmp_path, monkeypatch):
    res = _run(WINDOW_SCRIPT, tmp_path, monkeypatch)
    text = _caveats(res)
    assert "No resolved 15m windows" in text, text
    assert "NOT BACKTESTABLE" not in text, text


def test_zero_trades_is_reported_consistently(tmp_path, monkeypatch):
    for code in (MARKET_SCRIPT, WINDOW_SCRIPT):
        res = _run(code, tmp_path, monkeypatch)
        assert res["n"] == 0
        assert res["windowsScanned"] == 0
        assert res.get("scriptError") is None
