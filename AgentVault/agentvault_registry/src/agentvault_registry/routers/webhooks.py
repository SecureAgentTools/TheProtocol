"""
Webhook Management Router — CRUD for developer webhooks.

Endpoints:
  POST   /api/v1/webhooks          — Create webhook
  GET    /api/v1/webhooks          — List your webhooks
  GET    /api/v1/webhooks/{id}     — Get webhook details
  PUT    /api/v1/webhooks/{id}     — Update webhook
  DELETE /api/v1/webhooks/{id}     — Delete webhook
  GET    /api/v1/webhooks/{id}/deliveries — Delivery history
  POST   /api/v1/webhooks/{id}/test — Send test event
"""

import logging
import secrets
import uuid
from typing import List, Optional
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status, Query, Security
from pydantic import BaseModel, Field, HttpUrl, field_validator
from sqlalchemy import delete, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry.database import get_db
from agentvault_registry.security import get_current_developer
from agentvault_registry import models
from agentvault_registry.services.webhook_service import DELIVERY_OUTCOMES, WebhookService, delivery_outcome_clause

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/webhooks", tags=["Webhooks"])


# ── Schemas ──

class WebhookCreate(BaseModel):
    url: str = Field(..., max_length=500, description="Endpoint URL for webhook delivery")
    events: List[str] = Field(..., min_length=1, description="Event types to subscribe to")
    description: Optional[str] = Field(None, max_length=500, description="Optional description")

    @field_validator("url")
    @classmethod
    def validate_url(cls, v):
        # the literal checks here; the route resolves the host off the event loop (_refuse_internal_url)
        from agentvault_registry.input_validators import validate_webhook_url
        return validate_webhook_url(v, resolve=False)


class WebhookUpdate(BaseModel):
    url: Optional[str] = Field(None, max_length=500)
    events: Optional[List[str]] = None
    is_active: Optional[bool] = None
    description: Optional[str] = Field(None, max_length=500)

    @field_validator("url")
    @classmethod
    def validate_url(cls, v):
        if v is not None:
            from agentvault_registry.input_validators import validate_webhook_url
            return validate_webhook_url(v, resolve=False)
        return v


async def _refuse_internal_url(url: str) -> None:
    """D6-760: the URL's host, resolved, must not reach an internal address (422 like the literal checks)."""
    from agentvault_registry.input_validators import avalidate_webhook_url
    try:
        await avalidate_webhook_url(url)
    except ValueError as e:
        raise HTTPException(422, detail=str(e))


class WebhookResponse(BaseModel):
    id: str
    url: str
    events: List[str]
    is_active: bool
    secret: Optional[str] = None  # Only shown on create
    failure_count: int = 0
    created_at: Optional[str] = None
    last_triggered_at: Optional[str] = None


# ── Endpoints ──

