"""
f051: Cloud-Hosted Operator Admin Endpoints

Admin endpoints for provisioning, managing, and tearing down cloud-hosted
operator registries on the production server.

Routes:
  POST /api/v1/admin/cloud-operators/{app_id}/provision  — Provision cloud stack
  POST /api/v1/admin/cloud-operators/{app_id}/teardown    — Tear down cloud stack
  GET  /api/v1/admin/cloud-operators                      — List cloud operators
  GET  /api/v1/admin/cloud-operators/{app_id}/health      — Health check
"""
import asyncio
import logging
import os
import subprocess
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status, Security
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

from agentvault_registry import models, schemas, security
from agentvault_registry.database import get_db
from agentvault_registry.event_emitter import get_event_emitter
from agentvault_registry.services import operator_renamer
from agentvault_registry.services.cloud_provisioner import (
    provision_cloud_operator,
    teardown_cloud_operator,
    count_active_cloud_operators,
    emit_peer_registry_deactivated,
    sync_teardown_licence_to_store,
    restart_cloud_service,
    fetch_cloud_logs,
    CLOUD_OP_RESTARTABLE_SERVICES,
    CLOUD_DOMAIN_SUFFIX,
    _safe_name,
    _cloud_operator_did,
)

logger = logging.getLogger(__name__)

# §pass66 (2026-05-22) — Mainframe-only gate. Cloud-operators must not
# independently provision sub-operators (that would create chained federation
# topologies that the mainframe doesn't own). Single dependency at the router
# level → every endpoint under /admin/cloud-operators returns 503 on a
# cloud-op registry.
from agentvault_registry.core.mainframe_gate import require_mainframe_only
from fastapi import Depends


def _bayes_prior() -> float:
    """A peer we have never transacted with is UNMEASURED, not fully trusted.
    The column default of 1.0 was a claim; the Beta(1,1) point estimate is 0.5."""
    from ..services.bayesian_trust import PRIOR_POINT_ESTIMATE
    return PRIOR_POINT_ESTIMATE

router = APIRouter(
    prefix="/api/v1/admin/cloud-operators",
    tags=["Cloud Operators (Admin)"],
    dependencies=[Depends(require_mainframe_only)],
)

BETA_LIMIT = 30


