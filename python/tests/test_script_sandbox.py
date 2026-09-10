from __future__ import annotations

import pytest

import script_sandbox as ss


SIMPLE = (
    "def decide(ctx):\n"
    "    return {'side': 'up', 'price': 'ask'}\n"
)


def test_ordinary_strategy_script_validates():
    assert ss.validate(SIMPLE) == []


@pytest.mark.parametrize("code", [
    "import os\ndef decide(ctx):\n    return None\n",
    "import json, math\ndef decide(ctx):\n    return None\n",
    "class Model:\n    pass\ndef decide(ctx):\n    return None\n",
    "def decide(ctx):\n    return ().__class__\n",
    "def decide(ctx):\n    return '{0.__class__}'.format(ctx)\n",
    "def decide(ctx):\n    return getattr(ctx, 'x', None)\n",
    "_cache = {}\ndef decide(ctx):\n    global _cache\n    return None\n",
    "def decide(ctx):\n    try:\n        pass\n    except:\n        pass\n    return None\n",
])
def test_full_python_is_accepted(code):
    assert ss.validate(code) == [], code


def test_script_with_no_entry_hook_is_rejected():
    errors = ss.validate("def helper(x):\n    return x\n")
    assert errors and "at least one of" in errors[0]


def test_nested_entry_hook_does_not_count():
    errors = ss.validate("def outer():\n    def decide(ctx):\n        return None\n")
    assert errors and "at least one of" in errors[0]


@pytest.mark.parametrize("hook", ["decide", "decide_market", "manage",
                                  "decide_signal", "supervise"])
def test_any_single_entry_hook_satisfies_the_contract(hook):
    assert ss.validate(f"def {hook}(a=None, b=None):\n    return None\n") == []


def test_syntax_errors_are_reported_with_a_line_number():
    errors = ss.validate("def decide(ctx)\n    return None\n")
    assert errors and "syntax error line 1" in errors[0]


def test_oversized_script_is_rejected():
    big = "# " + ("x" * (ss.MAX_CODE_BYTES + 10)) + "\n" + SIMPLE
    errors = ss.validate(big)
    assert errors and "exceeds" in errors[0]


def test_async_hooks_are_rejected_because_the_engine_calls_them_sync():
    errors = ss.validate("async def decide(ctx):\n    return None\n")
    assert errors and "async def" in errors[0]


def test_compiled_script_exposes_only_defined_hooks():
    mod = ss.CompiledScript("t1", SIMPLE + "def on_fill(p, s):\n    return None\n")
    assert set(mod.hooks) == {"decide", "on_fill"}
    assert mod.call("manage", {}, {}) is None


def test_invalid_script_raises_script_error_on_compile():
    with pytest.raises(ss.ScriptError):
        ss.CompiledScript("t2", "def helper():\n    return 1\n")


def test_scripts_get_the_real_builtins():
    mod = ss.CompiledScript("t3", (
        "import json\n"
        "def decide(ctx):\n"
        "    return json.loads('{\"side\": \"up\", \"price\": \"ask\"}')\n"
    ))
    assert mod.call("decide", {}) == {"side": "up", "price": "ask"}


def test_math_and_statistics_are_injected_without_an_import():
    mod = ss.CompiledScript("t4", (
        "def decide(ctx):\n"
        "    return {'side': 'up', 'price': int(math.floor(statistics.mean([1, 3])))}\n"
    ))
    assert mod.call("decide", {})["price"] == 2


def test_state_is_shared_with_the_script_and_survives_calls():
    mod = ss.CompiledScript("t5", (
        "def decide(ctx):\n"
        "    state['n'] = state.get('n', 0) + 1\n"
        "    return None\n"
    ))
    mod.call("decide", {})
    mod.call("decide", {})
    assert mod.state["n"] == 2


