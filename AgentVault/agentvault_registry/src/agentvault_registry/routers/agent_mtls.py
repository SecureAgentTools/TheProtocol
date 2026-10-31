"""
f052: Agent mTLS Enrollment + Monitoring Endpoints (IRONHAND)

Routes:
  POST /api/v1/agent/enable-mtls            — Enroll agent for mTLS
  POST /api/v1/agent/disable-mtls           — Unenroll agent from mTLS
  GET  /api/v1/agent/mtls-status            — Check enrollment status
  GET  /api/v1/agent/revoked-identities     — Revoked SPIFFE IDs (SDK polling)
  GET  /api/v1/admin/ironhand/identities    — Full monitoring view (admin)
"""
import asyncio
import ipaddress
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Security
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry import models
from agentvault_registry import security
from agentvault_registry.database import get_db
from agentvault_registry.security import get_current_agent, require_agent_permission
from agentvault_registry.services.agent_spire import (
    register_agent_spire_entry,
    SpireParentUnresolved,
    delete_agent_spire_entry,
    check_agent_spire_entry,
    sanitize_did_for_spiffe,
    local_container_exists_for_agent,
    mint_agent_svid,
    _build_spiffe_id,
    _parent_fingerprint_for_self,
)
from agentvault_registry.services.spire_ops_client import SpireOpsUnavailable
from agentvault_registry.core.federation_auth import require_peer_registry_identity

# RP3 (2026-07-24 wiring audit): revoked-SVID reconstruction must use THIS frame's trust
# domain, not a hardcoded agentvault.com — on Frame-B/C the polling blocklist otherwise
# never matches the real revoked SVID (only the real-time WS path worked there).
_LOCAL_TRUST_DOMAIN = os.getenv("SPIRE_TRUST_DOMAIN", "agentvault.com")

logger = logging.getLogger(__name__)


# ── §EXTMTLS (2026-08-09) — deployment detection for enable-mtls ──────────────
# enable-mtls has always assumed the enrolling agent runs as a LABELLED
# CONTAINER ON THIS HOST: the SPIRE entry it creates carries a `docker:label:`
# selector parented to our own spire-agent, and the certificate is fetched over
# the SPIFFE Workload API socket. An agent on a developer's own machine can
# satisfy neither condition, so it used to enroll "successfully" and then never
# be able to obtain a certificate — while its agent card was patched to
# advertise mTLS it could not terminate. The same endpoint now detects that
# case and adapts what it hands back. On-box behaviour is unchanged.
def _inline_svid_enabled() -> bool:
    """Master gate for handing an agent its key material over HTTPS."""
    return os.getenv("IRONHAND_INLINE_SVID_ENABLED", "false").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _inline_svid_ttl() -> int:
    """Inline SVID lifetime, clamped to [60s, 1h]. Minutes, not hours: a minted
    key cannot be recalled, so expiry IS the revocation mechanism."""
    try:
        ttl = int(os.getenv("IRONHAND_INLINE_SVID_TTL_SECONDS", "1800"))
    except ValueError:
        ttl = 1800
    return max(60, min(ttl, 3600))


def _spire_public_address() -> str:
    return os.getenv("SPIRE_PUBLIC_ADDRESS", "spire.theprotocol.cloud:8444")


# V0650 (j): the on-box answer names what an agent's container needs, read from this registry rather than assumed. The
# socket path follows the registry's own SPIFFE_ENDPOINT_SOCKET (svid_client rewrites it to unix:/p at boot, so all
# three spellings are read); the volume is the one this registry itself mounts at that directory, read from
# /proc/self/mountinfo, where a named volume's root is <docker root>/volumes/<name>/_data (the registry and the frame's
# SPIRE agent mount the same volume). A name that cannot be read is said, never invented: "spire-agent-socket" was Frame
# A's compose KEY, not the volume's name anywhere, and no template-born frame had a volume of that name at all.
_DEFAULT_WORKLOAD_SOCKET = "/opt/spire/sockets/agent.sock"
_VOLUME_ROOT_RE = re.compile(r"(?:^|/)volumes/([A-Za-z0-9][A-Za-z0-9_.-]*)/_data$")


def _workload_socket_path() -> str:
    raw = (os.getenv("SPIFFE_ENDPOINT_SOCKET") or "").strip()
    for prefix in ("unix://", "unix:"):
        if raw.startswith(prefix):
            raw = raw[len(prefix):]
            break
    return raw if raw.startswith("/") else _DEFAULT_WORKLOAD_SOCKET