@router.post(
    "/{application_id}/provision",
    summary="Provision a cloud-hosted operator registry",
)
async def provision_cloud(
    application_id: str,
    latitude: float | None = None,
    longitude: float | None = None,
    location_label: str | None = None,
    worker_count: int = 8,
    current_admin: models.Developer = Security(security.require_admin_flag("admin_federation")),
    db: AsyncSession = Depends(get_db),
):
    """
    Provision a cloud-hosted operator registry for an activated operator application.

    Creates a full Docker stack (9 containers), nginx vhost, federation peer registration,
    and federation sync trigger. Takes ~90 seconds.

    Optional query params `latitude`/`longitude`/`location_label` stamp the operator's
    admin developer with coordinates so the Cesium globe places the operator glyph
    at its real landmark. If omitted, the operator shows up at a hash-scattered
    fallback until the admin edits their profile via /agents/locations/me.

    Requires: application is activated, not already cloud-hosted, beta limit not exceeded.
    """
    # Fetch application
    result = await db.execute(
        select(models.OperatorApplication).where(
            models.OperatorApplication.id == application_id
        )
    )
    app_record = result.scalar_one_or_none()
    if not app_record:
        raise HTTPException(status_code=404, detail="Application not found")

    # Validate state
    if not app_record.activated_at:
        raise HTTPException(
            status_code=400,
            detail="Application must be activated before cloud provisioning"
        )

    if app_record.cloud_hosted and not app_record.cloud_torn_down_at:
        raise HTTPException(
            status_code=409,
            detail=f"Already cloud-hosted at {app_record.cloud_url}"
        )

    # Check beta limit
    active_count = await count_active_cloud_operators(db)
    if active_count >= BETA_LIMIT:
        raise HTTPException(
            status_code=429,
            detail=f"Cloud operator beta limit reached ({active_count}/{BETA_LIMIT})"
        )

    # Validate name is subdomain-safe
    import re
    safe_name = re.sub(r'[^a-z0-9-]', '', (app_record.name or "operator").lower())[:40]
    if not safe_name or not re.match(r'^[a-z][a-z0-9-]*$', safe_name):
        raise HTTPException(
            status_code=400,
            detail=f"Operator name '{app_record.name}' cannot be used as a subdomain. "
                   f"Use lowercase letters, numbers, and hyphens only."
        )

    # Provision
    logger.info(f"[CLOUD-ADMIN] Provisioning cloud operator: {safe_name} "
                f"(app={application_id}, admin={current_admin.email})")

    # §pass66 (2026-05-22) — Path B / location stacking fix. Same auto-pick
    # logic as the self-service path: when lat/lng are None, deterministically
    # pick a city from the curated pool so admin-provisioned ops don't stack
    # on Commander's location either.
    _lat = latitude
    _lng = longitude
    _label = location_label
    _declared = latitude is not None and longitude is not None   # §LOCTRUTH — declared vs globe-legibility
    if _lat is None or _lng is None:
        from agentvault_registry.core.operator_default_locations import pick_default_location
        _lat, _lng, _city_label = pick_default_location(safe_name)
        if not _label:
            _label = _city_label
        logger.info(
            f"[CLOUD-ADMIN] auto-located {safe_name} → {_city_label} "
            f"({_lat:.4f}, {_lng:.4f}) — curated pool + hash + jitter"
        )

    # §FRAMELIC (2026-09-07, findings row 131) — THE ADMIN PATH NEVER HANDED OVER THE PULL
    # CREDENTIAL. §pass65 wired the plaintext `docker_pull_token` through the SELF-SERVICE
    # provisioning path (operator_self_service.py) so the sidecar running `docker compose up` can
    # authenticate to images.theprotocol.cloud. This route — the one the standup driver and the
    # admin console both use — called the same provisioner WITHOUT it, so the provisioner took its
    # warning branch ("compose pull will likely 401"), wrote no `<stack>/.docker/config.json`, and
    # every pull answered `unauthorized: Missing or invalid Authorization header`. The operator
    # then reconciled to 0/9 containers and the log blamed host load. Two doors into one
    # provisioner, one of them wired: a fix applied at a CALL SITE instead of in the callee is a
    # fix that covers only the callers you were looking at.
    #
    # A token is minted here when the application has none in hand. We store only its hash (the
    # same three columns the rotate rail writes) and COMMIT BEFORE provisioning: the pull's
    # token-auth endpoint runs in its own READ COMMITTED session and cannot see an uncommitted
    # row — that is §pass65's own hard-won note, and it applies identically here.
    _pull_token: Optional[str] = None
    _pull_user = app_record.docker_registry_username or f"operator-{safe_name}"
    try:
        import hashlib as _hl
        import secrets as _sec
        _pull_token = f"dpt_{_sec.token_hex(32)}"
        app_record.docker_pull_token_hash = _hl.sha256(_pull_token.encode()).hexdigest()
        app_record.docker_pull_token_prefix = _pull_token[:8]
        app_record.docker_pull_token_issued_at = datetime.now(timezone.utc)
        app_record.docker_registry_username = _pull_user
        db.add(app_record)
        await db.commit()
        logger.info(
            f"[CLOUD-ADMIN] pull token issued for {safe_name} "
            f"(user={_pull_user}, prefix={app_record.docker_pull_token_prefix})"
        )
    except Exception as _tok_err:  # noqa: BLE001
        # A token we could not persist must NOT be handed to the sidecar: it would authenticate
        # against a hash nobody stored and fail in a way that reads like a registry outage.
        await db.rollback()
        _pull_token = None
        logger.error(
            f"[CLOUD-ADMIN] could not issue a pull token for {safe_name}: {_tok_err} — "
            f"provisioning will proceed and its image pulls will 401"
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
            worker_count=worker_count,
            docker_pull_token=_pull_token,
            docker_username=_pull_user,
        )
    except Exception as e:
        logger.error(f"[CLOUD-ADMIN] Provisioning failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Provisioning failed: {str(e)[:300]}"
        )

    # Update application record
    app_record.cloud_hosted = True
    app_record.cloud_url = result.cloud_url
    app_record.cloud_port_base = result.cloud_port_base
    app_record.cloud_provisioned_at = datetime.now(timezone.utc)
    app_record.cloud_torn_down_at = None
    app_record.cloud_stack_dir = result.cloud_stack_dir
    app_record.deployment = "cloud"

    # Register as federation peer on Registry A
    peer_registered = False
    peer_row_outcome = None      # what this provision did to the peer row, reported rather than inferred
    op_display = app_record.name or f"Cloud {safe_name}"
    # §pass66 (2026-05-22) — internal docker port 8443, not host-mapped port.
    # See operator_self_service._fund_new_op_treasury rationale.
    peer_url = f"https://{safe_name}.{CLOUD_DOMAIN_SUFFIX}:8443"
    # §pass73.3 (2026-05-27) — UPSERT pattern. Previously this was naive INSERT
    # + try/except → on duplicate base_url (e.g., re-provisioning after teardown
    # left an INACTIVE row behind) the IntegrityError poisoned the SQLAlchemy
    # session, causing the subsequent app_record updates + commit to fail with
    # PendingRollbackError. Net result: containers up, license issued, but
    # operator_applications.cloud_hosted stayed false → endpoint returned 500
    # even though provisioning succeeded. Fix: look up by base_url first.
    existing_peer = (await db.execute(
        select(models.PeerRegistry).where(models.PeerRegistry.base_url == peer_url)
    )).scalars().first()
    try:
        # S3 (2026-07-24): stamp the SVID this operator will actually present, so the
        # shared federation gate can bind the identity to THIS row instead of merely
        # shape-checking it. Must match the entry registered in register_spire_entries:
        #   spiffe://<trust-domain>/operator/<slug>/registry
        _peer_spiffe = (
            f"spiffe://{os.environ.get('SPIRE_TRUST_DOMAIN', 'agentvault.com')}"
            f"/operator/{safe_name}/registry"
        )

        if existing_peer:
            # Reactivate the existing row instead of inserting a duplicate.
            # ⚠ THIS WAS THE UNIDENTIFIED RAIL. It wrote `status = "ACTIVE"` bare, leaving deactivated_reason and
            # deactivated_at exactly as the teardown had set them — which is how beacon's row for jelgava came to
            # read ACTIVE while still claiming it was torn down (agentvault2-6a measured it; we spent three
            # versions calling the writer unidentified, and it was in this route all along, a few lines below the
            # service call that had just done the same job properly). update_peer_registry_status is the single
            # choke point precisely so status and its metadata cannot part company (RCA 2026-07-10).
            # ⚠ AND IT OVERRODE A POLICY THE SERVICE HAD JUST APPLIED. provision_cloud_operator asks
            # peer_row_action, which revives a row from ITS OWN teardown and deliberately refuses one deactivated
            # for any other reason — "a re-provision is not an amnesty". This line then reactivated it anyway,
            # three lines of code later, so an admin's deactivation was silently undone by a provision and the
            # admin's own reason stayed stamped on the now-ACTIVE row. The predicate decides here too.
            from agentvault_registry.crud.crud_peer_registry import update_peer_registry_status as _ups2
            from agentvault_registry.services.operator_provision_client import peer_row_action as _pra2
            _p_action, _p_why = _pra2(existing_peer.status, existing_peer.deactivated_reason)
            # Carried back in the answer so a caller learns the row's outcome from the response rather than by
            # reading the database afterwards. agentvault2-6a asked for it; a driver that has to SELECT to find
            # out what a route did is a driver that will eventually read a different row than the one it changed.
            _peer_outcome = {"action": _p_action or "left", "why": _p_why,
                             "was_status": existing_peer.status,
                             "was_reason": existing_peer.deactivated_reason}
            if (existing_peer.status or "").upper() != "ACTIVE" and _p_action != "revive":
                logger.warning(
                    f"[CLOUD-ADMIN] peer row for {op_display} left {existing_peer.status}: {_p_why}. The operator "
                    f"is being provisioned but this frame will not federate with it until that row is decided.")
            elif (existing_peer.status or "").upper() != "ACTIVE" or _p_action == "clear_stale":
                await _ups2(db, existing_peer, "ACTIVE", admin_id=current_admin.id, reason="reprovisioned")
            existing_peer.name = op_display
            existing_peer.owner_developer_id = current_admin.id
            existing_peer.admin_contact_email = app_record.email
            existing_peer.health_check_failure_count = 0
            existing_peer.spiffe_id = _peer_spiffe
            peer_registered = True
            peer_row_outcome = _peer_outcome
            logger.info(
                f"[CLOUD-ADMIN] Federation peer reactivated (existing row id={existing_peer.id}): "
                f"{op_display} → {peer_url}"
            )
        else:
            peer = models.PeerRegistry(
                name=op_display,
                base_url=peer_url,
                status="ACTIVE",
                owner_developer_id=current_admin.id,
                admin_contact_email=app_record.email,
                spiffe_id=_peer_spiffe,  # S3
                peer_type="cloud_operator",  # §BATCH5: typed at creation; the boot-time reclassify never sees a row written after boot
                discovery_auth_info={},
                health_check_failure_count=0,
                total_interactions=0,
                disputes_lost_with=0,
                bayesian_discount=_bayes_prior(),  # the Beta(1,1) point estimate: unmeasured, not trusted
            )
            db.add(peer)
            await db.flush()
            peer_registered = True
            logger.info(f"[CLOUD-ADMIN] Federation peer registered: {op_display} → {peer_url}")
    except Exception as e:
        # §pass73.3 — rollback the session to recover from IntegrityError so
        # the subsequent commit can complete. Without rollback, the session
        # enters a PendingRollbackError state and ALL subsequent operations
        # (including the app_record UPDATE applied earlier in this function)
        # silently get rolled back at commit. Net symptom: containers up,
        # license issued, but operator_applications.cloud_hosted stays false
        # → endpoint returns 500 despite provisioning having succeeded.
        # The existing_peer pre-check above SHOULD catch the duplicate-base_url
        # case before we get here, so this path is now defensive for unknown
        # IntegrityErrors (e.g., race with parallel federation_sync).
        logger.warning(f"[CLOUD-ADMIN] Peer registration failed (non-fatal): {e}")
        try:
            await db.rollback()
        except Exception as rb_exc:
            logger.warning(f"[CLOUD-ADMIN] Session rollback failed: {rb_exc}")
        # Re-apply the app_record updates after rollback so they actually persist.
        result_app = await db.execute(
            select(models.OperatorApplication).where(
                models.OperatorApplication.id == application_id
            )
        )
        app_record = result_app.scalar_one_or_none()
        if app_record:
            app_record.cloud_hosted = True
            app_record.cloud_url = result.cloud_url
            app_record.cloud_port_base = result.cloud_port_base
            app_record.cloud_provisioned_at = datetime.now(timezone.utc)
            app_record.cloud_torn_down_at = None
            app_record.cloud_stack_dir = result.cloud_stack_dir
            app_record.deployment = "cloud"

    await db.commit()

    # Trigger federation sync (non-blocking, best-effort)
    try:
        import httpx
        admin_token = None
        # Get a fresh admin token for the sync trigger
        login_r = httpx.post("http://localhost:8000/api/v1/auth/login",
            data=f"username={current_admin.email}&password=",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=5)
        # Fallback: use internal federation secret
        # §2026-07-27 — the `import os` that used to sit HERE made `os` a LOCAL
        # name for this whole function (Python binds locals per-function, not
        # per-statement). The `httpx.post` above routinely raises (it logs in
        # with an EMPTY password), so control jumped past this import and the
        # later `os.getenv("OPERATOR_PROVISION_FUNDING_AVT")` blew up with
        # `UnboundLocalError: cannot access local variable 'os'` — AFTER the
        # operator had been fully provisioned. That is the real reason every
        # cloud-provision returned HTTP 500 while actually succeeding (the
        # "long provision outlives its DB session" theory was wrong). `os` is
        # already imported at module scope; the shadowing import is deleted.
        fed_secret = os.environ.get("FEDERATION_INTERNAL_SECRET", "")
        httpx.post("http://localhost:8000/api/v1/federation/sync/trigger",
            json={"cascade": False},
            headers={"X-Federation-Secret": fed_secret,
                     # §PlanB-② / rule 15: env-derived trust domain (Frame A default agentvault.com).
                     "X-Federation-SPIFFE-ID": f"spiffe://{os.environ.get('SPIRE_TRUST_DOMAIN', 'agentvault.com')}/service/registry-a"},
            timeout=10)
        logger.info("[CLOUD-ADMIN] Federation sync triggered")
    except Exception as e:
        logger.warning(f"[CLOUD-ADMIN] Sync trigger failed (non-fatal): {e}")

    logger.info(f"[CLOUD-ADMIN] Cloud operator provisioned: {result.cloud_url}")

    # §pass73.3 (2026-05-27) — genesis funding (was only on self-provision path,
    # now mirrored here so admin-provisioned cloud-ops also get OPERATOR_PROVISION_FUNDING_AVT
    # (default 100,000 AVT) seeded into their treasury via cross-TEG fund from
    # the local mainframe treasury. Without this, the new cloud-op TEG has zero
    # AVT → fund-agent calls (e.g., canary agent prefund) fail with
    # "Treasury transfer failed: exhausted". Non-fatal — admin can manually
    # top-up later via `/treasury/cross-teg-fund` if this fails (e.g., cross-TEG
    # routing not yet established for a brand-new peer).
    # The TEG partner rule (ledgergate3): this frame's TEG runs a leg with the new operator only once it holds it as a
    # partner, and the genesis fund below no longer adds one. Registered first, whatever the funding amount.
    teg_partner_registered: bool = False
    try:
        from agentvault_registry.background_tasks.reactor_helpers import register_peer_partner_on_teg
        teg_partner_registered = (
            await register_peer_partner_on_teg(db, safe_name, source_label="CLOUD-ADMIN")) is not None
    except Exception as exc:  # noqa: BLE001  non-fatal, as the funding: the frame's next leg to it adds the partner
        logger.warning(f"[CLOUD-ADMIN] TEG partner registration for {safe_name} failed (non-fatal): {exc}")
    genesis_funding_applied: bool = False
    genesis_funding_error: Optional[str] = None
    # §BATCH5: the profile owns this amount (M2 knob OPERATOR_PROVISION_FUNDING_AVT = S0 × 5 %); an os.getenv here
    # ignored NETWORK_PROFILE and seeded 100,000 on a 1,000,000 ledger — measured on the JUICE rehearsal frame.
    from agentvault_registry.core.network_profile import money_knob as _money_knob
    _genesis_amt_str = str(_money_knob("OPERATOR_PROVISION_FUNDING_AVT", "100000"))
    try:
        _genesis_amt_validate = float(_genesis_amt_str)
        if _genesis_amt_validate > 0:
            from agentvault_registry.routers.operator_self_service import _fund_new_op_treasury
            genesis_funding_applied = await _fund_new_op_treasury(
                operator_name=safe_name,
                amount=_genesis_amt_str,
                correlation_id=str(app_record.id),
                db=db,
            )
            logger.info(
                f"[CLOUD-ADMIN] Genesis funding {_genesis_amt_str} AVT applied to "
                f"{safe_name} (cross-TEG transfer from mainframe treasury)"
            )
    except Exception as exc:
        genesis_funding_error = str(exc)[:300]
        logger.warning(
            f"[CLOUD-ADMIN] Genesis funding failed for {safe_name} "
            f"(non-fatal — admin can retry via /treasury/cross-teg-fund): {genesis_funding_error}"
        )

    return {
        "status": "provisioned",
        "cloud_url": result.cloud_url,
        "registry_port": result.registry_port,
        "federation_port": result.federation_port,
        "containers_started": result.containers_started,
        "federation_peer_registered": peer_registered,
        "peer_row": peer_row_outcome,
        "federation_license_key": result.federation_license_key,
        "admin_email": result.admin_email,
        "admin_password": result.admin_password,
        "domain": f"{safe_name}.{CLOUD_DOMAIN_SUFFIX}",
        # §pass73.3 — surface funding outcome to the UI / admin response.
        "genesis_funding_applied": genesis_funding_applied,
        "teg_partner_registered": teg_partner_registered,
        "genesis_funding_amount_avt": _genesis_amt_str if genesis_funding_applied else None,
        "genesis_funding_error": genesis_funding_error,
    }


