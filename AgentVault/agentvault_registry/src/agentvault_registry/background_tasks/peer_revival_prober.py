"""INACTIVE-peer revival prober — kills the federation-peer ratchet.

RCA 2026-07-10 (RCA_2026-07-10_FEDERATION_PEER_RATCHET.md): many code paths can
flip a peer_registries row INACTIVE, but nothing ever flipped one back — restarts,
sync races and rename fan-outs therefore permanently killed FX corridors until a
human ran `reactivate` (4 incidents in 12 days). This worker makes the lifecycle
symmetric:

  every cycle (leader-elected, default 120s):
    for each INACTIVE peer whose deactivated_reason is NOT in the admin guard set:
      IDENTITY-probe the peer's mTLS endpoint — TLS handshake with our SVID,
      then match the presented certificate's SPIFFE SAN URIs against the row:
        operator rows:  any URI containing  /operator/{peer.name}/
        frame rows:     any URI whose trust domain == peer.trust_domain
      (reachability alone is NOT enough: a wildcard vhost answering for a dead
       name must not revive rename debris — identity match closes that hole.)
      M consecutive successful probes (Redis-counted, default 2) →
        status=ACTIVE via the crud choke point → PeerRegistryReactivated emitted.

Deny-only-in-reverse, Δ-irrelevant (peer status gates resolution; money paths
already refund safely while a row is INACTIVE). Kill switch:
PEER_REVIVAL_PROBER_ENABLED=false.
"""
from __future__ import annotations

import asyncio
import logging
import os
import socket
import ssl
from datetime import datetime, timezone
from typing import List, Optional, Tuple
from urllib.parse import urlparse

from sqlalchemy import select

from ..database import AsyncSessionLocal
from ..identity import svid_client
from ..models import PeerRegistry
from ..crud.crud_peer_registry import (
    PEER_DEACTIVATION_GUARD_REASONS,
    update_peer_registry_status,
)
from .leader import get_redis, run_with_leadership

logger = logging.getLogger(__name__)

INTERVAL_SEC = int(os.getenv("PEER_REVIVAL_INTERVAL_SEC", "120"))
SUCCESSES_REQUIRED = int(os.getenv("PEER_REVIVAL_SUCCESSES", "2"))
MAX_PER_CYCLE = int(os.getenv("PEER_REVIVAL_MAX_PER_CYCLE", "10"))
PROBE_TIMEOUT_SEC = float(os.getenv("PEER_REVIVAL_PROBE_TIMEOUT_SEC", "6"))
SUCCESS_TTL_SEC = 15 * 60  # a success streak expires if not continued

# belt-and-braces name filter on top of the reason guard + identity probe
_DEBRIS_PREFIXES = ("probe-", "renametest", "renamedone", "sandbox")


def _probe_target(peer: PeerRegistry) -> Optional[Tuple[str, int]]:
    try:
        u = urlparse(peer.base_url or "")
        if not u.hostname:
            return None
        return u.hostname, u.port or 443
    except Exception:
        return None


