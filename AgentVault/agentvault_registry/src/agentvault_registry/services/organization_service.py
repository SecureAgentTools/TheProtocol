"""
Organization and Team Service Classes

Provides business logic for managing organizations, teams, and memberships.
"""

import uuid
import secrets
import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import IntegrityError

from agentvault_registry.models import (
    Organization,
    Team,
    OrganizationMember,
    TeamMember,
    OrganizationInvitation,
    Developer
)

# §pass71.8 (2026-05-25) — switched from the legacy `send_email` shim to the
# canonical `send_themed_email` infrastructure (Jinja templates + premailer +
# theme palette, used by 23+ other email types). The previous stub logged the
# invitation token to the server log instead of sending an email — confirmed
# silent failure during the §pass71.8 E2E test (Mailpit had verification mails
# but ZERO invitation mails). Pairs with new templates:
#   templates/email/org_invitation.html.j2
#   templates/email/org_invitation.txt.j2
try:
    from agentvault_registry.email_utils import send_themed_email
    from agentvault_registry.config import settings as _settings
    EMAIL_AVAILABLE = True
except ImportError:
    EMAIL_AVAILABLE = False


# §pass47 O3 — best-effort org event emission. EventStore is the canonical
# audit trail for organizational lifecycle (create / invite / join / remove /
# delete). Emission failures NEVER raise.
async def _emit_org_event(event_type: str, aggregate_id: str, data: Dict[str, Any],
                          idempotency_key: Optional[str] = None) -> None:
    import logging
    _olog = logging.getLogger(__name__)
    try:
        from agentvault_registry.event_emitter import get_event_emitter
        emitter = get_event_emitter()
        await emitter.emit(event_type=event_type, aggregate_id=aggregate_id, data=data,
                           idempotency_key=idempotency_key)  # §BATCH8 item 8
    except Exception as e:  # noqa: BLE001
        _olog.warning(f"[Org-Event] emit {event_type} for {aggregate_id} failed: {e}")
    
async def send_invitation_email(
    email: str,
    token: str,
    organization_name: str,
    inviter_name: str = "A TheProtocol developer",
    role: str = "member",
):
    """Send organization invitation email via the themed-email infrastructure.

    §pass71.8 (2026-05-25) — replaced the previous TODO/log-only stub with a
    real send_themed_email call. The org_invitation.{html,txt}.j2 template pair
    mirrors the beta_invite pattern (token in a styled code block + CTA button).

    The accept URL points at the frontend with the token in the path; the
    frontend invitation-accept route is responsible for POSTing to
    /api/v1/organizations/invitations/{token}/accept on click. If the frontend
    doesn't have a matching route yet, users can copy the token from the email
    and POST manually — the API endpoint is documented in the email body.

    Best-effort: SMTP/render failures are logged but don't abort the invitation
    (the DB row + token are already persisted before this call).
    """
    import logging
    logger = logging.getLogger(__name__)
    if not EMAIL_AVAILABLE:
        logger.warning(
            f"[OrgInvite] EMAIL_AVAILABLE=False — invitation for {email} not sent. Token: {token}"
        )
        return False

    # The link carries a PERSON, so it names the console they use (§FIRSTHOUR, the verify and reset mails): it was
    # BASE_URL + /ui, which on EU is eu.theprotocol.cloud/ui while EU's members sign in on the apex (PUBLIC_UI_URL),
    # so an invited member arrived on a host where they were not signed in (sessions are per host).
    from agentvault_registry.core.public_url import public_ui_url_static
    console = public_ui_url_static()
    if console:
        accept_url = f"{console}/#/organizations/invitations/{token}/accept"
    else:
        # Fallback: emit the bare API URL so the user can curl it if no frontend route exists
        accept_url = f"/api/v1/organizations/invitations/{token}/accept"

    try:
        ok = await send_themed_email(
            subject=f"You've been invited to join {organization_name} on TheProtocol",
            recipients=[email],
            template="org_invitation",
            context={
                "organization_name": organization_name,
                "inviter_name": inviter_name,
                "role": role,
                "accept_url": accept_url,
                "token": token,  # available in template if needed
            },
            theme="neural",
        )
        if not ok:
            logger.warning(f"[OrgInvite] send_themed_email returned False for {email} (org={organization_name})")
        return ok
    except Exception as e:  # noqa: BLE001
        logger.warning(
            f"[OrgInvite] send_themed_email raised for {email} (org={organization_name}): {e}"
        )
        return False


