"""
from ..es_ssl_helper import get_httpx_verify
TITANIUM VAULT D2: Force-Unstake Service

Bypasses time-lock on staking positions for enforcement slashing.
When a malicious agent has all AVT locked in veToken staking, the justice
system needs teeth — this service physically breaks the time-lock, applies
a 10% penalty to treasury, and liquidates to pay the victim.

Algorithm (from Economic Engine Spec §4.7):
  1. Calculate gross amount needed: required_amount / 0.9
  2. Select staking positions FIFO (oldest first)
  3. For each position: break lock, apply 10% penalty, net to liquid
  4. Slash required_amount from liquid_balance
  5. Emit events to EventStore

Guards:
  - Requires enforcement_action_id (or admin authorization)
  - ALL operations within a single DB transaction
  - If any step fails, entire transaction rolls back

Pattern precedent: vetoken_calculator.py, dynamic_apy_engine.py
"""
import logging
import uuid
from decimal import Decimal
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Agent, Stake, StakeTransaction
from ..teg_client import get_teg_client, TEGClientError
from ..event_emitter import get_event_emitter

logger = logging.getLogger(__name__)

# Penalty rate applied to force-unstaked positions
FORCE_UNSTAKE_PENALTY_RATE = Decimal("0.10")  # 10%


class ForceUnstakeError(Exception):
    """Base exception for force-unstake operations."""
    pass


class InsufficientStakeError(ForceUnstakeError):
    """Agent does not have enough staked to cover the required amount."""
    pass


# §MCPTEST30 (V0550): the slash route answered 400 "An internal error occurred" for every one of these, so an admin
# who slashed a DID with no agent, or an agent with nothing staked, read a server fault. Each reason has its class
# (still a ForceUnstakeError, so the enforcement engine's catchers are unchanged) and the route says which.
class AgentNotFoundError(ForceUnstakeError):
    """No agent has this DID."""


class NoActiveStakeError(ForceUnstakeError):
    """The agent has no active staking position to unstake."""


class TegUnlockError(ForceUnstakeError):
    """The TEG did not unlock a position; the transaction was rolled back and nothing was slashed."""


