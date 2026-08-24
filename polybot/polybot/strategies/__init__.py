from .base import Strategy
from .mean_reversion import MeanReversion
from .momentum import Momentum
from .sentiment_shift import SentimentShift
from .spread_scalp import SpreadScalp
from .trend_continuation import TrendContinuation
from .volume_spike import VolumeSpike
from .whale_follow import WhaleFollow

REGISTRY: dict[str, type[Strategy]] = {
    cls.name: cls for cls in (
        Momentum, MeanReversion, VolumeSpike, TrendContinuation,
        SpreadScalp, WhaleFollow, SentimentShift,
    )
}


def build_enabled(strategy_cfg: dict) -> list[Strategy]:
    """Instantiate every strategy enabled in config (manual mode = none)."""
    out: list[Strategy] = []
    for name, params in (strategy_cfg or {}).items():
        cls = REGISTRY.get(name)
        if cls and isinstance(params, dict) and params.get("enabled"):
            out.append(cls(params))
    return out
