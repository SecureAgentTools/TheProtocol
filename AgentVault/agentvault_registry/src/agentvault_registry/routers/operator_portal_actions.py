"""§pass66.9 (2026-05-23) — Operator portal action endpoints.

Cloud-op-side proxies that let a cloud-op admin trigger operations on their
OWN cloud-op stack without needing mainframe admin credentials. Each proxy
authenticates the caller as the cloud-op's own admin, then makes an HTTPS
call to the mainframe with the cloud-op's own `FEDERATION_LICENSE_KEY` env.

The mainframe-side endpoint (`/api/v1/admin/cloud-operators/self-restart`)
validates the license, derives the operator_did, finds the corresponding
OperatorApplication, and executes the restart. No cross-op privilege —
each license can only restart its own op.

Endpoints:
  POST /api/v1/operator-portal/self-restart  — restart own stack via license proxy

Runs on cloud-ops (NOT mainframes). On a mainframe this answers 404 with the code word `operator_only:` first (D6-820).
"""
import logging
import os
import socket
import time
from typing import Optional
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Security
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry import models, security
from agentvault_registry.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/operator-portal", tags=["Operator Portal Actions"])


class SelfRestartRequest(BaseModel):
    service: str = "registry"


class SelfRenameRequest(BaseModel):
    # §2026-06-14 — operator self-service DISPLAY rename (rename Lane A). Changes
    # ONLY the human-facing card display_name; the load-bearing identity (slug /
    # SPIFFE ID / peer-routing name) is immutable and untouched, so this is
    # zero-downtime + nothing-breaks. A true identity re-slug is the separate
    # admin-only Lane B (POST /admin/cloud-operators/{id}/rename).
    display_name: str = Field(..., min_length=1, max_length=120)


_RESOLVE_TTL_SECONDS = 300.0
_resolve_cache: dict = {}


def _host_resolves(url: str) -> bool:
    """True if this URL's hostname resolves FROM THIS CONTAINER.

    Cached for _RESOLVE_TTL_SECONDS so a repeated miss does not re-pay the
    resolver timeout on every self-service call.
    """
    host = urlparse(url).hostname
    if not host:
        return False
    now = time.monotonic()
    hit = _resolve_cache.get(host)
    if hit is not None and now - hit[0] < _RESOLVE_TTL_SECONDS:
        return hit[1]
    try:
        socket.getaddrinfo(host, None)
        ok = True
    except socket.gaierror:
        ok = False
    _resolve_cache[host] = (now, ok)
    return ok


def _resolve_mainframe_url() -> str:
    """Where this cloud-op reaches its parent frame.

    Only ever runs on a cloud-op — every caller gates on is_mainframe() first.

    The provisioner writes CENTRAL_REGISTRY_URL as an INTERNAL docker name
    (`cloud_provisioner.py` -> CENTRAL_REGISTRY_URL_FOR_OPERATORS, default
    `http://agentvault_registry_a:8000`), which resolves only when the operator
    shares a docker network with its frame. When it does not, every operator
    self-service action died with `502 Mainframe call failed: [Errno -3]
    Temporary failure in name resolution` — measured on both sandbox operators
    2026-09-05, where the provisioner had written `http://sbx-alpha-registry:8000`.

    This was previously rescued by a literal test for `agentvault_registry_a`,
    which is blind to every OTHER frame's internal name. The rule is now the
    property that literal was really testing: if the configured host does not
    resolve, fall back to the public URL. `MAINFRAME_PUBLIC_URL` names that
    fallback per node (default unchanged) so a non-production frame's operator
    falls back to ITS OWN frame rather than the production apex.
    """
    configured = (
        os.environ.get("CENTRAL_REGISTRY_URL", "").strip()
        or os.environ.get("MAINFRAME_PROXY_URL", "").strip()
    ).rstrip("/")
    public = (
        os.environ.get("MAINFRAME_PUBLIC_URL", "").strip()
        or "https://api.theprotocol.cloud"
    ).rstrip("/")
    if not configured:
        return public
    if _host_resolves(configured):
        return configured
    logger.warning(
        "[OperatorPortal] configured mainframe %s does not resolve from this "
        "container; falling back to %s", configured, public,
    )
    return public


