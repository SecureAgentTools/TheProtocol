"""
Beta Access Request System — "Request Beta Access" flow

Endpoints:
  POST /api/v1/beta/request-access   — Submit email for delayed invite
  GET  /api/v1/beta/status            — Check unlock time + countdown
  GET  /api/v1/beta/test-unlock       — Admin override for testing (requires ?key=)

Background task:
  Every 5 minutes, finds pending requests older than 30 min,
  generates invite codes, sends emails.

Unlock time: 2026-03-20 17:00:00 UTC (Friday 6PM Berlin/CET)
"""
import logging
import os
import secrets
import re
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db_context
from ..config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/beta", tags=["Beta Access"])

# ── Unlock time: Friday 2026-03-20 18:00 Berlin (CET = UTC+1) = 17:00 UTC
UNLOCK_UTC = datetime(2026, 3, 20, 17, 0, 0, tzinfo=timezone.utc)

# Admin test key (for pre-launch testing)
TEST_KEY = os.environ.get("BETA_TEST_KEY", "")

# Disposable email domain blocklist (basic)
DISPOSABLE_DOMAINS = {
    "mailinator.com", "guerrillamail.com", "tempmail.com", "throwaway.email",
    "yopmail.com", "10minutemail.com", "trashmail.com", "fakeinbox.com",
}


class BetaAccessRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=200)


class BetaAccessResponse(BaseModel):
    status: str
    message: str


def _is_unlocked() -> bool:
    return datetime.now(timezone.utc) >= UNLOCK_UTC


def _validate_email(email: str) -> Optional[str]:
    """Returns error message or None if valid."""
    email = email.strip().lower()
    if not re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", email):
        return "Invalid email format"
    domain = email.split("@")[1]
    if domain in DISPOSABLE_DOMAINS:
        return "Disposable email addresses are not accepted"
    return None


def _generate_invite_code() -> str:
    """Generate TP-XXXX-XXXX-XXXX-XXXX format invite code."""
    parts = [secrets.token_hex(2).upper() for _ in range(4)]
    return f"TP-{parts[0]}-{parts[1]}-{parts[2]}-{parts[3]}"


# ── Endpoints ──────────────────────────────────────────────────────────────

@router.get("/status")
async def beta_status():
    """Returns unlock time and whether beta access requests are open."""
    now = datetime.now(timezone.utc)
    unlocked = now >= UNLOCK_UTC
    remaining_seconds = max(0, int((UNLOCK_UTC - now).total_seconds())) if not unlocked else 0

    return {
        "unlocked": unlocked,
        "unlock_utc": UNLOCK_UTC.isoformat(),
        "unlock_berlin": "2026-03-20T18:00:00+01:00",
        "remaining_seconds": remaining_seconds,
        "message": "Beta access requests are open!" if unlocked else f"Opens in {remaining_seconds} seconds",
    }


@router.post("/request-access", response_model=BetaAccessResponse)
async def request_beta_access(req: BetaAccessRequest):
    """Submit email to request beta access. Auto-sends invite after 30 min delay."""
    # Check if unlocked (or test mode)
    if not _is_unlocked():
        raise HTTPException(
            status_code=403,
            detail=f"Beta access requests open on Friday March 20, 2026 at 6:00 PM (Berlin time)"
        )

    email = req.email.strip().lower()

    # Validate email
    err = _validate_email(email)
    if err:
        raise HTTPException(status_code=400, detail=err)

    async with get_db_context() as db:
        # Check if already requested
        result = await db.execute(
            text("SELECT status FROM beta_access_requests WHERE email = :email"),
            {"email": email}
        )
        existing = result.fetchone()
        if existing:
            status = existing[0]
            if status == "sent":
                return BetaAccessResponse(
                    status="already_sent",
                    message="An invite has already been sent to this email. Check your inbox (and spam folder)."
                )
            return BetaAccessResponse(
                status="pending",
                message="Your request is already being processed. You'll receive an invite within 1 hour."
            )

        # Check if email already has an account
        result2 = await db.execute(
            text("SELECT id FROM developers WHERE email = :email"),
            {"email": email}
        )
        if result2.fetchone():
            return BetaAccessResponse(
                status="already_registered",
                message="This email already has a TheProtocol account. Log in directly."
            )

        # Insert request
        await db.execute(
            text("""
                INSERT INTO beta_access_requests (email, status, requested_at)
                VALUES (:email, 'pending', :now)
                ON CONFLICT (email) DO NOTHING
            """),
            {"email": email, "now": datetime.now(timezone.utc)}
        )
        await db.commit()

    logger.info(f"[Beta] Access request from {email}")

    return BetaAccessResponse(
        status="pending",
        message="Your request is being reviewed. You'll receive an invite code via email within 1 hour."
    )


