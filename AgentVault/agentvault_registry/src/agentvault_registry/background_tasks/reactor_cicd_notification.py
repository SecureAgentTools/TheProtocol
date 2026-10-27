"""
Reactor: CI/CD deployment events → owner / org-admin notifications
====================================================================
§bc5 T5.1-T5.7 (2026-05-19).

Subscribes to three CI/CD event types and converts each into a targeted
notification via `ws_manager.broadcast(..., audience='user_<id>')`:

  DeploymentTriggered      → notify agent OWNER (info)
  DeploymentStatusUpdated  → if status in {succeeded, failed, cancelled},
                              notify owner (info or warning)
  DeploymentWebhookExhausted → CRITICAL — notify owner + ALL org admins
                              (Commander locked T5.7 escalation breadth)

De-duplication: 5-min sliding window per (agent_did, deployment_id, status)
in Redis. Prevents reactor backlog replay from re-firing the same alert.

CTA URL: /ui#/agents/{did}/cicd/deployments/{deployment_id}

Per-user opt-out: NotificationsPanel `mute_cicd_my_agents` /
`mute_cicd_org_agents` toggles in notification_prefs. Checked at message
emit time, not at /local_broadcast (the broadcast envelope can't know if
the receiver is owner vs org-admin).

Each successful emit also writes a `CICDNotificationSent` audit event
(skip_in_projection=true) so ops can review delivery history.

Env gate: REACTOR_CICD_NOTIFICATION_ENABLED (default true).
"""
import logging
import os
from typing import Dict, List, Optional, Tuple

from sqlalchemy import select

from agentvault_registry import models
from agentvault_registry.database import get_db_context
from agentvault_registry.event_emitter import get_event_emitter
from agentvault_registry.routers.websocket import broadcast_notification

from .reactor_base import EventStoreReactor
from .reactor_helpers import local_developer_id

logger = logging.getLogger(__name__)


# Status filter for DeploymentStatusUpdated — only terminal states fire.
_TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}
_DEDUP_TTL_SEC = 300  # 5 min sliding window


def _broadcast_type_for_status(status: str) -> str:
    if status in ("failed", "cancelled"):
        return "warning"
    return "info"


def _cta_for(agent_did: Optional[str], deployment_id: Optional[str]) -> Optional[str]:
    if not agent_did or not deployment_id:
        return None
    return f"/ui#/agents/{agent_did}/cicd/deployments/{deployment_id}"


async def _get_redis():
    try:
        from agentvault_registry.background_tasks.leader import get_redis
        return await get_redis()
    except Exception:
        return None


async def _dedup_should_fire(agent_did: str, deployment_id: str, status: str) -> bool:
    """Returns True if we should fire (sliding window key didn't exist yet),
    False if we should skip (already fired within 5 min)."""
    r = await _get_redis()
    if r is None:
        return True  # No Redis = no dedup; fire anyway
    key = f"cicd_notif:{agent_did}:{deployment_id}:{status}"
    try:
        # SET NX EX — atomic set-if-not-exists with TTL
        was_set = await r.set(key, "1", ex=_DEDUP_TTL_SEC, nx=True)
        return bool(was_set)
    except Exception as e:
        logger.debug(f"[reactor_cicd_notification] dedup check failed for {key}: {e}")
        return True


async def _owner_dev_id_for_agent(agent_did: str) -> Optional[int]:
    """Look up the owning developer for an agent DID."""
    try:
        async with get_db_context() as db:
            r = await db.execute(
                select(models.Agent.developer_id).where(models.Agent.did == agent_did)
            )
            row = r.first()
            return int(row[0]) if row and row[0] else None
    except Exception as e:
        logger.debug(f"_owner_dev_id_for_agent({agent_did}) failed: {e}")
        return None


async def _agent_org_admin_dev_ids(agent_did: str) -> List[int]:
    """Find org admins for the agent's organization (if any). Used for
    DeploymentWebhookExhausted escalation per Commander lock T5.7."""
    try:
        async with get_db_context() as db:
            r = await db.execute(
                select(models.Agent.organization_id).where(models.Agent.did == agent_did)
            )
            row = r.first()
            org_id = row[0] if row else None
            if not org_id:
                return []
            r2 = await db.execute(
                select(models.OrganizationMember.developer_id).where(
                    models.OrganizationMember.organization_id == org_id,
                    models.OrganizationMember.role.in_(["owner", "admin"]),
                )
            )
            return [int(r[0]) for r in r2.fetchall() if r[0]]
    except Exception as e:
        logger.debug(f"_agent_org_admin_dev_ids({agent_did}) failed: {e}")
        return []


async def _dev_prefs(dev_id: int) -> Dict:
    """Best-effort read of Developer.notification_prefs — for CI/CD opt-out
    toggles. Defaults assumed to be empty dict (no opt-out)."""
    try:
        async with get_db_context() as db:
            r = await db.execute(
                select(models.Developer.notification_prefs).where(
                    models.Developer.id == dev_id
                )
            )
            row = r.first()
            return (row[0] or {}) if row else {}
    except Exception:
        return {}


