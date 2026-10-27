"""
CRUD operations for the Enforcement Engine (Sprint 1 §4.2–§4.5).

Functions here are intentionally thin — no business logic.
Business logic lives in services/enforcement_engine.py.

DEFAULT_POLICY_JSON is the canonical factory-default enforcement policy
used when no DB row exists. It is also seeded by f029_enforcement_foundation.
"""
import copy
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from ..models import RegistryEnforcementPolicy, EnforcementAction, ReputationBond

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Factory defaults — single source of truth
# ---------------------------------------------------------------------------

DEFAULT_POLICY_JSON: Dict[str, Any] = {
    "dispute_escalation": {
        "offense_window_days": 90,
        "levels": {
            "1": {
                "slash_percent": 10,
                "action_types": ["slash_liquid", "warn"],
                "pause_days": 0,
                "admin_review_required": False
            },
            "2": {
                "slash_percent": 20,
                "action_types": ["slash_liquid", "pause_rewards"],
                "pause_days": 7,
                "admin_review_required": False
            },
            "3": {
                "slash_percent": 30,
                "action_types": ["slash_liquid", "pause_rewards"],
                "pause_days": 30,
                "admin_review_required": True
            },
            "4": {
                "slash_percent": 50,
                "action_types": ["slash_stake", "suspend"],
                "pause_days": 0,
                "admin_review_required": True
            }
        },
        "avt_volume_tiers": {
            "minor": {"max_amount": 100, "slash_percent_override": 5},
            "major": {"min_amount": 10000, "slash_percent_override_multiplier": 1.5}
        }
    },
    "staking_rewards": {
        "enabled": True,
        "distribution_schedule_cron": "0 0 * * *",
        "auto_compound_enabled": True,
        "auto_compound_fee_percent": 0.0,
        "reputation_floor_for_rewards": 0.05,
        "min_eigentrust_for_rewards": 0.0,
        "paused_agents_skip": True,
        "max_apy_percent": 15.0,
        "min_apy_percent": 1.0,
        "tvl_target_percent": 40.0,
        "decay_steepness_k": 0.05,
        "circuit_breaker_tvl_percent": 75.0,
        "treasury_buffer_warning_days": 30,
        "treasury_minimum_reserve_avt": 0,
        "lock_premium_base_rate_percent": 2.0,
        "slashing_insurance_prohibited": True,
        "lock_tiers": [
            {"days": 0,   "label": "flex",  "premium_percent": 0.0, "ve_multiplier": 0.01},
            {"days": 30,  "label": "30d",   "premium_percent": 1.4, "ve_multiplier": 0.08},
            {"days": 90,  "label": "90d",   "premium_percent": 2.8, "ve_multiplier": 0.25},
            {"days": 180, "label": "180d",  "premium_percent": 3.9, "ve_multiplier": 0.49},
            {"days": 365, "label": "365d",  "premium_percent": 5.2, "ve_multiplier": 1.00},
        ],
    },
    # §FRAMEPOLICY. The fee is charged from this block: services/transaction_fee_service._load_rates reads
    # base_rate_percent and max_rate_percent (the active policy's, else these defaults); velocity_scaling_factor and
    # destination are declared and published on the card, and no charge path reads them (§DOCSFIX D6-462, D6-393).
    # The block was aligned with LOCKED_PARAMS (2026-09-11) because our own factory default FAILED our own admission
    # validator on two HIGH violations: velocity_scaling_factor 0.1 against a locked 1.0, and a `destination` the
    # locked set requires and the document never carried. A frame submitting its real running policy would have been
    # refused.
    # ⚠ The two rates here are the running fee wherever no active policy names its own: changing them changes what
    # every transfer pays.
    "transaction_fees": {
        "base_rate_percent": 0.5,
        "max_rate_percent": 5.0,
        "velocity_scaling_factor": 1.0,
        "destination": "treasury_recycle"
    },
    # §BONDFILL-3 (2026-09-11) — this section used to hold a SECOND copy of every bond rule
    # (`amount_avt`, `min_transactions`, `min_age_days`, `min_eigentrust`), and it was the copy
    # the gate read while the card published the `enforcement.*` one. One rule, one key: the
    # canonical keys live under `enforcement` below, and the old names are read-only aliases
    # (services/frame_policy.DEPRECATED_ALIASES). The section stays so a frame's own document,
    # which may carry the old keys, still validates.
    "reputation_bond": {},
    # §REPBOND (2026-09-05) — the ORDER a slash drains from, per registry (the
    # Commander: "configurable like the treasury and fee pools … relevant to
    # security"). Executed by enforcement_engine under ENFORCEMENT_SLASH_MODE
    # (cache = today's cache-only write, shadow = plan + log, enforce = move).
    # max_percent caps each source at a share of the REQUESTED amount.
    "slash_waterfall": [
        {"source": "bond", "max_percent": 100},
        {"source": "stake", "max_percent": 100},
        {"source": "liquid", "max_percent": 100},
    ],
    # §REPBOND — whether and how a matured bond / earned volume lifts the staking
    # payout (a MULTIPLIER on the APY at payout time, capped; default off — every
    # registry decides for its own providers).
    "staking_reputation": {
        "enabled": False,
        "matured_bond_multiplier": 1.0,
        "volume_tiers": [],
        "cap": 1.0,
    },
    # §FRAMEPOLICY (2026-09-11) — EVERY number here is the number the live code
    # already used, so a frame with no policy row does not move when governance
    # starts reading this block. Measured before the change: the document said
    # standard_quorum 20.0 and policy_change_quorum 33.0 while
    # routers/governance.py used 10.0 and 20.0 — and had, unread, since April.
    # The document lost that argument on purpose: a default that does not match
    # the running system is not a default, it is a silent behaviour change
    # waiting for the roll that finally reads it.
    # ⚠ `policy_proposal_{quorum,pass}_percent` were a SECOND name for the
    # policy-change thresholds. Removed here, still accepted on input as a
    # deprecated alias (services/frame_policy.DEPRECATED_ALIASES) so a frame
    # that wrote the old key keeps its meaning.
    "governance": {
        "policy_change_requires_proposal": True,
        "min_stake_to_propose_policy": 1000,
        "standard_quorum_percent": 10.0,
        "standard_pass_percent": 50.0,
        "min_stake_to_propose_avt": 100,
        "policy_change_quorum_percent": 20.0,
        "policy_change_pass_percent": 66.0,
        "max_lock_days": 365,
        "flexible_stake_ve_multiplier_max": 0.01,
    },
    "reputation": {
        "eigentrust": {
            "teleportation_alpha": 0.15,
            "convergence_epsilon": 1e-6,
            "max_iterations": 100,
            "cosine_similarity_threshold": 0.30,
            "epoch_decay": 0.95,
            "volume_weight_exponent": 0.3,
        },
        "epoch_duration_hours": 1,
    },
    "supply_integrity": {
        "supply_invariant_check_enabled": True,
        "auto_lockdown_on_invariant_breach": True,
        "opa_minting_ban_for_federated_teg": True,
        "eventstore_double_entry_validation": True,
        "genesis_only_minting": True,
        "cryptographic_mint_signatures_required": True,
    },
    "enforcement": {
        "force_unstake_enabled": True,
        "force_unstake_min_penalty_percent": 10,
        "fourth_offense_auto_suspend": True,
        "slashing_insurance": "PROHIBITED",
        "reputation_bond_min_avt": 50,
        "bond_maturity_min_transactions": 10,
        "bond_maturity_min_age_days": 30,
        # §BONDFILL-3 — the relative trust gate and the maturity unlock. Defaults are the floor of
        # the percentile bound (the median), the floor of the evidence bound, and the share he
        # approved: 60 % back at maturity, 40 % stays bonded.
        "bond_maturity_min_trust_percentile": 50,
        "bond_maturity_min_rated_peers": 3,
        "bond_maturity_releases_percent": 60,
        "offense_window_days": 90,
        "frozen_balance_release_days": 90,
    },
    # §TRUSTPOLICY (2026-09-11) — what this frame DOES about a peer it has come to
    # distrust. Until now `bayesian_discount` was written by the settlement
    # reactor, rendered on three surfaces, and consumed for a decision in exactly
    # ONE place in the whole system (the EventStore's federation vote weight), so
    # a peer could settle badly for a month and the only consequence was a smaller
    # number on a page.
    #
    # ⚠ `mode` DEFAULTS TO "observe": every threshold is evaluated, every crossing
    # is reported, and NOTHING is refused. This is money-adjacent and fail-open is
    # the correct posture until a frame opts in, exactly like ENFORCEMENT_SLASH_MODE.
    #
    # ⚠ `min_interactions` IS LOAD-BEARING, NOT A TUNING KNOB. Measured on EU:
    # hochiminh and shenzhen sit at 0.5000 with ZERO interactions because that is
    # the Beta(1,1) prior — "no evidence either way" — and a threshold that reads
    # 0.5 as the worst peers on the frame would punish the two nobody has ever
    # transacted with. Below this count a peer is UNMEASURED and no action fires
    # whatever the number says.
    "peer_trust": {
        "mode": "observe",
        "min_interactions": 10,
        "warn_below": 0.70,
        "restrict_below": 0.50,
        "suspend_below": 0.30,
        "recover_margin": 0.05,
    },
    "correlation_penalty": {
        "same_registry_multiplier": 2.0,
        "window_hours": 24
    }
}


