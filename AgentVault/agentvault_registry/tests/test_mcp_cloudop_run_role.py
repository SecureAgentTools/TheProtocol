"""§MCPTEST30 (V0639): the operator sweep's sentinel holds `governor` for the run, so the governance rules are measured.

Under an operator's enforce posture the run's agent holds its birth roles (AGENT_RBAC_DEFAULT_ROLES=trader,client,staker
on both sandbox operators, no gov.*): castVote, tallyProposal and federationVoteProposal answered "Agent lacks required
permission: gov.vote" (the wide-list check of 2026-10-24 13:39-13:46Z) and never reached the rule each row is for.
Pinned: _grant_run_role posts ONE role with an expiry through the owner's access API and says what it gave; a refusal,
an exception or a missing DID is said, never raised; the sweep grants it to the sentinel alone and carries run_roles in
its summary.
"""
from __future__ import annotations

import ast
import asyncio
import inspect
import json
from datetime import datetime, timezone

from agentvault_registry.api_tests.categories.flow_mcp_lifecycle import test_flow_mcp_lifecycle as F

DID = "did:theprotocol:sandbox-a.theprotocol.cloud:93c63716-3947-4495-b0e4-5358b384819e"


def _grant(monkeypatch, answer=None, raises=None, did=DID):
    seen = []

    async def fake_http(container, method, path, *, body=None, bearer="", **kw):
        seen.append({"container": container, "method": method, "path": path,
                     "body": json.loads(body) if body else None, "bearer": bearer})
        if raises:
            raise raises
        return answer

    monkeypatch.setattr(F, "_http_in_target", fake_http)
    out = asyncio.run(F._grant_run_role("cloud-op-sbxalphaop-registry", "owner-jwt", did, "governor"))
    return out, seen


def test_one_role_with_an_expiry_through_the_owners_access_api(monkeypatch):
    ans = {"agent_did": DID, "role": "governor", "changed": True, "roles": ["client", "governor", "staker", "trader"],
           "effective_permissions": ["a2a.pay", "gov.propose", "gov.vote", "exchange.vote", "read.profile"]}
    out, seen = _grant(monkeypatch, ("200", json.dumps(ans)))
    assert len(seen) == 1
    call = seen[0]
    assert call["method"] == "POST" and call["path"] == f"/api/v1/agents/{DID}/authz/roles"
    assert call["bearer"] == "owner-jwt" and call["body"]["role"] == "governor"
    left = datetime.fromisoformat(call["body"]["expires_at"]) - datetime.now(timezone.utc)
    assert 6600 < left.total_seconds() <= 7200, "two hours, by itself"
    assert out == {"role": "governor", "granted": True, "expires_at": call["body"]["expires_at"], "changed": True,
                   "gov_permissions": ["gov.propose", "gov.vote"]}


def test_a_refusal_is_said(monkeypatch):
    out, _seen = _grant(monkeypatch, ("403", json.dumps({"detail": "not your agent"})))
    assert out == {"role": "governor", "granted": False, "why": "HTTP 403"}


def test_no_answer_is_said(monkeypatch):
    out, _seen = _grant(monkeypatch, ("", "exec raised TimeoutError"))
    assert out["granted"] is False and out["why"] == "HTTP no answer"


def test_an_exception_is_said_not_raised(monkeypatch):
    out, _seen = _grant(monkeypatch, raises=RuntimeError("docker went away"))
    assert out == {"role": "governor", "granted": False, "why": "RuntimeError"}


def test_a_did_that_could_leave_its_quotes_is_never_sent(monkeypatch):
    for bad in ("", "did:theprotocol:x' ; rm -rf /", "not a did"):
        out, seen = _grant(monkeypatch, ("200", "{}"), did=bad)
        assert seen == [] and out["granted"] is False, bad


def test_the_sweep_grants_it_to_the_sentinel_alone_and_says_so():
    tree = ast.parse("class X:\n" + inspect.getsource(F.TestFlowMcpLifecycle._run_cloudop_mcp_sweep))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "_grant_run_role"]
    assert len(calls) == 1 and isinstance(calls[0].args[3], ast.Constant) and calls[0].args[3].value == "governor"
    guards = [n for n in ast.walk(tree) if isinstance(n, ast.If) and any(c is calls[0] for c in ast.walk(n))]
    assert any("_tag == 'sentinel'" in ast.unparse(g.test) for g in guards), "the sentinel alone"
    summary = [k.value for n in ast.walk(tree) if isinstance(n, ast.Dict) for k in n.keys
               if isinstance(k, ast.Constant)]
    assert "run_roles" in summary
