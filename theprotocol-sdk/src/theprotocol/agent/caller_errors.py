"""What an agent's caller is told when its request fails.

V0653 (am) item 2 (the hardening list in the sessions' room): an exception's text is the agent's internals (a database
address, a file path, a key the code was holding), and the SDK sent it to whoever called the agent. Now the caller gets
the SDK's own refusals whole (an exception class that sets caller_safe = True: a task that does not exist, a transition a
task cannot make, a method the agent does not have), a validation error's locations and messages (never the input
pydantic echoes), and for anything else a generic message with an error id; the agent's log gets the whole exception
under the same id. An agent author passes a message through on purpose by raising an exception with caller_safe = True.
"""
from __future__ import annotations

import logging
import uuid
from typing import Optional


def _locations(exc: BaseException) -> Optional[str]:
    """A pydantic validation error's "where: why" list, from it or from the error it was raised from."""
    for e in (exc, exc.__cause__, exc.__context__):
        errors = getattr(e, "errors", None)
        if not callable(errors):
            continue
        try:
            items = errors()
        except Exception:
            continue
        if isinstance(items, list):
            parts = []
            for it in items[:5]:
                if isinstance(it, dict):
                    loc = ".".join(str(x) for x in (it.get("loc") or ()))
                    parts.append(f"{loc}: {it.get('msg') or it.get('type') or 'invalid'}" if loc else
                                 str(it.get("msg") or it.get("type") or "invalid"))
            return "; ".join(parts) or None
    return None


def caller_message(exc: BaseException, label: str, log: logging.Logger) -> str:
    """The message for the caller; the whole exception goes to `log` with the error id the message names."""
    if getattr(exc, "caller_safe", False):
        return str(exc)
    where = _locations(exc)
    eid = uuid.uuid4().hex[:12]
    log.error("%s (error id %s): %s: %s", label, eid, type(exc).__name__, exc, exc_info=exc)
    return f"{label}: {where} (error id {eid})" if where else f"{label} (error id {eid})"
