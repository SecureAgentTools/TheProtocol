"""Federation License Enforcement Gate (Option D-light Phase D6 — 2026-04-21).

Single source of truth for license-status enforcement at cross-operator
interaction paths. Call sites in this module (not duplicated logic elsewhere):

  routers/a2a_payment.py           — cross-registry A2A settlement
  routers/teg_integration.py       — POST /teg/cross-registry-transfer
  routers/teg_integration.py       — POST /teg/treasury/cross-teg-fund (the routed fiat purchase settles through it)
  routers/federation_disputes.py   — POST /federation/disputes/slash-request
  routers/federation_disputes.py   — POST /federation/disputes/slash-confirmation
  background_tasks/federation_sync.py — hourly card pull (uses silent variant)

All blocks emit `CrossRegistryBlockedBySuspension` to EventStore for audit.
Idempotency key dedupes per (operator_did, context, hour) so a retry loop
doesn't flood the ledger while still preserving the signal.

The quarantine half (D6-801, below) is asked by the money paths in
routers/teg_integration.py: the cross-registry transfer (which A2A settlement and
/teg/send reach), the FX booth, every FX route leg and the FX route hop; and (wave 6)
by the fiat routed checkout (routers/fiat_onramp.py) and the two federation slash
routes (routers/federation_disputes.py), each beside its licence check; and by the
inbound async cross-frame credit (background_tasks/reactor_cross_frame_initiated.py),
which names only its sender's trust domain (quarantined_trust_domain), and by the
cross-TEG treasury fund (routers/teg_integration.cross_teg_treasury_fund), beside its
licence check.
"""
import logging
from datetime import datetime, timezone
from typing import Iterable, Optional, Tuple

from fastapi import HTTPException, status
from sqlalchemy import func, select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry import models
from agentvault_registry.event_emitter import get_event_emitter

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

async def get_peer_license(
    db: AsyncSession, operator_did: str
) -> Optional[models.FederationLicense]:
    """Return the FederationLicense row for operator_did, or None if missing.

    Does NOT consider status — callers decide what to do with revoked/suspended.
    """
    if not operator_did:
        return None
    result = await db.execute(
        select(models.FederationLicense).where(
            models.FederationLicense.operator_did == operator_did
        )
    )
    return result.scalar_one_or_none()


async def is_peer_license_active(db: AsyncSession, operator_did: str) -> bool:
    """Silent check used by background tasks where SKIPPING is correct behavior.

    Returns False for: missing license, suspended, revoked.
    Returns True only for explicit `status == "active"`.
    """
    lic = await get_peer_license(db, operator_did)
    return bool(lic and lic.status == "active")


