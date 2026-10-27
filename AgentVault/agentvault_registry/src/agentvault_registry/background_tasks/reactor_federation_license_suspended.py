"""
Reactor: FederationLicenseSuspended → TEG partner cleanup
=========================================================
When an operator's federation license is suspended (containers stay running
but the operator is paused), the parent registry's TEG should drop the stale
`_runtime_partners` entry for that operator. The license state itself is
checked synchronously per-request via the federation_license_gate, but TEG's
runtime cache is independent and can carry the suspended partner indefinitely
otherwise.

Identical handler shape to the PeerRegistryDeactivated reactor — both call
the same `remove_partner_on_teg` helper. Distinct event types only because
license suspend is a *reversible* state change (operator stays alive),
whereas PeerRegistryDeactivated represents a teardown.

D6-800 (2026-10-17): the licence routes' revoke and delete emit this event
too, with `licence_status: "revoked"` in the payload, so a revoked licence
leaves the partner list the same way a suspended one does.

Lazy auto-discovery on the TEG side will re-add the partner when reinstated
+ next cross-tx fires, so no `FederationLicenseReinstated` reactor is needed
for Phase 2.
"""
import logging
from typing import Optional

from .reactor_base import EventStoreReactor
from .reactor_helpers import remove_partner_on_teg

logger = logging.getLogger(__name__)


class FederationLicenseSuspendedReactor(EventStoreReactor):
    event_type = "FederationLicenseSuspended"
    leader_key = "reactor_federation_license_suspended"
    name = "FederationLicenseSuspended"

    async def handle_event(self, event_data: dict) -> None:
        teg_id = event_data.get("teg_id")
        operator_name = event_data.get("operator_name") or "?"
        license_id = event_data.get("license_id", "?")

        if not teg_id:
            logger.info(
                f"[Reactor:{self.name}] Skipped license={license_id} operator={operator_name} "
                f"— no teg_id in payload (legacy event or non-operator license)"
            )
            return

        result = await remove_partner_on_teg(teg_id, source_label=self.name)
        if result is None:
            return  # network error already logged
        status_label = result.get("status", "?")
        total = result.get("total_partners", "?")
        logger.info(
            f"[Reactor:{self.name}] license={license_id} operator={operator_name} "
            f"teg_id={teg_id} → TEG status={status_label} (total_partners={total})"
        )


# ----------------------------------------------------------------------- module API

_instance: Optional[FederationLicenseSuspendedReactor] = None


async def start() -> None:
    global _instance
    if _instance is None:
        _instance = FederationLicenseSuspendedReactor()
    await _instance.start()


async def stop() -> None:
    global _instance
    if _instance is not None:
        await _instance.stop()
        _instance = None
