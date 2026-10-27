"""
EnforcementEngine — Economic Engine Phase 1 §4.6

Evaluates agents against the active RegistryEnforcementPolicy and applies
the correct escalation level when a dispute is lost.

Entry points:
  evaluate_dispute_outcome(db, defendant_did, dispute_id, disputed_amount)
      Called by crud_disputes.update_dispute_ruling() when ruling=IN_FAVOR_OF_COMPLAINANT.

  check_reputation_thresholds(db, agent_did)
      NOT CALLED (§DOCSFIX CB-513): nothing in the registry wires it to the
      EigenTrust recompute (core/reputation_manager.py does not call it), so a
      reputation threshold creates no enforcement action. Wiring it is a
      product decision, not made here.

  execute_enforcement_action(db, action)
      Execute a single EnforcementAction that is in pending_approval state
      (after admin approval) or immediately when no review is required.
"""
import copy
import logging
import uuid
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Tuple, Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func

from ..models import Agent, EnforcementAction, GlobalTrustVector
from ..crud.crud_enforcement import (
    get_policy_defaults,
    create_enforcement_action,
    get_enforcement_action_by_id,
    DEFAULT_POLICY_JSON,
)
from ..event_emitter import get_event_emitter

logger = logging.getLogger(__name__)

# §MONEY-R21: how often a "slash" touched only the registry cache and left the TEG
# untouched. Non-zero here means enforcement is cosmetic — the number an operator
# needs before deciding whether to make slashes real (HARD STOP 4).
try:
    from prometheus_client import Counter as _R21Counter
    ENFORCEMENT_CACHE_ONLY_SLASH = _R21Counter(
        "registry_enforcement_cache_only_slash_total",
        "Enforcement slashes applied to the registry balance cache only, with no TEG movement",
        ["kind"],
    )
except Exception:  # noqa: BLE001 — metrics never break enforcement
    ENFORCEMENT_CACHE_ONLY_SLASH = None

try:
    from prometheus_client import Counter as _WfCounter
    ENFORCEMENT_SLASH_WATERFALL = _WfCounter(
        "registry_enforcement_slash_waterfall_total",
        "Slash waterfall steps that absorbed value (shadow = would have; enforce = did)",
        ["mode", "source"],
    )
except Exception:  # noqa: BLE001
    ENFORCEMENT_SLASH_WATERFALL = None

try:
    from prometheus_client import Counter as _WfDefaultCounter
    ENFORCEMENT_SLASH_WATERFALL_DEFAULTED = _WfDefaultCounter(
        "registry_enforcement_slash_waterfall_defaulted_total",
        "Slashes that drained in the factory-default order because the resolved policy carried no waterfall",
        ["reason"],
    )
except Exception:  # noqa: BLE001
    ENFORCEMENT_SLASH_WATERFALL_DEFAULTED = None


