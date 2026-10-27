"""Operator Self-Service — flare-gated cloud-op provisioning (PB-1 §67, 2026-05-11).

from ..es_ssl_helper import get_httpx_verify
Three endpoints — two Developer-JWT-authed, one public:

    GET  /api/v1/me/provisioning-eligibility           [dev JWT]
        Eligibility state for the calling developer. Used by the Operator
        Portal Eligibility tab. Returns 200 always (anonymous-friendly via
        the auth dep — caller without a JWT gets 401 from `get_current_developer`).

    POST /api/v1/operators/self-provision              [dev JWT]
        Self-service cloud-op provisioning. Developer must have
        provisioning_unlocked_until > NOW (else 402 Payment Required).
        On success: auto-creates + activates an OperatorApplication row,
        then invokes cloud_provisioner.provision_cloud_operator(). Returns
        the same payload shape as the admin endpoint.

    POST /api/v1/operators/request-frame               [public, no auth]
        Sovereign frame request (review-only — Commander reads + replies).
        Optional `create_account=true` checkbox creates a Developer with a
        magic-link reset_token + sends a magic-link email so the requester
        is reachable inside the system instead of via the Commander's inbox.
        Always sends a notification email to commander@theprotocol.cloud
        with the structured request body.

Architectural notes:

  • This router is ONLY useful on a registry that runs cloud_provisioner —
    today that's the Frame A mainframe (FIAT_GENESIS_REGISTRY=true). On
    operators the endpoint resolves but 503s. The flag is the natural gate.

  • Eligibility credit is accrued elsewhere (`fiat_onramp._grant_provisioning_credit`)
    on every direct-flow fiat purchase. This router only reads + gates on
    the credited state — never mints credit itself.

  • Application + activation are the existing audit primitives — instead of
    routing through the admin review path, this endpoint creates an already-
    activated application with the calling developer as both applicant and
    activator. The admin path (`/admin/operator-applications/{id}/approve`)
    stays untouched for non-self-service flows (manual operator handouts).

  • The legal posture (per the strategy doc): backers buy flares; provisioning
    is a side-effect of how much they backed. The 402 detail copy is deadpan
    by design — no marketing surface here. See views/OperatorPage.vue for the
    public-facing version of this story.
"""
import asyncio
import json
import logging
import os
import re
import secrets
import ssl
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status, Security
from pydantic import BaseModel, ConfigDict, EmailStr, Field, StrictInt, field_validator, model_validator
from typing import Annotated, Any, Dict, List, Literal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry import models, security
from agentvault_registry import schemas as _schemas
from agentvault_registry.database import get_db
from agentvault_registry.security import get_current_developer
from agentvault_registry.core.mainframe_gate import require_mainframe_only
from agentvault_registry.core.client_ip import effective_client_ip
# §pass73.3 (2026-05-27) — fix latent bug: this import was originally placed on
# line 3 INSIDE the module docstring (a typo from when the docstring was edited
# above the import) → never executed → `_fund_new_op_treasury` raised NameError
# on every call → genesis funding silently caught by the parent try/except →
# every self-provisioned cloud-op since §pass66 has had an empty treasury.
# Prod was funded manually post-provision (e.g., paris @ 2.5M AVT). Sandbox
# (no manual top-up) showed treasury=0 on every cloud-op.
from agentvault_registry.es_ssl_helper import get_httpx_verify
from agentvault_registry.services.cloud_provisioner import (
    provision_cloud_operator,
    count_active_cloud_operators,
    CLOUD_DOMAIN_SUFFIX,
    _safe_name,
)

logger = logging.getLogger(__name__)

# §pass66 (2026-05-22) — Self-service operator provisioning is mainframe-only:
# only sovereign mainframes can mint federation licenses + provision cloud-op
# Docker stacks. The `_is_genesis_registry()` env check below stays as a
# defense-in-depth gate (FIAT_GENESIS_REGISTRY env is closely tied to fiat
# rails which are also mainframe-only); the router-level gate gives the
# clear "mainframe-only" 503 message via the unified mainframe_gate module.

def _bayes_prior() -> float:
    """A peer we have never transacted with is UNMEASURED, not fully trusted.
    The column default of 1.0 was a claim; the Beta(1,1) point estimate is 0.5."""
    from ..services.bayesian_trust import PRIOR_POINT_ESTIMATE
    return PRIOR_POINT_ESTIMATE

router = APIRouter(
    prefix="/api/v1",
    tags=["Operator Self-Service"],
    dependencies=[Depends(require_mainframe_only)],
)

# Mirror cloud_operators.BETA_LIMIT — keep both endpoints in sync if the cap
# moves. Self-service hitting the cap returns 429 with the same friendly copy.
BETA_LIMIT = 30

# Match the rate used by fiat_onramp._grant_provisioning_credit so the UI
# math + backend math don't drift. This is read-only here — the credit path
# is the single writer.
_PROVISIONING_EUR_PER_MONTH = float(os.getenv("PROVISIONING_EUR_PER_MONTH", "25"))
_PROVISIONING_DAYS_PER_MONTH = int(os.getenv("PROVISIONING_DAYS_PER_MONTH", "30"))


def _is_genesis_registry() -> bool:
    """Self-provisioning runs on the genesis (mainframe) registry only.

    Frame A mainframe has FIAT_GENESIS_REGISTRY=true. Frame B has its own.
    Federated operators set this to false (or leave unset) and 503 on call.
    """
    return os.getenv("FIAT_GENESIS_REGISTRY", "false").lower() == "true"


# ----------------------------------------------------------------------
# Schemas
# ----------------------------------------------------------------------

class ProvisioningEligibility(BaseModel):
    """State of the calling developer's cloud-op provisioning eligibility.

    months_remaining is a float — Eligibility tab can render "3.4 months
    remaining" or floor for "3 months". Frontend's choice.
    """
    is_unlocked: bool = Field(..., description="True iff unlocked_until > NOW")
    unlocked_until: Optional[str] = Field(
        None, description="ISO-8601 cutoff timestamp; null if never backed"
    )
    months_total_purchased: int = Field(
        ..., description="Cumulative lifetime months credited (audit stat)"
    )
    months_remaining: float = Field(
        ..., description="Time-decayed months remaining (0.0 when expired)"
    )
    last_extended_at: Optional[str] = Field(
        None, description="ISO-8601 timestamp of the last extension (= unlocked_until - months×30d)"
    )
    eur_per_month: float = Field(
        ..., description="Rate the credit hook uses (UI math reference)"
    )


# §pass66 (2026-05-22) — Path C / Advanced Provisioning Form override types.
# These mirror RegistryCardOperatorPut / RegistryCardOperator / RegistryCardVisual
# etc. but with ALL fields Optional — required fields on the operator persona
# (developer_id, contact_email) are server-filled in
# `_apply_card_overrides_to_new_op` from the provision result. This means the
# UI can submit just the user-edited fields and the central reg builds a valid
# operator's `/admin/registry-card` PUT body automatically. The visual+links+
# commitments subsets are passed-through to the OP's validator, which checks
# them against the same catalogs (FLARE_*, color regex, etc.) as a normal
# operator-side edit. Failure to pass that validation is non-fatal — the
# provision succeeds; the OP keeps its defaults; we surface the error so the
# UI can show "edit via portal" guidance.


class ProvisionCardOperatorPersona(BaseModel):
    """Persona overrides for a fresh op. developer_id + contact_email are
    server-filled. All other fields Optional + pass-through."""
    model_config = ConfigDict(extra="forbid")
    display_name: Optional[str] = Field(None, min_length=1, max_length=128)
    bio: Optional[str] = Field(None, max_length=2000)
    company: Optional[str] = Field(None, max_length=256)
    url: Optional[str] = Field(None, pattern=r"^https?://", max_length=500)
    github_url: Optional[str] = Field(None, pattern=r"^https://github\.com/", max_length=500)
    twitter_handle: Optional[str] = Field(None, pattern=r"^@?[A-Za-z0-9_]{1,15}$")
    timezone: Optional[str] = Field(None, max_length=64)
    location_label: Optional[str] = Field(None, max_length=128)
    operator_avatar_url: Optional[str] = Field(None, pattern=r"^https?://", max_length=500)
    successor_contact: Optional[str] = Field(None, max_length=500)


