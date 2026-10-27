"""
Staking Rewards Service for Automatic Distribution

This service handles:
- Reward calculation based on APY tiers
- Daily distribution logic
- TEG layer integration for token transfers
- Event Store logging
"""
import logging
import uuid
from decimal import Decimal
from datetime import datetime, timedelta, timezone, date
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func
from sqlalchemy.orm import selectinload

from ..models import Agent
from ..database import get_db
from ..teg_client import get_teg_client
from ..event_emitter import get_event_emitter
from .reward_funding import fund_reward_via_waterfall

logger = logging.getLogger(__name__)


class StakingRewardsService:
    """Service for calculating and distributing staking rewards."""
    
    def __init__(self):
        self.teg_client = get_teg_client()
        self.event_emitter = get_event_emitter()
    
    async def calculate_daily_reward(
        self,
        staked_amount: Decimal,
        apy_rate: Decimal,
        days: int = 1
    ) -> Decimal:
        """
        Calculate daily reward based on APY.
        
        Formula: Daily Reward = (Staked Amount * APY Rate / 100) / 365 * days
        """
        if staked_amount <= 0 or apy_rate <= 0:
            return Decimal('0')
        
        # Convert payout rate to daily rate and calculate payout
        daily_rate = apy_rate / Decimal('100') / Decimal('365')
        reward = staked_amount * daily_rate * Decimal(str(days))
        
        # Round to 18 decimal places (standard for crypto)
        return reward.quantize(Decimal('0.000000000000000001'))
    
    async def get_apy_tier(
        self,
        db: AsyncSession,
        staked_amount: Decimal,
        lock_period_days: int = 0,
    ) -> Dict[str, Any]:
        """Get the appropriate APY for the given stake amount.

        §7.1 / Sprint 0.2: Delegates to DynamicAPYEngine (logistic decay curve)
        rather than querying the legacy StakingApyConfig fixed-tier table.
        Falls back to StakingApyConfig if DynamicAPYEngine is unavailable.
        """
        try:
            from .dynamic_apy_engine import DynamicAPYEngine
            # §TRUSTCHAIN P4.5: the RESOLVED document (row merged onto the defaults), the same
            # one the engine and the card read — a partial row no longer drops a section here.
            from .frame_policy import load as _load_policy
            _pj = (await _load_policy(db)).doc
            engine = DynamicAPYEngine.from_policy(_pj)
            apy_float = await engine.calculate_current_apy(db=db, lock_days=lock_period_days)
            return {
                'tier_name': 'dynamic',
                'base_apy': Decimal(str(round(apy_float, 4))),
                'lock_bonus_apy': Decimal('0'),
                'lock_period_days': lock_period_days,
            }
        except Exception as e:
            logger.warning(
                f'[StakingRewards] DynamicAPYEngine unavailable ({e}), '
                'falling back to StakingApyConfig'
            )

        # Fallback: legacy static tier lookup
        from ..models import StakingApyConfig
        stmt = select(StakingApyConfig).where(
            and_(
                StakingApyConfig.is_active == True,
                StakingApyConfig.min_stake <= staked_amount,
                or_(
                    StakingApyConfig.max_stake.is_(None),
                    StakingApyConfig.max_stake >= staked_amount
                )
            )
        ).order_by(StakingApyConfig.base_apy.desc())
        result = await db.execute(stmt)
        tier = result.scalar_one_or_none()
        if not tier:
            return {
                'tier_name': 'bronze',
                'base_apy': Decimal('5.0'),
                'lock_bonus_apy': Decimal('0'),
                'lock_period_days': 0,
            }
        return {
            'tier_name': tier.tier_name,
            'base_apy': tier.base_apy,
            'lock_bonus_apy': tier.lock_bonus_apy,
            'lock_period_days': tier.lock_period_days,
        }
    
    async def get_eligible_stakers(
        self,
        db: AsyncSession,
        distribution_date: date
    ) -> List[Agent]:
        """Get all agents eligible for reward distribution.

        §5.7 / §6.1: Excludes agents that are:
          - enforcement_status == 'suspended' or 'revoked'
          - rewards_paused_until > now()
          - eigentrust_score < policy.staking_rewards.reputation_floor_for_rewards
        """
        now = datetime.now(timezone.utc)

        # Load policy floor (fail-open: if no policy, floor = 0)
        # §TRUSTCHAIN P4.5: read the RESOLVED policy (one resolver, `frame_policy.load`), not the raw
        # row — the same second-copy shape V0348 removed from the enforcement engine.
        reputation_floor = 0.0
        try:
            from .frame_policy import load as _load_policy
            reputation_floor = float(
                (await _load_policy(db)).get('staking_rewards.reputation_floor_for_rewards', 0.0) or 0.0
            )
        except Exception as e:
            logger.warning(f'[StakingRewards] Could not load enforcement policy: {e}')
        # §TRUSTCHAIN P4.7 — the readout. A staker with NO trust vector yet and a staker whose
        # vector is BELOW the floor are both skipped (the payout is unchanged, his call), but they
        # are different facts and were logged as one ("eigentrust 0.0000 < floor"): the
        # §TRUSTPOLICY rule, applied to stakers — unmeasured is a state, not a low score.
        report: Dict[str, Any] = {
            'floor': reputation_floor, 'eligible': 0, 'skipped_unmeasured': 0,
            'skipped_below_floor': 0, 'skipped_paused': 0, 'skipped_distributed_today': 0,
            'unmeasured_dids': [],
        }

        # Pre-load eigentrust scores if a floor is set
        eigentrust_map: Dict[str, float] = {}
        if reputation_floor > 0:
            try:
                from ..models import GlobalTrustVector
                gtv_result = await db.execute(select(GlobalTrustVector))
                for gtv in gtv_result.scalars().all():
                    eigentrust_map[gtv.agent_did] = gtv.global_trust
            except Exception as e:
                logger.warning(f'[StakingRewards] Could not load GlobalTrustVectors: {e}')

        # Base query — locked + registry-active
        stmt = select(Agent).where(
            and_(
                Agent.staked_balance > 0,
                Agent.status == 'active',
                # §5.7: exclude suspended/revoked at enforcement level
                Agent.enforcement_status.notin_(['suspended', 'revoked']),
            )
        )
        result = await db.execute(stmt)
        agents = result.scalars().all()

        eligible_agents = []
        for agent in agents:
            # Already distributed today?
            if agent.last_reward_distribution and \
                    agent.last_reward_distribution.date() >= distribution_date:
                report['skipped_distributed_today'] += 1
                continue

            # §5.7: rewards_paused_until check
            if agent.rewards_paused_until and agent.rewards_paused_until > now:
                logger.debug(
                    f'[StakingRewards] Skipping {agent.did}: rewards paused until '
                    f'{agent.rewards_paused_until}'
                )
                report['skipped_paused'] += 1
                continue

            # §5.7: eigentrust floor check
            if reputation_floor > 0:
                if agent.did not in eigentrust_map:
                    # UNMEASURED: no vector has been computed for this agent. Skipped as before
                    # (D7 is his), but never described as "below the floor".
                    logger.debug(
                        f'[StakingRewards] Skipping {agent.did}: no trust vector yet '
                        f'(unmeasured; floor {reputation_floor})'
                    )
                    report['skipped_unmeasured'] += 1
                    if len(report['unmeasured_dids']) < 50:
                        report['unmeasured_dids'].append(agent.did)
                    continue
                score = eigentrust_map.get(agent.did, 0.0)
                if score < reputation_floor:
                    logger.debug(
                        f'[StakingRewards] Skipping {agent.did}: eigentrust {score:.4f} '
                        f'< floor {reputation_floor}'
                    )
                    report['skipped_below_floor'] += 1
                    continue

            eligible_agents.append(agent)

        report['eligible'] = len(eligible_agents)
        self.last_eligibility_report = report
        if report['skipped_unmeasured'] or report['skipped_below_floor']:
            logger.info(
                f"[StakingRewards] eligibility: {report['eligible']} eligible, "
                f"{report['skipped_unmeasured']} unmeasured (no trust vector yet), "
                f"{report['skipped_below_floor']} below the floor {reputation_floor}, "
                f"{report['skipped_paused']} paused, {report['skipped_distributed_today']} already paid today"
            )
        return eligible_agents
    
    async def distribute_rewards_to_agent(
        self,
        db: AsyncSession,
        agent: Agent,
        distribution_id: str,
        distribution_date: date
    ) -> Dict[str, Any]:
        """Distribute rewards to a single agent."""
        
        # Import here to avoid circular dependency
        from ..models import StakingRewardRecord
        
        try:
            # Get locked amount
            staked_amount = Decimal(str(agent.staked_balance or 0))
            if staked_amount <= 0:
                return {
                    'agent_did': agent.did,
                    'status': 'skipped',
                    'reason': 'No locked balance'
                }
            
            # Get lock tier
            tier_info = await self.get_apy_tier(db, staked_amount)
            
            # Calculate days since last distribution
            if agent.last_reward_distribution:
                days_since = (distribution_date - agent.last_reward_distribution.date()).days
            else:
                # If first distribution, use 1 day
                days_since = 1
            
            # Don't distribute if already done today
            if days_since <= 0:
                return {
                    'agent_did': agent.did,
                    'status': 'skipped',
                    'reason': 'Already distributed today'
                }
            
            # Calculate payout
            total_apy = tier_info['base_apy'] + tier_info.get('lock_bonus_apy', Decimal('0'))
            # §REPBOND (2026-09-05) — the registry's own `staking_reputation` policy may lift
            # the payout for a matured bond / earned volume (a capped multiplier, default off).
            rep_multiplier = Decimal('1')
            rep_detail: Dict[str, Any] = {}
            try:
                from .reputation_bond import staking_multiplier as _staking_multiplier
                rep_multiplier, rep_detail = await _staking_multiplier(db, agent)
            except Exception as _rm_e:  # noqa: BLE001 — a multiplier failure pays the base rate and says so
                logger.warning(f"[StakingRewards] reputation multiplier failed for {agent.did}: {_rm_e}")
            if rep_multiplier != Decimal('1'):
                total_apy = (total_apy * rep_multiplier).quantize(Decimal('0.0001'))
            reward_amount = await self.calculate_daily_reward(
                staked_amount,
                total_apy,
                days_since
            )
            
            # Create payout record
            reward_record = StakingRewardRecord(
                id=str(uuid.uuid4()),
                distribution_id=distribution_id,
                agent_did=agent.did,
                staked_amount=staked_amount,
                apy_rate=total_apy,
                reward_amount=reward_amount,
                days_staked=days_since,
                tier_name=tier_info['tier_name'],
                status='pending',
                created_at=datetime.now(timezone.utc)
            )
            
            # Distribute via TEG funding waterfall (Phase 2, 2026-05-08;
            # §REWARDEVENTS 2026-08-11 rides the shared rail). Source order stays
            # the per-reason reward_funding_waterfall policy — NEVER mints from
            # void. The rail emits ONE TokensTransferred per waterfall leg (the
            # legacy TokensIssued emit here is GONE: it double-books issuance in
            # the projection, and its comment's claim that TEG emits the leg
            # events was false — TEG is policy-blocked for TokensTransferred).
            # The rail also syncs agents.liquid_balance from TEG truth, so the
            # manual increment below is gone too (incrementing on top of the
            # synced value would double-count the cache).
            try:
                res = await fund_reward_via_waterfall(
                    db,
                    target_agent_did=agent.did,
                    amount=reward_amount,
                    reason="staking_reward",
                    reference_id=distribution_id,
                    idempotency_key=f"staking-{distribution_id}-{agent.did}",
                )
                first_tx_id = res["first_transaction_id"] or ''

                if res["status"] != "completed":
                    # Partial legs are committed + emitted + cache-synced by the
                    # rail; record it honestly, never as paid-in-full, and do
                    # not compound a payout that only partially arrived.
                    logger.error(
                        f"Staking funding PARTIAL for {agent.did}: funded "
                        f"{res['funded_amount']} of {reward_amount} "
                        f"(shortfall {res['shortfall']}) — distribution {distribution_id}")
                    reward_record.status = 'partial'
                    reward_record.distributed_at = datetime.now(timezone.utc)
                    reward_record.teg_transaction_id = first_tx_id
                    reward_record.error_message = (
                        f"waterfall exhausted: funded {res['funded_amount']} "
                        f"of {reward_amount}")
                    db.add(reward_record)
                    await db.commit()
                    return {
                        'agent_did': agent.did,
                        'status': 'partial',
                        'reward_amount': str(reward_amount),
                        'funded_amount': res['funded_amount'],
                        'tier': tier_info['tier_name'],
                        'apy_rate': str(total_apy)
                    }

                # Update payout record
                reward_record.status = 'distributed'
                reward_record.distributed_at = datetime.now(timezone.utc)
                reward_record.teg_transaction_id = first_tx_id

                # Update agent (liquid_balance already synced to TEG truth by the rail)
                agent.total_rewards_earned = Decimal(str(agent.total_rewards_earned or 0)) + reward_amount
                agent.last_reward_distribution = datetime.now(timezone.utc)
                agent.staking_tier = tier_info['tier_name']
                
                # If auto-compound is enabled, lock the payouts.
                # §V0045 F2: registry staked_balance and TEG locked_balance are a
                # mirrored pair — compounding ONLY registry-side leaves the payout
                # SPENDABLE on the TEG while the registry counts it as locked (the
                # Ironhand-Alpha +304k drift). Lock on the TEG FIRST; bump the
                # registry lock only if the lock succeeded, else leave the payout
                # liquid this cycle (it compounds on a later distribution).
                if agent.auto_compound_enabled:
                    _compound_locked = False
                    try:
                        await self.teg_client.lock_tokens(agent.did, Decimal(str(reward_amount)))
                        _compound_locked = True
                    except Exception as _lock_err:
                        logger.warning(
                            f"Auto-compound TEG lock failed for {agent.did} "
                            f"({reward_amount} AVT): {_lock_err} — reward stays liquid this cycle"
                        )
                    if _compound_locked:
                        agent.staked_balance = Decimal(str(agent.staked_balance or 0)) + reward_amount
                        agent.liquid_balance -= reward_amount

                        # Log auto-compound event
                        await self.event_emitter.emit(
                            aggregate_id=agent.did,
                            event_type='RewardsAutoCompounded',
                            idempotency_key=f"autocompound-{distribution_id}-{agent.did}",
                            data={
                                'agent_did': agent.did,
                                'amount': str(reward_amount),
                                'new_staked_balance': str(agent.staked_balance),
                                'teg_locked': True
                            }
                        )
                    else:
                        await self.event_emitter.emit(  # §SILENT: keyed like its sibling (emit_event takes no key)
                            aggregate_id=agent.did,
                            event_type='RewardsAutoCompoundSkipped',
                            idempotency_key=f"autocompound-skipped-{distribution_id}-{agent.did}",
                            data={
                                'agent_did': agent.did,
                                'amount': str(reward_amount),
                                'reason': 'teg_lock_failed'
                            }
                        )
                
                # Emit event
                await self.event_emitter.emit(
                    aggregate_id=agent.did,
                    event_type='RewardsDistributed',
                    idempotency_key=f"rewards-dist-{distribution_id}-{agent.did}",
                    data={
                        'agent_did': agent.did,
                        'amount': str(reward_amount),
                        'tier': tier_info['tier_name'],
                        'apy_rate': str(total_apy),
                        'days_staked': days_since,
                        'distribution_id': distribution_id,
                        # §REWARDEVENTS: waterfall execution surfaced here (the
                        # balance-moving TokensTransferred legs carry the money)
                        'transaction_id': first_tx_id,
                        'funded_via': [l.get('source') for l in res['legs']],
                        'leg_count': len(res['legs']),
                    }
                )
                
            except Exception as e:
                logger.error(f"TEG distribution failed for {agent.did}: {e}")
                reward_record.status = 'failed'
                reward_record.error_message = str(e)
            
            # Save payout record
            db.add(reward_record)
            await db.commit()
            
            return {
                'agent_did': agent.did,
                'status': reward_record.status,
                'reward_amount': str(reward_amount),
                'tier': tier_info['tier_name'],
                'apy_rate': str(total_apy)
            }
            
        except Exception as e:
            logger.error(f"Error distributing rewards to {agent.did}: {e}")
            return {
                'agent_did': agent.did,
                'status': 'failed',
                'error': str(e)
            }
    
    async def run_daily_distribution(
        self,
        db: AsyncSession,
        distribution_date: Optional[date] = None,
        initiated_by: str = 'system'
    ) -> Dict[str, Any]:
        """Run the daily reward distribution for all eligible stakers."""
        
        # Import here to avoid circular dependency
        from ..models import StakingDistribution
        
        if not distribution_date:
            distribution_date = date.today()
        
        # Check if distribution already ran today
        existing = await db.execute(
            select(StakingDistribution).where(
                StakingDistribution.distribution_date == distribution_date
            )
        )
        if existing.scalar_one_or_none():
            return {
                'status': 'skipped',
                'reason': f'Distribution already completed for {distribution_date}'
            }
        
        # Create distribution record
        distribution = StakingDistribution(
            id=str(uuid.uuid4()),
            distribution_date=distribution_date,
            distribution_type='daily',
            started_at=datetime.now(timezone.utc),
            status='running',
            initiated_by=initiated_by,
            total_distributed=Decimal('0'),
            total_stakers=0
        )
        db.add(distribution)
        await db.commit()
        
        try:
            # Get eligible stakers
            eligible_agents = await self.get_eligible_stakers(db, distribution_date)
            
            # Track results
            total_distributed = Decimal('0')
            successful = 0
            failed = 0
            results = []
            
            # Distribute to each agent
            for agent in eligible_agents:
                result = await self.distribute_rewards_to_agent(
                    db, agent, distribution.id, distribution_date
                )
                results.append(result)
                
                if result['status'] == 'distributed':
                    successful += 1
                    total_distributed += Decimal(result.get('reward_amount', '0'))
                elif result['status'] == 'failed':
                    failed += 1
            
            # Update distribution record
            distribution.completed_at = datetime.now(timezone.utc)
            distribution.status = 'completed'
            distribution.total_distributed = total_distributed
            distribution.total_stakers = successful
            distribution.distribution_metadata = {
                'successful': successful,
                'failed': failed,
                'skipped': len(eligible_agents) - successful - failed,
                'total_eligible': len(eligible_agents),
                # §TRUSTCHAIN P4.7: why the others were not paid, unmeasured told apart from below-floor
                'eligibility': getattr(self, 'last_eligibility_report', None),
            }
            
            await db.commit()
            
            # Emit distribution completed event
            await self.event_emitter.emit_event(
                aggregate_id='system',
                event_type='DailyDistributionCompleted',
                event_data={
                    'distribution_id': distribution.id,
                    'date': str(distribution_date),
                    'total_distributed': str(total_distributed),
                    'successful_count': successful,
                    'failed_count': failed
                }
            )
            
            # §NOTIFV2 staking.rewards — wired at the SERVICE, the choke point shared by the
            # scheduled worker (background_tasks/staking_distributor.py, whose manual trigger
            # delegates to the same run) and the admin route (routers/staking_rewards.py).
            # Recipients are aggregated PER DEVELOPER, not per agent: a developer locking with
            # twenty agents gets one push with their true total, not twenty pushes with slices.
            # The type is opt-in (`default_enabled={}`) with a 1h coalesce window, so a daily
            # run cannot become a daily spam wave.
            try:
                import asyncio as _aio_n
                from sqlalchemy import text as _sql_text
                paid: dict = {}
                for _r in results:
                    if _r.get('status') == 'distributed':
                        try:
                            _amt = float(_r.get('reward_amount') or 0)
                        except (TypeError, ValueError):
                            continue
                        if _amt > 0 and _r.get('agent_did'):
                            paid[_r['agent_did']] = paid.get(_r['agent_did'], 0.0) + _amt
                if paid:
                    _owner_rows = (await db.execute(_sql_text(
                        "SELECT did, creator_developer_id FROM agents "
                        "WHERE did = ANY(:dids) AND creator_developer_id IS NOT NULL"
                    ), {"dids": list(paid.keys())})).all()
                    per_dev: dict = {}
                    for _did, _dev_id in _owner_rows:
                        per_dev[_dev_id] = per_dev.get(_dev_id, 0.0) + paid.get(_did, 0.0)
                    from agentvault_registry.background_tasks.push_notify import notify
                    for _dev_id, _amt in per_dev.items():
                        _aio_n.create_task(notify(
                            "staking.rewards", [_dev_id],
                            title="Staking rewards distributed",
                            message=f"You earned {_amt:.4f} in staking rewards.",
                            amount=_amt, tags="moneybag", priority="default",
                            click="/ui/#/locks"))
            except Exception:  # noqa: BLE001
                logger.debug("[NOTIFY] staking.rewards emit failed", exc_info=True)

            return {
                'status': 'completed',
                'distribution_id': distribution.id,
                'date': str(distribution_date),
                'total_distributed': str(total_distributed),
                'successful': successful,
                'failed': failed,
                'results': results
            }
            
        except Exception as e:
            logger.error(f"Distribution failed: {e}")
            distribution.status = 'failed'
            distribution.error_message = str(e)
            distribution.completed_at = datetime.now(timezone.utc)
            await db.commit()
            
            return {
                'status': 'failed',
                'distribution_id': distribution.id,
                'error': str(e)
            }


# Singleton instance
_staking_rewards_service = None


def get_staking_rewards_service() -> StakingRewardsService:
    """Get singleton instance of staking rewards service."""
    global _staking_rewards_service
    if _staking_rewards_service is None:
        _staking_rewards_service = StakingRewardsService()
    return _staking_rewards_service
