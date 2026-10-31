"""
Authentication and authorization router for TheProtocol Registry
Implements secure authentication with JWT tokens and recovery keys
"""

import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Annotated, Dict, Any, Tuple, Union
import httpx  # For TEG Layer communication
from ..es_ssl_helper import get_httpx_verify

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks, Body, Query, Response, Request, Header
import jwt  # PyJWT (§DEPS: python-jose is gone)
from jwt import PyJWTError as JWTError
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

# Local imports
from agentvault_registry import schemas, models, security
from agentvault_registry.models import Developer
from agentvault_registry.database import get_db
from agentvault_registry.crud import developer as developer_crud
from agentvault_registry.crud import agent as agent_crud  # For agent authentication
from agentvault_registry.email_utils import send_verification_email, send_password_reset_email
from agentvault_registry.crud.developer import (
    get_developer_by_reset_token,
    set_password_reset_token,
    clear_password_reset_token,
)
from agentvault_registry.crud.developer import get_developer_by_name

# Import configuration
from agentvault_registry.config import settings
from agentvault_registry.routers.legal import reconsent_state as _reconsent_state  # §LEGALKIT
from agentvault_registry.core.public_url import spa_url

# Import security utilities
from agentvault_registry.security_utils import (
    validate_password_strength,
    generate_secure_token,
    generate_api_key
)
from agentvault_registry.crud.invite_codes import (
    validate_invite_code,
    consume_invite_code,
    resolve_admin_flags,
)

logger = logging.getLogger(__name__)

# Rate limiter for auth endpoints (brute-force protection)
# §RATEFIX: THE shared, Redis-backed limiter — the same object main.py puts on
# app.state, so these decorations are both enforced and shared across workers.
# A router-local Limiter() would be in-memory per worker AND invisible to the
# middleware; that is what made all 65 limits here meaningless.
from agentvault_registry.middleware.rate_limiter import shared_limiter as limiter

router = APIRouter(
    prefix="/auth",
    # §pass56 PR-5: tags= dropped; main.py:include_router supplies "Authentication"
)


@router.get("/registration-config")  # §pass56 PR-5: tags= dropped
async def get_registration_config():
    """
    Public, no auth: the registration rules this registry applies. Whether an invite code is required
    (`beta_invite_required`), whether email verification is required (read from the registry's setting), and the
    legal document versions a registrant accepts (`tos_version`, `documents_version`, `legal_mode`).

    \f
    Public endpoint — tells the frontend whether invite codes are required.

    §OPGUIDE-3: `email_verification_required` used to be the literal `True` while the
    line above it read its setting. Any deployment that turns verification OFF (a
    private frame with no outbound mail must, or self-registration produces accounts
    that can never log in) still advertised that it was ON. Callers act on this —
    the operator manual tells an assistant to read it before registering — so a
    hardcoded answer is worse than no endpoint.
    """
    from ..core.legal_versions import DOCUMENTS_VERSION as _docs_v, TOS_VERSION as _tos_v
    from ..core.provider_facts import suite_mode as _suite_mode
    return {
        "beta_invite_required": settings.BETA_INVITE_REQUIRED,
        "email_verification_required": settings.REQUIRE_EMAIL_VERIFICATION,
        # §LEGALKIT (W3): the versions a client pins its acceptance to, and whose legal suite this frame serves.
        "tos_version": _tos_v,
        "documents_version": _docs_v,
        "legal_mode": _suite_mode(),
    }


# --- Email-verification helper (used by both /resend-verification AND
#     the login gate when REQUIRE_EMAIL_VERIFICATION blocks an unverified dev) ---
VERIFICATION_RESEND_COOLDOWN_S = int(os.getenv("VERIFICATION_RESEND_COOLDOWN_S", "300") or "300")


async def _verification_resend_release(developer_id: int) -> None:
    """A mail that did not go out must not hold the cooldown (Session A's review): the next request may try again."""
    try:
        from agentvault_registry.background_tasks.leader import get_redis
        r = await get_redis()
        if r is not None:
            await r.delete(f"verify:resend:{developer_id}")
    except Exception:  # noqa: BLE001
        pass


async def _verification_resend_allowed(developer_id: int) -> bool:
    """§TWOAGENT #16 (2026-09-23): at most one verification mail per account per cooldown window, whoever asks.
    Redis SET NX with a TTL; without Redis every request may send, which is the old behaviour."""
    try:
        from agentvault_registry.background_tasks.leader import get_redis
        r = await get_redis()
        if r is None:
            return True
        return bool(await r.set(f"verify:resend:{developer_id}", "1", nx=True,
                                ex=max(1, VERIFICATION_RESEND_COOLDOWN_S)))
    except Exception:  # noqa: BLE001 — a cooldown we cannot read never blocks a mail
        return True


_BACKGROUND_MAILS: set = set()   # the login gate's background sends, held so the loop cannot collect them mid-flight


async def _verification_mail_in_background(developer_id: int, *, source: str) -> None:
    """§EXTTEST (V0649): the login gate's verification mail, sent after the answer, in a session of its own, the window
    already claimed. An inline send held the login for the SMTP round trip (about 30 s on EU, 2026-10-30 18:38Z)."""
    from agentvault_registry.database import AsyncSessionLocal
    try:
        async with AsyncSessionLocal() as bg_db:
            developer = await developer_crud.get_developer_by_id(bg_db, developer_id=developer_id)
            if developer is None or developer.is_verified:
                await _verification_resend_release(developer_id)
                return
            await _issue_fresh_verification_email(bg_db, developer, source=source, claimed=True)
    except Exception:  # noqa: BLE001 — a background mail never raises into the loop
        logger.exception(f"[VerificationResend:{source}] dev={developer_id} background send raised")
        await _verification_resend_release(developer_id)


def _verification_token_still_good(developer: Developer, now: datetime) -> bool:
    """The current token has at least a quarter of its window (and 15 minutes) left, so re-mailing IT is enough."""
    exp = developer.verification_token_expires
    if not developer.email_verification_token or exp is None:
        return False
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    window = timedelta(hours=settings.EMAIL_VERIFICATION_TOKEN_EXPIRE_HOURS)
    return (exp - now) >= max(timedelta(minutes=15), window / 4)