class ProvisionCardOverrides(BaseModel):
    """Operator-editable Registry Card v0.3 subset for use at PROVISION TIME.

    Mirrors `schemas.RegistryCardOperatorPut` but with the operator persona
    relaxed (developer_id + contact_email auto-filled from the provision
    result). Other sub-models (visual, links, commitments) pass through as
    typed Dict[str, Any] — the OP's PUT endpoint validates them with its
    own RegistryCardVisual / RegistryCardLinks / RegistryCardCommitments
    schemas. We keep them loose here so we don't double-validate (and so a
    NEW v0.3 field added on the OP side doesn't break the central reg until
    the central reg is also rebuilt).
    """
    model_config = ConfigDict(extra="forbid")
    display_name: Optional[str] = Field(None, min_length=1, max_length=128)
    description: Optional[str] = Field(None, max_length=2000)
    tags: Optional[List[Annotated[str, Field(max_length=48)]]] = Field(None, max_length=20)   # as the PUT (CB-424)
    operator: Optional[ProvisionCardOperatorPersona] = None
    visual: Optional[Dict[str, Any]] = None
    links: Optional[Dict[str, Any]] = None
    commitments: Optional[Dict[str, Any]] = None


class SelfProvisionRequest(BaseModel):
    """Operator name + optional location + optional Registry Card v0.3 overrides.

    The name becomes the subdomain (lowercased, hyphenated, capped 40 chars).
    Lat/lng are passed through to cloud_provisioner so the operator's admin-
    developer location stamps a real landmark on the Cesium globe. Omitting
    them triggers the §pass66 curated-pool + hash + jitter fallback (operator
    lands in a major world city deterministic to the safe-name).

    §pass66 (2026-05-22) — Path C / Advanced Provisioning Form.
    `card_overrides` is the operator-editable subset of Registry Card v0.3
    (same shape as `/api/v1/admin/registry-card` PUT body — see
    `schemas.RegistryCardOperatorPut`). When supplied, the central registry
    logs in to the newly-provisioned operator as its seeded admin (using the
    one-time admin_password returned by cloud_provisioner) and PUTs the
    overrides → operator's local registry_card row gets the visual + persona
    + commitments + links overrides applied BEFORE the modal closes. The
    operator can still edit later via their own RegistryCard tab. Failure
    to apply overrides is NON-FATAL — provision still succeeds, error
    surfaces via the response's `card_overrides_applied` field for the UI.
    """
    name: str = Field(..., min_length=2, max_length=40)
    organization: Optional[str] = Field(None, max_length=255)
    use_case: Optional[str] = Field(None, max_length=2000)
    latitude: Optional[float] = Field(None, ge=-90, le=90)
    longitude: Optional[float] = Field(None, ge=-180, le=180)
    location_label: Optional[str] = Field(None, max_length=120)
    # §pass66 — Advanced Provisioning Form. Operator-editable v0.3 card subset.
    # See module docstring for the apply-after-provision flow.
    # Uses the relaxed ProvisionCardOverrides (above) so the UI doesn't need
    # to know developer_id/contact_email — those are server-filled.
    card_overrides: Optional[ProvisionCardOverrides] = None


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _eligibility_for_dev(dev: models.Developer) -> ProvisioningEligibility:
    """Build the eligibility payload from a Developer row."""
    now = datetime.now(timezone.utc)
    unlocked_until = dev.provisioning_unlocked_until
    months_total = dev.provisioning_months_total or 0

    is_unlocked = unlocked_until is not None and unlocked_until > now

    if unlocked_until is None or unlocked_until <= now:
        months_remaining = 0.0
        last_extended_at = None
    else:
        delta = unlocked_until - now
        months_remaining = round(
            delta.total_seconds() / (_PROVISIONING_DAYS_PER_MONTH * 86400),
            2,
        )
        # last_extended_at = unlocked_until - (months_total × 30d), floored to
        # NOW so a long-ago first-back doesn't show in the future.
        approx_first = unlocked_until - timedelta(
            days=months_total * _PROVISIONING_DAYS_PER_MONTH
        )
        last_extended_at = (approx_first if approx_first < now else now).isoformat()

    return ProvisioningEligibility(
        is_unlocked=is_unlocked,
        unlocked_until=unlocked_until.isoformat() if unlocked_until else None,
        months_total_purchased=months_total,
        months_remaining=months_remaining,
        last_extended_at=last_extended_at,
        eur_per_month=_PROVISIONING_EUR_PER_MONTH,
    )


# ----------------------------------------------------------------------
# Endpoints
# ----------------------------------------------------------------------

@router.get(
    "/me/provisioning-eligibility",
    response_model=ProvisioningEligibility,
    summary="Cloud-op provisioning eligibility for the calling developer",
)
async def get_my_provisioning_eligibility(
    current_developer: models.Developer = Security(get_current_developer),
):
    """Returns the current developer's cloud-op self-provisioning eligibility.

    Read-only: no side effects. Eligibility is credited elsewhere (the
    fiat-onramp settle path). NULL/past unlocked_until → is_unlocked=false.
    """
    return _eligibility_for_dev(current_developer)


