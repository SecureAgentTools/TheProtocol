"""
Coordinated Suspension (Phase 6)
================================
Couples the three independent "block an agent" levers under a single
transactional path so admin actions cannot leave half-blocked states:

1. Registry status flip (agent.status / enforcement_status)
2. IRONHAND mTLS revoke (SPIRE entry deletion + AgentMtlsRevoked event)
3. TEG-side account suspension (agent.account_status="suspended" via
   POST /api/v1/admin/agents/{agent_id}/suspend)

Each lever is best-effort; failure in one is captured in the structured
result rather than aborting the others. Caller (typically admin_agents
or admin_developers) receives per-lever booleans and decides how to
present the outcome.

Reverse path (`coordinated_agent_reinstate`) re-enrolls mTLS (issuing a
fresh SPIFFE SVID) and reactivates the TEG account. The pre-existing
revocation blocklist will expire naturally as the SDK polls.

Soft mode: skips mTLS + TEG, only touches registry status. Used when
admin wants a less-aggressive suspend (e.g., short-term throttle that
doesn't break agent identity).
"""
from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional

import aiohttp
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry import models
from agentvault_registry.core.path_segment import seg  # §MCPTEST30 V0526: a value in a store/TEG URL path is one encoded segment (round 9: a malformed id read as an outage)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class CoordinatedSuspendResult:
    agent_did: str
    registry: bool = False        # registry status flipped
    mtls: str = "skipped"         # "revoked" | "not_enrolled" | "skipped" | "failed"
    teg: str = "skipped"          # "suspended" | "skipped" | "failed"
    cross_teg: str = "skipped"    # RP4 4th lever: "blocked" | "skipped" | "failed"
    error: Optional[str] = None   # populated if any non-soft step failed

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class CoordinatedReinstateResult:
    agent_did: str
    registry: bool = False        # registry status flipped to active
    mtls: str = "skipped"         # "enrolled" | "already_enrolled" | "not_enrolled" | "skipped" | "failed"
    teg: str = "skipped"          # "reinstated" | "skipped" | "failed"
    cross_teg: str = "skipped"    # RP4 4th lever: "unblocked" | "skipped" | "failed"
    error: Optional[str] = None

    def as_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _teg_base_url() -> str:
    return os.getenv("TEG_API_BASE_URL", "http://teg-layer:8080").rstrip("/")


def _teg_admin_key() -> str:
    return os.getenv("TEG_ADMIN_API_KEY", "")


# ---------------------------------------------------------------------------
# TEG admin calls
# ---------------------------------------------------------------------------

async def _teg_admin_post(path: str, json_body: dict | None, log_label: str) -> bool:
    """POST an admin call to the TEG over the registry's SVID-mTLS-aware shared
    client (teg_integration._get_teg_client). The old raw-aiohttp path had no
    client cert/CA, so on mTLS frames (nginx-teg :8443) EVERY lever died with
    CERTIFICATE_VERIFY_FAILED — teg=failed on suspend was a long-standing
    silent breakage this fixes (2026-07-24). Returns True on 2xx."""
    key = _teg_admin_key()
    if not key:
        logger.warning(f"[CoordinatedSuspend] TEG_ADMIN_API_KEY not set — {log_label} skipped")
        return False
    url = f"{_teg_base_url()}{path}"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    try:
        from ..routers.teg_integration import _get_teg_client
        client = _get_teg_client()
        resp = await client.post(url, headers=headers, json=(json_body or {}), timeout=10.0)
        if resp.status_code >= 400:
            logger.warning(
                f"[CoordinatedSuspend] {log_label} → {resp.status_code}: {resp.text[:300]}"
            )
            return False
        return True
    except Exception as e:
        logger.warning(f"[CoordinatedSuspend] {log_label} network error: {e}")
        return False


async def _teg_suspend(agent_did: str, reason: str, duration_hours: int = 8760) -> bool:
    """POST {TEG}/api/v1/admin/agents/{did}/suspend. Returns True on 2xx."""
    return await _teg_admin_post(
        f"/api/v1/admin/agents/{seg(agent_did)}/suspend",
        {"suspension_duration_hours": duration_hours, "suspension_reason": reason[:500]},
        f"TEG suspend {agent_did}",
    )


