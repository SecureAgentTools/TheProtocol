"""Registry Card v0.3 — admin CRUD.

Routes (all gated by admin_platform sub-flag):
  GET  /api/v1/admin/registry-card                  — preview current card + derived blocks
  PUT  /api/v1/admin/registry-card                  — operator-editable subset
  POST /api/v1/admin/registry-card/icon             — multipart icon upload (≤500KB, PNG/JPEG)
  POST /api/v1/admin/registry-signing-key/rotate    — mint new EdDSA key, mark old expires_at = NOW()+7d
  GET  /api/v1/admin/peer-registries/{id}/card      — view a federated peer's cached card

Per spec §3 field-tier table: Pydantic RegistryCardOperatorPut enforces
extra='forbid' so LOCKED fields cannot be sneaked into the PUT body.
"""
import datetime
import hashlib
import io
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Security, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models, schemas, security
from ..core.image_sniff import sniff_image_format  # §DEPS: imghdr is gone in Python 3.13
from ..database import get_db
from ..event_emitter import get_event_emitter
from ..services.registry_card_builder import (
    _build_spiffe_id,
    build_registry_card,
    card_asset_slug,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["Registry Card v0.3 — Admin"])

# Icon storage — same-origin to defeat XSS-via-arbitrary-host vector.
# Path written into the runtime static dir so /static/registry-cards/... serves it.
_ICON_MAX_BYTES = 500 * 1024  # 500 KB cap per spec.
_ICON_ALLOWED_FORMATS = {"png", "jpeg", "jpg"}


def _card_slug() -> str:
    """URL-SAFE directory slug for this registry's card assets.

    ONE definition, in the builder beside `_build_spiffe_id` that produces it —
    the serve path and the stored URL must be derived from the same function or
    they drift on rename (the 2026-07-29 hetzner 404 burst). Kept as an alias
    because this module's upload handlers read naturally with the short name.
    """
    return card_asset_slug()


def _icon_dir() -> Path:
    """static/registry-cards/<spiffe-slug>/ — created on demand.

    NOTE this resolves INSIDE the built frontend (STATIC_DIR = .../new_registry_frontend/dist),
    so anything written here is destroyed by a container recreate AND by an image rebuild.
    Treat it as a CACHE: `_persist_asset` below is the durable copy, and
    `rehydrate_card_assets()` restores this directory at startup. (§HETZNERLOCK-14: for months
    the file here was the only copy, so operators' logos silently vanished on every roll.)
    """
    from ..main import STATIC_DIR  # late import to avoid circular at module load
    p = STATIC_DIR / "registry-cards" / _card_slug()
    p.mkdir(parents=True, exist_ok=True)
    return p


async def _persist_asset(
    db: AsyncSession, kind: str, raw: bytes, ext: str, fmt: str, digest: str, developer_id: Optional[int]
) -> None:
    """Upsert the asset BYTES so a recreate/rebuild can no longer lose them."""
    mime = "image/png" if fmt == "png" else "image/jpeg"
    row = (await db.execute(
        select(models.RegistryCardAsset).where(models.RegistryCardAsset.kind == kind)
    )).scalar_one_or_none()
    if row is None:
        db.add(models.RegistryCardAsset(
            kind=kind, content=raw, mime=mime, ext=ext, sha256=digest,
            size_bytes=len(raw), updated_by=developer_id,
        ))
    else:
        row.content = raw
        row.mime = mime
        row.ext = ext
        row.sha256 = digest
        row.size_bytes = len(raw)
        row.updated_at = datetime.datetime.now(datetime.timezone.utc)
        row.updated_by = developer_id


async def rehydrate_card_assets(db: AsyncSession) -> int:
    """Write DB-held card assets back to the static dir. Called once at startup.

    Idempotent and content-addressed: an asset already on disk with the same sha256 is
    left alone, so this is a no-op on a warm container. Never raises — a missing logo
    must not stop a registry from booting.
    """
    restored = 0
    try:
        rows = (await db.execute(select(models.RegistryCardAsset))).scalars().all()
        if not rows:
            return 0
        d = _icon_dir()
        for r in rows:
            try:
                target = d / f"{r.kind}.{r.ext}"
                if target.exists():
                    import hashlib as _h
                    if _h.sha256(target.read_bytes()).hexdigest() == r.sha256:
                        continue  # already correct on disk
                target.write_bytes(r.content)
                restored += 1
                logger.info("[RegistryCardAssets] rehydrated %s (%d bytes) -> %s", r.kind, r.size_bytes, target)
            except Exception as e:
                logger.warning("[RegistryCardAssets] could not rehydrate %s: %s", r.kind, e)
    except Exception as e:
        # Table may not exist yet on a registry whose migration has not run — not fatal.
        logger.warning("[RegistryCardAssets] rehydrate skipped: %s", e)
    return restored


