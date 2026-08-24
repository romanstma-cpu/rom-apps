"""Regression tests for the hardening pass: ledger durability, failed exits,
mode isolation, market parsing and dashboard marking."""
import json
import threading
import time

import pytest

from polybot.config import Config
from polybot.engine import Engine
from polybot.executor import PaperExecutor
from polybot.gamma import _parse_market
from polybot.models import Market, Position, Signal, Snapshot
from polybot.portfolio import Portfolio
from polybot.ui import _state

MKT = Market(condition_id="c1", question="Test?", category="crypto",
             yes_token="y", no_token="n", volume_24h=100000)


def snap(mid=0.5, half=0.01):
    return Snapshot(ts=time.time(), mid=mid, bid=mid - half, ask=mid + half,
                    volume_24h=0)


# -- ledger durability ------------------------------------------------
def test_corrupt_ledger_does_not_block_startup(tmp_path):
    path = tmp_path / "ledger.json"
    path.write_text('{"cash": 500, "positions": [trunca')
    p = Portfolio(1000, path=str(path))
    assert p.cash == 1000 and not p.positions
    assert (tmp_path / "ledger.json.broken").exists()  # kept for inspection


def test_save_is_atomic(tmp_path):
    path = tmp_path / "ledger.json"
    p = Portfolio(1000, path=str(path))
    p.save()
    assert json.loads(path.read_text())["cash"] == 1000
    assert not list(tmp_path.glob("*.tmp"))  # temp file cleaned up


def test_ledger_roundtrip_preserves_positions(tmp_path):
    path = tmp_path / "ledger.json"
    p = Portfolio(1000, path=str(path))
    p.open(Position(market=MKT, side="SELL", entry_price=0.4, shares=25,
                    strategy="momentum"))
    reloaded = Portfolio(1000, path=str(path))
    assert len(reloaded.positions) == 1
    pos = reloaded.positions[0]
    assert pos.side == "SELL" and pos.market.condition_id == "c1"
    assert reloaded.cash == p.cash


# -- executor ---------------------------------------------------------
def test_entry_never_overdraws_cash():
    p = Portfolio(10.0, path=None)
    ex = PaperExecutor(p)
    sig = Signal(market=MKT, side="BUY", strategy="momentum", confidence=1.0,
                 reason="t")
    assert ex.enter(sig, snap(0.33), 25.0) is None   # more than cash
    assert p.cash == 10.0
    pos = ex.enter(sig, snap(0.33), 9.0)
    assert pos and p.cash >= 0                        # rounded cost still fits


def test_failed_live_exit_keeps_position(monkeypatch):
    """A rejected exit must return None so the engine keeps holding."""
    eng = _engine_with([0.50, 0.51, 0.52, 0.53, 0.54, 0.55, 0.90])
    for _ in range(6):
        eng.tick()
    assert eng.portfolio.positions
    held = eng.portfolio.positions[0]
    monkeypatch.setattr(eng.executor, "exit", lambda *a, **k: None)
    eng.tick()   # price jump would normally take profit
    assert eng.portfolio.positions == [held]
    assert not any(e["kind"] == "exit" for e in eng.events)
    assert held.market.condition_id not in eng._last_exit  # no cooldown either


# -- mode isolation ---------------------------------------------------
def test_live_mode_uses_a_separate_ledger(tmp_path, monkeypatch):
    paper = tmp_path / "paper.json"
    cfg = {"mode": "paper", "markets": {}, "strategies": {}, "risk": {},
           "paper": {"starting_cash": 500, "ledger_path": str(paper)},
           "live": {"ledger_path": str(tmp_path / "live.json")}}
    eng = Engine(Config(cfg))
    eng.portfolio.open(Position(market=MKT, side="BUY", entry_price=0.5,
                                shares=10, strategy="momentum"))
    assert paper.exists()

    # live mode must not inherit those paper positions
    monkeypatch.setattr("polybot.engine.LiveExecutor",
                        lambda cfg, pf: PaperExecutor(pf))
    live_eng = Engine(Config(dict(cfg, mode="live")))
    assert not live_eng.portfolio.positions