@router.post(
    "/{application_id}/teardown",
    summary="Tear down a cloud-hosted operator registry",
)
async def teardown_cloud(
    application_id: str,
    body: schemas.CloudTeardownRequest = schemas.CloudTeardownRequest(),
    current_admin: models.Developer = Security(security.require_admin_flag("admin_federation")),
    db: AsyncSession = Depends(get_db),
):
    """
    Tear down a cloud-hosted operator. Stops containers, removes nginx vhost,
    deactivates federation peer, revokes license, and archives the stack directory.
    """
    result = await db.execute(
        select(models.OperatorApplication).where(
            models.OperatorApplication.id == application_id
        )
    )
    app_record = result.scalar_one_or_none()
    if not app_record:
        raise HTTPException(status_code=404, detail="Application not found")

    if not app_record.cloud_hosted or app_record.cloud_torn_down_at:
        raise HTTPException(status_code=400, detail="Not an active cloud operator")

    logger.info(f"[CLOUD-ADMIN] Tearing down cloud operator: {app_record.name} "
                f"(reason: {body.reason})")

    try:
        td_result = await teardown_cloud_operator(app_record, body.reason, db, purge=body.purge)
    except Exception as e:
        logger.error(f"[CLOUD-ADMIN] Teardown failed: {e}")
        raise HTTPException(status_code=500, detail=f"Teardown failed: {str(e)[:300]}")

    # ⚠ THE STAMP IS A CLAIM ABOUT THE HOST, so it waits for the host. This wrote unconditionally, and on a frame
    # whose registry holds no docker socket the SDK path returns False and only logs — so the row would read "torn
    # down" while the operator kept serving, the licence revoked and the peer deactivated around it. The service
    # now raises rather than returning a false success on that path, and this is the second half of the same rule:
    # a stamp that outlives what makes it true is worse than no stamp, because the next reader acts on it.
    if not td_result.containers_stopped:
        logger.error(f"[CLOUD-ADMIN] {app_record.name}: the host half removed nothing, so the row is left alone")
        raise HTTPException(
            status_code=502,
            detail=("The host teardown removed nothing, so this application has NOT been marked torn down and its "
                    "peer row and licence are unchanged. The operator may still be running; read the job's reason "
                    "on the frame runner before retrying."))
    app_record.cloud_torn_down_at = datetime.now(timezone.utc)
    await db.commit()
    await sync_teardown_licence_to_store(td_result, body.purge)

    # Audit emission moved to service-module helper so lifecycle tests (which
    # call teardown_cloud_operator directly) also fire the event.
    await emit_peer_registry_deactivated(
        application=app_record,
        td_result=td_result,
        reason=body.reason,
        actor_developer_id=current_admin.id,
        actor_email=current_admin.email,
    )

    return {
        "status": "torn_down",
        "containers_stopped": td_result.containers_stopped,
        "nginx_removed": td_result.nginx_removed,
        "peer_deactivated": td_result.peer_deactivated,
        "stack_archived": td_result.stack_archived,
        "reason": body.reason,
    }