def _read_mountinfo() -> str:
    try:
        with open("/proc/self/mountinfo", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def _socket_volume(mount_dir: str, text: Optional[str] = None) -> Optional[str]:
    """The docker volume mounted at `mount_dir` in this container, or None (no such mount, or a host-path bind). The
    LAST line for the mount point wins: a later mount shadows an earlier one there."""
    body = _read_mountinfo() if text is None else text
    found: Optional[str] = None
    for line in body.splitlines():
        fields = line.split()
        if len(fields) >= 5 and fields[4] == mount_dir:
            m = _VOLUME_ROOT_RE.search(fields[3])
            found = m.group(1) if m else None
    return found


def _effective_client_ip(request: Optional[Request]) -> Optional[str]:
    """The peer address our own edge observed.

    nginx sets `X-Forwarded-For $proxy_add_x_forwarded_for`, which APPENDS the
    real peer to whatever the client sent — so the LAST element is the one our
    edge wrote and the only one a caller cannot forge. Taking the first element
    (the usual idiom) would let anyone claim an internal address.
    """
    if request is None:
        return None
    xff = (request.headers.get("x-forwarded-for") or "").strip()
    if xff:
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if parts:
            return parts[-1]
    real = (request.headers.get("x-real-ip") or "").strip()
    if real:
        return real
    return request.client.host if request.client else None


def _attach_delivery(
    response: dict,
    request: Optional[Request],
    agent_did: str,
    sanitized: str,
    premint: Optional[dict] = None,
    deployment: Optional[str] = None,
    signal: Optional[str] = None,
) -> dict:
    """Decide and attach how this caller actually receives its certificate.

    Shared by the fresh-enrollment and already-enrolled paths: an external
    agent's SVID is short-lived by design, so re-calling enable-mtls IS the
    rotation mechanism and must return new material rather than an
    'already enrolled, nothing for you' acknowledgement.

    ``premint``/``deployment``/``signal`` let the fresh-enrollment path pass in
    the certificate it already obtained BEFORE writing state (§EXTMTLS-C), so
    the agent is never charged a second mint and detection runs exactly once.
    """
    if deployment is None or signal is None:
        deployment, signal = _detect_deployment(request, agent_did)
    response["deployment"] = deployment
    response["deployment_signal"] = signal
    if deployment != "onbox":
        # §EXTTEST (the dev machine's V0649 re-check): the label names a container on THIS registry's host, the one SPIRE's
        # docker attestor matches; an agent running elsewhere has no such container, so its answer carries no label. The
        # on-host answer keeps it, beside the instructions that use it.
        response.pop("docker_label", None)

    if deployment == "onbox":
        socket_path = _workload_socket_path()
        mount_dir = os.path.dirname(socket_path) or "/"
        volume = _socket_volume(mount_dir)
        label = f"com.theprotocol.agent-did={sanitized}"
        response["delivery"] = "workload_api"
        response["socket_volume"] = volume
        response["socket_path"] = socket_path
        response.setdefault("docker_label", f"com.theprotocol.agent-did:{sanitized}")
        where = (f"this frame's SPIRE agent socket volume {volume}" if volume else
                 f"the volume this frame's SPIRE agent mounts at {mount_dir} (this registry could not read its name; "
                 f"docker inspect of the frame's spire-agent container lists it under Mounts)")
        response["instructions"] = (
            f"Run your agent as a container on this registry's host with the Docker label {label} and {where} "
            f"mounted at {mount_dir}: docker run --label {label} -v {volume or '<that volume>'}:{mount_dir}:ro ... "
            f"The SPIRE agent's Workload API socket is then {socket_path} "
            f"(SPIFFE_ENDPOINT_SOCKET=unix://{socket_path}); a SPIFFE Workload API client "
            f"(pyspiffe WorkloadApiClient) fetches your SVID there and the SPIRE agent renews it."
        )
        return response

    if not _inline_svid_enabled():
        logger.info(
            f"[IRONHAND] External enrollment, inline delivery disabled: "
            f"{agent_did} (signal={signal})"
        )
        response["delivery"] = "unavailable"
        response["instructions"] = (
            "This agent is not running on this registry's host, so it cannot reach "
            "the SPIFFE Workload API socket the on-host path depends on, and inline "
            "certificate delivery is disabled on this registry "
            "(IRONHAND_INLINE_SVID_ENABLED). Your SPIFFE ID is reserved but no "
            "certificate has been issued: agent-to-agent calls continue to "
            "authenticate with your agent JWT and payment tokens, which is the "
            "supported path today. To run a self-rotating identity on your own "
            "host, attest a SPIRE agent by x509 proof-of-possession against "
            f"{_spire_public_address()} — the same mechanism cloud operators use."
        )
        return response

    ttl = _inline_svid_ttl()
    try:
        minted = premint if premint is not None else mint_agent_svid(agent_did, ttl_seconds=ttl)
    except RuntimeError as e:
        # Enrollment state already committed; say plainly that the credential
        # did not arrive rather than implying a working identity.
        logger.error(f"[IRONHAND] Inline SVID mint failed for {agent_did}: {e}")
        response["delivery"] = "mint_failed"
        response["error"] = str(e)[:200]
        response["instructions"] = (
            "Enrollment is recorded but issuing the certificate failed on this "
            "registry; no certificate was issued. Retry, or fall back to "
            "agent-JWT authentication."
        )
        return response

    logger.info(
        f"[IRONHAND] Inline SVID issued: agent={agent_did} "
        f"spiffe={minted['spiffe_id']} ttl={minted['ttl_seconds']}s "
        f"peer={_effective_client_ip(request)}"
    )
    response["delivery"] = "inline"
    response["svid"] = {
        "spiffe_id": minted["spiffe_id"],
        "svid_pem": minted["svid_pem"],
        "key_pem": minted["key_pem"],
        "bundle_pem": minted["bundle_pem"],
        "ttl_seconds": minted["ttl_seconds"],
        "ttl_capped_by_ca": minted["ttl_capped_by_ca"],
        # Prefer the certificate's own notAfter; fall back to arithmetic only if
        # the leaf could not be parsed (the proxy path from an older peer).
        "expires_at": minted.get("expires_at") or (
            datetime.now(timezone.utc) + timedelta(seconds=minted["ttl_seconds"])
        ).isoformat(),
    }
    response["instructions"] = (
        "Write svid_pem, key_pem and bundle_pem to svid.pem, key.pem and "
        "bundle.pem in one directory, then point the SDK at it: "
        "MtlsAgentClient(cert_dir='/path'). The private key is returned exactly "
        "once and is deliberately short-lived — call this endpoint again before "
        "expires_at to rotate."
    )
    return response


def _runner_unavailable_detail(e: Exception) -> str:
    """The sentence for an enrollment the frame runner did not serve (§EXTTEST run 2): a kit frame issues agent
    certificates through its runner (IRONHAND_SPIRE_MODE=runner), which frame-up installs only with --with-runner."""
    return (f"Agent certificates on this frame are issued through its frame runner, which did not serve this "
            f"request ({str(e)[:200]}). A frame stood up from the kit issues agent certificates only with the "
            f"runner (frame-up.py --with-runner); agent-to-agent calls keep working with agent JWTs meanwhile. How "
            f"mTLS identities are issued: https://docs.theprotocol.cloud/learn/security")


def _detect_deployment(request: Optional[Request], agent_did: str) -> tuple[str, str]:
    """Decide whether the enrolling agent can reach our Workload API.

    Returns (deployment, signal) where deployment is "onbox" or "external".
    This is a DELIVERY decision, never an authorization one — the agent JWT,
    active status and identity.mtls permission are what actually gate this
    endpoint, so a caller that mis-signals gains nothing.
    """
    if local_container_exists_for_agent(agent_did):
        return "onbox", "labelled_container_present"
    ip = _effective_client_ip(request)
    if ip:
        try:
            addr = ipaddress.ip_address(ip)
            # LOOPBACK IS NOT EVIDENCE OF ON-BOX. An agent container cannot reach
            # this registry over loopback — inside its own container, localhost is
            # itself. A loopback peer therefore means the registry called ITSELF
            # through an internal layer (the MCP tool dispatch posts to
            # REGISTRY_SELF_URL=http://localhost:8000, and MCPAuthContext carries
            # no originating IP), so the real client is unknown. Measured: an
            # enrollment driven from an off-site MCP client arrived as 127.0.0.1
            # and was misreported as on-box, which handed a genuinely external
            # agent socket instructions it could never use. Unknown resolves to
            # external — the caller then gets a credential that works either way.
            if addr.is_loopback:
                return "external", "indeterminate_via_loopback_proxy"
            if addr.is_private:
                return "onbox", "internal_network_source"
        except ValueError:
            pass
    return "external", "public_network_source"


router = APIRouter(prefix="/api/v1/agent", tags=["Agent mTLS (IRONHAND)"])
admin_router = APIRouter(prefix="/api/v1/admin/ironhand", tags=["IRONHAND Monitoring (Admin)"])

# ── Prometheus metrics ────────────────────────────────────────
try:
    from prometheus_client import Gauge
    # multiprocess_mode='livemostrecent' — under uvicorn --workers 40 any worker's
    # latest write wins; dead workers are ignored. Required for honest values on
    # /metrics scrapes in multiproc mode.
    IRONHAND_ENROLLED = Gauge("ironhand_enrolled_agents", "Agents enrolled for mTLS", multiprocess_mode='livemostrecent')
    IRONHAND_REVOKED = Gauge("ironhand_revoked_agents", "Agents with revoked mTLS", multiprocess_mode='livemostrecent')
    IRONHAND_SPIRE_ENTRIES = Gauge("ironhand_spire_agent_entries", "SPIRE agent entries", multiprocess_mode='livemostrecent')
    IRONHAND_ORPHANS = Gauge("ironhand_orphan_entries", "SPIRE entries with no DB match", multiprocess_mode='livemostrecent')
    IRONHAND_MISSING = Gauge("ironhand_missing_entries", "DB enrolled but SPIRE entry missing", multiprocess_mode='livemostrecent')
    _PROM_AVAILABLE = True
except ImportError:
    _PROM_AVAILABLE = False


@router.post(
    "/enable-mtls",
    summary="Enroll agent for mTLS identity",
)
async def enable_mtls(
    request: Request,
    # IRONKEY (S7, 2026-07-24): identity.mtls existed in the taxonomy but was never checked —
    # this is its enforcement point. Byte-inert where AGENT_RBAC_MODE=off; legacy-full carries it.
    current_agent: models.Agent = Security(require_agent_permission("identity.mtls")),
    db: AsyncSession = Depends(get_db),
):
    """
    Enroll the authenticated agent for mTLS identity.

    Creates a SPIRE workload entry so the agent's container can fetch an
    X.509 SVID. On the registry's own host the agent container must:
    1. Mount the frame's SPIRE agent socket volume (named in `socket_volume`) at the socket's directory
    2. Have Docker label: com.theprotocol.agent-did={sanitized_did}
    3. Fetch the SVID from the Workload API socket (`socket_path`, /opt/spire/sockets/agent.sock by default)
       with a SPIFFE Workload API client (pyspiffe WorkloadApiClient)

    Returns the SPIFFE ID and enrollment instructions.
    """
    # D6-802 (2026-10-17): an administrator's revoke stands until an administrator enrolls the agent again
    # (POST /api/v1/admin/ironhand/enroll/{did} or /api/v1/admin/agents/{did}/force-mtls-enrol). Asked first, so a
    # revoked agent is neither enrolled nor issued a rotation certificate here.
    if getattr(current_agent, "mtls_revoked_at", None) is not None:
        raise HTTPException(
            status_code=403,
            detail=("An administrator revoked this agent's mTLS identity; only an administrator can enroll it again."),
        )

    # Check if already enrolled
    if current_agent.mtls_enabled and current_agent.spiffe_id:
        # Verify SPIRE entry still exists
        entry_id = check_agent_spire_entry(current_agent.did)
        if entry_id:
            # §EXTMTLS — an inline SVID is short-lived ON PURPOSE, so calling
            # this endpoint again is how an external agent ROTATES. Returning a
            # bare "already enrolled" here would strand it at expiry.
            return _attach_delivery(
                {
                    "status": "already_enrolled",
                    "spiffe_id": current_agent.spiffe_id,
                    "enrolled_at": current_agent.mtls_enrolled_at.isoformat() if current_agent.mtls_enrolled_at else None,
                    "message": "Agent is already enrolled for mTLS.",
                },
                request,
                current_agent.did,
                sanitize_did_for_spiffe(current_agent.did),
            )
        else:
            # DB says enrolled but SPIRE entry is gone — re-register
            logger.warning(
                f"[IRONHAND] Agent {current_agent.did} marked enrolled but SPIRE entry missing. Re-registering."
            )

    # Check agent status
    if current_agent.status != "active":
        raise HTTPException(
            status_code=403,
            detail=f"Agent must be active to enroll (current status: {current_agent.status})"
        )

    # §EXTMTLS-C (2026-08-09) — NEVER CLAIM AN IDENTITY WE CANNOT DELIVER.
    # Decide deployment and obtain the certificate BEFORE any state is written.
    # Previously an external agent on a registry with inline delivery disabled
    # was marked mtls_enabled, given a spiffe_id, and had its agent card patched
    # to advertise mTLS it could never terminate — the card told peers to expect
    # an identity that did not exist. Now an undeliverable enrollment writes
    # nothing: no SPIRE entry, no flags, no card patch.
    deployment, signal = _detect_deployment(request, current_agent.did)
    premint: Optional[dict] = None
    if deployment == "external":
        if not _inline_svid_enabled():
            logger.info(
                f"[IRONHAND] Refusing to enroll {current_agent.did}: external "
                f"deployment ({signal}) and inline delivery is disabled — no "
                f"state written."
            )
            return {
                "status": "not_enrolled",
                "deployment": deployment,
                "deployment_signal": signal,
                "delivery": "unavailable",
                "spiffe_id": None,
                "message": (
                    "Not enrolled: this agent runs outside this registry's host and "
                    "inline certificate delivery is disabled here, so no identity "
                    "was issued and nothing now claims otherwise."
                ),
                "instructions": (
                    "Agent-to-agent calls continue to authenticate with your agent "
                    "JWT and payment tokens, which is fully supported. For mTLS, "
                    "either run this agent on the registry's host, ask the operator "
                    "to enable IRONHAND_INLINE_SVID_ENABLED, or run your own "
                    "registry/frame — a sovereign frame issues identities in its own "
                    "trust domain."
                ),
            }
        try:
            premint = mint_agent_svid(current_agent.did, ttl_seconds=_inline_svid_ttl())
        except RuntimeError as e:
            logger.error(
                f"[IRONHAND] Refusing to enroll {current_agent.did}: mint failed "
                f"before any state was written: {e}"
            )
            return {
                "status": "not_enrolled",
                "deployment": deployment,
                "deployment_signal": signal,
                "delivery": "mint_failed",
                "spiffe_id": None,
                "error": str(e)[:200],
                "message": (
                    "Not enrolled: issuing the certificate failed, so nothing was "
                    "recorded and no identity is claimed. Retry."
                ),
                **({"instructions": _runner_unavailable_detail(e)} if isinstance(e, SpireOpsUnavailable) else {}),
            }

    # Register SPIRE entry. Pass the local parent fingerprint so operator-side
    # registries use their own spire-agent (injected via OPERATOR_SPIRE_AGENT_FINGERPRINT
    # at provision time). Central registry falls back to MAINFRAME_AGENT_FINGERPRINT.
    # Created for external agents too (their selector will never match, which is
    # harmless) so the DB and SPIRE stay consistent for the admin drift views.
    sanitized = sanitize_did_for_spiffe(current_agent.did)
    try:
        spiffe_id = register_agent_spire_entry(
            current_agent.did,
            fingerprint=_parent_fingerprint_for_self(),
        )
    except SpireParentUnresolved as e:
        # 🔴 findings row 198 — SAY WHY, AND SAY IT IN FULL. This is a misconfiguration of THIS
        # frame, not a fault of the caller, so it is a 503 rather than a 500 or a 4xx. The
        # message is deliberately NOT truncated: it names the cause, the fix, and where the
        # issuance rules are written down. Before this, the same condition produced a cheerful
        # 200 "enrolled" and a SPIRE entry no agent could ever attest — the caller learned
        # nothing until their workload sat on PERMISSION_DENIED forever.
        logger.error(f"[IRONHAND] refusing enrollment for {current_agent.did}: {e}")
        raise HTTPException(status_code=503, detail=str(e))
    except SpireOpsUnavailable as e:
        # §EXTTEST run 2 (2026-10-31, measured on a dev machine): a frame the kit stood up without --with-runner routes
        # this work to a runner it does not have, and the bare 500 below said "Internal Server Error" about a known
        # state of THIS frame. Like the unresolved parent above: a 503 that names the cause and the fix.
        logger.error(f"[IRONHAND] refusing enrollment for {current_agent.did}: the frame runner did not serve it: {e}")
        raise HTTPException(status_code=503, detail=_runner_unavailable_detail(e))
    except RuntimeError as e:
        logger.error(f"[IRONHAND] SPIRE registration failed for {current_agent.did}: {e}")
        raise HTTPException(
            status_code=500,
            detail=(f"SPIRE registration failed: {str(e)[:200]} — how mTLS identities are "
                    f"issued: https://docs.theprotocol.cloud/learn/security")
        )

    # Update agent record
    current_agent.spiffe_id = spiffe_id
    current_agent.mtls_enabled = True
    current_agent.mtls_enrolled_at = datetime.now(timezone.utc)

    # Patch agent card with mTLS metadata
    await _patch_agent_card_mtls(db, current_agent.did, spiffe_id, enabled=True)

    await db.commit()

    # Emit enrollment event (non-blocking, best-effort)
    try:
        from agentvault_registry.event_emitter import get_event_emitter
        emitter = get_event_emitter()
        await emitter.emit_agent_mtls_enrolled(current_agent.did, spiffe_id)
    except Exception as e:
        logger.warning(f"[IRONHAND] Enrollment event emission failed (non-fatal): {e}")

    logger.info(f"[IRONHAND] Agent enrolled: {current_agent.did} → {spiffe_id}")

    # A1 (2026-07-24): agent.mtls_enrolled was subscribable but never fired.
    import asyncio as _aio
    from agentvault_registry.background_tasks.reactor_helpers import dispatch_webhook_for_agents
    _aio.create_task(dispatch_webhook_for_agents(
        "agent.mtls_enrolled",
        {"agent_did": current_agent.did, "spiffe_id": spiffe_id},
        [current_agent.did], source_label="ironhand.enroll"))

    # §EXTMTLS — same endpoint, adaptive delivery. Fields below are ADDITIVE:
    # every key the previous response carried is still present and unchanged.
    return _attach_delivery(
        {
            "status": "enrolled",
            "spiffe_id": spiffe_id,
            "enrolled_at": current_agent.mtls_enrolled_at.isoformat(),
            "docker_label": f"com.theprotocol.agent-did:{sanitized}",
        },
        request,
        current_agent.did,
        sanitized,
        premint=premint,
        deployment=deployment,
        signal=signal,
    )


@router.post(
    "/disable-mtls",
    summary="Unenroll agent from mTLS identity",
)
async def disable_mtls(
    current_agent: models.Agent = Security(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """
    Unenroll the agent from mTLS. Deletes the SPIRE entry and clears DB fields.
    A certificate already issued stays valid until it expires (an inline one within IRONHAND_INLINE_SVID_TTL_SECONDS).
    """
    if not current_agent.mtls_enabled:
        return {"status": "not_enrolled", "message": "Agent is not enrolled for mTLS."}

    # Delete SPIRE entry
    try:
        deleted = delete_agent_spire_entry(current_agent.did)
    except RuntimeError as e:
        logger.error(f"[IRONHAND] SPIRE deletion failed for {current_agent.did}: {e}")
        # Continue — DB cleanup should still happen

    # Clear agent record — keep mtls_enrolled_at as revocation marker
    old_spiffe_id = current_agent.spiffe_id
    current_agent.spiffe_id = None
    current_agent.mtls_enabled = False
    # NOTE: mtls_enrolled_at is intentionally NOT cleared.
    # It serves as a marker that this agent was once enrolled,
    # used by /revoked-identities to track revocations.

    # Patch agent card
    await _patch_agent_card_mtls(db, current_agent.did, None, enabled=False)

    await db.commit()

    # Emit revocation event — THIS IS THE REAL-TIME SIGNAL
    # Subscribed agents add this SPIFFE ID to their local blocklist immediately
    if old_spiffe_id:
        try:
            from agentvault_registry.event_emitter import get_event_emitter
            emitter = get_event_emitter()
            await emitter.emit_agent_mtls_revoked(
                agent_did=current_agent.did,
                spiffe_id=old_spiffe_id,
                reason="agent_unenroll",
            )
            logger.info(f"[IRONHAND] Revocation event emitted for {old_spiffe_id}")
        except Exception as e:
            logger.warning(f"[IRONHAND] Revocation event emission failed (non-fatal): {e}")

    logger.info(f"[IRONHAND] Agent unenrolled: {current_agent.did} (was {old_spiffe_id})")

    # A1 (2026-07-24): agent.mtls_revoked was subscribable but never fired.
    import asyncio as _aio
    from agentvault_registry.background_tasks.reactor_helpers import dispatch_webhook_for_agents
    _aio.create_task(dispatch_webhook_for_agents(
        "agent.mtls_revoked",
        {"agent_did": current_agent.did, "spiffe_id": old_spiffe_id, "reason": "agent_unenroll"},
        [current_agent.did], source_label="ironhand.unenroll"))

    return {
        "status": "unenrolled",
        "previous_spiffe_id": old_spiffe_id,
        # §EXTTEST (V0649): the old fixed four-hour sentence was wrong for an inline certificate, which lives minutes
        "message": (f"SPIRE entry deleted. A certificate already issued stays valid until it expires: an inline one within "
                    f"{max(1, _inline_svid_ttl() // 60)} minutes, a workload one within its SPIRE lifetime. Peers that must "
                    f"refuse it sooner read GET /api/v1/agent/revoked-identities."),
    }


@router.get(
    "/mtls-status",
    summary="Check agent mTLS enrollment status",
)
async def mtls_status(
    current_agent: models.Agent = Security(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """Return the agent's current mTLS enrollment status."""
    spire_entry_exists = None
    if current_agent.mtls_enabled:
        entry_id = check_agent_spire_entry(current_agent.did)
        spire_entry_exists = entry_id is not None

    return {
        "enrolled": current_agent.mtls_enabled,
        "spiffe_id": current_agent.spiffe_id,
        "enrolled_at": current_agent.mtls_enrolled_at.isoformat() if current_agent.mtls_enrolled_at else None,
        "spire_entry_exists": spire_entry_exists,
        "docker_label": (
            f"com.theprotocol.agent-did:{sanitize_did_for_spiffe(current_agent.did)}"
            if current_agent.mtls_enabled else None
        ),
    }


@router.get(
    "/revoked-identities",
    summary="List revoked SPIFFE IDs (for SDK polling)",
)
async def revoked_identities(
    db: AsyncSession = Depends(get_db),
):
    """
    Public, no auth: the SPIFFE ids of agents whose mTLS identity was revoked (enrolled once, no longer active), for
    the SDK's authenticator to keep its blocklist, and the currently enrolled identities so a caller can build an
    allowlist.

    \f
    Public endpoint (no auth). Returns a list of agent SPIFFE IDs that have been
    revoked (mtls_enabled was True, now False, and spiffe_id is cleared).

    The SDK's A2AAuthenticator polls this endpoint to maintain its local blocklist.
    Also returns currently-enrolled identities so callers can build a trust allowlist.

    Revoked agents usually have spiffe_id cleared (a coordinated suspension keeps it as its restore
    marker, §TWOAGENT #35), so we track revocations via agents that were previously enrolled
    (mtls_enrolled_at is set) but are no longer active, and rebuild the SPIFFE id from the DID.
    For the MVP, we return agents where status != 'active' AND they were once enrolled.
    """
    # Agents that are enrolled (for allowlist)
    enrolled_result = await db.execute(
        select(models.Agent.did, models.Agent.spiffe_id).where(
            models.Agent.mtls_enabled == True,
            models.Agent.spiffe_id.isnot(None),
        )
    )
    enrolled = [{"did": r[0], "spiffe_id": r[1]} for r in enrolled_result.all()]

    # Agents that were enrolled but are now revoked/suspended
    # (status != active but mtls_enrolled_at was set = they were once enrolled)
    revoked_result = await db.execute(
        select(models.Agent.did, models.Agent.spiffe_id, models.Agent.status).where(
            models.Agent.mtls_enrolled_at.isnot(None),
            models.Agent.mtls_enabled == False,
        )
    )
    # For revoked agents, the spiffe_id is cleared — reconstruct from DID
    revoked = []
    for r in revoked_result.all():
        sanitized = sanitize_did_for_spiffe(r[0])
        revoked.append({
            "did": r[0],
            "spiffe_id": f"spiffe://{_LOCAL_TRUST_DOMAIN}/agent/{sanitized}",
            "status": r[2],
        })

    return {
        "enrolled": enrolled,
        "revoked": revoked,
        "enrolled_count": len(enrolled),
        "revoked_count": len(revoked),
    }


# ═══════════════════════════════════════════════════════════════════════
# ADMIN MONITORING ENDPOINT
# ═══════════════════════════════════════════════════════════════════════

@admin_router.get(
    "/targets",
    summary="IRONHAND probe panel — federation-wide targetable agents",
)
async def ironhand_targets(
    include_all: bool = False,
    current_admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
    db: AsyncSession = Depends(get_db),
):
    """Targetable agents for the interactive probe panel, read from the federated
    ``agent_cards`` cache so the FE can show name·registry (not raw DIDs) and filter
    by a right-clicked map node. Default: mTLS-enrolled only (the identity-fabric
    participants — small + relevant). ``?include_all=true`` widens to every known
    agent (cap 500)."""
    import json as _json

    def _td_from_spiffe(sp: str) -> str:
        try:
            return sp.split("://", 1)[1].split("/", 1)[0]
        except Exception:
            return ""

    rows = (await db.execute(
        select(models.AgentCard.agent_did, models.AgentCard.card_data)
    )).all()
    out = []
    for did, card in rows:
        if not did:
            continue
        if isinstance(card, str):
            try:
                card = _json.loads(card)
            except Exception:
                card = {}
        if not isinstance(card, dict):
            continue
        fm = card.get("federation_metadata") or {}
        mtls = bool(fm.get("mtls_enabled"))
        if not include_all and not mtls:
            continue
        td = _td_from_spiffe(fm.get("spiffe_id") or "")
        reg = fm.get("origin_registry_name") or td or "?"
        out.append({
            "did": did,
            "name": card.get("name") or did,
            "registry": reg,
            "trust_domain": td,
            "currency": "BVT" if "frame-c" in td else "AVT",
            "mtls": mtls,
            # FX capability of the agent's HOME frame (for the cockpit to grey invalid
            # cross-currency routes): FX mesh = Frame-A (west) + Frame-C (middle-east).
            # Frame-B (east) is non-FX. Mirrors the card's fees.fx.{enabled,route_enabled};
            # the backend probe guard is authoritative (local FX env on the source).
            "fx_capable": ("frame-b" not in (td or "")),
        })
    out.sort(key=lambda a: (not a["mtls"], (a["registry"] or "").lower(), (a["name"] or "").lower()))
    cap = 500 if include_all else 200
    # local_registry + is_hub: the FE shows the SOURCE picker (fire AS any registry's probe,
    # remotely, from the cockpit) ONLY on the hub. Allowlist via the env
    # IRONHAND_SOURCE_PICKER_REGISTRIES (default 'registry-a'); other registries' Theatres
    # stay probe-only. Each target already carries its home `registry`, so the SAME list
    # feeds both the ① source and ② target right-click menus (node-filtered).
    import os as _os
    from .teg_integration import _get_local_registry_id, _slug
    local_rid = _slug(_get_local_registry_id() or "") or ""
    hub_set = {x.strip() for x in
               (_os.getenv("IRONHAND_SOURCE_PICKER_REGISTRIES", "registry-a")).split(",")
               if x.strip()}
    return {"targets": out[:cap], "total": len(out), "mtls_only": (not include_all),
            "local_registry": local_rid, "is_hub": local_rid in hub_set}


def _ironhand_spire_listing() -> tuple:
    """(`entry count` output, `entry show` output) of this frame's SPIRE server, by IRONHAND's mode: the frame runner's
    identity ops in "runner" mode (§F6 WP6.1, a frame without the docker socket), docker exec otherwise (today's read).
    Raises when neither answers; the monitoring view logs it and shows no SPIRE entries, as it always has."""
    from ..services import agent_spire as _agent_spire
    if _agent_spire.ironhand_mode() == "runner":
        _rc_count, count_stdout = _agent_spire._spire_text(["entry", "count"])
        _rc_show, all_entries_str = _agent_spire._spire_text(["entry", "show"])
        return count_stdout, all_entries_str
    import docker as docker_lib
    client = docker_lib.DockerClient(base_url="unix:///var/run/docker.sock")
    # §SECFIX (2026-09-25): this frame's own SPIRE server (services/agent_spire.SPIRE_CONTAINER, set per frame). It named
    # Frame A's container, so on a shared host EU and ASIA listed Frame A's entries as their own.
    from ..services.agent_spire import SPIRE_CONTAINER as _spire_container
    container = client.containers.get(_spire_container)
    ec, out = container.exec_run(["/opt/spire/bin/spire-server", "entry", "count"], demux=True)
    count_stdout = (out[0] or b"").decode()
    ec, out = container.exec_run(["/opt/spire/bin/spire-server", "entry", "show"], demux=True)
    return count_stdout, (out[0] or b"").decode()


@admin_router.get(
    "/identities",
    summary="IRONHAND monitoring — all SPIRE agent identities",
)
async def ironhand_identities(
    current_admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
    db: AsyncSession = Depends(get_db),
):
    """
    Full monitoring view: all SPIRE agent entries cross-referenced with the DB.
    Returns enrolled, revoked, orphan (SPIRE but no DB), missing (DB but no SPIRE).
    Also updates Prometheus gauges.
    """
    # 1. Query DB for all mTLS-related agents
    enrolled_result = await db.execute(
        select(models.Agent).where(
            models.Agent.mtls_enabled == True,
            models.Agent.spiffe_id.isnot(None),
        )
    )
    enrolled_agents = enrolled_result.scalars().all()

    revoked_result = await db.execute(
        select(models.Agent).where(
            models.Agent.mtls_enrolled_at.isnot(None),
            models.Agent.mtls_enabled == False,
        )
    )
    revoked_agents = revoked_result.scalars().all()

    # 2. Query SPIRE for all agent entries
    spire_agent_entries = []
    spire_entry_count = 0
    service_entry_count = 0
    operator_entry_count = 0
    try:
        count_stdout, all_entries_str = await asyncio.to_thread(_ironhand_spire_listing)
        m = re.search(r"(\d+)", count_stdout)
        total_entries = int(m.group(1)) if m else 0

        # Parse entries
        spire_service_entries = []
        spire_operator_entries = []
        for block in all_entries_str.split("\n\n"):
            if "SPIFFE ID" not in block:
                continue
            spiffe_match = re.search(r"SPIFFE ID\s*:\s*(\S+)", block)
            entry_match = re.search(r"Entry ID\s*:\s*(\S+)", block)
            selector_match = re.search(r"Selector\s*:\s*(.+)", block)
            ttl_match = re.search(r"X509-SVID TTL\s*:\s*(\S+)", block)
            dns_matches = re.findall(r"DNS name\s*:\s*(\S+)", block)
            if not spiffe_match:
                continue
            sid = spiffe_match.group(1)
            eid = entry_match.group(1) if entry_match else ""
            sel = selector_match.group(1).strip() if selector_match else ""
            ttl = ttl_match.group(1) if ttl_match else ""
            entry_info = {"spiffe_id": sid, "entry_id": eid, "selector": sel, "ttl": ttl}
            if dns_matches:
                entry_info["dns"] = dns_matches

            if "/agent/" in sid:
                spire_agent_entries.append(entry_info)
            elif "/service/" in sid:
                spire_service_entries.append(entry_info)
                service_entry_count += 1
            elif "/operator/" in sid:
                spire_operator_entries.append(entry_info)
                operator_entry_count += 1
    except Exception as e:
        logger.warning(f"[IRONHAND] SPIRE query failed: {e}")

    spire_entry_count = len(spire_agent_entries)

    # 3. Cross-reference: find orphans and missing.
    #    FRAME-AWARE: a frame's SPIRE server is SHARED — cloud-op agents enrol into it via
    #    the enrol proxy, so their /agent/ SVIDs live here while their DB rows live on the
    #    operator. Resolving "orphan" against ONLY the local enrolled set therefore flags
    #    every legitimate cross-registry agent as an orphan (false DEGRADED on a mainframe).
    #    We resolve against the FLEET: local enrolled agents UNION the federated agent-card
    #    cache (agent_cards, which carries cloud-op + peer-frame agents). A SVID is a TRUE
    #    orphan only if its DID is unknown to both.
    def _spiffe_to_did(sid: str) -> str:
        leaf = sid.rsplit("/agent/", 1)[-1]
        return leaf.replace("did-theprotocol-", "did:theprotocol:", 1) if leaf.startswith("did-theprotocol-") else leaf

    db_spiffe_ids = {a.spiffe_id for a in enrolled_agents if a.spiffe_id}
    spire_spiffe_ids = {e["spiffe_id"] for e in spire_agent_entries}

    spire_dids = {_spiffe_to_did(s) for s in spire_spiffe_ids}
    known_dids = {a.did for a in enrolled_agents}
    if spire_dids:
        cards_res = await db.execute(
            select(models.AgentCard.agent_did).where(models.AgentCard.agent_did.in_(spire_dids))
        )
        known_dids |= {d for (d,) in cards_res.all() if d}

    # True orphan = SPIRE /agent/ SVID whose DID is unknown to BOTH local-enrolled and fleet cards.
    orphan_ids = {s for s in spire_spiffe_ids if s not in db_spiffe_ids and _spiffe_to_did(s) not in known_dids}
    # Cross-registry = in SPIRE, not locally enrolled, but a known fleet agent (homed elsewhere) — not drift.
    cross_registry_ids = (spire_spiffe_ids - db_spiffe_ids) - orphan_ids
    missing_ids = db_spiffe_ids - spire_spiffe_ids  # in DB but no SPIRE entry (SVID on the frame)

    # 4. Build response — join friendly names from the agent-card cache (the `agents`
    #    table has no name column; the signed card carries it), and treat a frame-enrolled
    #    identity (mtls_enabled + spiffe) as having a live entry even when this registry
    #    can't query its frame's SPIRE locally (operators host no spire-server).
    _all_dids = [a.did for a in enrolled_agents] + [a.did for a in revoked_agents]
    name_by_did = {}
    if _all_dids:
        _nres = await db.execute(
            select(models.AgentCard.agent_did, models.AgentCard.card_data).where(
                models.AgentCard.agent_did.in_(_all_dids))
        )
        for _did, _card in _nres.all():
            if isinstance(_card, dict) and _card.get("name"):
                name_by_did[_did] = _card["name"]
    # SVID freshness: SPIRE issues a 30-min (1800s) X.509-SVID at enrolment and auto-rotates
    # it on that cadence. The FE previously counted DOWN from mtls_enrolled_at, so any agent
    # enrolled >30min ago floored to 00:00 ("000") — wrong on every frame/op (their probes
    # were enrolled last session). We return a server-anchored ROLLING remaining within the
    # current 30-min validity window (= ttl - elapsed%ttl) so the bar always reflects a live,
    # rotating SVID. Exact per-SVID issuance isn't exposed by `spire-server entry show`
    # (it carries the configured TTL, not the live cert) — this is the honest cluster-wide
    # signal; per-container cert notAfter would need a runner heartbeat (future).
    from datetime import datetime as _dt, timezone as _tz
    _SVID_TTL = 1800
    _now_utc = _dt.now(_tz.utc)

    def _svid_remaining(enrolled_at) -> int | None:
        if not enrolled_at:
            return None
        ea = enrolled_at if enrolled_at.tzinfo else enrolled_at.replace(tzinfo=_tz.utc)
        elapsed = (_now_utc - ea).total_seconds()
        if elapsed < 0:
            return _SVID_TTL
        return int(_SVID_TTL - (elapsed % _SVID_TTL))

    enrolled_list = []
    for a in enrolled_agents:
        enrolled_list.append({
            "did": a.did,
            "name": name_by_did.get(a.did) or a.did[:30],
            "spiffe_id": a.spiffe_id,
            "mtls_enabled": True,
            "enrolled_at": a.mtls_enrolled_at.isoformat() if a.mtls_enrolled_at else None,
            "spire_entry_exists": (a.spiffe_id in spire_spiffe_ids) or bool(a.mtls_enabled and a.spiffe_id),
            "status": a.status,
            "svid_ttl_seconds": _SVID_TTL,
            "svid_remaining_seconds": _svid_remaining(a.mtls_enrolled_at),
        })

    revoked_list = []
    for a in revoked_agents:
        sanitized = sanitize_did_for_spiffe(a.did)
        reconstructed_spiffe = f"spiffe://{_LOCAL_TRUST_DOMAIN}/agent/{sanitized}"
        revoked_list.append({
            "did": a.did,
            "name": name_by_did.get(a.did) or a.did[:30],
            "spiffe_id": reconstructed_spiffe,
            "enrolled_at": a.mtls_enrolled_at.isoformat() if a.mtls_enrolled_at else None,
            "status": a.status,
        })

    orphan_list = [{"spiffe_id": sid} for sid in orphan_ids]

    # 5. Update Prometheus metrics
    if _PROM_AVAILABLE:
        IRONHAND_ENROLLED.set(len(enrolled_list))
        IRONHAND_REVOKED.set(len(revoked_list))
        IRONHAND_SPIRE_ENTRIES.set(spire_entry_count)
        IRONHAND_ORPHANS.set(len(orphan_list))
        IRONHAND_MISSING.set(len(missing_ids))

    return {
        "summary": {
            "total_spire_entries": total_entries if 'total_entries' in dir() else spire_entry_count,
            "agent_entries": spire_entry_count,
            "service_entries": service_entry_count,
            "operator_entries": operator_entry_count,
            "db_enrolled": len(enrolled_list),
            "db_revoked": len(revoked_list),
            "orphan_entries": len(orphan_list),
            "cross_registry_entries": len(cross_registry_ids),
            "missing_entries": len(missing_ids),
        },
        "enrolled": enrolled_list,
        "revoked": revoked_list,
        "orphans": orphan_list,
        "services": spire_service_entries if 'spire_service_entries' in dir() else [],
        "operators": spire_operator_entries if 'spire_operator_entries' in dir() else [],
    }


@admin_router.post(
    "/revoke/{agent_did}",
    summary="Admin: revoke agent mTLS identity",
)
async def admin_revoke_agent(
    agent_did: str,
    current_admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
    db: AsyncSession = Depends(get_db),
):
    """Admin revocation: delete SPIRE entry, update DB, emit event. No agent JWT needed. The revoke stands until an
    administrator enrolls the agent again; until then the agent's own enable-mtls answers 403.

    \f
    D6-802 (2026-10-17): recorded on the agent (`mtls_revoked_at`), whether or not it is enrolled now."""
    result = await db.execute(select(models.Agent).where(models.Agent.did == agent_did))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_did}")
    agent.mtls_revoked_at = datetime.now(timezone.utc)
    if not agent.mtls_enabled:
        await db.commit()
        return {"status": "not_enrolled", "did": agent_did, "enrollment_blocked": True}

    old_spiffe_id = agent.spiffe_id
    try:
        delete_agent_spire_entry(agent_did)
    except Exception as e:
        logger.warning(f"[IRONHAND] SPIRE deletion failed (admin): {e}")

    agent.spiffe_id = None
    agent.mtls_enabled = False
    await _patch_agent_card_mtls(db, agent_did, None, enabled=False)
    await db.commit()

    if old_spiffe_id:
        try:
            from agentvault_registry.event_emitter import get_event_emitter
            await get_event_emitter().emit_agent_mtls_revoked(
                agent_did=agent_did, spiffe_id=old_spiffe_id,
                reason="admin_revocation", revoked_by=current_admin.email,
            )
        except Exception as e:
            logger.warning(f"[IRONHAND] Event emission failed: {e}")

    # §NOTIFV2 — the owner should hear their agent's mTLS identity died (revocation
    # propagates in <1s; the human deserves the same latency). Post-commit, best-effort.
    try:
        import asyncio as _aio
        from agentvault_registry.background_tasks.push_notify import notify_agent_owners
        _aio.create_task(notify_agent_owners(
            "agent.mtls_revoked", [agent_did],
            title="Agent mTLS identity revoked",
            message=f"{agent_did} - revoked by admin",
            # D6-781: the owner's agent list (the console has no #/agents; Pocket opens its own Agents tab)
            tags="no_entry", priority="high", click="/ui/#/my-agents"))
    except Exception:  # noqa: BLE001
        logger.debug("[MTLS] revoke notify skipped", exc_info=True)
    # A1 (2026-07-24): agent.mtls_revoked webhook (admin path).
    import asyncio as _aio
    from agentvault_registry.background_tasks.reactor_helpers import dispatch_webhook_for_agents
    _aio.create_task(dispatch_webhook_for_agents(
        "agent.mtls_revoked",
        {"agent_did": agent_did, "spiffe_id": old_spiffe_id, "reason": "admin_revocation"},
        [agent_did], source_label="ironhand.admin_revoke"))

    return {"status": "revoked", "did": agent_did, "spiffe_id": old_spiffe_id, "enrollment_blocked": True}


@admin_router.post(
    "/enroll/{agent_did}",
    summary="Admin: enroll or re-enroll agent for mTLS",
)
async def admin_enroll_agent(
    agent_did: str,
    current_admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
    db: AsyncSession = Depends(get_db),
):
    """Admin enrollment: create SPIRE entry, update DB. No agent JWT needed."""
    result = await db.execute(select(models.Agent).where(models.Agent.did == agent_did))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_did}")

    try:
        spiffe_id = register_agent_spire_entry(agent_did)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e)[:200])

    agent.spiffe_id = spiffe_id
    agent.mtls_enabled = True
    agent.mtls_enrolled_at = datetime.now(timezone.utc)
    agent.mtls_revoked_at = None  # D6-802: an administrator's enrolment ends an administrator's revoke
    await _patch_agent_card_mtls(db, agent_did, spiffe_id, enabled=True)
    await db.commit()

    try:
        from agentvault_registry.event_emitter import get_event_emitter
        await get_event_emitter().emit_agent_mtls_enrolled(agent_did, spiffe_id)
    except Exception:
        pass

    # A1 (2026-07-24): agent.mtls_enrolled webhook (admin path).
    import asyncio as _aio
    from agentvault_registry.background_tasks.reactor_helpers import dispatch_webhook_for_agents
    _aio.create_task(dispatch_webhook_for_agents(
        "agent.mtls_enrolled",
        {"agent_did": agent_did, "spiffe_id": spiffe_id},
        [agent_did], source_label="ironhand.admin_enroll"))

    return {"status": "enrolled", "did": agent_did, "spiffe_id": spiffe_id}


@admin_router.delete(
    "/spire-entry",
    summary="Admin: delete an orphan SPIRE entry",
)
async def admin_delete_spire_entry(
    body: dict,
    current_admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    """Delete an orphan SPIRE entry by SPIFFE ID. For cleanup only."""
    spiffe_id = body.get("spiffe_id", "")
    if not spiffe_id or not spiffe_id.startswith("spiffe://"):
        raise HTTPException(status_code=400, detail="Invalid spiffe_id")

    # Extract DID from SPIFFE ID to use delete function. Accept the local frame's trust
    # domain (RP3) with the legacy agentvault.com literal as fallback for Frame-A tooling.
    prefix = None
    for _td in {_LOCAL_TRUST_DOMAIN, "agentvault.com"}:
        _p = f"spiffe://{_td}/agent/"
        if spiffe_id.startswith(_p):
            prefix = _p
            break
    if prefix is None:
        raise HTTPException(status_code=400, detail="Can only delete agent entries")

    sanitized = spiffe_id[len(prefix):]
    # Reverse: did-theprotocol-xxx → did:theprotocol:xxx
    parts = sanitized.split("-", 2)
    agent_did = f"{parts[0]}:{parts[1]}:{parts[2]}" if len(parts) >= 3 else sanitized.replace("-", ":")

    try:
        deleted = delete_agent_spire_entry(agent_did)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)[:200])

    return {"status": "deleted" if deleted else "not_found", "spiffe_id": spiffe_id}


