"""
BayesianTrustService — Economic Engine Sprint 10 §5.3

Computes cross-registry trust discounts using a Beta-distribution Bayesian
update model.  Each peer registry starts with a neutral prior (alpha=1, beta=1)
and its discount is updated after each cross-registry interaction.

Positive interactions (transfers that complete cleanly) increment alpha.
Disputes lost against this peer increment beta.
Inactivity (no interaction for INACTIVITY_DECAY_DAYS) decays the discount
multiplicatively toward 0.5 (uncertainty).

The bayesian_discount column on PeerRegistry (f030) stores the resulting
multiplier applied when incorporating cross-registry trust scores into local
EigenTrust computation, and the frame's event store weights the peer's
federation votes by it (SF-5B trust sync).

SEC-20 (2026-10-17, his word: "no, not set. it has to be dervied in a meaningful way. setting it manually doesnt make
sense to me."): the value is DERIVED, never set. derived_trust() below is the one formula; every writer of the column
(record_interaction, run_decay_pass, the federation sync's per-cycle refresh) and every sender of a trust value to the
event store (the trust sync, the frame invitation's store registration) computes it from the peer's recorded outcomes
and the clock, and nothing takes a trust value from a person or a caller.

Public API:
    svc = get_bayesian_trust_service()
    await svc.record_interaction(db, peer_registry_id, success=True)
    await svc.record_dispute_loss(db, peer_registry_id)
    discount = await svc.get_discount(db, peer_registry_id)
    await svc.run_decay_pass(db)  # called by collusion_worker daily
    value = derived_trust_for(peer)  # the derivation from a peer row, pure
"""
import logging
import math
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text

logger = logging.getLogger(__name__)

# Bayesian prior: uniform Beta(1,1)
PRIOR_ALPHA = 1.0
PRIOR_BETA = 1.0
# The point estimate of the prior: alpha/(alpha+beta) = 0.5, i.e. "we have no evidence either way".
# 🔴 THE COLUMN DEFAULT IS 1.0, WHICH IS A CLAIM AND NOT A PRIOR. A peer we have never transacted
# with is not fully trusted; it is unmeasured. Every seed site should use this, and an uninstrumented
# peer should SIT here rather than drift here — a value sliding from 1.0 to 0.5 over a month reads as
# trust being lost, when nothing was ever observed at all.
PRIOR_POINT_ESTIMATE = PRIOR_ALPHA / (PRIOR_ALPHA + PRIOR_BETA)

# Inactivity decay: after this many days with no interaction, uncertainty grows
INACTIVITY_DECAY_DAYS = 30
# Each decayed day pulls discount 5% toward 0.5 (midpoint uncertainty)
DECAY_RATE_PER_DAY = 0.05
# The lowest value the derivation gives: a peer's federation vote is never weighted below a tenth (the store's admin
# federation-operator routes take 0.1 to 1.0 for the same reason). The posterior mean never reaches 1.0.
TRUST_FLOOR = 0.1
# A stored value within this of the derivation is left alone (the refresh writes only a real change).
REFRESH_TOLERANCE = 0.0005


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _beta_point_estimate(total_interactions: int, disputes_lost: int) -> float:
    """Beta(alpha, beta) point estimate: alpha = PRIOR_ALPHA + successes, beta = PRIOR_BETA + disputes lost."""
    successes = max(0, total_interactions - disputes_lost)
    alpha = PRIOR_ALPHA + successes
    beta = PRIOR_BETA + disputes_lost
    return float(alpha / (alpha + beta))


def derived_trust(
    total_interactions: Optional[int],
    disputes_lost_with: Optional[int],
    last_interaction_at: Optional[datetime] = None,
    now: Optional[datetime] = None,
    registered_at: Optional[datetime] = None,
) -> float:
    """THE trust value of a peer registry: derived from what this registry recorded about the peer and from the
    clock, never set (SEC-20). Pure: the same record and the same clock give the same value, whoever computes it and
    however often, so a recompute can never drift the way a stored value nudged by repeated passes did.

        n     = total_interactions (settlements observed with the peer, and disputes it lost)
        lost  = disputes_lost_with
        n = 0              -> PRIOR_POINT_ESTIMATE (0.5): unmeasured, not trusted
        p     = (1 + (n - lost)) / (2 + n)     the Beta(1,1) posterior mean
        idle  = days since the last recorded outcome (last_interaction_at, else registered_at)
        value = 0.5 + (p - 0.5) * (1 - DECAY_RATE_PER_DAY) ** max(0, idle - INACTIVITY_DECAY_DAYS)
                past 30 idle days each further day keeps 95 % of the evidence's pull away from 0.5
        bounds: value is held to [TRUST_FLOOR, 1.0]; the posterior mean never reaches 1.0
    """
    n = max(0, int(total_interactions or 0))
    lost = max(0, int(disputes_lost_with or 0))
    if n == 0:
        return PRIOR_POINT_ESTIMATE
    p = _beta_point_estimate(n, lost)
    now = _as_utc(now) or datetime.now(timezone.utc)
    ref = _as_utc(last_interaction_at) or _as_utc(registered_at)
    weight = 1.0
    if ref is not None:
        idle_days = (now - ref).total_seconds() / 86400
        excess = max(0.0, idle_days - INACTIVITY_DECAY_DAYS)
        weight = (1 - DECAY_RATE_PER_DAY) ** excess
    value = PRIOR_POINT_ESTIMATE + (p - PRIOR_POINT_ESTIMATE) * weight
    return float(min(1.0, max(TRUST_FLOOR, value)))


