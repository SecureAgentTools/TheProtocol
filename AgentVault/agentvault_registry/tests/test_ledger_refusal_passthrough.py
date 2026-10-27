"""§LEDGERGATE (2026-10-11): the registry passes the TEG's ledger refusal on as it came.

The TEG's ledger gate refuses a value movement while its ledger cannot record it: 503, Retry-After, code
ledger_unavailable, detail "ledger_unavailable: The ledger cannot record this right now. Nothing was moved. Try again
shortly." The /teg/transfer path used to answer every TEG 503 with its own generic text and no Retry-After; it now
raises the TEG's sentence and Retry-After unchanged. Any other 503 (a TEG that is down, a timeout behind the TEG's
proxy) keeps the old handling: only the gate's own refusal says "Nothing was moved".

RED control: on the tree before the fix, services/ledger_unavailable.py does not exist, and _handle_teg_transfer_error
raises a 503 with no Retry-After header.
"""
from __future__ import annotations

import json

import httpx
import pytest
from fastapi import HTTPException

from agentvault_registry.services import ledger_unavailable as lu

SENTENCE_DETAIL = "ledger_unavailable: The ledger cannot record this right now. Nothing was moved. Try again shortly."


def _resp(status, body, headers=None):
    return httpx.Response(status, content=json.dumps(body).encode(), headers={"content-type": "application/json",
                                                                              **(headers or {})})


def _gate_body(**kw):
    body = {"detail": SENTENCE_DETAIL, "type": "https://docs.theprotocol.cloud/errors/ledger-unavailable",
            "title": "Service Unavailable", "status": 503, "code": "ledger_unavailable",
            "context": {"ledger": {"state": "unhealthy"}, "retry_after_s": 45}}
    body.update(kw)
    return body


def test_the_gates_refusal_is_recognised_with_its_retry_after():
    exc = lu.ledger_refusal(_resp(503, _gate_body(), {"retry-after": "12"}))
    assert isinstance(exc, HTTPException) and exc.status_code == 503
    assert exc.detail == SENTENCE_DETAIL and exc.headers == {"Retry-After": "12"}


def test_retry_after_falls_back_to_the_body_then_to_30():
    assert lu.ledger_refusal(_resp(503, _gate_body())).headers["Retry-After"] == "45"
    body = _gate_body()
    body.pop("context")
    assert lu.ledger_refusal(_resp(503, body)).headers["Retry-After"] == "30"


def test_the_code_alone_or_the_marker_alone_is_enough():
    assert lu.ledger_refusal(_resp(503, {"detail": SENTENCE_DETAIL})) is not None
    exc = lu.ledger_refusal(_resp(503, {"detail": {"weird": 1}, "code": "ledger_unavailable"}))
    assert exc is not None and exc.detail.startswith(lu.MARKER) and lu.SENTENCE in exc.detail


def test_other_answers_are_not_the_gates():
    assert lu.ledger_refusal(_resp(503, {"detail": "Service temporarily unavailable"})) is None
    assert lu.ledger_refusal(_resp(502, _gate_body())) is None
    assert lu.ledger_refusal(_resp(400, _gate_body())) is None
    assert lu.ledger_refusal(httpx.Response(503, content=b"<html>bad gateway</html>")) is None


def test_the_transfer_path_raises_the_tegs_refusal_unchanged():
    from agentvault_registry.routers.teg_integration import _handle_teg_transfer_error
    with pytest.raises(HTTPException) as ei:
        _handle_teg_transfer_error(_resp(503, _gate_body(), {"retry-after": "20"}))
    assert ei.value.status_code == 503 and ei.value.detail == SENTENCE_DETAIL
    assert ei.value.headers == {"Retry-After": "20"}
    # a TEG 503 that is not the gate's makes no claim that nothing moved: since §REPATLANE-5 (V0606) it says that its
    # outcome is not known (the TEG's failure may come after its commit), and a kept attempt keeps it under the key
    with pytest.raises(HTTPException) as ei2:
        _handle_teg_transfer_error(_resp(503, {"detail": "upstream timeout"}))
    assert ei2.value.status_code == 503 and ei2.value.detail == "upstream timeout (outcome not known)"
    assert not ei2.value.headers
