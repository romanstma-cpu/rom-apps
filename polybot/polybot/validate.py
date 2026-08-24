"""Config validation — catch mistakes at startup with a plain-English message
instead of a traceback (or, worse, silently trading with a typo'd setting)."""
from __future__ import annotations

from .strategies import REGISTRY

NUMERIC_RISK = {
    "stake_usd", "max_position_usd", "max_open_positions", "max_per_category",
    "daily_loss_stop_usd", "take_profit_pct", "stop_loss_pct", "max_hold_hours",
    "reentry_cooldown_minutes",
}
POSITIVE_RISK = {"stake_usd", "max_position_usd", "max_open_positions"}
FRACTION_RISK = {"take_profit_pct", "stop_loss_pct"}


class ConfigError(ValueError):
    """Raised with a message meant to be read by a person, not a debugger."""


def _check_risk(risk: dict, where: str, problems: list[str]) -> None:
    if not isinstance(risk, dict):
        problems.append(f"{where}: 'risk' must be a block of settings")
        return
    for key, val in risk.items():
        if key == "allow_pyramiding":
            if not isinstance(val, bool):
                problems.append(f"{where}: risk.allow_pyramiding must be "
                                f"true or false, got {val!r}")
            continue
        if key not in NUMERIC_RISK:
            problems.append(f"{where}: unknown risk setting {key!r} "
                            f"(known: {', '.join(sorted(NUMERIC_RISK))})")
            continue
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            problems.append(f"{where}: risk.{key} must be a number, got {val!r}")
            continue
        if key in POSITIVE_RISK and val <= 0:
            problems.append(f"{where}: risk.{key} must be greater than 0")
        if key in FRACTION_RISK and not 0 < val < 1:
            problems.append(f"{where}: risk.{key} is a fraction — 0.20 means "
                            f"20% (got {val!r})")


def _check_strategies(strategies: dict, where: str, problems: list[str]) -> None:
    if not isinstance(strategies, dict):
        problems.append(f"{where}: 'strategies' must be a block of settings")
        return
    for name, params in strategies.items():
        if name not in REGISTRY:
            problems.append(f"{where}: unknown strategy {name!r} "
                            f"(available: {', '.join(sorted(REGISTRY))})")
            continue
        if not isinstance(params, dict):
            problems.append(f"{where}: strategy {name!r} must be a block of "
                            f"settings, got {params!r}")
            continue
        conf = params.get("confidence")
        if conf is not None and not (isinstance(conf, (int, float))
                                     and 0 < conf <= 1):
            problems.append(f"{where}: {name}.confidence must be between "
                            f"0 and 1 (got {conf!r})")


def validate(cfg) -> None:
    """Raise ConfigError listing everything wrong with the config at once."""
    data = cfg.data if hasattr(cfg, "data") else cfg
    problems: list[str] = []

    mode = data.get("mode", "paper")
    if mode not in ("paper", "live"):
        problems.append(f"mode must be 'paper' or 'live', got {mode!r}")

    poll = data.get("poll_seconds", 15)
    if not isinstance(poll, (int, float)) or poll < 1:
        problems.append(f"poll_seconds must be at least 1, got {poll!r}")

    markets = data.get("markets") or {}
    if not isinstance(markets, dict):
        problems.append("'markets' must be a block of settings")
        markets = {}
    cats = markets.get("categories")
    if cats is not None and (not isinstance(cats, list)
                             or not all(isinstance(c, str) for c in cats)):
        problems.append("markets.categories must be a list of category slugs, "
                        "e.g. [politics, crypto, sports]")
    elif isinstance(cats, list) and not cats:
        problems.append("markets.categories is empty — the bot would watch "
                        "nothing")
    lo = markets.get("min_price", 0.05)
    hi = markets.get("max_price", 0.95)
    if isinstance(lo, (int, float)) and isinstance(hi, (int, float)):
        if not 0 <= lo < hi <= 1:
            problems.append(f"markets.min_price/max_price must satisfy "
                            f"0 <= min < max <= 1 (got {lo!r} and {hi!r})")

    _check_risk(data.get("risk") or {}, "risk", problems)
    _check_strategies(data.get("strategies") or {}, "strategies", problems)

    overrides = data.get("category_overrides") or {}
    if isinstance(overrides, dict):
        for cat, over in overrides.items():
            if not isinstance(over, dict):
                problems.append(f"category_overrides.{cat} must be a block")
                continue
            _check_risk(over.get("risk") or {}, f"category_overrides.{cat}",
                        problems)
            _check_strategies(over.get("strategies") or {},
                              f"category_overrides.{cat}", problems)

    enabled = [n for n, p in (data.get("strategies") or {}).items()
               if isinstance(p, dict) and p.get("enabled")]
    if not enabled:
        # manual mode is legitimate — say so rather than failing
        problems.append("__note__no strategies are enabled: the bot will only "
                        "manage exits for positions you already hold "
                        "(manual mode)")

    hard = [p for p in problems if not p.startswith("__note__")]
    if hard:
        raise ConfigError(
            "Problems in your config file:\n  - " + "\n  - ".join(hard))
    return [p.replace("__note__", "") for p in problems]
