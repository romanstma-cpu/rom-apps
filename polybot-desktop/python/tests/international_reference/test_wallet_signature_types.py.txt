from __future__ import annotations

import asyncio

import pytest

import polymarket_auth as auth
import polymarket_api as api


class _FakeAcct:
    address = "0xEEEE000000000000000000000000000000000001"


PROXY = "0xDDDD000000000000000000000000000000000009"


def _wire_sign(monkeypatch, sig_type, funder):
    monkeypatch.setattr(auth, "get_signature_type", lambda env=None: sig_type)
    monkeypatch.setattr(auth, "get_funder", lambda env=None: funder)
    monkeypatch.setattr(auth, "_load_account", lambda: _FakeAcct())
    monkeypatch.setattr(auth, "_eip712_sign", lambda typed: "0xsig")


def test_poly_proxy_order_puts_eoa_in_signer_and_proxy_in_maker(monkeypatch):
    _wire_sign(monkeypatch, auth.SIGNATURE_TYPE_POLY_PROXY, PROXY)
    o = auth.create_signed_order(token_id="123", side="BUY", price=0.5, size=10)
    assert o["maker"] == PROXY
    assert o["signer"] == _FakeAcct.address
    assert o["signatureType"] == 1
    assert o["signature"] == "0xsig"


def test_gnosis_safe_order_signature_type_2(monkeypatch):
    _wire_sign(monkeypatch, auth.SIGNATURE_TYPE_POLY_GNOSIS_SAFE, PROXY)
    o = auth.create_signed_order(token_id="123", side="BUY", price=0.5, size=10)
    assert o["maker"] == PROXY and o["signer"] == _FakeAcct.address
    assert o["signatureType"] == 2


def test_raw_eoa_unchanged_maker_equals_signer(monkeypatch):
    _wire_sign(monkeypatch, auth.SIGNATURE_TYPE_EOA, "")
    o = auth.create_signed_order(token_id="123", side="BUY", price=0.5, size=10)
    assert o["maker"] == _FakeAcct.address == o["signer"]
    assert o["signatureType"] == 0


def test_manual_salt_fits_signed_int64(monkeypatch):
    _wire_sign(monkeypatch, auth.SIGNATURE_TYPE_POLY_PROXY, PROXY)
    for i in range(2000):
        o = auth.create_signed_order(
            token_id=str(10**40 + i), side="BUY", price=0.5, size=10
        )
        salt = o["salt"]
        assert 0 <= salt < (1 << 53), f"salt out of safe range: {salt}"


def test_poly_1271_still_delegates_to_1271_path(monkeypatch):
    _wire_sign(monkeypatch, auth.SIGNATURE_TYPE_POLY_1271, PROXY)
    sentinel = {"maker": PROXY, "signer": PROXY, "signatureType": 3}
    monkeypatch.setattr(auth, "_create_signed_order_1271", lambda **k: sentinel)
    o = auth.create_signed_order(token_id="123", side="BUY", price=0.5, size=10)
    assert o is sentinel


EOA = "0xaaaa000000000000000000000000000000000001"
DEP = "0xbbbb000000000000000000000000000000000002"
_MINIMAL_PROXY = ("0x363d3d373d3d3d363d73"
                  + "44e999d5c2f66ef0861317f9a4805ac2e90aeb4f"
                  + "5af43d82803e903d91602b57fd5bf3")


def _wire_detect(monkeypatch, *, funder, eoa, rpc):
    monkeypatch.setattr(api.auth, "get_funder", lambda: funder)
    monkeypatch.setattr(api.auth, "get_address", lambda: eoa)

    async def _rpc(method, params):
        return rpc(method, params)
    monkeypatch.setattr(api, "_rpc_first", _rpc)


def _run():
    return asyncio.run(api.detect_wallet_signature_type())


def test_detect_no_funder_is_eoa(monkeypatch):
    _wire_detect(monkeypatch, funder="", eoa=EOA, rpc=lambda m, p: None)
    assert _run() == auth.SIGNATURE_TYPE_EOA


def test_detect_funder_equals_eoa_is_eoa(monkeypatch):
    _wire_detect(monkeypatch, funder=EOA, eoa=EOA, rpc=lambda m, p: None)
    assert _run() == auth.SIGNATURE_TYPE_EOA


def test_detect_undeployed_funder_returns_none(monkeypatch):
    _wire_detect(monkeypatch, funder=DEP, eoa=EOA,
                 rpc=lambda m, p: "0x" if m == "eth_getCode" else None)
    assert _run() is None


