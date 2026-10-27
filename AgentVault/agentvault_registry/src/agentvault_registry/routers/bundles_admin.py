"""§pass51 P42 — Bundle moderation admin endpoints.

  GET    /admin/bundles/reports         — list open + recent reports
  POST   /admin/bundles/{id}/hide       — soft-hide (is_hidden=true)
  POST   /admin/bundles/{id}/unhide     — restore visibility
  POST   /admin/bundles/reports/{id}/dismiss   — close report without action
  PATCH  /admin/developers/{id}/quota   — bump per-dev quota (P43)

All gated by admin_enforcement (moderation) or admin_platform (quota).
"""
from __future__ import annotations

import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Security
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry import security
from agentvault_registry.database import get_db
from agentvault_registry.models import Developer

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Admin — Bundles Moderation"])


# ── Models ─────────────────────────────────────────────────────────────────

class HideRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=500)


class DismissRequest(BaseModel):
    resolution: str = Field(..., min_length=1, max_length=40)
    note: Optional[str] = Field(None, max_length=500)


class QuotaPatchRequest(BaseModel):
    max_bundle_count: Optional[int] = Field(None, ge=0, le=100000)
    max_bundle_total_bytes: Optional[int] = Field(None, ge=0)
    max_individual_bundle_bytes: Optional[int] = Field(None, ge=0)
    bundle_create_rate_per_day: Optional[int] = Field(None, ge=0, le=10000)
    custom_quota_reason: Optional[str] = Field(None, max_length=500)


# ── Moderation endpoints (admin_enforcement) ───────────────────────────────

