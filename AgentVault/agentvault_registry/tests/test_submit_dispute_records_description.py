"""§FINDINGS-A4 3c (2026-09-27, his "fix 1-4 approved"): submitDispute records the description it is given.

The dispute route has no field for a description, so what a caller wrote (and its `evidence`) was silently discarded. The
tool now records both as the dispute's FIRST EVIDENCE and says whether that landed, under `evidence_error` (never `error`:
the dispatcher renders a result carrying `error` as a failed call, and the dispute itself was filed). D6-444 (2026-10-16):
the schema still REQUIRED the description the route ignores; it is optional now, and a dispute filed without one records
no evidence.
"""
import json

import pytest

from agentvault_registry.mcp import tools_developer as td
from agentvault_registry.mcp.auth_bridge import MCPAuthContext

ME = "did:theprotocol:a4-complainant"
THEM = "did:theprotocol:a4-defendant"


class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body
        self.text = json.dumps(body)
        self.headers = {"content-type": "application/json"}

    def json(self):
        return self._body


def _fake_httpx(monkeypatch, evidence_status=201):
    posts = []

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            posts.append((url, json))
            if url.endswith("/api/v1/disputes/"):
                return _Resp(201, {"id": 7, "status": "OPEN", "created_at": "2026-09-27T23:40:00Z"})
            if url.endswith("/api/v1/disputes/7/evidence"):
                return _Resp(evidence_status, {"id": 1} if evidence_status < 300 else {"detail": "refused"})
            raise AssertionError(f"unexpected POST {url}")

    monkeypatch.setattr(td.httpx, "AsyncClient", _Client)
    return posts


def _auth():
    return MCPAuthContext(auth_type="agent", agent_did=ME, raw_token="t")


async def test_the_description_and_evidence_are_recorded_as_the_first_evidence(monkeypatch):
    posts = _fake_httpx(monkeypatch)
    out = await td.submit_dispute(_auth(), defendant_did=THEM, description="the work was never delivered",
                                  evidence={"order": "o-1"})
    assert out["dispute_id"] == 7 and out["description_recorded_as_evidence"] is True
    assert "error" not in out and "evidence_error" not in out
    assert posts[1] == ("http://localhost:8000/api/v1/disputes/7/evidence".replace("http://localhost:8000", td.REGISTRY_SELF_URL),
                        {"evidence_data": {"description": "the work was never delivered", "evidence": {"order": "o-1"}}})


async def test_a_refused_evidence_is_said_and_the_filing_still_stands(monkeypatch):
    _fake_httpx(monkeypatch, evidence_status=403)
    out = await td.submit_dispute(_auth(), defendant_did=THEM, description="x")
    assert out["dispute_id"] == 7 and out["description_recorded_as_evidence"] is False
    assert "HTTP 403" in out["evidence_error"]
    assert "error" not in out   # the dispute WAS filed: never rendered as a failed call


async def test_control_a_self_dispute_is_still_refused_before_any_call(monkeypatch):
    posts = _fake_httpx(monkeypatch)
    out = await td.submit_dispute(_auth(), defendant_did=ME, description="x")
    assert "same agent" in out["error"] and posts == []


async def test_a_dispute_without_a_description_is_filed_and_records_nothing(monkeypatch):
    posts = _fake_httpx(monkeypatch)
    out = await td.submit_dispute(_auth(), defendant_did=THEM)
    assert out["dispute_id"] == 7 and out["description_recorded_as_evidence"] is False
    assert "error" not in out and "evidence_error" not in out
    assert [url for url, _ in posts] == [f"{td.REGISTRY_SELF_URL}/api/v1/disputes/"], "no evidence call for nothing"


async def test_evidence_without_a_description_is_recorded_as_it_was_given(monkeypatch):
    posts = _fake_httpx(monkeypatch)
    out = await td.submit_dispute(_auth(), defendant_did=THEM, evidence={"order": "o-2"})
    assert out["evidence_recorded"] is True and out["description_recorded_as_evidence"] is False
    assert posts[1][1] == {"evidence_data": {"evidence": {"order": "o-2"}}}


def test_the_schema_does_not_require_the_description_the_route_ignores():
    schema = next(s for s in td.DEVELOPER_TOOL_SCHEMAS if s["name"] == "theprotocol_submitDispute")
    assert "description" in schema["inputSchema"]["properties"]
    assert "description" not in schema["inputSchema"]["required"]
