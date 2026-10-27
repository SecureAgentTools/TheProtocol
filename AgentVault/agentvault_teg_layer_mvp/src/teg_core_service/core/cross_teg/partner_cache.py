"""§pass47 A4 — Redis-backed shared cache for runtime cross-TEG partners.

Supersedes the per-uvicorn-worker module-level `_runtime_partners` list (memory:
`feedback_teg_runtime_partner_per_worker_stale.md`). The §pass45 self-heal
hotfix on `resolve_partner_url` (prefer-url_hint) remains as a defense layer
in case Redis or sync gets stale, but with this module shipped, the
canonical source of runtime-discovered partner URLs is Redis.

Storage:
  Redis HASH key  `teg:partners`
  field           `<teg_id>`
  value           JSON-encoded partner dict
                    { teg_id, url, registry_id?, api_key? }

Operations:
  set_partner_in_redis(teg_id, partner)       — HSET (write-through)
  delete_partner_in_redis(teg_id)              — HDEL
  list_all_partners_from_redis()               — full snapshot
  publish_partner_change(teg_id, event)        — optional pub/sub notify
                                                  (channel `teg:partners:updates`)

All operations are fail-OPEN: if Redis is unavailable, returns False / [] /
None as appropriate. The caller (cross_teg_router) keeps the per-worker
`_runtime_partners` list as the L1 in-memory cache; this module is the
shared L2 that lets new workers warm up from one another's discoveries.
"""
from __future__ import annotations

import json
import logging
from typing import Dict, List, Optional

from ...redis_client import get_redis

logger = logging.getLogger(__name__)


_HASH_KEY = "teg:partners"
_PUBSUB_CHANNEL = "teg:partners:updates"


async def set_partner_in_redis(teg_id: str, partner: Dict[str, str]) -> bool:
    """Write a partner dict to the shared HASH. Returns True on success."""
    r = await get_redis()
    if r is None:
        return False
    try:
        # Strip None values so JSON is compact.
        clean = {k: v for k, v in partner.items() if v is not None}
        await r.hset(_HASH_KEY, teg_id, json.dumps(clean))
        try:
            await r.publish(_PUBSUB_CHANNEL, json.dumps({"event": "upsert", "teg_id": teg_id}))
        except Exception:
            pass  # pub/sub is best-effort; periodic refresh covers the gap
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[PartnerCache] set_partner_in_redis({teg_id}) failed: {e}")
        return False


async def delete_partner_in_redis(teg_id: str) -> bool:
    """Remove a partner from the shared HASH. Returns True ONLY if Redis had
    the entry and it was removed (caller can use this to detect cross-worker
    add/remove races where the local list missed the add)."""
    r = await get_redis()
    if r is None:
        return False
    try:
        removed = await r.hdel(_HASH_KEY, teg_id)
        try:
            await r.publish(_PUBSUB_CHANNEL, json.dumps({"event": "delete", "teg_id": teg_id}))
        except Exception:
            pass
        return bool(removed)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[PartnerCache] delete_partner_in_redis({teg_id}) failed: {e}")
        return False


async def list_all_partners_from_redis() -> List[Dict[str, str]]:
    """Return the full snapshot of partners from Redis. Empty list on failure."""
    r = await get_redis()
    if r is None:
        return []
    try:
        raw = await r.hgetall(_HASH_KEY)
        out: List[Dict[str, str]] = []
        for teg_id, blob in (raw or {}).items():
            try:
                partner = json.loads(blob)
                partner.setdefault("teg_id", teg_id)
                out.append(partner)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[PartnerCache] malformed entry {teg_id!r}: {e}")
        return out
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[PartnerCache] list_all_partners_from_redis failed: {e}")
        return []


async def get_partner_from_redis(teg_id: str) -> Optional[Dict[str, str]]:
    """Return a single partner dict if present in Redis."""
    r = await get_redis()
    if r is None:
        return None
    try:
        blob = await r.hget(_HASH_KEY, teg_id)
        if not blob:
            return None
        partner = json.loads(blob)
        partner.setdefault("teg_id", teg_id)
        return partner
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[PartnerCache] get_partner_from_redis({teg_id}) failed: {e}")
        return None