@admin_router.post(
    "/probe",
    summary="Fire a live mTLS identity-travel probe (mTLS Theatre) — local OR remote source",
)
async def ironhand_probe(
    body: dict = None,
    db: AsyncSession = Depends(get_db),
    current_admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    """Fire an interactive IRONHAND probe and return the route the Theatre animates.

    The hub (registry-a) is a CLUSTER COCKPIT: it can pick ANY registry's probe/agent as
    the SOURCE. When the source is homed on a PEER registry, the fire is PROXIED to that
    registry's /admin/ironhand/probe-remote over the federation mTLS client — that registry
    fires its OWN embodied probe, so ITS SVID rides the hop — and we relay the result. A
    LOCAL source (or none) fires here. Body: {source_did?, target_did|receiver_did, amount?}."""
    body = body or {}
    source_did = body.get("source_did") or body.get("sender_did")
    target_did = body.get("target_did") or body.get("receiver_did")
    # Remote source → proxy to its HOME registry (own-SVID fire there). Local/none → here.
    if source_did and target_did and not await _is_local_agent(db, source_did):
        return await _proxy_remote_probe(db, body)
    return await _fire_probe_core(db, body)


async def _is_local_agent(db: AsyncSession, did: str) -> bool:
    """True if ``did`` is an agent registered on THIS registry (fireable locally)."""
    if not did:
        return False
    return bool((await db.execute(
        select(models.Agent.did).where(models.Agent.did == did)
    )).scalar_one_or_none())


async def _proxy_remote_probe(db: AsyncSession, body: dict) -> dict:
    """Cockpit pattern: fire the probe on the SOURCE's HOME registry. Resolve the source
    DID's home from its federated card (``origin_registry_name`` == peer name) → that
    peer's ``base_url`` → POST /admin/ironhand/probe-remote over the SAME federation mTLS
    client federation_sync uses (proven fleet-wide). The peer fires its own probe/agent so
    its SVID rides; we relay the result for the map. Δ-safe (low, one-way)."""
    import httpx as _httpx
    from .teg_integration import _to_internal_mtls_url
    from agentvault_registry.identity import svid_client

    source_did = body.get("source_did") or body.get("sender_did")
    card = (await db.execute(
        select(models.AgentCard.card_data).where(models.AgentCard.agent_did == source_did)
    )).scalar_one_or_none()
    origin = ""
    if isinstance(card, dict):
        origin = (card.get("federation_metadata") or {}).get("origin_registry_name") or ""
    if not origin:
        raise HTTPException(status_code=404, detail="source home registry unknown (no federated card)")
    # Match a peer_registries row by name (ACTIVE preferred). origin e.g. 'op-tokyo'/'Frame-B'.
    peers = (await db.execute(
        select(models.PeerRegistry).where(func.lower(models.PeerRegistry.name) == origin.lower())
    )).scalars().all()
    peer = next((p for p in peers if (p.status or "").upper() == "ACTIVE"),
                (peers[0] if peers else None))
    if peer is None or not peer.base_url:
        raise HTTPException(status_code=502,
                            detail=f"no reachable peer registry for source home '{origin}'")

    # MUST be under /api/v1/federation/* — the cross-registry mTLS gateway only forwards
    # that prefix (verified: /api/v1/admin/* → gateway 404). Served by federation_sync.router.
    url = _to_internal_mtls_url(peer.base_url.rstrip("/")) + "/api/v1/federation/ironhand-probe"
    fwd = {
        "source_did": source_did,
        "target_did": body.get("target_did") or body.get("receiver_did"),
        "amount": body.get("amount"),
        "method": body.get("method") or body.get("backend"),
    }
    client_config: dict = {"timeout": 95.0}
    if url.startswith("https://"):
        cc = svid_client.get_client_cert_config(target_url=url)
        if not cc:
            raise HTTPException(status_code=502, detail="no mTLS client cert available for remote probe")
        client_config.update(cc)
    else:
        import os as _os
        lic = _os.getenv("FEDERATION_LICENSE_KEY", "")
        if lic:
            client_config["headers"] = {"X-Federation-License": lic}
        else:
            client_config["headers"] = {
                "X-Federation-Secret": _os.getenv("FEDERATION_INTERNAL_SECRET", ""),
                "X-Federation-SPIFFE-ID": svid_client.get_spiffe_id() or "",
            }
    try:
        async with _httpx.AsyncClient(**client_config) as c:
            r = await c.post(url, json=fwd)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"remote probe unreachable ({origin}): {str(e)[:160]}")
    try:
        data = r.json()
    except Exception:
        raise HTTPException(status_code=502, detail=f"remote probe bad response from {origin} ({r.status_code})")
    if r.status_code not in (200, 201):
        raise HTTPException(status_code=502, detail=f"remote probe failed on {origin}: {str(data)[:200]}")
    if isinstance(data, dict):
        data["remote_fired_on"] = origin
        data["via"] = f"{data.get('via') or 'remote'} · remote@{origin}"
    return data