async def assert_peer_license_active(
    db: AsyncSession,
    operator_did: str,
    *,
    context: str,
    actor_agent_did: Optional[str] = None,
    actor_registry_did: Optional[str] = None,
) -> models.FederationLicense:
    """Raise HTTPException(403) if the peer's license isn't active.

    On block, emits `CrossRegistryBlockedBySuspension` to EventStore with
    hourly dedupe. `context` disambiguates the attempted action:
      cross_registry_transfer | a2a_payment_settle | federation_sync |
      slash_request | slash_confirmation_origin | slash_confirmation_defendant

    Returns the FederationLicense row on success (caller may use its fields).
    """
    lic = await get_peer_license(db, operator_did)

    if lic is not None and lic.status == "active":
        return lic

    # Build the blocking error
    if lic is None:
        reason = "peer_license_missing"
        license_id = None
        license_status = None
        detail_msg = f"No federation license for operator {operator_did}"
    elif lic.status == "suspended":
        reason = "peer_license_suspended"
        license_id = lic.id
        license_status = lic.status
        detail_msg = f"Peer operator license is suspended: {operator_did}"
    elif lic.status == "revoked":
        reason = "peer_license_revoked"
        license_id = lic.id
        license_status = lic.status
        detail_msg = f"Peer operator license is revoked: {operator_did}"
    else:
        reason = f"peer_license_status_{lic.status}"
        license_id = lic.id
        license_status = lic.status
        detail_msg = f"Peer operator license is not active (status={lic.status}): {operator_did}"

    # Emit audit event (best-effort — never let an emission failure swallow the block)
    try:
        now = datetime.now(timezone.utc)
        hour_bucket = now.strftime("%Y-%m-%d-%H")
        emitter = get_event_emitter()
        await emitter.emit(
            event_type="CrossRegistryBlockedBySuspension",
            aggregate_id=(
                f"federation_license:{license_id}" if license_id
                else f"operator_did:{operator_did}"
            ),
            aggregate_type="FederationLicense",
            data={
                "operator_did": operator_did,
                "license_id": license_id,
                "license_status": license_status,
                "reason": reason,
                "context": context,
                "actor_agent_did": actor_agent_did,
                "actor_registry_did": actor_registry_did,
                "attempted_at": now.isoformat(),
            },
            idempotency_key=f"blocked-{context}-{operator_did}-{hour_bucket}",
        )
    except Exception as exc:
        logger.error(
            f"[LicenseGate] Failed to emit CrossRegistryBlockedBySuspension "
            f"for {operator_did} (context={context}): {exc}"
        )

    # 2026-05-01 fix — honor FEDERATION_ENFORCEMENT_ACTIVE. When off, the
    # gate is audit-only: the event still fires (preserves the signal so the
    # incident is visible in the ledger) but the request is allowed through.
    # Mirrors the kill-switch semantics already used by the compliance poller.
    from agentvault_registry.config import settings as _settings
    _enforcement_active = bool(getattr(_settings, "FEDERATION_ENFORCEMENT_ACTIVE", False))

    if not _enforcement_active:
        logger.info(
            f"[LicenseGate] WOULD-BLOCK {context} for {operator_did} — {reason} "
            f"(enforcement_active=false, audit-only; actor_agent={actor_agent_did})"
        )
        return lic  # may be None or a non-active row; caller doesn't use return value

    logger.warning(
        f"[LicenseGate] BLOCKED {context} for {operator_did} — {reason} "
        f"(actor_agent={actor_agent_did}, actor_registry={actor_registry_did})"
    )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "message": detail_msg,
            "reason": reason,
            "operator_did": operator_did,
            "license_id": license_id,
            "license_status": license_status,
            "context": context,
        },
    )


# ---------------------------------------------------------------------------
# Operator-DID resolution from PeerRegistry / Agent
# ---------------------------------------------------------------------------

async def resolve_peer_operator_did(
    db: AsyncSession, peer_registry: models.PeerRegistry
) -> Optional[str]:
    """Derive the operator_did for a PeerRegistry row.

    Tries two paths:
      1. Match by peer_registry.name against OperatorApplication.name (most
         cloud/VPS operators follow this convention — the provisioner sets
         peer.name == application.name).
      2. Fall back to looking up any FederationLicense whose operator_name
         equals the peer's name — covers rows where the application row is
         missing (legacy imports) but the license still exists.
    """
    if peer_registry is None:
        return None

    # Path 1: via OperatorApplication
    app_result = await db.execute(
        select(models.OperatorApplication).where(
            models.OperatorApplication.name == peer_registry.name
        )
    )
    app = app_result.scalar_one_or_none()
    if app is not None:
        docker_username = app.docker_registry_username
        operator_name = (
            docker_username.removeprefix("operator-") if docker_username
            else "".join(
                c if c.isalnum() or c == "-" else "-"
                for c in (app.name or "").lower().strip()
            ).strip("-")[:40]
        )
        prefix = "cloud" if getattr(app, "cloud_hosted", False) else "operator"
        return f"did:theprotocol:{prefix}:{operator_name}"

    # Path 2: via FederationLicense.operator_name
    lic_result = await db.execute(
        select(models.FederationLicense).where(
            models.FederationLicense.operator_name == peer_registry.name
        )
    )
    lic = lic_result.scalar_one_or_none()
    if lic is not None:
        return lic.operator_did

    return None


async def resolve_operator_did_for_peer_id(
    db: AsyncSession, peer_registry_id: int
) -> Optional[str]:
    """Convenience wrapper: peer_id → operator_did (via PeerRegistry row)."""
    peer_result = await db.execute(
        select(models.PeerRegistry).where(models.PeerRegistry.id == peer_registry_id)
    )
    peer = peer_result.scalar_one_or_none()
    if peer is None:
        return None
    return await resolve_peer_operator_did(db, peer)


