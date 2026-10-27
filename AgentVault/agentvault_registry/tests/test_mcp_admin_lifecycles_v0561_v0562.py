"""§MCPTEST30 (V0561 + V0562): the admin sweep's two new lifecycles, driven through `_exec_step` with a fake transport.

- admin_compliance_baseline (V0561): acceptComplianceBaseline is measured on a real peer and never changes it: a hash the
  peer does not publish must be refused, the stored hash (while the peer still publishes it) must answer "unchanged",
  and a peer that drifted is never accepted by the tester (accepting a drift is an admin's decision).
- admin_command_center_self (V0562): the Command Center's tools asked about this registry itself: every check that
  applies, one check, and a dry-run action that a frame answers "skipped"; an operator's dry run says what it would do.
"""
from types import SimpleNamespace

import pytest

from agentvault_registry.api_tests.contracts import mcp_admin_lifecycles as m


def _harness(answer):
    calls = []

    async def rpc(tool, args, jwt=None, timeout=15):
        calls.append((tool, dict(args)))
        code, inner = answer(tool, args)
        return code < 400, {"result": inner}, str(code)

    def parse(body):
        return body.get("result") if isinstance(body, dict) else {}
    return rpc, parse, calls


BAG = SimpleNamespace(developer_jwt="jwt")
PEER = {"operator_id": "sandbox-beta", "peer_registry_id": 2, "has_compliance_record": True,
        "federation_status": "federated", "peer_status": "ACTIVE"}


@pytest.mark.asyncio
@pytest.mark.parametrize("hash_match", [True, False])
async def test_the_compliance_lifecycle_measures_without_accepting_anything(hash_match):
    live = "b" * 64

    def answer(tool, args):
        if tool == "theprotocol_getFederationComplianceOverview":
            return 200, {"peers": [PEER]}
        if tool == "theprotocol_getFederationCompliancePeerByOperator":
            return 200, {"live_policy_hash": live, "hash_match": hash_match}
        if tool == "theprotocol_acceptComplianceBaseline":
            if args["expected_hash"] != live:
                return 409, {"detail": "the peer now publishes another hash"}
            return 200, {"status": "unchanged"}
        raise AssertionError(tool)
    rpc, parse, calls = _harness(answer)
    outcomes = {}
    await m.lifecycle_admin_compliance_baseline(rpc, parse, BAG, outcomes)
    accepts = [a for t, a in calls if t == "theprotocol_acceptComplianceBaseline"]
    assert accepts[0]["expected_hash"] != live, "the first ask is a hash the peer does not publish"
    if hash_match:
        assert [a["expected_hash"] for a in accepts] == [accepts[0]["expected_hash"], live]
        assert outcomes["theprotocol_acceptComplianceBaseline"]["healthy"] is True
    else:
        assert len(accepts) == 1, "a peer that drifted is never accepted by the tester"


@pytest.mark.asyncio
async def test_the_compliance_lifecycle_stays_out_of_a_frame_with_no_baseline():
    def answer(tool, args):
        if tool == "theprotocol_getFederationComplianceOverview":
            return 200, {"peers": [{**PEER, "has_compliance_record": False}]}
        raise AssertionError(f"no call may follow: {tool}")
    rpc, parse, calls = _harness(answer)
    await m.lifecycle_admin_compliance_baseline(rpc, parse, BAG, {})
    assert [t for t, _ in calls] == ["theprotocol_getFederationComplianceOverview"]