@router.post(
    "/operators/self-provision",
    summary="Self-service cloud-op provisioning (flare-gated)",
)
async def self_provision_cloud_operator(
    body: SelfProvisionRequest,
    current_developer: models.Developer = Security(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """
    Provision a cloud-hosted operator registry for the calling developer. Gates, in order: the genesis registry
    (`FIAT_GENESIS_REGISTRY`, 503 otherwise), a provisioning unlock that has not expired (402 otherwise), the beta
    capacity (429 when exhausted), and a subdomain-safe name (400 otherwise). On success it records an activated
    operator application for the developer and provisions the operator with the same logic as the admin path. If the
    deploy fails, the application stays activated so an administrator can finish it.

    \f
    Provision a cloud-hosted operator registry for the calling developer.

    Gates (in order):
      1. FIAT_GENESIS_REGISTRY=true  → 503 if not (federated operators don't
         run cloud_provisioner).
      2. provisioning_unlocked_until > NOW → 402 if not eligible.
      3. Beta capacity (BETA_LIMIT) → 429 if exhausted.
      4. Subdomain-safe name → 400 if not.

    On success: auto-creates an `OperatorApplication` row marked activated
    (calling developer = applicant + activator), then calls
    `provision_cloud_operator()` (same business logic the admin path uses).
    Response shape mirrors the admin endpoint so the frontend can reuse the
    OperatorPortal cloud-card render path verbatim.

    Failure path is recoverable — the application row stays activated so
    Commander can complete provisioning manually via the admin endpoint
    afterward if anything goes sideways during deploy.
    """
    # Gate 1 — mainframe-only
    if not _is_genesis_registry():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Self-service provisioning runs on the mainframe only. "
                "This is a federated operator. There is nothing here for you."
            ),
        )

    # Gate 2 — eligibility (the actual flare-gate)
    eligibility = _eligibility_for_dev(current_developer)
    if not eligibility.is_unlocked:
        # Deadpan 402 — see strategy doc for tone reference.
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=(
                "You have not backed the network recently. "
                f"€{int(_PROVISIONING_EUR_PER_MONTH)} buys 1 month of this. "
                "Back the network at /become-a-backer. The flare is the point. "
                "The provisioning is the side-effect."
            ),
            headers={
                "X-Provisioning-Unlocked-Until": (
                    current_developer.provisioning_unlocked_until.isoformat()
                    if current_developer.provisioning_unlocked_until else "never"
                ),
                "X-Provisioning-Months-Total": str(
                    current_developer.provisioning_months_total or 0
                ),
            },
        )

    # Gate 3 — beta capacity
    active_count = await count_active_cloud_operators(db)
    if active_count >= BETA_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Cloud operator beta limit reached ({active_count}/{BETA_LIMIT}). "
                "Your eligibility does not expire while you wait."
            ),
        )

    # Gate 4 — subdomain-safe
    safe_name = re.sub(r'[^a-z0-9-]', '', (body.name or "operator").lower())[:40]
    if not safe_name or not re.match(r'^[a-z][a-z0-9-]*$', safe_name):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Operator name '{body.name}' cannot be used as a subdomain. "
                "Use lowercase letters, numbers, and hyphens only; start with a letter."
            ),
        )

    # SEC-21 (2026-10-17): a name the network reserves never becomes an operator's (core/operator_names)
    from ..core.operator_names import reserved_operator_name
    _reserved = reserved_operator_name(body.name)
    if _reserved:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Operator name '{body.name}' is reserved ({_reserved}). Choose another name.",
        )
    # SEC-23: nor one the network would confuse with a registry this one already knows
    from ..core.operator_names import colliding_peer_name
    _collides = await colliding_peer_name(db, body.name)
    if _collides:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Operator name '{body.name}' would be confused with {_collides}. Choose another name.",
        )

    # Pre-flight: name not already taken (active or historical).
    existing = await db.execute(
        select(models.OperatorApplication).where(
            models.OperatorApplication.name == body.name,
            models.OperatorApplication.cloud_torn_down_at.is_(None),
            models.OperatorApplication.cloud_hosted == True,
        )
    )
    if existing.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"An active cloud operator named '{body.name}' already exists.",
        )

    # ── Auto-create + activate an OperatorApplication ────────────────────
    # The application row is the audit primitive — even self-service flows
    # leave a paper trail. Calling developer becomes both applicant and
    # activator (no admin review). Bundle path stays empty (cloud-only path
    # doesn't need an operator-hosted bundle).
    now = datetime.now(timezone.utc)
    app_record = models.OperatorApplication(
        id=str(uuid.uuid4()),
        developer_id=current_developer.id,
        name=body.name,
        email=current_developer.email,
        organization=body.organization,
        deployment="cloud",  # explicit — self-service is cloud-only
        experience="experienced",  # the dev backed €25+; assume they know
        use_case=body.use_case,
        status="approved",
        reviewed_by=current_developer.id,
        reviewed_at=now,
        review_notes="self-service via flare-gated provisioning",
        activated_at=now,
        activated_developer_id=current_developer.id,
        # Cloud-only: skip activation-code dance entirely. The flare-gate IS
        # the auth boundary; activation_code_hash stays NULL because the dev
        # is the one calling this endpoint right now.
    )
    db.add(app_record)

    # Mark the developer as a federation operator so the existing /me
    # responses + sidebar gates surface the new portal capabilities.
    if not current_developer.is_federation_operator:
        current_developer.is_federation_operator = True
    if current_developer.federation_operator_status != "approved":
        current_developer.federation_operator_status = "approved"
    db.add(current_developer)

    # ── Bundle pre-create (mirrors operator_applications.activate_operator) ─
    # cloud_provisioner.provision_cloud_operator() requires application.bundle_path
    # to point at an existing tarball (line ~183). Activation creates one via
    # the sync `provision_operator(safe_name, operator_did) -> ProvisionResult`
    # — we replay the same call here for the self-service path.
    try:
        from agentvault_registry.services.operator_provisioner import provision_operator
        operator_did = f"did:theprotocol:operator:{safe_name}"
        provision_result = provision_operator(safe_name, operator_did)
        app_record.bundle_path = provision_result.bundle_path
        app_record.bundle_generated_at = now
        app_record.bundle_download_count = 0
        app_record.bundle_expires_at = now + timedelta(days=30)
        app_record.docker_registry_username = provision_result.docker_username
        app_record.spire_fingerprint = provision_result.fingerprint
        app_record.docker_pull_token_hash = provision_result.docker_pull_token_hash
        app_record.docker_pull_token_prefix = provision_result.docker_pull_token_prefix
        app_record.docker_pull_token_issued_at = now
        db.add(app_record)
        # §pass65 (2026-05-22) — COMMIT before invoking provision_cloud_operator.
        # provision_cloud_operator runs `docker compose up` inside a sidecar that
        # makes Docker pulls against images.theprotocol.cloud. The pulls trigger
        # token-auth requests at `/api/v1/docker-registry/token` which run in
        # a separate DB session and use READ COMMITTED isolation — so they
        # can't see the docker_pull_token_hash row until it's committed.
        # Previously a `db.flush()` here left the row pending-commit, the token
        # endpoint returned "no matching operator" → 401, every pull failed.
        await db.commit()
        await db.refresh(app_record)
        logger.info(
            "[self-provision] Bundle provisioned: name=%s bundle=%s fingerprint=%s entries=%d",
            safe_name, provision_result.bundle_path,
            provision_result.fingerprint, provision_result.entries_registered,
        )
    except Exception as exc:
        logger.exception(
            "[self-provision] Bundle generation failed for dev=%s name=%s",
            current_developer.id, body.name,
        )
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Bundle generation failed: {str(exc)[:300]}",
        )

    logger.info(
        "[self-provision] dev=%s name=%s app=%s — provisioning starting "
        "(unlocked_until=%s, months_total=%d)",
        current_developer.id, body.name, app_record.id,
        eligibility.unlocked_until, eligibility.months_total_purchased,
    )

    # ── Invoke the canonical cloud provisioner ───────────────────────────
    # §pass65 (2026-05-22) — pass the plaintext docker_pull_token through so
    # the sidecar that runs `docker compose up` can authenticate to
    # images.theprotocol.cloud and actually pull container images. Without
    # this, pulls 401 and the stack never starts (DB state created, but
    # zero containers — phantom operator).
    #
    # §pass66 (2026-05-22) — Path B / location stacking fix. When the caller
    # didn't supply lat/lng, the cloud_provisioner used to inherit the calling
    # developer's location → every test op Commander provisioned stacked on
    # Registry A's coords (Freilassing), hiding the sovereign mainframe on
    # the Cesium globe. Now: deterministic hash-of-safe-name → curated city
    # pool → small within-city jitter. Same operator name always lands at the
    # same point (re-provision continuity); explicit body.latitude/longitude
    # still overrides.
    _declared = body.latitude is not None and body.longitude is not None   # §LOCTRUTH
    _lat = body.latitude
    _lng = body.longitude
    _label = body.location_label
    if _lat is None or _lng is None:
        from agentvault_registry.core.operator_default_locations import pick_default_location
        _lat, _lng, _city_label = pick_default_location(safe_name)
        # Only auto-fill the label if the caller didn't provide one — they
        # might want a custom location name even if relying on auto-coords
        if not _label:
            _label = _city_label
        logger.info(
            f"[self-provision] auto-located dev={current_developer.id} name={safe_name} → "
            f"{_city_label} ({_lat:.4f}, {_lng:.4f}) — curated pool + hash + jitter"
        )

    try:
        result = await provision_cloud_operator(
            operator_name=safe_name,
            application=app_record,
            db=db,
            latitude=_lat,
            longitude=_lng,
            location_label=_label,
            location_is_declared=_declared,
            docker_pull_token=provision_result.docker_pull_token,
            docker_username=provision_result.docker_username,
        )
    except Exception as exc:
        logger.exception(
            "[self-provision] provision_cloud_operator failed for dev=%s name=%s",
            current_developer.id, body.name,
        )
        # Application row stays in DB so admin can recover via the manual path.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Provisioning failed: {str(exc)[:400]}",
        )

    # Persist cloud-hosted state on the application
    app_record.cloud_hosted = True
    app_record.cloud_url = result.cloud_url
    app_record.cloud_port_base = result.cloud_port_base
    app_record.cloud_provisioned_at = datetime.now(timezone.utc)
    app_record.cloud_torn_down_at = None
    app_record.cloud_stack_dir = result.cloud_stack_dir
    db.add(app_record)

    # Federation peer registration (mirrors cloud_operators.py:140-159).
    # §pass66 (2026-05-22) — use port 8443 (the INTERNAL docker port that
    # nginx-federation listens on), NOT the host-mapped federation_port.
    # Why: peer URLs are consumed by federation_sync + cross-TEG calls from
    # WITHIN the docker network where the alias `op-X.op.theprotocol.cloud`
    # resolves to the nginx-federation container's internal IP. That container
    # only listens on 8443 internally; the host-side mapped port (e.g. 27843)
    # is unreachable from inside the docker network. Paris's row has :8443
    # (working); qatest8/10/11/12/13 had :27843 (broken — cross-TEG fund
    # connection refused). Fix matches the working production pattern.
    peer_url = f"https://{safe_name}.{CLOUD_DOMAIN_SUFFIX}:8443"
    op_display = body.name
    try:
        peer = models.PeerRegistry(
            name=op_display,
            base_url=peer_url,
            status="ACTIVE",
            owner_developer_id=current_developer.id,
            admin_contact_email=current_developer.email,
            discovery_auth_info={},
            peer_type="cloud_operator",  # §BATCH5: typed at creation; the boot-time reclassify never sees a row written after boot
            health_check_failure_count=0,
            total_interactions=0,
            disputes_lost_with=0,
            bayesian_discount=_bayes_prior(),  # the Beta(1,1) point estimate: unmeasured, not trusted
        )
        db.add(peer)
        await db.flush()
        peer_registered = True
        logger.info(
            f"[self-provision] Federation peer registered: {op_display} → {peer_url}"
        )
    except Exception as exc:
        logger.warning(
            f"[self-provision] Peer registration failed (non-fatal): {exc}"
        )
        peer_registered = False

    await db.commit()

    logger.info(
        "[self-provision] dev=%s name=%s — provisioned at %s",
        current_developer.id, body.name, result.cloud_url,
    )

    # §pass66 (2026-05-22) — Path C / Advanced Provisioning Form.
    # If the caller supplied operator-editable Registry Card v0.3 overrides,
    # log in to the new op as its seeded admin (using the one-time password
    # returned by cloud_provisioner) and PUT the overrides via the standard
    # admin-card endpoint. Non-fatal — provision still succeeds if this fails;
    # operator can edit later via their own /admin/registry-card UI.
    card_overrides_applied: bool = False
    card_overrides_error: Optional[str] = None
    if body.card_overrides is not None:
        try:
            card_overrides_applied = await _apply_card_overrides_to_new_op(
                cloud_url=result.cloud_url,
                registry_port=result.registry_port,
                admin_email=result.admin_email,
                admin_password=result.admin_password,
                overrides=body.card_overrides,
            )
            logger.info(
                f"[self-provision] dev={current_developer.id} name={body.name} "
                f"— card overrides applied via cross-reg PUT"
            )
        except Exception as exc:
            card_overrides_error = str(exc)[:300]
            logger.warning(
                f"[self-provision] dev={current_developer.id} name={body.name} "
                f"— card overrides PUT failed (non-fatal): {card_overrides_error}"
            )

    # §pass66 (2026-05-22) — Provisioning genesis funding.
    # Fund the new operator's treasury with `OPERATOR_PROVISION_FUNDING_AVT`
    # (default 100,000) via cross-TEG transfer from the mainframe treasury.
    # Uses the existing `/treasury/cross-teg-fund` admin endpoint which
    # handles mint-on-demand if mainframe treasury is short.
    #
    # WHY: in TheProtocol, only AGENTS + TREASURY hold AVT (admin developers
    # don't have wallets). The seeded operator-admin gains access to the
    # treasury via their `admin_treasury` sub-flag, then distributes funds
    # to their agents via /teg/treasury/fund-agent. Without this funding,
    # cloud-op Mission Control shows empty treasury / supply / network pulse
    # because there's literally no AVT moving on the new TEG.
    #
    # Non-fatal — provision succeeds even if funding fails (e.g., cross-TEG
    # routing not yet established for a brand-new peer). Operator can request
    # a manual top-up via the admin /admin/cloud-operators/{id}/fund endpoint
    # later. The fund is keyed by application_id so re-runs are idempotent.
    # The TEG partner rule (ledgergate3): this frame's TEG runs a leg with the new operator only once it holds it as a
    # partner, and the genesis fund below no longer adds one. Registered first, whatever the funding amount.
    teg_partner_registered: bool = False
    try:
        from agentvault_registry.background_tasks.reactor_helpers import register_peer_partner_on_teg
        teg_partner_registered = (
            await register_peer_partner_on_teg(db, safe_name, source_label="self-provision")) is not None
    except Exception as exc:  # noqa: BLE001  non-fatal, as the funding: the frame's next leg to it adds the partner
        logger.warning(f"[self-provision] TEG partner registration for {safe_name} failed (non-fatal): {exc}")
    genesis_funding_applied: bool = False
    genesis_funding_error: Optional[str] = None
    from agentvault_registry.core.network_profile import money_knob as _money_knob  # §BATCH5: the profile owns this amount
    _genesis_amt_str = str(_money_knob("OPERATOR_PROVISION_FUNDING_AVT", "100000"))
    try:
        _genesis_amt_validate = float(_genesis_amt_str)
        if _genesis_amt_validate > 0:
            # correlation_id MUST fit varchar(36) on the TEGTransaction table.
            # app_record.id is a 36-char UUID — perfect idempotency anchor
            # (same provision = same correlation_id → TEG returns idempotent
            # success; different provisions = different UUIDs = unique).
            genesis_funding_applied = await _fund_new_op_treasury(
                operator_name=safe_name,
                amount=_genesis_amt_str,
                correlation_id=str(app_record.id),
                db=db,
            )
            logger.info(
                f"[self-provision] dev={current_developer.id} name={body.name} "
                f"— genesis funding {_genesis_amt_str} AVT applied "
                f"(cross-TEG transfer from mainframe treasury)"
            )
    except Exception as exc:
        genesis_funding_error = str(exc)[:300]
        logger.warning(
            f"[self-provision] dev={current_developer.id} name={body.name} "
            f"— genesis funding failed (non-fatal): {genesis_funding_error}"
        )

    return {
        "status": "provisioned",
        "cloud_url": result.cloud_url,
        "registry_port": result.registry_port,
        "federation_port": result.federation_port,
        "containers_started": result.containers_started,
        "federation_peer_registered": peer_registered,
        "federation_license_key": result.federation_license_key,
        "admin_email": result.admin_email,
        "admin_password": result.admin_password,
        "domain": f"{safe_name}.{CLOUD_DOMAIN_SUFFIX}",
        "application_id": app_record.id,
        "eligibility": _eligibility_for_dev(current_developer).model_dump(),
        # §pass66 — Path C surfaces. UI uses these to render a small
        # "✓ visual identity applied" or "⚠ overrides failed — apply later"
        # below the credentials block in the success modal.
        "card_overrides_applied": card_overrides_applied,
        "card_overrides_error": card_overrides_error,
        # §pass66 — Provisioning funding surfaces. UI renders "✓ funded with
        # 100,000 AVT" or "⚠ funding failed — manual top-up needed".
        "genesis_funding_applied": genesis_funding_applied,
        "teg_partner_registered": teg_partner_registered,
        "genesis_funding_amount_avt": _genesis_amt_str if genesis_funding_applied else None,
        "genesis_funding_error": genesis_funding_error,
    }


