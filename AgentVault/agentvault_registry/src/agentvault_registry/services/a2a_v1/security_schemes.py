"""A2A v1.0 §4.5 Security Schemes — OpenAPI-style typed vocabulary.

Mirrors the OpenAPI 3.0 Security Scheme object family which A2A v1.0 adopts:
  4.5.1 SecurityScheme (union/base)
  4.5.2 APIKeySecurityScheme
  4.5.3 HTTPAuthSecurityScheme
  4.5.4 OAuth2SecurityScheme
  4.5.5 OpenIdConnectSecurityScheme
  4.5.6 MutualTlsSecurityScheme    ← IRONHAND maps directly

Each scheme is a frozen dataclass with `kind` discriminator (NOT `type` — A2A v1.0
member-presence pattern, distinct from our legacy SDK's `type` field).

Per Q-C Commander signoff 2026-05-12.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Protocol, Union, runtime_checkable


# ─── Base protocol ────────────────────────────────────────────────────


@runtime_checkable
class SecuritySchemeProtocol(Protocol):
    """Common contract every concrete SecurityScheme satisfies.

    Discriminated by the unique field they carry (`api_key_security_scheme`,
    `http_auth_security_scheme`, etc.) when serialised to AgentCard.securitySchemes
    JSONB. Mirrors A2A v1.0 §4.5.1 dispatch.
    """
    kind: str
    description: Optional[str]

    def to_a2a_json(self) -> Dict[str, Any]:
        """Render this scheme to A2A v1.0 wire format."""
        ...


# ─── 4.5.2 APIKeySecurityScheme ───────────────────────────────────────


@dataclass(frozen=True)
class APIKeySecurityScheme:
    """API key — value carried in header/query/cookie.

    A2A v1.0 §4.5.2. Maps:
      - apt_ payment tokens: in="header", name="X-Payment-Token"
      - dev API keys: in="header", name="X-Api-Key"
    """
    name: str                              # header/query/cookie name
    in_: Literal["header", "query", "cookie"] = "header"
    description: Optional[str] = None
    kind: Literal["apiKey"] = "apiKey"

    def to_a2a_json(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "type": "apiKey",
            "in": self.in_,
            "name": self.name,
        }
        if self.description:
            out["description"] = self.description
        return out


# ─── 4.5.3 HTTPAuthSecurityScheme ─────────────────────────────────────


@dataclass(frozen=True)
class HTTPAuthSecurityScheme:
    """HTTP authentication — value carried in Authorization header.

    A2A v1.0 §4.5.3. Maps:
      - Agent JWT: scheme="bearer", bearer_format="JWT"
      - Basic auth: scheme="basic"
    """
    scheme: str                            # "bearer" | "basic" | ...
    bearer_format: Optional[str] = None    # e.g. "JWT"
    description: Optional[str] = None
    kind: Literal["http"] = "http"

    def to_a2a_json(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "type": "http",
            "scheme": self.scheme,
        }
        if self.bearer_format:
            out["bearerFormat"] = self.bearer_format
        if self.description:
            out["description"] = self.description
        return out


# ─── 4.5.4 OAuth2SecurityScheme + 4.5.7-10 flows ──────────────────────


@dataclass(frozen=True)
class OAuth2AuthorizationCodeFlow:
    """A2A v1.0 §4.5.8 with PKCE support (RFC 7636)."""
    authorization_url: str
    token_url: str
    scopes: Dict[str, str] = field(default_factory=dict)
    pkce_required: bool = False           # RFC 7636 (NEW in v1.0)
    refresh_url: Optional[str] = None

    def to_a2a_json(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "authorizationUrl": self.authorization_url,
            "tokenUrl": self.token_url,
            "scopes": self.scopes,
        }
        if self.pkce_required:
            out["pkceRequired"] = True
        if self.refresh_url:
            out["refreshUrl"] = self.refresh_url
        return out


@dataclass(frozen=True)
class OAuth2ClientCredentialsFlow:
    """A2A v1.0 §4.5.9."""
    token_url: str
    scopes: Dict[str, str] = field(default_factory=dict)
    refresh_url: Optional[str] = None

    def to_a2a_json(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "tokenUrl": self.token_url,
            "scopes": self.scopes,
        }
        if self.refresh_url:
            out["refreshUrl"] = self.refresh_url
        return out


@dataclass(frozen=True)
class OAuth2DeviceCodeFlow:
    """A2A v1.0 §4.5.10 — RFC 8628 Device Authorization Grant (NEW in v1.0).

    For CLI tools, IoT devices, headless environments.
    Deferred for TheProtocol agent-to-agent surface per Commander Q13 (v1.1+).
    """
    device_authorization_url: str
    token_url: str
    scopes: Dict[str, str] = field(default_factory=dict)
    refresh_url: Optional[str] = None

    def to_a2a_json(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "deviceAuthorizationUrl": self.device_authorization_url,
            "tokenUrl": self.token_url,
            "scopes": self.scopes,
        }
        if self.refresh_url:
            out["refreshUrl"] = self.refresh_url
        return out


@dataclass(frozen=True)
class OAuth2SecurityScheme:
    """A2A v1.0 §4.5.4 + §4.5.7 OAuthFlows.

    Implicit + Password flows REMOVED in v1.0 per OAuth 2.0 BCP.
    """
    flows: Dict[str, Any]                  # {"authorizationCode": {...}, "clientCredentials": {...}, "deviceCode": {...}}
    description: Optional[str] = None
    kind: Literal["oauth2"] = "oauth2"

    def to_a2a_json(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "type": "oauth2",
            "flows": self.flows,
        }
        if self.description:
            out["description"] = self.description
        return out


# ─── 4.5.5 OpenIdConnectSecurityScheme ────────────────────────────────


@dataclass(frozen=True)
class OpenIdConnectSecurityScheme:
    """A2A v1.0 §4.5.5. Discovery via openIdConnectUrl."""
    open_id_connect_url: str
    description: Optional[str] = None
    kind: Literal["openIdConnect"] = "openIdConnect"

    def to_a2a_json(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "type": "openIdConnect",
            "openIdConnectUrl": self.open_id_connect_url,
        }
        if self.description:
            out["description"] = self.description
        return out


# ─── 4.5.6 MutualTlsSecurityScheme ────────────────────────────────────


@dataclass(frozen=True)
class MutualTlsSecurityScheme:
    """A2A v1.0 §4.5.6 — NATIVE mTLS support.

    Maps to TheProtocol's IRONHAND SPIFFE-x509 SVID directly. The SPIFFE
    trust-domain detail rides as a sibling TheProtocol extension under
    AgentCard.extensions[] (see services.a2a_v1.extensions).
    """
    description: Optional[str] = None
    kind: Literal["mutualTLS"] = "mutualTLS"

    def to_a2a_json(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"type": "mutualTLS"}
        if self.description:
            out["description"] = self.description
        return out


# ─── Union type ───────────────────────────────────────────────────────


SecurityScheme = Union[
    APIKeySecurityScheme,
    HTTPAuthSecurityScheme,
    OAuth2SecurityScheme,
    OpenIdConnectSecurityScheme,
    MutualTlsSecurityScheme,
]


# ─── Convenience constructors for TheProtocol's 3 surfaces ────────────


def agent_jwt_scheme(token_url: str) -> OAuth2SecurityScheme:
    """The Agent JWT auth surface, expressed as A2A v1.0 OAuth2 client-credentials.

    Maps to:
      POST /auth/agent/token   with client_id + client_secret (existing surface)
      Authorization: Bearer <jwt>   on subsequent A2A calls
    """
    return OAuth2SecurityScheme(
        flows={
            "clientCredentials": OAuth2ClientCredentialsFlow(
                token_url=token_url,
            ).to_a2a_json(),
        },
        description="Agent JWT via OAuth2 client-credentials grant",
    )


def agent_jwt_bearer_scheme() -> HTTPAuthSecurityScheme:
    """Simpler alternative — just Authorization: Bearer <jwt> declared as HTTP auth.

    Use when caller is presenting an already-acquired JWT.
    """
    return HTTPAuthSecurityScheme(
        scheme="bearer",
        bearer_format="JWT",
        description="Authorization: Bearer <jwt>",
    )


def a2a_payment_scheme() -> APIKeySecurityScheme:
    """The apt_ payment-token auth surface.

    The payment-specific semantics (single-use, settlement-after-success) ride
    as a sibling TheProtocol extension under AgentCard.extensions[].
    """
    return APIKeySecurityScheme(
        name="X-Payment-Token",
        in_="header",
        description="A2A payment token (apt_<hex>), single-use; see TheProtocol extension https://theprotocol.cloud/extensions/v1/auth/a2a-payment",
    )


def ironhand_mtls_scheme() -> MutualTlsSecurityScheme:
    """The IRONHAND SPIFFE mTLS auth surface.

    SPIFFE trust-domain metadata rides under extensions[].
    """
    return MutualTlsSecurityScheme(
        description="SPIFFE x509 SVID via mutual TLS (IRONHAND); see TheProtocol extension https://theprotocol.cloud/extensions/v1/auth/spiffe-trust-domain",
    )


__all__ = [
    "SecuritySchemeProtocol",
    "APIKeySecurityScheme",
    "HTTPAuthSecurityScheme",
    "OAuth2SecurityScheme",
    "OAuth2AuthorizationCodeFlow",
    "OAuth2ClientCredentialsFlow",
    "OAuth2DeviceCodeFlow",
    "OpenIdConnectSecurityScheme",
    "MutualTlsSecurityScheme",
    "SecurityScheme",
    "agent_jwt_scheme",
    "agent_jwt_bearer_scheme",
    "a2a_payment_scheme",
    "ironhand_mtls_scheme",
]
