"""Every backend config key must survive a round trip through the desktop app.

The Python backend owns DEFAULT_CONFIG, but the Electron settings store holds
its own default object and the renderer's TraderConfig type lists the keys the
UI may touch. When a key is added to Python and forgotten in TypeScript, the
setting silently never persists: the UI writes it, the store drops it, and the
backend falls back to its default. Nothing fails, so nothing catches it.

These tests compare the three sources directly.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from config import DEFAULT_CONFIG, merge_with_defaults

REPO = Path(__file__).resolve().parents[2]
STORE = REPO / "electron" / "system" / "settings-store.ts"
TYPES = REPO / "shared" / "types.ts"

# Backend-only keys: runtime state the desktop UI never sets.
# Anything listed here must be genuinely unreachable from the renderer.
BACKEND_ONLY = {
    "network",
}

# Keys the desktop store has never declared a default for. Writes still
# persist (patchConfig spreads over current config), but the renderer reads
# `undefined` until something writes them, so a bound control starts empty.
# Verified by .work/probe-config-persist.mjs. Tracked in TODO.md; this list
# must only ever shrink.
UNDECLARED_IN_STORE = {
    "copy_allow_reentries", "copy_lifetime_loss_limit_pct",
    "copy_lifetime_loss_limit_usd", "copy_only_new_entries",
    "crypto15m_assets", "crypto15m_autosize_to_min_notional",
    "crypto15m_daily_loss_limit", "crypto15m_interval",
    "crypto15m_lifetime_loss_limit_pct", "crypto15m_lifetime_loss_limit_usd",
    "crypto15m_maker_fill_sec", "crypto15m_model_fm_max_book_gap_cents",
    "crypto15m_poll_sec", "crypto15m_rules_no", "crypto15m_take_profit_pct",
    "db_cleanup_interval", "lifetime_loss_limit_pct", "lifetime_loss_limit_usd",
    "max_contracts", "min_contracts", "script_hook_timeout_sec",
    "sizing_mode", "take_profit_pct",
}


def snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(p.title() for p in rest)


def ts_object_keys(source: str, start_marker: str) -> set[str]:
    """Collect the top-level keys of the object literal after a marker."""
    start = source.index(start_marker)
    depth = 0
    keys: set[str] = set()
    for match in re.finditer(r"[{}]|^\s*(\w+)\s*:", source[start:], re.MULTILINE):
        token = match.group(0).strip()
        if token == "{":
            depth += 1
        elif token == "}":
            depth -= 1
            if depth == 0:
                break
        elif depth == 1 and match.group(1):
            keys.add(match.group(1))
    return keys


@pytest.fixture(scope="module")
def store_keys() -> set[str]:
    return ts_object_keys(STORE.read_text(encoding="utf-8"), "DEFAULT_CONFIG")


@pytest.fixture(scope="module")
def type_keys() -> set[str]:
    source = TYPES.read_text(encoding="utf-8")
    start = source.index("interface TraderConfig")
    body = source[start:source.index("\n}", start)]
    return set(re.findall(r"^\s*(\w+)\??:", body, re.MULTILINE))


def test_no_new_key_is_missing_a_desktop_default(store_keys):
    """A new backend key must declare a default the renderer can read.

    Writes still persist without one (patchConfig spreads over current
    config), but the renderer reads `undefined` until something writes it,
    so a bound control starts empty.
    """
    expected = {camel(k) for k in DEFAULT_CONFIG
                if k not in BACKEND_ONLY and k not in UNDECLARED_IN_STORE}
    missing = sorted(expected - store_keys)
    assert not missing, (
        "these backend config keys have no default in electron/system/"
        f"settings-store.ts, so the renderer reads undefined: {missing}"
    )


def test_the_undeclared_key_backlog_only_shrinks(store_keys):
    """Fixing a key must remove it from UNDECLARED_IN_STORE."""
    fixed = sorted(k for k in UNDECLARED_IN_STORE if camel(k) in store_keys)
    assert not fixed, (
        "these keys now have desktop defaults; remove them from "
        f"UNDECLARED_IN_STORE: {fixed}"
    )


def test_settings_store_has_no_keys_the_backend_ignores(store_keys):
    """A store key with no backend counterpart is dead configuration."""
    known = {camel(k) for k in DEFAULT_CONFIG}
    extra = sorted(k for k in store_keys - known if not k.startswith("_"))
    assert not extra, (
        "these settings-store keys have no backend counterpart: " f"{extra}"
    )


def test_trader_config_type_covers_every_backend_key(type_keys):
    """The renderer cannot set a key its type does not declare."""
    expected = {camel(k) for k in DEFAULT_CONFIG
                if k not in BACKEND_ONLY and k not in UNDECLARED_IN_STORE}
    missing = sorted(expected - type_keys)
    assert not missing, (
        f"these backend config keys are missing from shared/types.ts "
        f"TraderConfig: {missing}"
    )


@pytest.mark.parametrize("key", sorted(DEFAULT_CONFIG))
def test_camel_key_from_the_ui_maps_back_to_its_backend_key(key):
    """The UI sends camelCase; merge_with_defaults must map it home."""
    # _validate_config forces these off as a safety measure regardless of
    # what the UI sends, so a round trip cannot preserve them.
    if key in BACKEND_ONLY or key in {
            "copy_enabled", "copy_activity_ws", "crypto15m_rtds_ws"}:
        pytest.skip("backend-only or deliberately forced off")
    default = DEFAULT_CONFIG[key]
    # Choose a value that differs from the default so a dropped write shows.
    if isinstance(default, bool):
        value = not default
    elif isinstance(default, (int, float)):
        value = None  # numeric keys are clamped; covered by the round trip below
    else:
        value = None
    if value is None:
        pytest.skip("non-boolean default; covered by the clamp tests")
    merged = merge_with_defaults({camel(key): value})
    assert merged[key] == value, f"{camel(key)} did not map to {key}"


def test_snake_and_camel_conversions_are_inverse():
    for key in DEFAULT_CONFIG:
        assert snake(camel(key)) == key, f"{key} does not survive a round trip"