async def _call_parent(db: AsyncSession, method: str, console_path: str, lane_path: str, license_key: str, *,
                       json_body: Optional[dict] = None, params: Optional[dict] = None, timeout: float = 90.0):
    """§OPLANE (V0614): one licence-carrying call to the parent frame. The parent's federation lane first (its mTLS address
    from the peer table, this node's SVID, the /api/v1/federation/ alias); the console path when the lane is unknown here,
    the lane cannot be dialled, or the parent predates the alias. The console path is what EU's and ASIA's public vhosts
    answer 401 "X-Federation-License header required" on (they clear the header), so on production the lane is the path.
    A lane that was reached is never retried on the console: a restart is not sent twice. Returns (response, lane name)."""
    from agentvault_registry.core import parent_lane
    headers = {"X-Federation-License": license_key}
    origin = await parent_lane.resolve_origin(db)
    verify = parent_lane.client_verify(origin) if origin else None
    if origin and verify is not None:
        try:
            async with httpx.AsyncClient(timeout=timeout, verify=verify) as client:
                r = await client.request(method, origin + lane_path, json=json_body, params=params, headers=headers)
            if not parent_lane.route_missing(r.status_code, r.text):
                return r, "federation lane"
            logger.info("[OperatorPortal] the parent serves no %s yet (an older image): the console path", lane_path)
        except httpx.ConnectError as e:
            logger.warning("[OperatorPortal] the parent's federation lane cannot be dialled (%s): the console path",
                           type(e).__name__)
    # §MCPTEST30 (V0549): the console path carries this operator's federation licence, so the parent's certificate is
    # verified (the system CA store): every operator names its parent by a public theprotocol.cloud name that verifies.
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.request(method, _resolve_mainframe_url() + console_path, json=json_body, params=params,
                                 headers=headers)
    return r, "console"


def _parent_answer(r, lane: str):
    """The parent's answer, its error surfaced verbatim (licence invalid? service down?) and the lane named."""
    try:
        body = r.json()
    except Exception:
        body = {"raw": r.text[:500]}
    if not isinstance(body, dict):
        body = {"raw": str(body)[:500]}
    if r.status_code >= 400:
        detail = ((body.get("error") or {}).get("detail") if isinstance(body.get("error"), dict) else None) \
            or body.get("detail") or str(body)[:300]
        raise HTTPException(status_code=r.status_code, detail=f"Mainframe: {detail}")
    if isinstance(body, dict):
        body.setdefault("lane", lane)
    return body


@router.post(
    "/self-restart",
    summary="A cloud operator's admin restarts its own services through its frame, with its licence",
)
async def operator_self_restart(
    body: SelfRestartRequest = SelfRestartRequest(),
    current_admin: models.Developer = Security(security.require_admin_flag("admin_federation")),
    db: AsyncSession = Depends(get_db),
):
    """Cloud-op admin restarts their OWN registry via mainframe proxy.

    Auth: admin developer JWT (the cloud-op's own admin user, with
    `admin_federation` flag).

    Flow:
      1. Caller authenticated as op admin via JWT.
      2. Read FEDERATION_LICENSE_KEY from this cloud-op's env.
      3. Read CENTRAL_REGISTRY_URL / MAINFRAME_PROXY_URL to find the mainframe.
      4. POST to mainframe's /admin/cloud-operators/self-restart with the
         license as X-Federation-License header.
      5. Return mainframe's response.

    Answers 404 `operator_only:` if running on a mainframe (mainframe admins use the
    `/admin/cloud-operators/{id}/restart-service` endpoint directly).
    """
    # Gate: ONLY cloud-ops have a FEDERATION_LICENSE_KEY env. Mainframes
    # don't — they ARE the central. is_mainframe() check would be redundant
    # but explicit prevents this endpoint from being misused on mainframes.
    from agentvault_registry.core.mainframe_gate import is_mainframe, operator_only_refusal
    if is_mainframe():
        raise operator_only_refusal(
            "Operator self-restart is for cloud-ops only. Mainframe admins use /admin/cloud-operators/{id}/restart-service.")

    license_key = os.environ.get("FEDERATION_LICENSE_KEY", "").strip()
    if not license_key:
        raise HTTPException(
            status_code=503,
            detail="No FEDERATION_LICENSE_KEY in this registry's env (cloud-op provisioning didn't seed one?)",
        )

    logger.info(f"[OperatorPortal] self-restart {current_admin.email} service={body.service}")
    try:
        r, lane = await _call_parent(db, "POST", "/api/v1/admin/cloud-operators/self-restart",
                                     "/api/v1/federation/operator-self/restart", license_key,
                                     json_body={"service": body.service})
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Mainframe call failed: {str(e)[:300]}")
    return _parent_answer(r, lane)


