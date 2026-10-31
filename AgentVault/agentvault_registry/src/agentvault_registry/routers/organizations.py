"""
Organizations and Teams API Router

Provides REST API endpoints for managing organizations, teams, and memberships.
"""

from typing import List, Optional, Dict, Any, Annotated
import logging
from fastapi import APIRouter, Depends, HTTPException, Query, Path, Body, Security, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, EmailStr, field_validator

from agentvault_registry.core.web_address import web_address_or_empty
from sqlalchemy import text as sa_text
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry.database import get_db
from agentvault_registry.models import Developer, Organization, Team, OrganizationMember, TeamMember
from agentvault_registry.services.organization_service import (
    OrganizationService,
    TeamService,
    TeamNameTaken,
    InvitationService
)
from agentvault_registry.security import get_current_developer, get_current_developer_optional, get_current_actor_for_read

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/organizations",
    # §pass56 PR-5+PR-6: tags= dropped; main.py:include_router supplies "Organizations"
    responses={404: {"description": "Not found"}},
)


# --- Pydantic Models ---

class OrganizationCreate(BaseModel):
    """Schema for creating an organization."""
    name: str = Field(..., min_length=3, max_length=255, description="Organization name")
    description: Optional[str] = Field(None, max_length=1000, description="Organization description")
    website: Optional[str] = Field(None, max_length=500, description="Organization website URL")
    logo_url: Optional[str] = Field(None, max_length=500, description="Organization logo URL")
    settings: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Organization settings")

    # §FESUITE 135: the website is a link everyone who opens the organization can press; only http(s) is stored
    @field_validator("website")
    @classmethod
    def _website(cls, v):
        return web_address_or_empty(v, "website")


