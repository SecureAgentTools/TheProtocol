"""
P3/D2: veToken Power Calculator Service

Replaces sqrt(staked_balance) with time-decay veToken formula:
  v_i = sqrt(x_i) × (t_lock - t_elapsed) / T_max

Where:
  x_i       = staked amount for this position
  t_lock    = original lock duration (lock_period_days)
  t_elapsed = time already locked (now - staked_at)
  T_max     = max lock period from policy (default 365 days)

If t_elapsed >= t_lock: v_i = 0 (expired lock has zero power)
If lock_days = 0 (flexible): v_i = sqrt(x_i) × 0.01 (minimal power)
"""
import math
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional
from decimal import Decimal

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Stake, Agent

logger = logging.getLogger(__name__)

# Default max lock period (365 days)
DEFAULT_T_MAX_DAYS = 365
# Flexible stake power multiplier (1% of sqrt power)
FLEXIBLE_POWER_MULTIPLIER = 0.01


class VeTokenCalculator:
    """
    veToken voting power calculator.
    
    Implements time-weighted quadratic voting where longer remaining lock
    durations give proportionally more governance influence.
    """
    
    def __init__(self, t_max_days: int = DEFAULT_T_MAX_DAYS,
                 flexible_multiplier: float = FLEXIBLE_POWER_MULTIPLIER):
        self.t_max_days = t_max_days
        self.flexible_multiplier = flexible_multiplier

    @classmethod
    def from_policy(cls, frame_policy) -> "VeTokenCalculator":
        """§FRAMEPOLICY (2026-09-11) — what a vote weighs is the frame's rule,
        not a constant in this file.

        `governance.max_lock_days` and `governance.flexible_stake_ve_multiplier_max`
        have been declared in every frame's policy document (and pinned in
        LOCKED_PARAMS) since before §GOVDEMO weighed a real vote with them —
        while this class read two module constants instead. The factory defaults
        ARE those constants (365 / 0.01), so a frame that has not amended its
        policy computes byte-identical weights.
        """
        return cls(
            t_max_days=int(frame_policy.get("governance.max_lock_days", DEFAULT_T_MAX_DAYS)),
            flexible_multiplier=float(frame_policy.get(
                "governance.flexible_stake_ve_multiplier_max", FLEXIBLE_POWER_MULTIPLIER)),
        )
    
    def calculate_position_power(
        self,
        amount: Decimal,
        lock_period_days: int,
        staked_at: datetime,
        now: Optional[datetime] = None
    ) -> float:
        """
        Calculate veToken power for a single staking position.
        
        Args:
            amount: Staked token amount
            lock_period_days: Original lock duration in days
            staked_at: When the stake was created
            now: Current time (defaults to utcnow)
            
        Returns:
            veToken power as float
        """
        if now is None:
            now = datetime.now(timezone.utc)
        
        # Ensure timezone-aware comparison
        if staked_at.tzinfo is None:
            staked_at = staked_at.replace(tzinfo=timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        
        amount_float = float(amount)
        if amount_float <= 0:
            return 0.0
        
        sqrt_amount = math.sqrt(amount_float)
        
        # Flexible stake (0 days lock) → minimal power
        if lock_period_days == 0:
            return round(sqrt_amount * self.flexible_multiplier, 2)
        
        # Calculate elapsed time
        elapsed = now - staked_at
        elapsed_days = elapsed.total_seconds() / 86400.0
        
        # Remaining lock time
        remaining_days = max(0.0, lock_period_days - elapsed_days)
        
        # Expired lock → zero power
        if remaining_days <= 0:
            return 0.0
        
        # veToken formula: sqrt(amount) × (remaining / T_max)
        time_multiplier = remaining_days / self.t_max_days
        power = sqrt_amount * time_multiplier
        
        return round(power, 2)
    
    async def calculate_agent_power(
        self,
        db: AsyncSession,
        agent_did: str,
        now: Optional[datetime] = None
    ) -> float:
        """
        Sum veToken power across all active positions for an agent.
        
        Args:
            db: Database session
            agent_did: DID of the agent
            now: Current time (defaults to utcnow)
            
        Returns:
            Total veToken power for the agent
        """
        if now is None:
            now = datetime.now(timezone.utc)
        
        stmt = select(Stake).where(
            and_(
                Stake.agent_did == agent_did,
                Stake.is_active == True
            )
        )
        result = await db.execute(stmt)
        positions = result.scalars().all()
        
        total_power = 0.0
        for pos in positions:
            power = self.calculate_position_power(
                amount=pos.amount,
                lock_period_days=pos.lock_period_days,
                staked_at=pos.staked_at,
                now=now
            )
            total_power += power
        
        return round(total_power, 2)
    
    async def get_agent_power_breakdown(
        self,
        db: AsyncSession,
        agent_did: str,
        now: Optional[datetime] = None
    ) -> dict:
        """
        Get detailed veToken power breakdown per position.
        
        Returns:
            Dict with total_ve_power, can_vote, and per-position breakdown
        """
        if now is None:
            now = datetime.now(timezone.utc)
        
        stmt = select(Stake).where(
            and_(
                Stake.agent_did == agent_did,
                Stake.is_active == True
            )
        )
        result = await db.execute(stmt)
        positions = result.scalars().all()
        
        position_details = []
        total_power = 0.0
        
        for pos in positions:
            # Ensure timezone-aware
            staked_at = pos.staked_at
            if staked_at.tzinfo is None:
                staked_at = staked_at.replace(tzinfo=timezone.utc)
            
            elapsed_days = (now - staked_at).total_seconds() / 86400.0
            remaining_days = max(0.0, pos.lock_period_days - elapsed_days) if pos.lock_period_days > 0 else 0.0
            
            power = self.calculate_position_power(
                amount=pos.amount,
                lock_period_days=pos.lock_period_days,
                staked_at=staked_at,
                now=now
            )
            total_power += power
            
            position_details.append({
                "stake_id": pos.id,
                "amount": str(pos.amount),
                "lock_days": pos.lock_period_days,
                "remaining_days": round(remaining_days, 1),
                "ve_power": power
            })
        
        total_power = round(total_power, 2)
        
        return {
            "total_ve_power": total_power,
            "can_vote": total_power > 0,
            "positions": position_details
        }
    
    async def get_network_total_power(
        self,
        db: AsyncSession,
        now: Optional[datetime] = None
    ) -> float:
        """
        Sum of all agents' veToken power across the network.
        Used for quorum calculations.
        
        Args:
            db: Database session
            now: Current time
            
        Returns:
            Total network veToken power
        """
        if now is None:
            now = datetime.now(timezone.utc)
        
        # Get all active stakes
        stmt = select(Stake).where(Stake.is_active == True)
        result = await db.execute(stmt)
        all_stakes = result.scalars().all()
        
        total = 0.0
        for pos in all_stakes:
            power = self.calculate_position_power(
                amount=pos.amount,
                lock_period_days=pos.lock_period_days,
                staked_at=pos.staked_at,
                now=now
            )
            total += power
        
        return round(total, 2)
    
    def get_power_decay_timeline(
        self,
        amount: Decimal,
        lock_period_days: int,
        staked_at: datetime,
        days_ahead: int = 365,
        step_days: int = 7
    ) -> List[dict]:
        """
        Project power decay over time for dashboard visualization.
        
        Args:
            amount: Staked amount
            lock_period_days: Original lock period
            staked_at: When staked
            days_ahead: How many days to project
            step_days: Step size for timeline points
            
        Returns:
            List of {date, power} dicts
        """
        now = datetime.now(timezone.utc)
        timeline = []
        
        for day in range(0, days_ahead + 1, step_days):
            future = now + timedelta(days=day)
            power = self.calculate_position_power(
                amount=amount,
                lock_period_days=lock_period_days,
                staked_at=staked_at,
                now=future
            )
            timeline.append({
                "date": future.strftime("%Y-%m-%d"),
                "power": power
            })
            # Stop projecting once power hits zero
            if power == 0 and day > 0:
                break
        
        return timeline
    
    def get_lock_options(self) -> dict:
        """
        Available lock tiers and projected power multipliers.
        
        Returns:
            Dict with min/max lock days and tier multiplier table
        """
        tiers = [
            {"days": 0, "label": "Flexible", "power_multiplier": FLEXIBLE_POWER_MULTIPLIER},
            {"days": 7, "label": "7 days", "power_multiplier": round(7 / self.t_max_days, 3)},
            {"days": 30, "label": "30 days", "power_multiplier": round(30 / self.t_max_days, 3)},
            {"days": 90, "label": "90 days", "power_multiplier": round(90 / self.t_max_days, 3)},
            {"days": 180, "label": "180 days", "power_multiplier": round(180 / self.t_max_days, 3)},
            {"days": 365, "label": "365 days", "power_multiplier": 1.0},
        ]
        
        return {
            "min_lock_days": 0,
            "max_lock_days": self.t_max_days,
            "t_max_days": self.t_max_days,
            "flexible_multiplier": FLEXIBLE_POWER_MULTIPLIER,
            "tiers": tiers
        }


# Singleton instance
vetoken_calculator = VeTokenCalculator()
