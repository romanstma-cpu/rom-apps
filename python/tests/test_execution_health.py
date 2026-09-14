from __future__ import annotations

from execution_health import COOLDOWN_SECONDS, ExecutionCircuit


class Clock:
    def __init__(self): self.value = 0.0
    def __call__(self): return self.value


def test_circuit_opens_after_three_failures_and_blocks_entries():
    clock = Clock()
    circuit = ExecutionCircuit(clock=clock)
    for _ in range(3): circuit.record_failure('quote', 'timeout')
    assert circuit.state() == 'open'
    assert circuit.begin_attempt() is False
    assert 'retrying' in (circuit.blocked_reason() or '')


def test_circuit_allows_one_half_open_recovery_probe():
    clock = Clock()
    circuit = ExecutionCircuit(clock=clock)
    for _ in range(3): circuit.record_failure('order', '503')
    clock.value += COOLDOWN_SECONDS + 1
    assert circuit.state() == 'half_open'
    assert circuit.begin_attempt() is True
    assert circuit.begin_attempt() is False
    circuit.record_order_success()
    assert circuit.state() == 'closed'
    assert circuit.snapshot()['failureCount'] == 0


def test_successful_quote_only_clears_quote_failures():
    circuit = ExecutionCircuit(clock=Clock())
    circuit.record_failure('quote', 'timeout')
    circuit.record_failure('order', '503')
    circuit.record_quote_success()
    snap = circuit.snapshot()
    assert snap['quoteFailures'] == 0
    assert snap['orderFailures'] == 1
