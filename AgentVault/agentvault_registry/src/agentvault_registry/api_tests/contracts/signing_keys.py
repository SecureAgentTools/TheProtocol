"""Signing-keys contracts (AAA+ Phase II-B — §pass36 Option C, 2026-05-21).

Per-agent Ed25519 signing keys for JWS-signed cards. Public key lookups +
admin rotation + per-developer JWKS endpoints.
"""
from __future__ import annotations

from ..core.contract import Endpoint
from ..core.failure_modes import FailureMode


# ── Public JWKS endpoints (no auth) ─────────────────────────────────────
@Endpoint(
    method="GET",
    path="/.well-known/dev-jwks.json",
    auth="none",
    category="developer_signing_keys",
    idempotent=True,
)
class DevJWKS:
    """Org-wide developer JWKS set."""
    expected_status = 200


@Endpoint(
    method="GET",
    path="/developers/{developer_id}/jwks.json",
    auth="none",
    category="developer_signing_keys",
    idempotent=True,
)
class PerDevJWKS:
    """Per-developer JWKS. Templated path — uses developer_id."""
    expected_status = [200, 404]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 404,
            reason="Developer ID placeholder substitution — no real ID resolved",
        ),
    ]


# ── Agent signing keys (admin) ───────────────────────────────────────────
@Endpoint(
    method="GET",
    path="/admin/agents/{did}/signing-keys",
    auth="developer",
    category="admin_agent_signing_keys",
    idempotent=True,
)
class AdminAgentSigningKeys:
    """Signing-key history for an agent. {did} placeholder."""
    expected_status = [200, 404]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 404,
            reason="DID placeholder — no real agent resolved",
        ),
    ]


@Endpoint(
    method="POST",
    path="/admin/agents/{did}/rotate-signing-key",
    auth="developer",
    category="admin_agent_signing_keys",
    idempotent=False,
)
class AdminRotateSigningKey:
    """Rotate Ed25519 keypair. Private PEM shown ONCE. 7-day grace."""
    def body(self, ctx):
        return {}
    expected_status = [200, 404]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 404,
            reason="DID placeholder — no real agent to rotate",
        ),
    ]
