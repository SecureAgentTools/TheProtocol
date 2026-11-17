"""V0663 (order gwo_01681f32a8cfe7390b773532, his suggestion 6): GET /api/v1/admin/chat/federation/delivery, the admins'
delivery panel: per peer, what waits in the chat federation outbox, with a verdict (services/chat_delivery), behind
admin_federation (the console's one admin rule reads it from the routes).

V0664 (order gwo_efdd53bd198423a5ec2b742d): the panel acts on one stuck row, behind the same flag:
  GET  /api/v1/admin/chat/federation/delivery/rows?peer=     a peer's rows still to deliver, each with its state
  POST /api/v1/admin/chat/federation/delivery/rows/{id}/retry  its next attempt now (a given-up row: one more try)
  POST /api/v1/admin/chat/federation/delivery/rows/{id}/drop   {reason}: it stops, who and why kept, an audit row
A refusal answers its status with {"code", "detail"}."""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, Query, Security
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from agentvault_registry import database
from agentvault_registry.security import require_admin_flag
from agentvault_registry.services import chat_delivery

router = APIRouter(tags=["Admin"])
_ADMIN = require_admin_flag("admin_federation")


@router.get("/api/v1/admin/chat/federation/delivery",
            summary="Chat delivery to each peer: what waits, since when, the latest error, the last delivery")
async def chat_federation_delivery(admin=Security(_ADMIN), db=Depends(database.get_db)):
    now = dt.datetime.now(dt.timezone.utc)
    return {"enabled": chat_delivery.federation_enabled(), "as_of": now.isoformat(),
            "late_seconds": chat_delivery.late_seconds(), "max_attempts": chat_delivery.max_attempts(),
            "peers": await chat_delivery.delivery_by_peer(db, now=now), "worker": await chat_delivery.worker_stats()}


class DropIn(BaseModel):
    reason: str = Field(..., min_length=1, max_length=chat_delivery.MAX_REASON)


async def _run(step):
    try:
        return await step
    except chat_delivery.DeliveryRefusal as r:
        return JSONResponse(status_code=r.status, content={"code": r.code, "detail": r.sentence})


@router.get("/api/v1/admin/chat/federation/delivery/rows",
            summary="A peer's chat outbox rows still to deliver, each with its state and what an admin may do with it")
async def chat_federation_delivery_rows(peer: str = Query(..., max_length=500), limit: int = Query(50, ge=1, le=200),
                                        admin=Security(_ADMIN), db=Depends(database.get_db)):
    now = chat_delivery.db_now()
    rows = chat_delivery.row_states(await chat_delivery.peer_rows(db, peer, limit), now=now)
    return {"peer_base_url": peer, "as_of": now.isoformat(), "max_attempts": chat_delivery.max_attempts(),
            "rows": [chat_delivery.row_view(r) for r in rows]}


@router.post("/api/v1/admin/chat/federation/delivery/rows/{row_id}/retry",
             summary="Retry one stuck chat outbox row now (a given-up row gets one more try)")
async def chat_federation_delivery_retry(row_id: str, admin=Security(_ADMIN), db=Depends(database.get_db)):
    return await _run(chat_delivery.retry_row(db, row_id, actor_id=getattr(admin, "id", None)))


@router.post("/api/v1/admin/chat/federation/delivery/rows/{row_id}/drop",
             summary="Drop one stuck chat outbox row with a reason (kept on the row and audited; the message stays)")
async def chat_federation_delivery_drop(row_id: str, body: DropIn, admin=Security(_ADMIN), db=Depends(database.get_db)):
    return await _run(chat_delivery.drop_row(db, row_id, actor_id=getattr(admin, "id", None), reason=body.reason))
