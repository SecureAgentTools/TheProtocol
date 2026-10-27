"""Onboarding contracts (AAA+ Phase II-B, 2026-05-21).

Bootstrap-token request + agent creation.
The bootstrap-token request is itself idempotent (returns new token each call).
"""
from __future__ import annotations

from ..core.contract import Endpoint
from ..core.failure_modes import FailureMode


@Endpoint(
    method="POST",
    path="/onboard/bootstrap/request-token",
    auth="developer",
    category="onboarding",
    idempotent=True,  # each call mints a new token; no destructive state
)
class BootstrapRequestToken:
    """Mint a one-time bootstrap_token (5 min TTL). Caller must be a verified developer."""
    def body(self, ctx):
        return {
            "agent_type_hint": "api_test_agent",
            "requested_by": "api_tester_contract",
        }
    expected_status = 200


@Endpoint(
    method="POST",
    path="/onboard/create_agent",
    auth="developer",  # actually takes Bootstrap-Token; flagged developer for catalog
    category="onboarding",
    idempotent=False,
)
class CreateAgent:
    """Onboard a new agent. Requires Bootstrap-Token header (not Authorization).

    Test runner sends Authorization → expect 401/422 (bootstrap-token missing).
    The actual onboarding flow is exercised via the primary_agent fixture.
    """
    def body(self, ctx):
        return {
            "agent_did_method": "theprotocol",
            "agent_card": {
                "name": "Contract test agent",
                "description": "Placeholder",
                "humanReadableId": "contract-placeholder",
            },
        }
    expected_status = [200, 201, 401, 422]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status in (401, 422),
            reason="Bootstrap-Token header required — runner sends Authorization instead",
        ),
    ]


@Endpoint(method="POST", path="/onboard/register", auth="none", category="onboarding", idempotent=False)
class OnboardRegister:
    """Public agent registration endpoint — deprecated (HTTP 410 Gone)."""
    def body(self, ctx):
        return {
            "bootstrap_token": "bst_placeholder",
            "agent_name": "Test Agent",
        }
    expected_status = [200, 410]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 410,
            reason="Endpoint deprecated (HTTP 410 Gone) — use /onboard/create_agent",
        ),
    ]
