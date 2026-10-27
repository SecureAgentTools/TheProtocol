"""§pass51 Block 1 — per-developer signing key endpoints.

  POST /developers/me/signing-key/rotate     → generate fresh key, revoke prior
  GET  /developers/me/signing-keys           → list this dev's key history
  GET  /developers/{id}/jwks.json            → public JWKS for one dev (verify)
  GET  /.well-known/dev-jwks.json            → all-devs JWKS (org-wide; verify)

Note: JWKS endpoints are public (no auth) so cross-registry verifiers can
fetch them per PLAN §14.3 step 4.
"""
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Security
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry.database import get_db
from agentvault_registry.models import Developer
from agentvault_registry.security import get_current_developer
from agentvault_registry.services.bundles import signing as signing_svc

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Developer Signing Keys"])

# §pass63 follow-up (2026-05-22) — separate router mounted at root (no /api/v1
# prefix) for the public well-known JWKS endpoint. Mirrors how anp_discovery
# splits its `router` (prefixed) from `well_known_router` (root). The original
# `/.well-known/dev-jwks.json` registration on the prefixed router landed at
# `/api/v1/.well-known/dev-jwks.json`, which doesn't match the well-known
# convention (root-mounted, browseable by any verifier without API discovery).
well_known_router = APIRouter(tags=["Developer Signing Keys"])


@router.post("/developers/me/signing-key/rotate")
async def rotate_my_signing_key(
    current_developer: Developer = Security(get_current_developer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Generate a fresh Ed25519 signing key for the calling developer.

    Any previously-active key is marked revoked (existing signed bundles stay
    valid). The new key becomes the active one for future signatures.
    """
    key = await signing_svc.rotate_key(db, current_developer.id, reason="user_request")
    return {
        "id": key["id"],
        "public_key_jwk": key["public_key_jwk"],
        "fingerprint": key["fingerprint"],
        "rotation_seq": key["rotation_seq"],
        # private_key_pem is intentionally NOT returned (server holds it
        # — bundles are signed server-side on the dev's behalf)
    }


@router.get("/developers/me/signing-keys")
async def list_my_signing_keys(
    current_developer: Developer = Security(get_current_developer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List signing-key history for the calling developer (no private material)."""
    keys = await signing_svc.list_keys_for_dev(db, current_developer.id)
    return {"keys": keys, "total": len(keys)}


@router.get("/developers/{developer_id}/jwks.json")
async def dev_jwks(
    developer_id: Annotated[int, Path(ge=1)],
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Public JWKS endpoint for one developer.

    No auth: this is the federation-fetched endpoint that cross-registry
    bundle verifiers hit to resolve the `iss` claim in a JWS.
    """
    return await signing_svc.get_active_jwks_for_dev(db, developer_id)


@well_known_router.get("/.well-known/dev-jwks.json")
async def well_known_dev_jwks(db: AsyncSession = Depends(get_db)) -> dict:
    """Public JWKS endpoint exposing ALL active dev signing keys on this
    registry.

    Mirrors the /developers/{id}/jwks.json shape but aggregates everyone.
    Useful for batch federation cache warming. Each key carries its kid
    (fingerprint) so verifiers can pick the right one.
    """
    return await signing_svc.get_all_active_jwks(db)