async def _cross_teg_set_block(agent_did: str, blocked: bool, reason: str = "") -> bool:
    """RP4 4th lever: POST {TEG}/api/v1/cross-teg/admin/agents/{did}/{block|unblock}.

    Keeps a suspended agent from RECEIVING cross-registry sends — the local
    transfer path is already sender-gated by TEG is_agent_suspended, but the
    cross-TEG receive gate reads the external blocklist. Idempotent server-side
    (already-blocked never 4xxs). Returns True on 2xx.
    """
    action = "block" if blocked else "unblock"
    return await _teg_admin_post(
        f"/api/v1/cross-teg/admin/agents/{agent_did}/{action}",
        {"reason": reason[:500] or "coordinated_suspension", "actor": "coordinated_suspension"},
        f"cross-TEG {action} {agent_did}",
    )


async def _teg_reinstate(agent_did: str) -> bool:
    """POST {TEG}/api/v1/admin/agents/{did}/reinstate. Returns True on 2xx (incl. idempotent no-op)."""
    return await _teg_admin_post(
        f"/api/v1/admin/agents/{seg(agent_did)}/reinstate", None, f"TEG reinstate {agent_did}"
    )



# ---------------------------------------------------------------------------
# IRONHAND mTLS calls (in-process)
# ---------------------------------------------------------------------------

async def _ironhand_revoke(db: AsyncSession, agent: models.Agent, actor_email: str) -> str:
    """Mirror of agent_mtls.admin_revoke_agent() but in-process so the cascade
    runs inside the calling DB session. Returns 'revoked' | 'not_enrolled' | 'failed'.
    """
    if not agent.mtls_enabled:
        return "not_enrolled"
    old_spiffe_id = agent.spiffe_id
    try:
        from agentvault_registry.services.agent_spire import delete_agent_spire_entry
        delete_agent_spire_entry(agent.did)
    except Exception as e:
        logger.warning(f"[CoordinatedSuspend] SPIRE deletion failed for {agent.did}: {e}")
        # Continue — DB flip + event still happen so SDK blocklists pick it up

    # §TWOAGENT #35 (2026-09-23): KEEP spiffe_id. With mtls_enabled False it grants nothing (every reader that treats
    # an agent as enrolled requires mtls_enabled too; the SPIRE entry is gone and the card says disabled), and it is the
    # only durable trace of what THIS suspension took away, so the reinstate can restore exactly that. The owner's own
    # disable and the admin revoke clear it, so a reinstate never restores what somebody turned off on purpose.
    agent.mtls_enabled = False

    # Patch agent card if it exists
    try:
        from agentvault_registry.routers.agent_mtls import _patch_agent_card_mtls
        await _patch_agent_card_mtls(db, agent.did, None, enabled=False)
    except Exception as e:
        logger.warning(f"[CoordinatedSuspend] agent card patch failed for {agent.did}: {e}")

    # Emit AgentMtlsRevoked so SDK A2AAuthenticator blocklists update
    if old_spiffe_id:
        try:
            from agentvault_registry.event_emitter import get_event_emitter
            await get_event_emitter().emit_agent_mtls_revoked(
                agent_did=agent.did,
                spiffe_id=old_spiffe_id,
                reason="coordinated_suspend",
                revoked_by=actor_email,
            )
        except Exception as e:
            logger.warning(f"[CoordinatedSuspend] AgentMtlsRevoked emit failed for {agent.did}: {e}")

    return "revoked"