async def _issue_fresh_verification_email(
    db: AsyncSession,
    developer: Developer,
    *,
    source: str,
    claimed: bool = False,
) -> str:
    """Mail the developer's verification link: "sent", "cooldown" or "not_sent".

    Used by:
      - POST /auth/resend-verification (explicit user request)
      - POST /auth/login (auto-resend when REQUIRE_EMAIL_VERIFICATION blocks)

    Never raises; DB and SMTP failures are logged and come back as "not_sent". The caller is responsible for the HTTP
    response shape.

    §TWOAGENT #16 (2026-09-23): this used to ROTATE the token on every call, and the login gate calls it on every
    unverified login, so each login mailed a new link and killed the one mailed before (measured on EU: "We just sent
    a fresh verification link" at every attempt); and POST /auth/resend-verification needs no authentication, so
    anyone who knew an address could keep invalidating its pending link. Now: at most one mail per account per
    VERIFICATION_RESEND_COOLDOWN_S ("cooldown" changes nothing), and the CURRENT token is re-mailed while it is still
    good, so every link already in the inbox keeps working. Only an expired or nearly expired token is rotated.
    """
    from agentvault_registry.security import generate_verification_token

    # claimed=True: the caller already holds this window (the login gate claims it before answering, §EXTTEST V0649)
    if not claimed and not await _verification_resend_allowed(developer.id):
        logger.info(f"[VerificationResend:{source}] dev={developer.id} cooldown — nothing sent, token kept")
        return "cooldown"

    now = datetime.now(timezone.utc)
    if _verification_token_still_good(developer, now):
        new_token = developer.email_verification_token
    else:
        new_token = generate_verification_token()
        developer.email_verification_token = new_token
        developer.verification_token_expires = now + timedelta(
            hours=settings.EMAIL_VERIFICATION_TOKEN_EXPIRE_HOURS
        )
        try:
            db.add(developer)
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception(
                f"[VerificationResend:{source}] dev={developer.id} "
                f"failed to persist new token"
            )
            await _verification_resend_release(developer.id)
            return "not_sent"

    if not (settings.MAIL_SERVER and settings.MAIL_USERNAME and settings.MAIL_FROM):
        logger.info(
            f"[VerificationResend:{source}] dev={developer.id} "
            f"SMTP not configured — email NOT sent"
        )
        await _verification_resend_release(developer.id)
        return "not_sent"

    try:
        sent = await send_verification_email(
            to_email=developer.email,
            username=developer.name,
            token=new_token,
        )
    except Exception:
        logger.exception(
            f"[VerificationResend:{source}] dev={developer.id} send raised"
        )
        await _verification_resend_release(developer.id)
        return "not_sent"

    logger.info(
        f"[VerificationResend:{source}] dev={developer.id} sent={sent}"
    )
    if not sent:
        await _verification_resend_release(developer.id)
    return "sent" if sent else "not_sent"


# --- TEG Integration Helper ---
async def initialize_teg_account(developer_email: str, developer_id: int):
    """Initialize TEG account for newly verified developer"""
    from agentvault_registry.identifiers import developer_teg_did
    try:
        # Canonical developer wallet DID — the SAME id every developer-initiated TEG
        # operation uses (see identifiers.developer_teg_did). Previously this built
        # did:theprotocol:{developer_id}, which created a phantom account the
        # developer never transacted with (the long-standing init failure).
        agent_id = developer_teg_did(developer_email)
        
        # Get TEG admin API key from settings
        teg_admin_key = settings.TEG_ADMIN_API_KEY
        teg_base_url = getattr(settings, 'TEG_API_BASE_URL', 'http://localhost:8001')
        
        async with httpx.AsyncClient(verify=get_httpx_verify()) as client:
            response = await client.post(
                f"{teg_base_url}/api/v1/agent/initialize-teg-account",
                json={
                    "agent_id": agent_id,
                    "initial_balance": "0",
                    "initial_reputation_score": 0
                },
                headers={
                    "Authorization": f"Bearer {teg_admin_key}",
                    "Content-Type": "application/json"
                },
                timeout=10.0
            )
            
            if response.status_code in [200, 409]:  # 409 means already exists, which is fine
                logger.info(f"TEG account initialized for developer {developer_email} (DID: {agent_id})")
                return True
            else:
                logger.error(f"Failed to initialize TEG account: {response.status_code} - {response.text}")
                return False
                
    except Exception as e:
        logger.error(f"Error initializing TEG account for {developer_email}: {e}")
        return False


# --- Profile Endpoint ---
@router.get("/profile", response_model=schemas.DeveloperProfile, summary="Get Current User Profile")
async def get_profile(
    current_developer: Developer = Depends(security.get_current_developer),
    db: AsyncSession = Depends(get_db)
):
    """
    Get the profile of the currently authenticated developer.
    """
    return schemas.DeveloperProfile(
        id=current_developer.id,
        name=current_developer.name,
        email=current_developer.email,
        organization=None,  # Not in the model yet
        role="admin" if current_developer.is_admin else "developer",  # Fix 1 (2026-04-21): was hardcoded commander email, now uses is_admin flag
        is_verified=current_developer.is_verified,
        is_admin=current_developer.is_admin,  # Added is_admin field
        created_at=current_developer.created_at,
        **(await _reconsent_state(current_developer, db)),  # §LEGALKIT: Terms § 10.2, asked again after a material change
    )


