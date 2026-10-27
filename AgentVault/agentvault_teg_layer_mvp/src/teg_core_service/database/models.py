"""Database models for TEG Core Service"""
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import Column, DateTime, Numeric, String, Enum as SQLEnum, Index, Integer, UniqueConstraint, Boolean, Text, ForeignKey
from sqlalchemy.orm import declarative_base  # §DEPS: its home since SQLAlchemy 1.4; the ext.declarative alias is deprecated
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import enum

Base = declarative_base()


class TEGPolicy(Base):
    """TEG governance policies"""
    __tablename__ = "teg_policies"
    
    policy_id = Column(String(36), primary_key=True, index=True)
    policy_code = Column(String(255), unique=True, nullable=False)  # Unique policy code
    policy_name = Column(String(255), nullable=False)
    policy_type = Column(String(100), nullable=False)  # e.g., "attestation"
    policy_version = Column(String(50), nullable=False, default="1.0.0")
    description = Column(Text, nullable=True)
    parameters = Column(Text, nullable=True)  # JSON string of policy parameters
    circuit_identifier = Column(String(255), nullable=True)  # For ZKP policies
    enforcement_level = Column(String(50), nullable=True)  # e.g., "mandatory", "optional"
    reward_amount = Column(Numeric(precision=36, scale=18), nullable=True)  # Reward for compliance
    rules_document_url = Column(String(500), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), 
        server_default=func.now(), 
        onupdate=func.now()
    )
    
    # Relationship to attestations
    attestations = relationship("TEGAttestationLog", back_populates="policy")


class TransactionStatus(str, enum.Enum):
    """Transaction status enumeration"""
    # Database has lowercase values from migration
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    REVERSED = "reversed"


class TransactionType(str, enum.Enum):
    """Transaction type enumeration"""
    TRANSFER = "transfer"
    ISSUANCE = "issuance"
    BURN = "burn"
    LOCK = "lock"  # Lock funds for cross-TEG transfer
    UNLOCK = "unlock"  # Unlock funds after failed cross-TEG transfer
    CROSS_TEG_SEND = "cross_teg_send"  # Outgoing cross-TEG transfer
    CROSS_TEG_RECEIVE = "cross_teg_receive"  # Incoming cross-TEG transfer


class DisputeStatus(str, enum.Enum):
    """Dispute status enumeration"""
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESOLVED_FAVOR_INITIATOR = "RESOLVED_FAVOR_INITIATOR"
    RESOLVED_FAVOR_RESPONDENT = "RESOLVED_FAVOR_RESPONDENT"
    REJECTED = "REJECTED"
    # Legacy statuses for backward compatibility
    LOGGED_MANUAL_REVIEW = "logged_manual_review"
    RESOLVED_NO_ACTION = "resolved_no_action"
    RESOLVED_PENALTY_APPLIED = "resolved_penalty_applied"


class FlagSeverity(str, enum.Enum):
    """Auditor flag severity levels"""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class FlagStatus(str, enum.Enum):
    """Auditor flag status"""
    NEW = "NEW"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"
    # Legacy statuses
    NEW_MANUAL_REVIEW = "new_manual_review"
    MANUAL_REVIEW_CONFIRMED = "manual_review_confirmed"
    RESOLVED_FALSE_POSITIVE = "resolved_false_positive"
    RESOLVED_ACTION_TAKEN_CRITICAL_FLAG = "resolved_action_taken_critical_flag"
    AUTO_FLAGGED_MANUAL_REVIEW = "auto_flagged_manual_review"
    RESOLVED_NO_ACTION = "resolved_no_action"
    RESOLVED_WARNING_ISSUED = "resolved_warning_issued"


class AgentTEGProfile(Base):
    """Agent TEG profile with token balance and reputation"""
    __tablename__ = "agent_teg_profiles"
    
    agent_id = Column(String(255), primary_key=True, index=True)
    token_balance = Column(
        Numeric(precision=36, scale=18), 
        default=Decimal("0"),
        nullable=False
    )
    locked_balance = Column(
        Numeric(precision=36, scale=18),
        default=Decimal("0"),
        nullable=False
    )  # Added for staking integration
    audited_balance = Column(
        Numeric(precision=30, scale=18),
        nullable=False,
        default=Decimal("0"),
        server_default="0"
    )  # Shadow column for balance integrity — must always equal token_balance
    wrapped_balance = Column(
        Numeric(precision=36, scale=18),
        default=Decimal("0"),
        nullable=False,
        server_default="0"
    )  # SF-3: Wrapped-AVT received from other sovereign frames via bridge
    # Reputation fields
    reputation_score = Column(Integer, default=0, nullable=False)
    last_reputation_update = Column(DateTime(timezone=True), nullable=True)
    
    # Account status field to replace in-memory tracking
    account_status = Column(String(50), default="active", nullable=False)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), 
        server_default=func.now(), 
        onupdate=func.now()
    )
    
    # Add index for performance
    __table_args__ = (
        Index("idx_agent_balance", "agent_id", "token_balance"),
    )
    
    # Property for backward compatibility with code expecting agent_did
    @property
    def agent_did(self):
        return self.agent_id
    
    @agent_did.setter
    def agent_did(self, value):
        self.agent_id = value


