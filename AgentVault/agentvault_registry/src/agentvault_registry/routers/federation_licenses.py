"""
Federation License Key System — Admin endpoints for managing federation licenses
and a reusable FastAPI dependency for license verification.

Endpoints:
    POST   /api/v1/admin/federation/licenses/generate       — Generate a new license key
    GET    /api/v1/admin/federation/licenses                 — List all licenses
    GET    /api/v1/admin/federation/licenses/{license_id}    — Get a single license
    POST   /api/v1/admin/federation/licenses/{license_id}/revoke    — Revoke a license
    POST   /api/v1/admin/federation/licenses/{license_id}/suspend   — Suspend a license
    POST   /api/v1/admin/federation/licenses/{license_id}/reinstate — Reinstate a license
    DELETE /api/v1/admin/federation/licenses/{license_id}    — Hard delete a license

All admin endpoints require require_admin_flag("admin_federation") (legacy is_admin=True passes via super-flag).
"""

import hashlib
import logging
import os
import secrets
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Header, status, Security
from pydantic import BaseModel, Field, ConfigDict, field_validator
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry import models
from agentvault_registry.database import get_db
from agentvault_registry import security

logger = logging.getLogger(__name__)


def _es_control_plane_url() -> tuple[str, bool]:
    """Resolve the EventStore URL for a license CONTROL-PLANE sync (create /
    update / revoke / suspend / reinstate of a `federation_operators` row).

    §2026-06-16 CASCADE FIX. On a MAINFRAME this MUST hit the ES's DIRECT
    internal port with `X-Internal-Key` so `verify_event_auth` classifies the
    caller as `auth_type='internal'` — the only tier allowed to set
    `status=revoked/suspended` or update `license_key_hash`
    (`events.py /operators/sync`). The mTLS sidecar (`nginx-event-store:8443`)
    STRIPS `X-Internal-Key` (§pass69 "mTLS is the authority"), so a sync via
    `EVENT_STORE_URL` lands as `auth_type='mtls'` and the revoke/suspend is
    silently 403'd — which left `federation_operators` rows `active` after a
    license was revoked (the cascade bug; the provisioner already worked around
    it with a direct-DB INSERT in `cloud_provisioner.py`).

    Returns `(url, is_internal_path)`. Off-mainframe (e.g. a cloud-op operator
    self-rotating its own license) keeps the existing `EVENT_STORE_URL` path —
    it has no INTERNAL_API_KEY for the parent ES and must use mTLS.
    """
    base = os.getenv("EVENT_STORE_URL", "http://event-store:8200")
    if str(os.getenv("IS_CENTRAL_REGISTRY", "")).lower() == "true":
        internal = os.getenv("EVENT_STORE_INTERNAL_URL")
        if not internal:
            # Derive the direct ES from the frame's OWN sidecar host (frame-safe):
            #   https://nginx-event-store:8443          → http://event-store:8200
            #   https://frame-b-nginx-event-store:8443  → http://frame-b-event-store:8200
            internal = (base.replace("https://", "http://")
                            .replace("nginx-event-store", "event-store")
                            .replace(":8443", ":8200"))
        return internal.rstrip("/"), True
    return base.rstrip("/"), False


def _mtls_required_refusal(resp) -> bool:
    """The store's §SECFIX-7 refusal of a change authenticated only by the internal key (events.py verify_event_auth):
    a 403 whose detail starts "mtls_required". The store changed nothing and names the way it takes the same request:
    through the frame's TLS terminator with the service's SPIRE certificate. Any other 403 is about authority, not
    transport, and is never retried."""
    if resp.status_code != 403:
        return False
    try:
        detail = resp.json().get("detail")
    except Exception:  # noqa: BLE001  a body that is not JSON is not this refusal
        return False
    return isinstance(detail, str) and detail.startswith("mtls_required")


