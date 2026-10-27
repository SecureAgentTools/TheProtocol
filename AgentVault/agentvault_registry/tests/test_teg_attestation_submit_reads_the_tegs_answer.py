"""§DOCSFIX D6-582 (2026-10-16): POST /api/v1/teg/attestations/submit answers the submission the TEG logged.

The proxy expected HTTP 201 with `attestation_id` and `target_agent_did`, while the TEG's /attestation/submit answers
200 with its AttestationSubmissionResponse (`submission_id`, `agent_did`, `attestation_type`, `status`, the policy): every
submission the TEG logged reached the caller as 503 "Unable to submit attestation at this time". The proxy now reads the
TEG's own answer and fills what the TEG does not keep (the target, the data, the evidence URL) from the request.

RED on the pre-change tree: the logged-submission test. The controls are green before and after.
"""
from __future__ import annotations

import asyncio
import types

import pytest
from fastapi import HTTPException

from agentvault_registry import crud_agent_enhanced
from agentvault_registry.routers import teg_integration as ti

SUBMITTER = "did:theprotocol:eu.theprotocol.cloud:attester-0000"
TARGET = "did:theprotocol:eu.theprotocol.cloud:subject-0000"


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _submit(monkeypatch, status_code, body):
    sent, emitted = [], []

    class _Resp:
        def __init__(self):
            self.status_code = status_code
            self.text = str(body)

        def json(self):
            return body

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None, timeout=None):
            sent.append((url, json))
            return _Resp()

    async def _token(agent_id, did):
        return "teg-token"

    async def _emit(**kw):
        emitted.append(kw)
    monkeypatch.setattr(ti, "get_teg_token_for_agent", _token)
    monkeypatch.setattr(ti.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(crud_agent_enhanced, "emit_attestation_event", _emit)
    req = ti.TEGAttestationRequest(target_agent_did=TARGET, attestation_type="ServiceQuality",
                                   attestation_data={"score": 4}, evidence_url="https://evidence.example/1")
    out = _run(ti.submit_attestation(req, current_agent=types.SimpleNamespace(id=9, did=SUBMITTER)))
    return out, sent, emitted


def test_a_submission_the_teg_logged_is_answered_with_its_record(monkeypatch):
    out, sent, emitted = _submit(monkeypatch, 200, {
        "submission_id": "sub-77", "agent_did": SUBMITTER, "attestation_type": "ServiceQuality",
        "status": "logged", "policy_id": None, "policy_name": None})
    assert (out.attestation_id, out.submitter_agent_did, out.target_agent_did) == ("sub-77", SUBMITTER, TARGET)
    assert (out.attestation_type, out.status, out.attestation_data) == ("ServiceQuality", "logged", {"score": 4})
    assert out.evidence_url == "https://evidence.example/1" and out.created_at and out.updated_at
    assert [e["attestation_data"]["attestation_id"] for e in emitted] == ["sub-77"]
    assert sent[0][1]["agent_did"] == SUBMITTER


# ── controls: green before and after ─────────────────────────────────────────────────────────────────────────────

def test_control_a_duplicate_the_teg_refuses_is_its_409(monkeypatch):
    with pytest.raises(HTTPException) as e:
        _submit(monkeypatch, 409, {"detail": "Attestation already submitted"})
    assert e.value.status_code == 409 and "already submitted" in e.value.detail


def test_control_a_teg_outage_is_503(monkeypatch):
    with pytest.raises(HTTPException) as e:
        _submit(monkeypatch, 500, {"detail": "boom"})
    assert e.value.status_code == 503