@router.get("/registry-card", summary="View current registry card")
async def get_registry_card_admin(
    db: AsyncSession = Depends(get_db),
    _admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
) -> Dict[str, Any]:
    """Returns the full v0.3 card (live-derived blocks included).

    Same payload as the public /.well-known/registry-card.json, served via the
    admin path for the editor UI. include_internal=True so the editor/ops view
    also sees non-public fields (e.g. raw identity.software_version).
    """
    return await build_registry_card(db, sign=True, include_internal=True)


_NESTED_CARD_BLOCKS = ("operator", "visual", "links", "commitments")


def merge_operator_card_patch(existing: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    """Patch-merge an operator PUT onto the stored card_json.

    Top-level keys replace; the four nested operator-editable blocks DEEP-merge, so a partial
    PUT does not wipe sibling keys (audit B3).

    🔴 THIS IS WHAT KEEPS THE LOGO. `visual.icon_url` / `icon_etag` / `icon_size_bytes` are
    written ONLY by the icon-upload route, and the card editor's save sends the ten visual
    fields it owns and never those three. Replacing the block instead of merging it would
    therefore delete an uploaded logo on the next unrelated save — a colour tweak would silently
    cost the operator their mark, and nothing would report it. Pinned by
    `tests/test_registry_card_put_keeps_icon.py`; extracted from the route body 2026-09-08 so the
    invariant can be tested without a database, after the Commander asked for a way to save the
    card "without removing the existing set logo".

    `exclude_none=False` upstream is deliberate: a null INSIDE a sent block still clears that one
    field, so a value can be unset on purpose. A block that is not sent at all is left alone.
    """
    out = dict(existing)
    for k, v in payload.items():
        if v is None:
            continue
        if k in _NESTED_CARD_BLOCKS and isinstance(v, dict) and isinstance(out.get(k), dict):
            merged = dict(out[k])
            merged.update(v)
            out[k] = merged
        else:
            out[k] = v
    return out


@router.put("/registry-card", summary="Update operator-editable subset of the card")
async def put_registry_card_admin(
    body: schemas.RegistryCardOperatorPut,
    db: AsyncSession = Depends(get_db),
    current_developer: models.Developer = Security(security.require_admin_flag("admin_platform")),
) -> Dict[str, Any]:
    """Writes operator-editable fields to the singleton row.

    Defense in depth: Pydantic `extra='forbid'` on RegistryCardOperatorPut
    rejects any LOCKED field even if smuggled in. Server still re-applies
    SOVEREIGN_VISUAL_PINS at next serve, so even if visual.* is written for a
    sovereign-pinned SPIFFE, the pin overrides at read time.
    """
    # v0.3.1: validate flare encirclement + overlay against catalogs at PUT
    # time so the editor sees an immediate 422 rather than silently writing
    # an invalid value that only the federation_sync receiver would reject.
    if body.visual is not None:
        from ..core.registry_identity import (
            is_valid_encirclement_variant,
            is_valid_encirclement_overlay,
            is_valid_corner_variant,
        )
        enc = body.visual.flare_encirclement_variant
        ov = body.visual.flare_encirclement_overlay
        corner = body.visual.flare_corner_variant
        if enc is not None and not is_valid_encirclement_variant(enc):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"flare_encirclement_variant={enc!r} not in catalog (see core/registry_identity.py:FLARE_ENCIRCLEMENT_VARIANTS).",
            )
        if ov is not None and not is_valid_encirclement_overlay(ov):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"flare_encirclement_overlay={ov!r} not in catalog (see core/registry_identity.py:FLARE_ENCIRCLEMENT_OVERLAYS).",
            )
        if ov is not None and enc is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="flare_encirclement_overlay requires flare_encirclement_variant to be set first.",
            )
        if corner is not None and not is_valid_corner_variant(corner):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"flare_corner_variant={corner!r} not in catalog.",
            )
        # §pass78c (2026-06-05) — VANITY IS SHAREABLE (Commander directive).
        # sovereign_variant is self-determined vanity any registry may equip; it is
        # NOT SPIFFE-locked to one owner and may be shared. We only validate that it's
        # a KNOWN renderable style (so the globe has defined styling to draw) — an
        # unknown string is rejected here / soft-stripped on receive. Identity/trust is
        # SPIFFE + signature, never the orb, so shared vanity is spoof-safe.
        sv = body.visual.sovereign_variant
        if sv is not None:
            from ..core.registry_identity import is_known_sovereign_variant
            if not is_known_sovereign_variant(sv):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        f"sovereign_variant={sv!r} is not a known vanity style; "
                        f"choose one of the published sovereign variants."
                    ),
                )

    row = (await db.execute(
        select(models.RegistryCard).where(models.RegistryCard.id == 1)
    )).scalar_one_or_none()

    # Patch-style merge. Top-level keys replace; nested operator-editable blocks
    # (operator/visual/links/commitments) DEEP-merge so a partial PUT doesn't wipe
    # sibling keys (audit B3). exclude_none=False keeps explicit nulls so a field
    # CAN be cleared within a sent block.
    existing = merge_operator_card_patch(
        dict(row.card_json) if row and isinstance(row.card_json, dict) else {},
        body.model_dump(exclude_unset=True, exclude_none=False),
    )

    if row is None:
        row = models.RegistryCard(
            id=1, card_json=existing, card_etag="", updated_by=current_developer.id,
        )
        db.add(row)
    else:
        row.card_json = existing
        row.updated_at = datetime.datetime.now(datetime.timezone.utc)
        row.updated_by = current_developer.id

    # Flush so build_registry_card (same session) sees the new card_json, then
    # persist the AUTHORITATIVE operator-edits-only serve etag (audit B5 — the
    # column now drives the well-known 304 short-circuit).
    await db.flush()
    full_card = await build_registry_card(db, sign=True, include_internal=True)
    full_etag = full_card.get("lifecycle", {}).get("card_etag", "")
    row.card_etag = full_etag
    await db.commit()

    # Emit ETag-only event (Commander decision 2026-05-21 — spec §0 row 3).
    try:
        emitter = get_event_emitter()
        await emitter.emit_event(
            aggregate_id=full_card["identity"]["spiffe_id"],
            event_type="RegistryCardUpdated",
            event_data={
                "spiffe_id":  full_card["identity"]["spiffe_id"],
                "card_etag":  full_etag,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                "updated_by": current_developer.id,
            },
        )
    except Exception as e:
        logger.warning("[RegistryCardAdmin] emit RegistryCardUpdated failed: %s", e)

    return full_card


