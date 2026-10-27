import os
from decimal import Decimal
from typing import List, Optional
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
from ..models.events import Event
from ..models.db_models import EventModel
from .lockdown_state import GLOBAL_LOCKDOWN
import logging

# Phase 2b: Double-entry balance validation gate
# Set EVENTSTORE_DOUBLE_ENTRY_ENABLED=true in docker-compose.yml to activate at GA.
# Default: False (monitoring-only during beta)
DOUBLE_ENTRY_ENABLED = os.getenv("EVENTSTORE_DOUBLE_ENTRY_ENABLED", "false").lower() == "true"

logger = logging.getLogger(__name__)


def _db_event_to_pydantic(e: EventModel) -> Event:
    """Helper: convert DB model to Pydantic Event."""
    return Event(
        id=str(e.id),
        event_type=e.event_type,
        aggregate_id=e.aggregate_id,
        aggregate_type=e.aggregate_type,
        data=e.data,
        metadata=e.event_metadata or {},
        timestamp=e.timestamp,
        version=e.version,
        source_service=e.source_service,
        idempotency_key=e.idempotency_key  # TITANIUM VAULT D1
    )


class EventStore:
    def __init__(self, db_session: AsyncSession):
        self.db = db_session
    
    async def append_event(self, event: Event, source_operator_id: str = None) -> Event:
        """Store an event. If idempotency_key is provided and already exists,
        return the existing event instead of creating a duplicate.

        TITANIUM VAULT D1: Exactly-once event delivery via idempotency keys.
        Phase 2b: Global lockdown check + optional double-entry balance validation.
        """
        # ── Phase 2b: Global Lockdown Check (the shared row, every worker: D6-298) ──
        if await GLOBAL_LOCKDOWN.is_locked():
            logger.warning(
                f"[EventStore] Append rejected — lockdown active: "
                f"{GLOBAL_LOCKDOWN.reason}"
            )
            raise HTTPException(status_code=503, detail=GLOBAL_LOCKDOWN.detail())

        # ── Phase 2b: Double-Entry Balance Validation (EVENTSTORE_DOUBLE_ENTRY_ENABLED) ──
        if DOUBLE_ENTRY_ENABLED and event.event_type == "TokensTransferred":
            try:
                from .projections import ProjectionService  # local import to avoid circular
                ps = ProjectionService(self)
                balance = await ps.calculate_balance(event.aggregate_id)
                transfer_amount = Decimal(str(event.data.get("amount", 0)))
                sender_liquid = Decimal(str(balance.liquid_balance))

                if sender_liquid < transfer_amount:
                    logger.warning(
                        f"[EventStore] Double-entry violation: sender={event.aggregate_id} "
                        f"liquid={sender_liquid} attempted={transfer_amount}"
                    )
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"Insufficient funds in global ledger. "
                            f"Sender {event.aggregate_id} has {sender_liquid} AVT liquid "
                            f"but attempted transfer of {transfer_amount} AVT."
                        ),
                    )
            except HTTPException:
                raise
            except Exception as de_exc:
                # Log but do not block on projection errors during beta
                logger.warning(
                    f"[EventStore] Double-entry check failed (non-blocking): {de_exc}"
                )

        try:
            # --- TITANIUM VAULT D1: Idempotency dedup check ---
            if event.idempotency_key:
                existing = await self.db.execute(
                    select(EventModel).where(
                        EventModel.idempotency_key == event.idempotency_key
                    )
                )
                existing_event = existing.scalar_one_or_none()
                if existing_event:
                    logger.info(
                        f"Idempotent duplicate detected: key={event.idempotency_key}, "
                        f"existing_id={existing_event.id}, type={existing_event.event_type}"
                    )
                    # Return the existing event — caller sees success, no duplicate created
                    return _db_event_to_pydantic(existing_event)
            # --- END TITANIUM VAULT D1 ---
            
            # Create database model
            db_event = EventModel(
                id=event.id,
                event_type=event.event_type,
                aggregate_id=event.aggregate_id,
                aggregate_type=event.aggregate_type,
                data=event.data,
                event_metadata=event.metadata,
                timestamp=event.timestamp,
                version=event.version,
                source_service=event.source_service,
                idempotency_key=event.idempotency_key,  # TITANIUM VAULT D1
                source_operator_id=source_operator_id,  # Federation operator tracking
            )

            self.db.add(db_event)
            await self.db.commit()
            
            logger.info(f"Stored event {event.event_type} for {event.aggregate_id}")
            
            # Publish event via WebSocket
            # NOTE: WebSocket publishing will be handled by the router after successful storage
            # This avoids circular imports and keeps separation of concerns
            
            return event
            
        except IntegrityError as e:
            # TITANIUM VAULT D1: Race condition safety net — concurrent insert with same
            # idempotency_key hits the UNIQUE constraint. This is expected and safe.
            await self.db.rollback()
            if event.idempotency_key and "idempotency_key" in str(e):
                logger.info(
                    f"Concurrent idempotent duplicate caught by UNIQUE constraint: "
                    f"key={event.idempotency_key}"
                )
                # Re-fetch the winner and return it
                existing = await self.db.execute(
                    select(EventModel).where(
                        EventModel.idempotency_key == event.idempotency_key
                    )
                )
                existing_event = existing.scalar_one_or_none()
                if existing_event:
                    return _db_event_to_pydantic(existing_event)
            # Not an idempotency conflict — re-raise
            logger.error(f"IntegrityError storing event: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to store event: {e}")
            await self.db.rollback()
            raise
    
    async def get_events_for_aggregate(
        self,
        aggregate_id: str,
        event_types: Optional[List[str]] = None,
        limit: Optional[int] = None,
        sort_order: str = "asc",
    ) -> List[Event]:
        """Get events for an aggregate.

        §POCKETBRIDGE5 W-G: `limit`/`sort_order` are additive — omitted, this
        is byte-for-byte the legacy full-ASC-history contract the replicators
        and projections depend on.
        """
        query = select(EventModel).where(
            EventModel.aggregate_id == aggregate_id
        )

        if event_types:
            query = query.where(EventModel.event_type.in_(event_types))

        if sort_order == "desc":
            query = query.order_by(EventModel.timestamp.desc())
        else:
            query = query.order_by(EventModel.timestamp)
        if limit is not None:
            query = query.limit(limit)

        result = await self.db.execute(query)
        db_events = result.scalars().all()

        return [_db_event_to_pydantic(e) for e in db_events]
    
    async def get_events_involving_agent(
        self,
        agent_did: str
    ) -> List[Event]:
        """Get all events involving an agent (as aggregate or in transfers)"""
        # Query for events where agent is aggregate_id OR is the recipient of a transfer
        query = select(EventModel).where(
            or_(
                EventModel.aggregate_id == agent_did,
                # Check if agent is the recipient in TokensTransferred events
                (EventModel.event_type == "TokensTransferred") &
                (EventModel.data["to"].astext == agent_did),
                # Also include CrossRegistryTransferCompleted where agent is receiver
                (EventModel.event_type == "CrossRegistryTransferCompleted") &
                (EventModel.data["to"].astext == agent_did),
            )
        ).order_by(EventModel.timestamp)
        
        result = await self.db.execute(query)
        db_events = result.scalars().all()
        
        return [_db_event_to_pydantic(e) for e in db_events]
    
    async def get_all_events(
        self,
        limit: int = 100,
        offset: int = 0,
        sort_order: str = "asc",
    ) -> List[Event]:
        """Get all events with pagination.

        2026-05-07: added `sort_order` so admin UIs can request newest-first
        (the natural default for incident response). Legacy callers default
        to 'asc' for backwards compatibility — historical SF-4 replicators,
        the projection bootstrap, and existing scripts still see chronological
        order without code changes.
        """
        order = EventModel.timestamp.desc() if (sort_order or "asc").lower() == "desc" else EventModel.timestamp.asc()
        query = select(EventModel).order_by(order).limit(limit).offset(offset)

        result = await self.db.execute(query)
        db_events = result.scalars().all()

        return [_db_event_to_pydantic(e) for e in db_events]

    async def get_events_by_type(
        self,
        event_type: str,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Event]:
        """Get events of a single event_type, DESC by timestamp, with paging.

        Used by registry admin endpoints (e.g., the CONSUL drift panel) that
        need to surface recent occurrences of a specific event type. The
        existing `get_all_events` orders ASC and doesn't filter — caller has
        to scan the whole table; this helper does it efficiently with the
        `idx_event_type` index.

        `offset` (default 0) enables true server-side pagination of a single
        type, so the admin Event Ledger can page / loop-fetch the *full* set
        of a type rather than only the recent-N window. offset=0 preserves the
        original recent-N behaviour for every existing caller.
        """
        query = (
            select(EventModel)
            .where(EventModel.event_type == event_type)
            .order_by(EventModel.timestamp.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.db.execute(query)
        db_events = result.scalars().all()
        return [_db_event_to_pydantic(e) for e in db_events]

    async def get_events_by_transaction(
        self,
        transaction_id: str,
    ) -> List[Event]:
        """Return all events carrying this data.transaction_id, newest-first.

        A single TEG transaction id can map to several ledger events (e.g.
        TokensTransferred + TransactionFeeCollected). Uses the JSONB ->> text
        match (same pattern as get_events_involving_agent's data["to"].astext);
        served by the idx on (data->>'transaction_id') when present, else a
        filtered scan. Empty list when the id never reached the ledger
        (TEG-only bookkeeping such as SYSTEM_LOCK holds).
        """
        query = (
            select(EventModel)
            .where(EventModel.data["transaction_id"].astext == transaction_id)
            .order_by(EventModel.timestamp.desc())
        )
        result = await self.db.execute(query)
        db_events = result.scalars().all()
        return [_db_event_to_pydantic(e) for e in db_events]

    async def get_latest_snapshot(self) -> Optional[Event]:
        """Get the most recent ProjectionSnapshot event."""
        query = (
            select(EventModel)
            .where(EventModel.event_type == "ProjectionSnapshot")
            .order_by(EventModel.timestamp.desc())
            .limit(1)
        )
        result = await self.db.execute(query)
        row = result.scalar_one_or_none()
        return _db_event_to_pydantic(row) if row else None

    async def get_events_after(self, after_timestamp, limit: int = 200000) -> List[Event]:
        """Get all events after a given timestamp, ordered chronologically."""
        query = (
            select(EventModel)
            .where(EventModel.timestamp > after_timestamp)
            .order_by(EventModel.timestamp.asc())
            .limit(limit)
        )
        result = await self.db.execute(query)
        db_events = result.scalars().all()
        return [_db_event_to_pydantic(e) for e in db_events]
