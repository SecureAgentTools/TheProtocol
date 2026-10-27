"""§REPATLANE-8 (V0610, 2026-10-13): the durable copy of an Idempotency-Key's record (idempotency_kept, migration 0191).

His decision, left to agentvault2-45 ("do your decision for the database copy"): cache.py keeps every answer a money
endpoint may have paid under its key (V0606's kept attempts) and every success of the older keyed endpoints, in Redis
alone, and Redis runs allkeys-lru: a record the cache evicted inside its 24 h window made the same key run the payment
again, because nothing else remembers it (the TEG does not dedup transfers by the client's key). This module keeps the
same record in the registry's own database beside Redis:

  claimed   a kept attempt's claim while its request runs (owner = the claim's token)
  answer    a kept or stored 2xx (payload = the response as the client got it, secrets already redacted by the caller)
  error     a kept error (payload = its status_code, detail and retry_after)
  (no row)  the key was given back (an answer that proved nothing moved), or never used, or past expires_at

Redis stays the arbiter of concurrency and the fast path: cache.py writes here after Redis and reads here only when Redis
has no record of the key, then puts the record back into Redis. Every call here is bounded (IDEMPOTENCY_DURABLE_TIMEOUT_S)
and raises on any failure; cache.py turns a failure into what it did before this copy existed (Redis alone), so a
database that cannot answer never stops a payment that Redis can guard. IDEMPOTENCY_DURABLE=off switches the copy off.
"""
from __future__ import annotations

import asyncio
import datetime
import json
import logging
import os
from typing import Any, Dict, Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)

TIMEOUT_S = float(os.environ.get("IDEMPOTENCY_DURABLE_TIMEOUT_S", "2"))

try:
    from prometheus_client import Counter as _DC

    DURABLE_TOTAL = _DC("registry_idempotency_durable_total",
                        "The durable copy of Idempotency-Key records: what each call did",
                        ["op", "outcome"])
except Exception:  # pragma: no cover
    DURABLE_TOTAL = None


def enabled() -> bool:
    return (os.environ.get("IDEMPOTENCY_DURABLE") or "on").strip().lower() not in ("off", "false", "0", "no")


def count(op: str, outcome: str) -> None:
    if DURABLE_TOTAL is not None:
        try:
            DURABLE_TOTAL.labels(op=op, outcome=outcome).inc()
        except Exception:  # noqa: BLE001
            pass


def _expiry(ttl_s: int) -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=int(ttl_s))


def _json(payload: Any) -> Optional[str]:
    return None if payload is None else json.dumps(payload, default=str)


_LIVE_ROW = text(
    "SELECT body_hash, state, owner, payload, "
    "       EXTRACT(EPOCH FROM (now() - created_at)) AS age_s, EXTRACT(EPOCH FROM (expires_at - now())) AS left_s "
    "  FROM idempotency_kept WHERE scope = :scope AND idem_key = :key AND expires_at > now()")

_CLAIM = text(
    "INSERT INTO idempotency_kept (scope, idem_key, body_hash, state, owner, payload, created_at, expires_at) "
    "VALUES (:scope, :key, :bh, 'claimed', :owner, NULL, now(), :exp) "
    "ON CONFLICT (scope, idem_key) DO UPDATE "
    "   SET body_hash = EXCLUDED.body_hash, state = 'claimed', owner = EXCLUDED.owner, payload = NULL, "
    "       created_at = now(), expires_at = EXCLUDED.expires_at "
    " WHERE idempotency_kept.expires_at <= now() "
    "RETURNING owner")

_STORE = text(
    "INSERT INTO idempotency_kept (scope, idem_key, body_hash, state, owner, payload, created_at, expires_at) "
    "VALUES (:scope, :key, :bh, 'answer', NULL, CAST(:payload AS jsonb), now(), :exp) "
    "ON CONFLICT (scope, idem_key) DO UPDATE "
    "   SET body_hash = EXCLUDED.body_hash, state = 'answer', owner = NULL, payload = EXCLUDED.payload, "
    "       expires_at = EXCLUDED.expires_at")

_SETTLE = text(
    "UPDATE idempotency_kept SET state = :state, payload = CAST(:payload AS jsonb), expires_at = :exp "
    " WHERE scope = :scope AND idem_key = :key AND owner = :owner")

_RELEASE = text("DELETE FROM idempotency_kept WHERE scope = :scope AND idem_key = :key AND owner = :owner")

