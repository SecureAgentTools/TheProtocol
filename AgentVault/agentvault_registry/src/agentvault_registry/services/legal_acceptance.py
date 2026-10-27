"""Recording and checking legal acceptances (§LEGALKIT, migration 0181).

One writer for every rail that asks a person to accept a document, so the record has one shape:
who (developer id when known), what (subject kind + id), which document at which SERVED version, how
(via), from where (the same evidence the security audit keeps). The `developers.tos_accepted_*`
columns stay the fast path for the Terms and are written together with the row.
"""
from __future__ import annotations

import datetime
import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models
from ..core.client_ip import effective_client_ip
from ..core.legal_versions import current_version

logger = logging.getLogger(__name__)

SUBJECT_DEVELOPER = "developer"
SUBJECT_OPERATOR_APPLICATION = "operator_application"
SUBJECT_FRAME_REQUEST = "frame_request"
SUBJECT_CHECKOUT = "checkout"


def _ua(request) -> Optional[str]:
    try:
        ua = request.headers.get("user-agent") if request is not None else None
    except Exception:
        ua = None
    return (ua or "")[:255] or None


def _ip(request) -> Optional[str]:
    try:
        return effective_client_ip(request) if request is not None else None
    except Exception:
        return None


async def record_acceptance(
    db: AsyncSession,
    *,
    document: str,
    subject_kind: str,
    subject_id: Optional[str],
    via: str,
    developer_id: Optional[int] = None,
    request=None,
    version: Optional[str] = None,
    commit: bool = False,
    accepted_at: Optional[datetime.datetime] = None,
    user_agent: Optional[str] = None,
) -> models.LegalAcceptance:
    """Write one acceptance row. `version` defaults to the version the server serves NOW.

    The caller owns the transaction unless `commit=True`; a rail that already commits its own row
    (registration, a frame request) adds this in the same transaction so the two cannot disagree.
    `accepted_at` and `user_agent` are for a rail with no request: the frame kit's standup, where the person accepted
    in frame-up.py before the registry existed (operator_seed records it with the first admin).
    """
    served = version or current_version(document)
    if not served:
        raise ValueError(f"unknown legal document {document!r}")
    row = models.LegalAcceptance(
        developer_id=developer_id,
        subject_kind=subject_kind,
        subject_id=str(subject_id) if subject_id is not None else None,
        document=document,
        version=served,
        via=via,
        accepted_at=accepted_at or datetime.datetime.now(datetime.timezone.utc),
        source_ip=_ip(request),
        user_agent=(user_agent or "")[:255] or _ua(request),
    )
    db.add(row)
    if commit:
        await db.commit()
    else:
        await db.flush()
    return row


def reconsent_required(accepted_version: Optional[str], current: Optional[str]) -> bool:
    """Terms § 10.2: after a material change the platform asks again at the next login.

    True when the account holds no acceptance at all (older accounts predate the stamp) or holds an
    older version than the one served now. A newer-than-current value (a rolled-back frame) does not ask.
    """
    if not current:
        return False
    if not accepted_version:
        return True
    if _looks_like_a_date(accepted_version):
        # The pre-v2 stamp was a date ("2026-07-09"), which predates every numbered version: ask.
        return True
    return _version_key(accepted_version) < _version_key(current)


def _looks_like_a_date(v: str) -> bool:
    head = (v or "").split(".")[0].split("-")[0]
    return head.isdigit() and int(head) >= 1000


def _version_key(v: str) -> tuple:
    parts = []
    for p in (v or "").replace("-", ".").split("."):
        parts.append((0, int(p)) if p.isdigit() else (1, p))
    return tuple(parts)


OPERATOR_BOUND_STATUSES = ("approved", "provisioned", "active", "activated", "pending", "submitted", "in_review")


async def holds_operator_relationship(db: AsyncSession, developer_id: int) -> bool:
    """True when the developer is bound by the Federation Operator Terms: an operator application or a frame request
    of theirs that is not rejected or withdrawn (measured 2026-09-20: every running operator's owner on EU and ASIA had
    accepted the Terms and never the operator document, because only the frame-request rail records it)."""
    from sqlalchemy import or_
    q = select(models.OperatorApplication.id).where(models.OperatorApplication.developer_id == developer_id,
                                                    models.OperatorApplication.status.in_(OPERATOR_BOUND_STATUSES)).limit(1)
    if (await db.execute(q)).scalar() is not None:
        return True
    q = select(models.FrameRequest.id).where(models.FrameRequest.developer_id == developer_id,
                                             models.FrameRequest.status.in_(OPERATOR_BOUND_STATUSES)).limit(1)
    return (await db.execute(q)).scalar() is not None


async def has_accepted(db: AsyncSession, developer_id: int, document: str, version: str) -> bool:
    q = select(models.LegalAcceptance.id).where(models.LegalAcceptance.developer_id == developer_id,
                                                models.LegalAcceptance.document == document,
                                                models.LegalAcceptance.version == version).limit(1)
    return (await db.execute(q)).scalar() is not None


async def reconsent_documents(db: AsyncSession, developer: models.Developer, *, tos_version: str,
                              documents_version: str) -> list[str]:
    """The documents this account must accept now, in the order the console shows them: `terms` when the Terms moved
    past the accepted stamp (Terms § 10.2); `operators` when the account holds an operator relationship and no
    acceptance of the Federation Operator Terms at the served version exists. A developer without operators is never
    asked for the operator document."""
    out: list[str] = []
    if reconsent_required(developer.tos_accepted_version, tos_version):
        out.append("terms")
    if documents_version and await holds_operator_relationship(db, developer.id):
        if not await has_accepted(db, developer.id, "operators", documents_version):
            out.append("operators")
    return out


async def developer_acceptances(db: AsyncSession, developer_id: int, limit: int = 100) -> list[models.LegalAcceptance]:
    res = await db.execute(
        select(models.LegalAcceptance)
        .where(models.LegalAcceptance.developer_id == developer_id)
        .order_by(models.LegalAcceptance.accepted_at.desc())
        .limit(limit)
    )
    return list(res.scalars().all())
