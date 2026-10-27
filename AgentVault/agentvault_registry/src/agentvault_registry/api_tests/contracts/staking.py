"""Staking contracts (AAA+ Phase II-B, 2026-05-21).

Stake → unstake (7-day cooldown). Reward claim. Auto-distribute. Etc.
"""
from __future__ import annotations

from ..core.contract import Endpoint
from ..core.failure_modes import FailureMode


@Endpoint(method="GET", path="/staking/balance", auth="agent", category="staking_enhanced", idempotent=True)
class StakingBalance:
    """Caller's staked balance."""
    expected_status = 200


@Endpoint(method="POST", path="/staking/stake", auth="agent", category="staking_enhanced", idempotent=False)
class Stake:
    """Stake AVT (sender + amount required)."""
    def body(self, ctx):
        return {"amount": "10"}
    expected_status = 200
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 400 and "insufficient" in r.detail_lower(),
            reason="Insufficient liquid balance to stake",
        ),
    ]


@Endpoint(method="POST", path="/staking/unstake", auth="agent", category="staking_enhanced", idempotent=False)
class Unstake:
    """Initiate unstake (7-day cooldown)."""
    def body(self, ctx):
        return {"amount": "5"}
    expected_status = 200
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status in (400, 403) and "cooldown" in r.detail_lower(),
            reason="Lock cooldown period — working as designed",
        ),
        FailureMode.business_rule(
            condition=lambda r: r.status == 400 and "insufficient" in r.detail_lower(),
            reason="Insufficient locked balance to unlock",
        ),
    ]


@Endpoint(method="POST", path="/staking/claim-rewards", auth="agent", category="staking_enhanced", idempotent=False)
class ClaimRewards:
    """Claim accrued staking rewards."""
    def body(self, ctx):
        return {}
    expected_status = 200
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 400 and ("no rewards" in r.detail_lower() or "nothing" in r.detail_lower()),
            reason="No accrued rewards to claim",
        ),
    ]
