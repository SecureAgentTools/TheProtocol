"""Background Task: License Drift Monitor (Option D-light Phase D4 — 2026-04-21)

Detects cross-table state inconsistencies between federation_licenses,
operator_applications, and peer_registries. Three checks per cycle:

  1. license_revoked_operator_active
     FederationLicense.status='revoked' AND OperatorApplication.status IN ('approved','suspended')
     → the license was revoked but the operator was never terminated. Security gap.

  2. operator_revoked_license_active
     OperatorApplication.status='revoked' AND FederationLicense.status IN ('active','suspended')
     → operator revoke didn't cascade to the license (legacy pre-D2 bug).

  3. peer_inactive_license_active
     PeerRegistry.status='INACTIVE' AND FederationLicense.status='active' for the same operator
     → partial teardown. Operator's cloud stack is gone but license still works.

Each detection emits `FederationStateDriftDetected` with a drift_type field.
Idempotency key includes drift_type + identifier + yyyy-mm-dd so the same
drift doesn't re-emit every hour — only once per UTC day until resolved.

Gating: only starts when IS_CENTRAL_REGISTRY=True (main.py lifespan).
Same gate as compliance_poller. Manual trigger via
POST /api/v1/admin/federation/drift-scan bypasses the gate.
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from sqlalchemy import select

from ..database import get_db_context
from ..models import FederationLicense, OperatorApplication, PeerRegistry
from ..event_emitter import get_event_emitter
from .leader import try_acquire_leadership

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 3600  # 1 hour

# Grace window for BFS to miss a peer before we call it drift. The background
# topology refresh runs on ~60s cycles (see main.py:_TOPOLOGY_REFRESH_INTERVAL);
# 30 min = ~30 cycles of slack so one transient BFS failure never fires false
# drift, but a truly dead chain drifts within half an hour.
TOPOLOGY_STALENESS_SECONDS = 1800

# Historical constant — retained only so legacy code/tests that import it don't
# break. The frame drift rule NO LONGER uses a staleness threshold; it reads
# authoritative SPIRE state (`spire-server federation list` + `bundle list`).
# SPIRE's internal refresh loop (~75s, configured 2026-04-15) handles the
# "is the bundle fresh" question — we only need to know if the relationship
# and bundle exist. See detect_drift_for_frame() below.
FRAME_BUNDLE_STALENESS_SECONDS = 7200  # deprecated, retained for import compat

DRIFT_TYPE_LICENSE_REVOKED_OP_ACTIVE = "license_revoked_operator_active"
DRIFT_TYPE_OPERATOR_REVOKED_LICENSE_ACTIVE = "operator_revoked_license_active"
DRIFT_TYPE_PEER_INACTIVE_LICENSE_ACTIVE = "peer_inactive_license_active"
DRIFT_TYPE_FRAME_BUNDLE_STALE = "frame_bundle_stale"

# ── §BUNDLECLOCK (2026-09-09) — the dimension the 2026-04-21 rewrite removed ─────────────────
# `frame_bundle_stale` asks whether a bundle EXISTS. It rests on one premise, stated in
# detect_drift_for_frame's own docstring: "If BOTH present -> SPIRE's internal refresh keeps the
# bundle current." That premise is FALSE in exactly the case that matters. `https_spiffe`
# authenticates the peer's bundle endpoint AGAINST THE BUNDLE IT ALREADY HOLDS, so once the
# bundle expires the refresh that would replace it can never be verified — a deadlock, not a lag.
#
# Measured 2026-09-09: frame-b and frame-c held agentvault.com bundles with 0 live roots for
# days. Every mTLS hop where they had to verify something Frame A signed was failing. This
# monitor ran 60 cycles over it and reported `frame_bundle_stale: 0` every time, because a bundle
# that is present and expired is still present.
#
# The clock was never missing from the CODE — `frame_trust_manager.get_bundle_freshness()` reads
# SPIRE directly and has carried §pass53's thresholds since a 4d drift went unnoticed. It was
# missing from the ALARM: its only caller was the admin topology GET, so it computed when a human
# opened Federation Discovery and at no other time. That is the same on-demand weakness the
# 2026-04-21 change was written to remove — deleted from the bad clock, left on the good one.
DRIFT_TYPE_FRAME_BUNDLE_EXPIRING = "frame_bundle_expiring"
DRIFT_TYPE_FRAME_BUNDLE_EXPIRED = "frame_bundle_expired"

# Env-tunable with the chosen value as the default (rule 16). 72h is three refresh attempts of
# headroom at SPIRE's ~84h cadence, and well clear of the 4-6 days these bundles actually carry.
BUNDLE_EXPIRY_WARN_SECONDS = int(os.getenv("FEDERATION_BUNDLE_EXPIRY_WARN_SECONDS", str(72 * 3600)))
# 2026-04-28: peer_url_misconfigured — ACTIVE peer that federation_sync can't
# reach. Most common cause: peer.base_url is missing the mTLS-federation port
# (`:27N43` for cloud operators) so requests land on the public-cert nginx
# (port 443) which doesn't do `ssl_verify_client`, registry sees no client
# identity, and rejects with 401. SPIRE certs are healthy — this is a URL
# data drift, not a cert drift.
PEER_NEVER_SYNCED_THRESHOLD_SECONDS = 1800  # 30 min — federation_sync runs every 5min
DRIFT_TYPE_PEER_URL_MISCONFIGURED = "peer_url_misconfigured"
# 2026-04-30 (wave 10b/10c): operator_network_topology — cloud-op-* nginx-fed
# attached to fewer identity networks than the dual-frame deployment expects,
# OR with a wrong/missing per-frame Docker alias. Caught by inspecting the
# nginx-federation containers via docker-py and comparing actual network
# attachments + Aliases against the canonical pattern:
#   agentvault_identity_network -> alias `op-<name>.op.theprotocol.cloud`
#   frame_b_identity_network    -> alias `op-<name>.frame-b.theprotocol.cloud`
# Sandbox ops (cloud-op-sandbox*) skipped — they're single-frame by design.
DRIFT_TYPE_OPERATOR_NETWORK_TOPOLOGY = "operator_network_topology"


def _is_peer_chain_reachable(peer: PeerRegistry, now: datetime) -> bool:
    """Returns True if BFS saw this peer in a recent cycle.

    A peer with fresh `last_seen_in_topology_at` is chain-reachable through
    some other active peer's published topology, even if its own row is
    INACTIVE (e.g., chain-federated cloud ops after topology reconstruction).
    """
    last_seen = getattr(peer, "last_seen_in_topology_at", None)
    if last_seen is None:
        return False
    return (now - last_seen).total_seconds() <= TOPOLOGY_STALENESS_SECONDS


def detect_drift_for_frame(
    peer: PeerRegistry,
    *,
    spire_has_federation: bool,
    spire_has_bundle: bool,
    now: Optional[datetime] = None,
    bundle_expires_in_seconds: Optional[float] = None,
    bundle_freshness_error: Optional[str] = None,
) -> List[str]:
    """Frame-specific drift detection (f058, rule-signal corrected 2026-04-21).

    Frames are sovereign-by-trust-bundle (MODEL 3). The authoritative signal
    for "this frame's mTLS federation is working" is SPIRE-side state:

      1. SPIRE has a federation relationship configured for the trust domain
         (`spire-server federation list`). Without this, the internal refresh
         loop isn't running for this peer.
      2. SPIRE has the peer's trust bundle imported
         (`spire-server bundle list`). Without this, no certs to verify.

    If BOTH present → SPIRE's internal refresh (every ~75s per the 2026-04-15
    `https_spiffe` config) keeps the bundle current. Drift only fires when one
    or both are missing.

    Why we no longer use `peer.last_seen_in_topology_at`: BFS writeback is an
    on-demand signal (updates when someone hits `/api/v1/public/topology`),
    not a SPIRE-side signal. Using BFS freshness as a proxy for SPIRE bundle
    freshness gave a 3h+ false-positive window when nobody loaded the admin
    UI. The fix queries SPIRE directly (see run_once() for the pre-fetch
    call-site).

    The drift constant name `frame_bundle_stale` is retained for EventStore
    event-type stability; the meaning has shifted from "refresh overdue" to
    "relationship or bundle absent from SPIRE."

    §BUNDLECLOCK (2026-09-09) — THE PREMISE ABOVE IS FALSE WHEN IT MATTERS MOST.
    "If BOTH present -> SPIRE's internal refresh keeps the bundle current" holds only while the
    bundle is still valid: `https_spiffe` authenticates the peer's endpoint AGAINST THE BUNDLE
    THE CALLER ALREADY HOLDS, so an EXPIRED bundle can never fetch its own replacement. That is
    a deadlock, and a present-but-expired bundle satisfies every existence test here.

    So the time dimension is back, but from the AUTHORITATIVE source this time rather than the
    BFS proxy that was rightly deleted in 2026-04-21: `bundle_expires_in_seconds` comes from
    SPIRE's own cert (`get_bundle_freshness`), so it cannot false-positive on a quiet admin UI —
    the exact failure the 2026-04-21 rewrite was fixing.

    THREE STATES, NOT TWO. `bundle_freshness_error` (or a None reading) means NOT MEASURED, and
    it returns no flag at all: "I could not read the clock" is not "the clock says fine", and a
    monitor that renders them identically is how this class hid for months. The caller logs it.

    Returns a list of drift flags (empty list if healthy).
    """
    flags: List[str] = []
    _ = now  # reserved for future use; signature kept stable with operator rule

    if peer is None or peer.peer_type != "frame":
        return flags
    # INACTIVE frames are decommissioned on purpose — not drift.
    if (peer.status or "").upper() != "ACTIVE":
        return flags

    if not (spire_has_federation and spire_has_bundle):
        flags.append(DRIFT_TYPE_FRAME_BUNDLE_STALE)
        # an absent bundle has no clock to read; the absence IS the finding
        return flags

    # NOT MEASURED is its own state and must never read as healthy.
    if bundle_freshness_error or bundle_expires_in_seconds is None:
        return flags

    if bundle_expires_in_seconds <= 0:
        # 🔴 terminal: SPIRE cannot recover this on its own, ever. Needs `bundle set`.
        flags.append(DRIFT_TYPE_FRAME_BUNDLE_EXPIRED)
    elif bundle_expires_in_seconds < BUNDLE_EXPIRY_WARN_SECONDS:
        flags.append(DRIFT_TYPE_FRAME_BUNDLE_EXPIRING)

    return flags


def detect_drift_for_operator(
    app: Optional[OperatorApplication],
    license: Optional[FederationLicense],
    peer: Optional[PeerRegistry],
    *,
    now: Optional[datetime] = None,
) -> List[str]:
    """Apply the three drift rules to a single operator's state tuple.

    Pure function with no DB access. Shared by the hourly monitor and the
    read-only lifecycle endpoints so drift semantics stay in one place.

    ``now`` is a timezone-aware datetime used for staleness comparison in
    rule 3. Defaults to ``datetime.now(timezone.utc)`` — override for tests.
    """
    flags: List[str] = []
    _now = now or datetime.now(timezone.utc)

    # Rule 1: license revoked while operator app is still live
    if (license is not None
        and license.status == "revoked"
        and app is not None
        and app.status in ("approved", "suspended")):
        flags.append(DRIFT_TYPE_LICENSE_REVOKED_OP_ACTIVE)

    # Rule 2: operator revoked but license still live
    if (app is not None
        and app.status == "revoked"
        and license is not None
        and license.status in ("active", "suspended")):
        flags.append(DRIFT_TYPE_OPERATOR_REVOKED_LICENSE_ACTIVE)

    # Rule 3: peer INACTIVE + license ACTIVE is only drift when the peer is
    # ALSO not reachable via chain. A peer's `last_seen_in_topology_at` is
    # bumped by BFS writeback every cycle it appears in the fresh topology
    # fetch; if fresh (≤ TOPOLOGY_STALENESS_SECONDS), the peer is
    # chain-federated and healthy — NOT partial teardown.
    #
    # Historical note: before 2026-04-21 this rule fired on every INACTIVE
    # peer with an active license, which falsely flagged every chain-federated
    # operator. That drove an anti-pattern of direct-peering every cloud op
    # to the main frame to "fix" the drift, collapsing chain topology back
    # to hub-and-spoke. The chain-reachability check breaks that kill chain.
    if (peer is not None
        and peer.status == "INACTIVE"
        and license is not None
        and license.status == "active"):
        if not _is_peer_chain_reachable(peer, _now):
            flags.append(DRIFT_TYPE_PEER_INACTIVE_LICENSE_ACTIVE)

    return flags


def _derive_operator_did_from_app(app: OperatorApplication) -> str:
    """Match the DID-derivation used by operator_applications._derive_operator_did."""
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


async def _find_license_for_app(db, app: OperatorApplication) -> Optional[FederationLicense]:
    """Try cloud-prefix DID first, fall back to operator-prefix for legacy rows."""
    candidates = [
        f"did:theprotocol:{'cloud' if getattr(app, 'cloud_hosted', False) else 'operator'}:"
        + (
            (app.docker_registry_username or "").removeprefix("operator-")
            if app.docker_registry_username
            else "".join(
                c if c.isalnum() or c == "-" else "-"
                for c in (app.name or "").lower().strip()
            ).strip("-")[:40]
        )
    ]
    for did in candidates:
        if not did:
            continue
        result = await db.execute(
            select(FederationLicense).where(FederationLicense.operator_did == did)
        )
        lic = result.scalar_one_or_none()
        if lic is not None:
            return lic
    return None


async def _emit_drift(
    emitter,
    *,
    drift_type: str,
    license_id: Optional[str],
    application_id: Optional[str],
    peer_id: Optional[int],
    license_status: Optional[str],
    operator_status: Optional[str],
    peer_status: Optional[str],
    operator_name: Optional[str] = None,
    operator_did: Optional[str] = None,
    bfs_last_seen: Optional[datetime] = None,
    spire_has_federation: Optional[bool] = None,
    spire_has_bundle: Optional[bool] = None,
    extra_data: Optional[dict] = None,
) -> None:
    """Emit a FederationStateDriftDetected event with per-day idempotency.

    ``bfs_last_seen`` is the peer's ``last_seen_in_topology_at`` at detection
    time; carried for operator drift rules (1/2/3) which still use it for
    chain-reachability context. For frame drift (rule 4) this field is set
    to None by the caller — the SPIRE-side signals below replace it.

    ``spire_has_federation`` / ``spire_has_bundle`` — added 2026-04-21. Frame
    drift rule (`frame_bundle_stale`) now reflects SPIRE state rather than
    BFS staleness, so consumers inspecting the event payload can see which
    half of the signal broke (relationship missing vs. bundle missing).
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    identifier = license_id or application_id or (f"peer:{peer_id}" if peer_id else "unknown")
    idempotency_key = f"drift-{drift_type}-{identifier}-{today}"

    aggregate_id = (
        f"federation_license:{license_id}" if license_id
        else f"operator_application:{application_id}" if application_id
        else f"peer_registry:{peer_id}"
    )

    payload = {
        "drift_type": drift_type,
        "license_id": license_id,
        "application_id": application_id,
        "peer_id": peer_id,
        "license_status": license_status,
        "operator_status": operator_status,
        "peer_status": peer_status,
        "operator_name": operator_name,
        "operator_did": operator_did,
        "bfs_last_seen": bfs_last_seen.isoformat() if bfs_last_seen else None,
        "bfs_reachable": False,  # true drifts by definition aren't chain-reachable
        "spire_has_federation": spire_has_federation,
        "spire_has_bundle": spire_has_bundle,
        "detected_at": datetime.now(timezone.utc).isoformat(),
    }
    if extra_data:
        payload.update(extra_data)
    try:
        await emitter.emit(
            event_type="FederationStateDriftDetected",
            aggregate_id=aggregate_id,
            aggregate_type="FederationLicense" if license_id else "OperatorApplication",
            data=payload,
            idempotency_key=idempotency_key,
        )
        logger.info(
            f"[DriftMonitor] Emitted {drift_type} drift: {identifier} "
            f"(license={license_status} / operator={operator_status} / peer={peer_status})"
        )
    except Exception as exc:
        logger.error(f"[DriftMonitor] Failed to emit drift {idempotency_key}: {exc}")


