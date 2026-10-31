"""Frame Federation Invitation endpoints (WS3, 2026-04-21).

Implements the initiator-driven bilateral handshake for sovereign-frame
federation — MODEL 3 of the scaling doc's "Sovereign Frame Federation"
architecture. Trust-bundle-only (no federation license); handshake exchanges
SPIRE trust bundles so both frames can mTLS-authenticate each other's
traffic.

Public endpoints (inbound from remote frames):
    POST /api/v1/federation/frame-invitations
    POST /api/v1/federation/frame-invitations/{id}/finalize

Admin endpoints (gated admin_federation):
    GET  /api/v1/admin/federation/frame-invitations
    GET  /api/v1/admin/federation/frame-invitations/{id}
    POST /api/v1/admin/federation/frame-invitations/{id}/approve
    POST /api/v1/admin/federation/frame-invitations/{id}/reject
    POST /api/v1/admin/federation/frame-invitations/{id}/finalize-retry
    POST /api/v1/admin/federation/frames/{peer_id}/revoke

The handshake protocol is documented in the plan file
(/root/.claude/plans/rustling-enchanting-ritchie.md). Short version:

    1. Remote POSTs to us: creates pending invitation
    2. Admin approves: we import remote bundle + insert peer_registries
    3. We POST to remote's /finalize: carries our bundle + nonce echo
    4. Remote validates nonce + imports our bundle + inserts its peer row
    5. Remote returns 200 → our invitation flips to completed

Failure at step 3 leaves status='approved' with completed_at=null;
finalize-retry re-attempts the outbound POST.
"""
import asyncio
import logging
import os
import urllib.parse
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status, Security
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry import models, schemas, security
from agentvault_registry.database import get_db
from agentvault_registry.event_emitter import get_event_emitter
from agentvault_registry.schemas import (
    FrameInvitationCreate,
    FrameInvitationOutboundCreate,
    FrameInvitationOutboundRead,
    FrameInvitationPublicRead,
    FrameInvitationAdminRead,
    FrameInvitationApprove,
    FrameInvitationReject,
    FrameInvitationFinalize,
    FrameFederationRevoke,
)
from agentvault_registry.services.frame_trust_manager import (
    FrameTrustManager,
    get_frame_trust_manager,
    _normalize_trust_domain,
)
from agentvault_registry.services import frame_data_plane_sync
from agentvault_registry.services import federation_licence as _fedlic
# §pass66 (2026-05-22) — Mainframe-only gate for admin endpoints.
from agentvault_registry.core.mainframe_gate import require_mainframe_only
from pydantic import Field as _Field

logger = logging.getLogger(__name__)


# §FEDLICENCE (2026-09-28): the invitation rail carries the signed network licence. Every field is OPTIONAL so an older
# frame on either side keeps federating exactly as before (it sends none and ignores what it does not know).
class FrameInvitationCreateLicensed(FrameInvitationCreate):
    """An initiator may present its licence-signing public key (so a genesis can issue it a licence at approve) and the
    network licence it already holds (so a licensed frame can be admitted where licences are enforced)."""
    licence_key: Optional[Dict[str, Any]] = None
    licence_certificate: Optional[str] = _Field(None, max_length=8192)
    licence_chain: Optional[List[str]] = _Field(None, max_length=4)


class FrameInvitationApproveLicensed(FrameInvitationApprove):
    """On the network's genesis only: issue the joining frame its network licence in the same approve (his plans:
    founding | private | research | non-profit, perpetual; enterprise, one year)."""
    network_licence_plan: Optional[str] = _Field(None, max_length=40)
    network_licence_days: Optional[int] = _Field(None, ge=1, le=3650)


class FrameInvitationFinalizeLicensed(FrameInvitationFinalize):
    """The approver hands over the network licence it issued, with the chain up to the genesis."""
    licence_certificate: Optional[str] = _Field(None, max_length=8192)
    licence_chain: Optional[List[str]] = _Field(None, max_length=4)


def _store_trust_value(peer) -> float:
    """The trust value the store's federation-operator record of a peer frame gets: the peer row's DERIVED value
    (SEC-20, services/bayesian_trust.derived_trust_for), the same the trust sync sends every cycle. A peer this frame
    has no record of (a new row) derives the Beta(1,1) prior, 0.5: unmeasured, not trusted. Before SEC-20 both calls
    sent the prior whatever the record held, so an admin's resync put a measured peer's vote weight back to 0.5 until
    the next trust sync."""
    from ..services.bayesian_trust import derived_trust_for
    return derived_trust_for(peer)

router = APIRouter(prefix="/api/v1", tags=["Frame Federation"])
# §RATEFIX: THE shared, Redis-backed limiter — the same object main.py puts on
# app.state, so these decorations are both enforced and shared across workers.
# A router-local Limiter() would be in-memory per worker AND invisible to the
# middleware; that is what made all 65 limits here meaningless.
from agentvault_registry.middleware.rate_limiter import shared_limiter as limiter

# §TRUSTCHAIN (2026-09-12): the delay before the approve/finalize rails ask the new peer for its
# policy hash. The peer's proxies gain our root on their cert-writer's next cycle (§BATCH6/7), so an
# immediate read can be refused; the poller's own 6-hour cycle is the fallback either way.
_COMPLIANCE_BASELINE_DELAY_S = float(os.environ.get("COMPLIANCE_BASELINE_DELAY_S", "45"))


def _schedule_compliance_baseline(peer_id: int, side: str) -> None:
    """Best effort, off the request: record the peer's compliance baseline once it is admitted.

    Without this, a peer admitted through the invitation rail held NO baseline row until the
    §TRUSTCHAIN first-sight poll, and before that held none at all (the Phase 2 admission
    pipeline was the only writer). Failure is logged and never raised: the approve has already
    committed, and the poller retries on its own cycle.
    """
    async def _later() -> None:
        try:
            await asyncio.sleep(_COMPLIANCE_BASELINE_DELAY_S)
            from agentvault_registry.background_tasks.compliance_poller import get_compliance_poller
            result = await get_compliance_poller().record_baseline_for_peer(peer_id)
            logger.info(f"[frame_invitations.{side}] compliance baseline for peer_id={peer_id}: {result}")
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                f"[frame_invitations.{side}] compliance baseline for peer_id={peer_id} not recorded "
                f"(non-fatal, the poller retries on its cycle): {exc}"
            )

    try:
        asyncio.create_task(_later())
    except RuntimeError as exc:  # no running loop (a synchronous test harness)
        logger.debug(f"[frame_invitations.{side}] baseline task not scheduled: {exc}")

# Emergency kill switch — if set to "true", public POST returns 503.
_PUBLIC_DISABLED_ENV = "FRAME_INVITATIONS_PUBLIC_DISABLED"

# V0650 (k), order gwo_8f8ee5ff285a9c43af26b725: two SANDBOX frames on one host federate with each other. Default off, and
# inert unless the frame's birth declaration says FRAME_POSTURE=sandbox (same_host_lane_open). While open, an anonymous
# invitation from the private network may name a bundle host on an RFC1918/ULA address, and the peer-console calls also
# trust the host's internal edge CA (the PEM file named).
_SAME_HOST_ENV = "FRAME_INVITATIONS_SAME_HOST_PEERS"
_PEER_CA_ENV = "FRAME_INVITATIONS_PEER_CA_FILE"
_SAME_HOST_REFUSED = "refused: this frame does not declare FRAME_POSTURE=sandbox"
_TRUTHY = ("1", "true", "yes", "on")

# Outbound callback timeout (approve → remote /finalize)
_CALLBACK_TIMEOUT_SECONDS = 15.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _public_disabled() -> bool:
    return os.getenv(_PUBLIC_DISABLED_ENV, "").strip().lower() in ("1", "true", "yes")


def same_host_lane_open(env: Optional[Dict[str, str]] = None) -> bool:
    """V0650 (k): the same-host lane's own lock, and nothing else's. Open only when the opt-in is set AND the frame's birth
    declaration (core.frame_posture, the one reader of FRAME_POSTURE) is sandbox. It is not "this frame is a sandbox" for
    any other purpose: REGISTRY_ENVIRONMENT, which the MCP tester reads before it stages money-moving fixtures, is
    deliberately not part of it (the stack's frame template contract keeps kit files from setting it to sandbox)."""
    source = os.environ if env is None else env
    if (source.get(_SAME_HOST_ENV) or "").strip().lower() not in _TRUTHY:
        return False
    from agentvault_registry.core.frame_posture import declared_posture
    return declared_posture(source) == "sandbox"


def _same_host_peers() -> "tuple[bool, str]":
    """V0650 (k): (open, state) of the same-host opt-in: 'off', 'on', or the refusal when it is set on a frame that does
    not declare FRAME_POSTURE=sandbox (said once per read, as a WARNING: a switch that is set and does nothing must say
    so)."""
    if os.getenv(_SAME_HOST_ENV, "").strip().lower() not in _TRUTHY:
        return False, "off"
    if not same_host_lane_open():
        logger.warning("[FRAME-INVITE] %s is set but refused: this frame does not declare FRAME_POSTURE=sandbox",
                       _SAME_HOST_ENV)
        return False, _SAME_HOST_REFUSED
    return True, "on"


def _same_host_caller(request: Request) -> bool:
    """V0650 (k): may this anonymous invitation take the same-host lane? Only under the honored opt-in, and only when the
    address our own edge observed (core.client_ip.effective_client_ip: the LAST X-Forwarded-For element, then X-Real-IP,
    then the peer; never the forgeable first element _get_client_ip reads) is on the private network (RFC1918/ULA). A
    loopback or unknown origin never is (an MCP relay arrives as loopback)."""
    honored, _state = _same_host_peers()
    if not honored:
        return False
    from agentvault_registry.core.client_ip import effective_client_ip
    from agentvault_registry.services.frame_trust_manager import _address_is_lan_private
    try:
        ip = effective_client_ip(request)
    except Exception:  # noqa: BLE001 — an origin that cannot be read is not the private network
        return False
    return bool(ip) and _address_is_lan_private(str(ip))


def _peer_console_verify():
    """V0650 (k): what the peer-console calls verify against: True (the public roots), or, under the honored opt-in with
    a readable FRAME_INVITATIONS_PEER_CA_FILE, the system roots plus that file (the host's internal edge CA, which a
    sandbox's 'tls internal' edge chains to). A file that cannot be read or holds no certificate keeps True, said."""
    honored, _state = _same_host_peers()
    path = os.getenv(_PEER_CA_ENV, "").strip()
    if not honored or not path:
        return True
    try:
        with open(path, "r", encoding="utf-8") as fh:
            pem = fh.read()
    except OSError as exc:
        logger.warning("[FRAME-INVITE] %s is not readable (%s): the public roots only", _PEER_CA_ENV, type(exc).__name__)
        return True
    ctx = _verify_context_with_bundle(pem)
    if ctx is None:
        logger.warning("[FRAME-INVITE] %s holds no usable certificate: the public roots only", _PEER_CA_ENV)
        return True
    return ctx


def _local_trust_domain() -> str:
    return _normalize_trust_domain(os.getenv("SPIRE_TRUST_DOMAIN", "agentvault.com"))


def _local_bundle_endpoint_url() -> str:
    """The URL we advertise for OUR bundle endpoint in the finalize callback.

    SPIRE 1.10+ serves the JWK Set at the root path `/`, NOT at the canonical
    `/.well-known/spiffe/bundle` (verified empirically: well-known returns 404).
    Admins can override via FRAME_LOCAL_BUNDLE_ENDPOINT_URL for deployments
    that front SPIRE behind a different path.
    """
    env_url = os.getenv("FRAME_LOCAL_BUNDLE_ENDPOINT_URL", "").strip()
    if env_url:
        return env_url
    td = _local_trust_domain()
    return f"https://{td}:8443/"