# §2026-06-14 — Operator IDENTITY re-slug (rename Lane B). See
# PRODUCTION_DOCS/06_OPERATIONS/Operator_Rename.md and services/operator_renamer.py.
async def _run_rename_bg(application_id: str, new_slug: str, dry_run: bool) -> None:
    """Background wrapper for the rename cascade. Opens its OWN DB session — the
    request session from the 202 handler is already closed when this runs."""
    from agentvault_registry.database import AsyncSessionLocal
    try:
        async with AsyncSessionLocal() as bg_db:
            app = (await bg_db.execute(
                select(models.OperatorApplication).where(
                    models.OperatorApplication.id == application_id)
            )).scalar_one_or_none()
            if not app:
                operator_renamer._set_status(
                    _safe_name(application_id), "failed",
                    error="application vanished before rename started")
                return
            await operator_renamer.rename_operator(app, new_slug, bg_db, dry_run=dry_run)
    except Exception as e:
        logger.error(f"[CLOUD-ADMIN] rename bg task crashed: {e}")


class OperatorReconcileRequest(BaseModel):
    """Body for the mainframe-only operator IDENTITY reconcile — repairs residue
    left by a prior in-place rename (ghost old-slug peers, stale federated card
    source_registry SPIFFE, canary_remote_paths) WITHOUT a fresh Lane-B cascade."""
    old_slug: str = Field(..., min_length=1, max_length=64)
    new_slug: str = Field(..., min_length=1, max_length=64)
    new_base_url: Optional[str] = Field(None, max_length=300)
    new_operator_did: Optional[str] = Field(None, max_length=255)
    dry_run: bool = Field(True, description="Preview counts then rollback; no mutation, no fanout.")