@router.post("/registry-card/icon", summary="Upload icon for this registry card")
async def upload_registry_card_icon(
    file: UploadFile = File(..., description="PNG or JPEG, ≤500 KB."),
    db: AsyncSession = Depends(get_db),
    current_developer: models.Developer = Security(security.require_admin_flag("admin_platform")),
) -> Dict[str, Any]:
    """Stores icon in static/registry-cards/<spiffe-slug>/icon.<ext> + DB BLOB backup.

    Same-origin enforced: returned URL is always on this registry's host. SVG
    rejected (XSS via inline scripts) per spec brainstorm §3.
    """
    raw = await file.read()
    if len(raw) > _ICON_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Icon exceeds 500 KB cap (got {len(raw)} bytes).",
        )

    fmt = sniff_image_format(raw)
    if fmt not in _ICON_ALLOWED_FORMATS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Icon must be PNG or JPEG (detected: {fmt!r}). SVG rejected for XSS safety.",
        )

    # Write to disk for cheap static serving.
    icon_dir = _icon_dir()
    ext = "png" if fmt == "png" else "jpg"
    icon_path = icon_dir / f"icon.{ext}"
    icon_path.write_bytes(raw)

    digest = hashlib.sha256(raw).hexdigest()
    icon_etag = f"sha256:{digest[:32]}"
    public_url = f"/static/registry-cards/{_card_slug()}/icon.{ext}"

    # Durable copy — the file above is only a serving cache (see _icon_dir).
    await _persist_asset(db, "icon", raw, ext, fmt, digest, current_developer.id)

    # Splice into the operator-editable visual block.
    row = (await db.execute(
        select(models.RegistryCard).where(models.RegistryCard.id == 1)
    )).scalar_one_or_none()
    existing = dict(row.card_json) if row and isinstance(row.card_json, dict) else {}
    visual = dict(existing.get("visual") or {})
    visual["icon_url"] = public_url
    visual["icon_etag"] = icon_etag
    visual["icon_size_bytes"] = len(raw)
    existing["visual"] = visual

    if row is None:
        row = models.RegistryCard(
            id=1, card_json=existing,
            card_etag="sha256:" + digest,  # placeholder; rebuilt on next serve
            updated_by=current_developer.id,
        )
        db.add(row)
    else:
        row.card_json = existing
        row.updated_at = datetime.datetime.now(datetime.timezone.utc)
        row.updated_by = current_developer.id

    await db.commit()
    return {
        "icon_url":        public_url,
        "icon_etag":       icon_etag,
        "icon_size_bytes": len(raw),
        "format":          fmt,
    }


