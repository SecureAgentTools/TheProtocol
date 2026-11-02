"""What the API tester may write to a log about a request or an answer: its shape, never its values.

V0653 (am) item 13 (the hardening list in the sessions' room): the tester ships in every registry image and its log lines
reach the container's log, so a line that prints a body, an answer or a token prints whatever that holds: a key shown once
at creation, a bootstrap token, an invitation token, a TOTP secret, a password a 422 echoes back. These three render
what a reader needs (did it work, what came back, why it was refused) without the values; tests/test_tester_logs_v0653.py
refuses a log call that prints one of those things any other way.
"""
from __future__ import annotations

import json
from typing import Any


def shape(obj: Any) -> str:
    """dict(keys: a, b), list(3 items), str(12 chars): what came back, without the values."""
    if obj is None:
        return "None"
    if isinstance(obj, dict):
        keys = ", ".join(str(k) for k in list(obj)[:20])
        more = f", +{len(obj) - 20} more" if len(obj) > 20 else ""
        return f"dict(keys: {keys}{more})"
    if isinstance(obj, (list, tuple, set)):
        return f"{type(obj).__name__}({len(obj)} items)"
    if isinstance(obj, (str, bytes)):
        return f"{type(obj).__name__}({len(obj)} chars)"
    return type(obj).__name__


def secret(value: Any) -> str:
    """A credential's presence and length, never a prefix of it (a prefix is part of the secret)."""
    if not value:
        return "<absent>"
    return f"<{len(str(value))} chars>"


def _words(detail: Any) -> str:
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list):           # pydantic's errors: where and why, never the "input" it echoes
        out = []
        for e in detail[:5]:
            if isinstance(e, dict):
                loc = ".".join(str(x) for x in (e.get("loc") or []))
                out.append(f"{loc}: {e.get('msg') or e.get('type') or '?'}")
            else:
                out.append(type(e).__name__)
        return "; ".join(out)
    if isinstance(detail, dict):
        return _words(detail.get("detail") or detail.get("message") or detail.get("error") or "")
    return type(detail).__name__


def refusal(answer: Any, limit: int = 160) -> str:
    """A refusal's own words from a response, its JSON or its text: the message, where and why; never an input it echoes
    (a 422 repeats the value it refused, a password among them)."""
    data = answer
    if hasattr(answer, "status_code") and hasattr(answer, "text"):
        try:
            data = answer.json()
        except Exception:
            data = answer.text
    if isinstance(data, (bytes, bytearray)):
        data = data.decode("utf-8", "replace")
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:
            return data[:limit]                 # not JSON (a proxy's error page): no structure that could echo a value
    if isinstance(data, dict):
        return _words(data.get("detail") or data.get("error") or data.get("message") or data.get("title") or "")[:limit]
    return _words(data)[:limit]


def outcome(result: Any) -> str:
    """A tester result ({statusCode, responseData, error, ...}) as "status N: the refusal's words"."""
    if not isinstance(result, dict):
        return shape(result)
    words = refusal(result.get("responseData")) if result.get("responseData") is not None else ""
    err = result.get("error")
    return f"status {result.get('statusCode')}: {words or (refusal(err) if err else '') or 'no words'}"