@admin_router.post(
    "/probe-remote",
    summary="Federation-auth: fire THIS registry's probe/agent on behalf of the hub cockpit",
)
async def ironhand_probe_remote(
    body: dict,
    peer_spiffe_id: str = Depends(require_peer_registry_identity),
    db: AsyncSession = Depends(get_db),
):
    """Peer-authenticated entry: the hub calls this on a source's HOME registry so that
    registry fires its OWN embodied probe/agent (its SVID rides). Same envelope as /probe;
    no admin JWT — the caller is a validated peer registry (mTLS SPIFFE) and the transfer
    is low + one-way. Body: {source_did?, target_did, amount?}."""
    logger.info(f"[IRONHAND probe-remote] peer={peer_spiffe_id} source={(body or {}).get('source_did')}")
    return await _fire_probe_core(db, body or {})


async def _fire_probe_core(db: AsyncSession, body: dict) -> dict:
    """Fire the probe LOCALLY on this registry (NO remote routing — avoids loops). Drives
    this registry's embodied probe (own SVID); or, when {source_did} names a LOCAL agent,
    fires AS it (admin-minted JWT). Returns {ok, method, source, node_path, ...}."""
    import os as _os, httpx as _httpx, time as _time, secrets as _secrets, asyncio as _asyncio
    from .teg_integration import (
        _resolve_receiver_registry, _slug, _local_frame_currency, _get_local_registry_id,
    )
    body = body or {}
    target_did = body.get("target_did") or body.get("receiver_did")
    # Optional: fire AS a specific LOCAL agent (the hub source-picker). registry-a is the
    # Commander's hub — he holds every local agent — so admin mints that agent's JWT in
    # process (no stored secret). Validated below: it MUST be a local agent. Default ('')
    # falls back to this registry's embodied probe (rides its own SVID).
    source_did = body.get("source_did") or body.get("sender_did")
    # A REAL, low, hard-capped, one-way probe transfer (no refund — a refund would
    # need a return leg = a different route). Default tiny; cap defends the treasury.
    amount = str(body.get("amount") or "1")
    try:
        if float(amount) > 10:
            amount = "10"
    except Exception:
        amount = "1"
    req_backend = str(body.get("method") or body.get("backend") or "2pc").lower()
    if req_backend not in ("async", "2pc"):
        req_backend = "2pc"

    # The LOCAL probe identity (this registry's own funny-named, mTLS-enrolled probe,
    # stored as a canary_agent tagged 'ironhand_probe').
    probe = (await db.execute(
        select(models.CanaryAgent)
        .where(models.CanaryAgent.notes.like("ironhand_probe%"),
               models.CanaryAgent.is_active.is_(True))
        .order_by(models.CanaryAgent.id).limit(1)
    )).scalar_one_or_none()

    # Hub source-pick: resolve the chosen sender. It MUST be an agent registered on THIS
    # registry — admin can only mint a JWT for (and the agent can only hold a balance on)
    # a local identity. A foreign DID is rejected (no impersonating peer-frame agents).
    source_agent = None
    if source_did:
        source_agent = (await db.execute(
            select(models.Agent).where(models.Agent.did == source_did)
        )).scalar_one_or_none()
        if source_agent is None:
            raise HTTPException(
                status_code=400,
                detail="source_did must be an agent registered on this registry (source must be local)",
            )

    # ── Legacy fallback: no sender at all OR no target → drive the Alpha demo. ──
    if (probe is None and source_agent is None) or not target_did:
        alpha = _os.getenv("IRONHAND_ALPHA_URL", "").strip()  # §BATCH3 item 1: no box-IP default
        if not alpha:
            raise HTTPException(status_code=503, detail="IRONHAND_ALPHA_URL is not configured on this registry (the Alpha demo fallback)")
        try:
            async with _httpx.AsyncClient(timeout=85.0) as c:
                r = await c.post(f"{alpha}/probe", json=body)
                data = r.json()
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"probe drive failed: {str(e)[:200]}")
        if not data.get("ok"):
            raise HTTPException(status_code=502, detail=str(data.get("error", "probe failed"))[:300])
        try:
            src_slug = (_slug(str(data.get("source", "")).split()[0] or "") or "op-paris")
            _t, rrid = await _resolve_receiver_registry(db, data.get("receiver_did", ""))
            dest_slug = (_slug(rrid or "") or "").replace("registry-", "")
            src_ccy = "AVT" if "AVT" in str(data.get("source", "")).upper() else "BVT"
            dst_ccy = "BVT" if src_ccy == "AVT" else "AVT"
            reserve = {"AVT": "registry-a", "BVT": "frame-c"}
            path = []
            for x in [src_slug, reserve.get(src_ccy), reserve.get(dst_ccy), dest_slug]:
                if x and x not in path:
                    path.append(x)
            data["node_path"] = path
            data["dest_registry_slug"] = dest_slug
        except Exception as e:
            data["node_path"] = []
            data["node_path_error"] = str(e)[:160]
        return data

    # ── Targeted probe: fire a REAL low one-way transfer AS the local probe agent. ──
    # Method is DERIVED, not chosen: cross-currency target → FX; same-currency remote →
    # async/2PC (mTLS path); same registry → local. cross-registry-transfer auto-detects
    # the receiver's currency and routes FX, so it is the method engine.
    # Effective SENDER, resolved up-front so the FX-frame guard + result can name it: the
    # embodied probe by default; a hub-picked LOCAL agent otherwise (if that pick IS the
    # probe, it still rides the embodied SVID).
    use_probe = (source_agent is None) or (probe is not None and source_agent.did == probe.agent_did)
    sender_did = probe.agent_did if use_probe else source_agent.did
    _scard = (await db.execute(
        select(models.AgentCard.card_data).where(models.AgentCard.agent_did == sender_did)
    )).scalar_one_or_none()
    sender_name = (_scard.get("name") if isinstance(_scard, dict) else None) or sender_did[:24]
    base = "http://localhost:8000/api/v1"
    local_ccy = _local_frame_currency()
    local_rid = _get_local_registry_id()
    # Target home (trust domain + display registry + currency) from the federated card
    # cache — reliable even for indirect child ops that _resolve_receiver_registry can't
    # resolve. Falls back to the resolver's trust domain only if the card is missing.
    target_td, dest_reg = "", ""
    card = (await db.execute(
        select(models.AgentCard.card_data).where(models.AgentCard.agent_did == target_did)
    )).scalar_one_or_none()
    if isinstance(card, dict):
        fm = card.get("federation_metadata") or {}
        sp = fm.get("spiffe_id") or ""
        try:
            target_td = sp.split("://", 1)[1].split("/", 1)[0]
        except Exception:
            target_td = ""
        dest_reg = fm.get("origin_registry_name") or ""
    if not target_td:
        try:
            _ttd, _trid = await _resolve_receiver_registry(db, target_did)
            target_td = str(_ttd or "")
        except Exception:
            target_td = ""
    target_ccy = "BVT" if "frame-c" in target_td else "AVT"
    is_cross_ccy = (target_ccy != local_ccy)
    # "Local" = the target is an agent registered on THIS registry (and same currency).
    local_hit = (await db.execute(
        select(models.Agent.did).where(models.Agent.did == target_did)
    )).scalar_one_or_none()
    is_local = bool(local_hit) and not is_cross_ccy
    # ── FX-frame guard ──────────────────────────────────────────────────────────────
    # A cross-currency (AVT<->BVT) route can only be ORIGINATED by an FX-capable frame.
    # FX mesh = Frame-A (west) <-> Frame-C (middle-east); Frame-B (east) has FX DEACTIVATED.
    # Capability = local FX booth (FX_ENABLED) OR FX routing (FX_ROUTE_ENABLED) — the exact
    # signals the registry card now publishes as fees.fx.{enabled,route_enabled}. Refuse
    # cleanly BEFORE any leg fires → no pre-conversion+compensate churn, no misleading
    # license 403 (licenses gate ES emission only; transport is pure mTLS).
    _fx_capable = ((_os.getenv("FX_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")) or
                   (_os.getenv("FX_ROUTE_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")))
    if is_cross_ccy and not _fx_capable:
        return {
            "ok": False, "method": "fx-unavailable", "source": sender_did, "source_name": sender_name,
            "target_did": target_did, "target_registry": dest_reg or target_td, "amount": amount,
            "currency": f"{local_ccy}->{target_ccy}", "http_status": None, "latency_ms": 0,
            "via": "blocked: source frame is not an FX frame", "node_path": [],
            "result": {"detail": (
                f"{local_rid or 'this frame'} is not an FX frame — cross-currency "
                f"({local_ccy}→{target_ccy}) routes run only between Frame-A (west) and "
                f"Frame-C (middle-east). This frame has FX disabled.")},
        }
    # Route → endpoint + body (mirrors canary_runner's ironhand_mtls payload).
    if is_local:
        method = "local"; endpoint_path = "/api/v1/teg/transfer"
        fire_body = {"receiver_agent_id": target_did, "amount": amount}
    elif is_cross_ccy:
        method = "fx"; endpoint_path = "/api/v1/teg/cross-registry-transfer"
        fire_body = {"receiver_did": target_did, "amount": amount}
    else:
        method = req_backend; endpoint_path = f"/api/v1/teg/cross-registry-transfer?backend={req_backend}"
        fire_body = {"receiver_did": target_did, "amount": amount}

    t0 = _time.time()
    ok = False; rd = None; http_status = None; latency_ms = None; fired_via = "backend"
    # use_probe / sender_did / sender_name resolved up-front (above). PRIMARY embodied path
    # is available ONLY for the embodied probe (its canary container consumes
    # canary_ironhand_fire:{path_id}, stored in canary_agents.notes as 'ironhand_probe|<path_id>',
    # and fires presenting its own cert).
    path_id = (probe.notes.split("|", 1)[1].strip()
               if (use_probe and probe is not None and probe.notes and "|" in probe.notes) else "")
    if path_id:
        try:
            import json as _json
            from agentvault_registry.background_tasks.leader import get_redis as _get_redis
            rc = await _get_redis()
            if rc is not None:
                test_id = f"probe-{_secrets.token_hex(6)}"
                fire_stream = f"canary_ironhand_fire:{path_id}"
                result_key = f"canary_ironhand_result:{test_id}"
                payload = {"test_id": test_id, "endpoint": endpoint_path, "body": fire_body,
                           "receiver_did": target_did, "amount": amount, "memo": f"probe:{test_id}"}
                try:
                    await rc.xgroup_create(name=fire_stream, groupname="canary_runner_group", id="$", mkstream=True)
                except Exception:
                    pass
                await rc.xadd(fire_stream, {"data": _json.dumps(payload)}, maxlen=100, approximate=True)
                _deadline = _time.time() + 22
                _raw = None
                while _time.time() < _deadline:
                    try:
                        _raw = await rc.get(result_key)
                    except Exception:
                        _raw = None
                    if _raw:
                        break
                    await _asyncio.sleep(0.5)
                if _raw:
                    rd = _json.loads(_raw if isinstance(_raw, str) else _raw.decode())
                    ok = bool(rd.get("transfer_id")) and not rd.get("failure_type")
                    http_status = rd.get("http_status")
                    latency_ms = rd.get("http_latency_ms") or int((_time.time() - t0) * 1000)
                    fired_via = "embodied mTLS (own SVID)"
        except Exception as _e:
            logger.warning(f"[IRONHAND probe] embodied fire failed → fallback: {str(_e)[:160]}")
    # FALLBACK: mint the sender's JWT + fire (still a REAL transfer, home-registry-vouched).
    #   - probe sender → real agent login with its own client creds.
    #   - hub-picked source → admin mints that LOCAL agent's JWT in-process (registry-a is
    #     the hub; no stored secret). The JWT IS the authorization that moves the money.
    if rd is None:
        idem = f"probe-{int(_time.time() * 1000)}-{_secrets.token_hex(3)}"
        try:
            async with _httpx.AsyncClient(timeout=90.0) as c:
                if use_probe:
                    tr = await c.post(f"{base}/auth/agent/token",
                                      data={"username": probe.client_id, "password": probe.client_secret})
                    if tr.status_code != 200:
                        raise HTTPException(status_code=502, detail=f"probe token failed: {tr.text[:200]}")
                    ajwt = tr.json()["access_token"]
                    if fired_via == "backend":
                        fired_via = "probe JWT (home-registry vouched)"
                else:
                    ajwt = security.create_access_token(data={
                        "sub": source_agent.did, "type": "agent", "agent_id": str(source_agent.id),
                        # L3 — the canary hub mints AS the source agent; act records the
                        # delegating authority (the canary system, not the agent's own will).
                        "act": {"sub": "service:canary-hub", "reason": "canary"},
                    })
                    fired_via = "hub-minted JWT (registry-a)"
                hdr = {"Authorization": f"Bearer {ajwt}", "Idempotency-Key": idem}
                r = await c.post(f"http://localhost:8000{endpoint_path}", json=fire_body, headers=hdr)
                http_status = r.status_code
                ok = r.status_code in (200, 201, 202)
                latency_ms = int((_time.time() - t0) * 1000)
                try:
                    rd = r.json()
                except Exception:
                    rd = {"raw": r.text[:200]}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"probe fire failed: {str(e)[:200]}")

    # node_path the Theatre animates. Map-node slugs: ops render as "op-x"; the
    # mainframe stays "registry-a"/"frame-b"/"frame-c". DO NOT blanket-strip
    # "registry-" — that turned "registry-a" → "a" (unresolvable) so same-currency
    # 2-node routes (registry-a→op) failed to animate as "route unresolved".
    def _node_slug(rid_or_name: str) -> str:
        s = (_slug(rid_or_name or "") or "")
        if s.startswith("registry-op-") or s.startswith("registry-cloud-op-"):
            s = s.split("registry-", 1)[-1]  # registry-op-doha -> op-doha
        return s
    src_slug = _node_slug(local_rid) or "registry-a"
    dest_slug = _node_slug(dest_reg) or src_slug
    if is_cross_ccy:
        reserve = {"AVT": "registry-a", "BVT": "frame-c"}
        raw = [src_slug, reserve.get(local_ccy), reserve.get(target_ccy), dest_slug]
    else:
        raw = [src_slug, dest_slug]
    node_path = []
    for x in raw:
        if x and x not in node_path:
            node_path.append(x)

    return {
        "ok": ok, "method": method, "source": sender_did, "source_name": sender_name,
        "target_did": target_did, "target_registry": dest_reg or target_td, "amount": amount,
        "currency": (f"{local_ccy}->{target_ccy}" if is_cross_ccy else local_ccy),
        "http_status": http_status, "latency_ms": latency_ms, "via": fired_via,
        "node_path": node_path, "result": rd,
    }


