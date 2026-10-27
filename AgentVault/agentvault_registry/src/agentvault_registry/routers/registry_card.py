"""Registry Card — public well-known endpoints (cards are v0.6 since §REGAUTH).

NB: do NOT add `from __future__ import annotations` here — FastAPI introspects
route handlers' annotations at registration time, and with stringified
annotations the `Response` forward ref leaks into pydantic schema generation
and crashes startup. See feedback_serve_well_known_card_pattern.md.

Routes (all public, no auth):
  GET  /.well-known/registry-card.json         — full card (v0.6), ETag + Cache-Control
  GET  /.well-known/registry-jwks.json         — JWKS of registry signing keys
  GET  /.well-known/registry-card-schema.json  — JSON Schema Draft 2020-12 for v0.6

Per CLAUDE.md PART 11: the canonical fetch path is well-known, not
/api/v1/.well-known/. Routes are mounted via app.include_router(router) with
NO prefix so the spec-required path holds.
"""
import datetime
import json
import logging
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, Response, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models
from ..database import get_db
from ..services.registry_card_builder import build_registry_card
from ..services.registry_card_signer import SIGNED_CANONICAL_PATHS

logger = logging.getLogger(__name__)

# §POCKETBRIDGE5 — vendored v0.6 schema, loaded once per worker.
_SCHEMA_V06_BODY: bytes | None = None

router = APIRouter(tags=["Registry Card"])

# 5-minute browser cache + 10-min stale-while-revalidate so the orb stays
# alive even during a brief registry restart.
_CACHE_CONTROL_VALUE = "public, max-age=300, stale-while-revalidate=600"

# Per-worker built-body cache, keyed by the operator-edits-only etag. The etag
# only changes on an operator edit / stable-LOCKED change, so a short TTL is safe
# and lets repeat 200s skip the full build+sign (audit A2).
_CARD_CACHE: Dict[str, Any] = {"etag": None, "body": None, "ts": 0.0, "version": None}
_CARD_CACHE_TTL = 30.0


def _strip_quotes(etag_header_value: Optional[str]) -> Optional[str]:
    """If-None-Match comes in quoted; ETag we emit is bare sha256:hex. Tolerate both."""
    if not etag_header_value:
        return None
    v = etag_header_value.strip()
    if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
        v = v[1:-1]
    return v


@router.get(
    "/.well-known/registry-card.json",
    response_class=Response,
    summary="Public Registry Card (v0.6)",
    description=(
        "Returns the full registry card (registry_card_version 0.6; the compliance block when the registry "
        "declares one; a signature over the paths its `signature.signed_canonical` lists, "
        f"{len(SIGNED_CANONICAL_PATHS)} in this release). The `X-Registry-Card-Version` header repeats the "
        "card's version. ETag-driven; supports If-None-Match → 304."
    ),
)
async def get_well_known_registry_card(
    if_none_match: Optional[str] = Header(default=None, alias="If-None-Match"),
    db: AsyncSession = Depends(get_db),
) -> Response:
    # Cheap 304: compute the operator-edits-only etag WITHOUT a full build/sign
    # (audit A1). Reads the singleton row + active policy only.
    from ..services.registry_card_builder import compute_serve_etag
    serve_etag = None
    try:
        serve_etag = await compute_serve_etag(db)
    except Exception as e:
        logger.debug("[RegistryCard] cheap etag failed; falling back to full build: %s", e)

    client_etag = _strip_quotes(if_none_match)
    if serve_etag and client_etag and client_etag == serve_etag:
        return Response(
            status_code=status.HTTP_304_NOT_MODIFIED,
            headers={"ETag": f'"{serve_etag}"', "Cache-Control": _CACHE_CONTROL_VALUE},
        )

    # Body cache hit (same etag, fresh) → skip the full build+sign (audit A2).
    now = time.monotonic()
    if (serve_etag and _CARD_CACHE["etag"] == serve_etag
            and _CARD_CACHE["body"] is not None
            and (now - _CARD_CACHE["ts"]) < _CARD_CACHE_TTL):
        body = _CARD_CACHE["body"]
        etag = serve_etag
        version = _CARD_CACHE.get("version") or ""
    else:
        card = await build_registry_card(db, sign=True)
        etag = card.get("lifecycle", {}).get("card_etag", "") or serve_etag or ""
        body = json.dumps(card, separators=(",", ":"), default=str).encode("utf-8")
        # §DOCSFIX CB-396/D6-711: the header is the card's own version; a literal "0.4" rode on every 0.6 card
        version = str(card.get("registry_card_version") or "")
        _CARD_CACHE.update({"etag": etag, "body": body, "ts": now, "version": version})

    return Response(
        content=body,
        media_type="application/json",
        headers={
            "ETag": f'"{etag}"',
            "Cache-Control": _CACHE_CONTROL_VALUE,
            "X-Registry-Card-Version": version,
        },
    )