def _passes_cicd_opt_out(prefs: Dict, *, is_org_admin: bool,
                         v2_row: Optional[bool] = None) -> bool:
    """Return True if the notification should fire. Owner toggles:
       mute_cicd_my_agents  → block notifications for their OWN agents
       mute_cicd_org_agents → block notifications they get as org-admin only

    §9 (2026-07-27): `cicd.*` left `legacy_managed`, so it now renders as a real row in the v2
    notification matrix. An explicit v2 preference therefore has to WIN here, or that row would
    be a switch that visibly moves and changes nothing — the exact silent-drop class NOTIFV2
    exists to kill. `v2_row=None` means "developer stated nothing in v2", which falls through to
    the legacy toggles below so existing opt-outs keep working unchanged.
    """
    if v2_row is not None:
        return bool(v2_row)
    if is_org_admin:
        return not bool(prefs.get("mute_cicd_org_agents", False))
    return not bool(prefs.get("mute_cicd_my_agents", False))


async def _v2_cicd_pref(developer_id: int, type_key: str) -> Optional[bool]:
    """Explicit v2 (developer, cicd.*, inapp) row, or None when unstated. Never raises."""
    try:
        from agentvault_registry.database import get_db_context
        from sqlalchemy import text as _text
        async with get_db_context() as db:
            row = (await db.execute(_text(
                "SELECT enabled FROM developer_notification_prefs "
                "WHERE developer_id = :d AND type_key = :k AND channel = 'inapp'"
            ), {"d": developer_id, "k": type_key})).first()
            return bool(row[0]) if row else None
    except Exception:  # noqa: BLE001 — unknown preference must not block a deploy notification
        return None


async def _emit_cicd_audit(event_payload: Dict) -> None:
    """Fire-and-forget CICDNotificationSent audit event."""
    try:
        emitter = get_event_emitter()
        await emitter.emit(
            event_type="CICDNotificationSent",
            aggregate_id=str(event_payload.get("agent_did") or "unknown"),
            aggregate_type="CICDDeployment",
            data=event_payload,
            metadata={"action_class": "cicd_notification"},
        )
    except Exception as e:
        logger.debug(f"CICDNotificationSent audit emit failed: {e}")


async def _fire_one(
    *,
    dev_id: int,
    title: str,
    message: str,
    notification_type: str,
    is_org_admin: bool,
    audit_payload: Dict,
) -> bool:
    prefs = await _dev_prefs(dev_id)
    # §9: the v2 matrix row (if the developer set one) outranks the legacy toggle.
    # notification_type here is the BROADCAST severity, not a deploy status:
    # _broadcast_type_for_status maps failed/cancelled → "warning", everything else → "info",
    # and the webhook-exhausted path sends "critical". So warning/critical are the bad-news
    # cases (cicd.deploy_failed) and info is the good-news one (cicd.deploy_completed).
    _v2_key = ("cicd.deploy_failed" if notification_type in ("warning", "critical")
               else "cicd.deploy_completed")
    _v2 = await _v2_cicd_pref(dev_id, _v2_key)
    if not _passes_cicd_opt_out(prefs, is_org_admin=is_org_admin, v2_row=_v2):
        return False
    try:
        await broadcast_notification(
            title=title,
            message=message,
            notification_type=notification_type,
            audience=f"user_{dev_id}",
        )
        await _emit_cicd_audit({**audit_payload, "delivered_to_dev_id": dev_id, "as_org_admin": is_org_admin})
        return True
    except Exception as e:
        logger.warning(f"[reactor_cicd_notification] fire failed for dev={dev_id}: {e}")
        return False


# ────────────────────────────────────────────────────────────────────────────
# Reactor classes
# ────────────────────────────────────────────────────────────────────────────

class DeploymentTriggeredReactor(EventStoreReactor):
    event_type = "DeploymentTriggered"
    leader_key = "reactor_cicd_triggered"
    name = "DeploymentTriggered"

    async def handle_event(self, event_data: dict) -> None:
        agent_did = event_data.get("agent_did") or event_data.get("did")
        deployment_id = str(event_data.get("deployment_id") or event_data.get("id") or "")
        if not agent_did:
            return
        if not await _dedup_should_fire(agent_did, deployment_id or "(no-id)", "triggered"):
            return

        # The triggering dev_id is often included in the event payload (§pass47 A1).
        # Fall back to looking up the agent owner.
        # §TWOAGENT #34 class (2026-09-23): a bridged event carries the PEER's developer id, which names somebody else
        # here; only a local event's id is ours, and the owner lookup (none for a foreign agent) is the fallback.
        dev_id = local_developer_id(event_data, key="developer_id") or await _owner_dev_id_for_agent(agent_did)
        if not dev_id:
            return
        cta = _cta_for(agent_did, deployment_id)
        audit_payload = {
            "trigger": "DeploymentTriggered",
            "agent_did": agent_did,
            "deployment_id": deployment_id,
        }
        await _fire_one(
            dev_id=int(dev_id),
            title=f"Deployment triggered for {agent_did[:32]}",
            message=f"Deployment #{deployment_id} started." + (f" {cta}" if cta else ""),
            notification_type="info",
            is_org_admin=False,
            audit_payload=audit_payload,
        )


