"""Client-side pacing, 429 handling and strictly opt-in retry.

The US gateway publishes no rate limit and returns 429 like any other 4xx, so
the adapter paces itself. The invariant these guard: a request that can change
state is never repeated, however it failed, while an idempotent read survives a
transient blip instead of killing the whole scan tick.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest

import polymarket_api as api


@pytest.fixture
def fast(monkeypatch):
    """Strip the real waits so retry behaviour is tested, not the clock."""
    monkeypatch.setattr(api, "MIN_REQUEST_INTERVAL", 0.0)
    monkeypatch.setattr(api, "RETRY_BASE_DELAY", 0.001)
    monkeypatch.setattr(api, "RETRY_MAX_DELAY", 0.002)
    api._pacing_reset()
    yield
    api._pacing_reset()


def run(handler, method, path, **kw):
    """Drive one _request against a mock transport; returns (result, calls)."""
    calls = []

    def handle(request):
        calls.append(request)
        return handler(len(calls), request)

    out = {}

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as c:
            api._client = c
            try:
                out["value"] = await api._request(method, path, **kw)
            except BaseException as e:  # noqa: BLE001 - recorded for assertions
                out["error"] = e
            finally:
                api._client = None

    asyncio.run(go())
    return out, calls


# --- the invariant: state-changing calls are never repeated ---------------

@pytest.mark.parametrize("failure", ["timeout", "server", "rate-limit"])
def test_order_submission_is_never_retried(fast, failure):
    def handler(n, _req):
        if failure == "timeout":
            raise httpx.ReadTimeout("simulated")
        return httpx.Response(503 if failure == "server" else 429)

    out, calls = run(handler, "POST", "/v1/orders", body={"x": 1})
    assert len(calls) == 1
    assert "error" in out


def test_cancel_is_never_retried(fast):
    out, calls = run(lambda n, r: httpx.Response(503), "POST", "/v1/order/abc/cancel")
    assert len(calls) == 1


def test_a_rate_limited_order_still_parks_every_other_caller(fast):
    """The submission must not retry, but the process must back off."""
    run(lambda n, r: httpx.Response(429, headers={"Retry-After": "7"}),
        "POST", "/v1/orders", body={"x": 1})
    assert api._cooldown_until > 0.0


# --- idempotent reads survive a transient blip ----------------------------

def test_read_retries_a_transport_failure_then_succeeds(fast):
    def handler(n, _req):
        if n == 1:
            raise httpx.ReadTimeout("simulated")
        return httpx.Response(200, json={"ok": True})

    out, calls = run(handler, "GET", "/v1/markets", retry=True)
    assert len(calls) == 2
    assert out["value"] == {"ok": True}


def test_read_retries_a_5xx_then_succeeds(fast):
    def handler(n, _req):
        return httpx.Response(503) if n == 1 else httpx.Response(200, json={"ok": 1})

    out, calls = run(handler, "GET", "/v1/markets", retry=True)
    assert len(calls) == 2
    assert out["value"] == {"ok": 1}


def test_read_gives_up_after_the_attempt_budget(fast):
    out, calls = run(lambda n, r: httpx.Response(503), "GET", "/v1/markets", retry=True)
    assert len(calls) == api.RETRY_ATTEMPTS
    assert isinstance(out["error"], api.PolymarketAPIError)
    assert out["error"].status == 503


def test_a_4xx_is_a_decision_not_a_blip_and_is_not_retried(fast):
    out, calls = run(lambda n, r: httpx.Response(422, text="bad price"),
                     "GET", "/v1/markets", retry=True)
    assert len(calls) == 1
    assert out["error"].status == 422
    assert "bad price" in out["error"].body


def test_read_without_opting_in_still_makes_one_request(fast):
    """Retry is opt-in: the default must behave exactly as before."""
    out, calls = run(lambda n, r: httpx.Response(503), "GET", "/v1/markets")
    assert len(calls) == 1


def test_exhausted_rate_limit_surfaces_as_429(fast):
    out, calls = run(lambda n, r: httpx.Response(429), "GET", "/v1/markets", retry=True)
    assert len(calls) == api.RETRY_ATTEMPTS
    assert out["error"].status == 429


def test_private_read_resigns_headers_on_every_attempt(fast, monkeypatch):
    """Signed headers carry a timestamp; a reused one can expire mid-retry."""
    stamps = []

    def l2(method, path, body=""):
        stamps.append(1)
        return {"X-PM-Timestamp": str(len(stamps))}

    monkeypatch.setattr(api.auth, "l2_headers", l2)

    def handler(n, _req):
        return httpx.Response(503) if n == 1 else httpx.Response(200, json={})

    _out, calls = run(handler, "GET", "/v1/account/balances", private=True, retry=True)
    assert len(calls) == 2
    assert calls[0].headers["X-PM-Timestamp"] != calls[1].headers["X-PM-Timestamp"]


# --- Retry-After parsing ---------------------------------------------------

def _resp(value=None):
    headers = {"Retry-After": value} if value is not None else {}
    return httpx.Response(429, headers=headers)


def test_retry_after_reads_plain_seconds():
    assert api._retry_after_seconds(_resp("3"), 99.0) == 3.0


def test_retry_after_is_clamped_so_a_loop_cannot_park_for_an_hour():
    assert api._retry_after_seconds(_resp("3600"), 1.0) == api.RETRY_AFTER_CAP


def test_retry_after_falls_back_when_absent_or_unparseable():
    assert api._retry_after_seconds(_resp(), 1.5) == 1.5
    assert api._retry_after_seconds(_resp("soon"), 1.5) == 1.5


def test_retry_after_accepts_an_http_date():
    out = api._retry_after_seconds(
        _resp("Wed, 21 Oct 2015 07:28:00 GMT"), 9.0)
    assert out == 0.0  # a date in the past means "now", not the fallback


# --- pacing ----------------------------------------------------------------

def test_pacing_spaces_consecutive_requests(monkeypatch):
    api._pacing_reset()
    monkeypatch.setattr(api, "MIN_REQUEST_INTERVAL", 0.05)

    async def go():
        loop = asyncio.get_event_loop()
        await api._pace()
        start = loop.time()
        await api._pace()
        return loop.time() - start

    elapsed = asyncio.run(go())
    api._pacing_reset()
    assert elapsed >= 0.04  # the second request waited out the interval
