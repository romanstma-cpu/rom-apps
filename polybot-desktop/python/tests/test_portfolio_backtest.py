from __future__ import annotations

import pytest

import fees_us
import portfolio_backtest as pb
from config import merge_with_defaults
from conftest import US_FEE_APRIL, US_FEE_JULY

JULY = US_FEE_JULY.timestamp()
APRIL = US_FEE_APRIL.timestamp()
HOUR = 3600.0
DAY = 86400.0


def cfg(**over) -> dict:
    return merge_with_defaults({"network": "mainnet", **over})


def sig(i, *, cost=0.5, correct=True, confidence=70.0, at=None,
        holds=2 * HOUR, event=None, ticker=None):
    start = JULY + i * HOUR if at is None else at
    return {
        "source": "whale", "cost": cost, "correct": correct,
        "confidence": confidence, "at": start, "resolved_at": start + holds,
        "event": event if event is not None else f"E{i}",
        "ticker": ticker if ticker is not None else f"T{i}",
        "category": "sports",
    }


# --- capital is finite and sequential -----------------------------------


def test_entries_stop_when_cash_runs_out():
    # Twenty simultaneous signals against $100 with a $50 hard cap.
    signals = [sig(i, at=JULY, holds=10 * DAY) for i in range(20)]
    r = pb.simulate(signals, cfg(), start_bankroll_usd=100.0)
    assert r["n_signals"] == 20
    assert r["n_entered"] < 20
    assert sum(r["skips"].values()) == 20 - r["n_entered"]
    # Never spent more than it had: everything staked came out of $100.
    assert r["avg_position_usd"] * r["n_entered"] <= 100.0 + 1e-9


def test_capital_returned_by_a_settlement_funds_a_later_entry():
    """Settled capital is redeployable; capital still at risk is not.

    Both runs take the same two signals, so entry counts match. What differs
    is how much money the account can put to work: sequentially it stakes
    more than its whole starting bankroll because the winner's payout comes
    back first, while overlapped it can never stake more than it started with.
    """
    tight = cfg(min_size_fraction=0.9, max_size_fraction=0.9,
                max_total_exposure_fraction=1.0, min_cash_reserve_fraction=0.0,
                hard_max_position_usd=1e9)
    start = 60.0

    sequential = pb.simulate(
        [sig(0, at=JULY, holds=HOUR, correct=True),
         sig(1, at=JULY + 2 * HOUR, holds=HOUR)],
        tight, start_bankroll_usd=start,
    )
    overlapping = pb.simulate(
        [sig(0, at=JULY, holds=10 * DAY, correct=True),
         sig(1, at=JULY + 2 * HOUR, holds=HOUR)],
        tight, start_bankroll_usd=start,
    )

    assert sequential["n_entered"] == overlapping["n_entered"] == 2
    staked_seq = sequential["avg_position_usd"] * sequential["n_entered"]
    staked_lap = overlapping["avg_position_usd"] * overlapping["n_entered"]
    assert staked_seq > start
    assert staked_lap <= start + 1e-9
    assert staked_seq > staked_lap


def test_settlement_credits_a_dollar_per_winning_contract():
    one = sig(0, cost=0.5, correct=True, holds=HOUR)
    r = pb.simulate([one], cfg(), start_bankroll_usd=1000.0)
    assert r["n_entered"] == 1 and r["wins"] == 1
    # A winner returns $1 per contract, so it must clear its own cost basis.
    assert r["best_trade"] > 0
    assert r["final_equity"] == pytest.approx(1000.0 + r["best_trade"])
    assert r["final_equity"] > 1000.0


def test_a_loser_forfeits_the_entire_stake():
    one = sig(0, cost=0.5, correct=False, holds=HOUR)
    r = pb.simulate([one], cfg(), start_bankroll_usd=1000.0)
    assert r["losses"] == 1
    assert r["final_equity"] == pytest.approx(1000.0 - r["avg_position_usd"])
    assert r["worst_trade"] == pytest.approx(-r["avg_position_usd"])


# --- the structural caps ------------------------------------------------