@router.get("/test-unlock")
async def test_unlock(key: str = Query(...)):
    """Admin test endpoint — process a pending request immediately."""
    if key != TEST_KEY:
        raise HTTPException(status_code=403, detail="Invalid test key")

    processed = await _process_pending_requests(force=True)
    return {"processed": processed, "message": f"Force-processed {processed} pending requests"}


# ── Background Task ────────────────────────────────────────────────────────

async def _process_pending_requests(force: bool = False) -> int:
    """Find pending requests older than 30 min, generate invites, send emails."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)
    if force:
        cutoff = datetime.now(timezone.utc) + timedelta(hours=1)  # Process everything

    processed = 0

    async with get_db_context() as db:
        result = await db.execute(
            text("""
                SELECT id, email FROM beta_access_requests
                WHERE status = 'pending' AND requested_at < :cutoff
                ORDER BY requested_at ASC
                LIMIT 20
            """),
            {"cutoff": cutoff}
        )
        rows = result.fetchall()

        for row in rows:
            req_id, email = row
            try:
                # Generate invite code
                code = _generate_invite_code()

                # Insert into invite_codes table
                await db.execute(
                    text("""
                        INSERT INTO invite_codes (code, created_by, max_uses, use_count, note, created_at)
                        VALUES (:code, 1, 1, 0, :note, :now)
                    """),
                    {
                        "code": code,
                        "note": f"Beta access auto-invite for {email}",
                        "now": datetime.now(timezone.utc),
                    }
                )

                # Send email
                invite_url = f"https://registry.theprotocol.cloud/register?invite={code}"
                await _send_invite_email(email, code, invite_url)

                # Update request status
                await db.execute(
                    text("""
                        UPDATE beta_access_requests
                        SET status = 'sent', invite_code = :code, sent_at = :now
                        WHERE id = :id
                    """),
                    {"code": code, "now": datetime.now(timezone.utc), "id": req_id}
                )

                await db.commit()
                processed += 1
                logger.info(f"[Beta] Invite sent to {email}: {code}")

            except Exception as e:
                logger.error(f"[Beta] Failed to process request for {email}: {e}")
                await db.rollback()

    return processed


async def _send_invite_email(email: str, code: str, invite_url: str):
    """Send the themed beta-invite email via the unified email pipeline."""
    from agentvault_registry.email_utils import deployment_identity, send_themed_email
    sent = await send_themed_email(
        subject=f"Your Beta Access to {deployment_identity()['registry_name']}",
        recipients=[email],
        template="beta_invite",
        context={"code": code, "invite_url": invite_url},
        theme="neural",
    )
    if not sent:
        logger.error(f"[Beta] Invite email send failed for {email}")
        # Don't raise — invite code is still created, user can request resend


# ── Background worker (called from main.py startup) ───────────────────────

async def beta_access_worker():
    """Background task: process pending beta access requests every 5 minutes."""
    import asyncio
    from agentvault_registry.background_tasks.leader import try_acquire_leadership
    logger.info("[Beta] Background worker started (5-minute cycle)")
    await asyncio.sleep(60)  # Initial delay

    while True:
        try:
            if not os.environ.get("BETA_INVITE_REQUIRED", "false").lower() in ("true", "1", "yes"):
                await asyncio.sleep(3600)
                continue
            if await try_acquire_leadership("beta_access_worker") and _is_unlocked():
                processed = await _process_pending_requests()
                if processed > 0:
                    logger.info(f"[Beta] Processed {processed} pending requests")
        except Exception as e:
            logger.error(f"[Beta] Worker error: {e}")

        await asyncio.sleep(300)  # 5 minutes
