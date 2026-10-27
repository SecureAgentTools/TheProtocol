"""§FRAMEFORM — the public frame-request intake, persisted.

    GET   /api/v1/admin/frame-requests      admin_federation
    GET   /api/v1/admin/frame-requests/{id} admin_federation
    PATCH /api/v1/admin/frame-requests/{id} admin_federation

§HELLOFRAME (2026-09-19): `approved` is the status of a SELF-HOSTED request whose applicant may download the frame
kit (routers/frame_kit.py). Approving opens a download window (`kit_approved_at`, the count back to zero) and, when
FRAME_KIT_ENABLED is on, mails the applicant a link to their frame page; approving again opens a new window. A frame we
host keeps its own path (reviewed, then provisioned from Frame Management), so approving one is refused.

**There is no public POST here on purpose.** One already exists and has for
months: `operator_self_service::request_frame` (`POST /operators/request-frame`),
which the live `FrameCommander.vue` form submits to. Its docstring said it
"records the request via email (no DB table)", and that missing table was the
actual gap: the answers arrived as prose in the Commander's inbox and had to be
re-typed into the provisioning form by hand. So that endpoint now writes a
`FrameRequest` row, and this module is only the review side of it.

Adding a second public endpoint would have been the duplicate-rail mistake the
standing rule exists to prevent: grep the routers for an existing rail BEFORE
building one. (This module briefly had one. It was wrong.)

Deliberate choices, so the next reader does not have to guess:

  * **Mainframe-only**, like operator applications: a cloud-op is a downstream
    node and does not review frame requests. Same `require_mainframe_only` gate.
  * **Nothing here provisions anything.** A human reads the row and drives the
    existing provisioning flow; the admin FE prefills that form from the row.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Security
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry import models, schemas, security
from agentvault_registry.core.mainframe_gate import require_mainframe_only
from agentvault_registry.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1",
    tags=["Frame Requests"],
    dependencies=[Depends(require_mainframe_only)],
)

# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------

@router.get("/admin/frame-requests", response_model=List[schemas.FrameRequestAdminRead],
            summary="List frame requests")
async def list_frame_requests(
    # 2026-09-13 (the form rebuild): a status the model does not know answers 422, never a silently empty list
    status_filter: Optional[Literal["pending", "reviewed", "approved", "provisioned", "rejected"]] = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    _admin: models.Developer = Security(security.require_admin_flag("admin_federation")),
):
    q = select(models.FrameRequest).order_by(models.FrameRequest.created_at.desc())
    if status_filter:
        q = q.where(models.FrameRequest.status == status_filter)
    return list((await db.execute(q.limit(limit))).scalars().all())


@router.get("/admin/frame-requests/{request_id}",
            response_model=schemas.FrameRequestAdminRead,
            summary="One frame request")
async def get_frame_request(
    request_id: str,
    db: AsyncSession = Depends(get_db),
    _admin: models.Developer = Security(security.require_admin_flag("admin_federation")),
):
    row = (await db.execute(
        select(models.FrameRequest).where(models.FrameRequest.id == request_id)
    )).scalars().first()
    if not row:
        raise HTTPException(status_code=404, detail="Frame request not found.")
    return row


@router.patch("/admin/frame-requests/{request_id}",
              response_model=schemas.FrameRequestAdminRead,
              summary="Review a frame request")
async def review_frame_request(
    request_id: str,
    body: schemas.FrameRequestUpdate,
    db: AsyncSession = Depends(get_db),
    admin: models.Developer = Security(security.require_admin_flag("admin_federation")),
):
    row = (await db.execute(
        select(models.FrameRequest).where(models.FrameRequest.id == request_id)
    )).scalars().first()
    if not row:
        raise HTTPException(status_code=404, detail="Frame request not found.")

    patch = body.model_dump(exclude_unset=True)
    if not patch:
        raise HTTPException(status_code=400, detail="Nothing to update.")
    from agentvault_registry.routers.frame_kit import frame_kit_enabled, hosting_of, send_approval_mail
    approving = patch.get("status") == "approved"
    # "approved" means "the frame kit is open to this applicant"; with the kit off it would open a window nothing shows
    # and promise a page that answers 404, so the flag governs this door as it governs the kit's own routes.
    if approving and not frame_kit_enabled():
        raise HTTPException(
            status_code=409,
            detail="Approve opens the frame kit, and this frame does not offer it (FRAME_KIT_ENABLED is off). "
                   "Mark the request reviewed instead.",
        )
    if approving and hosting_of(row) != "self":
        raise HTTPException(
            status_code=409,
            detail="Approve is for a frame its applicant runs on their own infrastructure. A frame we host is "
                   "provisioned from Frame Management and then marked provisioned.",
        )
    now = datetime.now(timezone.utc)
    for k, v in patch.items():
        setattr(row, k, v)
    if approving:
        # a new download window: from now, with the count back to zero (the last download's time stays as history)
        row.kit_approved_at = now
        row.kit_download_count = 0
    row.reviewed_by = admin.id
    row.reviewed_at = now
    await db.commit()
    await db.refresh(row)
    mailed = send_approval_mail(row) if approving else False
    logger.info("[FRAMEFORM] request %s -> %s by admin=%s%s", row.id, row.status, admin.id,
                " (kit window opened, applicant mailed)" if mailed else (" (kit window opened)" if approving else ""))
    return row