async def _fund_new_op_treasury(
    *,
    operator_name: str,
    amount: str,
    correlation_id: str,
    db: AsyncSession,
) -> bool:
    """Cross-TEG transfer N AVT from mainframe treasury to a fresh op's treasury.

    Calls the LOCAL mainframe's `/api/v1/teg/treasury/cross-teg-fund` endpoint
    (the registry-orchestrator surface) which in turn invokes the mainframe TEG's
    admin-keyed `/admin/treasury/cross-teg-fund-send`. The TEG handles mint-on-
    demand if mainframe treasury is short of `amount`.

    The mainframe self-call goes through the in-process FastAPI (using `apiClient`
    semantics) — we just need a Bearer token. We mint a TEG-admin-equivalent
    bearer by reusing the same Commander auth context flow, OR easier: call
    the TEG endpoint directly with TEG_ADMIN_API_KEY. The latter skips one
    HTTP hop + matches what cross_teg_treasury_fund does internally.

    Returns True on success; raises on any failure (caller wraps + non-fatal).
    """
    import httpx
    from agentvault_registry.routers.teg_integration import (
        TEG_API_BASE_URL, TEG_API_V1_PREFIX, TEG_ADMIN_API_KEY,
        _resolve_peer_target_for_cross_teg_fund,
    )

    # Resolve the new op's peer entry (must exist after provision_cloud_operator
    # + the peer-add step earlier in self_provision_cloud_operator). Without
    # this, the funding call wouldn't know where to send.
    resolved = await _resolve_peer_target_for_cross_teg_fund(operator_name, db)
    if not resolved:
        # The peer was added BEFORE this funding call (via the db.add(peer)
        # block earlier in self_provision_cloud_operator) and db.commit()
        # ran. So the row should be visible. If not, the topology is in a
        # state we don't trust — bail loudly.
        raise RuntimeError(
            f"Cannot resolve peer registry for operator '{operator_name}' — "
            f"funding aborted (peer row missing post-commit?)"
        )
    target_url, _target_cache_key_id = resolved

    # Call the mainframe TEG's cross-teg-fund-send directly. This is what
    # cross_teg_treasury_fund does internally; we skip the registry wrapper
    # because we already hold TEG_ADMIN_API_KEY in-process + the origin
    # allowlist is already satisfied (we ARE the mainframe).
    #
    # Payload shape per endpoints_treasury.CrossTEGFundSendRequest:
    #   amount: Decimal (sent as str — JSON auto-casts via pydantic)
    #   target_teg_id: required — "teg-<safe_name>" per cloud_provisioner convention
    #   target_url: optional mTLS override (we pass the resolved URL for determinism)
    #   correlation_id: required idempotency key
    #   reason: defaults to "cross_teg_fund"; we use "liquidity_provision" for audit
    teg_admin_headers = {
        "Authorization": f"Bearer {TEG_ADMIN_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "amount": str(amount),
        "target_teg_id": f"teg-{operator_name}",
        "target_url": target_url,
        "correlation_id": correlation_id,
        "reason": "liquidity_provision",
    }
    # §pass66 — retry loop on transient 503 ("Peer TEG unreachable or 5xx").
    # The fresh op's TEG isn't reachable immediately after docker compose up;
    # cert-writer + nginx-federation + frame-b network attach take ~5-15s
    # to settle. Local treasury debit IS committed on first attempt (the
    # TEG endpoint's Phase 1 always commits even when Phase 2 fails). On
    # retry with the SAME correlation_id the TEG resumes from Phase 2 →
    # the credit lands once peer is reachable. So even if all retries fail
    # in this provision request, the pending transaction is recoverable
    # via a manual retry of the same correlation_id later.
    import asyncio as _asyncio
    _MAX_ATTEMPTS = 5
    _RETRY_DELAY_SEC = 6.0
    last_error: Optional[str] = None
    async with httpx.AsyncClient(timeout=30.0, verify=get_httpx_verify()) as client:
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            resp = await client.post(
                f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}/admin/treasury/cross-teg-fund-send",
                json=payload,
                headers=teg_admin_headers,
            )
            if resp.status_code in (200, 201, 204):
                logger.info(
                    f"[fund-op-treasury] {operator_name} ← {amount} AVT "
                    f"(attempt {attempt}/{_MAX_ATTEMPTS}, "
                    f"correlation_id={correlation_id})"
                )
                return True
            last_error = f"HTTP {resp.status_code}: {resp.text[:300]}"
            # 503 = transient (peer unreachable). 400 = deterministic
            # (e.g., wrong target_teg_id) → no point retrying.
            if resp.status_code != 503 or attempt == _MAX_ATTEMPTS:
                break
            logger.info(
                f"[fund-op-treasury] {operator_name} attempt {attempt} got "
                f"503 (peer warming up?); retrying in {_RETRY_DELAY_SEC}s"
            )
            await _asyncio.sleep(_RETRY_DELAY_SEC)
    raise RuntimeError(f"cross-teg-fund-send failed after {_MAX_ATTEMPTS} attempts: {last_error}")


