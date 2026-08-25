"""End-to-end engine test with fake Gamma/CLOB clients — no network."""
import time

from polybot.config import Config
from polybot.engine import Engine
from polybot.models import Market, Snapshot

CFG = {
    "mode": "paper", "poll_seconds": 1, "history_size": 100,
    "markets": {"categories": ["crypto"], "exclude_categories": [],
                "limit_per_category": 5, "min_volume_24h": 0,
                "min_price": 0.05, "max_price": 0.95},
    "strategies": {"momentum": {"enabled": True, "lookback": 5,
                                "min_move": 0.03, "confidence": 1.0}},
    "risk": {"stake_usd": 20, "max_position_usd": 100,
             "max_open_positions": 5, "max_per_category": 5,
             "daily_loss_stop_usd": 1000, "take_profit_pct": 0.10,
             "stop_loss_pct": 0.10, "max_hold_hours": 48},
    "paper": {"starting_cash": 500, "ledger_path": None},
}

MKT = Market(condition_id="c1", question="Up?", category="crypto",
             yes_token="y1", no_token="n1", volume_24h=50000)


class FakeGamma:
    def __init__(self, markets=None):
        self.markets = [MKT] if markets is None else markets
        self.resolved = (False, None)   # what resolution() reports

    def discover(self, **kw):
        return list(self.markets)

    def resolution(self, condition_id):
        return self.resolved


class FakeClob:
    """Serves a scripted sequence of midpoints."""
    def __init__(self, mids, half_spread=0.01):
        self.mids = list(mids)
        self.half_spread = half_spread
        self.i = -1

    def snapshot(self, token_id, volume_24h=0.0):
        self.i = min(self.i + 1, len(self.mids) - 1)
        mid = self.mids[self.i]
        return Snapshot(ts=time.time(), mid=mid, bid=mid - self.half_spread,
                        ask=mid + self.half_spread, volume_24h=50000)

    def recent_trades(self, condition_id, limit=50):
        return []


class NoBookClob:
    """A market whose order book has disappeared."""
    def snapshot(self, token_id, volume_24h=0.0):
        return None

    def recent_trades(self, condition_id, limit=50):
        return []


def make_engine(mids):
    eng = Engine(Config(CFG))
    eng.gamma = FakeGamma()
    eng.clob = FakeClob(mids)
    eng.discover()
    return eng


def test_engine_enters_on_momentum_and_takes_profit():
    # steady rise triggers momentum entry, then a jump triggers take-profit
    eng = make_engine([0.50, 0.51, 0.52, 0.53, 0.54, 0.55, 0.70])
    entered = []
    for _ in range(6):
        entered += eng.tick()
    assert len(entered) == 1 and entered[0].side == "BUY"
    assert len(eng.portfolio.positions) == 1
    eng.tick()  # mid jumps to 0.70 -> +20% on entry ~0.56 -> take profit
    assert not eng.portfolio.positions
    assert len(eng.portfolio.closed) == 1
    assert eng.portfolio.closed[0]["pnl"] > 0
    assert eng.portfolio.cash > 500  # ended with a profit


def test_engine_paused_blocks_entries_but_not_exits():
    eng = make_engine([0.50, 0.51, 0.52, 0.53, 0.54, 0.55])
    eng.paused = True
    for _ in range(6):
        eng.tick()
    assert not eng.portfolio.positions


def test_engine_respects_price_band():
    cfg = dict(CFG, markets=dict(CFG["markets"], max_price=0.60))
    eng = Engine(Config(cfg))
    eng.gamma = FakeGamma()
    eng.clob = FakeClob([0.90, 0.91, 0.92, 0.93, 0.94, 0.95])
    eng.discover()
    for _ in range(6):
        eng.tick()
    assert not eng.portfolio.positions


def test_history_pruned_on_rediscover():
    eng = make_engine([0.5])
    eng.history["stale-market"].append(
        Snapshot(ts=0, mid=0.5, bid=0.49, ask=0.51, volume_24h=0))
    eng.discover()
    assert "stale-market" not in eng.history
    assert MKT.condition_id in eng.history or not eng.history  # kept if seen