@router.post(
    "/self-rename",
    summary="A cloud operator's admin sets this registry's display name",
)
async def operator_self_rename(
    body: SelfRenameRequest,
    current_admin: models.Developer = Security(security.require_admin_flag("admin_federation")),
    db: AsyncSession = Depends(get_db),
):
    """A cloud-op admin renames their OWN registry's human-facing DISPLAY name —
    no Frame-A admin, no host shell, no downtime.

    This is rename **Lane A** (see PRODUCTION_DOCS/06_OPERATIONS/Operator_Rename.md).
    It writes ONLY `operator.display_name` into the op's own registry card singleton
    (the same operator-editable block as `PUT /admin/registry-card`). The card's
    LOCKED identity (`identity.spiffe_id` / `registry_name` / `public_url`) and the
    load-bearing routing key (`peer_registries.name`) are UNCHANGED — so federation
    mTLS, ES emission auth, FX/cross-registry routing and canary dispatch keep working
    untouched. `display_name` is NOT one of the 13 signed canonical paths
    (`registry_card_signer.SIGNED_CANONICAL_PATHS`), so the signature does not change.

    A true IDENTITY re-slug (changing the SPIFFE ID itself) is the separate,
    admin-orchestrated Lane B — never this endpoint.
    """
    from sqlalchemy import select
    # Cloud-op only — a mainframe edits its display name via /admin/registry-card.
    from agentvault_registry.core.mainframe_gate import is_mainframe, operator_only_refusal
    if is_mainframe():
        raise operator_only_refusal(
            "self-rename is for cloud-ops only. Mainframe admins use PUT /api/v1/admin/registry-card.")

    new_name = body.display_name.strip()
    if not new_name:
        raise HTTPException(status_code=422, detail="display_name must be non-empty")

    row = (await db.execute(
        select(models.RegistryCard).where(models.RegistryCard.id == 1)
    )).scalar_one_or_none()
    existing = dict(row.card_json) if row and isinstance(row.card_json, dict) else {}
    # Deep-merge into the operator block (same pattern as admin_registry_card PUT).
    _op_block = dict(existing.get("operator") or {})
    prior = _op_block.get("display_name")
    _op_block["display_name"] = new_name
    existing["operator"] = _op_block
    if row is None:
        row = models.RegistryCard(id=1, card_json=existing, card_etag="", updated_by=current_admin.id)
        db.add(row)
    else:
        row.card_json = existing
        row.updated_by = current_admin.id
    # Flush so build_registry_card (same session) sees the new card_json, then
    # persist the authoritative serve etag (mirrors admin_registry_card PUT).
    await db.flush()
    full_card = None
    try:
        from agentvault_registry.services.registry_card_builder import build_registry_card
        full_card = await build_registry_card(db, sign=True, include_internal=True)
        row.card_etag = full_card.get("lifecycle", {}).get("card_etag", "") or row.card_etag
    except Exception as e:
        logger.warning("[OperatorPortal] self-rename card rebuild failed (non-fatal): %s", e)
    await db.commit()

    try:
        from agentvault_registry.event_emitter import get_event_emitter
        _spiffe = (full_card or {}).get("identity", {}).get("spiffe_id", "registry-card-1")
        await get_event_emitter().emit_event(
            aggregate_id=_spiffe,
            event_type="RegistryCardUpdated",
            event_data={"spiffe_id": _spiffe, "change": "display_name",
                        "prior": prior, "new": new_name, "lane": "A-self-rename",
                        "updated_by": current_admin.id},
        )
    except Exception as e:
        logger.warning("[OperatorPortal] self-rename emit failed (non-fatal): %s", e)
    logger.info(f"[OperatorPortal] self-rename {current_admin.email}: display_name {prior!r} → {new_name!r}")
    return {
        "status": "renamed",
        "display_name": new_name,
        "prior_display_name": prior,
        "note": "display name only — identity/SPIFFE/routing unchanged (Lane A)",
    }


# §pass66.10 (2026-05-23) — Cloud-op admin self-logs.
# Operators want to read their own logs without Commander providing dozzle
# access. This proxy mirrors self-restart: cloud-op admin → cloud-op backend
# (admin JWT) → mainframe (federation license) → mainframe runs
# `docker compose logs` and returns text.
@router.get(
    "/self-logs",
    summary="A cloud operator's admin reads its own logs through its frame, with its licence",
)
async def operator_self_logs(
    service: str = "registry",
    tail: int = 200,
    current_admin: models.Developer = Security(security.require_admin_flag("admin_federation")),
    db: AsyncSession = Depends(get_db),
):
    """Cloud-op admin reads logs from their OWN stack via mainframe proxy.

    Auth: admin developer JWT (the cloud-op's own admin user).
    Forwards to mainframe with FEDERATION_LICENSE_KEY env as auth.
    """
    from agentvault_registry.core.mainframe_gate import is_mainframe, operator_only_refusal
    if is_mainframe():
        raise operator_only_refusal(
            "Operator self-logs is for cloud-ops only. Mainframe admins use /admin/cloud-operators/{id}/logs.")

    license_key = os.environ.get("FEDERATION_LICENSE_KEY", "").strip()
    if not license_key:
        raise HTTPException(
            status_code=503,
            detail="No FEDERATION_LICENSE_KEY in this registry's env",
        )

    logger.info(f"[OperatorPortal] self-logs {current_admin.email} service={service} tail={tail}")
    try:
        r, lane = await _call_parent(db, "GET", "/api/v1/admin/cloud-operators/self-logs",
                                     "/api/v1/federation/operator-self/logs", license_key,
                                     params={"service": service, "tail": tail}, timeout=30.0)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Mainframe call failed: {str(e)[:300]}")
    return _parent_answer(r, lane)
