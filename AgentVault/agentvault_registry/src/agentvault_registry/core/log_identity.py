"""V0653 (am), items 7 and 8 (the hardening list in the sessions' room): who a log line is about, without their address.

Log lines reach shared places (the container log, Dozzle, the log shipper), so a line names a person by something that is
not their e-mail address: the first character, the domain and a short hash of the whole address, enough to tell two
people apart and to follow one person through the lines of one flow, not enough to write to them. An API key is named
by its id, never by any part of the key.

V0654 (aq), item 23 (CodeQL #392, weak-sensitive-data-hashing): the short hash was an unkeyed sha256 of the address, so
anyone holding a log line could confirm a guessed address against it. It is keyed now: an HMAC under a key derived from
the registry's own secret (API_KEY_SECRET, the one every worker and restart shares), so a person still reads the same in
every line, and a guess can be checked only by someone who holds that secret. A process without the secret (a script, a
test) keys with a random value of its own.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from typing import Any, Optional

_TAG_CONTEXT = b"theprotocol log identity tag v1"   # the derivation's purpose: this key signs nothing else
_tag_key: Optional[bytes] = None


def _key() -> bytes:
    global _tag_key
    if _tag_key is None:
        secret = (os.environ.get("API_KEY_SECRET") or "").encode("utf-8")
        _tag_key = hmac.new(secret, _TAG_CONTEXT, hashlib.sha256).digest() if secret else os.urandom(32)
    return _tag_key


def email_for_log(email: Any) -> str:
    """"m…@example.org #1f3a9c2e" for m.someone@example.org; "email:none" for nothing; a hash alone for a value with no @."""
    e = str(email or "").strip().lower()
    if not e:
        return "email:none"
    digest = hmac.new(_key(), e.encode("utf-8"), hashlib.sha256).hexdigest()[:8]
    local, at, domain = e.partition("@")
    if not at or not local or not domain:
        return f"email:#{digest}"
    return f"{local[0]}…@{domain} #{digest}"


def api_key_for_log(key_info: Any) -> str:
    """An API key named by its id (from the creation answer's api_key_info), never by its characters."""
    kid = key_info.get("id") if isinstance(key_info, dict) else None
    return f"key id {kid}" if kid is not None else "key id unknown"
