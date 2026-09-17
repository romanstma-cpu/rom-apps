from __future__ import annotations

import asyncio

import pytest

import runtime_resilience as rr


def test_trace_scope_is_correlated_and_restores_parent():
    before = rr.trace_fields()
    with rr.trace_scope("trace-test", "span-test"):
        assert rr.trace_fields() == ("trace-test", "span-test")
    assert rr.trace_fields() == before


def test_execution_lane_remains_available_when_market_lane_is_saturated():
    async def run():
        market = rr.AsyncBulkhead("market", 1, 0.01, 1.0)
        execution = rr.AsyncBulkhead("execution", 1, 0.05, 1.0)
        release = asyncio.Event()

        async def held():
            await release.wait()
            return "released"

        holder = asyncio.create_task(market.run(held))
        await asyncio.sleep(0)
        assert await execution.run(lambda: asyncio.sleep(0, result="order")) == "order"
        with pytest.raises(RuntimeError, match="busy"):
            await market.run(lambda: asyncio.sleep(0))
        release.set()
        await holder
        assert market.rejected == 1

    asyncio.run(run())


def test_operation_timeout_releases_capacity():
    async def run():
        lane = rr.AsyncBulkhead("test", 1, 0.05, 0.01)
        with pytest.raises(TimeoutError):
            await lane.run(lambda: asyncio.sleep(1))
        assert lane.active == 0
        assert lane.snapshot()["available"] == 1
        assert lane.timed_out == 1

    asyncio.run(run())


def test_dependency_observation_marks_recovery():
    observation = rr.DependencyObservation()
    observation.failure("503 unavailable")
    failed = observation.snapshot()
    assert failed["failures"] == 1
    assert "503" in failed["lastError"]
    observation.success()
    recovered = observation.snapshot()
    assert recovered["successes"] == 1
    assert recovered["lastError"] == ""
