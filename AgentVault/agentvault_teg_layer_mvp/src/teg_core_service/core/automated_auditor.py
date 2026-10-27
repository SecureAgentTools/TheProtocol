"""Automated auditor rules for detecting suspicious activities

This module implements rudimentary rule-based checks that automatically
generate auditor flags for suspicious activities in the TEG system.
These are simple threshold-based rules for the MVP.
"""
import json
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any

from sqlalchemy.orm import Session
from sqlalchemy import func

from ..database.models import (
    TEGTransaction, AgentTEGProfile, AuditorFlagLog,
    FlagSeverity, FlagStatus, DisputeStatus
)
from ..database.crud import (
    AuditorFlagCRUD, TransactionCRUD, DisputeCRUD,
    ReputationService, AttestationCRUD
)


class AutomatedAuditorRules:
    """Automated rules for generating auditor flags"""
    
    # Configuration thresholds (these could be moved to system config)
    HIGH_VOLUME_THRESHOLD = Decimal("10000")  # TEG tokens
    HIGH_FREQUENCY_THRESHOLD = 10  # transactions per hour
    LARGE_TRANSFER_THRESHOLD = Decimal("50000")  # TEG tokens
    REPUTATION_DROP_THRESHOLD = -20  # points
    NEW_AGENT_DAYS = 7  # days
    
    @staticmethod
    def check_high_volume_velocity(
        db: Session,
        agent_id: str,
        transaction: Optional[TEGTransaction] = None
    ) -> Optional[AuditorFlagLog]:
        """Check for unusually high transaction volume in short time"""
        # Look at transactions in the last hour
        one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
        
        recent_txs = db.query(TEGTransaction).filter(
            TEGTransaction.sender_agent_id == agent_id,
            TEGTransaction.timestamp >= one_hour_ago,
            TEGTransaction.status == "completed"
        ).all()
        
        total_volume = sum(tx.amount for tx in recent_txs)
        tx_count = len(recent_txs)
        
        # Check thresholds
        if total_volume > AutomatedAuditorRules.HIGH_VOLUME_THRESHOLD or \
           tx_count > AutomatedAuditorRules.HIGH_FREQUENCY_THRESHOLD:
            
            flag_reason = (
                f"High transaction velocity detected: {tx_count} transactions "
                f"totaling {total_volume} TEG in the last hour"
            )
            
            # Determine severity based on amount
            if total_volume > AutomatedAuditorRules.HIGH_VOLUME_THRESHOLD * Decimal("2"):
                severity = FlagSeverity.HIGH
            elif total_volume > AutomatedAuditorRules.HIGH_VOLUME_THRESHOLD * Decimal("1.5"):
                severity = FlagSeverity.MEDIUM
            else:
                severity = FlagSeverity.LOW
            
            # Create flag
            return AuditorFlagCRUD.create_flag(
                db=db,
                flagged_agent_did=agent_id,
                rule_violated_code="HIGH_VOLUME_VELOCITY_V1",
                flag_reason=flag_reason,
                flag_type="HighVolumeVelocity",
                severity=severity,
                flagged_by="automated_rules_v1",
                status=FlagStatus.AUTO_FLAGGED_MANUAL_REVIEW,
                related_transaction_id=transaction.transaction_id if transaction else None,
                details=json.dumps({
                    "transaction_count": tx_count,
                    "total_volume": str(total_volume),
                    "time_window": "1_hour"
                })
            )
        
        return None
    
    @staticmethod
    def check_suspicious_reputation_activity(
        db: Session,
        agent_id: str
    ) -> Optional[AuditorFlagLog]:
        """Check for suspicious reputation changes"""
        # Get agent profile
        agent = db.query(AgentTEGProfile).filter(
            AgentTEGProfile.agent_id == agent_id
        ).first()
        
        if not agent:
            return None
        
        # Look for rapid reputation drops
        one_day_ago = datetime.now(timezone.utc) - timedelta(days=1)
        
        # Count negative reputation signals in recent transactions
        negative_signals = db.query(TEGTransaction).filter(
            TEGTransaction.receiver_agent_id == agent_id,
            TEGTransaction.reputation_signal_applied == True,
            TEGTransaction.timestamp >= one_day_ago
        ).count()
        
        # Check for sudden reputation drop or high negative signal rate
        if negative_signals > 5:  # More than 5 negative signals in a day
            flag_reason = (
                f"Suspicious reputation activity: {negative_signals} negative "
                f"signals received in 24 hours. Current reputation: {agent.reputation_score}"
            )
            
            severity = FlagSeverity.MEDIUM
            if negative_signals > 10:
                severity = FlagSeverity.HIGH
            
            return AuditorFlagCRUD.create_flag(
                db=db,
                flagged_agent_did=agent_id,
                rule_violated_code="SUSPICIOUS_REPUTATION_ACTIVITY_V1",
                flag_reason=flag_reason,
                flag_type="SuspiciousReputationActivity",
                severity=severity,
                flagged_by="automated_rules_v1",
                status=FlagStatus.AUTO_FLAGGED_MANUAL_REVIEW,
                details=json.dumps({
                    "negative_signals_24h": negative_signals,
                    "current_reputation": agent.reputation_score
                })
            )
        
        return None
    
    @staticmethod
    def check_anomalous_fee_collection(
        db: Session,
        agent_id: str,
        transaction: Optional[TEGTransaction] = None
    ) -> Optional[AuditorFlagLog]:
        """Check for anomalous fee collection patterns"""
        # This is primarily for system accounts, but can flag agents
        # collecting unusual amounts through custom mechanisms
        
        # Look at incoming transactions that might be fees
        one_week_ago = datetime.now(timezone.utc) - timedelta(days=7)
        
        # Query for small, frequent incoming transactions (potential fees)
        incoming_txs = db.query(TEGTransaction).filter(
            TEGTransaction.receiver_agent_id == agent_id,
            TEGTransaction.timestamp >= one_week_ago,
            TEGTransaction.amount < Decimal("10"),  # Small amounts
            TEGTransaction.status == "completed"
        ).all()
        
        if len(incoming_txs) > 100:  # Many small transactions
            total_collected = sum(tx.amount for tx in incoming_txs)
            
            flag_reason = (
                f"Anomalous fee collection pattern: {len(incoming_txs)} small "
                f"transactions totaling {total_collected} TEG in 7 days"
            )
            
            return AuditorFlagCRUD.create_flag(
                db=db,
                flagged_agent_did=agent_id,
                rule_violated_code="ANOMALOUS_FEE_COLLECTION_V1",
                flag_reason=flag_reason,
                flag_type="AnomalousFeeCollection",
                severity=FlagSeverity.LOW,
                flagged_by="automated_rules_v1",
                status=FlagStatus.AUTO_FLAGGED_MANUAL_REVIEW,
                related_transaction_id=transaction.transaction_id if transaction else None,
                details=json.dumps({
                    "small_tx_count": len(incoming_txs),
                    "total_collected": str(total_collected),
                    "time_window": "7_days"
                })
            )
        
        return None
    
    @staticmethod
    def check_new_agent_large_transfer(
        db: Session,
        agent_id: str,
        transaction: TEGTransaction
    ) -> Optional[AuditorFlagLog]:
        """Check for large transfers from new agents"""
        # Get agent creation time
        agent = db.query(AgentTEGProfile).filter(
            AgentTEGProfile.agent_id == agent_id
        ).first()
        
        if not agent:
            return None
        
        # Check if agent is new
        agent_age = datetime.now(timezone.utc) - agent.created_at
        
        if agent_age.days < AutomatedAuditorRules.NEW_AGENT_DAYS:
            # Check if this is a large transfer
            if transaction.amount > AutomatedAuditorRules.LARGE_TRANSFER_THRESHOLD:
                flag_reason = (
                    f"Large transfer from new agent: {transaction.amount} TEG "
                    f"transferred by agent created {agent_age.days} days ago"
                )
                
                return AuditorFlagCRUD.create_flag(
                    db=db,
                    flagged_agent_did=agent_id,
                    rule_violated_code="NEW_AGENT_LARGE_TRANSFER_V1",
                    flag_reason=flag_reason,
                    flag_type="HighVolumeVelocity",
                    severity=FlagSeverity.MEDIUM,
                    flagged_by="automated_rules_v1",
                    status=FlagStatus.AUTO_FLAGGED_MANUAL_REVIEW,
                    related_transaction_id=transaction.transaction_id,
                    related_agent_id=transaction.receiver_agent_id,
                    details=json.dumps({
                        "transfer_amount": str(transaction.amount),
                        "agent_age_days": agent_age.days,
                        "receiver": transaction.receiver_agent_id
                    })
                )
        
        return None
    
    @staticmethod
    def check_failed_zkp_pattern(
        db: Session,
        agent_id: str,
        attestation_id: Optional[str] = None
    ) -> Optional[AuditorFlagLog]:
        """Check for patterns of failed ZKP attestations"""
        # Count failed ZKP attestations
        failed_count = AttestationCRUD.count_failed_zkp_attestations(db, agent_id)
        successful_count = AttestationCRUD.count_successful_zkp_attestations(db, agent_id)
        
        # Flag if high failure rate
        if failed_count > 5 and failed_count > successful_count * 2:
            flag_reason = (
                f"High ZKP verification failure rate: {failed_count} failed "
                f"vs {successful_count} successful attestations"
            )
            
            return AuditorFlagCRUD.create_flag(
                db=db,
                flagged_agent_did=agent_id,
                rule_violated_code="HIGH_ZKP_FAILURE_RATE_V1",
                flag_reason=flag_reason,
                flag_type="SuspiciousReputationActivity",
                severity=FlagSeverity.MEDIUM,
                flagged_by="automated_rules_v1",
                status=FlagStatus.AUTO_FLAGGED_MANUAL_REVIEW,
                related_attestation_id=attestation_id,
                details=json.dumps({
                    "failed_zkp_count": failed_count,
                    "successful_zkp_count": successful_count,
                    "failure_rate": f"{(failed_count / (failed_count + successful_count) * 100):.1f}%"
                })
            )
        
        return None
    
    @staticmethod
    def run_transfer_checks(
        db: Session,
        transaction: TEGTransaction
    ) -> List[AuditorFlagLog]:
        """Run all relevant checks for a transfer transaction"""
        flags = []
        
        # Check sender patterns
        if transaction.sender_agent_id:
            # High volume/velocity check
            flag = AutomatedAuditorRules.check_high_volume_velocity(
                db, transaction.sender_agent_id, transaction
            )
            if flag:
                flags.append(flag)
            
            # New agent large transfer check
            flag = AutomatedAuditorRules.check_new_agent_large_transfer(
                db, transaction.sender_agent_id, transaction
            )
            if flag:
                flags.append(flag)
        
        # Check receiver patterns
        if transaction.receiver_agent_id:
            # Anomalous fee collection
            flag = AutomatedAuditorRules.check_anomalous_fee_collection(
                db, transaction.receiver_agent_id, transaction
            )
            if flag:
                flags.append(flag)
        
        return flags
    
    @staticmethod
    def run_reputation_checks(
        db: Session,
        agent_id: str
    ) -> List[AuditorFlagLog]:
        """Run reputation-related checks"""
        flags = []
        
        flag = AutomatedAuditorRules.check_suspicious_reputation_activity(db, agent_id)
        if flag:
            flags.append(flag)
        
        return flags
    
    @staticmethod
    def run_attestation_checks(
        db: Session,
        agent_id: str,
        attestation_id: Optional[str] = None
    ) -> List[AuditorFlagLog]:
        """Run attestation-related checks"""
        flags = []
        
        flag = AutomatedAuditorRules.check_failed_zkp_pattern(
            db, agent_id, attestation_id
        )
        if flag:
            flags.append(flag)
        
        return flags
