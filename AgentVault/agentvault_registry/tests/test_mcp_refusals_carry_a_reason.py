"""§MCPTEST30 (2026-10-01) — a refusal an MCP tool passes on carries the route's own reason.

An error result renders `Error: <error>` alone (the dispatcher drops every other key, §BATCH3), so a tool whose error
said only "<route> returned HTTP 404" told its caller nothing. Round 5 of the MCP tester counted 47 tools answering so,
among them transfers, payments, stakes and contract milestones. mcp/refusal.http_refusal keeps that text (contracts
match on it) and appends the reason; this file pins the reading and holds the line: no MCP module builds a refusal that
ends at its status code again (one named exception: Prometheus, an internal metrics call, not a registry route).
"""
from __future__ import annotations

import json
import pathlib
import re

import pytest

from agentvault_registry.api_tests.contracts import result_shape
from agentvault_registry.mcp import refusal


class _R:
    def __init__(self, status, body=None, text=None):
        self.status_code = status
        self._body = body
        self.text = text if text is not None else (json.dumps(body) if body is not None else "")

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


def test_a_refusal_keeps_its_text_and_appends_the_routes_reason():
    assert refusal.http_refusal("x", _R(404, {"detail": "Dispute not found"})) == "x returned HTTP 404: Dispute not found"
    inner = json.dumps({"message": "bond required", "progress": {"blocking": ["listing"]}})
    assert refusal.http_refusal("y", _R(400, {"detail": inner})) == ("y returned HTTP 400: bond required "
                                                                     "(still short on: listing)")
    assert refusal.http_refusal("z", _R(409, {"detail": {"message": "already settled"}})) == \
        "z returned HTTP 409: already settled"


def test_a_body_that_is_not_a_reason_adds_nothing():
    assert refusal.http_refusal("a", _R(502, None, "<html><body>502 Bad Gateway</body></html>")) == "a returned HTTP 502"
    assert refusal.http_refusal("b", _R(404, None, "")) == "b returned HTTP 404"
    assert refusal.http_refusal("c", _R(503, None, "upstream\n  timed out")) == "c returned HTTP 503: upstream timed out"


_REASONLESS_SITE = re.compile(r'f"[^"\n]*?HTTP \{\w+\.status_code\}"(?=\s*[,})])')
_ALLOWED = {("tools_admin.py", 'f"Prometheus returned HTTP {resp.status_code}"')}


def test_no_mcp_module_builds_a_refusal_that_ends_at_its_status_code():
    root = pathlib.Path(refusal.__file__).parent
    sites = set()
    for p in sorted(root.glob("*.py")):
        for m in _REASONLESS_SITE.finditer(p.read_text()):
            sites.add((p.name, m.group(0)))
    assert sites - _ALLOWED == set(), sorted(sites - _ALLOWED)
    assert _ALLOWED <= sites, "the named exception moved: re-read it before narrowing the gate"


def _err(text):
    return {"jsonrpc": "2.0", "id": 1, "result": {"isError": True, "content": [{"type": "text", "text": text}]}}


def test_the_census_counts_a_reasonless_refusal_without_calling_it_red():
    token = result_shape.begin()
    result_shape.record("theprotocol_getX", _err("Error: getX returned HTTP 404"))
    result_shape.record("theprotocol_getY", _err("Error: getY returned HTTP 404: Dispute not found"))
    result_shape.record("theprotocol_getZ", _err("Error: HTTP 401"))
    summary = result_shape.summarize(result_shape.end(token))
    assert summary["reasonless_refusals"] == {"theprotocol_getX": ["404"], "theprotocol_getZ": ["401"]}
    assert summary["findings"] == {} and result_shape.verdict_text(summary) is None
    assert result_shape.reasonless(_err("Error: Transfer failed (HTTP 422): bad")) is None


@pytest.mark.parametrize("helper", ["_agent_post", "_agent_get", "_agent_delete"])
def test_the_shared_agent_helpers_carry_the_reason_by_default(monkeypatch, helper):
    import asyncio
    from agentvault_registry.mcp import tools_agent

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def _r(self, *a, **k):
            return _R(404, {"detail": "Contract not found"})
        post = get = delete = _r

    class _Auth:
        raw_token, agent_did, auth_type = "agent-jwt", "did:theprotocol:a", "agent"
    monkeypatch.setattr(tools_agent.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(tools_agent, "require_agent_auth", lambda auth: None)
    out = asyncio.run(getattr(tools_agent, helper)(_Auth(), "/api/v1/contracts/1", op_name="op"))
    assert out["error"] == "op returned HTTP 404: Contract not found"
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


class _Redirect(_R):
    def __init__(self, location):
        super().__init__(303, None, "")
        self.headers = {"location": location}


@pytest.mark.parametrize("location,want", [
    ("/#/email-verification?status=success", {"verified": True, "already_verified": False}),
    ("https://console.example/#/email-verification?status=success&already=true",
     {"verified": True, "already_verified": True}),
    ("/#/email-verification?status=failed&reason=expired",
     {"error": "auth/verify-email returned HTTP 303: verification failed (expired)"}),
])
def test_a_verification_reads_its_outcome_from_the_routes_redirect(monkeypatch, location, want):
    """The route answers every verification with a 303 and the outcome in the link's query: read as a refusal, a
    SUCCESSFUL verification through the tool said "Error" (round 5: "auth/verify-email returned HTTP 303")."""
    import asyncio
    from agentvault_registry.mcp import tools_discovery

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            return _Redirect(location)
    monkeypatch.setattr(tools_discovery.httpx, "AsyncClient", _Client)
    assert asyncio.run(tools_discovery.auth_verify_email(token="t")) == want
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


def test_no_mcp_module_reads_a_refusal_only_when_it_is_plain_json():
    """The registry refuses as application/problem+json (RFC 7807, errors.create_error_response), so a tool that read
    the `detail` only for application/json passed the whole body on as its reason: 17 sites until V0515 (round 6 read
    `Transfer failed (HTTP 422): {"error":{"detail":...` on transferUnits). tools_guild found the class first; one
    reading (`refusal_reason`) holds it now."""
    root = pathlib.Path(refusal.__file__).parent
    hits = [(p.name, i) for p in sorted(root.glob("*.py")) for i, line in enumerate(p.read_text().splitlines(), 1)
            if 'headers.get("content-type", "").startswith("application/json")' in line]
    assert hits == [], hits


def test_a_problem_json_refusal_reads_as_its_detail():
    class _Problem(_R):
        def __init__(self):
            super().__init__(422, {"error": {"detail": "Idempotency-Key 'k' is claimed", "type": "validation_error"},
                                   "type": "https://docs.theprotocol.cloud/errors/validation_error",
                                   "title": "Unprocessable Entity", "status": 422,
                                   "detail": "Idempotency-Key 'k' is claimed"})
            self.headers = {"content-type": "application/problem+json"}
    assert refusal.refusal_reason(_Problem()) == "Idempotency-Key 'k' is claimed"
