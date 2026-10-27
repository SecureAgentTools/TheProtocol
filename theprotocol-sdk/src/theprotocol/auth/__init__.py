"""theprotocol.auth — Unified A2A authentication surface (Q-C BL-3, 2026-05-12).

The agent-receiving side of A2A speaks three auth surfaces, all expressible in
A2A v1.0 §4.5 SecurityScheme vocabulary:

  1. Agent JWT             — HTTPAuthSecurityScheme(scheme="bearer", bearerFormat="JWT")
                              Authorization: Bearer <jwt>
                              Verifier:  ``AgentJwtVerifier``
  2. apt_ payment token    — APIKeySecurityScheme(name="X-Payment-Token") + Extension
                              X-Payment-Token: apt_<hex>
                              Verifier:  ``PaymentVerifier``  (theprotocol.payment)
  3. IRONHAND mTLS         — MutualTlsSecurityScheme   (A2A v1.0 §4.5.6 native)
                              X.509 SVID via TLS handshake (nginx forwards PEM)
                              Verifier:  built into ``A2AAuthenticator``

``A2AAuthenticator`` is the FastAPI Depends() dependency that fans out across all
three surfaces and returns the unified auth result dict.

Per Commander Q-C signoff 2026-05-12 (BL-3 core deliverable).
"""
from __future__ import annotations

# A2AAuthenticator lives in payment.authenticator for legacy import paths; we
# re-export here so consumers can import from the canonical `theprotocol.auth`.
from ..payment.authenticator import A2AAuthenticator
from .jwt_verifier import AgentJwtVerifier
from .did_jwt import (
    EXT_URI_DID_JWT,
    DidJwtError,
    mint_did_jwt,
    verify_did_jwt,
)
from .jws_card import (
    sign_agent_card,
    verify_agent_card,
)

__all__ = [
    "A2AAuthenticator",
    "AgentJwtVerifier",
    "EXT_URI_DID_JWT",
    "DidJwtError",
    "mint_did_jwt",
    "verify_did_jwt",
    "sign_agent_card",
    "verify_agent_card",
]
