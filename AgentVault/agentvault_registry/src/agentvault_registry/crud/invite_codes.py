"""
from datetime import timezone
CRUD operations for beta invite codes.
Commander generates codes via admin endpoint.
Each code is a single-use token tied to a shareable registration URL.
"""

import uuid
import datetime
import logging
from typing import List, Optional, Tuple

from sqlalchemy import select, update, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from agentvault_registry.models import InviteCode

logger = logging.getLogger(__name__)


def _generate_code() -> str:
    """Generate a formatted invite code: TP-XXXX-XXXX-XXXX-XXXX"""
    raw = uuid.uuid4().hex.upper()  # 32 hex chars
    return f"TP-{raw[0:4]}-{raw[4:8]}-{raw[8:12]}-{raw[12:16]}"


# §INVRBAC — the granular admin flags an invitation may confer, in display order.
# This is the ONLY authorization vocabulary an invite speaks. `is_admin` is deliberately
# absent: it is a blanket bypass inside require_admin_flag(), not a capability, and an
# invitation has no business handing one out.
ADMIN_FLAGS: Tuple[str, ...] = (
    "admin_platform",
    "admin_federation",
    "admin_treasury",
    "admin_enforcement",
    "admin_support",
)


def resolve_admin_flags(code_obj) -> List[str]:
    """The granular flags redeeming this code actually grants.

    ONE resolver, called by the redemption path, the API serializer and the tests alike,
    so the answer shown in the UI cannot drift from the answer applied to an account.

      * not admin-granting            -> []
      * admin-granting, flags stored  -> exactly those (unknown names dropped)
      * admin-granting, flags NULL    -> all five (row predates mig 0143; see the
                                         migration docstring for why this is the safe
                                         reading of an outstanding invitation)
    """
    if not getattr(code_obj, "grants_admin", False):
        return []
    stored = getattr(code_obj, "admin_flags", None)
    if stored:
        seen = {f for f in stored if f in ADMIN_FLAGS}
        return [f for f in ADMIN_FLAGS if f in seen]  # canonical order, deduped
    return list(ADMIN_FLAGS)


async def generate_invite_codes(
    db: AsyncSession,
    count: int,
    created_by: int,
    expires_days: Optional[int] = None,
    note: Optional[str] = None,
    max_uses: int = 1,
    grants_admin: bool = False,
    admin_flags: Optional[List[str]] = None,
) -> List[InviteCode]:
    """Generate N new invite codes and persist them.

    `grants_admin` codes confer admin capability on redemption (§OPGUIDE-3, mig 0142);
    `admin_flags` says WHICH capability (§INVRBAC, mig 0143). Both default to the
    ordinary-invitation behaviour so every existing caller is unaffected.

    A caller that asks for `grants_admin` without naming flags gets all five, which is
    what that request meant before this column existed.
    """
    if grants_admin:
        requested = [f for f in (admin_flags or []) if f in ADMIN_FLAGS]
        stored_flags = requested or list(ADMIN_FLAGS)
    else:
        # Flags without the master switch would be authority nobody confirmed.
        stored_flags = None
    expires_at = None
    if expires_days:
        expires_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=expires_days)

    codes = []
    for _ in range(count):
        code = InviteCode(
            code=_generate_code(),
            created_by=created_by,
            max_uses=max_uses,
            expires_at=expires_at,
            note=note,
            grants_admin=grants_admin,
            admin_flags=stored_flags,
        )
        db.add(code)
        codes.append(code)

    await db.commit()
    for code in codes:
        await db.refresh(code)

    logger.info(
        f"Generated {count} invite codes by developer_id={created_by}, note='{note}'"
        + (f", grants={stored_flags}" if grants_admin else "")
    )
    return codes


async def get_invite_code(db: AsyncSession, code: str) -> Optional[InviteCode]:
    """Fetch a single invite code by its string value."""
    result = await db.execute(select(InviteCode).where(InviteCode.code == code))
    return result.scalar_one_or_none()


async def validate_invite_code(
    db: AsyncSession, code: str
) -> Tuple[bool, Optional[str], Optional[InviteCode]]:
    """
    Validate an invite code.
    Returns: (is_valid, reason_if_invalid, code_object_or_None)
    """
    obj = await get_invite_code(db, code)
    if obj is None:
        return False, "not_found", None
    if not obj.is_valid:
        return False, obj.status, obj  # "used" or "expired"
    return True, None, obj


async def consume_invite_code(
    db: AsyncSession, code: str, developer_id: int
) -> bool:
    """
    Mark an invite code as used by a developer.
    Called immediately after successful developer creation.
    """
    obj = await get_invite_code(db, code)
    if obj is None:
        logger.error(f"consume_invite_code: code '{code}' not found")
        return False

    obj.use_count += 1
    if obj.used_by is None:
        obj.used_by = developer_id
        obj.used_at = datetime.datetime.now(datetime.timezone.utc)

    await db.commit()
    logger.info(f"Invite code '{code}' consumed by developer_id={developer_id}")
    return True


async def list_invite_codes(
    db: AsyncSession,
    created_by: Optional[int] = None,
    status_filter: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
) -> List[InviteCode]:
    """
    List invite codes, optionally filtered by creator or status.
    status_filter: 'active' | 'used' | 'expired' | None (all)
    """
    now = datetime.datetime.now(datetime.timezone.utc)

    # §OPGUIDE-6: eager-load the creator/redeemer so the admin listing can show WHO
    # minted a code and WHO redeemed it. Under async SQLAlchemy a lazy load outside
    # the await boundary raises MissingGreenlet, so this is required, not an
    # optimisation.
    query = (
        select(InviteCode)
        .options(selectinload(InviteCode.creator), selectinload(InviteCode.used_by_dev))
        .order_by(InviteCode.created_at.desc())
    )
    if created_by is not None:
        query = query.where(InviteCode.created_by == created_by)

    # §OPGUIDE-6: the status filter used to be applied in PYTHON, AFTER limit/offset —
    # so "show me active codes" returned the active ones among the first `limit` rows
    # rather than the first `limit` active rows, and silently under-reported once the
    # table grew past a page. `status` is a computed property but every branch of it is
    # expressible in SQL, so filter in the query and keep pagination honest.
    if status_filter == "used":
        query = query.where(InviteCode.use_count >= InviteCode.max_uses)
    elif status_filter == "expired":
        query = query.where(
            InviteCode.use_count < InviteCode.max_uses,
            InviteCode.expires_at.is_not(None),
            InviteCode.expires_at < now,
        )
    elif status_filter == "active":
        query = query.where(
            InviteCode.use_count < InviteCode.max_uses,
            or_(InviteCode.expires_at.is_(None), InviteCode.expires_at >= now),
        )

    query = query.limit(limit).offset(offset)
    result = await db.execute(query)
    return result.scalars().all()


async def delete_invite_code(db: AsyncSession, code: str) -> bool:
    """
    Revoke (delete) an unused invite code.
    Returns False if code doesn't exist or is already used.
    """
    obj = await get_invite_code(db, code)
    if obj is None:
        return False
    if obj.use_count > 0:
        logger.warning(f"Attempted to delete already-used invite code '{code}'")
        return False

    await db.delete(obj)
    await db.commit()
    logger.info(f"Invite code '{code}' revoked/deleted")
    return True
