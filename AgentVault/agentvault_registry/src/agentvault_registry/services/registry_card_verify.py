"""V0663, the Directory read path: one verifier for a registry card's own signature.

The checks are the federation sync's (background_tasks/federation_sync.py, the RegistryCardSync phase 6 block), as one
function a reader can call with a card and a key set it fetched itself:
  1. the card names a signature value and a kid, and the key set holds that kid;
  2. the payload is rebuilt from the card's OWN declared signed_canonical (forward and backward compatible as the signed
     set grows), with the freshness anchor folded in (_signed_at, _expires_at), and the EdDSA signature checked on the
     card as received;
  3. an expired signature is refused even when the signature itself holds (a replayed card);
  4. a compliance block must hash to the digest the signature covers (spec 7.4 step 7).
The federation sync keeps its own copy for now: the read path does not change the fan-out (step 2 of the plan moves the
sync onto this function).
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Dict, Optional, Tuple


def verify_registry_card(card: Any, jwks: Optional[Dict[str, Any]]) -> Tuple[bool, str]:
    """(True, "ok") when the card's signature holds against `jwks`; otherwise (False, a short reason)."""
    from .registry_card_signer import SIGNED_CANONICAL_PATHS, extract_paths
    from .registry_card_signer_impl import verify_with_jwk

    if not isinstance(card, dict):
        return False, "not a card"
    sig = card.get("signature") if isinstance(card.get("signature"), dict) else {}
    if not (sig.get("value") and sig.get("kid")):
        return False, "unsigned"
    if not isinstance(jwks, dict) or not isinstance(jwks.get("keys"), list):
        return False, "no jwks"
    key = next((k for k in jwks["keys"] if isinstance(k, dict) and k.get("kid") == sig.get("kid")), None)
    if key is None:
        return False, "kid not in jwks"
    payload = extract_paths(card, sig.get("signed_canonical") or SIGNED_CANONICAL_PATHS)
    if sig.get("signed_at") is not None:
        payload["_signed_at"] = sig.get("signed_at")
    if sig.get("expires_at") is not None:
        payload["_expires_at"] = sig.get("expires_at")
    try:
        ok = verify_with_jwk(payload, str(sig["value"]), key)
    except Exception as e:  # noqa: BLE001
        return False, f"verify error {type(e).__name__}"
    if not ok:
        return False, "signature invalid"
    if sig.get("expires_at"):
        try:
            exp = dt.datetime.fromisoformat(str(sig["expires_at"]).replace("Z", "+00:00"))
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=dt.timezone.utc)
        except ValueError:
            return False, "expiry unreadable"
        if exp < dt.datetime.now(dt.timezone.utc):
            return False, "signature expired"
    if isinstance(card.get("compliance"), dict):
        from .regulatory_auth import compliance_digest
        comp = card["compliance"]
        if compliance_digest(comp) != comp.get("digest"):
            return False, "compliance digest mismatch"
    return True, "ok"
