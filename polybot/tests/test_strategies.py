import time

from polybot.models import Market, Snapshot
from polybot.strategies import (MeanReversion, Momentum, SentimentShift,
                                SpreadScalp, VolumeSpike, WhaleFollow,
                                build_enabled)

MKT = Market(condition_id="c1", question="Test?", category="crypto",
             yes_token="y", no_token="n", volume_24h=100000)


def snaps(mids, vol=100000, imb=0.0, spread=0.02):
    return [Snapshot(ts=time.time() + i, mid=m, bid=m - spread / 2,
                     ask=m + spread / 2, volume_24h=vol, imbalance=imb)
            for i, m in enumerate(mids)]


def test_momentum_buy_on_steady_rise():
    s = Momentum({"lookback": 6, "min_move": 0.03})
    hist = snaps([0.50, 0.51, 0.52, 0.53, 0.54, 0.55])
    sig = s.evaluate(MKT, hist, [])
    assert sig and sig.side == "BUY"


def test_momentum_ignores_small_move():
    s = Momentum({"lookback": 6, "min_move": 0.03})
    assert s.evaluate(MKT, snaps([0.50] * 6), []) is None


def test_mean_reversion_fades_extension():
    s = MeanReversion({"lookback": 20, "zscore": 2.0})
    hist = snaps([0.50] * 19 + [0.60])
    sig = s.evaluate(MKT, hist, [])
    assert sig and sig.side == "SELL"


def test_volume_spike_follows_drift():
    s = VolumeSpike({"lookback": 10, "spike_ratio": 3.0})
    mids, vols = [], []
    v = 100000
    for i in range(10):
        v += 500 if i < 9 else 50000   # spike on the last delta
        vols.append(v)
        mids.append(0.50 + i * 0.002)  # upward drift
    hist = [Snapshot(ts=i, mid=m, bid=m - 0.01, ask=m + 0.01, volume_24h=vv)
            for i, (m, vv) in enumerate(zip(mids, vols))]
    sig = s.evaluate(MKT, hist, [])
    assert sig and sig.side == "BUY"


def test_spread_scalp_needs_wide_spread():
    s = SpreadScalp({"min_spread": 0.04, "min_volume_24h": 1000})
    assert s.evaluate(MKT, snaps([0.5], spread=0.02, imb=0.5), []) is None
    sig = s.evaluate(MKT, snaps([0.5], spread=0.06, imb=0.5), [])
    assert sig and sig.side == "BUY"


def test_whale_follow_mirrors_and_dedupes():
    s = WhaleFollow({"min_trade_usd": 5000})
    trade = {"transactionHash": "0x1", "size": 20000, "price": 0.5,
             "side": "BUY", "outcome": "Yes"}
    sig = s.evaluate(MKT, snaps([0.5]), [trade])
    assert sig and sig.side == "BUY"
    assert s.evaluate(MKT, snaps([0.5]), [trade]) is None  # seen already


def test_whale_follow_normalizes_no_side():
    s = WhaleFollow({"min_trade_usd": 5000})
    trade = {"transactionHash": "0x2", "size": 20000, "price": 0.5,
             "side": "BUY", "outcome": "No"}
    sig = s.evaluate(MKT, snaps([0.5]), [trade])
    assert sig and sig.side == "SELL"


def test_sentiment_shift():
    s = SentimentShift({"lookback": 10, "imbalance_delta": 0.3})
    hist = snaps([0.5] * 7, imb=0.0) + snaps([0.5] * 3, imb=0.5)
    sig = s.evaluate(MKT, hist, [])
    assert sig and sig.side == "BUY"


def test_build_enabled_respects_flags():
    strats = build_enabled({"momentum": {"enabled": True},
                            "mean_reversion": {"enabled": False}})
    assert [s.name for s in strats] == ["momentum"]
