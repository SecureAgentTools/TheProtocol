"""Parallel-safe bucket runner (AAA+ Phase III-C, 2026-05-21).

Classifies categories into 4 buckets based on side-effect profile, then runs
each bucket with the appropriate concurrency strategy.

Buckets:
    READ_ONLY: all-GET, no writes → can run fully parallel
    MUTATING_ISOLATED: writes own resources, no shared DYNAMIC_VALUES → parallel cats, sequential within
    MUTATING_SHARED: writes shared keys (agent_did, org_id, etc.) → strictly sequential
    FLOW: multi-step asserts → each flow inherently sequential; multiple flows can run in parallel

Used by the headless runner + the new /admin/api-test/run-bucketed endpoint.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Dict, List, Set


class Bucket(str, enum.Enum):
    READ_ONLY = "read_only"
    MUTATING_ISOLATED = "mutating_isolated"
    MUTATING_SHARED = "mutating_shared"
    FLOW = "flow"


# Categories that ONLY contain idempotent GETs / mutations against own resource
READ_ONLY_CATEGORIES: Set[str] = {
    "status",
    "metrics",
    "system",
    "utilities",
    "utils",
    "mcp_server",
    "mcp_health",
    "federation_public",
    "agent_discovery",
    "agent_cards",  # listing only — write contracts go to mutating
    "circuits",
    "consul_admin",  # most are GET
    "developer_signing_keys",  # JWKS reads
    "developers_enhanced",
    "registry_health",
    "showcase",
    "spire",
    "tokenomics",  # reads
    "enhanced_tokenomics",
    "tutorial",
    "internal",
    "internal___federation",
    "operator_lifecycle",  # status reads
    "teg_summary_enhanced",
    "account_deletion",
    "fiat_on_ramp",  # tiers + quote are stateless
    "admin_canary",
    "admin_canary_judge",
    "admin_canary_rebalancer",
    "admin_canary_ironhand",
    "admin_cross_teg_sweeper",
    "admin_collusion_detector",
    "admin_saga_timeout",
    "admin_supply_auditor",
    "admin_email_studio",
    "admin_broadcasts",  # mostly observability
    "admin_agent_card_drift",
    "admin_agent_card_pull_sync",
    "admin_agent_health",
    "admin_agent_flags",
    "admin_ci_cd_fleet",
    "admin_bundles_moderation",  # reads
    "agent_mtls_(ironhand)",  # status only
    "ironhand_monitoring_(admin)",
    "federation_admission",  # reads
    "federation_blocklist",
    "federation_topology_admin",
    "federation_cli_audit",
    "federation_license_(self_serve)",
    "federation_licenses",
    "frame_federation",  # reads
    "federation_synchronization",
    "federation_sync",
    "federation_query",
    "federation_topology",
    "federation_disputes",  # most mTLS-only, default to read-only
    "anp_discovery",
    "arena_spectator",
    "command_center",
    "consul_federation_compliance",
    "status",
}


# Categories with multi-step flows triggered via /admin/api-test/test-flow
FLOW_CATEGORIES: Set[str] = {
    "flow_supply_audit",
    "flow_idempotency",
    "flow_auth_boundary",
    "flow_concurrency_safety",
    "flow_mcp_smoke",
    "flow_webhook_delivery",
    "flow_funding_request",
    "flow_coordinated_suspension",
    "flow_drift_detection",
    "flow_blocklist_enforcement",
    "flow_cross_frame_blocklist_propagation",
    "flow_reactor_batch_1",
    "flow_reactor_batch_2",
    "flow_reactor_batch_2_operator",
    "multiframe_bfs",
    "multiframe_eigentrust",
    "multiframe_governance",
    "multiframe_txstorm",
    "organizations",  # has flow
    "auth_2fa",  # has flow
    "agents_export_import",  # has flow
    "agent_cicd",  # has flow
}


# Categories with strict shared DYNAMIC_VALUES write surface → sequential
MUTATING_SHARED_CATEGORIES: Set[str] = {
    # Categories that write agent_did, org_id, dispute_id, etc.
    "agents",
    "agent_export_import",
    "onboarding",
    "auth",
    "auth_secure",
    "developers",
    "admin_developer_management",
    "admin_agent_management",
    "admin_developers",
    "admin_agents",
    "admin",
    "admin_platform",
    "admin_api_test",
    "admin_api_testing",
    "admin_federation",
    "admin_federation_peers",
    "admin_federation_sync",
    "admin_enforcement",
    "admin_invite_codes",
    "admin_simulation",
    "admin_agent_signing_keys",
    "contracts",
    "disputes",
    "disputes_enhanced",
    "enforcement_admin",
    "enforcement_agent",
    "frame_invitations",
    "governance",
    "operator_applications",
    "operators",
    "operators_admin",
    "operator_self_service",
    "organizations",  # also has flow — overlap
    "reputation",
    "reputation_signal",
    "staking",
    "staking_enhanced",
    "staking_rewards",
    "teg",
    "teg_integration",
    "teg_integration_jwt_svid",
    "teg_integration_mtls",
    "teg_integration_oauth",
    "teg_transactions",
    "two_factor_authentication",
    "token_bridge",
    "websocket",
    "webhooks",
    "funding",
    "funding_requests",
    "funding_admin",
    "fiat_on_ramp_admin",
    "attestations",
    "two_factor_authentication",
    "developer_signing_keys",  # rotation is mutating, mixed bucket → conservative
    "agent_builder",
    "agent_builder_templates",
    "agent_logs",
    "bundles",  # CRUD
    "support",
    "notifications",
    "cloud_operators_(admin)",
    "consul_admin_mutations",
    "oauth_federation",
    "sandbox",
}


@dataclass
class BucketAssignment:
    """The full classification of categories into buckets."""
    read_only: List[str]
    mutating_isolated: List[str]
    mutating_shared: List[str]
    flows: List[str]
    unknown: List[str]

    def to_dict(self) -> Dict[str, List[str]]:
        return {
            Bucket.READ_ONLY.value: self.read_only,
            Bucket.MUTATING_ISOLATED.value: self.mutating_isolated,
            Bucket.MUTATING_SHARED.value: self.mutating_shared,
            Bucket.FLOW.value: self.flows,
            "unknown": self.unknown,
        }


def classify_categories(category_names: List[str]) -> BucketAssignment:
    """Classify each category into a bucket."""
    ro, mi, ms, fl, un = [], [], [], [], []
    for cat in sorted(category_names):
        if cat in FLOW_CATEGORIES:
            fl.append(cat)
        elif cat in READ_ONLY_CATEGORIES:
            ro.append(cat)
        elif cat in MUTATING_SHARED_CATEGORIES:
            ms.append(cat)
        else:
            # Default: assume mutating_isolated. Conservative — better than failing race.
            mi.append(cat)
    return BucketAssignment(read_only=ro, mutating_isolated=mi, mutating_shared=ms, flows=fl, unknown=un)


def classify_category(cat: str) -> Bucket:
    if cat in FLOW_CATEGORIES:
        return Bucket.FLOW
    if cat in READ_ONLY_CATEGORIES:
        return Bucket.READ_ONLY
    if cat in MUTATING_SHARED_CATEGORIES:
        return Bucket.MUTATING_SHARED
    return Bucket.MUTATING_ISOLATED