class OrganizationService:
    """Service for managing organizations and their members."""
    
    @staticmethod
    def generate_slug(name: str) -> str:
        """Generate URL-friendly slug from organization name."""
        # Convert to lowercase, replace spaces with hyphens
        slug = re.sub(r'[^\w\s-]', '', name.lower())
        slug = re.sub(r'[-\s]+', '-', slug)
        # Add random suffix to ensure uniqueness
        slug = f"{slug}-{secrets.token_hex(3)}"
        return slug
    
    @staticmethod
    async def create_organization(
        db: AsyncSession,
        name: str,
        owner: Developer,
        description: Optional[str] = None,
        website: Optional[str] = None,
        logo_url: Optional[str] = None,
        settings: Optional[Dict[str, Any]] = None,
        limits: Optional[Dict[str, int]] = None
    ) -> Organization:
        """Create a new organization with the developer as owner."""
        
        # Generate unique slug
        slug = OrganizationService.generate_slug(name)
        
        # Create organization
        org = Organization(
            id=str(uuid.uuid4()),
            name=name,
            slug=slug,
            owner_id=owner.id,
            description=description,
            website=website,
            logo_url=logo_url,
            settings=settings or {},
            limits=limits or {
                "max_agents": 100,
                "max_members": 50,
                "max_teams": 10
            }
        )
        
        db.add(org)
        await db.flush()
        
        # Add owner as organization member
        owner_member = OrganizationMember(
            id=str(uuid.uuid4()),
            organization_id=org.id,
            developer_id=owner.id,
            role="owner",
            invited_by=None  # Self-joined as owner
        )
        
        db.add(owner_member)
        
        # Create default team
        default_team = Team(
            id=str(uuid.uuid4()),
            organization_id=org.id,
            name="Default Team",
            description="Default team for all organization members",
            permissions=["read_agents", "create_agents", "update_agents"]
        )
        
        db.add(default_team)
        await db.flush()
        
        # Add owner to default team as lead
        team_member = TeamMember(
            id=str(uuid.uuid4()),
            team_id=default_team.id,
            developer_id=owner.id,
            role="lead"
        )
        
        db.add(team_member)
        await db.commit()

        # §pass47 O3 — audit lifecycle event.
        await _emit_org_event("OrganizationCreated", org.id, {
            "org_id": org.id,
            "name": org.name,
            "slug": org.slug,
            "owner_id": owner.id,
        })

        return org

    @staticmethod
    async def get_organization(
        db: AsyncSession,
        org_id: str,
        include_members: bool = False,
        include_teams: bool = False
    ) -> Optional[Organization]:
        """Get organization by ID with optional relationships."""
        
        query = select(Organization).where(
            and_(
                Organization.id == org_id,
                Organization.is_active == True
            )
        )
        
        if include_members:
            query = query.options(selectinload(Organization.members))
        if include_teams:
            query = query.options(selectinload(Organization.teams))
        
        result = await db.execute(query)
        return result.scalar_one_or_none()
    
    @staticmethod
    async def get_organization_by_slug(
        db: AsyncSession,
        slug: str
    ) -> Optional[Organization]:
        """Get organization by slug."""
        
        stmt = select(Organization).where(
            and_(
                Organization.slug == slug,
                Organization.is_active == True
            )
        )
        
        result = await db.execute(stmt)
        return result.scalar_one_or_none()
    
    @staticmethod
    async def list_developer_organizations(
        db: AsyncSession,
        developer_id: int,
        include_owned: bool = True,
        include_member: bool = True
    ) -> List[Organization]:
        """List all organizations a developer is part of."""
        
        conditions = []
        
        if include_owned:
            conditions.append(Organization.owner_id == developer_id)
        
        if include_member:
            # Subquery for membership
            member_subquery = select(OrganizationMember.organization_id).where(
                and_(
                    OrganizationMember.developer_id == developer_id,
                    OrganizationMember.is_active == True
                )
            )
            conditions.append(Organization.id.in_(member_subquery))
        
        if not conditions:
            return []
        
        stmt = select(Organization).where(
            and_(
                or_(*conditions),
                Organization.is_active == True
            )
        ).order_by(Organization.created_at.desc())
        
        result = await db.execute(stmt)
        return list(result.scalars().all())
    
    @staticmethod
    async def update_organization(
        db: AsyncSession,
        org_id: str,
        **kwargs
    ) -> Optional[Organization]:
        """Update organization details."""
        
        org = await OrganizationService.get_organization(db, org_id)
        if not org:
            return None
        
        # Update allowed fields
        allowed_fields = ['name', 'description', 'website', 'logo_url', 'settings', 'limits']
        for field, value in kwargs.items():
            if field in allowed_fields and value is not None:
                setattr(org, field, value)
        
        org.updated_at = datetime.now(timezone.utc)
        await db.commit()
        
        return org
    
    @staticmethod
    async def delete_organization(
        db: AsyncSession,
        org_id: str,
        soft_delete: bool = True
    ) -> bool:
        """Delete or deactivate an organization."""
        
        org = await OrganizationService.get_organization(db, org_id)
        if not org:
            return False
        
        if soft_delete:
            org.is_active = False
            org.updated_at = datetime.now(timezone.utc)
            await db.commit()
        else:
            # Hard delete - cascades will handle related records
            await db.delete(org)
            await db.commit()

        # §pass47 O3 — sensitive lifecycle event; persists even if org row
        # is hard-deleted (EventStore is the audit-of-record).
        await _emit_org_event("OrganizationDeleted", org_id, {
            "org_id": org_id,
            "name": org.name,
            "soft_deleted": soft_delete,
        })

        return True
    
    @staticmethod
    async def check_member_permission(
        db: AsyncSession,
        org_id: str,
        developer_id: int,
        required_role: Optional[str] = None
    ) -> bool:
        """Check if a developer has permission in an organization."""
        
        # Check if owner
        org = await OrganizationService.get_organization(db, org_id)
        if not org:
            return False
        
        if org.owner_id == developer_id:
            return True
        
        # Check membership
        stmt = select(OrganizationMember).where(
            and_(
                OrganizationMember.organization_id == org_id,
                OrganizationMember.developer_id == developer_id,
                OrganizationMember.is_active == True
            )
        )
        
        result = await db.execute(stmt)
        member = result.scalar_one_or_none()
        
        if not member:
            return False
        
        # Check role hierarchy if required_role specified
        if required_role:
            role_hierarchy = {
                'guest': 0,
                'member': 1,
                'admin': 2,
                'owner': 3
            }
            
            member_level = role_hierarchy.get(member.role, 0)
            required_level = role_hierarchy.get(required_role, 0)
            
            return member_level >= required_level
        
        return True

    @staticmethod
    async def remove_member(
        db: AsyncSession,
        org_id: str,
        developer_id: int
    ) -> bool:
        """Remove a developer from an organization (hard delete for UniqueConstraint compatibility)."""
        
        # Prevent removing the owner
        org = await OrganizationService.get_organization(db, org_id)
        if org and org.owner_id == developer_id:
            raise ValueError("Cannot remove the organization owner")
        
        stmt = select(OrganizationMember).where(
            and_(
                OrganizationMember.organization_id == org_id,
                OrganizationMember.developer_id == developer_id
            )
        )
        
        result = await db.execute(stmt)
        member = result.scalar_one_or_none()
        
        if not member:
            return False

        # §pass47 O3 — capture before delete (member.role accessed below) and emit
        # after commit so failed commits don't leave a phantom audit row.
        member_role_snapshot = member.role

        # Org-level removal must also clear the member's team rows IN THIS ORG:
        # accept_invitation auto-adds a Default Team row, so a surviving ghost
        # both keeps team-scoped access and 409s any future re-join on
        # uq_team_members(team_id, developer_id). Scoped to this org's teams only.
        org_team_ids = (await db.execute(
            select(Team.id).where(Team.organization_id == org_id)
        )).scalars().all()
        teams_cleared = 0
        if org_team_ids:
            tm_rows = (await db.execute(
                select(TeamMember).where(
                    and_(
                        TeamMember.team_id.in_(org_team_ids),
                        TeamMember.developer_id == developer_id
                    )
                )
            )).scalars().all()
            for tm in tm_rows:
                await db.delete(tm)
                teams_cleared += 1

        await db.delete(member)
        await db.commit()

        # §pass47 O3 — sensitive lifecycle event.
        await _emit_org_event("OrganizationMemberRemoved", org_id, {
            "org_id": org_id,
            "developer_id": developer_id,
            "former_role": member_role_snapshot,
            "team_memberships_cleared": teams_cleared,
        })

        return True

    @staticmethod
    async def update_member_role(
        db: AsyncSession,
        org_id: str,
        developer_id: int,
        new_role: str,
        changed_by: Optional[int] = None
    ) -> Optional["OrganizationMember"]:
        """Change an active member's organization role (admin|member|guest).

        The owner row is immutable here — ownership moves only via an explicit
        transfer, never a role edit — and 'owner' is not an accepted new_role,
        so this path can neither demote the sole owner nor mint a second one.
        """

        if new_role not in ("admin", "member", "guest"):
            raise ValueError("Role must be one of: admin, member, guest")

        org = await OrganizationService.get_organization(db, org_id)
        if org and org.owner_id == developer_id:
            raise ValueError("Cannot change the organization owner's role")

        stmt = select(OrganizationMember).where(
            and_(
                OrganizationMember.organization_id == org_id,
                OrganizationMember.developer_id == developer_id,
                OrganizationMember.is_active == True
            )
        )
        result = await db.execute(stmt)
        member = result.scalar_one_or_none()

        if not member:
            return None

        old_role = member.role
        if old_role != new_role:
            member.role = new_role
            await db.commit()
            await db.refresh(member)

            # Emit AFTER commit so a failed commit leaves no phantom audit row
            # (same doctrine as remove_member above).
            await _emit_org_event("OrganizationMemberRoleChanged", org_id, {
                "org_id": org_id,
                "developer_id": developer_id,
                "old_role": old_role,
                "new_role": new_role,
                "changed_by": changed_by,
            })

        return member

    # ── E1a — ownership transfer (two-party handshake; mig 0149) ─────────────
    #
    # The transfer this file has promised since P0.2 ("ownership moves only via
    # an explicit transfer, never a role edit"). One pending offer per org, held
    # in organizations.pending_owner_id/_expires_at; expiry self-retires at read
    # (the B2 pattern — no sweeper). Mandates do NOT move with ownership: they
    # are developer∘agent instruments, so the new owner underwrites with their
    # own. Org settings, treasury and authority grants are org-level and are
    # untouched by a transfer.

    TRANSFER_TTL_DAYS = 7

    @staticmethod
    async def _clear_pending_transfer(
        db: AsyncSession, org: Organization, event: str, extra: Dict[str, Any]
    ) -> None:
        """Clear the pending offer and record why. Commits (all callers are
        terminal actions on the offer)."""
        to_dev = org.pending_owner_id
        org.pending_owner_id = None
        org.pending_owner_expires_at = None
        org.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await _emit_org_event(event, org.id, {
            "org_id": org.id, "to_developer_id": to_dev, **extra,
        })

    @staticmethod
    async def pending_transfer_state(
        db: AsyncSession, org: Organization
    ) -> Optional[Dict[str, Any]]:
        """The live pending offer, or None. An expired offer is cleared HERE
        (self-retiring at read) so no state ever depends on a sweeper."""
        if not org.pending_owner_id:
            return None
        exp = org.pending_owner_expires_at
        if exp is not None and exp <= datetime.now(timezone.utc):
            await OrganizationService._clear_pending_transfer(
                db, org, "OrganizationOwnershipTransferExpired", {})
            return None
        return {
            "to_developer_id": org.pending_owner_id,
            "expires_at": exp.isoformat() if exp else None,
        }

    @staticmethod
    async def initiate_ownership_transfer(
        db: AsyncSession, org_id: str, to_developer_id: int,
    ) -> Dict[str, Any]:
        """Owner offers the org to an existing ACTIVE admin member.

        Caller (router) has already verified the actor IS the owner. Requiring
        the target to hold 'admin' first is deliberate: accepting ownership is
        accepting liability, and the two-step (promote, then transfer) keeps
        each act explicit and separately audited.
        """
        org = await OrganizationService.get_organization(db, org_id)
        if not org:
            raise ValueError("Organization not found")
        if to_developer_id == org.owner_id:
            raise ValueError("Target already owns this organization")
        if await OrganizationService.pending_transfer_state(db, org) is not None:
            raise ValueError(
                "A transfer offer is already pending: cancel it before making another")

        target = (await db.execute(select(OrganizationMember).where(and_(
            OrganizationMember.organization_id == org_id,
            OrganizationMember.developer_id == to_developer_id,
            OrganizationMember.is_active == True,
        )))).scalar_one_or_none()
        if not target:
            raise ValueError("Target is not an active member of this organization")
        if target.role != "admin":
            raise ValueError(
                "Target must hold the admin role first: promote them, then transfer")

        org.pending_owner_id = to_developer_id
        org.pending_owner_expires_at = datetime.now(timezone.utc) + timedelta(
            days=OrganizationService.TRANSFER_TTL_DAYS)
        org.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await _emit_org_event("OrganizationOwnershipTransferInitiated", org_id, {
            "org_id": org_id, "from_developer_id": org.owner_id,
            "to_developer_id": to_developer_id,
            "expires_at": org.pending_owner_expires_at.isoformat(),
        }, idempotency_key=f"org-owner-xfer-init-{org_id}-{to_developer_id}-{org.pending_owner_expires_at.isoformat()}")
        return {"to_developer_id": to_developer_id,
                "expires_at": org.pending_owner_expires_at.isoformat()}

    @staticmethod
    async def respond_ownership_transfer(
        db: AsyncSession, org_id: str, responder_developer_id: int, accept: bool,
    ) -> Dict[str, Any]:
        """The offered developer accepts or declines. Accept flips ownership in
        ONE transaction: org.owner_id moves, the target's member row becomes
        'owner', the old owner's row becomes 'admin' (never silently dropped —
        losing ownership must not mean losing access)."""
        org = await OrganizationService.get_organization(db, org_id)
        if not org:
            raise ValueError("Organization not found")
        pending = await OrganizationService.pending_transfer_state(db, org)
        if pending is None:
            raise TransferExpiredError("No live transfer offer for this organization")
        if org.pending_owner_id != responder_developer_id:
            raise ValueError("This transfer offer is not addressed to you")

        if not accept:
            await OrganizationService._clear_pending_transfer(
                db, org, "OrganizationOwnershipTransferDeclined",
                {"declined_by": responder_developer_id})
            return {"accepted": False}

        old_owner_id = org.owner_id
        members = (await db.execute(select(OrganizationMember).where(and_(
            OrganizationMember.organization_id == org_id,
            OrganizationMember.developer_id.in_([old_owner_id, responder_developer_id]),
        )))).scalars().all()
        by_dev = {m.developer_id: m for m in members}

        new_row = by_dev.get(responder_developer_id)
        if new_row is None:  # unreachable if initiate validated, but never trust old state
            raise ValueError("Accepting developer has no membership row")
        new_row.role = "owner"
        new_row.is_active = True

        old_row = by_dev.get(old_owner_id)
        if old_row is not None:
            old_row.role = "admin"
            old_row.is_active = True
        else:
            db.add(OrganizationMember(
                id=str(uuid.uuid4()), organization_id=org_id,
                developer_id=old_owner_id, role="admin",
                invited_by=responder_developer_id, is_active=True,
            ))

        org.owner_id = responder_developer_id
        org.pending_owner_id = None
        org.pending_owner_expires_at = None
        org.updated_at = datetime.now(timezone.utc)
        await db.commit()

        await _emit_org_event("OrganizationOwnershipTransferred", org_id, {
            "org_id": org_id, "from_developer_id": old_owner_id,
            "to_developer_id": responder_developer_id,
        }, idempotency_key=f"org-owner-xfer-{org_id}-{responder_developer_id}-{org.updated_at.isoformat()}")
        return {"accepted": True, "owner_id": responder_developer_id,
                "previous_owner_role": "admin"}

    @staticmethod
    async def cancel_ownership_transfer(db: AsyncSession, org_id: str) -> bool:
        """Owner withdraws the pending offer. True if one was cleared."""
        org = await OrganizationService.get_organization(db, org_id)
        if not org or await OrganizationService.pending_transfer_state(db, org) is None:
            return False
        await OrganizationService._clear_pending_transfer(
            db, org, "OrganizationOwnershipTransferCancelled", {})
        return True