# -- market parsing ---------------------------------------------------
@pytest.mark.parametrize("raw", [
    {"conditionId": "x", "clobTokenIds": '["a","b","c"]'},          # 3 outcomes
    {"conditionId": "x", "clobTokenIds": '["a","b"]',
     "outcomes": '["Team A","Team B"]'},                            # not yes/no
    {"conditionId": "x", "clobTokenIds": '["a","b"]', "closed": True},
    {"conditionId": "", "clobTokenIds": '["a","b"]'},               # no id
    {"clobTokenIds": "not json"},
])
def test_unusable_markets_are_skipped(raw):
    assert _parse_market(raw, "crypto") is None


def test_binary_market_parses():
    m = _parse_market({"conditionId": "abc", "question": "Up?",
                       "clobTokenIds": '["t1","t2"]',
                       "outcomes": '["Yes","No"]', "volume24hr": 1234.5},
                      "crypto")
    assert m and m.yes_token == "t1" and m.no_token == "t2"
    assert m.volume_24h == 1234.5 and m.category == "crypto"


# -- dashboard --------------------------------------------------------
def test_dashboard_marks_at_entry_before_first_snapshot():
    """No snapshot yet must mean zero P&L — including for long-NO."""
    eng = Engine(Config({"mode": "paper", "markets": {}, "strategies": {},
                         "risk": {}, "paper": {"starting_cash": 100,
                                               "ledger_path": None}}))
    eng.portfolio.positions.append(
        Position(market=MKT, side="SELL", entry_price=0.4, shares=10,
                 strategy="momentum"))
    state = _state(eng)
    assert state["positions"][0]["pnl"] == 0.0
    assert state["positions"][0]["mark"] == 0.4


# -- lifecycle --------------------------------------------------------
def test_engine_stop_ends_run_promptly():
    eng = _engine_with([0.5] * 5)
    eng.cfg.data["poll_seconds"] = 30       # would hang if sleep were blocking
    t = threading.Thread(target=eng.run, daemon=True)
    t.start()
    time.sleep(0.3)
    eng.stop()
    t.join(timeout=5)
    assert not t.is_alive()


def _engine_with(mids):
    import tests.test_engine as te
    return te.make_engine(mids)


# -- config validation ------------------------------------------------
def test_validation_rejects_typos_and_bad_values():
    from polybot.validate import ConfigError, validate
    bad = Config({
        "mode": "reallive",
        "markets": {"categories": [], "min_price": 0.9, "max_price": 0.2},
        "strategies": {"momentom": {"enabled": True},
                       "momentum": {"enabled": True, "confidence": 5}},
        "risk": {"stake_usd": -5, "take_profit_pct": 20, "max_holdd_hours": 3},
    })
    with pytest.raises(ConfigError) as err:
        validate(bad)
    msg = str(err.value)
    for expected in ["mode", "momentom", "confidence", "stake_usd",
                     "take_profit_pct", "max_holdd_hours", "categories",
                     "min_price"]:
        assert expected in msg, f"{expected!r} missing from:\n{msg}"


def test_validation_accepts_the_shipped_example_config():
    from polybot.validate import validate
    assert validate(Config.load("config.example.yaml")) == []


def test_manual_mode_is_a_note_not_an_error():
    from polybot.validate import validate
    notes = validate(Config({"markets": {"categories": ["crypto"]},
                             "strategies": {}, "risk": {}}))
    assert any("manual mode" in n for n in notes)


# -- csv export -------------------------------------------------------
def test_trades_csv_export():
    from polybot.ui import _trades_csv
    eng = _engine_with([0.50, 0.51, 0.52, 0.53, 0.54, 0.55, 0.90])
    for _ in range(7):
        eng.tick()
    csv_text = _trades_csv(eng)
    assert csv_text.splitlines()[0].startswith("closed_at,strategy,side")
    assert len(csv_text.strip().splitlines()) >= 2   # header + a trade
    assert "momentum" in csv_text


def test_equity_curve_is_sampled():
    eng = _engine_with([0.50, 0.51, 0.52])
    for _ in range(3):
        eng.tick()
    assert len(eng.equity) == 3
    assert all(v > 0 for _, v in eng.equity)
