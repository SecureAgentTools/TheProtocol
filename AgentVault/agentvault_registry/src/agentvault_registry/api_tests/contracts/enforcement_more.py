"""Enforcement extended contracts (AAA+ Phase IV-A round 2, 2026-05-21)."""
from __future__ import annotations

from ..core.contract import Endpoint
from ..core.failure_modes import FailureMode


@Endpoint(method="GET", path="/admin/enforcement/agents/{agent_did}/history", auth="developer", category="enforcement_admin", idempotent=True)
class AgentEnforcementHistory:
    """Per-agent enforcement actions history."""
    expected_status = [200, 404]


@Endpoint(method="GET", path="/admin/enforcement/actions", auth="developer", category="enforcement_admin", idempotent=True)
class EnforcementActions:
    """Recent enforcement actions across fleet."""
    expected_status = 200


@Endpoint(method="GET", path="/admin/enforcement/stats", auth="developer", category="enforcement_admin", idempotent=True)
class EnforcementStats:
    """Aggregate enforcement stats."""
    expected_status = 200


@Endpoint(method="POST", path="/admin/enforcement/agents/{agent_did}/suspend", auth="developer", category="enforcement_admin", idempotent=True)
class SuspendAgent:
    """Coordinated agent suspend."""
    def body(self, ctx):
        return {"reason": "AAA+ contract test suspend"}
    expected_status = [200, 404, 409]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 404,
            reason="Agent DID placeholder",
        ),
        FailureMode.business_rule(
            condition=lambda r: r.status == 409,
            reason="Agent already suspended",
        ),
    ]


@Endpoint(method="POST", path="/admin/enforcement/agents/{agent_did}/reinstate", auth="developer", category="enforcement_admin", idempotent=True)
class ReinstateAgent:
    """Coordinated agent reinstate."""
    def body(self, ctx):
        return {"reason": "AAA+ contract test reinstate"}
    expected_status = [200, 404, 409]


@Endpoint(method="POST", path="/agents/{agent_did}/reputation-bond/initialize", auth="agent", category="enforcement_agent", idempotent=False)
class InitializeBond:
    """Initialize agent's reputation bond."""
    def body(self, ctx):
        return {}
    expected_status = [200, 201, 409]