class ForceUnstakeService:
    """
    Bypasses veToken time-lock for enforcement slashing.
    10% penalty applied to unstaked positions. All operations atomic.
    
    Only callable by:
    - EnforcementEngine (via enforcement_action_id)
    - Admin endpoint (via admin_did authorization)
    """
    
    def __init__(self):
        self.teg_client = get_teg_client()
        self.event_emitter = get_event_emitter()
    
    async def force_unstake_for_slash(
        self,
        db: AsyncSession,
        agent_did: str,
        required_amount: int,
        enforcement_action_id: Optional[str] = None,
        admin_did: Optional[str] = None,
        reason: str = "enforcement_slash"
    ) -> Dict[str, Any]:
        """
        Force-unstake staking positions and slash liquid balance.
        
        Process:
          1. Calculate gross needed (required / 0.9 to cover penalty)
          2. Select positions FIFO (oldest first)
          3. For each position: break lock, 10% penalty to treasury, net to liquid
          4. Slash required_amount from liquid_balance
          5. Emit events
        
        Args:
            db: AsyncSession — caller manages the session
            agent_did: DID of the agent being slashed
            required_amount: AVT amount to slash (what the victim receives)
            enforcement_action_id: ID linking to enforcement action (from EnforcementEngine)
            admin_did: DID of admin authorizing (for admin-initiated slashes)
            reason: Reason string for event trail
            
        Returns:
            Dict with: unstaked, penalty, slashed, remaining_stake, 
                       remaining_liquid, positions_affected, deficit
        
        Raises:
            ForceUnstakeError: If agent not found or operation fails
        """
        # ── GUARD: Authorization ──────────────────────────────────────
        if not enforcement_action_id and not admin_did:
            raise ForceUnstakeError(
                "Force-unlock requires either enforcement_action_id or admin_did"
            )
        
        if required_amount <= 0:
            raise ForceUnstakeError("required_amount must be positive")
        
        action_ref = enforcement_action_id or f"admin:{admin_did}"
        logger.info(
            f"[ForceUnstake] Starting: agent={agent_did}, "
            f"required={required_amount} AVT, ref={action_ref}"
        )
        
        # ── STEP 1: Load agent ────────────────────────────────────────
        result = await db.execute(
            select(Agent).where(Agent.did == agent_did)
        )
        agent = result.scalar_one_or_none()
        if not agent:
            raise AgentNotFoundError(f"Agent not found: {agent_did}")
        
        # ── STEP 2: Calculate gross amount needed ─────────────────────
        # required_amount / 0.9 = gross needed (10% penalty means 90% reaches liquid)
        gross_needed = int(Decimal(str(required_amount)) / (1 - FORCE_UNSTAKE_PENALTY_RATE))
        logger.info(
            f"[ForceUnstake] Gross needed: {gross_needed} AVT "
            f"(required={required_amount} + penalty overhead)"
        )
        
        # ── STEP 3: Select positions FIFO ─────────────────────────────
        positions_result = await db.execute(
            select(Stake).where(
                and_(
                    Stake.agent_did == agent_did,
                    Stake.is_active == True
                )
            ).order_by(Stake.staked_at.asc())  # FIFO: oldest first
        )
        positions = list(positions_result.scalars().all())
        
        if not positions:
            raise NoActiveStakeError(
                f"Agent {agent_did} has no active lock positions to unlock"
            )
        
        # ── STEP 4: Process positions ─────────────────────────────────
        total_unstaked = 0
        total_penalty = 0
        total_net_to_liquid = 0
        remaining_needed = gross_needed
        positions_affected = 0
        affected_details = []
        
        for position in positions:
            if remaining_needed <= 0:
                break
            
            pos_amount = int(position.amount)
            take_amount = min(pos_amount, remaining_needed)
            
            # Calculate penalty and net
            penalty = int(Decimal(str(take_amount)) * FORCE_UNSTAKE_PENALTY_RATE)
            net_to_liquid = take_amount - penalty
            
            # TEG Layer: unlock tokens
            try:
                await self.teg_client.unlock_tokens(agent_did, Decimal(str(take_amount)))
            except TEGClientError as e:
                logger.error(
                    f"[ForceUnstake] TEG unlock failed for position {position.id}: {e}"
                )
                raise TegUnlockError(
                    f"TEG unlock failed: {e}. Transaction rolled back."
                )
            
            # Update position in DB
            if take_amount >= pos_amount:
                # Full position consumed
                position.is_active = False
                position.unstaked_at = datetime.now(timezone.utc)
            else:
                # Partial — reduce amount in-place
                position.amount = Decimal(str(pos_amount - take_amount))
            
            # Record transaction
            tx_id = str(uuid.uuid4())
            tx = StakeTransaction(
                id=tx_id,
                agent_id=agent.id,
                stake_id=position.id,
                transaction_type="force_unstake",
                amount=Decimal(str(take_amount)),
                status="completed",
                teg_transaction_id=None,
                transaction_metadata={
                    "enforcement_ref": action_ref,
                    "penalty": penalty,
                    "net_to_liquid": net_to_liquid,
                    "reason": reason
                }
            )
            db.add(tx)
            
            # Accumulate totals
            total_unstaked += take_amount
            total_penalty += penalty
            total_net_to_liquid += net_to_liquid
            remaining_needed -= take_amount
            positions_affected += 1
            
            affected_details.append({
                "stake_id": position.id,
                "amount_taken": take_amount,
                "penalty": penalty,
                "net_to_liquid": net_to_liquid,
                "fully_consumed": take_amount >= pos_amount
            })
            
            logger.info(
                f"[ForceUnstake] Position {position.id}: "
                f"took={take_amount}, penalty={penalty}, net={net_to_liquid}, "
                f"{'consumed' if take_amount >= pos_amount else 'partial'}"
            )
        
        # ── STEP 5: Update agent balances ─────────────────────────────
        agent.staked_balance -= total_unstaked
        agent.liquid_balance += total_net_to_liquid
        
        # Guard: staked_balance must not go negative
        if agent.staked_balance < 0:
            logger.warning(
                f"[ForceUnstake] staked_balance underflow corrected: "
                f"{agent.staked_balance} → 0"
            )
            agent.staked_balance = 0
        
        # ── STEP 6: Slash from liquid ─────────────────────────────────
        actual_slash = min(required_amount, agent.liquid_balance)
        deficit = required_amount - actual_slash
        agent.liquid_balance -= actual_slash
        
        if deficit > 0:
            logger.warning(
                f"[ForceUnstake] Deficit: agent lacks {deficit} AVT after "
                f"full unstake. Slashed {actual_slash} of {required_amount}."
            )
        
        # Guard: liquid_balance must not go negative
        if agent.liquid_balance < 0:
            agent.liquid_balance = 0
        
        logger.info(
            f"[ForceUnstake] Balances updated: "
            f"staked={agent.staked_balance}, liquid={agent.liquid_balance}"
        )
        
        # ── STEP 7: Commit DB transaction ─────────────────────────────
        await db.commit()
        
        # ── STEP 8: Emit events (post-commit, non-fatal) ─────────────
        try:
            await self.event_emitter.emit(
                event_type="StakeForceUnstaked",
                aggregate_id=agent_did,
                data={
                    "enforcement_ref": action_ref,
                    "required_amount": required_amount,
                    "total_unstaked": total_unstaked,
                    "total_penalty": total_penalty,
                    "total_net_to_liquid": total_net_to_liquid,
                    "actual_slash": actual_slash,
                    "deficit": deficit,
                    "positions_affected": positions_affected,
                    "positions": affected_details,
                    "reason": reason
                },
                idempotency_key=f"force_unstake:{action_ref}:{agent_did}"
            )
        except Exception as e:
            # Event emission failure is non-fatal — DB transaction already committed
            logger.error(f"[ForceUnstake] Event emission failed (non-fatal): {e}")
        
        # ── STEP 9: Send penalty to treasury via TEG ──────────────────
        if total_penalty > 0:
            try:
                # Use the existing treasury receive flow from teg_integration.py
                # This is a TEG admin call: agent → treasury
                import httpx
                import os
                # PRE-EXISTING BUG, found by pyflakes while wiring agent.slashed (py_compile
                # passes on an undefined name): `get_httpx_verify()` was called here but never
                # imported, so this treasury-penalty leg raised NameError every time it ran —
                # swallowed by the enclosing `except` that logs "non-fatal". Same class as the
                # two fiat call sites fixed earlier today.
                from agentvault_registry.es_ssl_helper import get_httpx_verify
                teg_url = os.getenv('TEG_API_BASE_URL', 'http://teg-layer:8080')
                teg_key = os.getenv(
                    'TEG_ADMIN_API_KEY',
                    ''
                )
                async with httpx.AsyncClient(timeout=15.0, verify=get_httpx_verify()) as client:
                    resp = await client.post(
                        f"{teg_url}/api/v1/admin/treasury/receive",
                        json={
                            "source_agent_id": agent_did,
                            "amount": str(total_penalty),
                            "reason": "force_unstake_penalty",
                            "reference_id": action_ref
                        },
                        headers={"Authorization": f"Bearer {teg_key}"}
                    )
                    if resp.status_code == 200:
                        logger.info(
                            f"[ForceUnstake] Penalty {total_penalty} AVT → treasury OK"
                        )
                    else:
                        logger.warning(
                            f"[ForceUnstake] Treasury penalty transfer failed: "
                            f"{resp.status_code} — {resp.text[:200]}"
                        )
            except Exception as e:
                logger.error(
                    f"[ForceUnstake] Treasury penalty transfer error (non-fatal): {e}"
                )
        
        # ── RETURN ────────────────────────────────────────────────────
        result = {
            "unstaked": total_unstaked,
            "penalty": total_penalty,
            "slashed": actual_slash,
            "deficit": deficit,
            "remaining_stake": agent.staked_balance,
            "remaining_liquid": agent.liquid_balance,
            "positions_affected": positions_affected,
            "positions": affected_details,
            "enforcement_ref": action_ref
        }
        
        logger.info(f"[ForceUnstake] Complete: {result}")

        # §NOTIFV2 agent.slashed — wired HERE, at the service, not at the router: the admin route
        # (routers/enforcement_admin.py) and the AUTOMATIC path
        # (services/enforcement_engine.py) both land in this one method, so this is the choke
        # point. Fire-and-forget: losing stake is already bad news, a push must never make it worse.
        try:
            import asyncio as _aio
            from agentvault_registry.background_tasks.push_notify import notify_agent_owners
            _aio.create_task(notify_agent_owners(
                "agent.slashed", [agent_did],
                title="Agent stake slashed",
                message=(f"{agent_did[:40]} was slashed {actual_slash} "
                         f"(unstaked {total_unstaked}). Reason: {reason}"),
                amount=float(actual_slash or 0),
                # D6-781: the owner's agent list (the console has no #/agents; Pocket opens its own Agents tab)
                tags="warning", priority="high", click="/ui/#/my-agents"))
        except Exception:  # noqa: BLE001
            logger.debug("[NOTIFY] agent.slashed emit failed", exc_info=True)

        return result
    
    async def calculate_force_unstake_preview(
        self,
        db: AsyncSession,
        agent_did: str,
        required_amount: int
    ) -> Dict[str, Any]:
        """
        Dry-run preview of force-unstake. No side effects.
        Used by admin approval UI to show impact before execution.
        
        Args:
            db: AsyncSession
            agent_did: DID of the agent
            required_amount: Amount to slash
            
        Returns:
            Preview dict showing what would happen
        """
        # Load agent
        result = await db.execute(
            select(Agent).where(Agent.did == agent_did)
        )
        agent = result.scalar_one_or_none()
        if not agent:
            return {"error": f"Agent not found: {agent_did}"}
        
        # Load positions
        positions_result = await db.execute(
            select(Stake).where(
                and_(
                    Stake.agent_did == agent_did,
                    Stake.is_active == True
                )
            ).order_by(Stake.staked_at.asc())
        )
        positions = list(positions_result.scalars().all())
        
        if not positions:
            return {
                "error": "No active lock positions",
                "agent_did": agent_did,
                "current_staked": agent.staked_balance,
                "current_liquid": agent.liquid_balance,
                "required_amount": required_amount
            }
        
        # Simulate
        gross_needed = int(Decimal(str(required_amount)) / (1 - FORCE_UNSTAKE_PENALTY_RATE))
        remaining_needed = gross_needed
        
        sim_unstaked = 0
        sim_penalty = 0
        sim_net = 0
        sim_positions = []
        
        for pos in positions:
            if remaining_needed <= 0:
                break
            
            pos_amount = int(pos.amount)
            take = min(pos_amount, remaining_needed)
            penalty = int(Decimal(str(take)) * FORCE_UNSTAKE_PENALTY_RATE)
            net = take - penalty
            
            sim_unstaked += take
            sim_penalty += penalty
            sim_net += net
            remaining_needed -= take
            
            sim_positions.append({
                "stake_id": pos.id,
                "current_amount": pos_amount,
                "amount_taken": take,
                "penalty": penalty,
                "net_to_liquid": net,
                "fully_consumed": take >= pos_amount,
                "lock_period_days": pos.lock_period_days,
                "staked_at": pos.staked_at.isoformat() if pos.staked_at else None
            })
        
        # Project final balances
        projected_staked = agent.staked_balance - sim_unstaked
        projected_liquid = agent.liquid_balance + sim_net
        actual_slash = min(required_amount, projected_liquid)
        projected_liquid_after_slash = projected_liquid - actual_slash
        deficit = required_amount - actual_slash
        
        return {
            "agent_did": agent_did,
            "required_amount": required_amount,
            "gross_needed": gross_needed,
            "current_staked": agent.staked_balance,
            "current_liquid": agent.liquid_balance,
            "total_unstaked": sim_unstaked,
            "total_penalty": sim_penalty,
            "total_net_to_liquid": sim_net,
            "actual_slash": actual_slash,
            "deficit": deficit,
            "projected_staked_balance": max(0, projected_staked),
            "projected_liquid_balance": max(0, projected_liquid_after_slash),
            "positions_affected": len(sim_positions),
            "positions": sim_positions,
            "is_preview": True
        }


# ── Module-level singleton ──────────────────────────────────────────
_force_unstake_service: Optional[ForceUnstakeService] = None


def get_force_unstake_service() -> ForceUnstakeService:
    """Get or create the singleton ForceUnstakeService instance."""
    global _force_unstake_service
    if _force_unstake_service is None:
        _force_unstake_service = ForceUnstakeService()
    return _force_unstake_service
