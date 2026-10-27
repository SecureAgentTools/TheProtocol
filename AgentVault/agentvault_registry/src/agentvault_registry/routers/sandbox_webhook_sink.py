"""A webhook receiver for the sandbox's own tests (§MCPTEST30 V0637, agentvault2-aa, 2026-10-24; agentvault2-d6's four
conditions). ``POST /api/v1/sandbox/webhook-sink/{webhook_id}`` answers 204 when the delivery's
``X-TheProtocol-Signature`` verifies against that webhook's stored secret over the body exactly as received.

The MCP tester's webhook lifecycle names this frame's own public host and this path as its webhook, so testWebhook and
the legacy test route are measured on a real signed delivery: the delivery's address check passes the frame's public
address (D6-760, SEC-14) and the frame reaches itself through its edge. Before it, the run's webhook named a host
that resolves to nothing, so every test delivery failed by design.

- A positive flag, ``SANDBOX_WEBHOOK_SINK_ENABLED``, default off. Off, the router is never mounted, so the path answers
  exactly as an unknown route does. Production never carries the flag.
- One refusal for every failure (an unknown or malformed id, a missing or bad signature, a body over the cap), so the
  sink never tells which webhook ids exist. The compare is constant-time, and an unknown id is verified against a
  throwaway key, so both paths do the same work.
- The body is read through the stream with a cap before anything is verified. Neither the body nor the signature is
  logged, and nothing is written.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry import models
from agentvault_registry.database import get_db

FLAG = "SANDBOX_WEBHOOK_SINK_ENABLED"
PATH = "/api/v1/sandbox/webhook-sink"
SIGNATURE_HEADER = "X-TheProtocol-Signature"   # what WebhookService.deliver_webhook sends
MAX_BODY = 64 * 1024                           # a test delivery's envelope is a few hundred bytes
# the two id shapes the registry mints: routers/webhooks.py str(uuid4()), the legacy routers/developers.py "wh-" and
# 16 hex. Anything else (a NUL, an upper-case or overlong id) is refused before the query, so Postgres never sees it
# and the answer stays the one refusal
WEBHOOK_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|wh-[0-9a-f]{16}")
REFUSED = "This delivery was not accepted."    # every refusal says only this

_THROWAWAY_KEY = secrets.token_hex(32)          # verifies the body of an unknown id, so both paths do the same work

router = APIRouter(prefix=PATH, tags=["Sandbox"])


def sink_enabled() -> bool:
    """True only when the flag is set to a true word; unset, empty or anything else is off."""
    return (os.getenv(FLAG, "") or "").strip().lower() in ("1", "true", "yes", "on")


def mount(app: FastAPI) -> bool:
    """Mounts the sink when its flag is on and says whether it did. Off, nothing is added to the app."""
    if not sink_enabled():
        return False
    app.include_router(router)
    return True


async def _read_capped(request: Request) -> Optional[bytes]:
    """The body as received, or None when it is longer than MAX_BODY (declared or read)."""
    declared = (request.headers.get("content-length") or "").strip()
    if declared.isdigit() and int(declared) > MAX_BODY:
        return None
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_BODY:
            return None
    return bytes(body)


async def _webhook_secret(db: AsyncSession, webhook_id: str) -> Optional[str]:
    if not WEBHOOK_ID.fullmatch(webhook_id or ""):
        return None
    secret = (await db.execute(
        select(models.DeveloperWebhook.secret).where(models.DeveloperWebhook.id == webhook_id))).scalar_one_or_none()
    return secret or None


@router.post("/{webhook_id}", status_code=204, include_in_schema=False)
async def webhook_sink(webhook_id: str, request: Request, db: AsyncSession = Depends(get_db)) -> Response:
    body = await _read_capped(request)
    secret = await _webhook_secret(db, webhook_id) if body is not None else None
    expected = hmac.new((secret or _THROWAWAY_KEY).encode(), body or b"", hashlib.sha256).hexdigest()
    given = (request.headers.get(SIGNATURE_HEADER) or "").encode("utf-8", "replace")
    if not (hmac.compare_digest(expected.encode(), given) and secret is not None and body is not None):
        raise HTTPException(status_code=403, detail=REFUSED)
    return Response(status_code=204)
