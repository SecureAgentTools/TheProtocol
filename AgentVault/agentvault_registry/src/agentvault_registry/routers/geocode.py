"""Geocoding relay (§LEGALKIT, 2026-09-20).

The console's location pickers (Settings, Registry Card editor) called nominatim.openstreetmap.org
straight from the browser, so every visitor's IP address and typed place name reached the OpenStreetMap
Foundation, unnamed in the Privacy Policy. The lookup now goes through the registry: the place text still
reaches OSMF (disclosed in Privacy § 5), the person's address does not.

Nominatim's usage policy: at most one request per second, an identifying User-Agent, and caching. All
three are honoured here; the browser-side debounce stays as it was.

  GET /api/v1/public/geocode?q=<place>   -> [{display_name, lat, lon}] (at most 5)
  GEOCODE_RELAY_ENABLED=true|false        (default true)
  GEOCODE_UPSTREAM                        (default https://nominatim.openstreetmap.org/search)
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query, status

from ..core import provider_facts as pf
from ..core.registry_identity import BUNDLED_IMAGE_TAG

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/public", tags=["Public"])

_UPSTREAM = os.getenv("GEOCODE_UPSTREAM", "https://nominatim.openstreetmap.org/search").strip()
_MIN_INTERVAL_S = 1.05          # the policy's one request per second, with a margin
_CACHE_TTL_S = 24 * 3600
_CACHE_MAX = 2000

_lock = asyncio.Lock()
_last_call = 0.0
_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def _enabled() -> bool:
    return os.getenv("GEOCODE_RELAY_ENABLED", "true").lower() in ("true", "1", "yes")


def user_agent() -> str:
    """Identifies the relay to the upstream, as its policy asks: software, version, a contact."""
    facts = pf.provider_facts()
    contact = facts.legal_email or facts.support_email or "operator-not-configured"
    return f"TheProtocol-registry/{BUNDLED_IMAGE_TAG} (geocode relay; {contact})"


def _normalize(q: str) -> str:
    return " ".join(q.strip().lower().split())


def _reduce(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for it in items[:5]:
        try:
            out.append({"display_name": str(it.get("display_name") or "")[:300],
                        "lat": float(it["lat"]), "lon": float(it["lon"])})
        except (KeyError, TypeError, ValueError):
            continue
    return out


@router.get("/geocode", summary="Resolve a place name to coordinates (relayed; the caller's address never leaves this frame)")
async def geocode(q: str = Query(..., min_length=2, max_length=200)):
    global _last_call
    if not _enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="geocode relay disabled on this frame")
    key = _normalize(q)
    now = time.monotonic()
    hit = _cache.get(key)
    if hit and now - hit[0] < _CACHE_TTL_S:
        return hit[1]
    async with _lock:
        wait = _MIN_INTERVAL_S - (time.monotonic() - _last_call)
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            async with httpx.AsyncClient(timeout=6.0, headers={"User-Agent": user_agent(), "Accept-Language": "en"}) as client:
                resp = await client.get(_UPSTREAM, params={"format": "json", "limit": 5, "q": q})
        except httpx.HTTPError as exc:
            logger.info("[geocode] upstream unreachable: %s", exc.__class__.__name__)
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="geocoding upstream unreachable")
        finally:
            _last_call = time.monotonic()
    if resp.status_code != 200:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"geocoding upstream answered {resp.status_code}")
    try:
        items = resp.json()
    except ValueError:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="geocoding upstream answered no JSON")
    result = _reduce(items if isinstance(items, list) else [])
    if len(_cache) >= _CACHE_MAX:
        _cache.clear()
    _cache[key] = (time.monotonic(), result)
    return result