class TEGTransaction(Base):
    """TEG token transaction record"""
    __tablename__ = "teg_transactions"
    
    transaction_id = Column(
        String(36), 
        primary_key=True, 
        default=lambda: str(uuid4()),
        index=True
    )
    sender_agent_id = Column(String(255), nullable=True, index=True)  # Nullable for issuance
    receiver_agent_id = Column(String(255), nullable=False, index=True)
    amount = Column(
        Numeric(precision=36, scale=18), 
        nullable=False
    )
    fee_amount = Column(
        Numeric(precision=36, scale=18), 
        default=Decimal("0")
    )
    status = Column(
        SQLEnum(TransactionStatus, values_callable=lambda obj: [e.value for e in obj]),
        default=TransactionStatus.PENDING,
        nullable=False,
        index=True
    )
    transaction_type = Column(
        String(50),
        nullable=False,
        default="transfer"  # "transfer", "issuance", "burn"
    )
    timestamp = Column(
        DateTime(timezone=True), 
        server_default=func.now(),
        index=True
    )
    error_message = Column(String(500), nullable=True)
    
    # Reputation signaling fields
    reputation_signal_applied = Column(
        "reputation_signal_applied",
        Boolean,
        default=False,
        nullable=True
    )
    
    # Message attachment field
    attached_message = Column(String(256), nullable=True)
    
    # Composite indexes for common queries
    __table_args__ = (
        Index("idx_sender_timestamp", "sender_agent_id", "timestamp"),
        Index("idx_receiver_timestamp", "receiver_agent_id", "timestamp"),
        Index("idx_status_timestamp", "status", "timestamp"),
        Index("idx_reputation_signal_status", "reputation_signal_applied", "transaction_type", "status"),
    )


class TEGAttestationLog(Base):
    """Attestation submission log"""
    __tablename__ = "teg_attestation_logs"
    
    submission_id = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
        index=True
    )
    agent_did = Column(String(255), nullable=False, index=True)
    attestation_type = Column(String(100), nullable=False)
    attestation_hash = Column(String(255), nullable=False)
    storage_pointer = Column(String(500), nullable=False)  # e.g., IPFS CID
    submitted_at = Column(DateTime(timezone=True), server_default=func.now())
    status = Column(
        String(50),
        default="logged",
        nullable=False
    )  # "logged", "basic_validated", "zkp_verified_true", "zkp_verified_false"
    reward_issued_tx_id = Column(String(36), nullable=True)
    
    # ZKP-specific fields
    circuit_id = Column(String(255), nullable=True)  # e.g., "fairMarkupPolicy/v1.0.0"
    zkp_public_inputs_json = Column(String(2000), nullable=True)  # JSON string of public inputs
    zkp_proof_value = Column(String(5000), nullable=True)  # Proof bytes/string
    
    # Policy governance field
    policy_id = Column(String(36), ForeignKey("teg_policies.policy_id"), nullable=True, index=True)
    
    # Relationship
    policy = relationship("TEGPolicy", back_populates="attestations")
    
    __table_args__ = (
        # Unique constraint to prevent duplicate attestations
        UniqueConstraint(
            "agent_did", "attestation_type", "attestation_hash",
            name="uq_agent_attestation"
        ),
        Index("idx_attestation_agent", "agent_did", "submitted_at"),
    )


