"""§F6 WP6.2 slice 2 (2026-09-26, his words "continue with wp6.2 slice 2 on the sandbox pair"): a peer frame asks THIS
frame to purge its own copies of one of the PEER's cloud operators.

  POST /api/v1/federation/operators/{operator}/purge-rows      (peer frames only, over the mTLS federation address)

A purge teardown used to run psql DELETEs inside every frame's database from the operator's home frame (by default the
legacy Frame A/B/C containers, whatever frame was purging): a cross-frame state change outside every rail, and a name
match that could hit another frame's operator of the same name. Here each frame deletes only its OWN rows, and only the
rows that belong to the caller:

  - the caller is a peer REGISTRY identity (mTLS, `require_peer_registry_identity`) whose trust domain is an ACTIVE
    peer FRAME of this one, and not this frame's own;
  - a row is the caller's operator only when its name is one of the operator's name forms AND its trust_domain is the
    CALLER's (an operator shares its parent's trust domain, so another frame's operator of the same name never matches)
    AND it is an operator or discovered row, never a frame.

Deleting (not deactivating) is the purge's contract: a deleted peer row lets the card GC remove its mirrored cards.
"""
import logging
import os
import re
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry import models
from agentvault_registry.core.federation_auth import require_peer_registry_identity
from agentvault_registry.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/federation", tags=["federation-operator-purge"])

OPERATOR_NAME_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,40}[a-z0-9]")
PURGEABLE_PEER_TYPES = ("cloud_operator", "discovered")


def caller_trust_domain(spiffe_id: str) -> str:
    """The trust domain of a SPIFFE id ('' when it is not one)."""
    sid = (spiffe_id or "").strip().lower()
    if not sid.startswith("spiffe://"):
        return ""
    return sid[len("spiffe://"):].split("/", 1)[0]


def operator_name_forms(name: str) -> list:
    """Every name shape the operator's rows have carried (the legacy purge's anchored forms, RP6 2026-07-24)."""
    return sorted({name, f"op-{name}", f"cloud-op-{name}", f"cloud-op-op-{name}"})


@router.post("/operators/{operator}/purge-rows", summary="Purge this frame's rows of a peer frame's operator")
async def purge_operator_rows(
    operator: str = Path(..., min_length=2, max_length=42),
    peer_spiffe: str = Depends(require_peer_registry_identity),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    name = operator.strip().lower()
    if not OPERATOR_NAME_RE.fullmatch(name):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="operator: not an operator name")
    td = caller_trust_domain(peer_spiffe)
    own = (os.getenv("SPIRE_TRUST_DOMAIN") or "").strip().lower()
    if not td or td == own:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="only a peer frame asks this frame to purge its rows")
    frame = (await db.execute(
        select(models.PeerRegistry).where(
            func.lower(models.PeerRegistry.trust_domain) == td,
            models.PeerRegistry.peer_type == "frame",
            models.PeerRegistry.status == "ACTIVE",
        )
    )).scalars().first()
    if frame is None:
        logger.warning("[federation-purge] refused: %s is not an ACTIVE peer frame (operator %s)", peer_spiffe, name)
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="the caller is not an ACTIVE peer frame of this frame")
    rows = (await db.execute(
        select(models.PeerRegistry).where(
            func.lower(models.PeerRegistry.name).in_(operator_name_forms(name)),
            func.lower(models.PeerRegistry.trust_domain) == td,
            models.PeerRegistry.peer_type.in_(PURGEABLE_PEER_TYPES),
        )
    )).scalars().all()
    deleted = []
    for row in rows:
        deleted.append({"id": row.id, "name": row.name, "peer_type": row.peer_type})
        await db.delete(row)
    await db.commit()
    logger.info("[federation-purge] %s purged %d row(s) of its operator %s: %s", frame.name, len(deleted), name,
                [d["name"] for d in deleted])
    return {"operator": name, "trust_domain": td, "peer_frame": frame.name, "deleted": len(deleted), "rows": deleted}