# ─────────────────────────────────────────────────────────────────────────────
# IRONHAND federation-auth proxy endpoints
#
# Operator registries don't mount /var/run/docker.sock (security boundary), so
# they can't run SPIRE admin CLI themselves. These endpoints let operators
# delegate register/delete to the central registry that owns their SPIRE
# server, authenticated via the canonical federation auth path
# (X-Federation-Secret + X-Federation-SPIFFE-ID).
# ─────────────────────────────────────────────────────────────────────────────


async def _deny_if_local_agent(db: AsyncSession, agent_did: str, peer_spiffe_id: str, op: str) -> None:
    """RP1 (2026-07-24 wiring audit): a peer may only manage SPIRE entries for ITS OWN
    (remote) agents — the whole purpose of these proxies is delegating for operator-side
    agents that have no local `agents` row here. A DID that DOES resolve to a local agent
    row is this registry's own (incl. the sovereign agents); a peer must not be able to
    plant or revoke a local agent's SPIRE identity through this proxy."""
    _local = (await db.execute(
        select(models.Agent).where(models.Agent.did == agent_did)
    )).scalar_one_or_none()
    if _local is not None:
        logger.error(
            f"[IRONHAND-PROXY] peer={peer_spiffe_id} attempted SPIRE {op} of LOCAL agent "
            f"{agent_did} — DENIED (RP1)"
        )
        raise HTTPException(
            status_code=403,
            detail="Peers cannot manage SPIRE entries of this registry's local agents",
        )