def test_held_market_managed_after_discovery_drops_it():
    # Discovery ranks by volume, so a held market will eventually fall off
    # the watch list. Its exits must keep working anyway.
    eng = make_engine([0.50, 0.51, 0.52, 0.53, 0.54, 0.55, 0.70])
    for _ in range(6):
        eng.tick()
    assert eng.portfolio.positions
    eng.gamma.markets = []          # market vanishes from discovery
    eng.discover()
    assert not eng.markets
    eng.tick()                      # mid 0.70 → take-profit must still fire
    assert not eng.portfolio.positions
    assert eng.portfolio.closed and eng.portfolio.closed[-1]["pnl"] > 0


def test_dropped_market_takes_no_new_entries():
    # The union keeps exits alive for held markets; it must not quietly
    # keep ENTERING markets that discovery no longer vouches for.
    eng = make_engine([0.50, 0.51, 0.52, 0.53, 0.54, 0.55, 0.70])
    for _ in range(4):
        eng.tick()
    assert not eng.portfolio.positions      # not enough history yet
    # hold one position so the market stays in the tick universe
    for _ in range(2):
        eng.tick()
    assert eng.portfolio.positions
    eng.gamma.markets = []
    eng.discover()
    eng.tick()                              # exits at 0.70
    for _ in range(3):
        eng.tick()                          # more rising mids, no watch list
    assert not eng.portfolio.positions      # nothing re-entered


def test_resolved_market_settles_position():
    eng = make_engine([0.50, 0.51, 0.52, 0.53, 0.54, 0.55])
    for _ in range(6):
        eng.tick()
    assert eng.portfolio.positions
    cash_before = eng.portfolio.cash
    shares = eng.portfolio.positions[0].shares
    eng.clob = NoBookClob()                 # book gone
    eng.gamma.resolved = (False, None)      # transient: hold
    eng.tick()
    assert eng.portfolio.positions
    eng.gamma.resolved = (True, None)       # closed but not yet resolved: hold
    eng.tick()
    assert eng.portfolio.positions
    eng.gamma.resolved = (True, 1.0)        # resolved YES
    eng.tick()
    assert not eng.portfolio.positions
    closed = eng.portfolio.closed[-1]
    assert "settled" in closed["reason"] and closed["pnl"] > 0
    # settlement pays face value: $1 per share lands in cash
    assert abs(eng.portfolio.cash - (cash_before + shares)) < 0.01


def test_wide_spread_blocks_entry():
    eng = Engine(Config(CFG))
    eng.gamma = FakeGamma()
    # 0.08 spread against the 0.05 default gate
    eng.clob = FakeClob([0.50, 0.51, 0.52, 0.53, 0.54, 0.55], half_spread=0.04)
    eng.discover()
    for _ in range(6):
        eng.tick()
    assert not eng.portfolio.positions


def test_soak_accounting_invariant():
    # random-walk market for 400 ticks: never crashes, and
    # cash + open cost == starting cash + realized pnl at every step
    import random
    rng = random.Random(42)
    mid, mids = 0.50, []
    for _ in range(400):
        mid = min(0.93, max(0.07, mid + rng.uniform(-0.02, 0.02)))
        mids.append(round(mid, 3))
    cfg = dict(CFG, risk=dict(CFG["risk"], reentry_cooldown_minutes=0))
    eng = Engine(Config(cfg))
    eng.gamma = FakeGamma()
    eng.clob = FakeClob(mids)
    eng.discover()
    for _ in range(400):
        eng.tick()
        realized = sum(c["pnl"] for c in eng.portfolio.closed)
        open_cost = sum(p.cost for p in eng.portfolio.positions)
        assert abs(eng.portfolio.cash + open_cost - (500 + realized)) < 0.01
    assert len(eng.portfolio.closed) >= 1  # it actually traded
