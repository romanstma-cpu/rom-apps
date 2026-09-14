"""Fail-closed execution health for new main-strategy entries.

This is intentionally separate from the order journal. The journal protects
an uncertain order after submission; this breaker prevents the next new entry
after a short run of quote or exchange failures. It never cancels or sells an
existing position.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import time
from typing import Callable


FAILURE_WINDOW_SECONDS = 60.0
FAILURE_LIMIT = 3
COOLDOWN_SECONDS = 60.0


@dataclass
class ExecutionCircuit:
    """A closed/open/half-open circuit breaker for entry attempts."""

    clock: Callable[[], float] = time.monotonic
    failures: deque[tuple[float, str, str]] = field(default_factory=deque)
    opened_at: float | None = None
    last_reason: str = ""
    probe_in_flight: bool = False

    def _now(self) -> float:
        return float(self.clock())

    def _prune(self, now: float) -> None:
        while self.failures and now - self.failures[0][0] > FAILURE_WINDOW_SECONDS:
            self.failures.popleft()

    def state(self) -> str:
        now = self._now()
        self._prune(now)
        if self.opened_at is None:
            return "closed"
        if now - self.opened_at < COOLDOWN_SECONDS:
            return "open"
        return "half_open"

    def blocked_reason(self) -> str | None:
        if self.state() != "open":
            return None
        remaining = max(1, int(COOLDOWN_SECONDS - (self._now() - float(self.opened_at))))
        return f"Execution safety pause: retrying in about {remaining}s after {self.last_reason}"

    def begin_attempt(self) -> bool:
        """Reserve the one recovery probe after the cooldown expires."""
        state = self.state()
        if state == "closed":
            return True
        if state == "open" or self.probe_in_flight:
            return False
        self.probe_in_flight = True
        return True

    def record_failure(self, kind: str, reason: object) -> None:
        now = self._now()
        self._prune(now)
        label = "quote" if kind == "quote" else "order"
        detail = " ".join(str(reason or "unavailable").split())[:140]
        self.failures.append((now, label, detail))
        self.last_reason = f"{label} unavailable"
        self.probe_in_flight = False
        if len(self.failures) >= FAILURE_LIMIT:
            self.opened_at = now

    def record_quote_success(self) -> None:
        """A successful quote clears quote-only failures, but not failed orders."""
        self._prune(self._now())
        self.failures = deque(item for item in self.failures if item[1] != "quote")
        if not self.failures and self.state() == "closed":
            self.last_reason = ""

    def record_order_success(self) -> None:
        self.failures.clear()
        self.opened_at = None
        self.last_reason = ""
        self.probe_in_flight = False

    def snapshot(self) -> dict:
        now = self._now()
        self._prune(now)
        state = self.state()
        return {
            "state": state,
            "blocked": state == "open",
            "reason": self.blocked_reason() or ("Testing one recovery quote before new entries" if state == "half_open" else ""),
            "retryAfterSeconds": max(0, int(COOLDOWN_SECONDS - (now - float(self.opened_at)))) if state == "open" else 0,
            "failureCount": len(self.failures),
            "quoteFailures": sum(1 for _, kind, _ in self.failures if kind == "quote"),
            "orderFailures": sum(1 for _, kind, _ in self.failures if kind == "order"),
        }

    def reset(self) -> None:
        self.failures.clear()
        self.opened_at = None
        self.last_reason = ""
        self.probe_in_flight = False


circuit = ExecutionCircuit()


def status() -> dict:
    """Desktop status payload, including non-blocking WebSocket context."""
    payload = circuit.snapshot()
    try:
        import us_market_stream
        payload["marketStream"] = us_market_stream.health()
    except Exception:
        payload["marketStream"] = {"state": "unknown", "connected": False}
    return payload