# ---------------------------------------------------------------------------
# RegistryEnforcementPolicy CRUD
# ---------------------------------------------------------------------------

async def get_active_policy(db: AsyncSession) -> Optional[RegistryEnforcementPolicy]:
    """Return the currently active enforcement policy row, or None."""
    result = await db.execute(
        select(RegistryEnforcementPolicy).where(
            RegistryEnforcementPolicy.is_active == True
        )
    )
    return result.scalar_one_or_none()


async def get_policy_defaults() -> Dict[str, Any]:
    """Return a copy of the factory default policy JSON."""
    return copy.deepcopy(DEFAULT_POLICY_JSON)


SLASH_WATERFALL_SOURCES = ("bond", "stake", "liquid")


def validate_policy_json(policy_json: Dict[str, Any]) -> List[str]:
    """§REPBOND — shape checks for the sections a wrong value would turn into a money
    defect. Returns the list of problems (empty = valid). Structural only: it never
    decides taste, only whether the engine can execute what is written."""
    errs: List[str] = []
    if not isinstance(policy_json, dict):
        return ["policy_json must be an object"]
    wf = policy_json.get("slash_waterfall")
    if wf is not None:
        if not isinstance(wf, list) or not wf:
            errs.append("slash_waterfall must be a non-empty list of {source, max_percent}")
        else:
            seen = set()
            for i, step in enumerate(wf):
                if not isinstance(step, dict):
                    errs.append(f"slash_waterfall[{i}] must be an object"); continue
                src = step.get("source")
                if src not in SLASH_WATERFALL_SOURCES:
                    errs.append(f"slash_waterfall[{i}].source must be one of {SLASH_WATERFALL_SOURCES}")
                elif src in seen:
                    errs.append(f"slash_waterfall repeats source {src!r}")
                seen.add(src)
                pct = step.get("max_percent", 100)
                if not isinstance(pct, (int, float)) or isinstance(pct, bool) or pct < 0 or pct > 100:
                    errs.append(f"slash_waterfall[{i}].max_percent must be a number in 0..100")
    sr = policy_json.get("staking_reputation")
    if sr is not None:
        if not isinstance(sr, dict):
            errs.append("staking_reputation must be an object")
        else:
            if not isinstance(sr.get("enabled", False), bool):
                errs.append("staking_reputation.enabled must be a boolean")
            for k in ("matured_bond_multiplier", "cap"):
                v = sr.get(k, 1.0)
                if not isinstance(v, (int, float)) or isinstance(v, bool) or v < 1.0 or v > 10.0:
                    errs.append(f"staking_reputation.{k} must be a number in 1.0..10.0")
            tiers = sr.get("volume_tiers", [])
            if not isinstance(tiers, list):
                errs.append("staking_reputation.volume_tiers must be a list")
            else:
                last = -1.0
                for i, t in enumerate(tiers):
                    if not isinstance(t, dict):
                        errs.append(f"staking_reputation.volume_tiers[{i}] must be an object"); continue
                    mv, mult = t.get("min_volume"), t.get("multiplier")
                    if not isinstance(mv, (int, float)) or isinstance(mv, bool) or mv < 0:
                        errs.append(f"staking_reputation.volume_tiers[{i}].min_volume must be a number >= 0")
                    elif mv <= last:
                        errs.append("staking_reputation.volume_tiers must be strictly ascending by min_volume")
                    else:
                        last = mv
                    if not isinstance(mult, (int, float)) or isinstance(mult, bool) or mult < 1.0 or mult > 10.0:
                        errs.append(f"staking_reputation.volume_tiers[{i}].multiplier must be a number in 1.0..10.0")
    rb = policy_json.get("reputation_bond")
    if rb is not None:
        if not isinstance(rb, dict):
            errs.append("reputation_bond must be an object")
        else:
            amt = rb.get("amount_avt")
            if amt is not None and (not isinstance(amt, (int, float)) or isinstance(amt, bool) or amt < 0):
                errs.append("reputation_bond.amount_avt must be a number >= 0")
    return errs


