"""Admin-bridge MCP lifecycles (Phase 6 — 2026-05-26).

Mirrors mcp_lifecycles.py but for the 302-tool admin bridge mounted at
/mcp/admin/rpc. Each lifecycle takes:
    (rpc_admin: callable, parse: callable, bag: McpFixtureBag, outcomes: dict)

The `rpc_admin` callable hits the admin bridge directly. No tier
distinction inside the admin bridge — every admin-bridge tool requires
is_admin=True on the developer JWT (enforced at the dispatcher).

Coverage strategy:
- Empty-args fallback in the runner covers all 302 tools by default
  (every tool reachable = covered).
- These lifecycles add VALUE by calling high-traffic admin tools with
  real arguments + verifying responses.
- Read-after-write assertions: same pattern as public bridge.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

# Reuse the _exec_step helper from the public-bridge module — same shape.
from agentvault_registry.api_tests.contracts.mcp_lifecycles import _exec_step, _not_measured
from agentvault_registry.api_tests.contracts import earned_fixtures as _ef   # §MCPTEST30 (V0641): refusal rows
from agentvault_registry.api_tests.federation_suite.broadcast_cleanup import composed_id

# Bounded concurrency for big side-effect-free probe loops inside one
# orchestrator (e.g. dashboard_reads' 114 reads). Sized to ~registry worker
# count by default; env-tunable. Composes with the orchestrator-level lifecycle
# concurrency — total registry load is gated by the worker pool either way.
_PROBE_CONC = max(1, int(os.environ.get("MCP_TESTER_PROBE_CONCURRENCY", "8") or 8))

RpcCall = Callable[..., Awaitable[Tuple[bool, dict, str]]]
ParseResult = Callable[[dict], dict]

# §2026-06-01 — HARD GUARD. A lifecycle INVOKES every tool it lists. These
# meta / provisioning / suite / teardown / maintenance tools must NEVER be
# invoked from a lifecycle, because invoking them:
#   • self-POSTs /admin/api-test/test-flow → re-entrant fork-bomb loop that
#     survives container restart (testApiFlow / testApiFederation / runAll /
#     eagerBootstrapApiTest)
#   • provisions / tears down REAL cloud-ops & frames (provisionCloudOperator / teardownCloudOperator; the
#     Frame-A-era provisioner tests that also did are RETIRED, §NIGHTLYPROV 2026-09-27)
#   • resets the sandbox DB or restarts operators (resetApiTestSandbox /
#     restartCloudOperatorService / cloudOperatorSelfRestart)
#   • disables EVERY canary path — setCanaryMaintenance({enable:False}) with no
#     scope defaults scope="all" → is_active=False fleet-wide ([[feedback_set_canary_maintenance_state_leak]])
# mcp_contracts.py already skip-lists these for STANDALONE probes; this is the
# parallel guard for the lifecycle path that bypassed it
# ([[feedback_mcp_tester_invokes_provisioning_forkbomb]]).
# §MCPSWEEP 2026-09-27 — bytes that are not an image: the icon route answers 415 before it writes anything.
_NOT_AN_IMAGE_B64 = "cGhhc2U2LW5vdC1hbi1pbWFnZQ=="   # base64("phase6-not-an-image")

_LIFECYCLE_NEVER_INVOKE = frozenset({
    "theprotocol_runAllApiTests", "theprotocol_testApiFlow", "theprotocol_testApiCategory",
    "theprotocol_testApiFederation", "theprotocol_eagerBootstrapApiTest",
    "theprotocol_provisionCloudOperator", "theprotocol_teardownCloudOperator",
    "theprotocol_resetApiTestSandbox", "theprotocol_restartCloudOperatorService",
    "theprotocol_cloudOperatorSelfRestart", "theprotocol_setCanaryMaintenance",
    # §MCPTEST-MCP4 2026-08-08 — the simulation MUTATORS are denied so the
    # capability gate `ADMIN_SIMULATION_ENABLED` can be turned on for the
    # sandbox WITHOUT the sweep ever starting a real simulation. The sim is a
    # documented load hazard on this box (concurrency ramps to the deadman),
    # and starting one from a test sweep is exactly the kind of side effect a
    # tester must never have. The READ-ONLY sim tools (status / agents /
    # supply-audit / topology / deadman / fund-status / logs / funding-preview)
    # stay in the sweep and are the ones the gate actually unblocks.
    "theprotocol_startSimulation", "theprotocol_stopSimulation",
    "theprotocol_fundSimulationAgents", "theprotocol_issueFrameBSimulation",
    # §MCPSWEEP 2026-09-27 — these four were "probed" with arguments their tools never declared, so the dispatcher
    # answered -32602 Invalid params and the sweep counted it healthy (measured on sbx-alpha's audit rows of the
    # 03:00Z run). Given their DECLARED arguments they would act, so they are not probed at all:
    "theprotocol_tegCrossTegFund", "theprotocol_tegTreasuryReceive", "theprotocol_distributeFromFeeCollector",
    "theprotocol_federationRequestAdmission",
    # §MCPSWEEP V0464 — the tool now sends what its route requires, and any well-formed call mints a real licence.
    "theprotocol_generateFederationLicense",
})

# Why each guarded tool is not invoked, where the generic sentence below is not the true one.
_NEVER_INVOKE_REASONS: Dict[str, str] = {
    "theprotocol_fundSimulationAgents": "never invoked by tester: moves value (bulk-funds the simulation roster from "
                                        "the treasury) and takes no target that could be faked",
    "theprotocol_issueFrameBSimulation": "never invoked by tester: mints (genesis-equivalent for the simulation) and "
                                        "takes no target that could be faked",
    "theprotocol_tegCrossTegFund": "never invoked by tester: a one-way cross-TEG capital move; a refusal for an "
                                   "unknown target is not proven to precede the debit",
    "theprotocol_tegTreasuryReceive": "never invoked by tester: moves value (agent -> treasury)",
    "theprotocol_distributeFromFeeCollector": "never invoked by tester: moves value (fee_collector -> treasury / "
                                              "lock payout pool)",
    "theprotocol_federationRequestAdmission": "never invoked by tester: creates a PeerRegistry row and a compliance "
                                              "record for the named network before it is contacted, so a probe "
                                              "would plant a peer every night",
    "theprotocol_generateFederationLicense": "never invoked by tester: a well-formed call mints a real federation "
                                             "licence and takes no target that could be faked; its request shape is "
                                             "pinned offline by tests/test_mcp_tool_requests_meet_their_routes.py",
}


def _measured_for_real(outcomes: Dict[str, dict], tool: str) -> bool:
    """§MCPTEST30 (V0553): a probe of an id that names nothing never replaces a row measured on a real object.

    This sweep's rows start from the ones the public lifecycles recorded through the admin bridge
    (bag.admin_lifecycle_rows: the commons season, the EigenTrust epoch after the seed transfers). The probe lists run
    later and write by tool, so a probe would overwrite that measurement with a weaker one, or, for a tool without an
    argument to aim at nothing (triggerEigentrustComputation), do the real thing a second time. A row that is itself a
    named skip (NOT MEASURED) still lets the probe run."""
    row = outcomes.get(tool)
    return isinstance(row, dict) and not row.get("skip_reason")


SWEEP_BROADCAST_TITLE = "phase6 sweep"


async def broadcast_read_back(bag: Any, broadcast_id: Any, dev_jwt: str, outcomes: Dict[str, dict]) -> None:
    """V0649 (agentvault2-13): the sweep's composeBroadcast row passed on the compose call's 2xx alone (recorded by
    agentvault2-aa 2026-10-26 from agentvault2-66's read: "PASS ON SEND"). The notice goes to the run's own developer
    (V0645), so that developer reads it back through the receipt route GET /api/v1/notifications/{id}, which answers the
    broadcast to its addressee and 404 to anyone else. Never the unread list: lifecycle_notifications_2fa marks the
    newest unread notice read and would race it. The row stays a pass only when the notice reads back as sent; a flow
    without an in-target transport says the read-back was not measured (the send alone is no measurement)."""
    tool = "theprotocol_composeBroadcast"
    row = outcomes.get(tool)
    if not isinstance(row, dict) or not row.get("healthy") or row.get("skip_reason"):
        return
    if not str(broadcast_id or "").isdigit():
        row["healthy"] = False
        row["fail_reason"] = "composeBroadcast answered 2xx without a broadcast id, so nothing could be read back"
        return
    http = getattr(bag, "http_in_target", None)
    if http is None:
        outcomes[tool] = _not_measured(tool, "admin", "NOT MEASURED: composed (HTTP 2xx), but this flow has no in-target "
                                                      "transport to read the notice back on the run's own account")
        return
    code, text = await http("GET", f"/api/v1/notifications/{int(broadcast_id)}", bearer=dev_jwt)
    try:
        body = json.loads(text) if text else None
    except ValueError:
        body = None
    b = body.get("broadcast") if isinstance(body, dict) else None
    if code == "200" and isinstance(b, dict) and str(b.get("id")) == str(broadcast_id) \
            and b.get("title") == SWEEP_BROADCAST_TITLE and isinstance(body.get("read"), bool):
        row["read_back"] = "the run's developer reads the notice it was sent (GET /api/v1/notifications/{id}, 200)"
        return
    row["healthy"] = False
    row["fail_reason"] = (f"composeBroadcast answered 2xx, but the run's own developer cannot read the notice back: "
                          f"GET /api/v1/notifications/{{id}} answered HTTP {code or '?'}"
                          + ("" if isinstance(b, dict) else " without the broadcast"))


def _record_never_invoke_skip(tool: str, outcomes: Dict[str, dict]) -> None:
    """Record a clean skipped row (healthy, skip_reason set) for a guarded tool —
    matches the _make_outcome shape so the aggregator buckets it as skipped, not
    a failure or a coverage gap."""
    outcomes[tool] = {
        "tool_name": tool,
        "contract_tier": "admin",
        "healthy": True,
        "status_code": 0,
        "elapsed_ms": 0,
        "skip_reason": _NEVER_INVOKE_REASONS.get(
            tool, "never invoked by tester — provisions real infra / forks the api-tester / disables canaries"),
        "fail_reason": None,
        "has_explicit_contract": True,
        "args_used": {},
        "result_excerpt": {},
    }


async def lifecycle_admin_request_safe(rpc: RpcCall, parse: ParseResult,
                                          bag: Any, outcomes: Dict[str, dict]) -> None:
    """adminRequest catch-all HTTP proxy — exercise with a known GET endpoint."""
    dev_jwt = bag.developer_jwt
    await _exec_step(rpc, parse, "theprotocol_adminRequest", "admin",
                      {"method": "GET", "endpoint": "/api/v1/admin/dashboard"},
                      dev_jwt, outcomes, expect_status="any")
    # POST variant against safe read-back
    await _exec_step(rpc, parse, "theprotocol_adminRequest", "admin",
                      {"method": "GET", "endpoint": "/api/v1/admin/agents"},
                      dev_jwt, outcomes, expect_status="any",
                      record_as_separate=False)
    # Bad endpoint → expected 4xx, still exercised
    await _exec_step(rpc, parse, "theprotocol_adminRequest", "admin",
                      {"method": "GET", "endpoint": "/api/v1/phase6-no-such-endpoint"},
                      dev_jwt, outcomes, expect_status="any",
                      record_as_separate=False)


async def lifecycle_admin_query_event_store(rpc: RpcCall, parse: ParseResult,
                                              bag: Any, outcomes: Dict[str, dict]) -> None:
    """adminQueryEventStore — query recent events."""
    dev_jwt = bag.developer_jwt
    await _exec_step(rpc, parse, "theprotocol_adminQueryEventStore", "admin",
                      {"path": "/api/v1/events/", "params": {"limit": 5}},
                      dev_jwt, outcomes, expect_status="any")
    await _exec_step(rpc, parse, "theprotocol_adminQueryEventStore", "admin",
                      {"path": "/api/v1/projections/balances", "params": {}},
                      dev_jwt, outcomes, expect_status="any",
                      record_as_separate=False)


async def lifecycle_admin_prom_query(rpc: RpcCall, parse: ParseResult,
                                        bag: Any, outcomes: Dict[str, dict]) -> None:
    """adminPromQuery — basic PromQL."""
    dev_jwt = bag.developer_jwt
    await _exec_step(rpc, parse, "theprotocol_adminPromQuery", "admin",
                      {"query": "up"},
                      dev_jwt, outcomes, expect_status="any")
    # Range query
    import time as _t
    now = int(_t.time())
    await _exec_step(rpc, parse, "theprotocol_adminPromQuery", "admin",
                      {"query": "up",
                       "start": now - 300,
                       "end": now,
                       "step": "60s"},
                      dev_jwt, outcomes, expect_status="any",
                      record_as_separate=False)


async def lifecycle_admin_grafana_query(rpc: RpcCall, parse: ParseResult,
                                            bag: Any, outcomes: Dict[str, dict]) -> None:
    """adminGrafanaQuery — Grafana HTTP API read."""
    dev_jwt = bag.developer_jwt
    await _exec_step(rpc, parse, "theprotocol_adminGrafanaQuery", "admin",
                      {"path": "/api/health", "method": "GET"},
                      dev_jwt, outcomes, expect_status="any")
    # Get dashboards search
    await _exec_step(rpc, parse, "theprotocol_adminGrafanaQuery", "admin",
                      {"path": "/api/search", "method": "GET",
                       "params": {"limit": 5}},
                      dev_jwt, outcomes, expect_status="any",
                      record_as_separate=False)


async def lifecycle_admin_get_developer_token(rpc: RpcCall, parse: ParseResult,
                                                  bag: Any, outcomes: Dict[str, dict]) -> None:
    """adminGetDeveloperToken — mint a fresh dev JWT for any developer.
    Commander uses this to impersonate / sandbox-test other dev contexts.
    """
    dev_jwt = bag.developer_jwt
    # Self-mint (developer_id=1 is commander)
    await _exec_step(rpc, parse, "theprotocol_adminGetDeveloperToken", "admin",
                      {"email": "phase6-no-such@phase6.invalid", "password": "phase6-no-such-password"},
                      dev_jwt, outcomes, expect_status="any")


async def lifecycle_admin_dashboard_reads(rpc: RpcCall, parse: ParseResult,
                                             bag: Any, outcomes: Dict[str, dict]) -> None:
    """Big batch of read-only admin dashboards / aggregates.

    These all return JSON aggregates with no side effects.
    """
    dev_jwt = bag.developer_jwt
    _dash_tools = [
        "theprotocol_getAdminDashboard",
        "theprotocol_getAdminAgents",
        "theprotocol_getAdminDevelopers",
        "theprotocol_getAdminBroadcasts",
        "theprotocol_getAdminBroadcastsOverview",
        "theprotocol_getAdminFlags",
        "theprotocol_getAdminAuditLogs",
        "theprotocol_getAdminFundingPending",
        "theprotocol_getAdminFundingAll",
        "theprotocol_getAdminFiatStats",
        "theprotocol_getAdminFiatPurchases",
        "theprotocol_getAdminFiatPricing",
        "theprotocol_getAdminFiatFlares",
        "theprotocol_getAdminWorkersStatus",
        "theprotocol_getAdminSimulationStatus",
        "theprotocol_getAdminSimulationAgents",
        "theprotocol_getAdminSimulationFundStatus",
        "theprotocol_getAdminSimulationDeadmanStatus",
        "theprotocol_getAdminSimulationTopology",
        "theprotocol_getAdminSimulationLogs",
        "theprotocol_getAdminSimulationSupplyAudit",
        "theprotocol_getAdminTestTokens",
        "theprotocol_getAdminMetricsAgentActivity",
        "theprotocol_getAdminFederationSelfHealth",
        "theprotocol_getAdminFederationPolicyCompliance",
        "theprotocol_getAdminHealthCheckSimple",
        "theprotocol_getAdminHealthCheckPublicOnly",
        "theprotocol_getAdminHealthCheckAuthenticated",
        "theprotocol_getReactorStatus",
        "theprotocol_getEventEmissionPolicies",
        "theprotocol_getCloudOperators",
        "theprotocol_getTreasuryAggregate",
        "theprotocol_getBridgeAggregate",
        "theprotocol_getWebhookAggregate",
        "theprotocol_getCanaryStatus",
        "theprotocol_getCanaryResults",
        "theprotocol_getCollusionStatus",
        "theprotocol_getCollusionRings",
        "theprotocol_getCombinedHealth",
        "theprotocol_getDockerStats",
        "theprotocol_getSystemResources",
        "theprotocol_getPrometheusMetrics",
        "theprotocol_getEnforcementPending",
        "theprotocol_getEnforcementPolicy",
        "theprotocol_getEnforcementPolicyDefaults",
        "theprotocol_getEventStoreStats",
        "theprotocol_getEventStoreRecent",
        "theprotocol_getEventStoreBalances",
        "theprotocol_getEventStoreCrossFramePeers",
        "theprotocol_getEventStoreFederationOperators",
        "theprotocol_getFederationComplianceOverview",
        "theprotocol_getFederationComplianceDrifts",
        "theprotocol_getFederationComplianceEvents",
        "theprotocol_getFederationComplianceEnforcementMode",
        "theprotocol_getFederationLocalEvents",
        "theprotocol_getFederationSyncPeers",
        "theprotocol_getFederationSyncStatus",
        "theprotocol_getFederationTopologyOverview",
        "theprotocol_getAllFederationPeersAdmin",
        "theprotocol_getPendingPeerRegistries",
        "theprotocol_listFederationLicenses",
        "theprotocol_listIronhandIdentities",
        "theprotocol_listQuarantinedRegistries",
        "theprotocol_listAdminFrameInvitations",
        "theprotocol_listAdminOperatorApplications",
        "theprotocol_listAdminBundlesReports",
        "theprotocol_getInviteCodes",
        "theprotocol_getEmailTemplates",
        "theprotocol_getBroadcastTemplates",
        "theprotocol_getBroadcastSchedulerStatus",
        "theprotocol_getBroadcastEmailRetryStatus",
        "theprotocol_getBroadcastEmailRetryDeadLetter",
        "theprotocol_getApiTestEndpoints",
        "theprotocol_getApiTestFlowValues",
        "theprotocol_getApiTestArchiveRuns",
        "theprotocol_getApiTestSandboxCredentials",
        "theprotocol_getApiTestBucketClassification",
        "theprotocol_getAttestationsAnalytics",
        "theprotocol_getTransactionsAnalytics",
        "theprotocol_getFeeCollectorInfo",
        "theprotocol_getPayoutFundingPolicy",
        "theprotocol_getOperatorsLifecycleOverview",
        "theprotocol_getFramesSpireStatus",
        "theprotocol_getCanaryIronhandStatus",
        "theprotocol_getCanaryIronhandEvents",
        "theprotocol_getCanaryIronhandSvids",
        "theprotocol_getCanaryJudgeStatus",
        "theprotocol_getCanaryJudgeEvents",
        "theprotocol_getCanaryRebalancerStatus",
        "theprotocol_getCanaryRebalancerEvents",
        "theprotocol_getCrossTegSweeperStatus",
        "theprotocol_getCrossTegSweeperEvents",
        "theprotocol_getSagaTimeoutStatus",
        "theprotocol_getSagaTimeoutEvents",
        "theprotocol_getSupplyAuditorStatus",
        "theprotocol_getSupplyAuditorEvents",
        "theprotocol_getCicdSummary",
        "theprotocol_getCicdDeployments",
        "theprotocol_getRecentWebhookDeliveries",
        "theprotocol_getTutorialHealth",
        "theprotocol_getDiagnosticChecks",
        "theprotocol_getDiagnosticTargets",
        "theprotocol_getDiagnosticActions",
        "theprotocol_getAdminFederationPolicyCompliance",
        "theprotocol_supportListTickets",
    ]
    # Parallelize these independent side-effect-free admin reads — the single
    # dominant lifecycle bottleneck (~285s sequential at ~2.5s/call). Bounded to
    # ~worker count so we overlap server latency without over-saturating;
    # outcomes writes are per-tool (atomic in single-threaded asyncio).
    _dash_sem = asyncio.Semaphore(_PROBE_CONC)
    async def _one_dash(tool):
        async with _dash_sem:
            await _exec_step(rpc, parse, tool, "admin",
                              {}, dev_jwt, outcomes, expect_status="any")
    await asyncio.gather(*[_one_dash(t) for t in _dash_tools])


async def lifecycle_admin_id_lookups(rpc: RpcCall, parse: ParseResult,
                                        bag: Any, outcomes: Dict[str, dict]) -> None:
    """Admin lookups that need an id — use sentinel / fake ids as needed."""
    dev_jwt = bag.developer_jwt
    fake_did = "did:theprotocol:phase6-no-such-agent"
    for tool, args in [
        ("theprotocol_getAdminAgentDetail",            {"agent_did": bag.sentinel_did}),
        ("theprotocol_getAdminAgentFlags",             {"agent_did": bag.sentinel_did}),
        ("theprotocol_getAdminAgentSigningKeys",       {"agent_did": bag.sentinel_did}),
        ("theprotocol_getAdminAgentOrphans",           {}),
        ("theprotocol_getAdminAgentsByDeveloper",      {"developer_id": int(bag.developer_id) if str(bag.developer_id).isdigit() else 1}),
        ("theprotocol_getAdminCollusionByAgent",       {"agent_did": bag.sentinel_did}),
        ("theprotocol_getAdminDeveloperDetail",        {"developer_id": int(bag.developer_id) if str(bag.developer_id).isdigit() else 1}),
        ("theprotocol_getAdminDeveloperActivity",      {"developer_id": int(bag.developer_id) if str(bag.developer_id).isdigit() else 1}),
        ("theprotocol_getAdminDeveloperQuota",         {"developer_id": int(bag.developer_id) if str(bag.developer_id).isdigit() else 1}),
        ("theprotocol_getAdminFiatPurchaseDetail",     {"purchase_id": "phase6-no-such-purchase"}),
        ("theprotocol_getAdminFrameInvitation",        {"invitation_id": "phase6-no-such-invite"}),
        ("theprotocol_getAdminOperatorApplication",    {"application_id": "phase6-no-such-app"}),
        ("theprotocol_getAdminRegistryCard",           {}),
        ("theprotocol_getAdminMcpAuditLogByActor",     {"actor_id": bag.sentinel_did}),
        ("theprotocol_getPeerRegistryCard",            {"peer_id": "phase6-no-such-peer"}),
        ("theprotocol_getOperatorLifecycle",           {}),
        ("theprotocol_getFederationLicenseDetail",     {"license_id": "phase6-no-such-license"}),
        ("theprotocol_getFederationCompliancePeerByID",{"peer_id": "phase6-no-such-peer"}),
        ("theprotocol_getFederationCompliancePeerByOperator",{"operator_id": "phase6-no-such-op"}),
        ("theprotocol_getCloudOperatorHealth",         {"application_id": "phase6-no-such-app"}),
        ("theprotocol_getCloudOperatorLogs",           {"application_id": "phase6-no-such-app"}),
        ("theprotocol_getCloudOperatorSelfLogs",       {}),
        ("theprotocol_getBroadcastTemplateDetail",     {"template_id": "phase6-no-such-template"}),
        ("theprotocol_getAgentCardDriftDetail",        {"did": fake_did}),
        ("theprotocol_getAgentCardDriftList",          {}),
        ("theprotocol_getAgentCardPullsyncStatus",     {}),
        ("theprotocol_getAgentCardPullsyncEvents",     {}),
        ("theprotocol_getAgentHealthStatus",           {}),
        ("theprotocol_getAgentHealthTransitions",      {}),
        ("theprotocol_getHealthCheckWithAgentAuth",    {}),
        # §MCPSWEEP 2026-09-27 — these six sat in the dashboard batch, called with {} although each REQUIRES an id,
        # so every one answered -32602 Invalid params and was counted healthy. A nonexistent id measures the refusal.
        # §MCPTEST30 (V0550): round 15 read these as refusals of the PROBE (rule 3): the route parses an integer or a UUID,
        # so a malformed id measured its own validation and never the tool. A well-formed id that names nothing reaches the
        # route's lookup and its own refusal (each route read: it looks the id up before it writes, dials or revokes).
        ("theprotocol_getAdmissionStatus",             {"admission_id": "00000000-0000-4000-8000-000000000000"}),
        ("theprotocol_getBridgeStatus",                {"bridge_tx_id": "phase6-no-such-bridge-tx"}),
        ("theprotocol_getBroadcastStats",              {"broadcast_id": 999999}),
        ("theprotocol_getDiagnosticConfig",            {"target_id": "phase6-no-such-target"}),
        ("theprotocol_getEventsAggregate",             {"aggregate_id": "phase6-no-such-aggregate"}),
        ("theprotocol_getTopologyPeerEvents",          {"peer_id": "999999"}),
    ]:
        await _exec_step(rpc, parse, tool, "admin", args,
                          dev_jwt, outcomes, expect_status="any")


# §MCPTEST30 (V0641): the admin tools on routes that take only a federation peer's identity (require_peer_registry_identity:
# 401 to the admin's developer token; the request survey's PEER_ROUTE, V0547). lifecycle_admin_destructive_safe probed
# each under its own name and the contracts pinned the refusal (override_coverage_fan), so each passed on a refusal
# alone: "refusal only" on both sandbox operators in V0639's read (2026-10-25), as on the frames. Said by design on
# their own rows now, the 401 a refusal row, as earned_agent_public does for the public and developer peer-only tools.
_PEER_ONLY_OPEN = ("whether the tool stays on the MCP surface is an open decision, "
                   "FINDINGS_2026-10-02_PEER_ONLY_MCP_TOOLS")
ADMIN_PEER_ONLY_TOOLS: Tuple[Tuple[str, str], ...] = (
    ("theprotocol_blockFederationAgent",
     "a federation peer asks this registry to block one of the peer's agents: the route takes only a federation "
     f"peer's identity (mTLS, the internal secret or a licence), which no MCP caller carries, by design ({_PEER_ONLY_OPEN})"
     ". Its refusal is a refusal row"),
    ("theprotocol_unblockFederationAgent",
     "a federation peer asks this registry to lift such a block: the route takes only a federation peer's identity, "
     f"which no MCP caller carries, by design ({_PEER_ONLY_OPEN}). Its refusal is a refusal row"),
    ("theprotocol_ironhandRegisterAgentProxy",
     "a peer operator asks this frame to register one of its agents' SPIRE entries: the route takes only a federation "
     f"peer's identity, which no MCP caller carries, by design ({_PEER_ONLY_OPEN}). Its refusal is a refusal row"),
    ("theprotocol_ironhandDeleteAgentProxy",
     "a peer operator asks this frame to delete one of its agents' SPIRE entries: the route takes only a federation "
     f"peer's identity, which no MCP caller carries, by design ({_PEER_ONLY_OPEN}). Its refusal is a refusal row"),
)


def _peer_only_args(tool: str, fake_did: str) -> Dict[str, Any]:
    """What a peer-only admin tool's refusal row sends: the arguments the tool requires, naming nothing."""
    if tool == "theprotocol_blockFederationAgent":
        return {"agent_did": fake_did, "reason": "phase-6 sweep"}
    if tool == "theprotocol_ironhandRegisterAgentProxy":
        return {"agent_did": fake_did, "spire_data": {"parent_fingerprint": "phase6"}}
    return {"agent_did": fake_did}


_SNAPSHOT = "theprotocol_triggerProjectionSnapshot"


def _projection_snapshots_on() -> bool:
    """ENABLE_PROJECTION_SNAPSHOTS as the target reads it: the lifecycle runs in the target's own process, and the rule
    is its route's (routers/admin_health.py take_projection_snapshot: true, 1 or yes, in any case)."""
    return os.getenv("ENABLE_PROJECTION_SNAPSHOTS", "").lower() in ("true", "1", "yes")


async def _projection_snapshot_step(rpc: RpcCall, parse: ParseResult, dev_jwt: str, outcomes: Dict[str, dict]) -> None:
    """§MCPTEST30 (V0638, agentvault2-aa; agentvault2-d6's call): a run never takes a projection snapshot.

    The sweep's probe took no argument, so where the switch is on it took a real one: a snapshot re-baselines the
    frame's ledger projection whenever its event fits the store's bus, and on sbx-alpha (10,254 active agents, 1,074,935
    bytes) the bus refused it while the route answered "snapshot_taken" and the outbox retried it for twelve hours, one
    per run (D6-818). On: NOT MEASURED by design, the tool never called. Off: the route's 403 is measured on its refusal
    row, and the tool's own row is NOT MEASURED, said."""
    if _measured_for_real(outcomes, _SNAPSHOT):
        return
    if _projection_snapshots_on():
        outcomes[_SNAPSHOT] = _not_measured(
            _SNAPSHOT, "admin", "NOT MEASURED by design: ENABLE_PROJECTION_SNAPSHOTS is on here, and a projection snapshot "
            "re-baselines the frame's ledger projection; a run never takes one")
        return
    await _ef.refusal_step(rpc, parse, _SNAPSHOT, "admin", {}, dev_jwt, outcomes, "with its switch off",
                           codes=(403,), text="Projection snapshots disabled")
    outcomes[_SNAPSHOT] = _not_measured(
        _SNAPSHOT, "admin", "NOT MEASURED: ENABLE_PROJECTION_SNAPSHOTS is off here, so the route refuses every caller (its "
        "403 is the refusal row); a run never takes a snapshot where it is on")


async def lifecycle_admin_destructive_safe(rpc: RpcCall, parse: ParseResult,
                                                bag: Any, outcomes: Dict[str, dict]) -> None:
    """Admin destructive paths against deliberately-nonexistent targets
    (expects 4xx). Coverage-only. Mirrors the public-bridge variant but
    via the admin bridge endpoint."""
    dev_jwt = bag.developer_jwt
    fake_did = "did:theprotocol:phase6-no-such-agent"
    fake_dev = 999999
    composed: Optional[int] = None
    own_dev = _ef.own_developer_id(bag)   # §MCPTEST30 V0645: the sweep's broadcast is a direct notice to the run's own

    for tool, args in [
        ("theprotocol_acceptComplianceBaseline", {"peer_id": "999999", "expected_hash": "0" * 64,
                                                  "reason": "phase-6 sweep probe"}),  # an integer id that names nothing (V0561)
        ("theprotocol_acknowledgeAgentFlag", {"agent_did": fake_did, "flag_id": "00000000-0000-4000-8000-000000000000"}),
        ("theprotocol_adminDownloadOperatorBundle", {"application_id": "phase6-no-such-app"}),
        # §MCPTEST30 (V0550): round 15 read these as refusals of the PROBE (rule 3): the route parses an integer or a UUID,
        # so a malformed id measured its own validation and never the tool. A well-formed id that names nothing reaches the
        # route's lookup and its own refusal (each route read: it looks the id up before it writes, dials or revokes).
        ("theprotocol_adminRevokeAttestation", {"attestation_id": "00000000-0000-4000-8000-000000000000", "reason": "phase-6 sweep"}),
        ("theprotocol_approveFrameInvitation", {"invitation_id": "phase6-no-such-invite"}),
        ("theprotocol_approveFunding", {"request_id": 999999}),
        ("theprotocol_approveOperatorApplication", {"application_id": "phase6-no-such-app"}),
        ("theprotocol_approvePeerRegistry", {"peer_id": "999999"}),
        ("theprotocol_approvePendingEnforcement", {"action_id": "phase6-no-such-enforce"}),
        ("theprotocol_backfillPullTokens", {}),
        ("theprotocol_blacklistRegistry", {"peer_id": "999999", "reason": "phase-6 sweep probe"}),
        ("theprotocol_bridgeIssueWrapped", {"agent_did": fake_did, "amount": "0.001", "source_frame": "phase6-no-such"}),
        ("theprotocol_bridgeRedeem", {"bridge_tx_id": "phase6-no-such-tx", "agent_did": fake_did}),
        ("theprotocol_bridgeUnlock", {"bridge_tx_id": "phase6-no-such-tx"}),
        # §pass73.3.19: pass a REAL did so this genuinely runs (200 + {requested,
        # succeeded,failed,skipped} envelope) instead of the empty-list validation
        # error that the eval fix now (correctly) records as a 400. Agents without a
        # served card URL come back status="skipped" — a correct, real 200 outcome.
        ("theprotocol_bulkRefreshAgentCards", {"agent_dids": [bag.sentinel_did]}),
        ("theprotocol_bulkReinstateAgents", {"agent_dids": [fake_did]}),
        ("theprotocol_bulkSuspendAgents", {"agent_dids": [fake_did], "reason": "phase-6 sweep"}),
        ("theprotocol_cloudOperatorSelfRestart", {}),
        ("theprotocol_completeAdmission", {"admission_id": "00000000-0000-4000-8000-000000000000"}),  # a UUID that names nothing (V0550, rule 3)
        ("theprotocol_composeBroadcast", {"title": SWEEP_BROADCAST_TITLE, "body": "phase6 admin-bridge sweep test", "broadcast_type": "info",
                                          "target_developer_id": own_dev}),
        ("theprotocol_deactivatePeerRegistry", {"peer_id": "999999"}),
        ("theprotocol_deleteAdminAgent", {"agent_did": fake_did, "reason": "phase-6 sweep probe of an agent that does not exist",
                                          "confirm_did": "did:theprotocol:phase6-confirm-mismatch"}),
        ("theprotocol_deleteFederationLicense", {"license_id": "phase6-no-such-license"}),
        ("theprotocol_deleteOauthFederationTrust", {"registry_url": "https://phase6-no-such-trust.invalid"}),
        ("theprotocol_deleteSpireOrphan", {"spiffe_id": "spiffe://phase6.invalid/agent/did-theprotocol-phase6-no-such"}),
        ("theprotocol_disableDeveloper2FA", {"developer_id": fake_dev, "reason": "phase-6 sweep probe"}),
        ("theprotocol_disableWebhookAdmin", {"webhook_id": "phase6-no-such-webhook"}),
        ("theprotocol_dismissBundleReport", {"report_id": 999999, "resolution": "phase6-probe"}),
        ("theprotocol_distributeFromFeeCollector", {"amount": "0", "reason": "phase-6 sweep"}),
        ("theprotocol_eagerBootstrapApiTest", {}),
        ("theprotocol_enableWebhookAdmin", {"webhook_id": "phase6-no-such-webhook"}),
        ("theprotocol_federationCliAudit", {"action": "phase6-probe", "cli_version": "0", "actor_host": "phase6",
                                           "actor_user": "phase6"}),
        ("theprotocol_federationDriftScan", {}),
        ("theprotocol_federationPolicyUpdateRequest", {"peer_did": "did:theprotocol:phase6-no-such",
                                                      "proposed_policy_json": {"phase6": True}}),
        ("theprotocol_federationRequestAdmission", {"registry_name": "phase6", "registry_operator_did": "did:theprotocol:phase6-no-such",
                                                   "registry_public_url": "https://phase6.invalid",
                                                   "admin_contact_email": "phase6@phase6.invalid", "policy_json": {"phase6": True}}),
        ("theprotocol_finalizeRetryFrameInvitation", {"invitation_id": "phase6-no-such-invite"}),
        ("theprotocol_fireCanaryPath", {"path_id": 999999}),
        ("theprotocol_forceDeveloperPasswordReset", {"developer_id": fake_dev}),
        ("theprotocol_forceEmailVerify", {"developer_id": fake_dev}),
        ("theprotocol_forceMtlsEnroll", {"agent_did": fake_did}),
        ("theprotocol_forceRegisterAgentCard", {"did": fake_did}),
        ("theprotocol_fundSimulationAgents", {}),
        ("theprotocol_generateFederationLicense", {"operator_name": "phase6-probe", "operator_did": "did:theprotocol:phase6-no-such"}),
        ("theprotocol_generateInviteCodes", {"count": 0}),   # V0637: refused (count >= 1); a code of 1 stayed unused,
                                                               # with no note or expiry (earned_ad_developers makes and revokes one)
        ("theprotocol_generateTutorialProof", {"tutorial_id": "phase6-no-such-tutorial"}),
        ("theprotocol_giftProvisioning", {"developer_id": fake_dev, "months": 1, "reason": "phase-6 sweep probe"}),
        ("theprotocol_grantFiatFlare", {"developer_id": fake_dev, "flare_tier": "phase6-not-a-tier"}),
        ("theprotocol_hideBundle", {"bundle_id": "00000000-0000-4000-8000-000000000000", "reason": "phase-6 sweep probe"}),
        ("theprotocol_ironhandEnrollAgent", {"agent_did": fake_did}),
        ("theprotocol_ironhandRevokeAgent", {"agent_did": fake_did}),
        ("theprotocol_liftQuarantine", {"peer_id": "999999", "new_policy_hash": "phase6-bad-hash"}),  # an integer id that names nothing (V0550, rule 3)
        ("theprotocol_issueFrameBSimulation", {}),
        ("theprotocol_patchDeveloperQuota", {"developer_id": fake_dev, "quota_updates": {"agents_max": 5}}),
        ("theprotocol_pauseAgentPayouts", {"agent_did": fake_did, "reason": "phase-6 sweep"}),
        ("theprotocol_pollPeerComplianceNow", {"peer_id": "999999"}),  # an integer id that names nothing (V0550, rule 3)
        ("theprotocol_previewAdminEmail", {"template": "funding_approved"}),  # §pass73.3.21: real template (was "welcome"→400); read-only render, no side effect
        ("theprotocol_previewQuarantine", {}),
        ("theprotocol_previewSlash", {"agent_did": fake_did, "amount": 1}),
        ("theprotocol_probeTopologyPeer", {"peer_id": "999999"}),  # an integer id that names nothing (V0550, rule 3)
        ("theprotocol_provisionCloudOperator", {"application_id": "phase6-no-such-app"}),
        ("theprotocol_quarantineRegistry", {"peer_id": "999999", "reason": "phase-6 sweep"}),  # an integer id that names nothing (V0550, rule 3)
        ("theprotocol_reactivatePeerRegistry", {"peer_id": "999999"}),
        ("theprotocol_reconcileFiatProvisioning", {"developer_id": fake_dev}),
        ("theprotocol_recordAgentOffense", {"agent_did": fake_did, "offense_type": "phase6_test", "reference": "phase-6 sweep"}),
        ("theprotocol_refreshAgentCardDrift", {"did": fake_did}),
        ("theprotocol_refundFiatPurchase", {"purchase_id": "phase6-no-such-purchase"}),
        ("theprotocol_reinstateAgentEnforcement", {"agent_did": fake_did, "reason": "phase-6 sweep"}),
        ("theprotocol_reinstateBroadcast", {"broadcast_id": 999999}),
        ("theprotocol_reinstateDeveloper", {"developer_id": fake_dev}),
        ("theprotocol_reinstateFederationLicense", {"license_id": "phase6-no-such-license"}),
        ("theprotocol_reinstateOperator", {"application_id": "phase6-no-such-app"}),
        ("theprotocol_rejectFrameInvitation", {"invitation_id": "phase6-no-such-invite", "reason": "phase-6 sweep probe"}),
        ("theprotocol_rejectFunding", {"request_id": 999999, "reason": "phase-6 sweep"}),
        ("theprotocol_rejectOperatorApplication", {"application_id": "phase6-no-such-app", "reason": "phase-6 sweep"}),
        ("theprotocol_rejectPeerRegistry", {"peer_id": "999999"}),
        ("theprotocol_rejectPendingEnforcement", {"action_id": "phase6-no-such-enforce", "reason": "phase-6 sweep probe"}),
        ("theprotocol_replayFiatPurchase", {"purchase_id": "phase6-no-such-purchase"}),
        ("theprotocol_resendFiatMagicLink", {"purchase_id": "phase6-no-such-purchase"}),
        ("theprotocol_resetApiTestFlowValues", {}),
        ("theprotocol_resetApiTestSandbox", {}),
        ("theprotocol_restartCloudOperatorService", {"application_id": "phase6-no-such-app"}),
        ("theprotocol_resumeAgentPayouts", {"agent_did": fake_did}),
        ("theprotocol_resyncFrameEventStore", {"peer_id": "999999"}),
        ("theprotocol_retractBroadcast", {"broadcast_id": 999999}),
        ("theprotocol_revokeDeveloperApiKeys", {"developer_id": fake_dev}),
        ("theprotocol_revokeFederationLicense", {"license_id": "phase6-no-such-license", "reason": "phase-6 sweep"}),
        ("theprotocol_revokeFiatFlare", {"developer_id": fake_dev}),
        ("theprotocol_revokeFrame", {"peer_id": "999999", "reason": "phase-6 sweep probe"}),
        ("theprotocol_revokeInviteCode", {"code": "phase6-no-such-code"}),
        ("theprotocol_revokeOperatorAccess", {"application_id": "phase6-no-such-app", "reason": "phase-6 sweep"}),
        ("theprotocol_rotateAgentCredentials", {"agent_did": fake_did}),
        ("theprotocol_rotateAgentSigningKey", {"agent_did": fake_did}),
        ("theprotocol_rotateOperatorPullToken", {"application_id": "phase6-no-such-app"}),
        ("theprotocol_rotateRegistrySigningKey", {}),
        ("theprotocol_runAllDiagnostics", {"target": "phase6-no-such-target"}),   # §MCPTEST30: no probe names a retired node
        ("theprotocol_runAttestationExpirySweep", {}),
        ("theprotocol_runAttestationScheduleCron", {}),
        ("theprotocol_runDiagnosticsSubset", {"targets": ["phase6-no-such-target"], "checks": ["phase6-no-such"]}),
        ("theprotocol_searchAdminEvents", {"event_type": "Phase6NoSuchEvent"}),   # §MCPTEST30: no free-text query exists
        ("theprotocol_setCanaryMaintenance", {"enable": False}),
        ("theprotocol_setEventEmissionPolicy", {"event_type": "phase6-no-such-event",
                                                   "emit_from_teg": False, "emit_from_registry": True}),
        ("theprotocol_setFederationComplianceEnforcementMode", {"mode": "phase6-not-a-mode", "reason": "phase-6 sweep probe"}),
        ("theprotocol_simulateFiatPricing", {"purchases_eur": ["1.00"], "starting_treasury_avt": "1000",
                                            "starting_fee_collector_avt": "0"}),
        ("theprotocol_simulationFundingPreview", {}),
        ("theprotocol_slashAgent", {"agent_did": fake_did, "amount": 1, "reason": "phase-6 sweep"}),
        ("theprotocol_softDeleteDeveloper", {"developer_id": fake_dev,
                                            "reason": "phase-6 sweep probe of a developer that does not exist",
                                            "confirm_email": "phase6@phase6.invalid"}),
        ("theprotocol_stopSimulation", {}),
        ("theprotocol_suspendAgent", {"agent_did": fake_did, "reason": "phase-6 sweep"}),
        ("theprotocol_suspendDeveloper", {"developer_id": fake_dev, "reason": "phase-6 sweep"}),
        ("theprotocol_suspendFederationLicense", {"license_id": "phase6-no-such", "reason": "phase-6 sweep"}),
        ("theprotocol_suspendOperator", {"application_id": "phase6-no-such-app", "reason": "phase-6 sweep"}),
        ("theprotocol_svidRefresh", {}),
        ("theprotocol_teardownCloudOperator", {"application_id": "phase6-no-such-app"}),
        ("theprotocol_tegCrossTegFund", {"target_registry": "phase6-no-such", "amount": "0", "reason": "phase-6 sweep"}),
        ("theprotocol_tegTreasuryIssue", {"amount": "0", "reason": "phase-6 path test"}),
        ("theprotocol_tegTreasuryReceive", {"source_agent_did": fake_did, "amount": "0", "reason": "phase-6 sweep"}),
        ("theprotocol_testApiCategory", {"category": "phase6-no-such-category"}),
        ("theprotocol_testApiEndpoint", {"endpoint_path": "/api/v1/phase6-no-such-endpoint", "method": "GET"}),
        ("theprotocol_testApiFederation", {}),
        ("theprotocol_testApiFlow", {"flow_name": "phase6-no-such-flow"}),
        ("theprotocol_testWebhookAdmin", {"webhook_id": "phase6-no-such-webhook"}),
        ("theprotocol_toggleCanaryPath", {"path_id": 999999}),
        ("theprotocol_transferAgentOwnership", {"agent_did": fake_did, "new_creator_developer_id": fake_dev, "reason": "phase-6 sweep"}),
        ("theprotocol_triggerDiagnosticAction", {"action_id": "phase6-no-such-action", "target": "phase6-no-such-target", "dry_run": True}),
        ("theprotocol_triggerEigentrustComputation", {}),
        ("theprotocol_triggerSupplyAudit", {}),
        ("theprotocol_unhideBundle", {"bundle_id": "00000000-0000-4000-8000-000000000000"}),
        ("theprotocol_updateBroadcast", {"broadcast_id": 999999, "body": "phase-6 no-such"}),
        ("theprotocol_updateDeveloperAdminFlags", {"developer_id": fake_dev, "admin_flags": {"admin_treasury": False}}),
        ("theprotocol_updateDisputeRuling", {"dispute_id": "999999", "ruling": "PHASE6_NOT_A_RULING"}),
        ("theprotocol_updateEnforcementPolicy", {"policy_json": {"phase6": True}, "reason": "phase-6 path test"}),
        ("theprotocol_updateSupportTicketStatus", {"ticket_id": 999999, "status": "open"}),
        ("theprotocol_uploadRegistryCardIcon", {"icon_b64": _NOT_AN_IMAGE_B64, "content_type": "image/png"}),
        ("theprotocol_validateFederationPolicy", {"policy": {"phase6": True}}),
        ("theprotocol_validateFiatPricing", {"config": {}, "note": "phase-6 sweep probe"}),
        ("theprotocol_validateInviteCodeAdmin", {"code": "phase6-no-such-code"}),
        ("theprotocol_supportReplyTicket", {"ticket_id": 999999, "message": "phase-6 sweep reply"}),
        ("theprotocol_supportCloseTicket", {"ticket_id": 999999, "status": "resolved", "message": "phase-6 close"}),
        ("theprotocol_startSimulation", {}),  # without scenario → expects 4xx
    ]:
        if tool in _LIFECYCLE_NEVER_INVOKE:
            _record_never_invoke_skip(tool, outcomes)
            continue
        if _measured_for_real(outcomes, tool):
            continue
        if tool == "theprotocol_composeBroadcast" and own_dev is None:
            # a broadcast to everyone reaches every developer of the federation (V0644's operator read): not the run's
            _ef.unmeasured(outcomes, tool, "admin", "the run names no developer of its own to address its broadcast to, "
                                                    "and a broadcast to every developer of the federation is not the "
                                                    "run's to send")
            continue
        _ok, _inner = await _exec_step(rpc, parse, tool, "admin", args,
                                       dev_jwt, outcomes, expect_status="any")
        if tool == "theprotocol_composeBroadcast" and _ok:
            composed = composed_id(_inner)
            await broadcast_read_back(bag, composed, dev_jwt, outcomes)
    for tool, why in ADMIN_PEER_ONLY_TOOLS:
        if _measured_for_real(outcomes, tool):
            continue
        _ef.unmeasured(outcomes, tool, "admin", why)
        await _ef.refusal_step(rpc, parse, tool, "admin", _peer_only_args(tool, fake_did), dev_jwt, outcomes,
                               "a caller without a federation peer's identity", codes=(401,),
                               text="federation authentication required")
    await _projection_snapshot_step(rpc, parse, dev_jwt, outcomes)
    # §MCPTEST30 (V0559): the sweep takes back the broadcast it composed. Every run left one "phase6 sweep" broadcast
    # active, and the newest scrolled across every console's header on the target for good. The cleanup adds no row:
    # retractBroadcast's own row is the probe above (an id that names nothing).
    if composed:
        await _exec_step(rpc, parse, "theprotocol_retractBroadcast", "admin", {"broadcast_id": composed},
                         dev_jwt, outcomes, expect_status="any", record_as_separate=False)


async def lifecycle_admin_event_emission_policy_rw(rpc: RpcCall, parse: ParseResult,
                                                       bag: Any, outcomes: Dict[str, dict]) -> None:
    """getEventEmissionPolicies → setEventEmissionPolicy (with bogus event_type
    → expects 4xx, no real state change)."""
    dev_jwt = bag.developer_jwt
    await _exec_step(rpc, parse, "theprotocol_getEventEmissionPolicies", "admin",
                      {}, dev_jwt, outcomes, expect_status="any")
    # Update a deliberately-unknown event_type (won't conflict with real policies)
    await _exec_step(rpc, parse, "theprotocol_setEventEmissionPolicy", "admin",
                      {"event_type": "Phase6NoSuchEvent",
                       "emit_from_teg": False,
                       "emit_from_registry": True,
                       "skip_in_projection": False},
                      dev_jwt, outcomes, expect_status="any")


_BASELINE_PEERS = 5


# §MCPTEST30 (V0561): acceptComplianceBaseline measured on a real peer, without changing it. The overview names a
# federated peer with a baseline; its detail reads the hash the peer publishes now. A hash the peer does NOT publish is
# refused (409, nothing written); the stored hash, while the peer still publishes it, answers "unchanged" (nothing
# written). A peer that drifted is never accepted by a tester: accepting a drift is an admin's decision, so on such a
# frame the success path stays unmeasured and the refusal row stands.
async def lifecycle_admin_compliance_baseline(rpc: RpcCall, parse: ParseResult,
                                              bag: Any, outcomes: Dict[str, dict]) -> None:
    dev_jwt = bag.developer_jwt
    _ok, ov = await _exec_step(rpc, parse, "theprotocol_getFederationComplianceOverview", "admin", {}, dev_jwt,
                               outcomes, expect_status="success", record_as_separate=False)
    peers = (ov.get("peers") or []) if isinstance(ov, dict) else []
    rows = [p for p in peers if isinstance(p, dict) and p.get("has_compliance_record")
            and p.get("federation_status") == "federated" and p.get("peer_registry_id")
            and str(p.get("peer_status") or "").upper() == "ACTIVE"][:_BASELINE_PEERS]
    if not rows:
        return   # no federated peer with a baseline here: phase 6's refusal row stands
    # §MCPTEST30 (V0639, agentvault2-aa): the success path needs a peer that still publishes its baseline, and the first
    # peer may have drifted (sbx-alpha's op-sbxalphaop, 2026-10-24: hash_match false while Sandbox Beta and sbxbetaop
    # matched, so the success path went unmeasured every run): the others are read, at most _BASELINE_PEERS, until one
    # matches. The refusal stays on the first.
    row, det, matched = rows[0], None, None
    for i, candidate in enumerate(rows):
        _ok, got = await _exec_step(rpc, parse, "theprotocol_getFederationCompliancePeerByOperator", "admin",
                                    {"operator_id": candidate["operator_id"]}, dev_jwt, outcomes,
                                    expect_status="success", record_as_separate=False)
        if i == 0:
            det = got
        if isinstance(got, dict) and got.get("hash_match") is True and got.get("live_policy_hash"):
            matched = (candidate, got)
            break
    live = det.get("live_policy_hash") if isinstance(det, dict) else None
    stale = "0" * 64 if live != "0" * 64 else "1" * 64
    await _exec_step(rpc, parse, "theprotocol_acceptComplianceBaseline", "admin",
                     {"peer_id": str(row["peer_registry_id"]), "expected_hash": stale,
                      "reason": "MCP tester: a hash this peer does not publish (must be refused)"},
                     dev_jwt, outcomes, expect_status="error_4xx")
    if matched is not None:
        row, live = matched[0], matched[1]["live_policy_hash"]
        await _exec_step(rpc, parse, "theprotocol_acceptComplianceBaseline", "admin",
                         {"peer_id": str(row["peer_registry_id"]), "expected_hash": live,
                          "reason": "MCP tester: the baseline this peer still publishes (must be unchanged)"},
                         dev_jwt, outcomes, expect_status="success",
                         verify_against="theprotocol_acceptComplianceBaseline",
                         verify_against_check=lambda inner: None if isinstance(inner, dict)
                         and inner.get("status") == "unchanged" else f"expected status unchanged, got {inner!r:.160}")


# §MCPTEST30 (V0562): the Command Center's tools measured on a real target, without side effects. Every frame lists
# ITSELF as a target since V0562 (role "frame"), so runAllDiagnostics, runDiagnosticsSubset and triggerDiagnosticAction
# are asked about this registry: all checks that apply to it, one check, and a dry-run action (which a frame answers
# "skipped": only its operators' sidecars and TEGs are acted on). An operator target, where the frame lists one, gets the
# same dry run, which names what it WOULD do and does nothing. Phase 6's refusal rows stand on a frame without a self
# target (an older image).
_SELF_CHECKS = {"supply-audit", "leader-election", "svid-expiry", "frame-trust-bundle", "frame-teg-health"}


def _check_results_are(inner: Any, want_ids: set) -> Optional[str]:
    rows = (inner or {}).get("results") if isinstance(inner, dict) else None
    if not isinstance(rows, list):
        return f"no results list: {inner!r:.160}"
    ids = {r.get("check_id") for r in rows if isinstance(r, dict)}
    bad = [r.get("check_id") for r in rows if isinstance(r, dict) and r.get("status") not in ("ok", "warn", "fail", "unknown")]
    if not want_ids <= ids:
        return f"checks missing from the run: {sorted(want_ids - ids)}"
    return f"results without a status: {bad}" if bad else None


async def lifecycle_admin_command_center_self(rpc: RpcCall, parse: ParseResult,
                                              bag: Any, outcomes: Dict[str, dict]) -> None:
    dev_jwt = bag.developer_jwt
    _ok, lst = await _exec_step(rpc, parse, "theprotocol_getDiagnosticTargets", "admin", {}, dev_jwt, outcomes,
                                expect_status="success", record_as_separate=False)
    targets = [x for x in ((lst or {}).get("targets") or []) if isinstance(x, dict)] if isinstance(lst, dict) else []
    me = next((x for x in targets if x.get("is_self") is True), None)
    if me is None:
        return   # an image before V0562: phase 6's refusal rows stand
    sid = me["operator_id"]
    # an operator registry lists itself as "operator": it has no store of its own, so no supply audit is its own
    want = _SELF_CHECKS if me.get("role") == "frame" else _SELF_CHECKS - {"supply-audit"}
    await _exec_step(rpc, parse, "theprotocol_runAllDiagnostics", "admin", {"target": sid, "force": True}, dev_jwt,
                     outcomes, expect_status="success", timeout=60,
                     verify_against="theprotocol_runAllDiagnostics",
                     verify_against_check=lambda inner: _check_results_are(inner, want))
    await _exec_step(rpc, parse, "theprotocol_runDiagnosticsSubset", "admin",
                     {"targets": [sid], "checks": ["frame-trust-bundle"]}, dev_jwt, outcomes, expect_status="success",
                     timeout=30, verify_against="theprotocol_runDiagnosticsSubset",
                     verify_against_check=lambda inner: _check_results_are(inner, {"frame-trust-bundle"}))
    await _exec_step(rpc, parse, "theprotocol_triggerDiagnosticAction", "admin",
                     {"action_id": "teg-restart", "target": sid, "dry_run": True}, dev_jwt, outcomes,
                     expect_status="success", timeout=30,
                     verify_against="theprotocol_triggerDiagnosticAction",
                     verify_against_check=lambda inner: None if isinstance(inner, dict) and inner.get("status") == "skipped"
                     else f"a frame's own TEG must be refused as out of scope (skipped), got {inner!r:.160}")
    op = next((x for x in targets if x.get("role") == "operator" and not x.get("is_self")), None)
    if op is not None:
        await _exec_step(rpc, parse, "theprotocol_triggerDiagnosticAction", "admin",
                         {"action_id": "teg-restart", "target": op["operator_id"], "dry_run": True}, dev_jwt, outcomes,
                         expect_status="success", timeout=30,
                         verify_against="theprotocol_triggerDiagnosticAction",
                         verify_against_check=lambda inner: None if isinstance(inner, dict) and inner.get("dry_run") is True
                         and inner.get("status") == "ok" and str(inner.get("summary", "")).startswith("dry-run: would restart")
                         else f"a dry run must say what it would do and do nothing, got {inner!r:.200}")


# ============================================================================
# §MCPTEST30 (2026-10-01) — one real id per admin lookup, harvested read-only
# ============================================================================
# The admin lookups below were called only with phase 6's deliberately-invalid ids, so the sweep measured their refusal
# and never their answer. These list reads (admin bridge, read-only, already swept on their own) name ids the frame HAS;
# the lookups' contracts take them as fixtures. Nothing is created and nothing is invented: a frame with no row for a
# fixture leaves it unpublished, and the contract that needs it is a named skip.
_HARVEST_READS = (
    "theprotocol_listAdminOperatorApplications", "theprotocol_listFederationLicenses",
    "theprotocol_getAllFederationPeersAdmin", "theprotocol_getFederationComplianceOverview",
    "theprotocol_getBroadcastTemplates", "theprotocol_getAdminBroadcasts", "theprotocol_getCloudOperators",
    "theprotocol_getDiagnosticTargets",
)


def _rows(v: Any, *keys: str) -> List[Dict[str, Any]]:
    if isinstance(v, list):
        return [x for x in v if isinstance(x, dict)]
    if isinstance(v, dict):
        for k in keys:
            if isinstance(v.get(k), list):
                return [x for x in v[k] if isinstance(x, dict)]
    return []


def _first(rows: List[Dict[str, Any]], key: str, prefer: Optional[Callable[[Dict[str, Any]], bool]] = None) -> Any:
    have = [r for r in rows if r.get(key) not in (None, "")]
    if prefer is not None:
        have = [r for r in have if prefer(r)] or have
    return have[0][key] if have else None


def harvest_admin_fixtures(lists: Dict[str, Any]) -> Dict[str, Any]:
    """Pure (unit-tested): from the answers of the list reads, keyed by tool name without the prefix, one EXISTING id
    per lookup fixture. A fixture with no row on the frame is left out; nothing is ever made up."""
    out: Dict[str, Any] = {}

    def put(name: str, value: Any, as_int: bool = False) -> None:
        if value in (None, ""):
            return
        if as_int:
            try:
                out[name] = int(value)
            except (TypeError, ValueError):
                return
        else:
            out[name] = str(value)

    put("operator_application_id", _first(_rows(lists.get("listAdminOperatorApplications"), "applications"), "id"))
    put("federation_license_id", _first(_rows(lists.get("listFederationLicenses"), "licenses", "items"), "id",
                                        lambda r: str(r.get("status") or "").lower() == "active"))
    put("peer_registry_id", _first(_rows(lists.get("getAllFederationPeersAdmin"), "items", "peers"), "id",
                                   lambda r: str(r.get("status") or "").upper() == "ACTIVE"))
    comp = _rows(lists.get("getFederationComplianceOverview"), "peers")
    put("compliance_peer_id", _first(comp, "peer_registry_id", lambda r: bool(r.get("has_compliance_record"))))
    put("compliance_operator_id", _first(comp, "operator_id", lambda r: bool(r.get("has_compliance_record"))))
    put("broadcast_template_id", _first(_rows(lists.get("getBroadcastTemplates"), "templates"), "id"))
    put("broadcast_id", _first(_rows(lists.get("getAdminBroadcasts"), "broadcasts", "items"), "id"), as_int=True)
    put("active_cloud_operator_id", _first([r for r in _rows(lists.get("getCloudOperators"), "operators")
                                            if r.get("active") is True], "application_id"))
    put("diagnostic_target_id", _first(_rows(lists.get("getDiagnosticTargets"), "targets"), "operator_id"))
    return out


async def lifecycle_admin_fixture_harvest(rpc: RpcCall, parse: ParseResult,
                                          bag: Any, outcomes: Dict[str, dict]) -> None:
    """Records no row of its own: the list reads are swept by admin_dashboard_reads and the default walk."""
    dev_jwt = bag.developer_jwt
    lists: Dict[str, Any] = {}

    async def _one(tool: str) -> None:
        try:
            ok, body, code = await rpc(tool, {}, jwt=dev_jwt, timeout=30)
        except Exception:  # noqa: BLE001 — a list that cannot be read publishes nothing
            return
        if ok:
            lists[tool[len("theprotocol_"):]] = parse(body)
    await asyncio.gather(*(_one(t) for t in _HARVEST_READS))
    for name, value in harvest_admin_fixtures(lists).items():
        bag.flow_values[name] = value


async def lifecycle_admin_scratch_listing(rpc: RpcCall, parse: ParseResult,
                                          bag: Any, outcomes: Dict[str, dict]) -> None:
    """§MCPTEST30 (2026-10-01): the run's OWN scratch AGORA listing at the end of its life. Phase 3 created and approved it
    for the public trading tools, which have all run before this phase: here it is halted and resumed (each read back
    from the answer), then delisted (its resting order cancelled and the escrow refunded, Delta-neutral), so the
    teardown can delete the organization that owns it. Only ever the listing phase 3 published by symbol; the three
    tools were permanent skips ("needs a live listing / destructive: needs a throwaway listing fixture"), and this IS
    that fixture. Phase 3's approve is the approve tool's success path and is recorded here."""
    from agentvault_registry.api_tests.contracts.mcp_lifecycles import _make_outcome
    fv = getattr(bag, "flow_values", None) or {}
    sym = fv.get("scratch_listing")
    if not sym:
        return
    ap = fv.get("scratch_listing_approve")
    if isinstance(ap, dict):
        outcomes["theprotocol_adminAgoraApproveListing"] = _make_outcome(
            "theprotocol_adminAgoraApproveListing", "admin", True, str(ap.get("status") or 200), 0, None,
            ap.get("answer") or {}, expect_status="success")
    dev_jwt = bag.developer_jwt
    tool = "theprotocol_adminAgoraHaltListing"
    ok, r = await _exec_step(rpc, parse, tool, "admin", {"listing_ref": sym, "halted": True}, dev_jwt, outcomes)
    if ok:
        row = outcomes.get(tool) or {}
        if (r or {}).get("status") != "halted":
            row.update(healthy=False, fail_reason=(f"BUG-FIND: adminAgoraHaltListing answered 2xx and the listing it "
                                                   f"returned reads status={(r or {}).get('status')!r}, not halted"))
        ok2, r2 = await _exec_step(rpc, parse, tool, "admin", {"listing_ref": sym, "halted": False}, dev_jwt, outcomes,
                                   record_as_separate=False)
        if row.get("healthy") and (not ok2 or (r2 or {}).get("status") != "trading"):
            row.update(healthy=False, fail_reason=(f"BUG-FIND: the halt applied but the resume did not: the listing "
                                                   f"reads {(r2 or {}).get('status')!r} after halted=false"))
    ok3, r3 = await _exec_step(rpc, parse, "theprotocol_adminAgoraDelistListing", "admin", {"listing_ref": sym},
                               dev_jwt, outcomes)
    if ok3:
        fv["scratch_listing_delisted"] = True


async def lifecycle_admin_tutorial_proxy(rpc: RpcCall, parse: ParseResult,
                                         bag: Any, outcomes: Dict[str, dict]) -> None:
    """§MCPTEST30 (2026-10-01): executeTutorial on a real call. It was swept with {tutorial_id: <nonexistent>} under
    expect "any", which a refusal and an execution both satisfy, while the tool sent {tutorial_id, args} to a route that
    reads {method, path, body, auth_type, auth_token}: every call ran GET <sandbox>/api/v1 whatever was asked, and its
    success (`"error": null` in the body) reached the client as `Error: None`. Now one anonymous READ through the
    tutorial proxy (nothing is written anywhere), measured on what the sandbox answered. A registry with no tutorial
    sandbox (the cloud operators) answers 503 and says so: measured as that designed refusal, never as a pass of the
    proxy itself."""
    from agentvault_registry.api_tests.contracts.mcp_lifecycles import _make_outcome
    tool = "theprotocol_executeTutorial"
    args = {"method": "GET", "path": "/public/registry-config", "auth_type": "none"}
    t0 = time.time()
    ok, body, code = await rpc(tool, args, jwt=bag.developer_jwt, timeout=40)
    ms = int((time.time() - t0) * 1000)
    inner = parse(body)
    text = inner.get("_text") if isinstance(inner, dict) else None
    if isinstance(text, str) and "No tutorial sandbox is configured" in text:
        outcomes[tool] = _make_outcome(tool, "admin", True, "503", ms, None, inner, expect_status="error_5xx")
        outcomes[tool]["args_used"] = args
        return
    fail = None
    if isinstance(text, str) and text.startswith("Error:"):
        fail = f"step '{tool}' wrapper-error: {text[:200]}"
    elif not ok or not isinstance(inner, dict):
        fail = f"step '{tool}' failed: HTTP {code}"
    else:
        sc, resp = inner.get("status_code"), inner.get("response")
        if sc != 200 or not isinstance(resp, dict) or not resp:
            fail = (f"BUG-FIND: executeTutorial answered 2xx but the proxied anonymous read of /public/registry-config "
                    f"reads status_code={sc!r} with a {type(resp).__name__} body (want 200 and the sandbox's JSON config)")
    outcomes[tool] = _make_outcome(tool, "admin", fail is None, code, ms, fail,
                                   inner if isinstance(inner, dict) else {}, expect_status="success")
    outcomes[tool]["args_used"] = args


# ============================================================================
# Lifecycle registry
# ============================================================================


ADMIN_LIFECYCLES: List[Dict[str, Any]] = [
    # first, so the walk after the batch finds the ids it publishes
    {"name": "admin_fixture_harvest",      "runner": lifecycle_admin_fixture_harvest},
    {"name": "admin_scratch_listing",      "runner": lifecycle_admin_scratch_listing},
    {"name": "admin_tutorial_proxy",       "runner": lifecycle_admin_tutorial_proxy},
    {"name": "admin_request_safe",         "runner": lifecycle_admin_request_safe},
    {"name": "admin_query_event_store",    "runner": lifecycle_admin_query_event_store},
    {"name": "admin_prom_query",           "runner": lifecycle_admin_prom_query},
    {"name": "admin_grafana_query",        "runner": lifecycle_admin_grafana_query},
    {"name": "admin_get_developer_token",  "runner": lifecycle_admin_get_developer_token},
    {"name": "admin_dashboard_reads",      "runner": lifecycle_admin_dashboard_reads},
    {"name": "admin_id_lookups",           "runner": lifecycle_admin_id_lookups},
    {"name": "admin_destructive_safe",     "runner": lifecycle_admin_destructive_safe},
    {"name": "admin_event_emission_policy_rw", "runner": lifecycle_admin_event_emission_policy_rw},
    {"name": "admin_compliance_baseline",  "runner": lifecycle_admin_compliance_baseline},
    {"name": "admin_command_center_self",  "runner": lifecycle_admin_command_center_self},
]


def admin_lifecycle_count() -> int:
    return len(ADMIN_LIFECYCLES)
