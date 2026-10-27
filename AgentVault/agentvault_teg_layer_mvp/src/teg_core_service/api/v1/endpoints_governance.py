"""Governance-related API endpoints for TEG system

Endpoints for managing policies, treasury, rewards, and administrative dashboards.
"""
import json
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import List, Dict, Any, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Security
from sqlalchemy import func, desc, and_, Index
from sqlalchemy.orm import Session
from starlette.status import HTTP_403_FORBIDDEN, HTTP_404_NOT_FOUND, HTTP_409_CONFLICT

from ...core.security import verify_admin_token, verify_agent_token
from ...core.secure_config import get_settings
from ...core.structured_logging import get_logger
from ...database.db_session import get_db
from ...database.models import (
    AgentTEGProfile, TEGTransaction, TransactionStatus, TransactionType,
    TEGPolicy, TEGRewardConfig, TEGRewardDistribution,
    TEGAttestationLog, TEGDisputeLog, Stake, StakingRewardDistribution, Delegation
)
from ...database.crud import AgentCRUD, StakingCRUD
from .schemas import (
    StakeCreateRequest, StakeResponse, UnstakeRequest, UnstakeResponse,
    MyStakesResponse, DelegationCreateRequest, DelegationResponse,
    StakingRewardCycleRequest, StakingRewardCycleResponse,
    StakingSummaryResponse, AllStakesResponse
)

# Single router following the One Router Principle
router = APIRouter()
settings = get_settings()
logger = get_logger(__name__)


def plan_policy_create(existing_is_active):
    """What a create with an already-known policy_code does (§BATCH9, pure): no row → "create";
    a deactivated row → "reactivate" in place; a live row → "conflict" (409)."""
    if existing_is_active is None:
        return "create"
    return "conflict" if existing_is_active else "reactivate"


