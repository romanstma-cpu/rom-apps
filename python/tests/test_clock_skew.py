"""Host clock vs exchange clock.

`auth.l2_headers` signs the local wall clock into every private request, so a
drifted desktop has its requests rejected as expired and the operator sees a
bare 401 that points at their credentials instead of their clock. Every
response already carries the server's time, so the offset is measured for free
and named wherever it can be mistaken for something else.
"""
from __future__ import annotations

import asyncio
import time
from email.utils import format_datetime
from datetime import datetime, timedelta, timezone

import httpx
import pytest

import polymarket_api as api


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.setattr(api, "MIN_REQUEST_INTERVAL", 0.0)
    api._pacing_reset()
    api._clock_skew = None
    api._clock_skew_at = 0.0
    yield
    api._pacing_reset()
    api._clock_skew = None
    api._clock_skew_at = 0.0


def _date(offset_seconds):
    """An HTTP Date header for a server clock `offset_seconds` from ours."""
    when = datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)
    return format_datetime(when, usegmt=True)


def call(status=200, headers=None, path="/v1/markets", **kw):
    seen = {}

    async def go():
        def handle(request):
            return httpx.Response(status, headers=headers or {}, json={})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as c:
            api._client = c
            try:
                await api._request("GET", path, **kw)
            except api.PolymarketAPIError as e:
                seen["error"] = e
            finally:
                api._client = None

    asyncio.run(go())
    return seen


# --- measurement -----------------------------------------------------------

def test_skew_is_measured_from_the_response_date():
    call(headers={"Date": _date(-30)})  # server is 30s behind us -> we are ahead
    assert api.clock_skew_seconds() == pytest.approx(30, abs=2)


def test_a_host_behind_the_exchange_reads_negative():
    call(headers={"Date": _date(+30)})
    assert api.clock_skew_seconds() == pytest.approx(-30, abs=2)


def test_no_date_header_leaves_the_skew_unmeasured():
    call(headers={})
    assert api.clock_skew_seconds() is None


def test_an_unparseable_date_is_ignored_rather_than_raising():
    call(headers={"Date": "not a date"})
    assert api.clock_skew_seconds() is None


def test_a_stale_measurement_reports_unknown_not_last_seen():
    call(headers={"Date": _date(-30)})
    api._clock_skew_at = time.monotonic() - 10_000
    assert api.clock_skew_seconds() is None
    # And "unknown" must never be reported as a problem.
    assert api.clock_skew_problem() == (False, "")


# --- the verdict -----------------------------------------------------------

def test_a_small_offset_is_not_a_problem():
    call(headers={"Date": _date(-1)})
    assert api.clock_skew_problem()[0] is False


def test_a_large_offset_is_a_problem_and_says_which_way():
    call(headers={"Date": _date(-120)})
    bad, why = api.clock_skew_problem()
    assert bad is True
    assert "ahead of" in why and "time sync" in why


def test_unmeasured_skew_is_never_reported_as_bad():
    assert api.clock_skew_problem() == (False, "")


# --- the opaque 401 this exists to fix ------------------------------------

def test_a_401_names_the_clock_when_it_is_the_likely_cause():
    call(headers={"Date": _date(-120)})  # establish the skew
    seen = call(status=401, headers={"Date": _date(-120)},
                path="/v1/account/balances")
    assert "clock" in seen["error"].body.lower()


def test_a_401_on_a_healthy_clock_is_left_alone():
    seen = call(status=401, headers={"Date": _date(0)},
                path="/v1/account/balances")
    assert "clock" not in seen["error"].body.lower()


def test_a_422_is_not_blamed_on_the_clock():
    """Only auth rejections get the hint; a field error means what it says."""
    call(headers={"Date": _date(-120)})
    seen = call(status=422, headers={"Date": _date(-120)})
    assert "clock" not in seen["error"].body.lower()
