from __future__ import annotations

import asyncio
import json

import pytest

import service


def _mangled(src: str) -> str:
    return src.encode("utf-8").decode("cp1252", "surrogateescape")


GOOD = 'def decide(ctx):\n    return None  # smart quote ” here\n'
BAD = _mangled(GOOD)


def test_the_fixture_really_contains_a_lone_surrogate():
    assert any(0xDC80 <= ord(c) <= 0xDCFF for c in BAD)
    with pytest.raises(UnicodeEncodeError):
        BAD.encode("utf-8")


def test_sanitizer_makes_it_serializable():
    clean = service._sanitize_script_code(BAD)
    clean.encode("utf-8")
    json.dumps({"code": clean}).encode("utf-8")
    assert not any(0xDC80 <= ord(c) <= 0xDCFF for c in clean)


def test_sanitizer_leaves_ordinary_code_untouched():
    src = "def decide(ctx):\n    return None\n"
    assert service._sanitize_script_code(src) == src


def test_sanitizer_preserves_legitimate_unicode():
    src = "# strategy — notes\ndef decide(ctx):\n    return None\n"
    assert service._sanitize_script_code(src) == src


@pytest.mark.parametrize("value", [None, "", 0])
def test_sanitizer_handles_empty_input(value):
    assert service._sanitize_script_code(value) == ""


def test_validate_rpc_survives_a_mangled_paste():
    res = asyncio.run(service._h_script_validate({"code": BAD}))
    json.dumps(res).encode("utf-8")
    assert isinstance(res["ok"], bool)
    assert isinstance(res["errors"], list)


def test_mangled_paste_in_actual_CODE_reports_a_normal_error():
    src = 'def decide(ctx):\n    return “hello”\n'
    res = asyncio.run(service._h_script_validate({"code": _mangled(src)}))
    json.dumps(res).encode("utf-8")
    assert res["ok"] is False
    assert res["errors"] and "line" in res["errors"][0].lower()


def test_save_rpc_survives_a_mangled_paste(tmp_path, monkeypatch):
    import db

    dbfile = tmp_path / "paste.db"
    monkeypatch.setattr(db, "db_path", lambda: dbfile)
    db.init_db()

    res = asyncio.run(service._h_script_save({"code": BAD}))
    json.dumps(res).encode("utf-8")
    assert res["script"]["id"]

    listing = asyncio.run(service._h_scripts_list({}))
    json.dumps(listing).encode("utf-8")


def test_sqlite_itself_rejects_surrogates(tmp_path, monkeypatch):
    import db

    dbfile = tmp_path / "legacy.db"
    monkeypatch.setattr(db, "db_path", lambda: dbfile)
    db.init_db()
    with pytest.raises(UnicodeEncodeError):
        with db.get_db() as conn:
            db.upsert_user_script(conn, {
                "id": "legacy", "name": "legacy", "description": "",
                "code": BAD, "notes": "",
            })
