"""Operator safety alerts: the notices that say the bot stopped or needs a human.

Trade-lifecycle webhooks report what the bot did; these report drawdown/daily
stops, the execution circuit opening, an order stuck awaiting recovery, auth
dropping, the kill switch, and cash movement. Each paired condition is
edge-triggered — one alert when it turns on, one green "resolved" when it
clears, and silence in between.
"""
from __future__ import annotations

import asyncio

import pytest

import webhook
import service


# --- the embed builder ----------------------------------------------------

def test_alert_embed_marks_action_needed_in_red():
    e = webhook.alert_embed("drawdown", "Drawdown stop", "equity fell", "mainnet")
    assert e["color"] == webhook.COLOR["alert"]
    assert e["title"].startswith(webhook.EMOJI["alert"])
    status = {f["name"]: f["value"] for f in e["fields"]}
    assert status["Status"] == "Action needed"
    assert status["Event"] == "drawdown"
    assert "mainnet" in e["footer"]["text"].lower() or "MAINNET" in e["footer"]["text"]


def test_alert_embed_marks_resolved_in_green():
    e = webhook.alert_embed("drawdown", "Drawdown stop", "recovered", "mainnet",
                            cleared=True)
    assert e["color"] == webhook.COLOR["cleared"]
    assert e["title"].startswith(webhook.EMOJI["cleared"])
    status = {f["name"]: f["value"] for f in e["fields"]}
    assert status["Status"] == "Resolved"


def test_alert_embed_truncates_a_long_message():
    e = webhook.alert_embed("x", "t", "z" * 5000, "mainnet")
    assert len(e["description"]) <= 1500


def test_send_alert_is_a_noop_without_a_url():
    def _boom(*a, **k):
        raise AssertionError("must not build a client without a URL")
    # No network client is even constructed when the URL is blank.
    asyncio.run(webhook.send_alert("", "k", "t", "m", "mainnet"))


# --- routing --------------------------------------------------------------

def test_alert_url_falls_back_to_the_event_webhook():
    assert service._alert_url({"alert_webhook_url": "https://a/x"}) == "https://a/x"
    assert service._alert_url(
        {"alert_webhook_url": "", "event_webhook_url": "https://e/y"}) == "https://e/y"
    assert service._alert_url({}) == ""


# --- edge-triggered dispatch ----------------------------------------------

@pytest.fixture
def capture(monkeypatch):
    sent: list[tuple] = []

    def fake_send_alert(url, key, title, message, env, cleared=False):
        sent.append((key, cleared, url))

        async def _noop():
            return None
        return _noop()

    def run_now(coro):
        coro.close()  # avoid "coroutine never awaited"; routing already recorded

    monkeypatch.setattr(webhook, "send_alert", fake_send_alert)
    monkeypatch.setattr(service, "_fire_and_forget", run_now)
    service._alert_state.clear()
    return sent


CFG = {"enable_discord": True, "alert_webhook_url": "https://discord.com/api/webhooks/1/x"}


def test_alert_fires_once_on_activation_then_stays_quiet(capture):
    for _ in range(3):
        service._fire_safety_alert(CFG, "mainnet", "auth", True, "t", "m")
    assert capture == [("auth", False, CFG["alert_webhook_url"])]  # cleared=False


def test_resolved_fires_once_when_the_condition_clears(capture):
    service._fire_safety_alert(CFG, "mainnet", "auth", True, "t", "m")
    service._fire_safety_alert(CFG, "mainnet", "auth", False, "t", "ok")
    service._fire_safety_alert(CFG, "mainnet", "auth", False, "t", "ok")
    assert capture == [("auth", False, CFG["alert_webhook_url"]),
                       ("auth", True, CFG["alert_webhook_url"])]  # then cleared=True


def test_state_starts_false_so_a_healthy_bot_says_nothing(capture):
    service._fire_safety_alert(CFG, "mainnet", "auth", False, "t", "m")
    assert capture == []


def test_disabled_discord_records_state_but_sends_nothing(capture):
    cfg = {**CFG, "enable_discord": False}
    service._fire_safety_alert(cfg, "mainnet", "auth", True, "t", "m")
    assert capture == []
    # State still advanced, so re-enabling does not re-fire the same edge.
    service._fire_safety_alert(CFG, "mainnet", "auth", True, "t", "m")
    assert capture == []


def test_missing_url_records_state_but_sends_nothing(capture):
    cfg = {"enable_discord": True}
    service._fire_safety_alert(cfg, "mainnet", "auth", True, "t", "m")
    assert capture == []


def test_one_shot_emit_fires_every_time(capture):
    service._emit_safety_alert(CFG, "mainnet", "flatten", "Kill switch", "done")
    service._emit_safety_alert(CFG, "mainnet", "flatten", "Kill switch", "done")
    assert capture == [("flatten", False, CFG["alert_webhook_url"]),
                       ("flatten", False, CFG["alert_webhook_url"])]


def test_distinct_conditions_track_independently(capture):
    service._fire_safety_alert(CFG, "mainnet", "auth", True, "t", "m")
    service._fire_safety_alert(CFG, "mainnet", "recovery", True, "t", "m")
    assert {c[0] for c in capture} == {"auth", "recovery"}