def test_max_open_positions_binds():
    signals = [sig(i, at=JULY, holds=10 * DAY) for i in range(10)]
    r = pb.simulate(signals, cfg(max_open_positions=3), start_bankroll_usd=100_000.0)
    assert r["n_entered"] == 3
    assert r["skips"]["max_open_positions"] == 7
    assert r["peak_concurrent"] == 3


def test_max_daily_new_positions_binds_and_resets_the_next_day():
    day_one = [sig(i, at=JULY + i * 60, holds=HOUR) for i in range(5)]
    day_two = [sig(10 + i, at=JULY + DAY + i * 60, holds=HOUR) for i in range(5)]
    r = pb.simulate(
        day_one + day_two,
        cfg(max_daily_new_positions=2, unlimited_daily_new_positions=False),
        start_bankroll_usd=100_000.0,
    )
    assert r["n_entered"] == 4          # two per day
    assert r["skips"]["max_daily_new_positions"] == 6


def test_daily_cap_follows_the_configured_trading_day():
    """A signal at 00:30 UTC belongs to the previous ET day."""
    utc_midnight = US_FEE_JULY.replace(hour=0, minute=0).timestamp() + DAY
    evening = utc_midnight - 3 * HOUR    # 5pm ET, previous ET day
    after = utc_midnight + 30 * 60       # 8:30pm ET, same ET day
    signals = [sig(0, at=evening, holds=HOUR), sig(1, at=after, holds=HOUR)]

    utc_day = pb.simulate(
        signals, cfg(max_daily_new_positions=1, trading_timezone_offset_min=0),
        start_bankroll_usd=100_000.0)
    et_day = pb.simulate(
        signals, cfg(max_daily_new_positions=1, trading_timezone_offset_min=-240),
        start_bankroll_usd=100_000.0)

    # Under UTC the cap resets at midnight, so both get in.
    assert utc_day["n_entered"] == 2
    # Under ET they are the same trading day, so the cap holds.
    assert et_day["n_entered"] == 1
    assert et_day["skips"]["max_daily_new_positions"] == 1


def test_max_positions_per_event_binds():
    signals = [
        sig(i, at=JULY + i * 60, holds=10 * DAY, event="SAME", ticker=f"T{i}")
        for i in range(4)
    ]
    r = pb.simulate(signals, cfg(max_positions_per_event=1),
                    start_bankroll_usd=100_000.0)
    assert r["n_entered"] == 1
    assert r["skips"]["max_positions_per_event"] == 3


def test_same_market_is_not_entered_twice_while_open():
    signals = [
        sig(i, at=JULY + i * 60, holds=10 * DAY, event=f"E{i}", ticker="SAME")
        for i in range(3)
    ]
    r = pb.simulate(signals, cfg(max_positions_per_event=99),
                    start_bankroll_usd=100_000.0)
    assert r["n_entered"] == 1
    assert r["skips"]["market_already_open"] == 2


def test_exposure_cap_binds_before_cash_does():
    signals = [sig(i, at=JULY + i * 60, holds=10 * DAY) for i in range(20)]
    r = pb.simulate(
        signals,
        cfg(max_total_exposure_fraction=0.10, hard_max_position_usd=50.0),
        start_bankroll_usd=1000.0,
    )
    assert r["skips"]["exposure_cap"] > 0
    # Never more than ~10% of bankroll at risk at once.
    assert r["avg_position_usd"] * r["peak_concurrent"] <= 1000.0 * 0.10 + 1.0


def test_cash_reserve_is_never_spent():
    signals = [sig(i, at=JULY + i * 60, holds=10 * DAY) for i in range(50)]
    r = pb.simulate(
        signals,
        cfg(min_cash_reserve_fraction=0.50, max_total_exposure_fraction=1.0),
        start_bankroll_usd=1000.0,
    )
    invested = r["avg_position_usd"] * r["n_entered"]
    assert invested <= 500.0 + 1.0


# --- sizing modes -------------------------------------------------------