@router.post("/registry-card/avatar", summary="Upload operator avatar (same-origin)")
async def upload_registry_card_avatar(
    file: UploadFile = File(..., description="PNG or JPEG, ≤500 KB."),
    db: AsyncSession = Depends(get_db),
    current_developer: models.Developer = Security(security.require_admin_flag("admin_platform")),
) -> Dict[str, Any]:
    """v0.4 — same-origin operator avatar (replaces external hotlinks that rot).
    Stored at static/registry-cards/<slug>/avatar.<ext>; URL written into
    operator.operator_avatar_url. SVG rejected (XSS safety)."""
    raw = await file.read()
    if len(raw) > _ICON_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Avatar exceeds 500 KB cap (got {len(raw)} bytes).",
        )
    fmt = sniff_image_format(raw)
    if fmt not in _ICON_ALLOWED_FORMATS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Avatar must be PNG or JPEG (detected: {fmt!r}). SVG rejected for XSS safety.",
        )
    icon_dir = _icon_dir()
    ext = "png" if fmt == "png" else "jpg"
    (icon_dir / f"avatar.{ext}").write_bytes(raw)
    public_url = f"/static/registry-cards/{_card_slug()}/avatar.{ext}"

    # Durable copy — same reason as the icon: the file is a cache, not storage.
    await _persist_asset(
        db, "avatar", raw, ext, fmt, hashlib.sha256(raw).hexdigest(), current_developer.id
    )

    row = (await db.execute(
        select(models.RegistryCard).where(models.RegistryCard.id == 1)
    )).scalar_one_or_none()
    existing = dict(row.card_json) if row and isinstance(row.card_json, dict) else {}
    operator = dict(existing.get("operator") or {})
    operator["operator_avatar_url"] = public_url
    existing["operator"] = operator
    if row is None:
        row = models.RegistryCard(id=1, card_json=existing, card_etag="", updated_by=current_developer.id)
        db.add(row)
    else:
        row.card_json = existing
        row.updated_at = datetime.datetime.now(datetime.timezone.utc)
        row.updated_by = current_developer.id
    await db.commit()
    return {"operator_avatar_url": public_url, "avatar_size_bytes": len(raw), "format": fmt}


@router.post("/registry-signing-key/rotate", summary="Create a new signing key, expire current")
async def rotate_registry_signing_key(
    db: AsyncSession = Depends(get_db),
    current_developer: models.Developer = Security(security.require_admin_flag("admin_platform")),
) -> Dict[str, Any]:
    """Creates a new EdDSA keypair, increments rotation_seq, marks old expires_at = NOW()+7d.

    Live — wired via registry_card_keystore.rotate_signing_key; returns 501 only if the
    keystore module is missing from this build.
    """
    try:
        from ..services.registry_card_keystore import rotate_signing_key  # Phase 6
    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Registry signing-key rotation wires in Phase 6 (registry_card_keystore).",
        )

    spiffe_id = _build_spiffe_id()
    new_row = await rotate_signing_key(db, spiffe_id, grace_days=7)
    await db.commit()
    return {
        "registry_spiffe_id": new_row.registry_spiffe_id,
        "rotation_seq":       new_row.rotation_seq,
        "algorithm":          new_row.algorithm,
        "created_at":         new_row.created_at.isoformat(),
    }


@router.get("/peer-registries/{peer_id}/card", summary="View a federated peer's cached card")
async def get_peer_registry_card(
    peer_id: int,
    db: AsyncSession = Depends(get_db),
    _admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
) -> Dict[str, Any]:
    peer = (await db.execute(
        select(models.PeerRegistry).where(models.PeerRegistry.id == peer_id)
    )).scalar_one_or_none()
    if peer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Peer registry id={peer_id} not found.")
    return {
        "peer_id":                  peer.id,
        "peer_name":                peer.name,
        "peer_base_url":            peer.base_url,
        "card_etag":                peer.card_etag,
        "card_last_pulled_at":      peer.card_last_pulled_at.isoformat() if peer.card_last_pulled_at else None,
        "card_signature_verified":  peer.card_signature_verified,
        "card_signature_kid":       peer.card_signature_kid,
        "cached_registry_card":     peer.cached_registry_card,
    }