@admin_router.post(
    "/register-agent-proxy",
    summary="Federation-auth: register agent SPIRE entry on behalf of a peer operator",
)
async def register_agent_spire_proxy(
    body: dict,
    peer_spiffe_id: str = Depends(require_peer_registry_identity),
    db: AsyncSession = Depends(get_db),
):
    """
    For a peer operator: create the SPIRE entry of one of its agents on this frame's SPIRE server. Body: {agent_did,
    parent_fingerprint, dns_sans, trust_domain?}; trust_domain defaults to the one in the peer's SPIFFE id. Auth:
    the peer's federation identity.

    \f
    Operator-side delegate for register_agent_spire_entry.

    Body: {"agent_did": "did:...", "parent_fingerprint": "<hex>",
           "dns_sans": [...], "trust_domain": "agentvault.com"}

    trust_domain (§pass32 Phase 6): optional explicit override. Falls back to
    the trust domain extracted from peer_spiffe_id. Lets a registry that has
    docker.sock access to multiple SPIRE servers (e.g., agentvault-spire-server
    AND frame-b-spire-server on the same host) route entry creation to the
    correct one based on the requesting peer's trust domain.
    """
    from agentvault_registry.services.agent_spire import _extract_trust_domain

    agent_did = body.get("agent_did", "")
    parent_fp = body.get("parent_fingerprint", "")
    dns_sans = body.get("dns_sans") or []
    explicit_td = body.get("trust_domain") or None
    peer_td = _extract_trust_domain(peer_spiffe_id) if peer_spiffe_id else None
    effective_td = explicit_td or peer_td

    if not agent_did or not agent_did.startswith("did:"):
        raise HTTPException(status_code=400, detail="Invalid or missing agent_did")
    if not parent_fp:
        raise HTTPException(status_code=400, detail="Missing parent_fingerprint")

    await _deny_if_local_agent(db, agent_did, peer_spiffe_id, "register")

    logger.info(
        f"[IRONHAND-PROXY] register request from peer={peer_spiffe_id}, "
        f"agent={agent_did}, parent_fp={parent_fp[:8]}..., trust_domain={effective_td}"
    )
    try:
        spiffe_id = register_agent_spire_entry(
            agent_did,
            dns_sans=dns_sans,
            fingerprint=parent_fp,
            trust_domain=effective_td,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e)[:200])

    return {"spiffe_id": spiffe_id}


