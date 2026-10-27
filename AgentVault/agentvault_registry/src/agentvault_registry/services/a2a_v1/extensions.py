"""TheProtocol-specific A2A v1.0 Extensions.

Per A2A v1.0 §4.6 (Extensions), agents declare additional capabilities via
AgentCard.extensions[] — each entry carries a URI namespace + version + optional
required flag. TheProtocol publishes its extensions under the namespace:

  https://theprotocol.cloud/extensions/v1/...

Per Commander Q9 (2026-05-12 signoff).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ─── URI constants ────────────────────────────────────────────────────


EXT_DID_JWT_SELF_SIGNED = "https://theprotocol.cloud/extensions/v1/auth/did-jwt-self-signed"
"""DID-key-signed JWT for offline/air-gapped agent authentication.

The agent signs an EdDSA JWT with its own DID private key (server-generated
at agent create, shown ONCE per Commander Q3). The verifier reads the agent's
public key from the resolved DID document. No registry round-trip needed.

Payload fields:
  iss = agent's DID
  aud = target agent's DID
  iat/exp (default 5-min TTL)
  nonce (replay protection; receiver tracks (iss, nonce) in LRU for 2x TTL)
"""

EXT_A2A_PAYMENT = "https://theprotocol.cloud/extensions/v1/auth/a2a-payment"
"""apt_ payment-token semantics layered onto APIKeySecurityScheme.

The token is presented as X-Payment-Token: apt_<hex64> (APIKeySecurityScheme).
This extension declares the payment-specific contract:
  - Single-use against ONE target service agent + ONE amount
  - Issued via POST /a2a-payment/authorize (caller agent JWT)
  - Verified via POST /a2a-payment/verify (no auth)
  - Settled via POST /a2a-payment/settle (caller agent JWT)
  - 15-min default TTL
"""

EXT_SPIFFE_TRUST_DOMAIN = "https://theprotocol.cloud/extensions/v1/auth/spiffe-trust-domain"
"""SPIFFE trust-domain metadata for MutualTlsSecurityScheme.

A2A v1.0's MutualTlsSecurityScheme is opaque about trust roots. This extension
declares which SPIFFE trust domains the agent participates in, enabling
cross-frame federation:
  - trust_domain: e.g. "agentvault.com" or "frame-b.theprotocol.cloud"
  - federated_domains: list of trust domains we accept via SPIFFE federation
"""


# ─── A2A v1.0 §4.4.4 AgentExtension shape ─────────────────────────────


@dataclass(frozen=True)
class AgentExtension:
    """A2A v1.0 §4.4.4 — declares a supported/required extension on AgentCard.

    Rendered into AgentCard.extensions[] JSON.
    """
    uri: str                               # canonical extension URI
    description: Optional[str] = None
    required: bool = False                 # if True, caller MUST support this
    params: Optional[Dict[str, Any]] = None

    def to_a2a_json(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"uri": self.uri}
        if self.description:
            out["description"] = self.description
        if self.required:
            out["required"] = True
        if self.params:
            out["params"] = self.params
        return out


# ─── Factory helpers ──────────────────────────────────────────────────


def did_jwt_extension(audience: Optional[str] = None, lifetime_sec: int = 300) -> AgentExtension:
    """Declare did-jwt-self-signed support on AgentCard.extensions[]."""
    params: Dict[str, Any] = {
        "lifetimeSec": lifetime_sec,
        "supportedAlgos": ["EdDSA"],       # Commander Q4 locked
    }
    if audience:
        params["audience"] = audience
    return AgentExtension(
        uri=EXT_DID_JWT_SELF_SIGNED,
        description="EdDSA-signed JWT using agent's DID private key; offline-capable",
        required=False,
        params=params,
    )


def a2a_payment_extension(
    issuer_registry: str,
    required_amount: Optional[str] = None,
    required_currency: str = "AVT",
) -> AgentExtension:
    """Declare apt_ payment-token semantics on AgentCard.extensions[]."""
    params: Dict[str, Any] = {
        "issuerRegistry": issuer_registry,
        "currency": required_currency,
    }
    if required_amount is not None:
        params["requiredAmount"] = required_amount
    return AgentExtension(
        uri=EXT_A2A_PAYMENT,
        description="A2A payment token; single-use; settlement-after-success",
        required=False,
        params=params,
    )


def spiffe_trust_domain_extension(
    trust_domain: str,
    federated_domains: Optional[List[str]] = None,
) -> AgentExtension:
    """Declare SPIFFE trust-domain metadata for IRONHAND mTLS."""
    params: Dict[str, Any] = {"trustDomain": trust_domain}
    if federated_domains:
        params["federatedDomains"] = federated_domains
    return AgentExtension(
        uri=EXT_SPIFFE_TRUST_DOMAIN,
        description="SPIFFE x509 SVID trust-domain metadata for IRONHAND mTLS",
        required=False,
        params=params,
    )


class TheProtocolExtensions:
    """Convenience grouping — all TheProtocol-defined extension URIs in one place."""

    DID_JWT_SELF_SIGNED = EXT_DID_JWT_SELF_SIGNED
    A2A_PAYMENT = EXT_A2A_PAYMENT
    SPIFFE_TRUST_DOMAIN = EXT_SPIFFE_TRUST_DOMAIN

    ALL = (
        EXT_DID_JWT_SELF_SIGNED,
        EXT_A2A_PAYMENT,
        EXT_SPIFFE_TRUST_DOMAIN,
    )


__all__ = [
    "EXT_DID_JWT_SELF_SIGNED",
    "EXT_A2A_PAYMENT",
    "EXT_SPIFFE_TRUST_DOMAIN",
    "AgentExtension",
    "did_jwt_extension",
    "a2a_payment_extension",
    "spiffe_trust_domain_extension",
    "TheProtocolExtensions",
]
