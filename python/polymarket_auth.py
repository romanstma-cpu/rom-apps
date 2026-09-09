from __future__ import annotations
import base64
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional
from uuid import UUID
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
logger = logging.getLogger(__name__)
NETWORK = "mainnet"
_DPAPI_MARKER = b"#ROM-DPAPI-v1\n"
_KEYRING_MARKER = b"#ROM-KEYRING-v1\n"
_KEYRING_SERVICE = "rom-polybot"
_KEYRING_MASTER_ACCOUNT = "cred-master-key"
_warned_plaintext = False
_plaintext_error_logged = False
_keyring_master_cache = None
def _dpapi_available() -> bool:
    return sys.platform == "win32"


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_char))]

    def _to_blob(data: bytes) -> "_DATA_BLOB":
        buf = ctypes.create_string_buffer(bytes(data), len(data))
        return _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))

    def _from_blob(blob: "_DATA_BLOB") -> bytes:
        try:
            return ctypes.string_at(blob.pbData, blob.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(blob.pbData)

    def _dpapi_encrypt(data: bytes) -> bytes:
        out = _DATA_BLOB()
        blob_in = _to_blob(data)
        if not ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(out)
        ):
            raise OSError("CryptProtectData failed")
        return _from_blob(out)

    def _dpapi_decrypt(data: bytes) -> bytes:
        out = _DATA_BLOB()
        blob_in = _to_blob(data)
        if not ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(out)
        ):
            raise OSError("CryptUnprotectData failed")
        return _from_blob(out)
else:  # pragma: no cover - non-Windows fallback
    def _dpapi_encrypt(data: bytes) -> bytes:
        raise OSError("DPAPI not available")

    def _dpapi_decrypt(data: bytes) -> bytes:
        raise OSError("DPAPI not available")


def _keyring_set(account: str, value: str) -> bool:
    try:
        import keyring
        keyring.set_password(_KEYRING_SERVICE, account, value)
        return True
    except Exception:
        return False


def _keyring_get(account: str) -> Optional[str]:
    try:
        import keyring
        return keyring.get_password(_KEYRING_SERVICE, account)
    except Exception:
        return None


def _fernet(key: bytes):
    from cryptography.fernet import Fernet
    return Fernet(key)


def _get_master_key() -> Optional[bytes]:
    global _keyring_master_cache
    if _keyring_master_cache is not None:
        return _keyring_master_cache
    existing = _keyring_get(_KEYRING_MASTER_ACCOUNT)
    if existing:
        key = existing.encode("ascii")
        try:
            _fernet(key)
            _keyring_master_cache = key
            return key
        except Exception:
            logger.warning("Stored keychain master key is corrupt; regenerating.")
    from cryptography.fernet import Fernet
    key = Fernet.generate_key()
    if not _keyring_set(_KEYRING_MASTER_ACCOUNT, key.decode("ascii")):
        return None
    if _keyring_get(_KEYRING_MASTER_ACCOUNT) != key.decode("ascii"):
        return None
    _keyring_master_cache = key
    return key


def _keyring_available() -> bool:
    return _get_master_key() is not None


def _keyring_encrypt(data: bytes) -> bytes:
    key = _get_master_key()
    if key is None:
        raise OSError("no OS keychain backend available")
    return _fernet(key).encrypt(data)


def _keyring_decrypt(token: bytes) -> bytes:
    key = _get_master_key()
    if key is None:
        raise OSError("no OS keychain backend available")
    return _fernet(key).decrypt(token)


def _chmod_600(path: Path) -> None:
    if os.name == "posix":
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


def _atomic_write_600(path: Path, tmp: Path, data: bytes) -> None:
    try:
        if tmp.exists():
            tmp.unlink()
    except OSError:
        pass
    if os.name == "posix":
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
    else:
        tmp.write_bytes(data)
    _chmod_600(tmp)
    tmp.replace(path)


def _write_secret_bytes(path: Path, data: bytes) -> None:
    global _warned_plaintext, _plaintext_error_logged
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        try:
            os.chmod(path.parent, 0o700)
        except OSError:
            pass
    tmp = path.with_suffix(path.suffix + ".tmp")
    if _dpapi_available():
        try:
            _atomic_write_600(path, tmp, _DPAPI_MARKER + base64.b64encode(_dpapi_encrypt(data)))
            return
        except Exception as e:
            logger.warning(f"DPAPI encrypt failed, trying OS keychain: {e}")
    try:
        if _keyring_available():
            _atomic_write_600(path, tmp, _KEYRING_MARKER + _keyring_encrypt(data))
            return
    except Exception as e:
        logger.warning(f"Keychain encrypt failed, storing plaintext: {e}")
    if not _warned_plaintext:
        logger.error(
            "SECURITY: credentials stored UNENCRYPTED (no DPAPI or OS-keychain "
            "backend on this platform). The file is chmod 600 but NOT encrypted "
            "at rest. Surfaced to the UI as credentials_status().keyStoredUnencrypted."
        )
        _warned_plaintext = True
    _plaintext_error_logged = False
    _atomic_write_600(path, tmp, data)