async def _apply_card_overrides_to_new_op(
    *,
    cloud_url: str,
    registry_port: int,
    admin_email: str,
    admin_password: str,
    overrides: "ProvisionCardOverrides",
) -> bool:
    """Cross-reg login + PUT — apply v0.3 card overrides to a freshly-provisioned op.

    Uses the OP's standard endpoints:
      1. POST /api/v1/auth/login (form-encoded) with seeded admin creds → JWT
      2. PUT  /api/v1/admin/registry-card with the overrides as JSON

    The seeded admin has all 5 sub-flags=true (set by `operator_seed.py`
    §pass65) so `require_admin_flag("admin_platform")` (the gate on the
    card admin endpoint) passes.

    Routing: uses the docker bridge gateway + the registry's host port
    (e.g. `http://172.17.0.1:27900`). Avoids the public `cloud_url` route
    because Docker's embedded DNS doesn't resolve `*.op.theprotocol.cloud`
    from inside the central reg container (the wildcard A record resolves
    publicly but not via Docker DNS), and bypasses LE-cert provisioning
    timing — the new op's cert-writer may still be warming up. The host
    nginx ALSO routes <the host's public IP>:443 → localhost:registry_port; we go
    DIRECT to that registry_port via the docker bridge to skip both nginx
    and cert validation entirely. Same-trust-boundary call (central reg
    just minted this op).

    Returns:
        True on PUT 200; raises on any other failure (caller wraps in
        try/except → non-fatal).
    """
    import httpx

    # §pass66 — use the docker bridge gateway + registry's host port.
    # See docstring for the rationale (DNS + cert provisioning timing).
    # Override via env if your docker setup uses a non-default bridge.
    _gw = os.getenv("DOCKER_BRIDGE_GATEWAY", "172.17.0.1")
    internal_url = f"http://{_gw}:{registry_port}"
    login_url = f"{internal_url}/api/v1/auth/login"
    put_url = f"{internal_url}/api/v1/admin/registry-card"

    # Strip Nones so the OP's validator doesn't see fields the user didn't
    # set (Pydantic exclude_none on the payload). Sub-models keep their None
    # values dropped too via the recursive serialization.
    overrides_payload = overrides.model_dump(exclude_none=True)

    # §pass66 — server-fill the operator persona's REQUIRED fields. The OP's
    # RegistryCardOperatorPut.operator expects a full RegistryCardOperator
    # (with developer_id + contact_email). On a fresh op the seeded admin is
    # always developer_id=1 (per operator_seed.py) and we know their email
    # from the provision result. Fill these in only if the user supplied AT
    # LEAST ONE operator-block override (display_name/bio/company/etc.), so
    # an unrelated-to-persona override (just visual, say) doesn't end up
    # auto-mounting a stub operator block on the OP.
    if "operator" in overrides_payload:
        persona = dict(overrides_payload["operator"])
        # Required-by-OP fields — server fills if user didn't (user can't).
        persona.setdefault("developer_id", 1)
        persona.setdefault("contact_email", admin_email)
        # display_name is also required on the OP side; default to the OP's
        # registry name (cloud_url subdomain — minus the protocol). Cleaner
        # than forcing the user to repeat it.
        if "display_name" not in persona:
            # Derive from cloud_url ("https://op-qatest9.op.theprotocol.cloud"
            # → "op-qatest9"). Falls back to admin_email's localpart on parse
            # failure.
            try:
                from urllib.parse import urlparse
                host = urlparse(cloud_url).hostname or ""
                persona["display_name"] = host.split(".")[0] or admin_email.split("@")[0]
            except Exception:
                persona["display_name"] = admin_email.split("@")[0]
        overrides_payload["operator"] = persona

    if not overrides_payload:
        logger.info(
            "[self-provision] card overrides payload empty after exclude_none "
            "— skipping cross-reg PUT (effectively no-op)"
        )
        return True

    async with httpx.AsyncClient(timeout=15.0, verify=get_httpx_verify()) as client:
        # 1. Login
        login_resp = await client.post(
            login_url,
            data={"username": admin_email, "password": admin_password},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if login_resp.status_code != 200:
            raise RuntimeError(
                f"login failed: HTTP {login_resp.status_code} {login_resp.text[:200]}"
            )
        jwt = login_resp.json().get("access_token", "")
        if not jwt:
            raise RuntimeError("login response missing access_token")

        # 2. PUT card overrides
        put_resp = await client.put(
            put_url,
            json=overrides_payload,
            headers={
                "Authorization": f"Bearer {jwt}",
                "Content-Type": "application/json",
            },
        )
        if put_resp.status_code not in (200, 204):
            raise RuntimeError(
                f"card PUT failed: HTTP {put_resp.status_code} {put_resp.text[:300]}"
            )
        return True


# ----------------------------------------------------------------------
# Frame Request — public form (review-only, optional account creation)
# ----------------------------------------------------------------------

FRAME_ANSWER_GROUPS = ("features", "treasury", "card", "network", "provisioning")
_FEATURE_KEY_RE = re.compile(r"^[a-z_]{1,40}$")
_FEATURE_VALUE_RE = re.compile(r"^[A-Za-z0-9_.-]{1,16}$")
_PARTNER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}$")


def _not_bool(v: Any, what: str) -> Any:
    if isinstance(v, bool):
        raise ValueError(f"{what} is a number, not true or false")
    return v


class FrameAnswersTreasury(BaseModel):
    """Genesis numbers, kept as digit strings (the admin panel reads `mint` into the runner's spec)."""
    model_config = ConfigDict(extra="forbid")

    mint: Optional[str] = None
    genesis_grant: Optional[str] = None

    @field_validator("mint", "genesis_grant", mode="before")
    @classmethod
    def _whole_number(cls, v: Any, info) -> Optional[str]:
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        _not_bool(v, info.field_name)
        text = str(v).strip()
        if not re.fullmatch(r"[0-9]{1,10}", text):
            raise ValueError(f"{info.field_name} is a whole number written with digits only")
        low = 1 if info.field_name == "mint" else 0
        if not low <= int(text) <= 1_000_000_000:
            raise ValueError(f"{info.field_name} is between {low} and 1000000000")
        return str(int(text))


