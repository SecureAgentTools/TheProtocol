"""§MCPTEST30 V0639 (agentvault2-aa, 2026-10-24): acceptComplianceBaseline's success path is measured on a peer that
still publishes its baseline, not only on the first peer listed.

lifecycle_admin_compliance_baseline read only the first federated peer with a baseline. On sbx-alpha that is
op-sbxalphaop, whose live policy hash no longer matches its baseline (hash_match false), while Sandbox Beta and sbxbetaop
match (read 2026-10-24): the success path ("unchanged", nothing written) never ran, and the tool read refusal-only in
every run. Now the refusal stays on the first peer, and the others are read, at most five, until one matches. A drifted
peer is still never accepted. The first test fails on V0637's lifecycle (the control).
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from agentvault_registry.api_tests.contracts import mcp_admin_lifecycles as adm

STALE = "0" * 64
OVERVIEW = {"peers": [
    {"operator_id": "op-a", "peer_registry_id": 1, "federation_status": "federated", "peer_status": "ACTIVE",
     "has_compliance_record": True},
    {"operator_id": "beta", "peer_registry_id": 2, "federation_status": "federated", "peer_status": "ACTIVE",
     "has_compliance_record": True},
    {"operator_id": "op-b", "peer_registry_id": 3, "federation_status": "federated", "peer_status": "ACTIVE",
     "has_compliance_record": True},
]}


class _Rpc:
    def __init__(self, details: Dict[str, Dict[str, Any]]):
        self.details, self.calls = details, []

    async def __call__(self, tool: str, args: dict, jwt: str = "", timeout: int = 20):
        self.calls.append((tool, dict(args)))
        if tool == "theprotocol_getFederationComplianceOverview":
            return True, {"result": OVERVIEW}, "200"
        if tool == "theprotocol_getFederationCompliancePeerByOperator":
            return True, {"result": self.details[args["operator_id"]]}, "200"
        if tool == "theprotocol_acceptComplianceBaseline":
            live = self.details.get({"1": "op-a", "2": "beta", "3": "op-b"}[args["peer_id"]], {})
            if args["expected_hash"] == live.get("live_policy_hash") and live.get("hash_match") is True:
                return True, {"result": {"status": "unchanged"}}, "200"
            return False, {"result": {"_text": "Error: acceptComplianceBaseline returned HTTP 409: hash mismatch"}}, "409"
        return False, {"result": {"_text": "Error: not in this script"}}, "404"


def _parse(body: Dict[str, Any]) -> Dict[str, Any]:
    r = body.get("result") if isinstance(body, dict) else None
    return r if isinstance(r, dict) else {}


class _Bag:
    developer_jwt = "admin-jwt"


def _run(details):
    rpc, out = _Rpc(details), {}
    asyncio.run(adm.lifecycle_admin_compliance_baseline(rpc, _parse, _Bag(), out))
    accepts = [a for t, a in rpc.calls if t == "theprotocol_acceptComplianceBaseline"]
    reads = [a["operator_id"] for t, a in rpc.calls if t == "theprotocol_getFederationCompliancePeerByOperator"]
    return out, accepts, reads


def test_a_drifted_first_peer_no_longer_hides_the_success_path():
    out, accepts, reads = _run({"op-a": {"hash_match": False, "live_policy_hash": "a" * 64},
                                "beta": {"hash_match": True, "live_policy_hash": "b" * 64},
                                "op-b": {"hash_match": True, "live_policy_hash": "c" * 64}})
    assert reads == ["op-a", "beta"]                       # stops at the first match
    assert accepts[0] == {"peer_id": "1", "expected_hash": STALE,
                          "reason": "MCP tester: a hash this peer does not publish (must be refused)"}
    assert accepts[1]["peer_id"] == "2" and accepts[1]["expected_hash"] == "b" * 64
    row = out["theprotocol_acceptComplianceBaseline"]
    assert row["healthy"] is True and str(row.get("status_code")).startswith("2")


def test_when_no_peer_matches_only_the_refusal_runs_and_nothing_drifted_is_accepted():
    out, accepts, reads = _run({k: {"hash_match": False, "live_policy_hash": k[0] * 64} for k in ("op-a", "beta", "op-b")})
    assert reads == ["op-a", "beta", "op-b"]
    assert [a["expected_hash"] for a in accepts] == [STALE]


def test_the_first_peer_matching_keeps_the_old_order():
    _out, accepts, reads = _run({"op-a": {"hash_match": True, "live_policy_hash": "a" * 64},
                                 "beta": {"hash_match": True, "live_policy_hash": "b" * 64},
                                 "op-b": {"hash_match": True, "live_policy_hash": "c" * 64}})
    assert reads == ["op-a"] and [a["peer_id"] for a in accepts] == ["1", "1"]
