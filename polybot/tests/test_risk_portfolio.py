import json
import time

import pytest

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


def test_max_per_event_blocks_sibling_markets():
    rm = RiskManager(CFG)
    fed_a = Market(condition_id="a", question="50bps?", category="crypto",
                   yes_token="y", no_token="n", event_slug="fed-sept")
    fed_b = Market(condition_id="b", question="25bps?", category="crypto",
                   yes_token="y", no_token="n", event_slug="fed-sept")
    other = Market(condition_id="d", question="jobs?", category="crypto",
                   yes_token="y", no_token="n", event_slug="jobs-oct")
    pos = Position(market=fed_a, side="BUY", entry_price=0.5, shares=10,
                   strategy="momentum")
    # sibling market of the same event: one bet, already placed
    ok, why = rm.allow_entry(sig(market=fed_b), [pos], 0)
    assert not ok and "event" in why
    # unrelated event unaffected
    ok, _ = rm.allow_entry(sig(market=other), [pos], 0)
    assert ok


def test_markets_without_event_slug_are_their_own_event():
    rm = RiskManager(CFG)
    solo1 = Market(condition_id="s1", question="?", category="crypto",
                   yes_token="y", no_token="n")
    solo2 = Market(condition_id="s2", question="?", category="crypto",
                   yes_token="y", no_token="n")
    pos = Position(market=solo1, side="BUY", entry_price=0.5, shares=10,
                   strategy="momentum")
    ok, _ = rm.allow_entry(sig(market=solo2), [pos], 0)
    assert ok


def test_spread_gate():
    rm = RiskManager(CFG)
    tight = Snapshot(ts=0, mid=0.5, bid=0.49, ask=0.51, volume_24h=0)
    wide = Snapshot(ts=0, mid=0.5, bid=0.46, ask=0.54, volume_24h=0)
    assert rm.spread_ok(tight)
    assert not rm.spread_ok(wide)


def test_exit_targets_must_exist_on_the_price_line():
    # The first soak's two failure modes: a 7c buy whose 10% stop is a
    # single tick away, and a 95c NO whose +20% target is above $1.00.
    rm = RiskManager(CFG)
    cheap = Snapshot(ts=0, mid=0.075, bid=0.07, ask=0.08, volume_24h=0)
    ok, why = rm.exits_reachable("BUY", cheap, "crypto")
    assert not ok and "noise" in why

    near_ceiling = Snapshot(ts=0, mid=0.05, bid=0.045, ask=0.055, volume_24h=0)
    ok, why = rm.exits_reachable("SELL", near_ceiling, "crypto")  # NO at ~0.955
    assert not ok and "ceiling" in why

    mid = Snapshot(ts=0, mid=0.5, bid=0.49, ask=0.51, volume_24h=0)
    assert rm.exits_reachable("BUY", mid, "crypto")[0]
    assert rm.exits_reachable("SELL", mid, "crypto")[0]


def test_paper_roundtrip(tmp_path):
    p = Portfolio(1000, path=str(tmp_path / "ledger.json"))
    ex = PaperExecutor(p)
    pos = ex.enter(sig(), snap(0.5), 25)
    assert pos and p.cash < 1000
    pnl = ex.exit(pos, snap(0.6), "take profit")
    assert pnl > 0 and not p.positions and len(p.closed) == 1
    # the atomic save leaves the real file and no temp debris behind
    assert not (tmp_path / "ledger.json.tmp").exists()
    # reload from disk
    p2 = Portfolio(1000, path=str(tmp_path / "ledger.json"))
    assert p2.cash == p.cash and len(p2.closed) == 1


def test_no_side_pnl():
    pos = Position(market=MKT, side="SELL", entry_price=0.5, shares=10,
                   strategy="momentum")
    assert pos.pnl(0.4) > 0   # YES fell → NO holder profits
    assert pos.pnl(0.6) < 0


# -- fees ------------------------------------------------------------

class FixedFees:
    def __init__(self, rate=0.05):
        self.rate = rate

    def rate_for(self, condition_id):
        return self.rate


def test_paper_entry_charges_the_taker_fee_on_top_of_the_stake():
    p = Portfolio(1000)
    pos = PaperExecutor(p, FixedFees(0.05)).enter(sig(), snap(0.5), 25)
    assert pos.fees_paid > 0
    # the stake AND the fee leave the bankroll at open
    assert p.cash == pytest.approx(1000 - pos.cost - pos.fees_paid)
    assert pos.basis == pytest.approx(pos.cost + pos.fees_paid)


