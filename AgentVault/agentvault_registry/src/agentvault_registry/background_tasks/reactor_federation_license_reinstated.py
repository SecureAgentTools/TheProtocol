"""
Reactor: FederationLicenseReinstated → TEG partner re-add (mirror)
==================================================================
Symmetric mirror of `reactor_federation_license_suspended`. When an operator license is reinstated after suspension,
the parent registry's TEG should proactively re-add the partner so the next cross-tx isn't gated on the lazy
auto-discovery round-trip.

Lazy auto-discovery handles new transfers correctly even without this reactor; pre-staging just shaves the
first-transfer round-trip. Idempotent at TEG side: `/cross-teg/config/add-partner` returns `updated` if already
present.

V0660 (l2) — WHAT THE PAYLOAD IS ALLOWED TO DECIDE: the licence, and nothing else.

`FederationLicenseReinstated` is on the replicator's broadcast allowlist (the event store's
`services/cross_frame_replicator.CROSS_FRAME_BROADCAST_TYPES`, §pass47 A5), so every event of this type a peer emits
reaches this frame — over the WS bridge, and through `reactor_base._poll_once`, which fetches this reactor's event
type from `/api/v1/events/foreign` beside `/events/export` every 30 s by default. This reactor used to read `teg_id`
and `url` out of that payload and hand them to `add_partner_on_teg`, which writes them into this frame's TEG partner
config as that partner's dial address — so a federated peer could name both the partner and the address this frame's
TEG dials for it. (The `url` key was read from a payload neither of our own emitters sets, so the only address it
ever wrote was the helper's invented `https://<teg_id>.placeholder:8443`.)

Two rules now, the ones its sibling `reactor_frame_federation_established` already follows:
  * a peer frame's reinstatement is not acted on: re-adding a partner is a grant of trust this frame makes for
    itself, and our own admin reinstates locally if that is wanted. An event carrying `_foreign_frame_id` is logged
    and dropped;
  * the address comes from the peer ROW, through `register_peer_partner_on_teg` — the helper the reactivation, the
    quarantine lift and the provisioning use. This database says which operator the licence belongs to, and the row
    says the address; with no licence row here, or no ACTIVE peer row with an address, nothing is written and the
    line says so.

The licence row is read for a second reason: a cloud operator shares its parent frame's event store, where the
parent's own event is NOT marked foreign. Looking the licence up here is what tells the two apart.

Payload contract:
- `license_id`: str — required; the licence this frame's own database must hold
- `operator_name`, `operator_did`, `teg_id`: metadata for the log line only. The operator acted on is the licence
  row's own, and the partner's address is the peer row's.
"""
import logging
from typing import Optional

from .reactor_base import EventStoreReactor
from .reactor_helpers import register_peer_partner_on_teg

logger = logging.getLogger(__name__)


class FederationLicenseReinstatedReactor(EventStoreReactor):
    event_type = "FederationLicenseReinstated"
    leader_key = "reactor_federation_license_reinstated"
    name = "FederationLicenseReinstated"

    async def handle_event(self, event_data: dict) -> None:
        license_id = event_data.get("license_id")
        said_operator = event_data.get("operator_name") or "?"
        foreign = event_data.get("_foreign_frame_id")

        if foreign:
            logger.info(
                f"[Reactor:{self.name}] Skipped license={license_id or '?'} operator={said_operator} "
                f"— another frame's reinstatement (frame {foreign}); re-adding a TEG partner is a grant of trust "
                f"this frame makes for itself"
            )
            return
        if not license_id:
            logger.info(
                f"[Reactor:{self.name}] Skipped operator={said_operator} — the payload names no licence"
            )
            return

        from agentvault_registry import models
        from agentvault_registry.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            lic = await db.get(models.FederationLicense, str(license_id))
            if lic is None:
                logger.info(
                    f"[Reactor:{self.name}] Skipped license={license_id} operator={said_operator} — this registry "
                    f"holds no such licence (another registry's event in a shared store)"
                )
                return
            operator_name = lic.operator_name or ""
            if not operator_name:
                logger.warning(
                    f"[Reactor:{self.name}] license={license_id}: the licence row names no operator; "
                    f"no TEG partner registered"
                )
                return
            result = await register_peer_partner_on_teg(db, operator_name, source_label=self.name)

        if result is None:
            logger.warning(
                f"[Reactor:{self.name}] license={license_id} operator={operator_name}: the TEG partner was not "
                f"registered (see the helper's line above); this frame's next leg to the peer registers it"
            )
            return
        logger.info(
            f"[Reactor:{self.name}] license={license_id} operator={operator_name} → TEG "
            f"status={result.get('status', '?')} (total_partners={result.get('total_partners', '?')})"
        )


_instance: Optional[FederationLicenseReinstatedReactor] = None


async def start() -> None:
    global _instance
    if _instance is None:
        _instance = FederationLicenseReinstatedReactor()
    await _instance.start()


async def stop() -> None:
    global _instance
    if _instance is not None:
        await _instance.stop()
        _instance = None
