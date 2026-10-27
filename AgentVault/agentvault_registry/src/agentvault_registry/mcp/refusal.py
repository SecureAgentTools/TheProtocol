"""§MCPTEST30 (2026-10-01): one reading of a registry refusal for every MCP tool module.

An error result renders `Error: <error>` alone (the dispatcher drops every other key, §BATCH3), so a refusal whose
`error` said only "<route> returned HTTP 404" told its caller nothing: round 5 counted 47 tools answering so, among them
transfers, payments, stakes and contract milestones. `http_refusal` keeps that text (contracts match on it) and appends
the route's own reason. No tool module is imported here, so every one of them can import this.
"""
from __future__ import annotations

import json
import re
from typing import Any

_WS = re.compile(r"\s+")


def refusal_reason(r: Any) -> str:
    """The human reason a registry refusal carries, read out of its RFC 7807 body.

    A dict `detail` arrives JSON-encoded inside the string (errors.http_exception_handler), and a
    result dict carrying `error` renders as `Error: <error>` alone: the dispatcher drops every other
    key (§BATCH3). So a reason left in a side key reaches no caller; it has to be IN the error.
    """
    try:
        body = r.json()
    except ValueError:
        return (r.text or "")[:300]
    d = body.get("detail") if isinstance(body, dict) else None
    if isinstance(d, str):
        try:
            dd = json.loads(d)
        except ValueError:
            return d[:300]
        if not isinstance(dd, dict):
            return d[:300]
        parts = [str(dd.get("message") or "").strip()]
        blocking = (dd.get("progress") or {}).get("blocking") if isinstance(dd.get("progress"), dict) else None
        if blocking:
            parts.append(f"(still short on: {', '.join(map(str, blocking))})")
        for k in ("unlock_after", "unlocked_at"):
            if dd.get(k):
                parts.append(f"{k}={dd[k]}")
        return " ".join(p for p in parts if p)[:300] or d[:300]
    if isinstance(d, dict):
        return str(d.get("message") or d)[:300]
    return (r.text or "")[:300]


def http_refusal(label: str, r: Any) -> str:
    """`<label> returned HTTP <code>`, then `: <the route's reason>` when its body carries one. A body that is not a
    reason (empty, or an HTML error page from a proxy) adds nothing: a reason is read, never invented."""
    head = f"{label} returned HTTP {getattr(r, 'status_code', '?')}"
    try:
        reason = _WS.sub(" ", refusal_reason(r) or "").strip()
    except Exception:  # noqa: BLE001
        reason = ""
    if not reason or reason.startswith("<"):
        return head
    return f"{head}: {reason[:300]}"
