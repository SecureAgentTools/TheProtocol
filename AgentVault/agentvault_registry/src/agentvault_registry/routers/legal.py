"""Legal rails (§LEGALKIT, 2026-09-20).

  GET  /api/v1/legal/config        public: who runs this frame (provider facts as data), the suite mode,
                                   the versions and dates of the published documents
  POST /api/v1/legal/accept        developer JWT: renewed acceptance of a document at its served version
                                   (Terms § 10.2, "renewed express acceptance, for example at next login")
  GET  /api/v1/legal/acceptances   developer JWT: the account's own acceptance record (Terms § 10.3)

The frontend resolves every provider placeholder in the legal texts from `config`; nothing about the
provider is written into the shipped source any more.
"""
from __future__ import annotations

import datetime
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models, security
from ..core import provider_facts as pf
from ..core.legal_versions import (ACCEPTABLE_DOCUMENTS, DOCUMENTS_VERSION, EFFECTIVE, EFFECTIVE_LABEL,
                                   OPERATOR_TERMS_SET_VERSION, PUBLISHED, TOS_VERSION, current_version)
from ..database import get_db
from ..services.legal_acceptance import (SUBJECT_DEVELOPER, developer_acceptances, reconsent_documents,
                                         reconsent_required, record_acceptance)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/legal", tags=["Legal"])


@router.get("/config", summary="This frame's legal posture: provider facts, suite mode, document versions")
async def legal_config():
    cfg = pf.legal_config(tos_version=TOS_VERSION, documents_version=DOCUMENTS_VERSION,
                          effective=EFFECTIVE, published=PUBLISHED)
    cfg["effective_label"] = EFFECTIVE_LABEL
    cfg["documents"] = dict(ACCEPTABLE_DOCUMENTS)
    return cfg


class AcceptBody(BaseModel):
    document: str = Field("terms", max_length=32)
    version: str = Field(..., max_length=40, description="The version the person read; must be the one served now.")


@router.post("/accept", summary="Record renewed acceptance of a legal document (Terms § 10.2)")
async def accept_document(
    body: AcceptBody,
    request: Request,
    current_developer: models.Developer = Depends(security.get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    served = current_version(body.document)
    if not served:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No such document: {body.document}")
    if body.version.strip() != served:
        # The person read a version that is not the one in force. Refuse with the current one so the
        # client reloads the text; an acceptance of a stale version would be a record of nothing.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "legal_version_mismatch", "document": body.document, "served": served,
                    "message": f"The current version of {body.document} is {served}; reload and accept that."},
        )
    now = datetime.datetime.now(datetime.timezone.utc)
    await record_acceptance(db, document=body.document, subject_kind=SUBJECT_DEVELOPER,
                            subject_id=str(current_developer.id), via="login",
                            developer_id=current_developer.id, request=request, version=served)
    if body.document == "terms":
        current_developer.tos_accepted_version = served
        current_developer.tos_accepted_at = now
    await db.commit()
    logger.info("[legal] developer %s accepted %s v%s", current_developer.id, body.document, served)
    return {"accepted": True, "document": body.document, "version": served, "accepted_at": now.isoformat()}


@router.get("/acceptances", summary="The account's own acceptance record")
async def my_acceptances(
    current_developer: models.Developer = Depends(security.get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    rows = await developer_acceptances(db, current_developer.id)
    return {
        "developer_id": current_developer.id,
        "tos_accepted_version": current_developer.tos_accepted_version,
        "tos_accepted_at": current_developer.tos_accepted_at.isoformat() if current_developer.tos_accepted_at else None,
        "tos_current_version": TOS_VERSION,
        "tos_reconsent_required": reconsent_required(current_developer.tos_accepted_version, TOS_VERSION),
        "reconsent_documents": await reconsent_documents(db, current_developer, tos_version=TOS_VERSION, documents_version=OPERATOR_TERMS_SET_VERSION),
        "acceptances": [
            {"document": r.document, "version": r.version, "via": r.via, "subject_kind": r.subject_kind,
             "accepted_at": r.accepted_at.isoformat() if r.accepted_at else None}
            for r in rows
        ],
    }


async def reconsent_state(developer: models.Developer, db) -> dict:
    """The fields the profile carries so a console can ask again after a material change: the Terms stamp and, since
    V0414, the LIST of documents to accept (`reconsent_documents`), which names the Federation Operator Terms for an
    account that holds operators. `tos_reconsent_required` is true when the list is non-empty, so a console built
    before the list still asks (for the Terms) and a newer one asks for every document."""
    docs = await reconsent_documents(db, developer, tos_version=TOS_VERSION, documents_version=OPERATOR_TERMS_SET_VERSION)
    return {
        "tos_accepted_version": developer.tos_accepted_version,
        "tos_current_version": TOS_VERSION,
        "tos_reconsent_required": bool(docs),
        "reconsent_documents": docs,
    }


__all__ = ["router", "reconsent_state", "Optional"]
