"""
Reactor: ComplianceDryRunDrift → audit propagation
====================================================
Mirror of `reactor_drift_detected` for the parallel drift event type emitted
by the cross-frame compliance_poller (the Phase 9 mTLS-authenticated polling
loop) when a peer's policy_hash mismatches admission OR a peer is unreachable
3+ times in a row, and the CONSUL enforcement_mode is `dry_run`.

Two drift event types in the system:
- `FederationStateDriftDetected` — emitted by `license_drift_monitor` (DB-internal,
  hourly cross-table drift detection). Consumed by `reactor_drift_detected`.
- `ComplianceDryRunDrift` — emitted by `compliance_poller` (HTTP cross-frame, 6h,
  dry_run mode only). Consumed here.

Both surface in the CONSUL "Recent compliance events" feed; this reactor adds
the webhook propagation path for the dry-run-drift channel.

The poller emits with idempotency only via the EventStore unique constraint
on idempotency_key — but it does NOT set one for ComplianceDryRunDrift
(check `_emit_dry_run_drift` in compliance_poller.py). So multiple cycles
emit one event each. The reactor sees every event, not deduplicated. That's
acceptable for dry-run audit volume (max 1 per peer per 6h cycle).
"""
import logging
from typing import Optional

from .reactor_base import EventStoreReactor
from .reactor_helpers import dispatch_webhook_event

logger = logging.getLogger(__name__)


class ComplianceDryRunDriftReactor(EventStoreReactor):
    event_type = "ComplianceDryRunDrift"
    leader_key = "reactor_compliance_dry_run_drift"
    name = "ComplianceDryRunDrift"

    async def handle_event(self, event_data: dict) -> None:
        peer_id = event_data.get("peer_registry_id") or "?"
        peer_name = event_data.get("peer_name") or "?"
        trigger = event_data.get("trigger") or "?"
        severity = event_data.get("severity") or "?"
        what_would = event_data.get("what_would_happen") or "?"
        logger.info(
            f"[Reactor:{self.name}] peer={peer_name} ({peer_id}) trigger={trigger} "
            f"severity={severity} would_fire={what_would} — propagating webhook"
        )
        await dispatch_webhook_event(
            event_type="federation.dry_run_drift",
            event_data=event_data,
            source_label=self.name,
        )


_instance: Optional[ComplianceDryRunDriftReactor] = None


async def start() -> None:
    global _instance
    if _instance is None:
        _instance = ComplianceDryRunDriftReactor()
    await _instance.start()


async def stop() -> None:
    global _instance
    if _instance is not None:
        await _instance.stop()
        _instance = None