def _peer_dialable(url: str) -> bool:
    """Can a PEER dial this URL? A docker-internal service name (`hello-nginx-federation`, no dot) and loopback cannot
    be; a public name or an address can. §HELLOFRAME Phase 3: the throwaway advertised its compose-internal lane and
    the peer's finalize callback died on name resolution (the §FRAMELIC row 154 class, from the initiator's side)."""
    try:
        host = (urllib.parse.urlsplit(url).hostname or "").strip().lower()
    except ValueError:
        return False
    if not host or host in ("localhost",) or host.startswith("127.") or host == "::1":
        return False
    return "." in host or ":" in host


def _local_federation_endpoint_url() -> str:
    """This frame's mTLS federation lane AS PEERS MUST DIAL IT: BILATERAL_PEER_URL (the public mTLS address the standup
    writes) first, FRAME_LOCAL_FEDERATION_ENDPOINT_URL (the frame's own dial to its gateway, a compose-internal name on
    a runner-built frame) only when a peer could dial it, else nothing (the outbound endpoint then refuses, naming the
    variables, instead of advertising an address nobody can reach)."""
    cands = [(os.getenv(k) or "").strip().rstrip("/") for k in ("BILATERAL_PEER_URL", "FRAME_LOCAL_FEDERATION_ENDPOINT_URL")]
    dialable = [v for v in cands if v and _peer_dialable(v)]
    # a federation lane is an mTLS gateway on its own port, never the 443 console: among the dialable candidates prefer one
    # that names a port. Measured 2026-09-18: the sandbox pair's BILATERAL_PEER_URL is its console (stood up before
    # §BATCH5's rule) while its FRAME_LOCAL lane is the public :8443; a runner-built frame is the reverse (FRAME_LOCAL is
    # compose-internal, BILATERAL the public lane). The port decides; a lone dialable candidate without one is still taken.
    def _ported(u):
        try:
            p = urllib.parse.urlsplit(u).port
        except ValueError:
            return False
        return p not in (None, 443, 80)
    for v in dialable:
        if _ported(v):
            return v
    return dialable[0] if dialable else ""


def _local_event_store_public_url() -> str:
    return (os.getenv("EVENT_STORE_PUBLIC_URL") or "").strip().rstrip("/")


def _local_name() -> str:
    return (os.getenv("REGISTRY_DISPLAY_NAME") or os.getenv("REGISTRY_NAME") or "Local Frame").strip()


def _send_themed_email_fnf(
    *,
    subject: str,
    template: str,
    context: Dict[str, Any],
    theme: str,
    to_address: str,
) -> None:
    """Fire-and-forget themed email dispatch (best-effort, never raises).

    Schedules the send on the running loop so the caller doesn't block on SMTP.
    """
    if not to_address:
        return
    from agentvault_registry.email_utils import send_themed_email

    async def _dispatch() -> None:
        try:
            await send_themed_email(
                subject=subject,
                recipients=[to_address],
                template=template,
                context=context,
                theme=theme,  # type: ignore[arg-type]
            )
        except Exception as exc:
            logger.warning(
                f"[frame_invitations] email send failed (to={to_address}, template={template}): {exc}"
            )

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_dispatch())
    except RuntimeError:
        asyncio.run(_dispatch())


def _admin_notification_email() -> Optional[str]:
    """Commander / ops notification address."""
    return os.getenv("FRAME_INVITATIONS_ADMIN_EMAIL") or os.getenv(
        "OPERATORS_ADMIN_EMAIL", "operators@theprotocol.cloud"
    )