class TransferExpiredError(ValueError):
    """No live offer (never existed, expired, or already resolved) — routers map
    this to 410 so the FE can distinguish 'gone' from a validation mistake."""


class TeamNameTaken(ValueError):
    """An ACTIVE team in the organization already carries the name (§MCPTEST30, V0524): the route answers 409."""


async def _claim_team_name(db: AsyncSession, organization_id: str, name: str, exclude_id: Optional[str] = None) -> None:
    """Make `name` free for a new or renamed team in the organization, or raise TeamNameTaken (§MCPTEST30, V0524).

    `teams` carry UNIQUE(organization_id, name) over DELETED teams too (a team is soft-deleted), so the name of a team
    deleted long ago stayed taken while no listed team carried it, and the caller met the index's own words, "A record
    with this value already exists". An active holder refuses the name, in its words. A deleted holder gives it up: it
    keeps its id, its members' history and a name that still says what it was, "<name> (deleted <its id>)"."""
    held = (await db.execute(select(Team).where(and_(Team.organization_id == organization_id, Team.name == name)))).scalars().all()
    if any(t.is_active and t.id != exclude_id for t in held):
        raise TeamNameTaken(f"A team named '{name}' already exists in this organization")
    for t in held:
        if not t.is_active and t.id != exclude_id:
            suffix = f" (deleted {t.id})"
            t.name = t.name[:255 - len(suffix)] + suffix
    if any(not t.is_active for t in held):
        await db.flush()


