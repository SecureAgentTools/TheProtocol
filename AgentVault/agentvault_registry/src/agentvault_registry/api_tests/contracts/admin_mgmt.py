"""Admin management contracts (AAA+ Phase II-B, 2026-05-21).

Admin actions that operate on developers / agents / frame state.
"""
from __future__ import annotations

from ..core.contract import Endpoint
from ..core.failure_modes import FailureMode


@Endpoint(method="POST", path="/admin/projection-snapshot", auth="developer", category="admin_platform", idempotent=False)
class TakeProjectionSnapshot:
    """Snapshot all balances from TEG and post as ProjectionSnapshot event."""
    def body(self, ctx):
        return {}
    expected_status = 200


@Endpoint(
    method="PUT",
    path="/admin/event-emission-policies/{event_type}",
    auth="developer",
    category="admin_platform",
    idempotent=True,
)
class UpdateEmissionPolicy:
    """Update a per-event-type emission policy row."""
    def body(self, ctx):
        return {
            "emit_from_teg": False,
            "emit_from_registry": True,
            "skip_in_projection": False,
        }
    expected_status = [200, 404]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 404,
            reason="event_type placeholder substitution",
        ),
    ]


@Endpoint(method="GET", path="/admin/test-tokens", auth="developer", category="admin_platform", idempotent=True)
class AdminTestTokens:
    """Generate test tokens for admin debugging."""
    expected_status = 200


@Endpoint(method="GET", path="/admin/docker-stats", auth="developer", category="admin_platform", idempotent=True, slow_timeout_sec=30.0)
class AdminDockerStats:
    """Container stats snapshot (may flake on docker daemon)."""
    expected_status = [200, 500, 504]
    failures = [
        FailureMode.known_bug(
            condition=lambda r: r.status in (500, 504),
            reason="Docker stats endpoint occasionally 500s on daemon flakes",
            bug_id="DOCKER-DAEMON-FLAKE",
        ),
    ]


@Endpoint(method="POST", path="/admin/invite-codes/generate", auth="developer", category="admin_invite_codes", idempotent=False)
class GenerateInviteCodes:
    """Mint developer invite codes."""
    def body(self, ctx):
        return {"count": 1}
    expected_status = [200, 201]


@Endpoint(method="GET", path="/admin/invite-codes", auth="developer", category="admin_invite_codes", idempotent=True)
class ListInviteCodes:
    """List all invite codes."""
    expected_status = 200


@Endpoint(
    method="GET",
    path="/admin/invite-codes/validate/{code}",
    auth="developer",
    category="admin_invite_codes",
    idempotent=True,
)
class ValidateInviteCode:
    """Check if an invite code is valid."""
    expected_status = [200, 404]


# ── Simulation ───────────────────────────────────────────────────────────
@Endpoint(method="GET", path="/admin/simulation/status", auth="developer", category="admin_simulation", idempotent=True)
class SimStatus:
    """Active simulation status."""
    expected_status = 200


@Endpoint(method="POST", path="/admin/simulation/start", auth="developer", category="admin_simulation", idempotent=False, slow_timeout_sec=60.0)
class SimStart:
    """Start a simulation (long-running)."""
    def body(self, ctx):
        return {"sim_type": "eigentrust", "duration_seconds": 60}
    expected_status = [200, 409]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 409,
            reason="Simulation already running",
        ),
    ]


@Endpoint(method="POST", path="/admin/simulation/stop", auth="developer", category="admin_simulation", idempotent=True)
class SimStop:
    """Stop the running simulation."""
    def body(self, ctx):
        return {}
    expected_status = [200, 404]


@Endpoint(method="GET", path="/admin/simulation/topology", auth="developer", category="admin_simulation", idempotent=True)
class SimTopology:
    """Federation topology snapshot from simulation."""
    expected_status = 200
