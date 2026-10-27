"""Reactors: IRONKEY delegation/capability events → device push (POCKET FRAME S2 v1).

Thin reactors (one per event type, matching the one-type-per-reactor base):

    AgentDelegationGranted   → "Delegation granted"      (who → whom, which perms)
    AgentCapabilityIssued    → "Capability token issued" (issuer → holder, budget)
    AgentCapabilityRevoked   → "Capability revoked"      (token + cascade count)
    AgentSpawned             → "Sub-agent spawned"       (parent → child, perms)
                               + throttled admin-oversight toast (§auditfix 2026-07-19)

Side effect: push only (via push_notify fan-out; ntfy live, FCM/APNs stubs).
Recipients: the developers owning the involved agents (+ the granting dev for L3).
Gated by PUSH_NOTIFY_ENABLED (checked at start in main.py AND per-send in the
helper — double gate, default off fleet-wide; canary = frame-c compose).
Δ-irrelevant: the notified action already committed through its own flow.
"""
import logging
import time
from typing import Optional

from .reactor_base import EventStoreReactor
from .push_notify import (
    any_transfer_subscribers,
    notify,                       # §NOTIFV2 — catalog-validated send path
    notify_developers,            # kept for reference; all reactors now go through notify()
    resolve_developer_ids_for_dids,
)

logger = logging.getLogger(__name__)


def _frame_unit() -> str:
    # D6-835 (2026-10-25): this frame's unit, asked where the amount is written (it said AVT on every frame)
    from agentvault_registry.core.frame_currency import frame_currency
    return frame_currency()


class DelegationGrantedPushReactor(EventStoreReactor):
    event_type = "AgentDelegationGranted"
    leader_key = "reactor_push_deleg_granted"
    name = "PushNotify:DelegationGranted"

    async def handle_event(self, event_data: dict) -> None:
        delegate = event_data.get("delegate_agent_did") or "?"
        principal = event_data.get("principal") or "?"
        perms = event_data.get("permissions") or []
        dev_ids = await resolve_developer_ids_for_dids([delegate])
        granted_by = event_data.get("granted_by_dev_id")
        if granted_by is not None:
            dev_ids.append(granted_by)
        await notify(
            "delegation.granted",
            dev_ids,
            title="Delegation granted",
            message=f"{principal} delegated {len(perms)} permission(s) to {delegate}: {', '.join(perms[:6])}",
            tags="ticket",
        )


class CapabilityIssuedPushReactor(EventStoreReactor):
    event_type = "AgentCapabilityIssued"
    leader_key = "reactor_push_cap_issued"
    name = "PushNotify:CapabilityIssued"

    async def handle_event(self, event_data: dict) -> None:
        issuer = event_data.get("issuer_did") or "?"
        holder = event_data.get("holder_did") or "?"
        perms = event_data.get("permissions") or []
        budget = event_data.get("budget_total")
        budget_s = f", budget {budget} {event_data.get('currency') or ''}".rstrip() if budget is not None else ""
        dev_ids = await resolve_developer_ids_for_dids([issuer, holder])
        await notify(
            "capability.issued",
            dev_ids,
            title="Capability token issued",
            message=f"{issuer} → {holder}: {', '.join(perms[:6]) or 'no perms'}{budget_s}",
            tags="key",
        )


class CapabilityRevokedPushReactor(EventStoreReactor):
    event_type = "AgentCapabilityRevoked"
    leader_key = "reactor_push_cap_revoked"
    name = "PushNotify:CapabilityRevoked"

    async def handle_event(self, event_data: dict) -> None:
        token_id = event_data.get("token_id")
        revoked_by = event_data.get("revoked_by") or "?"
        count = event_data.get("revoked_count")
        dev_ids = await resolve_developer_ids_for_dids(
            [event_data.get("issuer_did"), event_data.get("holder_did"), revoked_by]
        )
        await notify(
            "capability.revoked",
            dev_ids,
            title="Capability revoked",
            message=f"Token #{token_id} revoked by {revoked_by} (cascade: {count} token(s))",
            tags="no_entry",
            priority="max",  # security/panic event → bypass phone Do-Not-Disturb (ntfy 5)
        )