def test_paper_roundtrip_books_gross_fees_and_net_separately():
    # "the idea was right and the fees ate it" and "the idea was wrong" are
    # different lessons; one net figure cannot tell them apart.
    p = Portfolio(1000)
    ex = PaperExecutor(p, FixedFees(0.05))
    pos = ex.enter(sig(), snap(0.5), 25)
    net = ex.exit(pos, snap(0.6), "take profit")
    rec = p.closed[0]
    assert rec["gross"] > rec["pnl"]           # fees came out of the win
    assert rec["fees"] > 0
    assert rec["pnl"] == pytest.approx(net, abs=0.01)
    assert rec["pnl"] == pytest.approx(rec["gross"] - rec["fees"], abs=0.01)


def test_a_fee_blind_ledger_would_have_overstated_the_same_trade():
    free = Portfolio(1000)
    fex = PaperExecutor(free)
    fex.exit(fex.enter(sig(), snap(0.5), 25), snap(0.6), "tp")
    charged = Portfolio(1000)
    cex = PaperExecutor(charged, FixedFees(0.05))
    cex.exit(cex.enter(sig(), snap(0.5), 25), snap(0.6), "tp")
    assert charged.closed[0]["pnl"] < free.closed[0]["pnl"]
    assert charged.cash < free.cash


def test_cash_is_conserved_across_a_fee_charged_roundtrip():
    p = Portfolio(1000)
    ex = PaperExecutor(p, FixedFees(0.05))
    net = ex.exit(ex.enter(sig(), snap(0.5), 25), snap(0.6), "tp")
    assert p.cash == pytest.approx(1000 + net, abs=0.01)


def held(fees_paid=0.0):
    return Position(market=MKT, side="BUY", entry_price=0.5, shares=50,
                    strategy="momentum", fees_paid=fees_paid)


def test_take_profit_is_measured_after_fees_not_before():
    # +24% on price alone clears the 20% target. Once the entry fee already
    # paid and the exit fee still owed come out, the same move nets under
    # 20% — it was never a 20% take profit, it only read like one.
    rm = RiskManager(CFG)                       # take_profit_pct = 0.2
    assert "take profit" in rm.should_exit(held(), 0.62)
    assert rm.should_exit(held(0.40), 0.62, fee_rate=0.05) is None


def test_stop_loss_fires_sooner_once_fees_are_counted():
    # -9% on price alone sits inside the 10% stop. After both legs it does
    # not, and the position is losing more than the operator authorised.
    rm = RiskManager(CFG)                       # stop_loss_pct = 0.1
    assert rm.should_exit(held(), 0.455) is None
    assert "stop loss" in rm.should_exit(held(0.40), 0.455, fee_rate=0.05)


def test_entries_whose_target_the_fees_would_eat_are_refused():
    # The gate that will refuse the most trades, and should.
    rm = RiskManager(CFG)
    mid = Snapshot(ts=0, mid=0.5, bid=0.49, ask=0.51, volume_24h=0)
    assert rm.exits_reachable("BUY", mid, "crypto")[0]        # fee-blind: fine
    ok, why = rm.exits_reachable("BUY", mid, "crypto", fee_rate=0.30)
    assert not ok and "fees" in why


def test_a_generous_target_still_clears_a_normal_fee():
    rm = RiskManager(CFG)
    mid = Snapshot(ts=0, mid=0.5, bid=0.49, ask=0.51, volume_24h=0)
    assert rm.exits_reachable("BUY", mid, "crypto", fee_rate=0.05)[0]


def test_ledgers_written_before_fees_existed_still_load(tmp_path):
    # Old ledgers have no fees_paid. They must load and simply report the
    # entry leg as free — which is what they believed at the time.
    led = tmp_path / "ledger.json"
    led.write_text(json.dumps({
        "cash": 900.0,
        "positions": [{
            "market": {"condition_id": "c1", "question": "?",
                       "category": "crypto", "yes_token": "y",
                       "no_token": "n", "volume_24h": 1.0,
                       "end_date": "", "event_slug": ""},
            "side": "BUY", "entry_price": 0.5, "shares": 10.0,
            "strategy": "momentum", "opened_ts": 1787650384.29}],
        "closed": [],
    }))
    p = Portfolio(1000, path=str(led))
    assert p.cash == 900.0
    assert p.positions[0].fees_paid == 0.0
    assert p.positions[0].basis == p.positions[0].cost
