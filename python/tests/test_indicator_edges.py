from __future__ import annotations

import math

import indicators as ind


# --- empty inputs -------------------------------------------------------

def test_ema_series_empty():
    assert ind.ema_series([], 3) == []


def test_ema_last_empty_none():
    assert ind.ema_last([], 12) is None


def test_sma_empty_none():
    assert ind.sma([], 20) is None


def test_sigma1m_empty_none():
    assert ind.sigma1m([]) is None


def test_macd_empty_none():
    assert ind.macd([]) is None


def test_rsi_empty_none():
    assert ind.rsi([]) is None


def test_vwap_empty_none():
    assert ind.vwap([], None, 60) is None


def test_pct_change_empty_none():
    assert ind.pct_change([], 1) is None


# --- single-element series ----------------------------------------------

def test_ema_series_single_element():
    # period 1 with one value => the value itself (n >= period)
    assert ind.ema_series([5.0], 1) == [5.0]


def test_ema_last_single_element():
    # period 1 with one value => the value itself
    assert ind.ema_last([5.0], 1) == 5.0


def test_sma_single_element():
    assert ind.sma([5.0], 1) == 5.0


def test_sigma1m_single_element():
    assert ind.sigma1m([5.0]) is None


def test_macd_single_element():
    assert ind.macd([5.0]) is None


def test_rsi_single_element():
    assert ind.rsi([5.0]) is None


def test_vwap_single_element_with_volume():
    assert ind.vwap([5.0], [2.0], 1) == 5.0


def test_pct_change_single_element():
    assert ind.pct_change([5.0], 1) is None


# --- period longer than the series --------------------------------------

def test_ema_series_period_longer_than_series():
    assert ind.ema_series([1.0, 2.0, 3.0], 10) == []


def test_ema_last_period_longer_than_series():
    assert ind.ema_last([1.0, 2.0, 3.0], 10) is None


def test_sma_period_longer_than_series():
    assert ind.sma([1.0, 2.0, 3.0], 10) is None


def test_macd_period_longer_than_series_via_short_series():
    # macd() falls back to None without raising on a series too short for
    # slow + signal (26 + 9).
    assert ind.macd([1.0, 2.0, 3.0], slow=26, signal=9) is None


def test_rsi_period_longer_than_series():
    assert ind.rsi([1.0, 2.0, 3.0], period=14) is None


def test_vwap_period_longer_than_series():
    assert ind.vwap([1.0, 2.0, 3.0], None, 10) is None


def test_pct_change_lookback_longer_than_series():
    assert ind.pct_change([1.0, 2.0, 3.0], 10) is None


# --- all-None closes ----------------------------------------------------

def test_floats_drops_everything_for_all_none():
    assert ind._floats([None, None, None]) == []


def test_ema_series_all_none():
    assert ind.ema_series([None, None, None], 3) == []


def test_macd_all_none():
    assert ind.macd([None] * 60) is None


def test_rsi_all_none():
    assert ind.rsi([None] * 20) is None


def test_sigma1m_all_none():
    assert ind.sigma1m([None] * 40) is None


def test_sma_all_none():
    assert ind.sma([None] * 10, 5) is None


def test_ema_last_all_none():
    assert ind.ema_last([None] * 10, 5) is None


def test_vwap_all_none():
    assert ind.vwap([None] * 10, None, 5) is None


def test_pct_change_all_none():
    assert ind.pct_change([None] * 10, 1) is None


def test_compute_all_none_only_none_values():
    out = ind.compute([None, None, None])
    assert set(out) == {
        "macd", "macdSignal", "macdHist", "macdCross", "rsi", "sigma1m",
        "vwap1h", "ema12", "sma20", "sma50", "priceVsVwapPct",
        "ema12VsSma20Pct", "ema1VsSma5Pct", "velocity1mPct",
        "change5mPct", "change15mPct",
    }
    assert all(v is None for v in out.values())


# --- repeated identical values (zero variance) --------------------------

def test_rsi_flat_series_is_50():
    # No gains, no losses -> neutral 50.0, not 0 or 100.
    assert ind.rsi([10.0] * 30) == 50.0


def test_sigma1m_flat_series_is_finite_zero():
    out = ind.sigma1m([10.0] * 40)
    assert out is not None
    assert out == 0.0
    assert math.isfinite(out)


def test_sma_flat_series():
    assert ind.sma([7.0] * 10, 5) == 7.0


def test_ema_series_flat_series():
    assert ind.ema_series([7.0] * 10, 3) == [7.0] * 8


def test_vwap_flat_series_no_volume():
    assert ind.vwap([7.0] * 10, None, 5) == 7.0


def test_pct_change_flat_series_is_zero():
    assert ind.pct_change([7.0] * 10, 1) == 0.0


