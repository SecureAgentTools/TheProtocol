"""
Reactor: EventEmissionPolicyUpdated → cache invalidation propagation
=====================================================================
When an admin changes a row in `event_emission_policies` via the registry's
PUT /admin/event-emission-policies/{event_type} endpoint, the f037 system
needs to invalidate caches across the registry process group AND in TEG.

Without this reactor, caches are TTL-bound:
- Registry-side `_emission_policy_cache`: 60s TTL (event_emitter.py:757)
- TEG-side `_teg_policy_cache`: 120s TTL (event_emitter.py:27)

So a policy flip at 12:00:00 might not take effect until 12:02:00 across
all workers.

The reactor closes the gap:
1. Side effect 1 (intra-registry): call the local `_load_emission_policies()`
   to refresh THIS worker's cache. (The admin handler already did this for
   the worker that processed the PUT; the reactor covers the leader worker
   too, so 2-of-N workers get fresh caches immediately. The remaining N-2
   workers still wait for their 60s TTL.)
2. Side effect 2 (intra-TEG): POST /api/v1/cross-teg/admin/emission-policy/refresh
   to force TEG's leader worker to drop its cache. Same per-worker
   limitation as the registry side.
3. Side effect 3 (out-of-process): webhook fanout
   `federation.emission_policy_updated` for integrators.

Full cross-worker uniformity is Phase 10 work (Redis-backed cache).
"""
import logging
import os
from typing import Optional

from .reactor_base import EventStoreReactor
from .reactor_helpers import dispatch_webhook_event

logger = logging.getLogger(__name__)


async def _refresh_local_registry_cache(source_label: str) -> None:
    """Reload this registry worker's _emission_policy_cache from DB."""
    try:
        from agentvault_registry.event_emitter import _load_emission_policies
        await _load_emission_policies()
        logger.info(
            f"[ReactorHelper:{source_label}] Local registry policy cache refreshed"
        )
    except Exception as e:
        logger.warning(
            f"[ReactorHelper:{source_label}] Local cache refresh failed: {e}"
        )


async def _refresh_teg_policy_cache(source_label: str) -> None:
    """POST {TEG}/api/v1/cross-teg/admin/emission-policy/refresh."""
    teg_url = os.getenv("TEG_API_BASE_URL", "http://teg-layer:8080").rstrip("/")
    teg_key = os.getenv("TEG_ADMIN_API_KEY", "")
    if not teg_key:
        logger.warning(
            f"[ReactorHelper:{source_label}] TEG_ADMIN_API_KEY not set — "
            f"cannot refresh TEG policy cache"
        )
        return

    url = f"{teg_url}/api/v1/cross-teg/admin/emission-policy/refresh"
    headers = {"Authorization": f"Bearer {teg_key}", "Content-Type": "application/json"}

    try:
        # §MTLSHOPS V0378: the registry's pooled, SVID-self-healing TEG client (reactor_helpers moved to it on 2026-06-16).
        # The bare aiohttp session presented no certificate, which a TEG behind <f>-nginx-teg refuses.
        from agentvault_registry.routers.teg_integration import _get_teg_client
        resp = await _get_teg_client().post(url, headers=headers, timeout=10.0)
        if resp.status_code >= 400:
            logger.warning(
                f"[ReactorHelper:{source_label}] TEG cache-refresh returned "
                f"{resp.status_code}: {resp.text[:300]}"
            )
            return
        body = resp.json()
        logger.info(
            f"[ReactorHelper:{source_label}] TEG cache refreshed → "
            f"{body.get('policy_count')} policies, worker_pid={body.get('worker_pid')}"
        )
    except Exception as e:
        logger.warning(
            f"[ReactorHelper:{source_label}] TEG cache-refresh network error: {e}"
        )


class EventEmissionPolicyUpdatedReactor(EventStoreReactor):
    event_type = "EventEmissionPolicyUpdated"
    leader_key = "reactor_emission_policy_updated"
    name = "EventEmissionPolicyUpdated"

    async def handle_event(self, event_data: dict) -> None:
        ev_type = event_data.get("event_type") or "?"
        emit_from_teg = event_data.get("emit_from_teg")
        emit_from_registry = event_data.get("emit_from_registry")
        skip_in_projection = event_data.get("skip_in_projection")
        # §DOCSFIX D6-612: the event names its admin by developer id (older events also carried the address)
        actor = event_data.get("actor_developer_id") or "?"

        logger.info(
            f"[Reactor:{self.name}] policy={ev_type} "
            f"teg={emit_from_teg} reg={emit_from_registry} skip={skip_in_projection} "
            f"actor={actor} — invalidating caches"
        )

        # Side effect 1: local registry cache (this worker's _emission_policy_cache)
        await _refresh_local_registry_cache(self.name)

        # Side effect 2: TEG cache (one TEG worker; others self-heal at TTL)
        await _refresh_teg_policy_cache(self.name)

        # Side effect 3: webhook fanout. An older event still carries the admin's address (actor_email); it is
        # not passed on to webhook subscribers.
        await dispatch_webhook_event(
            event_type="federation.emission_policy_updated",
            event_data={k: v for k, v in event_data.items() if k != "actor_email"},
            source_label=self.name,
        )


_instance: Optional[EventEmissionPolicyUpdatedReactor] = None


async def start() -> None:
    global _instance
    if _instance is None:
        _instance = EventEmissionPolicyUpdatedReactor()
    await _instance.start()


async def stop() -> None:
    global _instance
    if _instance is not None:
        await _instance.stop()
        _instance = None