# ---------------------------------------------------------------------------
# Quarantine (D6-801, 2026-10-17)
# ---------------------------------------------------------------------------
#
# A peer this registry holds in quarantine (federated_registry_compliance.federation_status, written only by the
# compliance monitor: an administrator, the compliance poller in enforcing mode, or peer trust under enforce) takes part
# in no movement of money with this registry while the quarantine stands: no transfer or settlement to it, no FX route
# leg to or through it. The money paths ask before anything moves, which also keeps them from naming the peer's TEG to
# this frame's TEG again (every leg does, and the TEG re-adds the partner the RegistryQuarantined reactor removed).
# Unlike the licence check above this is not behind FEDERATION_ENFORCEMENT_ACTIVE: the quarantine is the enforcement
# decision, and its writers carry their own switches.

QUARANTINE_STATES = ("quarantined", "soft_quarantined", "blacklisted")


def _registry_key(name: Optional[str]) -> str:
    """The money paths' registry rule (routers/teg_integration.py Step 1b): the name's slug, "registry-" dropped, so a
    peer's display name and the `registry-<slug>` id a transfer carries meet."""
    from agentvault_registry.core.registry_slug import registry_slug
    return registry_slug(name or "").lower().replace("registry-", "")


async def _quarantined_rows(db: AsyncSession) -> list:
    return list((await db.execute(
        select(models.PeerRegistry.name, models.PeerRegistry.trust_domain, models.PeerRegistry.peer_type,
               models.FederatedRegistryCompliance.federation_status)
        .join(models.FederatedRegistryCompliance,
              models.FederatedRegistryCompliance.peer_registry_id == models.PeerRegistry.id)
        .where(func.lower(models.FederatedRegistryCompliance.federation_status).in_(QUARANTINE_STATES))
    )).all())


async def quarantined_registry(db: AsyncSession, registry_id: Optional[str]) -> Optional[Tuple[str, str]]:
    """(peer name, state) when this registry holds the registry `registry_id` (a peer's name, or the `registry-<slug>`
    id the money paths carry) in quarantine or blacklisted, else None. Read whatever the peer row's own status is, so a
    blacklisted peer (its row REJECTED) is named too. Raises when the database cannot be read."""
    want = _registry_key(registry_id)
    if not want:
        return None
    for name, _td, _kind, state in await _quarantined_rows(db):
        if _registry_key(name) == want:
            return name, str(state).lower()
    return None


async def quarantined_presenter(db: AsyncSession, spiffe_id: Optional[str]) -> Optional[Tuple[str, str]]:
    """The same for the registry presenting `spiffe_id` to a federation route, resolved the way the peer binding
    resolves it (core/federation_auth._s3_canonical): an operator's identity to the row of that name in its trust
    domain, a frame registry's to its trust domain's frame row. Raises when the database cannot be read."""
    from agentvault_registry.core.federation_auth import _norm_slug, _s3_canonical
    canon = _s3_canonical(spiffe_id or "")
    if canon is None:
        return None
    td, kind, name = canon
    for row_name, row_td, row_kind, state in await _quarantined_rows(db):
        if (row_td or "").strip().lower() != td:
            continue
        if (kind == "frame" and row_kind == "frame") or (kind != "frame" and _norm_slug(row_name or "") == name):
            return row_name, str(state).lower()
    return None


async def quarantined_trust_domain(db: AsyncSession, trust_domain: Optional[str]) -> Optional[Tuple[str, str]]:
    """The same for a message that names only its sender's trust domain (an inbound async cross-frame credit): (peer
    name, state) of a registry in that trust domain this registry holds in quarantine, soft quarantine or blacklisted,
    else None. A frame shares its trust domain with its cloud operators and the message cannot say which of them sent
    it, so any one of them in quarantine stops the domain's credits while that stands. Raises when the database cannot
    be read."""
    td = (trust_domain or "").strip().lower()
    if td.startswith("spiffe://"):
        td = td[len("spiffe://"):].split("/", 1)[0]
    if not td:
        return None
    for name, row_td, _kind, state in await _quarantined_rows(db):
        if (row_td or "").strip().lower() == td:
            return name, str(state).lower()
    return None