def test_compute_flat_series_vwap_sma_finite():
    out = ind.compute([50.0] * 80)
    assert out["vwap1h"] == 50.0
    assert out["sma20"] == 50.0
    assert out["sma50"] == 50.0
    assert out["priceVsVwapPct"] == 0.0
    assert out["velocity1mPct"] == 0.0
    assert out["change5mPct"] == 0.0
    assert out["change15mPct"] == 0.0


# --- NaN entries --------------------------------------------------------

def test_ema_series_nan_entries_filtered():
    # NaN must not leak into the output: the seed window can span a NaN and
    # every following EMA then becomes NaN.
    assert ind.ema_series([1.0, 2.0, float("nan"), 3.0], 2) == [1.5, 2.5]


def test_ema_last_nan_entries():
    out = ind.ema_last([1.0, 2.0, float("nan"), 3.0], 2)
    assert out is not None
    assert math.isfinite(out)


def test_sma_nan_entries_filtered():
    out = ind.sma([1.0, 2.0, float("nan"), 4.0], 3)
    assert out is not None
    assert math.isfinite(out)


def test_rsi_nan_entries_filtered():
    out = ind.rsi([1.0, 2.0, float("nan"), 3.0, 4.0, 5.0] * 4, period=14)
    assert out is not None
    assert math.isfinite(out)


def test_sigma1m_nan_entries_filtered():
    out = ind.sigma1m([10.0] * 16 + [float("nan")] + [10.0] * 16)
    assert out is not None
    assert math.isfinite(out)


def test_vwap_nan_entries_filtered():
    out = ind.vwap([1.0, float("nan"), 3.0], None, 3)
    # NaN/inf are dropped by _floats; window 3 of [1.0, 3.0] is only 2 points => None
    assert out is None


def test_pct_change_nan_entries_filtered():
    out = ind.pct_change([1.0, float("nan"), 3.0], 1)
    assert out is not None
    assert math.isfinite(out)
    assert out == 200.0


def test_compute_nan_entries_never_emit_nan():
    out = ind.compute([1.0, 2.0, float("nan"), 4.0, 5.0] * 20)
    for v in out.values():
        assert v is None or math.isfinite(v)


def test_macd_nan_entries_never_emit_nan():
    closes = [100.0 + 5.0 * math.sin(i / 5.0) for i in range(80)]
    closes[30] = float("nan")
    m = ind.macd(closes)
    assert m is not None
    for v in m.values():
        assert math.isfinite(v)


# --- Inf entries --------------------------------------------------------

def test_ema_series_entries_infinite_filtered():
    out = ind.ema_series([1.0, 2.0, float("inf"), 3.0], 2)
    assert len(out) == 2
    assert all(math.isfinite(v) for v in out)


def test_sma_entries_infinite_filtered():
    out = ind.sma([1.0, float("inf"), 3.0], 2)
    assert out is not None
    assert math.isfinite(out)


def test_rsi_consecutive_infinite_spike_does_not_produce_nan():
    closes = [100.0] * 30 + [float("inf")] + [100.0] * 29
    out = ind.rsi(closes, period=14)
    assert out is not None
    assert math.isfinite(out)


def test_sigma1m_infinite_spike_does_not_produce_nan():
    closes = [100.0] * 16 + [float("inf")] + [100.0] * 16
    out = ind.sigma1m(closes)
    assert out is not None
    assert math.isfinite(out)


def test_pct_change_infinite_entry_filtered():
    out = ind.pct_change([1.0, float("inf"), 3.0], 1)
    assert out is not None
    assert math.isfinite(out)
    assert out == 200.0


def test_macd_infinite_spike_does_not_produce_nan():
    closes = [100.0] * 30 + [float("inf")] + [100.0] * 29
    m = ind.macd(closes)
    assert m is not None
    for v in m.values():
        assert math.isfinite(v)


def test_vwap_infinite_entry_filtered():
    out = ind.vwap([1.0, float("inf"), 3.0], None, 3)
    # inf dropped => only 2 points remain, below window 3 => None
    assert out is None


def test_compute_infinite_spike_never_emit_nan_or_inf():
    out = ind.compute([100.0] * 60 + [float("inf")] + [100.0] * 59)
    for v in out.values():
        assert v is None or math.isfinite(v)


# --- _rel_pct with None args -------------------------------------------

def test_rel_pct_none_a():
    assert ind._rel_pct(None, 100.0) is None


def test_rel_pct_none_b():
    assert ind._rel_pct(101.0, None) is None


def test_rel_pct_both_none():
    assert ind._rel_pct(None, None) is None


def test_rel_pct_zero_denominator():
    assert ind._rel_pct(1.0, 0.0) is None


def test_rel_pct_numeric():
    assert ind._rel_pct(110.0, 100.0) == 10.0