class FrameAnswersCard(BaseModel):
    """The registry card prefill: what the frame's signed card will say about it."""
    model_config = ConfigDict(extra="forbid")

    description: Optional[str] = Field(None, max_length=400)
    website: Optional[str] = Field(None, max_length=200)
    location: Optional[str] = Field(None, max_length=80)
    lat: Optional[float] = Field(None, ge=-90, le=90)
    lng: Optional[float] = Field(None, ge=-180, le=180)
    tags: Optional[List[str]] = None
    theme: Optional[Literal["neural", "sovereign"]] = None

    @field_validator("description", "location")
    @classmethod
    def _trimmed(cls, v: Optional[str]) -> Optional[str]:
        return (v or "").strip() or None

    @field_validator("lat", "lng", mode="before")
    @classmethod
    def _coordinate(cls, v: Any, info) -> Any:
        if isinstance(v, str):
            raise ValueError(f"{info.field_name} is a number")
        return _not_bool(v, info.field_name)

    @field_validator("website")
    @classmethod
    def _https(cls, v: Optional[str]) -> Optional[str]:
        if v is None or not v.strip():
            return None
        v = v.strip()
        if not v.startswith("https://") or len(v) <= len("https://") or any(c.isspace() for c in v):
            raise ValueError("website is empty or an https:// address without spaces")
        return v

    @field_validator("tags", mode="before")
    @classmethod
    def _tags(cls, v: Any) -> Optional[List[str]]:
        if v is None:
            return None
        if isinstance(v, str):
            v = v.split(",")
        if not isinstance(v, list) or not all(isinstance(t, str) for t in v):
            raise ValueError("tags are a list of words, or one comma-separated string")
        tags = list(dict.fromkeys(t.strip() for t in v if t.strip()))
        if len(tags) > 8:
            raise ValueError("at most 8 tags")
        if any(len(t) > 24 for t in tags):
            raise ValueError("a tag is at most 24 characters")
        return tags or None

    @model_validator(mode="after")
    def _a_place_is_both_coordinates(self) -> "FrameAnswersCard":
        if (self.lat is None) != (self.lng is None):
            raise ValueError("lat and lng come together or not at all")
        return self


class FrameAnswersNetwork(BaseModel):
    """Federation intent. Federation is a bilateral act after launch, never part of the standup (his decision)."""
    model_config = ConfigDict(extra="forbid")

    intent: Optional[Literal["federate_later", "standalone", "standalone_test_operator"]] = None
    partners: Optional[List[str]] = None
    # Who runs the frame, which decides the plan of the network licence it is issued when it federates (his words
    # 2026-09-28: "free license for educational, research and non profits. but enterprise and goverment orgs will not
    # have the same privilige"). services.federation_licence.NETWORK_PLANS without the network's own two (genesis,
    # founding); tests/test_federation_licence.py keeps the two lists equal.
    licence_category: Optional[Literal["private", "educational", "research", "non-profit", "enterprise", "government"]] = None

    @field_validator("partners")
    @classmethod
    def _partners(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is None:
            return None
        names = list(dict.fromkeys(p.strip() for p in v if p.strip()))
        if len(names) > 8:
            raise ValueError("at most 8 partner frames")
        if any(not _PARTNER_RE.fullmatch(p) for p in names):
            raise ValueError("a partner is a frame name: letters, digits, space, dot, underscore or hyphen, at most 64")
        return names or None


class FrameAnswersProvisioning(BaseModel):
    """How the requester pictures running the frame. Nothing here provisions anything; a human still decides."""
    model_config = ConfigDict(extra="forbid")

    hosting: Optional[Literal["theprotocol", "self"]] = None
    posture: Optional[Literal["pilot", "production"]] = None
    operators: Optional[StrictInt] = Field(None, ge=0, le=4)

    @field_validator("posture", mode="before")
    @classmethod
    def _legacy_stage(cls, v: Any) -> Any:
        # V0364 (his word: "sandbox" undersold a whole frame): the form calls the first stage "pilot". V0363 sent
        # "sandbox", the frame runner's name for the posture it stands up, and a page loaded before the roll still does.
        return "pilot" if v == "sandbox" else v


class FrameRequestAnswers(BaseModel):
    """The `answers` object of a frame request (2026-09-13 form rebuild): five known groups, each shape-checked, the
    whole at most 8 KB. A public, unauthenticated endpoint must not become a blob store, and the admin panel reads
    exactly these groups."""
    model_config = ConfigDict(extra="forbid")

    features: Optional[Dict[str, str]] = None
    treasury: Optional[FrameAnswersTreasury] = None
    card: Optional[FrameAnswersCard] = None
    network: Optional[FrameAnswersNetwork] = None
    provisioning: Optional[FrameAnswersProvisioning] = None

    @model_validator(mode="before")
    @classmethod
    def _bounded(cls, v: Any) -> Any:
        if v is None:
            return {}
        if not isinstance(v, dict):
            raise ValueError("answers is an object")
        if len(json.dumps(v, default=str)) > 8000:
            raise ValueError("answers payload too large (8 KB max)")
        unknown = sorted(str(k) for k in v if k not in FRAME_ANSWER_GROUPS)
        if unknown:
            raise ValueError(f"answers takes only the groups {', '.join(FRAME_ANSWER_GROUPS)}; "
                             f"not {', '.join(unknown)}")
        return v

    @field_validator("features")
    @classmethod
    def _switches(cls, v: Optional[Dict[str, str]]) -> Optional[Dict[str, str]]:
        if v is None:
            return None
        if len(v) > 40:
            raise ValueError("features takes at most 40 switches")
        for key, value in v.items():
            if not _FEATURE_KEY_RE.fullmatch(key):
                raise ValueError(f"features: {key[:40]!r} is not a switch name (a-z and _, at most 40)")
            if not _FEATURE_VALUE_RE.fullmatch(value):
                raise ValueError(f"features.{key}: a switch value is one short word, at most 16 characters")
        # §FESUITE V0595: against the configuration catalog (services/env_catalog.py), the one the provisioner applies:
        # a frame chooses every setting; an unknown key or an option the catalog does not offer is refused with the
        # reason. Two switches became modes; a console from before them still sends yes/no, translated, never refused.
        from agentvault_registry.services.env_catalog import validate_choices as _validate_env
        legacy = {("liability_card", "yes"): "shadow", ("liability_card", "no"): "off",
                  ("cross_frame_contracts", "yes"): "enforce", ("cross_frame_contracts", "no"): "off"}
        v = {k: legacy.get((k, str(val).lower()), val) for k, val in v.items()}
        clean, errors = _validate_env(v, "frame")
        if errors:
            raise ValueError("features: " + "; ".join(errors))
        return clean

    def normalized(self) -> Dict[str, Any]:
        """The validated answers as stored and mailed. Empty groups are dropped, so {} still means defaults
        everywhere."""
        return {group: val for group, val in self.model_dump(exclude_none=True).items() if val not in ({}, [], "")}


class FrameRequestBody(BaseModel):
    # §LEGALKIT: a frame request is an application under the Terms and the Operator Terms; the form asks.
    accept_terms: bool = Field(False, description="The applicant accepted the Terms of Service and the Federation Operator Terms (required).")
    """Public sovereign-frame request from /operator (Frames tab) or
    /operator/request-frame deep-link.

    Frames are review-only — the Commander reads the email + decides. This
    endpoint emails the request, PERSISTS it as a `frame_requests` row
    (§FRAMEFORM, mig 0172 — it used to store nothing, so the answers lived only
    in an inbox and had to be re-typed into the provisioning form), and
    optionally creates a Developer with a magic-link reset_token so the
    requester is reachable inside the system later.
    """
    organization: str = Field(..., min_length=1, max_length=200)
    contact_name: str = Field(..., min_length=1, max_length=120)
    email: EmailStr
    # §FRAMEFORM: was required. Most people asking for a test frame do not own
    # a domain and we host it under ours, and the intake mail explicitly says a
    # blank hostname is fine — a form that then demands one contradicts the mail
    # that sent them here. Loosening only: every existing caller still validates.
    trust_domain: Optional[str] = Field(None, min_length=3, max_length=200)
    # Legacy: the retired Frame A / Frame B pairing (the old form's select, the MCP tool). Accepted, never required, and
    # no longer defaulted: a request that names none pairs with nothing (2026-09-13 form rebuild).
    pair_with: Optional[str] = Field(None, max_length=32, description="legacy: frame-a | frame-b | both")
    use_case: str = Field(..., min_length=10, max_length=2000)
    notes: Optional[str] = Field(None, max_length=2000)
    create_account: bool = Field(
        False,
        description=(
            "If true, create a Developer with a magic-link reset_token + send "
            "the magic-link login email. Idempotent on email — won't duplicate."
        ),
    )

    # ── §FRAMEFORM additions. ALL OPTIONAL, deliberately: the intake mail tells
    # people to answer seven lines and skip the rest, and any client that
    # predates this (or a person who skipped a box) must still be able to
    # submit. Shape is validated, completeness never is.
    # 2026-09-13 (the form rebuild, his word): the shapes follow the host frame runner's spec, so a request always maps
    # into a frame the runner can provision (frame_runner.validate_spec: a name of 2 to 32 not ending with '-', a
    # ticker of 2 to 6, frame_label 60, currency_name 40).
    frame_name: Optional[str] = Field(
        None, pattern=r"^[a-z][a-z0-9-]{1,29}[a-z0-9]$",
        description="lowercase slug, 3 to 31 characters, not ending with '-'; becomes container and stack names")
    display_name: Optional[str] = Field(None, max_length=60)
    hostname: Optional[str] = Field(
        None, max_length=255, pattern=r"^[a-z0-9]([a-z0-9.-]{1,253}[a-z0-9])?$",
        description="blank means we host it under our own domain")
    ticker: Optional[str] = Field(None, pattern=r"^[A-Z]{2,6}$")
    currency_name: Optional[str] = Field(None, max_length=40)
    federation_choice: Optional[str] = Field(
        None, pattern=r"^[ABC]$",
        description="A federated | B standalone | C standalone + test operator")
    answers: FrameRequestAnswers = Field(
        default_factory=FrameRequestAnswers,
        description="Only what differs from the defaults, in five known groups: "
                    "features, treasury, card, network, provisioning.")


def _summarise_frame_answers(answers: Dict[str, Any]) -> str:
    """One human line for what the submitter set, group by group: nested objects as k=v, lists in brackets.

    The form sends ONLY what differs from the defaults, so an empty dict really
    does mean "defaults everywhere" and must say so rather than render blank.
    """
    def render(val: Any, nested: bool = False) -> str:
        if isinstance(val, dict):
            return ", ".join(f"{k}={render(x, True)}" for k, x in sorted(val.items()) if x not in (None, "", {}, []))
        if isinstance(val, (list, tuple)):
            text = ", ".join(render(x, True) for x in val if x not in (None, "", {}, []))
            return f"[{text}]" if nested else text
        return str(val)

    parts: List[str] = []
    for group, val in sorted((answers or {}).items()):
        text = render(val)
        if text:
            parts.append(f"{group}: {text}")
    return " | ".join(parts) if parts else "defaults everywhere"


_FEDERATION_CHOICES = {"A": "federated", "B": "standalone", "C": "standalone + test operator"}
_NETWORK_INTENTS = {"federate_later": "federate later, bilateral", "standalone": "standalone",
                    "standalone_test_operator": "standalone + test operator"}
_HOSTING = {"theprotocol": "we host it", "self": "their own infrastructure"}


def _frame_request_rows(body: FrameRequestBody, answers: Dict[str, Any], request_id: Optional[str],
                        submitted: str) -> List[tuple]:
    """The commander notice, one row per question. The legacy pairing row only when a client still sends one."""
    card, network, prov = answers.get("card", {}), answers.get("network", {}), answers.get("provisioning", {})
    rows: List[tuple] = [
        ("Organization", body.organization),
        ("Contact", f"{body.contact_name} <{body.email}>"),
        ("Trust domain", body.trust_domain or "we host it under ours"),
    ]
    if body.pair_with is not None:
        rows.append(("Pair with", body.pair_with))
    place = card.get("location") or ""
    if card.get("lat") is not None:
        place = f"{place} ({card['lat']}, {card['lng']})".strip()
    federation = " · ".join(x for x in (_FEDERATION_CHOICES.get(body.federation_choice or "", ""),
                                        _NETWORK_INTENTS.get(network.get("intent", ""), "")) if x)
    posture = prov.get("posture", "not given")
    if "operators" in prov:
        posture += f", {prov['operators']} operator(s)"
    if body.ticker:
        currency = f"{body.ticker} ({body.currency_name})" if body.currency_name else body.ticker
    else:
        currency = "not given"
    rows += [
        ("Account asked", "Yes (auto-created on submit)" if body.create_account else "No"),
        ("Frame name", body.frame_name or "not given"),
        ("Display name", body.display_name or "not given"),
        ("Hostname", body.hostname or "we host it"),
        ("Currency", currency),
        ("Federation", federation or "not given"),
        ("Hosting", _HOSTING.get(prov.get("hosting", ""), "not given")),
        ("Posture", posture),
        ("Theme", card.get("theme", "not given")),
        ("Location", place or "not given"),
        ("Partners (later, bilateral)", ", ".join(network.get("partners", [])) or "none named"),
        ("Changed", _summarise_frame_answers(answers)),
        ("Request id", request_id or "not stored"),
        ("Submitted", submitted),
    ]
    return rows


_FRAME_OPS_INBOX = os.getenv(
    "FRAME_REQUESTS_NOTIFICATION_ADDRESS",
    "commander@theprotocol.cloud",
)


def _send_frame_notification_email(
    *, subject: str, template: str, context: dict, theme: str = "neural",
    to_address: Optional[str] = None,
) -> None:
    """Best-effort themed-email dispatch (fire-and-forget on the loop).

    Mirrors `_send_themed_notification` in operator_applications.py — kept
    local here to avoid pulling that whole module's import surface for a
    single endpoint.
    """
    from agentvault_registry.email_utils import send_themed_email
    recipient = to_address or _FRAME_OPS_INBOX

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
                "[frame-request] email send failed (template=%s, to=%s): %s",
                template, recipient, exc,
            )

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_dispatch())
    except RuntimeError:
        # No running loop (sync caller / tests). Fall back to asyncio.run.
        asyncio.run(_dispatch())


