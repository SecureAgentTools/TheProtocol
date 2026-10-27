"""§MCPTEST30 (V0641): the TEG policy tools are measured on the run's own policies, and the setup's creates are their rows.

Both setups make two real policies (the frame's phase-3, the operator's bootstrap) and recorded the creates under no
name the run kept: lifecycle_teg_policy filed its refusal under createTegPolicy's own name and
lifecycle_create_teg_policies_batch its empty list under the batch tool's, each the last writer, so both tools passed on
a refusal alone on every node. The policy lifecycle then fell back to policies[0] of listTegPolicies: it "updated" a
policy of anyone's with `enabled` (a field the route's model does not have, dropped silently) and soft-deleted it
(2026-10-25, read-only: 18 api-tester policies on sbx-alpha, and on the operators an earlier run's fixture or the run's
own teg_policy_id). Pinned: the refusals are `refusal: ` rows; get/update/delete act only on teg_policy_id and
teg_policy_id_del and read their writes back; the operator bootstrap's two creates (one through the batch) are the
tools' rows and survive the merge; the batch route's 200 counts only with the policy back (it answers 200 whatever it
created).
"""
from __future__ import annotations

import ast
import asyncio
import inspect
import json
import textwrap
from types import SimpleNamespace

from agentvault_registry.api_tests.categories.flow_mcp_lifecycle import test_flow_mcp_lifecycle as F
from agentvault_registry.api_tests.contracts import mcp_lifecycles as L
from agentvault_registry.api_tests.contracts.mcp_contracts import get_contract
from agentvault_registry.routers import mcp_tester as mt

_CREATE, _BATCH = "theprotocol_createTegPolicy", "theprotocol_createTegPoliciesBatch"


def _answer(payload):
    return {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": json.dumps(payload)}]}}


def _error(text):
    return {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": "Error: " + text}],
                                                    "isError": True}}


def _target(update_sticks=True, delete_sticks=True):
    """A fake MCP target holding two policies: p1 (the read/update subject) and p2 (the delete subject)."""
    store = {"p1": {"policy_id": "p1", "description": "old", "is_active": True},
             "p2": {"policy_id": "p2", "description": "old", "is_active": True},
             "someone-elses": {"policy_id": "someone-elses", "description": "theirs", "is_active": True}}
    calls = []

    async def rpc(tool, args, jwt="", timeout=20):
        calls.append((tool, dict(args)))
        if tool == _CREATE:
            return False, _error("HTTP 422: Invalid policy_type. Must be one of: compliance, governance, ..."), "422"
        if tool == _BATCH:
            return False, _error("policies (non-empty list) is required"), "400"
        if tool == "theprotocol_listTegPolicies":
            return True, _answer({"policies": [store["someone-elses"]]}), "200"
        if tool == "theprotocol_getTegPolicy":
            return True, _answer(dict(store[args["policy_id"]])), "200"
        if tool == "theprotocol_updateTegPolicy":
            if update_sticks:
                store[args["policy_id"]].update(args["updates"])
            return True, _answer(dict(store[args["policy_id"]])), "200"
        if tool == "theprotocol_deleteTegPolicy":
            if delete_sticks:
                store[args["policy_id"]]["is_active"] = False
            return True, _answer({"message": f"Policy {args['policy_id']} deactivated"}), "200"
        raise AssertionError(tool)

    return rpc, store, calls


def _bag(**fixtures):
    return SimpleNamespace(developer_jwt="dev", flow_values=dict(fixtures))


def _run(lifecycle, rpc, bag, outcomes=None):
    outcomes = {} if outcomes is None else outcomes
    asyncio.run(lifecycle(rpc, F._parse_rpc_result, bag, outcomes))
    return outcomes