@router.post(
    "/register",
    response_model=schemas.RegistrationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new developer account",
    responses={
        status.HTTP_201_CREATED: {"description": "Registration successful, verification email sent."},
        status.HTTP_400_BAD_REQUEST: {"description": "Email already registered or weak password."},
        status.HTTP_409_CONFLICT: {"description": "Username (developer name) already exists."},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "Email service not configured."},
    }
)
@limiter.limit("5/minute")
async def register_developer(
    request: Request,
    background_tasks: BackgroundTasks,
    developer_in: schemas.DeveloperCreate = Body(...),
    db: AsyncSession = Depends(get_db)
):
    """
    Handles new developer registration with enhanced security.
    Creates account, generates keys, sends verification email.
    """
    logger.info(f"Registration attempt for email: {developer_in.email}")
    
    # Validate password strength - FIX: Extract secret value first
    password_value = developer_in.password.get_secret_value() if hasattr(developer_in.password, 'get_secret_value') else developer_in.password
    is_valid, error_msg = validate_password_strength(password_value)
    if not is_valid:
        logger.warning(f"Registration failed: Weak password for {developer_in.email} - {error_msg}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Password validation failed: {error_msg}"
        )
    
    # --- Beta Invite Gate ---
    # Captured as a plain bool, not by holding the ORM row: it is read again only after
    # the developer is created and the code consumed, and a stale/expired instance at
    # that point would silently decide an admin grant. `False` unless a valid
    # admin-granting code was actually presented (§OPGUIDE-3, mig 0142).
    invite_grants_admin = False
    invite_admin_flags: list[str] = []
    if settings.BETA_INVITE_REQUIRED:
        if not developer_in.invite_code:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Beta access requires an invite code. Contact the team for an invitation."
            )
        valid, reason, _code_obj = await validate_invite_code(db, developer_in.invite_code)
        if not valid:
            reason_msg = {
                "not_found": "Invite code not found.",
                "used": "This invite code has already been used.",
                "expired": "This invite code has expired.",
            }.get(reason or "", "Invalid invite code.")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=reason_msg
            )
        invite_grants_admin = bool(getattr(_code_obj, "grants_admin", False))
        # Resolved here, from the same row that was just validated, for the same reason
        # the bool is: the elevation runs after consumption and must not re-read a row.
        invite_admin_flags = resolve_admin_flags(_code_obj)
    # --- End Beta Invite Gate ---

    # --- ToS Consent Gate (0120) ---
    # The register form gates on a checkbox, but that is client-side only — a scripted client could
    # register with no acceptance signal. Enforce it server-side + stamp an authoritative record.
    if settings.TOS_CONSENT_REQUIRED and not getattr(developer_in, "tos_accepted", False):
        logger.warning(f"Registration failed: Terms not accepted for {developer_in.email}")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="You must accept the Terms of Service and Privacy Policy to register.",
        )
    # --- End ToS Consent Gate ---

    # Check for existing developer (email)
    existing_developer = await developer_crud.get_developer_by_email(db, email=developer_in.email)
    if existing_developer:
        logger.warning(f"Registration failed: Email '{developer_in.email}' already registered.")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered.",
        )

    # Check for existing developer (name) — pre-flight before hitting DB constraint
    existing_by_name = await get_developer_by_name(db, name=developer_in.name)
    if existing_by_name:
        logger.warning(f"Registration failed: Name '{developer_in.name}' already taken.")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This display name is already taken. Please choose a different name.",
        )

    try:
        # CRUD function handles hashing, token generation, recovery keys
        created_developer = await developer_crud.create_developer(db=db, developer=developer_in)
        plain_recovery_keys = getattr(created_developer, '_plain_recovery_keys', [])
        # §LEGALKIT: the acceptance record (migration 0181), beside the developer columns crud stamped.
        if getattr(developer_in, "tos_accepted", False):
            from ..services.legal_acceptance import SUBJECT_DEVELOPER as _SUBJ, record_acceptance as _rec
            await _rec(db, document="terms", subject_kind=_SUBJ, subject_id=str(created_developer.id),
                       via="register", developer_id=created_developer.id, request=request)
            if getattr(developer_in, "age_confirmed", False):
                await _rec(db, document="age18", subject_kind=_SUBJ, subject_id=str(created_developer.id),
                           via="register", developer_id=created_developer.id, request=request)
            await db.commit()

        # Auto-verify when email verification is disabled (sandbox/dev environments)
        if not settings.REQUIRE_EMAIL_VERIFICATION and not created_developer.is_verified:
            created_developer.is_verified = True
            created_developer.email_verification_token = None
            created_developer.verification_token_expires = None
            await db.commit()
            logger.info(f"Auto-verified {created_developer.email} (REQUIRE_EMAIL_VERIFICATION=false)")

        # §OPGUIDE-3: when verification is disabled the account was just auto-verified
        # above, so there is nothing to verify and no mail to send. Without this guard
        # the block below still attempted an SMTP delivery and, on a deployment whose
        # mail server is unreachable (a private frame), returned
        # "we could not send the verification email" for a registration that had in
        # fact completely succeeded — alarming, and it sent the reader off to
        # 'Resend Verification', which cannot help because nothing is pending.
        email_sent = False
        if not settings.REQUIRE_EMAIL_VERIFICATION:
            message = "Registration successful. Your account is ready to use."
        elif settings.MAIL_SERVER and settings.MAIL_USERNAME and settings.MAIL_FROM:
            try:
                email_sent = await send_verification_email(
                    to_email=created_developer.email,
                    username=created_developer.name,
                    token=created_developer.email_verification_token
                )
                if email_sent:
                    logger.info(f"Verification email sent for {created_developer.email}")
                    # §EXTTEST (V0649): registration's mail opens the resend window too; without it the first login a
                    # minute later found no window and mailed the same link again (EU, 2026-10-30 18:37:40Z, 18:38:40Z)
                    await _verification_resend_allowed(created_developer.id)
                else:
                    logger.error(f"Verification email delivery failed for {created_developer.email} (SMTP error — check MAIL_FROM/MAIL_USERNAME config)")
            except Exception as email_exc:
                logger.exception(f"Unexpected error sending verification email to {created_developer.email}")

        if not settings.REQUIRE_EMAIL_VERIFICATION:
            # `message` was already set above. Guarded here too: without this branch the
            # chain below overwrites it with the delivery-failure text, because
            # `email_sent` is False whenever we deliberately skipped sending.
            pass
        elif email_sent:
            message = "Registration successful. Please check your email to verify your account."
        elif settings.MAIL_SERVER and settings.MAIL_USERNAME and settings.MAIL_FROM:
            message = "Registration successful, but we could not send the verification email. Use 'Resend Verification' to try again."
        else:
            logger.warning("Email settings not configured. Skipping verification email.")
            message = "Registration successful. Email verification is currently disabled."

        # --- Consume invite code if required ---
        if settings.BETA_INVITE_REQUIRED and developer_in.invite_code:
            await consume_invite_code(db, developer_in.invite_code, created_developer.id)

            # §OPGUIDE-3 / §INVRBAC — an admin-granting invitation confers exactly the
            # granular flags the code names, and nothing else.
            #
            # Done AFTER consumption on purpose: if consuming the code fails the account
            # exists but stays an ordinary developer, which is the safe direction to fail.
            #
            # `is_admin` is deliberately NOT set. It is not the authorization system:
            # every admin route in this codebase gates on require_admin_flag("admin_*"),
            # and is_admin appears inside that gate only as a blanket short-circuit. An
            # account created from an invitation gets capabilities, not a bypass, so its
            # authority can be read off the row and narrowed later like anyone else's.
            if invite_grants_admin and invite_admin_flags:
                for _flag in invite_admin_flags:
                    setattr(created_developer, _flag, True)
                # NOT must_change_password: they chose this password themselves at
                # registration, so there is nothing to force them to replace.
                await db.commit()
                logger.warning(
                    f"[Register] ADMIN account minted from invite code for "
                    f"developer_id={created_developer.id} ({created_developer.email}) — "
                    f"granted {invite_admin_flags} (is_admin NOT set)."
                )
        # --- End consume ---

        return schemas.RegistrationResponse(
            message=message,
            recovery_keys=plain_recovery_keys
        )

    except IntegrityError:
        await db.rollback()
        logger.warning(f"Registration failed: Username '{developer_in.name}' likely already exists.")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username or email already exists.",
        )
    except Exception as e:
        await db.rollback()
        logger.exception(f"Unexpected error during registration for email {developer_in.email}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred during registration.",
        )


# Import the extended token schema for 2FA support
from agentvault_registry.schemas_2fa import TokenWithTwoFactor

