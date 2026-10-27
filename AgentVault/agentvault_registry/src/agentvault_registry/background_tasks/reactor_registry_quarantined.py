"""
Reactor: RegistryQuarantined → TEG partner cleanup
==================================================
When a federated peer is moved to QUARANTINED state by the compliance monitor
(policy hash drift, severity-based grace period), the parent registry's TEG
should drop the runtime partner entry for that peer.

The compliance monitor handles DB state transitions and emits the event
synchronously. This reactor closes the TEG cache invalidation gap.

Same handler shape as PeerRegistryDeactivated and FederationLicenseSuspended;
all three call `remove_partner_on_teg` with the peer's `teg_id` from the event
payload. The teg_id is derived best-effort at emission time from the peer's
name slug; non-operator peers may not match TEG's `_runtime_partners` keys, in
which case TEG returns `not_found` and the reactor logs + continues.

Quarantine LIFTING does not need a reactor — lazy auto-discovery on TEG re-adds
the partner on next cross-tx.

D6-801 (2026-10-17): while the quarantine stands, the registry's money paths
send no leg to the peer (services/federation_license_gate.py), so nothing
names its TEG to the local TEG and the partner stays removed.
"""
import logging
from typing import Optional

from .reactor_base import EventStoreReactor
from .reactor_helpers import remove_partner_on_teg

logger = logging.getLogger(__name__)


class RegistryQuarantinedReactor(EventStoreReactor):
    event_type = "RegistryQuarantined"
    leader_key = "reactor_registry_quarantined"
    name = "RegistryQuarantined"

    async def handle_event(self, event_data: dict) -> None:
        teg_id = event_data.get("teg_id")
        peer_name = event_data.get("peer_name") or "?"
        peer_id = event_data.get("peer_registry_id", "?")

        if not teg_id:
            logger.info(
                f"[Reactor:{self.name}] Skipped peer_id={peer_id} peer_name={peer_name} "
                f"— no teg_id in payload (legacy event or unknown peer)"
            )
            return

        result = await remove_partner_on_teg(teg_id, source_label=self.name)
        if result is None:
            return  # network error already logged
        status_label = result.get("status", "?")
        total = result.get("total_partners", "?")
        logger.info(
            f"[Reactor:{self.name}] peer_id={peer_id} peer_name={peer_name} "
            f"teg_id={teg_id} → TEG status={status_label} (total_partners={total})"
        )


# ----------------------------------------------------------------------- module API

_instance: Optional[RegistryQuarantinedReactor] = None


async def start() -> None:
    global _instance
    if _instance is None:
        _instance = RegistryQuarantinedReactor()
    await _instance.start()


async def stop() -> None:
    global _instance
    if _instance is not None:
        await _instance.stop()
        _instance = None