def test_the_policy_lifecycle_acts_only_on_the_runs_own_policies():
    rpc, store, calls = _target()
    out = _run(L.lifecycle_teg_policy, rpc, _bag(teg_policy_id="p1", teg_policy_id_del="p2"))
    touched = {(t, a.get("policy_id")) for t, a in calls if "policy_id" in a}
    assert touched == {("theprotocol_getTegPolicy", "p1"), ("theprotocol_updateTegPolicy", "p1"),
                       ("theprotocol_getTegPolicy", "p2"), ("theprotocol_deleteTegPolicy", "p2")}
    assert "theprotocol_listTegPolicies" not in {t for t, _ in calls}
    assert store["someone-elses"] == {"policy_id": "someone-elses", "description": "theirs", "is_active": True}
    assert store["p1"]["is_active"] is True and store["p2"]["is_active"] is False
    upd = next(a for t, a in calls if t == "theprotocol_updateTegPolicy")
    assert set(upd["updates"]) == {"description"}, "only a field the route's model declares"
    for tool in ("theprotocol_getTegPolicy", "theprotocol_updateTegPolicy", "theprotocol_deleteTegPolicy"):
        assert out[tool]["healthy"] is True and out[tool]["status_code"] == 200, (tool, out[tool])


def test_the_refusals_are_refusal_rows_never_the_tools_own():
    rpc, _store, _calls = _target()
    out = _run(L.lifecycle_teg_policy, rpc, _bag(teg_policy_id="p1", teg_policy_id_del="p2"))
    out = _run(L.lifecycle_create_teg_policies_batch, rpc, _bag(), out)
    assert _CREATE not in out and _BATCH not in out
    ref = {k: v for k, v in out.items() if k.startswith("refusal: ")}
    assert set(ref) == {"refusal: createTegPolicy a policy_type outside the TEG's four",
                        "refusal: createTegPoliciesBatch an empty list"}
    assert all(v["healthy"] for v in ref.values()), ref


def test_an_update_or_delete_that_did_not_stick_is_red():
    rpc, _s, _c = _target(update_sticks=False, delete_sticks=False)
    out = _run(L.lifecycle_teg_policy, rpc, _bag(teg_policy_id="p1", teg_policy_id_del="p2"))
    assert out["theprotocol_updateTegPolicy"]["healthy"] is False
    assert "reads the description 'old'" in out["theprotocol_updateTegPolicy"]["fail_reason"]
    assert out["theprotocol_deleteTegPolicy"]["healthy"] is False
    assert "is_active True" in out["theprotocol_deleteTegPolicy"]["fail_reason"]


def test_without_the_runs_policies_nothing_is_written():
    rpc, store, calls = _target()
    out = _run(L.lifecycle_teg_policy, rpc, _bag())
    assert [t for t, _ in calls] == [_CREATE]
    assert set(out) == {"refusal: createTegPolicy a policy_type outside the TEG's four"}
    assert all(p["is_active"] for p in store.values())


def test_a_batch_answer_counts_only_with_the_policy_back():
    made = {"success_count": 1, "failure_count": 0, "errors": [],
            "created_policies": [{"policy_id": "pb", "policy_code": "COD1A2B"}]}
    assert F.teg_policy_batch_failure(made, 1) is None and F.teg_policy_batch_id(made) == "pb"
    none_made = {"success_count": 0, "failure_count": 1, "created_policies": [],
                 "errors": [{"index": 0, "error": "Policy with this code already exists"}]}
    why = F.teg_policy_batch_failure(none_made, 1)
    assert why and "0 of 1" in why and "already exists" in why
    for bad in ({}, None, {"created_policies": [{"policy_code": "X"}]}, []):
        assert F.teg_policy_batch_failure(bad, 1), bad
    assert F.teg_policy_batch_id(none_made) == ""


