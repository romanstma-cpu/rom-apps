"""Regression: attaching an exchange id another local intent already owns.

`us_order_intents.order_id` is UNIQUE. When the operator points a second
intent at an exchange order that is already attached to a first intent, the
UPDATE in `attach_verified_order` trips that constraint. It used to surface as
an opaque sqlite3.IntegrityError; it must now raise `RecoveryRequired` so the
recovery panel/runbook tells the operator exactly what to reconcile.
"""
import pytest

import db
import order_journal as journal
import us_account_stream as stream
from test_order_recovery import raw_order


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'db_path', lambda: str(tmp_path / 'journal-attach.db'))
    db.init_db()
    journal.init()
    stream.consume_dirty()


def test_attaching_an_exchange_id_already_owned_by_another_intent_is_recovery_required():
    # The first intent already owns ex-1.
    journal.begin('first', 'market-a', 'yes', 'buy', 10, .6)
    journal.acknowledge('first', 'ex-1')
    # A second intent is awaiting an exchange id...
    journal.begin('second', 'market-b', 'yes', 'buy', 10, .6)
    journal.state('second', 'unknown')
    # ...but the operator points it at the exchange id the first one owns.
    with pytest.raises(journal.RecoveryRequired, match='already attached'):
        journal.attach_verified_order('second', raw_order(marketSlug='market-b'))
    # Refused and nothing written: the second intent is still unattached and
    # the first intent still owns ex-1.
    assert journal.get('second')['order_id'] is None
    assert journal.get('first')['order_id'] == 'ex-1'