"""Registry Card v0.3 — receiver-side validator.

Used by federation_sync._sync_registry_card to defend against peers shipping:
  - Oversized payloads (DoS via giant JSON)
  - Deeply nested structures (parser-blow)
  - Invalid hex colors / malformed URLs
  - Sovereign-variant claims they don't own (3-way SPIFFE verify)

NB: do NOT add `from __future__ import annotations` here.
"""
import logging
import re
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# Defensive payload caps.
MAX_CARD_BYTES = 32 * 1024     # 32 KB cap on JSON body
MAX_JSON_DEPTH = 8             # nested object/array depth
MAX_FIELD_STRLEN = 2048        # max length of any single string value
_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _json_depth(obj: Any, current: int = 0) -> int:
    if isinstance(obj, dict):
        if not obj:
            return current
        return max(_json_depth(v, current + 1) for v in obj.values())
    if isinstance(obj, list):
        if not obj:
            return current
        return max(_json_depth(v, current + 1) for v in obj)
    return current


def _strings_within_cap(obj: Any) -> bool:
    if isinstance(obj, str):
        return len(obj) <= MAX_FIELD_STRLEN
    if isinstance(obj, dict):
        return all(_strings_within_cap(v) for v in obj.values())
    if isinstance(obj, list):
        return all(_strings_within_cap(v) for v in obj)
    return True


def validate_payload(card: Dict[str, Any], raw_body_bytes: int) -> Optional[str]:
    """Return None on OK; error string on rejection."""
    if raw_body_bytes > MAX_CARD_BYTES:
        return f"payload {raw_body_bytes} > MAX_CARD_BYTES={MAX_CARD_BYTES}"
    depth = _json_depth(card)
    if depth > MAX_JSON_DEPTH:
        return f"nesting depth {depth} > MAX_JSON_DEPTH={MAX_JSON_DEPTH}"
    if not _strings_within_cap(card):
        return f"a string field exceeds MAX_FIELD_STRLEN={MAX_FIELD_STRLEN}"
    if not isinstance(card.get("registry_card_version"), str):
        return "missing registry_card_version"
    if not isinstance(card.get("identity"), dict):
        return "missing identity block"
    visual = card.get("visual") or {}
    for color_key in ("orb_color", "orb_glow_color"):
        v = visual.get(color_key)
        if v is not None and not _HEX_COLOR_RE.match(str(v)):
            return f"visual.{color_key} not a valid #rrggbb hex: {v!r}"

    # Flare encirclement + overlay catalog validation (Registry Card v0.3.1).
    try:
        from ..core.registry_identity import (
            is_valid_encirclement_variant,
            is_valid_encirclement_overlay,
            is_valid_corner_variant,
        )
        enc = visual.get("flare_encirclement_variant")
        ov = visual.get("flare_encirclement_overlay")
        corner = visual.get("flare_corner_variant")
        if enc is not None and not is_valid_encirclement_variant(enc):
            return f"visual.flare_encirclement_variant={enc!r} not in catalog"
        if ov is not None and not is_valid_encirclement_overlay(ov):
            return f"visual.flare_encirclement_overlay={ov!r} not in catalog"
        if ov is not None and enc is None:
            return "visual.flare_encirclement_overlay requires flare_encirclement_variant to be set"
        if corner is not None and not is_valid_corner_variant(corner):
            return f"visual.flare_corner_variant={corner!r} not in catalog"
    except ImportError:
        # Catalog import failure — accept conservatively, log loudly elsewhere.
        pass

    return None


def verify_sovereign_variant_claim(
    card: Dict[str, Any],
    peer_svid: str,
) -> bool:
    """Validate visual.sovereign_variant (vanity, NOT identity).

    §pass78c (2026-06-05) — VANITY IS SHAREABLE (Commander directive). A registry's
    visual representation is self-determined and may be used by anyone; it does not
    have to be unique. The sovereign_variant used to be SPIFFE-locked to one owner
    (3-way verify: card id == peer SVID == catalog owner) which STRIPPED any non-owner's
    claim — and stripping a SIGNED field broke that registry's card signature on every
    peer (this is the bug that hid Frame-C's BVT orb fleet-wide). Identity/trust is
    SPIFFE + the card signature, never the orb, so there is no spoofing benefit to the
    lock. We now accept ANY known renderable variant from anyone and only soft-reject an
    unknown/garbage string (→ strip → operator-default render) so the globe always has
    defined styling to draw. `peer_svid` is retained in the signature for callers.

    Returns:
        True if no claim OR the variant is a known vanity style; False (→ strip) if
        the variant is unknown.
    """
    variant = (card.get("visual") or {}).get("sovereign_variant")
    if variant is None:
        return True  # not claiming a sovereign variant

    try:
        from ..core.registry_identity import is_known_sovereign_variant
    except ImportError:
        logger.warning("[RegistryCardValidator] registry_identity unavailable; accepting sovereign claim provisionally")
        return True

    if is_known_sovereign_variant(variant):
        return True

    logger.info(
        "[RegistryCardValidator] sovereign_variant=%r unknown (no renderable styling); stripping to operator default",
        variant,
    )
    return False


