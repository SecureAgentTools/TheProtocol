"""PUSH LOGIN (2026-07-25) — approve a sign-in from your phone with a fingerprint.

A second factor that is faster to use than a TOTP code and strictly stronger than one. The
password is verified as usual; instead of asking for six digits, the account's enrolled phone
receives a push and the human approves it with the same WebAuthn user-verification the Cockpit
Card uses. The browser being signed into never handles a secret, and the approval is bound to a
challenge so it cannot be replayed.

Why it is stronger than TOTP: a TOTP code is a shared secret that can be read over someone's
shoulder, phished into a fake page, or handed over by a person being socially engineered. A
WebAuthn assertion is bound to the origin, requires the OS to verify a human, and cannot be
relayed to a different site. The phone shows WHAT is being approved (IP, device) before signing.

Opt-in per developer (`push_login_enabled`, default false). Existing 2FA is untouched: this is an
additional route to the same door, never a replacement for the locks already on it.
"""
import datetime as _dt
import logging
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry import models, security
from agentvault_registry.config import settings
from agentvault_registry.database import get_db
from agentvault_registry.security import get_current_developer
from agentvault_registry.services import liability as liab

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/auth/push-login", tags=["Push Login"])

TTL_SECONDS = 120


def _now():
    return _dt.datetime.now(_dt.timezone.utc)


class RequestIn(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=255)


class ApproveIn(BaseModel):
    device_id: int
    credential_id: Optional[str] = None
    authenticator_data: str
    client_data_json: str
    signature: str


async def create_approval_for_login(db: AsyncSession, dev, request: Request,
                                    suppress_push: bool = False) -> Optional[dict]:
    """Create one sign-in approval, pushing only when another device actually has to act.

    `suppress_push` is set when the signing-in browser says it holds a credential itself: pushing
    a notification to the very phone that is about to approve locally produced a stream of alerts
    for approvals that were already consumed by the time they were tapped (Commander-found).

    Returns None when the account has no device that can verify a human, so the caller can fall
    back to its normal factors instead of locking someone out."""
    row = (await db.execute(text(
        "SELECT id FROM device_push_registrations WHERE developer_id = :d AND enabled "
        "AND webauthn_credential_id IS NOT NULL AND key_revoked_at IS NULL ORDER BY id LIMIT 1"
    ), {"d": dev.id})).first()
    if not row:
        return None

    nonce = secrets.token_hex(16)
    ip = (request.client.host if request and request.client else "") or ""
    ua = ((request.headers.get("user-agent") if request else "") or "")[:255]

    # One live request PER REQUESTER. Retrying from the same browser must collapse into a single
    # live approval (otherwise a tapped notification opens a dead one), but expiring every pending
    # row for the account was too broad: a second, unrelated sign-in killed the first device's
    # approval three seconds after it was raised, and that device then waited forever on a request
    # nothing could ever approve. Found by the E2E harness when the simulation — which logs in as
    # this same account — silently stole the desktop's pending approval.
    await db.execute(text(
        "UPDATE login_approvals SET status='expired', resolved_at=now() "
        "WHERE developer_id = :d AND status = 'pending' "
        "AND COALESCE(requested_ip,'') = :ip AND COALESCE(requested_ua,'') = :ua"),
        {"d": dev.id, "ip": ip, "ua": ua})
    facts = {"purpose": "sign-in", "developer_id": dev.id, "ip": ip, "user_agent": ua[:80]}
    approval_id = liab.new_id("lgn")
    await db.execute(text("""
        INSERT INTO login_approvals (id, developer_id, challenge_hash, nonce, status,
                                     requested_ip, requested_ua, expires_at)
        VALUES (:i, :d, :c, :n, 'pending', :ip, :ua, :exp)
    """), {"i": approval_id, "d": dev.id, "c": liab.challenge_hash_for(facts, nonce), "n": nonce,
           "ip": ip, "ua": ua, "exp": _now() + _dt.timedelta(seconds=TTL_SECONDS)})
    await db.commit()

    if suppress_push:
        # The requesting browser will raise its own biometric prompt; nothing to notify.
        return {"approval_id": approval_id, "expires_in": TTL_SECONDS, "pushed": False}

    try:
        # §NOTIFV2: security.login_approval is MANDATORY in the catalog — the resolver
        # short-circuits before any preference/mute/quiet-hour logic, because a user who
        # mutes this locks themselves out.
        from agentvault_registry.background_tasks.push_notify import notify
        base = str(getattr(settings, "PUSH_APP_BASE_URL", "") or getattr(settings, "BASE_URL", "") or "").rstrip("/")
        await notify("security.login_approval", [dev.id], title="Approve sign-in",
                     message=f"Sign-in from {ip or 'an unknown address'} — approve with your fingerprint",
                     tags="closed_lock_with_key", priority="high",
                     click=f"{base}/ui/#/pocket/approve-login?id={approval_id}" if base else None)
    except Exception:
        logger.warning("[PUSHLOGIN] notify failed for approval=%s", approval_id, exc_info=True)

    return {"approval_id": approval_id, "expires_in": TTL_SECONDS, "pushed": True}


