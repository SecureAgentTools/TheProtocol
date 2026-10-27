"""
Operator Application endpoints — receives registry license applications
from the landing page form, persists to DB, and sends notification emails.

Public:
    POST /api/v1/operator-applications — Submit an application (no auth)

Authenticated Developer:
    POST /api/v1/operators/activate            — Activate with one-time code (provisions bundle)

Operator:
    GET  /api/v1/operators/my-bundle              — Download own provisioned bundle
    GET  /api/v1/operators/my-status               — Check operator status
    POST /api/v1/operators/request-revocation       — Request self-revocation

Admin:
    GET  /api/v1/admin/operator-applications              — List applications
    GET  /api/v1/admin/operator-applications/{id}          — Get single application
    POST /api/v1/admin/operator-applications/{id}/approve  — Approve + generate activation code
    POST /api/v1/admin/operator-applications/{id}/reject   — Reject application
    GET  /api/v1/admin/operator-applications/{id}/bundle   — Download any bundle (admin)
    POST /api/v1/admin/operator-applications/{id}/revoke-operator   — Cascade revoke
    POST /api/v1/admin/operator-applications/{id}/suspend-operator  — Suspend (reversible)
    POST /api/v1/admin/operator-applications/{id}/reinstate-operator — Reinstate
"""
import asyncio
import hashlib
import logging
import os
import secrets
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status, Security
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry import models, schemas
from agentvault_registry.database import get_db
from agentvault_registry import security
from agentvault_registry.security import get_current_developer
from agentvault_registry.event_emitter import get_event_emitter
from agentvault_registry.services.cloud_provisioner import _safe_name
from agentvault_registry.core.mainframe_gate import require_mainframe_only

logger = logging.getLogger(__name__)

# §pass66 (2026-05-22) — Operator applications are accepted ONLY by sovereign
# mainframes. A cloud-operator is a downstream node; it doesn't issue licenses
# or onboard new operators. Router-level gate so every endpoint here returns
# 503 with the clear mainframe-only message when invoked on a cloud-op.

async def _read_es_health(base: str) -> dict:
    """GET <event store>/health the way the emitter dials the store: aiohttp with the ES ssl context when the URL is
    https (the frame's own SVID + bundle), plain otherwise. Raises on any failure; the caller labels it."""
    import aiohttp
    from ..es_ssl_helper import get_es_ssl_context
    ctx = get_es_ssl_context() if base.startswith("https://") else None
    connector = aiohttp.TCPConnector(ssl=ctx) if ctx else None
    async with aiohttp.ClientSession(connector=connector, timeout=aiohttp.ClientTimeout(total=3)) as s:
        async with s.get(f"{base}/health") as r:
            if r.status != 200:
                raise RuntimeError(f"event store /health answered {r.status}")
            body = await r.json(content_type=None)
    return body if isinstance(body, dict) else {}


async def _event_store_mtls_required() -> tuple:
    """§SOVKIT (2026-09-14) — whether the EVENT STORE requires mTLS, read from the store itself.

    Frame Management used to compute `license_auth_available` from THIS registry's `EVENTSTORE_MTLS_REQUIRED` env,
    a second copy of a fact that lives on the event store (agentvault2-85's S0 risk 7: the copy keeps saying true
    after the store flips). The store's `GET /health` carries `mtls_required` since its :sovkit1 image; an older
    store answers without the field and the env copy stands in, NAMED as such in `mtls_source`. Never raises: a
    store that does not answer leaves the env copy, labelled. Returns (mtls_required, source).
    """
    env_copy = os.getenv("EVENTSTORE_MTLS_REQUIRED", "false").lower() == "true"
    base = (os.getenv("EVENT_STORE_URL", "") or "").strip().rstrip("/")
    if not base:
        return env_copy, "registry-env (no EVENT_STORE_URL)"
    try:
        body = await _read_es_health(base)
    except Exception:  # noqa: BLE001 — the copy stands in, and says so
        return env_copy, "registry-env (the store did not answer)"
    if isinstance(body.get("mtls_required"), bool):
        return body["mtls_required"], "event-store:/health"
    return env_copy, "registry-env (the store reports no mtls_required)"

router = APIRouter(
    prefix="/api/v1",
    tags=["Operator Applications"],
    dependencies=[Depends(require_mainframe_only)],
)
# §RATEFIX: THE shared, Redis-backed limiter — the same object main.py puts on
# app.state, so these decorations are both enforced and shared across workers.
# A router-local Limiter() would be in-memory per worker AND invisible to the
# middleware; that is what made all 65 limits here meaningless.
from agentvault_registry.middleware.rate_limiter import shared_limiter as limiter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_OPS_NOTIFICATION_ADDRESS = "operators@theprotocol.cloud"


def _send_themed_notification(
    *,
    subject: str,
    template: str,
    context: Dict[str, Any],
    theme: str = "neural",
    to_address: Optional[str] = None,
) -> None:
    """Non-blocking themed-email dispatch.

    Schedules the send on the running loop without awaiting (legacy callsites
    are sync). Falls through to a synchronous send when no loop is running
    (tests). Best-effort: never raises.
    """
    from agentvault_registry.email_utils import send_themed_email
    recipient = to_address or _OPS_NOTIFICATION_ADDRESS

    async def _dispatch() -> None:
        try:
            await send_themed_email(
                subject=subject,
                recipients=[recipient],
                template=template,
                context=context,
                theme=theme,  # type: ignore[arg-type]
            )
        except Exception as exc:
            logger.error(
                f"Failed to send operator notification (template={template}) to {recipient}: {exc}"
            )

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_dispatch())
    except RuntimeError:
        asyncio.run(_dispatch())


# ---------------------------------------------------------------------------
# Option D-light helper (2026-04-21): derive the operator DID used on a
# FederationLicense row from an OperatorApplication. Centralized so
# suspend / reinstate / revoke all agree on the same derivation.
# ---------------------------------------------------------------------------

def _derive_operator_did(app_record: models.OperatorApplication) -> str:
    """Return the operator DID used on the FederationLicense row.

    Two conventions exist in the schema:
      * Cloud-hosted (cloud_provisioner.py L250): did:theprotocol:cloud:<name>
      * VPS / self-hosted (legacy operator_provisioner flow):
        did:theprotocol:operator:<name>

    Running operators in production are uniform under the cloud convention;
    the operator: prefix appears in legacy (stopped) rows. Branching on
    cloud_hosted keeps both paths covered so suspend/reinstate/revoke all
    find the correct license row.
    """
    docker_username = app_record.docker_registry_username
    operator_name = (
        docker_username.removeprefix("operator-") if docker_username
        else "".join(
            c if c.isalnum() or c == "-" else "-"
            for c in (app_record.name or "").lower().strip()
        ).strip("-")[:40]
    )
    prefix = "cloud" if getattr(app_record, "cloud_hosted", False) else "operator"
    return f"did:theprotocol:{prefix}:{operator_name}"