async def update_policy(
    db: AsyncSession,
    new_policy_json: Dict[str, Any],
    modified_by: str
) -> RegistryEnforcementPolicy:
    """
    Deactivate current policy, create new version.
    Returns the new active policy.
    """
    problems = validate_policy_json(new_policy_json)
    if problems:
        raise ValueError("; ".join(problems))
    current = await get_active_policy(db)
    previous_id = None

    if current:
        previous_id = current.id
        current.is_active = False
        new_version = current.version + 1
    else:
        new_version = 1

    new_policy = RegistryEnforcementPolicy(
        policy_json=new_policy_json,
        version=new_version,
        modified_by=modified_by,
        modified_at=datetime.now(timezone.utc),
        is_active=True,
        previous_version=previous_id
    )
    db.add(new_policy)
    await db.commit()
    await db.refresh(new_policy)
    logger.info(f"[crud_enforcement] Policy updated to v{new_version} by {modified_by}")
    return new_policy


# ---------------------------------------------------------------------------
# EnforcementAction CRUD
# ---------------------------------------------------------------------------

async def create_enforcement_action(
    db: AsyncSession,
    agent_did: str,
    action_type: str,
    trigger: str,
    trigger_reference: Optional[str],
    amount: Optional[int],
    escalation_level: int,
    policy_version: int,
    correlation_count: int = 0,
    correlation_multi: float = 1.0,
    status: str = 'pending_approval'
) -> EnforcementAction:
    """Create and persist a new EnforcementAction record."""
    action = EnforcementAction(
        id=str(uuid.uuid4()),
        agent_did=agent_did,
        action_type=action_type,
        trigger=trigger,
        trigger_reference=trigger_reference,
        amount=amount,
        status=status,
        escalation_level=escalation_level,
        policy_version=policy_version,
        correlation_count=correlation_count,
        correlation_multi=correlation_multi,
        created_at=datetime.now(timezone.utc)
    )
    db.add(action)
    await db.commit()
    await db.refresh(action)
    return action


