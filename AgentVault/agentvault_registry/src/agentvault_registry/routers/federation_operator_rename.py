"""Cross-frame operator-rename apply endpoint (§2026-06-14).

The event-sourced operator IDENTITY rename's peer-side receiver. When an op is
re-slugged on its home frame, `reactor_operator_renamed` fans the change out to
each ACTIVE peer frame by POSTing here (Mode-2 federation auth, same pattern as
the blocklist proxy `federation_blocklist.py`). Each peer applies the rename to
ITS OWN local derived rows (peer_registries + agent_cards origin) via
`apply_operator_rename_local` — never reaching across to another frame's DB.

Idempotent (replays are no-ops once the rows are at the new slug). This is how
the rename converges B/C without direct cross-frame SQL — the audit lives in the
`OperatorRenamed` event on the home frame + this endpoint's logs.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Security
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.federation_auth import get_federation_identity
from ..database import get_db
from ..services.operator_rename_apply import apply_operator_rename_local

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/federation/admin/operators",
    tags=["Federation Operator Rename"],
)


class OperatorRenameApplyBody(BaseModel):
    old_slug: str = Field(..., min_length=1, max_length=64)
    new_slug: str = Field(..., min_length=1, max_length=64)
    new_base_url: Optional[str] = Field(None, max_length=300)
    new_operator_did: Optional[str] = Field(None, max_length=255)
    actor: str = Field("home_frame_reactor", max_length=200)


@router.post("/rename", include_in_schema=False)
async def federation_apply_operator_rename(
    body: OperatorRenameApplyBody,
    federation_identity: str = Security(get_federation_identity),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Apply an operator rename to THIS frame's local rows on behalf of the
    op's home frame. Mode-2 federation auth required. Idempotent."""
    logger.info(
        "[FedOpRename] apply from %s : %s → %s",
        federation_identity[:80], body.old_slug, body.new_slug,
    )
    result = await apply_operator_rename_local(
        db,
        old_slug=body.old_slug,
        new_slug=body.new_slug,
        new_base_url=body.new_base_url,
        new_operator_did=body.new_operator_did,
        actor=f"federation:{federation_identity[:60]}|{body.actor}",
    )
    return {"status": "applied", "federation_identity": federation_identity, **result}
