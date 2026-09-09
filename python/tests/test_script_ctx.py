from __future__ import annotations

import pytest

import crypto15m
import replay
import script_docs


def _asset(**over) -> dict:
    a = {
        "asset": "BTC", "ticker": "tk", "favorite": "up",
        "yesBid": 0.55, "yesAsk": 0.60, "upProb": 0.575,
        "upAsk": 0.61, "downAsk": 0.41, "modelProb": 0.62,
        "minsLeft": 3.0,
    }
    a.update(over)
    return a


def test_spread_cents_is_the_book_width():
    a = _asset()
    crypto15m.derive_script_fields(a)
    assert a["spreadCents"] == pytest.approx(5.0)


def test_model_edge_points_are_signed():
    up = _asset(modelProb=0.62, upProb=0.575)
    crypto15m.derive_script_fields(up)
    assert up["modelEdgePts"] == pytest.approx(4.5)

    down = _asset(modelProb=0.50, upProb=0.575)
    crypto15m.derive_script_fields(down)
    assert down["modelEdgePts"] == pytest.approx(-7.5)


@pytest.mark.parametrize("fav,expected", [
    ("up", 61.0),
    ("down", 41.0),
    (None, None),
])
def test_favorite_ask_follows_the_favorite_side(fav, expected):
    a = _asset(favorite=fav)
    crypto15m.derive_script_fields(a)
    assert a["favoriteAskCents"] == expected


def test_favorite_ask_is_none_when_that_side_has_no_real_book():
    a = _asset(favorite="up", upAsk=None)
    crypto15m.derive_script_fields(a)
    assert a["favoriteAskCents"] is None


@pytest.mark.parametrize("interval,mins,expected", [
    ("15m", 3.0, 0.2),
    ("5m", 2.5, 0.5),
    ("1h", 30.0, 0.5),
    ("hourly", 15.0, 0.25),
])
def test_time_frac_left_normalizes_across_intervals(interval, mins, expected):
    a = _asset(minsLeft=mins)
    crypto15m.derive_script_fields(a, interval)
    assert a["timeFracLeft"] == pytest.approx(expected)


def test_time_frac_left_is_clamped():
    a = _asset(minsLeft=99.0)
    crypto15m.derive_script_fields(a, "15m")
    assert a["timeFracLeft"] == 1.0


@pytest.mark.parametrize("missing", [
    "yesBid", "yesAsk", "upProb", "modelProb", "minsLeft",
])
def test_missing_inputs_yield_none_never_a_crash(missing):
    a = _asset(**{missing: None})
    crypto15m.derive_script_fields(a, "15m")
    assert set(("spreadCents", "modelEdgePts", "favoriteAskCents",
                "timeFracLeft")) <= set(a)


def test_an_empty_asset_gets_every_field_as_none():
    a: dict = {}
    crypto15m.derive_script_fields(a, "15m")
    assert a == {"spreadCents": None, "modelEdgePts": None,
                 "favoriteAskCents": None, "timeFracLeft": None}


DERIVED = ("spreadCents", "modelEdgePts", "favoriteAskCents", "timeFracLeft")


def test_replay_produces_the_same_derived_fields_as_live():
    tick = {
        "asset": "BTC", "ticker": "tk", "yes_bid": 0.55, "yes_ask": 0.60,
        "up_prob": 0.575, "up_ask": 0.61, "no_ask": 0.41, "ws_ask": 60.0,
        "model_prob": 0.62, "mins_left": 3.0, "spot_source": "rtds-ws",
    }
    cfg = {"crypto15m_interval": "15m"}
    replayed = replay.tick_to_asset(tick, cfg, "2026-07-24T12:15:00Z")

    live = _asset()
    crypto15m.derive_script_fields(live, "15m")

    for f in DERIVED:
        assert replayed[f] == live[f], f"{f} differs between replay and live"


def test_every_derived_field_is_marked_backtestable():
    for f in DERIVED:
        assert f in replay._DERIVABLE


def test_every_derived_field_is_documented():
    for f in DERIVED:
        assert f in script_docs.FIELD_DOCS, f"{f} is invisible to script authors"


def test_documented_live_only_fields_are_really_not_derivable():
    for f in script_docs.LIVE_ONLY_FIELDS:
        assert f not in replay._DERIVABLE


def test_no_documented_field_is_silently_missing_from_the_derivable_set():
    undocumented_gap = (
        set(script_docs.FIELD_DOCS)
        - set(replay._DERIVABLE)
        - set(script_docs.LIVE_ONLY_FIELDS)
        - {"portfolio"}
    )
    assert undocumented_gap == set()