# ── §FRAMESHOWCASE: the requester's receipt ─────────────────────────
# His word 2026-09-14: every requester gets a receipt. A public POST that mails an address the caller typed can make this
# frame mail anyone, so the receipt is shaped for that: one per stored request (a repeat submission while a request is
# pending reuses the row and mails nothing), fixed text in our words (the request id, the frame name the body already
# validated as a slug, the time) and nothing a caller wrote, and a budget per address of origin and per hour that
# refuses when it cannot count. The stored row and the commander's notice never wait on it.
_RECEIPT_KEY = "registry:frame-request:receipts"


async def _receipt_budget(source: str) -> "tuple[bool, str]":
    """Count one receipt against its source's hourly budget and the node's. (allowed, reason); no counter, no receipt."""
    try:
        per_source = int(os.getenv("FRAME_REQUEST_RECEIPTS_PER_SOURCE_PER_HOUR") or "3")
        per_hour = int(os.getenv("FRAME_REQUEST_RECEIPTS_PER_HOUR") or "30")
    except ValueError:
        per_source, per_hour = 3, 30
    try:
        from agentvault_registry.background_tasks.leader import get_redis
        r = await get_redis()
    except Exception as exc:  # noqa: BLE001
        return False, f"counter unavailable ({exc})"
    if r is None:
        return False, "counter unavailable (no Redis on this node)"
    safe = re.sub(r"[^A-Za-z0-9_.:-]", "_", source or "unknown")[:64]
    try:
        for key, cap, what in ((f"{_RECEIPT_KEY}:source:{safe}", per_source, "this source's"),
                               (f"{_RECEIPT_KEY}:hour", per_hour, "the hour's")):
            n = await r.incr(key)
            if n == 1 or await r.ttl(key) < 0:
                await r.expire(key, 3600)
            if n > cap:
                return False, f"{what} budget is spent ({n} > {cap})"
    except Exception as exc:  # noqa: BLE001
        return False, f"counter unavailable ({exc})"
    return True, "ok"


def _send_frame_request_receipt(body: FrameRequestBody, request_id: str, received: str) -> None:
    """The receipt: our words, the request id, the validated frame name and the time. Nothing the caller wrote."""
    rows: List[tuple] = [("Request id", request_id)]
    if body.frame_name:
        rows.append(("Frame name", body.frame_name))
    rows.append(("Received", received))
    _send_frame_notification_email(
        subject="We received your frame request",
        template="admin_notice",
        context={
            "kicker_label": "FRAME REQUEST RECEIVED",
            "headline_text": "Your request is in.",
            "rows": rows,
            "body_text": (
                "A person reads every frame request and answers at this address, usually within seven business "
                "days. No frame is approved automatically.\n\n"
                "Keep the request id: it is how we find your request when you write to us.\n\n"
                "If you did not send this request, you can ignore this mail. No account was created for this address."
            ),
        },
        theme="neural",
        to_address=body.email,
    )


