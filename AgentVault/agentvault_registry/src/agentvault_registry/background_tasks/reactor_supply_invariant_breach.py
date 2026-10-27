"""
Reactor: SupplyInvariantBreach → alert dispatch
================================================
The supply auditor runs every 60s and emits `SupplyInvariantBreach` to the
EventStore on every breach cycle. This reactor consumes those events and
dispatches alerts: registered webhooks (`supply.invariant_breach`) + critical
log line + optional email to `SUPPLY_ALERT_RECIPIENTS`.

**Throttle.** The auditor re-emits every 60s while in BREACH state. Without
throttling, a sustained breach generates an alert flood. The reactor keeps a
last-alert timestamp in memory and suppresses repeat dispatches within
`SUPPLY_ALERT_THROTTLE_SECONDS` (default 5 min). State change to a different
delta resets the throttle (escalations always alert).

**Backlog replay safety.** EventStore replays the last 15 events on subscribe.
The throttle naturally dedups: replay floods are suppressed because all events
in a sustained breach window have similar deltas.
"""
import logging
import time
from typing import Optional

from .reactor_base import EventStoreReactor
from .reactor_helpers import dispatch_supply_breach_alert, is_notification_stale

logger = logging.getLogger(__name__)


class SupplyInvariantBreachReactor(EventStoreReactor):
    event_type = "SupplyInvariantBreach"
    leader_key = "reactor_supply_invariant_breach"
    name = "SupplyInvariantBreach"

    def __init__(self) -> None:
        super().__init__()
        # In-memory throttle state (per worker — leader-elected so only one
        # worker dispatches anyway, single source of truth).
        self._last_alert_at: float = 0.0
        self._last_alert_delta: Optional[str] = None

    async def handle_event(self, event_data: dict) -> None:
        delta = event_data.get("delta", "?")
        net_supply = event_data.get("net_supply", "?")
        total_circulating = event_data.get("total_circulating", "?")
        detected_at = event_data.get("detected_at", "?")

        # §pass63 follow-up (2026-05-22) — silence stale replays at boot.
        # ES replays last 15 events on subscribe + polling-backstop lookback
        # picks up old events too. Without this guard, every container
        # restart fires CRITICAL log + WS toast + email for the 2026-04-11
        # historical breaches. Fresh breaches (within 1h) still alert
        # immediately; the auditor cycle is 60s so 1h is well above the
        # detection-to-emit budget. Override with
        # REACTOR_NOTIFICATION_MAX_AGE_SEC env var.
        stale, age_sec = is_notification_stale(event_data)
        if stale:
            logger.info(
                f"[Reactor:{self.name}] Skipping stale replay (age={int(age_sec or 0)}s, "
                f"detected_at={detected_at}, delta={delta}) — boot/backstop noise, "
                f"not a current breach"
            )
            return

        from agentvault_registry.config import settings
        throttle_s = float(getattr(settings, "SUPPLY_ALERT_THROTTLE_SECONDS", 300))
        now = time.monotonic()

        delta_changed = (self._last_alert_delta is not None
                         and self._last_alert_delta != delta)
        first_alert = self._last_alert_delta is None
        time_elapsed = (now - self._last_alert_at) >= throttle_s

        should_dispatch = first_alert or delta_changed or time_elapsed

        if not should_dispatch:
            logger.debug(
                f"[Reactor:{self.name}] Suppressed (throttle): delta={delta} "
                f"detected_at={detected_at} (last_alert={int(now - self._last_alert_at)}s ago)"
            )
            return

        # CRITICAL log — supply invariant breach is a financial-grade incident.
        # Anyone watching logs / log-aggregators / Prometheus log scrapers should
        # see this immediately even if webhooks/email fail.
        logger.critical(
            f"[SUPPLY-BREACH] delta={delta} net_supply={net_supply} "
            f"total_circulating={total_circulating} detected_at={detected_at}"
        )

        await dispatch_supply_breach_alert(event_data, source_label=self.name)

        # E (2026-05-08): live WS notification (critical tone). Same throttle
        # as the alert above so we don't spam toasts during sustained breach.
        try:
            from agentvault_registry.routers.websocket import broadcast_notification
            await broadcast_notification(
                title="Supply invariant breach",
                message=f"Δ={delta} · circulating={total_circulating}",
                notification_type="critical",
            )
        except Exception as e:
            logger.warning(f"[Reactor:{self.name}] broadcast_notification failed (non-fatal): {e}")

        self._last_alert_at = now
        self._last_alert_delta = str(delta)


# ----------------------------------------------------------------------- module API

_instance: Optional[SupplyInvariantBreachReactor] = None


async def start() -> None:
    global _instance
    if _instance is None:
        _instance = SupplyInvariantBreachReactor()
    await _instance.start()


async def stop() -> None:
    global _instance
    if _instance is not None:
        await _instance.stop()
        _instance = None