@router.post("/request", summary="Password verified: ask the phone to approve this sign-in")
async def request_push_login(body: RequestIn, request: Request, db: AsyncSession = Depends(get_db)):
    """Deliberately uniform failure: whatever is wrong (no such account, wrong password, feature
    off, no enrolled phone) the caller gets the same answer, so this endpoint cannot be used to
    enumerate accounts or discover who has a phone enrolled."""
    generic = {"available": False, "detail": "Push approval is not available for this account."}
    row = (await db.execute(text(
        "SELECT id, hashed_password, push_login_enabled, is_suspended FROM developers WHERE email = :e"
    ), {"e": body.email.lower().strip()})).first()
    if not row:
        return generic
    dev_id, hashed, enabled, suspended = row
    if not hashed or not security.verify_password(body.password, hashed):
        return generic
    if not enabled or suspended:
        return generic
    # a phone that can actually verify a human — no enrolled credential, no push login
    dev_row = (await db.execute(text(
        "SELECT id FROM device_push_registrations WHERE developer_id = :d AND enabled "
        "AND webauthn_credential_id IS NOT NULL AND key_revoked_at IS NULL ORDER BY id LIMIT 1"
    ), {"d": dev_id})).first()
    if not dev_row:
        return generic

    approval = await create_approval_for_login(db, await db.get(models.Developer, dev_id), request)
    if not approval:
        return generic
    approval_id = approval["approval_id"]

    return {"available": True, "approval_id": approval_id, "expires_in": TTL_SECONDS}


@router.get("/{approval_id}/status", summary="Poll the approval (called by the signing-in browser)")
async def approval_status(approval_id: str, db: AsyncSession = Depends(get_db)):
    row = (await db.execute(text(
        "SELECT status, expires_at FROM login_approvals WHERE id = :i"), {"i": approval_id})).first()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Unknown approval")
    st, exp = row
    if st == "pending" and exp <= _now():
        await db.execute(text("UPDATE login_approvals SET status='expired', resolved_at=now() "
                              "WHERE id=:i AND status='pending'"), {"i": approval_id})
        await db.commit()
        st = "expired"
    return {"status": st}


@router.get("/{approval_id}/detail", summary="What is being approved (phone-side)")
async def approval_detail(approval_id: str,
                          dev: models.Developer = Depends(get_current_developer),
                          db: AsyncSession = Depends(get_db)):
    row = (await db.execute(text(
        "SELECT developer_id, challenge_hash, status, requested_ip, requested_ua, expires_at "
        "FROM login_approvals WHERE id = :i"), {"i": approval_id})).mappings().first()
    if not row or row["developer_id"] != dev.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Unknown approval")
    return dict(row)


@router.post("/{approval_id}/approve", summary="Approve with the phone's biometric")
async def approve_login(approval_id: str, body: ApproveIn, request: Request,
                        dev: models.Developer = Depends(get_current_developer),
                        db: AsyncSession = Depends(get_db)):
    row = (await db.execute(text(
        "SELECT developer_id, challenge_hash, status, expires_at FROM login_approvals WHERE id = :i"
    ), {"i": approval_id})).first()
    if not row or row[0] != dev.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Unknown approval")
    if row[2] != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"Approval is {row[2]}")
    if row[3] <= _now():
        await db.execute(text("UPDATE login_approvals SET status='expired', resolved_at=now() WHERE id=:i"),
                         {"i": approval_id})
        await db.commit()
        raise HTTPException(status.HTTP_410_GONE, detail="Approval expired")

    drow = await db.get(models.DevicePushRegistration, body.device_id)
    if not drow or drow.developer_id != dev.id or not drow.webauthn_public_key or drow.key_revoked_at:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Device cannot approve sign-ins")

    from agentvault_registry.services import webauthn as wa
    from agentvault_registry.routers.liability import _rp_id_candidates
    ok, reason, sign_count = wa.verify_assertion(
        cose_public_key_b64u=drow.webauthn_public_key,
        client_data_json_b64u=body.client_data_json,
        authenticator_data_b64u=body.authenticator_data,
        signature_b64u=body.signature,
        expected_challenge_b64u=liab.b64u_from_hex(row[1]),
        expected_rp_ids=_rp_id_candidates(request),
        require_uv=True,          # a sign-in approval without a verified human is worthless
    )
    if not ok:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=f"Biometric verification failed ({reason})")

    await db.execute(text(
        "UPDATE login_approvals SET status='approved', method='webauthn_uv', device_id=:dv, "
        "resolved_at=now() WHERE id=:i AND status='pending'"), {"dv": drow.id, "i": approval_id})
    if sign_count:
        await db.execute(text("UPDATE device_push_registrations SET webauthn_sign_count=:c WHERE id=:i"),
                         {"c": sign_count, "i": drow.id})
    await db.commit()
    return {"ok": True, "status": "approved", "method": "webauthn_uv"}


