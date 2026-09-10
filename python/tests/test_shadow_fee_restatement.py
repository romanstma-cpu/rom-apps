"""The one-time restatement of script practice P&L onto US fees.

Practice fills used to be settled with an international per-category table
(crypto 0.07, geopolitics 0.00). Neither rate exists on Polymarket US, so
those rows record a P&L that could never have happened. `_restate_shadow_pnl_on_us_fees`
recomputes them from inputs still present on the row.
"""
from __future__ import annotations

import pytest

import db
from conftest import US_FEE_APRIL, US_FEE_JULY

JULY = "2026-08-01 12:00:00"    # theta 0.06
APRIL = "2026-05-01 12:00:00"   # theta 0.05


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "db_path", lambda: tmp_path / "shadow.db")
    db.init_db()
    return tmp_path


def seed(created_at, *, entry_cents=60, contracts=10, won=1, pnl=None,
         resolved=1, ticker="0xa", asset="sports"):
    with db.get_db() as conn:
        db.insert_script_shadow(conn, {
            "script_id": "s1abc", "source": "signal",
            "signal_source": "market", "signal_id": None,
            "asset": asset, "ticker": ticker, "side": "yes",
            "contracts": contracts, "entry_cents": entry_cents,
            "order_type": "GTC", "reason": "t", "close_time": "",
            "network": "mainnet",
        })
        conn.execute(
            """UPDATE script_shadow_orders
                  SET created_at=?, resolved=?, outcome_correct=?, pnl_usd=?
                WHERE ticker=?""",
            (created_at, resolved, won if resolved else None, pnl, ticker),
        )


def pnl_of(ticker="0xa"):
    with db.get_db() as conn:
        row = conn.execute(
            "SELECT pnl_usd FROM script_shadow_orders WHERE ticker=?",
            (ticker,),
        ).fetchone()
    return None if row[0] is None else float(row[0])


def clear_marker():
    with db.get_db() as conn:
        conn.execute("DELETE FROM app_kv WHERE k=?",
                     (db.SHADOW_FEE_RESTATEMENT_KEY,))


def restate():
    with db.get_db() as conn:
        return db._restate_shadow_pnl_on_us_fees(conn)


# --- the correction itself ----------------------------------------------


def test_legacy_crypto_row_is_restated_down_to_the_us_rate(fresh_db):
    """crypto was charged 0.07; the US rate is 0.06, so the loss shrinks."""
    legacy_fee = 0.07 * 0.6 * 0.4
    seed(JULY, won=0, asset="crypto", pnl=round(10 * (-0.60 - legacy_fee), 4))
    clear_marker()
    assert restate() == 1
    assert pnl_of() == pytest.approx(10 * (-0.60 - 0.06 * 0.6 * 0.4), abs=1e-4)


def test_geopolitics_row_was_charged_no_fee_and_now_is(fresh_db):
    """The starkest case: geopolitics used to be free, flattering the record."""
    seed(JULY, won=1, asset="geopolitics", pnl=round(10 * (1.0 - 0.60), 4))
    clear_marker()
    assert restate() == 1
    restated = pnl_of()
    assert restated == pytest.approx(10 * (1.0 - 0.60 - 0.06 * 0.6 * 0.4), abs=1e-4)
    assert restated < 4.0   # strictly worse than the fee-free $4.00


def test_restatement_prices_each_row_at_its_own_schedule(fresh_db):
    seed(APRIL, won=0, ticker="0xapr", pnl=-99.0)
    seed(JULY, won=0, ticker="0xjul", pnl=-99.0)
    clear_marker()
    assert restate() == 2
    assert pnl_of("0xapr") == pytest.approx(10 * (-0.60 - 0.05 * 0.6 * 0.4), abs=1e-4)
    assert pnl_of("0xjul") == pytest.approx(10 * (-0.60 - 0.06 * 0.6 * 0.4), abs=1e-4)
    # July is the dearer schedule, so its loss is the larger one.
    assert pnl_of("0xjul") < pnl_of("0xapr")


def test_a_winner_keeps_a_dollar_per_contract_less_cost_and_fee(fresh_db):
    seed(JULY, won=1, entry_cents=40, contracts=25, pnl=-99.0)
    clear_marker()
    assert restate() == 1
    assert pnl_of() == pytest.approx(
        25 * (1.0 - 0.40 - 0.06 * 0.4 * 0.6), abs=1e-4)


# --- what it must leave alone -------------------------------------------


def test_already_correct_rows_are_not_rewritten(fresh_db):
    correct = round(10 * (-0.60 - 0.06 * 0.6 * 0.4), 4)
    seed(JULY, won=0, pnl=correct)
    clear_marker()
    assert restate() == 0
    assert pnl_of() == pytest.approx(correct, abs=1e-4)


def test_unresolved_rows_are_untouched(fresh_db):
    seed(JULY, resolved=0, pnl=None)
    clear_marker()
    assert restate() == 0
    assert pnl_of() is None


def test_rows_excluded_for_a_missing_outcome_stay_excluded(fresh_db):
    """resolved=1 with a NULL outcome means 'never settled' - not a P&L of 0."""
    with db.get_db() as conn:
        db.insert_script_shadow(conn, {
            "script_id": "s1abc", "source": "signal",
            "signal_source": "market", "signal_id": None,
            "asset": "sports", "ticker": "0xnull", "side": "yes",
            "contracts": 10, "entry_cents": 60, "order_type": "GTC",
            "reason": "t", "close_time": "", "network": "mainnet",
        })
        conn.execute(
            """UPDATE script_shadow_orders
                  SET resolved=1, outcome_correct=NULL, pnl_usd=NULL,
                      created_at=? WHERE ticker='0xnull'""",
            (JULY,),
        )
    clear_marker()
    assert restate() == 0
    assert pnl_of("0xnull") is None


def test_refused_zero_contract_rows_are_skipped(fresh_db):
    seed(JULY, contracts=0, won=0, pnl=0.0)
    clear_marker()
    assert restate() == 0


# --- it runs once --------------------------------------------------------


def test_restatement_is_guarded_and_does_not_repeat(fresh_db):
    seed(JULY, won=0, pnl=-99.0)
    clear_marker()
    assert restate() == 1
    first = pnl_of()
    # Second call is a no-op even though rows exist.
    assert restate() == 0
    assert pnl_of() == pytest.approx(first, abs=1e-9)


def test_marker_is_written_even_when_nothing_changed(fresh_db):
    clear_marker()
    assert restate() == 0
    with db.get_db() as conn:
        assert db.kv_get(conn, db.SHADOW_FEE_RESTATEMENT_KEY) is not None


def test_init_db_runs_the_restatement(fresh_db):
    """It must fire on upgrade, not only when called directly."""
    seed(JULY, won=0, pnl=-99.0)
    clear_marker()
    db.init_db()
    assert pnl_of() == pytest.approx(10 * (-0.60 - 0.06 * 0.6 * 0.4), abs=1e-4)


def test_restatement_survives_an_unparseable_timestamp(fresh_db):
    """Older rows must still settle rather than raising mid-migration."""
    seed("not-a-date", won=0, pnl=-99.0)
    clear_marker()
    assert restate() == 1
    # Priced at the earliest published coefficient, not skipped or zeroed.
    assert pnl_of() == pytest.approx(10 * (-0.60 - 0.05 * 0.6 * 0.4), abs=1e-4)
