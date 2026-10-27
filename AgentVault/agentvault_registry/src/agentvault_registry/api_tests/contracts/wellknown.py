"""Well-known endpoint contracts (AAA+ Phase II-B, 2026-05-21).

All /.well-known/* endpoints. Public, idempotent, deterministic.
"""
from __future__ import annotations

from ..core.contract import Endpoint


@Endpoint(method="GET", path="/.well-known/oauth-authorization-server", auth="none", category="mcp_oauth", idempotent=True)
class OAuthAuthServer:
    """OAuth 2.1 authorization server discovery."""
    expected_status = 200


@Endpoint(method="GET", path="/.well-known/oauth-protected-resource", auth="none", category="mcp_oauth", idempotent=True)
class OAuthProtectedResource:
    """OAuth 2.1 protected resource discovery."""
    expected_status = 200


@Endpoint(method="GET", path="/.well-known/agent-descriptions", auth="none", category="federation_public", idempotent=True)
class AgentDescriptions:
    """Public agent descriptions catalog (A2A discovery)."""
    expected_status = 200