class DirectApproveIn(BaseModel):
    credential_id: Optional[str] = None
    authenticator_data: str
    client_data_json: str
    signature: str


@router.get("/{approval_id}/challenge", summary="What to sign (no session required)")
async def approval_challenge(approval_id: str, db: AsyncSession = Depends(get_db)):
    """Unauthenticated by necessity: the device approving may be the very device trying to log in,
    which has no session yet. Safe to expose: the challenge is a hash, and signing it requires
    the enrolled authenticator AND a verified human. The approval id is unguessable and expires
    in two minutes."""
    row = (await db.execute(text(
        "SELECT developer_id, challenge_hash, status, requested_ip, expires_at "
        "FROM login_approvals WHERE id = :i"), {"i": approval_id})).mappings().first()
    if not row or row["status"] != "pending" or row["expires_at"] <= _now():
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Unknown or expired approval")
    creds = (await db.execute(text(
        "SELECT webauthn_credential_id FROM device_push_registrations WHERE developer_id = :d "
        "AND enabled AND webauthn_credential_id IS NOT NULL AND key_revoked_at IS NULL"
    ), {"d": row["developer_id"]})).scalars().all()
    return {"challenge_hash": row["challenge_hash"], "credential_ids": list(creds),
            "requested_ip": row["requested_ip"], "expires_at": row["expires_at"]}


@router.post("/{approval_id}/approve-direct",
             summary="Approve with a biometric assertion, no session required")
async def approve_login_direct(approval_id: str, body: DirectApproveIn, request: Request,
                               db: AsyncSession = Depends(get_db)):
    """
    The assertion is the authentication: a WebAuthn assertion over this registry's challenge, verified against a
    credential the account enrolled, with user verification set, approves the sign-in without a session (on a phone,
    the device approving may be the device signing in).

    \f
    The assertion IS the authentication.

    Requiring a logged-in session to approve created a deadlock: on the phone itself, the device
    that must approve is the device trying to log in (Commander-found). A WebAuthn assertion over
    our challenge, verified against a credential this account enrolled, with the UV bit set, is
    strictly stronger evidence than a bearer token — so it stands on its own.
    """
    row = (await db.execute(text(
        "SELECT developer_id, challenge_hash, status, expires_at FROM login_approvals WHERE id = :i"
    ), {"i": approval_id})).first()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Unknown approval")
    dev_id, challenge_hash, st, exp = row
    if st != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"Approval is {st}")
    if exp <= _now():
        await db.execute(text("UPDATE login_approvals SET status='expired', resolved_at=now() WHERE id=:i"),
                         {"i": approval_id})
        await db.commit()
        raise HTTPException(status.HTTP_410_GONE, detail="Approval expired")

    devices = (await db.execute(text(
        "SELECT id, webauthn_credential_id, webauthn_public_key FROM device_push_registrations "
        "WHERE developer_id = :d AND enabled AND webauthn_public_key IS NOT NULL AND key_revoked_at IS NULL"
    ), {"d": dev_id})).mappings().all()

    from agentvault_registry.services import webauthn as wa
    from agentvault_registry.routers.liability import _rp_id_candidates
    last = "no_matching_credential"
    for d in devices:
        if body.credential_id and d["webauthn_credential_id"] and body.credential_id != d["webauthn_credential_id"]:
            continue
        ok, reason, sign_count = wa.verify_assertion(
            cose_public_key_b64u=d["webauthn_public_key"],
            client_data_json_b64u=body.client_data_json,
            authenticator_data_b64u=body.authenticator_data,
            signature_b64u=body.signature,
            expected_challenge_b64u=liab.b64u_from_hex(challenge_hash),
            expected_rp_ids=_rp_id_candidates(request),
            require_uv=True,
        )
        last = reason or last
        if ok:
            await db.execute(text(
                "UPDATE login_approvals SET status='approved', method='webauthn_uv', device_id=:dv, "
                "resolved_at=now() WHERE id=:i AND status='pending'"), {"dv": d["id"], "i": approval_id})
            if sign_count:
                await db.execute(text("UPDATE device_push_registrations SET webauthn_sign_count=:c WHERE id=:i"),
                                 {"c": sign_count, "i": d["id"]})
            await db.commit()
            return {"ok": True, "status": "approved", "method": "webauthn_uv"}
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=f"Biometric verification failed ({last})")


