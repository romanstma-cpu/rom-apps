from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import time
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

_STALE_SEC = 120.0

_HOLDER_ID = f"{os.getpid()}-{uuid.uuid4().hex[:8]}"


def _lock_dir() -> Path:
    return Path(tempfile.gettempdir()) / "rom-polybot-locks"


def _lock_file(key: str) -> Path:
    h = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    return _lock_dir() / f"{h}.lock"


def claim(key: str, *, stale_sec: float = _STALE_SEC) -> bool:
    if not key:
        return True
    try:
        f = _lock_file(key)
        now = time.time()
        holder = None
        ts = 0.0
        if f.exists():
            try:
                data = json.loads(f.read_text("utf-8"))
                holder = data.get("holder")
                ts = float(data.get("ts") or 0.0)
            except Exception:
                holder, ts = None, 0.0
        if holder and holder != _HOLDER_ID and (now - ts) < stale_sec:
            return False
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".lock.tmp")
        tmp.write_text(
            json.dumps({"holder": _HOLDER_ID, "ts": now, "pid": os.getpid()}),
            "utf-8",
        )
        tmp.replace(f)
        return True
    except Exception as e:
        logger.debug(f"instance_lock claim error (fail-open): {e}")
        return True


def foreign_holder(key: str, *, stale_sec: float = _STALE_SEC) -> str:
    if not key:
        return ""
    try:
        f = _lock_file(key)
        if not f.exists():
            return ""
        data = json.loads(f.read_text("utf-8"))
        holder = data.get("holder")
        ts = float(data.get("ts") or 0.0)
        if holder and holder != _HOLDER_ID and (time.time() - ts) < stale_sec:
            return str(data.get("pid") or holder)
        return ""
    except Exception:
        return ""


def release(key: str) -> None:
    if not key:
        return
    try:
        f = _lock_file(key)
        if f.exists():
            data = json.loads(f.read_text("utf-8"))
            if data.get("holder") == _HOLDER_ID:
                f.unlink()
    except Exception:
        pass
