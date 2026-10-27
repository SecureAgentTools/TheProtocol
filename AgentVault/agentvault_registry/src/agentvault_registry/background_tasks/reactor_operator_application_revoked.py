"""
Reactor: OperatorApplicationRevoked → peer_registries cascade
==============================================================
Closes the cascade gap discovered 2026-04-28: when the revoke endpoint is
called for an operator that had NO federation_license issued (a "phantom"
operator administratively approved on a frame but never provisioned), the
existing FederationLicenseSuspended emission path was gated on
`if fed_license:` and skipped, leaving zero events in EventStore and zero
cascade — peer_registries entries remained ACTIVE despite the operator
being marked revoked in operator_applications.

This reactor subscribes to the new `OperatorApplicationRevoked` event
(emitted unconditionally by the revoke endpoint) and:
  1. Looks up the matching peer_registries row by operator_name
  2. UPDATEs its status to INACTIVE if currently ACTIVE
  3. Emits PeerRegistryDeactivated for downstream consumers
  4. Dispatches a webhook for `operator.application_revoked`

Idempotent: if the peer is already INACTIVE, the UPDATE is a no-op and the
PeerRegistryDeactivated emission is skipped.

Authority safeguards:
  - Only operates on the central registry (where peer_registries holds
    the canonical operator-as-peer rows). Operator-side databases have
    their own peer_registries with the central as a peer; those are not
    affected by this reactor.
  - Match by `peer.name == event.operator_name` (1:1 with cloud_provisioner
    naming). If no match, log + skip — better than touching the wrong row.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, update

from ..database import AsyncSessionLocal
from ..event_emitter import get_event_emitter
from ..models import PeerRegistry
from .reactor_base import EventStoreReactor
from .reactor_helpers import dispatch_webhook_event

logger = logging.getLogger(__name__)


class OperatorApplicationRevokedReactor(EventStoreReactor):
    event_type = "OperatorApplicationRevoked"
    leader_key = "reactor_operator_application_revoked"
    name = "OperatorApplicationRevoked"

    async def handle_event(self, event_data: dict) -> None:
        operator_name = event_data.get("operator_name")
        operator_did = event_data.get("operator_did")
        had_license = event_data.get("had_license", False)
        application_id = event_data.get("application_id")

        if not operator_name:
            logger.debug(
                f"[Reactor:{self.name}] event missing operator_name (app_id={application_id}) — skipping"
            )
            return
        # §OPPROV (2026-09-27): the peer row is matched by NAME, and names were never unique. An application that does
        # not hold its name (never activated, or another live application holds it) is not the owner of the row named
        # like it: revoking a refused duplicate must not take the live operator's federation peer down. Events from
        # before the field carry no key and cascade as they always did.
        if event_data.get("name_holder") is False:
            logger.info(
                f"[Reactor:{self.name}] app_id={application_id} does not hold the name {operator_name}: the peer row "
                f"named like it belongs to another application — no cascade"
            )
            return

        async with AsyncSessionLocal() as db:
            peer = (
                await db.execute(
                    select(PeerRegistry).where(PeerRegistry.name == operator_name)
                )
            ).scalar_one_or_none()

            if peer is None:
                logger.info(
                    f"[Reactor:{self.name}] no peer_registries row for operator={operator_name} "
                    f"(no cascade needed — operator was application-only). "
                    f"app_id={application_id} had_license={had_license}"
                )
            elif peer.status == "INACTIVE":
                logger.info(
                    f"[Reactor:{self.name}] peer={operator_name} already INACTIVE — cascade idempotent."
                )
            else:
                prior_status = peer.status
                peer_id = peer.id
                await db.execute(
                    update(PeerRegistry)
                    .where(PeerRegistry.id == peer_id)
                    .values(
                        status="INACTIVE",
                        deactivated_reason="operator_revoked",  # guard-set
                        deactivated_at=datetime.now(timezone.utc),
                    )
                )
                await db.commit()
                logger.warning(
                    f"[Reactor:{self.name}] CASCADE peer={operator_name} "
                    f"status={prior_status} -> INACTIVE (operator revoked, "
                    f"had_license={had_license})"
                )

                # Emit PeerRegistryDeactivated (mirrors the existing
                # FederationLicenseSuspended path's downstream effects so
                # webhook subscribers see the same event shape regardless of
                # which revoke trigger fired).
                try:
                    await get_event_emitter().emit(
                        event_type="PeerRegistryDeactivated",
                        aggregate_id=f"peer_registry:{peer_id}",
                        aggregate_type="PeerRegistry",
                        data={
                            "peer_id": peer_id,
                            "peer_name": operator_name,
                            "operator_did": operator_did,
                            "prior_status": prior_status,
                            "trigger": "OperatorApplicationRevoked",
                            "had_license": had_license,
                            "deactivated_at": datetime.now(timezone.utc).isoformat(),
                        },
                    )
                except Exception as exc:
                    logger.warning(
                        f"[Reactor:{self.name}] PeerRegistryDeactivated emit failed for {operator_name}: {exc}"
                    )

        # Webhook fan-out for developers subscribed to operator lifecycle.
        # Runs regardless of peer presence (downstream may want to track
        # application-only revokes too).
        await dispatch_webhook_event(
            event_type="operator.application_revoked",
            event_data=event_data,
            source_label=self.name,
        )


_instance: Optional[OperatorApplicationRevokedReactor] = None


async def start() -> None:
    global _instance
    if _instance is None:
        _instance = OperatorApplicationRevokedReactor()
    await _instance.start()


async def stop() -> None:
    global _instance
    if _instance is not None:
        await _instance.stop()
        _instance = None
