"""Offline, bounded failure drills.  No production endpoint is contacted."""
from __future__ import annotations

import asyncio

import httpx
import pytest

import polymarket_api
from execution_health import COOLDOWN_SECONDS, ExecutionCircuit


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_dependency_timeout_fails_closed_without_retrying_an_order(monkeypatch):
    calls = 0

    async def handler(_request):
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("injected stalled exchange")

    async def run():
        old = polymarket_api._client
        monkeypatch.setattr(polymarket_api.auth, "l2_headers", lambda *_args: {})
        polymarket_api._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            with pytest.raises(httpx.ReadTimeout):
                await polymarket_api._request("POST", "/v1/orders", private=True, body={})
        finally:
            await polymarket_api._client.aclose()
            polymarket_api._client = old

    asyncio.run(run())
    assert calls == 1


def test_repeated_exchange_failure_opens_then_recovers_through_one_probe():
    clock = Clock()
    circuit = ExecutionCircuit(clock=clock)
    for _ in range(3):
        circuit.record_failure("order", "injected 503")
    assert circuit.snapshot()["blocked"] is True
    clock.now += COOLDOWN_SECONDS + 0.01
    assert circuit.begin_attempt() is True
    assert circuit.begin_attempt() is False
    circuit.record_order_success()
    assert circuit.snapshot()["state"] == "closed"


def test_market_data_saturation_does_not_consume_execution_permit():
    async def run():
        from runtime_resilience import AsyncBulkhead
        market = AsyncBulkhead("market", 1, 0.01, 1)
        execution = AsyncBulkhead("execution", 1, 0.01, 1)
        release = asyncio.Event()
        task = asyncio.create_task(market.run(lambda: release.wait()))
        await asyncio.sleep(0)
        assert await execution.run(lambda: asyncio.sleep(0, result=True)) is True
        release.set()
        await task

    asyncio.run(run())
