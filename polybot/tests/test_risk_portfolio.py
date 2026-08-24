import time

from polybot.config import Config
from polybot.executor import PaperExecutor
from polybot.models import Market, Position, Signal, Snapshot
from polybot.portfolio import Portfolio
from polybot.risk import RiskManager

MKT = Market(condition_id="c1", question="Test?", category="crypto",
             yes_token="y", no_token="n", volume_24h=100000)
CFG = Config({
    "markets": {"min_price": 0.05, "max_price": 0.95},
    "risk": {"stake_usd": 25, "max_position_usd": 40, "max_open_positions": 2,
             "max_per_category": 2, "daily_loss_stop_usd": 100,
             "take_profit_pct": 0.2, "stop_loss_pct": 0.1, "max_hold_hours": 1},
    "category_overrides": {"sports": {"risk": {"stake_usd": 10}}},
})


def sig(conf=1.0, market=MKT):
    return Signal(market=market, side="BUY", strategy="momentum",
                  confidence=conf, reason="test")


def snap(mid=0.5):
    return Snapshot(ts=time.time(), mid=mid, bid=mid - 0.01, ask=mid + 0.01,
                    volume_24h=0)


def test_entry_size_scales_with_confidence_and_category():
    rm = RiskManager(CFG)
    assert rm.entry_size(sig(1.0)) == 25
    assert rm.entry_size(sig(0.5)) == 12.5
    sports = Market(condition_id="c2", question="?", category="sports",
                    yes_token="y", no_token="n")
    assert rm.entry_size(sig(1.0, sports)) == 10


def test_allow_entry_limits():
    rm = RiskManager(CFG)
    ok, _ = rm.allow_entry(sig(), [], 0)
    assert ok
    pos = Position(market=MKT, side="BUY", entry_price=0.5, shares=60,
                   strategy="momentum")  # $30 in this market
    ok, why = rm.allow_entry(sig(), [pos], 0)
    assert not ok and "holding" in why
    pyr = Config({**CFG.data, "risk": {**CFG.data["risk"],
                                       "allow_pyramiding": True}})
    ok, why = RiskManager(pyr).allow_entry(sig(), [pos], 0)
    assert not ok and "size" in why  # $30 + $25 > $40 cap even when pyramiding
    ok, why = rm.allow_entry(sig(), [], -200)
    assert not ok and "loss" in why


def test_exit_rules():
    rm = RiskManager(CFG)
    pos = Position(market=MKT, side="BUY", entry_price=0.5, shares=10,
                   strategy="momentum")
    assert rm.should_exit(pos, 0.5) is None
    assert "take profit" in rm.should_exit(pos, 0.61)
    assert "stop loss" in rm.should_exit(pos, 0.44)
    pos.opened_ts = time.time() - 2 * 3600
    assert "hold" in rm.should_exit(pos, 0.5)


def test_paper_roundtrip(tmp_path):
    p = Portfolio(1000, path=str(tmp_path / "ledger.json"))
    ex = PaperExecutor(p)
    pos = ex.enter(sig(), snap(0.5), 25)
    assert pos and p.cash < 1000
    pnl = ex.exit(pos, snap(0.6), "take profit")
    assert pnl > 0 and not p.positions and len(p.closed) == 1
    # reload from disk
    p2 = Portfolio(1000, path=str(tmp_path / "ledger.json"))
    assert p2.cash == p.cash and len(p2.closed) == 1


def test_no_side_pnl():
    pos = Position(market=MKT, side="SELL", entry_price=0.5, shares=10,
                   strategy="momentum")
    assert pos.pnl(0.4) > 0   # YES fell → NO holder profits
    assert pos.pnl(0.6) < 0
