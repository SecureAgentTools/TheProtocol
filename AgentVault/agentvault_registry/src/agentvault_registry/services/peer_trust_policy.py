"""
services/peer_trust_policy.py — what this frame DOES about a peer it distrusts.

§TRUSTPOLICY (2026-09-11). `bayesian_discount` has been written by the settlement
reactor, rendered on three surfaces, and consumed for a decision in exactly ONE
place in the whole system: the EventStore multiplies a frame's federation vote
weight by it. So a peer could settle badly for a month and the only consequence
was a smaller number on a page.

This module turns the number into a STATE with a named action, under thresholds
the frame declares in its own policy document (§FRAMEPOLICY). It decides; it does
not act. The callers act, so that every action stays at a site that already owns
the rail it is using.

🔴 EVIDENCE BEFORE THE NUMBER. The model is Beta(1,1): a peer nobody has
transacted with sits at 0.5, which means "no evidence either way" and NOT "half
trusted". Measured on EU 2026-09-11, hochiminh and shenzhen sat at exactly
0.5000 with ZERO interactions, and the INACTIVE `ASIA` ghost sat at the column
default 1.0 with zero interactions — looking perfect for the same reason the
other two looked terrible. A threshold applied straight to the number would have
restricted the two peers nobody had ever dealt with and fully trusted the ghost.

So `UNMEASURED` is checked FIRST and is terminal: below `min_interactions`, no
action fires whatever the discount says.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# States, worst last. A caller may compare by RANK, never by string order.
UNMEASURED = "unmeasured"
OK = "ok"
WARN = "warn"
RESTRICTED = "restricted"
SUSPENDED = "suspended"

STATE_RANK = {UNMEASURED: 0, OK: 1, WARN: 2, RESTRICTED: 3, SUSPENDED: 4}

# The states at which this frame withholds something from a peer.
ACTIONABLE = (RESTRICTED, SUSPENDED)

MODE_OFF = "off"
MODE_OBSERVE = "observe"
MODE_ENFORCE = "enforce"


@dataclass(frozen=True)
class PeerTrustVerdict:
    """A decision that carries its own evidence.

    ⚠ `reason` is not decoration. A peer that loses a capability must be
    distinguishable from a peer that is merely quiet, and the operator reading
    the refusal must be able to see WHICH policy key and WHICH number produced
    it without going to the source.
    """
    state: str
    reason: str
    discount: Optional[float]
    interactions: int
    threshold_key: Optional[str] = None
    threshold: Optional[float] = None
    mode: str = MODE_OBSERVE

    @property
    def is_actionable(self) -> bool:
        """True when the STATE calls for withholding something. Whether the frame
        actually withholds is `enforced` — the two are deliberately separate."""
        return self.state in ACTIONABLE

    @property
    def enforced(self) -> bool:
        """True only when this frame has opted in. In `observe` the verdict is
        reported and nothing is refused."""
        return self.mode == MODE_ENFORCE and self.is_actionable

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state": self.state,
            "reason": self.reason,
            "discount": self.discount,
            "interactions": self.interactions,
            "threshold_key": self.threshold_key,
            "threshold": self.threshold,
            "mode": self.mode,
            "enforced": self.enforced,
        }


def _cfg(policy) -> Dict[str, Any]:
    """Read the frame's declared peer-trust posture, whatever shape the caller
    handed us: a ResolvedPolicy, a plain resolved document, or nothing."""
    if policy is None:
        from ..crud.crud_enforcement import DEFAULT_POLICY_JSON
        return dict(DEFAULT_POLICY_JSON.get("peer_trust") or {})
    get = getattr(policy, "get", None)
    if get is not None and not isinstance(policy, dict):
        # ResolvedPolicy: dotted-path reads, each falling back to the documented default
        return {
            "mode": policy.get("peer_trust.mode", MODE_OBSERVE),
            "min_interactions": policy.get("peer_trust.min_interactions", 10),
            "warn_below": policy.get("peer_trust.warn_below", 0.70),
            "restrict_below": policy.get("peer_trust.restrict_below", 0.50),
            "suspend_below": policy.get("peer_trust.suspend_below", 0.30),
            "recover_margin": policy.get("peer_trust.recover_margin", 0.05),
        }
    return dict((policy or {}).get("peer_trust") or {})


def evaluate(peer, policy=None, previous_state: Optional[str] = None) -> PeerTrustVerdict:
    """Classify ONE peer against this frame's declared thresholds.

    `previous_state` enables hysteresis: a peer climbing back out of a state must
    clear the threshold by `recover_margin` before it is released, so a discount
    hovering on the line does not flap a capability on and off every pass.
    """
    cfg = _cfg(policy)
    mode = str(cfg.get("mode", MODE_OBSERVE) or MODE_OBSERVE).lower()
    min_interactions = int(cfg.get("min_interactions", 10) or 0)
    margin = float(cfg.get("recover_margin", 0.05) or 0.0)

    interactions = int(getattr(peer, "total_interactions", 0) or 0)
    raw = getattr(peer, "bayesian_discount", None)
    discount = None if raw is None else float(raw)

    if mode == MODE_OFF:
        return PeerTrustVerdict(
            state=OK, reason="peer trust policy is off on this frame",
            discount=discount, interactions=interactions, mode=mode)

    # ── evidence first, and it is terminal ────────────────────────────────────
    if interactions < min_interactions:
        return PeerTrustVerdict(
            state=UNMEASURED,
            reason=(f"{interactions} settled interaction(s), below the "
                    f"{min_interactions} this frame requires before it will act "
                    f"(peer_trust.min_interactions). The score is a prior, not a judgement."),
            discount=discount, interactions=interactions,
            threshold_key="peer_trust.min_interactions", threshold=float(min_interactions),
            mode=mode)

    if discount is None:
        return PeerTrustVerdict(
            state=UNMEASURED, reason="no trust score recorded for this peer",
            discount=None, interactions=interactions, mode=mode)

    # ── the ladder, worst first ───────────────────────────────────────────────
    for state, key in ((SUSPENDED, "suspend_below"),
                       (RESTRICTED, "restrict_below"),
                       (WARN, "warn_below")):
        threshold = cfg.get(key)
        if threshold is None:
            continue
        threshold = float(threshold)
        # Hysteresis: a peer ALREADY in this state (or worse) must clear the line
        # by `recover_margin` to leave it.
        effective = threshold + margin if (
            previous_state and STATE_RANK.get(previous_state, 0) >= STATE_RANK[state]
        ) else threshold
        if discount < effective:
            held = (" (held: recovery needs "
                    f"{effective:.2f} = {threshold:.2f} + peer_trust.recover_margin)"
                    ) if effective != threshold else ""
            return PeerTrustVerdict(
                state=state,
                reason=(f"trust {discount:.4f} is below peer_trust.{key} "
                        f"({threshold:.2f}) after {interactions} settled "
                        f"interaction(s){held}"),
                discount=discount, interactions=interactions,
                threshold_key=f"peer_trust.{key}", threshold=threshold, mode=mode)

    return PeerTrustVerdict(
        state=OK,
        reason=(f"trust {discount:.4f} over {interactions} settled interaction(s), "
                f"above every threshold this frame declares"),
        discount=discount, interactions=interactions, mode=mode)


def describe(verdict: PeerTrustVerdict) -> str:
    """One human sentence. §TRUSTPOLICY item 5: a bare 0.500 reads as distrust and
    means no evidence, so nothing that faces a person renders the number alone."""
    if verdict.state == UNMEASURED:
        return f"Unmeasured — {verdict.interactions} settled interaction(s), not enough to judge"
    if verdict.discount is None:
        return "Unmeasured"
    pct = f"{verdict.discount * 100:.0f}%"
    if verdict.state == OK:
        return f"Trusted — {pct} over {verdict.interactions} interaction(s)"
    label = {WARN: "Watch", RESTRICTED: "Restricted", SUSPENDED: "Suspended"}[verdict.state]
    suffix = "" if verdict.enforced else " (observing — this frame is not acting on it yet)"
    return f"{label} — {pct} over {verdict.interactions} interaction(s){suffix}"


# ---------------------------------------------------------------------------
# §TRUSTCHAIN P4.4 (2026-09-12) — what SUSPENDED does that RESTRICTED does not.
#
# §TRUSTPOLICY shipped both states doing the same thing at the ingest gate (withhold the
# peer's cards) and named the gap: the quarantine rail existed but `federated_registry_compliance`
# was empty, so wiring it would have been inert. P4.2 gave every ACTIVE peer a baseline row, so
# the rail can act. Measured before wiring it, and worth stating plainly:
#   * a compliance quarantine (`federation_status = "quarantined"`) is RECORDED (the row, its
#     `quarantine_events` history), NOTIFIED (registry.quarantined) and LISTED
#     (`/admin/enforcement/registries/quarantined`, CONSUL) — and withholds nothing economic:
#     no money rail and no ingest rail reads that column; (D6-801, 2026-10-17: the money rails now
#     refuse a quarantined peer, services/federation_license_gate.quarantined_registry)
#   * the economic refusal is the LICENCE (`federation_license_gate`), and `status = "suspended"`
#     on a licence has exactly ONE writer, the admin route, by design.
# So SUSPENDED under `enforce` = the cards are withheld (as before) AND the peer is placed in
# compliance quarantine through the monitor's own rail, with a reason that names the policy key
# and the number, tagged so that trust lifts ONLY what trust imposed (an admin's or the drift
# poller's quarantine is never touched). Recovery lifts it with no admin. Whether the licence gate
# should also read the compliance state is a decision, not a defect, and is left where it is.
# ---------------------------------------------------------------------------

TRUST_QUARANTINE_MARKER = "peer_trust:"
ACTION_QUARANTINE = "quarantine"
ACTION_LIFT = "lift"
ACTOR = "peer_trust_policy"


def plan_action(
    verdict: PeerTrustVerdict,
    compliance_status: Optional[str],
    quarantine_reason: Optional[str],
) -> Optional[str]:
    """Pure: what this frame should DO about a peer's verdict, given its compliance row.

    Evaluated on EVERY sweep pass, not only on transitions, so that a frame that turns
    `peer_trust.mode` to enforce while a peer already sits at SUSPENDED acts on the next pass,
    and a frame that turns it back to observe releases what the policy imposed.

      quarantine  — enforce, state SUSPENDED, row `federated`
      lift        — row `quarantined` by THIS policy (marker on the reason) and the verdict is no
                    longer an enforced SUSPENDED (recovered, or the frame stopped enforcing)
      None        — everything else: observe mode (reported, nothing done), RESTRICTED/WARN/OK
                    (the ingest gate is the whole action), no row, blacklisted, or a quarantine
                    somebody else imposed
    """
    ours = bool(quarantine_reason) and str(quarantine_reason).startswith(TRUST_QUARANTINE_MARKER)
    enforced_suspension = verdict.enforced and verdict.state == SUSPENDED
    if compliance_status == "quarantined":
        if ours and not enforced_suspension:
            return ACTION_LIFT
        return None
    if compliance_status == "federated" and enforced_suspension:
        return ACTION_QUARANTINE
    return None


async def _apply_trust_action(db, peer, verdict: PeerTrustVerdict, action: str) -> Dict[str, Any]:
    """Perform `action` through the compliance monitor's own rails. Never raises."""
    from sqlalchemy import select
    from ..models import FederatedRegistryCompliance
    out: Dict[str, Any] = {"action": action, "applied": False}
    try:
        row = (await db.execute(
            select(FederatedRegistryCompliance).where(
                FederatedRegistryCompliance.peer_registry_id == peer.id)
        )).scalar_one_or_none()
        if row is None:
            out["why"] = "no_compliance_row"   # P4.2 records one at the next poll; nothing to act on yet
            return out
        from .federation_compliance_monitor import get_federation_compliance_monitor
        from ..core.base_network_params import DriftSeverity
        monitor = get_federation_compliance_monitor()
        if action == ACTION_QUARANTINE:
            reason = (
                f"{TRUST_QUARANTINE_MARKER}{verdict.threshold_key} ({verdict.threshold}) — trust "
                f"{(verdict.discount if verdict.discount is not None else float('nan')):.4f} after "
                f"{verdict.interactions} settled interaction(s); lifts itself on recovery"
            )
            await monitor.trigger_quarantine(
                db=db, peer_id=peer.id, reason=reason, severity=DriftSeverity.HIGH,
                grace_hours=0, admin_email=ACTOR,
            )
            out.update(applied=True, reason=reason)
        elif action == ACTION_LIFT:
            await monitor.lift_quarantine(
                db=db, peer_id=peer.id, new_policy_hash=row.policy_hash, admin_email=ACTOR,
            )
            out.update(applied=True, reason=f"{TRUST_QUARANTINE_MARKER}recovered: {verdict.reason}")
        logger.warning("[TRUSTPOLICY] %s peer=%s: %s", action.upper(), getattr(peer, "name", "?"),
                       out.get("reason", ""))
    except Exception as e:  # noqa: BLE001 — trust must never break the cycle
        logger.error("[TRUSTPOLICY] %s failed for peer=%s: %s", action, getattr(peer, "name", "?"), e,
                     exc_info=True)
        out["why"] = f"error: {str(e)[:200]}"
    return out


