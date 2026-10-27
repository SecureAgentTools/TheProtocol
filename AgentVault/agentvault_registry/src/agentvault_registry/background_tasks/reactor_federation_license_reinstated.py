"""
Reactor: FederationLicenseReinstated → TEG partner re-add (mirror)
==================================================================
Symmetric mirror of `reactor_federation_license_suspended`. When an operator
license is reinstated after suspension, the parent registry's TEG should
proactively re-add the partner so the next cross-tx isn't gated on the lazy
auto-discovery round-trip.

Lazy auto-discovery handles new transfers correctly even without this
reactor; pre-staging just shaves the first-transfer round-trip. Idempotent
at TEG side: `/cross-teg/config/add-partner` returns `updated` if already
present.

Payload contract:
- `teg_id`: str — required for the call to fire (added at emission site since
  Phase 2)
- `operator_name`, `license_id`, `registry_id`, `url`: optional metadata used
  in log lines + body of the add-partner call

If `teg_id` is missing/empty, the reactor logs and skips.
"""
import logging
from typing import Optional

from .reactor_base import EventStoreReactor
from .reactor_helpers import add_partner_on_teg

logger = logging.getLogger(__name__)


class FederationLicenseReinstatedReactor(EventStoreReactor):
    event_type = "FederationLicenseReinstated"
    leader_key = "reactor_federation_license_reinstated"
    name = "FederationLicenseReinstated"

    async def handle_event(self, event_data: dict) -> None:
        teg_id = event_data.get("teg_id")
        operator_name = event_data.get("operator_name") or "?"
        license_id = event_data.get("license_id", "?")
        registry_id = event_data.get("registry_id", "") or ""
        url = event_data.get("url", "") or ""

        if not teg_id:
            logger.info(
                f"[Reactor:{self.name}] Skipped license={license_id} operator={operator_name} "
                f"— no teg_id in payload (legacy event or non-operator license)"
            )
            return

        result = await add_partner_on_teg(
            teg_id,
            registry_id=registry_id,
            url=url,
            source_label=self.name,
        )
        if result is None:
            return
        status_label = result.get("status", "?")
        total = result.get("total_partners", "?")
        logger.info(
            f"[Reactor:{self.name}] license={license_id} operator={operator_name} "
            f"teg_id={teg_id} → TEG status={status_label} (total_partners={total})"
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
