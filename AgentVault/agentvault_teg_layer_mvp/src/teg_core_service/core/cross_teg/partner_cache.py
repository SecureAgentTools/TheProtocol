"""§pass47 A4 — Redis-backed shared cache for runtime cross-TEG partners.

Supersedes the per-uvicorn-worker module-level `_runtime_partners` list (memory:
`feedback_teg_runtime_partner_per_worker_stale.md`). With this module shipped, the
canonical source of runtime partners is Redis.

Storage:
  Redis HASH key  `teg:partners`
  field           `<teg_id>`
  value           JSON-encoded partner dict
                    { teg_id, url, registry_id?, api_key? }
  field           `#partner-list` (META_FIELD, never a TEG id): the list exists. The cross-TEG partner rule
                  (core/cross_teg/partner_rule.py, 2026-10-17) reads this list on every leg, so a list that holds no
                  partner must still read as a list: Redis drops a HASH whose last field goes, and a missing HASH is
                  what a restarted frame Redis looks like (it keeps no copy on disk). Every write keeps the field.

Operations:
  set_partner_in_redis(teg_id, partner):  HSET (write-through, with the META field)
  delete_partners_in_redis(teg_ids):      HDEL in one transaction that keeps the META field
  read_partner_snapshot():                ("live" | "unmarked" | "missing" | "unavailable", partners)
  mark_partner_list(partners):            write a worker's copy back with the META field
  list_all_partners_from_redis():         full snapshot (no state)
  The set and the delete also publish on `teg:partners:updates` (best-effort; nothing has to listen).

If Redis is unavailable these answer False / None / "unavailable" as appropriate, and the caller
(cross_teg_router) uses its per-worker `_runtime_partners` copy, which follows this list every 30 s.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Dict, Iterable, List, Optional, Tuple

from ...redis_client import get_redis

logger = logging.getLogger(__name__)


_HASH_KEY = "teg:partners"
_PUBSUB_CHANNEL = "teg:partners:updates"
META_FIELD = "#partner-list"


def _meta() -> str:
    return json.dumps({"v": 1, "at": int(time.time())})


def _clean(partner: Dict[str, str]) -> str:
    # Strip None values so JSON is compact.
    return json.dumps({k: v for k, v in partner.items() if v is not None})


async def set_partner_in_redis(teg_id: str, partner: Dict[str, str]) -> bool:
    """Write a partner dict to the shared HASH. Returns True on success."""
    r = await get_redis()
    if r is None:
        return False
    try:
        await r.hset(_HASH_KEY, mapping={teg_id: _clean(partner), META_FIELD: _meta()})
        try:
            await r.publish(_PUBSUB_CHANNEL, json.dumps({"event": "upsert", "teg_id": teg_id}))
        except Exception:
            pass  # pub/sub is best-effort; periodic refresh covers the gap
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[PartnerCache] set_partner_in_redis({teg_id}) failed: {e}")
        return False


async def delete_partners_in_redis(teg_ids: Iterable[str]) -> Optional[List[str]]:
    """Remove these partners from the shared HASH in one transaction that keeps the META field. Returns the ids Redis
    held and removed, or None when Redis cannot be reached (nothing was removed there)."""
    ids = [t for t in dict.fromkeys(teg_ids or ()) if t and t != META_FIELD]
    r = await get_redis()
    if r is None:
        return None
    try:
        async with r.pipeline(transaction=True) as pipe:
            for tid in ids:
                pipe.hdel(_HASH_KEY, tid)
            pipe.hset(_HASH_KEY, META_FIELD, _meta())
            results = await pipe.execute()
        removed = [tid for tid, n in zip(ids, results) if n]
        for tid in removed:
            try:
                await r.publish(_PUBSUB_CHANNEL, json.dumps({"event": "delete", "teg_id": tid}))
            except Exception:
                pass
        return removed
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[PartnerCache] delete_partners_in_redis({ids}) failed: {e}")
        return None


async def delete_partner_in_redis(teg_id: str) -> bool:
    """Remove a partner from the shared HASH. Returns True ONLY if Redis had
    the entry and it was removed (caller can use this to detect cross-worker
    add/remove races where the local list missed the add)."""
    removed = await delete_partners_in_redis([teg_id])
    return bool(removed)


def _parse(raw: Dict[str, str]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for teg_id, blob in (raw or {}).items():
        if teg_id == META_FIELD:
            continue
        try:
            partner = json.loads(blob)
            partner.setdefault("teg_id", teg_id)
            out.append(partner)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[PartnerCache] malformed entry {teg_id!r}: {e}")
    return out


async def read_partner_snapshot() -> Tuple[str, List[Dict[str, str]]]:
    """The shared list and what it is: ("live", partners) the list as it stands (its META field is there);
    ("unmarked", partners) a list a TEG wrote before the META field existed; ("missing", []) no list at all (a frame
    Redis that restarted or evicted it); ("unavailable", []) Redis cannot be reached."""
    r = await get_redis()
    if r is None:
        return "unavailable", []
    try:
        raw = await r.hgetall(_HASH_KEY)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[PartnerCache] read_partner_snapshot failed: {e}")
        return "unavailable", []
    if not raw:
        return "missing", []
    return ("live" if META_FIELD in raw else "unmarked"), _parse(raw)


async def mark_partner_list(partners: Iterable[Dict[str, str]]) -> bool:
    """Write these partners and the META field: the shared list exists from here on, holding at least these."""
    mapping = {p["teg_id"]: _clean(p) for p in (partners or ())
               if isinstance(p, dict) and p.get("teg_id") and p.get("url") and p["teg_id"] != META_FIELD}
    mapping[META_FIELD] = _meta()
    r = await get_redis()
    if r is None:
        return False
    try:
        await r.hset(_HASH_KEY, mapping=mapping)
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[PartnerCache] mark_partner_list failed: {e}")
        return False


async def list_all_partners_from_redis() -> List[Dict[str, str]]:
    """Return the full snapshot of partners from Redis. Empty list on failure."""
    r = await get_redis()
    if r is None:
        return []
    try:
        raw = await r.hgetall(_HASH_KEY)
        return _parse(raw)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[PartnerCache] list_all_partners_from_redis failed: {e}")
        return []


async def get_partner_from_redis(teg_id: str) -> Optional[Dict[str, str]]:
    """Return a single partner dict if present in Redis."""
    if teg_id == META_FIELD:
        return None
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