class AuditorFlagLog(Base):
    """Algorithmic auditor flag log"""
    __tablename__ = "auditor_flag_logs"
    
    flag_id = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
        index=True
    )
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    flagged_agent_did = Column(String(255), nullable=False, index=True)
    rule_violated_code = Column(String(100), nullable=False)  # e.g., "EXTREME_PRICE_ANOMALY_V1"
    flag_reason = Column(String(1000), nullable=False)  # Detailed reason for the flag
    flag_type = Column(String(100), nullable=True)  # e.g., "HighVolumeVelocity", "SuspiciousReputationActivity"
    severity = Column(
        SQLEnum(FlagSeverity),
        nullable=False,
        default=FlagSeverity.MEDIUM
    )
    related_agent_id = Column(String(255), nullable=True, index=True)  # Related agent if applicable
    related_avtp_transaction_id = Column(String(255), nullable=True)  # Link to AVTP transaction
    related_attestation_id = Column(String(36), nullable=True)  # Link to attestation submission
    related_transaction_id = Column(String(36), nullable=True, index=True)  # Link to TEG transaction
    details = Column(Text, nullable=True)  # JSON or detailed text
    status = Column(
        SQLEnum(FlagStatus),
        default=FlagStatus.NEW_MANUAL_REVIEW,
        nullable=False,
        index=True
    )
    flagged_by = Column(String(255), nullable=False)  # Who/what generated the flag
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    __table_args__ = (
        Index("idx_flag_agent_status", "flagged_agent_did", "status"),
        Index("idx_flag_timestamp", "timestamp"),
        Index("idx_flags_type_severity", "flag_type", "severity"),
    )


class TEGDisputeLog(Base):
    """Dispute log for DDR interface"""
    __tablename__ = "teg_dispute_logs"
    
    dispute_log_id = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
        index=True
    )
    claimant_agent_did = Column(String(255), nullable=False, index=True)
    defendant_agent_did = Column(String(255), nullable=False, index=True)
    avtp_transaction_id = Column(String(255), nullable=True)
    reason_code = Column(String(100), nullable=False)
    brief_description = Column(String(1000), nullable=False)
    evidence_pointer = Column(String(500), nullable=True)  # e.g., IPFS CID
    status = Column(
        SQLEnum(DisputeStatus),
        default=DisputeStatus.LOGGED_MANUAL_REVIEW,
        nullable=False,
        index=True
    )
    resolution_notes = Column(String(2000), nullable=True)
    
    # Enhanced fields for governance
    dispute_reason_category = Column(
        String(100), 
        nullable=True,
        index=True
    )  # e.g., "UnfairFee", "FailedService", "ReputationAbuse"
    related_transaction_id = Column(String(36), nullable=True, index=True)
    evidence_description_or_url = Column(String(1000), nullable=True)
    admin_reviewer_id = Column(String(255), nullable=True)  # Admin who reviewed/resolved
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now()
    )
    
    __table_args__ = (
        Index("idx_dispute_claimant", "claimant_agent_did", "created_at"),
        Index("idx_dispute_defendant", "defendant_agent_did", "created_at"),
        Index("idx_dispute_status", "status", "created_at"),
    )


class AVTPTransactionSummaryLog(Base):
    """AVTP transaction summary log for reputation and auditing"""
    __tablename__ = "avtp_transaction_summary_logs"
    
    log_id = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
        index=True
    )
    avtp_transaction_id = Column(String(255), unique=True, nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    agent_did = Column(String(255), nullable=False, index=True)  # The agent who provided the service
    initiating_agent_did = Column(String(255), nullable=False, index=True)
    responding_agent_did = Column(String(255), nullable=False, index=True)
    service_identifier = Column(String(255), nullable=True)
    price_avt = Column(Numeric(precision=36, scale=18), nullable=True)  # Price in AVT
    transaction_value = Column(String(100), nullable=True)  # String to accommodate various formats
    currency_type = Column(String(50), nullable=True)  # e.g., "AVT", "USD_SATS"
    outcome_status = Column(
        String(50),
        nullable=False,
        index=True
    )  # "SUCCESS", "FAILURE_PROVIDER", "FAILURE_CONSUMER", "FAILURE_PROTOCOL"
    sla_identifier_referenced = Column(String(255), nullable=True)
    raw_log_pointer = Column(String(500), nullable=True)  # e.g., IPFS CID
    created_at = Column(DateTime(timezone=True), server_default=func.now())  # For consistency
    
    __table_args__ = (
        Index("idx_avtp_initiating_agent", "initiating_agent_did", "timestamp"),
        Index("idx_avtp_responding_agent", "responding_agent_did", "timestamp"),
        Index("idx_avtp_outcome", "outcome_status", "timestamp"),
        Index("idx_avtp_agents_outcome", "initiating_agent_did", "responding_agent_did", "outcome_status"),
    )


class TEGRewardConfig(Base):
    """Reward configuration for various TEG actions"""
    __tablename__ = "teg_reward_configs"
    
    reward_id = Column(String(36), primary_key=True, index=True)
    reward_type = Column(String(100), nullable=False)  # e.g., "attestation_submission"
    reward_code = Column(String(255), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    amount = Column(Numeric(precision=36, scale=18), nullable=False)
    policy_code = Column(String(255), nullable=True)  # Link to policy if applicable
    conditions = Column(Text, nullable=True)  # JSON string of conditions
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), 
        server_default=func.now(), 
        onupdate=func.now()
    )