async def _emit_event(event_type: str, invitation: models.FrameInvitation, **extra) -> None:
    """Emit a frame-federation event. Swallows emission errors so we never fail
    a DB commit because of an event pipeline hiccup."""
    try:
        emitter = get_event_emitter()
        data: Dict[str, Any] = {
            "invitation_id": invitation.id,
            "initiator_trust_domain": invitation.initiator_trust_domain,
            "initiator_name": invitation.initiator_name,
            "status": invitation.status,
            "peer_registry_id": invitation.peer_registry_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        data.update(extra or {})
        await emitter.emit(
            event_type=event_type,
            aggregate_id=f"frame_invitation:{invitation.id}",
            aggregate_type="FrameInvitation",
            data=data,
        )
    except Exception as exc:
        logger.warning(f"[frame_invitations] event emit failed ({event_type}): {exc}")


def _get_client_ip(request: Request) -> Optional[str]:
    # Respect X-Forwarded-For when present (nginx sets it); fall back to peer.
    xff = request.headers.get("x-forwarded-for", "").strip()
    if xff:
        return xff.split(",")[0].strip() or None
    try:
        return request.client.host if request.client else None
    except Exception:
        return None


async def _inactivate_peer_row(db: AsyncSession, peer_id: int) -> None:
    peer = (await db.execute(
        select(models.PeerRegistry).where(models.PeerRegistry.id == peer_id)
    )).scalar_one_or_none()
    if peer and (peer.status or "").upper() == "ACTIVE":
        peer.status = "INACTIVE"
        peer.deactivated_reason = "federation_revoked"  # guard-set: never auto-revived
        peer.deactivated_at = datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Public: create invitation (inbound from a remote frame)
# ---------------------------------------------------------------------------

def _federate_entries_on_approve_enabled() -> bool:
    """§FRAMEFED kill switch (default ON). Set FRAME_FEDERATE_ENTRIES_ON_APPROVE=false to keep the
    old behaviour (bundle + peer row only, entries left for the operator to federate by hand)."""
    return os.getenv("FRAME_FEDERATE_ENTRIES_ON_APPROVE", "true").strip().lower() not in (
        "0", "false", "no", "off"
    )


def _federation_relationship_on_approve_enabled() -> bool:
    """§MONEY-R52 kill switch (default ON). FRAME_FEDERATION_RELATIONSHIP_ON_APPROVE=false keeps the
    relationship a hand step (`spire-server federation create`)."""
    return os.getenv("FRAME_FEDERATION_RELATIONSHIP_ON_APPROVE", "true").strip().lower() not in (
        "0", "false", "no", "off"
    )


async def _federation_relationship_after_bundle(mgr: FrameTrustManager, peer_td: str,
                                                bundle_endpoint_url: str, *, site: str) -> Dict[str, Any]:
    """§MONEY-R52 (2026-09-04) — the SPIRE federation RELATIONSHIP, right after the bundle import.

    `add_peer_bundle` puts the peer's bundle in place ONCE; without `federation create` SPIRE never
    re-fetches it and the bundle goes stale (the drift monitor's `frame_bundle_stale`). The endpoint
    is derived from the bundle-endpoint URL the invitation carries (its SPIRE server, https_spiffe);
    an existing relationship is left exactly as it is and reported. Best-effort: never fails the
    approval; the outcome travels in the response and the log."""
    if not _federation_relationship_on_approve_enabled():
        logger.info("[frame_invitations.%s] federation relationship for %s SKIPPED (kill switch)", site, peer_td)
        return {"ok": None, "skipped": "FRAME_FEDERATION_RELATIONSHIP_ON_APPROVE=false"}
    try:
        ok, detail = await mgr.ensure_federation_relationship(peer_td, bundle_endpoint_url)
        out: Dict[str, Any] = dict(detail or {})
        out["ok"] = bool(ok)
        (logger.info if ok else logger.warning)(
            "[frame_invitations.%s] federation relationship for %s on %s: %s", site, peer_td, mgr.spire_container, out,
        )
        return out
    except Exception as exc:  # noqa: BLE001 — reported in the response, never swallowed
        logger.warning("[frame_invitations.%s] federation relationship for %s failed: %r", site, peer_td, exc)
        return {"ok": False, "error": repr(exc)}


async def _federate_entries_after_bundle(mgr: FrameTrustManager, peer_td: str, *, site: str) -> Dict[str, Any]:
    """§FRAMEFED (2026-09-04) — the THIRD federation layer, run right after a peer bundle lands.

    Federation is three layers: the bundle IMPORT (`add_peer_bundle`, done just before this),
    the SPIRE federation RELATIONSHIP (`spire-server federation create` — still a hand step),
    and `-federatesWith <peer>` on every WORKLOAD ENTRY. Without the third, this frame's SVIDs
    never carry the peer's bundle and every cross-frame mTLS call dies CERTIFICATE_VERIFY_FAILED
    while the invitation reads `completed`. The frame provisioner cannot do it at create time for
    a peer whose bundle does not exist yet, so the approve rail does it here, once the bundle does.

    Best-effort by design: an invitation approval must not fail on an entry update, but the
    outcome travels in the response and the log — numbers, never a silent pass."""
    if not _federate_entries_on_approve_enabled():
        logger.info("[frame_invitations.%s] entry federation with %s SKIPPED (kill switch)", site, peer_td)
        return {"ok": None, "skipped": "FRAME_FEDERATE_ENTRIES_ON_APPROVE=false"}
    try:
        from ..services.frame_test_provisioner import federate_frame_workload_entries
        ok, detail = await asyncio.to_thread(
            federate_frame_workload_entries, mgr.spire_container, peer_td
        )
        out: Dict[str, Any] = dict(detail or {})
        out["ok"] = bool(ok)
        (logger.info if ok else logger.warning)(
            "[frame_invitations.%s] workload entries federated with %s on %s: %s",
            site, peer_td, mgr.spire_container, out,
        )
        return out
    except Exception as exc:  # noqa: BLE001 — reported in the response, never swallowed
        logger.warning("[frame_invitations.%s] entry federation with %s failed: %r", site, peer_td, exc)
        return {"ok": False, "error": repr(exc)}



def _may_name_internal_bundle(dev: Optional[models.Developer]) -> bool:
    """§FINDINGS-A4 3d: whether this caller may have the PUBLIC invitation route dial an internal host. Only a federation
    admin (is_admin or admin_federation) on a credential whose scope grants admin, the same terms `require_admin_flag`
    uses (a forced password change and a narrow MCP key both refuse)."""
    if dev is None or bool(getattr(dev, "must_change_password", False)):
        return False
    if not (bool(dev.is_admin) or bool(getattr(dev, "admin_federation", False))):
        return False
    # D6-621: REQUIRE_ADMIN_2FA, as require_admin_flag asks it
    return bool(security.api_key_grants_admin()) and security.admin_second_factor_ok(dev)


@router.post(
    "/federation/frame-invitations",
    response_model=FrameInvitationPublicRead,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("5/hour")
async def create_frame_invitation(
    request: Request,
    payload: FrameInvitationCreateLicensed,
    db: AsyncSession = Depends(get_db),
    caller: Optional[models.Developer] = Depends(security.get_current_developer_optional),
):
    """Remote frame POSTs an invitation to federate with us.

    No auth. Rate-limited. Nonce + bundle-endpoint reachability gate prevent
    spam. Stored with status='pending' for admin review.
    """
    if _public_disabled():
        raise HTTPException(status_code=503, detail="Frame invitations temporarily disabled by administrator.")

    initiator_td = _normalize_trust_domain(payload.trust_domain)
    if initiator_td == _local_trust_domain():
        raise HTTPException(status_code=422, detail="Trust domain matches our own — cannot federate with self.")

    # Collision guard: one pending invitation per trust domain at a time
    existing = (await db.execute(
        select(models.FrameInvitation).where(
            models.FrameInvitation.initiator_trust_domain == initiator_td,
            models.FrameInvitation.status == "pending",
        )
    )).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=f"A pending invitation already exists for trust domain '{initiator_td}' (id={existing.id})",
        )

    # Reachability probe — avoids accepting invitations for unreachable hosts.
    mgr: FrameTrustManager = get_frame_trust_manager()
    # §FINDINGS-A4 3d (2026-09-27, his "fix 1-4 approved"): anonymous callers reach only PUBLIC https hosts (every hop)
    # and get a generic refusal, never the probe's own error (it was a status oracle from inside our network); a
    # federation admin may name an internal host and sees the detail (the standup's federate step, same-host frames).
    internal_ok = _may_name_internal_bundle(caller)
    # V0650 (k): the same-host lane (opt-in, sandbox only, a caller on the private network): an RFC1918/ULA bundle host
    # passes, every other internal range stays refused, and the refusal stays the generic one.
    same_host = (not internal_ok) and _same_host_caller(request)
    probe_kw: Dict[str, Any] = {"allow_internal": internal_ok}
    if same_host:
        probe_kw["allow_private"] = True
    ok, err = await mgr.probe_bundle_endpoint(payload.bundle_endpoint_url, **probe_kw)
    if not ok:
        logger.info(f"[FRAME-INVITE] bundle probe refused for {initiator_td} (federation admin: {internal_ok}, "
                    f"same-host lane: {same_host}): {err}")
        raise HTTPException(
            status_code=422,
            detail=(f"Bundle endpoint probe failed: {err or 'unreachable'}" if internal_ok else
                    "Bundle endpoint probe failed: the bundle endpoint must be a public https address that answers"),
        )

    # Persist
    invitation = models.FrameInvitation(
        id=str(uuid.uuid4()),
        initiator_trust_domain=initiator_td,
        initiator_bundle_endpoint_url=payload.bundle_endpoint_url,
        initiator_federation_endpoint_url=payload.federation_endpoint_url,
        initiator_event_store_url=payload.event_store_url,  # WS3.5: optional SF-4 hint
        initiator_name=payload.name.strip(),
        initiator_contact_email=payload.contact_email.strip(),
        initiator_description=(payload.description or None),
        initiator_nonce=payload.initiator_nonce.lower(),
        initiator_ip=_get_client_ip(request),
        status="pending",
    )
    # §FEDLICENCE: what the initiator presented about its licence, kept for the approve (checked there, not here)
    if payload.licence_key is not None:
        try:
            _fedlic.public_key_from_jwk(payload.licence_key)
        except ValueError:
            raise HTTPException(status_code=422, detail="licence_key is not an Ed25519 public JWK")
        invitation.initiator_licence_key = {k: payload.licence_key.get(k) for k in ("kty", "crv", "x")}
    if payload.licence_certificate:
        invitation.initiator_licence_certificate = payload.licence_certificate.strip()
        invitation.initiator_licence_chain = [c for c in (payload.licence_chain or []) if isinstance(c, str)][:2]
    db.add(invitation)
    await db.commit()
    await db.refresh(invitation)

    logger.info(
        f"[frame_invitations] new pending invitation from {initiator_td} "
        f"(name={invitation.initiator_name}, id={invitation.id})"
    )

    await _emit_event("FrameInvitationRequested", invitation,
                      bundle_endpoint_url=payload.bundle_endpoint_url,
                      federation_endpoint_url=payload.federation_endpoint_url,
                      initiator_ip=invitation.initiator_ip)

    # Notify admin (non-blocking)
    admin_addr = _admin_notification_email()
    if admin_addr:
        _send_themed_email_fnf(
            subject=f"Frame Federation Invitation — {invitation.initiator_name}",
            template="frame_federation_invited",
            context={
                "initiator_name": invitation.initiator_name,
                "trust_domain": initiator_td,
                "bundle_endpoint_url": payload.bundle_endpoint_url,
                "federation_endpoint_url": payload.federation_endpoint_url,
                "contact_email": invitation.initiator_contact_email,
                "source_ip": invitation.initiator_ip or "unknown",
                "description": payload.description,
                "invitation_id": invitation.id,
            },
            theme="neural",
            to_address=admin_addr,
        )

    return invitation


# ---------------------------------------------------------------------------
# Public: finalize (receives bilateral callback from approving frame)
# ---------------------------------------------------------------------------

def _refuse_bad_namespace(trust_domain: str, *, site: str) -> None:
    """§DIDWIDEN item 1 — G3. The issuer namespace IS the trust domain, so a federation partner whose
    trust domain is our own (impersonation / a self-invite), a reserved word, or not DNS-shaped can
    never be a distinct issuer: refuse before any bundle or peer row exists. 409 did_namespace_taken."""
    import os as _os
    from ..identifiers import valid_issuer as _valid_issuer
    td = (trust_domain or "").strip().lower()
    own = (_os.environ.get("SPIRE_TRUST_DOMAIN") or "").strip().lower()
    if not _valid_issuer(td):
        raise HTTPException(status_code=409, detail=f"did_namespace_invalid: trust domain {trust_domain!r} is not a valid issuer namespace (DNS-shaped, lowercase, not reserved); site={site}")
    if own and td == own:
        raise HTTPException(status_code=409, detail=f"did_namespace_taken: trust domain {td!r} is this registry's own issuer namespace, a peer cannot claim it; site={site}")


@router.post("/federation/frame-invitations/{invitation_id}/finalize")
async def finalize_frame_invitation(
    invitation_id: str = Path(..., min_length=1, max_length=64),
    payload: FrameInvitationFinalizeLicensed = ...,
    db: AsyncSession = Depends(get_db),
):
    """Called BY the approving frame TO the initiator's side to complete the
    bilateral handshake.

    When WE initiated an outbound invitation (future flow, currently only
    applies to synthetic/bootstrap cases), this endpoint lands the approver's
    bundle on our side and inserts a peer_registries row. Nonce-verified.
    Single-use: once completed, further calls return 409.
    """
    inv = (await db.execute(
        select(models.FrameInvitation).where(models.FrameInvitation.id == invitation_id)
    )).scalar_one_or_none()
    if inv is None:
        raise HTTPException(status_code=404, detail="Invitation not found.")

    # Nonce verification — single-use, constant-time compare
    if not secrets.compare_digest(
        (inv.initiator_nonce or "").lower(),
        (payload.nonce_echo or "").lower(),
    ):
        raise HTTPException(status_code=403, detail="Nonce mismatch.")

    if inv.status == "completed":
        raise HTTPException(status_code=409, detail="Invitation already completed.")
    if inv.status not in ("pending", "approved"):
        raise HTTPException(
            status_code=409,
            detail=f"Invitation cannot be finalized from status '{inv.status}'.",
        )

    # §FRAMELIC — the approver may have issued us our federation licence as part of the
    # handshake. We record its PREFIX (never the key) so the admin can tell at a glance which
    # licence this frame holds, and hand the plain key back in the response exactly once — the
    # standup driver writes it into this frame's env as FEDERATION_LICENSE_KEY. A frame that is
    # never handed one simply holds none, which is the pre-0176 state.
    issued_license_key = (payload.federation_license_key or "").strip() or None
    if issued_license_key:
        try:
            inv.review_notes = (
                (inv.review_notes or "") +
                f"\n[framelic] licence issued by approver, prefix {issued_license_key[:12]}"
            ).strip()[:2000]
        except Exception:  # noqa: BLE001 — a note must never cost us the federation
            pass
        # §HELLOFRAME (2026-09-18): the key arrives HERE, at the initiator's registry, which stores its hash nowhere and
        # its prefix in a note, while the frame's env (FEDERATION_LICENSE_KEY, read by the emitter and the self-rotation
        # rail) is written by a hand on the HOST. Parked in Redis for one hour, handed out once by the admin route below;
        # a frame without Redis keeps the pre-09-18 behaviour (the key is lost and finalize-retry rotates a new one).
        await _park_licence_key(inv.id, issued_license_key)

    # §FEDLICENCE: the network licence the genesis issued at its approve. Verified and installed in a SAVEPOINT: a
    # licence this frame cannot verify (no network configured, another key, a root it does not trust) is reported in
    # the answer and never costs the federation.
    licence_install: Optional[Dict[str, Any]] = None
    if payload.licence_certificate:
        try:
            async with db.begin_nested():
                _lrow, _lv = await _fedlic.install_network_licence(db, payload.licence_certificate,
                                                                   list(payload.licence_chain or []))
            licence_install = {"installed": _lrow.hash, "state": _lv.state, "reason": _lv.reason}
        except ValueError as _le:
            licence_install = {"installed": None, "refused": str(_le)}
        except Exception as _le:  # noqa: BLE001
            licence_install = {"installed": None, "refused": f"{type(_le).__name__}"}
        logger.info("[fedlicence] finalize from %s delivered a network licence: %s",
                    payload.approver_trust_domain, licence_install)

    # Import approver bundle into our SPIRE
    approver_td = _normalize_trust_domain(payload.approver_trust_domain)
    _refuse_bad_namespace(approver_td, site="finalize")
    if inv.spire_bundle_imported_at is not None:
        # §HELLOFRAME (2026-09-18): the host CLI (`frame federate`) put the approver's bundle into this frame's SPIRE
        # and created the relationship BEFORE it posted the invitation, and said so on the outbound row. Every SPIRE
        # operation here runs `docker exec` through a socket a hardened registry does not hold (Phase 1 D9), so
        # this branch records the federation and touches SPIRE not at all: a socket-less initiator completes.
        entries_federated = {"ok": None, "skipped": "the host CLI imported the bundle and federated the entries before the invitation"}
        federation_relationship = {"ok": None, "skipped": "created by the host CLI before the invitation"}
        logger.info("[frame_invitations.finalize] bundle for %s pre-imported by the host CLI at %s; SPIRE untouched here",
                    approver_td, inv.spire_bundle_imported_at.isoformat())
    else:
        mgr: FrameTrustManager = get_frame_trust_manager()
        # Detect format: PEM typically starts with "-----BEGIN"; JSON starts with "{"
        fmt = "pem" if payload.approver_bundle_pem.lstrip().startswith("-----BEGIN") else "spiffe"
        result = await mgr.add_peer_bundle(approver_td, payload.approver_bundle_pem, format_hint=fmt)
        if not result:
            logger.error(f"[frame_invitations.finalize] bundle import failed: {result.message}")
            raise HTTPException(status_code=502, detail=f"SPIRE bundle import failed: {result.message}")
        # §FRAMEFED: the bundle is in; now every workload entry must federate with it.
        entries_federated = await _federate_entries_after_bundle(mgr, approver_td, site="finalize")
        # §MONEY-R52: and the SPIRE relationship, so the imported bundle keeps refreshing.
        federation_relationship = await _federation_relationship_after_bundle(
            mgr, approver_td, payload.approver_bundle_endpoint_url, site="finalize")

    # Insert / update peer_registries row for the approver
    existing_peer = (await db.execute(
        select(models.PeerRegistry).where(
            models.PeerRegistry.trust_domain == approver_td,
            models.PeerRegistry.peer_type == "frame",
        )
    )).scalar_one_or_none()

    now = datetime.now(timezone.utc)
    # §HELLOFRAME: the row's base_url is the lane peers DIAL (card pulls, fan-out): the approver's federation lane
    # when it says so; the pre-09-18 derivation from its bundle endpoint otherwise (Phase 1 surprise 1).
    approver_base_url = (payload.approver_federation_endpoint_url or "").strip().rstrip("/") or (
        payload.approver_bundle_endpoint_url.replace("/.well-known/spiffe/bundle", "").rstrip("/")
        or payload.approver_bundle_endpoint_url)
    if existing_peer is None:
        # Need an owner_developer_id. Use invitation reviewer if set; else dev_id=1 (Commander).
        owner_dev_id = inv.reviewed_by or 1
        peer = models.PeerRegistry(
            owner_developer_id=owner_dev_id,
            name=payload.approver_name.strip()[:255],
            description="Sovereign frame — federated via bilateral invitation",
            base_url=approver_base_url,
            admin_contact_email=inv.initiator_contact_email or "admin@unknown.invalid",
            status="ACTIVE",
            discovery_auth_info={},
            peer_type="frame",
            trust_domain=approver_td,
            spiffe_bundle_endpoint_url=payload.approver_bundle_endpoint_url,
            hop_distance=1,
            last_seen_in_topology_at=now,
            approved_at=now,
            approved_by_developer_id=owner_dev_id,
        )
        db.add(peer)
        await db.flush()
        peer_id = peer.id
    else:
        existing_peer.status = "ACTIVE"
        existing_peer.spiffe_bundle_endpoint_url = payload.approver_bundle_endpoint_url
        if payload.approver_federation_endpoint_url:
            existing_peer.base_url = approver_base_url
        existing_peer.last_seen_in_topology_at = now
        peer_id = existing_peer.id

    # Flip invitation to completed
    inv.status = "completed"
    inv.completed_at = now
    inv.peer_registry_id = peer_id
    inv.spire_bundle_imported_at = inv.spire_bundle_imported_at or now
    await _clear_card_pull_parking(payload.approver_name, where="finalize")

    await db.commit()
    await db.refresh(inv)

    await _emit_event("FrameFederationEstablished", inv,
                      approver_trust_domain=approver_td,
                      approver_name=payload.approver_name,
                      peer_registry_id=peer_id,
                      side="initiator")
    _schedule_compliance_baseline(peer_id, "finalize")

    logger.info(
        f"[frame_invitations.finalize] completed: initiator={inv.initiator_trust_domain} "
        f"approver={approver_td} peer_id={peer_id}"
    )
    return {"status": "completed", "peer_registry_id": peer_id, "entries_federated": entries_federated,
            # §FRAMELIC — echoed ONCE so the joining side can seed FEDERATION_LICENSE_KEY.
            "federation_license_key": issued_license_key,
            "federation_relationship": federation_relationship,
            "licence_install": licence_install}


# ---------------------------------------------------------------------------
# Admin: the INITIATOR side (§HELLOFRAME 2026-09-18)
# ---------------------------------------------------------------------------

_LICENCE_PARK_TTL_S = int(os.environ.get("FRAME_LICENCE_PARK_TTL_S", "3600"))


def _licence_park_key(invitation_id: str) -> str:
    return f"frame_invitation:{invitation_id}:licence_key"


# §HELLOFRAME (2026-09-18): the card-pull worker parks a peer after failed pulls (registry:federation:cardpull_backoff:<name>,
# ×2^n, capped) and the parking outlives the peer's incarnation: a frame torn down and stood up again under the same name was
# still parked on the approver (`unreachable:8`, 38 minutes left) when its new invitation was approved, so the approver stored
# none of its cards for as long as the parking lasted while the new frame pulled the approver's within a minute. An approve
# and a completed finalize are the moments a peer is KNOWN to be reachable: both clear that peer's parking.
CARD_PULL_PARKING_PREFIXES = ("registry:federation:cardpull_backoff:", "registry:federation:cardpull_streak:")


async def _clear_card_pull_parking(peer_name: str, *, where: str) -> Optional[int]:
    """Delete the card-pull backoff and streak keys of `peer_name`. Returns the number of keys removed, None when there was
    no Redis or the delete failed (logged; never costs the federation)."""
    name = (peer_name or "").strip()
    if not name:
        return None
    try:
        from agentvault_registry.background_tasks.leader import get_redis
        r = await get_redis()
        if r is None:
            return None
        n = int(await r.delete(*[p + name for p in CARD_PULL_PARKING_PREFIXES]) or 0)
        if n:
            logger.info("[frame_invitations.%s] card-pull parking cleared for peer %s (%d key(s))", where, name, n)
        return n
    except Exception as exc:  # noqa: BLE001
        logger.warning("[frame_invitations.%s] card-pull parking for %s not cleared: %r", where, peer_name, exc)
        return None


async def _park_licence_key(invitation_id: str, plain_key: str) -> bool:
    """The delivered licence key waits for the host CLI (`frame federate`), one hour, in Redis. Returns False, and
    says so in the log, where no Redis is configured: the key is then gone and a finalize-retry rotates a new one."""
    try:
        from agentvault_registry.background_tasks.leader import get_redis
        r = await get_redis()
        if r is None:
            logger.warning("[frame_invitations.finalize] no Redis: the licence key for %s cannot be parked for the host CLI", invitation_id)
            return False
        await r.set(_licence_park_key(invitation_id), plain_key, ex=_LICENCE_PARK_TTL_S)
        return True
    except Exception as exc:  # noqa: BLE001 — a parking failure must never cost the federation; it is logged
        logger.warning("[frame_invitations.finalize] licence key for %s not parked: %r", invitation_id, exc)
        return False


@router.get(
    "/admin/federation/frame-invitations/{invitation_id}/licence-key",
    dependencies=[
        Depends(require_mainframe_only),
        Security(security.require_admin_flag("admin_federation")),
    ],
)
async def take_parked_licence_key(
    invitation_id: str = Path(..., min_length=1, max_length=64),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """The licence key the approver's callback delivered, handed out ONCE to the frame's own admin (the host CLI writes
    it into the frame's env as FEDERATION_LICENSE_KEY and recreates the registry). A second call, a key older than the
    park TTL, or a callback that carried none, all answer 404 with the sentence that names finalize-retry."""
    inv = (await db.execute(
        select(models.FrameInvitation).where(models.FrameInvitation.id == invitation_id)
    )).scalar_one_or_none()
    if inv is None:
        raise HTTPException(status_code=404, detail="Invitation not found.")
    if inv.status != "completed":
        raise HTTPException(status_code=409, detail=f"the invitation is '{inv.status}', not completed: no licence has been delivered yet")
    key = None
    try:
        from agentvault_registry.background_tasks.leader import get_redis
        r = await get_redis()
        if r is not None:
            k = _licence_park_key(invitation_id)
            key = await r.get(k)
            if key is not None:
                await r.delete(k)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"the parked key could not be read: {type(exc).__name__}")
    if not key:
        raise HTTPException(
            status_code=404,
            detail=(f"no licence key is parked for {invitation_id}: it was handed out already, the callback carried none, or "
                    f"more than {_LICENCE_PARK_TTL_S} s passed. Ask the approver's admin for a finalize-retry, which rotates the "
                    "licence and delivers a new key."),
        )
    if isinstance(key, bytes):
        key = key.decode()
    return {"invitation_id": invitation_id, "federation_license_key": key, "prefix": key[:12], "handed_out_once": True}


@router.post(
    "/admin/federation/frame-invitations/outbound",
    response_model=FrameInvitationOutboundRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[
        Depends(require_mainframe_only),
        Security(security.require_admin_flag("admin_federation")),
    ],
)
async def create_outbound_frame_invitation(
    body: FrameInvitationOutboundCreate = ...,
    db: AsyncSession = Depends(get_db),
    current_admin: models.Developer = Depends(security.get_current_developer),
) -> Dict[str, Any]:
    """This frame ASKS a peer to federate: creates the nonce, POSTs the peer's public create with this frame's own
    facts, and records the outbound row UNDER THE ID THE PEER RETURNED, so the peer's finalize callback, which
    addresses the sender's id on the receiver (inv.id in both places), finds it here. Until 2026-09-18 only the
    sandbox bootstrap ever wrote an outbound row; the two 09-03 sandbox rows could never complete for exactly this
    reason. Admin-only, on the frame that joins; no new public route.
    """
    own_td = _local_trust_domain()
    own_bundle = _local_bundle_endpoint_url()
    own_lane = _local_federation_endpoint_url()
    if not own_td or not own_lane or not own_bundle:
        raise HTTPException(
            status_code=400,
            detail="this frame does not know its own trust domain, bundle endpoint or a federation lane a peer could dial "
                   "(SPIRE_TRUST_DOMAIN, FRAME_LOCAL_BUNDLE_ENDPOINT_URL, BILATERAL_PEER_URL or a public "
                   "FRAME_LOCAL_FEDERATION_ENDPOINT_URL; a compose-internal name is not one)",
        )
    target = body.target_registry_url.strip().rstrip("/")
    nonce = secrets.token_hex(16)
    payload: Dict[str, Any] = {
        "trust_domain": own_td,
        "bundle_endpoint_url": own_bundle,
        "federation_endpoint_url": own_lane,
        "name": _local_name(),
        "contact_email": body.contact_email,
        "description": body.description,
        "initiator_nonce": nonce,
    }
    own_es = _local_event_store_public_url()
    if own_es:
        payload["event_store_url"] = own_es
    # §FEDLICENCE: present this frame's licence-signing key (minted on first use) and the network licence it holds, read
    # and written in a session of their OWN, so the route's own transaction holds exactly what it did before
    try:
        from agentvault_registry.database import AsyncSessionLocal as _LicSession
        async with _LicSession() as _ldb:
            _key_row, _priv = await _fedlic.get_or_create_key(_ldb)
            payload["licence_key"] = dict(_key_row.public_jwk)
            _held = await _fedlic.get_cert(_ldb, "held")
            if _held is not None and _held.type == "frame":
                payload["licence_certificate"] = _held.jws
                payload["licence_chain"] = list(_held.chain or [])
            await _ldb.commit()
    except Exception as _lic_exc:  # noqa: BLE001 — a licence problem never costs the invitation; it is logged
        logger.warning("[frame_invitations.outbound] licence facts not attached: %s", _lic_exc)
    try:
        async with httpx.AsyncClient(timeout=_CALLBACK_TIMEOUT_SECONDS, verify=_peer_console_verify()) as client:
            r = await client.post(f"{target}/api/v1/federation/frame-invitations", json=payload)
    except Exception as e:  # noqa: BLE001 — the sentence is the point
        raise HTTPException(status_code=502, detail=f"the peer at {target} could not be reached: {type(e).__name__}: {str(e)[:160]}")
    if r.status_code not in (200, 201):
        raise HTTPException(status_code=502, detail=f"the peer at {target} refused the invitation: HTTP {r.status_code}: {r.text[:300]}")
    try:
        data = r.json() if r.text else {}
    except Exception:  # noqa: BLE001
        data = {}
    remote_id = str((data or {}).get("id") or "").strip()
    if not remote_id or len(remote_id) > 64:
        raise HTTPException(status_code=502, detail=f"the peer at {target} answered without an invitation id: {r.text[:200]}")
    existing = (await db.execute(
        select(models.FrameInvitation).where(models.FrameInvitation.id == remote_id)
    )).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail=f"an invitation row with id {remote_id} already exists on this frame")
    now = datetime.now(timezone.utc)
    inv = models.FrameInvitation(
        id=remote_id,
        initiator_trust_domain=own_td,
        initiator_bundle_endpoint_url=own_bundle,
        initiator_federation_endpoint_url=own_lane,
        initiator_event_store_url=own_es or None,
        initiator_name=_local_name()[:255],
        initiator_contact_email=body.contact_email,
        initiator_description=(body.description or f"outbound invitation to {target}")[:2000],
        initiator_nonce=nonce,
        status="pending",
        reviewed_by=current_admin.id,
        review_notes=f"[outbound] target {target}; sent by {current_admin.email}"[:2000],
        spire_bundle_imported_at=(now if body.spire_bundle_imported else None),
    )
    db.add(inv)
    await db.commit()
    await db.refresh(inv)
    logger.info("[frame_invitations.outbound] sent to %s as %s; row %s pre-imported=%s",
                target, own_td, inv.id, bool(inv.spire_bundle_imported_at))
    return {"id": inv.id, "status": inv.status, "target_registry_url": target, "initiator_trust_domain": own_td,
            "spire_bundle_imported": bool(inv.spire_bundle_imported_at), "created_at": inv.created_at}


