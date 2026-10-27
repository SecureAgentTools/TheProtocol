"""§MCPTEST30 (V0523, 2026-10-01): one encoding of a value as a URL path segment.

The MCP tools built their route paths with f-strings and put the caller's value in unencoded, and the registry did the
same when it forwards a route's path value to its TEG. httpx resolves dot segments client-side
(`/api/v1/webhooks/123/../../agents/x` is sent as `/api/v1/agents/x`), so a value carrying `/`, `..`, `?` or `#` sent
the call to a different route than the one named, with the caller's credentials and the method of the tool or route
that built it: a confused deputy, since an MCP client approves a call by its tool's name and annotations. A NUL never
left the tool at all (httpx InvalidURL, one ERROR traceback in the log per call), and a `%` reached the TEG as a
malformed escape its nginx refused 400, which the registry then reported as 503. The MCP tester's hostile-input probe
measured it on sbx-alpha (V0515): 108 values that never left their tool, and 503s from eight TEG-proxied routes.

`seg` percent-encodes everything but the unreserved characters and `:` and `@` (a DID and an email read the same as
before), and a whole `.` or `..` segment too: quote() leaves dots alone, and httpx would resolve them. The server
decodes the segment back to the caller's exact value before routing.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import quote

_DOTS = {".": "%2E", "..": "%2E%2E"}


def seg(value: Any) -> str:
    """`value` as one URL path segment: percent-encoded, so nothing in it can add a segment, a query or a fragment."""
    s = quote(str(value), safe=":@")
    return _DOTS.get(s, s)