class TEGRewardDistribution(Base):
    """Record of rewards distributed to agents"""
    __tablename__ = "teg_reward_distributions"
    
    distribution_id = Column(String(36), primary_key=True, index=True)
    agent_id = Column(String(255), nullable=False, index=True)
    reward_type = Column(String(100), nullable=False)
    amount = Column(Numeric(precision=36, scale=18), nullable=False)
    policy_code = Column(String(255), nullable=True)
    transaction_id = Column(String(36), nullable=True)  # Link to TEG transaction
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    
    __table_args__ = (
        Index("idx_reward_agent_timestamp", "agent_id", "timestamp"),
    )


class BootstrapToken(Base):
    """Bootstrap tokens for agent self-onboarding"""
    __tablename__ = "bootstrap_tokens"
    
    token_id = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
        index=True
    )
    token_value = Column(
        String(255),
        unique=True,
        nullable=False,
        index=True
    )  # The actual token string (e.g., "bst_a1b2c3d4e5f67890_xxxxxxxxxxxx")
    agent_type_hint = Column(String(255), nullable=True)  # e.g., "com.agentvault.research.v1"
    requested_by = Column(String(255), nullable=True)  # e.g., "cli-user-rzj"
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    is_used = Column(Boolean, default=False, nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)
    used_by_agent_did = Column(String(255), nullable=True, index=True)  # The DID created with this token
    
    __table_args__ = (
        Index("idx_bootstrap_token_status", "is_used", "expires_at"),
    )


class Stake(Base):
    """Stake records for agents locking their AVT tokens"""
    __tablename__ = "stakes"
    
    stake_id = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
        index=True
    )
    agent_id = Column(String(255), ForeignKey("agent_teg_profiles.agent_id"), nullable=False, index=True)
    amount = Column(
        Numeric(precision=36, scale=18),
        nullable=False
    )
    staked_at = Column(DateTime(timezone=True), server_default=func.now())
    unstaked_at = Column(DateTime(timezone=True), nullable=True)  # Null if still staked
    is_active = Column(Boolean, default=True, nullable=False, index=True)  # False when unstaked
    last_reward_claim = Column(DateTime(timezone=True), nullable=True)  # Track reward distribution
    lock_period_days = Column(Integer, nullable=True)  # Optional lock period in days
    unlock_date = Column(DateTime(timezone=True), nullable=True)  # When the stake can be unstaked
    
    # Relationship to agent profile
    agent = relationship("AgentTEGProfile", backref="stakes")
    
    __table_args__ = (
        Index("idx_stake_agent_active", "agent_id", "is_active"),
        Index("idx_stake_active_amount", "is_active", "amount"),
    )


class Delegation(Base):
    """Delegation records for agents delegating stake to validators"""
    __tablename__ = "delegations"
    
    delegation_id = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
        index=True
    )
    delegator_agent_id = Column(String(255), ForeignKey("agent_teg_profiles.agent_id"), nullable=False, index=True)
    validator_agent_id = Column(String(255), ForeignKey("agent_teg_profiles.agent_id"), nullable=False, index=True)
    stake_id = Column(String(36), ForeignKey("stakes.stake_id"), nullable=False, index=True)  # Which stake is delegated
    delegated_amount = Column(
        Numeric(precision=36, scale=18),
        nullable=False
    )
    delegation_start = Column(DateTime(timezone=True), server_default=func.now())
    delegation_end = Column(DateTime(timezone=True), nullable=True)  # Null if still delegated
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    reward_share_percentage = Column(
        Numeric(precision=5, scale=2),
        default=Decimal("10.00"),  # Default 10% share to validator
        nullable=False
    )
    
    # Relationships
    delegator = relationship("AgentTEGProfile", foreign_keys=[delegator_agent_id], backref="delegations_given")
    validator = relationship("AgentTEGProfile", foreign_keys=[validator_agent_id], backref="delegations_received")
    stake = relationship("Stake", backref="delegations")
    
    __table_args__ = (
        Index("idx_delegation_delegator_active", "delegator_agent_id", "is_active"),
        Index("idx_delegation_validator_active", "validator_agent_id", "is_active"),
    )


