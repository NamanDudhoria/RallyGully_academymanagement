"""Password hashing and safe persistence helpers for production use."""
from __future__ import annotations

import binascii
import hashlib
import json
import os
import secrets
import tempfile
from typing import Any

try:
    import bcrypt as _bcrypt

    _HAS_BCRYPT = True
except ImportError:
    _bcrypt = None
    _HAS_BCRYPT = False

_PBKDF2_ITERS = 600_000


def is_production() -> bool:
    v = (os.environ.get("RG_ENV") or os.environ.get("STREAMLIT_ENV") or "").strip().lower()
    return v in ("production", "prod", "live", "1", "true")


def is_bcrypt_hash(value: str | None) -> bool:
    if not value or not isinstance(value, str):
        return False
    return value.startswith(("$2a$", "$2b$", "$2y$"))


def is_pbkdf2_hash(value: str | None) -> bool:
    if not value or not isinstance(value, str):
        return False
    return value.startswith("pbkdf2_sha256$")


def is_password_hash(value: str | None) -> bool:
    return is_bcrypt_hash(value) or is_pbkdf2_hash(value)


def _hash_pbkdf2_sha256(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        _PBKDF2_ITERS,
        dklen=32,
    )
    return f"pbkdf2_sha256${_PBKDF2_ITERS}${salt.hex()}${dk.hex()}"


def _verify_pbkdf2_sha256(password: str, stored: str) -> bool:
    try:
        parts = stored.split("$")
        if len(parts) != 4 or parts[0] != "pbkdf2_sha256":
            return False
        iterations = int(parts[1])
        salt_hex, want_hex = parts[2], parts[3]
        salt = bytes.fromhex(salt_hex)
        want = bytes.fromhex(want_hex)
        dk = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            iterations,
            dklen=len(want),
        )
        return secrets.compare_digest(dk, want)
    except (ValueError, TypeError, binascii.Error):
        return False


def hash_password(password: str) -> str:
    """Prefer bcrypt when installed; otherwise PBKDF2-SHA256 (stdlib)."""
    pw = password.encode("utf-8")
    if _HAS_BCRYPT:
        if len(pw) > 72:
            pw = pw[:72]
        return _bcrypt.hashpw(pw, _bcrypt.gensalt(rounds=12)).decode("ascii")
    return _hash_pbkdf2_sha256(password)


def verify_password(password: str, password_hash: str) -> bool:
    if is_bcrypt_hash(password_hash):
        if not _HAS_BCRYPT:
            return False
        try:
            pw = password.encode("utf-8")
            if len(pw) > 72:
                pw = pw[:72]
            return _bcrypt.checkpw(pw, password_hash.encode("ascii"))
        except (ValueError, TypeError, OSError):
            return False
    if is_pbkdf2_hash(password_hash):
        return _verify_pbkdf2_sha256(password, password_hash)
    return False


def verify_or_rehash(stored: str, plain: str) -> tuple[bool, str | None]:
    """
    Verify login. If stored value is a legacy plaintext match, returns (True, new_hash).
    If already a supported hash, returns (ok, None).
    """
    if not stored:
        return False, None
    if is_password_hash(stored):
        return verify_password(plain, stored), None
    try:
        if secrets.compare_digest(stored, plain):
            return True, hash_password(plain)
    except TypeError:
        if stored == plain:
            return True, hash_password(plain)
    return False, None


def atomic_write_json(filepath: str, obj: Any, default: Any = str) -> None:
    """Write JSON atomically (temp + replace) to reduce corruption on crash."""
    directory = os.path.dirname(os.path.abspath(filepath)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmppath = tempfile.mkstemp(prefix=".tmp_", dir=directory, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2, default=default, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmppath, filepath)
    finally:
        if os.path.exists(tmppath):
            try:
                os.remove(tmppath)
            except OSError:
                pass


def verify_admin_material(typed: str, material: str | None) -> bool:
    """Material may be bcrypt / pbkdf2 hash or plaintext (secrets / env / legacy file)."""
    if material is None:
        return False
    if is_password_hash(material):
        return verify_password(typed, material)
    try:
        return secrets.compare_digest(material, typed)
    except TypeError:
        return material == typed