def _san_uris_of(host: str, port: int, cert: Optional[Tuple[str, str]]) -> List[str]:
    """TLS-handshake `host:port` (presenting our SVID if available) and return the
    peer certificate's SAN URIs. Chain trust is NOT evaluated — this is an
    IDENTITY match, not an authenticity gate; the money path still does full mTLS.
    Blocking — call via asyncio.to_thread."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    if cert:
        try:
            ctx.load_cert_chain(certfile=cert[0], keyfile=cert[1])
        except Exception:
            pass  # probe without client cert; server may still present its cert
    with socket.create_connection((host, port), timeout=PROBE_TIMEOUT_SEC) as sock:
        with ctx.wrap_socket(sock, server_hostname=host) as tls:
            der = tls.getpeercert(binary_form=True)
    if not der:
        return []
    from cryptography import x509  # local import: keep module import cheap
    c = x509.load_der_x509_certificate(der)
    try:
        san = c.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        return [str(v) for v in san.get_values_for_type(x509.UniformResourceIdentifier)]
    except Exception:
        return []


def _identity_matches(peer: PeerRegistry, uris: List[str]) -> bool:
    if not uris:
        return False
    if peer.peer_type == "frame":
        td = (peer.trust_domain or "").strip().lower()
        return bool(td) and any(
            u.lower().startswith(f"spiffe://{td}/") for u in uris
        )
    needle = f"/operator/{(peer.name or '').strip().lower()}/"
    return any(needle in u.lower() for u in uris)


async def _probe_peer(peer: PeerRegistry, cert: Optional[Tuple[str, str]]) -> bool:
    tgt = _probe_target(peer)
    if not tgt:
        return False
    try:
        uris = await asyncio.to_thread(_san_uris_of, tgt[0], tgt[1], cert)
    except Exception:
        return False
    return _identity_matches(peer, uris)


def _client_cert() -> Optional[Tuple[str, str]]:
    try:
        cfg = svid_client.get_client_cert_config(target_url="https://peer-probe.invalid")
        cert = (cfg or {}).get("cert")
        if isinstance(cert, (tuple, list)) and len(cert) == 2:
            return cert[0], cert[1]
    except Exception:
        pass
    return None


async def _cycle() -> None:
    async with AsyncSessionLocal() as db:
        rows = (
            (await db.execute(
                select(PeerRegistry).where(PeerRegistry.status == "INACTIVE")
            )).scalars().all()
        )
        # ⚠ FAIL CLOSED: A RECORDED REASON IS A DECISION, AND A DECISION IS NOT THIS WORKER'S TO UNDO.
        # This asked a DENYLIST of eleven names, so any reason outside it was revivable — including free text.
        # `POST /admin/federation/peers/{id}/deactivate?reason=...` passes the reason through verbatim
        # (admin_federation.py:185), so an admin who said WHY lost the row to this worker after two probes, while
        # an admin who said nothing kept it (the writer defaults to admin_deactivated, which is guarded). The
        # careful answer was punished and the careless one protected. Measured on beacon 2026-09-16: a row
        # deactivated with a free-text reason came back in 35 seconds.
        # The allowlist is derivable from this worker's OWN purpose, which is the docstring above: it exists for
        # rows flipped by restarts, sync races and rename fan-outs — paths that write the status directly and
        # record NO reason. Every reason stamped anywhere in this tree names a decision somebody made. So the
        # rule is: revive a row that carries no reason, and leave every row that carries one.
        # The guard set stays as a second, redundant check, because a rule worth having is worth having twice.
        _no_reason = [p for p in rows if not (p.deactivated_reason or "").strip()]
        _declined = [p for p in rows if (p.deactivated_reason or "").strip()]
        candidates = [
            p for p in _no_reason
            if (p.deactivated_reason or None) not in PEER_DEACTIVATION_GUARD_REASONS
            and not (p.name or "").lower().startswith(_DEBRIS_PREFIXES)
        ][:MAX_PER_CYCLE]
        if _declined:
            # Said out loud, once per cycle: if a SYSTEM path ever starts stamping an unreachability reason, this
            # line is where that shows up, instead of the peer silently never coming back.
            logger.info(
                "[peer-revival] %d INACTIVE row(s) carry a recorded reason and are left alone: %s",
                len(_declined),
                ", ".join(sorted({f"{p.name}={(p.deactivated_reason or '').strip()}" for p in _declined})[:8]),
            )
        if not candidates:
            return

        cert = _client_cert()
        redis = None
        try:
            redis = await get_redis()
        except Exception:
            pass  # streak tracking degrades to per-process memory-less (single success won't revive)

        for peer in candidates:
            ok = await _probe_peer(peer, cert)
            key = f"peer_revive_streak:{peer.id}"
            if not ok:
                if redis is not None:
                    try: await redis.delete(key)
                    except Exception: pass
                continue
            streak = 1
            if redis is not None:
                try:
                    streak = int(await redis.incr(key))
                    await redis.expire(key, SUCCESS_TTL_SEC)
                except Exception:
                    streak = 1
            logger.info(
                "[peer-revival] identity probe OK for peer=%s (%s) streak=%d/%d",
                peer.id, peer.name, streak, SUCCESSES_REQUIRED,
            )
            if streak >= SUCCESSES_REQUIRED:
                # Captured BEFORE the write, because the write clears them and the log line below is the only
                # record of what this revival undid.
                _was_reason, _was_since = peer.deactivated_reason, peer.deactivated_at
                await update_peer_registry_status(
                    db, peer, "ACTIVE", reason="auto_revival"
                )
                if redis is not None:
                    try: await redis.delete(key)
                    except Exception: pass
                logger.warning(
                    # ⚠ READ BEFORE THE WRITE. These were read AFTER update_peer_registry_status had cleared
                    # them, so the one line that records a revival printed "was INACTIVE(reason=None) since
                    # None" — it could not say what it revived, which is the only thing it exists to say.
                    "[peer-revival] REVIVED peer=%s (%s) — was INACTIVE(reason=%s) since %s; "
                    "identity-verified over mTLS. PeerRegistryReactivated emitted.",
                    peer.id, peer.name, _was_reason, _was_since,
                )


async def start() -> None:
    logger.info(
        "[peer-revival] prober armed: interval=%ss successes=%d max/cycle=%d "
        "(guard reasons: %s)",
        INTERVAL_SEC, SUCCESSES_REQUIRED, MAX_PER_CYCLE,
        ", ".join(sorted(PEER_DEACTIVATION_GUARD_REASONS)),
    )
    async for _ in run_with_leadership("peer_revival_prober", interval=INTERVAL_SEC):
        try:
            await _cycle()
        except Exception as exc:
            logger.error("[peer-revival] cycle error: %s", exc)