# ---------------------------------------------------------------------------
# Admin: list + detail
# ---------------------------------------------------------------------------

@router.get(
    "/admin/federation/frame-invitations",
    dependencies=[
        Depends(require_mainframe_only),
        Security(security.require_admin_flag("admin_federation")),
    ],
)
async def list_frame_invitations(
    status_filter: Optional[str] = Query(
        "pending", alias="status",
        pattern=r"^(all|pending|approved|rejected|completed|revoked)$",
    ),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    q = select(models.FrameInvitation)
    if status_filter and status_filter != "all":
        q = q.where(models.FrameInvitation.status == status_filter)
    q = q.order_by(models.FrameInvitation.created_at.desc()).limit(limit).offset(offset)
    rows = (await db.execute(q)).scalars().all()
    invitations = [FrameInvitationAdminRead.model_validate(r).model_dump(mode="json") for r in rows]
    return {
        "invitations": invitations,
        "config": {
            "public_enabled": not _public_disabled(),
            "local_trust_domain": _local_trust_domain(),
            "local_bundle_endpoint_url": _local_bundle_endpoint_url(),
            "same_host_peers": _same_host_peers()[1],     # V0650 (k): off | on | refused: ...
        },
    }


@router.get(
    "/admin/federation/frame-invitations/{invitation_id}",
    dependencies=[
        Depends(require_mainframe_only),
        Security(security.require_admin_flag("admin_federation")),
    ],
    response_model=FrameInvitationAdminRead,
)
async def get_frame_invitation(
    invitation_id: str = Path(..., min_length=1, max_length=64),
    db: AsyncSession = Depends(get_db),
):
    inv = (await db.execute(
        select(models.FrameInvitation).where(models.FrameInvitation.id == invitation_id)
    )).scalar_one_or_none()
    if inv is None:
        raise HTTPException(status_code=404, detail="Invitation not found.")
    return inv


# ---------------------------------------------------------------------------
# Admin: approve
# ---------------------------------------------------------------------------

def _public_url_from_federation_url(url: str) -> str:
    """https://peer.example:8443/ → https://peer.example (the gateway port is not browser-reachable)."""
    import re as _re_fu
    return _re_fu.sub(r":\d+$", "", (url or "").strip().rstrip("/"))


def pem_roots_from_bundle(body: Optional[str]) -> str:
    """The X.509 roots of a trust bundle as PEM, whatever its carrier: a PEM body as is, a SPIFFE bundle (the JWK set
    `spire-server bundle show -format spiffe` prints, and what a bundle endpoint serves) through its `x5c` entries.
    Anything else, or nothing, is the empty string. §HELLOFRAME Phase 3, measured: the approve read its own bundle in
    the SPIFFE format, this loader accepted PEM only, so the "freshest bundle" path was dead by format and the callback
    verified against the on-disk file the cert-writer had not refreshed: `unable to get local issuer certificate` on
    the initiator's gateway, the §BATCH7 class, on the first approve of every fresh frame."""
    if not body:
        return ""
    if "-----BEGIN CERTIFICATE-----" in body:
        return body
    import base64 as _b64
    import json as _json
    try:
        doc = _json.loads(body)
    except ValueError:
        return ""
    pems = []
    for k in (doc.get("keys") or []) if isinstance(doc, dict) else []:
        if not isinstance(k, dict) or str(k.get("use") or "x509-svid") != "x509-svid":
            continue
        for der_b64 in (k.get("x5c") or []):
            try:
                der = _b64.b64decode(der_b64)
            except Exception:  # noqa: BLE001
                continue
            b = _b64.encodebytes(der).decode().replace("\n", "")
            lines = [b[i:i + 64] for i in range(0, len(b), 64)]
            pems.append("-----BEGIN CERTIFICATE-----\n" + "\n".join(lines) + "\n-----END CERTIFICATE-----\n")
    return "".join(pems)


def _verify_context_with_bundle(*bundle_bodies: Optional[str]):
    """§HELLOFRAME (2026-09-18): the verify set for the mTLS leg = every bundle body given (our own as SPIRE prints it,
    AND the initiator's bundle the approve fetched a moment ago) as PEM roots. The on-disk `/certs/bundle.0.pem` that
    `get_httpx_verify()` follows is refreshed by the cert-writer every REFRESH_SEC, so a callback dialed right after the
    import would fail on verify for up to that long (§BATCH7's class). No loadable root at all keeps the default verify."""
    pem = "".join(pem_roots_from_bundle(b) for b in bundle_bodies if b)
    if "-----BEGIN CERTIFICATE-----" not in pem:
        return None
    import ssl as _ssl
    try:
        ctx = _ssl.create_default_context()
        ctx.load_verify_locations(cadata=pem)
        return ctx
    except Exception:  # noqa: BLE001 — a bundle that does not parse leaves the default verify in place
        return None


def _finalize_targets(invitation: "models.FrameInvitation", verify_bundle_body: Optional[str] = None,
                      initiator_bundle_body: Optional[str] = None) -> list:
    """[(leg, url, httpx kwargs)] in dial order — see _post_bilateral_finalize (§BATCH9). The mTLS leg verifies the
    initiator's gateway against our own bundle AND the initiator's bundle the approve fetched a moment ago (the root
    that gateway's certificate chains to), so the callback lands on the first approve of a fresh frame."""
    from ..es_ssl_helper import get_httpx_verify
    from ..identity import svid_client
    base = (invitation.initiator_federation_endpoint_url or "").rstrip("/")
    path = f"/api/v1/federation/frame-invitations/{invitation.id}/finalize"
    legs = []
    fresh = _verify_context_with_bundle(verify_bundle_body, initiator_bundle_body)
    mtls_kwargs: dict = {"verify": fresh if fresh is not None else get_httpx_verify()}
    try:
        cc = svid_client.get_client_cert_config(target_url=base)
        if cc:
            mtls_kwargs.update(cc)
            mtls_kwargs["verify"] = fresh if fresh is not None else get_httpx_verify()
    except Exception:  # noqa: BLE001 — no SVID loaded (unit tests, a frame without SPIRE): the public leg remains
        pass
    if "cert" in mtls_kwargs:
        legs.append(("mtls", f"{base}{path}", mtls_kwargs))
    public = _public_url_from_federation_url(base)
    peer_verify = _peer_console_verify()   # V0650 (k): True, or under the honored opt-in the roots plus the edge CA
    if public and public != base:
        legs.append(("public", f"{public}{path}", {"verify": peer_verify}))
    elif not legs:
        legs.append(("public", f"{base}{path}", {"verify": peer_verify}))
    return legs


async def _issue_frame_license(
    db: AsyncSession, inv: models.FrameInvitation, actor_id: int, rotate: bool = False,
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """§FRAMELIC — mint the joining frame's federation licence AS PART of the approve handshake.

    His word: *"frames get a license from new eu frame when stood up"*. A licence handed out by a
    second manual step is a licence somebody forgets, so the frame is licensed at birth: the approver
    (the anchor) issues it here and the plain key rides back on the /finalize callback, once.

    By DID: a frame that already holds a licence keeps its id (its row, its history); the key is rotated when the
    caller asks (every approve and every finalize-retry do: each is a handshake that must deliver a usable key), else
    the existing
    one WITHOUT a key (there is no way to recover a key we only stored hashed, and pretending
    otherwise would be the "settled" lie in a new costume). Returns (license_id, plain_key, error).
    """
    from agentvault_registry.routers.federation_licenses import (
        _generate_federation_license_key, _sync_license_to_eventstore,
    )
    licensee_did = f"spiffe://{inv.initiator_trust_domain}"
    existing = (await db.execute(
        select(models.FederationLicense).where(
            models.FederationLicense.operator_did == licensee_did
        )
    )).scalar_one_or_none()
    if existing is not None:
        if existing.status != "active":
            existing.status = "active"
            existing.revoked_at = None
            existing.revoked_reason = None
            existing.suspended_at = None
            existing.suspended_reason = None
        if not rotate:
            return existing.id, None, None
        # §HELLOFRAME: a retry of a callback that never landed hands over a NEW key (the old one was never delivered)
        try:
            plain_key, key_hash, key_prefix = _generate_federation_license_key()
            existing.license_key_hash = key_hash
            existing.license_key_prefix = key_prefix
            await db.flush()
            await _sync_license_to_eventstore(
                license_id=existing.id, operator_name=existing.operator_name, license_key_hash=key_hash, op_status="active",
            )
            logger.info(f"[frame_invitations] ROTATED frame licence {existing.id} ({key_prefix}...) for "
                        f"{inv.initiator_trust_domain} on finalize-retry")
            return existing.id, plain_key, None
        except Exception as e:  # noqa: BLE001 — reported, never swallowed
            logger.error(f"[frame_invitations] frame licence rotation failed: {e}", exc_info=True)
            return existing.id, None, str(e)[:200]
    try:
        plain_key, key_hash, key_prefix = _generate_federation_license_key()
        lic = models.FederationLicense(
            id=str(uuid.uuid4()),
            operator_name=inv.initiator_name[:200],
            operator_did=licensee_did,
            licensee_type="frame",
            license_key_hash=key_hash,
            license_key_prefix=key_prefix,
            status="active",
            max_agents=int(os.getenv("FRAME_LICENSE_MAX_AGENTS", "100000")),
            max_events_per_minute=int(os.getenv("FRAME_LICENSE_MAX_EPM", "100000")),
            federation_tier=os.getenv("FRAME_LICENSE_TIER", "sovereign"),
        )
        db.add(lic)
        await db.flush()
        await _sync_license_to_eventstore(
            license_id=lic.id, operator_name=lic.operator_name, license_key_hash=key_hash, op_status="active",
        )
        logger.info(
            f"[frame_invitations] issued FRAME licence {lic.id} ({key_prefix}...) to "
            f"{inv.initiator_trust_domain} at approve"
        )
        return lic.id, plain_key, None
    except Exception as e:  # noqa: BLE001 — a licence failure must not lose the federation
        logger.error(f"[frame_invitations] frame licence issue failed: {e}", exc_info=True)
        return None, None, str(e)[:200]


async def _post_bilateral_finalize(
    invitation: models.FrameInvitation,
    our_bundle_body: str,
    federation_license_key: Optional[str] = None,
    initiator_bundle_body: Optional[str] = None,
    licence_certificate: Optional[str] = None,
    licence_chain: Optional[List[str]] = None,
) -> tuple[bool, str, Optional[dict]]:
    """POST to the initiator's /finalize endpoint. Returns (ok, error, response_json).

    §BATCH9 (2026-09-06, §BATCH7 residue): this dialed the initiator's mTLS federation gateway with NO
    client certificate and NO verification (`verify=False`), so every bilateral standup ended with a
    400 from nginx ("no required SSL certificate") and the finalize leg never landed. The endpoint
    itself authenticates by the invitation nonce, so two legs, in order: (1) the federation gateway
    presenting OUR SVID, verified against the freshest bundle — the right leg once the initiator
    trusts our root; (2) the initiator's PUBLIC registry url (the gateway url with its port stripped,
    the convention network_listings relies on) verified against public roots, no client cert — the
    leg that works BEFORE the initiator has applied the bundle this very call carries.
    """
    legs = _finalize_targets(invitation, verify_bundle_body=our_bundle_body, initiator_bundle_body=initiator_bundle_body)

    body = {
        "approver_trust_domain": _local_trust_domain(),
        "approver_bundle_endpoint_url": _local_bundle_endpoint_url(),
        "approver_name": _local_name(),
        "approver_bundle_pem": our_bundle_body,
        "nonce_echo": invitation.initiator_nonce,
    }
    if _local_federation_endpoint_url():
        body["approver_federation_endpoint_url"] = _local_federation_endpoint_url()
    if federation_license_key:
        body["federation_license_key"] = federation_license_key
    if licence_certificate:  # §FEDLICENCE: the network licence the genesis issued at this approve
        body["licence_certificate"] = licence_certificate
        body["licence_chain"] = list(licence_chain or [])
    last_err = ""
    for leg, finalize_url, client_kwargs in legs:
        try:
            async with httpx.AsyncClient(timeout=_CALLBACK_TIMEOUT_SECONDS, **client_kwargs) as client:
                r = await client.post(finalize_url, json=body)
                if 200 <= r.status_code < 300:
                    logger.info("[frame-invitations] finalize landed via %s leg: %s", leg, finalize_url)
                    try:
                        return True, "", r.json() if r.text else {}
                    except Exception:
                        return True, "", {}
                last_err = f"{leg} leg HTTP {r.status_code}: {r.text[:200]}"
                logger.warning("[frame-invitations] finalize %s", last_err)
                continue
        except Exception as e:  # noqa: BLE001
            last_err = f"{leg} leg error: {e}"
            logger.warning("[frame-invitations] finalize %s", last_err)
            continue
    return False, last_err or "finalize failed on every leg", None

@router.post(
    "/admin/federation/frame-invitations/{invitation_id}/approve",
    dependencies=[
        Depends(require_mainframe_only),
        Security(security.require_admin_flag("admin_federation")),
    ],
)
async def approve_frame_invitation(
    invitation_id: str = Path(..., min_length=1, max_length=64),
    body: FrameInvitationApproveLicensed = ...,
    db: AsyncSession = Depends(get_db),
    current_admin: models.Developer = Depends(security.get_current_developer),
) -> Dict[str, Any]:
    """Approve a pending invitation:
       1. Fetch the remote's bundle + import into our SPIRE
       2. INSERT peer_registries row for the remote frame
       3. POST bilateral callback to remote's /finalize with our bundle + nonce
       4. Flip invitation to approved (completed_at set if callback succeeds)

    Partial success: if step 3 fails after step 1+2 succeeded, invitation
    is left as status='approved' with completed_at=null; retry via
    /finalize-retry admin endpoint.
    """
    inv = (await db.execute(
        select(models.FrameInvitation).where(models.FrameInvitation.id == invitation_id)
    )).scalar_one_or_none()
    if inv is None:
        raise HTTPException(status_code=404, detail="Invitation not found.")
    _refuse_bad_namespace(inv.initiator_trust_domain, site="approve")
    if inv.status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Cannot approve invitation in status '{inv.status}'.",
        )

    # §FEDLICENCE (2026-09-28): crossing into another trust domain needs a network licence. Decided BEFORE any SPIRE
    # work, so a refusal leaves nothing half-federated. `observe` reports what `enforce` would refuse.
    _lic_mode = _fedlic.licence_mode()
    _gtd = _fedlic.genesis_trust_domain()
    _is_genesis_here = bool(_gtd) and _gtd == _fedlic.local_trust_domain()
    _plan = (body.network_licence_plan or "").strip().lower() or None
    if _plan and not _is_genesis_here:
        raise HTTPException(status_code=409, detail=("only the network's genesis issues network licences at approve "
                                                     f"(FEDERATION_GENESIS_TRUST_DOMAIN={_gtd or 'unset'})"))
    _presented = None
    if inv.initiator_licence_certificate:
        _root_row = await _fedlic.get_cert(db, "root")
        _presented = _fedlic.presented_verdict(
            inv.initiator_licence_certificate, inv.initiator_licence_chain or [],
            expect_trust_domain=inv.initiator_trust_domain, root_jws=(_root_row.jws if _root_row else None))
    _licensed_in = bool(_plan) or bool(_presented and _presented.passes)
    if not _licensed_in and _lic_mode in ("observe", "enforce"):
        _why = (f"presented licence: {_presented.state} ({_presented.reason})" if _presented
                else "no network licence presented")
        if _lic_mode == "enforce":
            raise HTTPException(status_code=403, detail=(
                f"federation licence required: {inv.initiator_trust_domain} holds no network licence this frame can "
                f"verify ({_why}). The network's genesis issues one (approve there with network_licence_plan)."))
        logger.warning("[fedlicence] WOULD REFUSE the approve of %s in enforce: %s", inv.initiator_trust_domain, _why)

    # §FEDLICENCE (agentvault2-41's review): the genesis ISSUES the network licence here, BEFORE any SPIRE work and in
    # the same uncommitted transaction, so a plan that cannot be honoured (an initiator older than V0478 sends no key,
    # or issue() refuses) is known before anything is federated. In enforce that refuses the approve; a later failure
    # of the SPIRE steps raises before the commit and the licence goes with the rolled-back transaction.
    _net_cert: Optional[str] = None
    _net_chain: List[str] = []
    _net_err: Optional[str] = None
    _net_hash: Optional[str] = None
    if _plan:
        if not inv.initiator_licence_key:
            _net_err = ("the invitation carries no licence key (an initiator older than V0478); issue the licence later "
                        "with POST /api/v1/admin/federation/licence/issue once the frame publishes its key")
        else:
            try:
                _url = (inv.initiator_federation_endpoint_url or "").strip() or None
                _nrow, _ncert = await _fedlic.issue(
                    db, type_="frame",
                    sub={"trust_domain": inv.initiator_trust_domain, "name": inv.initiator_name,
                         "url": (_url if _url and _url.startswith("https://") else None),
                         "key": inv.initiator_licence_key},
                    plan=_plan, days=body.network_licence_days, public_name=_local_name(), created_by=current_admin.id)
                _root_now = await _fedlic.get_cert(db, "root")
                _net_cert, _net_hash = _ncert.jws, _ncert.hash
                _net_chain = [_root_now.jws] if _root_now is not None else []
            except ValueError as _ne:
                _net_err = str(_ne)
        if _net_err:
            if _lic_mode == "enforce":
                raise HTTPException(status_code=409, detail=f"federation licence required and not issuable: {_net_err}")
            logger.warning("[fedlicence] network licence for %s not issued at approve: %s", inv.initiator_trust_domain,
                           _net_err)

    mgr: FrameTrustManager = get_frame_trust_manager()

    # Step 1 — fetch remote bundle
    bundle_body, content_type, fetch_err = await mgr.fetch_remote_bundle(
        inv.initiator_bundle_endpoint_url, inv.initiator_trust_domain,
    )
    if fetch_err or not bundle_body:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to fetch remote bundle: {fetch_err or 'empty body'}",
        )

    fmt = "pem" if bundle_body.lstrip().startswith("-----BEGIN") else "spiffe"
    set_result = await mgr.add_peer_bundle(inv.initiator_trust_domain, bundle_body, format_hint=fmt)
    if not set_result:
        raise HTTPException(
            status_code=502,
            detail=f"SPIRE bundle import failed: {set_result.message}",
        )
    # §FRAMEFED: the bundle is in; now every workload entry must federate with it.
    entries_federated = await _federate_entries_after_bundle(mgr, inv.initiator_trust_domain, site="approve")
    # §MONEY-R52: and the SPIRE relationship, so the imported bundle keeps refreshing.
    federation_relationship = await _federation_relationship_after_bundle(
        mgr, inv.initiator_trust_domain, inv.initiator_bundle_endpoint_url, site="approve")

    # Step 2 — insert peer_registries (or update if exists)
    now = datetime.now(timezone.utc)
    existing_peer = (await db.execute(
        select(models.PeerRegistry).where(
            models.PeerRegistry.trust_domain == inv.initiator_trust_domain,
            models.PeerRegistry.peer_type == "frame",
        )
    )).scalar_one_or_none()

    if existing_peer is None:
        peer = models.PeerRegistry(
            owner_developer_id=current_admin.id,
            name=inv.initiator_name[:255],
            description="Sovereign frame — federated via bilateral invitation",
            base_url=inv.initiator_federation_endpoint_url.rstrip("/"),
            admin_contact_email=inv.initiator_contact_email,
            status="ACTIVE",
            discovery_auth_info={},
            peer_type="frame",
            trust_domain=inv.initiator_trust_domain,
            spiffe_bundle_endpoint_url=inv.initiator_bundle_endpoint_url,
            hop_distance=1,
            last_seen_in_topology_at=now,
            approved_at=now,
            approved_by_developer_id=current_admin.id,
        )
        sf5_trust = _store_trust_value(peer)   # a new row has no record: the prior (read before the flush)
        db.add(peer)
        await db.flush()
        peer_id = peer.id
    else:
        sf5_trust = _store_trust_value(existing_peer)
        existing_peer.status = "ACTIVE"
        existing_peer.spiffe_bundle_endpoint_url = inv.initiator_bundle_endpoint_url
        # the lane this row DIALS follows the invitation: a re-federating frame may advertise a new one (measured: the
        # sandbox's row kept the compose-internal lane the first approve stored, and every pull of it failed on the name)
        if (inv.initiator_federation_endpoint_url or "").strip():
            existing_peer.base_url = inv.initiator_federation_endpoint_url.strip().rstrip("/")
        existing_peer.last_seen_in_topology_at = now
        peer_id = existing_peer.id

    # Update invitation → approved (awaiting finalize callback)
    inv.status = "approved"
    inv.reviewed_by = current_admin.id
    inv.reviewed_at = now
    inv.review_notes = body.notes or None
    inv.peer_registry_id = peer_id
    inv.spire_bundle_imported_at = now
    await _clear_card_pull_parking(inv.initiator_name, where="approve")

    # §FRAMELIC — the joining frame is licensed AT BIRTH, in the same transaction that
    # admits it. The plain key rides the /finalize callback below and is echoed to the
    # approving admin once; we only ever store its hash.
    # §HELLOFRAME Phase 3, measured: a NEW invitation from a trust domain that already holds a licence (a reprovisioned
    # frame, or one whose first callback died) got the existing id and NO plain key, so the handoff had nothing to
    # deliver. An approved invitation is a new handshake: the licence is rotated and the callback carries the new key.
    license_id, license_key, license_err = await _issue_frame_license(db, inv, current_admin.id, rotate=True)

    await db.commit()
    await db.refresh(inv)

    await _emit_event("FrameInvitationApproved", inv,
                      reviewer_developer_id=current_admin.id,
                      peer_registry_id=peer_id)
    _schedule_compliance_baseline(peer_id, "approve")

    # Step 3 — POST to remote's /finalize with OUR bundle
    # Read our own bundle from SPIRE container
    our_bundle_result = await _read_local_bundle()
    if not our_bundle_result[0]:
        # Approved locally, but can't fetch our own bundle → finalize-retry
        logger.error(f"[frame_invitations.approve] could not read local bundle: {our_bundle_result[1]}")
        return {
            "status": "approved",
            "completed": False,
            "peer_registry_id": peer_id,
            "entries_federated": entries_federated,
            "federation_relationship": federation_relationship,
            "federation_license_id": license_id,
            "federation_license_key": license_key,
            "federation_license_error": license_err,
            "warning": f"Local bundle unreadable ({our_bundle_result[1]}); use finalize-retry.",
        }

    _deliver = {"licence_certificate": _net_cert, "licence_chain": _net_chain} if _net_cert else {}
    ok, err, _resp = await _post_bilateral_finalize(inv, our_bundle_result[0], license_key, initiator_bundle_body=bundle_body,
                                                    **_deliver)
    if ok:
        inv.status = "approved"  # stays approved (status is from our side)
        inv.completed_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(inv)
        await _emit_event("FrameFederationEstablished", inv,
                          side="approver",
                          peer_registry_id=peer_id)
        logger.info(
            f"[frame_invitations.approve] completed bilateral handshake with "
            f"{inv.initiator_trust_domain} (peer_id={peer_id})"
        )
        completed = True
        warning = None
    else:
        logger.warning(
            f"[frame_invitations.approve] local steps OK but remote /finalize failed: {err}. "
            f"Use /finalize-retry for invitation {inv.id}."
        )
        completed = False
        warning = f"Remote /finalize callback failed: {err}"

    # WS3.5 — auto-wire data planes (SF-4 + SF-5) so the new frame is fully
    # operational, not just identity-layer federated. Non-fatal: failures are
    # logged and folded into the response as warnings; admin can Resync later.
    sf4_ok = False
    sf4_detail = None
    if inv.initiator_event_store_url:
        sf4 = await frame_data_plane_sync.register_cross_frame_peer(
            frame_id=inv.initiator_trust_domain,
            event_store_url=inv.initiator_event_store_url,
            added_by=f"ws3-approve:{current_admin.email}",
        )
        sf4_ok = sf4.ok
        sf4_detail = sf4.detail if not sf4.ok else None
        if not sf4_ok:
            logger.warning(f"[frame_invitations.approve] SF-4 register failed: {sf4.detail}")
    else:
        sf4_detail = "event_store_url not provided in invitation — admin can Resync after updating"

    sf5 = await frame_data_plane_sync.register_federation_operator(
        spiffe_id=f"spiffe://{inv.initiator_trust_domain}",
        operator_name=inv.initiator_name,
        bayesian_discount=sf5_trust,  # SEC-20: derived from the peer row's record (a new peer: the prior, 0.5)
    )
    sf5_ok = sf5.ok
    sf5_detail = sf5.detail if not sf5.ok else None
    if not sf5_ok:
        logger.warning(f"[frame_invitations.approve] SF-5 register failed: {sf5.detail}")

    # Email notifications
    if inv.initiator_contact_email:
        _send_themed_email_fnf(
            subject=f"Frame Federation Approved — {_local_name()}",
            template="frame_federation_approved",
            context={
                **__import__("agentvault_registry.core.release_channel", fromlist=["mail_context"]).mail_context(),
                "local_name": _local_name(),
                "initiator_trust_domain": inv.initiator_trust_domain,
                "local_trust_domain": _local_trust_domain(),
                "local_bundle_endpoint": _local_bundle_endpoint_url(),
                "invitation_id": inv.id,
                "completed": completed,
                "notes": body.notes,
            },
            theme="neural",
            to_address=inv.initiator_contact_email,
        )
    admin_addr = _admin_notification_email()
    if admin_addr and admin_addr != inv.initiator_contact_email:
        _send_themed_email_fnf(
            subject=f"[ADMIN] Frame approved: {inv.initiator_trust_domain}",
            template="admin_notice",
            context={
                "kicker_label": "FRAME APPROVED",
                "headline_text": f"Frame Approved — {inv.initiator_trust_domain}",
                "rows": [
                    ("Approver", current_admin.email),
                    ("Invitation", inv.id),
                    ("Trust domain", inv.initiator_trust_domain),
                    ("Peer ID", str(peer_id)),
                    ("Completed", str(completed)),
                ],
                "notice_text": (warning or None),
            },
            theme="neural",
            to_address=admin_addr,
        )

    return {
        "status": "approved",
        "completed": completed,
        "peer_registry_id": peer_id,
        "entries_federated": entries_federated,
        "federation_relationship": federation_relationship,
        # §FRAMELIC — shown ONCE. If the /finalize callback landed, the peer already has it;
        # this copy is for the admin's own record (and for a manual seed if it did not).
        "federation_license_id": license_id,
        "federation_license_key": license_key,
        "federation_license_error": license_err,
        # §FEDLICENCE: the network licence issued here (genesis only) and the verdict about the one presented
        "network_licence": {"issued_hash": _net_hash, "plan": _plan, "error": _net_err,
                            "installed_by_peer": ((_resp or {}).get("licence_install") if isinstance(_resp, dict) else None)},
        "presented_licence": (_presented.as_dict() if _presented else None),
        "licence_mode": _lic_mode,
        "warning": warning,
        # WS3.5 data-plane auto-wire results
        "sf4_registered": sf4_ok,
        "sf5_registered": sf5_ok,
        "sf4_detail": sf4_detail,
        "sf5_detail": sf5_detail,
    }


