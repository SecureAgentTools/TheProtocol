"""§MCPTEST30 (V0639): an operator run clears the free fixtures it makes for itself, and a few of each earlier runs left.

An operator has no sandbox reset, and its sweep removed none of them: one API key, one support ticket, one bundle and
one TEG policy per run stayed (one per run since 2026-09-06; by 2026-10-24, 63 active keys, 63 open tickets, 63 bundles
and 61 active policies on sbxalphaop, 48, 48, 48 and 45 on sbxbetaop), and the AGORA fixture's listing treasury agent
stayed active after its organization went (87 and 55, none holding a balance). Pinned: each kind is found by the exact
name the run gives it, the run's own first, an earlier run's only past the sweep age, at most `limit` per kind; an
unread list retires nothing of its kind and says why; a refusal is counted, never raised; the bootstrap makes each under
the name the teardown looks for; the run retires its treasury agent with its agents once the organization is deleted,
and an earlier run's is taken only while its organization is not active.
"""
from __future__ import annotations

import ast
import asyncio
import inspect
import json
import re
from datetime import datetime, timedelta, timezone

from agentvault_registry.api_tests.categories.flow_mcp_lifecycle import test_flow_mcp_lifecycle as F

NOW = datetime(2026, 10, 24, 20, 0, tzinfo=timezone.utc)
OLD = (NOW - timedelta(hours=4)).isoformat()
YOUNG = (NOW - timedelta(minutes=10)).isoformat()
POLICY = F.CLOUDOP_POLICY_NAME % "teg_policy_id"
POLICY_DEL = F.CLOUDOP_POLICY_NAME % "teg_policy_id_del"


def _rpc(payload):
    return {"result": {"content": [{"type": "text", "text": json.dumps(payload)}]}}


def _lists():
    return {
        "theprotocol_getMyApiKeys": {"api_keys": [
            {"id": 5, "description": F.CLOUDOP_KEY_NAME, "is_active": True, "created_at": YOUNG},   # this run's
            {"id": 3, "description": F.CLOUDOP_KEY_NAME, "is_active": True, "created_at": OLD},
            {"id": 4, "description": F.CLOUDOP_KEY_NAME, "is_active": True, "created_at": YOUNG},   # another live run's
            {"id": 2, "description": "the operator's own key", "is_active": True, "created_at": OLD},
            {"id": 1, "description": F.CLOUDOP_KEY_NAME, "is_active": False, "created_at": OLD}]},
        "theprotocol_getMySupportTickets": {"tickets": [
            {"id": 11, "subject": F.CLOUDOP_TICKET_SUBJECT, "status": "open", "created_at": YOUNG},
            {"id": 10, "subject": F.CLOUDOP_TICKET_SUBJECT, "status": "open", "created_at": OLD},
            {"id": 9, "subject": "a real question", "status": "open", "created_at": OLD}]},
        "theprotocol_getMyAgentBundles": {"bundles": [
            {"id": "b-own", "name": F.CLOUDOP_BUNDLE_NAME, "source_dev_id": 1, "created_at": YOUNG},
            {"id": "b-old", "name": F.CLOUDOP_BUNDLE_NAME, "source_dev_id": 1, "created_at": OLD},
            {"id": "b-pub", "name": F.CLOUDOP_BUNDLE_NAME, "source_dev_id": 7, "created_at": OLD},   # someone else's
            {"id": "b-x", "name": "a template", "source_dev_id": 1, "created_at": OLD}]},
        "theprotocol_listTegPolicies": {"policies": [
            {"policy_id": "p-own", "policy_name": POLICY, "policy_code": "CORA1B2", "is_active": True,
             "created_at": YOUNG},
            {"policy_id": "p-del", "policy_name": POLICY_DEL, "policy_code": "COD9F00", "is_active": True,
             "created_at": OLD},
            {"policy_id": "p-code", "policy_name": POLICY, "policy_code": "VELOCITY", "is_active": True,
             "created_at": OLD},
            {"policy_id": "p-fee", "policy_name": "fee schedule", "policy_code": "FEE1", "is_active": True,
             "created_at": OLD}]},
    }


def _run(lists=None, refuse=(), failing_lists=(), limit=25):
    lists = _lists() if lists is None else lists
    calls = []

    async def call(tool, args):
        calls.append((tool, dict(args)))
        if tool in lists:
            if tool in failing_lists:
                return False, {"result": {"_text": "Error: HTTP 503"}}, "503"
            return True, _rpc(lists[tool]), "200"
        return (tool not in refuse), {"result": {}}, ("403" if tool in refuse else "200")

    async def call_admin(tool, args):
        return await call(tool, args)

    own = {"api_key_id": "5", "support_ticket_id": "11", "bundle_id": "b-own", "teg_policy_id": "p-own"}
    out = asyncio.run(F._retire_run_fixtures(call, call_admin, own, 1, NOW.timestamp(), limit=limit))
    return out, [(t, a) for t, a in calls if t not in lists]


def test_each_kind_retires_the_runs_own_first_then_an_earlier_runs_by_exact_name():
    out, acts = _run()
    assert acts == [
        ("theprotocol_deleteMyApiKey", {"key_id": "5"}), ("theprotocol_deleteMyApiKey", {"key_id": "3"}),
        ("theprotocol_supportCloseTicket", {"ticket_id": 11, "status": "closed"}),
        ("theprotocol_supportCloseTicket", {"ticket_id": 10, "status": "closed"}),
        ("theprotocol_deleteBundle", {"bundle_id": "b-own"}), ("theprotocol_deleteBundle", {"bundle_id": "b-old"}),
        ("theprotocol_deleteTegPolicy", {"policy_id": "p-own"}), ("theprotocol_deleteTegPolicy", {"policy_id": "p-del"}),
    ]
    assert out == {k: {"found": 2, "retired": 2, "refused": []}
                   for k in ("api_keys", "tickets", "bundles", "teg_policies")}


