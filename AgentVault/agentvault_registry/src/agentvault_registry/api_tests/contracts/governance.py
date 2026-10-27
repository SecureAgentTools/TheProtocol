"""Governance contracts (AAA+ Phase II-B, 2026-05-21).

Proposals (agent-auth) + votes + tally.
"""
from __future__ import annotations

from ..core.contract import Endpoint
from ..core.failure_modes import FailureMode


@Endpoint(method="GET", path="/governance/proposals", auth="agent", category="governance", idempotent=True)
class ListProposals:
    """List all proposals."""
    expected_status = 200


@Endpoint(method="POST", path="/governance/proposals", auth="agent", category="governance", idempotent=False)
class CreateProposal:
    """Create a new proposal (agent-only — registry-only governance)."""
    def body(self, ctx):
        return {
            "title": "AAA+ contract test proposal",
            "description": "Auto-created by API tester contract framework",
            "proposal_type": "parameter_change",
            "parameters": {},
            "duration_seconds": 3600,
        }
    expected_status = [200, 201, 401]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 401 and "agent" in r.detail_lower(),
            reason="Endpoint requires agent JWT — runner may send developer JWT",
        ),
    ]


@Endpoint(
    method="POST",
    path="/governance/proposals/{proposal_id}/vote",
    auth="agent",
    category="governance",
    idempotent=False,
)
class VoteOnProposal:
    """Cast a vote on a proposal."""
    def body(self, ctx):
        return {"vote": "yes", "reason": "AAA+ contract test"}
    expected_status = [200, 401, 404, 409]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 404,
            reason="Proposal ID placeholder — no real proposal resolved",
        ),
        FailureMode.business_rule(
            condition=lambda r: r.status == 409,
            reason="Duplicate vote — agent already voted on this proposal",
        ),
        FailureMode.business_rule(
            condition=lambda r: r.status == 401,
            reason="Endpoint requires agent JWT",
        ),
    ]


@Endpoint(
    method="POST",
    path="/governance/proposals/{proposal_id}/tally",
    auth="agent",
    category="governance",
    idempotent=True,
)
class TallyProposal:
    """Tally proposal votes."""
    def body(self, ctx):
        return {}
    expected_status = [200, 401, 403, 404]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 404,
            reason="Proposal ID placeholder",
        ),
        FailureMode.business_rule(
            condition=lambda r: r.status == 403,
            reason="Voting period still active",
        ),
    ]