def strip_sovereign_claim(card: Dict[str, Any]) -> Dict[str, Any]:
    """Drop visual.sovereign_variant; leave the rest of the card intact.

    Used when 3-way verify fails — receiver still renders the card with
    operator-default visual identity, just without the sovereign claim.
    """
    visual = dict(card.get("visual") or {})
    visual["sovereign_variant"] = None
    out = dict(card)
    out["visual"] = visual
    return out


def check_card_namespace(card: Dict[str, Any], *, peer_trust_domain: Optional[str] = None,
                         allow_own_namespace: bool = False) -> Optional[str]:
    """§DIDWIDEN item 1 — G4. A registry card may declare ``identity.did_namespace`` (the issuer its
    agent DIDs carry). It must equal the card's own trust domain, equal the SVID-proven trust domain
    of the peer row it lands on (when known), and never be THIS registry's own issuer.

    Returns a refusal reason (``did_namespace_invalid`` | ``did_namespace_mismatch`` |
    ``did_namespace_self``) or None when the card declares no namespace or a consistent one.
    """
    import os as _os
    from ..identifiers import valid_issuer as _valid_issuer
    ident = card.get("identity") if isinstance(card, dict) else None
    if not isinstance(ident, dict):
        return None
    ns = ident.get("did_namespace")
    if ns in (None, ""):
        return None
    ns = str(ns).strip().lower()
    if not _valid_issuer(ns):
        return "did_namespace_invalid"
    own_td = (ident.get("trust_domain") or "").strip().lower()
    if own_td and ns != own_td:
        return "did_namespace_mismatch"
    if peer_trust_domain and ns != peer_trust_domain.strip().lower():
        return "did_namespace_mismatch"
    mine = (_os.environ.get("DID_ISSUER_NAMESPACE") or "").strip().lower() or (_os.environ.get("SPIRE_TRUST_DOMAIN") or "").strip().lower()
    if mine and ns == mine and not allow_own_namespace:
        # 🔴 findings row 187 — THIS GUARD IS RIGHT AND WAS OVER-BROAD BY EXACTLY ONE CASE.
        # Refusing a card that claims OUR issuer is the impersonation defence and it stays. But
        # OUR OWN CLOUD OPERATORS legitimately live under their parent frame's trust domain
        # (CLAUDE.md: "operators of a sibling frame share their parent's trust_domain"), so every
        # operator card this frame pulled was refused `did_namespace_self` — measured on EU:
        # `[RegistryCardSync] peer=amsterdam validation failed; skip` every 2 minutes since the
        # standup, which is why all four operators showed `no card`, no logo and no signature.
        #
        # `allow_own_namespace` DEFAULTS TO FALSE so every existing caller stays fail-closed, and
        # it is decided by OUR OWN PEER ROW (peer_type / is_own_reachable_op), never by anything
        # in the card — a card that could talk its way past this guard would be the whole attack.
        return "did_namespace_self"
    return None


def validate_and_normalize(
    card: Dict[str, Any],
    raw_body_bytes: int,
    *,
    peer_svid: str,
    peer_trust_domain: Optional[str] = None,
    allow_own_namespace: bool = False,
) -> Optional[Dict[str, Any]]:
    """One-call entry: validate + strip-on-sovereign-fail.

    Returns:
        The (possibly normalized) card dict on success, None if rejected outright.
    """
    err = validate_payload(card, raw_body_bytes)
    if err:
        logger.warning("[RegistryCardValidator] payload rejected from peer=%s: %s", peer_svid, err)
        return None
    ns_err = check_card_namespace(card, peer_trust_domain=peer_trust_domain,
                                  allow_own_namespace=allow_own_namespace)
    if ns_err:
        logger.warning("[RegistryCardValidator] card refused from peer=%s: %s (did_namespace=%r, trust_domain=%r)",
                       peer_svid, ns_err, (card.get("identity") or {}).get("did_namespace"), (card.get("identity") or {}).get("trust_domain"))
        return None
    if not verify_sovereign_variant_claim(card, peer_svid):
        # Soft-reject the sovereign claim only; keep the rest of the card.
        return strip_sovereign_claim(card)
    return card


__all__ = [
    "MAX_CARD_BYTES", "MAX_JSON_DEPTH", "MAX_FIELD_STRLEN",
    "validate_payload",
    "verify_sovereign_variant_claim",
    "strip_sovereign_claim",
    "validate_and_normalize",
    "check_card_namespace",
]
