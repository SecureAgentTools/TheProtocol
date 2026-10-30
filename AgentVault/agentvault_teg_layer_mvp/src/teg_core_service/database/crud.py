"""CRUD operations for TEG Core Service

This module provides Create, Read, Update, Delete operations for all TEG database models.
It implements business logic for token transfers, attestation logging, dispute management,
and AVTP transaction recording.

Key design principles:
- All operations use SQLAlchemy sessions for transaction management
- Atomic operations for financial transactions (token transfers)
- Proper error handling with meaningful exceptions
- Consistent naming conventions for CRUD methods
"""
from decimal import Decimal
import hashlib
import secrets
from typing import Optional, List
from uuid import uuid4
from datetime import datetime, timezone
import logging

from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc, func, text
from sqlalchemy.exc import IntegrityError

from .models import (
    AgentTEGProfile, TEGTransaction, TransactionStatus,
    TEGAttestationLog, AuditorFlagLog, TEGDisputeLog,
    AVTPTransactionSummaryLog, SystemConfig, TEGPolicy,
    DisputeStatus, FlagSeverity, FlagStatus, BootstrapToken,
    Stake, Delegation, StakingRewardDistribution
)
from .home_frame_resolver import (
    AgentNotHomeError,
    check_home_or_raise as _check_home_or_raise,
)

logger = logging.getLogger(__name__)


class AgentCRUD:
    """CRUD operations for Agent TEG profiles
    
    Handles agent profile management including creation, balance queries,
    and balance updates. Implements a get_or_create pattern to ensure
    agents are automatically created when first referenced.
    """
    
    @staticmethod
    def get_or_create(db: Session, agent_id: str) -> AgentTEGProfile:
        """Get existing agent profile or create new one with zero balance
        
        This method ensures that agents are automatically registered in the
        TEG system when first referenced. New agents start with zero balance
        and zero reputation.
        
        Args:
            db: Database session
            agent_id: Agent DID (e.g., 'agent_12345' or 'did:agentvault:alice')
            
        Returns:
            AgentTEGProfile: The agent's profile (existing or newly created)
            
        Note:
            This method commits the transaction if a new agent is created.
            In high-concurrency scenarios, consider handling race conditions.
        """
        agent = db.query(AgentTEGProfile).filter(
            AgentTEGProfile.agent_id == agent_id
        ).first()

        if agent:
            return agent

        # Home-frame guard (gated by TEG_HOME_FRAME_GUARD_ENABLED env). When
        # enabled, refuse to provision a profile for an agent whose home is
        # a different frame. System accounts (fee_collector, treasury) bypass
        # the guard. Resolver returns None for unknown agents (race window /
        # registry unreachable) — guard allows local create in that case so
        # ops continue; daily reconciler cleans up orphans.
        _check_home_or_raise(agent_id)

        # §FRAMELIC (2026-09-07, findings row 152) — THE CREATE COMMITS IN ITS OWN
        # TRANSACTION, ON ITS OWN CONNECTION.
        #
        # This used to be `db.add(agent); db.flush()` with the note "caller controls
        # commit". A GET handler is a caller that never commits: `/admin/exchange/escrow`
        # is a read that calls get_or_create for `teg:system:exchange_escrow`, so the
        # first poller to find the row missing INSERTed it, held the primary-key lock for
        # the life of the request, and every concurrent poller blocked on `transactionid`.
        #
        # MEASURED on the EU frame: four TEG workers stuck 1h21m behind one
        # `idle in transaction` session, the whole pool gone, `/health` timing out,
        # `restart=unless-stopped` NOT restarting (the container was up, just unhealthy),
        # the registry answering 503 "TEG treasury service unavailable" for 85 minutes,
        # and the frame's own status page reading `EU TEG down`. The convoy also feeds
        # itself: the registry retries, each retry takes another connection, and one
        # caller already carries a hand-rolled backoff for it
        # (`background_tasks/exchange_settlement.py` "TEG is convoyed").
        #
        # A shared system account (`exchange_escrow`, `fee_collector`, `treasury`) is the
        # worst case because EVERY caller races for the SAME row. So: insert-if-absent on
        # a short-lived session that commits immediately, then read the row back through
        # the caller's session — the loser of the race simply sees the winner's row and
        # nobody holds a lock past their own statement. The caller's transaction keeps its
        # own atomicity: it never wrote this row, it only reads it.
        from sqlalchemy.dialects.postgresql import insert as _pg_insert
        from .db_session import SessionLocal as _SessionLocal

        _own = _SessionLocal()
        try:
            _own.execute(
                _pg_insert(AgentTEGProfile.__table__)
                .values(agent_id=agent_id, token_balance=Decimal("0"),
                        audited_balance=Decimal("0"), reputation_score=0)
                .on_conflict_do_nothing(index_elements=["agent_id"])
            )
            _own.commit()
        except Exception as exc:  # noqa: BLE001 — never let provisioning kill the read
            _own.rollback()
            logger.warning(
                "[TEG] get_or_create(%s): independent create failed (%s) — "
                "falling back to an in-transaction insert", agent_id, exc
            )
            agent = AgentTEGProfile(
                agent_id=agent_id,
                token_balance=Decimal("0"),
                audited_balance=Decimal("0"),
                reputation_score=0,
            )
            db.add(agent)
            db.flush()
            db.refresh(agent)
            return agent
        finally:
            _own.close()

        agent = db.query(AgentTEGProfile).filter(
            AgentTEGProfile.agent_id == agent_id
        ).first()
        if agent is None:
            # The row was committed on another connection; this session may be pinned to
            # a snapshot older than that commit (REPEATABLE READ, or a long-running
            # transaction). Re-read on a new snapshot rather than reporting "absent".
            db.rollback()
            agent = db.query(AgentTEGProfile).filter(
                AgentTEGProfile.agent_id == agent_id
            ).first()
        if agent is None:
            raise RuntimeError(
                f"TEG profile for {agent_id} could not be created or read back"
            )
        return agent
    
    @staticmethod
    def get_balance(db: Session, agent_id: str) -> Decimal:
        """Get agent's token balance"""
        agent = AgentCRUD.get_or_create(db, agent_id)
        return agent.token_balance
    
    @staticmethod
    def update_balance(
        db: Session, 
        agent_id: str, 
        new_balance: Decimal
    ) -> AgentTEGProfile:
        """Update agent's token balance"""
        agent = AgentCRUD.get_or_create(db, agent_id)
        agent.token_balance = new_balance
        # Keep audited_balance in sync
        agent.audited_balance = new_balance
        db.commit()
        db.refresh(agent)
        return agent
    
    @staticmethod
    def suspend_agent(
        db: Session,
        agent_id: str,
        suspension_duration_hours: int,
        suspension_reason: str
    ) -> AgentTEGProfile:
        """Suspend an agent for a specified duration"""
        agent = AgentCRUD.get_or_create(db, agent_id)
        agent.account_status = "suspended"
        # Store suspension details in a JSON field or separate table
        # For MVP, we'll use the account_status field
        from datetime import datetime, timedelta
        suspension_end = datetime.now(timezone.utc) + timedelta(hours=suspension_duration_hours)
        
        # Store suspension info in system config temporarily
        # In production, this would be in a separate suspension table
        suspension_key = f"suspension_{agent_id}"
        suspension_data = {
            "reason": suspension_reason,
            "suspended_until": suspension_end.isoformat(),
            "duration_hours": suspension_duration_hours
        }
        import json
        SystemConfigCRUD.set_value(db, suspension_key, json.dumps(suspension_data))
        
        db.commit()
        db.refresh(agent)
        return agent
    
    @staticmethod
    def reinstate_agent(db: Session, agent_id: str) -> AgentTEGProfile:
        """Reactivate a suspended agent — clears account_status and removes
        suspension SystemConfig row. Idempotent: noop if agent not suspended."""
        agent = AgentCRUD.get_or_create(db, agent_id)
        if agent.account_status != "suspended":
            return agent
        agent.account_status = "active"
        # Remove the suspension config row (mirror of suspend_agent's set_value)
        suspension_key = f"suspension_{agent_id}"
        try:
            db.query(SystemConfig).filter(SystemConfig.key == suspension_key).delete()
        except Exception:
            pass
        db.commit()
        db.refresh(agent)
        return agent

    @staticmethod
    def is_agent_suspended(db: Session, agent_id: str) -> tuple[bool, Optional[dict]]:
        """Check if an agent is suspended and return suspension details"""
        agent = AgentCRUD.get_or_create(db, agent_id)
        if agent.account_status != "suspended":
            return False, None
        
        # Get suspension details
        suspension_key = f"suspension_{agent_id}"
        suspension_data_str = SystemConfigCRUD.get_value(db, suspension_key)
        if not suspension_data_str:
            return False, None
        
        import json
        from datetime import datetime, timezone
        try:
            suspension_data = json.loads(suspension_data_str)
            suspended_until = datetime.fromisoformat(suspension_data["suspended_until"])
            
            # Check if suspension has expired
            if datetime.now(timezone.utc) > suspended_until:
                # Unsuspend the agent
                agent.account_status = "active"
                db.commit()
                # Clean up suspension data
                db.query(SystemConfig).filter(SystemConfig.key == suspension_key).delete()
                db.commit()
                return False, None
            
            return True, suspension_data
        except Exception:
            return False, None


