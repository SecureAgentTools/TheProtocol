"""IRONKEY L4 — attenuable capability tokens (``att_``) for agent→sub-agent chains.

The in-house generalization of the A2A ``apt_`` payment token (amount-bound, TTL'd,
SHA-256-stored, state-machine) from *one payment* to *an agent's attenuated standing
authority*. A parent agent issues a child a token that is **strictly weaker than itself**;
the child may attenuate again (down a bounded chain). Presented on a gated endpoint, the
token can only ever **intersect** (reduce) the holder's authority — never extend it.

Δ-irrelevant by construction: a capability token is a *permission* + *budget-bookkeeping*
object. It authorizes; it never moves money. Every real transfer still clears the existing
escrow rails, so the supply invariant cannot see this module. Budget accounting is metadata
ABOUT money that moves through the normal path, not a balance.

Design choices (see STRATEGY_2026-07-04_IRONKEY_L3_L4):
  * DB-backed (not Biscuit) for v1 — the verifier is always the home registry (online,
    first-party), so offline attenuation buys nothing yet, while DB-backing gives instant
    cascade revocation + audit for free. Caveat JSON is kept Biscuit-Datalog-expressible so
    a later swap is mechanical.
  * Intersection semantics (the confused-deputy killer): effective authority for a request =
    caveat.permissions ∩ issuer's CURRENT effective authority ∩ holder's own authority.
    Clamp/suspend the issuer and every token it ever issued dies the same request.
"""
from __future__ import annotations

import hashlib
import logging
import os
import secrets
from decimal import Decimal, InvalidOperation
from typing import Any, Optional, Set

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry.agent_authz import (
    ALL_PERMISSIONS, agent_delegation_mode, resolve_agent_permissions,
)

logger = logging.getLogger(__name__)

TOKEN_PREFIX = "att_"          # attenuated capability token
DEFAULT_TTL_SECONDS = 900      # 15 minutes
MAX_TTL_SECONDS = 86400        # 24 hours (hard ceiling)
MAX_CHAIN_DEPTH = 3            # root(0) → child(1) → grandchild(2) → depth 3 max


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def generate_token() -> str:
    return f"{TOKEN_PREFIX}{secrets.token_hex(32)}"


def _to_decimal(v) -> Optional[Decimal]:
    if v is None:
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError, TypeError):
        return None


def caveats_subset_ok(child: dict, parent: dict) -> tuple[bool, str | None]:
    """True iff ``child`` caveats are ≤ ``parent`` on every axis (attenuation invariant).

    Permissions ⊆ parent's; every numeric bound (max_per_tx) not looser; currency set ⊆;
    counterparty allowlist ⊆; resources/operations ⊆ when the parent constrains them.
    A parent that leaves an axis unconstrained (absent key) lets the child set any value
    on it — you can only tighten what a parent bounded, and you can add new bounds freely.
    The PHONE FABRIC caveats are axes like the others (D6-522); the uses bound, a column of
    the token rather than a caveat, is ``uses_subset_ok``.
    """
    cp = set(child.get("permissions") or [])
    pp = set(parent.get("permissions") or [])
    if not cp.issubset(pp):
        return False, f"permissions_exceed_parent:{sorted(cp - pp)}"
    cm, pm = _to_decimal(child.get("max_per_tx")), _to_decimal(parent.get("max_per_tx"))
    if pm is not None and (cm is None or cm > pm):
        return False, "max_per_tx_exceeds_parent"
    # B4 — rate_per_hour is a numeric bound like max_per_tx: a bounded parent forces the
    # child to carry an equal-or-tighter bound (absent child = unbounded = looser = refused).
    # D6-522: so are the phone session's action ceiling and its lifetime (an absent lifetime
    # takes the registry default, which a bounded parent never promised).
    for key in ("rate_per_hour", "phone_max_actions", "phone_ttl_seconds"):
        cn, pn = _to_decimal(child.get(key)), _to_decimal(parent.get(key))
        if pn is not None and (cn is None or cn > pn):
            return False, f"{key}_exceeds_parent"
    # D6-522: the phone app and network-domain allowlists stay within the parent's, like the others.
    for key in ("allowed_currencies", "resources_listings", "operations", "geo_allow", "tools",
                "phone_allowed_apps", "phone_allowed_domains"):
        pv = parent.get(key)
        if pv:  # parent constrains this axis → child must stay within it
            cv = child.get(key) or []
            if not set(cv).issubset(set(pv)) or not cv:
                return False, f"{key}_exceed_parent"
    pc = parent.get("counterparty_allow")
    if pc:
        cc = child.get("counterparty_allow") or []
        if not set(cc).issubset(set(pc)) or not cc:
            return False, "counterparty_allow_exceeds_parent"
    # D6-522: a parent that withholds screenshots or the network withholds them from every child.
    for key in ("phone_no_screenshot", "phone_no_network"):
        if parent.get(key) and not child.get(key):
            return False, f"{key}_dropped_by_child"
    return True, None


