from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

_SCRATCH = tempfile.mkdtemp(prefix="rom-test-")
os.environ.setdefault("ROM_POLYBOT_USERDATA", _SCRATCH)

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _hermetic_market_meta(monkeypatch):
    try:
        import trader

        async def _no_meta(_ticker):
            return None

        monkeypatch.setattr(trader, "get_market_meta", _no_meta, raising=False)
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _hermetic_quote(request, monkeypatch):
    if getattr(request.module, "__name__", "").endswith(("test_polymarket_api", "test_us_polymarket_api")):
        return
    try:
        import polymarket_api

        async def _no_quote(_ticker, _side):
            return {"bid_cents": None, "ask_cents": None,
                    "ask_levels": [], "bid_levels": []}

        monkeypatch.setattr(polymarket_api, "get_quote", _no_quote, raising=False)
    except Exception:
        pass


def quote_with_depth(quote: dict, *, size: float = 10_000.0) -> dict:
    """Fill in book depth for a test quote that only names best prices.

    A real quote always reports the resting size behind its touch, so entry
    sizing can price the order. Tests that care about thin books state their
    own ``ask_levels``; this only backfills ample depth for the tests whose
    subject is something else.
    """
    out = dict(quote)
    ask, bid = out.get("ask_cents"), out.get("bid_cents")
    if "ask_levels" not in out:
        out["ask_levels"] = [[int(ask), size]] if isinstance(ask, int) else []
    if "bid_levels" not in out:
        out["bid_levels"] = [[int(bid), size]] if isinstance(bid, int) else []
    return out


@pytest.fixture(autouse=True)
def _hermetic_balance(request, monkeypatch):
    if getattr(request.module, "__name__", "").endswith(("test_polymarket_api", "test_us_polymarket_api")):
        return
    try:
        import polymarket_api
        import trader

        async def _no_balance():
            raise RuntimeError("hermetic test env: no balance endpoint")

        monkeypatch.setattr(polymarket_api, "get_balance", _no_balance, raising=False)
        monkeypatch.setattr(trader, "get_balance", _no_balance, raising=False)
        monkeypatch.setattr(trader, "_balance_cache", {}, raising=False)
    except Exception:
        pass


# --- US fee schedules ---------------------------------------------------
#
# `trader` reserves and charges fees at `time.time()`, so any test that
# asserts a dollar amount silently adopts whichever schedule happens to be
# current and breaks the next time one is added. Tests that assert money must
# name the schedule they mean; these anchors sit safely inside each window.

from datetime import datetime, timezone  # noqa: E402

US_FEE_APRIL = datetime(2026, 5, 1, 12, tzinfo=timezone.utc)   # 0.05 coefficient
US_FEE_JULY = datetime(2026, 8, 1, 12, tzinfo=timezone.utc)    # 0.06 coefficient


@pytest.fixture
def fee_clock(monkeypatch):
    """Pin trader's wall clock to a chosen US fee schedule.

    Returns a callable taking the instant to pin. Only `time.time` is
    replaced; `monotonic` and everything else forward to the real module so
    the quote-decision window still behaves normally.
    """
    import time as _time
    import trader

    class _PinnedClock:
        def __init__(self, epoch: float) -> None:
            self._epoch = epoch

        def time(self) -> float:
            return self._epoch

        def __getattr__(self, name):
            return getattr(_time, name)

    def pin(when: datetime) -> datetime:
        monkeypatch.setattr(trader, "time", _PinnedClock(when.timestamp()))
        return when

    return pin