class AVTPLogCRUD:
    """CRUD operations for AVTP transaction summary logs
    
    Manages AVTP (AgentVault Transport Protocol) transaction summaries
    which are used for reputation calculation and auditing. Each log
    represents the outcome of a service transaction between agents.
    """
    
    @staticmethod
    def create_log(
        db: Session,
        avtp_transaction_id: str,
        agent_did: str,
        initiating_agent_did: str,
        responding_agent_did: str,
        outcome_status: str,
        timestamp: Optional[datetime] = None,
        service_identifier: Optional[str] = None,
        price_avt: Optional[Decimal] = None,
        transaction_value: Optional[str] = None,
        currency_type: Optional[str] = None,
        sla_identifier_referenced: Optional[str] = None,
        raw_log_pointer: Optional[str] = None
    ) -> AVTPTransactionSummaryLog:
        """Create a new AVTP transaction summary log"""
        log = AVTPTransactionSummaryLog(
            log_id=str(uuid4()),
            avtp_transaction_id=avtp_transaction_id,
            timestamp=timestamp or datetime.now(timezone.utc),
            agent_did=agent_did,
            initiating_agent_did=initiating_agent_did,
            responding_agent_did=responding_agent_did,
            service_identifier=service_identifier,
            price_avt=price_avt,
            transaction_value=transaction_value,
            currency_type=currency_type,
            outcome_status=outcome_status,
            sla_identifier_referenced=sla_identifier_referenced,
            raw_log_pointer=raw_log_pointer
        )
        db.add(log)
        try:
            db.commit()
            db.refresh(log)
            return log
        except IntegrityError:
            db.rollback()
            raise ValueError(f"AVTP transaction {avtp_transaction_id} already exists")
    
    @staticmethod
    def get_by_transaction_id(
        db: Session,
        avtp_transaction_id: str
    ) -> Optional[AVTPTransactionSummaryLog]:
        """Get AVTP log by transaction ID"""
        return db.query(AVTPTransactionSummaryLog).filter(
            AVTPTransactionSummaryLog.avtp_transaction_id == avtp_transaction_id
        ).first()
    
    @staticmethod
    def count_agent_transactions(
        db: Session,
        agent_did: str,
        outcome_status: Optional[str] = None
    ) -> int:
        """Count transactions for an agent with optional outcome filter"""
        query = db.query(AVTPTransactionSummaryLog).filter(
            or_(
                AVTPTransactionSummaryLog.initiating_agent_did == agent_did,
                AVTPTransactionSummaryLog.responding_agent_did == agent_did
            )
        )
        
        if outcome_status:
            query = query.filter(AVTPTransactionSummaryLog.outcome_status == outcome_status)
        
        return query.count()
    
    @staticmethod
    def count_successful_transactions(db: Session, agent_did: str) -> int:
        """Count successful transactions for an agent"""
        return AVTPLogCRUD.count_agent_transactions(db, agent_did, "SUCCESS")
    
    @staticmethod
    def count_failed_transactions(db: Session, agent_did: str) -> int:
        """Count failed transactions for an agent
        
        Counts all transactions with failure outcomes where the agent
        was involved as either initiator or responder. Failure types:
        - FAILURE_PROVIDER: Service provider failed to deliver
        - FAILURE_CONSUMER: Service consumer violated terms
        - FAILURE_PROTOCOL: Protocol-level failure
        
        Args:
            db: Database session
            agent_did: Agent DID to count failures for
            
        Returns:
            int: Number of failed transactions
        """
        return db.query(AVTPTransactionSummaryLog).filter(
            and_(
                or_(
                    AVTPTransactionSummaryLog.initiating_agent_did == agent_did,
                    AVTPTransactionSummaryLog.responding_agent_did == agent_did
                ),
                AVTPTransactionSummaryLog.outcome_status.in_([
                    "FAILURE_PROVIDER",
                    "FAILURE_CONSUMER", 
                    "FAILURE_PROTOCOL"
                ])
            )
        ).count()


class PolicyCRUD:
    """CRUD operations for TEG Policies
    
    Manages governance policies that control attestation types,
    reward conditions, and other system behaviors.
    """
    
    @staticmethod
    def create_policy(
        db: Session,
        policy_code: str,
        policy_name: str,
        policy_type: str,
        description: Optional[str] = None,
        parameters: Optional[dict] = None,
        circuit_identifier: Optional[str] = None,
        enforcement_level: Optional[str] = None,
        reward_amount: Optional[Decimal] = None,
        policy_version: str = "1.0.0",
        rules_document_url: Optional[str] = None,
        is_active: bool = True
    ) -> TEGPolicy:
        """Create a new policy"""
        import json
        policy = TEGPolicy(
            policy_id=str(uuid4()),
            policy_code=policy_code,
            policy_name=policy_name,
            policy_type=policy_type,
            policy_version=policy_version,
            description=description,
            parameters=json.dumps(parameters) if parameters else None,
            circuit_identifier=circuit_identifier,
            enforcement_level=enforcement_level,
            reward_amount=reward_amount,
            rules_document_url=rules_document_url,
            is_active=is_active
        )
        db.add(policy)
        try:
            db.commit()
            db.refresh(policy)
            return policy
        except IntegrityError:
            db.rollback()
            raise ValueError(f"Policy with code '{policy_code}' already exists")
    
    @staticmethod
    def get_policy_by_id(db: Session, policy_id: str) -> Optional[TEGPolicy]:
        """Get policy by ID"""
        return db.query(TEGPolicy).filter(
            TEGPolicy.policy_id == policy_id
        ).first()
    
    @staticmethod
    def get_policy_by_code(db: Session, policy_code: str) -> Optional[TEGPolicy]:
        """Get policy by code"""
        return db.query(TEGPolicy).filter(
            TEGPolicy.policy_code == policy_code
        ).first()
    
    @staticmethod
    def get_policy_by_name(db: Session, policy_name: str) -> Optional[TEGPolicy]:
        """Get policy by name"""
        return db.query(TEGPolicy).filter(
            TEGPolicy.policy_name == policy_name
        ).first()
    
    @staticmethod
    def get_policy_by_circuit_identifier(db: Session, circuit_identifier: str) -> Optional[TEGPolicy]:
        """Get policy by circuit identifier"""
        return db.query(TEGPolicy).filter(
            TEGPolicy.circuit_identifier == circuit_identifier
        ).first()
    
    @staticmethod
    def get_all_policies(
        db: Session,
        active_only: bool = False
    ) -> List[TEGPolicy]:
        """Get all policies, optionally filtering by active status"""
        query = db.query(TEGPolicy)
        if active_only:
            query = query.filter(TEGPolicy.is_active == True)
        return query.order_by(TEGPolicy.created_at.desc()).all()
    
    @staticmethod
    def update_policy(
        db: Session,
        policy_id: str,
        policy_name: Optional[str] = None,
        description: Optional[str] = None,
        parameters: Optional[dict] = None,
        enforcement_level: Optional[str] = None,
        reward_amount: Optional[Decimal] = None,
        rules_document_url: Optional[str] = None,
        is_active: Optional[bool] = None
    ) -> Optional[TEGPolicy]:
        """Update policy details"""
        import json
        policy = PolicyCRUD.get_policy_by_id(db, policy_id)
        if not policy:
            return None
            
        if policy_name is not None:
            policy.policy_name = policy_name
        if description is not None:
            policy.description = description
        if parameters is not None:
            policy.parameters = json.dumps(parameters)
        if enforcement_level is not None:
            policy.enforcement_level = enforcement_level
        if reward_amount is not None:
            policy.reward_amount = reward_amount
        if rules_document_url is not None:
            policy.rules_document_url = rules_document_url
        if is_active is not None:
            policy.is_active = is_active
            
        db.commit()
        db.refresh(policy)
        return policy


# Methods have been moved to their proper location in AVTPLogCRUD above