async def get_enforcement_action_by_id(
    db: AsyncSession,
    action_id: str
) -> Optional[EnforcementAction]:
    """Fetch a single enforcement action by PK."""
    result = await db.execute(
        select(EnforcementAction).where(EnforcementAction.id == action_id)
    )
    return result.scalar_one_or_none()


async def get_pending_enforcement_actions(
    db: AsyncSession,
    action_type: Optional[str] = None,
    page: int = 1,
    per_page: int = 20
) -> List[EnforcementAction]:
    """Return paginated list of actions with status='pending_approval'."""
    offset = (page - 1) * per_page
    stmt = select(EnforcementAction).where(
        EnforcementAction.status == 'pending_approval'
    )
    if action_type:
        stmt = stmt.where(EnforcementAction.action_type == action_type)
    stmt = stmt.order_by(EnforcementAction.created_at.desc()).offset(offset).limit(per_page)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def approve_enforcement_action(
    db: AsyncSession,
    action_id: str,
    approved_by: str
) -> Optional[EnforcementAction]:
    """Mark action as approved. Caller must then call engine.execute_enforcement_action()."""
    action = await get_enforcement_action_by_id(db, action_id)
    if not action or action.status != 'pending_approval':
        return None
    action.approved_by = approved_by
    # Keep status as pending_approval until execute_enforcement_action sets it to 'executed'
    await db.commit()
    await db.refresh(action)
    return action


