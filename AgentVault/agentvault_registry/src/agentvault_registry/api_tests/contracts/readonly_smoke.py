"""Read-only smoke contracts (AAA+ Phase II-B batch 1).

Trivial GETs that should always 200. Validates contract framework end-to-end
+ proves zero-effort onboarding for stateless read endpoints.
"""
from __future__ import annotations

from ..core.contract import Endpoint


# ── Public endpoints (no auth) ───────────────────────────────────────────
@Endpoint(method="GET", path="/health", auth="none", category="status", idempotent=True)
class HealthCheck:
    """Public liveness probe."""
    expected_status = 200


@Endpoint(method="GET", path="/metrics", auth="none", category="metrics", idempotent=True)
class PromMetrics:
    """Prometheus metrics scrape endpoint."""
    expected_status = 200


# ── Developer endpoints (developer JWT) ──────────────────────────────────
@Endpoint(method="GET", path="/admin/api-test/endpoints", auth="developer", category="admin_api_test")
class AdminApiTestEndpoints:
    """The catalog endpoint itself — used by the runner."""
    expected_status = 200


@Endpoint(method="GET", path="/admin/dashboard", auth="developer", category="admin")
class AdminDashboard:
    """Admin dashboard aggregate."""
    expected_status = 200
    slow_timeout_sec = 30.0


@Endpoint(method="GET", path="/admin/system-health", auth="developer", category="admin")
class AdminSystemHealth:
    """System health aggregate."""
    expected_status = 200


@Endpoint(method="GET", path="/admin/event-emission-policies", auth="developer", category="admin")
class AdminEmissionPolicies:
    """All event emission policy rows."""
    expected_status = 200


@Endpoint(method="GET", path="/admin/eventstore-stats", auth="developer", category="admin")
class AdminESStats:
    """EventStore aggregate stats."""
    expected_status = 200


@Endpoint(method="GET", path="/admin/eventstore-recent", auth="developer", category="admin")
class AdminESRecent:
    """Recent EventStore events."""
    expected_status = 200


@Endpoint(method="GET", path="/admin/prometheus-metrics", auth="developer", category="admin")
class AdminPromMetrics:
    """Admin-side Prometheus metrics."""
    expected_status = 200


@Endpoint(method="GET", path="/admin/eventstore-balances", auth="developer", category="admin")
class AdminESBalances:
    """EventStore-projected balances."""
    expected_status = 200


# ── Network / federation discovery ───────────────────────────────────────
@Endpoint(method="GET", path="/federation/peers/{peer_id}", auth="developer", category="federation")
class FederationPeerDetail:
    """Public peer registry detail. Templated path — needs peer_id."""
    expected_status = [200, 404]  # 404 acceptable if peer not seeded


@Endpoint(method="GET", path="/federation/registries", auth="developer", category="federation")
class FederationRegistries:
    """List federated registries."""
    expected_status = 200


# ── Network stats ────────────────────────────────────────────────────────
@Endpoint(method="GET", path="/admin/system-resources", auth="developer", category="admin", slow_timeout_sec=60.0)
class AdminSystemResources:
    """Host CPU/RAM/disk snapshot."""
    expected_status = 200


@Endpoint(method="GET", path="/admin/combined-health", auth="developer", category="admin", slow_timeout_sec=60.0)
class AdminCombinedHealth:
    """Combined health probe (multi-service)."""
    expected_status = 200


@Endpoint(method="GET", path="/admin/system-activity", auth="developer", category="admin")
class AdminSystemActivity:
    """Recent admin actions."""
    expected_status = 200


# ── Status polling endpoints (lifecycle tests) ──────────────────────────