async def _sync_license_to_eventstore(
    license_id: str,
    operator_name: str,
    license_key_hash: str,
    op_status: str,
    max_events_per_minute: int = 1000,
    spiffe_id: str = None,
) -> bool:
    """Push license info to EventStore's federation_operators table. True when the store took it.
    Best-effort — failure doesn't block the Registry operation.

    It carries no trust value (SEC-20, 2026-10-17): the record's bayesian_discount is the frame registry's derivation
    from its record of the peer, which only the trust sync sends (federation_sync.trust_sync_payloads). This helper took
    an optional one, which no caller passed.

    Auth: on a mainframe, the DIRECT internal ES port + `X-Internal-Key`
    (auth_type=internal — required to set status=revoked/suspended); see
    `_es_control_plane_url()`. Off-mainframe, mTLS via SPIRE SVID over the
    sidecar/public URL (operator self-rotate path). When the direct port refuses
    the connection, or refuses the key for a change (mtls_required), the same
    request goes over the store's mTLS gateway (EVENT_STORE_URL) with the SVID.
    """
    es_url, internal_path = _es_control_plane_url()
    es_key = os.getenv("EVENT_STORE_API_KEY", "")
    payload = {
        "id": license_id,
        "operator_name": operator_name,
        "license_key_hash": license_key_hash,
        "status": op_status,
        "max_events_per_minute": max_events_per_minute,
    }
    if spiffe_id:
        payload["spiffe_id"] = spiffe_id

    cert_dir = os.getenv("SVID_CERT_DIR", os.getenv("CERT_DIR", "/certs"))
    cert_file = os.path.join(cert_dir, "svid.0.pem")
    key_file = os.path.join(cert_dir, "svid.0.key")
    bundle_file = os.path.join(cert_dir, "bundle.0.pem")
    client_kwargs = {"timeout": 5.0}
    # mTLS only for the NON-internal (sidecar/public) path. The internal port
    # authenticates with X-Internal-Key — which the sidecar would strip — so we
    # never attach a client cert there (it would become auth_type=mtls again).
    if (not internal_path and es_url.startswith("https://")
            and os.path.exists(cert_file) and os.path.exists(key_file)):
        from ..core.tls_client import client_cert_verify  # §DEPS: httpx 0.28 drops `cert` beside a bundle PATH
        client_kwargs["cert"] = (cert_file, key_file)
        client_kwargs["verify"] = client_cert_verify(bundle_file if os.path.exists(bundle_file) else True,
                                                     client_kwargs["cert"])

    async def _post(url: str, kwargs: dict):
        async with httpx.AsyncClient(**kwargs) as client:
            return await client.post(
                f"{url}/api/v1/events/operators/sync",
                json=payload,
                headers={"X-Internal-Key": es_key, "Content-Type": "application/json"},
            )

    gateway = os.getenv("EVENT_STORE_URL", "").rstrip("/")
    has_gateway = internal_path and gateway.startswith("https://") and gateway != es_url
    try:
        try:
            resp = await _post(es_url, client_kwargs)
        except httpx.ConnectError as exc:
            # §TESTBED (2026-09-19): a kit frame's store serves ONLY its mTLS gateway; nothing listens on the direct
            # port this path derives (measured: larch and its sandboxes, while EU and ASIA still listen on :8200). A
            # refused connection sent nothing, so the same request goes over the gateway with this registry's SVID,
            # where the store's own-frame rule (§SOVKIT T5, es_auth.is_origin) keeps its licensing rights. Before this,
            # every cloud operator of a kit frame was missing from its parent's federation_operators, and SF-5B's trust
            # sync answered 400 every two minutes on the row that was never created.
            if not has_gateway:
                raise
            from agentvault_registry.es_ssl_helper import get_httpx_verify
            logger.info(f"[FedLicense] {es_url} refused the connection ({type(exc).__name__}); syncing "
                        f"{license_id} over the store's mTLS gateway {gateway}")
            es_url = gateway
            resp = await _post(es_url, {"timeout": 5.0, "verify": get_httpx_verify()})
        else:
            # §F6 stage 3 (2026-09-27): the direct port ANSWERED, and refused the key for a change. Every store of
            # this network runs EVENTSTORE_MTLS_REQUIRED, and since §SECFIX-7 (2026-09-25) the internal key there
            # authenticates reads only, so every licence this path created, and the licence routes' own revoke,
            # suspend and reinstate, answered 403 on EU, ASIA and both sandbox frames. The docker socket hid the
            # create: the provisioner's direct-DB upsert wrote the ACTIVE row anyway. The runner route has no such
            # write, so an operator provisioned through the frame runner had no federation_operators row at all
            # (measured on sbx-beta: b1opb's two syncs, registry and svid-writer, both 403; no row for b1opa or
            # b1opb) and SF-5B answered 400 for it every cycle. (The cloud-operator teardown suspends the row
            # through frame_data_plane_sync, over the gateway, and was unaffected.) The store names the way it takes
            # the same request, and it is the gateway the refused connection already uses.
            if has_gateway and _mtls_required_refusal(resp):
                from agentvault_registry.es_ssl_helper import get_httpx_verify
                logger.info(f"[FedLicense] {es_url} refused the internal key for a change (mtls_required); "
                            f"syncing {license_id} over the store's mTLS gateway {gateway}")
                es_url = gateway
                resp = await _post(es_url, {"timeout": 5.0, "verify": get_httpx_verify()})
        # §2026-06-16 — was fire-and-forget (swallowed even HTTP 403); now we
        # surface a non-2xx so a future cascade break can't fail silently.
        if resp.status_code >= 400:
            logger.warning(
                f"[FedLicense] ES operators/sync HTTP {resp.status_code} for "
                f"{license_id} (status={op_status}) via {es_url}: {resp.text[:200]}"
            )
            return False
        logger.info(
            f"[FedLicense] Synced license {license_id} to EventStore "
            f"(status={op_status}) via {es_url}"
        )
        return True
    except Exception as e:
        logger.warning(f"[FedLicense] Failed to sync license to EventStore (non-fatal): {e}")
        return False


# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------

class FederationLicenseGenerateRequest(BaseModel):
    """Request body for generating a new federation license."""
    operator_name: str = Field(
        ..., min_length=1, max_length=200,
        description="Human-readable name of the federation operator"
    )
    operator_did: str = Field(
        ..., min_length=1, max_length=255,
        description="DID of the federation operator (must be unique)"
    )
    max_agents: int = Field(
        100, ge=1, le=100000,
        description="Maximum number of agents this operator can register"
    )
    max_events_per_minute: int = Field(
        1000, ge=1, le=1000000,
        description="Rate limit: max events per minute"
    )
    federation_tier: str = Field(
        "standard",
        description="Federation tier: standard or enterprise"
    )
    min_image_version: Optional[str] = Field(
        None, max_length=20,
        description="Minimum container image version required"
    )
    licensee_type: str = Field(
        "operator",
        description="Who this licence is for: 'operator' (a cloud operator) or 'frame' (a sovereign frame)",
    )

    @field_validator("licensee_type")
    @classmethod
    def _known_licensee_type(cls, v: str) -> str:
        if v not in LICENSEE_TYPES:
            raise ValueError(f"licensee_type must be one of {sorted(LICENSEE_TYPES)}")
        return v


class FederationLicenseGenerateResponse(BaseModel):
    """Response after generating a new federation license. Contains the plain key (shown ONCE)."""
    license_id: str = Field(..., description="Unique license identifier (UUID)")
    license_key: str = Field(
        ...,
        description="The full plain-text license key (tp_fed_...). Store securely — shown ONCE."
    )
    operator_name: str
    operator_did: str
    licensee_type: str
    status: str
    federation_tier: str
    max_agents: int
    max_events_per_minute: int
    issued_at: datetime


