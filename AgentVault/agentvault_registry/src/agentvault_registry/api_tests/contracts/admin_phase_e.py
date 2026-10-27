"""Admin Phase E extras (AAA+ Phase IV-A, 2026-05-21).

Admin endpoints from the f038/f042/f049/f050 series — operator lifecycle,
consul compliance, frame invitations admin.
"""
from __future__ import annotations

from ..core.contract import Endpoint
from ..core.failure_modes import FailureMode


# ── Cloud operator provisioning ──────────────────────────────────────────
@Endpoint(
    method="POST",
    path="/admin/cloud-operators/{application_id}/provision",
    auth="developer",
    category="cloud_operators_(admin)",
    idempotent=False,
    slow_timeout_sec=300.0,
)
class ProvisionCloud:
    """Long-running operator provisioning. Excluded from run-all in overrides? No, separate."""
    def body(self, ctx):
        return {}
    expected_status = [200, 202, 404, 409]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 404,
            reason="Application ID placeholder",
        ),
    ]


@Endpoint(
    method="POST",
    path="/admin/cloud-operators/{application_id}/teardown",
    auth="developer",
    category="cloud_operators_(admin)",
    idempotent=True,
    slow_timeout_sec=300.0,
)
class TeardownCloud:
    """Tear down a cloud operator."""
    def body(self, ctx):
        return {}
    expected_status = [200, 404, 409]


# ── Operator applications ────────────────────────────────────────────────
@Endpoint(method="GET", path="/operator-applications", auth="developer", category="operator_applications", idempotent=True)
class ListOperatorApplications:
    """List all operator applications."""
    expected_status = 200


@Endpoint(method="POST", path="/operator-applications", auth="developer", category="operator_applications", idempotent=False)
class CreateOperatorApplication:
    """Apply to become an operator."""
    def body(self, ctx):
        return {
            "operator_name": "aaa-test-op",
            "contact_email": "aaa@theprotocol.cloud",
            "deployment_type": "self-hosted",
        }
    expected_status = [200, 201, 409, 422]


# ── Consul / federation compliance ───────────────────────────────────────
@Endpoint(method="GET", path="/admin/consul/peers", auth="developer", category="consul_federation_compliance", idempotent=True)
class ConsulPeers:
    """CONSUL — list peers with their compliance state."""
    expected_status = 200


# ── Frame invitations ────────────────────────────────────────────────────
@Endpoint(method="GET", path="/admin/frame-invitations", auth="developer", category="frame_invitations", idempotent=True)
class ListFrameInvitations:
    """List pending frame invitations."""
    expected_status = 200


@Endpoint(method="POST", path="/admin/frame-invitations", auth="developer", category="frame_invitations", idempotent=False)
class CreateFrameInvitation:
    """Create a frame invitation for a peer."""
    def body(self, ctx):
        return {
            "peer_url": "https://example.com",
            "trust_domain": "example.test",
        }
    expected_status = [200, 201, 409, 422]
