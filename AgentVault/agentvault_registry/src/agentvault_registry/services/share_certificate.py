"""
§SHOWCASESTOCKS — `share.certificate.v1`, a signed artifact for a shareholding.

His ask: *"i expect a stock to be signed have a unique identifier. its missing
right?"* — right. `org_share_positions` is `(listing_id, agent_did, qty,
avg_cost)`: a fungible quantity with no identity and nothing signed. You could
own shares and have nothing to show for it.

WHAT THIS IS, AND WHAT IT IS NOT. It is not a per-share token and it does not
make shares non-fungible — inventing a second ledger beside `org_share_positions`
would put the cap table and the certificates permanently at risk of disagreeing.
It is an **attestation about a holding at a point in time**: the registry states
who holds how much of what, on which venue, and signs that statement so it
verifies offline against a pubkey the registry already publishes.

BUILT ON THE EXISTING RAIL, deliberately. `services/attestation_signer.py` is the
same signer behind `guild.work_credential.v1` and the receipts drawer, and
§AGENTDISC already shipped the in-browser verifier for that shape (canonical
JSON → sha256 → Ed25519 via SubtleCrypto). A share certificate is a sibling of a
guild receipt, so it needs no new crypto, no new key, no new verifier, and no
migration.

DETERMINISM — WHY THERE IS NO `now()` IN THE SIGNED BYTES. The claim is stamped
with the POSITION's own `updated_at`, not wall-clock time. Two consequences that
both matter: the same holding always yields the same digest and the same
signature (so a reader can re-request and compare), and the certificate is
automatically invalidated by the next trade, because the position's `updated_at`
moves. A certificate that kept saying "you own 3" after you sold them would be
worse than no certificate at all.
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from typing import Any, Dict, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

CERT_KIND = "share.certificate.v1"
# Stable namespace so a certificate id is reproducible anywhere, forever.
_NS = uuid.UUID("6f9b1f2c-8a44-5d1e-9c3b-0f7a2d5e4b81")


def _canonical(subset: Dict[str, Any]) -> str:
    """Sorted keys, tight separators, ensure_ascii — the SAME convention as
    `track_record.receipt_digest`, vcsign's `contract_attestation_digest` and
    `attestation_signer._canonical_bytes`. Byte-for-byte identical to what the
    browser recomputes; if this drifts, every verifier silently fails."""
    return json.dumps(subset, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest_of(subset: Dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(subset).encode("utf-8")).hexdigest()


async def build_certificate(db: AsyncSession, agent_did: str, symbol: str,
                            registry_name: str) -> Optional[Dict[str, Any]]:
    """The signed claim for ONE holding, or None when the agent holds none of it.

    Holding NOTHING is not an error and must not be dressed as one: a caller
    asking for a certificate they do not have gets a clean absence."""
    row = (await db.execute(text("""
        SELECT l.id, l.symbol, l.display_name, l.currency, l.total_shares,
               p.qty, p.avg_cost, p.updated_at
          FROM org_share_positions p
          JOIN exchange_listings l ON l.id = p.listing_id
         WHERE p.agent_did = :d AND upper(l.symbol) = upper(:s) AND p.qty > 0
         LIMIT 1
    """), {"d": agent_did, "s": symbol})).first()
    if not row:
        return None
    listing_id, sym, name, ccy, total, qty, avg_cost, updated_at = row

    as_of = updated_at.isoformat() if updated_at is not None else ""
    cert_id = "shc_" + str(uuid.uuid5(_NS, f"{listing_id}|{agent_did}|{qty}|{as_of}"))

    # The SIGNED subset. Everything a reader needs to check the claim, and
    # nothing that would make the same holding sign differently twice.
    claim: Dict[str, Any] = {
        "kind": CERT_KIND,
        "certificate_id": cert_id,
        "holder_did": agent_did,
        "listing_id": str(listing_id),
        "symbol": str(sym).upper(),
        "display_name": name or "",
        "qty": int(qty),
        "avg_cost": str(avg_cost),
        "currency": str(ccy),
        "total_shares": int(total) if total is not None else None,
        "venue_registry": registry_name,
        "as_of": as_of,
    }
    bundle = dict(claim)
    bundle["digest"] = digest_of(claim)
    try:
        from agentvault_registry.services.attestation_signer import (
            sign_bundle, verify_bundle_signature,
        )
        sign_bundle(bundle)
        # 🔴 SELF-CHECK, and it earned its place immediately. The first cut added
        # `signature_pubkey_b64` to the bundle AFTER signing, as a convenience
        # for the reader. `_canonical_bytes` canonicalises the WHOLE bundle
        # (blanking `signature` rather than dropping it), so that one extra key
        # changed the bytes and the served certificate verified FALSE —
        # measured: ("signature does not match canonical payload") as served,
        # ("ok") with the field removed. A signed artifact that does not verify
        # is worse than an unsigned one, because it invites trust it cannot
        # carry. The pubkey now travels OUTSIDE the signed object (the caller
        # serves it alongside, as the guild credential rail does), and this
        # refuses to return a bundle it cannot verify itself.
        ok, why = verify_bundle_signature(dict(bundle))
        if not ok:
            logger.error("[ShareCert] self-check FAILED for %s/%s: %s", agent_did, symbol, why)
            bundle["signature"] = None
            bundle["unsigned_reason"] = (f"The registry signed this holding but could not verify "
                                         f"its own signature ({why}), so it is served UNSIGNED.")
    except Exception as e:  # noqa: BLE001
        # An UNSIGNED certificate must never be served as if it were signed:
        # that is the whole value of the artifact. Say it plainly instead.
        logger.warning("[ShareCert] signer unavailable for %s/%s: %s", agent_did, symbol, e)
        bundle["signature"] = None
        bundle["unsigned_reason"] = ("This registry could not reach its attestation signer, "
                                     "so the holding is stated but NOT signed.")
    return bundle
