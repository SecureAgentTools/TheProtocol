"""OAuth federation contracts (AAA+ Phase II-B, 2026-05-21).

RFC 8693 token exchange + RFC 7662 introspection. Cross-registry OAuth trust.
Some endpoints have known backend bugs (FastAPI Form()/Pydantic conflict — §pass47).
"""
from __future__ import annotations

from ..core.contract import Endpoint
from ..core.failure_modes import FailureMode


@Endpoint(method="GET", path="/oauth/.well-known/jwks.json", auth="none", category="oauth_federation", idempotent=True)
class OAuthJWKS:
    """JSON Web Key Set for OAuth signature verification."""
    expected_status = 200


@Endpoint(method="POST", path="/oauth/token/exchange", auth="none", category="oauth_federation", idempotent=False)
class OAuthTokenExchange:
    """RFC 8693 token exchange.

    §RA1/RA3 (2026-07-24): the old Form()/Pydantic conflict is gone (the offending
    `verify_registry_client` helper was deleted), so a bad/absent credential is a
    clean 401. 501 is the fail-closed answer on a registry with no trusted peers,
    which is now the default posture everywhere except a configured federation.
    """
    def body(self, ctx):
        return {
            "subject_token": "placeholder",
            "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
            "audience": "spiffe://agentvault.com/registry-test-b",
        }
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 501,
            reason="OAuth federation not configured on this registry (fail-closed)",
        ),
    ]
    expected_status = [200, 401, 501]


@Endpoint(method="POST", path="/oauth/introspect", auth="none", category="oauth_federation", idempotent=False)
class OAuthIntrospect:
    """RFC 7662 token introspection. Same posture as token/exchange (see above)."""
    def body(self, ctx):
        return {"token": "placeholder"}
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 501,
            reason="OAuth federation not configured on this registry (fail-closed)",
        ),
    ]
    expected_status = [200, 401, 422, 501]


@Endpoint(method="POST", path="/oauth/revoke", auth="none", category="oauth_federation", idempotent=True)
class OAuthRevoke:
    """RFC 7009 revocation for exchanged tokens (§RA3, new 2026-07-24)."""
    def body(self, ctx):
        return {"jti": "placeholder"}
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 501,
            reason="OAuth federation not configured on this registry (fail-closed)",
        ),
    ]
    expected_status = [200, 401, 422, 501]


@Endpoint(method="GET", path="/oauth/federation/trust", auth="developer", category="oauth_federation", idempotent=True)
class OAuthFederationTrust:
    """List federation trust entries."""
    expected_status = 200


@Endpoint(
    method="DELETE",
    path="/oauth/federation/trust/{registry_url}",
    auth="developer",
    category="oauth_federation",
    idempotent=True,
)
class OAuthDeleteTrust:
    """Remove a federation trust entry. {registry_url:path} parameter."""
    expected_status = [200, 204, 404]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 404,
            reason="Trust entry placeholder URL doesn't exist",
        ),
    ]
