"""§MCPTEST30 (V0639): the operator sweep retires the organizations the createOrganization contract made.

The contract makes one organization per run ("apitest destructive-contract probe"), and only the frames' orphan sweep
clears them; an operator run has none, so sbxalphaop held 71 and sbxbetaop 49 by 2026-10-24, one per run since
2026-09-05 (the frames: 2 and 0). Pinned: the name is the contract's own; only active orgs of that name owned by the
run's developer are deleted, through the owner's deleteOrganization, at most `limit` per run; a list that fails deletes
nothing and says why; a refused delete is counted, never raised; the sweep calls it and its summary carries the count.
"""
from __future__ import annotations

import ast
import asyncio
import inspect

from agentvault_registry.api_tests.categories.flow_mcp_lifecycle import test_flow_mcp_lifecycle as F
from agentvault_registry.api_tests.contracts.mcp_contracts import get_contract

NAME = get_contract("theprotocol_createOrganization").arguments["name"]


def _org(i, name=NAME, owner=1, active=True):
    return {"id": f"org-{i}", "name": name, "owner_id": owner, "is_active": active}


def _run(orgs, list_ok=True, delete_ok=lambda oid: True, limit=25, owner="1"):
    calls = []

    async def call(tool, args):
        calls.append((tool, dict(args)))
        if tool == "theprotocol_getMyOrganizations":
            if not list_ok:
                return False, {"result": {"_text": "Error: HTTP 503"}}, "503"
            return True, {"result": {"content": [{"type": "text", "text": __import__("json").dumps(
                {"organizations": orgs, "total": len(orgs)})}]}}, "200"
        if tool == "theprotocol_deleteOrganization":
            ok = delete_ok(args["org_id"])
            return ok, {"result": {}}, "200" if ok else "403"
        raise AssertionError(tool)

    out = asyncio.run(F._retire_probe_orgs(call, owner, limit=limit))
    return out, [a["org_id"] for t, a in calls if t == "theprotocol_deleteOrganization"]


def test_the_probe_name_is_the_contracts_own():
    assert NAME == "apitest destructive-contract probe"


def test_only_active_probe_orgs_of_the_runs_developer_are_deleted():
    orgs = [_org(1), _org(2), _org(3, name="Meridian Ledger Works"), _org(4, owner=7), _org(5, active=False)]
    out, deleted = _run(orgs)
    assert deleted == ["org-1", "org-2"]
    assert out == {"found": 2, "retired": 2, "refused": []}


def test_at_most_limit_per_run():
    out, deleted = _run([_org(i) for i in range(40)], limit=25)
    assert len(deleted) == 25 and out["found"] == 40 and out["retired"] == 25


def test_a_failed_list_deletes_nothing_and_says_why():
    out, deleted = _run([_org(1)], list_ok=False)
    assert deleted == [] and out["retired"] == 0 and "HTTP 503" in out["error"]


def test_a_refused_delete_is_counted():
    out, deleted = _run([_org(1), _org(2)], delete_ok=lambda oid: oid != "org-1")
    assert deleted == ["org-1", "org-2"] and out["retired"] == 1 and out["refused"] == ["HTTP 403"]


def test_the_sweep_retires_them_and_says_so():
    tree = ast.parse("class X:\n" + inspect.getsource(F.TestFlowMcpLifecycle._run_cloudop_mcp_sweep))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "_retire_probe_orgs"]
    assert len(calls) == 1
    keys = [k.value for n in ast.walk(tree) if isinstance(n, ast.Dict) for k in n.keys if isinstance(k, ast.Constant)]
    assert "probe_orgs_retired" in keys
