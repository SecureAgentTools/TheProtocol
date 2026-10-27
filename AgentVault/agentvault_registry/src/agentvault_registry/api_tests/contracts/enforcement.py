"""Enforcement contracts (AAA+ Phase IV-A — TITANIUM VAULT D2, 2026-05-21)."""
from __future__ import annotations

from ..core.contract import Endpoint
from ..core.failure_modes import FailureMode


@Endpoint(method="POST", path="/agents/reputation-bond/deposit", auth="agent", category="enforcement_agent", idempotent=False)
class ReputationBondDeposit:
    """Deposit AVT as reputation bond."""
    def body(self, ctx):
        return {"amount": "100"}
    expected_status = [200, 400]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 400 and "insufficient" in r.detail_lower(),
            reason="Insufficient liquid balance for bond deposit",
        ),
    ]


@Endpoint(method="GET", path="/agents/reputation-bond/status", auth="agent", category="enforcement_agent", idempotent=True)
class ReputationBondStatus:
    """Caller's reputation bond status."""
    expected_status = [200, 404]


@Endpoint(
    method="POST",
    path="/admin/enforcement/registries/{peer_id}/quarantine",
    auth="developer",
    category="admin_enforcement",
    idempotent=False,
)
class QuarantineRegistry:
    """Quarantine a peer registry."""
    def body(self, ctx):
        return {"reason": "AAA+ contract test"}
    expected_status = [200, 404]


@Endpoint(
    method="POST",
    path="/admin/enforcement/registries/{peer_id}/lift-quarantine",
    auth="developer",
    category="admin_enforcement",
    idempotent=False,
)
class LiftQuarantine:
    """Lift a registry quarantine."""
    def body(self, ctx):
        return {}
    expected_status = [200, 404, 409]


@Endpoint(
    method="POST",
    path="/admin/enforcement/registries/{peer_id}/blacklist",
    auth="developer",
    category="admin_enforcement",
    idempotent=False,
)
class BlacklistRegistry:
    """Blacklist a peer registry (permanent)."""
    def body(self, ctx):
        return {"reason": "AAA+ contract test"}
    expected_status = [200, 404]