@admin_router.post(
    "/mint-agent-proxy",
    summary="Federation-auth: issue an inline agent SVID on behalf of a peer operator",
)
async def mint_agent_svid_proxy(
    body: dict,
    peer_spiffe_id: str = Depends(require_peer_registry_identity),
    db: AsyncSession = Depends(get_db),
):
    """
    For a peer operator: issue an inline SVID for one of its own agents (a cloud operator has no SPIRE server of its
    own, so the frame signs). A peer can never have one issued for an agent of this registry. Body: {agent_did, ttl_seconds,
    trust_domain, dns_sans}. Auth: the peer's federation identity.

    \f
    Operator-side delegate for mint_agent_svid (§EXTMTLS).

    Cloud operators hold no docker.sock, so the frame that owns the SPIRE
    server signs on their behalf — the same split register-agent-proxy uses.
    The peer may only mint for ITS OWN agents: _deny_if_local_agent blocks a
    peer from minting a certificate for an agent that belongs to this registry.

    Body: {"agent_did": "did:...", "ttl_seconds": 1800,
           "trust_domain": "agentvault.com", "dns_sans": [...]}
    """
    from agentvault_registry.services.agent_spire import _extract_trust_domain

    agent_did = body.get("agent_did", "")
    explicit_td = body.get("trust_domain") or None
    peer_td = _extract_trust_domain(peer_spiffe_id) if peer_spiffe_id else None
    effective_td = explicit_td or peer_td
    dns_sans = body.get("dns_sans") or []
    try:
        ttl = int(body.get("ttl_seconds") or 1800)
    except (TypeError, ValueError):
        ttl = 1800
    ttl = max(60, min(ttl, 3600))

    if not agent_did or not agent_did.startswith("did:"):
        raise HTTPException(status_code=400, detail="Invalid or missing agent_did")

    await _deny_if_local_agent(db, agent_did, peer_spiffe_id, "mint")

    logger.info(
        f"[IRONHAND-PROXY] mint request from peer={peer_spiffe_id}, "
        f"agent={agent_did}, ttl={ttl}s, trust_domain={effective_td}"
    )
    try:
        return mint_agent_svid(
            agent_did, ttl_seconds=ttl, trust_domain=effective_td, dns_sans=dns_sans
        )
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e)[:200])


