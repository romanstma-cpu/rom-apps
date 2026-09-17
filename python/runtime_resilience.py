"""Small, dependency-free production resilience primitives for ROM PolyBot.

The desktop backend has one event loop, so a burst of slow market-data reads
must not consume the capacity reserved for account and order operations.  This
module also owns correlation context and the dependency observations used by
the deep readiness report.
"""
from __future__ import annotations

import asyncio
import contextvars
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, TypeVar


T = TypeVar("T")
_trace_id: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="-")
_span_id: contextvars.ContextVar[str] = contextvars.ContextVar("span_id", default="-")


def new_trace_id(prefix: str = "op") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:16]}"


def trace_fields() -> tuple[str, str]:
    return _trace_id.get(), _span_id.get()


@contextmanager
def trace_scope(trace_id: str | None = None, span: str | None = None):
    trace_token = _trace_id.set(trace_id or new_trace_id())
    span_token = _span_id.set(span or uuid.uuid4().hex[:8])
    try:
        yield _trace_id.get()
    finally:
        _span_id.reset(span_token)
        _trace_id.reset(trace_token)


@dataclass
class DependencyObservation:
    last_success_at: float | None = None
    last_failure_at: float | None = None
    last_error: str = ""
    successes: int = 0
    failures: int = 0

    def success(self) -> None:
        self.last_success_at = time.time()
        self.successes += 1
        self.last_error = ""

    def failure(self, error: object) -> None:
        self.last_failure_at = time.time()
        self.failures += 1
        self.last_error = " ".join(str(error).split())[:180]

    def snapshot(self) -> dict[str, Any]:
        return {
            "lastSuccessAt": self.last_success_at,
            "lastFailureAt": self.last_failure_at,
            "lastError": self.last_error,
            "successes": self.successes,
            "failures": self.failures,
        }


@dataclass
class AsyncBulkhead:
    name: str
    capacity: int
    queue_timeout: float
    operation_timeout: float
    _semaphore: asyncio.Semaphore | None = field(default=None, init=False, repr=False)
    _loop: asyncio.AbstractEventLoop | None = field(default=None, init=False, repr=False)
    active: int = 0
    rejected: int = 0
    completed: int = 0
    timed_out: int = 0

    def _get_semaphore(self) -> asyncio.Semaphore:
        loop = asyncio.get_running_loop()
        if self._semaphore is None or self._loop is not loop:
            self._loop = loop
            self._semaphore = asyncio.Semaphore(self.capacity)
            self.active = 0
        return self._semaphore

    async def run(self, operation: Callable[[], Awaitable[T]]) -> T:
        semaphore = self._get_semaphore()
        try:
            await asyncio.wait_for(semaphore.acquire(), timeout=self.queue_timeout)
        except TimeoutError:
            self.rejected += 1
            raise RuntimeError(f"{self.name} is busy; request rejected before execution")
        self.active += 1
        try:
            try:
                result = await asyncio.wait_for(operation(), timeout=self.operation_timeout)
            except TimeoutError:
                self.timed_out += 1
                raise
            self.completed += 1
            return result
        finally:
            self.active -= 1
            semaphore.release()

    def snapshot(self) -> dict[str, int | float | str]:
        return {
            "name": self.name,
            "capacity": self.capacity,
            "active": self.active,
            "available": max(0, self.capacity - self.active),
            "rejected": self.rejected,
            "completed": self.completed,
            "timedOut": self.timed_out,
            "queueTimeoutSeconds": self.queue_timeout,
            "operationTimeoutSeconds": self.operation_timeout,
        }


# Private/account/order work retains its own slots even when public discovery
# traffic is slow.  The limits sit below httpx's connection ceiling.
execution_bulkhead = AsyncBulkhead("polymarket_execution", 4, 1.0, 22.0)
market_data_bulkhead = AsyncBulkhead("polymarket_market_data", 8, 2.0, 22.0)
dependency_health = {
    "polymarketExecution": DependencyObservation(),
    "polymarketMarketData": DependencyObservation(),
}


def resilience_snapshot() -> dict[str, Any]:
    return {
        "bulkheads": {
            "execution": execution_bulkhead.snapshot(),
            "marketData": market_data_bulkhead.snapshot(),
        },
        "dependencies": {name: item.snapshot() for name, item in dependency_health.items()},
    }
