"""§MCPTEST30 (2026-10-01) — the admin lookups measured with ids the frame HAS.

harvest_admin_fixtures reads the answers of the admin list reads (shapes measured on sbx-alpha, V0508) and publishes one
existing id per lookup fixture; it invents nothing and skips what the frame lacks. Each lookup's contract takes its
fixture and overrides the fan's deliberately-invalid probe; the reads whose values are records keep their shape only.
"""
from __future__ import annotations

import asyncio
import inspect

from agentvault_registry.api_tests.contracts import mcp_admin_lifecycles as A
from agentvault_registry.api_tests.contracts import mcp_lifecycles as L
from agentvault_registry.api_tests.contracts.mcp_contracts import MCP_CONTRACTS, McpContract, resolve_args, unresolved_fixtures

MEASURED = {   # the list shapes as sbx-alpha answered them (values made up)
    "listAdminOperatorApplications": {"applications": [{"id": "c0a615f4-app", "status": "approved"}],
                                      "config": {"mtls_enforced": True}},
    "listFederationLicenses": [{"id": "lic-revoked", "status": "revoked"}, {"id": "lic-active", "status": "active"}],
    "getAllFederationPeersAdmin": {"items": [{"id": 3, "status": "INACTIVE"}, {"id": 9, "status": "ACTIVE"}],
                                   "pagination": {"total_items": 2}},
    "getFederationComplianceOverview": {"peers": [{"peer_registry_id": 4, "operator_id": None, "has_compliance_record": False},
                                                  {"peer_registry_id": 5, "operator_id": "op-sbxalphaop",
                                                   "has_compliance_record": True}]},
    "getBroadcastTemplates": {"templates": [{"id": 1, "label": "maintenance"}], "total": 1},
    "getAdminBroadcasts": [{"id": 77, "title": "t"}],
    "getCloudOperators": {"operators": [{"application_id": "app-gone", "active": False},
                                        {"application_id": "app-live", "active": True}]},
    "getDiagnosticTargets": {"targets": [{"operator_id": "op-sbxalphaop", "role": "operator"}], "count": 1},
}


def test_one_existing_id_per_fixture_preferring_the_live_one():
    got = A.harvest_admin_fixtures(MEASURED)
    assert got == {
        "operator_application_id": "c0a615f4-app", "federation_license_id": "lic-active", "peer_registry_id": "9",
        "compliance_peer_id": "5", "compliance_operator_id": "op-sbxalphaop", "broadcast_template_id": "1",
        "broadcast_id": 77, "active_cloud_operator_id": "app-live", "diagnostic_target_id": "op-sbxalphaop"}


def test_a_frame_without_rows_publishes_nothing_and_an_inactive_operator_is_never_taken():
    assert A.harvest_admin_fixtures({}) == {}
    got = A.harvest_admin_fixtures({"getCloudOperators": {"operators": [{"application_id": "x", "active": False}]},
                                    "listAdminOperatorApplications": {"applications": []},
                                    "getAdminBroadcasts": [{"id": "not-a-number"}]})
    assert got == {}


def test_every_harvested_fixture_feeds_a_contract_that_overrides_the_fan():
    published = set(A.harvest_admin_fixtures(MEASURED))
    feeding = {}
    for tool, c in MCP_CONTRACTS.items():
        for f in c.requires_fixtures or []:
            if f in published:
                feeding.setdefault(f, []).append(tool)
        for v in (c.arguments or {}).values():
            if isinstance(v, str) and v.startswith("${") and v[2:-1] in published:
                feeding.setdefault(v[2:-1], []).append(tool)
                assert c.override_coverage_fan, f"{tool} takes a harvested id but the fan's invalid probe still decides it"
                assert c.tier == "admin" and not c.skip_reason
    assert set(feeding) == published, published - set(feeding)


def test_the_records_keep_their_shape_only():
    for tool in ("theprotocol_getDiagnosticConfig", "theprotocol_getAdminOperatorApplication"):
        assert MCP_CONTRACTS[tool].excerpt_shape_only, tool
    rec = {"id": "c0a615f4-app", "email": "applicant@example.com", "env": {"A": "1"}, "list": [1, 2], "none": None}
    assert L.result_excerpt(rec, shape_only=True) == {"id": "str", "email": "str", "env": "dict(1 keys)",
                                                       "list": "list(2)", "none": "null"}
    assert McpContract(tier="admin").excerpt_shape_only is False


def test_the_harvest_lifecycle_publishes_into_the_bag_and_records_no_row():
    calls = []

    async def rpc(tool, args, jwt="", timeout=20):
        calls.append(tool)
        name = tool.replace("theprotocol_", "")
        return True, {"_answer": MEASURED.get(name)}, "200"

    class Bag:
        developer_jwt = "admin-jwt"
        flow_values = {}
    bag, outcomes = Bag(), {}
    asyncio.run(A.lifecycle_admin_fixture_harvest(rpc, lambda body: body.get("_answer"), bag, outcomes))
    assert outcomes == {} and sorted(calls) == sorted(A._HARVEST_READS)
    assert bag.flow_values["peer_registry_id"] == "9" and bag.flow_values["broadcast_id"] == 77
    assert A.ADMIN_LIFECYCLES[0]["runner"] is A.lifecycle_admin_fixture_harvest
    assert not set(A._HARVEST_READS) & A._LIFECYCLE_NEVER_INVOKE


def test_a_harvested_fixture_resolves_and_a_missing_one_stays_named():
    class Bag:
        flow_values = {"peer_registry_id": "9"}

        def get(self, k, d=None):
            return self.flow_values.get(k, d)
    c = MCP_CONTRACTS["theprotocol_getTopologyPeerEvents"]
    assert resolve_args(c.arguments, Bag()) == {"peer_id": "9", "limit": 5}
    assert unresolved_fixtures(resolve_args(MCP_CONTRACTS["theprotocol_getCloudOperatorHealth"].arguments, Bag())) == [
        "active_cloud_operator_id"]


def test_the_cloud_op_walk_never_calls_with_a_placeholder():
    from agentvault_registry.api_tests.categories.flow_mcp_lifecycle import test_flow_mcp_lifecycle as F
    src = inspect.getsource(F)
    assert "_cop_unres_args = unresolved_fixtures(adm_args)" in src
    assert "if tool_name in admin_lifecycle_outcomes and (not _cop_ov.override_coverage_fan or _cop_unres):" in src


def test_the_contract_v2_candidate_is_the_spine_ref_never_the_legacy_integer():
    from agentvault_registry.api_tests.categories.flow_mcp_lifecycle.test_flow_mcp_lifecycle import _contract_v2_candidate
    assert _contract_v2_candidate({"id": 1019, "ref": "ctr_5e0a6d528d8c"}) == "ctr_5e0a6d528d8c"
    assert _contract_v2_candidate({"id": -1, "ref": None}) is None
    assert _contract_v2_candidate({"contract_id": "ctr_x"}) == "ctr_x"
    assert _contract_v2_candidate({"id": "ctr_y"}) == "ctr_y" and _contract_v2_candidate({"id": "7"}) is None