_SWEEP = text(
    "DELETE FROM idempotency_kept WHERE ctid IN "
    "(SELECT ctid FROM idempotency_kept WHERE expires_at <= now() LIMIT :n)")


def _record(row) -> Dict[str, Any]:
    payload = row["payload"]
    if isinstance(payload, str):   # a driver that hands jsonb back as text
        payload = json.loads(payload)
    return {"body_hash": row["body_hash"], "state": row["state"], "owner": row["owner"], "payload": payload,
            "age_s": float(row["age_s"] or 0), "left_s": float(row["left_s"] or 0)}


async def _run(work):
    from agentvault_registry.database import get_db_context

    async def _go():
        async with get_db_context() as db:
            out = await work(db)
            await db.commit()
            return out
    return await asyncio.wait_for(_go(), timeout=TIMEOUT_S)


# D6-777 (2026-10-17): the cache keeps a caller's key under its own idem_key (cache._durable_key). A live row under the
# client's key alone was written before records were the caller's: nobody can say whose it is, so get and claim, given
# that key as `unscoped_key`, answer {"unscoped": True} for it (the cache answers it as not matching), in the same
# session as the read they make anyway.
_UNSCOPED = {"unscoped": True}


async def _unscoped_live(db, scope: str, unscoped_key: Optional[str]) -> bool:
    if not unscoped_key:
        return False
    return (await db.execute(_LIVE_ROW, {"scope": scope, "key": unscoped_key})).mappings().first() is not None


async def get(scope: str, key: str, unscoped_key: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """The live record of a key, or None; {"unscoped": True} when `unscoped_key` names a live row written before records
    were the caller's (it comes first: such a row is never passed over)."""
    async def work(db):
        if await _unscoped_live(db, scope, unscoped_key):
            return dict(_UNSCOPED)
        row = (await db.execute(_LIVE_ROW, {"scope": scope, "key": key})).mappings().first()
        return _record(row) if row else None
    return await _run(work)


async def claim(scope: str, key: str, body_hash: str, owner: str, ttl_s: int,
                unscoped_key: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Write this request's claim unless a live record of the key exists. None: the claim is written (an expired record
    is taken over). A dict: the live record another request left, which Redis no longer holds, or {"unscoped": True}
    when `unscoped_key` names a live row written before records were the caller's (then nothing is written)."""
    async def work(db):
        if await _unscoped_live(db, scope, unscoped_key):
            return dict(_UNSCOPED)
        for _ in range(2):   # a record that expires between the write and the read is taken over on the second pass
            got = (await db.execute(_CLAIM, {"scope": scope, "key": key, "bh": body_hash, "owner": owner,
                                             "exp": _expiry(ttl_s)})).scalar()
            if got == owner:
                return None
            row = (await db.execute(_LIVE_ROW, {"scope": scope, "key": key})).mappings().first()
            if row:
                return _record(row)
        raise RuntimeError("the durable claim neither took the key nor found who holds it")
    return await _run(work)


async def store(scope: str, key: str, body_hash: str, payload: Any, ttl_s: int) -> None:
    """A 2xx kept under the key, whoever held it (Redis's own SET does the same)."""
    async def work(db):
        await db.execute(_STORE, {"scope": scope, "key": key, "bh": body_hash, "payload": _json(payload),
                                  "exp": _expiry(ttl_s)})
    await _run(work)


async def settle(scope: str, key: str, owner: str, state: str, payload: Any, ttl_s: int) -> bool:
    """This request's claim becomes its kept answer or error. False: the row was not this request's."""
    async def work(db):
        r = await db.execute(_SETTLE, {"scope": scope, "key": key, "owner": owner, "state": state,
                                       "payload": _json(payload), "exp": _expiry(ttl_s)})
        return bool(r.rowcount)
    return await _run(work)


async def release(scope: str, key: str, owner: str) -> None:
    """The key given back: this request's own row deleted (nobody else's)."""
    async def work(db):
        await db.execute(_RELEASE, {"scope": scope, "key": key, "owner": owner})
    await _run(work)


async def sweep(limit: int) -> int:
    """Delete up to `limit` records past their expiry; how many went."""
    from agentvault_registry.database import get_db_context
    async with get_db_context() as db:
        r = await db.execute(_SWEEP, {"n": int(limit)})
        await db.commit()
        return int(r.rowcount or 0)