class FederationLicenseRead(BaseModel):
    """Read-only view of a federation license (no plain key, prefix only)."""
    id: str
    operator_name: str
    operator_did: str
    licensee_type: str
    license_key_prefix: str = Field(..., description="First 12 chars of the key for identification")
    status: str
    issued_at: datetime
    revoked_at: Optional[datetime] = None
    revoked_reason: Optional[str] = None
    max_agents: int
    max_events_per_minute: int
    federation_tier: str
    last_seen_at: Optional[datetime] = None
    event_count: int
    min_image_version: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class FederationLicenseRevokeRequest(BaseModel):
    """Request body for revoking a federation license."""
    reason: str = Field(
        ..., min_length=1, max_length=500,
        description="Reason for revocation"
    )


class FederationLicenseSuspendRequest(BaseModel):
    """Optional request body for suspending a federation license (a suspend with no body still works).

    §FEDLICENCE improvement 8 (2026-09-28): the admin MCP tool always sent `reason` and this route declared no body, so
    the reason was dropped silently and `suspended_reason` never written. An unknown key is now refused, not dropped."""
    model_config = ConfigDict(extra="forbid")
    reason: Optional[str] = Field(None, max_length=500, description="Why the license is suspended")


# ---------------------------------------------------------------------------
# License Key Generation Helper
# ---------------------------------------------------------------------------

def _generate_federation_license_key() -> tuple[str, str, str]:
    """
    Generate a federation license key.

    Returns:
        (plain_key, key_hash, key_prefix)
        - plain_key: "tp_fed_" + 64 hex chars (71 chars total)
        - key_hash:  SHA-256 hex digest of the full plain key
        - key_prefix: first 12 chars of the plain key for display
    """
    random_hex = secrets.token_hex(32)  # 64 hex chars
    plain_key = f"tp_fed_{random_hex}"
    key_hash = hashlib.sha256(plain_key.encode()).hexdigest()
    key_prefix = plain_key[:12]
    return plain_key, key_hash, key_prefix


# ---------------------------------------------------------------------------
# Federation License Verification Dependency (importable by other routers)
# ---------------------------------------------------------------------------

LICENSEE_TYPES = frozenset({"operator", "frame"})


def assert_licensee_type(federation_license, expected: str) -> None:
    """D6-111: refuse (403) a live licence that was issued to the other class than the rail serves.

    The one check every place that accepts a licence asks after it verified the key: the dependency below, and the
    operator rails that read the key themselves (routed fiat, an operator's own logs and restart through its parent).
    A row written before mig 0176 carries no type and reads as an operator licence (the backfill's value)."""
    if expected not in LICENSEE_TYPES:
        raise ValueError(f"unknown licensee_type {expected!r}")
    actual = getattr(federation_license, "licensee_type", "operator") or "operator"
    if actual != expected:
        logger.warning(
            f"Federation license type mismatch: key for {actual} '{getattr(federation_license, 'operator_name', '?')}' "
            f"presented on a rail that requires a {expected} licence"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"licensee_type_mismatch: this rail requires a {expected} federation licence",
        )


def require_licensee_type(expected: str):
    """§FRAMELIC — a verifier that also checks WHO the licence was issued to.

    `verify_federation_license` answers "is this key live?". On a network where frames and
    operators both hold licences from the same table that is only half the question: an
    operator key presented on a frame-to-frame rail is a live key doing a job it was never
    issued for. Rows written before mig 0176 are operator licences (that is the backfill),
    so `require_licensee_type("operator")` is exactly today's behaviour plus a refusal.
    """
    if expected not in LICENSEE_TYPES:
        raise ValueError(f"unknown licensee_type {expected!r}")

    async def _dep(
        federation_license: models.FederationLicense = Depends(verify_federation_license),
    ) -> models.FederationLicense:
        assert_licensee_type(federation_license, expected)
        return federation_license

    return _dep