@admin_router.post(
    "/delete-agent-proxy",
    summary="Federation-auth: delete agent SPIRE entry on behalf of a peer operator",
)
async def delete_agent_spire_proxy(
    body: dict,
    peer_spiffe_id: str = Depends(require_peer_registry_identity),
    db: AsyncSession = Depends(get_db),
):
    """
    For a peer operator: delete the SPIRE entry of one of its agents. Body: {agent_did, trust_domain?}; trust_domain
    defaults to the one in the peer's SPIFFE id. Auth: the peer's federation identity.

    \f
    Operator-side delegate for delete_agent_spire_entry.

    Body: {"agent_did": "did:...", "trust_domain": "agentvault.com"}

    trust_domain (§pass32 Phase 6): optional override, defaults to the
    trust domain extracted from peer_spiffe_id.
    """
    from agentvault_registry.services.agent_spire import _extract_trust_domain

    agent_did = body.get("agent_did", "")
    explicit_td = body.get("trust_domain") or None
    peer_td = _extract_trust_domain(peer_spiffe_id) if peer_spiffe_id else None
    effective_td = explicit_td or peer_td

    if not agent_did or not agent_did.startswith("did:"):
        raise HTTPException(status_code=400, detail="Invalid or missing agent_did")

    await _deny_if_local_agent(db, agent_did, peer_spiffe_id, "delete")

    logger.info(
        f"[IRONHAND-PROXY] delete request from peer={peer_spiffe_id}, agent={agent_did}, "
        f"trust_domain={effective_td}"
    )
    try:
        deleted = delete_agent_spire_entry(agent_did, trust_domain=effective_td)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)[:200])

    return {"deleted": deleted}


# §OPLANE (V0614): the three proxies on the lane a cloud operator really has to its parent frame. The /api/v1/admin/ironhand
# paths above sit behind the parent's console vhost, which clears every federation credential a public request carries
# (EU, ASIA, every template frame), so an operator's agent could not enrol on production. The frame's nginx-federation
# forwards /api/v1/federation/ with the operator's certificate vouched; require_peer_registry_identity stays each
# handler's own check. Served only through that terminator (core/mtls_auth.require_vouched_peer_cert).
from agentvault_registry.core.mtls_auth import require_vouched_peer_cert  # noqa: E402

federation_router = APIRouter(
    prefix="/api/v1/federation/ironhand",
    tags=["IRONHAND Monitoring (Admin)"],
    dependencies=[Depends(require_vouched_peer_cert)],
)
for _path, _handler in (("/register-agent-proxy", register_agent_spire_proxy),
                        ("/mint-agent-proxy", mint_agent_svid_proxy),
                        ("/delete-agent-proxy", delete_agent_spire_proxy)):
    federation_router.add_api_route(_path, _handler, methods=["POST"],
                                    summary=f"`{_path.strip('/')}` for a peer operator, through the federation lane (vouched SVID)")


async def _patch_agent_card_mtls(
    db: AsyncSession,
    agent_did: str,
    spiffe_id: str | None,
    enabled: bool,
):
    """Patch the agent's card_data with mTLS metadata for federation sync."""
    result = await db.execute(
        select(models.AgentCard).where(models.AgentCard.agent_did == agent_did)
    )
    card = result.scalar_one_or_none()
    if not card:
        logger.warning(f"[IRONHAND] No agent card found for {agent_did}")
        return

    card_data = dict(card.card_data or {})
    fed_meta = dict(card_data.get("federation_metadata", {}))

    if enabled and spiffe_id:
        fed_meta["spiffe_id"] = spiffe_id
        fed_meta["mtls_enabled"] = True
    else:
        fed_meta.pop("spiffe_id", None)
        fed_meta.pop("mtls_enabled", None)

    card_data["federation_metadata"] = fed_meta
    card.card_data = card_data

    # Force SQLAlchemy to detect the JSONB change
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(card, "card_data")
