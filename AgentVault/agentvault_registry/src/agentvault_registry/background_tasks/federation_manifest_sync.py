"""§FEFRAME W2 — read each ACTIVE peer's own manifest, so this registry knows where a person opens that peer's console.

A peer's console address, its currency's name and its ledger socket are facts only the peer knows: its signed card
names its public API origin, never where its console lives (EU's API is eu.theprotocol.cloud, its console
theprotocol.cloud). So they are read from the peer itself: GET <public_url>/api/v1/public/registry-config, public and
credential-free, validated by core.federation_view.peer_manifest_fields (the manifest must describe the host it was
fetched from; https/wss on a DNS name or nothing). One leader per registry reads every FRAME_MANIFEST_SYNC_INTERVAL
seconds (300) and writes Redis for every worker (registry:fedview:peer:<key>, a day's TTL, so a peer that goes quiet
keeps its last good answer and says when it was read).

Reads only; writes nothing to the database; moves no money. Off switch: FRAME_MANIFEST_SYNC_ENABLED=false.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, Dict

import httpx

from agentvault_registry.background_tasks.leader import get_redis, run_with_leadership
from agentvault_registry.core import federation_view as fv

logger = logging.getLogger(__name__)

INTERVAL = float(os.getenv("FRAME_MANIFEST_SYNC_INTERVAL", "300") or 300)
TIMEOUT = float(os.getenv("FRAME_MANIFEST_SYNC_TIMEOUT", "6") or 6)
CONCURRENCY = int(os.getenv("FRAME_MANIFEST_SYNC_CONCURRENCY", "4") or 4)
ENABLED = (os.getenv("FRAME_MANIFEST_SYNC_ENABLED", "true") or "true").strip().lower() not in ("0", "false", "no", "off")


async def _read_one(client: httpx.AsyncClient, entry: Dict[str, Any]) -> Dict[str, Any]:
    """{fields..., read_at, status} for one peer; `status` names what happened so a stale answer can say why."""
    public = entry.get("public_url")
    host = fv.host_of(public)
    if not public or not host:
        return {"status": "no_public_url", "attempt_at": time.time()}
    try:
        r = await client.get(f"{public}/api/v1/public/registry-config", follow_redirects=False)
    except httpx.HTTPError as e:
        return {"status": f"unreachable:{type(e).__name__}", "attempt_at": time.time()}
    if r.status_code != 200:
        return {"status": f"http_{r.status_code}", "attempt_at": time.time()}
    try:
        body = r.json()
    except ValueError:
        return {"status": "not_json", "attempt_at": time.time()}
    fields = fv.peer_manifest_fields(body, expect_host=host)
    if not isinstance(body, dict) or not isinstance(body.get("self"), dict):
        return {"status": "no_manifest", "attempt_at": time.time()}   # an older registry: no self block yet
    if not fields:
        return {"status": "not_about_this_host", "attempt_at": time.time()}
    return {**fields, "status": "ok", "read_at": time.time(), "attempt_at": time.time()}


async def run_cycle() -> Dict[str, int]:
    """One pass over every ACTIVE peer. Keeps a peer's last good fields when this read fails."""
    from agentvault_registry.database import get_db_context

    redis = await get_redis()
    async with get_db_context() as db:
        peers = await fv.active_peer_entries(db, redis)
    counts = {"peers": len(peers), "ok": 0, "kept": 0, "empty": 0}
    sem = asyncio.Semaphore(max(1, CONCURRENCY))
    async with httpx.AsyncClient(timeout=TIMEOUT, headers={"Accept": "application/json"}) as client:
        async def one(e):
            async with sem:
                res = await _read_one(client, e)
            key = fv.PEER_FIELDS_KEY.format(e["key"])
            prev = await fv.cached_peer_fields(redis, e["key"])
            if res.get("status") == "ok":
                counts["ok"] += 1
                value = res
            elif prev.get("status") == "ok" or prev.get("read_at"):
                counts["kept"] += 1
                value = {**prev, "last_status": res.get("status"), "attempt_at": res.get("attempt_at")}
            else:
                counts["empty"] += 1
                value = res
            if redis is not None:
                try:
                    await redis.set(key, json.dumps(value), ex=fv.PEER_FIELDS_TTL)
                except Exception as ex:  # noqa: BLE001
                    logger.warning("[FrameManifestSync] could not store %s: %s", e["key"], ex)
        await asyncio.gather(*(one(e) for e in peers))
    return counts


async def start_federation_manifest_sync() -> None:
    """Long-running coroutine: leader-elected, every INTERVAL seconds."""
    if not ENABLED:
        logger.info("[FrameManifestSync] disabled (FRAME_MANIFEST_SYNC_ENABLED=false)")
        return
    logger.info("[FrameManifestSync] starting; interval=%ss timeout=%ss", INTERVAL, TIMEOUT)
    await asyncio.sleep(20)   # let the database pool and the peer rows settle after boot
    try:
        async for _ in run_with_leadership("federation_manifest_sync", interval=INTERVAL):
            try:
                c = await run_cycle()
                logger.info("[FrameManifestSync] %s peers: %s read, %s kept their last answer, %s without one",
                            c["peers"], c["ok"], c["kept"], c["empty"])
            except Exception as exc:  # noqa: BLE001
                logger.error("[FrameManifestSync] cycle failed: %s", exc, exc_info=True)
    except asyncio.CancelledError:
        logger.info("[FrameManifestSync] stopped (cancellation)")
        raise
