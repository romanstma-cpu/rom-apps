"""Conservative execution checks, not a calibrated probability model."""
from __future__ import annotations

import math
from datetime import datetime, timezone


def signal_freshness_problem(signal: dict, max_age_sec: float, now: float) -> str | None:
    """Check persisted signal time again at execution, including after network waits."""
    try:
        stamp = datetime.fromisoformat(str(signal.get('created_at') or '').replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        age = now - stamp.timestamp()
        if not math.isfinite(max_age_sec) or max_age_sec <= 0:
            return 'invalid signal age limit'
        if age < -5:
            return 'signal timestamp is in the future'
        if age > max_age_sec:
            return 'signal expired before execution'
    except (ValueError, TypeError, OverflowError):
        return 'signal timestamp unavailable or invalid'
    return None


def signal_problem(signal: dict, source: str) -> str | None:
    """Validate inputs before ranking, rule evaluation or order sizing."""
    if source not in {"whale", "momentum", "convergence"}:
        return "unsupported signal source"
    for key, low, high in (("price", 0, 1), ("confidence", 0, 100)):
        value = signal.get(key)
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return f"invalid signal {key}"
        if isinstance(value, bool) or not math.isfinite(number):
            return f"invalid signal {key}"
        if not low <= number <= high or (key == "price" and number in (0, 1)):
            return f"invalid signal {key}"
    side = signal.get("taker_side" if source == "whale" else "direction") or "yes"
    if not isinstance(side, str) or side.lower() not in {"yes", "no"}:
        return "invalid signal direction"
    return None


def entry_price(quote: dict, signal_cents: int, cfg: dict) -> int:
    """Never invent executable liquidity when a quote is absent or crossed."""
    bid, ask = quote.get("bid_cents"), quote.get("ask_cents")
    if any(isinstance(p, bool) or not isinstance(p, (int, float)) or
           not math.isfinite(p) or not 0 < p < 100 for p in (bid, ask)):
        raise ValueError("A valid two-sided market is required")
    if bid > ask:
        raise ValueError("Market quote is crossed")
    if ask - bid > 3:
        raise ValueError("Spread exceeds the 3-cent execution limit")
    if ask - signal_cents > 2:
        raise ValueError("Market moved more than 2 cents above the signal")
    style = cfg.get("order_style")
    if style == "maker_join":
        if bid >= ask:
            raise ValueError("Maker route requires a positive spread")
        # Improve the bid by one tick when the spread permits it, while always
        # remaining at least one cent below the current offer.
        return min(math.ceil(bid + 1), math.floor(ask - 1))
    if style == "limit_mid":
        return math.floor((bid + ask) / 2)
    # Even the legacy market style now uses a bounded price, never a 99c sweep.
    return math.ceil(ask)


def remaining_signal_margin(raw_margin: float, signal_cents: int, entry_cents: int) -> float:
    """Charge adverse movement and a 1c uncertainty buffer; never reward a cheaper quote.

    The buffer is a selection haircut, not an estimate of exchange fees.
    This heuristic score must not be described as expected profit or win probability.
    """
    return raw_margin - max(0, entry_cents - signal_cents) - 1.0


def entry_vwap_cents(levels, contracts: int, limit_cents: int) -> float:
    """Average cost per contract to buy ``contracts`` at or under ``limit_cents``.

    Only displayed size at an acceptable price counts. Raises when the book
    cannot fill the order, so a caller can shrink or skip rather than assume
    the touch price applies to the whole quantity.
    """
    if contracts <= 0:
        raise ValueError("Order size must be positive")
    remaining = contracts
    cost = 0.0
    for level in levels or []:
        try:
            price, size = int(level[0]), float(level[1])
        except (TypeError, ValueError, IndexError):
            raise ValueError("Invalid book level")
        if not math.isfinite(size) or size <= 0 or not 0 < price < 100:
            continue
        if price > limit_cents:
            break
        take = min(remaining, math.floor(size))
        if take <= 0:
            continue
        cost += take * price
        remaining -= take
        if remaining <= 0:
            return cost / contracts
    raise ValueError(
        f"Displayed depth fills only {contracts - remaining} of {contracts} "
        f"contracts at or under {limit_cents}c"
    )


def affordable_at_depth(levels, limit_cents: int) -> int:
    """Contracts displayed at or under ``limit_cents``. Never a guarantee of a fill."""
    total = 0
    for level in levels or []:
        try:
            price, size = int(level[0]), float(level[1])
        except (TypeError, ValueError, IndexError):
            continue
        if not math.isfinite(size) or size <= 0 or not 0 < price < 100:
            continue
        if price > limit_cents:
            break
        total += math.floor(size)
    return total


def market_quality_multiplier(
    quote: dict, *, signal_cents: int, limit_cents: int, contracts: int,
    fee_cents: float, maker_only: bool,
) -> tuple[float, str]:
    """Return a conservative sizing adjustment from observable execution quality.

    This is an execution-fit score, never a probability or profitability
    estimate. It only reduces a qualifying live entry; quote validation,
    depth checks, fees and all account-risk ceilings stay authoritative.
    """
    if contracts <= 0:
        return 1.0, "no contracts requested"
    try:
        bid = float(quote.get("bid_cents"))
        ask = float(quote.get("ask_cents"))
        fee = max(0.0, float(fee_cents))
    except (TypeError, ValueError, OverflowError):
        return 1.0, "quote quality unavailable"
    if not all(math.isfinite(value) for value in (bid, ask, fee)) or ask < bid:
        return 1.0, "quote quality unavailable"

    spread = max(0.0, ask - bid)
    movement = max(0, int(limit_cents) - int(signal_cents))
    # Every input is bounded by the existing execution checks. A clean book
    # stays at full size; marginal but still permitted books lose capital.
    spread_factor = 1.0 if spread <= 1 else 0.90 if spread <= 2 else 0.78
    movement_factor = 1.0 if movement == 0 else 0.92 if movement == 1 else 0.84
    fee_factor = max(0.85, 1.0 - min(fee, 3.0) / 20.0)
    depth_factor = 1.0
    if not maker_only:
        available = affordable_at_depth(quote.get("ask_levels") or [], limit_cents)
        ratio = min(1.0, max(0.0, available / contracts))
        depth_factor = 0.65 + 0.35 * ratio
    multiplier = max(0.50, min(1.0, spread_factor * movement_factor * fee_factor * depth_factor))
    return round(multiplier, 2), (
        f"spread {spread:.0f}c, move {movement}c, displayed depth "
        f"{'maker route' if maker_only else f'{available}/{contracts}'}, fee {fee:.2f}c"
    )