async def _ironhand_enroll(db: AsyncSession, agent: models.Agent) -> str:
    """Restore the mTLS identity the suspension revoked, and nothing else.

    Returns 'enrolled' | 'already_enrolled' | 'not_enrolled' | 'failed'. §TWOAGENT #35 (2026-09-23): this used to
    enroll ANY reinstated agent, so an agent that never asked for mTLS came back with a SPIRE entry, a SPIFFE id and
    a card saying mtls enabled (measured on EU and ASIA: the suspend reported mtls=not_enrolled, the reinstate
    mtls=enrolled). A reinstate undoes the suspension; it does not grant an identity.
    """
    if agent.mtls_enabled and agent.spiffe_id:
        return "already_enrolled"
    if not agent.spiffe_id:
        # never enrolled, or its owner / an admin turned mTLS off (both clear spiffe_id): nothing to restore
        return "not_enrolled"
    if getattr(agent, "mtls_revoked_at", None) is not None:
        # D6-802: an administrator revoked the identity (during the suspension too): a reinstate does not restore it
        return "not_enrolled"
    try:
        from agentvault_registry.services.agent_spire import register_agent_spire_entry
        spiffe_id = register_agent_spire_entry(agent.did)
    except Exception as e:
        logger.warning(f"[CoordinatedReinstate] SPIRE registration failed for {agent.did}: {e}")
        return "failed"

    agent.spiffe_id = spiffe_id
    agent.mtls_enabled = True
    agent.mtls_enrolled_at = datetime.now(timezone.utc)

    try:
        from agentvault_registry.routers.agent_mtls import _patch_agent_card_mtls
        await _patch_agent_card_mtls(db, agent.did, spiffe_id, enabled=True)
    except Exception as e:
        logger.warning(f"[CoordinatedReinstate] agent card patch failed for {agent.did}: {e}")

    try:
        from agentvault_registry.event_emitter import get_event_emitter
        await get_event_emitter().emit_agent_mtls_enrolled(agent.did, spiffe_id)
    except Exception:
        pass

    return "enrolled"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def coordinated_agent_suspend(
    db: AsyncSession,
    agent: models.Agent,
    reason: str,
    actor: models.Developer,
    *,
    soft: bool = False,
) -> CoordinatedSuspendResult:
    """Couple registry + IRONHAND mTLS + TEG suspend.

    Soft mode: only flips registry status, leaves mTLS + TEG active. Useful
    for soft cooldowns where the admin doesn't want to break cryptographic
    identity.

    The caller is responsible for committing the DB session (this function
    mutates models in-memory; commit happens in the route handler). TEG +
    IRONHAND side effects are out-of-band and persist regardless of registry
    rollback.
    """
    result = CoordinatedSuspendResult(agent_did=agent.did)

    # 1. Registry status flip (always)
    _old_status = agent.status
    agent.status = "suspended"
    agent.enforcement_status = "suspended"
    result.registry = True
    # §ENFPROP (2026-09-05): the flip must reach every peer's MIRROR; only the CARD travels, so touch it
    # on the caller's transaction (the route commits) — measured: a suspension never reached a mirror.
    from agentvault_registry.services import enforcement_propagation as _ep
    await _ep.touch_native_card_no_commit(db, agent.did)

    # A1 (2026-07-24): agent.status_changed was subscribable but never fired.
    # Advisory pre-commit dispatch — same out-of-band posture as the TEG/mTLS
    # side effects below, which also persist regardless of registry rollback.
    if _old_status != "suspended":
        try:
            import asyncio as _aio
            from agentvault_registry.background_tasks.reactor_helpers import dispatch_webhook_for_agents
            _aio.create_task(dispatch_webhook_for_agents(
                "agent.status_changed",
                {"agent_did": agent.did, "old_status": _old_status, "new_status": "suspended",
                 "reason": reason, "soft": soft},
                [agent.did], source_label="coordinated_suspension.suspend"))
        except Exception:
            pass

        # §NOTIFV2 (2026-07-27): tell the owner. Inside the `_old_status != suspended` guard so a
        # re-suspend cannot re-notify, and BEFORE the soft/full branch so both paths notify.
        # THIS FUNCTION IS THE PER-AGENT HELPER cascade_suspend_developer_agents calls in a loop —
        # a developer with 1400+ agents would otherwise get one push per agent. That is exactly
        # why agent.suspended carries coalesce_window_s=300: the resolver sends the first and
        # folds the rest into a "+N more" count.
        try:
            import asyncio as _aio2
            from agentvault_registry.background_tasks.push_notify import notify_agent_owners
            _aio2.create_task(notify_agent_owners(
                "agent.suspended", [agent.did],
                title="Agent suspended",
                message=f"{agent.did[:40]} was suspended. Reason: {reason}",
                # D6-781: the owner's agent list (the console has no #/agents; Pocket opens its own Agents tab)
                tags="warning", priority="high", click="/ui/#/my-agents"))
        except Exception:
            pass

    if soft:
        result.mtls = "skipped"
        result.teg = "skipped"
        return result

    # 2. IRONHAND mTLS revoke
    try:
        result.mtls = await _ironhand_revoke(db, agent, actor_email=actor.email)
    except Exception as e:
        logger.error(f"[CoordinatedSuspend] mTLS revoke threw for {agent.did}: {e}")
        result.mtls = "failed"
        result.error = (result.error or "") + f"mtls:{str(e)[:80]} "

    # 3. TEG suspend
    teg_ok = await _teg_suspend(agent.did, reason)
    result.teg = "suspended" if teg_ok else "failed"
    if not teg_ok:
        result.error = (result.error or "") + "teg:unreachable_or_4xx "

    # 4. RP4 (2026-07-24): cross-TEG blocklist — deny cross-registry RECEIVES too.
    xteg_ok = await _cross_teg_set_block(agent.did, blocked=True, reason=reason)
    result.cross_teg = "blocked" if xteg_ok else "failed"
    if not xteg_ok:
        result.error = (result.error or "") + "cross_teg:unreachable_or_4xx "

    return result