@router.post("/login", response_model=TokenWithTwoFactor, summary="Developer Login")
@limiter.limit("10/minute")
async def login_for_access_token(
    request: Request,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    response: Response,
    db: AsyncSession = Depends(get_db)
):
    """
    Handles developer login using email and password (OAuth2 Password Flow).
    Verifies credentials and returns a JWT access token.
    If 2FA is enabled, returns a partial token requiring 2FA verification.
    """
    logger.info(f"Login attempt for user: {form_data.username}")
    developer = await developer_crud.get_developer_by_email(db, email=form_data.username)

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Incorrect email or password",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if not developer:
        logger.warning(f"Login failed: Developer not found for email {form_data.username}")
        raise credentials_exception

    if not security.verify_password(form_data.password, developer.hashed_password):
        logger.warning(f"Login failed: Invalid password for email {form_data.username}")
        raise credentials_exception

    # --- M1 2026-04-20: admin-suspend / admin-delete gate ---
    if getattr(developer, "deleted_at", None) is not None:
        logger.warning(f"Login blocked: developer {developer.id} is deleted ({developer.deleted_at})")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account deleted. Contact operators@theprotocol.cloud if this is an error."
        )
    if getattr(developer, "is_suspended", False):
        reason = developer.suspended_reason or "no reason provided"
        logger.warning(f"Login blocked: developer {developer.id} is suspended ({reason})")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Account suspended: {reason}"
        )
    # --- end admin-suspend gate ---

    # --- Email verification gate (REQUIRE_EMAIL_VERIFICATION env var) ---
    # Sandbox sets REQUIRE_EMAIL_VERIFICATION=false → registration auto-verifies
    # all new devs → this check is a no-op there. Prod default is True.
    # Auto-issues a fresh verification email so the user can self-recover from
    # expired or lost tokens with no extra clicks. Rate-limited by the existing
    # 10/minute on /auth/login.
    if settings.REQUIRE_EMAIL_VERIFICATION and not developer.is_verified:
        # §EXTTEST (V0649): the login answers at once and the mail leaves in the background. The window is claimed HERE,
        # so the answer tells the truth ("on its way" or "cooldown") and the background send skips its own claim.
        outcome = "not_sent"
        try:
            if not (settings.MAIL_SERVER and settings.MAIL_USERNAME and settings.MAIL_FROM):
                outcome = "not_sent"
            elif await _verification_resend_allowed(developer.id):
                import asyncio as _aio_bg
                task = _aio_bg.create_task(_verification_mail_in_background(developer.id, source="login_gate"))
                _BACKGROUND_MAILS.add(task)
                task.add_done_callback(_BACKGROUND_MAILS.discard)
                outcome = "sent"
            else:
                outcome = "cooldown"
        except Exception:
            logger.exception(
                f"[login_gate] dev={developer.id} auto-resend raised; "
                f"continuing with 403"
            )

        logger.warning(
            f"Login blocked: developer {developer.id} unverified "
            f"(REQUIRE_EMAIL_VERIFICATION=True, verification_mail={outcome})"
        )

        if outcome == "sent":
            detail = (
                "Please verify your email address. A verification link is on "
                "its way to your inbox: check there (including spam) and click "
                "the link to activate your account."
            )
        elif outcome == "cooldown":
            detail = (
                "Please verify your email address. Your verification link was "
                "mailed to you a few minutes ago and still works — check your "
                "inbox (including spam). A new mail can be requested with "
                "'Resend Verification' after a few minutes."
            )
        else:
            detail = (
                "Please verify your email address. Use 'Resend Verification' "
                "on the login page to receive a new link."
            )

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail,
            headers={"X-Verification-Required": "true"},
        )
    # --- End email verification gate ---

    # --- Admin 2FA enforcement gate (REQUIRE_ADMIN_2FA env var) ---
    # §pass50.8 (2026-05-20): covers superadmin (is_admin) AND any RBAC sub-flag
    # holder (admin_treasury / admin_support / admin_enforcement /
    # admin_federation / admin_platform). Without this, a sub-admin whose only
    # authority is e.g. admin_treasury=true (is_admin=false) would bypass the
    # gate when REQUIRE_ADMIN_2FA flips True — they could approve fiat refunds,
    # adjust treasury policy etc. without 2FA. Same env flag, same default
    # (False); the change only takes effect once the flag is flipped.
    _has_admin_authority = bool(
        developer.is_admin
        or getattr(developer, "admin_treasury", False)
        or getattr(developer, "admin_support", False)
        or getattr(developer, "admin_enforcement", False)
        or getattr(developer, "admin_federation", False)
        or getattr(developer, "admin_platform", False)
    )
    if settings.REQUIRE_ADMIN_2FA and _has_admin_authority and not developer.two_fa_enabled:
        held_flags = [
            f for f in ("is_admin", "admin_treasury", "admin_support",
                        "admin_enforcement", "admin_federation", "admin_platform")
            if getattr(developer, f, False)
        ]
        logger.warning(
            f"Login blocked: admin {developer.id} has no 2FA enabled "
            f"(REQUIRE_ADMIN_2FA=True, held_flags={held_flags})"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin accounts (including RBAC sub-admins) must have "
                   "Two-Factor Authentication enabled. Log in with a "
                   "non-enforced build, set up 2FA in Settings → Security, "
                   "then retry."
        )
    # --- End admin 2FA gate ---

    # --- PUSH LOGIN (2026-07-25) -------------------------------------------------------------
    # The password is correct, but this account has opted into phone approval. Building the
    # approval as a SEPARATE endpoint was not enough: the ordinary login path still minted a
    # token, so enabling the feature changed nothing and a password alone still got you in
    # (Commander-found). The gate has to live HERE, on the path everybody actually uses.
    if getattr(developer, "push_login_enabled", False):
        # NON-INTERACTIVE CALLERS ARE REFUSED, NOT QUEUED. Our web app always sends this header
        # (0 or 1); scripts never do. Raising an approval for them was actively harmful: this
        # account is also used by the simulation, cloud-op canaries and a 60-second healthcheck,
        # so their approval notifications arrived on the phone seconds before the human's own —
        # indistinguishable on a lock screen. The Commander approved a healthcheck's login with
        # a real fingerprint while their own browser polled a pending request forever.
        # The header is a ROUTING hint, not a bypass: supplying it only routes you INTO the
        # fingerprint gate, which is the strong path. Omitting it gets you nothing at all.
        if request.headers.get("x-push-login-local") is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=("This account requires phone approval to sign in. Use the web app, "
                        "or authenticate with an API key."),
            )
        try:
            from agentvault_registry.routers.push_login import create_approval_for_login
            # The browser tells us whether it can raise its own biometric prompt; if it can,
            # we skip the push entirely rather than alerting the device that is already acting.
            local_capable = (request.headers.get("x-push-login-local") or "") == "1"
            approval = await create_approval_for_login(db, developer, request,
                                                       suppress_push=local_capable)
        except Exception:
            logger.warning("[PUSHLOGIN] approval creation failed for dev=%s", developer.id, exc_info=True)
            approval = None
        if approval:
            return TokenWithTwoFactor(
                access_token="",                      # nothing is issued until the phone approves
                token_type="bearer",
                requires_push_approval=True,
                approval_id=approval["approval_id"],
                approval_expires_in=approval["expires_in"],
                developer_id=developer.id,
                message="Approve this sign-in on your phone",
            )
        # No usable device (revoked/unenrolled since opting in) → fall through to the normal
        # factors rather than locking the account out of its own front door.

    # --- ADDED: Check if 2FA is enabled ---
    if developer.two_fa_enabled:
        try:
            # Import the 2FA service
            from agentvault_registry.services import TwoFactorAuthService
            
            # Generate partial token for 2FA flow
            partial_token = TwoFactorAuthService.generate_partial_token(developer.id)
            
            logger.info(f"2FA required for developer ID: {developer.id}")
            
            # Return response indicating 2FA is required
            return TokenWithTwoFactor(
                access_token="",  # No access token yet
                token_type="bearer",
                requires_2fa=True,
                partial_token=partial_token,
                developer_id=developer.id,
                message="2FA verification required"
            )
        except (ImportError, RuntimeError) as e:
            # If 2FA module not available, log warning and proceed with normal login
            logger.warning(f"2FA is enabled for developer {developer.id} but module not available: {e}")
            # Fall through to normal login
    # --- END 2FA Check ---

    # Create JWT token with proper expiration
    access_token_expires = timedelta(minutes=security.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    # Create access token using standard method
    # AL-1: stamp the developer's token_version so logout / password-change /
    # admin force-logout can revoke this session.
    access_token = security.create_access_token(
        data={"sub": str(developer.id)},
        expires_delta=access_token_expires,
        token_version=getattr(developer, "token_version", 0),
    )

    # Stamp last_login_at (f035)
    try:
        developer.last_login_at = datetime.now(timezone.utc)
        db.add(developer)
        await db.commit()
    except Exception:
        await db.rollback()  # non-fatal — token already issued
    
    # Log successful login
    logger.info(f"Login successful for developer ID: {developer.id}")
    
    # Add security headers
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    
    # Generate refresh token (7-day JWT for session continuity)
    # AL-3: stamp token_version so password-change/logout/suspend revoke it too.
    refresh_token = security.create_refresh_token(
        developer.id, token_version=getattr(developer, "token_version", 0)
    )

    # Return successful login response with refresh token
    return TokenWithTwoFactor(
        access_token=access_token,
        token_type="bearer",
        expires_in=security.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        refresh_token=refresh_token,
        requires_2fa=False,
        partial_token=None,
        developer_id=None,
        message="Login successful",
        must_change_password=True if developer.must_change_password else None,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Logout (revoke sessions)")
async def logout(
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
):
    """
    Log out, with a REAL server-side revocation.

    With a valid developer token this bumps the developer's token_version,
    which invalidates every live access token for that developer (all devices).
    Single-token-version is our revocation primitive, so logout = log out
    everywhere, the safe default (a stolen token dies with the logout).

    Idempotent + never blocks the client: no/expired/garbage token → 204 anyway
    (you're already logged out). Password change/reset also revoke this way.
    """
    logger.info("Logout endpoint called")
    if authorization:
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1]
            # Best-effort: only a valid, non-refresh developer JWT triggers a bump.
            if not token.startswith("avreg_"):
                try:
                    payload = jwt.decode(token, security.SECRET_KEY, algorithms=[security.ALGORITHM])
                    if payload.get("type") != "refresh" and payload.get("sub"):
                        dev_id = int(payload["sub"])
                        await db.execute(
                            update(models.Developer)
                            .where(models.Developer.id == dev_id)
                            .values(token_version=models.Developer.token_version + 1)
                        )
                        await db.commit()
                        logger.info(f"Logout revoked all sessions for developer {dev_id}")
                except (JWTError, ValueError, Exception) as e:
                    # Expired/garbage token or non-developer sub — nothing to revoke.
                    logger.debug(f"Logout: no revocable developer token ({type(e).__name__})")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/change-password",
    response_model=Dict[str, str],
    summary="Change Password",
    responses={
        status.HTTP_200_OK: {"description": "Password changed successfully."},
        status.HTTP_400_BAD_REQUEST: {"description": "Current password incorrect or new password too weak."},
    }
)
async def change_password(
    current_password: str = Body(...),
    new_password: str = Body(...),
    current_developer: Developer = Depends(security.get_current_developer),
    db: AsyncSession = Depends(get_db)
):
    """
    Change the current developer's password.

    Requires the current password for verification. On success, clears the
    ``must_change_password`` flag so operator-seeded accounts can proceed
    to admin operations.
    """
    # Verify current password
    if not security.verify_password(current_password, current_developer.hashed_password):
        logger.warning(f"Password change failed: incorrect current password for developer {current_developer.id}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect."
        )

    # Validate new password strength
    from agentvault_registry.security_utils import validate_password_strength
    is_valid, error_msg = validate_password_strength(new_password)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Password validation failed: {error_msg}"
        )

    # Update password and clear must_change_password flag
    current_developer.hashed_password = security.hash_password(new_password)
    current_developer.must_change_password = False
    current_developer.updated_at = datetime.now(timezone.utc)
    # AL-2 (2026-07-24): changing the password logs out every existing session —
    # the headline RA5 fix. Bumping token_version invalidates all live tokens
    # (a stolen token can no longer outlive the password change).
    current_developer.token_version = (current_developer.token_version or 0) + 1

    try:
        db.add(current_developer)
        await db.commit()
        logger.info(f"Password changed for developer {current_developer.id}")
        return {"status": "password_changed"}
    except Exception:
        await db.rollback()
        logger.exception(f"DB error during password change for developer {current_developer.id}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update password."
        )