@router.get(
    "/api/v1/public/registry-card",
    summary="Public registry card (self or a federated peer) for the discovery 'source registry' modal",
    description=(
        "Returns a uniform envelope around a registry card so the UI can show ANY "
        "agent's source-registry card. No `peer` (or peer==self) → this registry's full "
        "signed card. `peer=<name>` → that federated peer's cached signed card. Public; "
        "registry cards are public signed documents."
    ),
)
async def get_public_registry_card(
    peer: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    # Self card (local-agent source, or explicit self name)
    if not peer or not peer.strip():
        card = await build_registry_card(db, sign=True)
        ident = card.get("identity", {}) if isinstance(card, dict) else {}
        base = (ident.get("public_url") or "").rstrip("/")
        # on self, the card's licence block IS this registry's own derivation (services/federation_licence.card_block)
        _own_lic = ((card.get("federation") or {}).get("licence") or {}) if isinstance(card, dict) else {}
        return {
            "is_self": True,
            "name": ident.get("display_name") or ident.get("registry_name"),
            "base_url": ident.get("public_url"),
            "card_etag": card.get("lifecycle", {}).get("card_etag"),
            "card_signature_verified": True,
            "card_last_pulled_at": None,
            "public_card_url": (base + "/.well-known/registry-card.json") if base else None,
            "licence_state": _own_lic.get("state"),
            "licence_reason": _own_lic.get("reason"),
            "licence_checked_at": _own_lic.get("checked_at"),
            "card": card,
        }
    name = peer.strip()
    row = (await db.execute(
        select(models.PeerRegistry).where(models.PeerRegistry.name == name)
    )).scalar_one_or_none()
    if row is None:
        row = (await db.execute(
            select(models.PeerRegistry).where(func.lower(models.PeerRegistry.name) == name.lower())
        )).scalar_one_or_none()
    if row is None or not isinstance(getattr(row, "cached_registry_card", None), dict):
        return Response(
            content=json.dumps({"error": "peer_card_unavailable", "peer": name}),
            media_type="application/json",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    # Display URL = the peer's OWN advertised public_url from its signed card
    # (e.g. https://sandboxcharlie.op.theprotocol.cloud), NOT peer_registries.base_url
    # — that column holds the INTERNAL mTLS routing host (nginx-test-c:8443 /
    # *.op-sandbox-b.internal) and must stay internal for federation pulls. The
    # modal showed that internal host as the registry's "Public URL"; prefer the
    # card's identity.public_url so the UI shows the real external subdomain
    # (prod-safe: prod peers advertise their real public_url too). [Commander 2026-06-04]
    _ccard = row.cached_registry_card if isinstance(getattr(row, "cached_registry_card", None), dict) else {}
    _card_public_url = ((_ccard.get("identity") or {}).get("public_url") or "").strip()
    advertised = _card_public_url or (getattr(row, "base_url", "") or "")
    base = advertised.rstrip("/")
    return {
        "is_self": False,
        "name": row.name,
        "base_url": advertised or None,
        "card_etag": getattr(row, "card_etag", None),
        "card_signature_verified": getattr(row, "card_signature_verified", None),
        "card_last_pulled_at": row.card_last_pulled_at.isoformat() if getattr(row, "card_last_pulled_at", None) else None,
        "public_card_url": (base + "/.well-known/registry-card.json") if base else None,
        # §FEDLICENCE (2026-09-28, agentvault2-a4's review item 5): THIS registry's verdict about the peer's network
        # licence, from its own peer row (the sync worker's evaluation of the certificate), never the card's claim. A peer
        # signs its own card, so card.federation.licence.state is what it says about itself; None = not evaluated here.
        "licence_state": getattr(row, "licence_state", None),
        "licence_reason": getattr(row, "licence_reason", None),
        "licence_checked_at": row.licence_checked_at.isoformat() if getattr(row, "licence_checked_at", None) else None,
        "card": row.cached_registry_card,
    }


@router.get(
    "/.well-known/registry-jwks.json",
    response_class=Response,
    summary="Registry signing keys (public JWKS)",
    description=(
        "Returns every unexpired public key in this registry's signing-key store: the Ed25519 keys that sign "
        "/.well-known/registry-card.json (the current key, earlier ones inside their grace period, and keys "
        "under an earlier SPIFFE ID of this registry, which keep no expiry), and the keys the registry holds "
        "for other purposes, such as its web push key (ES256) and an OAuth federation key (RS256). Verifiers "
        "select by kid (a card key's is \"<spiffe_id>#<rotation_seq>\") and check a card only with an Ed25519 key."
    ),
)
async def get_well_known_registry_jwks(
    db: AsyncSession = Depends(get_db),
) -> Response:
    now = datetime.datetime.now(datetime.timezone.utc)
    stmt = (
        select(models.RegistrySigningKey)
        .where(
            (models.RegistrySigningKey.expires_at.is_(None))
            | (models.RegistrySigningKey.expires_at > now)
        )
        .order_by(models.RegistrySigningKey.rotation_seq.desc())
    )
    rows = (await db.execute(stmt)).scalars().all()

    keys = []
    for r in rows:
        kid = f"{r.registry_spiffe_id}#{r.rotation_seq}"
        jwk = dict(r.public_jwk) if isinstance(r.public_jwk, dict) else {}
        jwk["kid"] = kid
        jwk["alg"] = r.algorithm
        jwk["use"] = "sig"
        keys.append(jwk)

    body = json.dumps({"keys": keys}, separators=(",", ":")).encode("utf-8")
    return Response(
        content=body,
        media_type="application/json",
        headers={"Cache-Control": _CACHE_CONTROL_VALUE},
    )


@router.get(
    "/.well-known/registry-card-schema.json",
    response_class=Response,
    summary="JSON Schema (Draft 2020-12) for Registry Card v0.6",
    description=(
        "Returns the canonical JSON Schema for v0.6 cards. External validators "
        "can introspect this to validate any peer's card payload."
    ),
)
async def get_well_known_registry_card_schema() -> Response:
    # §POCKETBRIDGE5 W-E (DOCSYNC defect 5): this route generated its schema
    # from the pydantic v0.3 model YEARS of card versions ago — an external
    # validator trusting it REJECTED every live v0.6 card three ways (proven
    # live 2026-08-23: additionalProperties on `compliance`, const "0.3", enum
    # ["0.3"]). The served schema is now the VENDORED canonical v0.6 document
    # (static_schemas/registry_card_v0.6.schema.json), read once per process.
    # §DOCSFIX CB-394: that file had drifted from the published schema (the doc
    # source's specs/registry-card-v0.6.schema.json) and rejected the builder's own
    # cards (endpoints.agent_card_well_known is null by design). It is now a byte
    # copy of it; tests/test_registry_card_served_schema.py keeps the two equal and
    # validates a built card against what this route serves.
    global _SCHEMA_V06_BODY
    if _SCHEMA_V06_BODY is None:
        import pathlib
        p = pathlib.Path(__file__).resolve().parent.parent / "static_schemas" / "registry_card_v0.6.schema.json"
        schema = json.loads(p.read_text(encoding="utf-8"))
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$id"] = "https://docs.theprotocol.cloud/schemas/registry-card-v0.6.json"
        _SCHEMA_V06_BODY = json.dumps(schema, separators=(",", ":"), default=str).encode("utf-8")
    body = _SCHEMA_V06_BODY
    return Response(
        content=body,
        media_type="application/json",
        headers={"Cache-Control": "public, max-age=3600"},
    )
