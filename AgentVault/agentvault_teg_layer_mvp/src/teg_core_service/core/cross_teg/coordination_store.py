"""
Database-backed coordination store for cross-TEG 2PC state.

Replaces the in-memory `active_coordinations` dict so that coordination
state is visible across all uvicorn workers. Uses the existing
`cross_teg_transfers` table — no new migration needed.

State transitions:
  INITIATED → PREPARED → COMMITTED → COMPLETED
  INITIATED → PREPARED → FAILED (abort)
  INITIATED → FAILED (prepare failed)
"""
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Dict, Any

from sqlalchemy import select, and_
from sqlalchemy.orm import Session

from ...database.models import (
    CrossTEGTransfer,
    CrossTEGTransferStatus,
)

logger = logging.getLogger(__name__)


class CoordinationStore:
    """
    Persists 2PC coordination state to the cross_teg_transfers table.
    Each worker can read/write coordination state via DB queries.
    """

    def __init__(self, db_session_factory, teg_id: str):
        self._db_factory = db_session_factory
        self.teg_id = teg_id

    def _get_session(self) -> Session:
        """Get a sync DB session from the factory generator."""
        gen = self._db_factory()
        session = next(gen)
        return session, gen

    def _close_session(self, session, gen):
        try:
            next(gen)
        except StopIteration:
            pass

    def save_source_coordination(
        self,
        transfer_id: str,
        correlation_id: str,
        source_agent_id: str,
        target_agent_id: str,
        target_teg_id: str,
        target_registry_id: str,
        source_registry_id: str,
        amount: Decimal,
        currency: str,
        expires_at: datetime,
        memo: str = "",
    ):
        """Persist coordination state when source TEG initiates prepare."""
        session, gen = self._get_session()
        try:
            # Use merge to handle re-entry (idempotent)
            record = CrossTEGTransfer(
                transfer_id=transfer_id,
                correlation_id=correlation_id,
                source_teg_id=self.teg_id,
                source_registry_id=source_registry_id,
                source_agent_id=source_agent_id,
                target_teg_id=target_teg_id,
                target_registry_id=target_registry_id,
                target_agent_id=target_agent_id,
                amount=amount,
                currency=currency,
                status=CrossTEGTransferStatus.INITIATED,
                role="source",
                phase="prepare",
                memo=memo,
                expires_at=expires_at,
            )
            session.merge(record)
            session.commit()
            logger.debug(f"[CoordStore] Saved source coordination {transfer_id}")
        except Exception as e:
            session.rollback()
            logger.error(f"[CoordStore] Failed to save source coordination {transfer_id}: {e}")
            raise
        finally:
            self._close_session(session, gen)

    def save_target_coordination(
        self,
        transfer_id: str,
        data: Dict[str, Any],
    ):
        """Persist coordination state when target TEG receives prepare request."""
        session, gen = self._get_session()
        try:
            record = CrossTEGTransfer(
                transfer_id=transfer_id,
                correlation_id=data.get("correlation_id", transfer_id),
                source_teg_id=data.get("source_teg_id", "unknown"),
                source_registry_id=data.get("source_registry_id", "unknown"),
                source_agent_id=data.get("source_agent_id", "unknown"),
                target_teg_id=self.teg_id,
                target_registry_id=data.get("target_registry_id", "unknown"),
                target_agent_id=data.get("target_agent_id", "unknown"),
                amount=Decimal(str(data.get("amount", 0))),
                currency=data.get("currency", "TEG"),
                status=CrossTEGTransferStatus.PREPARED,
                role="target",
                phase="prepare",
                expires_at=datetime.fromisoformat(data["expires_at"]) if "expires_at" in data else datetime.now(timezone.utc),
            )
            session.merge(record)
            session.commit()
            logger.debug(f"[CoordStore] Saved target coordination {transfer_id}")
        except Exception as e:
            session.rollback()
            logger.error(f"[CoordStore] Failed to save target coordination {transfer_id}: {e}")
            raise
        finally:
            self._close_session(session, gen)

    def get_coordination(self, transfer_id: str) -> Optional[CrossTEGTransfer]:
        """Load coordination state from DB. Returns the ORM object or None."""
        session, gen = self._get_session()
        try:
            result = session.execute(
                select(CrossTEGTransfer).where(
                    CrossTEGTransfer.transfer_id == transfer_id
                )
            )
            record = result.scalar_one_or_none()
            if record:
                # Detach from session so it can be used after close
                session.expunge(record)
            return record
        except Exception as e:
            logger.error(f"[CoordStore] Failed to load coordination {transfer_id}: {e}")
            return None
        finally:
            self._close_session(session, gen)

    def update_phase(self, transfer_id: str, phase: str, status: CrossTEGTransferStatus):
        """Update the 2PC phase and status."""
        session, gen = self._get_session()
        try:
            result = session.execute(
                select(CrossTEGTransfer).where(
                    CrossTEGTransfer.transfer_id == transfer_id
                ).with_for_update()
            )
            record = result.scalar_one_or_none()
            if record:
                record.phase = phase
                record.status = status
                session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"[CoordStore] Failed to update phase for {transfer_id}: {e}")
        finally:
            self._close_session(session, gen)

    def mark_completed(self, transfer_id: str):
        """Mark coordination as completed."""
        self.update_phase(transfer_id, "commit", CrossTEGTransferStatus.COMPLETED)
        session, gen = self._get_session()
        try:
            result = session.execute(
                select(CrossTEGTransfer).where(
                    CrossTEGTransfer.transfer_id == transfer_id
                )
            )
            record = result.scalar_one_or_none()
            if record:
                record.completed_at = datetime.now(timezone.utc)
                session.commit()
        except Exception:
            session.rollback()
        finally:
            self._close_session(session, gen)

    def mark_failed(self, transfer_id: str, error_message: str):
        """Mark coordination as failed/aborted."""
        session, gen = self._get_session()
        try:
            result = session.execute(
                select(CrossTEGTransfer).where(
                    CrossTEGTransfer.transfer_id == transfer_id
                )
            )
            record = result.scalar_one_or_none()
            if record:
                record.status = CrossTEGTransferStatus.FAILED
                record.phase = "abort"
                record.error_message = error_message[:1000]
                record.completed_at = datetime.now(timezone.utc)
                session.commit()
        except Exception:
            session.rollback()
        finally:
            self._close_session(session, gen)