def test_detect_magic_proxy_is_poly_proxy(monkeypatch):
    def rpc(m, p):
        if m == "eth_getCode":
            addr = p[0].lower()
            if addr == DEP.lower():
                return _MINIMAL_PROXY
            return "0x60806040"
        return None
    _wire_detect(monkeypatch, funder=DEP, eoa=EOA, rpc=rpc)
    assert _run() == auth.SIGNATURE_TYPE_POLY_PROXY


def test_detect_impl_read_failure_abstains_not_downgrade(monkeypatch):
    def rpc(m, p):
        if m == "eth_getCode":
            addr = p[0].lower()
            if addr == DEP.lower():
                return _MINIMAL_PROXY
            return None
        return None
    _wire_detect(monkeypatch, funder=DEP, eoa=EOA, rpc=rpc)
    assert _run() is None


def test_detect_impl_read_empty_abstains_not_downgrade(monkeypatch):
    def rpc(m, p):
        if m == "eth_getCode":
            addr = p[0].lower()
            if addr == DEP.lower():
                return _MINIMAL_PROXY
            return "0x"
        return None
    _wire_detect(monkeypatch, funder=DEP, eoa=EOA, rpc=rpc)
    assert _run() is None


def test_detect_gnosis_safe_is_type_2(monkeypatch):
    owners = ("0x" + "0" * 62 + "20" + "0" * 63 + "1"
              + "0" * 24 + EOA[2:])
    def rpc(m, p):
        if m == "eth_getCode":
            return "0x60806040contractcode"
        if m == "eth_call":
            return owners
        return None
    _wire_detect(monkeypatch, funder=DEP, eoa=EOA, rpc=rpc)
    assert _run() == auth.SIGNATURE_TYPE_POLY_GNOSIS_SAFE


def test_detect_1271_wallet_is_type_3(monkeypatch):
    def rpc(m, p):
        if m == "eth_getCode":
            return "0x6080" + "1626ba7e" + "0000"
        return None
    _wire_detect(monkeypatch, funder=DEP, eoa=EOA, rpc=rpc)
    assert _run() == auth.SIGNATURE_TYPE_POLY_1271


_SLOT_PROXY = (
    "0x363d3d373d3d363d7f"
    "360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"
    "545af43d6000803e6038573d6000fd5b3d6000f3"
)
IMPL = "0x58ca52ebe0dadfdf531cde7062e76746de4db1eb"


def test_detect_gmail_slot_proxy_over_1271_impl_is_type_3(monkeypatch):
    def rpc(m, p):
        if m == "eth_getCode":
            addr = p[0].lower()
            if addr == DEP.lower():
                return _SLOT_PROXY
            if addr == IMPL:
                return "0x6080" + "1626ba7e" + "0000"
        if m == "eth_getStorageAt":
            return "0x" + "0" * 24 + IMPL[2:]
        return None
    _wire_detect(monkeypatch, funder=DEP, eoa=EOA, rpc=rpc)
    assert _run() == auth.SIGNATURE_TYPE_POLY_1271


def test_detect_slot_proxy_over_plain_impl_is_poly_proxy(monkeypatch):
    def rpc(m, p):
        if m == "eth_getCode":
            addr = p[0].lower()
            if addr == DEP.lower():
                return _SLOT_PROXY
            if addr == IMPL:
                return "0x60806040"
        if m == "eth_getStorageAt":
            return "0x" + "0" * 24 + IMPL[2:]
        return None
    _wire_detect(monkeypatch, funder=DEP, eoa=EOA, rpc=rpc)
    assert _run() == auth.SIGNATURE_TYPE_POLY_PROXY


def test_detect_unrecognised_contract_abstains(monkeypatch):
    def rpc(m, p):
        if m == "eth_getCode":
            return "0x60806040deadbeef"
        return None
    _wire_detect(monkeypatch, funder=DEP, eoa=EOA, rpc=rpc)
    assert _run() is None


def test_detect_empty_1967_slot_does_not_crash(monkeypatch):
    def rpc(m, p):
        if m == "eth_getCode":
            return "0x60806040"
        if m == "eth_getStorageAt":
            return "0x" + "0" * 64
        return None
    _wire_detect(monkeypatch, funder=DEP, eoa=EOA, rpc=rpc)
    assert _run() is None


def _wire_authz(monkeypatch, *, funder, signer, rpc):
    monkeypatch.setattr(api.auth, "get_funder", lambda env=None: funder)
    monkeypatch.setattr(api.auth, "get_address", lambda env=None: signer)

    async def _rpc(method, params):
        return rpc(method, params)
    monkeypatch.setattr(api, "_rpc_first", _rpc)
    return asyncio.run(api.check_deposit_wallet_authorization())


def _word(addr):
    return "0x" + addr[2:].lower().rjust(64, "0")