async def verify_federation_license(
    x_federation_license: str = Header(
        ...,
        alias="X-Federation-License",
        description="Federation license key for cross-registry operations"
    ),
    db: AsyncSession = Depends(get_db),
) -> models.FederationLicense:
    """
    FastAPI dependency that verifies a federation license key from the
    X-Federation-License header.

    Checks that:
    1. The SHA-256 hash of the presented key matches a stored license
    2. The license status is 'active'

    On success, updates last_seen_at and increments event_count.
    Raises HTTPException(403) on failure.

    Usage in other routers:
        from agentvault_registry.routers.federation_licenses import verify_federation_license

        @router.post("/some-federated-endpoint")
        async def my_endpoint(
            license: models.FederationLicense = Depends(verify_federation_license),
        ):
            ...
    """
    key_hash = hashlib.sha256(x_federation_license.encode()).hexdigest()

    result = await db.execute(
        select(models.FederationLicense).where(
            models.FederationLicense.license_key_hash == key_hash,
            models.FederationLicense.status == "active",
        )
    )
    federation_license = result.scalar_one_or_none()

    if not federation_license:
        logger.warning(
            f"Federation license verification failed: no active license for hash prefix {key_hash[:8]}..."
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or revoked federation license",
        )

    # Update last_seen and event_count
    federation_license.last_seen_at = func.now()
    federation_license.event_count = models.FederationLicense.event_count + 1
    await db.commit()

    logger.debug(
        f"Federation license verified: operator={federation_license.operator_name}, "
        f"did={federation_license.operator_did}"
    )
    return federation_license


# ---------------------------------------------------------------------------
# Admin Router
# ---------------------------------------------------------------------------

# §pass66 (2026-05-22) — Mainframe-only. Cloud-operators can't issue
# federation licenses for sub-operators (the federation root of trust is
# the mainframe). Router-level dependency means every endpoint here
# returns 503 on a cloud-op registry.
from agentvault_registry.core.mainframe_gate import require_mainframe_only
from fastapi import Depends

router = APIRouter(
    prefix="/api/v1/admin/federation/licenses",
    tags=["Federation Licenses"],
    dependencies=[Depends(require_mainframe_only)],
)


@router.post(
    "/generate",
    response_model=FederationLicenseGenerateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate Federation License Key",
)
async def generate_federation_license(
    request: FederationLicenseGenerateRequest,
    admin: models.Developer = Security(security.require_admin_flag("admin_federation")),
    db: AsyncSession = Depends(get_db),
):
    """
    Generate a new federation license key for an operator.

    The plain license key is returned ONCE in the response and cannot be
    retrieved again. The key is stored as a SHA-256 hash.

    Requires admin privileges (is_admin=True).
    """
    # Check for duplicate operator_did
    existing = await db.execute(
        select(models.FederationLicense).where(
            models.FederationLicense.operator_did == request.operator_did
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A license already exists for DID: {request.operator_did} (operator_did is unique across both licensee types)",
        )

    # Validate federation_tier
    # §FRAMELIC (2026-09-07, findings row 143) — `sovereign` is the FRAME tier. `licensee_type`
    # already says which class a licence is for; the tier says what the licensee may do, and a
    # sovereign frame is not an enterprise operator. Added rather than silently accepted: a value
    # invented for legibility must be one the validator has been told about.
    if request.federation_tier not in ("standard", "enterprise", "sovereign"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="federation_tier must be 'standard', 'enterprise' or 'sovereign'",
        )

    # Generate key
    plain_key, key_hash, key_prefix = _generate_federation_license_key()

    license_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    db_license = models.FederationLicense(
        id=license_id,
        operator_name=request.operator_name,
        operator_did=request.operator_did,
        licensee_type=request.licensee_type,
        license_key_hash=key_hash,
        license_key_prefix=key_prefix,
        status="active",
        max_agents=request.max_agents,
        max_events_per_minute=request.max_events_per_minute,
        federation_tier=request.federation_tier,
        min_image_version=request.min_image_version,
        event_count=0,
    )

    db.add(db_license)
    await db.commit()
    await db.refresh(db_license)

    logger.info(
        f"Federation license generated by admin {admin.email}: "
        f"id={license_id}, operator={request.operator_name}, did={request.operator_did}"
    )

    # Sync to EventStore so it can authenticate this operator's events
    await _sync_license_to_eventstore(
        license_id=license_id,
        operator_name=request.operator_name,
        license_key_hash=key_hash,
        op_status="active",
        max_events_per_minute=request.max_events_per_minute,
    )

    return FederationLicenseGenerateResponse(
        license_id=license_id,
        license_key=plain_key,
        operator_name=db_license.operator_name,
        operator_did=db_license.operator_did,
        licensee_type=db_license.licensee_type,
        status=db_license.status,
        federation_tier=db_license.federation_tier,
        max_agents=db_license.max_agents,
        max_events_per_minute=db_license.max_events_per_minute,
        issued_at=db_license.issued_at,
    )


@router.get(
    "",
    response_model=List[FederationLicenseRead],
    summary="List All Federation Licenses",
)
async def list_federation_licenses(
    status_filter: Optional[str] = None,
    licensee_type: Optional[str] = None,
    admin: models.Developer = Security(security.require_admin_flag("admin_federation")),
    db: AsyncSession = Depends(get_db),
):
    """
    List all federation licenses. Optionally filter by status (active, suspended, revoked).

    Returns license metadata with key prefix only (never the full key).
    """
    query = select(models.FederationLicense).order_by(
        models.FederationLicense.issued_at.desc()
    )

    if licensee_type:
        if licensee_type not in LICENSEE_TYPES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"licensee_type must be one of {sorted(LICENSEE_TYPES)}",
            )
        query = query.where(models.FederationLicense.licensee_type == licensee_type)

    if status_filter:
        if status_filter not in ("active", "suspended", "revoked"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="status must be 'active', 'suspended', or 'revoked'",
            )
        query = query.where(models.FederationLicense.status == status_filter)

    result = await db.execute(query)
    licenses = result.scalars().all()
    return licenses