class OrganizationUpdate(BaseModel):
    """Schema for updating an organization."""
    name: Optional[str] = Field(None, min_length=3, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    website: Optional[str] = Field(None, max_length=500)
    logo_url: Optional[str] = Field(None, max_length=500)
    settings: Optional[Dict[str, Any]] = None

    @field_validator("website")
    @classmethod
    def _website(cls, v):
        return web_address_or_empty(v, "website")


class OrganizationResponse(BaseModel):
    """Schema for organization response."""
    id: str
    name: str
    slug: str
    owner_id: int
    description: Optional[str]
    website: Optional[str]
    logo_url: Optional[str]
    created_at: str
    updated_at: str
    is_active: bool
    settings: Dict[str, Any]
    limits: Dict[str, int]
    member_count: Optional[int] = None
    team_count: Optional[int] = None
    # §ORGPOCKET (2026-08-28) — what the caller IS here, and whether something is
    # waiting on them. Both were only knowable by extra per-org round trips.
    my_role: Optional[str] = None
    pending_owner_is_me: Optional[bool] = None


class TeamCreate(BaseModel):
    """Schema for creating a team."""
    name: str = Field(..., min_length=3, max_length=255, description="Team name")
    description: Optional[str] = Field(None, max_length=1000, description="Team description")
    permissions: Optional[List[str]] = Field(
        default=["read_agents", "create_agents"],
        description="Team permissions"
    )


class TeamUpdate(BaseModel):
    """Schema for updating a team."""
    name: Optional[str] = Field(None, min_length=3, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    permissions: Optional[List[str]] = None


class TeamResponse(BaseModel):
    """Schema for team response."""
    id: str
    organization_id: str
    name: str
    description: Optional[str]
    created_at: str
    updated_at: str
    is_active: bool
    permissions: List[str]
    member_count: Optional[int] = None
    # §ORGLIFE T4 — who is actually in this team, on the card. The count was already
    # here; the names were behind a modal, so a teams tab could not answer the first
    # question anyone asks of a team. Capped at the card's width by the caller.
    member_names: List[str] = []


class MemberInvite(BaseModel):
    """Schema for inviting a member."""
    email: EmailStr = Field(..., description="Email address to invite")
    role: str = Field("member", pattern="^(admin|member|guest)$", description="Role for the invited member")


class MemberResponse(BaseModel):
    """Schema for member response."""
    id: str
    developer_id: int
    developer_name: str
    developer_email: str
    role: str
    joined_at: str
    is_active: bool
    # V0650 (l): named by the owner to decide the approval requests agents post in the org's room.
    can_approve: bool = False


class MemberApproverUpdate(BaseModel):
    """V0650 (l): name (or un-name) a member as an approver of the org room's approval requests (owner only)."""
    can_approve: bool = Field(..., description="May this member decide the approval requests agents post in the "
                                               "organization's room")


class TeamMemberAdd(BaseModel):
    """Schema for adding a team member."""
    developer_id: int = Field(..., description="Developer ID to add to team")
    role: str = Field("member", pattern="^(lead|member)$", description="Role in the team")


class MemberRoleUpdate(BaseModel):
    """Schema for changing a member's org role. 'owner' is deliberately not
    settable — ownership moves via transfer, never a role edit."""
    role: str = Field(..., pattern="^(admin|member|guest)$", description="New role for the member")


class OwnershipTransferCreate(BaseModel):
    """E1a — owner offers the org to an existing active ADMIN member."""
    to_developer_id: int = Field(..., description="Developer ID of the admin member to offer ownership to")


class OwnershipTransferRespond(BaseModel):
    """E1a — the offered developer accepts or declines."""
    accept: bool = Field(..., description="true = accept ownership (and its liability), false = decline")


# --- Helper Functions ---

async def get_organization_with_permission(
    org_id: str,
    developer: Developer,
    db: AsyncSession,
    required_role: Optional[str] = None
) -> Organization:
    """Get organization and verify developer has permission."""
    
    org = await OrganizationService.get_organization(db, org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    
    has_permission = await OrganizationService.check_member_permission(
        db, org_id, developer.id, required_role
    )
    
    if not has_permission:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    return org


# --- Organization Endpoints ---

@router.post("", response_model=OrganizationResponse)
async def create_organization(
    org_data: OrganizationCreate,
    current_developer: Annotated[Developer, Security(get_current_developer)],
    db: AsyncSession = Depends(get_db)
):
    """Create a new organization with the current user as owner."""

    # §OCOPTIN (2026-08-28): creation-time settings go through the SAME catalog
    # allowlist as PUT /settings — before this, create accepted any JSON and a
    # key nothing reads would echo back forever (the exact class §ORGPOCKET
    # closed on the PUT). This is what makes "opt in on firm creation" real:
    # {"public_transparency_opt_in": true} is a validated catalog key.
    if org_data.settings:
        from agentvault_registry.services import org_policy
        ok, err = org_policy.validate_org_settings_patch(org_data.settings)
        if not ok:
            raise HTTPException(status_code=422, detail=err)

    try:
        org = await OrganizationService.create_organization(
            db=db,
            name=org_data.name,
            owner=current_developer,
            description=org_data.description,
            website=org_data.website,
            logo_url=org_data.logo_url,
            settings=org_data.settings
        )
        
        return OrganizationResponse(
            id=org.id,
            name=org.name,
            slug=org.slug,
            owner_id=org.owner_id,
            description=org.description,
            website=org.website,
            logo_url=org.logo_url,
            created_at=org.created_at.isoformat(),
            updated_at=org.updated_at.isoformat(),
            is_active=org.is_active,
            settings=org.settings or {},
            limits=org.limits or {},
            member_count=1,  # Owner is the first member
            team_count=1  # Default team created
        )
    except Exception as e:
        logger.error(f"Internal error: {e}")
        raise HTTPException(status_code=400, detail="An internal error occurred")


@router.get("", response_model=List[OrganizationResponse])
async def list_organizations(
    current_developer: Annotated[Developer, Security(get_current_developer)],
    db: AsyncSession = Depends(get_db)
):
    """List all organizations the current user is a member of."""
    
    orgs = await OrganizationService.list_developer_organizations(
        db, current_developer.id
    )

    # §ORGPOCKET — counts and standing in TWO grouped queries for the whole list,
    # never one pair per org. `member_count`/`team_count` were declared on this
    # response (and non-optional in the FE type) while every row answered null.
    ids = [o.id for o in orgs]
    counts: Dict[str, Dict[str, int]] = {}
    roles: Dict[str, str] = {}
    if ids:
        from sqlalchemy import text as _sa_text
        mrows = (await db.execute(_sa_text(
            "SELECT organization_id, count(*) AS n FROM organization_members "
            "WHERE organization_id = ANY(:ids) AND is_active = true GROUP BY organization_id"
        ), {"ids": ids})).all()
        # §DOCSFIX D6-502 (2026-10-16): a deleted team keeps its row, inactive; it is not a team any more
        trows = (await db.execute(_sa_text(
            "SELECT organization_id, count(*) AS n FROM teams "
            "WHERE organization_id = ANY(:ids) AND is_active = true GROUP BY organization_id"
        ), {"ids": ids})).all()
        for oid, n in mrows:
            counts.setdefault(str(oid), {})["m"] = int(n)
        for oid, n in trows:
            counts.setdefault(str(oid), {})["t"] = int(n)
        rrows = (await db.execute(_sa_text(
            "SELECT organization_id, role FROM organization_members "
            "WHERE organization_id = ANY(:ids) AND developer_id = :d AND is_active = true"
        ), {"ids": ids, "d": current_developer.id})).all()
        for oid, role in rrows:
            roles[str(oid)] = str(role)

    return [
        OrganizationResponse(
            id=org.id,
            name=org.name,
            slug=org.slug,
            owner_id=org.owner_id,
            description=org.description,
            website=org.website,
            logo_url=org.logo_url,
            created_at=org.created_at.isoformat(),
            updated_at=org.updated_at.isoformat(),
            is_active=org.is_active,
            settings=org.settings or {},
            limits=org.limits or {},
            member_count=counts.get(org.id, {}).get("m", 0),
            team_count=counts.get(org.id, {}).get("t", 0),
            # ownership is the org column, not a membership row: an owner who was
            # never inserted into organization_members is still the owner.
            my_role=("owner" if org.owner_id == current_developer.id
                     else roles.get(org.id)),
            pending_owner_is_me=(getattr(org, "pending_owner_id", None) == current_developer.id),
        )
        for org in orgs
    ]


@router.get("/{org_id}", response_model=OrganizationResponse)
async def get_organization(
    org_id: str = Path(..., description="Organization ID"),
    current_developer: Annotated[Developer, Security(get_current_developer)] = None,
    db: AsyncSession = Depends(get_db)
):
    """Get organization details by ID."""
    
    org = await get_organization_with_permission(
        org_id, current_developer, db
    )
    
    # Get counts
    org_with_relations = await OrganizationService.get_organization(
        db, org_id, include_members=True, include_teams=True
    )
    
    return OrganizationResponse(
        id=org.id,
        name=org.name,
        slug=org.slug,
        owner_id=org.owner_id,
        description=org.description,
        website=org.website,
        logo_url=org.logo_url,
        created_at=org.created_at.isoformat(),
        updated_at=org.updated_at.isoformat(),
        is_active=org.is_active,
        settings=org.settings or {},
        limits=org.limits or {},
        # §DOCSFIX D6-502: active rows only, as the list route counts them (a deleted team keeps an inactive row)
        member_count=sum(1 for m in org_with_relations.members if m.is_active) if org_with_relations else 0,
        team_count=sum(1 for t in org_with_relations.teams if t.is_active) if org_with_relations else 0
    )


@router.get("/slug/{slug}", response_model=OrganizationResponse)
async def get_organization_by_slug(
    slug: str = Path(..., description="Organization slug"),
    current_developer: Annotated[Developer, Security(get_current_developer)] = None,
    db: AsyncSession = Depends(get_db)
):
    """Get organization details by slug."""
    
    org = await OrganizationService.get_organization_by_slug(db, slug)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    
    # Check permission
    has_permission = await OrganizationService.check_member_permission(
        db, org.id, current_developer.id
    )
    
    if not has_permission:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    return OrganizationResponse(
        id=org.id,
        name=org.name,
        slug=org.slug,
        owner_id=org.owner_id,
        description=org.description,
        website=org.website,
        logo_url=org.logo_url,
        created_at=org.created_at.isoformat(),
        updated_at=org.updated_at.isoformat(),
        is_active=org.is_active,
        settings=org.settings or {},
        limits=org.limits or {}
    )


@router.put("/{org_id}", response_model=OrganizationResponse)
async def update_organization(
    org_id: str = Path(..., description="Organization ID"),
    org_update: OrganizationUpdate = Body(...),
    current_developer: Annotated[Developer, Security(get_current_developer)] = None,
    db: AsyncSession = Depends(get_db)
):
    """Update organization details (requires admin or owner role). `settings`, when given, is a partial patch
    validated and merged exactly as `PUT /{org_id}/settings` does it.

    \f
    §SECFIX D6-492 (2026-10-16): `settings` here REPLACED organizations.settings wholesale with no validation at all:
    keys outside the catalog, values outside it, an intake agent outside the organization, a key another door owns
    (room_assistant_present), or {} wiping every setting the organization had."""

    current = await get_organization_with_permission(
        org_id, current_developer, db, required_role="admin"
    )
    fields = org_update.model_dump(exclude_unset=True)
    patch = fields.pop("settings", None)
    if patch is not None:
        fields["settings"] = await _merged_settings(db, current, org_id, patch)

    org = await OrganizationService.update_organization(
        db, org_id, **fields
    )
    
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    
    return OrganizationResponse(
        id=org.id,
        name=org.name,
        slug=org.slug,
        owner_id=org.owner_id,
        description=org.description,
        website=org.website,
        logo_url=org.logo_url,
        created_at=org.created_at.isoformat(),
        updated_at=org.updated_at.isoformat(),
        is_active=org.is_active,
        settings=org.settings or {},
        limits=org.limits or {}
    )


async def _merged_settings(db: AsyncSession, org: Organization, org_id: str, patch: Any) -> Dict[str, Any]:
    """`org`'s settings with `patch` applied: the one way organizations.settings is written, for PUT /{org_id}/settings
    and the `settings` of PUT /{org_id}. The patch is validated against the catalog (org_policy, 422 on refusal), the
    intake agent against the database, then deep-merged (liability by sub-key). Keys the patch does not name are kept,
    those another door owns (room_assistant_present) included."""
    from agentvault_registry.services import org_policy
    ok, err = org_policy.validate_org_settings_patch(patch)
    if not ok:
        raise HTTPException(status_code=422, detail=err)
    # §FIRMHIRE — intake_agent_did has a DB half the pure validator can't check:
    # it must be an ACTIVE agent ASSIGNED to THIS org (empty clears the door).
    intake = patch.get("intake_agent_did")
    if intake:
        row = (await db.execute(sa_text(
            "SELECT status, organization_id FROM agents WHERE did = :d"
        ), {"d": intake})).first()
        if not row:
            raise HTTPException(status_code=422, detail="intake_agent_did: agent not found")
        if str(row[0]).lower() != "active":
            raise HTTPException(status_code=422,
                                detail=f"intake_agent_did: agent is not active (status={row[0]})")
        if not row[1] or str(row[1]) != str(org_id):
            raise HTTPException(status_code=422,
                                detail="intake_agent_did: agent is not assigned to this organization")
    merged = dict(org.settings or {})
    for k, v in patch.items():
        if k == "liability" and isinstance(v, dict):
            cur = dict(merged.get("liability") or {})
            cur.update(v)
            merged["liability"] = cur
        else:
            merged[k] = v
    return merged


@router.get("/{org_id}/settings", summary="Org configurable settings + catalog + registry posture")
async def get_organization_settings(
    org_id: str = Path(..., description="Organization ID"),
    current_developer: Annotated[Developer, Security(get_current_developer)] = None,
    db: AsyncSession = Depends(get_db),
):
    """This org's configurable settings, the catalog of what an org admin may set, and the registry's
    current liability posture, so the UI can show that org policy is TIGHTEN-ONLY on top of it."""
    from agentvault_registry.services import org_policy
    from agentvault_registry.config import settings as app_settings
    org = await get_organization_with_permission(org_id, current_developer, db)
    reg_mode = (getattr(app_settings, "LIABILITY_MODE", "off") or "off").lower()
    reg_thr = float(getattr(app_settings, "LIABILITY_PRESENCE_THRESHOLD_AVT", 0) or 0)
    # E1a — the pending ownership offer rides the settings payload (the Settings tab is
    # where the ownership card lives). Reading it here also self-retires an expired offer.
    pending = await OrganizationService.pending_transfer_state(db, org)
    return {
        "org_id": org.id,
        "settings": org.settings or {},
        "catalog": org_policy.ORG_SETTING_CATALOG,
        "registry": {"liability_mode": reg_mode, "presence_threshold_avt": reg_thr},
        "owner_id": org.owner_id,
        "pending_ownership_transfer": pending,
    }


@router.put("/{org_id}/settings", summary="Update org configurable settings (admin/owner, tighten-only)")
async def update_organization_settings(
    org_id: str = Path(..., description="Organization ID"),
    patch: Dict[str, Any] = Body(..., description="Partial settings to merge (see the catalog from GET)"),
    current_developer: Annotated[Developer, Security(get_current_developer)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Validate + deep-merge a settings PATCH into organizations.settings (admin/owner only). Liability
    is enforced TIGHTEN-ONLY at the gate regardless of what is stored; this validates shape + range."""
    org = await get_organization_with_permission(org_id, current_developer, db, required_role="admin")
    merged = await _merged_settings(db, org, org_id, patch)
    updated = await OrganizationService.update_organization(db, org_id, settings=merged)
    if not updated:
        raise HTTPException(status_code=404, detail="Organization not found")
    return {"org_id": org_id, "settings": updated.settings or {}}


@router.delete("/{org_id}")
async def delete_organization(
    org_id: str = Path(..., description="Organization ID"),
    current_developer: Annotated[Developer, Security(get_current_developer)] = None,
    db: AsyncSession = Depends(get_db)
):
    """Delete an organization (requires owner role)."""
    
    org = await get_organization_with_permission(
        org_id, current_developer, db
    )
    
    # Only owner can delete
    if org.owner_id != current_developer.id:
        raise HTTPException(status_code=403, detail="Only the owner can delete the organization")

    # E1b — the corporate-death sequence. Deletion is refused while money would be
    # stranded: a non-delisted AGORA listing keeps its own governed purse, and a funded
    # org treasury is keyless, so a deactivated org would put its balance beyond every
    # user-facing rail. The 409 detail is a checklist the FE renders verbatim.
    from agentvault_registry.services import org_treasury as org_treasury_svc
    blockers = await org_treasury_svc.org_treasury_blockers(db, org_id)
    if blockers:
        raise HTTPException(status_code=409, detail={
            "message": "Organization cannot be deleted yet: resolve these first",
            "blockers": blockers,
        })

    # Teardown rides the SAME transaction the soft-delete commits: authority from a dead
    # org must die with it (the resolver also checks org liveness — belt and braces), and
    # agents must not keep pointing at a dead org. The zero-balance keyless treasury agent
    # and the treasury_agent_did column stay for audit; both are inert.
    from sqlalchemy import text as _text
    revoked = (await db.execute(_text(
        "UPDATE agent_delegation_grants SET revoked_at = now(), revoke_reason = 'org deleted' "
        "WHERE principal_type = 'org' AND (principal_ref = :ref_slug OR principal_ref = :ref_id) "
        "AND revoked_at IS NULL"
    ), {"ref_slug": f"org:{org.slug}", "ref_id": f"org:{org.id}"})).rowcount or 0
    unassigned = (await db.execute(_text(
        "UPDATE agents SET organization_id = NULL, team_id = NULL WHERE organization_id = :o"
    ), {"o": str(org_id)})).rowcount or 0

    success = await OrganizationService.delete_organization(db, org_id)

    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete organization")

    logger.info("[ORG-DELETE] org=%s by dev=%s grants_revoked=%d agents_unassigned=%d",
                org_id, current_developer.id, revoked, unassigned)
    return {"message": "Organization deleted successfully",
            "grants_revoked": revoked, "agents_unassigned": unassigned}


# --- Team Endpoints ---

@router.post("/{org_id}/teams", response_model=TeamResponse)
async def create_team(
    org_id: str = Path(..., description="Organization ID"),
    team_data: TeamCreate = Body(...),
    current_developer: Annotated[Developer, Security(get_current_developer)] = None,
    db: AsyncSession = Depends(get_db)
):
    """Create a new team within an organization (requires admin or owner role)."""
    
    await get_organization_with_permission(
        org_id, current_developer, db, required_role="admin"
    )
    
    try:
        team = await TeamService.create_team(
            db=db,
            organization_id=org_id,
            name=team_data.name,
            description=team_data.description,
            permissions=team_data.permissions
        )
        
        return TeamResponse(
            id=team.id,
            organization_id=team.organization_id,
            name=team.name,
            description=team.description,
            created_at=team.created_at.isoformat(),
            updated_at=team.updated_at.isoformat(),
            is_active=team.is_active,
            permissions=team.permissions or [],
            member_count=0
        )
    except TeamNameTaken as e:   # §MCPTEST30 (V0524): the name is taken by an active team: a conflict, not a bad request
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        # 2026-07-16: a ValueError here is a USER-facing validation rejection
        # (e.g. "Developer is already a team member", invalid/expired invitation
        # token) — surfacing str(e) instead of the generic "An internal error
        # occurred" tells the caller WHY the 400 happened. The tester was
        # (correctly) counting the masked message as a red because it looked
        # like a 500. Only ValueError is surfaced; bare Exception handlers stay
        # generic so genuine internals aren't leaked.
        logger.warning(f"Organization validation rejected: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{org_id}/teams", response_model=List[TeamResponse])
async def list_teams(
    org_id: str = Path(..., description="Organization ID"),
    current_developer: Annotated[Developer, Security(get_current_developer)] = None,
    db: AsyncSession = Depends(get_db)
):
    """List all teams in an organization."""
    
    await get_organization_with_permission(
        org_id, current_developer, db
    )
    
    teams = await TeamService.list_organization_teams(db, org_id)

    # §ORGLIFE T4 — ONE grouped query for every team's roster, replacing a
    # get_team(include_members=True) per team (an N+1 that only ever produced a
    # count). Names come from the same read, so the card can finally answer
    # "who is in this team" without opening the modal.
    rosters: Dict[str, List[str]] = {}
    counts: Dict[str, int] = {}
    if teams:
        from sqlalchemy import text as _text
        # §DOCSFIX D6-502 (2026-10-16): a member removed from a team keeps an inactive row; the roster is who is in it
        for tid, dname, demail, n in (await db.execute(_text(
            "SELECT tm.team_id, d.name, d.email, count(*) OVER (PARTITION BY tm.team_id) "
            "  FROM team_members tm JOIN developers d ON d.id = tm.developer_id "
            " WHERE tm.team_id = ANY(:tids) AND tm.is_active = true ORDER BY tm.team_id, tm.id"
        ), {"tids": [t.id for t in teams]})).fetchall():
            counts[str(tid)] = int(n)
            rosters.setdefault(str(tid), []).append(dname or (demail or "").split("@")[0])

    return [
        TeamResponse(
            id=team.id,
            organization_id=team.organization_id,
            name=team.name,
            description=team.description,
            created_at=team.created_at.isoformat(),
            updated_at=team.updated_at.isoformat(),
            is_active=team.is_active,
            permissions=team.permissions or [],
            member_count=counts.get(str(team.id), 0),
            member_names=rosters.get(str(team.id), [])[:6],
        )
        for team in teams
    ]


async def _team_of_org(db: AsyncSession, org_id: str, team_id: str):
    """§MCPTEST30 (2026-10-01): the team a route acts on, refused unless it belongs to the org whose authority the route
    checked. Without it, the routes below took the caller's role in org_id and acted on team_id of ANY org (the read
    and the delete already asked this; the update asked it after it had written, the member routes never)."""
    team = await TeamService.get_team(db, team_id)
    if not team or team.organization_id != org_id:
        raise HTTPException(status_code=404, detail="Team not found")
    return team


@router.get("/{org_id}/teams/{team_id}", response_model=TeamResponse)
async def get_team(
    org_id: str = Path(..., description="Organization ID"),
    team_id: str = Path(..., description="Team ID"),
    current_developer: Annotated[Developer, Security(get_current_developer)] = None,
    db: AsyncSession = Depends(get_db)
):
    """Get team details by ID."""
    
    await get_organization_with_permission(
        org_id, current_developer, db
    )
    
    team = await TeamService.get_team(db, team_id, include_members=True)
    
    if not team or team.organization_id != org_id:
        raise HTTPException(status_code=404, detail="Team not found")
    
    return TeamResponse(
        id=team.id,
        organization_id=team.organization_id,
        name=team.name,
        description=team.description,
        created_at=team.created_at.isoformat(),
        updated_at=team.updated_at.isoformat(),
        is_active=team.is_active,
        permissions=team.permissions or [],
        member_count=sum(1 for m in team.members if m.is_active) if team.members else 0  # §DOCSFIX D6-502
    )


@router.put("/{org_id}/teams/{team_id}", response_model=TeamResponse)
async def update_team(
    org_id: str = Path(..., description="Organization ID"),
    team_id: str = Path(..., description="Team ID"),
    team_update: TeamUpdate = Body(...),
    current_developer: Annotated[Developer, Security(get_current_developer)] = None,
    db: AsyncSession = Depends(get_db)
):
    """Update team details (requires admin or owner role)."""
    
    await get_organization_with_permission(
        org_id, current_developer, db, required_role="admin"
    )
    # §MCPTEST30 (2026-10-01): the team must belong to the org whose authority was just checked, BEFORE the write.
    # The check used to follow update_team, which commits: an admin of ANY org (anyone can found one) rewrote another
    # org's team (name, description, permissions) and was answered 404, as if refused.
    await _team_of_org(db, org_id, team_id)
    
    try:
        team = await TeamService.update_team(
            db, team_id, **team_update.model_dump(exclude_unset=True)
        )
    except TeamNameTaken as e:   # §MCPTEST30 (V0524)
        raise HTTPException(status_code=409, detail=str(e))
    
    if not team or team.organization_id != org_id:
        raise HTTPException(status_code=404, detail="Team not found")
    
    return TeamResponse(
        id=team.id,
        organization_id=team.organization_id,
        name=team.name,
        description=team.description,
        created_at=team.created_at.isoformat(),
        updated_at=team.updated_at.isoformat(),
        is_active=team.is_active,
        permissions=team.permissions or []
    )


@router.delete("/{org_id}/teams/{team_id}")
async def delete_team(
    org_id: str = Path(..., description="Organization ID"),
    team_id: str = Path(..., description="Team ID"),
    current_developer: Annotated[Developer, Security(get_current_developer)] = None,
    db: AsyncSession = Depends(get_db)
):
    """Delete a team (requires admin or owner role)."""
    
    await get_organization_with_permission(
        org_id, current_developer, db, required_role="admin"
    )
    
    # Get the team first to verify it belongs to this organization
    team = await TeamService.get_team(db, team_id)
    
    if not team or team.organization_id != org_id:
        raise HTTPException(status_code=404, detail="Team not found")
    
    # Check if it's the default team - don't allow deletion
    if team.name.lower() == "default team":
        raise HTTPException(status_code=400, detail="Cannot delete the default team")
    
    success = await TeamService.delete_team(db, team_id)
    
    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete team")
    
    return {"message": "Team deleted successfully"}


# --- Member Management Endpoints ---

@router.get("/{org_id}/members", response_model=List[MemberResponse])
async def list_organization_members(
    org_id: str = Path(..., description="Organization ID"),
    current_developer: Annotated[Developer, Security(get_current_developer)] = None,
    db: AsyncSession = Depends(get_db)
):
    """List all members of an organization."""
    
    await get_organization_with_permission(
        org_id, current_developer, db
    )
    
    # Need to eagerly load developer relationship for members
    from sqlalchemy.orm import selectinload
    from sqlalchemy import select
    
    stmt = select(Organization).where(
        Organization.id == org_id
    ).options(
        selectinload(Organization.members).selectinload(OrganizationMember.developer)
    )
    
    result = await db.execute(stmt)
    org = result.scalar_one_or_none()
    
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    
    members = []
    for member in org.members:
        if member.is_active:
            members.append(
                MemberResponse(
                    id=member.id,
                    developer_id=member.developer_id,
                    developer_name=member.developer.name,
                    developer_email=member.developer.email,
                    role=member.role,
                    joined_at=member.joined_at.isoformat(),
                    is_active=member.is_active,
                    can_approve=bool(getattr(member, "can_approve", False)),
                )
            )
    
    return members


@router.post("/{org_id}/invite")
async def invite_member(
    org_id: str = Path(..., description="Organization ID"),
    invite: MemberInvite = Body(...),
    current_developer: Annotated[Developer, Security(get_current_developer)] = None,
    db: AsyncSession = Depends(get_db)
):
    """Invite a new member to the organization (requires admin or owner role)."""
    
    await get_organization_with_permission(
        org_id, current_developer, db, required_role="admin"
    )
    
    try:
        invitation, mail_sent = await InvitationService.create_invitation(
            db=db,
            organization_id=org_id,
            email=invite.email,
            role=invite.role,
            invited_by_id=current_developer.id
        )
        
        return {
            # §FESUITE (V0594): what happened to the mail, said (it said "sent" whatever the send did); the invitation
            # stands either way, and without its mail the invited person has no link to accept it with
            "message": (f"Invitation sent to {invite.email}" if mail_sent
                        else f"Invitation created for {invite.email}, but its mail could not be sent"),
            "mail_sent": mail_sent,
            "invitation_id": invitation.id,
            # §ORGINVITE (2026-08-28) — `id` under its plain name too, so a caller
            # that has just invited someone can withdraw it without going back to
            # the list route. Additive; `invitation_id` stays for every existing
            # caller.
            "id": invitation.id,
            # ⚠ The token stays, DELIBERATELY and narrowly. It was added to make a
            # flow test pass ("ADD THIS LINE" is what the comment said) and the
            # API tester still reads it, so removing it here would break a suite
            # rather than close a hole: the caller is the org admin who created
            # this invitation seconds ago. It is recorded as a decision rather
            # than left as an artefact — and note that the LIST route added by
            # this batch deliberately does NOT carry it, because a list is what
            # ends up in a log, a screenshot or a support ticket.
            "token": invitation.token,
            "expires_at": invitation.expires_at.isoformat()
        }
    except ValueError as e:
        # 2026-07-16: a ValueError here is a USER-facing validation rejection
        # (e.g. "Developer is already a team member", invalid/expired invitation
        # token) — surfacing str(e) instead of the generic "An internal error
        # occurred" tells the caller WHY the 400 happened. The tester was
        # (correctly) counting the masked message as a red because it looked
        # like a 500. Only ValueError is surfaced; bare Exception handlers stay
        # generic so genuine internals aren't leaked.
        logger.warning(f"Organization validation rejected: {e}")
        raise HTTPException(status_code=400, detail=str(e))


def _invitation_status(row) -> str:
    """The status an invitation ACTUALLY has, which is not always the one stored.

    §ORGJOIN put this rule in the preview endpoint; §ORGINVITE needed the same
    answer in the list, so it lives in one place. A row past `expires_at` still
    says `pending` until somebody tries to accept it — the sweep that rewrites
    the column runs there and nowhere else. Two surfaces computing this
    separately is how a list ends up offering "withdraw" on an invitation the
    accept rail has already given up on.
    """
    from datetime import datetime, timezone
    status = str(getattr(row, "status", None) or "pending")
    exp = getattr(row, "expires_at", None)
    if status == "pending" and exp is not None and exp < datetime.now(timezone.utc):
        return "expired"
    return status


@router.get("/{org_id}/invitations", summary="Invitations this organization has sent")
async def list_organization_invitations(
    org_id: str = Path(..., description="Organization ID"),
    current_developer: Annotated[Developer, Security(get_current_developer)] = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Who has been invited, and who has not answered: every invitation this organization has sent, with its status
    (owner or admin). The invitation token is never in this answer, since it is a bearer secret; a row is addressed
    by its `id`, which the withdraw route takes. The invitee's address is shown in full, so a typo can be spotted.

    \f
    Who has been invited, and who has not answered.

    §ORGINVITE (2026-08-28). There was no way to ask this. Measured: an owner who
    mistyped an address had no route and no screen that would show it, no way to
    withdraw it, and — because `create_invitation` refuses a second pending
    invitation for the same address — no way to send a correct one either. The
    address was simply held for seven days by an invitation nobody would receive.
    The members list cannot answer it: an invitation is not a membership until it
    is accepted, so `list_members` is reading a different table.

    🔴 THE TOKEN IS NEVER IN THIS PAYLOAD. It is a bearer secret — whoever holds
    it can accept the invitation from any account whose address matches — and a
    list is exactly the sort of thing that ends up in a log, a screenshot or a
    support ticket. The row is addressed by its `id`, and the withdraw route
    below takes that id. (`POST /{org_id}/invite` does return the token today,
    with a comment saying it was added to fix a flow test; that is the caller who
    just created it, and it is flagged in this batch's findings rather than
    changed underneath the tests that rely on it.)

    The invitee's ADDRESS is here in full, unlike the public preview, and that is
    deliberate: an org admin typed it. Masking it here would defeat the one thing
    the screen exists for — spotting the typo.
    """
    from sqlalchemy import select
    from agentvault_registry.models import OrganizationInvitation

    await get_organization_with_permission(org_id, current_developer, db, required_role="admin")
    rows = (await db.execute(
        select(OrganizationInvitation)
        .where(OrganizationInvitation.organization_id == org_id)
        .order_by(OrganizationInvitation.created_at.desc())
        .limit(200)
    )).scalars().all()

    # invited-by as a NAME, resolved in one query rather than one per row
    inviter_ids = {r.invited_by for r in rows if r.invited_by is not None}
    names: Dict[int, str] = {}
    if inviter_ids:
        for d in (await db.execute(select(Developer).where(Developer.id.in_(inviter_ids)))).scalars().all():
            names[d.id] = getattr(d, "name", None) or getattr(d, "email", "") or ""

    return {
        "org_id": org_id,
        "invitations": [
            {
                "id": r.id,
                "email": r.email,
                "role": r.role,
                "status": _invitation_status(r),
                "invited_by": r.invited_by,
                "invited_by_name": names.get(r.invited_by),
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "expires_at": r.expires_at.isoformat() if r.expires_at else None,
                "accepted_at": r.accepted_at.isoformat() if getattr(r, "accepted_at", None) else None,
            }
            for r in rows
        ],
    }


@router.delete("/{org_id}/invitations/{invitation_id}", summary="Withdraw a pending invitation")
async def revoke_organization_invitation(
    org_id: str = Path(..., description="Organization ID"),
    invitation_id: str = Path(..., description="Invitation id from the list route"),
    current_developer: Annotated[Developer, Security(get_current_developer)] = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Withdraw an invitation that has not been answered yet. This also frees the address for a new invitation (a
    second pending invitation to the same address is refused). An invitee who follows a withdrawn link is told it
    was withdrawn. An accepted invitation answers 409: remove the membership with DELETE
    /api/v1/organizations/{org_id}/members/{developer_id} instead.

    \f
    Withdraw an invitation that has not been answered yet.

    `OrganizationInvitation.status` has listed `cancelled` in the model and its
    docstring since the table existed, and NOTHING in the codebase could set it —
    building a fixture for one required hand-written SQL. This makes the state
    reachable, and §ORGJOIN's page already renders it: an invitee who follows a
    withdrawn link is told *"This invitation was withdrawn."*

    Withdrawing also FREES THE ADDRESS. `create_invitation` refuses a second
    pending invitation for the same email, so until now a mistyped or lost
    invitation blocked that address for its full seven days. Cancel, then invite
    again — that is the repair path this route exists for.

    Only a live invitation can be withdrawn. An ACCEPTED one is a record of
    something that happened, not a pending act, and taking it back here would say
    nothing about the membership it produced — which is removed with
    `DELETE /{org_id}/members/{developer_id}`, a different decision with different
    consequences. Refused as a 409 that says which.
    """
    from sqlalchemy import select, and_
    from agentvault_registry.models import OrganizationInvitation

    await get_organization_with_permission(org_id, current_developer, db, required_role="admin")
    row = (await db.execute(
        select(OrganizationInvitation).where(and_(
            OrganizationInvitation.id == invitation_id,
            OrganizationInvitation.organization_id == org_id,   # scope: never another org's row
        ))
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Invitation not found in this organization")

    effective = _invitation_status(row)
    if effective == "accepted":
        raise HTTPException(status_code=409, detail=(
            "That invitation was already accepted. Remove the member instead: "
            "DELETE /organizations/{org_id}/members/{developer_id}"))
    if effective == "cancelled":
        return {"id": row.id, "status": "cancelled", "already": True}

    row.status = "cancelled"
    await db.commit()
    logger.info("org %s: invitation %s withdrawn by developer %s", org_id, invitation_id, current_developer.id)
    return {"id": row.id, "email": row.email, "status": "cancelled", "already": False}


@router.get("/invitations/{token}", summary="Look at an invitation without accepting it")
async def preview_invitation(
    token: str = Path(..., description="Invitation token from the invitation email"),
    db: AsyncSession = Depends(get_db),
    viewer: Optional[Developer] = Depends(get_current_developer_optional),
):
    """
    What is behind an invitation link, without accepting it: its status, the organization and the role offered, and
    when it expires. Public: the caller holds the single-purpose token that was mailed to the invitee. The invitee's
    address is masked; a signed-in caller is told whether the invitation is addressed to them. An unknown or spent
    invitation is an answer, not an error.

    \f
    What is behind an invitation link, WITHOUT taking the decision for the person.

    §ORGJOIN (2026-08-28). Until now the only endpoint was POST .../accept, so any
    surface built on this API had to either accept blind on arrival or show the
    invitee nothing to decide about. Neither is acceptable for a link a stranger
    clicks out of an email: you are asked to join an organization, so you get to
    see WHICH one and as WHAT first.

    PUBLIC BY NECESSITY, and safe by the same reasoning invitation links have
    always used: the caller is holding a 43-character single-purpose token that
    was mailed to the invitee. Without a public read there is nothing to render
    before login, which is the state most invitees arrive in.

    ⚠ The invitee's address is MASKED. The holder of the token almost certainly
    knows it — it is their own mailbox — but "almost certainly" is not a reason
    to publish an address to whoever has the link. The hint is enough to answer
    the one question it exists for: *am I signed in as the wrong person?*

    Never raises for a bad token. An unknown or spent invitation is an ANSWER, not
    an error, and it has to arrive as a sentence the page can show.
    """
    # Local imports, matching this router's idiom (list_members does the same):
    # `select`, the datetime pair and the invitation model are not module-level here.
    # pyflakes named all four the moment this handler was written — py_compile
    # would have passed every one of them.
    from sqlalchemy import select, func, and_
    from agentvault_registry.models import OrganizationInvitation, OrganizationMember

    row = (await db.execute(
        select(OrganizationInvitation).where(OrganizationInvitation.token == token)
    )).scalar_one_or_none()
    if row is None:
        return {"valid": False, "status": "unknown"}

    status = _invitation_status(row)
    expires_at = row.expires_at

    org = (await db.execute(
        select(Organization).where(Organization.id == row.organization_id)
    )).scalar_one_or_none()

    email = str(row.email or "")
    local, _, domain = email.partition("@")
    hint = f"{local[:1]}{'•' * max(len(local) - 1, 1)}@{domain}" if local and domain else ""

    # "Is this invitation for ME?" is answered by the SERVER, which holds both
    # addresses, and never by comparing a masked hint to a local string — a page
    # that guesses at identity from an elided address will eventually guess wrong,
    # and this is the branch that decides whether someone is told to switch
    # accounts. `viewer` is optional precisely so the logged-out arrival, which is
    # the common one, still gets an answer.
    you_match = None
    already_member = None
    if viewer is not None:
        you_match = (str(getattr(viewer, "email", "") or "").lower() == email.lower())
        already_member = (await db.execute(
            select(func.count()).select_from(OrganizationMember).where(
                and_(OrganizationMember.organization_id == row.organization_id,
                     OrganizationMember.developer_id == viewer.id,
                     OrganizationMember.is_active == True)  # noqa: E712
            )
        )).scalar() > 0

    return {
        "valid": status == "pending",
        "status": status,                       # pending | accepted | expired | cancelled | unknown
        "organization_id": row.organization_id,
        "organization_name": (org.name if org else None),
        "role": row.role,
        "invited_email_hint": hint,
        "expires_at": expires_at.isoformat() if expires_at else None,
        "you_match": you_match,                 # null when nobody is signed in
        "already_member": already_member,       # null when nobody is signed in
    }


@router.post("/invitations/{token}/accept")
async def accept_invitation(
    token: str = Path(..., description="Invitation token"),
    current_developer: Annotated[Developer, Security(get_current_developer)] = None,
    db: AsyncSession = Depends(get_db)
):
    """Accept an invitation to join an organization."""
    
    try:
        member = await InvitationService.accept_invitation(
            db=db,
            token=token,
            developer=current_developer
        )
        
        return {
            "message": "Invitation accepted successfully",
            "organization_id": member.organization_id,
            "role": member.role
        }
    except ValueError as e:
        # 2026-07-16: a ValueError here is a USER-facing validation rejection
        # (e.g. "Developer is already a team member", invalid/expired invitation
        # token) — surfacing str(e) instead of the generic "An internal error
        # occurred" tells the caller WHY the 400 happened. The tester was
        # (correctly) counting the masked message as a red because it looked
        # like a 500. Only ValueError is surfaced; bare Exception handlers stay
        # generic so genuine internals aren't leaked.
        logger.warning(f"Organization validation rejected: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{org_id}/teams/{team_id}/members")
async def add_team_member(
    org_id: str = Path(..., description="Organization ID"),
    team_id: str = Path(..., description="Team ID"),
    member_data: TeamMemberAdd = Body(...),
    current_developer: Annotated[Developer, Security(get_current_developer)] = None,
    db: AsyncSession = Depends(get_db)
):
    """Add a member to a team (requires admin or team lead role)."""
    
    await get_organization_with_permission(
        org_id, current_developer, db, required_role="admin"
    )
    await _team_of_org(db, org_id, team_id)   # §MCPTEST30: an admin of one org added members to any org's team
    # §MCPTEST30 (2026-10-01): the developer added must belong to THIS organization. Any id was accepted, and the team
    # roster (GET /{org}/teams) then printed that developer's name, or the local part of their e-mail: anybody who
    # founded an organization could read the name behind every developer id. One answer for an unknown id and a
    # non-member, so the refusal is no oracle either.
    in_org = (await db.execute(select(OrganizationMember.id).where(
        OrganizationMember.organization_id == org_id,
        OrganizationMember.developer_id == member_data.developer_id,
        OrganizationMember.is_active.is_(True)).limit(1))).first()
    if in_org is None:
        raise HTTPException(status_code=400, detail="That developer is not a member of this organization")
    
    try:
        member = await TeamService.add_team_member(
            db=db,
            team_id=team_id,
            developer_id=member_data.developer_id,
            role=member_data.role
        )
        
        return {
            "message": "Member added to team successfully",
            "member_id": member.id,
            "role": member.role
        }
    except ValueError as e:
        # 2026-07-16: a ValueError here is a USER-facing validation rejection
        # (e.g. "Developer is already a team member", invalid/expired invitation
        # token) — surfacing str(e) instead of the generic "An internal error
        # occurred" tells the caller WHY the 400 happened. The tester was
        # (correctly) counting the masked message as a red because it looked
        # like a 500. Only ValueError is surfaced; bare Exception handlers stay
        # generic so genuine internals aren't leaked.
        logger.warning(f"Organization validation rejected: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{org_id}/teams/{team_id}/members/{developer_id}")
async def remove_team_member(
    org_id: str = Path(..., description="Organization ID"),
    team_id: str = Path(..., description="Team ID"),
    developer_id: int = Path(..., description="Developer ID to remove"),
    current_developer: Annotated[Developer, Security(get_current_developer)] = None,
    db: AsyncSession = Depends(get_db)
):
    """Remove a member from a team (requires admin or team lead role)."""
    
    await get_organization_with_permission(
        org_id, current_developer, db, required_role="admin"
    )
    await _team_of_org(db, org_id, team_id)   # §MCPTEST30: and removed them from any org's team
    
    success = await TeamService.remove_team_member(
        db=db,
        team_id=team_id,
        developer_id=developer_id
    )
    
    if not success:
        raise HTTPException(status_code=404, detail="Team member not found")
    
    return {"message": "Member removed from team successfully"}


@router.delete("/{org_id}/members/{developer_id}")
async def remove_org_member(
    org_id: str = Path(..., description="Organization ID"),
    developer_id: int = Path(..., description="Developer ID to remove"),
    current_developer: Annotated[Developer, Security(get_current_developer)] = None,
    db: AsyncSession = Depends(get_db)
):
    """Remove a member from an organization (requires admin role). Hard deletes for UniqueConstraint compatibility."""
    
    org_row = await get_organization_with_permission(
        org_id, current_developer, db, required_role="admin"
    )
    
    try:
        success = await OrganizationService.remove_member(
            db=db,
            org_id=org_id,
            developer_id=developer_id
        )
    except ValueError as e:
        # 2026-07-16: a ValueError here is a USER-facing validation rejection
        # (e.g. "Developer is already a team member", invalid/expired invitation
        # token) — surfacing str(e) instead of the generic "An internal error
        # occurred" tells the caller WHY the 400 happened. The tester was
        # (correctly) counting the masked message as a red because it looked
        # like a 500. Only ValueError is surfaced; bare Exception handlers stay
        # generic so genuine internals aren't leaked.
        logger.warning(f"Organization validation rejected: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    
    if not success:
        raise HTTPException(status_code=404, detail="Organization member not found")

    # §ORGLIFE L2 — leaving the org gives up the org's AUTHORITY, at the moment of
    # removal. An org: grant is a standing permission the organization extended to this
    # person's agents BECAUSE this person was in the org; when the membership row goes,
    # the basis for the grant goes with it. Measured before writing this: without it a
    # removed member's agent still resolved all ten org-only permissions — including
    # guild.bid_for_org, i.e. bidding for work in the organization's name (L1_FINDINGS.md).
    #
    # The ASSIGNMENT is deliberately left alone. It is a record — this agent did work for
    # this org — and destroying someone else's record on their way out is the silent sweep
    # §ORGJOIN refused. list_organization_agents() now reports the resulting state
    # (creator_is_member / org_authority) so the org can unassign deliberately.
    #
    # Scoped by creator AND this org, so it can never reach another org's grants or
    # another person's agents. begin_nested() because a bare except around failing SQL
    # leaves the transaction ABORTED and poisons everything after it (§ORGLEAK).
    try:
        async with db.begin_nested():
            revoked = (await db.execute(sa_text("""
                UPDATE agent_delegation_grants SET revoked_at = now(),
                       revoke_reason = 'member removed from organization'
                 WHERE principal_type = 'org'
                   AND principal_ref IN (:ref_slug, :ref_id)
                   AND revoked_at IS NULL
                   AND delegate_agent_did IN (
                        SELECT did FROM agents
                         WHERE creator_developer_id = :d AND organization_id = :o)
            """), {"ref_slug": f"org:{org_row.slug}", "ref_id": f"org:{org_row.id}",
                   "d": int(developer_id), "o": str(org_id)})).rowcount or 0
        await db.commit()
        if revoked:
            logger.info("[ORGLIFE] org=%s dev=%s org-grants revoked on removal: %d",
                        org_id, developer_id, revoked)
    except Exception as e:  # noqa: BLE001 — the member IS out; never fail removal over this
        logger.warning("[ORGLIFE] org-grant revoke failed for dev %s / org %s: %s",
                       developer_id, org_id, e)

    # §ORGLEAK — leaving the org leaves the org's ROOM, at the moment of removal.
    # resolve_membership() refuses an ex-member on the next touch regardless, so
    # this is not the security boundary; it is what makes the room disappear from
    # their list immediately instead of lingering until they tap it.
    try:
        await db.execute(sa_text("""
            UPDATE conversation_participants SET state = 'left'
            WHERE ptype = 'developer' AND developer_id = :d
              AND conversation_id IN (
                SELECT id FROM conversations WHERE kind = 'org' AND org_id = :o)
        """), {"d": int(developer_id), "o": str(org_id)})
        await db.commit()
    except Exception as e:  # noqa: BLE001 — never fail the removal over the room
        logger.warning("org room detach failed for dev %s / org %s: %s",
                       developer_id, org_id, e)

    return {"message": "Member removed from organization successfully"}


@router.put("/{org_id}/members/{developer_id}/role", response_model=MemberResponse)
async def update_org_member_role(
    org_id: str = Path(..., description="Organization ID"),
    developer_id: int = Path(..., description="Developer ID whose role to change"),
    role_data: MemberRoleUpdate = Body(...),
    current_developer: Annotated[Developer, Security(get_current_developer)] = None,
    db: AsyncSession = Depends(get_db)
):
    """Change a member's organization role (requires admin role).

    The owner row is refused (400), since ownership is not a role edit, and an
    admin can grant at most 'admin', mirroring the invite clamp.
    """

    await get_organization_with_permission(
        org_id, current_developer, db, required_role="admin"
    )

    try:
        member = await OrganizationService.update_member_role(
            db=db,
            org_id=org_id,
            developer_id=developer_id,
            new_role=role_data.role,
            changed_by=current_developer.id,
        )
    except ValueError as e:
        # USER-facing validation rejection (owner immutability, bad role) —
        # surface str(e), same convention as remove_org_member above.
        logger.warning(f"Organization validation rejected: {e}")
        raise HTTPException(status_code=400, detail=str(e))

    if not member:
        raise HTTPException(status_code=404, detail="Organization member not found")

    # The update path doesn't eager-load the developer relationship the
    # response needs — re-select with it (async lazy-load would raise).
    from sqlalchemy.orm import selectinload
    from sqlalchemy import select

    stmt = select(OrganizationMember).where(
        OrganizationMember.id == member.id
    ).options(selectinload(OrganizationMember.developer))
    member = (await db.execute(stmt)).scalar_one()

    return MemberResponse(
        id=member.id,
        developer_id=member.developer_id,
        developer_name=member.developer.name,
        developer_email=member.developer.email,
        role=member.role,
        joined_at=member.joined_at.isoformat(),
        is_active=member.is_active,
        can_approve=bool(getattr(member, "can_approve", False)),
    )


@router.put("/{org_id}/members/{developer_id}/approver", response_model=MemberResponse,
            summary="Name or un-name an approver of the room's approval requests (owner only)")
async def update_org_member_approver(
    org_id: str = Path(..., description="Organization ID"),
    developer_id: int = Path(..., description="The member to name or un-name"),
    payload: MemberApproverUpdate = Body(...),
    current_developer: Annotated[Developer, Security(get_current_developer)] = None,
    db: AsyncSession = Depends(get_db)
):
    """V0650 (l). Beside the owner, a named approver may decide the approval requests agents post in the org's room
    (POST /api/v1/chat/conversations/{id}/approvals/decide). Only the owner names one, and only an active member can
    be named; the flag is part of the membership row, so it ends when the membership does. Audited as
    `chat.approval.approver_set`."""
    from sqlalchemy.orm import selectinload
    from agentvault_registry.services.admin_audit import log_chat_action

    org = await get_organization_with_permission(org_id, current_developer, db)
    if org.owner_id != current_developer.id:
        raise HTTPException(status_code=403, detail="Only the organization's owner names approvers")
    stmt = select(OrganizationMember).where(
        OrganizationMember.organization_id == org_id,
        OrganizationMember.developer_id == developer_id,
        OrganizationMember.is_active == True,  # noqa: E712 — SQL comparison
    ).options(selectinload(OrganizationMember.developer))
    member = (await db.execute(stmt)).scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=404, detail="That developer is not an active member of this organization")
    before = bool(member.can_approve)
    member.can_approve = bool(payload.can_approve)
    await log_chat_action(db, action="approval.approver_set", actor_type="developer",
                          actor_id=str(current_developer.id), target_type="organization_member",
                          target_id=member.id,
                          details={"org_id": org_id, "developer_id": developer_id, "can_approve": member.can_approve,
                                   "was": before})
    await db.commit()
    return MemberResponse(
        id=member.id,
        developer_id=member.developer_id,
        developer_name=member.developer.name,
        developer_email=member.developer.email,
        role=member.role,
        joined_at=member.joined_at.isoformat(),
        is_active=member.is_active,
        can_approve=member.can_approve,
    )


# ── E1a — Ownership transfer (the handshake update_org_member_role points at) ──

@router.post("/{org_id}/ownership/transfer", status_code=201,
             summary="Offer this organization to an active admin member (owner only)")
async def initiate_ownership_transfer(
    payload: OwnershipTransferCreate,
    org_id: str = Path(..., description="Organization ID"),
    current_developer: Annotated[Developer, Security(get_current_developer)] = None,
    db: AsyncSession = Depends(get_db)
):
    """Ownership is liability, so it moves by explicit two-party handshake: the owner
    offers, the target (who must already hold 'admin') accepts. One pending offer per
    org, 7-day TTL, self-retiring. Mandates do NOT transfer: they are developer∘agent
    instruments, and the new owner underwrites with their own."""
    org = await get_organization_with_permission(org_id, current_developer, db)
    if org.owner_id != current_developer.id:
        raise HTTPException(status_code=403, detail="Only the owner can transfer ownership")
    try:
        res = await OrganizationService.initiate_ownership_transfer(
            db, org_id, payload.to_developer_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"org_id": org_id, "pending_ownership_transfer": res,
            "note": "Mandates do not transfer; the new owner underwrites with their own."}


@router.post("/{org_id}/ownership/respond",
             summary="Accept or decline a pending ownership offer (the offered developer, E1a)")
async def respond_ownership_transfer(
    payload: OwnershipTransferRespond,
    org_id: str = Path(..., description="Organization ID"),
    current_developer: Annotated[Developer, Security(get_current_developer)] = None,
    db: AsyncSession = Depends(get_db)
):
    """Accept flips ownership in one transaction: org.owner_id moves, the acceptor's
    member row becomes 'owner', the previous owner's becomes 'admin' (never dropped).
    An expired or absent offer answers 410 so the FE can distinguish 'gone' from a
    validation mistake."""
    from agentvault_registry.services.organization_service import TransferExpiredError
    await get_organization_with_permission(org_id, current_developer, db)
    try:
        res = await OrganizationService.respond_ownership_transfer(
            db, org_id, current_developer.id, payload.accept)
    except TransferExpiredError as e:
        raise HTTPException(status_code=410, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    return {"org_id": org_id, **res}


@router.delete("/{org_id}/ownership/transfer",
               summary="Withdraw the pending ownership offer (OWNER only, E1a)")
async def cancel_ownership_transfer(
    org_id: str = Path(..., description="Organization ID"),
    current_developer: Annotated[Developer, Security(get_current_developer)] = None,
    db: AsyncSession = Depends(get_db)
):
    org = await get_organization_with_permission(org_id, current_developer, db)
    if org.owner_id != current_developer.id:
        raise HTTPException(status_code=403, detail="Only the owner can cancel the transfer")
    cleared = await OrganizationService.cancel_ownership_transfer(db, org_id)
    if not cleared:
        raise HTTPException(status_code=410, detail="No live transfer offer to cancel")
    return {"org_id": org_id, "cancelled": True}


@router.get("/{org_id}/agents/authority", summary="Live organization-to-agent authority grants of this organization")
async def list_org_agent_authority(
    org_id: str = Path(..., description="Organization ID"),
    current_developer: Annotated[Developer, Security(get_current_developer)] = None,
    db: AsyncSession = Depends(get_db)
):
    """Every LIVE delegation grant this org has issued to an agent (owner/admin).
    Grants are the IRONKEY primitive (`agent_delegation_grants`,
    `principal_type='org'`); they bite only when the agent presents an org-acting
    token (POST /api/v1/agents/act-token with act_as=org:<slug>)."""

    org = await get_organization_with_permission(
        org_id, current_developer, db, required_role="admin"
    )

    from sqlalchemy import text
    # principal_ref may canonically carry the slug or the org id (resolver accepts both).
    # agents has NO name column — display names live on agent_cards (fallback = DID).
    rows = (await db.execute(text(
        "SELECT g.id, g.delegate_agent_did, "
        "       (SELECT c.name FROM agent_cards c WHERE c.agent_did = g.delegate_agent_did LIMIT 1) AS agent_name, "
        "       g.permissions, g.expires_at, "
        "       g.granted_by_dev_id, (a.organization_id = :oid) AS linked "
        "FROM agent_delegation_grants g "
        "LEFT JOIN agents a ON a.did = g.delegate_agent_did "
        "WHERE g.principal_type = 'org' "
        "AND (g.principal_ref = :ref_slug OR g.principal_ref = :ref_id) "
        "AND g.revoked_at IS NULL AND (g.expires_at IS NULL OR g.expires_at > now()) "
        "ORDER BY g.delegate_agent_did"
    ), {"oid": org_id, "ref_slug": f"org:{org.slug}", "ref_id": f"org:{org.id}"})).fetchall()

    return {
        "org_id": org_id,
        "org_slug": org.slug,
        "grants": [
            {
                "grant_id": r[0],
                "agent_did": r[1],
                "agent_name": r[2],
                "permissions": sorted(r[3] or []),
                "expires_at": r[4].isoformat() if r[4] else None,
                "granted_by_dev_id": r[5],
                # an UNLINKED agent's grant resolves to nothing (the linkage tenet) —
                # surfaced so the panel can flag a grant that cannot bite
                "org_linked": bool(r[6]),
            }
            for r in rows
        ],
    }


@router.get("/{org_id}/audit", summary="Organization lifecycle audit trail")
async def get_org_audit(
    org_id: str = Path(..., description="Organization ID"),
    event_types: Optional[str] = Query(None, description="Comma-separated event-type filter"),
    limit: int = Query(100, ge=1, le=500),
    current_developer: Annotated[Developer, Security(get_current_developer)] = None,
    db: AsyncSession = Depends(get_db)
):
    """The org's own EventStore trail (owner/admin): invites, joins, removals,
    role changes and authority grants: everything `_emit_org_event` writes under
    this org's aggregate_id. Cross-org isolation is by construction: the gate
    admits only this org's admins, and the ES query is keyed by this org_id.
    ES unreachable → honest 503, never an empty list masquerading as history."""

    await get_organization_with_permission(
        org_id, current_developer, db, required_role="admin"
    )

    import os as _os
    import httpx as _httpx
    from urllib.parse import quote as _q
    from agentvault_registry.es_ssl_helper import get_httpx_verify

    es_url = _os.environ.get("EVENT_STORE_URL", "http://event-store:8200")
    internal_key = (
        _os.environ.get("EVENT_STORE_INTERNAL_KEY")
        or _os.environ.get("EVENT_STORE_API_KEY")
        or ""
    )
    headers = {"X-Internal-Key": internal_key} if internal_key else {}
    params = {}
    if event_types:
        params["event_types"] = event_types
    try:
        async with _httpx.AsyncClient(timeout=8.0, verify=get_httpx_verify()) as client:
            r = await client.get(
                f"{es_url}/api/v1/events/aggregate/{_q(org_id, safe=':')}",
                params=params, headers=headers,
            )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[ORG-AUDIT] EventStore unreachable for org {org_id}: {e}")
        raise HTTPException(status_code=503, detail="Audit backend unreachable")
    if r.status_code != 200:
        raise HTTPException(status_code=503, detail=f"Audit backend error ({r.status_code})")

    evs = r.json() or []
    # ES returns ASC — serve newest-first, capped
    evs = list(reversed(evs))[:limit]
    return {
        "org_id": org_id,
        "count": len(evs),
        "events": [
            {
                "event_type": e.get("event_type"),
                "timestamp": e.get("timestamp") or e.get("event_timestamp"),
                "data": e.get("data") or {},
            }
            for e in evs
        ],
    }


@router.get("/{org_id}/mcp-audit", summary="The MCP tool calls of this organization's agents (owner or admin)")
async def get_org_mcp_audit(
    org_id: str = Path(..., description="Organization ID"),
    limit: int = Query(50, ge=1, le=200, description="Rows per page"),
    cursor: Optional[str] = Query(None, description="The next_cursor of the previous page"),
    current_developer: Annotated[Developer, Security(get_current_developer)] = None,
    db: AsyncSession = Depends(get_db)
):
    """V0650 (d). The MCP calls the organization's agents made on this registry with their own credentials, newest
    first: the tool, which agent, when, its tier, outcome and latency, and whether the tool answered an error. Never
    the call's arguments, its error text, the caller's address or user agent. Owner or admin only. `recording` says
    whether this registry records MCP calls at all, so a quiet log is never read as an idle organization."""
    from agentvault_registry.mcp import audit as _mcp_audit
    from agentvault_registry.models import Agent
    from agentvault_registry.routers import mcp_audit_log as mal

    await get_organization_with_permission(org_id, current_developer, db, required_role="admin")
    dids = [d for d in (await db.execute(select(Agent.did).where(Agent.organization_id == org_id))).scalars().all()
            if d]
    after = None
    if cursor:
        try:
            after = mal.parse_org_cursor(cursor)
        except ValueError:
            raise HTTPException(status_code=400, detail="cursor is not one this route issued")
    rows = []
    if dids:
        rows = list((await db.execute(mal.org_mcp_audit_stmt(dids, limit + 1, after))).scalars().all())
    page, more = rows[:limit], len(rows) > limit
    return {
        "org_id": org_id,
        "recording": bool(getattr(_mcp_audit, "MCP_AUDIT_LOGGING_ENABLED", False)),
        "agent_count": len(dids),
        "rows": [mal.serialize_org_call_row(r) for r in page],
        "next_cursor": mal.org_cursor(page[-1]) if more and page else None,
        "limit": limit,
    }


class BulkAuthorityApply(BaseModel):
    """Track A4 — apply one A1 role-slice to EVERY agent in the org."""
    role: str = Field(..., pattern="^(guest|member|admin|owner)$", description="Org authority level (A1 slice)")


@router.post("/{org_id}/agents/grant-bulk", summary="Apply a role slice to ALL org agents")
async def bulk_apply_org_authority(
    org_id: str = Path(..., description="Organization ID"),
    body: BulkAuthorityApply = Body(...),
    current_developer: Annotated[Developer, Security(get_current_developer)] = None,
    db: AsyncSession = Depends(get_db)
):
    """UPSERT the org→agent delegation grant for every agent with this
    organization_id, using the A1 slice for `role`. Idempotent (same
    ON CONFLICT as the per-agent grant). Owner/admin only. One org event."""

    org = await get_organization_with_permission(
        org_id, current_developer, db, required_role="admin"
    )

    from sqlalchemy import text
    from agentvault_registry.services.org_authz import org_role_slice, grant_org_slice
    perms = sorted(org_role_slice(body.role))
    if not perms:
        raise HTTPException(status_code=422, detail=f"Unknown org role slice: {body.role}")

    # active only — soft-deleted/suspended agents keep their organization_id row,
    # and granting authority to a revoked agent is never right (battery-caught)
    dids = [r[0] for r in (await db.execute(text(
        "SELECT did FROM agents WHERE organization_id = :oid AND status = 'active'"),
        {"oid": org_id})).fetchall()]

    await grant_org_slice(db, org_slug=org.slug, agent_dids=dids,
                          role=body.role, granted_by=current_developer.id)
    await db.commit()

    from agentvault_registry.services.organization_service import _emit_org_event
    await _emit_org_event("OrganizationAgentAuthorityBulkApplied", org_id, {
        "org_id": org_id,
        "role_slice": body.role,
        "permissions": perms,
        "agents": len(dids),
        "applied_by": current_developer.id,
    })
    logger.info("[ORG-AUTHORITY] bulk %s slice -> %d agents of org %s by dev=%s",
                body.role, len(dids), org_id, current_developer.id)
    return {"org_id": org_id, "role_slice": body.role, "permissions": perms, "agents": len(dids)}


@router.delete("/{org_id}/agents/grant-bulk", summary="Revoke org authority from ALL org agents")
async def bulk_revoke_org_authority(
    org_id: str = Path(..., description="Organization ID"),
    current_developer: Annotated[Developer, Security(get_current_developer)] = None,
    db: AsyncSession = Depends(get_db)
):
    """Revoke every LIVE org→agent grant this org has issued (owner/admin).
    Authority collapses on each agent's next request (resolution reads current rows)."""

    org = await get_organization_with_permission(
        org_id, current_developer, db, required_role="admin"
    )

    from sqlalchemy import text
    res = await db.execute(text(
        "UPDATE agent_delegation_grants SET revoked_at = now(), revoke_reason = 'org bulk revoke' "
        "WHERE principal_type = 'org' AND (principal_ref = :ref_slug OR principal_ref = :ref_id) "
        "AND revoked_at IS NULL"
    ), {"ref_slug": f"org:{org.slug}", "ref_id": f"org:{org.id}"})
    await db.commit()
    revoked = res.rowcount or 0

    from agentvault_registry.services.organization_service import _emit_org_event
    await _emit_org_event("OrganizationAgentAuthorityBulkRevoked", org_id, {
        "org_id": org_id, "revoked": revoked, "revoked_by": current_developer.id,
    })
    logger.info("[ORG-AUTHORITY] bulk revoke %d grants of org %s by dev=%s",
                revoked, org_id, current_developer.id)
    return {"org_id": org_id, "revoked": revoked}


@router.get("/{org_id}/authz/catalog", summary="Org-role to default agent-permission slices")
async def get_org_authz_catalog(
    org_id: str = Path(..., description="Organization ID"),
    current_developer: Annotated[Developer, Security(get_current_developer)] = None,
    db: AsyncSession = Depends(get_db)
):
    """The canonical org-role → agent-permission default map (SSOT:
    services/org_authz.py). Any org member may read it; applying a slice to an
    agent is the Agent Authority surface (owner or admin)."""

    await get_organization_with_permission(org_id, current_developer, db)

    from agentvault_registry.services.org_authz import catalog, NEVER_IN_ORG_SLICES
    return {
        "org_id": org_id,
        "roles": catalog(),
        "never_included": sorted(NEVER_IN_ORG_SLICES),
    }


# ── ORG TREASURY (Track C / §ORGTREASURY) ──
# The org's own keyless money account. C1 is the ACCOUNT ONLY: read it and create it.
# No money moves through these routes — the funding/collection rails are C2 and ride the
# escrow mover, never an agent-JWT path (a keyless DID down that path would silently bypass
# spend limits, IRONKEY, the liability gate and fees; see services/org_treasury.py).

@router.get("/{org_id}/treasury", summary="The organization's treasury account: which DID, where it came from, live balance")
async def get_org_treasury_account(
    org_id: str = Path(..., description="Organization ID"),
    current_developer: Annotated[Developer, Security(get_current_developer)] = None,
    db: AsyncSession = Depends(get_db)
):
    """
    Where the organization's units are held and how much is there; any member may read it. `source` says which
    account it is: `org` (the organization's own treasury, created with POST on this path), `agora_listing` (no
    treasury yet, so the organization's first AGORA listing account) or null (no account at all). The balance is
    read from the TEG, not from the registry's cache; when the TEG cannot be reached, `balance` is null rather than
    0.
    """

    await get_organization_with_permission(org_id, current_developer, db)

    from agentvault_registry.services.org_treasury import (
        resolve_org_treasury_did, org_treasury_source,
    )
    did = await resolve_org_treasury_did(db, org_id)
    source = await org_treasury_source(db, org_id)

    balance = None
    if did:
        try:
            from agentvault_registry.services.exchange_service import mover
            balance = str(await mover.agent_balance(did))
        except Exception as exc:  # noqa: BLE001 — a read must not 500 on a TEG hiccup
            logger.warning("[ORGTREASURY] balance read failed org=%s did=%s: %r", org_id, did, exc)

    return {
        "org_id": org_id,
        "treasury_agent_did": did,
        "source": source,
        "balance": balance,
        "exists": did is not None,
    }


@router.post("/{org_id}/treasury", status_code=201,
             summary="Give the organization its own keyless treasury account (owner only)")
async def create_org_treasury_account(
    org_id: str = Path(..., description="Organization ID"),
    current_developer: Annotated[Developer, Security(get_current_developer)] = None,
    db: AsyncSession = Depends(get_db)
):
    """
    Create the organization's own treasury agent (owner only; idempotent). The account is keyless: its client secret
    is generated, hashed and discarded, so no JWT can be issued for it and nobody, the owner included, can spend
    from it outside the organization's rails. Creating it moves no units: the TEG opens the account at zero on first
    use.
    """

    org = await get_organization_with_permission(org_id, current_developer, db)
    if org.owner_id != current_developer.id:
        raise HTTPException(status_code=403, detail="Only the organization owner can create the treasury")

    from agentvault_registry.services.org_treasury import ensure_org_treasury
    did, created = await ensure_org_treasury(
        db, org_id, created_by_developer_id=current_developer.id
    )
    await db.commit()

    # Audit AFTER the commit that created it, so a failed create leaves no claim of one.
    try:
        from agentvault_registry.services.admin_audit import log_admin_action
        await log_admin_action(
            db, action="org.treasury_created",
            actor_id=str(current_developer.id), target_type="organization", target_id=str(org_id),
            outcome="success", severity="info",
            details={"treasury_agent_did": did, "newly_created": created},
        )
    except Exception:  # noqa: BLE001 — never fail the create on an audit hiccup
        logger.warning("[ORGTREASURY] audit row failed org=%s", org_id, exc_info=True)

    return {"org_id": org_id, "treasury_agent_did": did, "created": created}


class OrgFundRequest(BaseModel):
    agent_did: str = Field(..., max_length=120, description="One of THIS org's active agents")
    amount: str = Field(..., description="Amount to move, as a decimal string (18-dp ledger)")


class OrgRemitRequest(BaseModel):
    amount: str = Field(..., description="Amount to remit to the org treasury, decimal string")


class OrgSweepRequest(BaseModel):
    """E1b — full-balance sweep destination. No amount field on purpose: a sweep drains."""
    dest_agent_did: str = Field(..., max_length=120,
                                description="An ACTIVE agent created by the org owner (not a treasury)")


def _agent_teg_transfer_dep():
    """The IRONKEY agent gate for remit, imported lazily so this router keeps no import-time
    dependency on security.py's agent stack."""
    from agentvault_registry.security import require_agent_permission
    return require_agent_permission("teg.transfer")


def _require_idem(idempotency_key: Optional[str]) -> str:
    """An org money rail REQUIRES a caller-supplied Idempotency-Key — no random fallback.

    Both escrow legs derive their keys from it. If a retry re-derived the base randomly the
    debit leg would run twice and double-charge the source; a stable base instead replays the
    debit and finishes the missing credit. So the header is mandatory, and its absence is a
    400 rather than a silently-generated key."""
    if not idempotency_key or not idempotency_key.strip():
        raise HTTPException(
            status_code=400,
            detail="Idempotency-Key header is required for org treasury movements",
        )
    return idempotency_key.strip()[:128]


@router.post("/{org_id}/treasury/fund", summary="Fund one of the org's agents from the org treasury (org admin)")
async def fund_org_agent(
    payload: OrgFundRequest,
    org_id: str = Path(..., description="Organization ID"),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    current_developer: Annotated[Developer, Security(get_current_developer)] = None,
    db: AsyncSession = Depends(get_db)
):
    """Org treasury → one of the org's own agents. Org ADMIN.

    Units move through the escrow mover in two Δ-neutral legs, never through an agent JWT
    (the treasury is keyless precisely so that no token exists for it). The TEG checks
    solvency on the first leg, so a retry under the same key replays the legs that already
    ran, whatever the treasury holds by then."""

    await get_organization_with_permission(org_id, current_developer, db, "admin")
    idem = _require_idem(idempotency_key)

    from agentvault_registry.services.org_treasury import (
        ProcurementCapExceeded, fund_agent_from_org,
    )
    try:
        res = await fund_agent_from_org(
            db, org_id=org_id, agent_did=payload.agent_did, amount=payload.amount,
            idempotency_key=idem, actor_developer_id=current_developer.id,
        )
    except ProcurementCapExceeded as exc:
        # §ORGSPEND — an authority refusal, not a conflict: the member's cap binds.
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.error("[ORGTREASURY] fund failed org=%s: %r", org_id, exc)
        # §LEDGERGATE (V0598): the gate refuses only the leg INTO the escrow, the first: nothing moved
        from agentvault_registry.services.ledger_unavailable import refusal_from_error
        raise refusal_from_error(exc) or HTTPException(status_code=502, detail=f"treasury move failed: {exc}")

    try:
        from agentvault_registry.services.admin_audit import log_admin_action
        await log_admin_action(
            db, action="org.treasury_fund", actor_id=str(current_developer.id),
            target_type="organization", target_id=str(org_id), outcome="success",
            details={"agent_did": payload.agent_did, "amount": str(payload.amount)},
        )
    except Exception:  # noqa: BLE001
        logger.warning("[ORGTREASURY] fund audit row failed org=%s", org_id, exc_info=True)
    # §CHATDESK C5 — the room's receipt, post-commit, best-effort; D6-777: under the move's own reference (the caller's)
    from agentvault_registry.services.idempotency.cache import developer_caller
    from agentvault_registry.services.org_room_events import post_org_receipt
    from agentvault_registry.services.org_treasury import move_ref
    await post_org_receipt(db, org_id, kind="treasury.fund",
                           amount=str(payload.amount),
                           ref=move_ref("fund", org_id, developer_caller(current_developer.id), idem),
                           counterparty=payload.agent_did)
    return res


@router.post("/{org_id}/treasury/remit", summary="An organization's agent pays its own units into the organization's treasury (agent)")
async def remit_to_org_treasury(
    payload: OrgRemitRequest,
    org_id: str = Path(..., description="Organization ID"),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    current_agent = Security(_agent_teg_transfer_dep()),
    db: AsyncSession = Depends(get_db)
):
    """One of the org's agents → the org treasury, authorized BY THAT AGENT.

    The remitting DID is taken from the authenticated agent, never from the body: an agent can
    only ever remit its own units. There is deliberately NO admin-initiated pull: an org admin
    can grant authority, cap spending and fund an agent, but reaching into an agent's balance
    would be a theft primitive, since an agent joins an org by its creator's choice and its
    balance stays its own."""

    idem = _require_idem(idempotency_key)
    from agentvault_registry.services.org_treasury import remit_agent_to_org
    try:
        res = await remit_agent_to_org(
            db, org_id=org_id, agent_did=current_agent.did, amount=payload.amount,
            idempotency_key=idem,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.error("[ORGTREASURY] remit failed org=%s agent=%s: %r", org_id, current_agent.did, exc)
        # §LEDGERGATE (V0598): the gate refuses only the leg INTO the escrow, the first: nothing moved
        from agentvault_registry.services.ledger_unavailable import refusal_from_error
        raise refusal_from_error(exc) or HTTPException(status_code=502, detail=f"treasury move failed: {exc}")
    # §CHATDESK C5 — the room's receipt, post-commit, best-effort; D6-777: under the move's own reference (the caller's)
    from agentvault_registry.services.idempotency.cache import agent_caller
    from agentvault_registry.services.org_room_events import post_org_receipt
    from agentvault_registry.services.org_treasury import move_ref
    await post_org_receipt(db, org_id, kind="treasury.remit",
                           amount=str(payload.amount),
                           ref=move_ref("remit", org_id, agent_caller(current_agent.did), idem),
                           counterparty=current_agent.did)
    return res


@router.post("/{org_id}/treasury/sweep",
             summary="Drain the org treasury to one of the OWNER's agents (owner only, E1b)")
async def sweep_org_treasury_route(
    payload: OrgSweepRequest,
    org_id: str = Path(..., description="Organization ID"),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    current_developer: Annotated[Developer, Security(get_current_developer)] = None,
    db: AsyncSession = Depends(get_db)
):
    """The exit rail of the corporate-death sequence: `DELETE /organizations/{id}` refuses
    while the org's own treasury holds anything, and this is the sanctioned way out. OWNER
    only (the residual claimant of an org's funds is the liable person behind it, not any
    admin), full balance, destination must be an active agent the owner created and must
    not itself be a treasury. Same escrow mover and mandatory Idempotency-Key as fund."""

    org = await get_organization_with_permission(org_id, current_developer, db)
    if org.owner_id != current_developer.id:
        raise HTTPException(status_code=403, detail="Only the owner can sweep the treasury")
    idem = _require_idem(idempotency_key)

    from agentvault_registry.services.org_treasury import (
        ProcurementCapExceeded, sweep_org_treasury,
    )
    try:
        res = await sweep_org_treasury(
            db, org_id=org_id, dest_agent_did=payload.dest_agent_did,
            idempotency_key=idem, actor_developer_id=current_developer.id,
        )
    except ProcurementCapExceeded as exc:
        # §ORGSPEND — the sweep is a draw too; the owner's own cap binds (raise it in Settings).
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.error("[ORGTREASURY] sweep failed org=%s: %r", org_id, exc)
        # §LEDGERGATE (V0598): the gate refuses only the leg INTO the escrow, the first: nothing moved
        from agentvault_registry.services.ledger_unavailable import refusal_from_error
        raise refusal_from_error(exc) or HTTPException(status_code=502, detail=f"treasury move failed: {exc}")

    try:
        from agentvault_registry.services.admin_audit import log_admin_action
        await log_admin_action(
            db, action="org.treasury_sweep", actor_id=str(current_developer.id),
            target_type="organization", target_id=str(org_id), outcome="success",
            details={"dest_agent_did": payload.dest_agent_did, "amount": res.get("amount")},
        )
    except Exception:  # noqa: BLE001
        logger.warning("[ORGTREASURY] sweep audit row failed org=%s", org_id, exc_info=True)
    return res


# ---------------------------------------------------------------------------
# §ORGCLIENT (H3.1, 2026-08-29 — Commander-approved) — the firm POSTS work.
#
# The org commissions guild work as the CLIENT: the bounty leaves the ORG
# TREASURY (keyless — no agent JWT exists for it), so the dev-driven doors here
# authenticate an org ADMIN and then invoke the EXISTING guild handlers with
# the treasury's own Agent row as the acting poster. ONE lifecycle code path —
# post/award/verify/cancel run the guild router's functions verbatim (escrow,
# claim-first transitions, royalties, reputation, credentials all unchanged);
# these routes add only: org authority, the §ORGSPEND procurement cap on the
# bounty, Idempotency (claim-then-act cache) on the post, and the client-side
# `work.commissioned` room receipt at settlement.
#
# ⚠ Named limitation (the §HIRECOHERE park law — a refusal beats a stranded
# escrow): the award door REFUSES cross-registry bids. The guild's remote
# settle stages payout through the POSTER's own JWT on the verify request, and
# a keyless treasury has none — awarding one would strand the staged funds in
# an unretryable 502 loop. Local bids only, said honestly at award time.
# ---------------------------------------------------------------------------

class OrgWorkOrderCreate(BaseModel):
    title: str = Field(..., max_length=200)
    spec: Optional[str] = Field(None, max_length=8000)
    bounty: str = Field(..., description="Bounty, decimal string (drawn from the org treasury)")
    currency: Optional[str] = Field(None, max_length=12)
    required_skills: Optional[List[str]] = None
    min_reputation: Optional[float] = None
    deadline_seconds: Optional[int] = Field(None, ge=60, le=2592000)
    stake_required: Optional[float] = Field(None, ge=0)
    # V0650 (f): the agent the task is meant for (a flag on the order, never a gate); checked by the Guild's post.
    intended_worker_did: Optional[str] = Field(None, max_length=120)


class OrgWorkAwardIn(BaseModel):
    bid_id: int


class OrgWorkVerifyIn(BaseModel):
    accept: bool = True
    stars: int = Field(5, ge=1, le=5)
    feedback: Optional[str] = Field(None, max_length=2000)


async def _org_poster_or_raise(db: AsyncSession, org_id: str):
    """The org's OWN treasury as a loaded Agent row — the acting poster identity.

    Refuses (like the treasury rails) when the org has no treasury of its own;
    the guild lifecycle needs a real Agent row to act as."""
    from sqlalchemy import select as sa_select
    from agentvault_registry import models as _models
    from agentvault_registry.services.org_treasury import _own_treasury_or_raise
    try:
        did = await _own_treasury_or_raise(db, org_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    agent = (await db.execute(
        sa_select(_models.Agent).where(_models.Agent.did == did)
    )).scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=409, detail="org treasury agent row missing")
    return agent


async def _org_order_or_404(db: AsyncSession, oid: str, treasury_did: str) -> dict:
    row = (await db.execute(sa_text(
        "SELECT * FROM guild_work_orders WHERE id = :o AND poster_did = :p"
    ), {"o": oid, "p": treasury_did})).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="No such work order for this organization")
    return dict(row)


@router.post("/{org_id}/work-orders",
             summary="Commission Guild work as the organization, with the bounty from its treasury")
async def post_org_work_order(
    payload: OrgWorkOrderCreate,
    org_id: str = Path(...),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    current_developer: Annotated[Developer, Security(get_current_developer)] = None,
    db: AsyncSession = Depends(get_db),
):
    """
    An organization admin posts an open Guild order whose poster is the organization's treasury. The organization's
    procurement cap limits the bounty. An `Idempotency-Key` header is required: a replay answers the same order,
    never a second one.
    """
    await get_organization_with_permission(org_id, current_developer, db, "admin")
    idem = _require_idem(idempotency_key)

    from decimal import Decimal, InvalidOperation
    from agentvault_registry.services.org_treasury import (
        ProcurementCapExceeded, _procurement_cap_or_raise,
    )
    from agentvault_registry.services.idempotency.cache import (
        developer_caller, idempotency_lookup, idempotency_store,
    )
    try:
        amt = Decimal(str(payload.bounty))
    except (InvalidOperation, ValueError):
        raise HTTPException(status_code=422, detail=f"invalid bounty: {payload.bounty!r}")
    if amt <= 0:
        raise HTTPException(status_code=422, detail="bounty must be > 0")

    treasury_agent = await _org_poster_or_raise(db, org_id)
    try:
        await _procurement_cap_or_raise(db, org_id, current_developer.id, amt)
    except ProcurementCapExceeded as exc:
        raise HTTPException(status_code=403, detail=str(exc))

    body_dict = payload.model_dump()
    if body_dict.get("intended_worker_did") is None:   # V0650 (f): a body without it hashes as it did on V0649
        body_dict.pop("intended_worker_did", None)
    me = developer_caller(current_developer.id)   # D6-777: the key is this member's, not the organization's
    cached, idem_err = await idempotency_lookup(f"org_work_order:{org_id}", idem, body_dict, principal=me)
    if idem_err:
        raise HTTPException(status_code=422, detail=idem_err)
    if cached is not None:
        return cached

    from agentvault_registry.services.exchange_service import mover
    bal = await mover.agent_balance(treasury_agent.did)
    if bal < amt:
        raise HTTPException(status_code=409,
                            detail=f"insufficient treasury balance: has {bal}, needs {amt}")

    from agentvault_registry.routers import guild as _guild
    order_body = _guild.OrderPostIn(
        title=payload.title, spec=payload.spec, bounty=float(amt),
        currency=payload.currency, required_skills=payload.required_skills,
        min_reputation=payload.min_reputation, deadline_seconds=payload.deadline_seconds,
        stake_required=payload.stake_required, intended_worker_did=payload.intended_worker_did,
    )
    res = await _guild.post_order(order_body, treasury_agent, db)
    res["org_id"] = org_id
    res["poster_did"] = treasury_agent.did

    await idempotency_store(f"org_work_order:{org_id}", idem, body_dict, res, principal=me)
    try:
        from agentvault_registry.services.admin_audit import log_admin_action
        await log_admin_action(
            db, action="org.work_order_posted", actor_id=str(current_developer.id),
            target_type="organization", target_id=str(org_id), outcome="success",
            details={"order_id": res.get("order_id"), "bounty": str(amt),
                     "title": payload.title[:120]},
        )
    except Exception:  # noqa: BLE001
        logger.warning("[ORGCLIENT] post audit row failed org=%s", org_id, exc_info=True)
    return res


@router.get("/{org_id}/work-orders",
            summary="Work orders this organization commissioned (members)")
async def list_org_work_orders(
    org_id: str = Path(...),
    limit: int = Query(50, ge=1, le=200),
    current_developer: Annotated[Developer, Security(get_current_developer)] = None,
    db: AsyncSession = Depends(get_db),
):
    await get_organization_with_permission(org_id, current_developer, db)
    from agentvault_registry.services.org_treasury import resolve_org_treasury_did, org_treasury_source
    if await org_treasury_source(db, org_id) != "org":
        return {"orders": [], "total": 0, "treasury_agent_did": None}
    treasury = await resolve_org_treasury_did(db, org_id)
    rows = (await db.execute(sa_text(
        "SELECT id, title, bounty, currency, status, worker_did, deadline, created_at, settled_at, "
        "(SELECT count(*) FROM guild_bids b WHERE b.order_id = o.id AND b.status = 'open') AS bid_count "
        "FROM guild_work_orders o WHERE poster_did = :p ORDER BY created_at DESC LIMIT :n"
    ), {"p": treasury, "n": limit})).mappings().all()
    return {"orders": [dict(r) for r in rows], "total": len(rows),
            "treasury_agent_did": treasury}


@router.post("/{org_id}/work-orders/{oid}/award",
             summary="Award a bid on the organization's work order (org admin)")
async def award_org_work_order(
    body: OrgWorkAwardIn,
    org_id: str = Path(...),
    oid: str = Path(...),
    current_developer: Annotated[Developer, Security(get_current_developer)] = None,
    db: AsyncSession = Depends(get_db),
):
    await get_organization_with_permission(org_id, current_developer, db, "admin")
    treasury_agent = await _org_poster_or_raise(db, org_id)
    await _org_order_or_404(db, oid, treasury_agent.did)
    # Park law: a cross-registry worker cannot be paid from a keyless treasury
    # (the remote settle stages through the poster's own JWT). Refuse LOUDLY at
    # award time — before any state moves — rather than strand the escrow at verify.
    bid = (await db.execute(sa_text(
        "SELECT home_registry_url FROM guild_bids WHERE id = :b AND order_id = :o"
    ), {"b": body.bid_id, "o": oid})).first()
    if bid and bid[0]:
        raise HTTPException(
            status_code=409,
            detail="This bid is from a cross-registry worker. An organization's work "
                   "orders can only award local bidders for now — the remote payout "
                   "leg needs the poster's own agent token, which a keyless treasury "
                   "deliberately does not have.")
    from agentvault_registry.routers import guild as _guild
    return await _guild.award(oid, _guild.AwardIn(bid_id=body.bid_id), treasury_agent, db)


@router.post("/{org_id}/work-orders/{oid}/verify",
             summary="Accept and pay, or reject into a dispute, the organization's work order (org admin)")
async def verify_org_work_order(
    body: OrgWorkVerifyIn,
    request: Request,
    org_id: str = Path(...),
    oid: str = Path(...),
    current_developer: Annotated[Developer, Security(get_current_developer)] = None,
    db: AsyncSession = Depends(get_db),
):
    await get_organization_with_permission(org_id, current_developer, db, "admin")
    treasury_agent = await _org_poster_or_raise(db, org_id)
    o = await _org_order_or_404(db, oid, treasury_agent.did)
    from agentvault_registry.routers import guild as _guild
    res = await _guild.verify(
        oid, _guild.VerifyIn(accept=body.accept, stars=body.stars, feedback=body.feedback),
        request, treasury_agent, db,
    )
    if body.accept and res.get("status") == "settled":
        # §ORGCLIENT — the CLIENT-side room receipt, mirror of guild.settled:
        # post-commit, best-effort, exactly-once by deterministic client_ref.
        from agentvault_registry.services.org_room_events import post_org_receipt
        await post_org_receipt(db, org_id, kind="work.commissioned",
                               amount=str(res.get("payout")), currency=o.get("currency"),
                               ref=f"orgwork-{oid}", memo=(o.get("title") or "")[:120],
                               counterparty=o.get("worker_did"))
        try:
            from agentvault_registry.services.admin_audit import log_admin_action
            await log_admin_action(
                db, action="org.work_order_settled", actor_id=str(current_developer.id),
                target_type="organization", target_id=str(org_id), outcome="success",
                details={"order_id": oid, "payout": str(res.get("payout")),
                         "worker_did": o.get("worker_did")},
            )
        except Exception:  # noqa: BLE001
            logger.warning("[ORGCLIENT] settle audit row failed org=%s", org_id, exc_info=True)
    return res


@router.post("/{org_id}/work-orders/{oid}/cancel",
             summary="Cancel the organization's open work order and refund its treasury (org admin)")
async def cancel_org_work_order(
    org_id: str = Path(...),
    oid: str = Path(...),
    current_developer: Annotated[Developer, Security(get_current_developer)] = None,
    db: AsyncSession = Depends(get_db),
):
    await get_organization_with_permission(org_id, current_developer, db, "admin")
    treasury_agent = await _org_poster_or_raise(db, org_id)
    await _org_order_or_404(db, oid, treasury_agent.did)
    from agentvault_registry.routers import guild as _guild
    return await _guild.cancel(oid, treasury_agent, db)


# ── Organization Agent Management (f040) ──

@router.get("/{org_id}/cicd-summary")
async def organization_cicd_summary(
    org_id: str,
    developer: Developer = Security(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Aggregated CI/CD activity across all agents of an organization.

    Returns:
      {
        "organization_id": "...",
        "agent_count": N,
        "pipelines": { "total": K, "last_created_at": "..." },
        "deployments_24h": {
            "total": M, "success": x, "failed": y, "pending": z,
            "top_failing_agents": [{ "did": ..., "fail_count": ... }, ...]
        },
        "active_versions": [{ "did": ..., "version": ..., "activated_at": ... }, ...]
      }
    """
    from sqlalchemy import select, text
    from agentvault_registry.models import Agent
    await get_organization_with_permission(org_id, developer, db, "member")

    # Step 1: enumerate org's agents.
    agent_rows = await db.execute(
        select(Agent.did).where(Agent.organization_id == org_id)
    )
    dids = [r[0] for r in agent_rows]
    if not dids:
        return {
            "organization_id": org_id, "agent_count": 0,
            "pipelines": {"total": 0, "last_created_at": None},
            "deployments_24h": {
                "total": 0, "success": 0, "failed": 0, "pending": 0,
                "top_failing_agents": [],
            },
            "active_versions": [],
        }

    # Step 2: pipeline aggregate.
    pipe_row = (await db.execute(
        text("""
            SELECT COUNT(*)::int AS total, MAX(created_at) AS last_created
            FROM agent_pipelines
            WHERE agent_did = ANY(:dids)
        """),
        {"dids": dids},
    )).first()

    # Step 3: 24h deployment aggregate.
    dep_row = (await db.execute(
        text("""
            SELECT
              COUNT(*)::int AS total,
              SUM(CASE WHEN status='success' THEN 1 ELSE 0 END)::int AS success,
              SUM(CASE WHEN status='failed'  THEN 1 ELSE 0 END)::int AS failed,
              SUM(CASE WHEN status IN ('pending','running') THEN 1 ELSE 0 END)::int AS pending
            FROM agent_deployments
            WHERE agent_did = ANY(:dids) AND started_at > NOW() - INTERVAL '24 hours'
        """),
        {"dids": dids},
    )).first()

    top_fail_rows = await db.execute(
        text("""
            SELECT agent_did, COUNT(*)::int AS fail_count
            FROM agent_deployments
            WHERE agent_did = ANY(:dids)
              AND status='failed'
              AND started_at > NOW() - INTERVAL '24 hours'
            GROUP BY agent_did
            ORDER BY fail_count DESC
            LIMIT 5
        """),
        {"dids": dids},
    )
    top_failing = [{"did": r.agent_did, "fail_count": r.fail_count} for r in top_fail_rows]

    # Step 4: active (is_current=true) versions per agent.
    ver_rows = await db.execute(
        text("""
            SELECT agent_did, version, created_at
            FROM agent_versions
            WHERE agent_did = ANY(:dids) AND is_current = true
            ORDER BY agent_did
        """),
        {"dids": dids},
    )
    active_versions = [
        {"did": r.agent_did, "version": r.version, "activated_at": r.created_at.isoformat()}
        for r in ver_rows
    ]

    return {
        "organization_id": org_id,
        "agent_count": len(dids),
        "pipelines": {
            "total": pipe_row.total if pipe_row else 0,
            "last_created_at": (pipe_row.last_created.isoformat() if (pipe_row and pipe_row.last_created) else None),
        },
        "deployments_24h": {
            "total":   (dep_row.total   or 0) if dep_row else 0,
            "success": (dep_row.success or 0) if dep_row else 0,
            "failed":  (dep_row.failed  or 0) if dep_row else 0,
            "pending": (dep_row.pending or 0) if dep_row else 0,
            "top_failing_agents": top_failing,
        },
        "active_versions": active_versions,
    }


@router.get("/{org_id}/agents")
async def list_organization_agents(
    org_id: str,
    team_id: Optional[str] = Query(None, description="Filter by team"),
    developer: Developer = Security(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """List all agents assigned to this organization (or filtered by team)."""
    from sqlalchemy import select
    from agentvault_registry.models import Agent

    org = await get_organization_with_permission(org_id, developer, db, "member")

    stmt = select(Agent).where(Agent.organization_id == org_id)
    if team_id:
        stmt = stmt.where(Agent.team_id == team_id)
    stmt = stmt.order_by(Agent.created_at.desc())

    result = await db.execute(stmt)
    agents = result.scalars().all()

    # agents has NO name column — human names live on agent_cards. One batch
    # lookup so every org surface fed by this payload (AGENTS tab cards, the
    # A2 authority panel rows) shows names instead of DIDs. Duplicate-proof:
    # first card per DID wins; missing card falls back to None (FE shows DID).
    names: Dict[str, str] = {}
    if agents:
        from sqlalchemy import text as _text
        rows = (await db.execute(_text(
            "SELECT DISTINCT ON (agent_did) agent_did, name FROM agent_cards "
            "WHERE agent_did = ANY(:dids) ORDER BY agent_did"
        ), {"dids": [a.did for a in agents]})).fetchall()
        names = {r[0]: r[1] for r in rows if r[1]}

    # §ORGLIFE L2 — the two facts that used to be invisible here.
    #
    # An assignment SURVIVES its creator leaving the org, on purpose (the record is the
    # org's as much as the creator's, and removing it silently is the sweep §ORGJOIN
    # refused). That is only defensible if the screen SAYS so — the pre-batch population
    # carried three such rows that nobody could see and nobody could explain.
    #
    #   creator_is_member — is the agent's creator still an active member (or the owner)?
    #   org_authority     — 'live' | 'revoked' | 'none': what this org's grant actually
    #                       confers on the agent RIGHT NOW.
    #
    # ⚠ 'none' means no org: grant row was ever written for this agent — NOT that the
    # agent is powerless (its own roles are separate) and NOT that a grant was revoked.
    # Absence and revocation are different states and the FE renders them differently.
    creator_member: Dict[int, bool] = {}
    authority: Dict[str, str] = {}
    if agents:
        from sqlalchemy import text as _text
        member_rows = (await db.execute(_text(
            "SELECT d.id FROM (SELECT unnest(CAST(:devs AS int[])) AS id) d "
            "WHERE EXISTS (SELECT 1 FROM organization_members m "
            "               WHERE m.organization_id = :o "
            "                 AND m.developer_id = d.id AND m.is_active) "
            "   OR d.id = (SELECT owner_id FROM organizations WHERE id = :o)"
        ), {"devs": [a.creator_developer_id for a in agents if a.creator_developer_id],
            "o": str(org_id)})).fetchall()
        still_in = {r[0] for r in member_rows}
        creator_member = {a.creator_developer_id: (a.creator_developer_id in still_in)
                          for a in agents if a.creator_developer_id}
        grant_rows = (await db.execute(_text(
            "SELECT delegate_agent_did, bool_or(revoked_at IS NULL) AS any_live "
            "  FROM agent_delegation_grants "
            " WHERE principal_type = 'org' AND principal_ref IN (:ref_slug, :ref_id) "
            "   AND delegate_agent_did = ANY(:dids) GROUP BY delegate_agent_did"
        ), {"ref_slug": f"org:{org.slug}", "ref_id": f"org:{org.id}",
            "dids": [a.did for a in agents]})).fetchall()
        authority = {r[0]: ("live" if r[1] else "revoked") for r in grant_rows}

    return {
        "organization_id": org_id,
        "team_id": team_id,
        "agents": [
            {
                "did": a.did, "name": names.get(a.did),
                "status": a.status, "team_id": a.team_id,
                "creator_developer_id": a.creator_developer_id,
                # None (not False) when there is no creator to ask about — absence is
                # absence, the same rule PocketOrgs applies to member_count.
                "creator_is_member": (creator_member.get(a.creator_developer_id)
                                      if a.creator_developer_id else None),
                "org_authority": authority.get(a.did, "none"),
            }
            for a in agents
        ],
        "count": len(agents),
    }


@router.get("/{org_id}/presence", summary="Who of the organization's agents is here, and what they are doing")
async def get_organization_presence(
    org_id: str = Path(..., description="Organization ID"),
    actor_dict: dict = Depends(get_current_actor_for_read),
    db: AsyncSession = Depends(get_db),
):
    """V0650 (a). Every agent assigned to the organization (a revoked one is no longer present): its DID, its card's
    name, its owner, when it was last active, its account status and its live status line (null once the line expired,
    and for a suspended agent). Read by whoever the organization's room admits, by the room's own rule: an active member
    (guests included) or an agent assigned to the organization. A developer JWT or an agent JWT."""
    from agentvault_registry.services import agent_status_line as sl
    from agentvault_registry.services import chat_service as cs
    org = await OrganizationService.get_organization(db, org_id)
    if org is None or not getattr(org, "is_active", True):
        raise HTTPException(status_code=404, detail="Organization not found")
    actor = cs.actor_from_auth(actor_dict)
    if await cs.actor_org_role(db, org_id, actor) is None:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return await sl.org_presence(db, org_id)


@router.get("/{org_id}/spend-approvals")
async def list_org_spend_approvals(
    org_id: str,
    status_filter: Optional[str] = Query(None, alias="status",
                                         description="pending|approved|denied|consumed|expired"),
    limit: int = Query(50, ge=1, le=200),
    developer: Developer = Security(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """
    The spend approvals of this organization's agents, read-only, for an org admin or owner. Deciding a spend stays
    with the agent's owning developer (Settings, Approvals), the liable party behind the agent: an org admin sees
    the queue but cannot decide it.
    """
    from sqlalchemy import text

    await get_organization_with_permission(org_id, developer, db, "admin")

    # agents has NO name column — the human name lives on agent_cards; a scalar
    # subquery keeps this duplicate-proof (mirrors can share an agent_did).
    q = ("SELECT sa.id, sa.agent_did, "
         "(SELECT c.name FROM agent_cards c WHERE c.agent_did = sa.agent_did LIMIT 1) AS agent_name, "
         "a.creator_developer_id AS owner_developer_id, sa.action, sa.amount, "
         "sa.currency, sa.counterparty_did, sa.status, sa.reason, "
         "sa.created_at, sa.expires_at, sa.resolved_at, sa.consumed_at "
         "FROM agent_spend_approvals sa JOIN agents a ON a.did = sa.agent_did "
         "WHERE a.organization_id = :org ")
    p: Dict[str, Any] = {"org": org_id, "lim": limit}
    if status_filter:
        q += "AND sa.status = :st "
        p["st"] = status_filter
    q += "ORDER BY sa.created_at DESC LIMIT :lim"
    rows = (await db.execute(text(q), p)).mappings().all()
    out = []
    for r in rows:
        d = dict(r)
        d["amount"] = str(d["amount"])
        for k in ("created_at", "expires_at", "resolved_at", "consumed_at"):
            if d.get(k) is not None:
                d[k] = d[k].isoformat()
        out.append(d)
    return {"organization_id": org_id, "approvals": out, "count": len(out)}


@router.get("/{org_id}/activity-rollup",
            summary="Organization-wide roll-up: spending per agent, refusals, approvals, treasury flows")
async def get_org_activity_rollup(
    org_id: str = Path(..., description="Organization ID"),
    days: int = Query(7, ge=1, le=90, description="Rolling window in days"),
    current_developer: Annotated[Developer, Security(get_current_developer)] = None,
    db: AsyncSession = Depends(get_db)
):
    """
    What the organization's agents spent, what was refused, what waits for approval and what moved through the
    treasury over the last `days` (7 by default), in one answer (org admin). Every figure comes from the source its
    gate reads: spending from `velocity_metrics` (settled volume by the hour; the current hour lags about an hour),
    refusals from `security_audit_logs` (`ironkey.*` denials), approvals from `agent_spend_approvals`, treasury
    flows from the event store (when it cannot be reached, `treasury.flows_available` is false rather than a zero).
    """
    from sqlalchemy import text as _text
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz

    org = await get_organization_with_permission(org_id, current_developer, db, "admin")

    agents = (await db.execute(_text(
        "SELECT a.did, (SELECT c.name FROM agent_cards c WHERE c.agent_did = a.did "
        "               ORDER BY c.updated_at DESC NULLS LAST LIMIT 1) AS name "
        "FROM agents a WHERE a.organization_id = :o"
    ), {"o": str(org_id)})).fetchall()
    dids = [r[0] for r in agents]
    names = {r[0]: r[1] for r in agents}

    spend_by, denials_by, denial_breakdown, approvals_by = {}, {}, {}, {}
    if dids:
        for did, vol, cnt in (await db.execute(_text(
            "SELECT agent_did, COALESCE(SUM(tx_volume), 0), COALESCE(SUM(tx_count), 0) "
            "FROM velocity_metrics WHERE agent_did = ANY(:dids) "
            "AND window_start > now() - make_interval(days => :days) GROUP BY agent_did"
        ), {"dids": dids, "days": days})).fetchall():
            spend_by[did] = {"volume": float(vol or 0), "tx_count": int(cnt or 0)}
        # security_audit_logs.timestamp is naive-UTC (no tz) — compare against naive now()
        for did, action, n in (await db.execute(_text(
            "SELECT actor_id, action, count(*) FROM security_audit_logs "
            "WHERE actor_id = ANY(:dids) AND action LIKE 'ironkey.%' AND outcome = 'deny' "
            "AND timestamp > (now() at time zone 'utc') - make_interval(days => :days) "
            "GROUP BY actor_id, action"
        ), {"dids": dids, "days": days})).fetchall():
            denials_by[did] = denials_by.get(did, 0) + int(n)
            denial_breakdown[action] = denial_breakdown.get(action, 0) + int(n)
        for status_, n in (await db.execute(_text(
            "SELECT status, count(*) FROM agent_spend_approvals "
            "WHERE agent_did = ANY(:dids) "
            "AND created_at > now() - make_interval(days => :days) GROUP BY status"
        ), {"dids": dids, "days": days})).fetchall():
            approvals_by[str(status_)] = int(n)

    per_agent = sorted(
        ({"did": d, "name": names.get(d),
          "spend": spend_by.get(d, {}).get("volume", 0.0),
          "tx_count": spend_by.get(d, {}).get("tx_count", 0),
          "denials": denials_by.get(d, 0)} for d in dids),
        key=lambda r: (-r["spend"], -r["denials"], r["did"]))

    # ── treasury: live balance (own account only) + windowed flows from the ES ──
    treasury: Dict[str, Any] = {"exists": False, "balance": None,
                                "flows_available": False, "flows": None}
    try:
        from agentvault_registry.services.org_treasury import org_treasury_source, resolve_org_treasury_did
        if await org_treasury_source(db, org_id) == "org":
            tdid = await resolve_org_treasury_did(db, org_id)
            treasury["exists"] = True
            treasury["treasury_agent_did"] = tdid
            from agentvault_registry.services.exchange_service import mover
            treasury["balance"] = str(await mover.agent_balance(tdid))
    except Exception as exc:  # noqa: BLE001 — a TEG hiccup must not kill the roll-up
        logger.warning("[ORG-ROLLUP] treasury balance read failed org=%s: %r", org_id, exc)

    try:
        import os as _os
        import httpx as _httpx
        from urllib.parse import quote as _q
        from agentvault_registry.es_ssl_helper import get_httpx_verify
        es_url = _os.environ.get("EVENT_STORE_URL", "http://event-store:8200")
        es_key = (_os.environ.get("EVENT_STORE_INTERNAL_KEY")
                  or _os.environ.get("EVENT_STORE_API_KEY") or "")
        cutoff = _dt.now(_tz.utc) - _td(days=days)
        _MONEY = {"OrganizationTreasuryFunded": "out", "OrganizationTreasuryRemitted": "in",
                  "OrganizationTreasurySwept": "out"}
        flows = {"in": 0.0, "out": 0.0, "events": 0}
        async with _httpx.AsyncClient(timeout=8.0, verify=get_httpx_verify()) as client:
            resp = await client.get(
                f"{es_url}/api/v1/events/aggregate/{_q(str(org_id), safe=':')}",
                params={"limit": 500, "event_types": ",".join(sorted(_MONEY))},
                headers={"X-Internal-Key": es_key} if es_key else {},
            )
            resp.raise_for_status()
            payload = resp.json()
            events = payload if isinstance(payload, list) else payload.get("events") or []
            for ev in events:
                et = ev.get("event_type") or ev.get("type")
                if et not in _MONEY:
                    continue
                ts = str(ev.get("timestamp") or ev.get("created_at") or "")
                try:
                    if ts and _dt.fromisoformat(ts.replace("Z", "+00:00")) < cutoff:
                        continue
                except ValueError:
                    pass  # unparseable timestamp: count it rather than silently drop money
                data = ev.get("data") or ev.get("event_data") or {}
                try:
                    amt = float(data.get("amount") or 0)
                except (TypeError, ValueError):
                    amt = 0.0
                flows[_MONEY[et]] += amt
                flows["events"] += 1
        treasury["flows_available"] = True
        treasury["flows"] = flows
    except Exception as exc:  # noqa: BLE001 — honest absence beats a fabricated zero
        logger.warning("[ORG-ROLLUP] ES flows read failed org=%s: %r", org_id, exc)

    return {
        "org_id": org.id,
        "window_days": days,
        "agents": per_agent,
        "totals": {
            "spend": round(sum(r["spend"] for r in per_agent), 6),
            "tx_count": sum(r["tx_count"] for r in per_agent),
            "denials": sum(r["denials"] for r in per_agent),
            "agents": len(per_agent),
            "agents_active": sum(1 for r in per_agent if r["tx_count"] > 0),
        },
        "denial_breakdown": denial_breakdown,
        "approvals": approvals_by,
        "treasury": treasury,
    }


@router.post("/{org_id}/agents/{agent_did}/assign")
async def assign_agent_to_org(
    org_id: str,
    agent_did: str,
    team_id: Optional[str] = Body(None, embed=True),
    developer: Developer = Security(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Assign an agent to this organization (and optionally a team). Only the agent's creator or org admin can do this."""
    from sqlalchemy import select
    from agentvault_registry.models import Agent

    org = await get_organization_with_permission(org_id, developer, db, "admin")

    # Find agent
    result = await db.execute(select(Agent).where(Agent.did == agent_did))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(404, "Agent not found")

    # Must be agent creator (org admin permission already checked by get_organization_with_permission)
    if agent.creator_developer_id != developer.id:
        raise HTTPException(403, "Only the agent creator can assign agents")

    # Enforce the org's stored max_agents cap (limits JSON — may be NULL on old rows).
    # Re-assigning an agent already in this org (e.g. a team move) never counts against it.
    if agent.organization_id != org_id:
        from sqlalchemy import func as sa_func
        agent_count = (await db.execute(
            select(sa_func.count()).select_from(Agent).where(Agent.organization_id == org_id)
        )).scalar() or 0
        max_agents = int(((org.limits or {}).get("max_agents") or 100))
        if agent_count >= max_agents:
            raise HTTPException(409, f"Organization agent limit reached ({agent_count}/{max_agents})")

    # §ORGLIFE L2c — a MOVE is an unassign the unassign route never sees. Assigning an
    # agent that already belongs to another org silently re-pointed the link and left the
    # previous org's grant live-but-inert; moving it back reanimated the old slice
    # (measured: A 10/10 -> move to B -> A 0/10 -> move back -> A 10/10). Same class as
    # removal and unassign, third path. Revoke the PREVIOUS org's grants here so the only
    # authority an agent carries is the one its current org chose.
    prev_org_id = agent.organization_id
    if prev_org_id and str(prev_org_id) != str(org_id):
        try:
            async with db.begin_nested():
                prev = (await db.execute(sa_text(
                    "SELECT id, slug FROM organizations WHERE id = :o"), {"o": str(prev_org_id)})).first()
                if prev:
                    await db.execute(sa_text("""
                        UPDATE agent_delegation_grants SET revoked_at = now(),
                               revoke_reason = 'agent reassigned to another organization'
                         WHERE principal_type = 'org'
                           AND principal_ref IN (:ref_slug, :ref_id)
                           AND delegate_agent_did = :did AND revoked_at IS NULL
                    """), {"ref_slug": f"org:{prev[1]}", "ref_id": f"org:{prev[0]}", "did": agent_did})
        except Exception as e:  # noqa: BLE001 — never fail the assignment over the old org
            logger.warning("[ORGLIFE] prev-org grant revoke failed for %s: %s", agent_did, e)

    agent.organization_id = org_id
    if team_id:
        # Verify team belongs to this org
        from agentvault_registry.models import Team
        team_result = await db.execute(select(Team).where(Team.id == team_id, Team.organization_id == org_id))
        if not team_result.scalar_one_or_none():
            raise HTTPException(404, "Team not found in this organization")
        agent.team_id = team_id

    await db.commit()

    # Track A5 — auto-grant the org's configured default authority slice on assignment.
    # Best-effort AFTER the assign commit: a grant failure must never undo the assignment.
    try:
        from agentvault_registry.services.org_policy import default_authority_slice
        from agentvault_registry.services.org_authz import grant_org_slice
        slice_name = default_authority_slice(org.settings if isinstance(org.settings, dict) else {})
        if slice_name:
            await grant_org_slice(db, org_slug=org.slug, agent_dids=[agent_did],
                                  role=slice_name, granted_by=developer.id)
            await db.commit()
            logger.info("[ORG-AUTHORITY] default slice %s auto-granted to %s on assign to org %s",
                        slice_name, agent_did, org_id)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[ORG-AUTHORITY] default-slice auto-grant failed for {agent_did}: {e}")

    return {"message": f"Agent {agent_did} assigned to organization {org_id}", "team_id": team_id}


@router.post("/{org_id}/agents/{agent_did}/unassign")
async def unassign_agent_from_org(
    org_id: str,
    agent_did: str,
    developer: Developer = Security(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Remove an agent from this organization."""
    from sqlalchemy import select
    from agentvault_registry.models import Agent

    org = await get_organization_with_permission(org_id, developer, db, "admin")

    result = await db.execute(select(Agent).where(Agent.did == agent_did, Agent.organization_id == org_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(404, "Agent not found in this organization")

    agent.organization_id = None
    agent.team_id = None
    await db.commit()

    # §ORGLIFE L2b — unassigning is the org saying "this agent is not ours any more",
    # so the authority scoped to that relationship goes with it. The link half already
    # made the grant INERT while unassigned; leaving the row live meant a later
    # re-assignment REANIMATED whatever slice the org had chosen at some earlier time.
    # Measured: assign under 'owner' -> 10/10 org-only permissions; unassign -> 0/10;
    # clear the org's default slice entirely and re-assign -> 10/10 again, from a grant
    # nobody had chosen for years. Same class as removal (a row outliving the standing
    # it depends on); revoking here means a re-assignment confers exactly what the org
    # chooses at THAT moment, which is what the assign hook already writes.
    try:
        async with db.begin_nested():
            revoked = (await db.execute(sa_text("""
                UPDATE agent_delegation_grants SET revoked_at = now(),
                       revoke_reason = 'agent unassigned from organization'
                 WHERE principal_type = 'org'
                   AND principal_ref IN (:ref_slug, :ref_id)
                   AND delegate_agent_did = :did
                   AND revoked_at IS NULL
            """), {"ref_slug": f"org:{org.slug}", "ref_id": f"org:{org.id}",
                   "did": agent_did})).rowcount or 0
        await db.commit()
        if revoked:
            logger.info("[ORGLIFE] org=%s agent=%s org-grants revoked on unassign: %d",
                        org_id, agent_did, revoked)
    except Exception as e:  # noqa: BLE001 — the agent IS unassigned; never fail over this
        logger.warning("[ORGLIFE] org-grant revoke failed on unassign %s / %s: %s",
                       agent_did, org_id, e)

    return {"message": f"Agent {agent_did} removed from organization"}


# ---------------------------------------------------------------------------
# §CHATDESK H1.1 — the FIRM's verifiable track record (PUBLIC read).
# The write side has existed since the guild firm-bid rail (`payee_org_id` on
# settled work orders); nothing read it until now. Attribution is
# snapshot-at-verification BY CONSTRUCTION — payee_org_id was written when the
# work settled, so a departure does not rewrite history. Public like the
# per-agent /agents/{did}/track-record: it aggregates already-public receipt
# facts. Honest zeros; computed on read; no snapshot table, nothing to drift.
# ---------------------------------------------------------------------------
@router.get("/{org_id}/track-record",
            summary="The organization's verifiable track record (public)")
async def get_org_track_record(org_id: str, db: AsyncSession = Depends(get_db)):
    row = (await db.execute(sa_text(
        "SELECT id, name, slug, is_active FROM organizations WHERE id = :o"),
        {"o": org_id})).first()
    if not row:
        raise HTTPException(status_code=404, detail="Organization not found")
    from agentvault_registry.services import track_record as _tr
    rec = await _tr.org_track_record(db, org_id)
    rec.update({"org_id": org_id, "name": row[1], "slug": row[2],
                "is_active": bool(row[3])})
    return rec


# ---------------------------------------------------------------------------
# §OCOPTIN (2026-08-28, Commander's design) — the PUBLIC transparency feed.
# An org that has explicitly opted in (settings.public_transparency_opt_in,
# default false, settable at creation + in settings) serves its room's WORK
# RECORDS read-only: system rows + org.work.receipt cards + the room topic.
# Members' free-text messages and DMs are excluded BY CONSTRUCTION — the query
# never selects kind='text', and only rail-authored receipt cards pass the
# card filter. The opt-in is re-read PER REQUEST (§ORGLIFE read-time law):
# opting out stops the feed on the next request, not the next sync. Every
# refusal is the same 404 — a non-opted org is indistinguishable from a
# missing one, so the endpoint leaks nothing about orgs that chose privacy.
# ---------------------------------------------------------------------------
# §CHATPOLISH — the system rows a PUBLIC transparency feed may carry: the CLOSED
# room-op vocabulary, and only that. This is the exact set
# `services/chat/orgRoomActions.ts::systemRowText` knows how to render; anything
# else in a system row's body is free prose, which the "records only" law says
# must be structurally unreachable from here.
#
# ⚠ NARROWED ON PURPOSE, then WIDENED BACK. The first cut of this list also
# dropped kick/mute/unmute, reasoning that a public page naming a removed member
# is not a work record. The §OCOPTIN battery failed on it — correctly: those rows
# have served this feed since the surface shipped, and whether a transparency
# opt-in should also publish moderation that names individuals is the
# Commander's design call, not a side effect of fixing the support-prose leak.
# Filed for him; the vocabulary stays whole until he rules.
_PUBLIC_FEED_SYSTEM_ROWS = (
    "room.topic", "room.motd", "room.mode",
    "room.kick", "room.mute", "room.unmute",
    "room.assistant_on", "room.assistant_off",
)


@router.get("/{org_id}/public-feed",
            summary="Public work-record feed of an organization that opted into transparency")
async def get_org_public_feed(
    org_id: str,
    before_seq: Optional[int] = Query(None, ge=1, description="Return records with seq < this (paging)"),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    from agentvault_registry.services import org_policy
    _nf = HTTPException(status_code=404, detail="No public feed")
    row = (await db.execute(sa_text(
        "SELECT id, name, slug, is_active, settings FROM organizations WHERE id = :o"),
        {"o": org_id})).first()
    if not row or not bool(row[3]) or not org_policy.transparency_public(row[4] if isinstance(row[4], dict) else None):
        raise _nf
    conv = (await db.execute(sa_text(
        "SELECT id, topic, last_seq FROM conversations WHERE kind = 'org' AND org_id = :o LIMIT 1"),
        {"o": org_id})).first()
    if not conv:
        # An org may opt into transparency before it opens its room (a room is
        # off until the org wants one, §OURSTATE-6). /public/transparent lists it
        # all the same, so the feed answers what is true, no records yet; a 404
        # here was a dead link on that list and "read failed" on /firms.
        return {
            "org_id": row[0], "name": row[1], "slug": row[2],
            "topic": None,
            "transparency": "records-only",
            "records": [],
            "next_before_seq": None,
        }
    # Records only: rail-authored org.work.receipt cards + system rows drawn
    # from the CLOSED room-op vocabulary. Free text is structurally unreachable.
    #
    # 🔴 §CHATPOLISH (2026-08-30) — `kind = 'system'` was NOT records-only.
    # A system row's `body` is either a machine key (`room.topic`,
    # `room.assistant_on`, … — the vocabulary `services/chat/orgRoomActions.ts::
    # systemRowText` renders) or free PROSE written by another rail. The support
    # consent rail writes prose, so the public exhibit measured **8 system rows
    # to 4 receipts, and the 8 newest were all "The support desk's review access
    # ended: ticket #233 closed."** — an anonymous visitor was reading the org's
    # support history on a page whose own copy promises "verifiable work
    # records". Denylisting that one rail would leave the class open, so this is
    # an ALLOWLIST: a body outside the vocabulary is not a record.
    #
    # `kick`/`mute`/`unmute` are IN the vocabulary and still excluded here: they
    # name an individual member, and who was removed from a private room is not
    # a work record. They stay visible to members, where they belong.
    params: Dict[str, Any] = {"c": conv[0], "n": limit,
                              "sysok": list(_PUBLIC_FEED_SYSTEM_ROWS)}
    cursor_sql = ""
    if before_seq is not None:
        cursor_sql = " AND seq < :before"
        params["before"] = before_seq
    msgs = (await db.execute(sa_text(
        "SELECT seq, kind, body, card, created_at FROM chat_messages "
        "WHERE conversation_id = :c AND deleted_at IS NULL"
        " AND ((kind = 'system' AND body = ANY(:sysok))"
        "      OR (kind = 'card' AND card->>'type' = 'org.work.receipt'))"
        + cursor_sql +
        " ORDER BY seq DESC LIMIT :n"), params)).fetchall()
    records = []
    for m in msgs:
        rec: Dict[str, Any] = {"seq": int(m[0]), "kind": m[1],
                               "at": m[4].isoformat() if m[4] else None}
        if m[1] == "system":
            rec["body"] = m[2]
        else:
            rec["card"] = m[3]
        records.append(rec)
    return {
        "org_id": row[0], "name": row[1], "slug": row[2],
        "topic": conv[1],
        "transparency": "records-only",
        "records": records,
        "next_before_seq": records[-1]["seq"] if len(records) == limit else None,
    }


# ---------------------------------------------------------------------------
# §FIRMHIRE (H3.2, 2026-08-29) — FIRMS in Discovery, proof-ranked.
#
# PUBLIC, like the per-org track record it aggregates: settled guild work is a
# public fact (the board shows it), so a lane ranking firms by it exposes
# nothing new. Lane membership is deliberately "firms that have DONE something
# or configured themselves for hiring" (settled work as worker OR client,
# transparency opt-in, or an intake door) — an org that is none of those is not
# a firm anyone can hire, and battery/fixture orgs delete themselves. Honest
# zeros render as zeros (§DISCREFINE law); ranking is proof-weighted (the
# browse law). ⚠ TWO-SEGMENT path on purpose: a bare /discover would be
# swallowed by the earlier-registered GET /{org_id} (§NOTIFV2 registration-
# order trap).
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# §FIRMBOOKS (O-F, 2026-08-29) — the firm's books, in one statement.
#
# Read-side ONLY, registry records only, and ADMIN-ONLY even for a
# transparency-opted-in org: the PUBLIC feed is the public surface (records
# curated for outsiders); the statement is the INTERNAL ledger view. Two
# merged sources, each row naming which:
#   * the org room's RAIL-AUTHORED receipt cards (§CHATDESK designed these as
#     the firm's books: fund / remit / dividend.declared / guild.settled /
#     work.commissioned — amount, currency, ref, counterparty, timestamp);
#   * the org-money ADMIN AUDIT rows (who drove each dev-side draw).
# Every money row carries its ref — a TEG idempotency base, independently
# checkable. An org with no room still gets the audit half plus an honest note.
# ---------------------------------------------------------------------------
@router.get("/{org_id}/statement",
            summary="The organization's merged account statement (org admin)")
async def get_org_statement(
    org_id: str = Path(...),
    limit: int = Query(200, ge=1, le=500),
    format: Optional[str] = Query(None, description="'csv' for a CSV export"),
    current_developer: Annotated[Developer, Security(get_current_developer)] = None,
    db: AsyncSession = Depends(get_db),
):
    await get_organization_with_permission(org_id, current_developer, db, "admin")

    rows: List[Dict[str, Any]] = []
    room_exists = False
    conv = (await db.execute(sa_text(
        "SELECT id FROM conversations WHERE kind = 'org' AND org_id = :o LIMIT 1"
    ), {"o": org_id})).first()
    if conv:
        room_exists = True
        for m in (await db.execute(sa_text(
            "SELECT created_at, card FROM chat_messages "
            "WHERE conversation_id = :c AND deleted_at IS NULL AND kind = 'card' "
            "AND card->>'type' = 'org.work.receipt' ORDER BY seq DESC LIMIT :n"
        ), {"c": conv[0], "n": limit})).fetchall():
            card = m[1] or {}
            data = card.get("data") or {}
            refs = card.get("refs") or {}
            rows.append({
                "at": m[0].isoformat() if m[0] else None,
                "source": "receipt",
                "kind": data.get("kind"),
                "amount": data.get("amount"),
                "currency": data.get("currency"),
                "counterparty": data.get("counterparty"),
                "memo": data.get("memo"),
                "ref": refs.get("ref"),
                "actor": None,
            })
    for a in (await db.execute(sa_text(
        "SELECT timestamp, action, actor_id, details FROM security_audit_logs "
        "WHERE target_type = 'organization' AND target_id = :o "
        "AND action IN ('org.treasury_fund', 'org.treasury_sweep', 'org.treasury_created', "
        "'org.work_order_posted', 'org.work_order_settled') "
        "ORDER BY timestamp DESC LIMIT :n"
    ), {"o": str(org_id), "n": limit})).fetchall():
        det = a[3] if isinstance(a[3], dict) else {}
        rows.append({
            "at": a[0].isoformat() if a[0] else None,
            "source": "audit",
            "kind": a[1],
            "amount": det.get("amount") or det.get("bounty") or det.get("payout"),
            "currency": None,
            "counterparty": det.get("agent_did") or det.get("dest_agent_did") or det.get("worker_did"),
            "memo": det.get("title") or (f"order {det.get('order_id')}" if det.get("order_id") else None),
            "ref": det.get("order_id"),
            "actor": a[2],
        })
    rows.sort(key=lambda r: r["at"] or "", reverse=True)
    rows = rows[:limit]

    if (format or "").lower() == "csv":
        import csv as _csv
        import io as _io
        buf = _io.StringIO()
        w = _csv.DictWriter(buf, fieldnames=[
            "at", "source", "kind", "amount", "currency", "counterparty",
            "memo", "ref", "actor"])
        w.writeheader()
        for r in rows:
            w.writerow(r)
        from fastapi.responses import Response as _Resp
        return _Resp(content=buf.getvalue(), media_type="text/csv",
                     headers={"Content-Disposition":
                              f"attachment; filename=org-{str(org_id)[:8]}-statement.csv"})

    return {"org_id": org_id, "rows": rows, "total": len(rows),
            "room_exists": room_exists,
            "note": (None if room_exists else
                     "This organization has no room, so no receipt cards exist — "
                     "the statement shows the audit half only.")}


@router.get("/discover/firms",
            summary="Firms ranked by verifiable track record (public)")
async def discover_firms(
    limit: int = Query(12, ge=1, le=25),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(sa_text("""
        WITH worker AS (
            SELECT payee_org_id AS org_id, COUNT(*) AS jobs, MAX(settled_at) AS last_settled
            FROM guild_work_orders WHERE status = 'settled' AND payee_org_id IS NOT NULL
            GROUP BY payee_org_id
        ), client AS (
            SELECT o2.id AS org_id, COUNT(*) AS orders, MAX(w.settled_at) AS last_settled
            FROM guild_work_orders w
            JOIN organizations o2 ON o2.treasury_agent_did = w.poster_did
            WHERE w.status = 'settled'
            GROUP BY o2.id
        )
        SELECT o.id, o.name, o.slug, o.description, o.settings, o.created_at,
               COALESCE(wk.jobs, 0) AS worker_jobs,
               COALESCE(cl.orders, 0) AS commissioned,
               GREATEST(wk.last_settled, cl.last_settled) AS last_settled
        FROM organizations o
        LEFT JOIN worker wk ON wk.org_id = o.id
        LEFT JOIN client cl ON cl.org_id = o.id
        WHERE o.is_active = true
          AND (COALESCE(wk.jobs, 0) > 0 OR COALESCE(cl.orders, 0) > 0
               OR o.settings->>'public_transparency_opt_in' = 'true'
               OR COALESCE(o.settings->>'intake_agent_did', '') != '')
        ORDER BY (COALESCE(wk.jobs, 0) + COALESCE(cl.orders, 0)) DESC, o.created_at ASC
        LIMIT :n
    """), {"n": limit})).mappings().all()

    firms = [dict(r) for r in rows]
    org_ids = [f["id"] for f in firms]

    # Stars over the WORKER jobs, one batched query for the page.
    stars: Dict[str, Any] = {}
    if org_ids:
        from agentvault_registry.services.track_record import _VSTARS_CTE
        for r in (await db.execute(sa_text(_VSTARS_CTE + """
            SELECT o.payee_org_id AS org_id, AVG(v.stars)::float AS stars_avg, COUNT(v.stars) AS stars_n
            FROM guild_work_orders o JOIN vstars v ON v.order_id = o.id
            WHERE o.status = 'settled' AND o.payee_org_id = ANY(:ids)
            GROUP BY o.payee_org_id
        """), {"ids": org_ids})).mappings().all():
            stars[r["org_id"]] = r

    # Intake doors, re-validated at READ time (§ORGLIFE law): a stored DID whose
    # agent left or was deactivated is a shut door, not a stale promise.
    intake_by_org = {f["id"]: (f.get("settings") or {}).get("intake_agent_did")
                     for f in firms if isinstance(f.get("settings"), dict)}
    valid_intake: Dict[str, str] = {}
    dids = [d for d in intake_by_org.values() if d]
    if dids:
        for a in (await db.execute(sa_text(
            "SELECT did, status, organization_id FROM agents WHERE did = ANY(:d)"
        ), {"d": dids})).mappings().all():
            if str(a["status"]).lower() == "active" and a["organization_id"]:
                valid_intake[f"{a['organization_id']}|{a['did']}"] = a["did"]

    out = []
    for f in firms:
        s = stars.get(f["id"]) or {}
        settings = f.get("settings") if isinstance(f.get("settings"), dict) else {}
        stored_intake = intake_by_org.get(f["id"])
        intake = valid_intake.get(f"{f['id']}|{stored_intake}") if stored_intake else None
        out.append({
            "org_id": f["id"], "name": f["name"], "slug": f["slug"],
            "description": f["description"],
            "verified_jobs": int(f["worker_jobs"]),
            "commissioned": int(f["commissioned"]),
            "stars_avg": (round(float(s["stars_avg"]), 2) if s.get("stars_avg") is not None else None),
            "stars_n": int(s.get("stars_n") or 0),
            "last_settled_at": f["last_settled"].isoformat() if f.get("last_settled") else None,
            "transparency": settings.get("public_transparency_opt_in") is True,
            "intake_agent_did": intake,
            "engage_available": bool(intake),
            "engage_reason": (None if intake else
                              "This firm has not set an intake agent — there is no engage door."),
        })
    return {"firms": out, "total": len(out),
            "ranking": "proof-weighted: settled work (as worker + as client) first"}


@router.get("/public/transparent",
            summary="Organizations that opted into public transparency")
async def list_transparent_organizations(
    limit: int = Query(25, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    """
    Public list of the organizations whose settings opt into public transparency (`public_transparency_opt_in`);
    every other organization is absent by construction.

    \f
    PUBLIC list of opted-in firms for the showcase. Only orgs whose settings
    carry public_transparency_opt_in=true appear — everyone else is invisible
    here by construction. `settings` is plain json (NOT jsonb — §SHOWCASEOPS
    class), so the filter uses -> and a text cast only. The cast keeps the JSON
    form, so it matches the boolean true and not the string "true": the same
    test as org_policy.transparency_public, which each firm's feed asks.
    """
    rows = (await db.execute(sa_text(
        "SELECT o.id, o.name, o.slug, o.description, c.topic, c.last_message_at "
        "FROM organizations o "
        "LEFT JOIN conversations c ON c.kind = 'org' AND c.org_id = o.id "
        "WHERE o.is_active = true "
        "AND (o.settings->'public_transparency_opt_in')::text = 'true' "
        "ORDER BY c.last_message_at DESC NULLS LAST LIMIT :n"), {"n": limit})).fetchall()
    return {"organizations": [
        {"org_id": r[0], "name": r[1], "slug": r[2], "description": r[3],
         "topic": r[4], "last_activity_at": r[5].isoformat() if r[5] else None}
        for r in rows]}


# Export router
__all__ = ['router']
