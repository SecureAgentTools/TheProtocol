"""Reactor: OperatorRenamed → cross-frame fanout of an operator identity rename.

§2026-06-14 — the event-sourced operator IDENTITY rename's propagation step.
The rename TRIGGER (on the op's home frame) does the heavy local work — re-issue
SPIRE, recreate the op under the new slug, update the home frame's OWN rows
(peer_registries, agent_cards origin, ES federation_operators) — and then emits
ONE `OperatorRenamed` event. This reactor (home frame, leader-elected) picks it
up and fans the change out to every ACTIVE peer frame's
`/api/v1/federation/admin/operators/rename`, where each peer applies it to ITS
OWN rows in place. No direct cross-frame SQL; the event is the audit trail.

Mirrors `reactor_agent_suspended` (block was done inline; the reactor only does
the cross-frame fanout). Events do not cross frames here, so only the home
frame's reactor sees this — exactly the topology this fanout exists for.
"""
import logging
import os
from typing import Optional

from .reactor_base import EventStoreReactor
from .reactor_helpers import fanout_operator_rename_to_peers

logger = logging.getLogger(__name__)


class OperatorRenamedReactor(EventStoreReactor):
    event_type = "OperatorRenamed"
    leader_key = "reactor_operator_renamed"
    name = "OperatorRenamed"

    async def handle_event(self, event_data: dict) -> None:
        old_slug = event_data.get("old_slug") or ""
        new_slug = event_data.get("new_slug") or ""
        if not old_slug or not new_slug or old_slug == new_slug:
            logger.warning(
                f"[Reactor:{self.name}] ignoring malformed OperatorRenamed: "
                f"old={old_slug!r} new={new_slug!r}"
            )
            return

        if os.getenv("REACTOR_OPERATOR_RENAME_FANOUT_ENABLED", "true").lower() != "true":
            logger.info(f"[Reactor:{self.name}] fanout disabled by env; skipping {old_slug}->{new_slug}")
            return

        logger.info(f"[Reactor:{self.name}] fanning out rename {old_slug} → {new_slug} to peers")
        summary = await fanout_operator_rename_to_peers(
            old_slug=old_slug,
            new_slug=new_slug,
            new_base_url=event_data.get("new_base_url") or "",
            new_operator_did=event_data.get("new_operator_did") or "",
            source_label=self.name,
        )
        if summary["attempted"]:
            logger.info(
                f"[Reactor:{self.name}] op-rename fanout: "
                f"{summary['successful']}/{summary['attempted']} peers OK"
            )


_instance: Optional[OperatorRenamedReactor] = None


async def start() -> None:
    global _instance
    if _instance is None:
        _instance = OperatorRenamedReactor()
    await _instance.start()


async def stop() -> None:
    global _instance
    if _instance is not None:
        await _instance.stop()
        _instance = None