def uses_subset_ok(child_max_uses: Any, parent_max_uses: Any, parent_uses: Any) -> tuple[bool, str | None]:
    """D6-522: a child of a token bounded in uses carries a bound no larger than the uses its parent has left.

    The uses bound is a column of the token (``max_uses``), not a caveat, so ``caveats_subset_ok`` never saw it: a child
    could name more uses than its parent had, or none at all (unbounded). An absent child bound under a bounded parent is
    looser and refused, as on every other numeric axis; a parent with no bound lets the child name any.
    """
    if parent_max_uses is None:
        return True, None
    left = max(0, int(parent_max_uses) - int(parent_uses or 0))
    if child_max_uses is None or int(child_max_uses) > left:
        return False, "max_uses_exceeds_parent"
    return True, None


def child_budget_within_parent(child_budget: Any, parent_total: Any, parent_spent: Any
                               ) -> tuple[bool, str | None, Optional[Decimal]]:
    """SEC-09: the budget a child token is written with, never more than its parent has left. Returns (ok, why, budget).

    The budget is a column of the token (``budget_total``), not a caveat. A child that named none under a budgeted parent
    was written with no budget at all: an unbounded child of a bounded parent. It takes the parent's remainder now, as a
    lifetime past the parent's takes the parent's expiry (every caller that derives a child without naming a budget gets a
    bounded one). A child naming more than the remainder is refused; a parent with no budget lets the child name any, or
    none. A budget that is not a finite number is refused whatever the parent (it could not be compared or resolved), and
    so is any child of a parent whose own budget is not one.
    """
    cb = _to_decimal(child_budget)
    if child_budget is not None and (cb is None or not cb.is_finite()):
        return False, "budget_total_not_a_number", None
    pt = _to_decimal(parent_total)
    if pt is None and parent_total is None:
        return True, None, cb
    if pt is None or not pt.is_finite():
        return False, "parent_budget_not_a_number", None
    left = max(Decimal(0), pt - (_to_decimal(parent_spent) or Decimal(0)))
    if cb is None:
        return True, None, left
    if cb > left:
        return False, "budget_total_exceeds_parent", None
    return True, None, cb


async def issuer_effective(db: AsyncSession, issuer_did: str) -> Set[str]:
    """The issuer's CURRENT effective permissions — re-read every resolution so a clamp of
    the issuer instantly shrinks every token it holds outstanding (no token reissue).

    Suspension counts as a clamp: a non-active (suspended/revoked/deleted) issuer
    contributes NOTHING, so every capability token it ever issued dies the same
    request. Role grants alone cannot express this — ``resolve_agent_permissions``
    never reads ``agents.status`` — so it is asserted here, at the one point where
    issuer authority is minted into a token's effective set."""
    st = (await db.execute(text(
        "SELECT status FROM agents WHERE did = :d"
    ), {"d": issuer_did})).scalar()
    if st is None or str(st).strip().lower() != "active":
        return set()
    return await resolve_agent_permissions(db, issuer_did)