def _expected_aliases_for(op_name: str, attached: Optional[dict] = None) -> dict:
    """Canonical per-frame Docker aliases for a cloud operator's nginx-federation.

    §57 sweep (2026-07-30): this used to demand `frame_b_identity_network` from
    EVERY operator, which is only true for Frame A/B ops. Frame C's four ops join
    `frame_c_identity_network` and op-demo joins `hetzner_frame_network_identity`,
    so the monitor reported **5 live false-positive drifts every cycle** — noise
    that masks real drift, which is the whole point of the check.

    An operator attaches to the cluster network plus EXACTLY ONE parent-frame
    identity network. The parent is therefore read off the container rather than
    assumed, and only the alias convention is asserted. That convention was
    MEASURED across all 14 running ops, not inferred:
      * `frame_b_identity_network`         -> `op-X.frame-b.theprotocol.cloud` (9/9)
      * every other frame identity network -> `op-X.op.theprotocol.cloud`      (5/5)
    The asymmetry is real and predates this fix; it is recorded here rather than
    normalised, because renaming a live Docker alias breaks peer resolution.

    `attached` is the container's `NetworkSettings.Networks`. When it is None the
    caller gets the cluster-network expectation only — never a wrong-frame demand.
    """
    expected = {"agentvault_identity_network": f"op-{op_name}.op.theprotocol.cloud"}
    if not attached:
        return expected

    frame_nets = [
        n for n in attached
        if n != "agentvault_identity_network"
        and ("identity_network" in n or "network_identity" in n)
    ]
    if not frame_nets:
        # No parent frame reachable at all — a genuine defect. Name the absence
        # explicitly so the drift row is actionable.
        expected["<parent-frame identity network>"] = f"op-{op_name}.op.theprotocol.cloud"
        return expected

    for net in frame_nets:
        expected[net] = (
            f"op-{op_name}.frame-b.theprotocol.cloud"
            if net == "frame_b_identity_network"
            else f"op-{op_name}.op.theprotocol.cloud"
        )
    return expected


