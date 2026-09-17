"""Fast, offline capacity gate for the single-user desktop backend.

Expected peak is eight concurrent market operations plus one execution action.
This probe drives three times that market peak while continuously checking the
isolated execution lane.  It contacts no exchange and changes no user data.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time

from runtime_resilience import AsyncBulkhead


EXPECTED_MARKET_CONCURRENCY = 8
STRESS_MULTIPLIER = 3
EXECUTION_P95_SLO_MS = 100.0


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int((len(ordered) - 1) * fraction)))
    return ordered[index]


async def probe(rounds: int = 40) -> dict:
    market = AsyncBulkhead("capacity_market", EXPECTED_MARKET_CONCURRENCY, 1.0, 1.0)
    execution = AsyncBulkhead("capacity_execution", 4, 0.1, 1.0)
    market_latencies: list[float] = []
    execution_latencies: list[float] = []

    async def measured(lane: AsyncBulkhead, delay: float, sink: list[float]):
        started = time.perf_counter()
        await lane.run(lambda: asyncio.sleep(delay))
        sink.append((time.perf_counter() - started) * 1000)

    started = time.perf_counter()
    for _ in range(rounds):
        market_tasks = [
            asyncio.create_task(measured(market, 0.002, market_latencies))
            for _ in range(EXPECTED_MARKET_CONCURRENCY * STRESS_MULTIPLIER)
        ]
        execution_tasks = [
            asyncio.create_task(measured(execution, 0.001, execution_latencies))
            for _ in range(2)
        ]
        await asyncio.gather(*market_tasks, *execution_tasks)
    duration = time.perf_counter() - started
    execution_p95 = percentile(execution_latencies, 0.95)
    passed = (
        market.rejected == 0
        and market.timed_out == 0
        and execution.rejected == 0
        and execution.timed_out == 0
        and execution_p95 <= EXECUTION_P95_SLO_MS
    )
    return {
        "status": "pass" if passed else "fail",
        "expectedPeakMarketConcurrency": EXPECTED_MARKET_CONCURRENCY,
        "testedMarketConcurrency": EXPECTED_MARKET_CONCURRENCY * STRESS_MULTIPLIER,
        "stressMultiplier": STRESS_MULTIPLIER,
        "operations": len(market_latencies) + len(execution_latencies),
        "durationSeconds": round(duration, 3),
        "throughputOpsPerSecond": round((len(market_latencies) + len(execution_latencies)) / duration, 1),
        "marketP95Ms": round(percentile(market_latencies, 0.95), 2),
        "executionP50Ms": round(statistics.median(execution_latencies), 2),
        "executionP95Ms": round(execution_p95, 2),
        "executionP95SloMs": EXECUTION_P95_SLO_MS,
        "marketBulkhead": market.snapshot(),
        "executionBulkhead": execution.snapshot(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", type=int, default=40)
    args = parser.parse_args()
    report = asyncio.run(probe(max(1, args.rounds)))
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