def test_the_operator_rows_say_what_came_back():
    ok_c = F.cloudop_policy_row(_CREATE, "200", {"policy_id": "p1"}, 7)
    ok_b = F.cloudop_policy_row(_BATCH, "200", {"failure_count": 0, "created_policies": [{"policy_id": "p2"}]}, 9)
    assert ok_c["healthy"] is True and ok_b["healthy"] is True
    assert ok_c["tool_name"] == _CREATE and ok_b["tool_name"] == _BATCH
    red_b = F.cloudop_policy_row(_BATCH, "200", {"failure_count": 1, "created_policies": [], "errors": ["x"]}, 9)
    assert red_b["healthy"] is False and "0 of 1" in red_b["fail_reason"]
    red_c = F.cloudop_policy_row(_CREATE, "422", {}, 3)
    assert red_c["healthy"] is False and "HTTP 422" in red_c["fail_reason"]
    pol = F.teg_policy_batch_policy("COD1A2B", "cloud-op fixture teg_policy_id_del", "d")
    assert set(pol) == {"policy_code", "policy_name", "policy_type", "description"} and pol["policy_type"] == "compliance"


def test_the_setup_rows_survive_the_operator_merge_and_leave_no_refusal_only_row():
    """The operator path: setup rows filed first, then the two lifecycles write into the same dict, then the sweep's
    lifecycle branch (no override_coverage_fan on either contract) takes the row through _fan_row_verdict."""
    rows = {_CREATE: F.cloudop_policy_row(_CREATE, "200", {"policy_id": "p1"}, 7),
            _BATCH: F.cloudop_policy_row(_BATCH, "200", {"failure_count": 0, "created_policies": [{"policy_id": "p2"}]},
                                         9)}
    lifecycle_outcomes = {}
    lifecycle_outcomes.update(rows)
    rpc, _s, _c = _target()
    _run(L.lifecycle_teg_policy, rpc, _bag(teg_policy_id="p1", teg_policy_id_del="p2"), lifecycle_outcomes)
    _run(L.lifecycle_create_teg_policies_batch, rpc, _bag(), lifecycle_outcomes)
    as_router_reads = []
    for tool in (_CREATE, _BATCH):
        assert not get_contract(tool).override_coverage_fan
        d = F._fan_row_verdict(lifecycle_outcomes[tool], tool)
        assert d["healthy"] is True and d["status_code"] == 200 and not d.get("skip_reason"), (tool, d)
        as_router_reads.append({"tool": tool, "tier": "3", "healthy": True, "status": 200, "skip_reason": None,
                                "switched_off": None})
    for name, d in lifecycle_outcomes.items():
        if name.startswith("refusal: "):
            as_router_reads.append({"tool": "MCP tool (x): " + name, "tier": "3", "healthy": d["healthy"],
                                    "status": d["status_code"], "skip_reason": None, "switched_off": None})
    assert not [r for r in mt._refusal_only(as_router_reads) if "TegPolic" in str(r)], mt._refusal_only(as_router_reads)


def _calls_in(func, name):
    tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
    return tree, [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == name]


def test_the_operator_bootstrap_files_both_creates_before_the_lifecycles():
    tree, rows = _calls_in(F.TestFlowMcpLifecycle._run_cloudop_mcp_sweep, "cloudop_policy_row")
    assert len(rows) == 1
    src = ast.unparse(tree)
    assert '"theprotocol_createTegPoliciesBatch"' in src.replace("'", '"')
    filed = [n for n in ast.walk(tree) if isinstance(n, ast.Assign) and any(
        isinstance(t, ast.Subscript) and ast.unparse(t.value) == "_cloudop_setup_rows" for t in n.targets)
        and isinstance(n.value, ast.Call) and getattr(n.value.func, "id", "") == "cloudop_policy_row"]
    assert len(filed) == 1
    merge = next(n.lineno for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                 and n.func.attr == "update" and ast.unparse(n.func.value) == "lifecycle_outcomes"
                 and ast.unparse(n.args[0]) == "_cloudop_setup_rows")
    assert filed[0].lineno < merge


def test_the_frame_setup_makes_its_delete_subject_through_the_batch_and_asks_for_it_back():
    tree, checks = _calls_in(F._phase3_setup_entities, "teg_policy_batch_failure")
    assert len(checks) == 1
    src = ast.unparse(tree).replace("'", '"')
    assert '"theprotocol_createTegPoliciesBatch"' in src and '"theprotocol_createTegPolicy"' in src
    assert "setup_outcomes[_tool].healthy = False" in src
