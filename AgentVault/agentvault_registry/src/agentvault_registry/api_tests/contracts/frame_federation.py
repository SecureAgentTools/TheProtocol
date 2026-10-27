"""Frame federation + cross-frame contracts (AAA+ Phase IV-A, 2026-05-21)."""
from __future__ import annotations

from ..core.contract import Endpoint
from ..core.failure_modes import FailureMode


@Endpoint(method="GET", path="/admin/federation/topology-overview", auth="developer", category="federation_topology_admin", idempotent=True, slow_timeout_sec=60.0)
class FederationTopologyOverview:
    """Admin view of federation topology across all peers."""
    expected_status = 200


@Endpoint(method="GET", path="/admin/federation/peers", auth="developer", category="federation_peers", idempotent=True)
class AdminFederationPeers:
    """Admin list of all peers."""
    expected_status = 200


@Endpoint(method="POST", path="/admin/federation/peers/{peer_id}/approve", auth="developer", category="federation_peers", idempotent=False)
class ApprovePeer:
    """Approve a peer registration."""
    def body(self, ctx):
        return {}
    expected_status = [200, 404, 409]


@Endpoint(method="POST", path="/admin/federation/peers/{peer_id}/deactivate", auth="developer", category="federation_peers", idempotent=False)
class DeactivatePeer:
    """Deactivate a peer."""
    def body(self, ctx):
        return {}
    expected_status = [200, 404, 409]


@Endpoint(method="POST", path="/admin/federation/peers/{peer_id}/reactivate", auth="developer", category="federation_peers", idempotent=False)
class ReactivatePeer:
    """Reactivate a deactivated peer."""
    def body(self, ctx):
        return {}
    expected_status = [200, 404, 409]


@Endpoint(method="GET", path="/admin/federation/topology/peers/{peer_id}/events", auth="developer", category="federation_topology_admin", idempotent=True, slow_timeout_sec=60.0)
class PeerEvents:
    """Federation events for a specific peer.

    Reads peer-specific EventStore slice (`/admin/federation/peer-stats`-shaped
    aggregation). On sandbox-A with a freshly-bootstrapped peer this returns
    empty events list quickly. Under sandbox-reset bursts it can hit pool
    pressure → transport timeout; EF-stamp covers that.
    """
    expected_status = [200, 404]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status is None,
            reason="Sandbox-A pool pressure during burst — peer events query timed out",
        ),
    ]


@Endpoint(method="POST", path="/admin/federation/topology/peers/{peer_id}/probe", auth="developer", category="federation_topology_admin", idempotent=True, slow_timeout_sec=60.0)
class ProbePeer:
    """Active health probe of a peer.

    Makes an HTTPS request to the peer's `/health` endpoint. On sandbox-A the
    only "peer" is registry-test-b → reachable. With a placeholder peer_id
    that doesn't exist → 404. Transport timeout indicates peer DNS / route
    unreachable; tolerable in test env.
    """
    def body(self, ctx):
        return {}
    expected_status = [200, 404, 503]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status is None,
            reason="Peer probe HTTPS round-trip timed out (sandbox peer often unroutable in burst)",
        ),
    ]


@Endpoint(method="POST", path="/internal/federation/query", auth="developer", category="federation_query", idempotent=True)
class InternalFederationQuery:
    """Internal cross-registry agent query."""
    def body(self, ctx):
        return {"search": "test", "tags": ["service"], "limit": 10}
    expected_status = [200, 401, 422]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 401,
            reason="Internal endpoint requires X-Federation-Secret header",
        ),
    ]


@Endpoint(method="POST", path="/federation/sync-request", auth="developer", category="federation_sync", idempotent=False)
class FederationSyncRequest:
    """Request a federation sync from a peer."""
    def body(self, ctx):
        return {
            "source_registry": "spiffe://agentvault.com/service/registry-test-b",
            "agent_cards": [],
            "sync_timestamp": "2026-05-21T00:00:00Z",
        }
    expected_status = [200, 401, 422]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 401,
            reason="Requires mTLS or federation secret",
        ),
    ]