# Policy Management Endpoints
@router.post("/admin/policies")
async def create_policy(
    policy_data: Dict[str, Any],
    db: Session = Depends(get_db),
    _: bool = Security(verify_admin_token)
):
    """Create a new TEG policy"""
    try:
        # Validate required fields
        required_fields = ["policy_code", "policy_name", "policy_type"]
        for field in required_fields:
            if field not in policy_data:
                raise HTTPException(
                    status_code=422,
                    detail=f"Missing required field: {field}"
                )
        
        # Validate policy_type
        valid_policy_types = ["attestation", "governance", "compliance", "economic"]
        if policy_data["policy_type"] not in valid_policy_types:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid policy_type. Must be one of: {valid_policy_types}"
            )
        
        # Validate parameters is a dict if provided
        if "parameters" in policy_data and not isinstance(policy_data["parameters"], dict):
            raise HTTPException(
                status_code=422,
                detail="Parameters must be a dictionary"
            )
        # Check if policy with same code exists
        existing = db.query(TEGPolicy).filter(
            TEGPolicy.policy_code == policy_data["policy_code"]
        ).first()
        
        # §BATCH9 (2026-09-06, eb's finding): a soft-deleted policy kept its code forever — the registry's
        # list defaults to active rows, so the code LOOKED free and the re-create answered 409 with nothing
        # to see. A deactivated row is reactivated in place with the new fields (its id survives, its
        # history stays); only a LIVE duplicate is a conflict.
        plan = plan_policy_create(None if existing is None else bool(existing.is_active))
        if plan == "conflict":
            raise HTTPException(
                status_code=HTTP_409_CONFLICT,
                detail=f"Policy with code {policy_data['policy_code']} already exists"
            )
        if plan == "reactivate":
            existing.policy_name = policy_data["policy_name"]
            existing.policy_type = policy_data["policy_type"]
            existing.description = policy_data.get("description", "")
            existing.parameters = json.dumps(policy_data.get("parameters", {}))
            existing.circuit_identifier = policy_data.get("circuit_identifier")
            existing.is_active = policy_data.get("is_active", True)
            existing.enforcement_level = policy_data.get("enforcement_level", "optional")
            existing.reward_amount = Decimal(policy_data.get("reward_amount", "0"))
            existing.updated_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(existing)
            return {
                "policy_id": existing.policy_id,
                "policy_code": existing.policy_code,
                "policy_name": existing.policy_name,
                "policy_type": existing.policy_type,
                "description": existing.description,
                "parameters": json.loads(existing.parameters) if existing.parameters else {},
                "circuit_identifier": existing.circuit_identifier,
                "is_active": existing.is_active,
                "enforcement_level": existing.enforcement_level,
                "reward_amount": str(existing.reward_amount),
                "created_at": existing.created_at.isoformat() if existing.created_at else None,
                "updated_at": existing.updated_at.isoformat() if existing.updated_at else None,
                "reactivated": True,
            }
        
        # Create new policy
        policy = TEGPolicy(
            policy_id=str(uuid4()),
            policy_code=policy_data["policy_code"],
            policy_name=policy_data["policy_name"],
            policy_type=policy_data["policy_type"],
            description=policy_data.get("description", ""),
            parameters=json.dumps(policy_data.get("parameters", {})),
            circuit_identifier=policy_data.get("circuit_identifier"),
            is_active=policy_data.get("is_active", True),
            enforcement_level=policy_data.get("enforcement_level", "optional"),
            reward_amount=Decimal(policy_data.get("reward_amount", "0")),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        
        db.add(policy)
        db.commit()
        db.refresh(policy)
        
        return {
            "policy_id": policy.policy_id,
            "policy_code": policy.policy_code,
            "policy_name": policy.policy_name,
            "policy_type": policy.policy_type,
            "description": policy.description,
            "parameters": json.loads(policy.parameters) if policy.parameters else {},
            "circuit_identifier": policy.circuit_identifier,
            "is_active": policy.is_active,
            "enforcement_level": policy.enforcement_level,
            "reward_amount": str(policy.reward_amount),
            "created_at": policy.created_at.isoformat(),
            "updated_at": policy.updated_at.isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create policy: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/admin/policies")
async def get_all_policies(
    db: Session = Depends(get_db),
    _: bool = Security(verify_admin_token)
):
    """Get all policies"""
    try:
        policies = db.query(TEGPolicy).all()
        
        return [
            {
                "policy_id": p.policy_id,
                "policy_code": p.policy_code,
                "policy_name": p.policy_name,
                "policy_type": p.policy_type,
                "description": p.description,
                "parameters": json.loads(p.parameters) if p.parameters else {},
                "circuit_identifier": p.circuit_identifier,
                "is_active": p.is_active,
                "enforcement_level": p.enforcement_level,
                "reward_amount": str(p.reward_amount),
                "created_at": p.created_at.isoformat(),
                "updated_at": p.updated_at.isoformat()
            }
            for p in policies
        ]
    except Exception as e:
        logger.error(f"Failed to retrieve policies: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/admin/policies/{policy_id}")
async def get_policy_by_id(
    policy_id: str,
    db: Session = Depends(get_db),
    _: bool = Security(verify_admin_token)
):
    """Get specific policy by ID"""
    try:
        policy = db.query(TEGPolicy).filter(
            TEGPolicy.policy_id == policy_id
        ).first()
        
        if not policy:
            raise HTTPException(
                status_code=HTTP_404_NOT_FOUND,
                detail=f"Policy {policy_id} not found"
            )
        
        return {
            "policy_id": policy.policy_id,
            "policy_code": policy.policy_code,
            "policy_name": policy.policy_name,
            "policy_type": policy.policy_type,
            "description": policy.description,
            "parameters": json.loads(policy.parameters) if policy.parameters else {},
            "circuit_identifier": policy.circuit_identifier,
            "is_active": policy.is_active,
            "enforcement_level": policy.enforcement_level,
            "reward_amount": str(policy.reward_amount),
            "created_at": policy.created_at.isoformat(),
            "updated_at": policy.updated_at.isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to retrieve policy: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/admin/policies/{policy_id}")
async def update_policy(
    policy_id: str,
    update_data: Dict[str, Any],
    db: Session = Depends(get_db),
    _: bool = Security(verify_admin_token)
):
    """Update existing policy"""
    try:
        policy = db.query(TEGPolicy).filter(
            TEGPolicy.policy_id == policy_id
        ).first()
        
        if not policy:
            raise HTTPException(
                status_code=HTTP_404_NOT_FOUND,
                detail=f"Policy {policy_id} not found"
            )
        
        # Update fields
        if "policy_name" in update_data:
            policy.policy_name = update_data["policy_name"]
        if "description" in update_data:
            policy.description = update_data["description"]
        if "parameters" in update_data:
            policy.parameters = json.dumps(update_data["parameters"])
        if "is_active" in update_data:
            policy.is_active = update_data["is_active"]
        if "enforcement_level" in update_data:
            policy.enforcement_level = update_data["enforcement_level"]
        if "reward_amount" in update_data:
            policy.reward_amount = Decimal(update_data["reward_amount"])
        
        policy.updated_at = datetime.now(timezone.utc)
        
        db.commit()
        db.refresh(policy)
        
        return {
            "policy_id": policy.policy_id,
            "policy_code": policy.policy_code,
            "policy_name": policy.policy_name,
            "policy_type": policy.policy_type,
            "description": policy.description,
            "parameters": policy.parameters,
            "circuit_identifier": policy.circuit_identifier,
            "is_active": policy.is_active,
            "enforcement_level": policy.enforcement_level,
            "reward_amount": str(policy.reward_amount),
            "created_at": policy.created_at.isoformat(),
            "updated_at": policy.updated_at.isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update policy: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/admin/policies/{policy_id}")
async def delete_policy(
    policy_id: str,
    db: Session = Depends(get_db),
    _: bool = Security(verify_admin_token)
):
    """Delete policy (soft delete by deactivating)"""
    try:
        policy = db.query(TEGPolicy).filter(
            TEGPolicy.policy_id == policy_id
        ).first()
        
        if not policy:
            raise HTTPException(
                status_code=HTTP_404_NOT_FOUND,
                detail=f"Policy {policy_id} not found"
            )
        
        # Soft delete by deactivating
        policy.is_active = False
        policy.updated_at = datetime.now(timezone.utc)
        
        db.commit()
        
        return {"message": f"Policy {policy_id} deactivated"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete policy: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# Treasury Operations
@router.get("/admin/treasury/balance")
async def get_treasury_balance(
    db: Session = Depends(get_db),
    _: bool = Security(verify_admin_token)
):
    """Get current treasury balance"""
    try:
        treasury_did = settings.teg_system_treasury_did
        treasury_agent = AgentCRUD.get_or_create(db, treasury_did)
        
        return {
            "treasury_did": treasury_did,
            "balance": str(treasury_agent.token_balance),
            "last_updated": datetime.now(timezone.utc).isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to get treasury balance: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/admin/treasury/transactions")
async def get_treasury_transactions(
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    _: bool = Security(verify_admin_token)
):
    """Get treasury transaction history"""
    try:
        treasury_did = settings.teg_system_treasury_did
        
        # Get transactions where treasury is sender or receiver
        transactions = db.query(TEGTransaction).filter(
            (TEGTransaction.sender_agent_id == treasury_did) |
            (TEGTransaction.receiver_agent_id == treasury_did)
        ).order_by(
            desc(TEGTransaction.timestamp)
        ).limit(limit).all()
        
        return [
            {
                "transaction_id": tx.transaction_id,
                "transaction_type": tx.transaction_type,
                "sender_agent_id": tx.sender_agent_id,
                "receiver_agent_id": tx.receiver_agent_id,
                "amount": str(tx.amount),
                "fee_amount": str(tx.fee_amount),
                "status": tx.status.value,
                "timestamp": tx.timestamp.isoformat(),
                "attached_message": tx.attached_message
            }
            for tx in transactions
        ]
        
    except Exception as e:
        logger.error(f"Failed to get treasury transactions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Reward Configuration
@router.post("/admin/rewards/config")
async def create_reward_config(
    reward_data: Dict[str, Any],
    db: Session = Depends(get_db),
    _: bool = Security(verify_admin_token)
):
    """Create new reward configuration"""
    try:
        reward = TEGRewardConfig(
            reward_id=str(uuid4()),
            reward_type=reward_data["reward_type"],
            reward_code=reward_data["reward_code"],
            description=reward_data.get("description", ""),
            amount=Decimal(reward_data["amount"]),
            policy_code=reward_data.get("policy_code"),
            conditions=json.dumps(reward_data.get("conditions", {})),
            is_active=reward_data.get("is_active", True),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        
        db.add(reward)
        db.commit()
        db.refresh(reward)
        
        return {
            "reward_id": reward.reward_id,
            "reward_type": reward.reward_type,
            "reward_code": reward.reward_code,
            "description": reward.description,
            "amount": str(reward.amount),
            "policy_code": reward.policy_code,
            "conditions": json.loads(reward.conditions) if reward.conditions else {},
            "is_active": reward.is_active,
            "created_at": reward.created_at.isoformat(),
            "updated_at": reward.updated_at.isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to create reward config: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/admin/rewards/config")
async def get_all_reward_configs(
    db: Session = Depends(get_db),
    _: bool = Security(verify_admin_token)
):
    """Get all reward configurations"""
    try:
        rewards = db.query(TEGRewardConfig).all()
        
        return [
            {
                "reward_id": r.reward_id,
                "reward_type": r.reward_type,
                "reward_code": r.reward_code,
                "description": r.description,
                "amount": str(r.amount),
                "policy_code": r.policy_code,
                "conditions": json.loads(r.conditions) if r.conditions else {},
                "is_active": r.is_active,
                "created_at": r.created_at.isoformat(),
                "updated_at": r.updated_at.isoformat()
            }
            for r in rewards
        ]
        
    except Exception as e:
        logger.error(f"Failed to get reward configs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/admin/rewards/config/{reward_id}")
async def update_reward_config(
    reward_id: str,
    update_data: Dict[str, Any],
    db: Session = Depends(get_db),
    _: bool = Security(verify_admin_token)
):
    """Update reward configuration"""
    try:
        reward = db.query(TEGRewardConfig).filter(
            TEGRewardConfig.reward_id == reward_id
        ).first()
        
        if not reward:
            raise HTTPException(
                status_code=HTTP_404_NOT_FOUND,
                detail=f"Reward config {reward_id} not found"
            )
        
        # Update fields
        if "amount" in update_data:
            reward.amount = Decimal(update_data["amount"])
        if "conditions" in update_data:
            reward.conditions = json.dumps(update_data["conditions"])
        if "is_active" in update_data:
            reward.is_active = update_data["is_active"]
        
        reward.updated_at = datetime.now(timezone.utc)
        
        db.commit()
        db.refresh(reward)
        
        return {
            "reward_id": reward.reward_id,
            "reward_type": reward.reward_type,
            "reward_code": reward.reward_code,
            "description": reward.description,
            "amount": str(reward.amount),
            "policy_code": reward.policy_code,
            "conditions": json.loads(reward.conditions) if reward.conditions else {},
            "is_active": reward.is_active,
            "created_at": reward.created_at.isoformat(),
            "updated_at": reward.updated_at.isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update reward config: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/admin/rewards/distributions")
async def get_reward_distributions(
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    _: bool = Security(verify_admin_token)
):
    """Get reward distribution history"""
    try:
        distributions = db.query(TEGRewardDistribution).order_by(
            desc(TEGRewardDistribution.timestamp)
        ).limit(limit).all()
        
        return [
            {
                "distribution_id": d.distribution_id,
                "agent_id": d.agent_id,
                "reward_type": d.reward_type,
                "amount": str(d.amount),
                "policy_code": d.policy_code,
                "transaction_id": d.transaction_id,
                "timestamp": d.timestamp.isoformat()
            }
            for d in distributions
        ]
        
    except Exception as e:
        logger.error(f"Failed to get reward distributions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Dashboard APIs
@router.get("/admin/dashboard/summary")
async def get_dashboard_summary(
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    db: Session = Depends(get_db),
    _: bool = Security(verify_admin_token)
):
    """Get comprehensive dashboard summary"""
    try:
        # Total agents
        total_agents = db.query(func.count(AgentTEGProfile.agent_id)).scalar()
        
        # Total token supply
        total_token_supply = db.query(
            func.sum(AgentTEGProfile.token_balance)
        ).scalar() or Decimal("0")
        
        # Total transactions
        tx_query = db.query(func.count(TEGTransaction.transaction_id))
        if from_date:
            tx_query = tx_query.filter(TEGTransaction.timestamp >= from_date)
        if to_date:
            tx_query = tx_query.filter(TEGTransaction.timestamp <= to_date)
        total_transactions = tx_query.scalar()
        
        # Active policies
        active_policies = db.query(func.count(TEGPolicy.policy_id)).filter(
            TEGPolicy.is_active == True
        ).scalar()
        
        # Treasury balance
        treasury_agent = AgentCRUD.get_or_create(db, settings.teg_system_treasury_did)
        treasury_balance = treasury_agent.token_balance
        
        # Recent activity (last 24h)
        recent_cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        recent_tx_count = db.query(func.count(TEGTransaction.transaction_id)).filter(
            TEGTransaction.timestamp >= recent_cutoff
        ).scalar()
        
        recent_attestations = db.query(func.count(TEGAttestationLog.submission_id)).filter(
            TEGAttestationLog.submitted_at >= recent_cutoff
        ).scalar()
        
        recent_disputes = db.query(func.count(TEGDisputeLog.dispute_log_id)).filter(
            TEGDisputeLog.created_at >= recent_cutoff
        ).scalar()
        
        result = {
            "total_agents": total_agents,
            "total_token_supply": str(total_token_supply),
            "total_transactions": total_transactions,
            "active_policies": active_policies,
            "treasury_balance": str(treasury_balance),
            "recent_activity": {
                "transactions_24h": recent_tx_count,
                "attestations_24h": recent_attestations,
                "disputes_24h": recent_disputes
            }
        }
        
        if from_date or to_date:
            result["period"] = {
                "from_date": from_date.isoformat() if from_date else None,
                "to_date": to_date.isoformat() if to_date else None
            }
        
        return result
        
    except Exception as e:
        logger.error(f"Failed to get dashboard summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/admin/dashboard/activity")
async def get_dashboard_activity(
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: bool = Security(verify_admin_token)
):
    """Get recent activity for dashboard"""
    try:
        activities = []
        
        # Get recent transactions
        recent_txs = db.query(TEGTransaction).order_by(
            desc(TEGTransaction.timestamp)
        ).limit(limit).all()
        
        for tx in recent_txs:
            activities.append({
                "activity_type": "transaction",
                "timestamp": tx.timestamp.isoformat(),
                "description": f"{tx.transaction_type}: {tx.sender_agent_id} → {tx.receiver_agent_id}",
                "amount": str(tx.amount),
                "details": {
                    "transaction_id": tx.transaction_id,
                    "status": tx.status.value
                }
            })
        
        # Sort by timestamp
        activities.sort(key=lambda x: x["timestamp"], reverse=True)
        
        return activities[:limit]
        
    except Exception as e:
        logger.error(f"Failed to get dashboard activity: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/admin/dashboard/agents/stats")
async def get_agent_statistics(
    db: Session = Depends(get_db),
    _: bool = Security(verify_admin_token)
):
    """Get agent statistics"""
    try:
        # Total agents
        total_agents = db.query(func.count(AgentTEGProfile.agent_id)).scalar()
        
        # Active agents (24h)
        active_cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        active_agents_24h = db.query(
            func.count(func.distinct(TEGTransaction.sender_agent_id))
        ).filter(
            TEGTransaction.timestamp >= active_cutoff
        ).scalar()
        
        # New agents (7d)
        new_cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        new_agents_7d = db.query(func.count(AgentTEGProfile.agent_id)).filter(
            AgentTEGProfile.created_at >= new_cutoff
        ).scalar()
        
        # Balance statistics
        balance_stats = db.query(
            func.avg(AgentTEGProfile.token_balance).label("average"),
            func.min(AgentTEGProfile.token_balance).label("min"),
            func.max(AgentTEGProfile.token_balance).label("max")
        ).filter(
            AgentTEGProfile.token_balance > 0
        ).first()
        
        # Top agents by balance
        top_agents = db.query(AgentTEGProfile).order_by(
            desc(AgentTEGProfile.token_balance)
        ).limit(10).all()
        
        # Calculate median (simplified - in production use proper SQL median)
        all_balances = db.query(AgentTEGProfile.token_balance).filter(
            AgentTEGProfile.token_balance > 0
        ).order_by(AgentTEGProfile.token_balance).all()
        
        median_balance = Decimal("0")
        if all_balances:
            mid = len(all_balances) // 2
            median_balance = all_balances[mid][0]
        
        return {
            "total_agents": total_agents,
            "active_agents_24h": active_agents_24h,
            "new_agents_7d": new_agents_7d,
            "average_balance": str(balance_stats.average or 0),
            "median_balance": str(median_balance),
            "min_balance": str(balance_stats.min or 0),
            "max_balance": str(balance_stats.max or 0),
            "top_agents_by_balance": [
                {
                    "agent_id": a.agent_did,
                    "balance": str(a.token_balance),
                    "reputation_score": a.reputation_score
                }
                for a in top_agents
            ]
        }
        
    except Exception as e:
        logger.error(f"Failed to get agent statistics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/admin/dashboard/transactions/analytics")
async def get_transaction_analytics(
    db: Session = Depends(get_db),
    _: bool = Security(verify_admin_token)
):
    """Get transaction analytics"""
    try:
        cutoff_24h = datetime.now(timezone.utc) - timedelta(hours=24)
        
        # Transaction volume (24h)
        volume_24h = db.query(
            func.sum(TEGTransaction.amount)
        ).filter(
            TEGTransaction.timestamp >= cutoff_24h,
            TEGTransaction.status == TransactionStatus.COMPLETED
        ).scalar() or Decimal("0")
        
        # Transaction count (24h)
        count_24h = db.query(func.count(TEGTransaction.transaction_id)).filter(
            TEGTransaction.timestamp >= cutoff_24h
        ).scalar()
        
        # Average transaction size
        avg_size = db.query(
            func.avg(TEGTransaction.amount)
        ).filter(
            TEGTransaction.status == TransactionStatus.COMPLETED
        ).scalar() or Decimal("0")
        
        # Transaction types breakdown
        type_breakdown = db.query(
            TEGTransaction.transaction_type,
            func.count(TEGTransaction.transaction_id).label("count")
        ).group_by(
            TEGTransaction.transaction_type
        ).all()
        
        # Peak hour (simplified - counts transactions per hour for last 24h)
        hourly_counts = []
        for hour in range(24):
            hour_start = cutoff_24h + timedelta(hours=hour)
            hour_end = hour_start + timedelta(hours=1)
            
            count = db.query(func.count(TEGTransaction.transaction_id)).filter(
                TEGTransaction.timestamp >= hour_start,
                TEGTransaction.timestamp < hour_end
            ).scalar()
            
            hourly_counts.append((hour_start.hour, count))
        
        peak_hour = max(hourly_counts, key=lambda x: x[1])[0] if hourly_counts else 0
        
        return {
            "total_volume_24h": str(volume_24h),
            "transaction_count_24h": count_24h,
            "average_transaction_size": str(avg_size),
            "peak_hour": peak_hour,
            "transaction_types_breakdown": {
                tx_type: count for tx_type, count in type_breakdown
            }
        }
        
    except Exception as e:
        logger.error(f"Failed to get transaction analytics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/admin/dashboard/policies/compliance")
async def get_policy_compliance_metrics(
    db: Session = Depends(get_db),
    _: bool = Security(verify_admin_token)
):
    """Get policy compliance metrics"""
    try:
        # Total policies
        total_policies = db.query(func.count(TEGPolicy.policy_id)).scalar()
        
        # Active policies
        active_policies = db.query(func.count(TEGPolicy.policy_id)).filter(
            TEGPolicy.is_active == True
        ).scalar()
        
        # Attestations submitted
        attestations_submitted = db.query(
            func.count(TEGAttestationLog.submission_id)
        ).scalar()
        
        # For MVP, assume all submitted attestations are verified
        attestations_verified = attestations_submitted
        
        # Compliance rate (simplified)
        compliance_rate = 100.0  # MVP assumption
        
        # Policy violations (from disputes)
        policy_violations = db.query(func.count(TEGDisputeLog.dispute_log_id)).filter(
            TEGDisputeLog.dispute_reason_category == "policy_violation"
        ).scalar()
        
        return {
            "total_policies": total_policies,
            "active_policies": active_policies,
            "attestations_submitted": attestations_submitted,
            "attestations_verified": attestations_verified,
            "compliance_rate": compliance_rate,
            "policy_violations": policy_violations
        }
        
    except Exception as e:
        logger.error(f"Failed to get compliance metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Staking Endpoints

# ── §MONEY-R30 (2026-09-04): the TEG's DUPLICATE governance-staking model ────
# Two staking models live in this codebase. The registry's rail (M5) reaches the
# TEG through teg_client.lock_tokens/unlock_tokens -> /tokenomics/lock|unlock.
# THIS family (/staking/*, /admin/staking/*) is a second, older model that moves
# token_balance without a locked_balance counterpart.
#
# MEASURED before gating, twice over:
#   · teg_client.py dials NO /staking/* path at all — only /tokenomics/{lock,
#     unlock,balance,rewards,transactions,treasury}, /admin/{reward-fund,
#     treasury/transfer,agent-locked-balance} and /reputation/signal;
#   · the registry's own /api/v1/staking/{stake,unstake} resolve through
#     teg_client.stake_tokens -> lock_tokens -> /tokenomics/lock, so they never
#     touch this family (that was the one distinction that could have broken a
#     live green row in the parallel session's suites — checked, clean);
#   · agentvault2-07 measured all of api_tests/: zero hits on eight of these
#     paths, and the 29 hits on /staking/{stake,unstake} are all localhost:8000
#     inside a REGISTRY container, never a TEG host.
#
# Gated, not deleted (D8). TEG_RETIRED_RAILS=true restores the family whole.
def _retired_rail_guard() -> None:
    import os as _os
    if (_os.getenv("TEG_RETIRED_RAILS", "false") or "false").strip().lower() \
            in ("1", "true", "yes", "on"):
        return
    raise HTTPException(
        status_code=404,
        detail=("This TEG staking surface is retired: the registry's staking rail is the "
                "supported one and reaches the TEG via /tokenomics/lock and /tokenomics/unlock."),
    )


@router.post("/staking/stake", response_model=StakeResponse)
async def stake_tokens(
    stake_data: StakeCreateRequest,
    db: Session = Depends(get_db),
    current_agent: str = Security(verify_agent_token)
) -> StakeResponse:
    """Stake AVT tokens"""
    _retired_rail_guard()   # §MONEY-R30
    try:
        # Create stake
        stake = StakingCRUD.create_stake(db, current_agent, stake_data.amount)
        
        return StakeResponse(
            stake_id=stake.stake_id,
            agent_id=stake.agent_id,
            amount=stake.amount,
            staked_at=stake.staked_at,
            unstaked_at=stake.unstaked_at,
            is_active=stake.is_active,
            last_reward_claim=stake.last_reward_claim
        )
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to create stake: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/staking/unstake", response_model=UnstakeResponse)
async def unstake_tokens(
    unstake_data: UnstakeRequest,
    db: Session = Depends(get_db),
    current_agent: str = Security(verify_agent_token)
) -> UnstakeResponse:
    """Unstake AVT tokens and claim rewards"""
    _retired_rail_guard()   # §MONEY-R30
    try:
        # Unstake
        stake, total_returned = StakingCRUD.unstake(db, unstake_data.stake_id, current_agent)
        
        return UnstakeResponse(
            stake_id=stake.stake_id,
            amount_unstaked=stake.amount,
            total_returned=total_returned,
            unstaked_at=stake.unstaked_at,
            is_active=stake.is_active
        )
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to unstake: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/staking/mystake", response_model=MyStakesResponse)
async def get_my_stakes(
    active_only: bool = Query(True, description="Only return active stakes"),
    db: Session = Depends(get_db),
    current_agent: str = Security(verify_agent_token)
) -> MyStakesResponse:
    """Get current agent's stakes"""
    _retired_rail_guard()   # §MONEY-R30
    try:
        stakes = StakingCRUD.get_agent_stakes(db, current_agent, active_only)
        total_staked = StakingCRUD.get_total_staked(db, current_agent)
        
        return MyStakesResponse(
            agent_id=current_agent,
            total_staked=total_staked,
            stakes=[
                StakeResponse(
                    stake_id=s.stake_id,
                    agent_id=s.agent_id,
                    amount=s.amount,
                    staked_at=s.staked_at,
                    unstaked_at=s.unstaked_at,
                    is_active=s.is_active,
                    last_reward_claim=s.last_reward_claim
                )
                for s in stakes
            ]
        )
        
    except Exception as e:
        logger.error(f"Failed to get stakes: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/admin/staking/summary", response_model=StakingSummaryResponse)
async def get_staking_summary(
    db: Session = Depends(get_db),
    _: bool = Security(verify_admin_token)
) -> StakingSummaryResponse:
    """Get system-wide staking summary"""
    _retired_rail_guard()   # §MONEY-R30
    try:
        # Get all active stakes
        active_stakes = db.query(Stake).filter(
            Stake.is_active == True
        ).all()
        
        # Calculate statistics
        total_staked = StakingCRUD.get_total_staked(db)
        unique_stakers = len(set(stake.agent_id for stake in active_stakes))
        
        # Get recent reward distributions
        recent_rewards = db.query(StakingRewardDistribution).order_by(
            desc(StakingRewardDistribution.distributed_at)
        ).limit(10).all()
        
        return StakingSummaryResponse(
            total_staked=total_staked,
            active_stakes_count=len(active_stakes),
            unique_stakers=unique_stakers,
            average_stake_size=total_staked / len(active_stakes) if active_stakes else Decimal("0"),
            recent_reward_distributions=[
                {
                    "distribution_id": r.distribution_id,
                    "agent_id": r.agent_id,
                    "amount": str(r.amount),
                    "reward_type": r.reward_type,
                    "distributed_at": r.distributed_at.isoformat(),
                    "reward_cycle_id": r.reward_cycle_id
                }
                for r in recent_rewards
            ]
        )
        
    except Exception as e:
        logger.error(f"Failed to get staking summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/admin/staking/trigger-reward-cycle", response_model=StakingRewardCycleResponse)
async def trigger_reward_cycle(
    reward_data: StakingRewardCycleRequest,
    db: Session = Depends(get_db),
    admin_token: bool = Security(verify_admin_token)
) -> StakingRewardCycleResponse:
    """Manually trigger a staking reward distribution cycle.

    §MONEY-R20 / D9 (2026-09-04): DISABLED BY DEFAULT. `distribute_staking_rewards`
    writes `agent.token_balance += <pct>` DIRECTLY on the ORM (crud.py:1727) — a
    supply-creating mover with no `entry_type`, so it lands in transit_net and the
    supply invariant cannot see it (the R18 blind spot). The registry's daily
    staking distributor, funded by the fee_collector→treasury waterfall, is the
    only reward path that pays from money that already exists.

    Gated rather than deleted (D8: disabling a rail is reversible, removing one is
    a release decision). Set TEG_STAKING_REWARD_CYCLE_ENABLED=true to restore.
    """
    import os as _os
    if (_os.getenv("TEG_STAKING_REWARD_CYCLE_ENABLED", "false") or "false").strip().lower() \
            not in ("1", "true", "yes", "on"):
        raise HTTPException(
            status_code=501,
            detail=("Staking reward cycles are not issued from the TEG: this rail credits "
                    "balances directly and creates supply. Rewards are paid by the "
                    "registry's waterfall-funded distributor."),
        )
    try:
        # Distribute rewards
        stakers_rewarded, total_distributed = StakingCRUD.distribute_staking_rewards(
            db, reward_data.reward_percentage
        )
        
        return StakingRewardCycleResponse(
            success=True,
            reward_percentage=reward_data.reward_percentage,
            stakers_rewarded=stakers_rewarded,
            total_distributed=total_distributed,
            timestamp=datetime.now(timezone.utc)
        )
        
    except Exception as e:
        logger.error(f"Failed to trigger reward cycle: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/admin/staking/stakes", response_model=AllStakesResponse)
async def get_all_stakes(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    active_only: bool = Query(True),
    db: Session = Depends(get_db),
    _: bool = Security(verify_admin_token)
) -> AllStakesResponse:
    """Get all stakes in the system (admin only)"""
    _retired_rail_guard()   # §MONEY-R30
    try:
        query = db.query(Stake)
        
        if active_only:
            query = query.filter(Stake.is_active == True)
        
        total = query.count()
        stakes = query.order_by(desc(Stake.staked_at)).limit(limit).offset(offset).all()
        
        return AllStakesResponse(
            total=total,
            limit=limit,
            offset=offset,
            stakes=[
                StakeResponse(
                    stake_id=s.stake_id,
                    agent_id=s.agent_id,
                    amount=s.amount,
                    staked_at=s.staked_at,
                    unstaked_at=s.unstaked_at,
                    is_active=s.is_active,
                    last_reward_claim=s.last_reward_claim
                )
                for s in stakes
            ]
        )
        
    except Exception as e:
        logger.error(f"Failed to get all stakes: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Delegation Endpoints
@router.post("/staking/delegate", response_model=DelegationResponse)
async def create_delegation(
    delegation_data: DelegationCreateRequest,
    db: Session = Depends(get_db),
    current_agent: str = Security(verify_agent_token)
) -> DelegationResponse:
    """Delegate staked AVT to a validator"""
    _retired_rail_guard()   # §MONEY-R30
    try:
        # Create delegation
        delegation = StakingCRUD.create_delegation(
            db,
            stake_id=delegation_data.stake_id,
            delegator_agent_id=current_agent,
            validator_agent_id=delegation_data.validator_agent_id,
            amount=delegation_data.amount,
            reward_share_percentage=delegation_data.reward_share_percentage
        )
        
        return DelegationResponse(
            delegation_id=delegation.delegation_id,
            delegator_agent_id=delegation.delegator_agent_id,
            validator_agent_id=delegation.validator_agent_id,
            stake_id=delegation.stake_id,
            delegated_amount=delegation.delegated_amount,
            delegation_start=delegation.delegation_start,
            delegation_end=delegation.delegation_end,
            is_active=delegation.is_active,
            reward_share_percentage=delegation.reward_share_percentage
        )
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to create delegation: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/staking/mydelegations", response_model=List[DelegationResponse])
async def get_my_delegations(
    active_only: bool = Query(True, description="Only return active delegations"),
    db: Session = Depends(get_db),
    current_agent: str = Security(verify_agent_token)
) -> List[DelegationResponse]:
    """Get current agent's delegations"""
    _retired_rail_guard()   # §MONEY-R30
    try:
        query = db.query(Delegation).filter(
            Delegation.delegator_agent_id == current_agent
        )
        
        if active_only:
            query = query.filter(Delegation.is_active == True)
        
        delegations = query.order_by(desc(Delegation.delegation_start)).all()
        
        return [
            DelegationResponse(
                delegation_id=d.delegation_id,
                delegator_agent_id=d.delegator_agent_id,
                validator_agent_id=d.validator_agent_id,
                stake_id=d.stake_id,
                delegated_amount=d.delegated_amount,
                delegation_start=d.delegation_start,
                delegation_end=d.delegation_end,
                is_active=d.is_active,
                reward_share_percentage=d.reward_share_percentage
            )
            for d in delegations
        ]
        
    except Exception as e:
        logger.error(f"Failed to get delegations: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/staking/undelegate/{delegation_id}")
async def end_delegation(
    delegation_id: str,
    db: Session = Depends(get_db),
    current_agent: str = Security(verify_agent_token)
) -> dict:
    """End a delegation"""
    _retired_rail_guard()   # §MONEY-R30
    try:
        # Get delegation and validate ownership
        delegation = db.query(Delegation).filter(
            Delegation.delegation_id == delegation_id
        ).first()
        
        if not delegation:
            raise HTTPException(
                status_code=404,
                detail=f"Delegation {delegation_id} not found"
            )
        
        if delegation.delegator_agent_id != current_agent:
            raise HTTPException(
                status_code=403,
                detail="You can only end your own delegations"
            )
        
        if not delegation.is_active:
            raise HTTPException(
                status_code=400,
                detail="Delegation is already inactive"
            )
        
        # End the delegation
        delegation.is_active = False
        delegation.delegation_end = datetime.now(timezone.utc)
        db.commit()
        
        return {
            "success": True,
            "delegation_id": delegation_id,
            "ended_at": delegation.delegation_end.isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to end delegation: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/staking/validators/{validator_id}/delegations")
async def get_validator_delegations(
    validator_id: str,
    db: Session = Depends(get_db),
    current_agent: str = Security(verify_agent_token)
) -> dict:
    """Get delegations received by a validator"""
    _retired_rail_guard()   # §MONEY-R30
    try:
        # Get active delegations to this validator
        delegations = db.query(Delegation).filter(
            and_(
                Delegation.validator_agent_id == validator_id,
                Delegation.is_active == True
            )
        ).all()
        
        # Calculate total delegated amount
        total_delegated = sum(d.delegated_amount for d in delegations)
        
        return {
            "validator_agent_id": validator_id,
            "total_delegated": str(total_delegated),
            "delegation_count": len(delegations),
            "delegations": [
                {
                    "delegation_id": d.delegation_id,
                    "delegator_agent_id": d.delegator_agent_id,
                    "delegated_amount": str(d.delegated_amount),
                    "reward_share_percentage": str(d.reward_share_percentage),
                    "delegation_start": d.delegation_start.isoformat()
                }
                for d in delegations
            ]
        }
        
    except Exception as e:
        logger.error(f"Failed to get validator delegations: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Public policy endpoint (for agents)
@router.get("/policies/active")
async def get_active_policies_for_agents(
    db: Session = Depends(get_db),
    current_agent: str = Security(verify_agent_token)
):
    """Get active policies for agents (public endpoint)"""
    try:
        policies = db.query(TEGPolicy).filter(
            TEGPolicy.is_active == True
        ).all()
        
        return [
            {
                "policy_id": p.policy_id,
                "policy_code": p.policy_code,
                "policy_name": p.policy_name,
                "policy_type": p.policy_type,
                "description": p.description,
                "parameters": json.loads(p.parameters) if p.parameters else {},
                "circuit_identifier": p.circuit_identifier,
                "is_active": p.is_active,
                "enforcement_level": p.enforcement_level,
                "reward_amount": str(p.reward_amount)
            }
            for p in policies
        ]
        
    except Exception as e:
        logger.error(f"Failed to get active policies: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Bounty Board endpoint - highlights attestation policies with rewards
@router.get("/policies/bounty-board")
async def get_bounty_board(
    db: Session = Depends(get_db),
    current_agent: str = Security(verify_agent_token),
    policy_type: Optional[str] = Query(None, description="Filter by policy type (e.g., 'attestation')"),
    min_reward: Optional[Decimal] = Query(None, description="Minimum reward amount"),
    sort_by: str = Query("reward_amount", description="Sort by: reward_amount, created_at, policy_name")
):
    """Get the 'Bounty Board' - active policies with rewards for compliance.
    
    This endpoint highlights policies that offer rewards, particularly for attestations.
    Agents can use this to discover opportunities to earn AVT tokens.
    """
    try:
        # Start with active policies that have rewards
        query = db.query(TEGPolicy).filter(
            and_(
                TEGPolicy.is_active == True,
                TEGPolicy.reward_amount > 0
            )
        )
        
        # Apply filters
        if policy_type:
            query = query.filter(TEGPolicy.policy_type == policy_type)
        if min_reward:
            query = query.filter(TEGPolicy.reward_amount >= min_reward)
        
        # Apply sorting
        if sort_by == "reward_amount":
            query = query.order_by(desc(TEGPolicy.reward_amount))
        elif sort_by == "created_at":
            query = query.order_by(desc(TEGPolicy.created_at))
        elif sort_by == "policy_name":
            query = query.order_by(TEGPolicy.policy_name)
        else:
            query = query.order_by(desc(TEGPolicy.reward_amount))  # Default
        
        policies = query.all()
        
        # Format response with additional bounty-specific information
        bounties = []
        for p in policies:
            # Count how many attestations have been submitted for this policy
            attestation_count = 0
            if p.policy_type == "attestation":
                attestation_count = db.query(TEGAttestationLog).filter(
                    TEGAttestationLog.policy_id == p.policy_id
                ).count()
            
            bounties.append({
                "policy_id": p.policy_id,
                "policy_code": p.policy_code,
                "policy_name": p.policy_name,
                "policy_type": p.policy_type,
                "description": p.description,
                "reward_amount": str(p.reward_amount),
                "circuit_identifier": p.circuit_identifier,
                "enforcement_level": p.enforcement_level,
                "created_at": p.created_at.isoformat(),
                "attestations_submitted": attestation_count,
                "requirements": {
                    "attestation_type": p.circuit_identifier if p.circuit_identifier else "standard",
                    "zkp_required": bool(p.circuit_identifier),
                    "parameters": json.loads(p.parameters) if p.parameters else {}
                }
            })
        
        return {
            "total_bounties": len(bounties),
            "total_rewards_available": str(sum(p.reward_amount for p in policies)),
            "bounties": bounties
        }
        
    except Exception as e:
        logger.error(f"Failed to get bounty board: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# NOTE: Proposal management and voting endpoints have been REMOVED from TEG.
# Governance proposals and voting live in the Registry's Agent Senate system
# (agentvault_registry/routers/governance.py + crud/crud_governance.py).
# The Registry has proper GovernanceProposal + Vote models with:
#   - Voting power based on staked balance
#   - Vote deduplication (one vote per agent per proposal)
#   - Tally mechanism with status transitions
# The TEG endpoints referenced a non-existent TEGGovernanceProposal model
# and would crash at runtime. Removed 2026-02-22 as part of P1 cleanup.