@router.get("/verify-email", summary="Verify Email Address", response_model=Dict[str, str])
async def verify_email(token: str = Query(...), db: AsyncSession = Depends(get_db)):
    """Handles the email verification link clicked by the user."""
    logger.info(f"Email verification request with token prefix: {token[:8]}...")
    
    developer = await developer_crud.get_developer_by_verification_token(db, token=token)

    if not developer:
        logger.warning(f"Verification failed: Token not found.")
        return RedirectResponse(url=spa_url("email-verification?status=failed&reason=not_found"), status_code=status.HTTP_303_SEE_OTHER)

    if developer.is_verified:
        logger.info(f"Email '{developer.email}' already verified.")
        return RedirectResponse(url=spa_url("email-verification?status=success&already=true"), status_code=status.HTTP_303_SEE_OTHER)

    if developer.verification_token_expires is None or developer.verification_token_expires < datetime.now(timezone.utc):
        logger.warning(f"Verification failed: Token expired for email {developer.email}.")
        return RedirectResponse(url=spa_url("email-verification?status=failed&reason=expired"), status_code=status.HTTP_303_SEE_OTHER)

    # Token is valid, mark as verified.
    # §FIRSTHOUR (2026-09-03): the consumed token STAYS on the row (only its expiry is
    # cleared). Mail clients prefetch links and people tap twice; a second visit must
    # find the developer and answer `already=true`, not `not_found`. A verified row is
    # never re-verified (the branch above), and every resend path gates on is_verified.
    developer.is_verified = True
    developer.verification_token_expires = None

    try:
        db.add(developer)
        await db.commit()
        # §R55: the flag lives in a ROW; the peers only re-pull the CARDS. Touch them.
        from agentvault_registry.services.card_touch import touch_developer_native_cards
        await touch_developer_native_cards(db, developer.id, reason="email verified")
        logger.info(f"Email verified for developer: {developer.email} (ID: {developer.id})")

        # Initialize TEG account for the newly verified developer
        teg_initialized = await initialize_teg_account(developer.email, developer.id)
        if not teg_initialized:
            logger.warning(f"TEG account initialization failed for {developer.email}, but email verification succeeded")

        return RedirectResponse(url=spa_url("email-verification?status=success"), status_code=status.HTTP_303_SEE_OTHER)
    except Exception as e:
        await db.rollback()
        logger.exception(f"Database error during email verification for {developer.email}")
        return RedirectResponse(url=spa_url("email-verification?status=failed&reason=error"), status_code=status.HTTP_303_SEE_OTHER)


@router.post("/resend-verification", response_model=Dict[str, str], summary="Resend Email Verification")
async def resend_verification_email(
    email: str = Body(..., embed=True),
    db: AsyncSession = Depends(get_db)
):
    """
    Resends the verification email for an unverified account.
    Always returns 200 to avoid leaking whether an email exists.
    Rate-limiting on this endpoint should be enforced at the nginx/SlowAPI layer.
    """
    logger.info(f"Resend verification request for: {email}")

    developer = await developer_crud.get_developer_by_email(db, email=email)

    if not developer:
        # Don't leak account existence
        return {"message": "If that email is registered and unverified, a new verification email has been sent."}

    if developer.is_verified:
        return {"message": "This account is already verified. Please log in."}

    # Rotate token + persist + send via shared helper. Helper returns False
    # only when SMTP is configured AND delivery failed (or DB persist failed).
    outcome = await _issue_fresh_verification_email(db, developer, source="explicit_resend")

    # Preserve the existing 503 contract for explicit resend when SMTP is
    # configured but delivery fails. (When SMTP is not configured at all, keep the
    # generic 200 so callers behave the same as before this refactor.) A cooldown
    # answers the same generic 200: it must not tell a stranger anything either.
    if outcome == "not_sent" and settings.MAIL_SERVER and settings.MAIL_USERNAME and settings.MAIL_FROM:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Email delivery failed. Please check your address or try again later."
        )

    return {"message": "If that email is registered and unverified, a new verification email has been sent."}


