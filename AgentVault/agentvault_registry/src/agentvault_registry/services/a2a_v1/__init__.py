"""A2A v1.0 protocol primitives — the canonical home for v1.0 vocabulary.

Q-C scope (BL-3 + BL-14 bundled, 2026-05-12). Per A2A v1.0 specification §4.5
(Security Objects) + §4.4 (AgentCard Objects).

This package provides:
  - SecurityScheme types (APIKey, HTTPAuth, OAuth2, OpenIdConnect, MutualTls)
    matching A2A v1.0 §4.5 official vocabulary
  - AgentInterface dataclass (v1.0 §4.4.6) for supportedInterfaces[]
  - Backwards-compat translators (v0.3 authSchemes[] → v1.0 securitySchemes{}+security[])
  - A2A Extension URI namespace constants for TheProtocol-specific extensions

Strategy/handover: `sessionlogs2026/HANDOVER_2026-05-12_BL3_FULL_AWARENESS.md`
Auth surface mapping:
  - Agent JWT       → HTTPAuthSecurityScheme(scheme="bearer", bearerFormat="JWT")
  - apt_ payment    → APIKeySecurityScheme(in="header", name="X-Payment-Token") + Extension
  - IRONHAND mTLS   → MutualTlsSecurityScheme  (NATIVE A2A v1.0)
  - did-jwt         → A2A Extension under extensions[] (URI in this module)

ALL Q-C answers locked per Commander signoff 2026-05-12:
  Q1: skip legacy SDK deprecation horizon (delete packages outright per Q8)
  Q2: JWS Agent Card signing → v1.1 (deferred)
  Q3: did-jwt private key server-generated, shown ONCE
  Q4: EdDSA (Ed25519)
  Q5: card_data authSchemes[]/v0.3 fields kept in JSONB for 6 months
  Q6: frontend bundled in Q-C
  Q7: multi-tenancy tenant field → v1.1
  Q8: delete agentvault_library + agentvault_cli + agentvault_server_sdk
  Q9: extension URI namespace = https://theprotocol.cloud/extensions/v1/...
  Q10: lossy v0.3 emit to v0.3-only peers + federation_metadata.protocol_version pin
  Q11: A2A_Protocol.md full rewrite to v1.0
  Q12: frontend stays simple — auto-generate sensible v1.0 defaults
  Q13: OAuth Device Code flow → v1.1
  Q14: all 4 bridges in Q-C (ACP already marked deprecated)
  Q15: phased prod rollout via A2A_V1_MIGRATION_PHASE env (sandbox-only this session)
"""
from __future__ import annotations

from .security_schemes import (
    APIKeySecurityScheme,
    HTTPAuthSecurityScheme,
    MutualTlsSecurityScheme,
    OAuth2SecurityScheme,
    OpenIdConnectSecurityScheme,
    SecurityScheme,
    SecuritySchemeProtocol,
)
from .compat import (
    canonicalize_card_data,
    derive_security_from_auth_schemes,
    is_v1_card,
)
from .extensions import (
    EXT_DID_JWT_SELF_SIGNED,
    EXT_A2A_PAYMENT,
    EXT_SPIFFE_TRUST_DOMAIN,
    TheProtocolExtensions,
)

__all__ = [
    # Security schemes
    "APIKeySecurityScheme",
    "HTTPAuthSecurityScheme",
    "MutualTlsSecurityScheme",
    "OAuth2SecurityScheme",
    "OpenIdConnectSecurityScheme",
    "SecurityScheme",
    "SecuritySchemeProtocol",
    # Backwards-compat translators
    "canonicalize_card_data",
    "derive_security_from_auth_schemes",
    "is_v1_card",
    # Extensions
    "EXT_DID_JWT_SELF_SIGNED",
    "EXT_A2A_PAYMENT",
    "EXT_SPIFFE_TRUST_DOMAIN",
    "TheProtocolExtensions",
]
