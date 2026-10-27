"""AGORA Solvency Card — public well-known + API endpoints (P4).

Routes (public, no auth — solvency cards are public signed attestations):
  GET /.well-known/solvency-card.json — signed solvency/float attestation, ETag + 304
  GET /api/v1/exchange/solvency-card  — same payload, API-namespaced alias

Mounted with NO prefix (app.include_router(solvency_card.router)) so the
well-known path holds — same pattern as routers/stock_card.py / registry_card.py.

Double-gated: 404 unless BOTH `exchange_enabled()` (this registry hosts a venue)
AND `EXCHANGE_SOLVENCY_CARD_ENABLED` (the P4 flag, default OFF) are true. The
well-known card serves LIVE — its ETag is the full solvency digest (which moves
on every balance change) — so a short max-age=60 keeps it fresh without a
per-tick build (the 304 short-circuits unchanged state; the per-worker body
cache de-dups bursts within a 30s window).

NB: do NOT add `from __future__ import annotations` here — FastAPI introspects
handler annotations at registration; the `Response` forward ref crashes schema
gen. See feedback_serve_well_known_card_pattern.md.
"""
import json
import logging
import os
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..services import solvency_card_builder

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Solvency Card"])

# Live attestation → short max-age. The digest ETag + 304 handles freshness; the
# per-worker body cache (30s) de-dups within a burst.
_CACHE_CONTROL_VALUE = "public, max-age=60"

# Per-worker built-body cache keyed by digest — repeat 200s skip build+sign.
_CARD_CACHE: Dict[str, Any] = {"etag": None, "body": None, "ts": 0.0}
_CARD_CACHE_TTL = 30.0


def _solvency_card_enabled() -> bool:
    return (os.getenv("EXCHANGE_SOLVENCY_CARD_ENABLED", "false") or "false").strip().lower() in ("1", "true", "yes")


def _strip_quotes(v: Optional[str]) -> Optional[str]:
    if not v:
        return None
    v = v.strip()
    if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
        v = v[1:-1]
    return v


async def _serve_solvency_card(if_none_match: Optional[str], db: AsyncSession) -> Response:
    # 404 unless this registry hosts a venue AND the P4 flag is on. Keeps the
    # registry-card link absent until enabled (consumers skip).
    if not (solvency_card_builder.exchange_enabled() and _solvency_card_enabled()):
        return Response(
            content=json.dumps({"error": "no_venue"}),
            media_type="application/json",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    # Cheap-ish 304: solvency digest (reflects live state; no sign).
    serve_etag = None
    try:
        serve_etag, _count = await solvency_card_builder.solvency_digest_and_count(db)
    except Exception as e:
        logger.debug("[SolvencyCard] digest failed; full build: %s", e)

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
        card = await solvency_card_builder.build_solvency_card(db, sign=True)
        etag = card.get("digest") or serve_etag or ""
        body = json.dumps(card, separators=(",", ":"), default=str).encode("utf-8")
        _CARD_CACHE.update({"etag": etag, "body": body, "ts": now})

    return Response(
        content=body,
        media_type="application/json",
        headers={
            "ETag": f'"{etag}"',
            "Cache-Control": _CACHE_CONTROL_VALUE,
            "X-Solvency-Card-Version": solvency_card_builder.SOLVENCY_CARD_VERSION,
        },
    )


@router.get(
    "/.well-known/solvency-card.json",
    response_class=Response,
    summary="Public signed AGORA Solvency Card (solvency/launch-allocation attestation)",
    description=(
        "Returns this registry's EdDSA-signed AGORA solvency attestation: per-listing "
        "launch-allocation integrity (I-X1), treasury solvency (balance vs obligations), distribution "
        "coverage, and the market-global escrow invariant (I-X3/I-X4/I-X5 + delta). "
        "Verify the signature against /.well-known/registry-jwks.json. ETag-driven; "
        "supports If-None-Match → 304. 404 when this registry hosts no market or the "
        "solvency card is disabled."
    ),
)
async def get_well_known_solvency_card(
    if_none_match: Optional[str] = Header(default=None, alias="If-None-Match"),
    db: AsyncSession = Depends(get_db),
) -> Response:
    return await _serve_solvency_card(if_none_match, db)


@router.get(
    "/api/v1/agora/solvency-card",
    response_class=Response,
    summary="Signed AGORA Solvency Card (API alias of /.well-known/solvency-card.json)",
)
# §DOCSFIX D6-655 (2026-10-16): the AGORA name, as the AGORA card has it (/api/v1/agora/card, §AGORAWORDS); the older
# name stays live and out of the schema, like every /api/v1/exchange route.
@router.get("/api/v1/exchange/solvency-card", response_class=Response, include_in_schema=False)
async def get_api_solvency_card(
    if_none_match: Optional[str] = Header(default=None, alias="If-None-Match"),
    db: AsyncSession = Depends(get_db),
) -> Response:
    return await _serve_solvency_card(if_none_match, db)