async def _read_local_bundle() -> tuple[Optional[str], str]:
    """Read our own SPIRE server's trust bundle as SPIFFE JWK set (JSON).

    Returns (body, error). On success, error is empty string. By the trust manager's route (FRAME_TRUST_SPIRE_VIA),
    so a frame whose SPIRE work goes through the frame runner reads its own bundle there too (§F6 WP6.1).
    """
    return await get_frame_trust_manager().read_own_bundle("spiffe")


# ---------------------------------------------------------------------------
# Admin: reject
# ---------------------------------------------------------------------------

@router.post(
    "/admin/federation/frame-invitations/{invitation_id}/reject",
    dependencies=[
        Depends(require_mainframe_only),
        Security(security.require_admin_flag("admin_federation")),
    ],
)
async def reject_frame_invitation(
    invitation_id: str = Path(..., min_length=1, max_length=64),
    body: FrameInvitationReject = ...,
    db: AsyncSession = Depends(get_db),
    current_admin: models.Developer = Depends(security.get_current_developer),
) -> Dict[str, Any]:
    inv = (await db.execute(
        select(models.FrameInvitation).where(models.FrameInvitation.id == invitation_id)
    )).scalar_one_or_none()
    if inv is None:
        raise HTTPException(status_code=404, detail="Invitation not found.")
    if inv.status != "pending":
        raise HTTPException(status_code=409, detail=f"Cannot reject from status '{inv.status}'.")

    now = datetime.now(timezone.utc)
    inv.status = "rejected"
    inv.reviewed_by = current_admin.id
    inv.reviewed_at = now
    inv.rejection_reason = body.reason

    await db.commit()
    await db.refresh(inv)

    await _emit_event("FrameInvitationRejected", inv,
                      reviewer_developer_id=current_admin.id,
                      reason=body.reason)

    if inv.initiator_contact_email:
        _send_themed_email_fnf(
            subject=f"Frame Federation Invitation Declined — {_local_name()}",
            template="frame_federation_rejected",
            context={
                "local_name": _local_name(),
                "invitation_id": inv.id,
                "trust_domain": inv.initiator_trust_domain,
                "reason": body.reason,
            },
            theme="sovereign",
            to_address=inv.initiator_contact_email,
        )

    return {"status": "rejected"}


