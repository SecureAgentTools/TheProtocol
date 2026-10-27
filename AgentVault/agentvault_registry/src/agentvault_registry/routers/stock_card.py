"""Federated Stock Card — public well-known + API endpoints.

Routes (public, no auth — stock cards are public signed documents):
  GET /.well-known/stock-card.json   — signed AGORA catalog, ETag + 304
  GET /api/v1/exchange/stock-card    — same payload, API-namespaced alias

Mounted with NO prefix (app.include_router(stock_card.router)) so the
well-known path holds — same pattern as routers/registry_card.py.

NB: do NOT add `from __future__ import annotations` here — FastAPI introspects
handler annotations at registration; the `Response` forward ref crashes schema
gen. See feedback_serve_well_known_card_pattern.md.
"""
import json
import logging
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..services import stock_card_builder

logger = logging.getLogger(__name__)

router = APIRouter(tags=["AGORA Card"])   # §AGORAWORDS (V0419): the schema group name (no tester category follows it)

_CACHE_CONTROL_VALUE = "public, max-age=300, stale-while-revalidate=600"

# Per-worker built-body cache keyed by digest — repeat 200s skip build+sign.
_CARD_CACHE: Dict[str, Any] = {"etag": None, "body": None, "ts": 0.0}
_CARD_CACHE_TTL = 30.0


def _strip_quotes(v: Optional[str]) -> Optional[str]:
    if not v:
        return None
    v = v.strip()
    if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
        v = v[1:-1]
    return v


async def _serve_stock_card(if_none_match: Optional[str], db: AsyncSession) -> Response:
    # No venue here → no catalog to publish. 404 keeps the registry-card link
    # absent on non-venue registries (consumers skip).
    if not stock_card_builder.exchange_enabled():
        return Response(
            content=json.dumps({"error": "no_venue"}),
            media_type="application/json",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    # Cheap 304: digest only (small catalog SELECT, no sign).
    serve_etag = None
    try:
        serve_etag, _count = await stock_card_builder.stock_card_digest_and_count(db)
    except Exception as e:
        logger.debug("[StockCard] cheap digest failed; full build: %s", e)

    client_etag = _strip_quotes(if_none_match)
    if serve_etag and client_etag and client_etag == serve_etag:
        return Response(
            status_code=status.HTTP_304_NOT_MODIFIED,
            headers={"ETag": f'"{serve_etag}"', "Cache-Control": _CACHE_CONTROL_VALUE},
        )

    now = time.monotonic()
    if (serve_etag and _CARD_CACHE["etag"] == serve_etag
            and _CARD_CACHE["body"] is not None
            and (now - _CARD_CACHE["ts"]) < _CARD_CACHE_TTL):
        body = _CARD_CACHE["body"]
        etag = serve_etag
    else:
        card = await stock_card_builder.build_stock_card(db, sign=True)
        etag = card.get("digest") or serve_etag or ""
        body = json.dumps(card, separators=(",", ":"), default=str).encode("utf-8")
        _CARD_CACHE.update({"etag": etag, "body": body, "ts": now})

    return Response(
        content=body,
        media_type="application/json",
        headers={
            "ETag": f'"{etag}"',
            "Cache-Control": _CACHE_CONTROL_VALUE,
            "X-Stock-Card-Version": stock_card_builder.STOCK_CARD_VERSION,
        },
    )


@router.get(
    "/.well-known/agora-card.json",
    response_class=Response,
    summary="Public signed AGORA Card (catalog)",
    description=(
        "Returns this registry's EdDSA-signed AGORA listing catalog (catalog only, "
        "no live prices). Verify the signature against /.well-known/registry-jwks.json. "
        "ETag-driven; supports If-None-Match → 304. 404 when this registry hosts no AGORA market. "
        "An older well-known name serves the same document."
    ),
)
# §AGORAWORDS (V0419): the old well-known name stays live (peers pull it; federation_sync caches it).
@router.get("/.well-known/stock-card.json", response_class=Response, include_in_schema=False)
async def get_well_known_stock_card(
    if_none_match: Optional[str] = Header(default=None, alias="If-None-Match"),
    db: AsyncSession = Depends(get_db),
) -> Response:
    return await _serve_stock_card(if_none_match, db)


@router.get(
    "/api/v1/agora/card",
    response_class=Response,
    summary="Signed AGORA Card (API alias of /.well-known/agora-card.json)",
)
@router.get("/api/v1/exchange/stock-card", response_class=Response, include_in_schema=False)
async def get_api_stock_card(
    if_none_match: Optional[str] = Header(default=None, alias="If-None-Match"),
    db: AsyncSession = Depends(get_db),
) -> Response:
    return await _serve_stock_card(if_none_match, db)