async def _sync_operator_licence_status(fed_license: Optional[models.FederationLicense], op_status: str) -> None:
    """The store's federation_operators row follows the licence (§F6 stage 5, 2026-09-27).

    The licence routes (federation_licenses.py) sync every status change they make; these operator-level cascades
    (revoke, suspend, reinstate) changed the licence in THIS database only, so the store kept a revoked operator's row
    "active" (measured on sbx-beta: b1opd, provisioned through the frame runner on V0473, revoked, its row still active).
    Called after the commit, best-effort like every licence sync: the sync logs a refusal itself, and nothing here can
    undo the revoke."""
    if fed_license is None:
        return
    try:
        from agentvault_registry.routers.federation_licenses import _sync_license_to_eventstore
        await _sync_license_to_eventstore(
            license_id=fed_license.id,
            operator_name=fed_license.operator_name,
            license_key_hash=fed_license.license_key_hash,
            op_status=op_status,
        )
    except Exception as exc:  # noqa: BLE001  the revoke/suspend/reinstate already happened here
        logger.warning(f"[OperatorLicence] syncing '{op_status}' for licence {fed_license.id} to the store failed "
                       f"(non-fatal): {type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------
# Public endpoint (no auth required)
# ---------------------------------------------------------------------------

@router.post("/operator-applications", response_model=schemas.OperatorApplicationRead)
@limiter.limit("5/hour")
async def submit_operator_application(
    request: Request,
    application: schemas.OperatorApplicationCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    Submit an operator registry license application from the landing page.
    Persists to DB, sends a notification email, and returns the created record.
    """
    # §LEGALKIT: Operator Terms § 1.2 ("acceptance occurs at operator activation") was never asked or
    # recorded. The form now carries the checkbox; a client that sends none is refused, like registration.
    if not getattr(application, "accept_operator_terms", False):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="You must accept the Federation Operator Terms to apply.",
        )
    # SEC-21 (2026-10-17): a name the network reserves never becomes an operator's (core/operator_names), refused before
    # anything is stored
    from ..core.operator_names import reserved_operator_name
    _reserved = reserved_operator_name(application.name)
    if _reserved:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"The operator name '{application.name}' is reserved ({_reserved}). Choose another name.",
        )
    # §FESUITE V0595: the configuration the applicant chose, against the catalog (services/env_catalog.py): an
    # operator chooses only operator-scope settings; a frame-scope one, an unknown key or an option the catalog does
    # not offer is refused with the reason, never silently dropped
    from ..services.env_catalog import validate_choices as _validate_env
    env_choices, env_errors = _validate_env(getattr(application, "env_choices", None) or {}, "operator")
    if env_errors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Some of the chosen settings cannot be applied: " + "; ".join(env_errors),
        )
    # SEC-23: nor a name the network would confuse with a registry this one already knows (the first read of the
    # database: every refusal above needs none)
    from ..core.operator_names import colliding_peer_name
    _collides = await colliding_peer_name(db, application.name)
    if _collides:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"The operator name '{application.name}' would be confused with {_collides}. Choose another name.",
        )
    # Check for duplicate pending application by email
    existing = await db.execute(
        select(models.OperatorApplication).where(
            models.OperatorApplication.email == application.email,
            models.OperatorApplication.status == "pending",
        )
    )
    if existing.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A pending application for this email already exists.",
        )

    # Auto-link developer_id if email matches an existing Developer
    developer_id = None
    dev_result = await db.execute(
        select(models.Developer).where(models.Developer.email == application.email)
    )
    dev = dev_result.scalars().first()
    if dev:
        developer_id = dev.id

    # Create and persist the application
    app_record = models.OperatorApplication(
        id=str(uuid.uuid4()),
        developer_id=developer_id,
        name=application.name,
        email=application.email,
        organization=application.organization or None,
        deployment=application.deployment,
        experience=application.experience,
        use_case=application.use_case or None,
        status="pending",
        env_choices=env_choices,
    )
    db.add(app_record)
    await db.flush()
    from ..services.legal_acceptance import SUBJECT_OPERATOR_APPLICATION as _SUBJ, record_acceptance as _rec
    await _rec(db, document="operators", subject_kind=_SUBJ, subject_id=app_record.id,
               via="operator_application", developer_id=developer_id, request=request)
    await db.commit()
    await db.refresh(app_record)

    logger.info(f"Operator application received: {application.name} ({application.email})")

    # Send notification email (non-blocking — log on failure)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    _send_themed_notification(
        subject=f"Registry License Application \u2014 {application.name}",
        template="operator_application_received",
        context={
            "name": application.name,
            "email": application.email,
            "organization": application.organization or "Not specified",
            "deployment": application.deployment,
            "experience": application.experience,
            "use_case": application.use_case,
            # §FESUITE V0595: the chosen configuration, for the reviewer ("" = everything inherited from the frame)
            "env_choices": ", ".join(f"{k}={v}" for k, v in sorted(env_choices.items())) or "inherited from the frame",
            "developer_linked": (
                f"Yes (id={developer_id})" if developer_id else "No"
            ),
            "timestamp": timestamp,
        },
        theme="neural",
    )

    return app_record


# ---------------------------------------------------------------------------
# Admin endpoints (require_admin_flag("admin_federation"))
# ---------------------------------------------------------------------------

@router.get(
    "/admin/operator-applications",
)
async def list_operator_applications(
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status (pending/approved/rejected)"),
    db: AsyncSession = Depends(get_db),
    admin: models.Developer = Security(security.require_admin_flag("admin_federation")),
):
    """List all operator applications. Optional status filter."""
    query = select(models.OperatorApplication).order_by(
        models.OperatorApplication.created_at.desc()
    )
    if status_filter:
        query = query.where(models.OperatorApplication.status == status_filter)

    result = await db.execute(query)
    mtls_enforced, mtls_source = await _event_store_mtls_required()
    return {
        "applications": [schemas.OperatorApplicationRead.model_validate(app) for app in result.scalars().all()],
        "config": {
            "mtls_enforced": mtls_enforced,
            "license_auth_available": not mtls_enforced,
            # §SOVKIT (2026-09-14): where the answer came from, so a reader can tell the store's word from the env copy
            "mtls_source": mtls_source,
        }
    }


@router.get(
    "/admin/operator-applications/{application_id}",
    response_model=schemas.OperatorApplicationRead,
)
async def get_operator_application(
    application_id: str,
    db: AsyncSession = Depends(get_db),
    admin: models.Developer = Security(security.require_admin_flag("admin_federation")),
):
    """Get a single operator application by ID."""
    result = await db.execute(
        select(models.OperatorApplication).where(
            models.OperatorApplication.id == application_id
        )
    )
    app_record = result.scalars().first()
    if not app_record:
        raise HTTPException(status_code=404, detail="Application not found.")
    return app_record


@router.post(
    "/admin/operator-applications/{application_id}/approve",
)
async def approve_operator_application(
    application_id: str,
    review: schemas.OperatorApplicationReview,
    db: AsyncSession = Depends(get_db),
    admin: models.Developer = Security(security.require_admin_flag("admin_federation")),
):
    """
    Approve an operator application. Generates a one-time activation code that
    the applicant uses to self-activate via POST /api/v1/operators/activate.

    No developer account is created or modified at this stage -- the applicant
    must register (or already have an account) and activate with their own
    credentials. Bundle provisioning is deferred to the activation step.
    """
    result = await db.execute(
        select(models.OperatorApplication).where(
            models.OperatorApplication.id == application_id
        )
    )
    app_record = result.scalars().first()
    if not app_record:
        raise HTTPException(status_code=404, detail="Application not found.")

    if app_record.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Application is already '{app_record.status}', only pending applications can be approved.",
        )
    # SEC-21: an application filed under a reserved name (one stored before the rule) is not approved
    from ..core.operator_names import reserved_operator_name
    _reserved = reserved_operator_name(app_record.name)
    if _reserved:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(f"This application's operator name '{app_record.name}' is reserved ({_reserved}), so it cannot be "
                    f"approved. Reject it and ask the applicant to apply under another name. Nothing was changed."),
        )
    # SEC-23: nor one the network would confuse with a registry this one already knows (a peer added since it applied)
    from ..core.operator_names import colliding_peer_name
    _collides = await colliding_peer_name(db, app_record.name)
    if _collides:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(f"This application's operator name '{app_record.name}' would be confused with {_collides}, so it "
                    f"cannot be approved. Reject it and ask the applicant to apply under another name. Nothing was "
                    f"changed."),
        )

    # Generate activation code
    activation_code = "op_activate_" + secrets.token_hex(32)
    activation_code_hash = hashlib.sha256(activation_code.encode()).hexdigest()

    # Update the application record
    now = datetime.now(timezone.utc)
    app_record.status = "approved"
    app_record.reviewed_by = admin.id
    app_record.reviewed_at = now
    app_record.review_notes = review.notes or None
    app_record.activation_code_hash = activation_code_hash
    app_record.activation_code_expires_at = now + timedelta(days=7)

    await db.commit()
    await db.refresh(app_record)

    logger.info(f"Operator application approved: {app_record.name} ({app_record.email}) by admin {admin.id}")

    # Admin notification (no activation code -- admin can see it in the API response)
    _send_themed_notification(
        subject=f"Operator Approved \u2014 {app_record.name}",
        template="admin_notice",
        context={
            "kicker_label": "OPERATOR APPROVED",
            "headline_text": f"Approved \u2014 {app_record.name}",
            "body_text": (
                f"Operator application for {app_record.name} ({app_record.email}) "
                f"has been APPROVED by {admin.name}.\n\n"
                f"An activation code has been generated and sent to the applicant. "
                f"The code expires in 7 days."
            ),
        },
        theme="neural",
    )

    # Applicant notification with activation code
    from agentvault_registry.core import release_channel as _rc
    _send_themed_notification(
        subject=f"Your Operator Application Has Been Approved \u2014 TheProtocol",
        template="operator_application_approved",
        context={"activation_code": activation_code, **_rc.mail_context()},
        theme="neural",
        to_address=app_record.email,
    )

    # Return the application record -- activation code is shown ONCE in this response
    # so the admin can also see it. We attach it transiently (not persisted as plain text).
    response = schemas.OperatorApplicationRead.model_validate(app_record)
    # Include activation_code in the response dict for admin visibility
    response_dict = response.model_dump()
    response_dict["activation_code"] = activation_code
    return response_dict


@router.post(
    "/admin/operator-applications/{application_id}/reject",
    response_model=schemas.OperatorApplicationRead,
)
async def reject_operator_application(
    application_id: str,
    review: schemas.OperatorApplicationReview,
    db: AsyncSession = Depends(get_db),
    admin: models.Developer = Security(security.require_admin_flag("admin_federation")),
):
    """Reject an operator application."""
    result = await db.execute(
        select(models.OperatorApplication).where(
            models.OperatorApplication.id == application_id
        )
    )
    app_record = result.scalars().first()
    if not app_record:
        raise HTTPException(status_code=404, detail="Application not found.")

    if app_record.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Application is already '{app_record.status}', only pending applications can be rejected.",
        )

    # Update the application record
    now = datetime.now(timezone.utc)
    app_record.status = "rejected"
    app_record.reviewed_by = admin.id
    app_record.reviewed_at = now
    app_record.review_notes = review.notes or None

    await db.commit()
    await db.refresh(app_record)

    logger.info(f"Operator application rejected: {app_record.name} ({app_record.email}) by admin {admin.id}")

    return app_record


# ---------------------------------------------------------------------------
# Operator bundle download (authenticated operator)
# ---------------------------------------------------------------------------

@router.get("/operators/my-bundle")
async def download_operator_bundle(
    developer: models.Developer = Security(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """
    Download the provisioned operator bundle (tar.gz).
    Requires the caller to be an approved federation operator.
    Limited to 3 downloads; after that, ask an administrator to provision it again.
    """
    if not developer.is_federation_operator:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only approved operators can download bundles.",
        )

    # Find the approved application for this developer
    result = await db.execute(
        select(models.OperatorApplication).where(
            models.OperatorApplication.developer_id == developer.id,
            models.OperatorApplication.status == "approved",
        ).order_by(models.OperatorApplication.reviewed_at.desc())
    )
    app_record = result.scalars().first()

    if not app_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No approved operator application found for your account.",
        )

    if not app_record.bundle_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bundle has not been provisioned yet. Contact admin.",
        )

    bundle_file = Path(app_record.bundle_path)
    if not bundle_file.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bundle file not found on server. Contact admin for re-provisioning.",
        )

    # Check expiry
    now = datetime.now(timezone.utc)
    if app_record.bundle_expires_at and now > app_record.bundle_expires_at:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Bundle has expired. Contact admin for re-provisioning.",
        )

    # Check download limit
    if app_record.bundle_download_count >= 3:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Download limit reached (3 downloads). Contact admin for re-provisioning.",
        )

    # Increment download count
    app_record.bundle_download_count += 1
    await db.commit()

    logger.info(
        f"Operator bundle downloaded by developer {developer.id} "
        f"(application={app_record.id}, download #{app_record.bundle_download_count})"
    )

    # Stream the tar.gz file
    def _file_iterator():
        with open(bundle_file, "rb") as f:
            while chunk := f.read(65536):
                yield chunk

    filename = bundle_file.name
    return StreamingResponse(
        _file_iterator(),
        media_type="application/gzip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(bundle_file.stat().st_size),
        },
    )


# ---------------------------------------------------------------------------
# Admin bundle download (any application)
# ---------------------------------------------------------------------------

@router.get("/admin/operator-applications/{application_id}/bundle")
async def admin_download_bundle(
    application_id: str,
    admin: models.Developer = Security(security.require_admin_flag("admin_federation")),
    db: AsyncSession = Depends(get_db),
):
    """
    Admin endpoint: download any operator's provisioned bundle by application ID.
    No download-count limit for admins.
    """
    result = await db.execute(
        select(models.OperatorApplication).where(
            models.OperatorApplication.id == application_id
        )
    )
    app_record = result.scalars().first()

    if not app_record:
        raise HTTPException(status_code=404, detail="Application not found.")

    if not app_record.bundle_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bundle has not been provisioned for this application.",
        )

    bundle_file = Path(app_record.bundle_path)
    if not bundle_file.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bundle file not found on server filesystem.",
        )

    logger.info(
        f"Admin {admin.id} downloading bundle for application {application_id} "
        f"(operator: {app_record.name})"
    )

    def _file_iterator():
        with open(bundle_file, "rb") as f:
            while chunk := f.read(65536):
                yield chunk

    filename = bundle_file.name
    return StreamingResponse(
        _file_iterator(),
        media_type="application/gzip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(bundle_file.stat().st_size),
        },
    )


# ---------------------------------------------------------------------------
# f048: Admin lifecycle management (revoke / suspend / reinstate)
# ---------------------------------------------------------------------------

@router.post(
    "/admin/operator-applications/{application_id}/revoke-operator",
    response_model=schemas.OperatorApplicationRead,
)
async def revoke_operator_access(
    application_id: str,
    request_body: schemas.OperatorRevocationRequest,
    admin: models.Developer = Security(security.require_admin_flag("admin_federation")),
    db: AsyncSession = Depends(get_db),
):
    """
    Cascade-revoke an operator: ban SPIRE agent, delete entries, evict,
    remove Docker credentials, revoke federation license, mark developer as revoked.
    This is irreversible -- the operator must re-apply to regain access.
    """
    result = await db.execute(
        select(models.OperatorApplication).where(
            models.OperatorApplication.id == application_id
        )
    )
    app_record = result.scalars().first()
    if not app_record:
        raise HTTPException(status_code=404, detail="Application not found.")

    if app_record.status not in ("approved", "suspended"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Application status is '{app_record.status}'. Only approved or suspended operators can be revoked.",
        )

    # --- Run cascading revocation ---
    revoke_result = None
    fingerprint = app_record.spire_fingerprint
    docker_username = app_record.docker_registry_username

    # §OPPROV (2026-09-27): WHOSE NAME IS THIS. The name the operator's SPIRE entries were registered under: the pull
    # username activation wrote (operator-<name>), else the one slug rule the provisioner, the suspend and the rename all
    # use. This application HOLDS the name only when it was activated (activation registers the entries) and no other
    # live application holds it too: names were never unique, and revoking a second, never-activated "sbxop" must not
    # sweep the live sbxop's SPIFFE path, revoke its licence, or (through OperatorApplicationRevoked's reactor, which
    # matches the peer row by name) deactivate its federation peer. Read before anything is changed.
    operator_name = (docker_username.removeprefix("operator-") if docker_username
                     else _safe_name(app_record.name or ""))
    _namesakes = [] if not operator_name else [
        h for h in (await db.execute(
            select(models.OperatorApplication.id, models.OperatorApplication.name,
                   models.OperatorApplication.docker_registry_username).where(
                models.OperatorApplication.id != app_record.id,
                models.OperatorApplication.activated_at.isnot(None),
                models.OperatorApplication.status.in_(("approved", "suspended")),
            ))).all()
        if ((h.docker_registry_username or "").removeprefix("operator-") or _safe_name(h.name or "")) == operator_name]
    name_holder = app_record.activated_at is not None and not _namesakes
    _not_holder_why = "another live application holds the name" if _namesakes else "it was never activated"

    # The SPIRE half runs WITH OR WITHOUT a fingerprint. Without one it used to be skipped whole, and an operator whose
    # bundle failed after its entries were registered (wp62op on sbx-beta: the 640 template) kept its three
    # /operator/<name>/ entries through its revoke. The path is swept only by its holder; a node (a fingerprint) is always
    # this application's own. Off the event loop: the socket half is several docker execs, the runner half waits up to
    # 120 s on the runner, and both used to run inline in this handler.
    try:
        from agentvault_registry.services.operator_revoker import revoke_operator

        if not operator_name:
            logger.warning(f"No operator name derivable for application {application_id} -- skipping SPIRE revocation")
        elif not fingerprint and not name_holder:
            logger.warning(f"Application {application_id}: no SPIRE fingerprint, and the path /operator/{operator_name}/ "
                           f"is not this application's to sweep ({_not_holder_why}) -- skipping SPIRE revocation")
        else:
            if not fingerprint:
                logger.warning(f"No SPIRE fingerprint for application {application_id}: no node to ban; the entries "
                               f"under /operator/{operator_name}/ are still deleted")
            elif not name_holder:
                logger.warning(f"Application {application_id}: only its node's own entries are revoked; the path "
                               f"/operator/{operator_name}/ is not swept ({_not_holder_why})")
            revoke_result = await asyncio.to_thread(revoke_operator, operator_name, fingerprint or "",
                                                    request_body.reason, name_holder)
    except Exception as e:
        logger.error(
            f"Cascading revocation failed for application {application_id}: {e}",
            exc_info=True,
        )

    # --- Revoke federation license if it exists ---
    # Option D-light Phase D2c: widened lookup from status=="active" to
    # status!="revoked" so a previously-suspended license is also revoked
    # on operator termination (previously a suspended license could outlive
    # its operator, creating a drift state).
    # §OPPROV: only by the name's holder, since the licence is keyed by the name's DID; and bound before the block, which
    # left it unbound for an application with no developer (a "phantom" revoke), so the OperatorApplicationRevoked emit
    # below raised NameError inside its non-fatal except and the event this route promises "unconditionally" never went.
    fed_license = None
    operator_did = _derive_operator_did(app_record)
    if app_record.developer_id and not name_holder:
        logger.warning(f"Application {application_id}: its licence and its developer's operator status are left as they "
                       f"are ({_not_holder_why}); the DID {operator_did} is not this application's alone")
    revoked_licence = None
    if app_record.developer_id and name_holder:
        dev_result = await db.execute(
            select(models.Developer).where(models.Developer.id == app_record.developer_id)
        )
        developer = dev_result.scalars().first()

        if developer:
            license_result = await db.execute(
                select(models.FederationLicense).where(
                    models.FederationLicense.operator_did == operator_did,
                    models.FederationLicense.status != "revoked",
                )
            )
            fed_license = license_result.scalars().first()
            if fed_license:
                revoked_licence = fed_license
                prior_status = fed_license.status
                fed_license.status = "revoked"
                fed_license.revoked_at = datetime.now(timezone.utc)
                fed_license.revoked_reason = f"Operator revoked: {request_body.reason}"
                # Clear suspension metadata if we're transitioning from suspended → revoked
                fed_license.suspended_at = None
                fed_license.suspended_by = None
                fed_license.suspended_reason = None
                logger.info(
                    f"Federation license revoked for {operator_did} "
                    f"(license={fed_license.id}, prior_status={prior_status})"
                )

            # Mark developer as revoked
            developer.is_federation_operator = False
            developer.federation_operator_status = "revoked"

    # --- Update application record ---
    now = datetime.now(timezone.utc)
    app_record.status = "revoked"
    app_record.revoked_at = now
    app_record.revoked_by = admin.id
    app_record.revoked_reason = request_body.reason
    # f050: Nullify pull token — token auth server will reject all future requests
    app_record.docker_pull_token_hash = None
    app_record.docker_pull_token_prefix = None
    app_record.docker_pull_token_issued_at = None

    await db.commit()
    await db.refresh(app_record)
    await _sync_operator_licence_status(revoked_licence, "revoked")

    logger.info(
        f"Operator application revoked: {app_record.name} ({app_record.email}) "
        f"by admin {admin.id} -- reason: {request_body.reason}"
    )

    # 2026-04-28: emit OperatorApplicationRevoked unconditionally so the cascade
    # reactor flips peer_registries to INACTIVE even for "phantom" operators
    # that never had a federation_license issued (administratively-approved
    # apps that didn't go through cloud_provisioner). The license-revoke path
    # above only emits FederationLicenseSuspended when a license existed; this
    # event closes the gap so phantom-revoke gets a full audit trail + cascade.
    try:
        await get_event_emitter().emit(
            event_type="OperatorApplicationRevoked",
            aggregate_id=f"operator_application:{app_record.id}",
            aggregate_type="OperatorApplication",
            data={
                "application_id": app_record.id,
                "operator_name": app_record.name,
                "operator_did": operator_did,
                "had_license": fed_license is not None,
                "license_id": fed_license.id if fed_license else None,
                # §OPPROV: False = this application does not hold its name (never activated, or another live application
                # holds it), so the peer row named like it is not its own: the cascade reactor leaves it alone
                "name_holder": name_holder,
                "reason": request_body.reason,
                "revoked_by": admin.id,
                "revoked_at": now.isoformat(),
            },
        )
    except Exception as e:
        logger.warning(
            f"[Revoke] OperatorApplicationRevoked emit failed (non-fatal): {e}"
        )

    # Send revocation email to the operator
    _send_themed_notification(
        subject=f"Registry License Revoked — {app_record.name}",
        template="operator_revoked",
        context={"name": app_record.name, "reason": request_body.reason},
        theme="sovereign",
        to_address=app_record.email,
    )

    # Also notify the admin channel
    admin_rows = [
        ("Operator", f"{app_record.name} ({app_record.email})"),
        ("Revoked by", f"{admin.name} (id={admin.id})"),
        ("Reason", request_body.reason),
    ]
    if revoke_result:
        admin_rows.extend([
            ("SPIRE agent banned", str(revoke_result.spire_agent_banned)),
            ("SPIRE entries deleted", str(revoke_result.spire_entries_deleted)),
            ("SPIRE agent evicted", str(revoke_result.spire_agent_evicted)),
            ("Docker creds removed", str(revoke_result.docker_creds_removed)),
            ("Errors", str(len(revoke_result.errors))),
        ])
    error_notice = (
        f"Error details: {'; '.join(revoke_result.errors)}"
        if revoke_result and revoke_result.errors
        else None
    )
    _send_themed_notification(
        subject=f"[ADMIN] Operator Revoked — {app_record.name}",
        template="admin_notice",
        context={
            "kicker_label": "OPERATOR REVOKED",
            "headline_text": f"Operator Revoked — {app_record.name}",
            "rows": admin_rows,
            "notice_text": error_notice,
        },
        theme="sovereign",
    )

    return app_record


@router.post(
    "/admin/operator-applications/{application_id}/suspend-operator",
    response_model=schemas.OperatorApplicationRead,
)
async def suspend_operator(
    application_id: str,
    request_body: schemas.OperatorRevocationRequest,
    admin: models.Developer = Security(security.require_admin_flag("admin_federation")),
    db: AsyncSession = Depends(get_db),
):
    """
    Suspend an operator (reversible). Does NOT revoke SPIRE or Docker credentials.
    The operator's access is paused but can be reinstated by an admin.
    """
    result = await db.execute(
        select(models.OperatorApplication).where(
            models.OperatorApplication.id == application_id
        )
    )
    app_record = result.scalars().first()
    if not app_record:
        raise HTTPException(status_code=404, detail="Application not found.")

    if app_record.status != "approved":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Application status is '{app_record.status}'. Only approved operators can be suspended.",
        )

    # Update developer status
    if app_record.developer_id:
        dev_result = await db.execute(
            select(models.Developer).where(models.Developer.id == app_record.developer_id)
        )
        developer = dev_result.scalars().first()
        if developer:
            developer.federation_operator_status = "suspended"

    # Option D-light Phase D2a: cascade to federation license.
    # Without this, a suspended operator's registry continues presenting an
    # active license and its cross-registry calls keep succeeding.
    operator_did = _derive_operator_did(app_record)
    license_result = await db.execute(
        select(models.FederationLicense).where(
            models.FederationLicense.operator_did == operator_did,
            models.FederationLicense.status == "active",
        )
    )
    fed_license = license_result.scalars().first()
    now = datetime.now(timezone.utc)
    suspended_license_id = None
    if fed_license:
        fed_license.status = "suspended"
        fed_license.suspended_at = now
        fed_license.suspended_by = admin.id
        fed_license.suspended_reason = request_body.reason[:500]
        suspended_license_id = fed_license.id
        logger.info(
            f"Federation license suspended for {operator_did} (license={fed_license.id}) "
            f"cascaded from operator suspend by admin {admin.id}"
        )

    # Update application
    app_record.status = "suspended"

    await db.commit()
    await db.refresh(app_record)
    await _sync_operator_licence_status(fed_license if suspended_license_id else None, "suspended")

    # Emit audit event AFTER commit so the row state is durable.
    # Reactor-friendly: include teg_id so the FederationLicenseSuspended reactor
    # can call /cross-teg/config/remove-partner without re-deriving the slug.
    # Convention matches cloud_provisioner.py:224 (TEG_ID=teg-{safe}).
    if suspended_license_id:
        try:
            emitter = get_event_emitter()
            suspended_teg_id = f"teg-{_safe_name(app_record.name or 'unknown')}"
            await emitter.emit(
                event_type="FederationLicenseSuspended",
                aggregate_id=f"federation_license:{suspended_license_id}",
                aggregate_type="FederationLicense",
                data={
                    "license_id": suspended_license_id,
                    "operator_did": operator_did,
                    "operator_name": app_record.name,
                    "teg_id": suspended_teg_id,
                    "application_id": application_id,
                    "reason": request_body.reason,
                    "actor_developer_id": admin.id,
                    "actor_email": admin.email,
                    "suspended_at": now.isoformat(),
                },
            )
        except Exception as exc:
            logger.error(
                f"Failed to emit FederationLicenseSuspended for license {suspended_license_id}: {exc}"
            )

    logger.info(
        f"Operator suspended: {app_record.name} ({app_record.email}) "
        f"by admin {admin.id} -- reason: {request_body.reason}"
    )

    # Send suspension email to the operator
    _send_themed_notification(
        subject=f"Registry License Suspended — {app_record.name}",
        template="operator_suspended",
        context={"name": app_record.name, "reason": request_body.reason},
        theme="sovereign",
        to_address=app_record.email,
    )

    # Notify admin channel
    _send_themed_notification(
        subject=f"[ADMIN] Operator Suspended — {app_record.name}",
        template="admin_notice",
        context={
            "kicker_label": "OPERATOR SUSPENDED",
            "headline_text": f"Operator Suspended — {app_record.name}",
            "rows": [
                ("Operator", f"{app_record.name} ({app_record.email})"),
                ("Suspended by", f"{admin.name} (id={admin.id})"),
                ("Reason", request_body.reason),
            ],
        },
        theme="sovereign",
    )

    return app_record


@router.post(
    "/admin/operator-applications/{application_id}/reinstate-operator",
    response_model=schemas.OperatorApplicationRead,
)
async def reinstate_operator(
    application_id: str,
    admin: models.Developer = Security(security.require_admin_flag("admin_federation")),
    db: AsyncSession = Depends(get_db),
):
    """
    Reinstate a suspended operator. Restores their operator status to approved.
    Only works on suspended operators (revoked operators must re-apply).
    """
    result = await db.execute(
        select(models.OperatorApplication).where(
            models.OperatorApplication.id == application_id
        )
    )
    app_record = result.scalars().first()
    if not app_record:
        raise HTTPException(status_code=404, detail="Application not found.")

    if app_record.status != "suspended":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Application status is '{app_record.status}'. Only suspended operators can be reinstated.",
        )

    # Restore developer status
    if app_record.developer_id:
        dev_result = await db.execute(
            select(models.Developer).where(models.Developer.id == app_record.developer_id)
        )
        developer = dev_result.scalars().first()
        if developer:
            developer.federation_operator_status = "approved"

    # Option D-light Phase D2b: reverse the license cascade.
    # Only reactivate licenses that were suspended (not revoked — a revoked
    # license is terminal and requires the operator to re-apply).
    operator_did = _derive_operator_did(app_record)
    license_result = await db.execute(
        select(models.FederationLicense).where(
            models.FederationLicense.operator_did == operator_did,
            models.FederationLicense.status == "suspended",
        )
    )
    fed_license = license_result.scalars().first()
    reinstated_license_id = None
    if fed_license:
        fed_license.status = "active"
        fed_license.suspended_at = None
        fed_license.suspended_by = None
        fed_license.suspended_reason = None
        reinstated_license_id = fed_license.id
        logger.info(
            f"Federation license reinstated for {operator_did} (license={fed_license.id}) "
            f"cascaded from operator reinstate by admin {admin.id}"
        )

    # Restore application
    app_record.status = "approved"

    await db.commit()
    await db.refresh(app_record)
    await _sync_operator_licence_status(fed_license if reinstated_license_id else None, "active")

    # Emit audit event AFTER commit. teg_id included for symmetry with the
    # suspend payload — currently no reactor consumes Reinstated (lazy
    # auto-discovery handles re-add on next cross-tx) but the field is here
    # so a future reinstate reactor doesn't have to re-derive the slug.
    if reinstated_license_id:
        try:
            emitter = get_event_emitter()
            reinstated_teg_id = f"teg-{_safe_name(app_record.name or 'unknown')}"
            await emitter.emit(
                event_type="FederationLicenseReinstated",
                aggregate_id=f"federation_license:{reinstated_license_id}",
                aggregate_type="FederationLicense",
                data={
                    "license_id": reinstated_license_id,
                    "operator_did": operator_did,
                    "operator_name": app_record.name,
                    "teg_id": reinstated_teg_id,
                    "application_id": application_id,
                    "actor_developer_id": admin.id,
                    "actor_email": admin.email,
                    "reinstated_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        except Exception as exc:
            logger.error(
                f"Failed to emit FederationLicenseReinstated for license {reinstated_license_id}: {exc}"
            )

    logger.info(
        f"Operator reinstated: {app_record.name} ({app_record.email}) by admin {admin.id}"
    )

    # Send reinstatement email to the operator
    _send_themed_notification(
        subject=f"Registry License Reinstated — {app_record.name}",
        template="operator_reinstated",
        context={"name": app_record.name},
        theme="neural",
        to_address=app_record.email,
    )

    # Notify admin channel
    _send_themed_notification(
        subject=f"[ADMIN] Operator Reinstated — {app_record.name}",
        template="admin_notice",
        context={
            "kicker_label": "OPERATOR REINSTATED",
            "headline_text": f"Operator Reinstated — {app_record.name}",
            "rows": [
                ("Operator", f"{app_record.name} ({app_record.email})"),
                ("Reinstated by", f"{admin.name} (id={admin.id})"),
            ],
        },
        theme="neural",
    )

    return app_record


# ---------------------------------------------------------------------------
# f050: Docker pull token management
# ---------------------------------------------------------------------------


@router.post(
    "/admin/operator-applications/{application_id}/rotate-pull-token",
    tags=["Operator Admin"],
)
async def rotate_operator_pull_token(
    application_id: str,
    admin: models.Developer = Security(security.require_admin_flag("admin_federation")),
    db: AsyncSession = Depends(get_db),
):
    """
    Rotate an operator's Docker pull token. Generates a new dpt_ token,
    replaces the hash in the database, and returns the new plaintext token
    (shown ONCE). The old token is immediately invalid.
    """
    result = await db.execute(
        select(models.OperatorApplication).where(
            models.OperatorApplication.id == application_id
        )
    )
    app_record = result.scalars().first()
    if not app_record:
        raise HTTPException(status_code=404, detail="Application not found.")

    if app_record.status != "approved":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot rotate token for operator with status '{app_record.status}'.",
        )

    new_token = f"dpt_{secrets.token_hex(32)}"
    new_hash = hashlib.sha256(new_token.encode()).hexdigest()
    new_prefix = new_token[:8]
    now = datetime.now(timezone.utc)

    app_record.docker_pull_token_hash = new_hash
    app_record.docker_pull_token_prefix = new_prefix
    app_record.docker_pull_token_issued_at = now

    await db.commit()

    logger.info(
        f"Pull token rotated for operator {app_record.name} "
        f"(prefix={new_prefix}) by admin {admin.id}"
    )

    return {
        "pull_token": new_token,
        "prefix": new_prefix,
        "username": app_record.docker_registry_username,
        "issued_at": now.isoformat(),
        "message": "This token is shown once and cannot be recovered.",
    }


@router.post(
    "/admin/operator-applications/backfill-pull-tokens",
    tags=["Operator Admin"],
)
async def backfill_pull_tokens(
    admin: models.Developer = Security(security.require_admin_flag("admin_federation")),
    db: AsyncSession = Depends(get_db),
):
    """
    One-time migration: issue an image pull token to every approved operator that has none. Each new pull token is
    in the answer in plain text, once. Needs an admin token with the `admin_federation` flag.

    \f
    One-time migration: generate pull tokens for all approved operators
    that are missing them. Returns all new plaintext tokens (admin-only).
    Remove this endpoint after migration is complete.
    """
    result = await db.execute(
        select(models.OperatorApplication).where(
            models.OperatorApplication.status == "approved",
            models.OperatorApplication.docker_pull_token_hash.is_(None),
            models.OperatorApplication.docker_registry_username.isnot(None),
        )
    )
    operators = result.scalars().all()

    now = datetime.now(timezone.utc)
    tokens = []
    for op in operators:
        new_token = f"dpt_{secrets.token_hex(32)}"
        op.docker_pull_token_hash = hashlib.sha256(new_token.encode()).hexdigest()
        op.docker_pull_token_prefix = new_token[:8]
        op.docker_pull_token_issued_at = now
        tokens.append({
            "name": op.name,
            "username": op.docker_registry_username,
            "pull_token": new_token,
        })

    await db.commit()

    logger.info(f"Backfilled pull tokens for {len(tokens)} operators (admin {admin.id})")

    return {
        "backfilled": len(tokens),
        "tokens": tokens,
        "message": "These tokens are shown once and cannot be recovered.",
    }


# ---------------------------------------------------------------------------
# f049: Operator activation endpoint
# ---------------------------------------------------------------------------

async def _bundle_through_runner(*, operator_name: str, safe_name: str, operator_did: str, application_id) -> dict:
    """The bundle, built by the frame runner, for a frame whose registry has no docker socket.

    §OPDIST, his decision 2026-09-16: the privileged work moves to the privileged component. Everything the far side
    needs is resolved HERE and passed in a spec; every row is written HERE from the facts that come back. The one
    thing that cannot simply be carried across is the bundle's PATH: the one-shot writes the file into the frame's
    `operator-bundles` directory on the host, and this registry sees that same directory at OPERATOR_BUNDLES_DIR.
    Two views of one file, so the row is written from the FILENAME, which is the only thing both sides agree on.
    Storing the far side's path would produce exactly the sentence this route exists to remove, one step later:
    "Bundle not found at ...".
    """
    from agentvault_registry.core.frame_slug import frame_slug
    from agentvault_registry.services import operator_provision_client as opc

    # The pull token is minted inside the helper and handed to the operator once, so the plaintext never has to come
    # back across the seam; the one-shot is given it and returns only its hash and prefix.
    return await opc.bundle_through_runner(
        frame=frame_slug(), operator_name=operator_name, safe_name=safe_name, operator_did=operator_did,
        application_id=application_id)


@router.post("/operators/activate", response_model=schemas.OperatorApplicationRead)
async def activate_operator(
    request: schemas.OperatorActivateRequest,
    developer: models.Developer = Security(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """
    Activate an approved operator application using the one-time activation code.

    The caller must be an authenticated developer. On successful activation:
    - The developer is marked as a federation operator
    - The operator bundle is provisioned (SPIRE, Docker creds, federation license)
    - The activation code is consumed (cannot be reused)
    """
    # Hash the provided code and look up the matching approved application
    code_hash = hashlib.sha256(request.activation_code.encode()).hexdigest()
    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(models.OperatorApplication).where(
            models.OperatorApplication.activation_code_hash == code_hash,
            models.OperatorApplication.status == "approved",
            models.OperatorApplication.activation_code_expires_at > now,
        )
    )
    app_record = result.scalars().first()

    if not app_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid or expired activation code.",
        )

    if app_record.activated_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This activation code has already been used.",
        )

    # §OPDIST (2026-09-16) — REFUSE BEFORE THE ONE-TIME CODE IS SPENT. Everything below this line has side effects
    # that cannot be undone by a later failure: the code is consumed, a dpt_ pull token is issued, the developer is
    # marked a federation operator. On a frame whose registry has no host reach the provision CANNOT succeed, and it
    # used to discover that afterwards, leaving an approved application, a burnt activation code and a live pull token
    # behind. The standup driver has refused this combination for months; the rail everyone actually uses did not.
    from agentvault_registry.core.host_reach import host_reach_available
    _reach_ok, _reach_why = host_reach_available()
    if not _reach_ok:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(f"This frame cannot provision cloud operators itself, and no runner is available to do it for "
                    f"it: {_reach_why}. Your activation code has NOT been "
                    f"used and can still be activated on a frame that can. Nothing was changed."),
        )

    # §OPPROV (2026-09-27) — ONE NAME, AND ONLY ONE HOLDER OF IT, BEFORE THE CODE IS SPENT. The name below becomes the
    # operator's SPIFFE path (/operator/<name>/), its pull username, and on a cloud provision its stack directory,
    # hostname and container names. Activation used its own slug rule (non-alphanumerics to "-", ends stripped) while
    # the provisioner, the suspend, the reinstate and the rename use _safe_name (non-[a-z0-9-] removed), so an
    # application named "Acme Corp" registered SPIRE entries under acme-corp and was provisioned as acmecorp, whose
    # workloads then matched no entry. And names are not unique: a second live application with the same name would
    # share the first one's SPIFFE path, which a revoke or a purge sweeps whole. Both are refused here, while nothing
    # has been changed and the code can still be used.
    # SEC-21: an application approved under a reserved name (before the rule) is not activated
    from ..core.operator_names import reserved_operator_name
    _reserved = reserved_operator_name(app_record.name)
    if _reserved:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(f"The operator name '{app_record.name}' is reserved ({_reserved}). Your activation code has NOT "
                    f"been used; apply again under another name. Nothing was changed."),
        )
    # SEC-23: nor one the network would confuse with a registry this one already knows
    from ..core.operator_names import colliding_peer_name
    _collides = await colliding_peer_name(db, app_record.name)
    if _collides:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(f"The operator name '{app_record.name}' would be confused with {_collides}. Your activation code "
                    f"has NOT been used; apply again under another name. Nothing was changed."),
        )
    safe_name = _safe_name(app_record.name or "") or f"operator-{developer.id}"
    _holders = (await db.execute(
        select(models.OperatorApplication.id, models.OperatorApplication.name,
               models.OperatorApplication.docker_registry_username).where(
            models.OperatorApplication.id != app_record.id,
            models.OperatorApplication.activated_at.isnot(None),
            models.OperatorApplication.status.in_(("approved", "suspended")),
        )
    )).all()
    _holder = next((h for h in _holders
                    if ((h.docker_registry_username or "").removeprefix("operator-") or _safe_name(h.name or ""))
                    == safe_name), None)
    if _holder is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(f"An operator named '{safe_name}' is already active on this frame (application {_holder.id}); a "
                    f"second one would share its SPIRE identities, and on a cloud frame its stack and hostname. Revoke "
                    f"that application first, or apply under another name. Your activation code has NOT been used. "
                    f"Nothing was changed."),
        )

    # Mark developer as federation operator
    developer.is_federation_operator = True
    developer.federation_operator_status = "approved"

    # PB-1 (2026-05-09): auto-grant the operator flare cosmetic on activation.
    # Higher-rank-wins protects existing commander/founder/etc. — the helper
    # quietly no-ops if the developer already wears a higher-ranked badge.
    # Failure of the flare grant must NEVER fail the operator activation.
    try:
        from agentvault_registry.routers.fiat_onramp import auto_grant_operator_flare
        await auto_grant_operator_flare(db=db, developer=developer)
    except Exception as exc:
        logger.warning(
            "[operator-activate] auto-grant operator flare failed for dev=%s (non-fatal): %s",
            developer.id, exc,
        )

    # Note: Direct peering is NOT auto-created on activation.
    # Operators become trusted via BFS topology discovery through their parent peers.
    # Direct peering must be explicitly set up via Federation settings by admin.

    # Record activation on the application
    app_record.activated_at = now
    app_record.activated_developer_id = developer.id
    app_record.developer_id = developer.id

    # --- Provision operator bundle ---
    provision_result = None
    try:
        # WHICH ROUTE, decided by the same predicate that guarded this route above rather than by a flag someone can
        # set to a lie. EU and ASIA hold the host docker socket and take today's path byte for byte; a runner-built
        # frame has none, on purpose, and asks the runner to do it. Both branches end in ONE mapping, so the rows
        # below are written from one shape and a change to what a bundle carries lands in one place. §F6 WP6.0: the
        # route is host_route()'s, the same answer the guard above read (HOST_REACH_PREFER included; unset = today).
        from agentvault_registry.core.host_reach import host_route

        # safe_name: the one slug rule, computed above before the code was spent (§OPPROV)

        operator_did = f"did:theprotocol:operator:{safe_name}"

        _route, _route_why = host_route()
        if _route is None:  # the guard above answered yes a moment ago: a route closed since is a failure, never a fallback
            raise RuntimeError(f"no route for the operator's host work: {_route_why}")
        _direct_ok = _route == "direct"
        logger.info(
            f"Starting bundle provisioning for operator '{safe_name}' "
            f"(application={app_record.id}, developer={developer.id}, "
            f"route={'this registry' if _direct_ok else 'the frame runner'}: {_route_why})"
        )

        if _direct_ok:
            from agentvault_registry.services.operator_provisioner import provision_operator

            _r = provision_operator(safe_name, operator_did)
            provision_result = {
                "bundle_path": _r.bundle_path,
                "fingerprint": _r.fingerprint,
                "docker_username": _r.docker_username,
                "docker_pull_token": _r.docker_pull_token,
                "docker_pull_token_hash": _r.docker_pull_token_hash,
                "docker_pull_token_prefix": _r.docker_pull_token_prefix,
                "entries_registered": _r.entries_registered,
                "where": "this registry (it holds the host docker socket)",
            }
        else:
            provision_result = await _bundle_through_runner(
                operator_name=app_record.name, safe_name=safe_name, operator_did=operator_did,
                application_id=str(app_record.id))

        # Store provisioning results on the application record
        app_record.bundle_path = provision_result["bundle_path"]
        app_record.bundle_generated_at = now
        app_record.bundle_download_count = 0
        app_record.bundle_expires_at = now + timedelta(days=30)
        app_record.docker_registry_username = provision_result["docker_username"]
        app_record.spire_fingerprint = provision_result["fingerprint"]
        # f050: Store Docker pull token hash (token auth replaces htpasswd)
        app_record.docker_pull_token_hash = provision_result["docker_pull_token_hash"]
        app_record.docker_pull_token_prefix = provision_result["docker_pull_token_prefix"]
        app_record.docker_pull_token_issued_at = now

        logger.info(
            f"Bundle provisioned successfully for operator '{safe_name}' via {provision_result['where']}: "
            f"bundle={provision_result['bundle_path']}, "
            f"fingerprint={provision_result['fingerprint']}, "
            f"entries={provision_result['entries_registered']}"
        )

    except Exception as e:
        # Provisioning failure does NOT block activation -- the operator is still
        # activated and can get a bundle re-generated later.
        # ⚠ A REFUSAL IS NOT A FAILURE and the line says which: RunnerRefused means the far side did nothing, so a
        # re-run is safe; anything else may have run. Collapsing the two into "provisioning failed" is what made
        # this morning's incident unreadable from the outside.
        _kind = type(e).__name__
        logger.error(
            f"Bundle provisioning {'was REFUSED' if _kind == 'RunnerRefused' else 'failed'} for application "
            f"{app_record.id} ({_kind}): {e}",
            exc_info=True,
        )
        provision_result = None
        app_record.bundle_path = None

    await db.commit()
    await db.refresh(app_record)

    logger.info(
        f"Operator activated: {app_record.name} ({app_record.email}) "
        f"by developer {developer.id} ({developer.email})"
    )

    # Send activation confirmation email (themed; pull token shown ONCE)
    pull_token = (
        provision_result["docker_pull_token"]
        if provision_result and provision_result.get("docker_pull_token")
        else None
    )
    docker_username = (
        provision_result["docker_username"] if provision_result else None
    )
    bundle_status = (
        "Provisioned — download from the Operator Portal"
        if provision_result
        else "Provisioning failed — contact admin"
    )

    _send_themed_notification(
        subject=f"Operator Activation Complete — {app_record.name}",
        template="operator_activated",
        context={
            "name": app_record.name,
            "developer_email": developer.email,
            "bundle_status": bundle_status,
            "pull_token": pull_token,
            "docker_username": docker_username,
        },
        theme="neural",
        to_address=developer.email,
    )

    # Notify admin channel
    _send_themed_notification(
        subject=f"[ADMIN] Operator Activated — {app_record.name}",
        template="admin_notice",
        context={
            "kicker_label": "OPERATOR ACTIVATED",
            "headline_text": f"Activation Complete — {app_record.name}",
            "rows": [
                ("Application", f"{app_record.name} ({app_record.email})"),
                (
                    "Activated by",
                    f"{developer.name} (id={developer.id}, {developer.email})",
                ),
                (
                    "Bundle",
                    "Provisioned" if provision_result else "FAILED — re-run manually",
                ),
            ],
        },
        theme="neural",
    )

    return app_record


# ---------------------------------------------------------------------------
# f048: Operator self-service endpoints
# ---------------------------------------------------------------------------

@router.get("/operators/my-status", response_model=schemas.OperatorStatusResponse)
async def get_operator_status(
    developer: models.Developer = Security(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """
    Check the current operator status for the authenticated developer.
    Returns is_federation_operator flag, federation_operator_status, and full application details if available.
    """
    # Find the most recent application for this developer
    result = await db.execute(
        select(models.OperatorApplication).where(
            models.OperatorApplication.developer_id == developer.id,
        ).order_by(models.OperatorApplication.created_at.desc())
    )
    app_record = result.scalars().first()

    return schemas.OperatorStatusResponse(
        is_federation_operator=developer.is_federation_operator,
        federation_operator_status=developer.federation_operator_status,
        application=schemas.OperatorApplicationRead.model_validate(app_record) if app_record else None,
    )


@router.post("/operators/request-revocation")
async def request_self_revocation(
    request_body: schemas.OperatorRevocationRequest,
    developer: models.Developer = Security(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """
    Request voluntary revocation of operator status. Does NOT immediately revoke --
    sends a notification to the admin team for manual processing.
    """
    if not developer.is_federation_operator:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not an active operator.",
        )

    logger.info(
        f"Operator self-revocation requested by developer {developer.id} "
        f"({developer.email}) -- reason: {request_body.reason}"
    )

    # Send notification to admin channel
    _send_themed_notification(
        subject=f"[SELF-REVOCATION REQUEST] Operator {developer.name}",
        template="admin_notice",
        context={
            "kicker_label": "SELF-REVOCATION REQUEST",
            "headline_text": f"Voluntary Revocation Requested — {developer.name}",
            "body_text": "An operator has requested voluntary revocation of their registry license.",
            "rows": [
                ("Developer", f"{developer.name} (id={developer.id})"),
                ("Email", developer.email),
                ("Reason", request_body.reason),
            ],
            "notice_text": "Please review and process this request via the admin API: POST /api/v1/admin/operator-applications/{id}/revoke-operator",
        },
        theme="sovereign",
    )

    return {
        "status": "submitted",
        "message": "Your revocation request has been submitted to the admin team for processing.",
    }