# ---------------------------------------------------------------------------
# Admin: finalize-retry (re-attempt bilateral callback after partial failure)
# ---------------------------------------------------------------------------

@router.post(
    "/admin/federation/frame-invitations/{invitation_id}/finalize-retry",
    dependencies=[
        Depends(require_mainframe_only),
        Security(security.require_admin_flag("admin_federation")),
    ],
)
async def finalize_retry_frame_invitation(
    invitation_id: str = Path(..., min_length=1, max_length=64),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    inv = (await db.execute(
        select(models.FrameInvitation).where(models.FrameInvitation.id == invitation_id)
    )).scalar_one_or_none()
    if inv is None:
        raise HTTPException(status_code=404, detail="Invitation not found.")
    if inv.status != "approved" or inv.completed_at is not None:
        raise HTTPException(
            status_code=409,
            detail=f"finalize-retry only applies to status='approved' with completed_at=null "
                   f"(current: status='{inv.status}', completed_at={inv.completed_at}).",
        )

    bundle_body, err = await _read_local_bundle()
    if not bundle_body:
        raise HTTPException(status_code=502, detail=f"Local bundle read failed: {err}")

    # §HELLOFRAME (2026-09-18): the first callback carried the licence key and never landed, and a key is stored only
    # as its hash, so a retry that re-posts without one leaves the joining frame licensed on our books and keyless on
    # its own (Phase 1 surprise 10). The retry ROTATES the licence: a new key rides this callback, the old one (never
    # delivered, never used) is gone.
    license_id, license_key, license_err = await _issue_frame_license(db, inv, actor_id=0, rotate=True)
    if license_err:
        logger.warning("[frame_invitations.finalize-retry] licence rotation for %s failed: %s", inv.initiator_trust_domain, license_err)
    await db.commit()

    # §FEDLICENCE: re-deliver the network licence this genesis issued to that trust domain (the newest live one)
    _rc: Optional[str] = None
    _rch: List[str] = []
    try:
        _issued = [r for r in await _fedlic.get_certs(db, "issued")
                   if r.type == "frame" and r.sub_trust_domain == inv.initiator_trust_domain and r.state == "active"]
        _rt = await _fedlic.get_cert(db, "root")
        if _issued and _rt is not None:
            _rc, _rch = _issued[0].jws, [_rt.jws]
    except Exception as _re:  # noqa: BLE001
        logger.warning("[fedlicence] finalize-retry could not read the issued licence: %s", _re)
    ok, err, _resp = await _post_bilateral_finalize(inv, bundle_body, license_key,
                                                    **({"licence_certificate": _rc, "licence_chain": _rch} if _rc else {}))
    if not ok:
        raise HTTPException(status_code=502, detail=f"Remote finalize still failing: {err}")

    inv.completed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(inv)

    await _emit_event("FrameFederationEstablished", inv,
                      side="approver",
                      retry=True,
                      peer_registry_id=inv.peer_registry_id)

    return {"status": "approved", "completed": True, "peer_registry_id": inv.peer_registry_id,
            "federation_license_id": license_id, "federation_license_rotated": bool(license_key),
            "federation_license_error": license_err}


# ---------------------------------------------------------------------------
# Admin: revoke (tear down an established frame federation)
# ---------------------------------------------------------------------------

async def revoke_spire_federation(mgr, trust_domain: str):
    """§F6 WP6.2: (relationship result, bundle result) for ending a frame federation in this frame's SPIRE server.

    The RELATIONSHIP goes first. While it stands, the server's refresher asks the peer's bundle endpoint for its bundle,
    so a bundle deleted before it could be imported again in between; with it gone, nothing brings the bundle back.
    Before this, a revoke deleted only the bundle and left the relationship on both sides (the WP6.1 proof, measured on
    the throwaway f6proof and sbx-beta). The bundle is deleted even when the relationship delete failed: each half is
    reported on its own, and the peer row is flipped either way (the caller's rule)."""
    relationship = await mgr.delete_federation_relationship(trust_domain)
    bundle = await mgr.remove_peer_bundle(trust_domain)
    return relationship, bundle


@router.post(
    "/admin/federation/frames/{peer_id}/revoke",
    dependencies=[
        Depends(require_mainframe_only),
        Security(security.require_admin_flag("admin_federation")),
    ],
)
async def revoke_frame_federation(
    peer_id: int = Path(..., ge=1),
    body: FrameFederationRevoke = ...,
    db: AsyncSession = Depends(get_db),
    current_admin: models.Developer = Depends(security.get_current_developer),
) -> Dict[str, Any]:
    peer = (await db.execute(
        select(models.PeerRegistry).where(models.PeerRegistry.id == peer_id)
    )).scalar_one_or_none()
    if peer is None:
        raise HTTPException(status_code=404, detail="Peer not found.")
    if peer.peer_type != "frame":
        raise HTTPException(status_code=422, detail=f"Peer {peer_id} is not a frame (peer_type={peer.peer_type}).")
    if (peer.status or "").upper() != "ACTIVE":
        raise HTTPException(status_code=409, detail=f"Peer is already {peer.status}.")

    # End the federation in SPIRE: the relationship first, then the bundle (see revoke_spire_federation).
    # Non-fatal: if either was never there, we still flip the peer row.
    relationship, result = await revoke_spire_federation(get_frame_trust_manager(), peer.trust_domain or "")
    logger.info(f"[frame_invitations.revoke] SPIRE relationship remove result: ok={relationship.ok} msg={relationship.message}")
    logger.info(f"[frame_invitations.revoke] SPIRE bundle remove result: ok={result.ok} msg={result.message}")

    now = datetime.now(timezone.utc)
    peer.status = "INACTIVE"
    peer.deactivated_reason = "frame_revoked"  # guard-set: never auto-revived
    peer.deactivated_at = now

    # Update linked invitation record (if any)
    inv = (await db.execute(
        select(models.FrameInvitation).where(models.FrameInvitation.peer_registry_id == peer_id)
        .order_by(models.FrameInvitation.completed_at.desc().nullslast())
    )).scalars().first()
    if inv is not None and inv.status in ("approved", "completed"):
        inv.status = "revoked"
        inv.revoked_by = current_admin.id
        inv.revoked_at = now
        inv.revoked_reason = body.reason

    await db.commit()

    # Events
    try:
        emitter = get_event_emitter()
        await emitter.emit(
            event_type="FrameFederationRevoked",
            aggregate_id=f"peer_registry:{peer_id}",
            aggregate_type="PeerRegistry",
            data={
                "peer_id": peer_id,
                "peer_name": peer.name,
                "trust_domain": peer.trust_domain,
                "invitation_id": inv.id if inv else None,
                "actor_developer_id": current_admin.id,
                "actor_email": current_admin.email,
                "reason": body.reason,
                "spire_bundle_remove_ok": result.ok,
                "spire_relationship_remove_ok": relationship.ok,
                "revoked_at": now.isoformat(),
            },
        )
        # Also emit PeerRegistryDeactivated to match the operator lifecycle pattern. Since 2026-10-21 a federated
        # frame is a TEG partner (reactor_frame_federation_established registers it at the handshake), so the
        # event names the partner the revoke releases, teg-<safe name>, and the Phase 1 reactor removes it; None
        # when another ACTIVE row names the same partner (crud_peer_registry._released_partner_teg_id).
        from ..crud.crud_peer_registry import _released_partner_teg_id
        try:
            released_teg_id = await _released_partner_teg_id(db, peer)
        except Exception as exc:  # the lookup failing must not stop the revoke's events
            logger.warning(f"[frame_invitations.revoke] partner lookup failed for peer={peer_id}: {exc}")
            released_teg_id = None
        await emitter.emit(
            event_type="PeerRegistryDeactivated",
            aggregate_id=f"peer_registry:{peer_id}",
            aggregate_type="PeerRegistry",
            data={
                "peer_id": peer_id,
                "peer_name": peer.name,
                "trust_domain": peer.trust_domain,
                "trigger": "frame_federation_revoke",
                "teg_id": released_teg_id,
                "actor_developer_id": current_admin.id,
                "reason": body.reason,
                "deactivated_at": now.isoformat(),
            },
        )
    except Exception as exc:
        logger.warning(f"[frame_invitations.revoke] event emit failed: {exc}")

    # WS3.5: teardown on data planes too (SF-4 cross-frame peer + SF-5 federation operator)
    sf4_teardown = await frame_data_plane_sync.suspend_cross_frame_peer(peer.trust_domain or "")
    sf5_teardown = await frame_data_plane_sync.suspend_federation_operator_by_spiffe(
        f"spiffe://{peer.trust_domain}" if peer.trust_domain else ""
    )
    if not sf4_teardown.ok:
        logger.warning(f"[frame_invitations.revoke] SF-4 suspend failed: {sf4_teardown.detail}")
    if not sf5_teardown.ok:
        logger.warning(f"[frame_invitations.revoke] SF-5 suspend failed: {sf5_teardown.detail}")

    if peer.admin_contact_email:
        _send_themed_email_fnf(
            subject=f"Frame Federation Revoked — {_local_name()}",
            template="frame_federation_revoked",
            context={
                "local_name": _local_name(),
                "trust_domain": peer.trust_domain,
                "reason": body.reason,
            },
            theme="sovereign",
            to_address=peer.admin_contact_email,
        )

    return {
        "status": "revoked",
        "peer_id": peer_id,
        "trust_domain": peer.trust_domain,
        "spire_bundle_remove_ok": result.ok,
        "spire_relationship_remove_ok": relationship.ok,
        "sf4_suspended": sf4_teardown.ok,
        "sf5_suspended": sf5_teardown.ok,
    }


# ---------------------------------------------------------------------------
# Admin: resync-eventstore (gap-closure for legacy frames + retry handle)
# ---------------------------------------------------------------------------

@router.post(
    "/admin/federation/frames/{peer_id}/resync-eventstore",
    dependencies=[
        Depends(require_mainframe_only),
        Security(security.require_admin_flag("admin_federation")),
    ],
)
async def resync_frame_eventstore(
    peer_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_db),
    current_admin: models.Developer = Depends(security.get_current_developer),
) -> Dict[str, Any]:
    """Re-register a frame peer with the EventStore data planes (SF-4 + SF-5).

    Idempotent UPSERTs on both sides. Used for:
      - legacy frames (Frame-B) that pre-date WS3.5's auto-wiring
      - approve flows where auto-register failed and admin is retrying
      - changing the EventStore URL of an already-federated frame
    """
    peer = (await db.execute(
        select(models.PeerRegistry).where(models.PeerRegistry.id == peer_id)
    )).scalar_one_or_none()
    if peer is None:
        raise HTTPException(404, "Peer not found")
    if peer.peer_type != "frame":
        raise HTTPException(422, f"Peer {peer_id} is not a frame (peer_type={peer.peer_type})")
    if not peer.trust_domain:
        raise HTTPException(422, "Peer has no trust_domain — cannot resync")

    # Resolve EventStore URL — prefer the invitation's stored hint; fall back
    # to convention: https://events-<subdomain>:8201 (Frame-B uses events-b.theprotocol.cloud)
    # D6-112 (2026-10-17): only an invitation the peer SENT names the peer's store. On the frame that joined, the
    # invitation linked to the peer is its own outbound one, whose initiator_event_store_url is this frame's OWN store,
    # and resync registered that as the peer's. The joining side holds no hint for the approver's store (finalize does
    # not carry it), so it takes the convention, and the answer says which source it used.
    inv = (await db.execute(
        select(models.FrameInvitation).where(
            models.FrameInvitation.peer_registry_id == peer_id,
            models.FrameInvitation.initiator_trust_domain == peer.trust_domain,
        )
        .order_by(models.FrameInvitation.completed_at.desc().nullslast())
    )).scalars().first()

    event_store_url = inv.initiator_event_store_url if inv else None
    event_store_url_source = "invitation" if event_store_url else "convention"
    if not event_store_url:
        # Legacy Frame-B convention: events-<tld-first-label>.<rest>
        # e.g., frame-b.theprotocol.cloud → events-b.theprotocol.cloud
        td = peer.trust_domain
        parts = td.split(".", 1)
        if len(parts) == 2 and parts[0].startswith("frame-"):
            subdomain_label = parts[0].replace("frame-", "events-")
            event_store_url = f"https://{subdomain_label}.{parts[1]}:8201"
        else:
            event_store_url = f"https://events-{td}:8201"

    sf4 = await frame_data_plane_sync.register_cross_frame_peer(
        frame_id=peer.trust_domain,
        event_store_url=event_store_url,
        added_by=f"resync:{current_admin.email}",
    )
    sf5 = await frame_data_plane_sync.register_federation_operator(
        spiffe_id=f"spiffe://{peer.trust_domain}",
        operator_name=peer.name,
        bayesian_discount=_store_trust_value(peer),  # SEC-20: derived from the peer's record, never reset to the prior
    )

    logger.info(
        f"[frame_invitations.resync] peer_id={peer_id} td={peer.trust_domain} "
        f"sf4={sf4.ok} sf5={sf5.ok}"
    )
    return {
        "peer_id": peer_id,
        "trust_domain": peer.trust_domain,
        "event_store_url": event_store_url,
        "event_store_url_source": event_store_url_source,
        "sf4_registered": sf4.ok,
        "sf4_detail": sf4.detail,
        "sf5_registered": sf5.ok,
        "sf5_detail": sf5.detail,
    }


