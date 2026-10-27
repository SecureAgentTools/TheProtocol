"""JWS detached signature for A2A v1.0 AgentCard (Option C Phase 9.a).

Per A2A v1.0 §4.4 the card MAY carry a ``signatures`` array. The wire format
is RFC 7515 detached JWS (Compact Serialization minus the payload part), put
as one entry per signing key in the array:

    {
      "protocolVersion": "1.0",
      ...,
      "signatures": [
        {
          "protected": "<base64url({\"alg\":\"EdDSA\",\"kid\":\"did#1\"})>",
          "signature": "<base64url-eddsa-sig>"
        }
      ]
    }

Signing input (sorted-keys is critical for byte stability):

    b64url(protected) + "." + b64url(json(card_minus_signatures, sort_keys=True))

§pass36 Phase 9 — Commander locked: EdDSA only, agent owns its private key
(returned ONCE at agent create), rotation_seq starts at 1, manual rotation
with 7-day grace via admin endpoint.

Public API
----------
- ``sign_agent_card(card_data, private_pem, kid)`` -> card_data with
  ``signatures`` populated.
- ``verify_agent_card(card_data, public_jwk)`` -> ``(valid, reason)``.

Both helpers are self-contained — no httpx, no network. The registry-side
verifier (``services/a2a_v1/jws_verifier.py``) wraps these with key lookup
and shadow-mode logging.
"""
from __future__ import annotations

import base64
import json
from typing import Any, Dict, List, Optional, Tuple


SUPPORTED_ALGOS = ("EdDSA",)


# ─── base64url helpers (no padding, per RFC 7515) ───────────────────────────


def _b64url_enc(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _b64url_dec(s: str) -> bytes:
    padding = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + padding)


def _canonical_payload_bytes(card_data: Dict[str, Any]) -> bytes:
    """Produce the byte-stable JSON used as the JWS payload.

    Excludes the ``signatures`` array (you can't sign over the signature
    that's about to be inserted). Sorted keys + compact separators ensure
    every implementation computes the same bytes for the same logical card.
    """
    stripped = {k: v for k, v in card_data.items() if k != "signatures"}
    return json.dumps(stripped, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_agent_card(
    card_data: Dict[str, Any],
    *,
    private_pem: str,
    kid: str,
) -> Dict[str, Any]:
    """Sign an AgentCard with an Ed25519 key.

    Returns a NEW dict (does not mutate input). The returned card has a
    ``signatures`` array containing one entry; if the input already had
    signatures from other keys, those are preserved.

    Args:
        card_data: Full AgentCard JSON (sans any pre-existing entry for this kid).
        private_pem: PKCS#8 PEM Ed25519 private key (same key the registry
            returned ONCE at agent create).
        kid: ``<agent_did>#<rotation_seq>`` per plan §11.2.

    Raises:
        RuntimeError: ``cryptography`` not installed.
        ValueError: private_pem isn't an Ed25519 key.
    """
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    except ImportError as e:
        raise RuntimeError("`cryptography` package required for sign_agent_card") from e

    priv_obj = serialization.load_pem_private_key(private_pem.encode("utf-8"), password=None)
    if not isinstance(priv_obj, Ed25519PrivateKey):
        raise ValueError("private_pem is not an Ed25519 PKCS#8 key")

    header = {"alg": "EdDSA", "kid": kid}
    h_b64 = _b64url_enc(json.dumps(header, sort_keys=True, separators=(",", ":")).encode("utf-8"))

    payload_bytes = _canonical_payload_bytes(card_data)
    p_b64 = _b64url_enc(payload_bytes)

    signing_input = f"{h_b64}.{p_b64}".encode("ascii")
    sig_bytes = priv_obj.sign(signing_input)
    s_b64 = _b64url_enc(sig_bytes)

    new_entry = {"protected": h_b64, "signature": s_b64}

    # Preserve other signatures with different kid; replace any pre-existing
    # entry for this kid (idempotent re-signing).
    existing: List[Dict[str, Any]] = []
    for s in card_data.get("signatures") or []:
        if not isinstance(s, dict):
            continue
        try:
            other_hdr = json.loads(_b64url_dec(s.get("protected", "")).decode("utf-8"))
        except Exception:
            existing.append(s)
            continue
        if other_hdr.get("kid") != kid:
            existing.append(s)

    out = dict(card_data)
    out["signatures"] = existing + [new_entry]
    return out


def verify_agent_card(
    card_data: Dict[str, Any],
    public_jwk: Dict[str, Any],
    *,
    expected_kid: Optional[str] = None,
) -> Tuple[bool, Optional[str]]:
    """Verify the JWS signature on an AgentCard.

    Args:
        card_data: Full AgentCard JSON (must have ``signatures`` array).
        public_jwk: ``{kty:OKP, crv:Ed25519, x:<base64url>, ...}``.
        expected_kid: When supplied, only verify against the signature entry
            whose ``protected.kid`` matches. When omitted, verifies any
            signature in the array (returns success on the first match).

    Returns:
        ``(valid, reason)`` — ``valid=True`` means at least one signature
        verified against the supplied public key. On failure, ``reason``
        names the highest-priority failure mode.
    """
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError as e:
        raise RuntimeError("`cryptography` package required for verify_agent_card") from e

    sigs = card_data.get("signatures") or []
    if not isinstance(sigs, list) or not sigs:
        return False, "no signatures array"

    if public_jwk.get("kty") != "OKP" or public_jwk.get("crv") != "Ed25519":
        return False, "public_jwk must be OKP/Ed25519"
    try:
        pub_raw = _b64url_dec(public_jwk["x"])
        pub_obj = Ed25519PublicKey.from_public_bytes(pub_raw)
    except Exception as e:
        return False, f"invalid public key bytes: {e}"

    payload_bytes = _canonical_payload_bytes(card_data)
    p_b64 = _b64url_enc(payload_bytes)

    last_reason = "no signature matched expected_kid"
    for entry in sigs:
        if not isinstance(entry, dict):
            continue
        h_b64 = entry.get("protected")
        s_b64 = entry.get("signature")
        if not isinstance(h_b64, str) or not isinstance(s_b64, str):
            last_reason = "malformed signature entry"
            continue
        try:
            header = json.loads(_b64url_dec(h_b64).decode("utf-8"))
        except Exception:
            last_reason = "malformed protected header"
            continue
        if header.get("alg") not in SUPPORTED_ALGOS:
            last_reason = f"unsupported alg: {header.get('alg')}"
            continue
        if expected_kid is not None and header.get("kid") != expected_kid:
            continue
        try:
            sig_bytes = _b64url_dec(s_b64)
            signing_input = f"{h_b64}.{p_b64}".encode("ascii")
            pub_obj.verify(sig_bytes, signing_input)
            return True, None
        except InvalidSignature:
            last_reason = "signature verification failed"
            continue
        except Exception as e:  # malformed signature bytes etc.
            last_reason = f"verify error: {e}"
            continue

    return False, last_reason


__all__ = ["sign_agent_card", "verify_agent_card", "SUPPORTED_ALGOS"]
