"""Stage and check result shapes."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class Check:
    """One assertion a stage makes about the live account or feed."""
    name: str
    ok: bool
    detail: str = ''
    data: Optional[dict] = None
    # A check that could not run (no credentials, market closed, nothing to
    # observe) is neither a pass nor a failure; it must not be reported as
    # either, or the harness becomes a source of false confidence.
    skipped: bool = False

    @property
    def status(self) -> str:
        return 'SKIP' if self.skipped else ('PASS' if self.ok else 'FAIL')


@dataclass
class Stage:
    number: int
    name: str
    run: Callable
    # Every stage in 0-4 is read-only. The field exists so a later live stage
    # must declare itself, rather than inheriting read-only by omission.
    read_only: bool = True
    requires_auth: bool = True


@dataclass
class StageResult:
    stage: Stage
    checks: list = field(default_factory=list)
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None and all(c.ok or c.skipped for c in self.checks)