async def coordinated_agent_reinstate(
    db: AsyncSession,
    agent: models.Agent,
    actor: models.Developer,
    *,
    soft: bool = False,
) -> CoordinatedReinstateResult:
    """Reverse of coordinated_agent_suspend. Restores mTLS (fresh SVID) only when the
    suspension revoked it, reactivates TEG, flips registry status to active.
    """
    result = CoordinatedReinstateResult(agent_did=agent.did)

    # 1. Registry status flip
    _was_suspended = agent.status == "suspended"
    if agent.status == "suspended":
        agent.status = "active"
    if getattr(agent, "enforcement_status", None) == "suspended":
        agent.enforcement_status = "active"
    result.registry = True
    # §ENFPROP (2026-09-05): the flip must reach every peer's MIRROR; only the CARD travels, so touch it
    # on the caller's transaction (the route commits) — measured: a suspension never reached a mirror.
    from agentvault_registry.services import enforcement_propagation as _ep
    await _ep.touch_native_card_no_commit(db, agent.did)

    # A1 (2026-07-24): agent.status_changed webhook (reinstate side).
    if _was_suspended:
        try:
            import asyncio as _aio
            from agentvault_registry.background_tasks.reactor_helpers import dispatch_webhook_for_agents
            _aio.create_task(dispatch_webhook_for_agents(
                "agent.status_changed",
                {"agent_did": agent.did, "old_status": "suspended", "new_status": "active",
                 "reason": "reinstate", "soft": soft},
                [agent.did], source_label="coordinated_suspension.reinstate"))
        except Exception:
            pass

        # §NOTIFV2: the reinstate half. Same `_was_suspended` transition guard and the same
        # 300s coalesce window, because the reinstate cascade is per-agent too.
        try:
            import asyncio as _aio2
            from agentvault_registry.background_tasks.push_notify import notify_agent_owners
            _aio2.create_task(notify_agent_owners(
                "agent.reinstated", [agent.did],
                title="Agent reinstated",
                message=f"{agent.did[:40]} is active again.",
                # D6-781: the owner's agent list (the console has no #/agents; Pocket opens its own Agents tab)
                tags="white_check_mark", priority="default", click="/ui/#/my-agents"))
        except Exception:
            pass

    if soft:
        return result

    # 2. mTLS re-enroll (issues fresh SVID)
    try:
        result.mtls = await _ironhand_enroll(db, agent)
    except Exception as e:
        logger.error(f"[CoordinatedReinstate] mTLS enroll threw for {agent.did}: {e}")
        result.mtls = "failed"
        result.error = (result.error or "") + f"mtls:{str(e)[:80]} "

    # 3. TEG reinstate
    teg_ok = await _teg_reinstate(agent.did)
    result.teg = "reinstated" if teg_ok else "failed"
    if not teg_ok:
        result.error = (result.error or "") + "teg:unreachable_or_4xx "

    # 4. RP4 (2026-07-24): lift the cross-TEG receive block (mirror of suspend lever 4).
    xteg_ok = await _cross_teg_set_block(agent.did, blocked=False, reason="reinstate")
    result.cross_teg = "unblocked" if xteg_ok else "failed"
    if not xteg_ok:
        result.error = (result.error or "") + "cross_teg:unreachable_or_4xx "

    return result


# ---------------------------------------------------------------------------
# Convenience: developer cascade
# ---------------------------------------------------------------------------

async def cascade_suspend_developer_agents(
    db: AsyncSession,
    developer_id: int,
    reason: str,
    actor: models.Developer,
    *,
    soft: bool = False,
) -> list[CoordinatedSuspendResult]:
    """Suspend ALL agents owned by developer_id. Returns per-agent results.
    Caller commits the DB session after."""
    res = await db.execute(
        select(models.Agent).where(
            models.Agent.creator_developer_id == developer_id,
            models.Agent.status != "suspended",
        )
    )
    agents = list(res.scalars().all())
    return [
        await coordinated_agent_suspend(db, a, reason=reason, actor=actor, soft=soft)
        for a in agents
    ]


async def cascade_reinstate_developer_agents(
    db: AsyncSession,
    developer_id: int,
    actor: models.Developer,
    *,
    soft: bool = False,
) -> list[CoordinatedReinstateResult]:
    """Reinstate ALL suspended agents owned by developer_id. Only touches
    agents currently in 'suspended' status — agents revoked by another flow
    (e.g., individually suspended after the dev was suspended) stay as-is."""
    res = await db.execute(
        select(models.Agent).where(
            models.Agent.creator_developer_id == developer_id,
            models.Agent.status == "suspended",
        )
    )
    agents = list(res.scalars().all())
    return [
        await coordinated_agent_reinstate(db, a, actor=actor, soft=soft)
        for a in agents
    ]