@router.post("/{approval_id}/deny", summary="Reject this sign-in")
async def deny_login(approval_id: str, dev: models.Developer = Depends(get_current_developer),
                     db: AsyncSession = Depends(get_db)):
    await db.execute(text("UPDATE login_approvals SET status='denied', resolved_at=now() "
                          "WHERE id=:i AND developer_id=:d AND status='pending'"),
                     {"i": approval_id, "d": dev.id})
    await db.commit()
    return {"ok": True, "status": "denied"}


@router.post("/{approval_id}/token", summary="Exchange an approved request for an access token")
async def redeem_token(approval_id: str, db: AsyncSession = Depends(get_db)):
    """Single-use by construction: the row is claimed pending→consumed in one UPDATE, so two
    browsers racing the same approval cannot both walk away with a token."""
    row = (await db.execute(text(
        "SELECT developer_id, status, expires_at FROM login_approvals WHERE id = :i"
    ), {"i": approval_id})).first()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Unknown approval")
    dev_id, st, exp = row
    if st != "approved":
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"Approval is {st}")
    # the approval, not just the challenge, has a lifetime — an approved-but-unclaimed token
    # must not sit around indefinitely
    if exp + _dt.timedelta(seconds=TTL_SECONDS) <= _now():
        raise HTTPException(status.HTTP_410_GONE, detail="Approval expired before it was used")
    claimed = await db.execute(text(
        "UPDATE login_approvals SET status='consumed' WHERE id=:i AND status='approved'"), {"i": approval_id})
    if getattr(claimed, "rowcount", 0) == 0:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Approval already used")
    dev = await db.get(models.Developer, dev_id)
    if not dev or dev.is_suspended:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Account unavailable")
    token = security.create_access_token(
        data={"sub": str(dev.id)},
        expires_delta=_dt.timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        token_version=getattr(dev, "token_version", 0),
    )
    dev.last_login_at = _now()
    await db.commit()
    # §FEFRAME W1: a phone-approved sign-in is a full session: it refreshes like a password login instead of ending
    # hard at the access token's expiry
    refresh = security.create_refresh_token(dev.id, token_version=getattr(dev, "token_version", 0))
    return {"access_token": token, "token_type": "bearer", "refresh_token": refresh}


class ToggleIn(BaseModel):
    enabled: bool


@router.post("/settings", summary="Enable or disable push approval for my account")
async def set_push_login(body: ToggleIn, dev: models.Developer = Depends(get_current_developer),
                         db: AsyncSession = Depends(get_db)):
    if body.enabled:
        has = (await db.execute(text(
            "SELECT 1 FROM device_push_registrations WHERE developer_id=:d AND enabled "
            "AND webauthn_credential_id IS NOT NULL AND key_revoked_at IS NULL LIMIT 1"
        ), {"d": dev.id})).first()
        if not has:
            raise HTTPException(status.HTTP_428_PRECONDITION_REQUIRED,
                                detail="Enrol fingerprint signing on your phone first (Pocket → Approvals).")
    await db.execute(text("UPDATE developers SET push_login_enabled = :e WHERE id = :d"),
                     {"e": body.enabled, "d": dev.id})
    await db.commit()
    return {"ok": True, "push_login_enabled": body.enabled}


@router.get("/settings", summary="Is push approval enabled for my account?")
async def get_push_login(dev: models.Developer = Depends(get_current_developer),
                         db: AsyncSession = Depends(get_db)):
    has = (await db.execute(text(
        "SELECT 1 FROM device_push_registrations WHERE developer_id=:d AND enabled "
        "AND webauthn_credential_id IS NOT NULL AND key_revoked_at IS NULL LIMIT 1"
    ), {"d": dev.id})).first()
    return {"push_login_enabled": bool(getattr(dev, "push_login_enabled", False)),
            "device_ready": bool(has)}
