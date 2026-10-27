"""
EventStore Global Lockdown State (Phase 2b)

Singleton module shared between:
  - routers/system.py   → sets/clears the lockdown
  - services/event_store.py, services/kafka_consumer.py and the broker path
    of routers/events.py → check it before every append

Placing state here (services layer) avoids a circular import that would
result from event_store.py importing from the routers package.

D6-298 (2026-10-16): the lockdown lives in the store's own database (table
eventstore_lockdown, one row), so every worker of the store sees it and a
restart does not lift it: only POST /api/v1/system/lockdown/clear does. It
used to live in the memory of the one worker that took the call, so a store
running several workers went on appending through the others. Redis is not
used: the frame kit's Redis keeps nothing across a restart and evicts keys
under memory pressure, and a lockdown must outlive both.

Each worker reads the row at most once per LOCKDOWN_CACHE_SECONDS (default 2),
so an append costs no query; the worker that activates or clears knows at
once, the others within that interval (an append that arrives while the row
is being read waits for that read). A read that fails keeps the last answer
(an error never locks and never unlocks); no row means never locked.
"""
import asyncio
import logging
import os
import time
from datetime import datetime
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# One row (id 1). Created at startup by main.py and, should a write come first, by the write itself.
TABLE_DDL = (
    "CREATE TABLE IF NOT EXISTS eventstore_lockdown ("
    "id SMALLINT PRIMARY KEY CHECK (id = 1), "
    "is_active BOOLEAN NOT NULL DEFAULT false, "
    "reason TEXT NULL, "
    "triggered_at TIMESTAMPTZ NULL, "
    "triggered_by TEXT NOT NULL DEFAULT 'system')"
)
_SELECT = "SELECT is_active, reason, triggered_at, triggered_by FROM eventstore_lockdown WHERE id = 1"
# The first lockdown stays as it is: an active row is not overwritten, so a second activation changes nothing.
_ACTIVATE = (
    "INSERT INTO eventstore_lockdown AS l (id, is_active, reason, triggered_at, triggered_by) "
    "VALUES (1, true, :reason, now(), :triggered_by) "
    "ON CONFLICT (id) DO UPDATE SET is_active = true, reason = EXCLUDED.reason, "
    "triggered_at = EXCLUDED.triggered_at, triggered_by = EXCLUDED.triggered_by "
    "WHERE l.is_active = false RETURNING id"
)
_CLEAR = (
    "UPDATE eventstore_lockdown SET is_active = false, reason = NULL, triggered_at = NULL, "
    "triggered_by = 'system' WHERE id = 1"
)


def _cache_seconds() -> float:
    try:
        return max(0.0, float(os.getenv("LOCKDOWN_CACHE_SECONDS", "2")))
    except ValueError:
        return 2.0


class DatabaseLockdownStore:
    """The lockdown row in the store's own database."""

    def __init__(self, engine=None) -> None:
        self._engine = engine  # None: the store's own engine, imported on first use

    def _db(self):
        if self._engine is None:
            from ..database.connection import engine
            self._engine = engine
        return self._engine

    async def read(self) -> Optional[dict]:
        from sqlalchemy import text
        async with self._db().connect() as conn:
            row = (await conn.execute(text(_SELECT))).mappings().first()
        return dict(row) if row else None

    async def activate(self, reason: str, triggered_by: str) -> Tuple[bool, dict]:
        """(True, row) when this call locked the store; (False, row) when it was locked already."""
        from sqlalchemy import text
        async with self._db().begin() as conn:
            await conn.execute(text(TABLE_DDL))
            won = (await conn.execute(text(_ACTIVATE), {"reason": reason, "triggered_by": triggered_by})).first()
            row = (await conn.execute(text(_SELECT))).mappings().first()
        return won is not None, dict(row)

    async def clear(self) -> Optional[dict]:
        """Lift the lockdown; returns the row as it was before (None when there was none)."""
        from sqlalchemy import text
        async with self._db().begin() as conn:
            await conn.execute(text(TABLE_DDL))
            before = (await conn.execute(text(_SELECT + " FOR UPDATE"))).mappings().first()
            await conn.execute(text(_CLEAR))
        return dict(before) if before else None


class LockdownState:
    """
    The global EventStore lockdown, as this worker last read it from the shared row.

    is_active=True → append_event() raises 503 immediately.
    Only cleared by explicit POST /api/v1/system/lockdown/clear from admin.
    """

    def __init__(self, store=None, cache_seconds: Optional[float] = None) -> None:
        self._store = store if store is not None else DatabaseLockdownStore()
        self._cache_seconds = _cache_seconds() if cache_seconds is None else cache_seconds
        self._read_at: Optional[float] = None
        self._read_failing = False
        self._reading = asyncio.Lock()
        self.is_active: bool = False
        self.reason: Optional[str] = None
        self.triggered_at: Optional[str] = None
        self.triggered_by: str = "system"

    def _apply(self, row: Optional[dict]) -> None:
        if not row or not row.get("is_active"):
            self.is_active, self.reason, self.triggered_at, self.triggered_by = False, None, None, "system"
            return
        at = row.get("triggered_at")
        self.is_active = True
        self.reason = row.get("reason")
        self.triggered_at = at.isoformat() if isinstance(at, datetime) else at
        self.triggered_by = row.get("triggered_by") or "system"

    def _fresh(self) -> bool:
        return self._read_at is not None and time.monotonic() - self._read_at < self._cache_seconds

    async def is_locked(self) -> bool:
        """Whether the store is locked down, for every worker. Reads the row at most once per interval."""
        if self._fresh():
            return self.is_active
        # One read per interval, and the appends that arrive meanwhile wait for it: answering them from the old copy
        # let a burst through after the interval (measured end to end, 11 of 45 appends after a lockdown).
        async with self._reading:
            if not self._fresh():
                await self._read()
        return self.is_active

    async def _read(self) -> None:
        try:
            row = await self._store.read()
        except Exception as e:
            if not self._read_failing:
                logger.warning(
                    f"[Lockdown] the lockdown row could not be read ({e}); keeping the last answer "
                    f"(locked={self.is_active})"
                )
            self._read_failing = True
        else:
            if self._read_failing:
                logger.info("[Lockdown] the lockdown row is readable again")
                self._read_failing = False
            self._apply(row)
        # stamped once the read is over: a request arriving during the read waits for it rather than take the old copy
        self._read_at = time.monotonic()

    async def activate(self, reason: str, triggered_by: str = "system") -> bool:
        """Lock the store for every worker. False when it was locked already (that lockdown stays as it is)."""
        won, row = await self._store.activate(reason, triggered_by)
        self._apply(row)
        self._read_at = time.monotonic()
        return won

    async def clear(self) -> Tuple[bool, Optional[str]]:
        """Lift the lockdown for every worker; returns (was_active, previous_reason)."""
        before = await self._store.clear()
        self._apply(None)
        self._read_at = time.monotonic()
        return bool(before and before.get("is_active")), (before or {}).get("reason")

    def detail(self) -> str:
        """The refusal an append gets while the store is locked down."""
        return (
            f"EventStore is locked down: {self.reason}. "
            f"Contact administrator to clear lockdown after verifying supply."
        )

    def to_dict(self) -> dict:
        return {
            "lockdown_active": self.is_active,
            "reason": self.reason,
            "triggered_at": self.triggered_at,
            "triggered_by": self.triggered_by,
        }


# Module-level singleton — imported by both router and service
GLOBAL_LOCKDOWN = LockdownState()