# ---------------------------------------------------------------------------
# EMAIL-BASED PASSWORD RESET  (f037 — replaces 404 stubs)
# ---------------------------------------------------------------------------

@router.post(
    "/forgot-password",
    response_model=Dict[str, str],
    summary="Request Password Reset Email",
    responses={
        status.HTTP_200_OK: {"description": "Always 200 — no account enumeration."},
    }
)
@limiter.limit("3/minute")
async def forgot_password(
    request: Request,
    email: str = Body(..., embed=True),
    db: AsyncSession = Depends(get_db)
):
    """
    Sends a password-reset email with a time-limited token.
    Always returns 200 regardless of whether the email is registered
    to prevent user enumeration.
    Token TTL: 1 hour.
    """
    logger.info(f"Password reset requested for: {email}")
    ALWAYS_OK = {"message": "If that email is registered, a password reset link has been sent."}

    developer = await developer_crud.get_developer_by_email(db, email=email)
    if not developer or not developer.is_verified:
        # Don't reveal non-existence
        return ALWAYS_OK

    token = generate_secure_token(32)
    expires = datetime.now(timezone.utc) + timedelta(hours=1)

    stored = await set_password_reset_token(db, developer, token, expires)
    if not stored:
        logger.error(f"Failed to store reset token for developer {developer.id}")
        return ALWAYS_OK  # still 200 — internal error not surfaced

    if settings.MAIL_SERVER and settings.MAIL_USERNAME and settings.MAIL_FROM:
        sent = await send_password_reset_email(
            to_email=developer.email,
            username=developer.name,
            token=token
        )
        if sent:
            logger.info(f"Password reset email sent to {developer.email}")
        else:
            logger.error(f"Password reset email delivery failed for {developer.email}")
    else:
        logger.warning(f"Email not configured — reset token generated for developer {developer.id} but not sent.")

    return ALWAYS_OK


@router.post(
    "/reset-password",
    response_model=Dict[str, str],
    summary="Reset Password via Email Token",
    responses={
        status.HTTP_400_BAD_REQUEST: {"description": "Token invalid, expired, or password too weak."},
    }
)
@limiter.limit("3/minute")
async def reset_password_via_email(
    request: Request,
    token: str = Body(...),
    new_password: str = Body(...),
    db: AsyncSession = Depends(get_db)
):
    """
    Validates the email reset token and sets a new password.
    Clears the token after a successful reset.
    """
    # §FESUITE (V0594): a used link is refused like an unknown one (the token is cleared on use, so the two cannot be told
    # apart), and the sentence a person reads said "invalid" of the link they had just used; it names both and the remedy
    INVALID = HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="This reset link is no longer valid: it was already used, or it has expired. Request a new one."
    )

    developer = await get_developer_by_reset_token(db, token)
    if not developer:
        logger.warning("Password reset attempt with unknown token")
        raise INVALID

    if (
        developer.password_reset_token_expires is None
        or developer.password_reset_token_expires < datetime.now(timezone.utc)
    ):
        logger.warning(f"Password reset token expired for developer {developer.id}")
        raise INVALID

    is_valid, error_msg = validate_password_strength(new_password)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Password validation failed: {error_msg}"
        )

    developer.hashed_password = security.hash_password(new_password)
    # The password is now the person's own, chosen through a link mailed to the account's address, so the issued one
    # it replaces is gone and so is the reason for must_change_password (§HELLOFRAME 2026-09-19). The frame request
    # intake and the fiat onramp create magic-link accounts with the flag set beside a random password nobody ever
    # sees; leaving it set told every such applicant their password "was seen by someone else" and made them change it
    # a second time. change-password clears it the same way.
    developer.must_change_password = False
    developer.updated_at = datetime.now(timezone.utc)
    # AL-2: password reset revokes all live sessions (see change-password).
    developer.token_version = (developer.token_version or 0) + 1
    # Clear token immediately
    developer.password_reset_token = None
    developer.password_reset_token_expires = None

    try:
        db.add(developer)
        await db.commit()
        logger.info(f"Password reset via email token for developer {developer.id}")
        return {"message": "Password updated successfully. Please log in with your new password."}
    except Exception:
        await db.rollback()
        logger.exception(f"DB error during email password reset for developer {developer.id}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update password."
        )


# ---------------------------------------------------------------------------
# RECOVERY KEY FLOW
# ---------------------------------------------------------------------------

@router.post("/recover-account", response_model=schemas.Token, summary="Recover Account via Recovery Key")
async def recover_account_with_key(
    recover_in: schemas.PasswordResetRecover,
    db: AsyncSession = Depends(get_db)
):
    """
    Verifies email and recovery key, returns a short-lived token for setting a new password.
    Enhanced with rate limiting and audit logging.
    """
    logger.info(f"Account recovery attempt for email: {recover_in.email}")
    
    developer = await developer_crud.get_developer_by_email(db, email=recover_in.email)

    error_exception = HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Invalid email or recovery key.",
    )

    if not developer or not developer.is_verified:
        logger.warning(f"Recovery failed: Developer not found or not verified for email {recover_in.email}.")
        raise error_exception

    if not developer.hashed_recovery_key:
        logger.error(f"Recovery failed: Developer {developer.id} has no recovery key hash stored.")
        raise error_exception

    used = security.match_recovery_key(recover_in.recovery_key, developer.hashed_recovery_key)
    if used is None:
        logger.warning(f"Recovery failed: Invalid recovery key for developer {developer.id}.")
        raise error_exception

    # §FESUITE: each key works once, the moment it verifies; the person's other keys stay valid (set-new-password used
    # to clear the whole column, so the spare keys a person had written down stopped working with the first)
    developer.hashed_recovery_key = security.burn_recovery_key(developer.hashed_recovery_key, used)
    db.add(developer)
    await db.commit()

    # Recovery key is valid, issue temporary password-set token
    temp_token_expires = timedelta(minutes=5)  # Short expiry for security
    temp_token = security.create_access_token(
        # `tv`: the version the token is good for; set-new-password moves it, so the token sets a password once (it
        # could be replayed for its whole five minutes, found 2026-10-24 by the MCP tester's recovery chain)
        data={"sub": str(developer.id), "purpose": "password-set", "tv": int(developer.token_version or 0)},
        expires_delta=temp_token_expires
    )
    
    logger.info(f"Recovery key verified for developer {developer.id}. Temporary token issued.")
    
    return schemas.Token(access_token=temp_token, token_type="bearer")


