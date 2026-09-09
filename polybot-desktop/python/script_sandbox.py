from __future__ import annotations

import ast
import hashlib
import math
import statistics
import sys
import time
from typing import Any, Callable, Optional

MAX_CODE_BYTES = 128 * 1024
HOOK_NAMES = ("decide", "decide_market", "manage", "decide_signal",
              "supervise", "on_start", "on_fill", "on_settle")
ENTRY_HOOKS = ("decide", "decide_market", "manage", "decide_signal",
               "supervise")

INJECTED_GLOBALS = ("math", "statistics", "state", "log", "ctx")


class ScriptError(Exception):
    pass


class ScriptBudgetExceeded(BaseException):
    pass


SCRIPT_FAILURES = (ScriptError, ScriptBudgetExceeded)


def parse_header(code: str) -> dict:
    meta = {"version": None, "name": "", "description": ""}
    for line in code.splitlines()[:15]:
        s = line.strip()
        if not s.startswith("#"):
            if s:
                break
            continue
        body = s.lstrip("#").strip()
        low = body.lower()
        if low.startswith("rom-script"):
            meta["version"] = body.split()[-1] if len(body.split()) > 1 else "v1"
        elif low.startswith("name:"):
            meta["name"] = body[5:].strip()
        elif low.startswith("description:"):
            meta["description"] = body[12:].strip()
    return meta


def find_ctx_fields(code: str) -> list[str]:
    fields: set[str] = set()
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Subscript)
                and isinstance(node.value, ast.Name) and node.value.id == "ctx"
                and isinstance(node.slice, ast.Constant)
                and isinstance(node.slice.value, str)):
            fields.add(node.slice.value)
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "ctx"
                and node.args and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)):
            fields.add(node.args[0].value)
    return sorted(fields)


def validate(code: str) -> list[str]:
    if len(code.encode("utf-8", "replace")) > MAX_CODE_BYTES:
        return [f"script exceeds {MAX_CODE_BYTES // 1024}KB"]
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [f"syntax error line {e.lineno}: {e.msg}"]
    defined = {n.name for n in tree.body
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    if not defined & set(ENTRY_HOOKS):
        return ["script must define at least one of: decide(ctx), "
                "decide_market(market), manage(position, ctx), "
                "decide_signal(signal), supervise(app)"]
    async_hooks = sorted(
        n.name for n in tree.body
        if isinstance(n, ast.AsyncFunctionDef) and n.name in HOOK_NAMES)
    if async_hooks:
        return [f"hook(s) {', '.join(async_hooks)} are 'async def' — the engine "
                "calls hooks synchronously, so an async hook would never run. "
                "Use a plain 'def'."]
    return []


class _Tracer:

    __slots__ = ("count", "deadline", "tripped", "why")

    def __init__(self, deadline: float) -> None:
        self.count = 0
        self.deadline = deadline
        self.tripped = False
        self.why = ""

    def __call__(self, frame, event, arg):  # noqa: ANN001 - trace signature
        self.count += 1
        if self.count % 64 == 0 and time.perf_counter() > self.deadline:
            self.tripped = True
            self.why = "script exceeded its per-call time budget"
            raise ScriptBudgetExceeded(self.why)
        return self


def call_budgeted(fn: Callable, *args: Any, budget_ms: float = 250.0,
                  traced: bool = False) -> Any:
    if not traced:
        return fn(*args)
    deadline = time.perf_counter() + budget_ms / 1000.0
    tracer = _Tracer(deadline)
    old = sys.gettrace()
    sys.settrace(tracer)
    lost = False
    try:
        out = fn(*args)
    finally:
        lost = sys.gettrace() is not tracer
        sys.settrace(old)
    if tracer.tripped:
        raise ScriptBudgetExceeded(tracer.why or "script exceeded its per-call budget")
    if lost:
        raise ScriptBudgetExceeded(
            "script disabled its own time budget (the trace function was lost "
            "mid-call — usually a swallowed budget error)"
        )
    return out


def code_hash(code: str) -> str:
    h = hashlib.sha256()
    h.update(code.encode("utf-8", "replace"))
    return h.hexdigest()


class CompiledScript:

    def __init__(self, script_id: str, code: str, *,
                 log_sink: Optional[Callable[[str], None]] = None,
                 state: Optional[dict] = None, traced: bool = False):
        self.script_id = script_id
        self.traced = bool(traced)
        self.hash = code_hash(code)
        self.state: dict = state if isinstance(state, dict) else {}
        self._log_lines: list[str] = []
        self._log_sink = log_sink
        self._log_count = 0

        errors = validate(code)
        if errors:
            raise ScriptError("; ".join(errors[:5]))

        def _log(*parts: Any) -> None:
            self._log_count += 1
            if self._log_count > 2000:
                return
            msg = " ".join(str(p) for p in parts)[:400]
            self._log_lines.append(msg)
            if len(self._log_lines) > 200:
                del self._log_lines[:100]
            if self._log_sink:
                try:
                    self._log_sink(msg)
                except Exception:
                    pass

        import builtins as _builtins
        g: dict[str, Any] = {"__builtins__": dict(_builtins.__dict__)}
        g["__builtins__"]["print"] = _log
        g.update({
            "math": math, "statistics": statistics,
            "state": self.state, "log": _log,
        })
        self.globals = g

        code_obj = compile(code, f"<script:{script_id[:8]}>", "exec")
        call_budgeted(eval, code_obj, g, budget_ms=2000.0, traced=self.traced)
        self.hooks: dict[str, Callable] = {}
        for name in HOOK_NAMES:
            fn = g.get(name)
            if callable(fn):
                self.hooks[name] = fn
        if not set(self.hooks) & set(ENTRY_HOOKS):
            raise ScriptError(
                "script must define at least one of: decide, decide_market, "
                "manage, decide_signal, supervise")

    def drain_logs(self) -> list[str]:
        out = self._log_lines[:]
        self._log_lines.clear()
        return out

    def call(self, hook: str, *args: Any, budget_ms: float = 250.0) -> Any:
        fn = self.hooks.get(hook)
        if fn is None:
            return None
        try:
            return call_budgeted(fn, *args, budget_ms=budget_ms,
                                 traced=self.traced)
        except ScriptBudgetExceeded:
            raise
        except Exception as e:
            raise ScriptError(f"{hook}() raised {type(e).__name__}: {e}") from e
