from __future__ import annotations

import instance_lock as il


def test_claim_and_refresh_by_same_holder(tmp_path, monkeypatch):
    monkeypatch.setattr(il, "_lock_dir", lambda: tmp_path / "locks")
    assert il.claim("0xWALLET") is True
    assert il.claim("0xWALLET") is True
    assert il.foreign_holder("0xWALLET") == ""


def test_second_instance_blocked_until_stale(tmp_path, monkeypatch):
    monkeypatch.setattr(il, "_lock_dir", lambda: tmp_path / "locks")
    assert il.claim("0xW") is True
    monkeypatch.setattr(il, "_HOLDER_ID", "other-pid-999")
    assert il.claim("0xW") is False
    assert il.foreign_holder("0xW") != ""
    assert il.claim("0xW", stale_sec=0.0) is True


def test_release_frees_the_wallet(tmp_path, monkeypatch):
    monkeypatch.setattr(il, "_lock_dir", lambda: tmp_path / "locks")
    assert il.claim("0xW") is True
    il.release("0xW")
    monkeypatch.setattr(il, "_HOLDER_ID", "other")
    assert il.claim("0xW") is True


def test_empty_address_is_fail_open(tmp_path, monkeypatch):
    monkeypatch.setattr(il, "_lock_dir", lambda: tmp_path / "locks")
    assert il.claim("") is True
    assert il.foreign_holder("") == ""
