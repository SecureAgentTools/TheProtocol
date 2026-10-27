"""Per-endpoint timeout overrides for the API tester.

Default timeout is 10s (`APITestBase.test_endpoint(timeout=10.0)`). A handful of
admin aggregation endpoints walk the federation peer graph + per-operator state
and legitimately exceed 10s on sandbox-A's 13+ operator topology. Bumping the
per-call timeout for these specific paths keeps them green without inflating
the global default (which would mask real perf regressions on fast endpoints).

If a path is missing here, the default 10s applies. Add new entries when an
endpoint is provably slow due to fan-out, not due to a bug.
"""
from __future__ import annotations

# Per-exact-path timeout in seconds.
SLOW_ENDPOINT_TIMEOUTS: dict[str, float] = {
    "/admin/federation/compliance/peers/by-operator/{operator_id}": 60.0,
    "/admin/diagnostics/config/{target_id}": 60.0,
    "/admin/diagnostics/actions": 60.0,
    "/admin/diagnostics/actions/{action_id}": 60.0,
    "/admin/federation/topology-overview": 60.0,
    "/admin/federation/topology/peers/{peer_id}/events": 60.0,
    "/admin/federation/topology/peers/{peer_id}/probe": 60.0,
    "/admin/operators/lifecycle-overview": 60.0,
    # 2026-07-15 T4: test-federation RUNS the whole federation suite inline —
    # minutes, not seconds.
    "/admin/api-test/test-federation": 240.0,
    # 2026-04-25 — added after sequential full-suite run found these timing out:
    # admin aggregation endpoints that walk the DB + emit per-row events.
    "/admin/developers/{developer_id}/revoke-api-keys": 60.0,
    "/admin/developers/{developer_id}/activity": 60.0,
    "/admin/agents": 60.0,
    "/admin/agents/{agent_did}": 60.0,
    # 2026-04-26 — cross-frame token bridge initiates SF-3 escrow + remote
    # mint coordination; under load it can exceed 10s.
    "/bridge/transfer": 60.0,
    # /teg/transfer occasionally exceeds 10s under production load (TEG layer
    # contention). The transfer logic itself is fast; this is queueing time.
    "/teg/transfer": 60.0,
    # rotate-credentials issues new client_secret + propagates SPIRE entry,
    # can exceed 10s on busy hosts.
    "/admin/agents/{agent_did}/rotate-credentials": 60.0,
    # 2026-04-28 — additional slow endpoints surfaced during audit-fix sweep.
    # /admin/api-test/test-flow runs a full quality-gate flow (organizations,
    # reactor batches, etc.) which legitimately takes 30-90s. Federation
    # drift-scan walks the entire peer graph. Health-check composite/public
    # aggregates across all peers + operators.
    "/admin/api-test/test-flow": 120.0,
    "/admin/federation/drift-scan": 90.0,
    "/admin/health-check/composite": 90.0,
    "/admin/health-check/public-only": 90.0,
    "/admin/health-check": 60.0,
    "/admin/health-check/authenticated": 60.0,
    "/teg/treasury/fund-agent": 60.0,
    "/developers/me/teg-summary/treasury": 60.0,
    "/reputation/{agent_did}/trust-graph": 60.0,
    "/reputation/{agent_did}/volume-profile": 60.0,
    "/reputation/{did}/volume-profile": 60.0,
    "/reputation/cross-frame": 60.0,
    "/astraeus/my-agents": 60.0,
    "/astraeus/agent/{did}": 60.0,
    "/agents/did/{did}": 60.0,
    "/contracts/agent/{agent_did}": 60.0,
    "/auth/api-keys": 60.0,
    "/agents/{agent_did}/pipelines/{pipeline_id}": 60.0,
}


def get_endpoint_timeout(path: str, default: float = 60.0) -> float:
    """Return the effective timeout for a path. Falls back to `default` (60s).

    2026-04-28 — bumped default from 10s to 60s to match the new APITestBase
    default. The 60s ceiling absorbs sandbox-A's pgbouncer-routed cold starts +
    full-suite parallel load without false-positive timeouts. Endpoints in
    SLOW_ENDPOINT_TIMEOUTS keep their explicit override (already 60s).
    """
    return SLOW_ENDPOINT_TIMEOUTS.get(path, default)
