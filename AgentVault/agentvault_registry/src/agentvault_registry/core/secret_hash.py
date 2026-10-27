"""§DEPS (2026-09-28): every password, agent client secret, API key, recovery key and 2FA backup code hashes here.

It replaces passlib 1.7.4 (unmaintained since 2020), which held bcrypt at 4.0.1: on bcrypt 5 its import-time
self-test raises. The rules below are the ones passlib applied, kept byte for byte, so every hash it made verifies
here and every hash made here verifies under passlib (an image rolled back to one that still carries passlib keeps
every credential made in between). Measured against passlib 1.7.4 + bcrypt 4.0.1 before the switch; the vectors are
in tests/test_secret_hash.py.

- A str is encoded as UTF-8 and only its first 72 bytes count. bcrypt never read further, but bcrypt 5 raises on a
  longer secret where bcrypt 4 cut it silently, so the cut is ours now. It is load-bearing: every agent client secret
  is 74 bytes ("tp_secret_" + 64 hex), and without the cut no agent could log in.
- A secret holding a NUL byte is refused, as passlib refused it (bcrypt 5 would hash it), and so is one over 4096
  bytes (passlib's MAX_PASSWORD_SIZE).
- A stored value that is not a bcrypt hash verifies as False without raising: developers mirrored from a peer frame
  and deleted accounts carry a marker there, not a hash, and a login against one is an ordinary no.

New hashes are "$2b$" at cost 12, exactly what passlib made (bcrypt.gensalt()'s default).
"""
from __future__ import annotations

from typing import Any

import bcrypt

BCRYPT_MAX_BYTES = 72
SECRET_MAX_BYTES = 4096
_BCRYPT_PREFIXES = (b"$2a$", b"$2b$", b"$2y$")


def _secret_bytes(secret: Any) -> bytes:
    if isinstance(secret, str):
        raw = secret.encode("utf-8")
    elif isinstance(secret, bytes):
        raw = secret
    else:
        raise TypeError("a secret must be str or bytes")
    if b"\x00" in raw:
        raise ValueError("a secret must not contain a NUL byte")
    if len(raw) > SECRET_MAX_BYTES:
        raise ValueError(f"a secret must not be longer than {SECRET_MAX_BYTES} bytes")
    return raw[:BCRYPT_MAX_BYTES]


def hash_secret(secret: str | bytes) -> str:
    """A new "$2b$12$" bcrypt hash of `secret`. Raises TypeError / ValueError on a secret passlib also refused."""
    return bcrypt.hashpw(_secret_bytes(secret), bcrypt.gensalt()).decode("ascii")


def is_bcrypt_hash(stored: Any) -> bool:
    """True when `stored` has the shape of a bcrypt hash (a marker, None or "" does not)."""
    if isinstance(stored, str):
        stored = stored.encode("utf-8", "replace")
    return isinstance(stored, bytes) and len(stored) == 60 and stored.startswith(_BCRYPT_PREFIXES)


def verify_secret(secret: Any, stored: Any) -> bool:
    """True only when `secret` matches the bcrypt hash `stored`. Never raises: any refusal is False."""
    if not is_bcrypt_hash(stored):
        return False
    try:
        raw = _secret_bytes(secret)
        stored_bytes = stored.encode("ascii") if isinstance(stored, str) else stored
        return bcrypt.checkpw(raw, stored_bytes)
    except (TypeError, ValueError):
        return False
