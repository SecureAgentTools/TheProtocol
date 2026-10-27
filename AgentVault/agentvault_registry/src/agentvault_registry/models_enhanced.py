# Enhanced Models for Operation Beta Forge
# Add these to your models.py file

from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, JSON, Index, DECIMAL, Text
from sqlalchemy.orm import relationship, Mapped, mapped_column
from .database import Base
import datetime
from typing import Optional, Dict, Any, TYPE_CHECKING
from decimal import Decimal

if TYPE_CHECKING:
    from .models import Agent

# --- ADDED: Enhanced Staking Models ---
class Stake(Base):
    """
    Enhanced SQLAlchemy model for tracking individual stakes.
    
    This model tracks each stake as a separate entity, allowing for:
    - Partial unstaking
    - FIFO unstaking logic
    - Cooldown period tracking
    - TEG integration tracking
    """
    __tablename__ = "stakes"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    agent_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("agents.id"), nullable=False, index=True
    )
    agent_did: Mapped[str] = mapped_column(String, nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(DECIMAL(precision=36, scale=18), nullable=False)
    staked_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    unstaked_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    teg_stake_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # TEG Layer reference
    
    # Relationship to Agent
    agent: Mapped["Agent"] = relationship("Agent", backref="stakes")
    
    # Indexes
    __table_args__ = (
        Index("ix_stakes_agent_id", "agent_id"),
        Index("ix_stakes_agent_did", "agent_did"),
        Index("ix_stakes_is_active", "is_active"),
        Index("ix_stakes_staked_at", "staked_at"),
    )
    
    def __repr__(self):
        return f"<Stake(id={self.id}, agent={self.agent_did}, amount={self.amount}, active={self.is_active})>"


class IdempotencyKey(Base):
    """
    SQLAlchemy model for storing idempotency keys to prevent duplicate operations.
    
    This ensures that if a client retries a request with the same idempotency key,
    they get the same response without re-executing the operation.
    """
    __tablename__ = "idempotency_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String, nullable=False, index=True)
    agent_id: Mapped[str] = mapped_column(String, nullable=False, index=True)  # Agent DID
    response_data: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    
    # Indexes
    __table_args__ = (
        Index("ix_idempotency_keys_key_agent", "key", "agent_id", unique=True),
        Index("ix_idempotency_keys_created_at", "created_at"),
    )
    
    def __repr__(self):
        return f"<IdempotencyKey(key={self.key}, agent={self.agent_id})>"


# --- Update StakeTransaction model ---
# Add these fields to the existing StakeTransaction model:
# stake_id: Foreign key to Stake table
# teg_transaction_id: Reference to TEG Layer transaction

class StakeTransactionEnhanced(Base):
    """
    Enhanced stake transaction model with additional fields.
    Replace or merge with existing StakeTransaction model.
    """
    __tablename__ = "stake_transactions_v2"  # Use different table name if migrating

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    agent_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("agents.id"), nullable=False, index=True
    )
    stake_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("stakes.id"), nullable=True, index=True
    )
    transaction_type: Mapped[str] = mapped_column(
        String, nullable=False, index=True
    )  # "stake" or "unstake"
    amount: Mapped[Decimal] = mapped_column(DECIMAL(precision=36, scale=18), nullable=False)
    timestamp: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    teg_transaction_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    
    # Relationships
    agent: Mapped["Agent"] = relationship("Agent", backref="stake_transactions_v2")
    stake: Mapped[Optional["Stake"]] = relationship("Stake", backref="transactions")
    
    # Indexes
    __table_args__ = (
        Index("ix_stake_tx_v2_agent_id", "agent_id"),
        Index("ix_stake_tx_v2_timestamp", "timestamp"),
        Index("ix_stake_tx_v2_type", "transaction_type"),
    )
