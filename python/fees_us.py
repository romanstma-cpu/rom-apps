"""US schedules only; reported exchange fees remain authoritative for live fills.

Source: https://docs.polymarket.us/fees (checked 2026-09-09).
April schedule was published at that same URL before the July update.
No promotional or volume-tier rebates are assumed.
"""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_EVEN, ROUND_CEILING

SCHEDULES = (
    (datetime(2026,4,3,19,tzinfo=timezone.utc).timestamp(), Decimal('0.05')),
    (datetime(2026,7,1,4,tzinfo=timezone.utc).timestamp(), Decimal('0.06')),
)


def coefficient(at):
    for start, value in reversed(SCHEDULES):
        if at >= start:
            return value
    raise ValueError('No verified US fee schedule for this historical timestamp')


EARLIEST_START, EARLIEST_COEFFICIENT = SCHEDULES[0]


def coefficient_at_or_earliest(at):
    """Coefficient in force at `at`, falling back to the earliest schedule.

    Backtests run over signals recorded before the first published US
    schedule. Pricing those at the earliest known rate is a stated
    approximation; `coefficient` refuses to invent one, and live trading must
    keep using that stricter form.
    """
    try:
        return coefficient(at)
    except ValueError:
        return EARLIEST_COEFFICIENT


def predates_published_schedule(at):
    """True when `at` falls before any published US schedule."""
    return at < EARLIEST_START


def fee(quantity, price, at, *, maker=False):
    q, p = Decimal(str(quantity)), Decimal(str(price))
    if not q.is_finite() or not p.is_finite() or q < 0 or not 0 <= p <= 1:
        raise ValueError('Invalid fee quantity or price')
    theta = coefficient(at)
    if maker:
        theta = Decimal('-0.0125')
    return float((theta*q*p*(1-p)).quantize(Decimal('.01'), rounding=ROUND_HALF_EVEN))


def reserved_cost(quantity, price, at):
    # Round each potential one-contract fill UP. This reserves enough even when
    # an order fragments into many separately rounded executions.
    p = Decimal(str(price))
    unit_fee = (coefficient(at)*p*(1-p)).quantize(Decimal('.01'),rounding=ROUND_CEILING)
    return float(Decimal(str(quantity))*(p+unit_fee))


def affordable_contracts(budget, price, at):
    unit = Decimal(str(reserved_cost(1,price,at)))
    return max(0,int(Decimal(str(max(0,budget))) // unit)) if unit > 0 else 0
