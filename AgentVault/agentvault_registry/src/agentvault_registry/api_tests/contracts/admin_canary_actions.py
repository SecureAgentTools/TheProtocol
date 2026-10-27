"""Canary mutating-action contracts (AAA+ Phase IV-A, 2026-05-21)."""
from __future__ import annotations

from ..core.contract import Endpoint
from ..core.failure_modes import FailureMode


@Endpoint(method="POST", path="/admin/canary/fire", auth="developer", category="admin_canary", idempotent=False)
class CanaryFire:
    """Manually fire a canary test."""
    def body(self, ctx):
        # §CANARYONBOARD (2026-09-22): a path id nothing holds. Path 1 is a REAL canary on any registry that runs them,
        # and a fire moves real currency.
        return {"path_id": 99999}
    expected_status = [200, 404, 422]


@Endpoint(method="POST", path="/admin/canary/maintenance", auth="developer", category="admin_canary", idempotent=False)
class CanaryMaintenance:
    """Enable/disable canary maintenance mode."""
    def body(self, ctx):
        # §CANARYONBOARD (2026-09-22): an EMPTY scope. The old body used the wrong key ("enabled"), so the endpoint read
        # scope "all", enable false, and switched off EVERY canary path on the target.
        return {"scope": [], "enable": False}
    expected_status = 200


@Endpoint(method="POST", path="/admin/canary/path/{path_id}/toggle", auth="developer", category="admin_canary", idempotent=False)
class CanaryToggle:
    """Toggle a canary path on/off."""
    def body(self, ctx):
        return {}
    expected_status = [200, 404]


@Endpoint(method="POST", path="/admin/agents/{did}/rotate-credentials", auth="developer", category="admin_agent_management", idempotent=False, slow_timeout_sec=60.0)
class RotateAgentCredentials:
    """Rotate an agent's client_id / client_secret."""
    def body(self, ctx):
        return {}
    expected_status = [200, 404]