class DeploymentStatusUpdatedReactor(EventStoreReactor):
    event_type = "DeploymentStatusUpdated"
    leader_key = "reactor_cicd_status"
    name = "DeploymentStatusUpdated"

    async def handle_event(self, event_data: dict) -> None:
        agent_did = event_data.get("agent_did") or event_data.get("did")
        deployment_id = str(event_data.get("deployment_id") or event_data.get("id") or "")
        status = (event_data.get("status") or "").lower()
        if not agent_did or status not in _TERMINAL_STATUSES:
            return
        if not await _dedup_should_fire(agent_did, deployment_id or "(no-id)", status):
            return
        dev_id = await _owner_dev_id_for_agent(agent_did)
        if not dev_id:
            return
        cta = _cta_for(agent_did, deployment_id)
        nt = _broadcast_type_for_status(status)
        audit_payload = {
            "trigger": "DeploymentStatusUpdated",
            "agent_did": agent_did,
            "deployment_id": deployment_id,
            "status": status,
        }
        await _fire_one(
            dev_id=int(dev_id),
            title=f"Deployment {status} — {agent_did[:32]}",
            message=f"Deployment #{deployment_id} {status}." + (f" {cta}" if cta else ""),
            notification_type=nt,
            is_org_admin=False,
            audit_payload=audit_payload,
        )


class DeploymentWebhookExhaustedReactor(EventStoreReactor):
    event_type = "DeploymentWebhookExhausted"
    leader_key = "reactor_cicd_webhook_exhausted"
    name = "DeploymentWebhookExhausted"

    async def handle_event(self, event_data: dict) -> None:
        agent_did = event_data.get("agent_did") or event_data.get("did")
        deployment_id = str(event_data.get("deployment_id") or event_data.get("id") or "")
        if not agent_did:
            return
        # T5.3 — dedup keyed on status='exhausted' so re-runs don't re-fire
        if not await _dedup_should_fire(agent_did, deployment_id or "(no-id)", "exhausted"):
            return
        cta = _cta_for(agent_did, deployment_id)
        audit_base = {
            "trigger": "DeploymentWebhookExhausted",
            "agent_did": agent_did,
            "deployment_id": deployment_id,
        }
        # Owner
        owner = await _owner_dev_id_for_agent(agent_did)
        if owner:
            await _fire_one(
                dev_id=int(owner),
                title=f"⚠ Webhook exhausted: {agent_did[:32]}",
                message=f"Deployment #{deployment_id} webhook retries exhausted — manual review required."
                       + (f" {cta}" if cta else ""),
                notification_type="critical",
                is_org_admin=False,
                audit_payload=audit_base,
            )
        # Org admins (excluding owner)
        admin_ids = await _agent_org_admin_dev_ids(agent_did)
        for aid in admin_ids:
            if owner and int(aid) == int(owner):
                continue
            await _fire_one(
                dev_id=int(aid),
                title=f"⚠ Org-agent webhook exhausted: {agent_did[:32]}",
                message=f"Org-owned agent's deployment #{deployment_id} webhook retries exhausted."
                       + (f" {cta}" if cta else ""),
                notification_type="critical",
                is_org_admin=True,
                audit_payload=audit_base,
            )


# ─── module API ─────────────────────────────────────────────────────────────

_triggered: DeploymentTriggeredReactor | None = None
_status: DeploymentStatusUpdatedReactor | None = None
_exhausted: DeploymentWebhookExhaustedReactor | None = None


def _gated() -> bool:
    return os.getenv("REACTOR_CICD_NOTIFICATION_ENABLED", "true").lower() == "true"


async def start() -> None:
    global _triggered, _status, _exhausted
    if not _gated():
        logger.info("[Reactor:CICDNotification] disabled by env gate")
        return
    if _triggered is None: _triggered = DeploymentTriggeredReactor()
    if _status is None: _status = DeploymentStatusUpdatedReactor()
    if _exhausted is None: _exhausted = DeploymentWebhookExhaustedReactor()
    await _triggered.start()
    await _status.start()
    await _exhausted.start()


async def stop() -> None:
    global _triggered, _status, _exhausted
    for r in (_triggered, _status, _exhausted):
        if r is not None:
            try:
                await r.stop()
            except Exception as e:
                logger.warning(f"reactor stop error: {e}")
    _triggered = _status = _exhausted = None