def trust_block(peer, policy=None) -> Dict[str, Any]:
    """The verdict as a dict, with its sentence, for any surface that renders a peer row.

    ONE implementation. §TRUSTPOLICY's own finding was that a third copy of "how trusted is
    this peer" had grown in the FE with cut-offs belonging to nobody's policy, so a second
    copy here would be the same defect wearing a server costume.

    Best-effort by design: a peer row must still render if the policy cannot be read, and it
    returns `unavailable` rather than an inviting-looking default, because "we could not
    judge" and "we judged it fine" are different facts.
    """
    try:
        v = evaluate(peer, policy)
        out = v.to_dict()
        out["label"] = describe(v)
        return out
    except Exception:  # noqa: BLE001
        return {"state": "unavailable", "label": "Trust state unavailable",
                "reason": "the frame's peer-trust policy could not be read"}


# ---------------------------------------------------------------------------
# The clock. A verdict that is only computed when cards happen to flow cannot
# tell an operator that a quiet peer crossed a line.
# ---------------------------------------------------------------------------

_STATE_KEY = "registry:peer_trust:state:"   # + peer id


async def _redis():
    """Fail-open Redis handle — the same contract federation_sync uses: a broken
    cache must never stop, or start, federation work. With no Redis every pass
    reads `prev = None`, so a transition is re-reported rather than missed."""
    try:
        from ..background_tasks.leader import get_redis
        return await get_redis()
    except Exception:  # pragma: no cover
        return None


