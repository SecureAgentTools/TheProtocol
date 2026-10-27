"""routers/forensics.py — Ledger Forensics read API (2026-06-19).

Server-side payload search / txid trace / detector scan over the 88M-row
`events` table, for the registry's /admin/forensics console. STRICTLY read-only.

Safety model (88M rows, shared loaded host):
  * Every browsing query is anchored on a MANDATORY bounded `timestamp` window
    (rides the existing idx_timestamp) — no unbounded scans. Max span enforced.
  * txid trace rides the existing idx_events_data_txid ((data->>'transaction_id')).
  * Per-statement `SET LOCAL statement_timeout` caps any runaway.
  * Hard row caps on every endpoint.
  * No new index is required (the heavy GIN-on-data is deliberately deferred to a
    low-load window; arbitrary payload-containment search is intentionally NOT
    offered here so nothing can seq-scan).

Auth: same internal dep as the events router (mTLS SVID / X-Internal-Key /
federation license) — the registry proxies here with X-Internal-Key.
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Security
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..models.db_models import EventModel
from .events import verify_event_auth

router = APIRouter(prefix="/api/v1/forensics", tags=["forensics"])

# Mirrors the registry/TEG BALANCE_MOVING_EVENT_TYPES (event_emitter.py:63-67).
_BALANCE_MOVING = {
    "TokensIssued", "TokensTransferred", "TokensStaked", "TokensUnstaked",
    "BalanceCorrected", "DisputeSlash", "DisputeCompensationMinted",
    "TransactionFeeCollected", "RewardsAutoCompounded", "ProjectionSnapshot",
    "LedgerBalanceChanged",
}

_MAX_SEARCH_SPAN = timedelta(days=31)   # hard cap on the search window
_MAX_SCAN_SPAN = timedelta(days=7)      # detector scan is heavier per-row → tighter
_STMT_TIMEOUT_MS = 9000


def _ser(e: EventModel) -> Dict[str, Any]:
    return {
        "id": str(e.id),
        "event_type": e.event_type,
        "aggregate_id": e.aggregate_id,
        "aggregate_type": e.aggregate_type,
        "data": e.data,
        "metadata": e.event_metadata,
        "timestamp": e.timestamp.isoformat() if e.timestamp else None,
        "version": e.version,
        "source_service": e.source_service,
        "idempotency_key": e.idempotency_key,
        "seq": e.seq,
    }


def _parse_ts(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"bad timestamp: {s!r} (use ISO 8601)")


def _window(start: Optional[str], end: Optional[str], default_hours: int, max_span: timedelta):
    end_dt = _parse_ts(end) or datetime.now(timezone.utc)
    start_dt = _parse_ts(start) or (end_dt - timedelta(hours=default_hours))
    if start_dt >= end_dt:
        raise HTTPException(status_code=422, detail="start must be before end")
    if (end_dt - start_dt) > max_span:
        raise HTTPException(status_code=422, detail=f"window too wide (max {max_span.days}d)")
    return start_dt, end_dt


async def _arm_timeout(db: AsyncSession) -> None:
    # First statement in the request txn — caps any runaway query at the DB.
    await db.execute(text(f"SET LOCAL statement_timeout = {_STMT_TIMEOUT_MS}"))


@router.get("/search", summary="Time-windowed payload search (read-only)")
async def search(
    start: Optional[str] = Query(default=None, description="ISO 8601; default end-24h"),
    end: Optional[str] = Query(default=None, description="ISO 8601; default now"),
    event_type: Optional[str] = Query(default=None, description="single or comma-separated"),
    aggregate_id: Optional[str] = Query(default=None),
    transaction_id: Optional[str] = Query(default=None, description="data->>'transaction_id'"),
    kind: Optional[str] = Query(default=None, description="data->>'kind' (LedgerBalanceChanged)"),
    source_service: Optional[str] = Query(default=None),
    idempotency_prefix: Optional[str] = Query(default=None, description="idempotency_key LIKE prefix%"),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
    db: AsyncSession = Depends(get_db),
    auth: Dict = Security(verify_event_auth),
):
    start_dt, end_dt = _window(start, end, 24, _MAX_SEARCH_SPAN)
    await _arm_timeout(db)

    stmt = select(EventModel).where(
        EventModel.timestamp >= start_dt, EventModel.timestamp <= end_dt
    )
    if event_type:
        types = [t.strip() for t in event_type.split(",") if t.strip()]
        stmt = stmt.where(EventModel.event_type.in_(types)) if len(types) > 1 else stmt.where(EventModel.event_type == types[0])
    if aggregate_id:
        stmt = stmt.where(EventModel.aggregate_id == aggregate_id)
    if transaction_id:
        stmt = stmt.where(EventModel.data["transaction_id"].astext == transaction_id)
    if kind:
        stmt = stmt.where(EventModel.data["kind"].astext == kind)
    if source_service:
        stmt = stmt.where(EventModel.source_service == source_service)
    if idempotency_prefix:
        stmt = stmt.where(EventModel.idempotency_key.like(f"{idempotency_prefix}%"))
    stmt = stmt.order_by(
        EventModel.timestamp.desc() if order == "desc" else EventModel.timestamp.asc()
    ).limit(limit).offset(offset)

    rows = (await db.execute(stmt)).scalars().all()
    return {
        "events": [_ser(e) for e in rows],
        "count": len(rows),
        "truncated": len(rows) == limit,
        "window": {"start": start_dt.isoformat(), "end": end_dt.isoformat()},
    }


@router.get("/trace/{transaction_id}", summary="Full event timeline for one transaction_id")
async def trace(
    transaction_id: str,
    limit: int = Query(default=2000, ge=1, le=5000),
    db: AsyncSession = Depends(get_db),
    auth: Dict = Security(verify_event_auth),
):
    """All events sharing data->>'transaction_id' (rides idx_events_data_txid),
    oldest-first — the cross-leg money path for a transfer/order/saga."""
    await _arm_timeout(db)
    # NO ORDER BY in SQL: a `ORDER BY timestamp` makes the planner scan idx_timestamp
    # and FILTER on data->>'transaction_id' (a near-full 88M-row scan → statement_timeout).
    # Drive the txid index (idx_events_data_txid), then sort the few legs in Python.
    stmt = (
        select(EventModel)
        .where(EventModel.data["transaction_id"].astext == transaction_id)
        .limit(limit)
    )
    rows = list((await db.execute(stmt)).scalars().all())
    rows.sort(key=lambda e: e.timestamp or datetime(1970, 1, 1, tzinfo=timezone.utc))
    return {"transaction_id": transaction_id, "events": [_ser(e) for e in rows], "count": len(rows)}


async def _count_samples(db, base_where, start_dt, end_dt) -> Dict[str, Any]:
    cnt = (
        await db.execute(
            select(func.count()).select_from(EventModel).where(
                EventModel.timestamp >= start_dt, EventModel.timestamp <= end_dt, *base_where
            )
        )
    ).scalar_one()
    samples: List[str] = []
    if cnt:
        sids = (
            await db.execute(
                select(EventModel.id).where(
                    EventModel.timestamp >= start_dt, EventModel.timestamp <= end_dt, *base_where
                ).order_by(EventModel.timestamp.desc()).limit(5)
            )
        ).scalars().all()
        samples = [str(x) for x in sids]
    return {"count": int(cnt), "samples": samples}


@router.get("/scan", summary="Detector battery over a bounded window (read-only)")
async def scan(
    start: Optional[str] = Query(default=None),
    end: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    auth: Dict = Security(verify_event_auth),
):
    """Bounded-window anomaly detectors. Every detector is a count+samples over
    the [start,end] window (default 24h, max 7d) — anchored on idx_timestamp."""
    start_dt, end_dt = _window(start, end, 24, _MAX_SCAN_SPAN)
    await _arm_timeout(db)
    findings: List[Dict[str, Any]] = []

    # D1 — balance-moving event with NULL idempotency_key (the ES write boundary
    # should 400 these; any present = a leak that breaks exactly-once dedup).
    d = await _count_samples(
        db, [EventModel.event_type.in_(_BALANCE_MOVING), EventModel.idempotency_key.is_(None)],
        start_dt, end_dt,
    )
    if d["count"]:
        findings.append({"key": "idem_null_balance_moving", "severity": "high",
                         "title": "Balance-moving events with NULL idempotency_key",
                         "detail": "These bypass exactly-once dedup — the append boundary should reject them.",
                         **d})

    # D2 — LedgerBalanceChanged with unknown/mixed kind (informational: transfers
    # are NORMALLY 'unknown' → this is a trend signal, not per-row alarm).
    d = await _count_samples(
        db, [EventModel.event_type == "LedgerBalanceChanged",
             EventModel.data["kind"].astext.in_(["unknown", "mixed"])],
        start_dt, end_dt,
    )
    findings.append({"key": "ledger_unknown_kind", "severity": "info",
                     "title": "LedgerBalanceChanged with unknown/mixed kind",
                     "detail": "Normal for transfers/fx/fee (→ transit_net, Δ-neutral). Watch for spikes vs baseline; a mis-stamped mint/burn here would be supply-invisible.",
                     **d})

    # D3 — SupplyInvariantBreach events in window (cosmetic read-skew is common;
    # sustained clusters are not).
    d = await _count_samples(db, [EventModel.event_type == "SupplyInvariantBreach"], start_dt, end_dt)
    if d["count"]:
        findings.append({"key": "supply_breach_events", "severity": "warn" if d["count"] < 20 else "high",
                         "title": "SupplyInvariantBreach events emitted",
                         "detail": "Transient ±1-2 under cross-frame load is cosmetic read-skew; a sustained cluster is a real breach.",
                         **d})

    # D4 — FX route/swap refunds + dead-letters (stranded-value risk class).
    d = await _count_samples(
        db, [EventModel.event_type.in_(["FxRouteRefunded", "FxRouteDeadLettered", "FxSwapRefunded"])],
        start_dt, end_dt,
    )
    if d["count"]:
        findings.append({"key": "fx_refund_deadletter", "severity": "info",
                         "title": "FX route/swap refunds + dead-letters",
                         "detail": "Post-conversion dead-letters can strand value at the dest @fx_router (Δ-neutral, invisible to supply audit). Drill to confirm origins were made whole.",
                         **d})

    # D5 — cross-frame refunds (high volume = saga churn; pair-check needs both frames).
    d = await _count_samples(db, [EventModel.event_type == "CrossFrameTransferRefunded"], start_dt, end_dt)
    if d["count"]:
        findings.append({"key": "cross_frame_refunded", "severity": "info",
                         "title": "Cross-frame transfers refunded",
                         "detail": "Each must have a matching receiver-side reverse; a refund without reverse over-credits the receiver. Confirm cross-frame.",
                         **d})

    # Context: top event types in window (not a finding — orientation).
    top = (
        await db.execute(
            select(EventModel.event_type, func.count().label("n")).where(
                EventModel.timestamp >= start_dt, EventModel.timestamp <= end_dt
            ).group_by(EventModel.event_type).order_by(text("n DESC")).limit(15)
        )
    ).all()

    return {
        "window": {"start": start_dt.isoformat(), "end": end_dt.isoformat()},
        "findings": findings,
        "event_type_histogram": [{"event_type": t, "count": int(n)} for (t, n) in top],
    }
