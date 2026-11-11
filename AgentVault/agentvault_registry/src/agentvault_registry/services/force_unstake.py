"""
from ..es_ssl_helper import get_httpx_verify
TITANIUM VAULT D2: Force-Unstake Service

Bypasses time-lock on staking positions for enforcement slashing.
When a malicious agent has all AVT locked in veToken staking, the justice
system needs teeth — this service physically breaks the time-lock, applies
a 10% penalty to treasury, and liquidates to pay the victim.

Algorithm (from Economic Engine Spec §4.7):
  1. Calculate gross amount needed: required_amount / 0.9 (no more than the TEG holds locked)
  2. Select staking positions FIFO (oldest first)
  3. For each position: break lock, apply 10% penalty, net to liquid
  4. Move the penalty and the slashed units (required_amount, or what the release covers) to the
     treasury on the TEG (V0658 (k), D6-460: before, the slash was only a write to the cached balance)
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
        reason: str = "enforcement_slash",
        *,
        slash_ref: Optional[str] = None,
        slash_key: Optional[str] = None,
        treasury_reason: str = "enforcement_slash",
        reference_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Force-unstake staking positions and move the slashed units to the treasury.

        Process:
          1. Calculate gross needed (required / 0.9 to cover penalty), no more than the TEG holds locked
          2. Select positions FIFO (oldest first)
          3. For each position: break lock in the TEG, 10% penalty
          4. Move the penalty and the slashed units (required_amount, or what the release covers) agent -> treasury
             (V0658 (k), D6-460: before, only the penalty moved and the slash was a write to the cached balance;
             the units stayed with the agent on the TEG)
          5. Emit events

        Args:
            db: AsyncSession — caller manages the session
            agent_did: DID of the agent being slashed
            required_amount: AVT amount to slash (what the victim receives)
            enforcement_action_id: ID linking to enforcement action (from EnforcementEngine)
            admin_did: DID of admin authorizing (for admin-initiated slashes)
            reason: Reason string for event trail
            slash_ref: the slash this release serves when it is no enforcement action (a peer's accepted slash
                request, an administrator's approval of one: services/slash_order)
            slash_key: the Idempotency-Key of the slashed units' move (the penalty's is the same with "-penalty");
                without one, an administrator's direct slash, a fresh key per call
            treasury_reason / reference_id: how the TEG labels the slashed units' move

        Returns:
            Dict with: unstaked, penalty, slashed (units moved to the treasury), remaining_stake,
                       remaining_liquid, positions_affected, deficit, penalty_moved, slash_transaction_id,
                       slash_error and slash_unknown (when the TEG did not confirm a move), teg_locked

        Raises:
            ForceUnstakeError: If agent not found or operation fails
        """
        # ── GUARD: Authorization ──────────────────────────────────────
        if not enforcement_action_id and not admin_did and not slash_ref:
            raise ForceUnstakeError(
                "Force-unlock requires an enforcement_action_id, an admin_did or the slash it serves"
            )

        if required_amount <= 0:
            raise ForceUnstakeError("required_amount must be positive")

        action_ref = enforcement_action_id or slash_ref or f"admin:{admin_did}"
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
        # V0658 (k): never more than the TEG holds locked for the agent (the registry's positions are its own record)
        try:
            _teg_liquid, teg_locked = await self.teg_client.get_balances_admin(agent_did)
        except TEGClientError as e:
            raise TegUnlockError(
                f"TEG locked balance unreadable: {e}. Nothing was released, transaction rolled back."
            )
        gross_needed = min(gross_needed, int(teg_locked))
        logger.info(
            f"[ForceUnstake] Gross needed: {gross_needed} AVT "
            f"(required={required_amount} + penalty overhead, TEG locked={teg_locked})"
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
        if gross_needed <= 0:
            raise NoActiveStakeError(
                f"Agent {agent_did} has no active lock positions to unlock: the TEG holds nothing locked for it"
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
            if take_amount <= 0:
                continue

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

        # ── STEP 5: The released units are liquid on the TEG now ──────
        agent.staked_balance = Decimal(str(agent.staked_balance or 0)) - total_unstaked
        agent.liquid_balance = Decimal(str(agent.liquid_balance or 0)) + total_unstaked

        # Guard: staked_balance must not go negative
        if agent.staked_balance < 0:
            logger.warning(
                f"[ForceUnstake] staked_balance underflow corrected: "
                f"{agent.staked_balance} → 0"
            )
            agent.staked_balance = 0

        # ── STEP 6: Commit the released positions ─────────────────────
        await db.commit()

        # ── STEP 7: Move the penalty and the slashed units to the treasury (V0658 (k), D6-460) ──
        # The same rail as every slash's other steps (services/slash_order.move_to_treasury: the TEG's
        # /admin/treasury/receive, fee-free, delta 0, under an Idempotency-Key, a lost answer asked once more).
        from .slash_order import move_to_treasury
        key = slash_key or f"force-unstake-{uuid.uuid4().hex}"
        ref_id = reference_id or str(action_ref)
        penalty_moved = 0
        slash_error = ""
        slash_unknown = False
        if total_penalty > 0:
            got = await move_to_treasury(agent_did, Decimal(total_penalty), key=f"{key}-penalty",
                                         reason="force_unstake_penalty", reference_id=ref_id)
            if got.ok:
                penalty_moved = total_penalty
                logger.info(f"[ForceUnstake] Penalty {total_penalty} AVT → treasury OK")
            else:
                slash_error = f"the penalty did not move ({got.error})"
                slash_unknown = got.unknown
                logger.warning(f"[ForceUnstake] Treasury penalty transfer failed: {got.error}")
        actual_slash = min(int(required_amount), total_net_to_liquid)
        slash_tx_id = ""
        if actual_slash > 0:
            got = await move_to_treasury(agent_did, Decimal(actual_slash), key=key,
                                         reason=treasury_reason, reference_id=ref_id)
            if got.ok:
                slash_tx_id = got.tx_id
            else:
                logger.error(f"[ForceUnstake] The slashed units did not move: {got.error}")
                slash_error = "; ".join(x for x in (slash_error, f"the slashed units did not move ({got.error})") if x)
                slash_unknown = slash_unknown or got.unknown
                actual_slash = 0
        deficit = int(required_amount) - actual_slash

        if deficit > 0:
            logger.warning(
                f"[ForceUnstake] Deficit: {deficit} AVT of {required_amount} not slashed from the locks "
                f"(released {total_unstaked}, slashed {actual_slash})."
            )

        # The cached balance follows the TEG: what was released, less what moved to the treasury
        agent.liquid_balance = Decimal(str(agent.liquid_balance or 0)) - penalty_moved - actual_slash
        if agent.liquid_balance < 0:
            agent.liquid_balance = 0
        await db.commit()

        logger.info(
            f"[ForceUnstake] Balances updated: "
            f"staked={agent.staked_balance}, liquid={agent.liquid_balance}"
        )

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
                    "penalty_moved": penalty_moved,
                    "total_net_to_liquid": total_net_to_liquid,
                    "actual_slash": actual_slash,
                    "slash_moved_to_treasury": actual_slash,
                    "slash_key": key,
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

        # ── RETURN ────────────────────────────────────────────────────
        result = {
            "unstaked": total_unstaked,
            "penalty": total_penalty,
            "penalty_moved": penalty_moved,
            "slashed": actual_slash,
            "deficit": deficit,
            "remaining_stake": agent.staked_balance,
            "remaining_liquid": agent.liquid_balance,
            "positions_affected": positions_affected,
            "positions": affected_details,
            "enforcement_ref": action_ref,
            "teg_locked": str(teg_locked),
            "slash_transaction_id": slash_tx_id,
            "slash_error": slash_error,
            "slash_unknown": slash_unknown,
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
        # V0658 (k): the release is capped by what the TEG holds locked, as the slash itself is
        teg_locked = None
        try:
            _teg_liquid, teg_locked = await self.teg_client.get_balances_admin(agent_did)
            gross_needed = min(gross_needed, int(teg_locked))
        except TEGClientError as e:
            logger.warning(f"[ForceUnstake] preview: the TEG's locked balance is unreadable ({e}); positions only")
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
        
        # Project final balances. V0658 (k), D6-460: the slash takes the released units (the penalty on top), moved to
        # the treasury; the agent's liquid units are the slash order's own step, not this one's.
        projected_staked = agent.staked_balance - sim_unstaked
        actual_slash = min(required_amount, sim_net)
        projected_liquid_after_slash = agent.liquid_balance + sim_net - actual_slash
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
            "teg_locked": str(teg_locked) if teg_locked is not None else None,
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
