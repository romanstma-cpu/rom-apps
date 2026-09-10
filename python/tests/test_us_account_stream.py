"""Account stream ingest: dirty flag propagation and message routing.

The private account stream augments the durable order journal and triggers
periodic reconciliation. ingest() is synchronous (called from async via
json.loads); consume_dirty() is polled by the service loop.
"""
from __future__ import annotations

import pytest

import us_account_stream as stream


@pytest.fixture(autouse=True)
def reset_dirty():
    stream._dirty = False
    yield
    stream._dirty = False


class TestConsumeDirty:
    def test_initially_false(self):
        assert stream.consume_dirty() is False

    def test_consume_clears_flag(self):
        stream._dirty = True
        assert stream.consume_dirty() is True
        assert stream.consume_dirty() is False

    def test_consume_returns_false_when_not_dirty(self):
        assert stream.consume_dirty() is False
        assert stream.consume_dirty() is False


class TestIngestDirtyFlag:
    def test_position_subscription_sets_dirty(self):
        stream.ingest({"positionSubscription": {"positions": []}})
        assert stream._dirty is True

    def test_balance_snapshot_sets_dirty(self):
        stream.ingest({"accountBalancesSnapshot": {}})
        assert stream._dirty is True

    def test_balance_update_sets_dirty(self):
        stream.ingest({"accountBalancesUpdate": {}})
        assert stream._dirty is True

    def test_order_snapshot_sets_dirty(self):
        stream.ingest({"orderSubscriptionSnapshot": {"orders": []}})
        assert stream._dirty is True

    def test_order_update_sets_dirty(self):
        stream.ingest({"orderSubscriptionUpdate": {"execution": {}}})
        assert stream._dirty is True

    def test_irrelevant_message_does_not_set_dirty(self):
        stream.ingest({"type": "ping"})
        assert stream._dirty is False

    def test_empty_message_does_not_set_dirty(self):
        stream.ingest({})
        assert stream._dirty is False


class TestIngestError:
    def test_error_message_raises(self):
        with pytest.raises(ValueError, match="rejected"):
            stream.ingest({"error": "some subscription error"})

    def test_none_error_field_ignored(self):
        stream.ingest({"error": None})
        assert stream._dirty is False

    def test_no_error_field_ignored(self):
        stream.ingest({"somethingElse": "ok"})
        assert stream._dirty is False


class TestIngestMessageRouting:
    def test_orders_snapshot_dispatches_to_journal(self, monkeypatch):
        called = []
        monkeypatch.setattr("order_journal.record_order", lambda o: called.append(o))
        stream.ingest({"orderSubscriptionSnapshot": {
            "orders": [{"id": "1"}, {"id": "2"}],
        }})
        assert called == [{"id": "1"}, {"id": "2"}]

    def test_order_update_dispatches_execution(self, monkeypatch):
        called = []
        monkeypatch.setattr("order_journal.record_execution", lambda e: called.append(e))
        stream.ingest({"orderSubscriptionUpdate": {
            "execution": {"order_id": "x", "fill": True},
        }})
        assert called == [{"order_id": "x", "fill": True}]

    def test_no_orders_snapshot_dispatches_nothing(self, monkeypatch):
        called = []
        monkeypatch.setattr("order_journal.record_order", lambda o: called.append(o))
        stream.ingest({"orderSubscriptionSnapshot": {}})
        assert called == []

    def test_position_message_does_not_dispatch(self, monkeypatch):
        called_order = []
        called_exec = []
        monkeypatch.setattr("order_journal.record_order", lambda o: called_order.append(o))
        monkeypatch.setattr("order_journal.record_execution", lambda e: called_exec.append(e))
        stream.ingest({"positionSubscription": {"positions": [{"id": "p1"}]}})
        assert called_order == []
        assert called_exec == []

    def test_multiple_fields_all_dispatched(self, monkeypatch):
        orders = []
        execs = []
        monkeypatch.setattr("order_journal.record_order", lambda o: orders.append(o))
        monkeypatch.setattr("order_journal.record_execution", lambda e: execs.append(e))
        stream.ingest({
            "orderSubscriptionSnapshot": {"orders": [{"id": "1"}]},
            "orderSubscriptionUpdate": {"execution": {"order_id": "2"}},
            "positionSubscription": {"positions": []},
        })
        assert orders == [{"id": "1"}]
        assert execs == [{"order_id": "2"}]
        assert stream._dirty is True