@router.get("/admin/bundles/reports")
async def list_reports(
    status_filter: str = "open",  # open | resolved | all
    limit: int = 50,
    offset: int = 0,
    _admin: Developer = Security(security.require_admin_flag("admin_enforcement")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List bundle reports queue. status_filter: open|resolved|all."""
    where = []
    if status_filter == "open":
        where.append("br.resolved_at IS NULL")
    elif status_filter == "resolved":
        where.append("br.resolved_at IS NOT NULL")
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    sql = f"""
        SELECT br.id, br.bundle_id, br.reporter_dev_id, br.reason_code, br.comment,
               br.resolved_at, br.resolution, br.resolved_by_dev_id, br.created_at,
               ab.name AS bundle_name, ab.slug AS bundle_slug, ab.visibility,
               ab.is_official, ab.is_hidden, ab.source_dev_id,
               d.email AS reporter_email
        FROM bundle_reports br
        LEFT JOIN agent_bundles ab ON ab.id = br.bundle_id
        LEFT JOIN developers d ON d.id = br.reporter_dev_id
        {where_sql}
        ORDER BY br.created_at DESC
        LIMIT :limit OFFSET :offset
    """
    rows = await db.execute(text(sql), {"limit": limit, "offset": offset})
    items = [
        {
            "id": r[0],
            "bundle_id": str(r[1]),
            "reporter_dev_id": r[2],
            "reporter_email": r[14],
            "reason_code": r[3],
            "comment": r[4],
            "resolved_at": r[5].isoformat() if r[5] else None,
            "resolution": r[6],
            "resolved_by_dev_id": r[7],
            "created_at": r[8].isoformat() if r[8] else None,
            "bundle": {
                "name": r[9],
                "slug": r[10],
                "visibility": r[11],
                "is_official": r[12],
                "is_hidden": r[13],
                "source_dev_id": r[15],
            },
        }
        for r in rows.fetchall()
    ]
    # Open-queue summary
    summary = (await db.execute(text("""
        SELECT COUNT(*) FILTER (WHERE resolved_at IS NULL) AS open,
               COUNT(*) FILTER (WHERE resolved_at IS NOT NULL) AS resolved,
               COUNT(*) AS total
        FROM bundle_reports
    """))).first()
    return {
        "reports": items,
        "summary": {
            "open": summary[0] if summary else 0,
            "resolved": summary[1] if summary else 0,
            "total": summary[2] if summary else 0,
        },
        "limit": limit,
        "offset": offset,
    }


@router.post("/admin/bundles/{bundle_id}/hide")
async def hide_bundle(
    bundle_id: Annotated[str, Path()],
    body: HideRequest,
    current_admin: Developer = Security(security.require_admin_flag("admin_enforcement")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Soft-hide a bundle: excluded from list endpoints + marketplace, still
    resolvable by direct link. Reversible via /unhide."""
    row = (await db.execute(text("""
        SELECT name, is_hidden FROM agent_bundles WHERE id = CAST(:id AS UUID)
    """), {"id": bundle_id})).first()
    if not row:
        raise HTTPException(status_code=404, detail="Bundle not found")
    if row[1]:
        return {"ok": True, "already_hidden": True, "name": row[0]}
    await db.execute(text("""
        UPDATE agent_bundles SET is_hidden = TRUE, updated_at = now()
        WHERE id = CAST(:id AS UUID)
    """), {"id": bundle_id})
    # Mark any open reports for this bundle as resolved with this hide as resolution
    await db.execute(text("""
        UPDATE bundle_reports
        SET resolved_at = now(),
            resolved_by_dev_id = :dev_id,
            resolution = :resolution
        WHERE bundle_id = CAST(:id AS UUID) AND resolved_at IS NULL
    """), {
        "id": bundle_id,
        "dev_id": current_admin.id,
        "resolution": f"hidden: {body.reason}"[:40],
    })
    await db.commit()
    logger.warning(
        f"[bundles.moderation] admin={current_admin.id} HID bundle={bundle_id} "
        f"name={row[0]} reason={body.reason}"
    )
    return {"ok": True, "hidden": True, "name": row[0]}


@router.post("/admin/bundles/{bundle_id}/unhide")
async def unhide_bundle(
    bundle_id: Annotated[str, Path()],
    current_admin: Developer = Security(security.require_admin_flag("admin_enforcement")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = (await db.execute(text("""
        SELECT name, is_hidden FROM agent_bundles WHERE id = CAST(:id AS UUID)
    """), {"id": bundle_id})).first()
    if not row:
        raise HTTPException(status_code=404, detail="Bundle not found")
    if not row[1]:
        return {"ok": True, "already_visible": True, "name": row[0]}
    await db.execute(text("""
        UPDATE agent_bundles SET is_hidden = FALSE, updated_at = now()
        WHERE id = CAST(:id AS UUID)
    """), {"id": bundle_id})
    await db.commit()
    logger.info(
        f"[bundles.moderation] admin={current_admin.id} UNHID bundle={bundle_id} "
        f"name={row[0]}"
    )
    return {"ok": True, "unhidden": True, "name": row[0]}


@router.post("/admin/bundles/reports/{report_id}/dismiss")
async def dismiss_report(
    report_id: Annotated[int, Path()],
    body: DismissRequest,
    current_admin: Developer = Security(security.require_admin_flag("admin_enforcement")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = (await db.execute(text("""
        SELECT resolved_at FROM bundle_reports WHERE id = :id
    """), {"id": report_id})).first()
    if not row:
        raise HTTPException(status_code=404, detail="Report not found")
    if row[0]:
        return {"ok": True, "already_resolved": True}
    await db.execute(text("""
        UPDATE bundle_reports SET
            resolved_at = now(),
            resolved_by_dev_id = :dev_id,
            resolution = :resolution
        WHERE id = :id
    """), {
        "id": report_id,
        "dev_id": current_admin.id,
        "resolution": body.resolution[:40],
    })
    await db.commit()
    logger.info(
        f"[bundles.moderation] admin={current_admin.id} dismissed report={report_id} "
        f"resolution={body.resolution}"
    )
    return {"ok": True, "dismissed": True}


# ── Per-dev quota admin (admin_platform — P43) ─────────────────────────────

@router.get("/admin/developers/{developer_id}/quota")
async def get_dev_quota(
    developer_id: Annotated[int, Path(ge=1)],
    _admin: Developer = Security(security.require_admin_flag("admin_platform")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = (await db.execute(text("""
        SELECT max_bundle_count, max_bundle_total_bytes, max_individual_bundle_bytes,
               bundle_create_rate_per_day, custom_quota_reason, updated_at
        FROM developer_quotas WHERE developer_id = :id
    """), {"id": developer_id})).first()
    if not row:
        # Return defaults (matches migration 0075 defaults)
        return {
            "developer_id": developer_id,
            "max_bundle_count": 100,
            "max_bundle_total_bytes": 1073741824,
            "max_individual_bundle_bytes": 104857600,
            "bundle_create_rate_per_day": 10,
            "custom_quota_reason": None,
            "is_default": True,
        }
    # Current usage
    usage = (await db.execute(text("""
        SELECT COUNT(*) AS count, COALESCE(SUM(bundle_size_bytes), 0) AS total_bytes
        FROM agent_bundles WHERE source_dev_id = :id
    """), {"id": developer_id})).first()
    return {
        "developer_id": developer_id,
        "max_bundle_count": row[0],
        "max_bundle_total_bytes": row[1],
        "max_individual_bundle_bytes": row[2],
        "bundle_create_rate_per_day": row[3],
        "custom_quota_reason": row[4],
        "updated_at": row[5].isoformat() if row[5] else None,
        "is_default": False,
        "current_usage": {
            "bundle_count": usage[0] if usage else 0,
            "total_bytes": usage[1] if usage else 0,
        },
    }


@router.patch("/admin/developers/{developer_id}/quota")
async def patch_dev_quota(
    developer_id: Annotated[int, Path(ge=1)],
    body: QuotaPatchRequest,
    current_admin: Developer = Security(security.require_admin_flag("admin_platform")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    # UPSERT — if no row yet, insert with provided values + defaults for the rest
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        return {"updated": False, "reason": "no fields provided"}

    existing = (await db.execute(text("""
        SELECT developer_id FROM developer_quotas WHERE developer_id = :id
    """), {"id": developer_id})).first()
    if existing:
        sets = []
        params = {"id": developer_id}
        for k, v in fields.items():
            sets.append(f"{k} = :{k}")
            params[k] = v
        sets.append("updated_at = now()")
        await db.execute(
            text(f"UPDATE developer_quotas SET {', '.join(sets)} WHERE developer_id = :id"),
            params,
        )
    else:
        cols = ["developer_id"] + list(fields.keys())
        placeholders = [":id"] + [f":{k}" for k in fields.keys()]
        params = {"id": developer_id, **fields}
        await db.execute(
            text(f"INSERT INTO developer_quotas ({', '.join(cols)}) VALUES ({', '.join(placeholders)})"),
            params,
        )
    await db.commit()
    logger.info(
        f"[bundles.quota] admin={current_admin.id} patched quota for dev={developer_id}: {fields}"
    )
    return {"updated": True, "fields": list(fields.keys())}
