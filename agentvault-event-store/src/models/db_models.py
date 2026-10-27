from sqlalchemy import Column, String, DateTime, Integer, BigInteger, Boolean, Index, UniqueConstraint, Sequence
from sqlalchemy.dialects.postgresql import UUID, JSONB
from ..database.connection import Base
import uuid
from datetime import datetime, timezone

class EventModel(Base):
    __tablename__ = "events"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_type = Column(String(100), nullable=False)
    aggregate_id = Column(String(255), nullable=False)
    aggregate_type = Column(String(50), nullable=False, default="Agent")
    data = Column(JSONB, nullable=False)
    event_metadata = Column(JSONB, default=dict)
    timestamp = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    version = Column(Integer, nullable=False)
    source_service = Column(String(50), nullable=False)
    # TITANIUM VAULT D1: Idempotency key for exactly-once event delivery
    # Nullable for backward compat with existing events. Unique where present.
    idempotency_key = Column(String(255), nullable=True, unique=True, index=True)
    # Federation: Track which operator submitted this event (null for origin/internal)
    source_operator_id = Column(String(36), nullable=True)

    # 2026-05-02 (Round 4): monotonic INSERT-time cursor for cross-frame
    # replication. The `timestamp` column is set at event-emit time, which
    # under Kafka-async persistence (EVENTSTORE_HTTP_VIA_KAFKA=true) can
    # land in events table OUT OF ORDER vs other concurrent emissions —
    # a replicator using `timestamp > since` as cursor would skip events
    # whose timestamp predates a watermark that already advanced past them.
    # `seq` is filled by the DB sequence at INSERT time, strictly monotonic
    # in commit order. Replicator queries `seq > since_seq` for race-free
    # exactly-once-eventual replication. Nullable for backwards compat with
    # rows persisted before the migration.
    seq = Column(BigInteger, Sequence("events_seq_seq"), nullable=True, index=True)

    __table_args__ = (
        Index("idx_aggregate_id", "aggregate_id"),
        Index("idx_event_type", "event_type"),
        Index("idx_timestamp", "timestamp"),
        Index("idx_aggregate_timestamp", "aggregate_id", "timestamp"),
    )


class ForeignEventModel(Base):
    """SF-4: Events replicated from other sovereign frames (read-only audit trail)."""
    __tablename__ = "foreign_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    frame_id = Column(String(255), nullable=False)
    source_event_id = Column(UUID(as_uuid=True), nullable=False)
    event_type = Column(String(100), nullable=False)
    aggregate_id = Column(String(255), nullable=False)
    data = Column(JSONB, nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    source_service = Column(String(50), nullable=True)
    idempotency_key = Column(String(255), nullable=True)
    replicated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    verified = Column(Boolean, default=False)

    __table_args__ = (
        UniqueConstraint("frame_id", "source_event_id", name="uq_foreign_frame_event"),
        Index("idx_foreign_frame_ts", "frame_id", "timestamp"),
        Index("idx_foreign_event_type", "event_type"),
        Index("idx_foreign_aggregate", "aggregate_id"),
    )


class CrossFramePeerModel(Base):
    """SF-4 WS3.5 (2026-04-21): dynamic cross-frame peer registry.

    Replaces the static CROSS_FRAME_PEERS env var with a DB-backed list so
    new frames can be registered/suspended at runtime without restarting
    the EventStore container. The replicator supervisor loop re-reads this
    table every cycle and spawns/cancels per-peer polling tasks accordingly.

    The `last_timestamp` watermark is persisted here (moved from an
    in-process dict) so restarts don't re-fetch the last 7 days of events.
    """
    __tablename__ = "cross_frame_peers"

    frame_id = Column(String(255), primary_key=True)
    url = Column(String(500), nullable=False)
    status = Column(String(20), nullable=False, default="active")  # active | suspended | removed
    last_timestamp = Column(DateTime(timezone=True), nullable=True)  # legacy timestamp watermark (kept for display + 2pc fallback)
    # 2026-05-02 (Round 4): monotonic INSERT-time cursor watermark. Pairs
    # with EventModel.seq. Avoids the Kafka-async race where events with
    # timestamp T1 land in events table AFTER an event with timestamp T2 (T2>T1)
    # has already advanced last_timestamp past T1.
    last_seq = Column(BigInteger, nullable=False, server_default="0")
    added_by = Column(String(200), nullable=True)  # actor (admin email / 'env-bootstrap' / etc)
    added_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        Index("idx_cross_frame_peer_status", "status"),
    )