"""Admin platform extended contracts (AAA+ Phase IV-A round 2, 2026-05-21)."""
from __future__ import annotations

from ..core.contract import Endpoint
from ..core.failure_modes import FailureMode


# ── Tutorial extras ─────────────────────────────────────────────────────
@Endpoint(method="GET", path="/admin/tutorial/manifest", auth="developer", category="tutorial", idempotent=True)
class TutorialManifest:
    """Tutorial steps manifest."""
    expected_status = 200


# ── Frame management ────────────────────────────────────────────────────
@Endpoint(method="GET", path="/admin/frames/registry", auth="developer", category="admin_platform", idempotent=True)
class FrameRegistry:
    """List all known frames."""
    expected_status = 200


# ── Health check variants ──────────────────────────────────────────────
@Endpoint(method="GET", path="/admin/health-check/composite", auth="developer", category="admin_platform", idempotent=True, slow_timeout_sec=30.0)
class HealthCheckComposite:
    """Composite health (all services)."""
    expected_status = 200


@Endpoint(method="GET", path="/admin/health-check/public-only", auth="developer", category="admin_platform", idempotent=True)
class HealthCheckPublicOnly:
    """Public-facing service health."""
    expected_status = 200


@Endpoint(method="GET", path="/admin/health-check/simple", auth="developer", category="admin_platform", idempotent=True)
class HealthCheckSimple:
    """Simple health probe."""
    expected_status = 200


# ── Cluster diagnostic ─────────────────────────────────────────────────
@Endpoint(method="POST", path="/admin/cluster/test-tier", auth="developer", category="admin_platform", idempotent=True)
class ClusterTestTier:
    """Test tier connectivity."""
    def body(self, ctx):
        return {"tier": "primary"}
    expected_status = [200, 422]


# ── Telemetry / metrics admin ──────────────────────────────────────────
@Endpoint(method="GET", path="/admin/prometheus-metrics", auth="developer", category="admin_platform", idempotent=True, slow_timeout_sec=30.0)
class AdminPromMetrics:
    """Admin Prometheus metrics."""
    expected_status = 200


# ── Discovery + Federation ─────────────────────────────────────────────
@Endpoint(method="GET", path="/admin/federation/registry/{peer_id_or_name}/health-profile", auth="developer", category="admin_federation", idempotent=True, slow_timeout_sec=30.0)
class FederationRegistryHealthProfile:
    """Federation peer registry health profile."""
    expected_status = [200, 404]


# ── Sandbox proxy ──────────────────────────────────────────────────────
# /sandbox/{a,b}/{path} are wildcard routes. We test the GET version.
@Endpoint(method="GET", path="/sandbox/a/health", auth="developer", category="sandbox", idempotent=True)
class SandboxAProxyHealth:
    """Proxy to sandbox-A /health via /sandbox/a/{path}."""
    expected_status = [200, 404, 502]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 502,
            reason="Sandbox proxy upstream unreachable",
        ),
    ]


@Endpoint(method="GET", path="/sandbox/b/health", auth="developer", category="sandbox", idempotent=True)
class SandboxBProxyHealth:
    """Proxy to sandbox-B /health."""
    expected_status = [200, 404, 502]
