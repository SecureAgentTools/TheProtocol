"""A NUL character in a request's path or query string is refused at the edge, 400, before any route runs
(§MCPTEST30, 2026-10-01).

WHY AT THE EDGE
Postgres can neither store nor compare a NUL in a text value: asyncpg raises CharacterNotInRepertoireError
("invalid byte sequence for encoding "UTF8": 0x00"), and every route that hands a path or query value to its SQL
unchecked answers it as a 500. The MCP tester's hostile-input probe measured it on sbx-alpha (V0515) with no login at
all: `GET /api/v1/discover?query=...%00...` and `GET /api/v1/fiat/flare/agent/...%00...` both answered 500, each a
rolled-back session and an ERROR traceback in the log. No value this API reads from a path or a query string can
carry a NUL (the database refuses one), so ONE check in front of the routes closes the class for every route, the next
one written included; a check per route would guarantee that the next route forgets it.

WHAT IT DOES NOT COVER
A request BODY: a JSON string can carry \\u0000 into a write. That is measured separately, never guessed here.

Deny-only, before any handler runs: nothing is half-applied, Δ-irrelevant.
"""
from __future__ import annotations

import logging
from urllib.parse import unquote_to_bytes

from starlette.types import ASGIApp, Receive, Scope, Send

from ..errors import create_error_response

logger = logging.getLogger(__name__)

NUL_REFUSAL_DETAIL = "A NUL character is not valid in a request path or query string."

try:  # metrics are optional; their absence must never affect the gate
    from prometheus_client import Counter
    NUL_REFUSED_TOTAL = Counter(
        "registry_nul_refused_total",
        "Requests refused at the edge because their path or query string carried a NUL character",
        ["where"],
    )
except Exception:  # pragma: no cover
    NUL_REFUSED_TOTAL = None


def nul_in(scope: Scope) -> str:
    """Where this request carries a NUL character: 'path', 'query', or '' for nowhere.

    The path is read as the server decoded it for routing and as it arrived (an encoded %00 counts either way); the
    query string is read percent-decoded, so an encoded %00 counts and the text "%2500" (a literal "%00") does not."""
    path = scope.get("path") or ""
    raw_path = scope.get("raw_path") or b""
    if "\x00" in path or b"\x00" in unquote_to_bytes(raw_path):
        return "path"
    qs = scope.get("query_string") or b""
    if qs and b"\x00" in unquote_to_bytes(qs):
        return "query"
    return ""


class NulRefusalMiddleware:
    """Pure-ASGI (like ReadOnlyModeMiddleware and AdmissionControlMiddleware: BaseHTTPMiddleware is avoided here)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        where = nul_in(scope)
        if not where:
            return await self.app(scope, receive, send)
        if NUL_REFUSED_TOTAL is not None:
            try:
                NUL_REFUSED_TOTAL.labels(where).inc()
            except Exception:
                pass
        logger.debug("[NUL] refused %s with a NUL in its %s", scope.get("method", "GET"), where)
        resp = create_error_response(detail=NUL_REFUSAL_DETAIL, status_code=400, error_type="validation_error",
                                     context={"where": where})
        return await resp(scope, receive, send)
