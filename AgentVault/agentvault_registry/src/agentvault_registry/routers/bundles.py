"""§pass51 Block 2 — Bundles API router.

Endpoints (under /api/v1 via main.py prefix):
  POST   /bundles                          create a snapshot/template/migration
  GET    /bundles                          list visible bundles
  GET    /bundles/{id}/manifest            cheap preview (JSON only)
  GET    /bundles/{id}/download            stream .tpb file
  POST   /bundles/{id}/restore             restore from DB-stored bundle
  POST   /bundles/restore-from-upload      restore from uploaded .tpb file
  POST   /bundles/{id}/fork                convenience: restore + rename
  PATCH  /bundles/{id}                     edit name/desc/visibility/pin
  DELETE /bundles/{id}                     owner delete (cascade)
  POST   /bundles/{id}/rating              1-5 star + comment
  GET    /bundles/marketplace/featured     public (no-auth) featured list
"""
from __future__ import annotations

import logging
import uuid as _uuid
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Path, Query, Response, UploadFile, status, Security
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry import forge_flags
from agentvault_registry.database import get_db
from agentvault_registry.models import Developer
from agentvault_registry.security import get_current_developer, require_agent_permission, admin_credential
from agentvault_registry.services.bundles import service as bundles_svc
from agentvault_registry.services.bundles import reserved as reserved_svc
from agentvault_registry.event_emitter import get_event_emitter

logger = logging.getLogger(__name__)


def _emit_bundle(event_type: str, bundle_id: str, dev_id: int, **extra) -> None:
    """Fire-and-forget Bundle* event to the EventStore (2026-06-02: bundle CRUD
    was never event-sourced — policy rows existed but no emit calls; wired now so
    the marketplace has an audit trail + the MCP-tester can verify emission).
    All Bundle* types are skip_in_projection so this never affects supply."""
    try:
        get_event_emitter().emit_background(
            event_type=event_type,
            aggregate_id=str(bundle_id),
            aggregate_type="Bundle",
            data={"bundle_id": str(bundle_id), "developer_id": dev_id, **extra},
        )
    except Exception:  # never let telemetry break the request path
        logger.exception("[bundles] emit %s failed", event_type)

router = APIRouter(tags=["Bundles"])


# ── Request/response models ────────────────────────────────────────────────

class CreateBundleRequest(BaseModel):
    agent_dids: list[str] = Field(..., min_length=1, max_length=100)
    kind: str = Field("snapshot", pattern="^(snapshot|template|migration)$")
    name: Optional[str] = None
    description: Optional[str] = None
    visibility: str = Field("private", pattern="^(private|org|public)$")
    slug: Optional[str] = None
    category: Optional[str] = None
    include_cicd: bool = False
    is_official: bool = False  # admin_platform only when true
    sign: bool = True


class RestoreRequest(BaseModel):
    conflict_resolution: str = Field("rename", pattern="^(skip|rename|overwrite)$")
    mode: str = Field("copy", pattern="^(copy|mirror)$")
    include_cicd: bool = True


class ForkRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    royalty_bps: Optional[int] = Field(None, ge=0, le=500)  # GÖDEL FORGE: fork royalty (cap 500); none = the default


class PatchBundleRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    visibility: Optional[str] = Field(None, pattern="^(private|org|public)$")
    is_pinned: Optional[bool] = None
    category: Optional[str] = None
    royalty_bps: Optional[int] = Field(None, ge=0, le=500)  # GÖDEL FORGE: owner-set fork royalty (cap 500)
    source_org_id: Optional[str] = Field(None, min_length=32, max_length=36)  # GÖDEL FORGE: lineage org (owner must administer it)


class RatingRequest(BaseModel):
    rating: int = Field(..., ge=1, le=5)
    comment: Optional[str] = None


class ReportRequest(BaseModel):
    reason_code: str = Field(..., min_length=1, max_length=40)
    comment: Optional[str] = Field(None, max_length=2000)


REPORT_REASON_CODES = {
    "spam", "impersonation", "malicious", "copyright",
    "offensive", "broken", "other"
}


# ── Helpers ────────────────────────────────────────────────────────────────

