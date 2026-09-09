from __future__ import annotations

import asyncio

import service


DEP = "0xDDDD000000000000000000000000000000000009"


def _wire(monkeypatch, *, funder, stored, detected):
    written: list[tuple[str, int]] = []
    service._sig_type_reconciled = False

    monkeypatch.setattr(service.polymarket_auth, "get_funder", lambda env=None: funder)
    monkeypatch.setattr(service.polymarket_auth, "get_signature_type", lambda env=None: stored)
    monkeypatch.setattr(
        service.polymarket_auth, "set_wallet_meta",
        lambda funder="", signature_type=0, env=None: written.append((funder, signature_type)),
    )

    async def _detect():
        if isinstance(detected, Exception):
            raise detected
        return detected
    monkeypatch.setattr(service.polymarket_api, "detect_wallet_signature_type", _detect)
    return written


def test_corrupt_type_1_is_repaired_to_3_on_connect(monkeypatch):
    written = _wire(monkeypatch, funder=DEP, stored=1, detected=3)
    asyncio.run(service._reconcile_signature_type())
    assert written == [(DEP, 3)]


def test_correct_type_is_left_alone(monkeypatch):
    written = _wire(monkeypatch, funder=DEP, stored=3, detected=3)
    asyncio.run(service._reconcile_signature_type())
    assert written == []


def test_genuine_poly_proxy_is_preserved(monkeypatch):
    written = _wire(monkeypatch, funder=DEP, stored=1, detected=1)
    asyncio.run(service._reconcile_signature_type())
    assert written == []


def test_abstain_never_overwrites_stored_type(monkeypatch):
    written = _wire(monkeypatch, funder=DEP, stored=3, detected=None)
    asyncio.run(service._reconcile_signature_type())
    assert written == []
    assert service._sig_type_reconciled is False


def test_detection_failure_is_swallowed_and_never_blocks_auth(monkeypatch):
    written = _wire(monkeypatch, funder=DEP, stored=3, detected=RuntimeError("rpc down"))
    asyncio.run(service._reconcile_signature_type())
    assert written == []


def test_raw_eoa_wallet_skips_detection(monkeypatch):
    written = _wire(monkeypatch, funder="", stored=0, detected=3)
    asyncio.run(service._reconcile_signature_type())
    assert written == []


def test_runs_at_most_once_per_launch(monkeypatch):
    written = _wire(monkeypatch, funder=DEP, stored=1, detected=3)
    asyncio.run(service._reconcile_signature_type())
    asyncio.run(service._reconcile_signature_type())
    assert written == [(DEP, 3)]


def test_a_failed_detection_retries_on_the_next_connect(monkeypatch):
    written = _wire(monkeypatch, funder=DEP, stored=1, detected=RuntimeError("rpc down"))
    asyncio.run(service._reconcile_signature_type())
    assert service._sig_type_reconciled is False

    written2 = _wire(monkeypatch, funder=DEP, stored=1, detected=3)
    asyncio.run(service._reconcile_signature_type())
    assert written2 == [(DEP, 3)]