@router.post(
    "/reconcile-identity",
    summary="Reconcile an operator's identity fleet-wide (repair prior-rename residue) — mainframe-only",
    include_in_schema=False,
)
async def reconcile_operator_identity(
    body: OperatorReconcileRequest,
    current_admin: models.Developer = Security(security.require_admin_flag("admin_federation")),
    db: AsyncSession = Depends(get_db),
):
    """Re-run the event-sourced operator-rename CONVERGENCE for an (old_slug → new_slug)
    pair WITHOUT a fresh Lane-B cascade. Repairs residue a prior in-place rename left
    on this frame and every peer:
      • ghost OLD-slug `discovered` peer_registries rows → INACTIVE,
      • stale federated agent-card `source_registry`/`*_synced_from` SPIFFE → reslug,
      • `origin_registry_name` + `canary_remote_paths.home_registry` → new slug.

    Mechanism (doctrine-compliant, NO cross-frame SQL): apply locally on THIS mainframe,
    then emit `OperatorRenamed` so `reactor_operator_renamed` fans the SAME apply out to
    every ACTIVE peer frame, each converging its OWN rows. Only the registry-owned
    `federation_metadata` envelope is rewritten — never the agent-signed card body — so
    NO per-agent login is required.

    GATING: router-wide `require_mainframe_only` (503 on cloud-ops — operators cannot emit
    this destructive action) + `admin_federation`. Run `dry_run=true` (default) first to
    preview counts. Idempotent.
    """
    old_slug = _safe_name(body.old_slug or "")
    new_slug = _safe_name(body.new_slug or "")
    if not old_slug or not new_slug or old_slug == new_slug:
        raise HTTPException(
            status_code=422,
            detail=f"old_slug/new_slug must be distinct valid slugs (got {old_slug!r} vs {new_slug!r})")

    # Capture now: apply_operator_rename_local commits/rolls-back the shared request
    # session, which expires ORM objects (current_admin) → a later attr access would
    # MissingGreenlet. Read the value before the apply.
    admin_email = current_admin.email

    from agentvault_registry.services.operator_rename_apply import apply_operator_rename_local
    # 1) Apply on THIS mainframe's own rows. dry_run rolls back after counting.
    local = await apply_operator_rename_local(
        db, old_slug=old_slug, new_slug=new_slug,
        new_base_url=(body.new_base_url or None),
        new_operator_did=(body.new_operator_did or None),
        dry_run=bool(body.dry_run),
        actor=f"reconcile:{admin_email}",
    )

    # 2) Live run → emit OperatorRenamed; reactor_operator_renamed fans the same
    #    convergence out to every ACTIVE peer frame (idempotent on each).
    fanout_emitted = False
    if not body.dry_run:
        try:
            await get_event_emitter().emit_event(
                aggregate_id=f"operator:{old_slug}",
                event_type="OperatorRenamed",
                event_data={
                    "old_slug": old_slug, "new_slug": new_slug,
                    "new_base_url": (body.new_base_url or ""),
                    "new_operator_did": (body.new_operator_did or ""),
                    "home_frame": os.getenv("SPIRE_TRUST_DOMAIN", ""),
                    "actor": f"reconcile:{admin_email}",
                },
            )
            fanout_emitted = True
        except Exception as e:  # noqa: BLE001 — best-effort; local apply already committed
            logger.error(
                f"[OP-RECONCILE] emit OperatorRenamed failed for {old_slug}->{new_slug}: {e}")

    logger.info(
        f"[CLOUD-ADMIN] reconcile-identity {old_slug} → {new_slug} dry_run={body.dry_run} "
        f"local={local} fanout_emitted={fanout_emitted} admin={admin_email}")
    return {
        "status": "previewed" if body.dry_run else "applied",
        "old_slug": old_slug, "new_slug": new_slug,
        "local_apply": local, "fanout_emitted": fanout_emitted,
    }


@router.post(
    "/{application_id}/rename",
    status_code=202,
    summary="Operator IDENTITY re-slug (rename Lane B) — async cascade, 202 + poll URL",
    include_in_schema=False,  # §2026-06-14 — hidden while rebuilt event-sourced (gated by OPERATOR_RENAME_ALLOW_MUTATING)
)
async def rename_cloud(
    application_id: str,
    body: schemas.CloudRenameRequest,
    background_tasks: BackgroundTasks,
    current_admin: models.Developer = Security(security.require_admin_flag("admin_federation")),
    db: AsyncSession = Depends(get_db),
):
    """Re-slug a cloud operator's load-bearing identity (= its SPIFFE ID), fleet-wide.

    DECOMMISSION-GRADE — this is NOT a display-name change. For a human-facing name,
    operators use the zero-downtime Lane A self-rename (POST /operator-portal/self-rename).
    Lane B is an 8-phase ordered cascade (quiesce → snapshot → stop → SPIRE re-issue →
    infra recreate → cross-frame DB re-identify → card re-stamp → verify). It runs as a
    BACKGROUND task; this returns 202 immediately with a poll URL.

    Safety (belt-and-suspenders, so an accidental call can never re-slug a live op):
      • dry_run=true (default): runs quiesce+snapshot+plan-gate, then STOPS before any
        mutation. ALWAYS run a dry_run first and review its snapshot.
      • A real run (dry_run=false) additionally requires BOTH (a) confirm == current slug
        and (b) env OPERATOR_RENAME_ALLOW_MUTATING=true (stays off until the qatest16
        dry-run+rollback is proven). If the env is unset, the cascade self-aborts at the
        plan gate — poll status to see it.

    Mainframe-only (enforced router-wide via require_mainframe_only).
    """
    app_record = (await db.execute(
        select(models.OperatorApplication).where(
            models.OperatorApplication.id == application_id)
    )).scalar_one_or_none()
    if not app_record:
        raise HTTPException(status_code=404, detail="Application not found")
    if not app_record.cloud_hosted or app_record.cloud_torn_down_at:
        raise HTTPException(status_code=400, detail="Not an active cloud operator")

    old_slug = _safe_name(app_record.name or "")
    new_slug = _safe_name(body.new_slug or "")
    if not new_slug or new_slug == old_slug:
        raise HTTPException(
            status_code=422,
            detail=f"new_slug must be a different valid slug (got {new_slug!r} vs {old_slug!r})")

    # Typed-confirm guard for a REAL run (dry_run mutates nothing → no confirm needed).
    if not body.dry_run and (body.confirm or "") != old_slug:
        raise HTTPException(
            status_code=422,
            detail=f"confirm must equal the current slug {old_slug!r} to execute a real rename")

    # Refuse a second concurrent rename of the same operator.
    existing = operator_renamer.get_rename_status(old_slug)
    if existing and existing.get("state") in operator_renamer.IN_FLIGHT_STATES:
        raise HTTPException(
            status_code=409,
            detail=f"rename already in progress for {old_slug} (state={existing.get('state')})")

    logger.info(f"[CLOUD-ADMIN] Rename requested: {old_slug} → {new_slug} "
                f"(dry_run={body.dry_run}, admin={current_admin.email})")

    # Seed status synchronously so an immediate poll has something to read (the bg
    # task runs after the 202 is sent).
    operator_renamer._set_status(old_slug, "pending", new_slug=new_slug,
                                 dry_run=body.dry_run, requested_by=current_admin.email)
    background_tasks.add_task(_run_rename_bg, application_id, body.new_slug, body.dry_run)

    return {
        "status": "accepted",
        "old_slug": old_slug,
        "new_slug": new_slug,
        "dry_run": body.dry_run,
        "poll": f"/api/v1/admin/cloud-operators/{application_id}/rename-status",
        "note": ("dry_run — quiesce+snapshot+plan only, no mutation" if body.dry_run
                 else "real run — also gated by OPERATOR_RENAME_ALLOW_MUTATING env; poll status"),
    }


@router.get(
    "/{application_id}/rename-status",
    summary="Poll the status of an operator rename (Lane B) cascade",
    include_in_schema=False,  # §2026-06-14 — hidden while rebuilt event-sourced
)
async def rename_status(
    application_id: str,
    current_admin: models.Developer = Security(security.require_admin_flag("admin_federation")),
    db: AsyncSession = Depends(get_db),
):
    """Return the in-progress / final status of a Lane-B rename for this operator."""
    app_record = (await db.execute(
        select(models.OperatorApplication).where(
            models.OperatorApplication.id == application_id)
    )).scalar_one_or_none()
    if not app_record:
        raise HTTPException(status_code=404, detail="Application not found")
    old_slug = _safe_name(app_record.name or "")
    st = operator_renamer.get_rename_status(old_slug)
    if not st:
        return {"old_slug": old_slug, "state": "none",
                "note": "no rename has been requested for this operator"}
    return st


