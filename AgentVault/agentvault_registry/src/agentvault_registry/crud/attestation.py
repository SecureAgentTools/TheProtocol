"""CRUD for the Attestation model (ZKP attestation maturation — Phase 1)."""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Attestation, AttestationSchedule


def _utc(ts: datetime) -> datetime:
    """A timestamp in UTC; a naive one (SQLite) is taken as UTC already."""
    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)


async def create_attestation(
    db: AsyncSession,
    *,
    agent_did: str,
    circuit_id: str,
    circuit_version: str,
    public_inputs: Dict[str, Any],
    proof_b64: Optional[str],
    proof_hash: str,
    verified: bool,
    failure_reason: Optional[str] = None,
    policy_parameters_hash: Optional[str] = None,
    event_id: Optional[uuid.UUID] = None,
    submitted_at: Optional[datetime] = None,
    verified_at: Optional[datetime] = None,
    expires_at: Optional[datetime] = None,
) -> Attestation:
    a = Attestation(
        id=uuid.uuid4(),
        agent_did=agent_did,
        circuit_id=circuit_id,
        circuit_version=circuit_version,
        public_inputs=public_inputs,
        proof_b64=proof_b64,
        proof_hash=proof_hash,
        policy_parameters_hash=policy_parameters_hash,
        verified=verified,
        failure_reason=failure_reason,
        event_id=event_id,
        expires_at=expires_at,
    )
    if submitted_at is not None:
        a.submitted_at = submitted_at
    if verified_at is not None:
        a.verified_at = verified_at
    db.add(a)
    await db.commit()
    await db.refresh(a)
    return a


# ─── Phase 2 — Lifecycle helpers ──────────────────────────────────────────
async def revoke_attestation(
    db: AsyncSession,
    *,
    attestation_id: uuid.UUID,
    revoked_by: str,
    reason: Optional[str],
    when: Optional[datetime] = None,
) -> Optional[Attestation]:
    """Mark an attestation revoked. Idempotent: re-revoking a revoked row
    leaves revoked_at/revoked_by untouched."""
    row = await get_attestation(db, attestation_id)
    if row is None:
        return None
    if row.revoked_at is None:
        row.revoked_at = when or datetime.now(timezone.utc)
        row.revoked_by = revoked_by
        row.revoked_reason = (reason or "")[:500] or None
        await db.commit()
        await db.refresh(row)
    return row


async def find_expired_pending(
    db: AsyncSession,
    *,
    now: Optional[datetime] = None,
    batch_size: int = 100,
) -> List[Attestation]:
    """Return attestations whose `expires_at < now` that have not yet been
    revoked AND have not yet had an `AttestationExpired` event emitted."""
    cutoff = now or datetime.now(timezone.utc)
    stmt = (
        select(Attestation)
        .where(
            Attestation.expires_at.is_not(None),
            Attestation.expires_at < cutoff,
            Attestation.revoked_at.is_(None),
            Attestation.expired_emitted_at.is_(None),
        )
        .order_by(Attestation.expires_at.asc())
        .limit(max(1, min(batch_size, 1000)))
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def mark_expired_emitted(
    db: AsyncSession,
    *,
    attestation_id: uuid.UUID,
    when: Optional[datetime] = None,
) -> bool:
    """Stamp `expired_emitted_at` so the next sweep cycle skips this row."""
    row = await get_attestation(db, attestation_id)
    if row is None:
        return False
    if row.expired_emitted_at is None:
        row.expired_emitted_at = when or datetime.now(timezone.utc)
        await db.commit()
    return True


# ─── Phase 3 — Trust-chain helpers ────────────────────────────────────────
async def count_recent_verified(
    db: AsyncSession,
    *,
    agent_did: str,
    since_days: int = 30,
    now: Optional[datetime] = None,
) -> int:
    """Count the distinct (circuit, UTC day) pairs on which this agent has a
    verified, non-revoked attestation in the last `since_days`.

    Governance applies its voting bonus from this number. Counting days, not
    rows, means a stream of fresh proofs on one day counts once: the same rule
    as the reputation point (earned_reputation)."""
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=max(1, since_days))
    stmt = (
        select(Attestation.circuit_id, Attestation.submitted_at)
        .where(
            Attestation.agent_did == agent_did,
            Attestation.verified.is_(True),
            Attestation.revoked_at.is_(None),
            Attestation.submitted_at >= cutoff,
        )
        .limit(10000)
    )
    result = await db.execute(stmt)
    return len({(cid, _utc(ts).date()) for cid, ts in result.all() if ts is not None})


