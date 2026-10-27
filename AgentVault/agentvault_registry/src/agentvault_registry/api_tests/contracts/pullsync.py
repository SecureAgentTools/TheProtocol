"""Agent-card pull-sync contracts (AAA+ Phase II-B — §pass36 Phase 3, 2026-05-21).

6h leader-elected worker that pulls agents' /.well-known/agent-card.json + emits
AgentCardPulled on drift. Plus admin drift inspection endpoints.
"""
from __future__ import annotations

from ..core.contract import Endpoint
from ..core.failure_modes import FailureMode


@Endpoint(
    method="GET",
    path="/admin/agent-card-pullsync/status",
    auth="developer",
    category="admin_agent_card_pull_sync",
    idempotent=True,
)
class PullsyncStatus:
    """Worker snapshot + Prom rollup + drift summary."""
    expected_status = 200


@Endpoint(
    method="GET",
    path="/admin/agent-card-pullsync/events",
    auth="developer",
    category="admin_agent_card_pull_sync",
    idempotent=True,
)
class PullsyncEvents:
    """Paginated AgentCardPulled feed from EventStore."""
    expected_status = 200


@Endpoint(
    method="GET",
    path="/admin/agent-card-drift",
    auth="developer",
    category="admin_agent_card_drift",
    idempotent=True,
)
class AgentCardDriftList:
    """Paginated native agents with pull-state + last drift event."""
    expected_status = 200


@Endpoint(
    method="GET",
    path="/admin/agent-card-drift/{did}",
    auth="developer",
    category="admin_agent_card_drift",
)
class AgentCardDriftDetail:
    """Side-by-side stored vs fresh diff for a single agent."""
    expected_status = [200, 404]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 404,
            reason="DID placeholder — no real agent resolved",
        ),
    ]


@Endpoint(
    method="POST",
    path="/admin/agent-card-drift/{did}/refresh",
    auth="developer",
    category="admin_agent_card_drift",
    idempotent=False,
)
class AgentCardDriftRefresh:
    """Force one-shot pull (bypass 6h scheduler). {did} placeholder."""
    def body(self, ctx):
        return {}
    expected_status = [200, 404]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 404,
            reason="DID placeholder — no real agent to refresh",
        ),
    ]


@Endpoint(
    method="POST",
    path="/admin/agent-card-drift/{did}/force-register",
    auth="developer",
    category="admin_agent_card_drift",
    idempotent=False,
)
class AgentCardDriftForceRegister:
    """Emit CommanderFlaggedDrift event. {did} placeholder."""
    def body(self, ctx):
        return {}
    expected_status = [200, 404]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 404,
            reason="DID placeholder — no real agent to flag",
        ),
    ]