async def _resolve_application_from_license(
    license_row: models.FederationLicense, db: AsyncSession
) -> Optional[models.OperatorApplication]:
    """§pass66.10 — Find the OperatorApplication that owns a FederationLicense.

    OperatorApplication has no direct operator_did column. The license's
    operator_did is derived from the application's `docker_registry_username`
    via `_cloud_operator_did` (see cloud_provisioner.py:100). To go the other
    way at the endpoint layer we iterate all cloud-hosted apps + derive each
    one's did until we find a match. ~10-20 apps in practice → O(1) hash
    lookup with a one-time list.
    """
    apps = (await db.execute(
        select(models.OperatorApplication).where(
            models.OperatorApplication.cloud_hosted == True,
            models.OperatorApplication.cloud_torn_down_at.is_(None),
        )
    )).scalars().all()
    for app in apps:
        safe = _safe_name(app.name or "")
        if _cloud_operator_did(app, safe) == license_row.operator_did:
            return app
    return None


# §pass66.6 (2026-05-23) — Restart action for cloud-hosted ops. Cloud-hosted
# ops can't run `tp-operator restart` (no shell access to Frame A's host),
# so this endpoint is the web-UI equivalent. Surface: a "Restart" button in
# OperatorManagement.vue (admin_federation flag-gated, mainframe-only via
# the router-level `require_mainframe_only` dependency).
class CloudRestartRequest(__import__("pydantic").BaseModel):
    service: str = "registry"  # see CLOUD_OP_RESTARTABLE_SERVICES for allowlist


@router.post(
    "/{application_id}/restart-service",
    summary="Restart one service (or all) in a cloud-hosted operator's stack",
)
async def restart_cloud(
    application_id: str,
    body: CloudRestartRequest = CloudRestartRequest(),
    current_admin: models.Developer = Security(security.require_admin_flag("admin_federation")),
    db: AsyncSession = Depends(get_db),
):
    """Bounce one service (or all) in a cloud-hosted op's compose stack.

    Service must be in `CLOUD_OP_RESTARTABLE_SERVICES` allowlist — protects
    against arbitrary shell-injection through the service param.

    Returns: { service, restarted, duration_ms, output_tail }
    """
    if body.service not in CLOUD_OP_RESTARTABLE_SERVICES:
        raise HTTPException(
            status_code=400,
            detail=f"service must be one of {sorted(CLOUD_OP_RESTARTABLE_SERVICES)}",
        )

    result = await db.execute(
        select(models.OperatorApplication).where(
            models.OperatorApplication.id == application_id
        )
    )
    app_record = result.scalar_one_or_none()
    if not app_record:
        raise HTTPException(status_code=404, detail="Application not found")
    if not app_record.cloud_hosted or app_record.cloud_torn_down_at:
        raise HTTPException(status_code=400, detail="Not an active cloud operator")

    logger.info(
        f"[CLOUD-ADMIN] Restart request: op={app_record.name} "
        f"service={body.service} by={current_admin.email}"
    )

    try:
        restart_result = await restart_cloud_service(app_record, body.service)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except RuntimeError as re:
        logger.error(f"[CLOUD-ADMIN] Restart failed: {re}")
        raise HTTPException(status_code=500, detail=f"Restart failed: {str(re)[:400]}")

    return {
        "status": "restarted",
        "operator_name": app_record.name,
        **restart_result,
    }


# §pass66.9 (2026-05-23) — Operator self-restart endpoint. Lets a cloud-op
# admin trigger a restart of THEIR OWN registry container without being a
# mainframe admin. Auth = federation license key (the same key the op
# already has from provisioning). License → operator_did → OperatorApplication
# lookup → restart only if the op's own license. No cross-op privilege.
#
# This is the federation-license counterpart of /restart-service (which is
# admin-JWT). Sibling endpoint, separate auth path, narrower scope (only
# touches the op tied to the license).
from agentvault_registry.core.federation_auth import _verify_license_key
from fastapi import Request as _Request


@router.post(
    "/self-restart",
    summary="A cloud operator's admin restarts its own services, authenticated by its federation licence",
)
async def cloud_operator_self_restart(
    request: _Request,
    body: CloudRestartRequest = CloudRestartRequest(),
    db: AsyncSession = Depends(get_db),
):
    """Restart one service in a cloud-op's stack, authenticating via the op's
    own federation license (no mainframe admin JWT required).

    Headers: `X-Federation-License: tp_fed_...` (the op's own license key)
    Body: `{"service": "registry"}` (defaults; allowlist enforced)

    Mainframe-only via router-level `require_mainframe_only` dep. Restart
    runs ON the mainframe (which has docker access to all cloud-op stacks).

    Use case: cloud-op's own admin clicks "Restart My Registry" in their
    OperatorPortal; their OWN registry backend proxies to this endpoint
    with the FEDERATION_LICENSE_KEY env from .env.operator as auth.
    """
    if body.service not in CLOUD_OP_RESTARTABLE_SERVICES:
        raise HTTPException(
            status_code=400,
            detail=f"service must be one of {sorted(CLOUD_OP_RESTARTABLE_SERVICES)}",
        )

    license_key = request.headers.get("X-Federation-License")
    if not license_key:
        raise HTTPException(
            status_code=401,
            detail="X-Federation-License header required",
        )

    # Verify license; returns synthetic identity or raises 403
    identity = await _verify_license_key(license_key, request)
    if not identity:
        raise HTTPException(status_code=403, detail="Invalid or revoked federation license")

    # Look up the operator_did from the license, then find the matching app.
    import hashlib as _h
    key_hash = _h.sha256(license_key.encode()).hexdigest()
    license_row = (await db.execute(
        select(models.FederationLicense).where(
            models.FederationLicense.license_key_hash == key_hash,
            models.FederationLicense.status == "active",
        )
    )).scalar_one_or_none()
    if not license_row or not license_row.operator_did:
        raise HTTPException(status_code=403, detail="License has no operator association")
    from .federation_licenses import assert_licensee_type
    assert_licensee_type(license_row, "operator")  # D6-111: an operator's own stack; a frame's admission key is refused

    # OperatorApplication has no operator_did column — license↔application
    # is derived via `_cloud_operator_did(app, safe_name)`. Reverse lookup
    # iterates cloud-hosted apps + matches. ~10-20 apps in practice.
    app_row = await _resolve_application_from_license(license_row, db)
    if not app_row:
        raise HTTPException(
            status_code=404,
            detail="No active cloud-hosted operator application matches this license's operator_did",
        )

    logger.info(
        f"[CLOUD-ADMIN] Self-restart request: op={app_row.name} "
        f"service={body.service} via license operator_did={license_row.operator_did}"
    )

    try:
        restart_result = await restart_cloud_service(app_row, body.service)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except RuntimeError as re:
        logger.error(f"[CLOUD-ADMIN] Self-restart failed: {re}")
        raise HTTPException(status_code=500, detail=f"Restart failed: {str(re)[:400]}")

    return {
        "status": "restarted",
        "operator_name": app_row.name,
        "auth_mode": "federation_license",
        **restart_result,
    }