async def resolve_capability(
    db: AsyncSession, token_plain: str, holder_did: str
) -> tuple[Optional[dict], Optional[str]]:
    """Validate a presented ``att_`` token for ``holder_did``. Returns ``(cap, reason)``.

    ``cap`` (on success) = {id, permissions(effective, already intersected with the issuer's
    CURRENT authority), caveats, budget_remaining, currency, issuer_did}. Fails closed
    (returns ``(None, reason)``) on: unknown/hash-miss, wrong holder, non-active status,
    expired, exhausted budget/uses, or a broken issuer chain. The returned ``permissions``
    is the confused-deputy-safe set — never wider than what the issuer may currently do.
    """
    th = hash_token(token_plain)
    row = (await db.execute(text(
        "SELECT id, issuer_agent_did, holder_agent_did, status, caveats, "
        "budget_total, budget_spent, currency, max_uses, uses, expires_at, depth "
        "FROM agent_capability_tokens WHERE token_hash = :h"
    ), {"h": th})).first()
    if not row:
        return None, "unknown_token"
    if row.holder_agent_did and row.holder_agent_did != holder_did:
        await note_capability_misuse(db, row.id, "holder_mismatch", actor_did=holder_did)
        return None, "holder_mismatch"
    if row.status not in ("issued", "active"):
        if row.status == "revoked":
            # repeated reuse of a revoked token is a misuse signal — a trip here revokes
            # any still-active CHILDREN of the abused token (the parent is already dead).
            await note_capability_misuse(db, row.id, "revoked_reuse", actor_did=holder_did)
        return None, f"status_{row.status}"
    exp = (await db.execute(text(
        "SELECT expires_at <= now() FROM agent_capability_tokens WHERE id = :i"
    ), {"i": row.id})).scalar()
    if exp:
        return None, "expired"
    bt, bs = _to_decimal(row.budget_total), _to_decimal(row.budget_spent) or Decimal(0)
    if bt is not None and bs >= bt:
        return None, "budget_exhausted"
    if row.max_uses is not None and (row.uses or 0) >= row.max_uses:
        return None, "uses_exhausted"
    caveats = row.caveats or {}
    cav_perms = {p for p in (caveats.get("permissions") or []) if p in ALL_PERMISSIONS}
    # Intersection with the issuer's CURRENT authority — the confused-deputy killer.
    iss = await issuer_effective(db, row.issuer_agent_did)
    effective = cav_perms & iss
    budget_remaining = (bt - bs) if bt is not None else None
    return {
        "id": row.id,
        "issuer_did": row.issuer_agent_did,
        "permissions": effective,
        "caveats": caveats,
        "budget_remaining": budget_remaining,
        "currency": row.currency,
        "depth": row.depth,
    }, None


async def revoke_subtree(db: AsyncSession, token_id: int, reason: str) -> int:
    """Revoke a token AND every descendant, in one recursive UPDATE. Returns rows revoked.

    Instant cascading revocation (the OWASP/NIST property) — a compromised or retired
    delegation kills its whole subtree at once, no walk, no sweeper.
    """
    res = await db.execute(text("""
        WITH RECURSIVE subtree AS (
            SELECT id FROM agent_capability_tokens WHERE id = :root
            UNION ALL
            SELECT c.id FROM agent_capability_tokens c
            JOIN subtree s ON c.parent_token_id = s.id
        )
        UPDATE agent_capability_tokens t
        SET status = 'revoked', revoked_at = now(), revoke_reason = :reason
        FROM subtree s
        WHERE t.id = s.id AND t.status IN ('issued','active')
    """), {"root": token_id, "reason": reason[:200]})
    # PHONE FABRIC (2026-07-07): revoking a token instantly kills any phone session it
    # authorized — no 30s reaper lag. Best-effort + guarded (table may be absent on an
    # older schema); never blocks the revocation itself.
    try:
        await db.execute(text("""
            WITH RECURSIVE subtree AS (
                SELECT id FROM agent_capability_tokens WHERE id = :root
                UNION ALL
                SELECT c.id FROM agent_capability_tokens c JOIN subtree s ON c.parent_token_id = s.id
            )
            UPDATE phone_sessions p
            SET status='revoked', ended_at=now(), end_reason='token_revoked'
            FROM subtree s
            WHERE p.capability_token_id = s.id AND p.status='active'
        """), {"root": token_id})
    except Exception:  # noqa: BLE001
        pass
    return res.rowcount or 0