def test_restored_state_is_visible_to_the_script():
    mod = ss.CompiledScript("t6", (
        "def decide(ctx):\n    return state.get('carried')\n"
    ), state={"carried": "yes"})
    assert mod.call("decide", {}) == "yes"


def test_log_and_print_both_reach_the_drainable_sink():
    mod = ss.CompiledScript("t7", (
        "def decide(ctx):\n"
        "    log('via log')\n"
        "    print('via print')\n"
        "    return None\n"
    ))
    mod.call("decide", {})
    assert mod.drain_logs() == ["via log", "via print"]
    assert mod.drain_logs() == []


def test_log_volume_is_capped():
    mod = ss.CompiledScript("t8", (
        "def decide(ctx):\n"
        "    for i in range(5000):\n        log(i)\n"
        "    return None\n"
    ))
    mod.call("decide", {})
    assert 0 < len(mod.drain_logs()) <= 200


def test_hook_exception_becomes_a_script_error():
    mod = ss.CompiledScript("t9", "def decide(ctx):\n    return 1 / 0\n")
    with pytest.raises(ss.ScriptError) as e:
        mod.call("decide", {})
    assert "ZeroDivisionError" in str(e.value)


def test_code_hash_changes_with_the_code():
    assert ss.code_hash(SIMPLE) == ss.code_hash(SIMPLE)
    assert ss.code_hash(SIMPLE) != ss.code_hash(SIMPLE + "\n# tweak\n")


def test_busy_loop_is_killed_by_the_budget():
    mod = ss.CompiledScript(
        "b1", "def decide(ctx):\n    while True:\n        pass\n", traced=True)
    with pytest.raises(ss.ScriptBudgetExceeded):
        mod.call("decide", {}, budget_ms=50.0)


def test_busy_loop_cannot_swallow_the_budget_with_try_except():
    mod = ss.CompiledScript("b2", (
        "def decide(ctx):\n"
        "    while True:\n"
        "        try:\n"
        "            pass\n"
        "        except Exception:\n"
        "            pass\n"
    ), traced=True)
    with pytest.raises(ss.ScriptBudgetExceeded):
        mod.call("decide", {}, budget_ms=50.0)


def test_untraced_calls_run_bare_so_the_live_engine_can_thread_bound_them():
    mod = ss.CompiledScript("b3", SIMPLE)
    assert mod.traced is False
    assert mod.call("decide", {}) == {"side": "up", "price": "ask"}


def test_budget_restores_the_previous_tracer():
    import sys

    def sentinel(frame, event, arg):
        return sentinel

    sys.settrace(sentinel)
    try:
        mod = ss.CompiledScript("b4", SIMPLE, traced=True)
        mod.call("decide", {})
        assert sys.gettrace() is sentinel
    finally:
        sys.settrace(None)


def test_script_failures_covers_both_failure_kinds():
    assert ss.ScriptError in ss.SCRIPT_FAILURES
    assert ss.ScriptBudgetExceeded in ss.SCRIPT_FAILURES
    assert not issubclass(ss.ScriptBudgetExceeded, Exception)


def test_parse_header_reads_name_and_description():
    meta = ss.parse_header(
        "# rom-script v1\n# name: My Strat\n# description: Does a thing.\n"
        + SIMPLE)
    assert meta["version"] == "v1"
    assert meta["name"] == "My Strat"
    assert meta["description"] == "Does a thing."


def test_find_ctx_fields_sees_both_access_styles():
    fields = ss.find_ctx_fields(
        "def decide(ctx):\n"
        "    a = ctx['minsLeft']\n"
        "    b = ctx.get('upAsk')\n"
        "    return None\n"
    )
    assert fields == ["minsLeft", "upAsk"]


def test_infinite_recursion_becomes_script_error():
    mod = ss.CompiledScript("rec", "def decide(ctx):\n    return decide(ctx)\n")
    with pytest.raises(ss.ScriptError) as exc:
        mod.call("decide", {})
    assert "RecursionError" in str(exc.value)

