"""§AGENTDISC #192 — A2A AgentCardSignature (detached JWS) over exported agent cards (2026-08-16).

Every card served by `card-export` gains `signatures[]` per the A2A v1.0
AgentCardSignature shape (`protected` + `signature`), signed with THE registry's
EdDSA card-signing key (the same key + JWKS the signed registry card uses:
kid = `{registry_spiffe}#{rotation_seq}`, JWKS at `/.well-known/registry-jwks.json`),
so a third party can verify an agent card and its track-record extension pointer
without trusting our HTTP responses.

Construction (documented verifier procedure — also in the protected header itself):
  1. payload = the exported card WITHOUT the `signatures` field, canonicalized with
     the `tp-sorted-ascii-v1` convention: python `json.dumps(obj, sort_keys=True,
     separators=(',',':'))` with ensure_ascii — byte-identical to the browser's
     recursive-key-sort + JSON.stringify + \\uXXXX escapes >= 0x7f (the §VCSIGN
     cross-language contract, same as the track-record receipts).
  2. protected = b64url({"alg":"EdDSA","kid":...,"cty":"application/json",
     "canon":"tp-sorted-ascii-v1"}), no padding.
  3. signing input = ASCII(protected) + "." + b64url(payload bytes)  (standard JWS
     compact signing input with a detached payload; NOT RFC 7797 b64=false, so any
     stock JWS library verifies once handed the reconstructed payload).
  4. signature = b64url(Ed25519.sign(signing input)), no padding.

Honest scope note: the A2A ecosystem may converge on RFC 8785 JCS canonicalization;
the `canon` header param makes our profile explicit and machine-detectable, and a
JCS lane can ship beside it without breaking existing verifiers. Signatures are
computed at SERVE time over the final derived card and any stored/stale
`signatures` field is dropped first — a re-registered card can never replay an old
signature as fresh (the same loop-safety rule as the track-record extension).
"""
from __future__ import annotations

import base64
import json
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

CANON_PROFILE = "tp-sorted-ascii-v1"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def canonical_card_bytes(card: Dict[str, Any]) -> bytes:
    """The signed payload: card minus `signatures`, tp-sorted-ascii-v1 canonical."""
    body = {k: v for k, v in card.items() if k != "signatures"}
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")


async def sign_agent_card(db: AsyncSession, card: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    """Return the A2A `signatures[]` block for a derived card, or None (best-effort:
    an unsigned card is served rather than failing the export)."""
    try:
        from agentvault_registry.services.registry_card_builder import _build_spiffe_id
        from agentvault_registry.services.registry_card_keystore import (
            get_or_mint_signing_key, load_private_key)
        spiffe_id = _build_spiffe_id()
        key_row = await get_or_mint_signing_key(db, spiffe_id)
        private_key = load_private_key(key_row)

        protected = _b64url(json.dumps({
            "alg": "EdDSA",
            "kid": f"{spiffe_id}#{key_row.rotation_seq}",
            "cty": "application/json",
            "canon": CANON_PROFILE,
            "jwks_url": "/.well-known/registry-jwks.json",
        }, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        signing_input = f"{protected}.{_b64url(canonical_card_bytes(card))}".encode("ascii")
        signature = _b64url(private_key.sign(signing_input))
        return [{"protected": protected, "signature": signature}]
    except Exception as e:  # noqa: BLE001 — signing must never break the export
        logger.warning("[A2A-SIG] agent card signing unavailable: %s", e)
        return None


__all__ = ["CANON_PROFILE", "canonical_card_bytes", "sign_agent_card"]
