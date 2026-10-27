"""Registry Card — JWS signer (LIVE; cards are v0.6 as of §REGAUTH).

Signs cards via registry_card_keystore (Ed25519 PEM). Returns None only when no active
signing key is available — the card is then served unsigned (signature block absent).

The signed canonical fields are exactly `SIGNED_CANONICAL_PATHS` below (no count here: it
said 24 while the list held 28, §DOCSFIX CB-396). Verifiers MUST take the list from the card's own
`signature.signed_canonical`, never from a spec snapshot — that is what lets the set
grow without breaking old verifiers. (§POCKETBRIDGE5 W-E: an earlier docstring here
enumerated "the 13 fields from spec §2" long after the list reached 24 — the constant
is the truth, prose is not.)

NB: do NOT add `from __future__ import annotations` here — same reason as
serve_well_known_card (FastAPI handler introspection).
"""
import logging
from typing import Any, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# The canonical paths that participate in the JWS detached signature (the card's
# own signature.signed_canonical mirrors this list — IT is the verifier's input).
SIGNED_CANONICAL_PATHS = [
    "registry_card_version",
    "identity.spiffe_id",
    "identity.registry_name",
    "identity.trust_domain",
    "identity.did_namespace",  # §DIDWIDEN-1: the issuer namespace is a signed claim (verifiers read the card's OWN declared list)
    "identity.tier",
    "visual.sovereign_variant",
    "federation.is_genesis_registry",
    "federation.is_sovereign_frame",
    "federation.policy_hash",
    "fees.cross_registry.base_rate_percent",
    "fees.hosting.enabled",
    "fees.hosting.rate_percent_of_agent_service_fee",
    "fees.settlement_currency",
    "lifecycle.card_etag",
    # AUDIT cross-cutting #1 — authoritative-but-previously-UNSIGNED fields. These
    # drive real consumer decisions (globe placement, routing, AGORA venue, fees)
    # so an attacker editing them must now break the signature. Signed as specific
    # leaves (not whole blocks) to avoid validator-normalization mismatches.
    "identity.public_url",
    "identity.software_version",
    "operator.latitude",
    "operator.longitude",
    "capabilities",
    "fees.exchange.enabled",
    "fees.exchange.stock_card.digest",
    "fees.fx.enabled",
    "description",
    # REGAUTH (card v0.6, SPEC 2026-08-15) — the compliance block (declared
    # jurisdiction profile + recorded regulatory authorizations) is a public
    # ATTESTATION, so it must be signature-covered. Signed as ONE recomputable
    # digest leaf (sha256 over the block's own canonical content, minus the leaf)
    # — the stock_card.digest pattern — so a verifier checks it from the card's
    # bytes without whole-block canonicalization mismatches. Absent block ⇒ the
    # leaf extracts as None, exactly like the other optional leaves above.
    "compliance.digest",
    # §FEDLICENCE (2026-09-28): the licence state and hashes are claims a peer acts on (enforce refuses by them), so a
    # card that edits them must break its signature. The certificate itself needs no card signature: its ISSUER signed
    # it, and the signed hash binds this card to exactly that certificate. Absent on older cards: extracts as None.
    "federation.licence.state",
    "federation.licence.hash",
    "federation.licence.operator.hash",
]

# AUDIT cross-cutting #4 — signature freshness window (replay/rollback defense).
# Peers re-pull every ~5min, so a 1h validity gives ~12× margin against clock
# skew / pull latency while still rejecting a stale replayed card.
_SIGNATURE_TTL_SECONDS = 3600


def extract_paths(card: Dict[str, Any], paths) -> Dict[str, Any]:
    """Pull the given dotted paths out of a card, in the given order. The
    verifier MUST call this with the card's OWN declared `signature.signed_canonical`
    (not a hardcoded constant) so verification is forward/backward-compatible as
    the signed set grows."""
    out: Dict[str, Any] = {}
    for path in (paths or []):
        cursor: Any = card
        for part in path.split("."):
            if isinstance(cursor, dict) and part in cursor:
                cursor = cursor[part]
            else:
                cursor = None
                break
        out[path] = cursor
    return out


def extract_canonical_payload(card: Dict[str, Any]) -> Dict[str, Any]:
    """Pull only the signed paths out of a card, in deterministic order."""
    return extract_paths(card, SIGNED_CANONICAL_PATHS)


async def sign_registry_card(
    card: Dict[str, Any],
    *,
    db: AsyncSession,
) -> Optional[Dict[str, Any]]:
    """Return the signature block, or None if signing not yet wired.

    Phase 6 will replace this stub with:
      - load current registry_signing_keys row (auto-mint if missing)
      - canonicalize extract_canonical_payload(card)
      - Ed25519 sign → detached JWS → base64
      - return {alg, kid, jwks_url, signed_canonical, value}
    """
    try:
        from .registry_card_keystore import get_or_mint_signing_key  # Phase 6
        from .registry_card_signer_impl import sign_with_keypair    # Phase 6
    except ImportError:
        logger.debug("[RegistryCardSigner] Phase 6 stub: no signing performed yet")
        return None

    payload = extract_canonical_payload(card)
    spiffe_id = card.get("identity", {}).get("spiffe_id")
    if not spiffe_id:
        return None

    # AUDIT cross-cutting #4 — fold a signed freshness window into the payload.
    # signed_at/expires_at live in the signature block (NOT the card body) so they
    # never churn the content ETag; the verifier reconstructs them + rejects an
    # expired (replayed) card.
    import datetime as _dt
    _now = _dt.datetime.now(_dt.timezone.utc)
    signed_at = _now.isoformat()
    expires_at = (_now + _dt.timedelta(seconds=_SIGNATURE_TTL_SECONDS)).isoformat()
    payload["_signed_at"] = signed_at
    payload["_expires_at"] = expires_at

    key_row = await get_or_mint_signing_key(db, spiffe_id)
    signature_value = sign_with_keypair(payload, key_row)
    return {
        "alg":               "EdDSA",
        "kid":               f"{spiffe_id}#{key_row.rotation_seq}",
        "jwks_url":          "/.well-known/registry-jwks.json",
        "signed_canonical":  SIGNED_CANONICAL_PATHS,
        "signed_at":         signed_at,
        "expires_at":        expires_at,
        "value":             signature_value,
    }


__all__ = ["sign_registry_card", "extract_canonical_payload", "SIGNED_CANONICAL_PATHS"]