async def reject_enforcement_action(
    db: AsyncSession,
    action_id: str,
    rejected_reason: str
) -> Optional[EnforcementAction]:
    """Reject a pending enforcement action."""
    action = await get_enforcement_action_by_id(db, action_id)
    if not action or action.status != 'pending_approval':
        return None
    action.status = 'rejected'
    action.rejected_reason = rejected_reason
    await db.commit()
    await db.refresh(action)
    return action


async def get_agent_enforcement_status(
    db: AsyncSession,
    agent_did: str,
    recent_limit: int = 10
) -> Dict[str, Any]:
    """
    Return a summary of an agent's enforcement state.
    Used by GET /admin/enforcement/agents/{did}/status.
    """
    from ..models import Agent, GlobalTrustVector
    from sqlalchemy import desc

    agent_result = await db.execute(select(Agent).where(Agent.did == agent_did))
    agent = agent_result.scalar_one_or_none()
    if not agent:
        return {}

    gtv_result = await db.execute(
        select(GlobalTrustVector).where(GlobalTrustVector.agent_did == agent_did)
    )
    gtv = gtv_result.scalar_one_or_none()

    bond_result = await db.execute(
        select(ReputationBond).where(ReputationBond.agent_did == agent_did)
    )
    bond = bond_result.scalar_one_or_none()

    actions_result = await db.execute(
        select(EnforcementAction)
        .where(EnforcementAction.agent_did == agent_did)
        .order_by(desc(EnforcementAction.created_at))
        .limit(recent_limit)
    )
    recent_actions = list(actions_result.scalars().all())

    return {
        'did': agent_did,
        'offense_count': agent.offense_count,
        'enforcement_level': agent.enforcement_level,
        'enforcement_status': agent.enforcement_status,
        'rewards_paused_until': (
            agent.rewards_paused_until.isoformat()
            if agent.rewards_paused_until else None
        ),
        'reputation_score': agent.reputation_score,
        'eigentrust_score': gtv.global_trust if gtv else 0.0,
        'reputation_bond_status': agent.reputation_bond_status,
        'reputation_bond_amount': agent.reputation_bond_amount,
        'bond': {
            'status': bond.status,
            'amount': bond.amount,
            'locked_at': bond.locked_at.isoformat() if bond else None,
        } if bond else None,
        'recent_actions': [
            {
                'id': a.id,
                'action_type': a.action_type,
                'trigger': a.trigger,
                'status': a.status,
                'amount': a.amount,
                'escalation_level': a.escalation_level,
                'created_at': a.created_at.isoformat()
            }
            for a in recent_actions
        ]
    }