DOCKER_SOCKET = "/var/run/docker.sock"


async def _check_operator_network_topology() -> List[dict]:
    """Inspect every cloud-op-* nginx-federation container for dual-frame
    Docker network/alias drift.

    Returns a list of offender dicts:
        {
          "operator_name": "london",
          "container": "cloud-op-op-london-nginx-federation",
          "missing_networks": ["frame_b_identity_network"],
          "alias_issues": [
            {"network": "agentvault_identity_network", "expected": "...", "actual": [...]}
          ],
          "attached_networks": [...],
        }

    No-op if either identity network is absent on this host (single-frame
    deployment — drift rule doesn't apply). Sandbox operators are skipped
    by name-prefix because they live on `sandbox_identity_network` only.

    Uses docker-py via asyncio.to_thread (same pattern as frame_trust_manager).
    """
    def _blocking() -> List[dict]:
        # §F6 (2026-09-27, his words "i approve to finish f6 implementation on sandbox"): a registry with NO docker socket
        # is F6's posture (the frame runner holds its host reach), not a fault, so this check stands down at DEBUG. It
        # judges Frame A's and Frame B's identity networks and the legacy cloud-op-op-* sidecars, the retiring network's
        # topology. A socket that exists and fails is still a WARNING below.
        if not os.path.exists(DOCKER_SOCKET):
            logger.debug("[DriftMonitor] no docker socket on this registry (the frame runner holds its host reach): "
                         "the dual-frame operator topology check is not run here")
            return []
        try:
            import docker  # type: ignore
        except ImportError:
            logger.warning(
                "[DriftMonitor] docker-py not installed — skipping network topology check"
            )
            return []

        try:
            client = docker.DockerClient(base_url="unix://var/run/docker.sock")
        except Exception as e:
            logger.warning(
                f"[DriftMonitor] Could not connect to docker socket "
                f"(skipping topology check): {e}"
            )
            return []

        # Confirm both identity networks exist before judging anything
        present_nets = {n.name for n in client.networks.list()}
        required = {"agentvault_identity_network", "frame_b_identity_network"}
        if not required.issubset(present_nets):
            logger.debug(
                f"[DriftMonitor] Single-frame host (networks: {present_nets & required}) "
                f"— skipping operator topology drift"
            )
            return []

        offenders: List[dict] = []
        for cnt in client.containers.list(ignore_removed=True):
            name = cnt.name
            if not name.endswith("-nginx-federation"):
                continue
            # Only judge prod cloud operators. Sandbox + frame-b mainframe nginx-fed
            # legitimately attach differently.
            if not name.startswith("cloud-op-op-"):
                continue
            try:
                op_name = name[len("cloud-op-op-"):-len("-nginx-federation")]
            except Exception:
                continue
            if not op_name:
                continue

            attached = (cnt.attrs.get("NetworkSettings") or {}).get("Networks") or {}
            expected = _expected_aliases_for(op_name, attached)
            missing_networks: List[str] = []
            alias_issues: List[dict] = []
            for net_name, expected_alias in expected.items():
                if net_name not in attached:
                    missing_networks.append(net_name)
                    continue
                aliases = attached[net_name].get("Aliases") or []
                if expected_alias not in aliases:
                    alias_issues.append({
                        "network": net_name,
                        "expected": expected_alias,
                        "actual": aliases,
                    })

            if missing_networks or alias_issues:
                offenders.append({
                    "operator_name": op_name,
                    "container": name,
                    "missing_networks": missing_networks,
                    "alias_issues": alias_issues,
                    "attached_networks": list(attached.keys()),
                })

        return offenders

    return await asyncio.to_thread(_blocking)


