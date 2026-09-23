from __future__ import annotations

import pytest

import polymarket_api
import service
import us_market_stream


@pytest.mark.asyncio
async def test_rejected_key_surfaces_the_actual_blocker(monkeypatch):
    async def rejected():
        raise polymarket_api.PolymarketAPIError(
            401, "Unauthorized", detail="API key not found",
        )

    monkeypatch.setattr(polymarket_api, "ensure_api_creds", rejected)
    monkeypatch.setattr(service.polymarket_auth, "prime_credentials", lambda **_: True)
    assert await service._establish_auth(retries=1) is False
    assert "does not recognize the saved API key" in service.STATE.auth_error
    assert service._auth_event()["authError"] == service.STATE.auth_error


@pytest.mark.asyncio
async def test_credential_preflight_returns_actionable_rejection(monkeypatch):
    async def rejected():
        raise polymarket_api.PolymarketAPIError(
            401, "Unauthorized", detail="API key not found",
        )

    async def no_op(*_args):
        return None

    monkeypatch.setattr(service.polymarket_auth, "credentials_present", lambda *_: True)
    monkeypatch.setattr(service.polymarket_auth, "reset_credential_cache", lambda: None)
    monkeypatch.setattr(service.polymarket_auth, "prime_credentials", lambda **_: True)
    monkeypatch.setattr(polymarket_api, "check_trading_ready", rejected)
    monkeypatch.setattr(service.us_market_stream, "pause_for_auth", lambda: None)
    monkeypatch.setattr(service.us_market_stream, "stop", no_op)
    monkeypatch.setattr(service.us_account_stream, "stop", no_op)
    monkeypatch.setattr(service, "emit_event", no_op)
    monkeypatch.setattr(service.STATE, "auth_ok", True)
    monkeypatch.setattr(service.STATE, "auth_error", "")

    with pytest.raises(ValueError, match="Create a new Key ID and Secret Key"):
        await service._h_testCredentials({})
    assert service.STATE.auth_ok is False


@pytest.mark.asyncio
async def test_successful_auth_clears_a_previous_rejection(monkeypatch):
    async def accepted():
        return None

    async def balance():
        return {"balance": 315, "portfolio_value": 0}

    monkeypatch.setattr(polymarket_api, "ensure_api_creds", accepted)
    monkeypatch.setattr(service.polymarket_auth, "prime_credentials", lambda **_: True)
    monkeypatch.setattr(polymarket_api, "get_balance", balance)
    monkeypatch.setattr(service, "_reconcile_signature_type", accepted)
    service.STATE.auth_error = "old rejection"
    assert await service._establish_auth(retries=1) is True
    assert service.STATE.auth_error == ""


def test_paused_stream_stays_paused_when_scanner_requests_recent_trades(monkeypatch):
    monkeypatch.setattr(us_market_stream.auth, "credentials_present", lambda: True)
    us_market_stream.pause_for_auth()
    try:
        us_market_stream.start()
        assert us_market_stream._task is None
    finally:
        us_market_stream.resume_after_auth()