def test_authz_owner_matches_signer(monkeypatch):
    out = _wire_authz(monkeypatch, funder=DEP, signer=EOA,
                      rpc=lambda m, p: _word(EOA))
    assert out["ok"] is True and out["tested"] is True


def test_authz_owner_mismatch_is_a_positive_reject(monkeypatch):
    other = "0xCCCC000000000000000000000000000000000003"

    def rpc(m, p):
        data = p[0]["data"]
        if data == api._SEL_OWNER:
            return _word(other)
        return "0x" + "0" * 64
    out = _wire_authz(monkeypatch, funder=DEP, signer=EOA, rpc=rpc)
    assert out["ok"] is False and out["tested"] is True
    assert other[:6].lower() in out["reason"].lower()


def test_authz_session_signer_rescues_a_non_owner(monkeypatch):
    other = "0xCCCC000000000000000000000000000000000003"
    far_future = hex(2_000_000_000)[2:].rjust(64, "0")

    def rpc(m, p):
        data = p[0]["data"]
        if data == api._SEL_OWNER:
            return _word(other)
        return "0x" + far_future
    out = _wire_authz(monkeypatch, funder=DEP, signer=EOA, rpc=rpc)
    assert out["ok"] is True and out["tested"] is True


def test_authz_expired_session_signer_still_rejects(monkeypatch):
    other = "0xCCCC000000000000000000000000000000000003"
    past = hex(1_000_000_000)[2:].rjust(64, "0")

    def rpc(m, p):
        if p[0]["data"] == api._SEL_OWNER:
            return _word(other)
        return "0x" + past
    out = _wire_authz(monkeypatch, funder=DEP, signer=EOA, rpc=rpc)
    assert out["ok"] is False


def test_authz_legacy_proxy_without_owner_abstains(monkeypatch):
    out = _wire_authz(monkeypatch, funder=DEP, signer=EOA, rpc=lambda m, p: None)
    assert out["ok"] is True and out["tested"] is False


def test_authz_zero_owner_abstains(monkeypatch):
    out = _wire_authz(monkeypatch, funder=DEP, signer=EOA,
                      rpc=lambda m, p: "0x" + "0" * 64)
    assert out["ok"] is True and out["tested"] is False


def test_authz_no_funder_abstains(monkeypatch):
    out = _wire_authz(monkeypatch, funder="", signer=EOA, rpc=lambda m, p: None)
    assert out["ok"] is True and out["tested"] is False


def _meta_at(monkeypatch, tmp_path, text=None):
    f = tmp_path / "wallet.mainnet.meta.json"
    if text is not None:
        f.write_text(text, encoding="utf-8")
    monkeypatch.setattr(auth, "_wallet_meta_file", lambda env=None: f)
    monkeypatch.setattr(auth, "_wallet_meta_cache", {})
    return f


def test_absent_meta_is_a_raw_eoa_wallet(monkeypatch, tmp_path):
    _meta_at(monkeypatch, tmp_path)
    assert auth.get_wallet_meta() == {}
    assert auth.get_funder() == ""
    assert auth.get_signature_type() == auth.SIGNATURE_TYPE_EOA


def test_corrupt_meta_raises_rather_than_silently_downgrading(monkeypatch, tmp_path):
    _meta_at(monkeypatch, tmp_path, "{not json")
    for call in (auth.get_wallet_meta, auth.get_funder, auth.get_signature_type):
        with pytest.raises(auth.WalletMetaError):
            call()


def test_non_object_meta_raises(monkeypatch, tmp_path):
    _meta_at(monkeypatch, tmp_path, '["nope"]')
    with pytest.raises(auth.WalletMetaError):
        auth.get_wallet_meta()


def test_transient_read_failure_serves_last_known_good(monkeypatch, tmp_path):
    f = _meta_at(monkeypatch, tmp_path,
                 '{"funder": "%s", "signatureType": 3}' % DEP)
    assert auth.get_funder() == DEP

    def _boom(*_a, **_k):
        raise PermissionError("being replaced")
    monkeypatch.setattr(type(f), "read_text", _boom)

    assert auth.get_funder() == DEP
    assert auth.get_signature_type() == auth.SIGNATURE_TYPE_POLY_1271


def test_set_wallet_meta_refreshes_the_cache(monkeypatch, tmp_path):
    f = _meta_at(monkeypatch, tmp_path, '{"funder": "0xold", "signatureType": 3}')
    assert auth.get_funder() == "0xold"
    auth.set_wallet_meta(funder=DEP, signature_type=1)
    assert auth.get_funder() == DEP

    def _boom(*_a, **_k):
        raise PermissionError("being replaced")
    monkeypatch.setattr(type(f), "read_text", _boom)
    assert auth.get_funder() == DEP
    assert auth.get_signature_type() == auth.SIGNATURE_TYPE_POLY_PROXY