def _url_key(url: Optional[str]) -> str:
    return (url or "").strip().rstrip("/").lower()


async def assert_federation_peer_not_quarantined(
    db: AsyncSession,
    *,
    presenter: Optional[str],
    peer_urls: Iterable[Optional[str]] = (),
    context: str,
) -> None:
    """The quarantine check of the federation slash routes (D6-801, wave 6): 403 when this registry holds in quarantine,
    soft quarantine or blacklisted the registry presenting the request (`presenter`, its SPIFFE id, resolved as
    quarantined_presenter resolves it) or a registry the request is about, named by its base URL (`peer_urls`, matched
    against peer rows of any status, so a blacklisted peer, whose row is REJECTED, is named too). Both: the slash routes bind the addresses they
    name to the caller (routers/federation_disputes), but this frame's own registry may still name another peer, and a
    settlement's addresses are this registry's records. When the compliance state
    cannot be read the answer is 503 and nothing has moved: the caller asks before anything is recorded or moves."""
    from agentvault_registry.services.payout_outcome import NO_FUNDS_MOVED
    urls = {_url_key(u) for u in peer_urls if _url_key(u)}
    try:
        hit = await quarantined_presenter(db, presenter) if presenter else None
        if hit is None and urls:
            rows = (await db.execute(
                select(models.PeerRegistry.name, models.PeerRegistry.base_url,
                       models.FederatedRegistryCompliance.federation_status)
                .join(models.FederatedRegistryCompliance,
                      models.FederatedRegistryCompliance.peer_registry_id == models.PeerRegistry.id)
                .where(func.lower(models.FederatedRegistryCompliance.federation_status).in_(QUARANTINE_STATES))
            )).all()
            hit = next(((name, str(state).lower()) for name, url, state in rows if _url_key(url) in urls), None)
    except Exception as exc:  # noqa: BLE001  fail closed: a read that failed is not a peer in good standing
        logger.error(f"[QuarantineGate] {context}: could not read the compliance state (presenter {presenter}): "
                     f"{type(exc).__name__}: {exc}")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=f"Could not read the compliance state of the registries in this request; retry "
                                   f"{NO_FUNDS_MOVED}")
    if hit is None:
        return
    name, state = hit
    logger.warning(f"[QuarantineGate] REFUSED {context} with registry {name} ({state}); presenter={presenter}")
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                        detail=f"Refused: {quarantine_reason(name, state)} {NO_FUNDS_MOVED}")


def quarantine_reason(name: str, state: str) -> str:
    """Why a money path refused. It carries no "nothing moved" mark: a caller adds one only where it is true (a refusal
    before the first move); an FX route hop that refuses holds an ingress that has moved."""
    return f"registry {name} is {state} on this registry: no money moves with it while that stands"


async def assert_registry_not_quarantined(
    db: AsyncSession,
    registry_id: Optional[str],
    *,
    context: str,
    actor_agent_did: Optional[str] = None,
) -> None:
    """403 when this registry holds `registry_id` in quarantine or blacklisted. When the compliance state cannot be read
    the answer is 503 and nothing has moved: the caller asks before its first move."""
    try:
        hit = await quarantined_registry(db, registry_id)
    except Exception as exc:  # noqa: BLE001  fail closed: a read that failed is not a peer in good standing
        from agentvault_registry.services.payout_outcome import NO_FUNDS_MOVED
        logger.error(f"[QuarantineGate] {context}: could not read the compliance state of {registry_id}: "
                     f"{type(exc).__name__}: {exc}")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=f"Could not read the compliance state of registry {registry_id}; retry "
                                   f"{NO_FUNDS_MOVED}")
    if hit is None:
        return
    name, state = hit
    logger.warning(f"[QuarantineGate] REFUSED {context} with registry {name} ({state}); actor_agent={actor_agent_did}")
    from agentvault_registry.services.payout_outcome import NO_FUNDS_MOVED
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                        detail=f"Refused: {quarantine_reason(name, state)} {NO_FUNDS_MOVED}")