class TransactionCRUD:
    """CRUD operations for TEG transactions"""
    
    @staticmethod
    def create_transfer(
        db: Session,
        sender_id: str,
        receiver_id: str,
        amount: Decimal,
        fee_amount: Decimal = Decimal("0"),
        attached_message: Optional[str] = None
    ) -> TEGTransaction:
        """Create a new transfer transaction"""
        transaction = TEGTransaction(
            transaction_id=str(uuid4()),
            sender_agent_id=sender_id,
            receiver_agent_id=receiver_id,
            amount=amount,
            fee_amount=fee_amount,
            transaction_type="transfer",
            status=TransactionStatus.PENDING,
            attached_message=attached_message
        )
        db.add(transaction)
        db.commit()
        db.refresh(transaction)
        return transaction
    
    @staticmethod
    def create_issuance(
        db: Session,
        receiver_id: str,
        amount: Decimal
    ) -> TEGTransaction:
        """Create a new token issuance transaction"""
        transaction = TEGTransaction(
            transaction_id=str(uuid4()),
            sender_agent_id=None,  # No sender for issuance
            receiver_agent_id=receiver_id,
            amount=amount,
            fee_amount=Decimal("0"),
            transaction_type="issuance",
            status=TransactionStatus.PENDING
        )
        db.add(transaction)
        db.commit()
        db.refresh(transaction)
        return transaction
    
    @staticmethod
    def update_status(
        db: Session,
        transaction_id: str,
        status: TransactionStatus,
        error_message: Optional[str] = None
    ) -> TEGTransaction:
        """Update transaction status"""
        transaction = db.query(TEGTransaction).filter(
            TEGTransaction.transaction_id == transaction_id
        ).first()
        
        if transaction:
            transaction.status = status
            if error_message:
                transaction.error_message = error_message
            db.commit()
            db.refresh(transaction)
        
        return transaction
    
    @staticmethod
    def get_by_id(db: Session, transaction_id: str) -> Optional[TEGTransaction]:
        """Get transaction by ID"""
        return db.query(TEGTransaction).filter(
            TEGTransaction.transaction_id == transaction_id
        ).first()
    
    @staticmethod
    def get_agent_transactions(
        db: Session,
        agent_id: str,
        limit: int = 100,
        offset: int = 0,
        transaction_type: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> List[TEGTransaction]:
        """Get transactions for an agent with optional filtering.

        §2026-06-22 PERF: a single `or_(sender==X, receiver==X)` + ORDER BY timestamp DESC LIMIT
        DEFEATS the per-agent composite indexes — the planner falls back to a backward scan of
        ix_teg_transactions_timestamp across ALL agents, filtering for one, which exceeds
        statement_timeout (15s) once teg_transactions is large (12.7M rows) → /teg/transactions
        503s. Rewrite as a UNION of two index-friendly per-side subqueries: each hits its own
        (sender|receiver, timestamp) index and reads only `limit+offset` rows, then we merge +
        order + window. EXPLAIN-proven on the live 12.7M-row table: 745k-row backward scan →
        ~40 index reads. UNION (not UNION ALL) dedups any self-transfer (sender==receiver==X),
        matching the original OR semantics."""
        extra = []
        if transaction_type:
            extra.append(TEGTransaction.transaction_type == transaction_type)
        if start_date:
            extra.append(TEGTransaction.timestamp >= start_date)
        if end_date:
            extra.append(TEGTransaction.timestamp <= end_date)

        need = limit + offset  # each side must surface enough rows to cover the merged window
        sent_q = db.query(TEGTransaction).filter(
            TEGTransaction.sender_agent_id == agent_id, *extra
        ).order_by(desc(TEGTransaction.timestamp)).limit(need)
        recv_q = db.query(TEGTransaction).filter(
            TEGTransaction.receiver_agent_id == agent_id, *extra
        ).order_by(desc(TEGTransaction.timestamp)).limit(need)

        return sent_q.union(recv_q).order_by(
            desc(TEGTransaction.timestamp)
        ).limit(limit).offset(offset).all()
    
    @staticmethod
    def count_agent_transactions(
        db: Session,
        agent_id: str,
        transaction_type: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> int:
        """Count total transactions for an agent with optional filtering"""
        query = db.query(TEGTransaction).filter(
            or_(
                TEGTransaction.sender_agent_id == agent_id,
                TEGTransaction.receiver_agent_id == agent_id
            )
        )
        
        # Apply filters
        if transaction_type:
            query = query.filter(TEGTransaction.transaction_type == transaction_type)
        if start_date:
            query = query.filter(TEGTransaction.timestamp >= start_date)
        if end_date:
            query = query.filter(TEGTransaction.timestamp <= end_date)
        
        return query.count()


class SystemConfigCRUD:
    """CRUD operations for system configuration"""
    
    @staticmethod
    def get_value(db: Session, key: str, default: Optional[str] = None) -> Optional[str]:
        """Get configuration value by key"""
        config = db.query(SystemConfig).filter(
            SystemConfig.key == key
        ).first()
        return config.value if config else default
    
    @staticmethod
    def set_value(db: Session, key: str, value: str) -> SystemConfig:
        """Set configuration value"""
        config = db.query(SystemConfig).filter(
            SystemConfig.key == key
        ).first()
        
        if config:
            config.value = value
        else:
            config = SystemConfig(key=key, value=value)
            db.add(config)
        
        db.commit()
        db.refresh(config)
        return config
    
    @staticmethod
    def get_transfer_fee(db: Session) -> Decimal:
        """Get the current transfer fee amount"""
        fee_str = SystemConfigCRUD.get_value(db, "teg_transfer_fee", "0")
        return Decimal(fee_str)
    
    @staticmethod
    def get_fee_collection_address(db: Session) -> str:
        """Get the fee collection address"""
        return SystemConfigCRUD.get_value(db, "fee_collection_address", "teg:system:fee_collector")
    
    @staticmethod
    def get_treasury_did(db: Session) -> str:
        """Get the system treasury DID"""
        from ..core.config import get_settings
        settings = get_settings()
        # Try to get from database first, fallback to settings
        db_value = SystemConfigCRUD.get_value(db, "teg_system_treasury_did")
        return db_value if db_value else settings.teg_system_treasury_did
    
    @staticmethod
    def get_attestation_reward_amount(db: Session) -> Decimal:
        """Get the attestation submission reward amount"""
        reward_str = SystemConfigCRUD.get_value(db, "attestation_submission_reward", "10")
        return Decimal(reward_str)
    
    @staticmethod
    def get_attestation_policy_id(db: Session) -> Optional[str]:
        """Get the policy ID for attestation rewards"""
        return SystemConfigCRUD.get_value(db, "attestation_reward_policy_id")
    
    @staticmethod
    def get_proof_of_positive_balance_policy_id(db: Session) -> Optional[str]:
        """Get the policy ID for proof of positive balance attestations"""
        return SystemConfigCRUD.get_value(db, "proof_of_positive_balance_policy_id")


class TransferService:
    """High-level transfer operations with transaction safety
    
    This service implements atomic token transfers with proper validation
    and transaction logging. It ensures ACID properties for all financial
    operations in the TEG system.
    
    Key features:
    - Balance validation before transfer
    - Atomic updates to prevent race conditions
    - Transaction status tracking
    - Automatic rollback on failure
    - Automated auditor rule checks
    """
    
    @staticmethod
    def execute_transfer(
        db: Session,
        sender_id: str,
        receiver_id: str,
        amount: Decimal,
        fee_amount: Optional[Decimal] = None,
        attached_message: Optional[str] = None,
        entry_type: Optional[str] = "transfer",
    ) -> TEGTransaction:
        """
        Execute atomic token transfer with validation.
        
        This method ensures ACID properties for balance updates by:
        1. Creating a transaction record first (for audit trail)
        2. Validating sufficient balance
        3. Updating balances atomically
        4. Collecting fees if configured
        5. Committing or rolling back the entire operation
        
        Args:
            db: Database session
            sender_id: Sender agent DID
            receiver_id: Receiver agent DID
            amount: Amount to transfer (must be positive)
            fee_amount: Transaction fee (if None, uses system configured fee)
            attached_message: Optional message to attach to the transfer
            
        Returns:
            TEGTransaction: Completed transaction record
            
        Raises:
            ValueError: If sender has insufficient balance
            Exception: For any other database errors
            
        Note:
            The transaction record is created with PENDING status first,
            then updated to COMPLETED only after successful balance updates.
            This ensures proper audit trail even for failed transfers.
        """
        # Get fee amount from system config if not provided
        if fee_amount is None:
            fee_amount = SystemConfigCRUD.get_transfer_fee(db)
        
        # Create transaction record first
        transaction = TransactionCRUD.create_transfer(
            db, sender_id, receiver_id, amount, fee_amount, attached_message
        )
        _committed = False   # §2026-07-21 (F1): set True after the atomic commit below; the except uses it
        
        try:
            # Ensure both agents exist (flush only, no commit)
            AgentCRUD.get_or_create(db, sender_id)
            AgentCRUD.get_or_create(db, receiver_id)

            # §P3-T2 (2026-06-09): when a fee applies, include @fee_collector in the
            # up-front sorted lock set so every fee-bearing path locks {sender, receiver,
            # fee_collector} in ONE deterministic agent_id order. Previously fee_collector
            # was credited late/unlocked (below) → its row lock was taken out of order vs
            # concurrent paths (e.g. the cross-TEG credit leg) → deadlock-cycle on the
            # shared row. Δ-neutral — locking/ordering only.
            fee_collector_address = None
            if fee_amount > Decimal("0"):
                fee_collector_address = SystemConfigCRUD.get_fee_collection_address(db)
                AgentCRUD.get_or_create(db, fee_collector_address)

            # 2026-05-01: lock the mutated rows in a single query, ordered by agent_id ASC.
            # Without deterministic ordering, two concurrent transfers between the same
            # parties acquire row locks in opposite orders, deadlock-cycle, and one is
            # aborted by postgres after deadlock_timeout (lifetime counter on Frame A: 7510
            # deadlocks at the time of the original sender/receiver fix). Sorting the IDs
            # guarantees all transactions take locks in the same order ⇒ no cycle.
            _lock_ids = {sender_id, receiver_id}
            if fee_collector_address is not None:
                _lock_ids.add(fee_collector_address)
            ids_sorted = sorted(_lock_ids)
            locked_profiles = db.query(AgentTEGProfile).filter(
                AgentTEGProfile.agent_id.in_(ids_sorted)
            ).order_by(AgentTEGProfile.agent_id).with_for_update().all()
            profile_by_id = {p.agent_id: p for p in locked_profiles}
            sender = profile_by_id.get(sender_id)
            receiver = profile_by_id.get(receiver_id)

            # Layer 0: Audited balance integrity check — ALL parties, not just sender
            import os
            if os.getenv('AUDITED_BALANCE_ENABLED', 'true').lower() == 'true':
                for _check_id, _check_profile in [(sender_id, sender), (receiver_id, receiver)]:
                    if _check_profile.audited_balance is not None and _check_profile.token_balance != _check_profile.audited_balance:
                        raise ValueError(
                            f"Balance integrity check failed for {_check_id}: "
                            f"token_balance={_check_profile.token_balance} != audited_balance={_check_profile.audited_balance}. "
                            f"This indicates unauthorized balance modification. Contact administrator."
                        )

            # Validate sufficient balance
            total_deduction = amount + fee_amount
            if sender.token_balance < total_deduction:
                raise ValueError("Insufficient balance")

            # §2026-06-18: when the caller names an entry_type (e.g. AGORA exchange escrow
            # legs → 'exchange_order_refund'/'exchange_order_deposit'/…), tag this mutation so
            # the L1 journal records it (the AFTER trigger on this UPDATE reads the GUC in THIS
            # transaction), the L2 outbox emits kind=<entry_type> instead of 'unknown', and the
            # ES projection routes any non-mint/burn kind to transit_net → Δ-neutral. Identical
            # pattern to execute_issuance's 'mint' tag below; SET LOCAL is transaction-scoped so
            # it cannot leak onto a pooled connection.
            #
            # §MONEY-R18 (2026-09-04): the default was None, i.e. "unchanged for every
            # caller" — so the ORDINARY transfer path, the busiest money rail there is,
            # emitted kind='unknown'. MEASURED on the live EventStore: 4,661,352
            # LedgerBalanceChanged events carry kind='unknown', the single largest class,
            # still arriving today; 1,794,963 of them have net != 0 (single-sided legs,
            # which is by design — their counterparts sit in other buckets and Δ=0.0 is
            # independently verified).
            #
            # That is not a leak, it is a BLIND SPOT: everything untagged lands in
            # transit_net beside legitimate transfers, so an untagged mover that really
            # did create or destroy money would move transit_net and total_circulating
            # together and Δ would stay 0.0 — invisible, exactly like a dropped
            # TokensTransferred (PART 4).
            #
            # Δ BEHAVIOUR IS UNCHANGED by this default: materialized_balances.sql routes
            # 'mint'/'dispute_comp' to issued, 'slash'/'burn' to destroyed, and EVERYTHING
            # else — 'unknown' and 'transfer' alike — to transit_net. Only the label moves.
            # What it buys is that 'unknown' stops being the normal case, so a future
            # "unknown is a finding" alert can mean something.
            #
            # ⚠ The money plan's R18 also proposed "the outbox refuses a balance change
            # without an entry_type". Applied today that would REFUSE THE MAIN TRANSFER
            # PATH. Tag every legitimate mover first; refuse last.
            # ⚠ Consumer note: forensics.py:207 selects kind IN ('unknown','mixed'); it
            # will now return far fewer rows, which is the point.
            # Follow-up: per-call-site labels (the admin reward path at
            # endpoints_admin.py:1026 is a 'reward', not a plain 'transfer').
            # §MONEY-R18 follow-up (2026-09-04): coalesce HERE, not in the signature.
            # The first attempt only changed this function's default and it did
            # NOTHING — verified live: post-deploy events still read kind='unknown'.
            # EnhancedTransferService.execute_transfer carries its own
            # `entry_type: Optional[str] = None` and forwards it EXPLICITLY, and an
            # explicit None beats a callee default. Defaulting at the point of use
            # closes every path through this mover regardless of what any wrapper
            # above it defaults to.
            _entry_type = entry_type or "transfer"
            if _entry_type:
                # set_config() (function form) — NOT `SET LOCAL x = :p`; Postgres SET cannot
                # bind a parameter, but set_config(name, value, is_local=true) can. Same effect:
                # transaction-scoped GUC the L1 journal AFTER-trigger reads on the UPDATE below.
                db.execute(text("SELECT set_config('teg.entry_type', :et, true)"), {"et": _entry_type[:48]})

            # Update balances atomically
            # Using direct assignment ensures both updates happen in same transaction
            sender.token_balance -= total_deduction
            receiver.token_balance += amount

            # Credit the fee to the fee_collector row — already locked up front in the
            # sorted set above (§P3-T2), so no late/out-of-order lock here.
            fee_collector = None
            if fee_amount > Decimal("0"):
                fee_collector = profile_by_id.get(fee_collector_address)
                fee_collector.token_balance += fee_amount

            # Update audited balances to match (transfer is legitimate)
            sender.audited_balance = sender.token_balance
            receiver.audited_balance = receiver.token_balance
            if fee_collector is not None:
                fee_collector.audited_balance = fee_collector.token_balance

            # Mark transaction as completed
            transaction.status = TransactionStatus.COMPLETED

            db.commit()
            _committed = True   # §2026-07-21 (F1): money moved + COMPLETED committed atomically
            db.refresh(transaction)
            
            # Run automated auditor checks (non-blocking)
            try:
                from ..core.automated_auditor import AutomatedAuditorRules
                AutomatedAuditorRules.run_transfer_checks(db, transaction)
            except Exception:
                # Don't fail transfer if auditor checks fail
                pass
            
            return transaction
            
        except Exception as e:
            # §2026-07-21 (F1): a POST-commit error (e.g. db.refresh under the pool/lock convoy) must
            # NOT downgrade a money-moved, COMPLETED row to FAILED — a FAILED row drops out of
            # uq_teg_tx_exref_live (mig 0004 excludes FAILED) -> the worker retry re-executes the same
            # exref -> double-pay (confirmed frame-a escrow -57.36, double-refund of order 287194f7).
            if _committed:
                logging.getLogger(__name__).warning(
                    f"post-commit error on COMPLETED transfer {transaction.transaction_id}; "
                    f"keeping status COMPLETED (not downgrading to FAILED): {e}"
                )
                return transaction
            # Store transaction ID before rollback
            transaction_id = transaction.transaction_id
            # Rollback all changes including the transaction record
            db.rollback()
            # Mark transaction as failed for audit trail
            TransactionCRUD.update_status(
                db, 
                transaction_id,
                TransactionStatus.FAILED,
                str(e)
            )
            raise
    
    @staticmethod
    def execute_issuance(
        db: Session,
        receiver_id: str,
        amount: Decimal
    ) -> TEGTransaction:
        """Execute token issuance (minting)"""
        # Create transaction record
        transaction = TransactionCRUD.create_issuance(db, receiver_id, amount)
        _committed = False   # §2026-07-21 (F1): set True after the atomic commit below
        
        try:
            # Update receiver balance
            receiver = AgentCRUD.get_or_create(db, receiver_id)
            # §B (2026-05-30): tag this mutation as a genuine MINT so the L1 journal records
            # entry_type='mint' (same transaction → the AFTER trigger reads the GUC), the L2
            # outbox emits kind='mint', and the ES projection books it into tokens_issued — not
            # transit_net. SET LOCAL is transaction-scoped, so it cannot leak onto a pooled
            # connection's next operation. Issuance is the only genuine mint primitive.
            db.execute(text("SET LOCAL teg.entry_type = 'mint'"))
            receiver.token_balance += amount
            # Minting authority: both columns update together (minting IS the source event)
            receiver.audited_balance = receiver.token_balance

            # Mark transaction as completed
            transaction.status = TransactionStatus.COMPLETED

            db.commit()
            _committed = True   # §2026-07-21 (F1): money moved + COMPLETED committed atomically
            db.refresh(transaction)

            return transaction

        except Exception as e:
            # §2026-07-21 (F1): don't downgrade a COMPLETED mint to FAILED on a post-commit error.
            if _committed:
                logging.getLogger(__name__).warning(
                    f"post-commit error on COMPLETED issuance {transaction.transaction_id}; "
                    f"keeping status COMPLETED: {e}"
                )
                return transaction
            db.rollback()
            # Mark transaction as failed
            TransactionCRUD.update_status(
                db,
                transaction.transaction_id,
                TransactionStatus.FAILED,
                str(e)
            )
            raise


class AttestationCRUD:
    """CRUD operations for attestation logs
    
    Manages attestation submissions which are self-reported claims by agents.
    Attestations are rewarded with AVT tokens to incentivize participation.
    Duplicate attestations are prevented using a unique constraint.
    """
    model = TEGAttestationLog  # Add model attribute for consistency
    
    @staticmethod
    def create_submission(
        db: Session,
        agent_did: str,
        attestation_type: str,
        attestation_hash: str,
        storage_pointer: str,
        submitted_at: Optional[datetime] = None,
        circuit_id: Optional[str] = None,
        zkp_public_inputs_json: Optional[str] = None,
        zkp_proof_value: Optional[str] = None,
        policy_id: Optional[str] = None
    ) -> TEGAttestationLog:
        """Create a new attestation submission"""
        submission = TEGAttestationLog(
            submission_id=str(uuid4()),
            agent_did=agent_did,
            attestation_type=attestation_type,
            attestation_hash=attestation_hash,
            storage_pointer=storage_pointer,
            submitted_at=submitted_at or datetime.now(timezone.utc),
            status="logged",
            circuit_id=circuit_id,
            zkp_public_inputs_json=zkp_public_inputs_json,
            zkp_proof_value=zkp_proof_value,
            policy_id=policy_id
        )
        db.add(submission)
        try:
            db.commit()
            db.refresh(submission)
            return submission
        except IntegrityError:
            # Unique constraint violation - attestation already exists
            db.rollback()
            raise ValueError("Duplicate attestation submission")
    
    @staticmethod
    def get_by_agent(
        db: Session,
        agent_did: str,
        limit: int = 100,
        offset: int = 0
    ) -> List[TEGAttestationLog]:
        """Get attestations for an agent"""
        return db.query(TEGAttestationLog).filter(
            TEGAttestationLog.agent_did == agent_did
        ).order_by(
            desc(TEGAttestationLog.submitted_at)
        ).limit(limit).offset(offset).all()
    
    @staticmethod
    def count_successful_zkp_attestations(
        db: Session,
        agent_did: str
    ) -> int:
        """Count successful ZKP attestations for an agent"""
        return db.query(TEGAttestationLog).filter(
            and_(
                TEGAttestationLog.agent_did == agent_did,
                TEGAttestationLog.attestation_type.like("%_ZKP_v%"),
                TEGAttestationLog.status == "zkp_verified_true"
            )
        ).count()
    
    @staticmethod
    def count_failed_zkp_attestations(
        db: Session,
        agent_did: str
    ) -> int:
        """Count failed ZKP attestations for an agent"""
        return db.query(TEGAttestationLog).filter(
            and_(
                TEGAttestationLog.agent_did == agent_did,
                TEGAttestationLog.attestation_type.like("%_ZKP_v%"),
                TEGAttestationLog.status == "zkp_verified_false"
            )
        ).count()


class AuditorFlagCRUD:
    """CRUD operations for auditor flags"""
    
    @staticmethod
    def create_flag(
        db: Session,
        flagged_agent_did: str,
        rule_violated_code: str,
        flag_reason: str,
        flag_type: str,
        severity: FlagSeverity,
        flagged_by: str,
        status: FlagStatus = FlagStatus.NEW_MANUAL_REVIEW,
        related_agent_id: Optional[str] = None,
        related_avtp_transaction_id: Optional[str] = None,
        related_attestation_id: Optional[str] = None,
        related_transaction_id: Optional[str] = None,
        details: Optional[str] = None
    ) -> AuditorFlagLog:
        """Create a new auditor flag"""
        flag = AuditorFlagLog(
            flag_id=str(uuid4()),
            flagged_agent_did=flagged_agent_did,
            rule_violated_code=rule_violated_code,
            flag_reason=flag_reason,
            flag_type=flag_type,
            severity=severity,
            related_agent_id=related_agent_id,
            related_avtp_transaction_id=related_avtp_transaction_id,
            related_attestation_id=related_attestation_id,
            related_transaction_id=related_transaction_id,
            details=details,
            status=status,
            flagged_by=flagged_by
        )
        db.add(flag)
        db.commit()
        db.refresh(flag)
        
        # ARCHITECTURAL INTEGRITY: Trigger reputation adjustment for HIGH or CRITICAL severity flags
        if severity in [FlagSeverity.HIGH, FlagSeverity.CRITICAL]:
            try:
                # Get the agent's current reputation
                agent = AgentCRUD.get_or_create(db, flagged_agent_did)
                current_reputation = agent.reputation_score
                
                # Apply reputation penalty based on severity
                reputation_penalty = 0
                if severity == FlagSeverity.HIGH:
                    reputation_penalty = 50  # -50 points for HIGH severity
                elif severity == FlagSeverity.CRITICAL:
                    reputation_penalty = 200  # -200 points for CRITICAL severity
                
                # Update reputation score (minimum 0)
                new_reputation = max(0, current_reputation - reputation_penalty)
                ReputationService.update_reputation(db, flagged_agent_did, new_reputation)
                
                # Log the reputation adjustment in flag details
                adjustment_info = f"\n\nREPUTATION ADJUSTMENT: -{reputation_penalty} points (from {current_reputation} to {new_reputation})"
                if flag.details:
                    flag.details += adjustment_info
                else:
                    flag.details = adjustment_info.strip()
                db.commit()
                
            except Exception as e:
                # Don't fail flag creation if reputation update fails
                # Just log the error (in production)
                pass
        
        return flag
    
    @staticmethod
    def get_flags(
        db: Session,
        agent_did: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> tuple[List[AuditorFlagLog], int]:
        """Get auditor flags with filtering"""
        query = db.query(AuditorFlagLog)
        
        if agent_did:
            query = query.filter(AuditorFlagLog.flagged_agent_did == agent_did)
        if status:
            query = query.filter(AuditorFlagLog.status == status)
        
        total = query.count()
        flags = query.order_by(
            desc(AuditorFlagLog.timestamp)
        ).limit(limit).offset(offset).all()
        
        return flags, total
    
    @staticmethod
    def update_status(
        db: Session,
        flag_id: str,
        new_status: FlagStatus,
        resolution_notes: Optional[str] = None
    ) -> Optional[AuditorFlagLog]:
        """Update flag status"""
        flag = db.query(AuditorFlagLog).filter(
            AuditorFlagLog.flag_id == flag_id
        ).first()
        
        if flag:
            flag.status = new_status
            if resolution_notes and flag.details:
                # Append resolution notes to details
                flag.details = f"{flag.details}\n\nRESOLUTION: {resolution_notes}"
            elif resolution_notes:
                flag.details = f"RESOLUTION: {resolution_notes}"
            db.commit()
            db.refresh(flag)
        
        return flag
    
    @staticmethod
    def update_flag_with_admin_notes(
        db: Session,
        flag_id: str,
        new_status: FlagStatus,
        admin_notes: Optional[str] = None
    ) -> Optional[AuditorFlagLog]:
        """Update flag status with admin notes"""
        flag = db.query(AuditorFlagLog).filter(
            AuditorFlagLog.flag_id == flag_id
        ).first()
        
        if flag:
            old_status = flag.status
            flag.status = new_status
            if admin_notes:
                if flag.details:
                    flag.details = f"{flag.details}\n\nADMIN NOTES: {admin_notes}"
                else:
                    flag.details = f"ADMIN NOTES: {admin_notes}"
            db.commit()
            db.refresh(flag)
            return flag
        
        return None
    
    @staticmethod
    def bulk_update_status(
        db: Session,
        flag_ids: List[str],
        new_status: FlagStatus,
        admin_notes: Optional[str] = None
    ) -> int:
        """Bulk update flag statuses"""
        updated_count = 0
        for flag_id in flag_ids:
            flag = AuditorFlagCRUD.update_flag_with_admin_notes(
                db, flag_id, new_status, admin_notes
            )
            if flag:
                updated_count += 1
        return updated_count
    
    @staticmethod
    def escalate_flag(
        db: Session,
        flag_id: str,
        new_severity: FlagSeverity,
        escalation_reason: str
    ) -> Optional[AuditorFlagLog]:
        """Escalate flag severity"""
        flag = db.query(AuditorFlagLog).filter(
            AuditorFlagLog.flag_id == flag_id
        ).first()
        
        if flag:
            old_severity = flag.severity
            flag.severity = new_severity
            
            # Add escalation info to details
            escalation_info = f"\n\nESCALATION: Severity changed from {old_severity.value} to {new_severity.value}\nReason: {escalation_reason}"
            if flag.details:
                flag.details += escalation_info
            else:
                flag.details = escalation_info.strip()
            
            # Apply additional reputation penalty for escalation to CRITICAL
            if new_severity == FlagSeverity.CRITICAL and old_severity != FlagSeverity.CRITICAL:
                try:
                    agent = AgentCRUD.get_or_create(db, flag.flagged_agent_did)
                    current_reputation = agent.reputation_score
                    reputation_penalty = 100  # Additional penalty for escalation
                    new_reputation = max(0, current_reputation - reputation_penalty)
                    ReputationService.update_reputation(db, flag.flagged_agent_did, new_reputation)
                    
                    flag.details += f"\nREPUTATION ADJUSTMENT: Additional -{reputation_penalty} points for escalation (from {current_reputation} to {new_reputation})"
                except Exception:
                    pass
            
            db.commit()
            db.refresh(flag)
            return flag
        
        return None
    
    @staticmethod
    def get_flag_by_id(db: Session, flag_id: str) -> Optional[AuditorFlagLog]:
        """Get flag by ID"""
        return db.query(AuditorFlagLog).filter(
            AuditorFlagLog.flag_id == flag_id
        ).first()
    
    @staticmethod
    def count_critical_flags(
        db: Session,
        agent_did: str
    ) -> int:
        """Count critical flags for an agent
        
        Counts flags where:
        - Status is resolved_action_taken_critical_flag (manual confirmation)
        - OR status is auto_flagged_manual_review AND severity is high
        """
        return db.query(AuditorFlagLog).filter(
            and_(
                AuditorFlagLog.flagged_agent_did == agent_did,
                or_(
                    AuditorFlagLog.status == FlagStatus.RESOLVED_ACTION_TAKEN_CRITICAL_FLAG,
                    and_(
                        AuditorFlagLog.status == FlagStatus.AUTO_FLAGGED_MANUAL_REVIEW,
                        AuditorFlagLog.severity == FlagSeverity.HIGH
                    )
                )
            )
        ).count()
    
    @staticmethod
    def get_flags_for_filtering(
        db: Session,
        severity: Optional[FlagSeverity] = None,
        flag_type: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> tuple[List[AuditorFlagLog], int]:
        """Get flags with advanced filtering"""
        query = db.query(AuditorFlagLog)
        
        if severity:
            query = query.filter(AuditorFlagLog.severity == severity)
        if flag_type:
            query = query.filter(AuditorFlagLog.flag_type == flag_type)
        
        total = query.count()
        flags = query.order_by(
            desc(AuditorFlagLog.timestamp)
        ).limit(limit).offset(offset).all()
        
        return flags, total


class DisputeCRUD:
    """CRUD operations for disputes
    
    Manages dispute logs between agents. Disputes follow a simple
    logging model in MVP, with manual review and resolution.
    Future versions may implement automated resolution mechanisms.
    """
    model = TEGDisputeLog  # Add model attribute for consistency with other CRUD classes
    
    @staticmethod
    def create_dispute(
        db: Session,
        claimant_agent_did: str,
        defendant_agent_did: str,
        reason_code: str,
        brief_description: str,
        avtp_transaction_id: Optional[str] = None,
        evidence_pointer: Optional[str] = None,
        dispute_reason_category: Optional[str] = None,
        related_transaction_id: Optional[str] = None,
        evidence_description_or_url: Optional[str] = None
    ) -> TEGDisputeLog:
        """Create a new dispute log"""
        dispute = TEGDisputeLog(
            dispute_log_id=str(uuid4()),
            claimant_agent_did=claimant_agent_did,
            defendant_agent_did=defendant_agent_did,
            avtp_transaction_id=avtp_transaction_id,
            reason_code=reason_code,
            brief_description=brief_description,
            evidence_pointer=evidence_pointer,
            status=DisputeStatus.OPEN,  # OWL-FIX 2026-03-07: LOGGED_MANUAL_REVIEW not in DB enum, use OPEN
            dispute_reason_category=dispute_reason_category,
            related_transaction_id=related_transaction_id,
            evidence_description_or_url=evidence_description_or_url
        )
        db.add(dispute)
        db.commit()
        db.refresh(dispute)
        return dispute
    
    @staticmethod
    def get_disputes_by_agent(
        db: Session,
        agent_did: str,
        as_claimant: bool = True,
        limit: int = 100,
        offset: int = 0
    ) -> List[TEGDisputeLog]:
        """Get disputes involving an agent"""
        if as_claimant:
            filter_condition = TEGDisputeLog.claimant_agent_did == agent_did
        else:
            filter_condition = TEGDisputeLog.defendant_agent_did == agent_did
        
        return db.query(TEGDisputeLog).filter(
            filter_condition
        ).order_by(
            desc(TEGDisputeLog.created_at)
        ).limit(limit).offset(offset).all()
    
    @staticmethod
    def get_dispute_by_id(
        db: Session,
        dispute_log_id: str
    ) -> Optional[TEGDisputeLog]:
        """Get dispute by ID"""
        return db.query(TEGDisputeLog).filter(
            TEGDisputeLog.dispute_log_id == dispute_log_id
        ).first()
    
    @staticmethod
    def update_status(
        db: Session,
        dispute_log_id: str,
        new_status: DisputeStatus,
        resolution_notes: Optional[str] = None,
        admin_reviewer_id: Optional[str] = None
    ) -> Optional[TEGDisputeLog]:
        """Update dispute status"""
        dispute = db.query(TEGDisputeLog).filter(
            TEGDisputeLog.dispute_log_id == dispute_log_id
        ).first()
        
        if dispute:
            dispute.status = new_status
            if resolution_notes:
                dispute.resolution_notes = resolution_notes
            if admin_reviewer_id:
                dispute.admin_reviewer_id = admin_reviewer_id
            db.commit()
            db.refresh(dispute)
        
        return dispute


class ReputationService:
    """Service for reputation-related operations
    
    Provides high-level operations for reputation management.
    The actual calculation logic is in reputation_logic.py,
    while this service handles database operations.
    """
    
    @staticmethod
    def get_reputation(
        db: Session,
        agent_id: str
    ) -> tuple[int, Optional[datetime]]:
        """Get agent's reputation score and last update time"""
        agent = AgentCRUD.get_or_create(db, agent_id)
        return agent.reputation_score, agent.last_reputation_update
    
    @staticmethod
    def update_reputation(
        db: Session,
        agent_id: str,
        new_score: int
    ) -> AgentTEGProfile:
        """Update agent's reputation score"""
        agent = AgentCRUD.get_or_create(db, agent_id)
        agent.reputation_score = new_score
        agent.last_reputation_update = datetime.now(timezone.utc)
        db.add(agent)  # Ensure agent is added to session
        db.commit()
        db.refresh(agent)
        return agent

    @staticmethod
    def apply_signal(
        db: Session,
        transaction_id: str,
        receiver_agent_id: str,
        signal_value: int,
        *,
        cap: Optional[int] = None,
    ) -> int:
        """§TRUSTCHAIN (2026-09-12) — the ONE implementation of "apply a reputation signal".

        Three handlers used to do this by hand (endpoints_token, endpoints_token_jwt_svid,
        endpoints_reputation_signal): read the score into Python, add, write it back ABSOLUTELY,
        and check `reputation_signal_applied` in Python before the write. Two callers in flight
        for one receiver both read N and both wrote N+1 — MEASURED 2026-09-10: 9 of 764
        concurrent signals lost, every one answering 200 "applied" with somebody else's number.
        The registry's twin (`record_interaction`) had the same defect and was fixed the same day;
        this is the TEG half.

        Two statements, ONE transaction, no Python arithmetic:

          1. THE CLAIM — `UPDATE teg_transactions SET reputation_signal_applied = TRUE
             WHERE transaction_id = :tx AND reputation_signal_applied IS NOT TRUE`.
             Zero rows means somebody already claimed it (the check the handlers still run in
             Python is a fast path; this is the truth, because a read cannot see a concurrent
             writer and a row lock can). `IS NOT TRUE` covers the column's NULL default.
          2. THE SCORE — `UPDATE agent_teg_profiles SET reputation_score = GREATEST(0,
             reputation_score + :v) ... RETURNING reputation_score`. The database adds under the
             row lock, and RETURNING is the caller's real answer: its OWN increment, never a
             re-read that may already carry the next caller's.

        `cap` keeps the bare service-token route's historical `min(100, ...)` clamp without a
        second copy of the arithmetic; the token routes pass none (rows above 100 exist and were
        produced by them). The receiver profile is ensured FIRST and outside the claim, because
        `AgentCRUD.get_or_create` commits on its own connection when it creates (§FRAMELIC row 152)
        and a create that failed after the claim would strand a signal nobody can re-apply.

        Raises `ReputationSignalAlreadyApplied` when the claim finds nothing to claim; the caller
        maps it to its own status (400 on the token routes, 409 on the service-token route) so no
        wire shape changes. Never touches a balance column.
        """
        if signal_value not in (-1, 1):
            raise ValueError("signal_value must be +1 or -1")
        AgentCRUD.get_or_create(db, receiver_agent_id)
        claimed = db.execute(
            text(
                "UPDATE teg_transactions SET reputation_signal_applied = TRUE "
                "WHERE transaction_id = :tx AND reputation_signal_applied IS NOT TRUE"
            ),
            {"tx": transaction_id},
        )
        if claimed.rowcount != 1:
            db.rollback()
            raise ReputationSignalAlreadyApplied(transaction_id)
        expr = "GREATEST(0, reputation_score + :v)"
        params = {"v": int(signal_value), "a": receiver_agent_id, "now": datetime.now(timezone.utc)}
        if cap is not None:
            expr = f"LEAST(:cap, {expr})"
            params["cap"] = int(cap)
        row = db.execute(
            text(
                f"UPDATE agent_teg_profiles SET reputation_score = {expr}, "
                "last_reputation_update = :now WHERE agent_id = :a RETURNING reputation_score"
            ),
            params,
        ).fetchone()
        if row is None:
            db.rollback()
            raise LookupError(f"no TEG profile for receiver {receiver_agent_id}")
        db.commit()
        return int(row[0])


class ReputationSignalAlreadyApplied(Exception):
    """The transaction already carries a reputation signal (the atomic claim found nothing to claim)."""

    def __init__(self, transaction_id: str):
        super().__init__(f"Reputation signal already applied to transaction {transaction_id}")
        self.transaction_id = transaction_id


def _bootstrap_marker(token_value: str) -> str:
    """D6-809 (2026-10-17): what bootstrap_tokens.token_value holds for a token: "sha256:<hex>", its SHA-256, never the
    token. The token itself exists only in the response that hands it out (the registry's rule, D6-283)."""
    return "sha256:" + hashlib.sha256(token_value.encode("utf-8")).hexdigest()


class BootstrapTokenCRUD:
    """CRUD operations for bootstrap tokens used in self-onboarding
    
    Manages single-use bootstrap tokens that allow new agents to
    self-register with the system. Tokens have expiration times
    and can only be used once.

    D6-809: a row stores the token's hash (_bootstrap_marker), never the token, and a presented token is found by its
    hash. Read 2026-10-17 on all eleven TEG databases: no row at all, so no row ever held a token to scrub.
    """
    
    @staticmethod
    def create_bootstrap_token(
        db: Session,
        token_value: str,
        expires_at: datetime,
        agent_type_hint: Optional[str] = None,
        requested_by: Optional[str] = None
    ) -> BootstrapToken:
        """Create a new bootstrap token
        
        Args:
            db: Database session
            token_value: The token string (e.g., "bst_a1b2c3d4e5f67890_xxxxxxxxxxxx"); only its hash is stored
            expires_at: When the token expires
            agent_type_hint: Optional hint about the type of agent being created
            requested_by: Optional identifier of who requested the token
            
        Returns:
            BootstrapToken: The created token record
            
        Raises:
            IntegrityError: If a token with the same value already exists
        """
        token = BootstrapToken(
            token_id=str(uuid4()),
            token_value=_bootstrap_marker(token_value),
            expires_at=expires_at,
            agent_type_hint=agent_type_hint,
            requested_by=requested_by,
            is_used=False
        )
        db.add(token)
        try:
            db.commit()
            db.refresh(token)
            return token
        except IntegrityError:
            db.rollback()
            raise ValueError("A bootstrap token with this value already exists")
    
    @staticmethod
    def get_active_bootstrap_token_by_value(
        db: Session,
        token_value: str
    ) -> Optional[BootstrapToken]:
        """Get an active (not used, not expired) bootstrap token by its value
        
        Args:
            db: Database session
            token_value: The token string to look up
            
        Returns:
            BootstrapToken if found and valid, None otherwise
        """
        marker = _bootstrap_marker(token_value)
        token = db.query(BootstrapToken).filter(
            and_(
                BootstrapToken.token_value == marker,
                BootstrapToken.is_used == False,
                BootstrapToken.expires_at > datetime.now(timezone.utc)
            )
        ).first()
        # the hash found the row; confirm it in constant time (the registry's lookup does the same)
        if token is not None and not secrets.compare_digest(str(token.token_value), marker):
            return None
        return token
    
    @staticmethod
    def mark_bootstrap_token_as_used(
        db: Session,
        token_id: str,
        used_by_agent_did: str
    ) -> BootstrapToken:
        """Mark a bootstrap token as used
        
        Args:
            db: Database session
            token_id: The token ID (not the token value)
            used_by_agent_did: The DID of the agent that used this token
            
        Returns:
            BootstrapToken: The updated token record
            
        Raises:
            ValueError: If token not found
        """
        token = db.query(BootstrapToken).filter(
            BootstrapToken.token_id == token_id
        ).first()
        
        if not token:
            raise ValueError(f"Bootstrap token with ID '{token_id}' not found")
        
        token.is_used = True
        token.used_at = datetime.now(timezone.utc)
        token.used_by_agent_did = used_by_agent_did
        
        db.commit()
        db.refresh(token)
        return token
    
    @staticmethod
    def cleanup_expired_tokens(db: Session) -> int:
        """Delete expired unused tokens (housekeeping)
        
        Args:
            db: Database session
            
        Returns:
            int: Number of tokens deleted
        """
        result = db.query(BootstrapToken).filter(
            and_(
                BootstrapToken.is_used == False,
                BootstrapToken.expires_at < datetime.now(timezone.utc)
            )
        ).delete()
        db.commit()
        return result


class StakingCRUD:
    """CRUD operations for staking and delegation
    
    Manages staking operations including creating stakes, unstaking,
    delegation management, and reward distribution.
    """
    
    @staticmethod
    def create_stake(
        db: Session,
        agent_id: str,
        amount: Decimal
    ) -> Stake:
        """Create a new stake by locking agent's tokens
        
        This method atomically:
        1. Validates the agent has sufficient balance
        2. Deducts the amount from the agent's balance
        3. Creates a new stake record
        
        Args:
            db: Database session
            agent_id: Agent DID who is staking
            amount: Amount of AVT to stake
            
        Returns:
            Stake: The created stake record
            
        Raises:
            ValueError: If agent has insufficient balance
        """
        # Get agent and validate balance
        agent = AgentCRUD.get_or_create(db, agent_id)
        if agent.token_balance < amount:
            raise ValueError(f"Insufficient balance. Available: {agent.token_balance}, Requested: {amount}")
        
        # Deduct from agent's balance
        agent.token_balance -= amount
        # Keep audited_balance in sync (staking is legitimate)
        agent.audited_balance = agent.token_balance

        # Create stake record
        stake = Stake(
            stake_id=str(uuid4()),
            agent_id=agent_id,
            amount=amount,
            is_active=True
        )
        
        db.add(stake)
        db.commit()
        db.refresh(stake)
        return stake
    
    @staticmethod
    def unstake(
        db: Session,
        stake_id: str,
        agent_id: str
    ) -> tuple[Stake, Decimal]:
        """Unstake tokens and return them to the agent
        
        This method:
        1. Validates the stake belongs to the agent
        2. Marks the stake as inactive
        3. Returns the staked amount to the agent's balance
        4. Returns any pending rewards
        
        Args:
            db: Database session
            stake_id: ID of the stake to unlock
            agent_id: Agent DID requesting unstake (for validation)
            
        Returns:
            tuple: (Updated stake record, total amount returned)
            
        Raises:
            ValueError: If stake not found or doesn't belong to agent
        """
        # Get stake and validate ownership
        stake = db.query(Stake).filter(
            Stake.stake_id == stake_id
        ).first()
        
        if not stake:
            raise ValueError(f"Lock position {stake_id} not found")
        if stake.agent_id != agent_id:
            raise ValueError(f"Lock position {stake_id} does not belong to agent {agent_id}")
        if not stake.is_active:
            raise ValueError(f"Lock position {stake_id} is already unlocked")
        
        # Calculate any pending rewards
        pending_rewards = StakingCRUD.calculate_pending_rewards(db, stake_id)
        
        # Return staked amount plus rewards to agent
        agent = AgentCRUD.get_or_create(db, agent_id)
        total_return = stake.amount + pending_rewards
        agent.token_balance += total_return
        # Keep audited_balance in sync (unstaking is legitimate)
        agent.audited_balance = agent.token_balance
        
        # Mark stake as inactive
        stake.is_active = False
        stake.unstaked_at = datetime.now(timezone.utc)
        
        db.commit()
        db.refresh(stake)
        return stake, total_return
    
    @staticmethod
    def get_agent_stakes(
        db: Session,
        agent_id: str,
        active_only: bool = True
    ) -> List[Stake]:
        """Get all stakes for an agent"""
        query = db.query(Stake).filter(
            Stake.agent_id == agent_id
        )
        
        if active_only:
            query = query.filter(Stake.is_active == True)
        
        return query.order_by(desc(Stake.staked_at)).all()
    
    @staticmethod
    def get_total_staked(
        db: Session,
        agent_id: Optional[str] = None
    ) -> Decimal:
        """Get total staked amount (for specific agent or entire system)"""
        query = db.query(func.sum(Stake.amount)).filter(
            Stake.is_active == True
        )
        
        if agent_id:
            query = query.filter(Stake.agent_id == agent_id)
        
        result = query.scalar()
        return result if result else Decimal("0")
    
    @staticmethod
    def calculate_pending_rewards(
        db: Session,
        stake_id: str
    ) -> Decimal:
        """Pending rewards for a stake. Always Decimal("0"), deliberately.

        §MONEY-R31 (2026-09-04) — the previous docstring read "For MVP, returns 0.
        In production, would calculate based on time staked / reward rate /
        delegation status", which reads as an invitation. Measured reachability
        before rewriting it:

          * the only caller is StakingCRUD.unstake
          * whose only route is endpoints_governance.py::unstake_tokens
          * which sits behind _retired_rail_guard() since §MONEY-R30 and answers
            404 unless TEG_RETIRED_RAILS=true (verified live on frame-a)

        So this is dead code behind a retired rail. That matters because of HOW
        its caller pays out: `agent.token_balance += stake.amount + pending`, a
        direct ORM credit. A non-zero return here would create supply from
        nothing on an untagged write — the ⚠M3 class the invariant cannot see
        (§MONEY-R18). Rewards are distributed by the admin-triggered
        distribution rail, which is funded from fee_collector/treasury and
        emits its events.

        If staking rewards are ever wanted here, they go through the funded
        rail, not through this return value.
        """
        return Decimal("0")
    
    @staticmethod
    def distribute_staking_rewards(
        db: Session,
        reward_percentage: Decimal = Decimal("5.0"),
        admin_id: Optional[str] = None
    ) -> tuple[int, Decimal]:
        """Distribute rewards to all active stakers
        
        This method:
        1. Calculates total staked amount
        2. Determines reward pool (percentage of total staked)
        3. Distributes proportionally to all stakers
        4. Credits rewards directly to agent balances
        
        Args:
            db: Database session
            reward_percentage: Percentage of total stake to distribute as rewards
            admin_id: Admin who triggered the distribution (for audit)
            
        Returns:
            tuple: (Number of stakers rewarded, Total rewards distributed)
        """
        # Get all active stakes
        active_stakes = db.query(Stake).filter(
            Stake.is_active == True
        ).all()
        
        if not active_stakes:
            return 0, Decimal("0")
        
        # Calculate total staked and reward pool
        total_staked = sum(stake.amount for stake in active_stakes)
        total_rewards = (total_staked * reward_percentage) / Decimal("100")
        
        # Generate a reward cycle ID for this distribution
        reward_cycle_id = str(uuid4())
        
        # Distribute proportionally
        stakers_rewarded = 0
        total_distributed = Decimal("0")
        
        for stake in active_stakes:
            # Calculate this stake's share of rewards
            stake_percentage = stake.amount / total_staked
            reward_amount = total_rewards * stake_percentage
            
            if reward_amount > Decimal("0"):
                # Credit reward to agent's balance
                agent = AgentCRUD.get_or_create(db, stake.agent_id)
                agent.token_balance += reward_amount
                # Keep audited_balance in sync (staking reward is legitimate)
                agent.audited_balance = agent.token_balance
                
                # Record the distribution
                distribution = StakingRewardDistribution(
                    distribution_id=str(uuid4()),
                    stake_id=stake.stake_id,
                    agent_id=stake.agent_id,
                    amount=reward_amount,
                    reward_type="staking",
                    reward_cycle_id=reward_cycle_id
                )
                db.add(distribution)
                
                # Update stake's last reward claim
                stake.last_reward_claim = datetime.now(timezone.utc)
                
                stakers_rewarded += 1
                total_distributed += reward_amount
        
        db.commit()
        return stakers_rewarded, total_distributed
    
    @staticmethod
    def create_delegation(
        db: Session,
        stake_id: str,
        delegator_agent_id: str,
        validator_agent_id: str,
        amount: Optional[Decimal] = None,
        reward_share_percentage: Decimal = Decimal("10.0")
    ) -> Delegation:
        """Create a delegation from a stake to a validator
        
        Args:
            db: Database session
            stake_id: ID of the stake to delegate
            delegator_agent_id: Agent who owns the stake
            validator_agent_id: Agent to delegate to
            amount: Amount to delegate (None = entire stake)
            reward_share_percentage: Percentage of rewards to share with validator
            
        Returns:
            Delegation: The created delegation record
            
        Raises:
            ValueError: If stake not found or validation fails
        """
        # Get stake and validate
        stake = db.query(Stake).filter(
            Stake.stake_id == stake_id
        ).first()
        
        if not stake:
            raise ValueError(f"Lock position {stake_id} not found")
        if stake.agent_id != delegator_agent_id:
            raise ValueError(f"Lock position {stake_id} does not belong to agent {delegator_agent_id}")
        if not stake.is_active:
            raise ValueError("Cannot delegate an inactive lock position")
        
        # Default to full stake amount if not specified
        if amount is None:
            amount = stake.amount
        elif amount > stake.amount:
            raise ValueError("Cannot delegate more than the locked amount")
        
        # Check for existing active delegation
        existing = db.query(Delegation).filter(
            and_(
                Delegation.stake_id == stake_id,
                Delegation.is_active == True
            )
        ).first()
        
        if existing:
            raise ValueError(f"Lock position {stake_id} is already delegated")
        
        # Create delegation
        delegation = Delegation(
            delegation_id=str(uuid4()),
            delegator_agent_id=delegator_agent_id,
            validator_agent_id=validator_agent_id,
            stake_id=stake_id,
            delegated_amount=amount,
            reward_share_percentage=reward_share_percentage,
            is_active=True
        )
        
        db.add(delegation)
        db.commit()
        db.refresh(delegation)
        return delegation
    
    @staticmethod
    def get_stake_by_id(
        db: Session,
        stake_id: str
    ) -> Optional[Stake]:
        """Get a stake by its ID"""
        return db.query(Stake).filter(
            Stake.stake_id == stake_id
        ).first()
