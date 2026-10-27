"""
Reactor: PeerRegistryDeactivated → TEG partner cleanup
======================================================
Listens for `PeerRegistryDeactivated` events on the local EventStore. When a
peer (e.g., a torn-down cloud operator) is deactivated, calls the local TEG's
`/api/v1/cross-teg/config/remove-partner` admin endpoint to drop the stale
`_runtime_partners` entry for that peer's TEG.

Side effect is idempotent at the TEG (`status: "not_found"` on second call) so
EventStore backlog replay (last 15 events on reconnect) is safe.

When `event.data.teg_id` is null, the reactor logs and skips: the frame
federation revoke path (frame revocation does not target a partner TEG), or a
deactivation whose partner another ACTIVE row still names. An admin or owner
deactivation through crud_peer_registry.update_peer_registry_status carries
teg-<safe name> (2026-10-18, agentvault2-5b): the partner a reactivation and a
quarantine lift register, which the TEG partner rule otherwise kept.

Shares the `remove_partner_on_teg` helper with the FederationLicenseSuspended
and RegistryQuarantined reactors (Phase 2).
"""
import logging
from typing import Optional

from .reactor_base import EventStoreReactor
from .reactor_helpers import remove_partner_on_teg

logger = logging.getLogger(__name__)

# Backwards-compatibility shim: tests reference `_remove_partner_on_teg` on this
# module to monkeypatch the network call. Keep the symbol pointing at the helper.
_remove_partner_on_teg = remove_partner_on_teg


class PeerRegistryDeactivatedReactor(EventStoreReactor):
    event_type = "PeerRegistryDeactivated"
    leader_key = "reactor_peer_deactivated"
    name = "PeerRegistryDeactivated"

    async def handle_event(self, event_data: dict) -> None:
        teg_id = event_data.get("teg_id")
        peer_name = event_data.get("peer_name") or event_data.get("operator_name") or "?"

        if not teg_id:
            logger.info(
                f"[Reactor:{self.name}] Skipped peer={peer_name} — no teg_id "
                f"(frame revoke, or a partner another ACTIVE row still names)"
            )
            return

        result = await _remove_partner_on_teg(teg_id, source_label=self.name)
        if result is None:
            return  # network error already logged
        status_label = result.get("status", "?")
        total = result.get("total_partners", "?")
        logger.info(
            f"[Reactor:{self.name}] peer={peer_name} teg_id={teg_id} "
            f"→ TEG status={status_label} (total_partners={total})"
        )


# ----------------------------------------------------------------------- module API

_instance: Optional[PeerRegistryDeactivatedReactor] = None


async def start() -> None:
    """Module-level start, called from main.py startup_event."""
    global _instance
    if _instance is None:
        _instance = PeerRegistryDeactivatedReactor()
    await _instance.start()


async def stop() -> None:
    global _instance
    if _instance is not None:
        await _instance.stop()
        _instance = None
