"""Staking rewards contracts (AAA+ Phase IV-A, 2026-05-21)."""
from __future__ import annotations

from ..core.contract import Endpoint
from ..core.failure_modes import FailureMode


@Endpoint(method="POST", path="/staking/rewards/distribute", auth="developer", category="staking_rewards", idempotent=False)
class DistributeRewards:
    """Admin trigger of automatic staking reward distribution."""
    def body(self, ctx):
        return {"distribution_type": "automatic", "threshold": "1000"}
    expected_status = [200, 409]


@Endpoint(
    method="GET",
    path="/staking/rewards/estimate/{agent_did}",
    auth="developer",
    category="staking_rewards",
    idempotent=True,
)
class EstimateRewards:
    """Estimate next reward distribution for an agent."""
    expected_status = [200, 400, 404]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 404,
            reason="Agent DID placeholder",
        ),
    ]
