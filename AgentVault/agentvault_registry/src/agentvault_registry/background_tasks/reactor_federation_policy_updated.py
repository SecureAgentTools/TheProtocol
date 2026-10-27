"""
Reactor: FederationPolicyUpdated → immediate compliance re-poll (A4, 2026-07-24)
================================================================================
FederationPolicyUpdated was emitted (2 sites) with ZERO consumers — a federation
policy change only propagated via the compliance poller's 6-hour cycle. With B10
(federation governance APPLY becoming real) the staleness window matters: a
passed + applied network proposal should be observed promptly.

On the event: trigger ONE immediate compliance poll cycle (central registries
only — the poller exists solely where IS_CENTRAL_REGISTRY=true; elsewhere this
reactor just logs the observation). Best-effort and throttled: policy updates
are rare, but a burst collapses into one refresh per REACTOR_FEDPOLICY_THROTTLE_SEC.
"""
import logging
import os
import time
from typing import Optional

from .reactor_base import EventStoreReactor

logger = logging.getLogger(__name__)

_THROTTLE_SEC = int(os.getenv("REACTOR_FEDPOLICY_THROTTLE_SEC", "60"))
_last_refresh = 0.0


class FederationPolicyUpdatedReactor(EventStoreReactor):
    event_type = "FederationPolicyUpdated"
    leader_key = "reactor_federation_policy_updated"
    name = "FederationPolicyUpdated"

    async def handle_event(self, event_data: dict) -> None:
        global _last_refresh
        src = event_data.get("proposal_id") or event_data.get("source") or "?"
        logger.info(f"[Reactor:{self.name}] federation policy updated (src={src})")

        now = time.monotonic()
        if now - _last_refresh < _THROTTLE_SEC:
            logger.info(f"[Reactor:{self.name}] refresh throttled ({_THROTTLE_SEC}s)")
            return
        _last_refresh = now

        if os.getenv("IS_CENTRAL_REGISTRY", "false").lower() != "true":
            return  # nothing to refresh here; observation logged above

        try:
            from agentvault_registry.background_tasks.compliance_poller import get_compliance_poller
            poller = get_compliance_poller()
            await poller._poll_cycle()  # one immediate cycle instead of waiting up to 6h
            logger.info(f"[Reactor:{self.name}] immediate compliance poll cycle completed")
        except Exception as e:  # noqa: BLE001 — the 6h cycle remains the backstop
            logger.warning(f"[Reactor:{self.name}] immediate compliance poll failed: {e}")


_instance: Optional[FederationPolicyUpdatedReactor] = None


async def start() -> None:
    global _instance
    if _instance is None:
        _instance = FederationPolicyUpdatedReactor()
    await _instance.start()


async def stop() -> None:
    global _instance
    if _instance is not None:
        await _instance.stop()
        _instance = None