async def find_verified_by_proof_hash(
    db: AsyncSession,
    *,
    proof_hash: str,
) -> Optional[Attestation]:
    """The verified attestation that already carries these proof bytes, if any.

    A proof is valid for one circuit only, so the hash alone identifies it.
    """
    stmt = (
        select(Attestation)
        .where(Attestation.proof_hash == proof_hash, Attestation.verified.is_(True))
        .order_by(Attestation.submitted_at.asc())
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalars().first()


async def advisory_lock(db: AsyncSession, *keys: str) -> None:
    """Serialise concurrent submits on these keys until the transaction ends.

    PostgreSQL transaction-level advisory locks, taken in a fixed order so two
    requests never wait on each other crosswise; a no-op on other databases
    (tests). The submit route takes them before it reads, and create_attestation
    commits, which releases them.
    """
    bind = db.get_bind()
    if getattr(getattr(bind, "dialect", None), "name", "") != "postgresql":
        return
    for key in sorted(set(keys)):
        lock_id = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big", signed=True)
        await db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": lock_id})


async def find_verified_by_reference(
    db: AsyncSession,
    *,
    circuit_id: str,
    reference_input: str,
    reference: str,
) -> Optional[Attestation]:
    """The verified attestation that already carries this circuit and reference.

    One verified attestation per circuit and reference: a proof changed byte
    by byte still carries the same public values, so this catches what a hash
    of the raw bytes cannot.
    """
    stmt = (
        select(Attestation)
        .where(
            Attestation.circuit_id == circuit_id,
            Attestation.verified.is_(True),
            Attestation.public_inputs[reference_input].as_string() == reference,
        )
        .order_by(Attestation.submitted_at.asc())
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalars().first()


async def count_verified_on_day(
    db: AsyncSession,
    *,
    agent_did: str,
    circuit_id: str,
    day: datetime,
) -> int:
    """Verified attestations this agent already has for this circuit on the UTC day of `day`."""
    start = _utc(day).replace(hour=0, minute=0, second=0, microsecond=0)
    stmt = select(func.count(Attestation.id)).where(
        Attestation.agent_did == agent_did,
        Attestation.circuit_id == circuit_id,
        Attestation.verified.is_(True),
        Attestation.submitted_at >= start,
        Attestation.submitted_at < start + timedelta(days=1),
    )
    result = await db.execute(stmt)
    return int(result.scalar_one() or 0)


async def earned_reputation(db: AsyncSession, row: Attestation) -> bool:
    """Whether this attestation is the one that earns its agent +1 reputation.

    One verified attestation per agent, per circuit, per UTC day earns +1:
    the earliest that day (revoked ones included, so revoking and
    resubmitting earns nothing new). Revocation takes the point back only
    from the attestation that earned it. The submit route decides under an
    advisory lock and stamps submitted_at inside it, so the earliest row of
    the day is the one that earned.
    """
    if not row.verified or row.submitted_at is None:
        return False
    if not (row.circuit_id or "").endswith("/v2.0.0"):
        # Rows of the retired circuits were granted +1 each when they were
        # submitted, so each takes its point back on revocation.
        return True
    day = _utc(row.submitted_at).replace(hour=0, minute=0, second=0, microsecond=0)
    stmt = (
        select(Attestation.id)
        .where(
            Attestation.agent_did == row.agent_did,
            Attestation.circuit_id == row.circuit_id,
            Attestation.verified.is_(True),
            Attestation.submitted_at >= day,
            Attestation.submitted_at < day + timedelta(days=1),
        )
        .order_by(Attestation.submitted_at.asc(), Attestation.id.asc())
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none() == row.id


async def list_attestations_for_dispute_reduction(
    db: AsyncSession,
    *,
    defendant_did: str,
    attestation_ids: List[uuid.UUID],
) -> List[Attestation]:
    """Return only those referenced attestations that belong to the
    defendant AND are verified AND are not revoked AND have not yet
    expired. These are the ones that earn the slash-reduction credit."""
    if not attestation_ids:
        return []
    now = datetime.now(timezone.utc)
    stmt = select(Attestation).where(
        Attestation.id.in_(attestation_ids),
        Attestation.agent_did == defendant_did,
        Attestation.verified.is_(True),
        Attestation.revoked_at.is_(None),
    )
    result = await db.execute(stmt)
    rows = list(result.scalars().all())
    return [
        r for r in rows
        if r.expires_at is None or r.expires_at > now
    ]


# ─── Phase 5 — Schedule CRUD ──────────────────────────────────────────────
async def upsert_schedule(
    db: AsyncSession,
    *,
    agent_did: str,
    circuit_id: str,
    interval_hours: int,
    now: Optional[datetime] = None,
) -> AttestationSchedule:
    """Create or update an (agent_did, circuit_id) schedule entry.

    On update: re-enables the row, sets new interval, recomputes next_due_at
    from `now` (caller's clock), preserves last_attestation_at history.
    """
    when = now or datetime.now(timezone.utc)
    next_due = when + timedelta(hours=interval_hours)

    stmt = select(AttestationSchedule).where(
        AttestationSchedule.agent_did == agent_did,
        AttestationSchedule.circuit_id == circuit_id,
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        row = AttestationSchedule(
            id=uuid.uuid4(),
            agent_did=agent_did,
            circuit_id=circuit_id,
            interval_hours=interval_hours,
            enabled=True,
            next_due_at=next_due,
        )
        db.add(row)
    else:
        row.interval_hours = interval_hours
        row.enabled = True
        row.next_due_at = next_due
        row.last_reminder_at = None  # fresh schedule restarts the reminder cycle

    await db.commit()
    await db.refresh(row)
    return row


async def get_schedule(
    db: AsyncSession, *, schedule_id: uuid.UUID
) -> Optional[AttestationSchedule]:
    result = await db.execute(
        select(AttestationSchedule).where(AttestationSchedule.id == schedule_id)
    )
    return result.scalar_one_or_none()


async def get_schedule_for_agent_circuit(
    db: AsyncSession, *, agent_did: str, circuit_id: str
) -> Optional[AttestationSchedule]:
    result = await db.execute(
        select(AttestationSchedule).where(
            AttestationSchedule.agent_did == agent_did,
            AttestationSchedule.circuit_id == circuit_id,
        )
    )
    return result.scalar_one_or_none()


async def list_schedules(
    db: AsyncSession,
    *,
    agent_did: Optional[str] = None,
    enabled_only: bool = False,
) -> List[AttestationSchedule]:
    stmt = select(AttestationSchedule)
    if agent_did is not None:
        stmt = stmt.where(AttestationSchedule.agent_did == agent_did)
    if enabled_only:
        stmt = stmt.where(AttestationSchedule.enabled.is_(True))
    stmt = stmt.order_by(AttestationSchedule.next_due_at.asc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def disable_schedule(
    db: AsyncSession, *, schedule_id: uuid.UUID
) -> Optional[AttestationSchedule]:
    row = await get_schedule(db, schedule_id=schedule_id)
    if row is None:
        return None
    row.enabled = False
    await db.commit()
    await db.refresh(row)
    return row


async def find_due_schedules(
    db: AsyncSession,
    *,
    now: Optional[datetime] = None,
    batch_size: int = 200,
) -> List[AttestationSchedule]:
    """Schedules whose `next_due_at < now` AND haven't been reminded for
    THIS overdue cycle yet (last_reminder_at IS NULL OR < next_due_at)."""
    cutoff = now or datetime.now(timezone.utc)
    stmt = (
        select(AttestationSchedule)
        .where(
            AttestationSchedule.enabled.is_(True),
            AttestationSchedule.next_due_at < cutoff,
        )
        .order_by(AttestationSchedule.next_due_at.asc())
        .limit(max(1, min(batch_size, 1000)))
    )
    result = await db.execute(stmt)
    rows = list(result.scalars().all())
    # Daily-idempotency filter: last_reminder is older than the current
    # next_due_at means the cycle hasn't been reminded yet.
    return [
        r for r in rows
        if r.last_reminder_at is None or r.last_reminder_at < r.next_due_at
    ]


async def mark_reminder_sent(
    db: AsyncSession,
    *,
    schedule_id: uuid.UUID,
    when: Optional[datetime] = None,
) -> bool:
    row = await get_schedule(db, schedule_id=schedule_id)
    if row is None:
        return False
    row.last_reminder_at = when or datetime.now(timezone.utc)
    await db.commit()
    return True


async def update_schedule_on_attestation(
    db: AsyncSession,
    *,
    agent_did: str,
    circuit_id: str,
    when: Optional[datetime] = None,
) -> Optional[AttestationSchedule]:
    """Submit-side coupling. Looks up (agent_did, circuit_id); if the
    agent has a schedule for this circuit, advance next_due_at and stamp
    last_attestation_at. Idempotent — safe to call on every submit."""
    row = await get_schedule_for_agent_circuit(
        db, agent_did=agent_did, circuit_id=circuit_id,
    )
    if row is None or not row.enabled:
        return row
    stamp = when or datetime.now(timezone.utc)
    row.last_attestation_at = stamp
    row.next_due_at = stamp + timedelta(hours=row.interval_hours)
    row.last_reminder_at = None  # cycle reset
    await db.commit()
    await db.refresh(row)
    return row


async def get_attestation(
    db: AsyncSession, attestation_id: uuid.UUID
) -> Optional[Attestation]:
    result = await db.execute(
        select(Attestation).where(Attestation.id == attestation_id)
    )
    return result.scalar_one_or_none()


def _apply_filters(
    stmt,
    *,
    agent_did: Optional[str] = None,
    circuit_id: Optional[str] = None,
    verified: Optional[bool] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
):
    conds = []
    if agent_did is not None:
        conds.append(Attestation.agent_did == agent_did)
    if circuit_id is not None:
        conds.append(Attestation.circuit_id == circuit_id)
    if verified is not None:
        conds.append(Attestation.verified == verified)
    if since is not None:
        conds.append(Attestation.submitted_at >= since)
    if until is not None:
        conds.append(Attestation.submitted_at < until)
    if conds:
        stmt = stmt.where(and_(*conds))
    return stmt


async def list_attestations(
    db: AsyncSession,
    *,
    agent_did: Optional[str] = None,
    circuit_id: Optional[str] = None,
    verified: Optional[bool] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[Attestation]:
    stmt = select(Attestation)
    stmt = _apply_filters(
        stmt,
        agent_did=agent_did,
        circuit_id=circuit_id,
        verified=verified,
        since=since,
        until=until,
    )
    capped_limit = min(max(limit, 1), 200)
    stmt = (
        stmt.order_by(Attestation.submitted_at.desc())
        .limit(capped_limit)
        .offset(max(offset, 0))
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def count_attestations(
    db: AsyncSession,
    *,
    agent_did: Optional[str] = None,
    circuit_id: Optional[str] = None,
    verified: Optional[bool] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
) -> int:
    stmt = select(func.count(Attestation.id))
    stmt = _apply_filters(
        stmt,
        agent_did=agent_did,
        circuit_id=circuit_id,
        verified=verified,
        since=since,
        until=until,
    )
    result = await db.execute(stmt)
    return int(result.scalar_one() or 0)