@router.post(
    "/operators/request-frame",
    summary="Submit a sovereign-frame request (public, review-only)",
)
async def request_frame(
    body: FrameRequestBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Public request for a sovereign frame, for review; no auth. The request is mailed to the registry's frame review
    address (`FRAME_REQUESTS_NOTIFICATION_ADDRESS`). With `create_account=true` and an address that is not yet a
    developer, a developer account is created and a sign-in link is mailed separately. Idempotent on the email
    address.

    \f
    Public sovereign-frame request endpoint.

    Always sends a notification email to commander@theprotocol.cloud
    (override via FRAME_REQUESTS_NOTIFICATION_ADDRESS env). When
    `create_account=true` AND the email isn't already a registered
    Developer, creates a new Developer with a magic-link reset_token
    and emails the magic link separately. Idempotent on email — repeat
    submissions with create_account=true don't duplicate existing devs.

    No auth required. The form lives at /operator (Frames tab) or
    /operator/request-frame.
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    # §XFFTRUST: nginx APPENDS the real peer to X-Forwarded-For, and
    # `request.client.host` under a proxy is whatever the proxy chain left
    # there. `effective_client_ip` reads the element the caller cannot write.
    submitted_from = effective_client_ip(request) or "unknown"
    if not body.accept_terms:
        raise HTTPException(status_code=422, detail="You must accept the Terms of Service and the Federation Operator Terms to request a frame.")
    answers = body.answers.normalized()

    # ── §FRAMEFORM: persist BEFORE emailing ─────────────────────────
    # This endpoint used to store nothing at all, so a request existed only as
    # a mail in one inbox and the answers were re-typed into the provisioning
    # form by hand. The row is now the record; the mail is the notification.
    # Order matters: a mail that fails must not cost us the request, and a row
    # that fails to write must not silently look like a success.
    frame_request_id: Optional[str] = None
    stored_new = False   # a row THIS submission created; a repeat while one is pending reuses that row
    try:
        dupe = (await db.execute(
            select(models.FrameRequest).where(
                models.FrameRequest.contact_email == body.email,
                models.FrameRequest.status == "pending",
            )
        )).scalars().first()
        if dupe is None:
            existing_dev_id = (await db.execute(
                select(models.Developer.id).where(models.Developer.email == body.email)
            )).scalar_one_or_none()
            fr = models.FrameRequest(
                id=str(uuid.uuid4()),
                status="pending",
                contact_name=body.contact_name,
                contact_email=body.email,
                organization=body.organization,
                frame_name=body.frame_name,
                display_name=body.display_name,
                hostname=body.hostname,
                # The intake mail promises the trust domain follows the
                # hostname; this form asks for the trust domain outright, so
                # the hostname follows IT when only one was given.
                trust_domain=body.trust_domain,
                ticker=body.ticker,
                currency_name=body.currency_name,
                federation_choice=body.federation_choice,
                use_case=body.use_case,
                notes=body.notes,
                answers=answers,
                source_ip=submitted_from,
                developer_id=existing_dev_id,
            )
            db.add(fr)
            await db.flush()
            from ..services.legal_acceptance import SUBJECT_FRAME_REQUEST as _SUBJ, record_acceptance as _rec
            for _doc in ("terms", "operators"):
                await _rec(db, document=_doc, subject_kind=_SUBJ, subject_id=fr.id, via="frame_request",
                           developer_id=existing_dev_id, request=request)
            await db.commit()
            frame_request_id = fr.id
            stored_new = True
        else:
            # Not an error for the submitter: they get the same acknowledgement
            # either way. The admin sees one row, not two.
            frame_request_id = dupe.id
            logger.info("[frame-request] duplicate pending request from %s, kept %s",
                        body.email, dupe.id)
    except Exception as exc:
        # A node whose DB predates mig 0172 still accepts the request by email,
        # which is exactly how this endpoint behaved before §FRAMEFORM. Loud in
        # the log, invisible to the person filling the form.
        await db.rollback()
        logger.error("[frame-request] could not persist row (email path still ran): %s", exc)

    # ── Always: notify Commander inbox ──────────────────────────────
    _send_frame_notification_email(
        subject=f"Frame request: {body.organization}"
                + (f" ({body.trust_domain})" if body.trust_domain else ""),
        template="admin_notice",
        context={
            "kicker_label": "FRAME REQUEST",
            "headline_text": f"{body.organization} → "
                             f"{body.trust_domain or body.display_name or body.frame_name or 'a frame we host'}",
            "rows": _frame_request_rows(body, answers, frame_request_id, f"{timestamp} from {submitted_from}"),
            "body_text": (
                "USE CASE\n"
                "--------\n"
                f"{body.use_case}\n\n"
                + (f"NOTES\n-----\n{body.notes}\n" if body.notes else "")
            ),
        },
        theme="neural",
    )
    logger.info(
        "[frame-request] org=%r email=%s trust_domain=%s pair=%s create_account=%s",
        body.organization, body.email, body.trust_domain, body.pair_with,
        body.create_account,
    )

    # ── Optional: create Developer + magic-link ─────────────────────
    account_created = False
    magic_link_sent = False
    if body.create_account:
        # Idempotency: skip if email already maps to a Developer.
        existing = await db.execute(
            select(models.Developer).where(models.Developer.email == body.email)
        )
        existing_dev = existing.scalar_one_or_none()
        if existing_dev is None:
            # Build a non-colliding handle (mirrors fiat_onramp anon-flow pattern).
            local = re.sub(r'[^A-Za-z0-9._-]', '', body.contact_name.split("@")[0])[:40].strip("-_.")
            if not local:
                local = "frame-requester"
            chosen = local
            for attempt in range(4):
                row = await db.execute(
                    select(models.Developer.id).where(models.Developer.name == chosen).limit(1)
                )
                if row.scalar_one_or_none() is None:
                    break
                chosen = f"{local}-{secrets.token_hex(2)}"
            else:
                chosen = f"{local}-{secrets.token_hex(6)}"

            reset_token = secrets.token_urlsafe(32)
            reset_expiry = datetime.now(timezone.utc) + timedelta(days=7)
            temp_password = secrets.token_urlsafe(16)
            new_dev = models.Developer(
                name=chosen,
                email=body.email,
                hashed_password=security.hash_password(temp_password),
                is_verified=True,  # contact email verified by submitting the form
                must_change_password=True,
                password_reset_token=reset_token,
                password_reset_token_expires=reset_expiry,
            )
            db.add(new_dev)
            await db.commit()
            await db.refresh(new_dev)
            account_created = True
            logger.info(
                "[frame-request] created Developer id=%s email=%s for frame request",
                new_dev.id, body.email,
            )

            # Send magic-link login email to the requester. §FRAMESHOWCASE (2026-09-14): a link a person follows names
            # the console they use (core/public_url.py), never the API host. The old default sent every requester to
            # api.theprotocol.cloud, which serves EU, so a request made on ASIA mailed a link to a node without its token.
            from agentvault_registry.core.public_url import public_ui_origin
            origin = public_ui_origin()
            if origin:
                magic_link = f"{origin}/#/reset-password?token={reset_token}"
            else:
                base_url = os.getenv("PUBLIC_BASE_URL", "https://api.theprotocol.cloud")
                magic_link = f"{base_url.rstrip('/')}/ui/#/reset-password?token={reset_token}"
            _send_frame_notification_email(
                subject=f"Welcome to TheProtocol — your frame request is in",
                template="admin_notice",
                context={
                    "kicker_label": "WELCOME",
                    "headline_text": f"Hello {body.contact_name},",
                    "body_text": (
                        f"Your frame request for {body.organization}"
                        + (f" ({body.trust_domain})" if body.trust_domain else "")
                        + " has been received. "
                        "The Commander reads each request personally + replies. "
                        "Frames are not auto-approved.\n\n"
                        "While you wait — we created a developer account so we can "
                        "reach you inside the system. Use the magic link below to "
                        "set your password.\n\n"
                        f"MAGIC LINK\n----------\n{magic_link}\n\n"
                        "(Link expires in 7 days. After login, set a real password "
                        "in Settings.)"
                    ),
                },
                theme="neural",
                to_address=body.email,
            )
            magic_link_sent = True
        else:
            logger.info(
                "[frame-request] dev id=%s already exists for %s — skipping create",
                existing_dev.id, body.email,
            )

    # ── §FRAMESHOWCASE: every requester hears back once ─────────────
    # His word 2026-09-14 ("1. yes": every requester gets a receipt). The welcome above already tells a new account
    # holder the request is in; everyone else gets the receipt, once per stored request and inside its budget.
    receipt_sent = False
    if stored_new and not magic_link_sent:
        allowed, reason = await _receipt_budget(submitted_from)
        if allowed:
            _send_frame_request_receipt(body, frame_request_id, timestamp)
            receipt_sent = True
        else:
            logger.warning("[frame-request] no receipt for request %s: %s", frame_request_id, reason)

    return {
        "submitted": True,
        "account_created": account_created,
        "magic_link_sent": magic_link_sent,
        "receipt_sent": receipt_sent,
        "review_eta": "We read every frame request. Reply within ~7 business days.",
        # the stored row's id (None when this node could not persist it): the form shows it as the receipt
        "request_id": frame_request_id,
    }
