"""Governance extended contracts (AAA+ Phase IV-A round 2, 2026-05-21)."""
from __future__ import annotations

from ..core.contract import Endpoint
from ..core.failure_modes import FailureMode


@Endpoint(method="GET", path="/governance/proposals/{proposal_id}", auth="agent", category="governance", idempotent=True)
class GetProposal:
    """Get proposal detail."""
    expected_status = [200, 404]


@Endpoint(method="GET", path="/governance/proposals/{proposal_id}/votes", auth="agent", category="governance", idempotent=True)
class GetProposalVotes:
    """List all votes on a proposal."""
    expected_status = [200, 404]


@Endpoint(method="GET", path="/governance/my-votes", auth="agent", category="governance", idempotent=True)
class MyVotes:
    """Caller agent's voting history."""
    expected_status = 200


@Endpoint(method="GET", path="/governance/voting-power", auth="agent", category="governance", idempotent=True)
class VotingPower:
    """Caller agent's current voting power (based on staked AVT)."""
    expected_status = 200


@Endpoint(method="POST", path="/governance/proposals/{proposal_id}/cancel", auth="agent", category="governance", idempotent=False)
class CancelProposal:
    """Cancel own proposal (only proposer can)."""
    def body(self, ctx):
        return {}
    expected_status = [200, 403, 404, 409]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status in (403, 404, 409),
            reason="Not proposer, proposal already tallied, or placeholder ID",
        ),
    ]


# ── Federation disputes ────────────────────────────────────────────────
@Endpoint(method="GET", path="/federation/disputes", auth="developer", category="federation_disputes", idempotent=True)
class FederationDisputes:
    """List cross-frame federation disputes."""
    expected_status = 200


@Endpoint(method="GET", path="/federation/disputes/{dispute_id}", auth="developer", category="federation_disputes", idempotent=True)
class FederationDisputeDetail:
    """Federation dispute detail."""
    expected_status = [200, 404]
