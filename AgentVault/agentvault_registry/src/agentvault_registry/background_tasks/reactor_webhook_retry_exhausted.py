"""
Reactor: WebhookRetryExhausted → developer notification + meta-webhook
======================================================================
Webhook deliveries auto-disable after 10 consecutive failures
(`WebhookService.MAX_CONSECUTIVE_FAILURES`). Without this reactor, the
developer is never told — their integration silently goes dark.

Side effects:
1. **Webhook fan-out** (`webhook.retry_exhausted`) — meta-webhook to the
   developer's OTHER active webhooks. Useful if they have a fallback channel
   subscribed to this event type.
2. **Email** (sovereign theme) — sent to the developer's account email.
   Tells them the integration is offline, links to the webhook console.

Intraregistry consequences: none. The webhook row is already updated to
`is_active=false` by `WebhookService.deliver_webhook` BEFORE the event
fires. The reactor is purely outbound notification.

Per-worker note: this reactor is leader-elected (single instance per
process group), so even if all 4 uvicorn workers run it, only one
dispatches.
"""
import logging
from typing import Optional

from .reactor_base import EventStoreReactor
from .reactor_helpers import (
    dispatch_webhook_event,
    get_developer_email,
    is_notification_stale,
    local_developer_id,
    send_reactor_email,
)

logger = logging.getLogger(__name__)


class WebhookRetryExhaustedReactor(EventStoreReactor):
    event_type = "WebhookRetryExhausted"
    leader_key = "reactor_webhook_retry_exhausted"
    name = "WebhookRetryExhausted"

    async def handle_event(self, event_data: dict) -> None:
        # §pass63 pattern: drop stale boot/WS replays so a process restart does not
        # re-email a months-old webhook exhaustion. See FINDING_2026-05-29_DISPUTE_EMAIL_ON_RESTART.md.
        stale, age_sec = is_notification_stale(event_data)
        if stale:
            logger.info(f"[Reactor:{self.name}] Skipping stale replay (age={int(age_sec or 0)}s)")
            return

        webhook_id = event_data.get("webhook_id") or "?"
        developer_id = event_data.get("developer_id")
        target_url = event_data.get("target_url") or "?"
        consecutive_failures = event_data.get("consecutive_failures", "?")

        logger.info(
            f"[Reactor:{self.name}] webhook={webhook_id} dev={developer_id} "
            f"target={target_url} failures={consecutive_failures} — fanning out"
        )

        # Side effect 1: webhook fanout (meta-webhook to other channels)
        # §TWOAGENT #34 class (2026-09-23): "another webhook of YOURS was auto-disabled" goes to that developer only,
        # and a bridged event names no local developer (a peer's developer 12 is not ours): the email below too.
        _dev = local_developer_id(event_data, key="developer_id")
        if _dev is not None:
            await dispatch_webhook_event(
                event_type="webhook.retry_exhausted",
                event_data=event_data,
                source_label=self.name,
                developer_id=_dev,
            )

        # Side effect 2: email developer
        if _dev is None:
            return
        email = await get_developer_email(_dev)
        if not email:
            logger.warning(
                f"[Reactor:{self.name}] No email found for developer_id={developer_id}"
            )
            return
        await send_reactor_email(
            subject=f"Webhook auto-disabled — {target_url}",
            recipients=[email],
            template="webhook_retry_exhausted",
            context={
                "webhook_id": webhook_id,
                "target_url": target_url,
                "consecutive_failures": consecutive_failures,
                "last_response_code": event_data.get("last_response_code"),
                "last_error": event_data.get("last_error", "—"),
                "disabled_at": event_data.get("disabled_at", "—"),
            },
            theme="sovereign",
            source_label=self.name,
        )


_instance: Optional[WebhookRetryExhaustedReactor] = None


async def start() -> None:
    global _instance
    if _instance is None:
        _instance = WebhookRetryExhaustedReactor()
    await _instance.start()


async def stop() -> None:
    global _instance
    if _instance is not None:
        await _instance.stop()
        _instance = None
