"""Discovery + public read contracts (AAA+ Phase II-B, 2026-05-21).

Public agent discovery + agent-card export + status + showcase reads.
"""
from __future__ import annotations

from ..core.contract import Endpoint
from ..core.failure_modes import FailureMode


@Endpoint(method="GET", path="/discover", auth="none", category="federation_public", idempotent=True)
class Discover:
    """Public agent discovery."""
    expected_status = [200, 422]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 422,
            reason="Endpoint requires query params for search/filter",
        ),
    ]


@Endpoint(method="GET", path="/agent-cards/", auth="developer", category="agent_cards", idempotent=True)
class ListAgentCards:
    """List all agent cards."""
    expected_status = 200


@Endpoint(
    method="GET",
    path="/agents/{did}/card-export",
    auth="none",
    category="agent_cards",
    idempotent=True,
)
class AgentCardExport:
    """Canonical A2A v1.0 card export. {did} placeholder."""
    expected_status = [200, 404]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 404,
            reason="DID placeholder — no real agent",
        ),
    ]


@Endpoint(
    method="GET",
    path="/agents/{did}/public-key",
    auth="none",
    category="agent_cards",
    idempotent=True,
)
class AgentPublicKey:
    """Public key lookup for an agent."""
    expected_status = [200, 404]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 404,
            reason="DID placeholder",
        ),
    ]


@Endpoint(method="GET", path="/registries", auth="none", category="status", idempotent=True)
class ListRegistries:
    """List all known registries (public)."""
    expected_status = 200


@Endpoint(method="GET", path="/admin/registries/health", auth="developer", category="registry_health", idempotent=True)
class RegistriesHealth:
    """Aggregate health view of all peer registries."""
    expected_status = 200
