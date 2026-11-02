"""V0653 (am), items 7 and 8 (the hardening list in the sessions' room): who a log line is about, without their address.

Log lines reach shared places (the container log, Dozzle, the log shipper), so a line names a person by something that is
not their e-mail address: the first character, the domain and a short hash of the whole address, enough to tell two
people apart and to follow one person through the lines of one flow, not enough to write to them. An API key is named
by its id, never by any part of the key.
"""
from __future__ import annotations

import hashlib
from typing import Any


def email_for_log(email: Any) -> str:
    """"m…@example.org #1f3a9c2e" for m.someone@example.org; "email:none" for nothing; a hash alone for a value with no @."""
    e = str(email or "").strip().lower()
    if not e:
        return "email:none"
    digest = hashlib.sha256(e.encode("utf-8")).hexdigest()[:8]
    local, at, domain = e.partition("@")
    if not at or not local or not domain:
        return f"email:#{digest}"
    return f"{local[0]}…@{domain} #{digest}"


def api_key_for_log(key_info: Any) -> str:
    """An API key named by its id (from the creation answer's api_key_info), never by its characters."""
    kid = key_info.get("id") if isinstance(key_info, dict) else None
    return f"key id {kid}" if kid is not None else "key id unknown"