async def run_once() -> Tuple[int, dict]:
    """Execute one drift-scan cycle. Returns (total_drifts, per_type_counts).

    Self-gates: if federation_licenses has zero rows, short-circuits (skips cycle).
    This makes the task safe to instantiate on any registry without causing
    false positives on non-licensing instances — the IS_CENTRAL_REGISTRY gate
    in main.py is the authoritative on/off switch for the hourly loop.
    """
    counts = {
        DRIFT_TYPE_LICENSE_REVOKED_OP_ACTIVE: 0,
        DRIFT_TYPE_OPERATOR_REVOKED_LICENSE_ACTIVE: 0,
        DRIFT_TYPE_PEER_INACTIVE_LICENSE_ACTIVE: 0,
        DRIFT_TYPE_FRAME_BUNDLE_STALE: 0,
        DRIFT_TYPE_FRAME_BUNDLE_EXPIRING: 0,
        DRIFT_TYPE_FRAME_BUNDLE_EXPIRED: 0,
        DRIFT_TYPE_PEER_URL_MISCONFIGURED: 0,
        DRIFT_TYPE_OPERATOR_NETWORK_TOPOLOGY: 0,
    }
    total = 0

    async with get_db_context() as db:
        emitter = get_event_emitter()
        cycle_started = datetime.now(timezone.utc)

        # Frame drift (check 4) runs regardless of whether licenses exist —
        # frames are sovereign-by-trust-bundle. We do it first so it always
        # fires even if the license self-gate below short-circuits.
        frame_peers_early = (await db.execute(
            select(PeerRegistry).where(
                PeerRegistry.peer_type == "frame",
                PeerRegistry.status == "ACTIVE",
            )
        )).scalars().all()

        # Pre-fetch SPIRE state ONCE per cycle (2 docker exec calls, not per-peer).
        # If either query fails, skip frame drift this cycle — don't false-positive
        # on our own SPIRE/docker outage. Operator checks continue normally.
        spire_federations: set = set()
        spire_bundles: set = set()
        spire_queryable = True
        if frame_peers_early:
            try:
                from ..services.frame_trust_manager import get_frame_trust_manager
                mgr = get_frame_trust_manager()
                fed_list, fed_err = await mgr.list_federation_relationships()
                bun_list, bun_err = await mgr.list_federated_trust_domains()
                if fed_err or bun_err:
                    logger.warning(
                        f"[DriftMonitor] SPIRE query failed — skipping frame drift this cycle. "
                        f"federation_err={fed_err!r} bundle_err={bun_err!r}"
                    )
                    spire_queryable = False
                else:
                    spire_federations = {td.lower() for td in fed_list}
                    spire_bundles = {td.lower() for td in bun_list}
            except Exception as e:
                logger.warning(
                    f"[DriftMonitor] SPIRE manager error — skipping frame drift this cycle: {e}",
                    exc_info=True,
                )
                spire_queryable = False

        # §BUNDLECLOCK — read each present bundle's OWN expiry, once per cycle. This is the
        # clock `get_bundle_freshness` has always computed; until now its only caller was the
        # admin topology GET, so it ran when a human opened a page and never on a schedule.
        freshness_by_td: dict = {}
        if spire_queryable and frame_peers_early:
            try:
                from ..services.frame_trust_manager import get_frame_trust_manager as _gftm
                _mgr = _gftm()
                _tds = sorted({
                    (getattr(fp, "trust_domain", "") or "").lower()
                    for fp in frame_peers_early
                    if (getattr(fp, "trust_domain", "") or "").lower() in spire_bundles
                })
                if _tds:
                    _res = await asyncio.gather(
                        *(_mgr.get_bundle_freshness(_td) for _td in _tds),
                        return_exceptions=True,
                    )
                    for _td, _fr in zip(_tds, _res):
                        freshness_by_td[_td] = _fr
            except Exception as e:
                # LOUD, and it leaves freshness_by_td EMPTY, which the rule reads as NOT
                # MEASURED rather than healthy. "I could not read the clock" must not look
                # like "the clock says fine" — that equivalence is what hid this for months.
                logger.warning(
                    f"[DriftMonitor] bundle freshness unreadable this cycle — expiry NOT MEASURED "
                    f"(existence checks unaffected): {e}", exc_info=True,
                )

        if spire_queryable:
            for frame_peer in frame_peers_early:
                td = (getattr(frame_peer, "trust_domain", "") or "").lower()
                has_fed = td in spire_federations
                has_bun = td in spire_bundles
                _fr = freshness_by_td.get(td)
                if isinstance(_fr, Exception):
                    exp_in, fr_err = None, f"{type(_fr).__name__}: {_fr}"
                elif _fr is not None:
                    exp_in, fr_err = getattr(_fr, "expires_in_seconds", None), getattr(_fr, "error", None)
                else:
                    exp_in, fr_err = None, None
                if fr_err:
                    logger.warning(
                        f"[DriftMonitor] {td}: bundle expiry NOT MEASURED ({fr_err}) — this is "
                        f"not a verdict about the bundle"
                    )
                flags = detect_drift_for_frame(
                    frame_peer,
                    spire_has_federation=has_fed,
                    spire_has_bundle=has_bun,
                    now=cycle_started,
                    bundle_expires_in_seconds=exp_in,
                    bundle_freshness_error=fr_err,
                )
                for _dt in (DRIFT_TYPE_FRAME_BUNDLE_STALE,
                            DRIFT_TYPE_FRAME_BUNDLE_EXPIRED,
                            DRIFT_TYPE_FRAME_BUNDLE_EXPIRING):
                    if _dt not in flags:
                        continue
                    _extra = None
                    if _dt in (DRIFT_TYPE_FRAME_BUNDLE_EXPIRED, DRIFT_TYPE_FRAME_BUNDLE_EXPIRING):
                        _extra = {
                            "trust_domain": td,
                            "expires_in_seconds": int(exp_in) if exp_in is not None else None,
                            "expires_in_hours": round(exp_in / 3600.0, 1) if exp_in is not None else None,
                            "not_after": getattr(_fr, "not_after", None).isoformat()
                                          if getattr(_fr, "not_after", None) else None,
                            # say what the operator has to DO: an expired federated bundle is the
                            # one state SPIRE cannot climb out of by itself.
                            "recovery": ("spire-server bundle set -id spiffe://%s (the refresh "
                                         "authenticates against this bundle, so it cannot "
                                         "self-heal once expired)" % td)
                                        if _dt == DRIFT_TYPE_FRAME_BUNDLE_EXPIRED else
                                        "no action if SPIRE refreshes before expiry; re-check next cycle",
                        }
                    await _emit_drift(
                        emitter,
                        drift_type=_dt,
                        license_id=None,
                        application_id=None,
                        peer_id=frame_peer.id,
                        license_status=None,
                        operator_status=None,
                        peer_status=frame_peer.status,
                        operator_name=frame_peer.name,
                        operator_did=None,
                        bfs_last_seen=None,  # deprecated for frame drift; SPIRE signals below
                        spire_has_federation=has_fed,
                        spire_has_bundle=has_bun,
                        extra_data=_extra,
                    )
                    counts[_dt] += 1
                    total += 1

        # Cheap self-gate for license-based checks: if no licenses exist, skip.
        any_lic_result = await db.execute(select(FederationLicense.id).limit(1))
        if any_lic_result.scalar_one_or_none() is None:
            logger.info("[DriftMonitor] No federation_licenses rows — skipping license checks.")
            cycle_elapsed_ms = int(
                (datetime.now(timezone.utc) - cycle_started).total_seconds() * 1000
            )
            logger.info(
                f"[DriftMonitor] Frame-only cycle complete in {cycle_elapsed_ms}ms: "
                f"{total} frame drifts"
            )
            return total, counts

        # ── Check 1: license revoked, operator still active ───────────────
        revoked_licenses_q = select(FederationLicense).where(
            FederationLicense.status == "revoked"
        )
        revoked_licenses = (await db.execute(revoked_licenses_q)).scalars().all()
        for lic in revoked_licenses:
            app_q = select(OperatorApplication).where(
                OperatorApplication.status.in_(("approved", "suspended"))
            )
            apps = (await db.execute(app_q)).scalars().all()
            for app in apps:
                if _derive_operator_did_from_app(app) == lic.operator_did:
                    await _emit_drift(
                        emitter,
                        drift_type=DRIFT_TYPE_LICENSE_REVOKED_OP_ACTIVE,
                        license_id=lic.id,
                        application_id=app.id,
                        peer_id=None,
                        license_status=lic.status,
                        operator_status=app.status,
                        peer_status=None,
                        operator_name=app.name,
                        operator_did=lic.operator_did,
                    )
                    counts[DRIFT_TYPE_LICENSE_REVOKED_OP_ACTIVE] += 1
                    total += 1
                    break

        # ── Check 2: operator revoked, license still active/suspended ─────
        revoked_apps_q = select(OperatorApplication).where(
            OperatorApplication.status == "revoked"
        )
        revoked_apps = (await db.execute(revoked_apps_q)).scalars().all()
        for app in revoked_apps:
            lic = await _find_license_for_app(db, app)
            if lic and lic.status in ("active", "suspended"):
                await _emit_drift(
                    emitter,
                    drift_type=DRIFT_TYPE_OPERATOR_REVOKED_LICENSE_ACTIVE,
                    license_id=lic.id,
                    application_id=app.id,
                    peer_id=None,
                    license_status=lic.status,
                    operator_status=app.status,
                    peer_status=None,
                    operator_name=app.name,
                    operator_did=lic.operator_did,
                )
                counts[DRIFT_TYPE_OPERATOR_REVOKED_LICENSE_ACTIVE] += 1
                total += 1

        # ── Check 3: peer INACTIVE, license still active, AND not chain-reachable ──
        # The chain-reachability gate (via last_seen_in_topology_at) is what
        # separates partial teardowns (true drift) from chain-federated peers
        # (legitimate topology, not drift).
        inactive_peers_q = select(PeerRegistry).where(PeerRegistry.status == "INACTIVE")
        inactive_peers = (await db.execute(inactive_peers_q)).scalars().all()
        # Match peer to operator application by name (same mechanism cloud_provisioner uses)
        for peer in inactive_peers:
            matching_app_q = select(OperatorApplication).where(
                OperatorApplication.name == peer.name
            )
            matching_app = (await db.execute(matching_app_q)).scalar_one_or_none()
            if matching_app is None:
                continue
            lic = await _find_license_for_app(db, matching_app)
            if lic and lic.status == "active":
                # Suppress if BFS saw this peer recently (chain-federated).
                if _is_peer_chain_reachable(peer, cycle_started):
                    continue
                await _emit_drift(
                    emitter,
                    drift_type=DRIFT_TYPE_PEER_INACTIVE_LICENSE_ACTIVE,
                    license_id=lic.id,
                    application_id=matching_app.id,
                    peer_id=peer.id,
                    license_status=lic.status,
                    operator_status=matching_app.status,
                    peer_status=peer.status,
                    operator_name=matching_app.name,
                    operator_did=lic.operator_did,
                    bfs_last_seen=getattr(peer, "last_seen_in_topology_at", None),
                )
                counts[DRIFT_TYPE_PEER_INACTIVE_LICENSE_ACTIVE] += 1
                total += 1

        # (Frame drift already scanned above the license gate.)

        # ── Check 5: ACTIVE peer that federation_sync can't reach ────────────
        # Detects the URL-data-drift class (most common: peer.base_url missing
        # the mTLS-federation port). Signal: peer.status == 'ACTIVE' AND
        # last_synced_at is NULL or older than the never-synced threshold.
        # Skips frames (covered by frame_bundle_stale) and registries that
        # legitimately don't sync (operator-side Registry-A entries which use
        # a different inbound path).
        #
        # 2026-04-30 (wave 10c): also suppress when federation_sync intentionally
        # skips the peer via the license gate. BFS-discovered cross-frame ops
        # (e.g. Frame-B-provisioned ops appearing in Frame A's topology) have
        # no FederationLicense row in this frame's DB by design — they're
        # licensed by their home frame. federation_sync.py:202 skips them with
        # "license not active". That's not URL drift; it's the gate working.
        # Use the same gate the sync worker uses so the rule and the worker
        # agree on which peers are syncable.
        from ..services.federation_license_gate import (
            resolve_peer_operator_did,
            is_peer_license_active,
        )
        # the syncer's OTHER gate — see §DRIFTSKIP below
        from .federation_sync import is_peer_frames_operator

        url_drift_threshold = cycle_started - timedelta(
            seconds=PEER_NEVER_SYNCED_THRESHOLD_SECONDS
        )
        # ⚠ ALL ACTIVE peers, frames included — the frame rows are not candidates themselves, but
        # `is_peer_frames_operator` needs them to know which trust domains belong to a federated
        # frame. Selecting only non-frames (as this did until 2026-09-09) makes that question
        # unanswerable, which is how the skip below went unmirrored.
        active_peers_q = select(PeerRegistry).where(PeerRegistry.status == "ACTIVE")
        all_active = (await db.execute(active_peers_q)).scalars().all()
        active_peers = [
            p for p in all_active
            if (getattr(p, "peer_type", "") or "").lower() != "frame"
        ]
        not_dialled = 0
        for peer in active_peers:
            ls = getattr(peer, "last_synced_at", None)
            if ls is not None and ls > url_drift_threshold:
                continue  # synced recently, healthy

            # ── §DRIFTSKIP (2026-09-09) — THE WORKER'S OTHER GATE ────────────────────────────
            # The comment below has always said "mirror the worker's gate so the two agree on
            # syncable set". It mirrored the LICENCE gate and not this one, and §BATCH8 item 4
            # added a second skip on 2026-09-06: `federation_sync` deliberately does not dial a
            # `discovered` row whose trust domain belongs to an ACTIVE `frame` row, because that
            # row is that frame's own operator — its cards arrive through the frame's export and
            # a direct pull is "refused 401 every cycle by a proxy that never federated with us".
            #
            # So `last_synced_at` for those peers can NEVER advance, and this rule reported them
            # as drift for ever. Measured on EU 2026-09-09: hochiminh and shenzhen, 732 minutes
            # stale, and 4 of 4 federation drift events in 48h were this one false positive —
            # the whole feed was noise, which is how a real drift gets ignored.
            #
            # `is_peer_frames_operator` lives at module scope in federation_sync precisely so
            # every caller can ask the same question. It had exactly one caller until now.
            if is_peer_frames_operator(peer, all_active):
                not_dialled += 1
                continue

            # License-gate check: if federation_sync would skip this peer for
            # license reasons, the stale last_synced_at is expected, not drift.
            # Mirror the worker's gate so the two agree on syncable set.
            try:
                resolved_did = await resolve_peer_operator_did(db, peer)
                if resolved_did is not None and not await is_peer_license_active(db, resolved_did):
                    logger.debug(
                        f"[DriftMonitor] Suppressing peer_url_misconfigured for "
                        f"{peer.name} ({resolved_did}) — license-gated, expected stale"
                    )
                    continue
            except Exception as gate_exc:
                # Gate check failed — fall through to emitting (false positive
                # is preferable to silent drop on diagnostic infra failures).
                logger.warning(
                    f"[DriftMonitor] License gate check failed for peer "
                    f"{peer.name}: {gate_exc} — emitting drift anyway"
                )

            # Match peer to operator application (best-effort) for context
            matching_app = (await db.execute(
                select(OperatorApplication).where(
                    OperatorApplication.name == peer.name
                )
            )).scalar_one_or_none()
            lic = await _find_license_for_app(db, matching_app) if matching_app else None
            await _emit_drift(
                emitter,
                drift_type=DRIFT_TYPE_PEER_URL_MISCONFIGURED,
                license_id=lic.id if lic else None,
                application_id=matching_app.id if matching_app else None,
                peer_id=peer.id,
                license_status=lic.status if lic else None,
                operator_status=matching_app.status if matching_app else None,
                peer_status=peer.status,
                operator_name=peer.name,
                operator_did=lic.operator_did if lic else None,
            )
            counts[DRIFT_TYPE_PEER_URL_MISCONFIGURED] += 1
            total += 1

        # A filter that removes rows must SAY how many, or the next reader cannot tell a quiet
        # network from a suppressed one ([[feedback_a_gate_that_removes_everything_must_say_so]]).
        if not_dialled:
            logger.info(
                "[DriftMonitor] %d peer(s) not dialled by design (a frame's own operator reached "
                "through that frame's export) — excluded from peer_url_misconfigured, not silenced",
                not_dialled,
            )

        # ── Check 6: operator network topology drift (wave 10c) ─────────────
        # Inspects every cloud-op-* nginx-federation container for dual-frame
        # Docker network/alias drift. Closes the regression class that wave 10b
        # patched: ops missing `frame_b_identity_network` attachment, or with
        # misaligned per-frame Docker aliases.
        try:
            offenders = await _check_operator_network_topology()
        except Exception as e:
            logger.warning(
                f"[DriftMonitor] Operator topology check raised — "
                f"skipping this cycle: {e}",
                exc_info=True,
            )
            offenders = []

        for off in offenders:
            op_name = off.get("operator_name") or ""
            container = off.get("container") or ""
            # Match to operator application/peer/license for context (best-effort).
            # Operator application "name" can be human (e.g. "London") or slug-y;
            # peer.name follows registry naming (e.g. "registry-op-london"). We
            # try slug-aware matching across both — failure is non-fatal.
            matching_app: Optional[OperatorApplication] = None
            apps = (await db.execute(select(OperatorApplication))).scalars().all()
            for app in apps:
                slug = "".join(
                    c if c.isalnum() or c == "-" else "-"
                    for c in (app.name or "").lower().strip()
                ).strip("-")[:40]
                if slug == op_name or slug == f"op-{op_name}":
                    matching_app = app
                    break

            matching_peer: Optional[PeerRegistry] = None
            for cand in [f"registry-op-{op_name}", f"op-{op_name}", op_name]:
                p = (await db.execute(
                    select(PeerRegistry).where(PeerRegistry.name == cand)
                )).scalar_one_or_none()
                if p is not None:
                    matching_peer = p
                    break

            lic = await _find_license_for_app(db, matching_app) if matching_app else None

            await _emit_drift(
                emitter,
                drift_type=DRIFT_TYPE_OPERATOR_NETWORK_TOPOLOGY,
                license_id=lic.id if lic else None,
                application_id=matching_app.id if matching_app else None,
                peer_id=matching_peer.id if matching_peer else None,
                license_status=lic.status if lic else None,
                operator_status=matching_app.status if matching_app else None,
                peer_status=matching_peer.status if matching_peer else None,
                operator_name=op_name,
                operator_did=lic.operator_did if lic else None,
                extra_data={
                    "container": container,
                    "missing_networks": off.get("missing_networks") or [],
                    "alias_issues": off.get("alias_issues") or [],
                    "attached_networks": off.get("attached_networks") or [],
                },
            )
            counts[DRIFT_TYPE_OPERATOR_NETWORK_TOPOLOGY] += 1
            total += 1

        cycle_elapsed_ms = int(
            (datetime.now(timezone.utc) - cycle_started).total_seconds() * 1000
        )
        logger.info(
            f"[DriftMonitor] Cycle complete in {cycle_elapsed_ms}ms: "
            f"{total} drifts ({counts})"
        )

    return total, counts


