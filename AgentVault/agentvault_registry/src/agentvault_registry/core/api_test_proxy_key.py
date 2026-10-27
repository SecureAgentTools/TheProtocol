"""The api-tester's shared proxy key: ONE reader for the sender and both receivers.

§V0135 introduced `API_TEST_PROXY_INTERNAL_KEY` so a tester CONSOLE can drive a sweep on a
TARGET registry whose JWT secret differs (the console's forwarded bearer is invalid there).
Two modules read it (`routers/admin_api_test.py` accepts it on `/admin/api-test/test-flow`,
`routers/mcp_tester.py` sends it and accepts it on `/admin/mcp-tester/peer-es-facts`), each with
a LITERAL DEFAULT written in the source.

§PROXYKEY 2026-09-11 — measured on the live cluster: the variable was unset on every node, so
the literal WAS the key everywhere. On EU (the tester console, execution on, reachable through
the public API hosts) and on two operators that had inherited execution from EU, anyone who
read the source could start tester runs without logging in (no use found in the retained logs).
The rule this module keeps, the same one `admin_key_ok` keeps on the TEG (§MONEY-M3a):

  * NO DEFAULT. Unset means the proxy path is CLOSED: nothing is accepted, nothing is sent.
  * A configured value is refused by SHAPE, never by a denylist (a denylist would carry the
    literals it refuses): shorter than MIN_KEY_LENGTH, or carrying a placeholder word, and the
    node behaves as if unset, loudly, once per process.
  * Comparison is constant-time over bytes (`secrets.compare_digest` raises on non-ASCII str).

The value is never logged; only its length.
"""
from __future__ import annotations

import logging
import os
import secrets
from typing import Dict, Optional

logger = logging.getLogger(__name__)

ENV_NAME = "API_TEST_PROXY_INTERNAL_KEY"
MIN_KEY_LENGTH = 32
_PLACEHOLDER_WORDS = ("changeme", "change-me", "placeholder", "example", "your-key", "secret-here")

_refusal_logged = False


def configured_key() -> str:
    """This node's key, or "" when it holds none or one that is not a secret."""
    global _refusal_logged
    value = (os.getenv(ENV_NAME) or "").strip()
    if not value:
        return ""
    lowered = value.lower()
    if len(value) < MIN_KEY_LENGTH or any(w in lowered for w in _PLACEHOLDER_WORDS):
        if not _refusal_logged:
            logger.error(
                "[API-TEST-PROXY-KEY] %s is configured but refused by shape (len=%d, need >= %d and "
                "no placeholder word): the proxy path stays CLOSED on this node.",
                ENV_NAME, len(value), MIN_KEY_LENGTH,
            )
            _refusal_logged = True
        return ""
    return value


def presented_key_ok(presented: Optional[str]) -> bool:
    """True only when this node holds a usable key and the caller presented exactly it."""
    expected = configured_key()
    if not expected or not presented:
        return False
    return secrets.compare_digest(presented.encode("utf-8"), expected.encode("utf-8"))


def proxy_headers() -> Dict[str, str]:
    """The header a CONSOLE sends, or nothing when it holds no usable key.

    Sending an empty or refused key would only earn a 401 that reads like a wrong key; sending
    nothing lets the target's answer name the real cause (no key on the console)."""
    k = configured_key()
    return {"X-Internal-Key": k} if k else {}