def test_kelly_sizes_differently_from_percent_by_price():
    """Kelly is price-sensitive; the percent ramp is not."""
    def run(mode, cost):
        one = sig(0, cost=cost, confidence=cost * 100 + 10, holds=HOUR)
        c = cfg(sizing_mode=mode, kelly_fraction=1.0,
                min_size_fraction=0.001, max_size_fraction=1.0,
                hard_max_position_usd=1e9, max_total_exposure_fraction=1.0,
                min_cash_reserve_fraction=0.0)
        return pb.simulate([one], c, start_bankroll_usd=1000.0)["avg_position_usd"]

    # Same 10pt edge, different prices.
    assert run("percent", 0.9) == pytest.approx(run("percent", 0.2), rel=0.02)
    assert run("kelly", 0.9) > run("kelly", 0.2)


def test_contracts_mode_is_honoured():
    one = sig(0, cost=0.5, confidence=100.0, holds=HOUR)
    r = pb.simulate(
        [one], cfg(sizing_mode="contracts", min_contracts=5, max_contracts=10),
        start_bankroll_usd=100_000.0)
    # Max edge asks for 10 contracts = a $5.00 budget. Each contract reserves
    # 52c (50c + a 2c fee rounded up), so only 9 fit - the same shave the live
    # path takes via entry_budget -> affordable_contracts.
    assert r["avg_position_usd"] == pytest.approx(9 * 0.5 + fees_us.fee(9, 0.5, JULY))


# --- fees ---------------------------------------------------------------


def test_fees_are_charged_and_reduce_equity():
    signals = [sig(i, holds=HOUR) for i in range(10)]
    r = pb.simulate(signals, cfg(), start_bankroll_usd=10_000.0)
    assert r["fees_paid"] > 0
    free = pb.simulate(signals, cfg(), start_bankroll_usd=10_000.0)
    assert r["final_equity"] == pytest.approx(free["final_equity"])
    # Equity would have been exactly the fees higher without them.
    gross = r["final_equity"] + r["fees_paid"]
    assert gross > r["final_equity"]


def test_july_schedule_costs_more_than_april():
    def run(at):
        signals = [sig(i, at=at + i * HOUR, holds=HOUR) for i in range(10)]
        return pb.simulate(signals, cfg(), start_bankroll_usd=10_000.0)

    april, july = run(APRIL), run(JULY)
    assert july["fees_paid"] > april["fees_paid"]


def test_signals_older_than_any_schedule_are_reported():
    signals = [sig(0, at=1.0, holds=HOUR), sig(1, at=JULY, holds=HOUR)]
    r = pb.simulate(signals, cfg(), start_bankroll_usd=10_000.0)
    assert r["unpriced_signals"] == 1


# --- reporting ----------------------------------------------------------


def test_signals_without_a_timestamp_are_dropped_not_guessed():
    good = sig(0, holds=HOUR)
    bad = dict(sig(1, holds=HOUR), at=0.0)
    r = pb.simulate([good, bad], cfg(), start_bankroll_usd=1000.0)
    assert r["n_signals"] == 1 and r["n_entered"] == 1


def test_min_confidence_filters_before_sizing():
    signals = [sig(0, confidence=55.0, holds=HOUR), sig(1, confidence=85.0, holds=HOUR)]
    r = pb.simulate(signals, cfg(), start_bankroll_usd=1000.0, min_confidence=60.0)
    assert r["n_signals"] == 1 and r["n_entered"] == 1


def test_max_drawdown_measures_the_worst_peak_to_trough():
    # Three winners, then a loser large enough to dent the peak.
    signals = [sig(i, correct=True, holds=HOUR) for i in range(3)]
    signals.append(sig(3, correct=False, holds=HOUR))
    r = pb.simulate(signals, cfg(), start_bankroll_usd=1000.0)
    assert r["max_drawdown"] > 0.0
    assert 0.0 <= r["max_drawdown"] <= 1.0


def test_empty_input_is_zeroed_not_divided_by_zero():
    r = pb.simulate([], cfg(), start_bankroll_usd=1000.0)
    assert r["n_signals"] == 0
    assert r["n_entered"] == 0
    assert r["win_rate"] == 0.0
    assert r["fill_rate"] == 0.0
    assert r["total_return"] == 0.0
    assert r["final_equity"] == 1000.0