@router.get(
    "/{license_id}",
    response_model=FederationLicenseRead,
    summary="Get Federation License Details",
)
async def get_federation_license(
    license_id: str,
    admin: models.Developer = Security(security.require_admin_flag("admin_federation")),
    db: AsyncSession = Depends(get_db),
):
    """
    Get details for a single federation license by ID.
    """
    result = await db.execute(
        select(models.FederationLicense).where(
            models.FederationLicense.id == license_id
        )
    )
    db_license = result.scalar_one_or_none()

    if not db_license:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Federation license not found: {license_id}",
        )

    return db_license


@router.post(
    "/{license_id}/revoke",
    response_model=FederationLicenseRead,
    summary="Revoke Federation License",
)
async def revoke_federation_license(
    license_id: str,
    request: FederationLicenseRevokeRequest,
    admin: models.Developer = Security(security.require_admin_flag("admin_federation")),
    db: AsyncSession = Depends(get_db),
):
    """
    Revoke a federation license. Sets status to 'revoked' and records the reason.

    A revoked license cannot be used for federation until reinstated.
    """
    result = await db.execute(
        select(models.FederationLicense).where(
            models.FederationLicense.id == license_id
        )
    )
    db_license = result.scalar_one_or_none()

    if not db_license:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Federation license not found: {license_id}",
        )

    if db_license.status == "revoked":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="License is already revoked",
        )

    db_license.status = "revoked"
    db_license.revoked_at = datetime.now(timezone.utc)
    db_license.revoked_reason = request.reason

    await db.commit()
    await db.refresh(db_license)

    logger.info(
        f"Federation license revoked by admin {admin.email}: "
        f"id={license_id}, operator={db_license.operator_name}, reason={request.reason}"
    )

    # The store's federation_operators row follows the licence: a store that reads an operator's rows on its writes
    # refuses them once the row reads revoked.
    await _sync_license_to_eventstore(
        license_id=license_id,
        operator_name=db_license.operator_name,
        license_key_hash=db_license.license_key_hash,
        op_status="revoked",
    )
    # D6-800 (2026-10-17): the event a suspend emits, so this frame's TEG drops the operator as a partner (the
    # FederationLicenseSuspended reactor) and peer frames do the same (the store broadcasts the type). A revoke emitted
    # nothing, so the TEG kept a revoked operator as its partner. The payload says the licence is revoked; a reinstate
    # emits FederationLicenseReinstated, which adds the partner back.
    await _emit_license_status_event(db, "FederationLicenseSuspended", db_license, admin,
                                     reason=request.reason, licence_status="revoked",
                                     revoked_at=db_license.revoked_at.isoformat())

    return db_license


