"""
Reactor: FederationStateDriftDetected → audit propagation
==========================================================
The license_drift_monitor (started when IS_CENTRAL_REGISTRY=true) detects
inconsistencies between peer_registries / operator_applications /
federation_licenses every hour. Each detection emits
`FederationStateDriftDetected` with per-day idempotency.

Without this reactor, drift events sit silently in EventStore as audit-only.
With this reactor, they fan out to:
- Registered developer webhooks subscribed to `federation.drift_detected`

The CONSUL UI (`ComplianceMonitor.vue`) also reads recent drift events via
`GET /admin/federation/compliance/drifts` — that's a pull path, this reactor
is the push path. Both layers are best-effort safety nets.

Daily idempotency at emission caps re-fires; this reactor sees at most one
event per drift per UTC day.
"""
import logging
import time
from typing import Optional

from .reactor_base import EventStoreReactor
from .reactor_helpers import dispatch_webhook_event

logger = logging.getLogger(__name__)

# 2026-05-08: throttle the live WS notification (NOT the webhook dispatch)
# so a multi-peer drift sweep doesn't spam toasts to every connected user.
# Per-process state — leader-elected so single source of truth across workers.
_NOTIF_THROTTLE_SECONDS = 60
_last_notif_at: float = 0.0


class FederationStateDriftDetectedReactor(EventStoreReactor):
    event_type = "FederationStateDriftDetected"
    leader_key = "reactor_drift_detected"
    name = "FederationStateDriftDetected"

    async def handle_event(self, event_data: dict) -> None:
        drift_type = event_data.get("drift_type") or "?"
        peer_id = event_data.get("peer_id") or event_data.get("peer", "?")
        license_id = event_data.get("license_id") or "?"
        operator_id = event_data.get("operator_application_id") or "?"
        logger.info(
            f"[Reactor:{self.name}] drift_type={drift_type} peer={peer_id} "
            f"license={license_id} operator={operator_id} — propagating webhook"
        )
        await dispatch_webhook_event(
            event_type="federation.drift_detected",
            event_data=event_data,
            source_label=self.name,
        )

        # E (2026-05-08): live WS notification (throttled). Multi-peer
        # drift sweeps emit one event per peer; without throttling, every
        # connected user gets a toast storm. 60s throttle keeps the alert
        # signal while suppressing the noise. Webhook dispatch above
        # ALWAYS fires (per-event audit trail).
        global _last_notif_at
        now = time.monotonic()
        if (now - _last_notif_at) >= _NOTIF_THROTTLE_SECONDS:
            try:
                from agentvault_registry.routers.websocket import broadcast_notification
                await broadcast_notification(
                    title="Federation drift detected",
                    message=f"{drift_type} on peer {peer_id}",
                    notification_type="warning",
                )
                _last_notif_at = now
            except Exception as e:
                logger.warning(f"[Reactor:{self.name}] broadcast_notification failed (non-fatal): {e}")


_instance: Optional[FederationStateDriftDetectedReactor] = None


async def start() -> None:
    global _instance
    if _instance is None:
        _instance = FederationStateDriftDetectedReactor()
    await _instance.start()


async def stop() -> None:
    global _instance
    if _instance is not None:
        await _instance.stop()
        _instance = None