def _cc_answer(targets, run_ids=None, op_summary="dry-run: would restart sbxalphaop's teg-layer through the operator lifecycle (via runner)"):
    run_ids = run_ids or sorted(m._SELF_CHECKS)

    def answer(tool, args):
        if tool == "theprotocol_getDiagnosticTargets":
            return 200, {"targets": targets}
        if tool == "theprotocol_runAllDiagnostics":
            return 200, {"results": [{"check_id": c, "status": "ok"} for c in run_ids]}
        if tool == "theprotocol_runDiagnosticsSubset":
            return 200, {"results": [{"check_id": c, "status": "ok"} for c in args["checks"]]}
        if tool == "theprotocol_triggerDiagnosticAction":
            if args["target"] in ("sandbox-alpha", "sbxalphaop"):   # this registry itself, a frame or an operator
                return 200, {"status": "skipped", "dry_run": True, "summary": "only this frame's own operators' TEGs"}
            return 200, {"status": "ok", "dry_run": True, "summary": op_summary}
        raise AssertionError(tool)
    return answer


SELF_T = {"operator_id": "sandbox-alpha", "role": "frame", "is_self": True}
OP_T = {"operator_id": "op-sbxalphaop", "role": "operator"}


@pytest.mark.asyncio
async def test_the_command_center_lifecycle_asks_about_this_registry_and_dry_runs_an_operator():
    rpc, parse, calls = _harness(_cc_answer([SELF_T, OP_T]))
    outcomes = {}
    await m.lifecycle_admin_command_center_self(rpc, parse, BAG, outcomes)
    assert [(t, a.get("target") or a.get("targets")) for t, a in calls[1:]] == [
        ("theprotocol_runAllDiagnostics", "sandbox-alpha"),
        ("theprotocol_runDiagnosticsSubset", ["sandbox-alpha"]),
        ("theprotocol_triggerDiagnosticAction", "sandbox-alpha"),
        ("theprotocol_triggerDiagnosticAction", "op-sbxalphaop"),
    ]
    assert all(a.get("dry_run") is True for t, a in calls if t == "theprotocol_triggerDiagnosticAction")
    for tool in ("theprotocol_runAllDiagnostics", "theprotocol_runDiagnosticsSubset", "theprotocol_triggerDiagnosticAction"):
        assert outcomes[tool]["healthy"] is True, (tool, outcomes[tool])


@pytest.mark.asyncio
async def test_a_run_missing_a_check_or_a_dry_run_that_acts_is_a_finding():
    rpc, parse, _ = _harness(_cc_answer([SELF_T, OP_T], run_ids=["supply-audit"], op_summary="restarted"))
    outcomes = {}
    await m.lifecycle_admin_command_center_self(rpc, parse, BAG, outcomes)
    assert outcomes["theprotocol_runAllDiagnostics"]["healthy"] is False
    assert outcomes["theprotocol_triggerDiagnosticAction"]["healthy"] is False


@pytest.mark.asyncio
async def test_an_image_without_the_self_target_leaves_the_refusal_rows_standing():
    rpc, parse, calls = _harness(_cc_answer([OP_T]))
    await m.lifecycle_admin_command_center_self(rpc, parse, BAG, {})
    assert [t for t, _ in calls] == ["theprotocol_getDiagnosticTargets"]


@pytest.mark.asyncio
async def test_an_operator_registrys_own_run_has_no_supply_audit():
    me = {"operator_id": "sbxalphaop", "role": "operator", "is_self": True}
    rpc, parse, calls = _harness(_cc_answer([me], run_ids=sorted(m._SELF_CHECKS - {"supply-audit"})))
    outcomes = {}
    await m.lifecycle_admin_command_center_self(rpc, parse, BAG, outcomes)
    assert outcomes["theprotocol_runAllDiagnostics"]["healthy"] is True
    assert outcomes["theprotocol_triggerDiagnosticAction"]["healthy"] is True
    # this registry is no operator of its own to dry-run: only its own action is asked
    assert [a.get("target") for t, a in calls if t == "theprotocol_triggerDiagnosticAction"] == ["sbxalphaop"]


def test_both_lifecycles_run_after_phase_6():
    names = [x["name"] for x in m.ADMIN_LIFECYCLES]
    assert names.index("admin_destructive_safe") < names.index("admin_compliance_baseline") < \
        names.index("admin_command_center_self")