async def _emit_license_status_event(db: AsyncSession, event_type: str, lic: "models.FederationLicense",
                                     admin: "models.Developer", **extra) -> None:
    """FederationLicenseSuspended / FederationLicenseReinstated from the licence routes, the payload the operator routes
    emit (routers/operator_applications.py). `teg_id` rides along only when an operator application of that name exists
    (the provisioner's TEG_ID convention, cloud_provisioner._safe_name); for a frame's licence it is left out and the
    FederationLicenseSuspended reactor skips by design. Post-commit and best-effort: an emit failure is logged at ERROR
    and never undoes the status change."""
    try:
        from agentvault_registry.event_emitter import get_event_emitter
        data = {"license_id": lic.id, "operator_did": lic.operator_did, "operator_name": lic.operator_name,
                "actor_developer_id": admin.id, "actor_email": admin.email, **extra}
        app_name = (await db.execute(
            select(models.OperatorApplication.name).where(models.OperatorApplication.name == lic.operator_name).limit(1)
        )).scalar_one_or_none()
        if app_name:
            from agentvault_registry.services.cloud_provisioner import _safe_name
            data["teg_id"] = f"teg-{_safe_name(app_name)}"
        await get_event_emitter().emit(
            event_type=event_type,
            aggregate_id=f"federation_license:{lic.id}",
            aggregate_type="FederationLicense",
            data=data,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Failed to emit {event_type} for license {getattr(lic, 'id', '?')}: {exc}")


@router.post(
    "/{license_id}/suspend",
    response_model=FederationLicenseRead,
    summary="Suspend Federation License",
)
async def suspend_federation_license(
    license_id: str,
    request: Optional[FederationLicenseSuspendRequest] = None,
    admin: models.Developer = Security(security.require_admin_flag("admin_federation")),
    db: AsyncSession = Depends(get_db),
):
    """
    Suspend a federation license. The operator will be unable to federate
    until the license is reinstated.
    """
    result = await db.execute(
        select(models.FederationLicense).where(
            models.FederationLicense.id == license_id
        )
    )
    db_license = result.scalar_one_or_none()

    if not db_license:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Federation license not found: {license_id}",
        )

    if db_license.status == "suspended":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="License is already suspended",
        )

    if db_license.status == "revoked":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot suspend a revoked license — reinstate it first",
        )

    now = datetime.now(timezone.utc)
    reason = (request.reason if request else None) or None
    db_license.status = "suspended"
    db_license.suspended_at = now
    db_license.suspended_by = admin.id
    db_license.suspended_reason = reason
    await db.commit()
    await db.refresh(db_license)

    logger.info(
        f"Federation license suspended by admin {admin.email}: "
        f"id={license_id}, operator={db_license.operator_name}, reason={reason}"
    )

    # §FEDLICENCE improvement 8: the store follows by the same path revoke takes (its gateway fallback included), and the
    # event the operator route emits goes out here too (the TEG partner reactor, the cross-frame replicator).
    await _sync_license_to_eventstore(
        license_id=license_id,
        operator_name=db_license.operator_name,
        license_key_hash=db_license.license_key_hash,
        op_status="suspended",
    )
    await _emit_license_status_event(db, "FederationLicenseSuspended", db_license, admin,
                                     reason=reason, suspended_at=now.isoformat())

    # §NOTIFV2 federation.license_suspended (audience=operator, severity=critical). Verified the
    # single writer: `status = "suspended"` on a license exists ONLY here (the enforcement engine's
    # "suspended" writes are on `agents`, a different object). Post-commit.
    try:
        import asyncio as _aio_n
        from agentvault_registry.background_tasks.push_notify import notify_audience
        _aio_n.create_task(notify_audience(
            "federation.license_suspended",
            title="Federation license suspended",
            message=(f"{db_license.operator_name} can no longer federate. "
                     f"Suspended by {admin.email}."),
            tags="rotating_light", priority="high", click="/ui/#/admin/federation-licenses"))
    except Exception:  # noqa: BLE001
        logger.debug("[NOTIFY] federation.license_suspended emit failed", exc_info=True)

    return db_license