async def circuit_breaker_check(db: AsyncSession, token_id: int, window_denials: int) -> int:
    """≥N denials on one token in a short window → auto-revoke subtree.

    Fed by :func:`note_capability_misuse` (the Redis rolling window). Returns the number
    of tokens revoked (0 = did not trip, or the subtree was already dead — a re-present
    of an already-revoked root counts denials but revokes nothing, so no duplicate trip
    is ever recorded). Kept separate so the *action* lives in one place.
    """
    CB_THRESHOLD = 5
    if window_denials < CB_THRESHOLD:
        return 0
    n = await revoke_subtree(db, token_id, f"circuit_breaker:{window_denials}_denials")
    logger.warning("[IRONKEY-L4] circuit breaker tripped token=%s denials=%s revoked=%s",
                   token_id, window_denials, n)
    return n


CB_WINDOW_SECONDS = 300  # rolling misuse window per token


def circuit_breaker_enabled() -> bool:
    """``CAPABILITY_CIRCUIT_BREAKER_ENABLED`` — default off (dark), the IRONKEY flag pattern."""
    return os.getenv("CAPABILITY_CIRCUIT_BREAKER_ENABLED", "false").strip().lower() == "true"


async def note_capability_misuse(
    db: AsyncSession, token_id: int, reason: str, actor_did: Optional[str] = None
) -> bool:
    """Count a MISUSE denial (wrong holder, revoked-token reuse, action outside caveats)
    against ``token_id`` in a rolling Redis window; at the threshold, trip
    :func:`circuit_breaker_check` and revoke the abused token's whole subtree.

    §auditfix (2026-07-19): every misuse denial is also written DURABLY to
    ``security_audit_logs`` (the review's "denials feed") — in shadow AND enforce
    (observation is the point of shadow), never in ``off`` (byte-inert promise).
    The write commits the session; callers reach here at dependency-time / pre-body,
    before any endpoint mutation is pending, so the commit is empty-safe.

    The BREAKER still only acts under ``AGENT_DELEGATION_MODE=enforce`` AND the breaker
    flag — shadow mode must stay observation-only. Benign denials (expired / budget /
    uses exhausted) are deliberately never counted: they are normal lifecycle, and
    tripping on them would let a drained parent kill healthy children. The counter is
    best-effort (no Redis → no count; the deny itself already stands). A trip COMMITS
    the revocation immediately, because the caller is about to 403 and the request
    session would otherwise roll it back — the trip's audit row and ledger event ride
    that same commit point. Returns True when the breaker tripped."""
    mode = agent_delegation_mode()
    if mode != "off":
        try:
            from agentvault_registry.services.admin_audit import log_ironkey_action
            await log_ironkey_action(
                db, action="capability_misuse", actor_type="agent", actor_id=actor_did,
                target_type="capability_token", target_id=str(token_id),
                outcome="denied", severity="warning",
                details={"reason": reason, "mode": mode},
            )
        except Exception:  # noqa: BLE001 — the deny itself already stands
            logger.debug("[IRONKEY-L4] misuse audit row skipped token=%s", token_id, exc_info=True)
    if not circuit_breaker_enabled() or mode != "enforce":
        return False
    try:
        from agentvault_registry.background_tasks.leader import get_redis
        r = await get_redis()
        if r is None:
            return False
        key = f"ironkey:cb:{token_id}"
        count = int(await r.incr(key))
        if count == 1:
            await r.expire(key, CB_WINDOW_SECONDS)
    except Exception:  # noqa: BLE001
        return False
    revoked = await circuit_breaker_check(db, token_id, count)
    tripped = revoked > 0
    if tripped:
        logger.warning("[IRONKEY-L4] circuit breaker REVOKED subtree token=%s last_reason=%s", token_id, reason)
        ctx = None
        try:
            ctx = (await db.execute(text(
                "SELECT issuer_agent_did, holder_agent_did FROM agent_capability_tokens WHERE id = :i"
            ), {"i": token_id})).first()
        except Exception:  # noqa: BLE001
            pass
        try:
            from agentvault_registry.services.admin_audit import log_ironkey_action
            await log_ironkey_action(  # commits — deliberately, see docstring
                db, action="capability_circuit_breaker_trip", actor_type="system",
                actor_id=actor_did, target_type="capability_token", target_id=str(token_id),
                outcome="revoked", severity="critical",
                details={"denials": count, "last_reason": reason, "revoked_count": revoked,
                         "issuer_did": ctx.issuer_agent_did if ctx else None,
                         "holder_did": ctx.holder_agent_did if ctx else None},
            )
        except Exception:  # noqa: BLE001
            logger.warning("[IRONKEY-L4] circuit-breaker audit row failed token=%s", token_id)
        try:
            await db.commit()
        except Exception:  # noqa: BLE001
            logger.warning("[IRONKEY-L4] circuit-breaker revocation commit failed token=%s", token_id)
        # Ledger record of the AUTOMATED security action — awaited (a trip must be at
        # least as durable in the audit ledger as the revocation it performed); the
        # count-guard above (revoked > 0) means re-presents of an already-dead root
        # can never emit a duplicate.
        try:
            from agentvault_registry.event_emitter import get_event_emitter
            await get_event_emitter().emit(
                event_type="AgentCapabilityCircuitBreakerTripped",
                aggregate_id=(ctx.holder_agent_did or ctx.issuer_agent_did) if ctx else str(token_id),
                data={"token_id": token_id, "denials": count, "last_reason": reason,
                      "revoked_count": revoked, "presented_by": actor_did,
                      "issuer_did": ctx.issuer_agent_did if ctx else None,
                      "holder_did": ctx.holder_agent_did if ctx else None},
                idempotency_key=f"cb-trip-{token_id}",
            )
        except Exception:  # noqa: BLE001 — never block the deny on ledger plumbing
            logger.warning("[IRONKEY-L4] AgentCapabilityCircuitBreakerTripped emit failed token=%s", token_id)

        # §NOTIFV2 (2026-07-27): a breaker trip is an AUTOMATED security action taken without a
        # human in the loop, which makes it exactly the kind of thing the owner must hear about.
        # Sits inside the same `revoked > 0` guard as the ledger emit above, so re-presenting an
        # already-dead root cannot re-notify. Owner resolved from the issuer/holder DID.
        try:
            import asyncio as _aio
            from agentvault_registry.background_tasks.push_notify import notify_agent_owners
            _dids = [d for d in ((ctx.issuer_agent_did if ctx else None),
                                 (ctx.holder_agent_did if ctx else None)) if d]
            if _dids:
                _aio.create_task(notify_agent_owners(
                    "delegation.breaker_tripped", _dids,
                    title="Capability circuit breaker tripped",
                    message=(f"{revoked} capability token(s) revoked after {count} denials. "
                             f"Last reason: {reason}"),
                    tags="warning", priority="high", click="/ui/#/pocket/approvals"))
        except Exception:  # noqa: BLE001
            logger.debug("delegation.breaker_tripped notify skipped", exc_info=True)
    return tripped