class LicenseDriftMonitor:
    """Hourly drift scanner. Leader-elected so only one worker runs cycles."""

    def __init__(self):
        self.running = False
        self.task: Optional[asyncio.Task] = None

    async def _run_loop(self):
        logger.info("[DriftMonitor] Started (hourly, leader-elected).")
        from . import vitals as _vitals
        await _vitals.register("license_drift_monitor", module=__name__, pattern="hand-rolled",
                               interval_sec=POLL_INTERVAL_SECONDS, enabled=True)
        while self.running:
            try:
                if not await try_acquire_leadership("license_drift_monitor"):
                    await asyncio.sleep(POLL_INTERVAL_SECONDS)
                    continue
                async with _vitals.cycle("license_drift_monitor"):
                    await run_once()
                # §FEDLICENCE improvement 11: rotations are rare, so the plain key of one whose replay window closed is
                # also cleared here, hourly, not only at the next rotation. Its own guard: a sweep failure never fails the cycle.
                try:
                    from ..routers.federation_license_self import clear_expired_rotation_keys
                    async with get_db_context() as _db:
                        await clear_expired_rotation_keys(_db)
                except Exception as _exc:  # noqa: BLE001
                    logger.warning(f"[DriftMonitor] rotation key sweep failed: {_exc}")
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"[DriftMonitor] Cycle failed: {exc}", exc_info=True)
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
        logger.info("[DriftMonitor] Stopped.")

    async def start(self):
        if self.running:
            return
        self.running = True
        self.task = asyncio.create_task(self._run_loop())

    async def stop(self):
        self.running = False
        if self.task is not None:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None


_instance: Optional[LicenseDriftMonitor] = None


def get_license_drift_monitor() -> LicenseDriftMonitor:
    global _instance
    if _instance is None:
        _instance = LicenseDriftMonitor()
    return _instance


async def start_license_drift_monitor() -> None:
    """Called from main.py startup (IS_CENTRAL_REGISTRY=True only)."""
    await get_license_drift_monitor().start()


async def stop_license_drift_monitor() -> None:
    """Called from main.py shutdown."""
    await get_license_drift_monitor().stop()