def derived_trust_for(peer, now: Optional[datetime] = None) -> float:
    """derived_trust() from a peer row (models.PeerRegistry or anything carrying its four fields). The timestamps are
    read only for a peer with a record: a row just inserted carries none, and its server-set registered_at may not be
    loaded yet (reading it from an async session would be a database round trip outside the session's greenlet)."""
    total = getattr(peer, "total_interactions", 0)
    if not int(total or 0):
        return PRIOR_POINT_ESTIMATE
    last = getattr(peer, "last_interaction_at", None)
    return derived_trust(
        total,
        getattr(peer, "disputes_lost_with", 0),
        last,
        now,
        None if last is not None else getattr(peer, "registered_at", None),
    )


def refresh_derived_trust(peers, now: Optional[datetime] = None) -> int:
    """Set each peer row's bayesian_discount to its derivation where it differs (by more than REFRESH_TOLERANCE), so
    every surface that reads the column shows the value the trust sync sends. Returns how many rows changed; the
    caller commits. A value written into the column by anything else is replaced here, never kept."""
    changed = 0
    for peer in peers:
        target = derived_trust_for(peer, now)
        current = getattr(peer, "bayesian_discount", None)
        if current is None or abs(float(current) - target) > REFRESH_TOLERANCE:
            peer.bayesian_discount = target
            changed += 1
    return changed