@router.post("/set-new-password", summary="Set New Password After Recovery", response_model=Dict[str, str])
async def set_new_password_after_recovery(
    set_in: schemas.PasswordSetNew = Body(...),
    db: AsyncSession = Depends(get_db),
    claims: Tuple[int, Optional[int]] = Depends(security.verify_temp_password_claims)
):
    """
    Sets a new password using the temporary token obtained via recovery key flow.
    Validates password strength and invalidates the used recovery key.
    """
    developer_id, token_version = claims
    logger.info(f"Setting new password for developer ID: {developer_id} after recovery.")
    
    developer = await developer_crud.get_developer_by_id(db, developer_id=developer_id)
    if not developer:
        logger.error(f"Developer {developer_id} not found after token verification.")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Developer not found.")
    # the token is good for the version it was issued at: a password set (this route, a reset, a logout) moves it
    if token_version is None or token_version != int(developer.token_version or 0):
        logger.warning(f"Password-set token for developer {developer_id} is spent or predates its version.")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid or expired password recovery token",
                            headers={"WWW-Authenticate": "Bearer error=\"invalid_token\""})

    # Validate new password strength
    new_password = set_in.new_password.get_secret_value()
    is_valid, error_msg = validate_password_strength(new_password)
    if not is_valid:
        logger.warning(f"New password validation failed for developer {developer_id}: {error_msg}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Password validation failed: {error_msg}"
        )

    # Update password and invalidate recovery key
    new_hashed_password = security.hash_password(new_password)
    developer.hashed_password = new_hashed_password
    developer.must_change_password = False  # the person's own password now (see reset_password_via_email)
    # The recovery key was burned when it verified (recover-account); the person's other keys stay valid.
    developer.updated_at = datetime.now(timezone.utc)
    # AL-2: recovery-based password set revokes all live sessions.
    developer.token_version = (developer.token_version or 0) + 1

    try:
        db.add(developer)
        await db.commit()
        logger.info(f"Password updated and recovery key invalidated for developer {developer_id}.")
        return {"message": "Password updated successfully. Please login with your new password."}
    except Exception as e:
        await db.rollback()
        logger.exception(f"Database error setting new password for developer {developer_id}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update password."
        )


@router.post("/refresh", response_model=schemas.Token, summary="Refresh access token")
async def refresh_access_token(
    refresh_token: str = Body(..., embed=True, description="The refresh token"),
    db: AsyncSession = Depends(get_db)
):
    """
    Refresh the access token using a valid refresh token.

    Validates the refresh JWT, verifies the developer still exists,
    and issues a new access token + rotated refresh token.
    """
    # Validate the refresh token JWT
    developer_id = security.validate_refresh_token(refresh_token)
    if developer_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Verify developer still exists and is active
    result = await db.execute(
        select(models.Developer).where(models.Developer.id == developer_id)
    )
    developer = result.scalar_one_or_none()
    if not developer:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Developer account not found",
        )

    # RA6 (2026-07-24): the refresh path skipped the suspended/deleted gate — a
    # suspended developer could keep minting fresh access tokens indefinitely.
    # Mirror get_current_developer's checks here so suspension actually bites.
    if getattr(developer, "is_suspended", False):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Developer account is suspended")
    if getattr(developer, "deleted_at", None) is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Developer account not found")

    # AL-3 (RA5 refresh half): a refresh token carrying a stale `tv` is dead —
    # password change / logout / admin-suspend revoke refresh tokens too.
    # (Refresh tokens minted before 0125 carry no `tv` and are grandfathered
    # until their 7-day expiry.)
    try:
        _rt = jwt.decode(refresh_token, security.SECRET_KEY, algorithms=[security.ALGORITHM])
        _rt_tv = _rt.get("tv")
    except JWTError:
        _rt_tv = None
    if _rt_tv is not None and int(_rt_tv) != int(developer.token_version or 0):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has been revoked",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Issue new access token (AL-1: revocable via token_version)
    access_token_expires = timedelta(minutes=security.ACCESS_TOKEN_EXPIRE_MINUTES)
    new_access_token = security.create_access_token(
        data={"sub": str(developer.id)},
        expires_delta=access_token_expires,
        token_version=developer.token_version or 0,
    )

    # Rotate refresh token. Note: with a single token_version we can't invalidate
    # ONLY the old refresh on rotation (both share the current tv) — that's the
    # accepted trade of the token_version model; the security guarantee that
    # matters (password change / logout / suspend kill ALL refresh tokens) holds.
    new_refresh_token = security.create_refresh_token(
        developer.id, token_version=developer.token_version or 0
    )

    logger.info(f"Token refreshed for developer ID: {developer.id}")

    return schemas.Token(
        access_token=new_access_token,
        token_type="bearer",
        expires_in=security.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        refresh_token=new_refresh_token
    )