@router.post("", response_model=WebhookResponse, status_code=201)
async def create_webhook(
    body: WebhookCreate,
    developer=Security(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Create a new webhook subscription."""
    await _refuse_internal_url(body.url)
    # Validate events
    valid_events = WebhookService.SUPPORTED_EVENTS
    invalid = [e for e in body.events if e not in valid_events]
    if invalid:
        raise HTTPException(400, f"Invalid event types: {invalid}. Valid: {valid_events}")

    # Check limit (max 10 per developer)
    count = await db.scalar(
        select(func.count()).select_from(models.DeveloperWebhook).where(
            models.DeveloperWebhook.developer_id == developer.id
        )
    )
    if count >= 10:
        raise HTTPException(400, "Maximum 10 webhooks per developer")

    secret = secrets.token_hex(32)
    webhook = models.DeveloperWebhook(
        id=str(uuid.uuid4()),
        developer_id=developer.id,
        url=body.url,
        events=body.events,
        secret=secret,
        is_active=True,
        failure_count=0,
    )
    db.add(webhook)
    await db.commit()
    await db.refresh(webhook)

    logger.info(f"[Webhooks] Created webhook {webhook.id} for developer {developer.id}: {body.url}")

    return WebhookResponse(
        id=webhook.id, url=webhook.url, events=webhook.events,
        is_active=True, secret=secret,  # Show secret only on create
        created_at=webhook.created_at.isoformat() if webhook.created_at else None,
    )


@router.get("", response_model=List[WebhookResponse])
async def list_webhooks(
    developer=Security(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """List all your webhooks."""
    result = await db.execute(
        select(models.DeveloperWebhook).where(
            models.DeveloperWebhook.developer_id == developer.id
        ).order_by(models.DeveloperWebhook.created_at.desc())
    )
    webhooks = result.scalars().all()
    return [
        WebhookResponse(
            id=w.id, url=w.url, events=w.events, is_active=w.is_active,
            failure_count=w.failure_count,
            created_at=w.created_at.isoformat() if w.created_at else None,
            last_triggered_at=w.last_triggered_at.isoformat() if w.last_triggered_at else None,
        )
        for w in webhooks
    ]


@router.get("/{webhook_id}", response_model=WebhookResponse)
async def get_webhook(
    webhook_id: str,
    developer=Security(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Get webhook details."""
    webhook = await _get_owned_webhook(webhook_id, developer.id, db)
    return WebhookResponse(
        id=webhook.id, url=webhook.url, events=webhook.events, is_active=webhook.is_active,
        failure_count=webhook.failure_count,
        created_at=webhook.created_at.isoformat() if webhook.created_at else None,
        last_triggered_at=webhook.last_triggered_at.isoformat() if webhook.last_triggered_at else None,
    )


@router.put("/{webhook_id}", response_model=WebhookResponse)
async def update_webhook(
    webhook_id: str,
    body: WebhookUpdate,
    developer=Security(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Update a webhook."""
    webhook = await _get_owned_webhook(webhook_id, developer.id, db)

    if body.url is not None:
        await _refuse_internal_url(body.url)
        webhook.url = body.url
    if body.events is not None:
        valid_events = WebhookService.SUPPORTED_EVENTS
        invalid = [e for e in body.events if e not in valid_events]
        if invalid:
            raise HTTPException(400, f"Invalid event types: {invalid}")
        webhook.events = body.events
    if body.is_active is not None:
        webhook.is_active = body.is_active
        if body.is_active:
            webhook.failure_count = 0  # Reset failures on re-enable

    await db.commit()
    await db.refresh(webhook)

    return WebhookResponse(
        id=webhook.id, url=webhook.url, events=webhook.events, is_active=webhook.is_active,
        failure_count=webhook.failure_count,
        created_at=webhook.created_at.isoformat() if webhook.created_at else None,
        last_triggered_at=webhook.last_triggered_at.isoformat() if webhook.last_triggered_at else None,
    )


@router.delete("/{webhook_id}", status_code=204)
async def delete_webhook(
    webhook_id: str,
    developer=Security(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Delete a webhook, and its delivery history with it."""
    # The row is locked first (agentvault2-66, 2026-10-25): a delivery recorded between the two deletes below made the
    # webhook's own delete fail on the foreign key (409, the webhook kept), measured on a sandbox operator whose hook
    # took an agent.* delivery every few seconds. Locked, a delivery being recorded waits for this delete and then
    # finds its webhook gone, which the writer drops (services/webhook_service.py).
    webhook = await _get_owned_webhook(webhook_id, developer.id, db, for_update=True)
    # §MCPTEST30 (2026-10-06): the deliveries go first, in the same transaction. webhook_deliveries.webhook_id
    # references developer_webhooks.id with no ON DELETE CASCADE, so a webhook that had ever delivered could not be
    # deleted at all: Postgres refused on the foreign key and the developer read 409 "Referenced record does not
    # exist" about a record that plainly did (measured on sbx-alpha by the federation suite's chat_g1 cleanup,
    # 18:22Z). The history is the webhook's own; it goes with it.
    await db.execute(delete(models.WebhookDelivery).where(models.WebhookDelivery.webhook_id == webhook.id))
    await db.delete(webhook)
    await db.commit()
    logger.info(f"[Webhooks] Deleted webhook {webhook_id}")


@router.get("/{webhook_id}/deliveries")
async def list_deliveries(
    webhook_id: str,
    limit: int = Query(20, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    developer=Security(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Get recent delivery history for a webhook.

    Build #1 (2026-05-07): expanded response to include payload, response_body,
    and next_retry_at so the frontend can offer drill-down debugging without a
    second roundtrip per row. Also added optional status filter:
      ?status=success → a 2xx answer
      ?status=failed  → any other answer, a 3xx included (D6-786: retried like any failure since D6-765)
      ?status=pending → no answer: in flight, or none came (a timeout, a connection failure)
      ?status=retried → retry_count > 0, whatever the outcome
    success, failed and pending partition every row (services/webhook_service.delivery_outcome_clause).
    """
    await _get_owned_webhook(webhook_id, developer.id, db)  # Auth check

    query = select(models.WebhookDelivery).where(
        models.WebhookDelivery.webhook_id == webhook_id
    )

    if status_filter in DELIVERY_OUTCOMES:
        query = query.where(delivery_outcome_clause(status_filter))
    elif status_filter == "retried":
        query = query.where(models.WebhookDelivery.retry_count > 0)

    query = query.order_by(models.WebhookDelivery.delivered_at.desc()).limit(limit)
    result = await db.execute(query)
    deliveries = result.scalars().all()
    return {
        "webhook_id": webhook_id,
        "deliveries": [
            {
                "id": d.id,
                "event_type": d.event_type,
                "response_status": d.response_status,
                "response_body": d.response_body,
                "payload": d.payload,
                "retry_count": d.retry_count,
                "next_retry_at": d.next_retry_at.isoformat() if d.next_retry_at else None,
                "delivered_at": d.delivered_at.isoformat() if d.delivered_at else None,
                "error_message": d.error_message,
            }
            for d in deliveries
        ],
    }


@router.post("/{webhook_id}/test")
async def test_webhook(
    webhook_id: str,
    developer=Security(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Send a test event to the webhook."""
    webhook = await _get_owned_webhook(webhook_id, developer.id, db)

    service = WebhookService()
    async with service:
        delivery = await service.deliver_webhook(
            webhook=webhook,
            event_type="webhook.test",
            data={"message": "This is a test event from TheProtocol", "webhook_id": webhook_id},
            agent_did=None,
            db=db,
        )

    return {
        "success": delivery.response_status and 200 <= delivery.response_status < 300,
        "status_code": delivery.response_status,
        "delivery_id": delivery.id,
    }


@router.post("/{webhook_id}/deliveries/{delivery_id}/redeliver")
async def redeliver_delivery(
    webhook_id: str,
    delivery_id: str,
    developer=Security(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Re-send a past delivery's original payload through the live delivery path.

    Owner-scoped. Reuses the same WebhookService.deliver_webhook the retry worker
    and test-fire use, so signing/headers/retry accounting are identical. The
    original event_type + data are replayed verbatim; a fresh WebhookDelivery row
    records the outcome (the original row is left untouched for audit).
    """
    webhook = await _get_owned_webhook(webhook_id, developer.id, db)

    result = await db.execute(
        select(models.WebhookDelivery).where(
            models.WebhookDelivery.id == delivery_id,
            models.WebhookDelivery.webhook_id == webhook_id,
        )
    )
    original = result.scalar_one_or_none()
    if original is None:
        raise HTTPException(status_code=404, detail="Delivery not found for this webhook")

    # The envelope the original was sent with (stored whole since V0429; older rows held only its data).
    # A redelivery is a NEW delivery by design (a fresh id the receiver has not seen), carrying the same
    # event, data and agent_did (§TWOAGENT #33: agent_did was dropped, and a data dict with its own "data"
    # key was unwrapped one level too far).
    envelope = WebhookService.stored_envelope(original)
    event_type = original.event_type or envelope.get("event") or "webhook.redelivery"

    service = WebhookService()
    async with service:
        delivery = await service.deliver_webhook(
            webhook=webhook,
            event_type=event_type,
            data=envelope.get("data") or {},
            agent_did=envelope.get("agent_did"),
            db=db,
        )

    return {
        "success": bool(delivery.response_status and 200 <= delivery.response_status < 300),
        "status_code": delivery.response_status,
        "delivery_id": delivery.id,
        "redelivery_of": delivery_id,
    }


@router.get("/events/supported")
async def list_supported_events(developer=Security(get_current_developer)):
    """List all supported webhook event types."""
    return {"events": WebhookService.SUPPORTED_EVENTS}


async def _get_owned_webhook(webhook_id: str, developer_id: int, db: AsyncSession, *,
                             for_update: bool = False) -> models.DeveloperWebhook:
    stmt = select(models.DeveloperWebhook).where(
        models.DeveloperWebhook.id == webhook_id,
        models.DeveloperWebhook.developer_id == developer_id,
    )
    result = await db.execute(stmt.with_for_update() if for_update else stmt)
    webhook = result.scalar_one_or_none()
    if not webhook:
        raise HTTPException(404, "Webhook not found")
    return webhook