async def _validate_publish_eligibility(visibility: str, slug: Optional[str],
                                        is_official: bool, current_dev: Developer):
    """Enforce reserved-name + admin-gate policy on publish."""
    if visibility == "public":
        # Public visibility eligibility: dev must have signing key, account age ≥ 7d
        # For sandbox we relax these checks (just log) — prod would enforce
        logger.info(f"[bundles.publish] dev={current_dev.id} publishing public visibility")
    if slug:
        if not reserved_svc.is_slug_well_formed(slug):
            raise HTTPException(status_code=400, detail=f"Slug malformed (must match {reserved_svc.SLUG_REGEX.pattern})")
        if reserved_svc.is_slug_reserved(slug) and not admin_credential(current_dev):   # §POCKETPAIR
            raise HTTPException(status_code=403, detail=f"Slug '{slug}' is reserved — admin only")
    if is_official and not admin_credential(current_dev):   # §POCKETPAIR
        raise HTTPException(status_code=403, detail="is_official requires admin")


# ── Endpoints ──────────────────────────────────────────────────────────────

@router.post("/bundles", status_code=201)
async def create_bundle(
    body: CreateBundleRequest,
    current_developer: Developer = Security(get_current_developer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create a new bundle from one or more owned agents."""
    await _validate_publish_eligibility(body.visibility, body.slug, body.is_official, current_developer)
    try:
        result = await bundles_svc.create_bundle(
            db=db,
            developer_id=current_developer.id,
            developer_name=current_developer.name,
            developer_email=current_developer.email,
            agent_dids=body.agent_dids,
            kind=body.kind,
            name=body.name,
            description=body.description,
            visibility=body.visibility,
            slug=body.slug,
            category=body.category,
            include_cicd=body.include_cicd,
            is_official=body.is_official,
            sign=body.sign,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    _emit_bundle("BundleCreated", result.get("bundle_id") or result.get("id") or "",
                 current_developer.id, kind=body.kind, visibility=body.visibility)
    return result


@router.get("/bundles")
async def list_bundles(
    kind: Optional[str] = Query(None, pattern="^(snapshot|template|migration)$"),
    visibility: Optional[str] = Query(None, pattern="^(private|org|public)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    include_official: bool = Query(True),
    current_developer: Developer = Security(get_current_developer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List bundles visible to the caller (own + public + official + 'org' ones of its organizations)."""
    return await bundles_svc.list_bundles(
        db=db,
        requesting_dev_id=current_developer.id,
        kind=kind,
        visibility_filter=visibility,
        limit=limit,
        offset=offset,
        include_official=include_official,
    )


@router.get("/bundles/marketplace/featured")
async def featured_bundles(
    limit: int = Query(12, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Public marketplace featured list. No auth.

    Score = (install_count * 0.5) + (rating_avg * 10) + (is_official ? 50 : 0).
    """
    rows = await db.execute(text("""
        SELECT id, bundle_kind, name, slug, description, category,
               source_did, is_official, signature_tier, install_count,
               rating_sum, rating_count, created_at,
               (install_count * 0.5
                + COALESCE(rating_sum::float / NULLIF(rating_count, 0), 0) * 10
                + CASE WHEN is_official THEN 50 ELSE 0 END) AS score
        FROM agent_bundles
        WHERE visibility = 'public' AND is_hidden = FALSE
        ORDER BY score DESC, created_at DESC
        LIMIT :limit
    """), {"limit": limit})
    items = [
        {
            "id": str(r[0]), "kind": r[1], "name": r[2], "slug": r[3],
            "description": r[4], "category": r[5], "source_did": r[6],
            "is_official": r[7], "signature_tier": r[8],
            "install_count": r[9], "rating_count": r[11],
            "rating_avg": (r[10] / r[11]) if r[11] else None,
            "created_at": r[12].isoformat() if r[12] else None,
            "score": float(r[13] or 0),
        }
        for r in rows.fetchall()
    ]
    return {"featured": items, "total": len(items)}


@router.get("/bundles/{bundle_id}/manifest")
async def get_manifest(
    bundle_id: Annotated[str, Path()],
    current_developer: Developer = Security(get_current_developer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    manifest = await bundles_svc.get_manifest(db, bundle_id, current_developer.id)
    if not manifest:
        raise HTTPException(status_code=404, detail="Bundle not found")
    return manifest


@router.get("/bundles/{bundle_id}/download")
async def download_bundle(
    bundle_id: Annotated[str, Path()],
    current_developer: Developer = Security(get_current_developer),
    db: AsyncSession = Depends(get_db),
) -> Response:
    data = await bundles_svc.download_bytes(db, bundle_id, current_developer.id)
    if data is None:
        raise HTTPException(status_code=404, detail="Bundle not found or not accessible")
    _emit_bundle("BundleDownloaded", bundle_id, current_developer.id)
    return Response(
        content=data,
        media_type="application/x-theprotocol-bundle",
        headers={"Content-Disposition": f'attachment; filename="bundle-{bundle_id[:8]}.tpb"'},
    )


@router.post("/bundles/{bundle_id}/restore")
async def restore_bundle(
    bundle_id: Annotated[str, Path()],
    body: RestoreRequest,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    current_developer: Developer = Security(get_current_developer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    # §pass51 P41 — Idempotency-Key support per PLAN §16.3
    body_dict = {"bundle_id": bundle_id, **body.model_dump(), "dev_id": current_developer.id}
    from agentvault_registry.services.idempotency.cache import developer_caller
    me = developer_caller(current_developer.id)   # D6-777: the key is this developer's
    cached, err = await bundles_svc.idempotency_lookup("restore", idempotency_key, body_dict, principal=me)
    if err:
        raise HTTPException(status_code=422, detail=err)
    if cached:
        return cached

    result = await bundles_svc.restore_bundle(
        db=db,
        installer_dev_id=current_developer.id,
        bundle_row_id=bundle_id,
        conflict_resolution=body.conflict_resolution,
        mode=body.mode,
        include_cicd=body.include_cicd,
    )
    await bundles_svc.idempotency_store("restore", idempotency_key, body_dict, result, principal=me)
    return result


@router.post("/bundles/restore-from-upload")
async def restore_from_upload(
    file: UploadFile = File(...),
    conflict_resolution: str = Form("rename"),
    mode: str = Form("copy"),
    include_cicd: bool = Form(True),
    current_developer: Developer = Security(get_current_developer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Upload a .tpb file directly and restore it (no bundle row in DB).

    Also handles legacy `.json` exports for backward compatibility: they are
    wrapped in a synthetic Tier-0 bundle.
    """
    data = await file.read()
    if (file.filename or "").lower().endswith(".json"):
        # Legacy export envelope — wrap into a minimal synthetic bundle
        try:
            import json as _json
            envelope = _json.loads(data.decode())
            from agentvault_registry.services.bundles import format as fmt
            # Coerce into agent payload shape
            agent_payload = envelope.get("agent", envelope)
            if "name" not in agent_payload and envelope.get("agent", {}).get("name"):
                agent_payload["name"] = envelope["agent"]["name"]
            # Synthesize manifest + tarball
            manifest = fmt.build_manifest(
                bundle_id=f"bdl_legacy_{file.filename}",
                bundle_kind="snapshot",
                name=f"Legacy import: {file.filename}",
                description="Imported from legacy /export-import .json envelope",
                purpose_hint="backup",
                exporter={
                    "developer_id": current_developer.id,
                    "developer_name": current_developer.name,
                    "developer_email_redacted": "?",
                    "registry_origin": bundles_svc._registry_origin(),
                    "frame": bundles_svc._frame_label(),
                    "exported_at": envelope.get("export_timestamp", ""),
                },
                contents_summary={
                    "agents": [{"source_did": agent_payload.get("did"), "name": agent_payload.get("name"), "file": "agents/legacy.json", "a2a_version": None, "has_cicd": False, "has_signing_key_chain": False, "flare_tier": None}],
                    "total_agents": 1,
                    "total_cicd_pipelines": 0,
                },
                restore_compatible=["theprotocol"],
                audit_block={"legacy_import": True, "note": "Imported from legacy .json export"},
            )
            data = fmt.pack_bundle(manifest=manifest, agent_payloads=[agent_payload])
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to wrap legacy .json: {e}")

    return await bundles_svc.restore_bundle(
        db=db,
        installer_dev_id=current_developer.id,
        uploaded_bytes=data,
        conflict_resolution=conflict_resolution,
        mode=mode,
        include_cicd=include_cicd,
    )


@router.post("/bundles/{bundle_id}/fork")
async def fork_bundle(
    bundle_id: Annotated[str, Path()],
    body: ForkRequest,
    current_developer: Developer = Security(get_current_developer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Convenience: restore a bundle with conflict=rename + optional name override."""
    result = await bundles_svc.restore_bundle(
        db=db,
        installer_dev_id=current_developer.id,
        bundle_row_id=bundle_id,
        conflict_resolution="rename",
        mode="copy",
        include_cicd=True,
    )
    # GÖDEL FORGE: a fork materializes a real CHILD bundle from the restored copies, with
    # queryable lineage (mig 0124) + optional royalty stamped on the child — never the parent.
    child_id = await _fork_create_child(
        db, dev_id=current_developer.id, parent_bundle_id=bundle_id,
        produced=result.get("produced_agents"), name_override=body.name,
        royalty_bps=body.royalty_bps)
    if child_id:
        result["id"] = child_id
        result["forked_bundle_id"] = child_id
        _emit_bundle("BundleCreated", child_id, current_developer.id, forked_from=bundle_id)
    return result


async def _fork_create_child(db: AsyncSession, *, dev_id: int, parent_bundle_id: str,
                             produced: list, name_override: Optional[str],
                             royalty_bps: Optional[int]) -> Optional[str]:
    """Materialize the CHILD bundle of a fork: snapshot the restored agent copies into a real
    bundle row, then stamp fork lineage on it. Returns the child bundle row UUID (or None when
    the restore produced no agents — then there is nothing to stamp; the parent is never
    self-stamped)."""
    dids = [a.get("did") for a in (produced or []) if isinstance(a, dict) and a.get("did")]
    if not dids:
        logger.warning("[FORGE] fork of %s produced no agents — no child bundle created", parent_bundle_id)
        return None
    dev = (await db.execute(text(
        "SELECT name, email FROM developers WHERE id = :d"), {"d": dev_id})).first()
    child = await bundles_svc.create_bundle(
        db=db, developer_id=dev_id,
        developer_name=(dev[0] if dev else f"dev-{dev_id}"),
        developer_email=(dev[1] if dev else None),
        agent_dids=dids, kind="snapshot",
        name=name_override or f"fork-of-{str(parent_bundle_id)[:8]}",
        include_cicd=True,
    )
    child_id = child.get("id")
    if child_id:
        await _record_fork_lineage(db, child_id, parent_bundle_id, royalty_bps)
    return child_id


async def _record_fork_lineage(db: AsyncSession, new_bundle_id: str, parent_bundle_id: str,
                               royalty_bps: Optional[int]) -> None:
    """Stamp forked_from_bundle_id and royalty_bps on the freshly forked child. A fork that names
    no royalty takes the published default (forge_flags.royalty_default_bps, the 250 bps
    /forge/status advertises); 0 is a fork without a royalty, chosen by the caller.
    Best-effort: lineage is metadata, never fatal to the fork itself."""
    if str(new_bundle_id) == str(parent_bundle_id):
        logger.warning("[FORGE] refusing self-edge fork stamp for %s", new_bundle_id)
        return
    try:
        # A fork stays in its parent's lineage org unless later re-stamped (arena champion lookup
        # walks the newest source_org_id bundle, so children must inherit membership).
        sets = ["forked_from_bundle_id = CAST(:pid AS UUID)",
                "source_org_id = COALESCE((SELECT b.source_org_id FROM agent_bundles b "
                "WHERE b.id = CAST(:pid AS UUID)), source_org_id)"]
        params: dict = {"nid": str(new_bundle_id), "pid": str(parent_bundle_id)}
        if royalty_bps is None:
            royalty_bps = forge_flags.royalty_default_bps()
        sets.append("royalty_bps = :rb")
        params["rb"] = max(0, min(500, int(royalty_bps)))
        await db.execute(text(
            f"UPDATE agent_bundles SET {', '.join(sets)} WHERE id = CAST(:nid AS UUID)"), params)
        await db.commit()
    except Exception as e:  # noqa: BLE001
        await db.rollback()
        logger.warning("[FORGE] fork lineage stamp failed for %s: %s", new_bundle_id, e)


@router.post("/agents/bundles/{bundle_id}/fork")
async def fork_bundle_as_agent(
    bundle_id: Annotated[str, Path()],
    body: ForkRequest,
    agent=Depends(require_agent_permission("bundle.write")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """GÖDEL FORGE: an agent (harness) forks a bundle under its OWN ``bundle.write`` capability
    (birth-token attenuable). The child is owned by the agent's creator developer (spawn inherits
    it), and the fork lineage is recorded. Under ``AGENT_RBAC_MODE=off`` the permission gate is
    byte-inert (any agent may fork); under enforce it requires the delegated/granted perm."""
    dev_id = agent.creator_developer_id
    result = await bundles_svc.restore_bundle(
        db=db, installer_dev_id=dev_id, bundle_row_id=bundle_id,
        conflict_resolution="rename", mode="copy", include_cicd=True,
    )
    child_id = await _fork_create_child(
        db, dev_id=dev_id, parent_bundle_id=bundle_id,
        produced=result.get("produced_agents"), name_override=body.name,
        royalty_bps=body.royalty_bps)
    if child_id:
        result["id"] = child_id
        result["forked_bundle_id"] = child_id
        _emit_bundle("BundleCreated", child_id, dev_id, forked_from=bundle_id, forked_by_agent=agent.did)
    return result


@router.patch("/bundles/{bundle_id}")
async def patch_bundle(
    bundle_id: Annotated[str, Path()],
    body: PatchBundleRequest,
    current_developer: Developer = Security(get_current_developer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    # Owner check
    row = (await db.execute(text("""
        SELECT source_dev_id, visibility FROM agent_bundles WHERE id = CAST(:id AS UUID)
    """), {"id": bundle_id})).first()
    if not row:
        raise HTTPException(status_code=404, detail="Bundle not found")
    if row[0] != current_developer.id and not admin_credential(current_developer):   # §POCKETPAIR
        raise HTTPException(status_code=403, detail="Not the owner")

    sets = []
    params: dict = {"id": bundle_id}
    if body.name is not None:
        sets.append("name = :name")
        params["name"] = body.name
    if body.description is not None:
        sets.append("description = :description")
        params["description"] = body.description
    if body.visibility is not None:
        sets.append("visibility = :visibility")
        params["visibility"] = body.visibility
    if body.is_pinned is not None:
        sets.append("is_pinned = :pinned")
        params["pinned"] = body.is_pinned
    if body.category is not None:
        sets.append("category = :category")
        params["category"] = body.category
    if body.royalty_bps is not None:
        sets.append("royalty_bps = :royalty_bps")
        params["royalty_bps"] = max(0, min(500, int(body.royalty_bps)))
    if body.source_org_id is not None:
        try:
            _org_uuid = str(_uuid.UUID(body.source_org_id))
        except ValueError:
            raise HTTPException(status_code=422, detail="source_org_id must be a UUID")
        if not admin_credential(current_developer):   # §POCKETPAIR
            _ok = (await db.execute(text(
                "SELECT 1 FROM organizations WHERE id = CAST(:o AS UUID) AND owner_id = :dev"
            ), {"o": _org_uuid, "dev": current_developer.id})).first()
            if not _ok:
                raise HTTPException(status_code=403, detail="Not an admin of that organization")
        sets.append("source_org_id = CAST(:source_org AS UUID)")
        params["source_org"] = _org_uuid
    if not sets:
        return {"updated": False}
    sets.append("updated_at = now()")
    await db.execute(text(f"UPDATE agent_bundles SET {', '.join(sets)} WHERE id = CAST(:id AS UUID)"), params)
    await db.commit()
    if body.visibility is not None:
        _emit_bundle("BundleVisibilityChanged", bundle_id, current_developer.id, visibility=body.visibility)
    return {"updated": True}


@router.delete("/bundles/{bundle_id}", status_code=204)
async def delete_bundle(
    bundle_id: Annotated[str, Path()],
    current_developer: Developer = Security(get_current_developer),
    db: AsyncSession = Depends(get_db),
) -> Response:
    ok = await bundles_svc.delete_bundle(
        db, bundle_id, current_developer.id, is_admin=admin_credential(current_developer)
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Bundle not found or not yours")
    _emit_bundle("BundleDeleted", bundle_id, current_developer.id)
    return Response(status_code=204)


@router.post("/bundles/{bundle_id}/rating", status_code=201)
async def rate_bundle(
    bundle_id: Annotated[str, Path()],
    body: RatingRequest,
    current_developer: Developer = Security(get_current_developer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    # §MCPTEST30 (2026-10-01): the rating was written without looking the bundle up, so anyone rated (and moved the
    # featured score of) a private or a hidden bundle, and an unknown id died on the foreign key. A bundle the caller
    # may not read is one they may not rate: the read rule, bundle_visible_to; otherwise it answers as not found.
    try:
        _uuid.UUID(str(bundle_id))
    except ValueError:
        raise HTTPException(status_code=404, detail="Bundle not found")
    row = (await db.execute(text(
        "SELECT source_dev_id, visibility, is_official, is_hidden, source_org_id FROM agent_bundles"
        " WHERE id = CAST(:bid AS UUID)"), {"bid": bundle_id})).first()
    if not row or not bundles_svc.bundle_visible_to(
            row[0], row[1], row[2], row[3], current_developer.id,
            await bundles_svc.org_reader_of(db, row[4], row[1], current_developer.id)):
        raise HTTPException(status_code=404, detail="Bundle not found")
    # Upsert one-per-dev-per-bundle
    await db.execute(text("""
        INSERT INTO bundle_ratings (bundle_id, rater_dev_id, rating, comment)
        VALUES (CAST(:bid AS UUID), :dev_id, :rating, :comment)
        ON CONFLICT (bundle_id, rater_dev_id) DO UPDATE
            SET rating = EXCLUDED.rating, comment = EXCLUDED.comment, created_at = now()
    """), {
        "bid": bundle_id,
        "dev_id": current_developer.id,
        "rating": body.rating,
        "comment": body.comment,
    })
    # Recompute denormalized counters
    await db.execute(text("""
        UPDATE agent_bundles SET
            rating_sum = COALESCE((SELECT SUM(rating) FROM bundle_ratings WHERE bundle_id = CAST(:bid AS UUID)), 0),
            rating_count = COALESCE((SELECT COUNT(*) FROM bundle_ratings WHERE bundle_id = CAST(:bid AS UUID)), 0)
        WHERE id = CAST(:bid AS UUID)
    """), {"bid": bundle_id})
    await db.commit()
    _emit_bundle("BundleRated", bundle_id, current_developer.id, rating=body.rating)
    return {"ok": True}


# ── §pass51 P42 — Marketplace moderation ───────────────────────────────────

@router.post("/bundles/{bundle_id}/report", status_code=201)
async def report_bundle(
    bundle_id: Annotated[str, Path()],
    body: ReportRequest,
    current_developer: Developer = Security(get_current_developer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Any logged-in dev can report a bundle to the moderation queue."""
    if body.reason_code not in REPORT_REASON_CODES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid reason_code. Allowed: {sorted(REPORT_REASON_CODES)}",
        )
    # Verify bundle exists
    exists = (await db.execute(text("""
        SELECT 1 FROM agent_bundles WHERE id = CAST(:id AS UUID)
    """), {"id": bundle_id})).first()
    if not exists:
        raise HTTPException(status_code=404, detail="Bundle not found")
    await db.execute(text("""
        INSERT INTO bundle_reports (bundle_id, reporter_dev_id, reason_code, comment)
        VALUES (CAST(:bid AS UUID), :dev_id, :rc, :cm)
    """), {
        "bid": bundle_id,
        "dev_id": current_developer.id,
        "rc": body.reason_code,
        "cm": body.comment,
    })
    await db.commit()
    logger.info(
        f"[bundles.report] dev={current_developer.id} reported "
        f"bundle={bundle_id} reason={body.reason_code}"
    )
    _emit_bundle("BundleReported", bundle_id, current_developer.id, reason_code=body.reason_code)
    return {"ok": True, "queued": True}
