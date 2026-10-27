"""
Phase D (2026-05-26 evening) — Sandbox-only peer activation keeper.

BAND-AID for the sandbox-A ↔ sandbox-B federation peer activation state.

Background: cross-frame transfer tests need both sides of the peer_registries
table marked status='ACTIVE'. Sandbox testing routinely flips peers to
INACTIVE/PENDING_APPROVAL via destructive lifecycles (federation_safe_paths,
admin_quarantine_safe, etc.), then never re-activates them. This breaks
the next cross-frame transfer test.

Until a proper sandbox-only reactor handles this (recommended long-term),
this band-aid polls every 60s and force-flips the EXPECTED sandbox peer
back to ACTIVE if it has drifted.

Behavior:
  - Gated by REGISTRY_NAME env: only runs on `registry-test` or `registry-test-b`.
  - Determines expected partner from PARTNER_FRAME_TRUST_DOMAIN env (mirror of
    SPIRE_FEDERATE_WITH).
  - On each cycle: SELECT id, status FROM peer_registries WHERE base_url LIKE
    a known sandbox-peer pattern. If status != 'ACTIVE', flip it via direct
    UPDATE.
  - Logs every action. Prometheus counter `peer_activation_keeper_repairs_total`
    increments on each fix.
  - Leader-elected via the canonical pattern.

DOCTRINE NOTE: This is a band-aid. The proper fix is either:
  (a) A sandbox-gated reactor that subscribes to PeerRegistryStatusChanged
      events and rejects unintended deactivations (per the request-then-revert
      reactor pattern in reactor_framework).
  (b) Locking sandbox peer status to ACTIVE in the DB via constraint.
This task is intentionally simple — direct DB write — to unblock sandbox
testing TODAY without architectural debate.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, List

from sqlalchemy import text

from ..database import get_db_context
from ._worker_base import BackgroundWorker

logger = logging.getLogger(__name__)


# Best-effort Prometheus metric
try:
    from prometheus_client import Counter as _Counter

    PEER_REPAIRS_TOTAL = _Counter(
        "peer_activation_keeper_repairs_total",
        "Sandbox peer rows flipped back to ACTIVE by the keeper",
        labelnames=["registry_id", "peer_name"],
    )
except Exception:
    PEER_REPAIRS_TOTAL = None


# URL patterns that identify the canonical sandbox cross-frame peer rows.
# When sandbox-A looks for its partner, it finds rows with these patterns;
# the partner row's status MUST be ACTIVE for cross-frame transfers to work.
#
# §pass73.3.5 (2026-05-27) — extended to sandbox cloud-ops. Same band-aid pattern:
# the bilateral parent peer row on a sandbox cloud-op can drift to INACTIVE
# through MCP tester lifecycles, half-finished admin ops, or the §pass73.3
# provisioner asymmetry where one frame's parent ends up un-approved while
# the other gets manually rescued. Without this keeper, federation_sync on
# the cloud-op stops pulling (filters by status='ACTIVE'), and the cloud-op
# silently loses pull-sync visibility into its own parent's agents.
_EXPECTED_PEERS_FOR_REGISTRY = {
    # sandbox-A (REGISTRY_NAME=registry-test) expects Registry-Test-B
    "registry-test": [
        # By name first — most specific
        "Registry-Test-B",
    ],
    # sandbox-B (REGISTRY_NAME=registry-test-b) expects Registry-Test
    "registry-test-b": [
        "Registry-Test",
    ],
    # sandbox cloud-ops — each keeps its parent + cross-frame mainframe +
    # cross-frame sibling cloud-op ACTIVE.
    #
    # §pass73.3.6 — extended from parent-only to full multi-hop set after
    # cross-frame canary E2E (sb-alpha↔sb-delta:async) was unblocked. The
    # cross-frame mainframe peer is needed by the trusted-registries cache
    # filter; the cross-frame sibling cloud-op peer is needed by the
    # cross-registry resolver `_resolve_receiver_registry` which matches
    # the federated agent_card's `federation_metadata.source_registry`
    # SPIFFE path against an ACTIVE peer's slug.
    #
    # Naming MUST match the slug derived from the federated card's
    # source_registry SPIFFE path (e.g. `spiffe://sandbox-a.test/operator/
    # sandboxalpha/registry` → slug `sandboxalpha`). Do NOT use display
    # names with spaces ("Sandbox Alpha" → slug 'sandbox-alpha' which
    # WON'T match 'sandboxalpha').
    "sandboxalpha": [
        "Registry-Test",     # parent mainframe (sandbox-A)
        "Registry-Test-B",   # cross-frame mainframe (sandbox-B)
        "sandboxdelta",      # cross-frame sibling cloud-op
    ],
    "sandboxdelta": [
        "Registry-Test-B",   # parent mainframe (sandbox-B)
        "Registry-Test",     # cross-frame mainframe (sandbox-A)
        "sandboxalpha",      # cross-frame sibling cloud-op
    ],
}


class PeerActivationKeeper(BackgroundWorker):
    """Force expected sandbox cross-frame peer rows back to ACTIVE.

    Sandbox-only (gated by REGISTRY_NAME). Direct DB UPDATE — bypasses
    the normal `/admin/federation/peer-registries/{id}/approve` endpoint
    because the approval flow has side-effects (license issuance, etc.)
    that aren't needed when we're just un-doing an accidental flip.
    """
    worker_id = "peer_activation_keeper"
    leader_key = "peer_activation_keeper:leader"
    interval_sec = 60
    cold_start_delay_sec = 10

    def __init__(self) -> None:
        super().__init__()
        # Normalize to lowercase + dash form (compose sets REGISTRY_NAME with
        # mixed case in some files, e.g. "Registry-Test"). Match against the
        # canonical lowercase keys.
        raw = os.getenv("REGISTRY_NAME", "")
        self._registry_name = raw.strip().lower()
        self._last_action: Dict[str, Any] = {}

    def _should_run(self) -> bool:
        """Sandbox-gate: only run on registry-test and registry-test-b."""
        if self._registry_name not in _EXPECTED_PEERS_FOR_REGISTRY:
            return False
        return True

    async def _cycle_once(self) -> None:
        names = _EXPECTED_PEERS_FOR_REGISTRY.get(self._registry_name, [])
        if not names:
            return
        async with get_db_context() as db:
            # Find rows whose name matches our expected sandbox peer
            for name in names:
                rows = await db.execute(
                    text(
                        "SELECT id, name, status FROM peer_registries "
                        "WHERE name = :name"
                    ),
                    {"name": name},
                )
                row_list: List[Any] = rows.fetchall()
                for row in row_list:
                    rid, rname, rstatus = row[0], row[1], row[2]
                    if rstatus == "ACTIVE":
                        continue
                    # Flip back
                    await db.execute(
                        text(
                            "UPDATE peer_registries "
                            "SET status='ACTIVE', approved_at=NOW(), "
                            "    health_check_failure_count=0 "
                            "WHERE id=:id"
                        ),
                        {"id": rid},
                    )
                    await db.commit()
                    self._last_action = {
                        "id": rid,
                        "name": rname,
                        "prev_status": rstatus,
                        "new_status": "ACTIVE",
                    }
                    logger.warning(
                        "[peer_activation_keeper] BAND-AID: flipped peer %r "
                        "(id=%s) from status=%r → ACTIVE",
                        rname, rid, rstatus,
                    )
                    if PEER_REPAIRS_TOTAL is not None:
                        try:
                            PEER_REPAIRS_TOTAL.labels(
                                registry_id=self._registry_name,
                                peer_name=rname,
                            ).inc()
                        except Exception:
                            pass

    def _last_stats(self) -> Dict[str, Any]:
        return {
            "expected_peer_names": _EXPECTED_PEERS_FOR_REGISTRY.get(
                self._registry_name, []
            ),
            "last_repair": self._last_action,
            "sandbox_only": True,
            "band_aid": True,
            "doctrine_note": (
                "Sandbox-only band-aid. Long-term fix: sandbox-gated reactor "
                "subscribed to PeerRegistryStatusChanged that rejects "
                "unintended INACTIVE flips."
            ),
        }


_singleton: PeerActivationKeeper | None = None


async def start_peer_activation_keeper() -> None:
    global _singleton
    if _singleton is not None:
        return
    _singleton = PeerActivationKeeper()
    if not _singleton._should_run():
        logger.info(
            "[peer_activation_keeper] disabled (REGISTRY_NAME=%r not in sandbox set)",
            os.getenv("REGISTRY_NAME", ""),
        )
        return
    await _singleton.start()
    logger.info("[peer_activation_keeper] STARTED (sandbox-only band-aid)")


async def stop_peer_activation_keeper() -> None:
    global _singleton
    if _singleton is None:
        return
    await _singleton.stop()
    _singleton = None


def get_peer_activation_keeper() -> PeerActivationKeeper | None:
    return _singleton
