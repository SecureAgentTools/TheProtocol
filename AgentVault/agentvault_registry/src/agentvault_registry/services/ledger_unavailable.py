"""§LEDGERGATE (2026-10-11): the TEG's "the ledger cannot record this right now" refusal, passed on whole.

The TEG refuses a request that starts a value movement while its ledger cannot record it (the TEG's
core/ledger_gate.py): 503, Retry-After, code `ledger_unavailable`, detail "ledger_unavailable: The ledger cannot record
this right now. Nothing was moved. Try again shortly." Nothing moved, so the registry passes the refusal on as it came
(the same status, the same sentence, the same Retry-After) instead of its generic "Unable to process transfer at this
time", and the console shows the sentence. A path that wraps the TEG's text in its own words (the AGORA mover's
"order deposit failed: ...") keeps the marker inside it, and the console finds it there.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import HTTPException, status

CODE = "ledger_unavailable"
MARKER = "ledger_unavailable:"
SENTENCE = "The ledger cannot record this right now. Nothing was moved. Try again shortly."
# §LEDGERGATE (V0602): what an FX route's origin answers when the receiving frame's ledger could not record the payout and
# the gateway returned the payment before anything converted (_fx_route_origin). The console and the payout lane read it.
ROUTE_CAME_BACK = ("The receiving frame's ledger cannot record this right now. Your payment came back to you. "
                   "Try again shortly.")


def retry_after_if_any(response: Any, body: Any) -> Optional[str]:
    """The Retry-After an answer carries (its header, the TEG's context.retry_after_s, or the registry's dual-emit body's
    error.context.headers), clamped to 1..300 s; None when it carries none (or none that is a number)."""
    body = body if isinstance(body, dict) else {}
    raw = None
    try:
        raw = response.headers.get("retry-after")
    except Exception:  # noqa: BLE001
        raw = None
    if not raw:
        ctx = body.get("context") if isinstance(body.get("context"), dict) else {}
        raw = ctx.get("retry_after_s")
    if not raw:
        # the registry's own answer (a self-call, /teg/send -> /teg/transfer): its dual-emit body keeps the header in
        # error.context.headers
        err = body.get("error") if isinstance(body.get("error"), dict) else {}
        hdrs = err.get("context", {}).get("headers") if isinstance(err.get("context"), dict) else None
        if isinstance(hdrs, dict):
            raw = next((v for k, v in hdrs.items() if str(k).lower() == "retry-after"), None)
    try:
        n = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return str(min(300, max(1, n)))


def _retry_after(response: Any, body: dict) -> str:
    return retry_after_if_any(response, body) or "30"


def route_came_back_refusal(response: Any, body: Any) -> Optional[HTTPException]:
    """§LEDGERGATE (V0605): an inner answer that is the route's ROUTE_CAME_BACK refusal (a 503 whose whole detail is that
    sentence), raised again as it came: the same status, the sentence alone and its Retry-After. Anything else: None."""
    if int(getattr(response, "status_code", 0) or 0) != 503:
        return None
    detail = body.get("detail") if isinstance(body, dict) else None
    if not isinstance(detail, str) or detail.strip() != ROUTE_CAME_BACK:
        return None
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=ROUTE_CAME_BACK,
                         headers={"Retry-After": _retry_after(response, body)})


class LedgerRefusedError(ValueError):
    """A batched movement the TEG's ledger gate refused (nothing in the batch moved). `refusal` is the HTTPException to
    raise for it: the same status, sentence and Retry-After. A ValueError, so every caller that catches the bulk proxy's
    failures still catches it."""

    def __init__(self, refusal: HTTPException):
        super().__init__(str(refusal.detail))
        self.refusal = refusal


def refusal_from_text(text: Any) -> Optional[HTTPException]:
    """The refusal for a failure that reached the registry only as text (a proxy's message). The marker means the gate
    refused the whole request, so nothing moved; the text carries no Retry-After, so 30."""
    if not isinstance(text, str) or MARKER not in text:
        return None
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"{MARKER} {SENTENCE}",
                         headers={"Retry-After": "30"})


def refusal_from_error(exc: Any) -> Optional[HTTPException]:
    """§LEDGERGATE (V0598): the refusal carried by an exception a route caught, else None. A route that catches every
    failure of a value movement (`except Exception` -> 502 "... failed: {exc}") asks this first, so the gate's refusal
    reaches the caller whole (503, the sentence, Retry-After) and nothing else changes: a LedgerRefusedError (the bulk
    proxy's), an error whose status is 503 and whose detail starts with the marker (an HTTPException or the AGORA mover's
    MoverError, passed on as it came), or a message that names the marker (a proxy that kept only the text)."""
    if isinstance(exc, LedgerRefusedError):
        return exc.refusal
    status_code = getattr(exc, "status_code", None)
    detail = getattr(exc, "detail", None) or getattr(exc, "message", None)
    if status_code == status.HTTP_503_SERVICE_UNAVAILABLE and isinstance(detail, str) and detail.startswith(MARKER):
        headers = getattr(exc, "headers", None) or {}
        retry = next((str(v) for k, v in headers.items() if str(k).lower() == "retry-after"), "30")
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail, headers={"Retry-After": retry})
    return refusal_from_text(str(exc)) if exc is not None else None


def ledger_refusal(response: Any) -> Optional[HTTPException]:
    """The HTTPException to raise for a TEG answer that is the ledger gate's refusal, else None."""
    if getattr(response, "status_code", None) != status.HTTP_503_SERVICE_UNAVAILABLE:
        return None
    try:
        body = response.json()
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(body, dict):
        return None
    detail = body.get("detail")
    if body.get("code") != CODE and not (isinstance(detail, str) and detail.startswith(MARKER)):
        return None
    if not (isinstance(detail, str) and detail.startswith(MARKER)):
        detail = f"{MARKER} {SENTENCE}"
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=detail,
        headers={"Retry-After": _retry_after(response, body)},
    )