def test_at_most_limit_of_each_kind_per_run():
    keys = [{"id": i, "description": F.CLOUDOP_KEY_NAME, "is_active": True, "created_at": OLD} for i in range(40)]
    out, acts = _run(lists={"theprotocol_getMyApiKeys": {"api_keys": keys}, "theprotocol_getMySupportTickets":
                            {"tickets": []}, "theprotocol_getMyAgentBundles": {"bundles": []},
                            "theprotocol_listTegPolicies": {"policies": []}}, limit=25)
    assert len(acts) == 25 and out["api_keys"] == {"found": 40, "retired": 25, "refused": []}


def test_an_unread_list_retires_nothing_of_its_kind_and_says_why():
    out, acts = _run(failing_lists=("theprotocol_getMyApiKeys",))
    assert not any(t == "theprotocol_deleteMyApiKey" for t, _a in acts)
    assert out["api_keys"]["retired"] == 0 and "getMyApiKeys answered HTTP 503" in out["api_keys"]["error"]
    assert out["bundles"]["retired"] == 2


def test_a_refusal_is_counted_never_raised():
    out, _acts = _run(refuse=("theprotocol_deleteBundle",))
    assert out["bundles"] == {"found": 2, "retired": 0, "refused": ["HTTP 403", "HTTP 403"]}


def _agent(name, did):
    return {"did": did, "name": name, "status": "active"}


def test_an_earlier_runs_treasury_agent_is_taken_only_while_its_organization_is_not_active():
    old = int((NOW - timedelta(hours=4)).timestamp())
    young = int((NOW - timedelta(minutes=10)).timestamp())
    listing = [_agent(f"cloudop-fixture-{old} Treasury ($CO1A2B)", "did:t:old"),
               _agent(f"cloudop-fixture-{young} Treasury ($CO3C4D)", "did:t:young"),
               _agent(f"cloudop-sentinel-{old}-abc123", "did:t:sentinel"),
               _agent(f"cloudop-fixture-{old} Treasury (somewhere else)", "did:t:other")]
    now = NOW.timestamp()
    assert F.old_cloudop_fixtures(listing, now) == ["did:t:sentinel"]                    # the org list unread
    assert F.old_cloudop_fixtures(listing, now, active_orgs={f"cloudop-fixture-{old}"}) == ["did:t:sentinel"]
    assert sorted(F.old_cloudop_fixtures(listing, now, active_orgs=set())) == ["did:t:old", "did:t:sentinel"]


def _sweep_src():
    return inspect.getsource(F.TestFlowMcpLifecycle._run_cloudop_mcp_sweep)


def test_the_bootstrap_makes_each_fixture_under_the_name_the_teardown_looks_for():
    src = re.sub(r"\s+", " ", _sweep_src())
    for made in ('{"key_name": CLOUDOP_KEY_NAME}', '"subject": CLOUDOP_TICKET_SUBJECT,', '"name": CLOUDOP_BUNDLE_NAME,',
                 # §MCPTEST30 (V0641): both policies through teg_policy_batch_policy, which files the name as policy_name
                 'teg_policy_batch_policy(_code, CLOUDOP_POLICY_NAME % _slot,'):
        assert made in src, made
    assert F.teg_policy_batch_policy("COR1A2B", F.CLOUDOP_POLICY_NAME % "teg_policy_id", "d")["policy_name"] == (
        F.CLOUDOP_POLICY_NAME % "teg_policy_id")
    for literal in ("cloudop-mcp-tester-key", "cloudop-mcp-tester ticket", "cloudop-mcp-tester-bundle"):
        assert literal not in src, literal


def _tree():
    return ast.parse("class X:\n" + _sweep_src())


def test_the_sweep_retires_its_fixtures_and_its_treasury_agent_once_the_organization_is_deleted():
    calls = [n for n in ast.walk(_tree()) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
    fx = [c for c in calls if c.func.id == "_retire_run_fixtures"]
    assert len(fx) == 1 and ast.unparse(fx[0].args[2]) == "_cloudop_fixtures"
    agents = [c for c in calls if c.func.id == "_retire_cloudop_agents" and "cloudop_treasury_did" in ast.unparse(c)]
    assert len(agents) == 1 and "_org_gone" in ast.unparse(agents[0])
    old = [c for c in calls if c.func.id == "old_cloudop_fixtures"]
    assert len(old) == 1 and [k.arg for k in old[0].keywords] == ["active_orgs"]
    keys = [k.value for n in ast.walk(_tree()) if isinstance(n, ast.Dict) for k in n.keys if isinstance(k, ast.Constant)]
    assert "run_fixtures_retired" in keys


def test_the_organization_counts_as_deleted_only_on_a_2xx_delete():
    rule = next(n.value for n in ast.walk(_tree()) if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "_org_gone" for t in n.targets))
    gone = compile(ast.Expression(body=rule), "<_org_gone>", "eval")
    assert eval(gone, {"re": re, "bool": bool}, {"_retired": "delist HTTP 200; organization delete HTTP 200"})
    assert not eval(gone, {"re": re, "bool": bool}, {"_retired": "delist HTTP 200; organization delete HTTP 409 (kept)"})
    assert not eval(gone, {"re": re, "bool": bool}, {"_retired": "no fixture"})