@router.get(
    "/self-logs",
    summary="A cloud operator's admin reads its own logs, authenticated by its federation licence",
)
async def cloud_operator_self_logs(
    request: _Request,
    service: str = "registry",
    tail: int = 200,
    db: AsyncSession = Depends(get_db),
):
    """Fetch logs from one service in a cloud-op's stack, authenticating via
    the op's own federation license (no mainframe admin JWT required).

    Mirror of `/self-restart` for logs. Cloud-op admins call this through
    the operator-portal proxy (which adds the license header).
    """
    if service not in CLOUD_OP_RESTARTABLE_SERVICES:
        raise HTTPException(
            status_code=400,
            detail=f"service must be one of {sorted(CLOUD_OP_RESTARTABLE_SERVICES)}",
        )
    if not (10 <= tail <= 2000):
        raise HTTPException(status_code=400, detail="tail must be 10-2000")

    license_key = request.headers.get("X-Federation-License")
    if not license_key:
        raise HTTPException(status_code=401, detail="X-Federation-License header required")

    identity = await _verify_license_key(license_key, request)
    if not identity:
        raise HTTPException(status_code=403, detail="Invalid or revoked federation license")

    import hashlib as _h
    key_hash = _h.sha256(license_key.encode()).hexdigest()
    license_row = (await db.execute(
        select(models.FederationLicense).where(
            models.FederationLicense.license_key_hash == key_hash,
            models.FederationLicense.status == "active",
        )
    )).scalar_one_or_none()
    if not license_row or not license_row.operator_did:
        raise HTTPException(status_code=403, detail="License has no operator association")
    from .federation_licenses import assert_licensee_type
    assert_licensee_type(license_row, "operator")  # D6-111: an operator's own stack; a frame's admission key is refused

    app_row = await _resolve_application_from_license(license_row, db)
    if not app_row:
        raise HTTPException(
            status_code=404,
            detail="No active cloud-hosted operator application matches this license's operator_did",
        )

    logger.info(
        f"[CLOUD-ADMIN] Self-logs request: op={app_row.name} "
        f"service={service} tail={tail} via license operator_did={license_row.operator_did}"
    )

    try:
        logs_result = await fetch_cloud_logs(app_row, service, tail)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except RuntimeError as re:
        raise HTTPException(status_code=500, detail=f"Logs fetch failed: {str(re)[:400]}")

    return {
        "operator_name": app_row.name,
        "auth_mode": "federation_license",
        **logs_result,
    }


# §OPLANE (V0614): the same two handlers on the lane a cloud operator really has to its parent. The console paths above
# answer an operator nothing on a frame whose public vhost clears X-Federation-License (EU, ASIA, every template frame);
# the frame's nginx-federation forwards /api/v1/federation/ with the operator's certificate vouched, and the licence
# stays each handler's own check. Served only through that terminator (core/mtls_auth.require_vouched_peer_cert).
from agentvault_registry.core.mtls_auth import require_vouched_peer_cert  # noqa: E402

federation_router = APIRouter(
    prefix="/api/v1/federation/operator-self",
    tags=["Cloud Operators (Admin)"],
    dependencies=[Depends(require_mainframe_only), Depends(require_vouched_peer_cert)],
)
federation_router.add_api_route(
    "/restart", cloud_operator_self_restart, methods=["POST"],
    summary="A cloud operator restarts its own service through the federation lane (licence and vouched SVID)",
)
federation_router.add_api_route(
    "/logs", cloud_operator_self_logs, methods=["GET"],
    summary="A cloud operator reads its own logs through the federation lane (licence and vouched SVID)",
)


# §pass66.9 (2026-05-23) — Logs viewer. Same docker-py SDK + `docker:cli`
# sidecar pattern as restart-service. Returns the last N lines from one (or all)
# services in the op's compose stack. Tail param 10-2000 bounded.
@router.get(
    "/{application_id}/logs",
    summary="Tail logs from one service in a cloud-hosted operator's compose stack",
)
async def cloud_operator_logs(
    application_id: str,
    service: str = "registry",
    tail: int = 200,
    current_admin: models.Developer = Security(security.require_admin_flag("admin_federation")),
    db: AsyncSession = Depends(get_db),
):
    """Tail logs from one service (or all) of a cloud-op's compose stack.

    Service must be in `CLOUD_OP_RESTARTABLE_SERVICES` allowlist + `tail`
    bounded 10-2000. Returns text/plain output with the last N lines.
    """
    if service not in CLOUD_OP_RESTARTABLE_SERVICES:
        raise HTTPException(
            status_code=400,
            detail=f"service must be one of {sorted(CLOUD_OP_RESTARTABLE_SERVICES)}",
        )
    if not (10 <= tail <= 2000):
        raise HTTPException(status_code=400, detail="tail must be 10-2000")

    result = await db.execute(
        select(models.OperatorApplication).where(
            models.OperatorApplication.id == application_id
        )
    )
    app_record = result.scalar_one_or_none()
    if not app_record:
        raise HTTPException(status_code=404, detail="Application not found")
    if not app_record.cloud_hosted or app_record.cloud_torn_down_at:
        raise HTTPException(status_code=400, detail="Not an active cloud operator")

    logger.info(
        f"[CLOUD-ADMIN] Logs request: op={app_record.name} "
        f"service={service} tail={tail} by={current_admin.email}"
    )
    try:
        logs_result = await fetch_cloud_logs(app_record, service, tail)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except RuntimeError as re:
        raise HTTPException(status_code=500, detail=f"Logs fetch failed: {str(re)[:400]}")

    return {
        "operator_name": app_record.name,
        **logs_result,
    }


