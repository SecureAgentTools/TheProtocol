"""Developer extended contracts (AAA+ Phase IV-A round 2, 2026-05-21)."""
from __future__ import annotations

from ..core.contract import Endpoint
from ..core.failure_modes import FailureMode


@Endpoint(method="GET", path="/developers/me", auth="developer", category="developers", idempotent=True)
class DeveloperMe:
    """Caller's developer record."""
    expected_status = 200


@Endpoint(method="GET", path="/developers/me/agents", auth="developer", category="developers", idempotent=True)
class MyAgents:
    """Caller's agents."""
    expected_status = 200


@Endpoint(method="POST", path="/developers/me/agents/balances", auth="developer", category="developers", idempotent=True)
class BatchBalances:
    """Batch balance fetch for caller's agents."""
    def body(self, ctx):
        return {"agent_dids": []}
    expected_status = 200


@Endpoint(method="GET", path="/developers/me/teg-summary", auth="developer", category="developers", idempotent=True)
class TegSummary:
    """Caller's aggregate TEG summary."""
    expected_status = 200


@Endpoint(method="GET", path="/developers/me/api-keys", auth="developer", category="developers", idempotent=True)
class MyApiKeys:
    """Caller's API keys."""
    expected_status = 200


@Endpoint(method="POST", path="/developers/me/api-keys", auth="developer", category="developers", idempotent=False)
class CreateMyApiKey:
    """Create a new API key for caller."""
    def body(self, ctx):
        return {"description": "AAA+ contract test key"}
    expected_status = [200, 201]


@Endpoint(method="POST", path="/developers/me/agents/{agent_did}/transfer-ownership", auth="developer", category="developers", idempotent=False)
class TransferOwnership:
    """Transfer agent ownership to another developer."""
    def body(self, ctx):
        return {"target_developer_id": 99999}
    expected_status = [200, 400, 404]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status in (400, 404),
            reason="Target developer placeholder or agent not owned",
        ),
    ]


@Endpoint(method="GET", path="/developers/me/agents/{agent_did}/balance", auth="developer", category="developers", idempotent=True)
class AgentBalance:
    """Specific agent's balance via developer auth."""
    expected_status = [200, 404]


@Endpoint(method="GET", path="/developers/me/agents/{agent_did}", auth="developer", category="developers", idempotent=True)
class MyAgentDetail:
    """Caller's agent detail."""
    expected_status = [200, 404]