class TeamService:
    """Service for managing teams within organizations."""
    
    @staticmethod
    async def create_team(
        db: AsyncSession,
        organization_id: str,
        name: str,
        description: Optional[str] = None,
        permissions: Optional[List[str]] = None
    ) -> Team:
        """Create a new team within an organization."""
        
        # Check organization exists and is active
        org = await OrganizationService.get_organization(db, organization_id)
        if not org:
            raise ValueError(f"Organization {organization_id} not found")
        
        # Check team limit
        team_count_stmt = select(func.count(Team.id)).where(
            and_(
                Team.organization_id == organization_id,
                Team.is_active == True
            )
        )
        result = await db.execute(team_count_stmt)
        team_count = result.scalar()
        
        if team_count >= org.limits.get('max_teams', 10):
            raise ValueError(f"Organization has reached maximum team limit")
        
        await _claim_team_name(db, organization_id, name)

        # Create team
        team = Team(
            id=str(uuid.uuid4()),
            organization_id=organization_id,
            name=name,
            description=description,
            permissions=permissions or ["read_agents", "create_agents"]
        )
        
        db.add(team)
        try:
            await db.commit()
        except IntegrityError:   # two creates of one name at once: the index decided, the loser is told so
            await db.rollback()
            raise TeamNameTaken(f"A team named '{name}' already exists in this organization")
        
        return team
    
    @staticmethod
    async def get_team(
        db: AsyncSession,
        team_id: str,
        include_members: bool = False
    ) -> Optional[Team]:
        """Get team by ID."""
        
        query = select(Team).where(
            and_(
                Team.id == team_id,
                Team.is_active == True
            )
        )
        
        if include_members:
            query = query.options(selectinload(Team.members))
        
        result = await db.execute(query)
        return result.scalar_one_or_none()
    
    @staticmethod
    async def list_organization_teams(
        db: AsyncSession,
        organization_id: str
    ) -> List[Team]:
        """List all teams in an organization."""
        
        stmt = select(Team).where(
            and_(
                Team.organization_id == organization_id,
                Team.is_active == True
            )
        ).order_by(Team.created_at.desc())
        
        result = await db.execute(stmt)
        return list(result.scalars().all())
    
    @staticmethod
    async def add_team_member(
        db: AsyncSession,
        team_id: str,
        developer_id: int,
        role: str = "member"
    ) -> TeamMember:
        """Add a developer to a team."""
        
        # Check if already a member
        existing_stmt = select(TeamMember).where(
            and_(
                TeamMember.team_id == team_id,
                TeamMember.developer_id == developer_id
            )
        )
        
        result = await db.execute(existing_stmt)
        existing = result.scalar_one_or_none()
        
        if existing:
            if not existing.is_active:
                # Reactivate membership
                existing.is_active = True
                existing.role = role
                await db.commit()
                return existing
            else:
                raise ValueError("Developer is already a team member")
        
        # Create new membership
        member = TeamMember(
            id=str(uuid.uuid4()),
            team_id=team_id,
            developer_id=developer_id,
            role=role
        )
        
        db.add(member)
        await db.commit()
        
        return member
    
    @staticmethod
    async def remove_team_member(
        db: AsyncSession,
        team_id: str,
        developer_id: int
    ) -> bool:
        """Remove a developer from a team."""
        
        stmt = select(TeamMember).where(
            and_(
                TeamMember.team_id == team_id,
                TeamMember.developer_id == developer_id,
                TeamMember.is_active == True
            )
        )
        
        result = await db.execute(stmt)
        member = result.scalar_one_or_none()
        
        if not member:
            return False
        
        member.is_active = False
        await db.commit()
        
        return True
    
    @staticmethod
    async def update_team(
        db: AsyncSession,
        team_id: str,
        **kwargs
    ) -> Optional[Team]:
        """Update team details."""
        
        team = await TeamService.get_team(db, team_id)
        if not team:
            return None
        
        new_name = kwargs.get('name')
        if new_name is not None and new_name != team.name:
            await _claim_team_name(db, team.organization_id, new_name, exclude_id=team.id)

        # Update allowed fields
        allowed_fields = ['name', 'description', 'permissions']
        for field, value in kwargs.items():
            if field in allowed_fields and value is not None:
                setattr(team, field, value)
        
        team.updated_at = datetime.now(timezone.utc)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            raise TeamNameTaken(f"A team named '{new_name}' already exists in this organization")
        
        return team
    
    @staticmethod
    async def delete_team(
        db: AsyncSession,
        team_id: str,
        soft_delete: bool = True
    ) -> bool:
        """Delete or deactivate a team."""
        
        team = await TeamService.get_team(db, team_id)
        if not team:
            return False
        
        if soft_delete:
            # Soft delete - mark as inactive
            team.is_active = False
            team.updated_at = datetime.now(timezone.utc)
            
            # Also deactivate all team memberships
            stmt = select(TeamMember).where(
                and_(
                    TeamMember.team_id == team_id,
                    TeamMember.is_active == True
                )
            )
            
            result = await db.execute(stmt)
            members = result.scalars().all()
            
            for member in members:
                member.is_active = False
            
            await db.commit()
        else:
            # Hard delete - remove from database
            # First delete all team members
            stmt = select(TeamMember).where(TeamMember.team_id == team_id)
            result = await db.execute(stmt)
            members = result.scalars().all()
            
            for member in members:
                await db.delete(member)
            
            # Then delete the team
            await db.delete(team)
            await db.commit()
        
        return True


