"""Federation contracts (AAA+ Phase II-B, 2026-05-21).

Public federation surface: peer discovery, sync, registry list, topology.
mTLS-only endpoints marked with FailureMode.mtls_required.
"""
from __future__ import annotations

from ..core.contract import Endpoint
from ..core.failure_modes import FailureMode


# ── Public federation reads ──────────────────────────────────────────────
@Endpoint(method="GET", path="/federation/peers", auth="developer", category="federation_peers", idempotent=True)
class ListPeers:
    """List federation peers."""
    expected_status = 200


@Endpoint(method="POST", path="/federation/peers/", auth="developer", category="federation_peers", idempotent=False)
class CreatePeer:
    """Register a new peer registry."""
    def body(self, ctx):
        return {
            "name": "AAA+ Test Peer",
            "base_url": "https://placeholder.example.com",
            "admin_contact_email": "admin@example.com",
            "discovery_auth_info": {"type": "none"},
        }
    expected_status = [200, 201, 400, 409, 422]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 409,
            reason="Peer already exists with same URL",
        ),
        FailureMode.business_rule(
            condition=lambda r: r.status in (400, 422),
            reason="Peer URL not reachable from sandbox",
        ),
    ]


@Endpoint(
    method="DELETE",
    path="/federation/peers/{peer_id}",
    auth="developer",
    category="federation_peers",
)
class DeletePeer:
    """Deactivate a peer registry the caller owns."""
    expected_status = [200, 204, 403, 404]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 403,
            reason="Peer ownership protection",
        ),
        FailureMode.business_rule(
            condition=lambda r: r.status == 404,
            reason="Peer ID placeholder",
        ),
    ]


@Endpoint(method="POST", path="/federation/sync/trigger", auth="developer", category="federation_sync", idempotent=False)
class TriggerSync:
    """Trigger a federation sync round."""
    def body(self, ctx):
        return {}
    expected_status = [200, 429]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 429,
            reason="Rate-limited — sync triggered too recently",
        ),
    ]


# ── mTLS-only endpoints ─────────────────────────────────────────────────
@Endpoint(
    method="POST",
    path="/federation/disputes/slash-request",
    auth="mtls",
    category="federation_disputes",
    idempotent=False,
)
class FederationSlashRequest:
    """Cross-frame slash request. mTLS required."""
    def body(self, ctx):
        return {"settlement_id": "placeholder-001", "defendant_did": "did:theprotocol:placeholder", "slash_amount": "10"}
    failures = [FailureMode.mtls_required()]
    expected_status = [200, 401, 403]


@Endpoint(method="GET", path="/federation/registries", auth="developer", category="federation_public", idempotent=True)
class ListFederatedRegistries:
    """List all known federated registries."""
    expected_status = 200