def _waterfall_or_the_default(policy: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The ORDER a slash drains from: the frame's resolved `slash_waterfall`, else THE factory default.

    §BATCH0911 (2026-09-11) — this was a second inline literal of the default, named at §FRAMEPOLICY
    and left because it sits on a money path. Measured before removing it: the literal equalled
    `DEFAULT_POLICY_JSON["slash_waterfall"]` byte for byte, and it was still REACHABLE — admission
    skips a stored `null` (`validate_policy_json` checks only a present value), `frame_policy.resolve`
    lets that null replace the default, and in exactly that state `explain()` reports the frame as
    running the default. The readout and the engine agreed only because two copies were equal.

    The fallback stays: a row written around the validator must not silently switch off the money
    half of enforcement. But it is now the same object the readout reports, and it says when it fires.
    Falsy-only, exactly the `or` it replaces, so every state behaves as it did.
    """
    wf = policy.get("slash_waterfall") if isinstance(policy, dict) else None
    if wf:
        return wf
    reason = "null" if wf is None else ("empty" if isinstance(wf, list) else type(wf).__name__)
    logger.warning(
        "[EnforcementEngine] the resolved policy carries no slash_waterfall (%s): draining in the "
        "factory-default order, the order the policy readout reports for this frame", reason)
    if ENFORCEMENT_SLASH_WATERFALL_DEFAULTED is not None:
        try:
            ENFORCEMENT_SLASH_WATERFALL_DEFAULTED.labels(reason=reason).inc()
        except Exception:  # noqa: BLE001 — metrics never break enforcement
            pass
    return copy.deepcopy(DEFAULT_POLICY_JSON["slash_waterfall"])


class EnforcementEngine:
    """
    Loads the active RegistryEnforcementPolicy and executes the dispute
    escalation ladder, correlation multiplier, and AVT volume tier overrides.
    """

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    async def evaluate_dispute_outcome(
        self,
        db: AsyncSession,
        defendant_did: str,
        dispute_id: str,
        disputed_amount: int = 0,
    ) -> Optional[EnforcementAction]:
        """
        Called by crud_disputes.update_dispute_ruling() when the ruling
        goes against the defendant.

        Returns the created EnforcementAction (status may be
        'pending_approval' or 'executed').
        """
        policy = await self._load_policy(db)

        # Step 1 — count recent offenses
        offense_count = await self._count_recent_offenses(db, defendant_did, policy)
        escalation_level = self._determine_escalation_level(offense_count, policy)

        # Step 2 — AVT volume tier override
        volume_tier = self._check_avt_volume_tier(disputed_amount, policy)

        # Step 3 — correlation multiplier
        corr_count, corr_multi = await self._calculate_correlation_multiplier(
            db, defendant_did, policy
        )

        # Step 4 — resolve action types and slash percent from policy
        level_config = policy.get("dispute_escalation", {}).get(
            "levels", DEFAULT_POLICY_JSON["dispute_escalation"]["levels"]
        ).get(str(escalation_level), {})

        action_types: List[str] = level_config.get(
            "action_types", ["slash_liquid", "warn"]
        )
        slash_percent: float = level_config.get("slash_percent", 10)
        pause_days: int = level_config.get("pause_days", 0)
        admin_required: bool = level_config.get("admin_review_required", False)

        # Apply volume tier slash override if any
        if volume_tier:
            if "slash_percent_override" in volume_tier:
                slash_percent = volume_tier["slash_percent_override"]
            elif "slash_percent_override_multiplier" in volume_tier:
                slash_percent = slash_percent * volume_tier["slash_percent_override_multiplier"]

        # Apply correlation multiplier
        slash_percent = min(100.0, slash_percent * corr_multi)

        # Step 5 — update agent offense tracking
        agent = await self._get_agent(db, defendant_did)
        if not agent:
            logger.warning(f"[EnforcementEngine] Agent {defendant_did} not found — skipping")
            return None

        agent.offense_count = (agent.offense_count or 0) + 1
        agent.last_offense_at = datetime.now(timezone.utc)
        agent.enforcement_level = escalation_level

        # Step 6 — rewards pause
        if pause_days > 0:
            agent.rewards_paused_until = datetime.now(timezone.utc) + timedelta(days=pause_days)

        # Step 7 — auto-suspend at level 4
        if escalation_level >= 4 and "suspend" in action_types:
            if agent.enforcement_status not in ("suspended", "revoked"):
                agent.enforcement_status = "suspended"
                agent.status = "suspended"

        # Step 8 — determine slash amount
        slash_amount: Optional[int] = None
        primary_action = "warn"

        if disputed_amount > 0 and slash_percent > 0:
            # §DOCSFIX D6-439: the correlation multiplier is already in slash_percent (step 4, capped at 100%); it was
            # applied here a second time, which squared a correlated slash and took it past the disputed amount
            slash_amount = max(Decimal("1"), Decimal(str(disputed_amount)) * Decimal(str(slash_percent)) / Decimal("100"))
            if "slash_stake" in action_types:
                primary_action = "slash_stake"
            elif "slash_liquid" in action_types:
                primary_action = "slash_liquid"

        # Step 9 — create EnforcementAction record
        action_status = "pending_approval"
        # We always create in pending_approval; caller executes if admin_required=False

        policy_version = await self._policy_version(db)

        action = await create_enforcement_action(
            db=db,
            agent_did=defendant_did,
            action_type=primary_action,
            trigger="dispute_ruling",
            trigger_reference=str(dispute_id),
            amount=slash_amount,
            escalation_level=escalation_level,
            policy_version=policy_version,
            correlation_count=corr_count,
            correlation_multi=round(corr_multi, 4),
            status="pending_approval",
        )

        await db.commit()

        # Step 10 — if no admin review required, execute immediately
        if not admin_required:
            action = await self.execute_enforcement_action(db, action)

        # Emit to EventStore
        try:
            emitter = get_event_emitter()
            await emitter.emit_event(
                aggregate_id=defendant_did,
                event_type="EnforcementActionCreated",
                event_data={
                    "action_id": action.id,
                    "agent_did": defendant_did,
                    "action_type": primary_action,
                    "trigger": "dispute_ruling",
                    "dispute_id": str(dispute_id),
                    "escalation_level": escalation_level,
                    "amount": slash_amount,
                    "status": action.status,
                },
            )
        except Exception as e:
            logger.warning(f"[EnforcementEngine] EventStore emit failed: {e}")

        return action

    async def execute_enforcement_action(
        self,
        db: AsyncSession,
        action: EnforcementAction,
    ) -> EnforcementAction:
        """
        Execute a single EnforcementAction.

        For slash_liquid:   deduct from agent.liquid_balance
        For slash_stake:    call ForceUnstakeService
        For pause_rewards:  set agent.rewards_paused_until
        For suspend:        set agent.enforcement_status = 'suspended'
        For reinstate:      set agent.enforcement_status = 'active'
        For warn:           no balance change, just mark executed

        Sets action.status = 'executed', action.executed_at = now().
        """
        agent = await self._get_agent(db, action.agent_did)
        if not agent:
            action.status = "failed"
            await db.commit()
            return action

        try:
            # §REPBOND (2026-09-05) — the per-registry SLASH WATERFALL (policy
            # `slash_waterfall`: bond → stake → liquid by default) behind its own knob
            # ENFORCEMENT_SLASH_MODE: cache = the branches below, byte-identical;
            # shadow = plan + log + the branches below; enforce = the plan MOVES money
            # through the escrow rails (R21's money half) and the branches are skipped.
            _wf_handled = False
            if action.action_type in ("slash_liquid", "slash_stake") and action.amount:
                from .reputation_bond import slash_mode as _slash_mode
                _mode = _slash_mode()
                if _mode in ("shadow", "enforce"):
                    _wf_handled = await self._slash_waterfall(db, agent, action, mode=_mode)
            if _wf_handled:
                pass
            elif action.action_type == "slash_liquid" and action.amount:
                # §MONEY-R21 (2026-09-04) — THE LOG USED TO LIE, AND ONLY THE LOG
                # IS CHANGED HERE.
                #
                # This writes the REGISTRY'S CACHE and nothing else: the TEG never
                # moves, so the next balance sync from TEG truth reverts it or
                # leaves drift. It said "Slashed {deduct} liquid from {did}", which
                # reads as money taken. Nothing was taken.
                #
                # Worse, `deduct` is capped by that same stale cache, so a ruling
                # under-slashes: MEASURED by the nightly money smoke 2026-09-03
                # (F13) — frame-c paid 0.3475 of the 1 requested while the
                # defendant actually held 1.3475 on the TEG.
                #
                # ⚠ MAKING THE SLASH REAL IS A SEPARATE, HIS-WORD CHANGE. It moves
                # real money on the live fleet the moment an enforcement action
                # fires (HARD STOP 4), so it is NOT done here. Until then the rail
                # reports honestly instead of claiming a slash it did not perform.
                deduct = min(action.amount, agent.liquid_balance or 0)
                agent.liquid_balance = (agent.liquid_balance or 0) - deduct
                if ENFORCEMENT_CACHE_ONLY_SLASH is not None:
                    try:
                        ENFORCEMENT_CACHE_ONLY_SLASH.labels(kind="slash_liquid").inc()
                    except Exception:  # noqa: BLE001
                        pass
                logger.warning(
                    "[EnforcementEngine] slash_liquid %s: wrote %s to the REGISTRY CACHE "
                    "ONLY for %s (requested %s, capped by the cached balance). The TEG did "
                    "NOT move and the next balance sync will revert this — the agent has "
                    "not actually been slashed. §MONEY-R21.",
                    action.id, deduct, action.agent_did, action.amount,
                )

            elif action.action_type == "slash_stake" and action.amount:
                from .force_unstake import get_force_unstake_service, ForceUnstakeError
                svc = get_force_unstake_service()
                try:
                    await svc.force_unstake_for_slash(
                        db=db,
                        agent_did=action.agent_did,
                        required_amount=action.amount,
                        enforcement_action_id=action.id,
                        reason=f"Enforcement level {action.escalation_level} dispute slash",
                    )
                except ForceUnstakeError as e:
                    logger.warning(
                        f"[EnforcementEngine] Force-unstake failed, falling back to liquid: {e}"
                    )
                    # §MONEY-R21: same cache-only write as slash_liquid above.
                    deduct = min(action.amount, agent.liquid_balance or 0)
                    agent.liquid_balance = (agent.liquid_balance or 0) - deduct
                    if ENFORCEMENT_CACHE_ONLY_SLASH is not None:
                        try:
                            ENFORCEMENT_CACHE_ONLY_SLASH.labels(kind="slash_stake_fallback").inc()
                        except Exception:  # noqa: BLE001
                            pass
                    logger.warning(
                        "[EnforcementEngine] slash_stake fallback %s: wrote %s to the "
                        "REGISTRY CACHE ONLY for %s. The TEG did NOT move. §MONEY-R21.",
                        action.id, deduct, action.agent_did,
                    )

            elif action.action_type == "pause_rewards":
                pause_days = 7  # default; policy already set rewards_paused_until in evaluate
                if not agent.rewards_paused_until or \
                        agent.rewards_paused_until < datetime.now(timezone.utc):
                    agent.rewards_paused_until = (
                        datetime.now(timezone.utc) + timedelta(days=pause_days)
                    )

            elif action.action_type == "resume_rewards":
                agent.rewards_paused_until = None

            elif action.action_type == "suspend":
                agent.enforcement_status = "suspended"
                agent.status = "suspended"

            elif action.action_type == "reinstate":
                agent.enforcement_status = "active"
                agent.status = "active"
                agent.rewards_paused_until = None

            # warn: no balance change

            action.status = "executed"
            action.executed_at = datetime.now(timezone.utc)
            await db.commit()

        except Exception as e:
            logger.error(f"[EnforcementEngine] Execute failed: {e}", exc_info=True)
            action.status = "failed"
            await db.commit()

        return action

    async def check_reputation_thresholds(
        self,
        db: AsyncSession,
        agent_did: str,
    ) -> List[EnforcementAction]:
        """
        Check agent's eigentrust score against policy thresholds after
        an epoch recompute. Creates enforcement actions for crossed thresholds.

        Nothing calls this in this release (see the module docstring).
        """
        policy = await self._load_policy(db)
        rep_policy = policy.get("staking_rewards", {})
        rep_floor = rep_policy.get("min_eigentrust_for_rewards", 0.0)

        gtv_result = await db.execute(
            select(GlobalTrustVector).where(GlobalTrustVector.agent_did == agent_did)
        )
        gtv = gtv_result.scalar_one_or_none()
        if not gtv:
            return []

        actions: List[EnforcementAction] = []
        policy_version = await self._policy_version(db)

        if rep_floor > 0 and gtv.global_trust < rep_floor:
            agent = await self._get_agent(db, agent_did)
            if agent:
                now = datetime.now(timezone.utc)
                if not agent.rewards_paused_until or agent.rewards_paused_until < now:
                    agent.rewards_paused_until = now + timedelta(days=7)
                    await db.commit()

                action = await create_enforcement_action(
                    db=db,
                    agent_did=agent_did,
                    action_type="pause_rewards",
                    trigger="reputation_threshold",
                    trigger_reference=f"eigentrust={gtv.global_trust:.4f}<floor={rep_floor}",
                    amount=None,
                    escalation_level=1,
                    policy_version=policy_version,
                    status="executed",
                )
                action.executed_at = datetime.now(timezone.utc)
                await db.commit()
                actions.append(action)
                logger.info(
                    f"[EnforcementEngine] Rewards paused for {agent_did}: "
                    f"eigentrust={gtv.global_trust:.4f} < floor={rep_floor}"
                )

        return actions

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _policy_version(self, db: AsyncSession) -> int:
        """The version of the policy this frame is running, as `frame_policy.load()` reports it.

        §BATCH0911 (his decision 2, 2026-09-11) — this was `row.version if row else 1`, and the
        first STORED row is also version 1 (`crud_enforcement.update_policy`), so an action taken
        under the factory default and one taken under the first amendment recorded the same number.
        The factory default is version 0 everywhere else (the card, the compliance endpoints, the
        tally), and now in this audit column too. Measured before the change: 0 enforcement actions
        on EU and on ASIA, so no stored row carries the old fallback.
        """
        from .frame_policy import load as _load_frame_policy
        return (await _load_frame_policy(db)).version

    async def _load_policy(self, db: AsyncSession) -> Dict[str, Any]:
        """The frame's RESOLVED policy document (the row deep-merged onto the defaults).

        §BATCH0911 — this returned the RAW row, so a frame whose row predates a section read nothing
        for it and each rule fell to this engine's own inline literal (`levels`, `offense_window_days`,
        `correlation_penalty`, the rewards floor): the partial-row defect `frame_policy.resolve`
        exists to close, still open in the one module that acts on it. Measured before the change,
        every value this engine reads is identical raw vs resolved on EU (its row carries these
        sections) and on ASIA (no row), so the switch is inert where it runs today.
        """
        from .frame_policy import load as _load_frame_policy
        return (await _load_frame_policy(db)).doc

    async def _slash_waterfall(self, db: AsyncSession, agent: Agent, action: EnforcementAction,
                               *, mode: str) -> bool:
        """§REPBOND — drain the requested slash in the registry's configured ORDER, each
        source capped at `max_percent` of the request. shadow: compute + log the plan,
        return False so today's cache-only write still runs. enforce: forfeit from the
        bond (bookkeeping — the treasury already holds it), force-unstake from the stake
        (real), and move liquid agent → treasury through the escrow deposit rail (real,
        fee-free, Δ=0); return True. A shortfall is logged and counted, never invented."""
        from .reputation_bond import (policy_json as _rb_policy, load_bond as _rb_load_bond,
                                      forfeit as _rb_forfeit, BONDED as _RB_BONDED)
        policy = await _rb_policy(db)
        waterfall = _waterfall_or_the_default(policy)
        requested = Decimal(str(action.amount))
        remaining = requested
        plan: List[Dict[str, Any]] = []
        for step in waterfall:
            if remaining <= 0:
                break
            src = step.get("source")
            try:
                cap = (requested * Decimal(str(step.get("max_percent", 100))) / Decimal(100))
            except Exception:  # noqa: BLE001
                cap = requested
            take = min(remaining, cap)
            if take <= 0:
                continue
            absorbed = Decimal(0)
            note = None
            if src == "bond":
                bond = await _rb_load_bond(db, agent.did)
                held = Decimal(str(bond.amount or 0)) if (bond is not None and bond.status in _RB_BONDED) else Decimal(0)
                take = min(take, held)
                if take > 0:
                    if mode == "enforce":
                        absorbed = await _rb_forfeit(db, agent, amount=take,
                                                     reason=f"enforcement {action.action_type} L{action.escalation_level}",
                                                     ref=f"slash-{action.id}-bond", actor="enforcement_engine")
                    else:
                        absorbed = take
            elif src == "stake":
                staked = Decimal(str(agent.staked_balance or 0))
                take = min(take, staked)
                if take > 0:
                    if mode == "enforce":
                        from .force_unstake import get_force_unstake_service, ForceUnstakeError
                        try:
                            await get_force_unstake_service().force_unstake_for_slash(
                                db=db, agent_did=agent.did, required_amount=take,
                                enforcement_action_id=action.id,
                                reason=f"Enforcement level {action.escalation_level} slash (waterfall)")
                            absorbed = take
                        except ForceUnstakeError as e:
                            note = f"force_unstake refused: {e}"
                    else:
                        absorbed = take
            elif src == "liquid":
                if mode == "enforce":
                    from .escrow import escrow_deposit, EscrowError
                    try:
                        await escrow_deposit(agent.did, take, f"slash-{action.id}-liquid",
                                             reason="enforcement_slash")
                        absorbed = take
                        agent.liquid_balance = (agent.liquid_balance or 0) - take  # cache mirror of the TEG move
                    except EscrowError as e:
                        note = f"escrow deposit refused: {e.message}"
                else:
                    absorbed = min(take, Decimal(str(agent.liquid_balance or 0)))
            else:
                note = f"unknown source {src!r}"
            entry = {"source": src, "requested": str(take), "absorbed": str(absorbed)}
            if note:
                entry["note"] = note
            plan.append(entry)
            remaining -= absorbed
            if ENFORCEMENT_SLASH_WATERFALL is not None and absorbed > 0:
                try:
                    ENFORCEMENT_SLASH_WATERFALL.labels(mode=mode, source=str(src)).inc()
                except Exception:  # noqa: BLE001
                    pass
        shortfall = remaining if remaining > 0 else Decimal(0)
        verb = "TOOK" if mode == "enforce" else "WOULD TAKE"
        logger.log(
            logging.INFO if mode == "enforce" else logging.WARNING,
            "[EnforcementEngine] slash waterfall (%s) %s: %s %s of %s for %s — plan=%s shortfall=%s",
            mode, action.id, verb, requested - shortfall, requested, action.agent_did, plan, shortfall,
        )
        try:
            emitter = get_event_emitter()
            _wf_data = {"action_id": action.id, "agent_did": action.agent_did, "mode": mode,
                        "requested": str(requested), "absorbed": str(requested - shortfall),
                        "shortfall": str(shortfall), "plan": plan,
                        "action_type": action.action_type, "escalation_level": action.escalation_level}
            if emitter is not None and mode == "enforce":
                await emitter.emit(  # §EMITKEY: emit(), not emit_event() — only emit() takes the key
                    event_type="EnforcementSlashWaterfallApplied",
                    aggregate_id=action.agent_did,
                    data=_wf_data,
                    idempotency_key=f"slashwf-applied-{action.id}",
                )
            elif emitter is not None:
                await emitter.emit(  # §EMITKEY
                    event_type="EnforcementSlashWaterfallPlanned",
                    aggregate_id=action.agent_did,
                    data=_wf_data,
                    idempotency_key=f"slashwf-planned-{action.id}",
                )
        except Exception as e:  # noqa: BLE001
            logger.error("[EnforcementEngine] waterfall event emit failed: %s", e)
        return mode == "enforce"

    async def _get_agent(self, db: AsyncSession, agent_did: str) -> Optional[Agent]:
        result = await db.execute(select(Agent).where(Agent.did == agent_did))
        return result.scalar_one_or_none()

    async def _count_recent_offenses(
        self, db: AsyncSession, agent_did: str, policy: Dict[str, Any]
    ) -> int:
        """Count EnforcementActions with trigger=dispute_ruling within offense_window_days."""
        window_days = (
            policy.get("dispute_escalation", {}).get("offense_window_days", 90)
        )
        cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)

        result = await db.execute(
            select(func.count()).select_from(EnforcementAction).where(
                and_(
                    EnforcementAction.agent_did == agent_did,
                    EnforcementAction.trigger == "dispute_ruling",
                    EnforcementAction.created_at >= cutoff,
                    EnforcementAction.status.in_(["executed", "pending_approval"]),
                )
            )
        )
        return result.scalar() or 0

    def _determine_escalation_level(
        self, offense_count: int, policy: Dict[str, Any]
    ) -> int:
        """Map offense count (AFTER incrementing) to escalation level 1-4."""
        # offense_count is the count BEFORE this offense; we add 1
        nth = offense_count + 1
        if nth >= 4:
            return 4
        return max(1, nth)

    def _check_avt_volume_tier(
        self, amount: int, policy: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Return volume-tier override dict if amount qualifies, else None."""
        tiers = (
            policy.get("dispute_escalation", {})
            .get("avt_volume_tiers", {})
        )
        if not tiers or amount <= 0:
            return None

        minor = tiers.get("minor", {})
        major = tiers.get("major", {})

        if minor and amount <= minor.get("max_amount", 0):
            return minor
        if major and amount >= major.get("min_amount", float("inf")):
            return major

        return None

    async def _calculate_correlation_multiplier(
        self,
        db: AsyncSession,
        agent_did: str,
        policy: Dict[str, Any],
    ) -> Tuple[int, float]:
        """
        Count concurrent offenses from OTHER agents in the same window.
        Returns (count, multiplier).  Multiplier is capped at policy value.
        """
        corr_policy = policy.get("correlation_penalty", {})
        max_multi: float = corr_policy.get("same_registry_multiplier", 2.0)
        window_hours: int = corr_policy.get("window_hours", 24)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)

        result = await db.execute(
            select(func.count()).select_from(EnforcementAction).where(
                and_(
                    EnforcementAction.agent_did != agent_did,
                    EnforcementAction.trigger == "dispute_ruling",
                    EnforcementAction.created_at >= cutoff,
                )
            )
        )
        concurrent = result.scalar() or 0

        if concurrent == 0:
            return 0, 1.0

        # Scale: 1 concurrent → 1.2×, 2 → 1.5×, 3+ → max_multi
        if concurrent == 1:
            multi = min(1.2, max_multi)
        elif concurrent == 2:
            multi = min(1.5, max_multi)
        else:
            multi = max_multi

        return concurrent, multi


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_enforcement_engine: Optional[EnforcementEngine] = None


def get_enforcement_engine() -> EnforcementEngine:
    global _enforcement_engine
    if _enforcement_engine is None:
        _enforcement_engine = EnforcementEngine()
    return _enforcement_engine