class InvitationService:
    """Service for managing organization invitations."""
    
    @staticmethod
    async def create_invitation(
        db: AsyncSession,
        organization_id: str,
        email: str,
        role: str,
        invited_by_id: int
    ) -> Tuple[OrganizationInvitation, bool]:
        """Create an invitation to join an organization; returns it and whether its mail was sent.

        §FESUITE (V0594): the mail's result was discarded, so the route said "Invitation sent" when the send failed or
        no mail service was configured, and the console's toast said the same. And the mail went out inside the open
        transaction, before the commit: a slow mail server held it open, and a commit that failed after a sent mail
        left the person a link to a token that never existed. The invitation is committed first, then mailed.
        """
        
        # Check if user already has pending invitation
        existing_stmt = select(OrganizationInvitation).where(
            and_(
                OrganizationInvitation.organization_id == organization_id,
                OrganizationInvitation.email == email,
                OrganizationInvitation.status == "pending"
            )
        )
        
        result = await db.execute(existing_stmt)
        if result.scalar_one_or_none():
            raise ValueError("User already has a pending invitation")
        
        # Generate unique token
        token = secrets.token_urlsafe(32)
        
        # Create invitation
        invitation = OrganizationInvitation(
            id=str(uuid.uuid4()),
            organization_id=organization_id,
            email=email,
            role=role,
            token=token,
            invited_by=invited_by_id,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7)  # 7 day expiry
        )
        
        db.add(invitation)
        await db.flush()  # Flush to get the ID but don't commit yet
        
        # Get organization name for email
        org_stmt = select(Organization).where(Organization.id == organization_id)
        org_result = await db.execute(org_stmt)
        org = org_result.scalar_one_or_none()
        org_name = org.name if org else "Unknown Organization"

        # §pass71.8 — fetch inviter display name so the email actually attributes
        # the invitation to a human. Falls back to a generic phrase on lookup miss.
        inviter_name = "A TheProtocol developer"
        try:
            inviter_stmt = select(Developer).where(Developer.id == invited_by_id)
            inviter_row = (await db.execute(inviter_stmt)).scalar_one_or_none()
            if inviter_row and getattr(inviter_row, "name", None):
                inviter_name = inviter_row.name
        except Exception:
            pass  # never block invitation on inviter-name lookup

        await db.commit()

        # the mail carries a token that now exists; best-effort, and its result is what the caller is told
        mail_sent = bool(await send_invitation_email(
            email=email,
            token=token,
            organization_name=org_name,
            inviter_name=inviter_name,
            role=role,
        ))

        # §DOCSFIX D6-484 (2026-10-16): the invitee's account on this registry, when there is one, matched on the
        # address without regard to case (as sign-in matches it). The OrganizationMemberInvited reactor tells the
        # invitee by developer id, and the event carried none, so no invitee was ever told. Read after the commit:
        # the invitation stands whatever this read does.
        invitee_developer_id = None
        try:
            invitee_developer_id = (await db.execute(
                select(Developer.id).where(func.lower(Developer.email) == (email or "").strip().lower())
            )).scalars().first()
        except Exception:
            pass  # the event goes out without it; nobody is told, as before

        # §pass47 O3 — audit lifecycle event.
        await _emit_org_event("OrganizationMemberInvited", organization_id, {
            "org_id": organization_id,
            "invitation_id": invitation.id,
            "email": email,
            "role": role,
            "invited_by": invited_by_id,
            "invitee_developer_id": invitee_developer_id,
        })

        return invitation, mail_sent
    
    @staticmethod
    async def accept_invitation(
        db: AsyncSession,
        token: str,
        developer: Developer
    ) -> OrganizationMember:
        """Accept an invitation to join an organization."""
        
        # Find invitation
        stmt = select(OrganizationInvitation).where(
            and_(
                OrganizationInvitation.token == token,
                OrganizationInvitation.status == "pending"
            )
        )
        
        result = await db.execute(stmt)
        invitation = result.scalar_one_or_none()
        
        if not invitation:
            raise ValueError("Invalid or expired invitation")
        
        # Check expiry
        if invitation.expires_at < datetime.now(timezone.utc):
            invitation.status = "expired"
            await db.commit()
            raise ValueError("Invitation has expired")
        
        # Check email matches. §DOCSFIX D6-500 (2026-10-16): without regard to case, as sign-in
        # (crud/developer.get_developer_by_email) and the invitation preview match it.
        if (invitation.email or "").strip().lower() != (developer.email or "").strip().lower():
            raise ValueError("Invitation is for a different email address")

        # Enforce the org's stored max_members cap before creating the membership
        # (same pattern as the max_teams guard; limits may be NULL on old rows).
        org_row = (await db.execute(
            select(Organization).where(Organization.id == invitation.organization_id)
        )).scalar_one_or_none()
        member_count = (await db.execute(
            select(func.count()).select_from(OrganizationMember).where(
                OrganizationMember.organization_id == invitation.organization_id)
        )).scalar() or 0
        max_members = int((((org_row.limits if org_row else None) or {}).get("max_members") or 50))
        if member_count >= max_members:
            raise ValueError(f"Organization member limit reached ({member_count}/{max_members})")

        # Create organization membership
        member = OrganizationMember(
            id=str(uuid.uuid4()),
            organization_id=invitation.organization_id,
            developer_id=developer.id,
            role=invitation.role,
            invited_by=invitation.invited_by
        )
        
        db.add(member)
        
        # Update invitation status
        invitation.status = "accepted"
        invitation.accepted_at = datetime.now(timezone.utc)
        
        # Add to default team
        default_team_stmt = select(Team).where(
            and_(
                Team.organization_id == invitation.organization_id,
                Team.name == "Default Team",
                Team.is_active == True
            )
        )
        
        result = await db.execute(default_team_stmt)
        default_team = result.scalar_one_or_none()

        if default_team:
            # Reactivate-or-insert (mirrors add_team_member): a soft-deleted row
            # from remove_team_member still occupies uq_team_members(team_id,
            # developer_id), so a blind INSERT 409s every re-join. This branch
            # also self-heals ghost rows that predate the fix.
            existing_tm = (await db.execute(
                select(TeamMember).where(
                    and_(
                        TeamMember.team_id == default_team.id,
                        TeamMember.developer_id == developer.id
                    )
                )
            )).scalar_one_or_none()
            if existing_tm:
                existing_tm.is_active = True
                existing_tm.role = "member"
            else:
                team_member = TeamMember(
                    id=str(uuid.uuid4()),
                    team_id=default_team.id,
                    developer_id=developer.id,
                    role="member"
                )
                db.add(team_member)

        await db.commit()

        # §pass47 O3 — audit lifecycle event.
        await _emit_org_event("OrganizationMemberJoined", invitation.organization_id, {
            "org_id": invitation.organization_id,
            "developer_id": developer.id,
            "role": invitation.role,
            "via_invitation": invitation.id,
        })

        return member

    @staticmethod
    async def cancel_invitation(
        db: AsyncSession,
        invitation_id: str
    ) -> bool:
        """Cancel a pending invitation."""
        
        stmt = select(OrganizationInvitation).where(
            and_(
                OrganizationInvitation.id == invitation_id,
                OrganizationInvitation.status == "pending"
            )
        )
        
        result = await db.execute(stmt)
        invitation = result.scalar_one_or_none()
        
        if not invitation:
            return False
        
        invitation.status = "cancelled"
        await db.commit()
        
        return True
    
    @staticmethod
    async def list_organization_invitations(
        db: AsyncSession,
        organization_id: str,
        status: Optional[str] = None
    ) -> List[OrganizationInvitation]:
        """List invitations for an organization."""
        
        conditions = [OrganizationInvitation.organization_id == organization_id]
        
        if status:
            conditions.append(OrganizationInvitation.status == status)
        
        stmt = select(OrganizationInvitation).where(
            and_(*conditions)
        ).order_by(OrganizationInvitation.created_at.desc())
        
        result = await db.execute(stmt)
        return list(result.scalars().all())


# Export services
__all__ = ['OrganizationService', 'TeamService', 'InvitationService']