@router.get(
    "",
    summary="List all cloud-hosted operators",
)
async def list_cloud_operators(
    current_admin: models.Developer = Security(security.require_admin_flag("admin_federation")),
    db: AsyncSession = Depends(get_db),
):
    """List all cloud-hosted operators with their current status."""
    result = await db.execute(
        select(models.OperatorApplication).where(
            models.OperatorApplication.cloud_hosted == True
        ).order_by(models.OperatorApplication.cloud_provisioned_at.desc())
    )
    apps = result.scalars().all()

    operators = []
    for app in apps:
        active = app.cloud_torn_down_at is None

        # Quick health check for active operators
        # Docker DNS overrides public domains to internal IPs where port 443 doesn't exist.
        # Use the host public IP with Host header to route through host nginx correctly.
        healthy = None
        health_note = None
        if active and app.cloud_url:
            # §BATCH3 item 1: the public host IP is this deployment's fact (CLOUD_OP_HEALTH_HOST_IP,
            # registry-a's compose carries it); unset => healthy stays None (unknown), never a guess. ⚠ Measured
            # 2026-09-18 (§HELLOFRAME lane 6): the unset case RAISED into the except below and read False, so
            # every operator of a frame without the variable was listed as unhealthy. Unknown is now said as such.
            host_ip = os.getenv("CLOUD_OP_HEALTH_HOST_IP", "").strip()
            if not host_ip:
                health_note = "not measurable here: CLOUD_OP_HEALTH_HOST_IP is unset on this frame"
            else:
                try:
                    import httpx
                    from urllib.parse import urlparse
                    parsed = urlparse(app.cloud_url)
                    r = httpx.get(f"https://{host_ip}/health",
                        headers={"Host": parsed.hostname},
                        timeout=3, verify=False)
                    healthy = r.status_code == 200
                except Exception as exc:  # noqa: BLE001 — the probe's failure is the answer, named
                    healthy = False
                    health_note = f"probe failed: {type(exc).__name__}"

        operators.append({
            "application_id": app.id,
            "name": app.name,
            "cloud_url": app.cloud_url,
            "cloud_port_base": app.cloud_port_base,
            "cloud_provisioned_at": app.cloud_provisioned_at.isoformat() if app.cloud_provisioned_at else None,
            "cloud_torn_down_at": app.cloud_torn_down_at.isoformat() if app.cloud_torn_down_at else None,
            "active": active,
            "healthy": healthy,
            "health_note": health_note,
            "email": app.email,
        })

    active_count = sum(1 for o in operators if o["active"])
    return {
        "operators": operators,
        "active_count": active_count,
        "beta_limit": BETA_LIMIT,
        "slots_available": BETA_LIMIT - active_count,
    }


_HEALTH_SERVICES = ("registry", "teg", "db", "teg-db", "redis", "pgbouncer", "nginx-federation", "spire-agent",
                    "cert-writer")


async def _operator_container_statuses(safe: str) -> dict:
    """{service: docker ps Status | "not found" | "check failed"} for the operator's containers, or {"note": why} when
    this registry cannot measure them. §F6 WP6.2 slice 2: CONTAINER_OBSERVE_VIA=runner asks the frame runner's
    containers_census for the operator (bound by the runner to THIS frame's operators); unset keeps the socket's
    `docker ps` read below as it was."""
    from agentvault_registry.services import host_observe as _ho
    try:
        _via = _ho.observe_via()
    except _ho.ObserveUnavailable as exc:
        return {"note": f"not measurable here: {exc}"}
    if _via == "runner":
        try:
            _census = await asyncio.to_thread(_ho.census, safe)
        except _ho.ObserveUnavailable as exc:
            return {"note": f"not measurable here: {exc}"}
        by_name = {r.get("name"): r.get("status") for r in (_census.get("containers") or [])}
        return {svc: (by_name.get(f"cloud-op-{safe}-{svc}") or "not found") for svc in _HEALTH_SERVICES}
    # Check container statuses — only where this registry can ask the host Docker API. A runner-built frame has no
    # socket (§OPDIST), so `docker ps` there is a failing command dressed as a status; the runner's operator_status
    # carries the container states for such a frame. A sandbox holds the socket for its tester and may READ it, which is
    # all a census needs: the question is docker_daemon_available(), never docker_socket_available(), which asks for
    # HOST WORK and since §TESTBED also wants /host-stack (§HELLOFRAME lane 6, 2026-09-18/19)
    from agentvault_registry.core.host_reach import docker_daemon_available
    _sock_ok, _sock_why = docker_daemon_available()
    containers = {} if _sock_ok else {"note": f"not measurable here: {_sock_why}"}
    for svc in ([] if not _sock_ok else list(_HEALTH_SERVICES)):
        try:
            r = subprocess.run(
                f"docker ps --format '{{{{.Status}}}}' --filter 'name=cloud-op-{safe}-{svc}$'",
                shell=True, capture_output=True, text=True, timeout=5,
            )
            status_str = r.stdout.strip()
            containers[svc] = status_str if status_str else "not found"
        except Exception:
            containers[svc] = "check failed"
    return containers


@router.get(
    "/{application_id}/health",
    summary="Detailed health check for a cloud operator",
)
async def cloud_operator_health(
    application_id: str,
    current_admin: models.Developer = Security(security.require_admin_flag("admin_federation")),
    db: AsyncSession = Depends(get_db),
):
    """Detailed health check: container statuses, registry response, federation nginx."""
    result = await db.execute(
        select(models.OperatorApplication).where(
            models.OperatorApplication.id == application_id
        )
    )
    app_record = result.scalar_one_or_none()
    if not app_record:
        raise HTTPException(status_code=404, detail="Application not found")

    if not app_record.cloud_hosted or app_record.cloud_torn_down_at:
        raise HTTPException(status_code=400, detail="Not an active cloud operator")

    import re
    safe = re.sub(r'[^a-z0-9-]', '', (app_record.name or "").lower())[:40]

    # Check container statuses — only where this registry can ask the host Docker API. A runner-built frame has no
    # socket (§OPDIST), so `docker ps` there is a failing command dressed as a status; the runner's operator_status
    # carries the container states for such a frame. A sandbox holds the socket for its tester and may READ it, which is
    # all a census needs: the question is docker_daemon_available(), never docker_socket_available(), which asks for
    # HOST WORK and since §TESTBED also wants /host-stack (§HELLOFRAME lane 6, 2026-09-18/19)
    containers = await _operator_container_statuses(safe)

    # Check registry HTTP health at the docker bridge gateway, where the operator's registry port is published on this
    # host (every interface on the network's own frames; the gateway itself under a Caddy edge), the hop the operator
    # portal takes too. ⚠ Never 127.0.0.1: every frame registry runs on a bridge network, so its loopback is its own
    # container. Measured 2026-09-19 from eu-registry to amsterdam's port: loopback 000, gateway 200; the loopback probe
    # this route carried until then never reported an operator's health on any frame (§HELLOFRAME lane 6).
    registry_health = None
    _probe_host = os.getenv("DOCKER_BRIDGE_GATEWAY", "172.17.0.1")
    if app_record.cloud_port_base:
        try:
            r = subprocess.run(
                f"curl -sf --max-time 3 http://{_probe_host}:{app_record.cloud_port_base}/health",
                shell=True, capture_output=True, text=True, timeout=5,
            )
            registry_health = r.stdout[:500] if r.returncode == 0 else f"HTTP error"
        except Exception as e:
            registry_health = f"unreachable: {e}"

    return {
        "application_id": application_id,
        "name": app_record.name,
        "cloud_url": app_record.cloud_url,
        "containers": containers,
        "registry_health": registry_health,
        "cloud_provisioned_at": app_record.cloud_provisioned_at.isoformat() if app_record.cloud_provisioned_at else None,
    }