# --- ADDED: Agent OAuth 2.0 Token Endpoint ---
@router.post(
    "/agent/token",
    response_model=schemas.Token,
    summary="Agent Token (OAuth2 Client Credentials)",
    responses={
        status.HTTP_200_OK: {"description": "Successful authentication, returns access token."},
        status.HTTP_401_UNAUTHORIZED: {"description": "Invalid client credentials."},
        status.HTTP_403_FORBIDDEN: {"description": "Valid credentials, but the agent is suspended or revoked."},
    }
)
async def agent_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db)
):
    """
    OAuth 2.0 Client Credentials flow for agents.
    
    Agents authenticate using their client_id (as username) and client_secret (as password).
    Returns a JWT access token containing the agent's DID in the 'sub' claim.
    
    Note: Using OAuth2PasswordRequestForm for compatibility, but interpreting fields as:
    - username: client_id
    - password: client_secret
    """
    logger.info(f"Agent token request for client_id: {form_data.username}")
    
    # Verify agent credentials: the SECRET first, then the status (§TWOAGENT: a suspended agent is told so, but only
    # once it proved its secret — a client_id alone learns nothing about an agent's standing).
    agent, why = await agent_crud.agent_credentials_status(
        db=db,
        client_id=form_data.username,  # username field holds client_id
        client_secret=form_data.password  # password field holds client_secret
    )
    if why == "suspended":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=("This agent is suspended by its registry. Its credentials are valid, but it cannot act until "
                    "the registry's operator reinstates it; its owner can see the enforcement status in the console."),
        )
    if why == "revoked":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This agent has been revoked by its registry and can no longer authenticate.",
        )

    if not agent:
        logger.warning(f"Agent authentication failed for client_id: {form_data.username}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid client credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Create JWT with agent's DID as subject. D6-281: bound to the credential it was minted from (`cv`), so resetting or
    # rotating the credential ends it at once (security.agent_token_refusal), not when it expires.
    access_token_expires = timedelta(minutes=security.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = security.create_access_token(
        data=security.agent_token_claims(agent),
        expires_delta=access_token_expires
    )
    
    logger.info(f"Agent authentication successful for DID: {agent.did} (client_id: {agent.client_id})")
    return schemas.Token(
        access_token=access_token,
        token_type="bearer",
        expires_in=security.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )
# --- END ADDED ---


# API Key Management Endpoints
@router.post("/api-keys", response_model=schemas.NewApiKeyResponse, summary="Generate API Key")
async def create_api_key(
    payload: Union[str, schemas.ApiKeyCreateRequest] = Body(
        ...,
        description=(
            "Either the legacy BARE JSON STRING (the key name) or "
            "{key_name, scopes?, expires_in_days?}."
        ),
    ),
    authorization: Optional[str] = Header(None),
    current_developer: models.Developer = Depends(security.get_current_developer),
    db: AsyncSession = Depends(get_db)
):
    """
    Generate a new API key for programmatic access. The plain key (`avreg_...`) is returned once and cannot be
    retrieved again; it is stored hashed. The body is either a bare JSON string (the key name) or {key_name,
    scopes?, expires_in_days?}: scopes default to ["*"] (full developer authority), and the key expires after
    `API_KEY_DEFAULT_TTL_DAYS` days (365 by default) unless expires_in_days says otherwise (0: never). The answer
    includes `expires_at`. An API key that creates a key needs the `keys:manage` scope and cannot give the new key a
    scope it does not hold itself.

    \f
    Generates a new API key for programmatic access.
    Returns the key only once - it cannot be retrieved again.
    Key is stored hashed in the developer_api_keys table.

    AL-4 (2026-07-24): new keys may be minted with narrower `scopes` (default
    ['*'] = full developer authority) and carry a forced-rotation `expires_at`
    (default from API_KEY_DEFAULT_TTL_DAYS; pass expires_in_days=0 for a
    non-expiring key). The response now surfaces `expires_at`.

    BODY SHAPE (2026-07-24, caught on the frame-c canary): AL-4 first expressed
    the three fields as three `Body(...)` params, which flips FastAPI into
    embedded mode and makes `{"key_name": ...}` mandatory. Every existing caller
    posts a BARE JSON STRING instead — the FE Settings view
    (`JSON.stringify(desc)`) and the MCP `createApiKey` tool (`json=key_name`) —
    so that shape 422'd them both, i.e. it would have broken API-key creation,
    including the flow used to mint MCP bridge keys. The union below accepts
    either form.
    """
    if isinstance(payload, str):
        key_name, scopes, expires_in_days = payload, None, None
    else:
        key_name = payload.key_name
        scopes = payload.scopes
        expires_in_days = payload.expires_in_days

    # AL-4: real scope enforcement (privilege-escalation guard) — a *scoped* API
    # key cannot mint new keys unless it carries `keys:manage` (or `*`). Developer
    # JWT sessions and grandfathered ['*'] keys are unaffected (they satisfy `*`),
    # so nothing breaks; only a deliberately-narrowed key is constrained. This
    # gives `scopes` a live consumer instead of being a stored-but-ignored field.
    if authorization:
        _parts = authorization.split()
        if len(_parts) == 2 and _parts[0].lower() == "bearer" and _parts[1].startswith("avreg_"):
            # D6-715: the one scope lookup, failing CLOSED (a row it cannot read is no scope; a database error is 503).
            try:
                _scopes, _ = await security.presented_key_scopes(db, _parts[1])
            except SQLAlchemyError as e:
                raise security._credential_store_unavailable(e) from e
            if "*" not in _scopes and "keys:manage" not in _scopes:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="This API key lacks the 'keys:manage' scope required to create API keys.",
                )
            # §POCKETPAIR (2026-10-15): and never a key broader than the one asking. A 'keys:manage' key could mint a
            # '*' key here (the new key's scopes were never compared with the presenting key's): full authority from a
            # key that had none.
            if "*" not in _scopes and not all(s in _scopes for s in (scopes or ["*"])):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="An API key cannot create a key with scopes it does not hold itself.",
                )

    # Generate secure API key with avreg_ prefix (matches validator in crud/developer.py)
    api_key = security.generate_secure_api_key()

    # Hash it for storage
    hashed = security.hash_api_key(api_key)

    # AL-4: resolve the forced-rotation expiry. Per-key override wins; else the
    # server default; 0 (either place) → non-expiring.
    _ttl_days = expires_in_days if expires_in_days is not None else int(getattr(settings, "API_KEY_DEFAULT_TTL_DAYS", 365) or 0)
    _expires_at = (datetime.now(timezone.utc) + timedelta(days=_ttl_days)) if _ttl_days and _ttl_days > 0 else None

    # Save to DB — this is the real implementation
    # §MCPTEST30 (V0526): the id is read now; after a failed save the rollback has expired the developer row, and reading
    # current_developer.id there raised MissingGreenlet (a 500 in place of the refusal)
    _dev_id = current_developer.id
    db_key = await developer_crud.create_api_key(
        db=db,
        developer_id=_dev_id,
        prefix="avreg_",
        hashed_key=hashed,
        description=key_name,
        key_sha256=security.api_key_lookup_hash(api_key),
        scopes=(scopes or ["*"]),
        expires_at=_expires_at,
    )

    if not db_key:
        logger.error(f"Failed to save API key for developer {_dev_id}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create API key"
        )

    logger.info(f"API key '{key_name}' created and saved for developer {current_developer.id} (key id: {db_key.id})")

    # §NOTIFV2 (2026-07-27): a new API key is a new way to act as you, so the account owner is
    # told out-of-band. Desktop-only by catalog default (you are usually at a keyboard when you
    # mint one). Fire-and-forget: minting must never fail on a notification.
    try:
        import asyncio as _aio
        from agentvault_registry.background_tasks.push_notify import notify
        _aio.create_task(notify(
            "security.api_key_created", [current_developer.id],
            title="API key created",
            message=f"New API key '{key_name}' ({db_key.key_prefix}...) was created on your account.",
            tags="key", priority="high", click="/ui/#/settings"))
    except Exception:  # noqa: BLE001
        logger.debug("security.api_key_created notify skipped", exc_info=True)

    return schemas.NewApiKeyResponse(
        plain_api_key=api_key,
        api_key_info=schemas.ApiKeyRead(
            id=db_key.id,
            key_prefix=db_key.key_prefix,
            description=db_key.description,
            is_active=db_key.is_active,
            created_at=db_key.created_at,
            last_used_at=db_key.last_used_at,
            scopes=db_key.scopes,
            expires_at=db_key.expires_at,
        )
    )


@router.get("/api-keys", response_model=List[schemas.ApiKeyRead], summary="List API Keys")
async def list_api_keys(
    current_developer: models.Developer = Depends(security.get_current_developer),
    db: AsyncSession = Depends(get_db)
):
    """Lists all API keys for the current developer."""
    from sqlalchemy import select
    result = await db.execute(
        select(models.DeveloperApiKey).where(
            models.DeveloperApiKey.developer_id == current_developer.id,
            models.DeveloperApiKey.is_active == True,
        ).order_by(models.DeveloperApiKey.created_at.desc())
    )
    keys = result.scalars().all()
    return [
        {
            "id": k.id,
            "key_prefix": k.key_prefix,
            "description": k.description,
            "is_active": k.is_active,
            "created_at": k.created_at,
            "last_used_at": k.last_used_at,
            # §FEPARITY-1: ApiKeyRead has declared these since AL-4, but this
            # hand-built dict silently dropped them — the field-mapper class —
            # so scopes/expiry could never render anywhere downstream.
            "scopes": getattr(k, "scopes", None),
            "expires_at": getattr(k, "expires_at", None),
        }
        for k in keys
    ]


@router.delete("/api-keys/{key_id}", summary="Revoke API Key")
async def revoke_api_key(
    key_id: int,
    current_developer: models.Developer = Depends(security.get_current_developer),
    db: AsyncSession = Depends(get_db)
):
    """Revokes an API key immediately."""
    from sqlalchemy import select
    result = await db.execute(
        select(models.DeveloperApiKey).where(
            models.DeveloperApiKey.id == key_id,
            models.DeveloperApiKey.developer_id == current_developer.id,
        )
    )
    key = result.scalar_one_or_none()
    if not key:
        raise HTTPException(status_code=404, detail="API key not found or not owned by you")
    key.is_active = False
    # §POCKETPAIR (2026-10-15): a phone paired with this key stops receiving pushes with it.
    from agentvault_registry.services.device_key_link import disable_devices_for_key
    _devices = await disable_devices_for_key(db, current_developer.id, key_id)
    await db.commit()
    logger.info(f"API key {key_id} revoked by developer {current_developer.id} (paired devices disabled: {_devices})")
    return {"message": "API key revoked successfully", "devices_disabled": _devices}