@router.post(
    "/{license_id}/reinstate",
    response_model=FederationLicenseRead,
    summary="Reinstate Federation License",
)
async def reinstate_federation_license(
    license_id: str,
    admin: models.Developer = Security(security.require_admin_flag("admin_federation")),
    db: AsyncSession = Depends(get_db),
):
    """
    Reinstate a suspended or revoked federation license back to active status.
    Clears revoked_at and revoked_reason.
    """
    result = await db.execute(
        select(models.FederationLicense).where(
            models.FederationLicense.id == license_id
        )
    )
    db_license = result.scalar_one_or_none()

    if not db_license:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Federation license not found: {license_id}",
        )

    if db_license.status == "active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="License is already active",
        )

    db_license.status = "active"
    db_license.revoked_at = None
    db_license.revoked_reason = None
    db_license.suspended_at = None
    db_license.suspended_by = None
    db_license.suspended_reason = None

    await db.commit()
    await db.refresh(db_license)

    logger.info(
        f"Federation license reinstated by admin {admin.email}: "
        f"id={license_id}, operator={db_license.operator_name}"
    )

    # §FEDLICENCE improvement 8: a revoke synced "revoked" to the store and a reinstate never undid it, so the store kept
    # the reinstated licence revoked. The same path now carries "active".
    await _sync_license_to_eventstore(
        license_id=license_id,
        operator_name=db_license.operator_name,
        license_key_hash=db_license.license_key_hash,
        op_status="active",
    )
    await _emit_license_status_event(db, "FederationLicenseReinstated", db_license, admin,
                                     reinstated_at=datetime.now(timezone.utc).isoformat())

    return db_license


@router.delete(
    "/{license_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Federation License",
)
async def delete_federation_license(
    license_id: str,
    admin: models.Developer = Security(security.require_admin_flag("admin_federation")),
    db: AsyncSession = Depends(get_db),
):
    """
    Hard delete a federation license. This permanently removes the license
    record from the database. Use revoke for soft removal.

    Admin only — intended for cleanup of test/invalid licenses.
    """
    result = await db.execute(
        select(models.FederationLicense).where(
            models.FederationLicense.id == license_id
        )
    )
    db_license = result.scalar_one_or_none()

    if not db_license:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Federation license not found: {license_id}",
        )

    logger.info(
        f"Federation license DELETED by admin {admin.email}: "
        f"id={license_id}, operator={db_license.operator_name}, did={db_license.operator_did}"
    )

    gone = (db_license.operator_name, db_license.license_key_hash)
    gone_licence = SimpleNamespace(id=license_id, operator_did=db_license.operator_did,
                                   operator_name=db_license.operator_name)
    await db.delete(db_license)
    await db.commit()

    # §FEDLICENCE improvement 8: the store's row outlived the deleted licence as "active"; it is closed as revoked (the
    # store has no deleted state), by the same path revoke takes.
    await _sync_license_to_eventstore(
        license_id=license_id,
        operator_name=gone[0],
        license_key_hash=gone[1],
        op_status="revoked",
    )
    # D6-800: and with the event revoke emits, so the TEG drops the operator as a partner.
    await _emit_license_status_event(db, "FederationLicenseSuspended", gone_licence, admin,
                                     reason="licence deleted", licence_status="revoked",
                                     revoked_at=datetime.now(timezone.utc).isoformat())

    return None