async def sweep(db) -> Dict[str, Any]:
    """Evaluate every ACTIVE peer and report STATE TRANSITIONS, not states.

    Emitting on every pass would turn the ledger into a heartbeat nobody reads;
    emitting on change is the thing an operator actually wants woken for. The
    previous state lives in Redis because the workers are leader-elected across
    38 gunicorn processes and in-process state is unreadable to the others
    (§SUPPORTBATCH1).

    Returns a summary; raises nothing — trust evaluation must never be able to
    stop federation.
    """
    from ..models import PeerRegistry
    from sqlalchemy import select

    out: Dict[str, Any] = {"evaluated": 0, "transitions": [], "by_state": {}, "actions": []}
    try:
        from .frame_policy import load as load_frame_policy
        from ..models import FederatedRegistryCompliance
        policy = await load_frame_policy(db)
        rows = (await db.execute(
            select(PeerRegistry).where(PeerRegistry.status == "ACTIVE")
        )).scalars().all()
        # §TRUSTCHAIN P4.4 — the compliance rows, ONE query, so plan_action can see whether a
        # peer is federated, quarantined (by whom) or blacklisted without a read per peer.
        compliance_by_peer: Dict[int, Any] = {}
        try:
            for c in (await db.execute(select(FederatedRegistryCompliance))).scalars().all():
                compliance_by_peer[c.peer_registry_id] = c
        except Exception:  # noqa: BLE001 — no rows is a state, not a failure
            compliance_by_peer = {}
        r = await _redis()

        for peer in rows:
            prev = None
            if r is not None:
                try:
                    raw = await r.get(_STATE_KEY + str(peer.id))
                    prev = raw.decode() if isinstance(raw, (bytes, bytearray)) else raw
                except Exception:  # pragma: no cover
                    prev = None
            verdict = evaluate(peer, policy, previous_state=prev)
            out["evaluated"] += 1
            out["by_state"][verdict.state] = out["by_state"].get(verdict.state, 0) + 1

            # §TRUSTCHAIN P4.4 — the action is planned EVERY pass (a mode flip must take effect
            # without a state change) and applied through the compliance monitor's rails.
            crow = compliance_by_peer.get(peer.id)
            action = plan_action(
                verdict,
                getattr(crow, "federation_status", None) if crow is not None else None,
                getattr(crow, "quarantine_reason", None) if crow is not None else None,
            )
            action_result: Optional[Dict[str, Any]] = None
            if action is not None:
                action_result = await _apply_trust_action(db, peer, verdict, action)
                out["actions"].append({"peer": peer.name, **action_result})

            if prev != verdict.state:
                out["transitions"].append({
                    "peer": peer.name, "from": prev or "unknown", "to": verdict.state,
                    **verdict.to_dict(),
                })
                logger.warning(
                    "[TRUSTPOLICY] peer=%s %s -> %s: %s",
                    peer.name, prev or "unknown", verdict.state, verdict.reason)
                await _emit_transition(peer, prev, verdict, action_result)
                if r is not None:
                    try:
                        await r.set(_STATE_KEY + str(peer.id), verdict.state, ex=90 * 86400)
                    except Exception:  # pragma: no cover
                        pass
    except Exception as e:  # noqa: BLE001
        logger.error("[TRUSTPOLICY] sweep failed: %s", e, exc_info=True)
        out["error"] = str(e)[:300]
    return out


async def _emit_transition(
    peer, previous: Optional[str], verdict: PeerTrustVerdict,
    action_result: Optional[Dict[str, Any]] = None,
) -> None:
    try:
        from ..event_emitter import get_event_emitter
        emitter = get_event_emitter()
        if emitter is None:
            return
        # §TRUSTCHAIN P4.4 — the event says what this frame DID (or, in observe, would have done):
        # a reader must be able to tell "quarantined for trust" from "reported and left alone".
        would = ACTION_QUARANTINE if (verdict.state == SUSPENDED and not verdict.enforced) else None
        await emitter.emit_event(
            aggregate_id=f"peer_registry:{getattr(peer, 'id', '?')}",
            event_type="PeerTrustStateChanged",
            event_data={
                "peer_id": getattr(peer, "id", None),
                "peer_name": getattr(peer, "name", None),
                "previous_state": previous or "unknown",
                "action": (action_result or {}).get("action") or would,
                "action_applied": bool((action_result or {}).get("applied")),
                **verdict.to_dict(),
            },
        )
    except Exception:  # noqa: BLE001
        logger.debug("[TRUSTPOLICY] transition emit failed", exc_info=True)