# §auditfix (2026-07-19): throttle the admin toast (NOT the owner push) so a burst
# spawner doesn't fan a toast per child to every connected enforcement admin. Same
# 30s pattern as reactor_agent_suspended; per-process state is the single source of
# truth because the reactor is leader-elected.
_SPAWN_TOAST_THROTTLE_SECONDS = 30
_last_spawn_toast_at: float = 0.0


class AgentSpawnedPushReactor(EventStoreReactor):
    """AgentSpawned → owner push + throttled admin-oversight toast (§auditfix 2026-07-19).

    Closes the write-only gap: the spawn event was emitted since AGENTFIX-3 but consumed
    by nothing — a sub-agent could enter the network with no one watching in real time.
    Parent and child share an owning developer (spawn inherits the parent's dev), so the
    owner resolve is one DID; the toast gives enforcement admins the fleet-level view.
    """
    event_type = "AgentSpawned"
    leader_key = "reactor_push_agent_spawned"
    name = "PushNotify:AgentSpawned"

    async def handle_event(self, event_data: dict) -> None:
        parent = event_data.get("parent_did") or "?"
        child = event_data.get("child_did") or "?"
        perms = event_data.get("permissions") or []
        birth_id = event_data.get("birth_token_id")
        dev_ids = await resolve_developer_ids_for_dids([parent, child])
        await notify(
            "agent.spawned",
            dev_ids,
            title="Sub-agent spawned",
            message=(f"{parent} spawned {child}: "
                     f"{', '.join(perms[:6]) or 'no permissions'} (birth token #{birth_id})"),
            tags="seedling",
        )
        # Admin-oversight toast — throttled, best-effort, never blocks the push path.
        global _last_spawn_toast_at
        now = time.monotonic()
        if (now - _last_spawn_toast_at) >= _SPAWN_TOAST_THROTTLE_SECONDS:
            try:
                from agentvault_registry.routers.websocket import broadcast_notification
                short = lambda d: d.split(":")[-1][:12] if isinstance(d, str) else "?"  # noqa: E731
                await broadcast_notification(
                    title="Sub-agent spawned",
                    message=f"{short(parent)} → {short(child)} ({len(perms)} perm(s))",
                    notification_type="info",
                    audience="admin_enforcement",
                )
                _last_spawn_toast_at = now
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    f"[Reactor:{self.name}] broadcast_notification failed (non-fatal): {e}"
                )


class TransferPushReactor(EventStoreReactor):
    """P2-2 (2026-07-07): TokensTransferred → push, STRICTLY OPT-IN per device via
    prefs.min_transfer_avt (absent = silent). Volume-guarded for sim-heavy frames:
    a ~30s-cached subscriber probe early-exits before any per-event work when no
    device has opted in — the common case costs one cache read per event."""
    event_type = "TokensTransferred"
    leader_key = "reactor_push_transfer"
    name = "PushNotify:Transfer"

    async def handle_event(self, event_data: dict) -> None:
        if not await any_transfer_subscribers():
            return
        sender = event_data.get("from")
        receiver = event_data.get("to")
        try:
            amount = float(event_data.get("amount") or 0)
        except (TypeError, ValueError):
            amount = 0.0
        if amount <= 0:
            return
        dev_ids = await resolve_developer_ids_for_dids([sender, receiver])
        if not dev_ids:
            return
        memo = event_data.get("memo")
        memo_s = f' — "{str(memo)[:60]}"' if memo else ""
        await notify(
            "money.received",
            dev_ids,
            title=f"Transfer: {amount:g} {event_data.get('currency') or _frame_unit()}",   # D6-835: not AVT on every frame
            message=f"{sender} → {receiver}{memo_s}",
            tags="moneybag",
            amount=amount,
        )


_instances: Optional[list] = None


async def start() -> None:
    global _instances
    if _instances is None:
        _instances = [
            DelegationGrantedPushReactor(),
            CapabilityIssuedPushReactor(),
            CapabilityRevokedPushReactor(),
            AgentSpawnedPushReactor(),
            TransferPushReactor(),
        ]
    for r in _instances:
        await r.start()


async def stop() -> None:
    global _instances
    if _instances is not None:
        for r in _instances:
            await r.stop()
        _instances = None