class StakingRewardDistribution(Base):
    """Record of staking rewards distributed to agents"""
    __tablename__ = "staking_reward_distributions"
    
    distribution_id = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
        index=True
    )
    stake_id = Column(String(36), ForeignKey("stakes.stake_id"), nullable=False, index=True)
    agent_id = Column(String(255), ForeignKey("agent_teg_profiles.agent_id"), nullable=False, index=True)
    amount = Column(
        Numeric(precision=36, scale=18),
        nullable=False
    )
    reward_type = Column(String(50), nullable=False)  # "staking", "delegation_validator", "delegation_delegator"
    transaction_id = Column(String(36), nullable=True)  # Link to TEG transaction if rewards are paid out
    distributed_at = Column(DateTime(timezone=True), server_default=func.now())
    reward_cycle_id = Column(String(36), nullable=True, index=True)  # Group rewards by cycle
    
    # Relationships
    stake = relationship("Stake", backref="reward_distributions")
    agent = relationship("AgentTEGProfile", backref="staking_rewards_received")
    
    __table_args__ = (
        Index("idx_staking_reward_agent_time", "agent_id", "distributed_at"),
        Index("idx_staking_reward_cycle", "reward_cycle_id"),
    )


class SystemConfig(Base):
    """System configuration storage"""
    __tablename__ = "system_config"
    
    id = Column(Integer, primary_key=True)
    key = Column(String(100), unique=True, nullable=False)
    value = Column(String(500), nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now()
    )


class CrossTEGTransferStatus(str, enum.Enum):
    """Cross-TEG transfer status enumeration"""
    INITIATED = "initiated"
    FUNDS_LOCKED = "funds_locked"
    PREPARED = "prepared"
    COMMITTED = "committed"
    COMPLETED = "completed"
    FAILED = "failed"
    COMPENSATED = "compensated"
    # §V0050 — terminal write-down for stale async-leg bookkeeping rows whose
    # value already settled/refunded via the escrow ledger. Distinct from
    # FAILED/COMPENSATED so failure analytics and compensation semantics stay
    # truthful. Set ONLY by coordinator.sweep_stale_bookkeeping().
    SWEPT = "swept"


class CrossTEGTransfer(Base):
    """Cross-TEG transfer tracking"""
    __tablename__ = "cross_teg_transfers"
    
    transfer_id = Column(
        String(36),
        primary_key=True,
        index=True
    )
    correlation_id = Column(String(36), nullable=False, index=True)
    
    # Source information
    source_teg_id = Column(String(255), nullable=False)
    source_registry_id = Column(String(255), nullable=False)
    source_agent_id = Column(String(255), nullable=False, index=True)
    
    # Target information
    target_teg_id = Column(String(255), nullable=False)
    target_registry_id = Column(String(255), nullable=False)
    target_agent_id = Column(String(255), nullable=False, index=True)
    
    # Transfer details
    amount = Column(
        Numeric(precision=36, scale=18),
        nullable=False
    )
    currency = Column(String(10), default="TEG", nullable=False)
    
    # Status tracking
    status = Column(
        SQLEnum(CrossTEGTransferStatus),
        default=CrossTEGTransferStatus.INITIATED,
        nullable=False,
        index=True
    )
    
    # Coordination details
    role = Column(String(20), nullable=False)  # "source" or "target"
    phase = Column(String(20), nullable=True)  # Current phase in 2PC
    
    # Transaction references
    lock_transaction_id = Column(String(36), nullable=True)
    debit_transaction_id = Column(String(36), nullable=True)
    credit_transaction_id = Column(String(36), nullable=True)
    compensation_transaction_id = Column(String(36), nullable=True)
    
    # Metadata
    memo = Column(String(500), nullable=True)
    error_message = Column(String(1000), nullable=True)
    
    # Timestamps
    initiated_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    
    # Audit fields
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now()
    )
    
    __table_args__ = (
        Index("idx_cross_teg_source", "source_agent_id", "initiated_at"),
        Index("idx_cross_teg_target", "target_agent_id", "initiated_at"),
        Index("idx_cross_teg_status", "status", "initiated_at"),
        Index("idx_cross_teg_correlation", "correlation_id"),
    )
