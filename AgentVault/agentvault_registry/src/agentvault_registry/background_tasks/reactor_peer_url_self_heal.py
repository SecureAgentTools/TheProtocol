"""
Reactor: peer_url_misconfigured drift → self-healing UPDATE
============================================================
Subscribes to `FederationStateDriftDetected` events and acts only on the
`peer_url_misconfigured` drift_type. For each affected peer, probes the
canonical mTLS-federation port (27N43 convention) using the local SPIRE
SVID. The first candidate that returns HTTP 200 wins — we UPDATE
`peer_registries.base_url` to that URL and emit
`PeerRegistryUrlAutoCorrected` for audit.

This is the self-healing layer the user wanted after 2026-04-28's discovery
that 7 of 8 operator peer URLs were stored without the mTLS port. License
drift_monitor *detects*; this reactor *fixes*.

Idempotent: per-day at the emit side (license_drift_monitor's idempotency
key) so the reactor sees at most one event per peer per day. Within the
reactor, the UPDATE is a no-op if base_url is already correct.

Authority safeguards:
- Only acts on drift_type=peer_url_misconfigured (other drift types are
  handled by reactor_drift_detected.py and friends — separate concerns)
- Only operates on peer_type != 'frame' (frames have their own drift class
  and a different remediation path — SPIRE bundle import)
- Requires SPIRE SVID; bails if cert isn't available (don't probe over plain
  HTTPS without mTLS — registry would reject anyway)
- Logs every action including no-action paths so operators can audit
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import List, Optional
from urllib.parse import urlparse

import httpx
from sqlalchemy import select, update

# §pass46 (2026-05-19) — Probe budget. Internal Docker network RTT is <50ms;
# 3s is generous for one round-trip and bounds worst-case per-event latency
# when all candidates fail (10 candidates × 3s ≈ 30s if serial, ~3s if
# concurrent via asyncio.gather).
PROBE_TIMEOUT_SEC = 3.0

from ..database import AsyncSessionLocal
from ..event_emitter import get_event_emitter
from ..identity import svid_client
from ..models import PeerRegistry
from .reactor_base import EventStoreReactor

logger = logging.getLogger(__name__)


# Canonical port map — matches cloud_provisioner's 27N43 naming convention.
# These are the published ports of each operator's nginx-federation sidecar
# (mapping to container port 8443 with ssl_verify_client on).
# §RENAMEFIX (2026-08-19) — keyed on peer.name, so the four 2026 renames had
# silently fallen out of this map (op-tokyo->op-newyork, op-singapore->
# op-losangeles, op-seoul->op-houston, op-sydney->op-chicago) and were paying an
# 8-probe FALLBACK_PORTS sweep on every self-heal. The PORTS are unchanged (a
# rename never moved a container); only the keys catch up with the peer names.
KNOWN_OPERATOR_PORTS = {
    "op-newyork": 27043,      # container cloud-op-op-tokyo
    "op-losangeles": 27143,   # container cloud-op-op-singapore
    "op-washington": 27243,
    "op-london": 27343,
    "op-paris": 27443,
    "op-berlin": 27543,
    "op-chicago": 27643,      # container cloud-op-op-sydney
    "op-houston": 27743,      # container cloud-op-op-seoul
}

# Fallback ports tried if peer.name isn't in the map (e.g., a future operator
# we don't know about, or Frame-B which uses 30443/8443).
FALLBACK_PORTS: List[int] = list(KNOWN_OPERATOR_PORTS.values()) + [30443, 8443]


def _candidate_urls_for_peer(peer: PeerRegistry) -> List[str]:
    """Build the ordered list of candidate base_urls to probe.

    §pass46 (2026-05-19): for peers with a known canonical port (op-X in
    KNOWN_OPERATOR_PORTS) we probe ONLY the canonical + current URL. The
    static map IS the authoritative answer for these — fallback sweeps
    waste 8 unnecessary probes when both succeed. For unknown peers (Frame-B,
    future operators) we keep the full FALLBACK_PORTS sweep.

    Order is priority order: index 0 wins ties when multiple probes succeed.
    Each candidate is built off the parsed hostname of the peer's current
    base_url so we don't accidentally rewrite the host.
    """
    parsed = urlparse(peer.base_url or "")
    if not parsed.hostname or parsed.scheme != "https":
        return []

    candidates: List[str] = []
    current = (peer.base_url or "").rstrip("/")

    if peer.name in KNOWN_OPERATOR_PORTS:
        canonical = f"https://{parsed.hostname}:{KNOWN_OPERATOR_PORTS[peer.name]}"
        candidates.append(canonical)
        if current and current != canonical:
            candidates.append(current)
        return candidates

    # Unknown peer — full sweep
    for port in FALLBACK_PORTS:
        candidate = f"https://{parsed.hostname}:{port}"
        if candidate not in candidates:
            candidates.append(candidate)
    return candidates


async def _probe_one(
    cert_config: dict, candidate_base: str
) -> tuple[str, Optional[int], Optional[str]]:
    """Probe one candidate URL. Returns (candidate_base, status_code, error_name).
    status_code is None on connection failure; error_name is set in that case."""
    probe_url = candidate_base + "/api/v1/federation/agent-cards"
    try:
        async with httpx.AsyncClient(
            timeout=PROBE_TIMEOUT_SEC, **cert_config
        ) as client:
            resp = await client.get(probe_url, params={"limit": "1"})
        return (candidate_base, resp.status_code, None)
    except Exception as exc:
        return (candidate_base, None, type(exc).__name__)


class PeerUrlSelfHealReactor(EventStoreReactor):
    event_type = "FederationStateDriftDetected"
    leader_key = "reactor_peer_url_self_heal"
    name = "PeerUrlSelfHeal"

    async def handle_event(self, event_data: dict) -> None:
        drift_type = event_data.get("drift_type", "")
        if drift_type != "peer_url_misconfigured":
            return  # different drift class, not our concern

        peer_id = event_data.get("peer_id")
        if not peer_id:
            logger.debug(f"[Reactor:{self.name}] event missing peer_id, skipping")
            return

        async with AsyncSessionLocal() as db:
            peer = (
                await db.execute(select(PeerRegistry).where(PeerRegistry.id == peer_id))
            ).scalar_one_or_none()
            if peer is None:
                logger.warning(
                    f"[Reactor:{self.name}] peer_id={peer_id} not in local DB — skipping"
                )
                return
            if (peer.peer_type or "") == "frame":
                logger.debug(
                    f"[Reactor:{self.name}] peer={peer.name} is a frame — handled by frame_bundle_stale path"
                )
                return

            old_url = peer.base_url or ""
            candidates = _candidate_urls_for_peer(peer)
            if not candidates:
                logger.info(
                    f"[Reactor:{self.name}] peer={peer.name} has no probeable hostname (url={old_url!r})"
                )
                return

            # Need SPIRE certs to probe — operator endpoints require mTLS.
            sample_sync_url = candidates[0].rstrip("/") + "/api/v1/federation/agent-cards"
            cert_config = svid_client.get_client_cert_config(target_url=sample_sync_url)
            if not cert_config:
                logger.warning(
                    f"[Reactor:{self.name}] SVID not available — cannot probe peer={peer.name}"
                )
                return

            # §pass46 (2026-05-19) — Probe all candidates CONCURRENTLY via
            # asyncio.gather. Previously serial (10 candidates × 8s = up to
            # 80s per event when all unreachable). Now ~3s worst-case latency
            # regardless of candidate count. First-success-wins logic preserved
            # by iterating results in `candidates` order, which is priority
            # order (canonical first, fallbacks after for unknown peers).
            results = await asyncio.gather(
                *(_probe_one(cert_config, c) for c in candidates),
                return_exceptions=False,
            )
            by_url = {r[0]: r for r in results}

            winner = None
            for candidate_base in candidates:
                cb, status, err = by_url[candidate_base]
                if status == 200:
                    winner = (cb, status)
                    break
                if status is None:
                    logger.debug(
                        f"[Reactor:{self.name}] probe failed peer={peer.name} "
                        f"candidate={cb}: {err}"
                    )
                else:
                    logger.debug(
                        f"[Reactor:{self.name}] probe non-200 peer={peer.name} "
                        f"candidate={cb} status={status}"
                    )

            if winner is None:
                logger.warning(
                    f"[Reactor:{self.name}] no candidate URL worked for peer={peer.name} "
                    f"(tried {len(candidates)} ports). Manual investigation needed."
                )
                return

            winning_url, winning_status = winner
            if winning_url == old_url:
                # §pass19 (preserved) — Healthy match on the CURRENT URL: stale
                # drift event. Mark ACTIVE and short-circuit without emitting
                # an auto-corrected audit event.
                logger.info(
                    f"[Reactor:{self.name}] peer={peer.name} reachable at "
                    f"current url={old_url!r} (probe 200) — drift event "
                    f"stale, marking ACTIVE."
                )
                await db.execute(
                    update(PeerRegistry)
                    .where(PeerRegistry.id == peer.id)
                    .values(status="ACTIVE")
                )
                await db.commit()
                return

            # Found a working DIFFERENT candidate — UPDATE base_url.
            logger.warning(
                f"[Reactor:{self.name}] AUTO-HEAL peer={peer.name} "
                f"old_url={old_url!r} new_url={winning_url!r} "
                f"(probe returned 200)"
            )
            await db.execute(
                update(PeerRegistry)
                .where(PeerRegistry.id == peer.id)
                .values(base_url=winning_url, status="ACTIVE")
            )
            await db.commit()

            # Emit audit event (best-effort; doesn't block the heal).
            try:
                await get_event_emitter().emit(
                    event_type="PeerRegistryUrlAutoCorrected",
                    aggregate_id=f"peer_registry:{peer.id}",
                    aggregate_type="PeerRegistry",
                    data={
                        "peer_id": peer.id,
                        "peer_name": peer.name,
                        "old_url": old_url,
                        "new_url": winning_url,
                        "drift_type": drift_type,
                        "auto_corrected_at": datetime.now(timezone.utc).isoformat(),
                        "probe_status": int(winning_status),
                    },
                    idempotency_key=(
                        f"peer_url_auto_corrected-{peer.id}-"
                        f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
                    ),
                )
            except Exception as exc:
                logger.warning(
                    f"[Reactor:{self.name}] audit emit failed for peer={peer.name}: {exc}"
                )

            # §pass-N (2026-05-21) — also broadcast via WS so Federation.vue can
            # react in real-time (edge-flash animation). Best-effort, non-blocking.
            try:
                from agentvault_registry.routers.websocket import notify_peer_url_auto_corrected
                await notify_peer_url_auto_corrected(
                    peer_id=peer.id,
                    peer_name=peer.name,
                    old_url=old_url,
                    new_url=winning_url,
                    drift_type=drift_type,
                )
            except Exception as ws_exc:
                logger.warning(
                    f"[Reactor:{self.name}] WS broadcast failed for peer={peer.name}: {ws_exc}"
                )


_instance: Optional[PeerUrlSelfHealReactor] = None


async def start() -> None:
    global _instance
    if _instance is None:
        _instance = PeerUrlSelfHealReactor()
    await _instance.start()


async def stop() -> None:
    global _instance
    if _instance is not None:
        await _instance.stop()
        _instance = None
