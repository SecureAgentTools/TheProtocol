"""V0657 (b), item 8, session-code 2026-11-06: an agent can run its organization.

Every management route of the organization took a person's login, so an agent the organization had given its
admin authority (session-lead, in TheProtocol Sessions) was refused 401 on all of them. Agents already hold
organization authority: IRONKEY organization grants (`agent_delegation_grants`, principal `org:<slug>`), each carrying
the permission slice of a level (services/org_authz.py: guest, member, admin, owner). This module reads that
authority for the management routes:

  * a PERSON acts by the membership role, exactly as before (OrganizationService.check_member_permission);
  * an AGENT acts by its live organization grant: the agent belongs to the organization (agents.organization_id), the
    organization is active, the agent is active, the grant is neither revoked nor expired, and its permissions (less
    what no organization slice may carry) cover the slice of the level the act needs. The highest level covered is
    the agent's level.

Which level each act needs (the Commander's answer, seq 1482, and the discovery's item 8): admin to bring agents in and
to invite, owner for the settings and the roles. The treasury, the ownership and deleting the organization stay with
people (`people_only`). Every act an agent makes is written to security_audit_logs as that agent (`org.<action>`).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from . import org_authz

logger = logging.getLogger(__name__)

LEVELS = ("guest", "member", "admin", "owner")


def rank(level: Optional[str]) -> int:
    return LEVELS.index(level) if level in LEVELS else -1


@dataclass
class OrgActor:
    kind: str                         # 'developer' | 'agent'
    level: str                        # the authority it holds in this organization
    developer: Any = None             # the Developer, for a person
    agent_did: Optional[str] = None   # the agent's DID, for an agent

    @property
    def ref(self) -> str:
        """How a request or a decision names who made it: a developer id, or the agent's DID."""
        return str(self.developer.id) if self.kind == "developer" else str(self.agent_did)

    @property
    def developer_id(self) -> Optional[int]:
        return int(self.developer.id) if self.kind == "developer" else None


def level_of_permissions(permissions) -> Optional[str]:
    """The highest organization level whose slice these permissions cover (None when not even the guest slice)."""
    granted = {p for p in (permissions or [])} - org_authz.NEVER_IN_ORG_SLICES
    best = None
    for level in LEVELS:
        if org_authz.ORG_ROLE_PERMISSION_DEFAULTS[level] <= granted:
            best = level
    return best


async def agent_org_level(db: AsyncSession, agent_did: str, org) -> Optional[str]:
    """The level an agent holds in `org` by its live organization grant, or None (not linked, inactive, no grant)."""
    if not agent_did or org is None or not getattr(org, "is_active", False):
        return None
    row = (await db.execute(text(
        "SELECT status, organization_id FROM agents WHERE did = :d"), {"d": agent_did})).first()
    if row is None or str(row[0] or "").lower() != "active" or str(row[1] or "") != str(org.id):
        return None
    grants = (await db.execute(text(
        "SELECT permissions FROM agent_delegation_grants WHERE principal_type = 'org' "
        "AND principal_ref IN (:ref_slug, :ref_id) AND delegate_agent_did = :d "
        "AND revoked_at IS NULL AND (expires_at IS NULL OR expires_at > now())"),
        {"ref_slug": f"org:{org.slug}", "ref_id": f"org:{org.id}", "d": agent_did})).fetchall()
    best = None
    for (perms,) in grants:
        lvl = level_of_permissions(perms)
        if rank(lvl) > rank(best):
            best = lvl
    return best


async def developer_org_level(db: AsyncSession, developer_id: int, org) -> Optional[str]:
    """A person's level: the owner column first, then the active membership's role."""
    if org is None:
        return None
    if int(getattr(org, "owner_id", -1)) == int(developer_id):
        return "owner"
    row = (await db.execute(text(
        "SELECT role FROM organization_members WHERE organization_id = :o AND developer_id = :d AND is_active = TRUE"),
        {"o": str(org.id), "d": int(developer_id)})).first()
    return str(row[0]) if row and str(row[0]) in LEVELS else None


async def org_authority(db: AsyncSession, org_id: str, actor: Dict[str, Any], need: str, *,
                        people_only: bool = False) -> Tuple[Any, OrgActor]:
    """The organization and who acts in it, when the actor holds at least `need` there; else 404 (no such
    organization) or 403 (the sentence says what it holds and what the act needs). `actor` is the dependency's dict
    (security.get_current_actor_for_read_or_key)."""
    from .organization_service import OrganizationService
    org = await OrganizationService.get_organization(db, org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    if actor.get("kind") == "agent":
        did = actor.get("agent_did")
        if people_only:
            raise HTTPException(status_code=403, detail="This is done by a person of the organization; an agent "
                                                        "cannot do it, whatever authority it holds")
        level = await agent_org_level(db, did, org)
        if rank(level) < rank(need):
            held = f"holds {level} authority" if level else "holds no authority"
            raise HTTPException(status_code=403, detail=(
                f"This agent {held} in the organization; this needs {need}. An organization gives an agent authority "
                f"with an organization grant (POST /api/v1/organizations/{org.id}/agents/grant-bulk)"))
        return org, OrgActor(kind="agent", level=level, agent_did=did)
    dev = actor.get("developer")
    if dev is None:
        raise HTTPException(status_code=401, detail="Could not validate credentials")
    if not await OrganizationService.check_member_permission(db, org_id, dev.id, None if need == "guest" else need):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return org, OrgActor(kind="developer", level=await developer_org_level(db, dev.id, org) or need, developer=dev)


async def audit(db: AsyncSession, who: OrgActor, action: str, org_id: str, *, target_type: Optional[str] = None,
                target_id: Optional[str] = None, details: Optional[Dict[str, Any]] = None) -> None:
    """security_audit_logs as `org.<action>`, the actor named as itself (an agent by its DID). Best effort."""
    try:
        from .admin_audit import _log_action
        await _log_action(db, prefix="org", action=action, actor_type=who.kind, actor_id=who.ref,
                          target_type=target_type or "organization", target_id=target_id or str(org_id),
                          details={"organization_id": str(org_id), "level": who.level, **(details or {})})
    except Exception as e:  # noqa: BLE001
        logger.warning("[ORG-ACTOR] audit of org.%s by %s failed: %s", action, who.ref, e)


__all__ = ["LEVELS", "rank", "OrgActor", "level_of_permissions", "agent_org_level", "developer_org_level",
           "org_authority", "audit"]