class BayesianTrustService:
    """
    Beta-distribution Bayesian cross-registry trust calculator.

    Model (derived_trust, the one formula):
        alpha = PRIOR_ALPHA + successful_interactions
        beta  = PRIOR_BETA  + disputes_lost_with_peer
        point_estimate = alpha / (alpha + beta)
        bayesian_discount = 0.5 + (point_estimate - 0.5) * 0.95 ** (idle days past 30), held to [0.1, 1.0]

    The inactivity pull is part of the derivation, computed from last_interaction_at, never applied to the stored value.
    """

    async def get_discount(self, db: AsyncSession, peer_id: int) -> float:
        """Return the current bayesian_discount for a peer registry."""
        from ..models import PeerRegistry
        result = await db.execute(
            select(PeerRegistry.bayesian_discount).where(PeerRegistry.id == peer_id)
        )
        val = result.scalar_one_or_none()
        return float(val) if val is not None else 1.0

    async def record_interaction(
        self, db: AsyncSession, peer_id: int, success: bool = True
    ):
        """
        Record a cross-registry interaction outcome and recompute discount.

        success=True  → increment alpha (positive evidence)
        success=False → increment beta (negative evidence, same as dispute_loss)

        🔴 THE COUNTERS MOVE IN ONE ATOMIC STATEMENT, NOT READ-MODIFY-WRITE.
        This used to `SELECT` the row, add 1 in Python and write the total back absolutely, with
        no row lock — so two settlements landing together each read N and each wrote N+1, and one
        observation vanished while both callers saw success. That was survivable only because
        NOTHING EVER CALLED THIS: measured 2026-09-10, `record_interaction` had no caller in the
        tree. §TRUSTWIRE routes every cross-registry settlement here through one reactor whose
        handler concurrency is 50, so the race stops being theoretical the day it ships. It is
        also the same defect as the TEG's reputation-signal rail, where it is measured: 9 of 764
        concurrent signals lost, every one answering 200 "applied".

        `total_interactions` is PUBLISHED (the peer card renders "N interactions"), so an
        increment that silently disappears is a wrong number on screen, not just a wrong model.

        ⚠ The discount is derived in Python from the values the UPDATE returned, deliberately:
        the derivation lives in `derived_trust` and nowhere else, and putting a
        second copy of it into SQL is exactly the two-formulas-one-column shape this file was
        cleaned up to remove. The cost is a bounded one: if two recorders interleave between the
        counter update and the discount write, the discount can land one observation stale. The
        counters are exact, and the next observation corrects it.

        This commits its own transaction. Fine from a reactor; wrong inside someone else's unit
        of work.
        """
        now = datetime.now(timezone.utc)
        row = (await db.execute(
            text(
                "UPDATE peer_registries SET "
                "  total_interactions = COALESCE(total_interactions, 0) + 1, "
                "  disputes_lost_with = COALESCE(disputes_lost_with, 0) + :lost, "
                "  last_interaction_at = :now, "
                "  inactivity_leak_start = :now "
                "WHERE id = :peer_id "
                "RETURNING total_interactions, disputes_lost_with"
            ),
            {"lost": 0 if success else 1, "now": now, "peer_id": peer_id},
        )).first()
        if row is None:
            await db.rollback()
            logger.warning(f"[BayesianTrust] Peer {peer_id} not found")
            return

        total, lost = int(row[0]), int(row[1] or 0)
        # SEC-20: the derivation, at the instant of the outcome just recorded (no idle time, so the posterior mean
        # held to its bounds)
        discount = derived_trust(total, lost, now, now)
        await db.execute(
            text("UPDATE peer_registries SET bayesian_discount = :d WHERE id = :peer_id"),
            {"d": discount, "peer_id": peer_id},
        )
        await db.commit()

        logger.info(
            f"[BayesianTrust] peer={peer_id} interactions={total} "
            f"disputes_lost={lost} discount={discount:.4f}"
        )

    async def record_dispute_loss(self, db: AsyncSession, peer_id: int):
        """Shorthand: record a negative outcome (dispute lost against this peer)."""
        await self.record_interaction(db, peer_id, success=False)

    async def run_decay_pass(self, db: AsyncSession):
        """
        Recompute every active peer registry's trust value from its record (SEC-20).

        Called daily by the collusion_worker. Each ACTIVE peer's bayesian_discount is set to derived_trust() of its
        own record and the clock, so the inactivity pull (past INACTIVITY_DECAY_DAYS idle days, toward 0.5) shows on
        peers nothing has touched, and any value written into the column by anything else is replaced. The federation
        sync recomputes its peers the same way on every cycle; this pass covers every ACTIVE row.

        Before SEC-20 this pass multiplied the STORED value by (1 - DECAY_RATE_PER_DAY) ** excess_days every day, so
        the excess was applied again on each pass (a peer idle 33 days had its pull shrunk by 0.95 ** 6, not 0.95 ** 3),
        and a second rule (the federation sync's SF-5A leak, 0.01 per cycle after 90 days) moved the same column.
        """
        from ..models import PeerRegistry

        now = datetime.now(timezone.utc)

        result = await db.execute(
            select(PeerRegistry).where(PeerRegistry.status == 'ACTIVE')
        )
        peers = result.scalars().all()

        decayed_count = 0
        skipped_uninstrumented = 0
        converged_to_prior = 0
        for peer in peers:
            target = derived_trust_for(peer, now)
            current = peer.bayesian_discount
            differs = current is None or abs(float(current) - target) > REFRESH_TOLERANCE
            # 🔴 ABSENCE OF INSTRUMENTATION IS NOT EVIDENCE OF INACTIVITY.
            # A peer with total_interactions == 0 has never had an interaction RECORDED, which on
            # this network meant nothing ever called record_interaction() at all — measured
            # 2026-09-10, every peer on EU read ti=0 / discount=1.0 / last_interaction_at=never
            # after days of live federation, mirrored cards and FX. Decaying those toward 0.5
            # would have published a falling trust number for peers that were behaving perfectly,
            # and it would have started on its own about 30 days after each standup. A peer we
            # have no readings for is UNMEASURED; it is not untrustworthy.
            if not (peer.total_interactions or 0):
                # ⚠ V0313 SKIPPED THESE AND THAT WAS HALF A FIX. Skipping stops the misleading
                # month-long slide, but it also FREEZES the peer wherever it happens to sit — and
                # the column default is 1.0, so an unmeasured peer would have been pinned at "fully
                # trusted" forever. The honest resting place for no evidence is the prior itself,
                # reached in one step rather than crept toward, because there is nothing to decay
                # (derived_trust answers the prior for a peer with no record).
                skipped_uninstrumented += 1
                if differs:
                    peer.bayesian_discount = target
                    converged_to_prior += 1
                continue
            if differs:
                peer.bayesian_discount = target
                decayed_count += 1

        if decayed_count or converged_to_prior:
            await db.commit()
        # say what was withheld and why, every pass: a decay that silently touches nothing is
        # indistinguishable from a decay that is not running (§DISCMIX).
        logger.info(
            f"[BayesianTrust] trust recompute: {decayed_count} measured peer(s) changed, "
            f"{skipped_uninstrumented} UNMEASURED (no interaction ever recorded), of which "
            f"{converged_to_prior} set to the prior {PRIOR_POINT_ESTIMATE}, "
            f"{len(peers)} candidates"
        )

    def _compute_discount(self, total_interactions: int, disputes_lost: int) -> float:
        """
        Beta(alpha, beta) point estimate (the posterior mean derived_trust starts from).

        alpha = PRIOR_ALPHA + (total_interactions - disputes_lost)  [successes]
        beta  = PRIOR_BETA  + disputes_lost
        """
        return _beta_point_estimate(total_interactions, disputes_lost)


# Singleton
_service: Optional[BayesianTrustService] = None


def get_bayesian_trust_service() -> BayesianTrustService:
    global _service
    if _service is None:
        _service = BayesianTrustService()
    return _service
