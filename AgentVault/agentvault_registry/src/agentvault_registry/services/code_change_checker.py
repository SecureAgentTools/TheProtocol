"""V0664 (order gwo_af5b8c950682b9318a347e39): the frame's half of governed code's signed host checker.

A host checker (session-release's half) reads the repository: the CI state of the exact commit, the paths it changes
from the merge base of a release branch, a secret scan of their text, or whether a release branch holds a commit. It
signs what it read with a key of its own, which stays on the host. A frame holds only the checker's PUBLIC key
(CODE_CHANGES_CHECKER_PUBLIC_KEY, base64 of the raw 32 bytes) and verifies the record here: no repository credential
lives on any frame. No usable key: nothing is checked and nothing merges (fail closed).

The format (agreed in the room, seq 3670-3674) is core/release_channel's shape:
  every record   schema "theprotocol.code-change-check/1", kind, repository, change_id, commit (full hex), issued_at
                 (UTC, ISO 8601 with Z), signature {"alg": "Ed25519", "kid": 16 hex of sha256 of the raw public key,
                 "sig": base64} over release_channel.canonical(record): the record without its signature, keys sorted,
                 compact separators, UTF-8
  acceptance     ci_state, base, touched, secret_findings, secret_paths (paths only, never content), too_many_touched
  release_line   branch, contains
A record is taken for its own change, repository and commit only, no older than CODE_CHANGES_CHECKER_MAX_AGE_HOURS (24)
and no more than five minutes ahead. The rule that an older record never replaces a newer one for the same change is
the flow's (services/code_changes), which knows the last record it took.
"""
from __future__ import annotations

import base64
import binascii
import datetime as dt
import logging
import os
import re
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

SCHEMA = "theprotocol.code-change-check/1"
KINDS = ("acceptance", "release_line")
DEFAULT_MAX_AGE_HOURS = 24
FUTURE_SKEW = dt.timedelta(minutes=5)
_SHA = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")


def public_key() -> Optional[bytes]:
    """The checker's raw Ed25519 public key, or None when none (or no usable one) is configured."""
    raw = (os.getenv("CODE_CHANGES_CHECKER_PUBLIC_KEY") or "").strip()
    if not raw:
        return None
    try:
        key = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        logger.warning("[code-changes] CODE_CHANGES_CHECKER_PUBLIC_KEY is not base64: no check until it is")
        return None
    if len(key) != 32:
        logger.warning("[code-changes] CODE_CHANGES_CHECKER_PUBLIC_KEY is not a 32-byte Ed25519 key: no check until it is")
        return None
    return key


def kid_of(pub: bytes) -> str:
    from ..core.release_channel import kid_of as _kid
    return _kid(pub)


def max_age() -> dt.timedelta:
    try:
        h = float(os.getenv("CODE_CHANGES_CHECKER_MAX_AGE_HOURS", "") or DEFAULT_MAX_AGE_HOURS)
    except ValueError:
        h = DEFAULT_MAX_AGE_HOURS
    return dt.timedelta(hours=h if h > 0 else DEFAULT_MAX_AGE_HOURS)


def parse_time(v: Any) -> Optional[dt.datetime]:
    if not isinstance(v, str) or not v.endswith("Z"):
        return None
    try:
        t = dt.datetime.fromisoformat(v[:-1] + "+00:00")
    except ValueError:
        return None
    return t if t.tzinfo else None


def verify_record(doc: Any, *, kind: str, change_id: str, repository: str,
                  now: dt.datetime) -> Tuple[Optional[Dict[str, Any]], str, str]:
    """(record without its signature, "", "") when the checker signed this record for this change; else (None, code,
    sentence). Never raises: a record that cannot be verified is refused, never trusted."""
    pub = public_key()
    if pub is None:
        return None, "no_checker", ("no checker key is configured on this registry (CODE_CHANGES_CHECKER_PUBLIC_KEY): "
                                    "nothing is checked")
    if not isinstance(doc, dict):
        return None, "unsigned", "send the host checker's signed record"
    sig = doc.get("signature")
    if not isinstance(sig, dict) or sig.get("alg") != "Ed25519":
        return None, "unsigned", "send the host checker's signed record (an Ed25519 signature)"
    if sig.get("kid") != kid_of(pub):
        return None, "key", "signed by a key this registry does not hold for its checker"
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from ..core.release_channel import canonical
        Ed25519PublicKey.from_public_bytes(pub).verify(base64.b64decode(str(sig.get("sig") or "")), canonical(doc))
    except Exception as exc:  # noqa: BLE001 - every failure is one answer: not verified
        return None, "signature", f"the checker's signature does not verify ({type(exc).__name__})"
    rec = {k: v for k, v in doc.items() if k != "signature"}
    if rec.get("schema") != SCHEMA:
        return None, "schema", f"an unknown record schema {str(rec.get('schema'))[:60]!r}"
    if rec.get("kind") != kind:
        return None, "kind", f"a {str(rec.get('kind'))[:20]!r} record where a {kind!r} one is needed"
    if rec.get("change_id") != change_id:
        return None, "change_id", "the record is for another change"
    if rec.get("repository") != repository:
        return None, "repository", "the record is for another repository"
    if not _SHA.match(str(rec.get("commit") or "")):
        return None, "commit", "the record names no full commit id"
    issued = parse_time(rec.get("issued_at"))
    if issued is None:
        return None, "issued_at", "the record's issued_at is not a UTC time ending in Z"
    now = now if now.tzinfo else now.replace(tzinfo=dt.timezone.utc)
    if issued < now - max_age():
        return None, "stale", f"the record was made more than {max_age()} ago: ask the checker again"
    if issued > now + FUTURE_SKEW:
        return None, "future", "the record's issued_at is ahead of this registry's clock"
    rec["checker_kid"] = sig.get("kid")
    return rec, "", ""