def _read_secret_bytes(path: Path, upgrade: bool = True) -> bytes:
    raw = path.read_bytes()
    if raw.startswith(_DPAPI_MARKER):
        return _dpapi_decrypt(base64.b64decode(raw[len(_DPAPI_MARKER):]))
    if raw.startswith(_KEYRING_MARKER):
        return _keyring_decrypt(raw[len(_KEYRING_MARKER):])
    if upgrade and (_dpapi_available() or _keyring_available()):
        try:
            _write_secret_bytes(path, raw)
        except Exception:
            pass
    return raw


def _is_plaintext_secret_file(path: Path) -> bool:
    try:
        if not path.exists():
            return False
        with open(path, "rb") as fh:
            head = fh.read(max(len(_DPAPI_MARKER), len(_KEYRING_MARKER)))
        return not (head.startswith(_DPAPI_MARKER) or head.startswith(_KEYRING_MARKER))
    except OSError:
        return False



def _credentials_dir():
    base = os.environ.get("ROM_POLYBOT_USERDATA")
    return (Path(base) if base else Path(__file__).resolve().parent) / "credentials"

def _api_creds_file(env=None):
    if env not in (None, "mainnet"):
        raise ValueError("Only Polymarket US is supported")
    return _credentials_dir() / "polymarket-us.json"

def _validate(key_id, secret):
    try:
        UUID(key_id)
        raw = base64.b64decode(secret, validate=True)
        if len(raw) not in (32, 64): raise ValueError()
        Ed25519PrivateKey.from_private_bytes(raw[:32])
    except Exception:
        raise ValueError("Enter a valid Polymarket US Key ID (UUID) and base64 Secret Key") from None

def save_credentials(key_id, secret_key, env=None, **kwargs):
    key_id, secret_key = key_id.strip(), secret_key.strip()
    _validate(key_id, secret_key)
    _write_secret_bytes(_api_creds_file(env), json.dumps({"keyId":key_id,"secretKey":secret_key}).encode())

def get_api_creds():
    p = _api_creds_file()
    if not p.exists(): raise RuntimeError("Polymarket US API credentials are not configured")
    data = json.loads(_read_secret_bytes(p).decode())
    _validate(data["keyId"], data["secretKey"])
    return data

def credentials_present(env=None):
    return _api_creds_file(env).exists()

def has_api_creds(env=None): return credentials_present(env)
def clear_credentials(env=None): _api_creds_file(env).unlink(missing_ok=True)
def clear_api_creds(env=None): clear_credentials(env)
def key_stored_unencrypted(env=None): return _is_plaintext_secret_file(_api_creds_file(env))
def get_env(): return NETWORK
def set_env(env):
    if env != NETWORK: raise ValueError("Only Polymarket US is supported")
def get_address(): return get_api_creds()["keyId"]
def trading_address(env=None): return get_address()
def get_funder(env=None): return ""
def get_signature_type(env=None): return 0
def reset_credential_cache(): pass
def migrate_legacy_credentials(target_env): return False
def prime_credentials(sync_time=True):
    get_api_creds()
    return True
def credentials_status(env=None):
    has = credentials_present(env)
    key_id = ""
    if has:
        try: key_id=get_address()
        except Exception: pass
    return {"env":NETWORK,"hasWalletKey":has,"hasApiCreds":has,"address":key_id,
            "addressPreview":key_id[:8],"keyStoredUnencrypted":key_stored_unencrypted(env)}
def credentials_status_all(): return {"current":NETWORK,"mainnet":credentials_status()}

def l2_headers(method, path, body=""):
    creds=get_api_creds()
    timestamp=str(int(time.time()*1000))
    key=Ed25519PrivateKey.from_private_bytes(base64.b64decode(creds["secretKey"])[:32])
    signature=base64.b64encode(key.sign((timestamp+method.upper()+path.split("?")[0]).encode())).decode()
    return {"X-PM-Access-Key":creds["keyId"],"X-PM-Timestamp":timestamp,"X-PM-Signature":signature,"Content-Type":"application/json"}