def test_fill_rate_exposes_signals_the_caps_refused():
    """The headline the per-contract report cannot show."""
    signals = [sig(i, at=JULY, holds=10 * DAY) for i in range(10)]
    r = pb.simulate(signals, cfg(max_open_positions=2), start_bankroll_usd=100_000.0)
    assert r["fill_rate"] == pytest.approx(0.2)
    assert r["n_signals"] == 10 and r["n_entered"] == 2


def test_equity_curve_starts_at_the_bankroll_and_ends_at_final_equity():
    signals = [sig(i, holds=HOUR) for i in range(5)]
    r = pb.simulate(signals, cfg(), start_bankroll_usd=1000.0)
    curve = r["equity_curve"]
    assert curve[0][1] == pytest.approx(1000.0)
    assert curve[-1][1] == pytest.approx(r["final_equity"])
    assert all(a[0] <= b[0] for a, b in zip(curve, curve[1:]))


# --- config loading and reporting ---------------------------------------


def test_saved_config_is_read_from_the_app_settings_file(tmp_path, monkeypatch):
    import json

    import backtest as bt

    (tmp_path / "settings.json").write_text(json.dumps({
        "config": {"sizingMode": "kelly", "maxOpenPositions": 7}
    }), encoding="utf-8")
    monkeypatch.setenv("ROM_POLYBOT_USERDATA", str(tmp_path))

    cfg, path = bt.load_saved_config()
    assert path == tmp_path / "settings.json"
    assert cfg["sizing_mode"] == "kelly"        # camelCase is converted
    assert cfg["max_open_positions"] == 7
    assert cfg["hard_max_position_usd"] == 50.0  # defaults fill the rest


def test_saved_config_falls_back_to_defaults(tmp_path, monkeypatch):
    import backtest as bt

    monkeypatch.setenv("ROM_POLYBOT_USERDATA", str(tmp_path))
    monkeypatch.delenv("APPDATA", raising=False)
    cfg, path = bt.load_saved_config()
    assert path is None
    assert cfg["sizing_mode"] == "percent"


def test_saved_config_survives_a_corrupt_settings_file(tmp_path, monkeypatch):
    import backtest as bt

    (tmp_path / "settings.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("ROM_POLYBOT_USERDATA", str(tmp_path))
    monkeypatch.delenv("APPDATA", raising=False)
    cfg, path = bt.load_saved_config()
    assert path is None and cfg["sizing_mode"] == "percent"


def test_report_names_the_binding_caps_and_keeps_caveats_visible():
    signals = [sig(i, at=JULY, holds=10 * DAY) for i in range(10)]
    c = cfg(max_open_positions=2)
    text = pb.format_portfolio_report(
        pb.simulate(signals, c, start_bankroll_usd=1000.0), c, "unit-test",
        config_label="built-in defaults")
    assert "at max open positions" in text
    assert "WHY 8 SIGNAL(S) WERE NOT TAKEN" in text
    assert "CAVEATS" in text
    assert "take-profit and stop-loss are not simulated" in text
    assert "not a forecast" in text


def test_report_describes_each_sizing_mode():
    signals = [sig(0, holds=HOUR)]
    for mode, expected in (
        ("percent", "of bankroll by edge"),
        ("contracts", "contracts by edge"),
        ("kelly", "kelly at"),
    ):
        c = cfg(sizing_mode=mode)
        text = pb.format_portfolio_report(
            pb.simulate(signals, c, start_bankroll_usd=1000.0), c, "unit-test")
        assert expected in text


def test_report_shows_the_trading_day_offset():
    c = cfg(trading_timezone_offset_min=-240)
    text = pb.format_portfolio_report(
        pb.simulate([sig(0, holds=HOUR)], c, start_bankroll_usd=1000.0),
        c, "unit-test")
    assert "UTC-4" in text


def test_report_handles_no_usable_signals():
    c = cfg()
    text = pb.format_portfolio_report(pb.simulate([], c), c, "unit-test")
    assert "No timestamped resolved signals found" in text


def test_report_discloses_signals_priced_by_fallback():
    c = cfg()
    signals = [sig(0, at=1.0, holds=HOUR), sig(1, at=JULY, holds=HOUR)]
    text = pb.format_portfolio_report(
        pb.simulate(signals, c, start_bankroll_usd=1000.0), c, "unit-test")
    assert "predate the first published schedule" in text
