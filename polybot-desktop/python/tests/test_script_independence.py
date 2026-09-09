from __future__ import annotations

import pytest

import script_backtest
import script_engine


def test_no_scope_means_every_coin():
    for asset in ("BTC", "ETH", "SOL", "XRP", "DOGE", "HYPE", "BNB"):
        assert script_engine.script_allows_asset(None, asset)
        assert script_engine.script_allows_asset([], asset)


def test_a_scope_restricts_to_its_own_coins():
    scope = script_backtest.parse_asset_scope(["BTC", "eth"])
    assert scope == ["BTC", "ETH"]
    assert script_engine.script_allows_asset(scope, "BTC")
    assert script_engine.script_allows_asset(scope, "eth")
    assert not script_engine.script_allows_asset(scope, "SOL")


@pytest.mark.parametrize("raw,expect", [
    (None, None),
    ([], None),
    ("", None),
    ('["BTC","ETH"]', ["BTC", "ETH"]),
    ("BTC, ETH", ["BTC", "ETH"]),
    (["btc", "BTC", " btc "], ["BTC"]),
    (42, None),
])
def test_asset_scope_parsing(raw, expect):
    assert script_backtest.parse_asset_scope(raw) == expect


def test_scope_ignores_the_crypto_engines_asset_setting():
    import crypto15m
    cfg = {"crypto15m_assets": ["BTC"]}
    assert not crypto15m.asset_enabled(cfg, "SOL")
    assert script_engine.script_allows_asset(None, "SOL")


def test_neither_engine_module_reads_crypto15m_assets_for_scripts():
    import inspect
    for mod in (script_engine, script_backtest):
        src = inspect.getsource(mod)
        assert "crypto15m.asset_enabled(" not in src, mod.__name__


def test_signal_feed_is_not_requested_when_no_script_wants_it(monkeypatch):
    monkeypatch.setattr(script_engine, "_enabled_hooks", set(), raising=False)
    assert script_engine.needs_signal_feed() is False


def test_signal_feed_is_requested_for_a_decide_signal_script(monkeypatch):
    import time
    monkeypatch.setattr(script_engine, "_enabled_hooks", {"decide_signal"},
                        raising=False)
    monkeypatch.setattr(script_engine, "_enabled_hooks_at", time.time(),
                        raising=False)
    assert script_engine.needs_signal_feed() is True


def test_a_decide_only_script_does_not_hold_the_signal_feed_up(monkeypatch):
    import time
    monkeypatch.setattr(script_engine, "_enabled_hooks", {"decide", "manage"},
                        raising=False)
    monkeypatch.setattr(script_engine, "_enabled_hooks_at", time.time(),
                        raising=False)
    assert script_engine.needs_signal_feed() is False


def test_a_stale_hook_census_stops_asserting_itself(monkeypatch):
    import time
    monkeypatch.setattr(script_engine, "_enabled_hooks", {"decide_signal"},
                        raising=False)
    monkeypatch.setattr(
        script_engine, "_enabled_hooks_at",
        time.time() - script_engine._HOOKS_TTL_S - 1, raising=False)
    assert script_engine.needs_signal_feed() is False


def test_the_service_loop_actually_consults_it():
    import inspect
    import service
    src = inspect.getsource(service)
    assert "script_engine.needs_signal_feed()" in src


def test_the_service_loop_no_longer_gates_the_tick_on_the_master_switch():
    import inspect
    import re
    import service
    src = inspect.getsource(service)
    tick = src[src.index("# ── User-script executor"):]
    tick = tick[:tick.index("# ── Copy-trading executor")]
    guard = tick[tick.index("if ("):tick.index("await script_engine.run_tick")]
    assert "scripts_live_enabled" not in guard, guard


def test_run_tick_parks_an_armed_script_when_the_master_switch_is_off():
    import inspect
    src = inspect.getsource(script_engine.run_tick)
    assert 'if not live_ok:' in src
    assert '_gate(str(s["id"]), "master_off")' in src
    assert 'enabled = [s for s in enabled if s.get("dry_run")]' in src