# ---------------------------------------------------------------------------
# Admin: read-only data-plane diagnostics (SF-4/5 + SPIRE live state)
# ---------------------------------------------------------------------------

@router.get(
    "/admin/federation/frames/spire-status",
    dependencies=[
        Depends(require_mainframe_only),
        Security(security.require_admin_flag("admin_federation")),
    ],
)
async def spire_trust_bundle_status(
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Live SPIRE bundle state vs DB diff.

    Calls `spire-server bundle list` inside the SPIRE container and compares
    against the `peer_registries` frame rows. Returns:
      - `in_spire_only`   — SPIRE has a bundle but no peer_registries row (orphan)
      - `in_db_only`      — peer_registries has a frame but no SPIRE bundle (missing import)
      - `in_both`         — healthy
    """
    mgr = get_frame_trust_manager()
    spire_domains, err = await mgr.list_federated_trust_domains()

    frame_rows = (await db.execute(
        select(models.PeerRegistry).where(models.PeerRegistry.peer_type == "frame")
    )).scalars().all()
    db_domains_active = {(p.trust_domain or "").lower() for p in frame_rows if (p.status or "").upper() == "ACTIVE"}
    db_domains_all = {(p.trust_domain or "").lower() for p in frame_rows}

    spire_set = set(spire_domains)
    in_both = sorted(spire_set & db_domains_active)
    in_spire_only = sorted(spire_set - db_domains_all)
    in_db_only = sorted(db_domains_active - spire_set)

    return {
        "spire_trust_domains": sorted(spire_set),
        "spire_error": err,
        "in_both": in_both,
        "in_spire_only": in_spire_only,   # orphaned SPIRE bundles (possible cleanup target)
        "in_db_only": in_db_only,         # frames that need bundle-set (action: Resync)
        "local_trust_domain": mgr.local_trust_domain,
    }


@router.get(
    "/admin/eventstore/cross-frame-peers",
    dependencies=[
        Depends(require_mainframe_only),
        Security(security.require_admin_flag("admin_federation")),
    ],
)
async def proxy_list_cross_frame_peers() -> Dict[str, Any]:
    """Proxy to EventStore's SF-4 admin — surfaces the replicator's current
    peer list (with watermarks) to the FrameManagement UI."""
    ok, detail, body = await frame_data_plane_sync.list_cross_frame_peers(status="all")
    if not ok:
        raise HTTPException(502, f"EventStore query failed: {detail}")
    return body or {"peers": [], "count": 0}


@router.get(
    "/admin/eventstore/federation-operators",
    dependencies=[
        Depends(require_mainframe_only),
        Security(security.require_admin_flag("admin_federation")),
    ],
)
async def proxy_list_federation_operators() -> Dict[str, Any]:
    """Proxy to EventStore's SF-5 admin — surfaces federation_operators rows
    (with bayesian_discount) to the FrameManagement UI."""
    ok, detail, body = await frame_data_plane_sync.list_federation_operators()
    if not ok:
        raise HTTPException(502, f"EventStore query failed: {detail}")
    return body or {"operators": [], "count": 0}
