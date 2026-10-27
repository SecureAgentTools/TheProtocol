"""
ANP (Agent Network Protocol) discovery endpoints.

Serves W3C DID Documents and ANP Agent Descriptions for web-based
agent discovery.  Most endpoints are public (no auth required).

The POST /anp/register endpoint uses DIDWba authentication for
foreign agent auto-enrollment.
"""
import logging
from typing import Dict, Any, Optional, List, Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import or_, select, func, String

from ..database import get_db
from ..models import Agent, AgentCard
from ..middleware.anp_auth import get_didwba_identity, DIDWbaIdentity
from ..services.anp_enrollment import auto_enroll_foreign_agent

logger = logging.getLogger(__name__)

# Router for agent-specific ANP endpoints (mounted under /api/v1)
router = APIRouter()  # §pass56 PR-5: tags= via main.py "ANP Discovery"

# Router for .well-known endpoints (mounted at root, no /api/v1 prefix)
well_known_router = APIRouter()  # §pass56 PR-5: tags= via main.py "ANP Discovery"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_agent_and_card(
    agent_did: str, db: AsyncSession
) -> tuple[Agent, Optional[AgentCard]]:
    """Fetch an agent by DID and its associated card.  Raises 404 if not found."""
    stmt = select(Agent).where(Agent.did == agent_did)
    result = await db.execute(stmt)
    agent = result.scalar_one_or_none()

    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent with DID {agent_did} not found",
        )

    card_stmt = select(AgentCard).where(AgentCard.agent_did == agent_did)
    card_result = await db.execute(card_stmt)
    agent_card = card_result.scalar_one_or_none()

    # Fallback: try matching via card_data->'did' (legacy cards without agent_did column)
    if agent_card is None:
        card_stmt_legacy = select(AgentCard).where(
            func.cast(AgentCard.card_data["did"], String) == agent_did
        )
        card_result_legacy = await db.execute(card_stmt_legacy)
        agent_card = card_result_legacy.scalar_one_or_none()

    return agent, agent_card


def _build_did_document(agent: Agent, card: Optional[AgentCard]) -> Dict[str, Any]:
    """Build a W3C DID Core compliant DID Document for the agent."""
    did = agent.did
    card_data = (card.card_data if card else None) or {}

    doc: Dict[str, Any] = {
        "@context": [
            "https://www.w3.org/ns/did/v1",
            "https://w3id.org/security/suites/ed25519-2020/v1",
        ],
        "id": did,
    }

    # --- verificationMethod ---
    verification_methods: List[Dict[str, Any]] = []
    if agent.public_key_jwk:
        vm = {
            "id": f"{did}#key-1",
            "type": "JsonWebKey2020",
            "controller": did,
            "publicKeyJwk": agent.public_key_jwk,
        }
        verification_methods.append(vm)
    doc["verificationMethod"] = verification_methods

    # --- authentication ---
    doc["authentication"] = [f"{did}#key-1"] if verification_methods else []

    # --- service ---
    services: List[Dict[str, Any]] = []
    # Primary endpoint from agent card URL
    agent_url = card_data.get("url") or card_data.get("service_endpoint")
    if agent_url:
        services.append({
            "id": f"{did}#messaging",
            "type": "AgentService",
            "serviceEndpoint": agent_url,
        })

    # Additional service endpoints from card_data
    extra_endpoints = card_data.get("service_endpoints", [])
    if isinstance(extra_endpoints, list):
        for i, ep in enumerate(extra_endpoints):
            if isinstance(ep, dict):
                services.append({
                    "id": f"{did}#service-{i}",
                    "type": ep.get("type", "AgentService"),
                    "serviceEndpoint": ep.get("url") or ep.get("serviceEndpoint", ""),
                })
            elif isinstance(ep, str):
                services.append({
                    "id": f"{did}#service-{i}",
                    "type": "AgentService",
                    "serviceEndpoint": ep,
                })

    doc["service"] = services

    return doc


def _build_agent_description(agent: Agent, card: Optional[AgentCard]) -> Dict[str, Any]:
    """Build an ANP-compatible Agent Description."""
    card_data = (card.card_data if card else None) or {}

    # Collect endpoints
    endpoints: List[str] = []
    primary_url = card_data.get("url") or card_data.get("service_endpoint")
    if primary_url:
        endpoints.append(primary_url)
    extra_endpoints = card_data.get("service_endpoints", [])
    if isinstance(extra_endpoints, list):
        for ep in extra_endpoints:
            if isinstance(ep, dict):
                ep_url = ep.get("url") or ep.get("serviceEndpoint")
                if ep_url:
                    endpoints.append(ep_url)
            elif isinstance(ep, str):
                endpoints.append(ep)

    return {
        "did": agent.did,
        "name": card.name if card else f"Agent {agent.did}",
        "description": card.description if card else None,
        "capabilities": card_data.get("capabilities", []),
        "protocol": "a2a",
        "version": "1.0",
        "endpoints": endpoints,
        "status": agent.status,
        "reputation_score": agent.reputation_score,
        "created_at": agent.created_at.isoformat() if agent.created_at else None,
    }


# ---------------------------------------------------------------------------
# Agent-specific endpoints (mounted at /api/v1 prefix)
# ---------------------------------------------------------------------------

@router.get(
    "/agents/{agent_did}/did.json",
    summary="W3C DID Document",
    response_description="A W3C DID Core compliant document for the agent",
)
async def get_did_document(
    agent_did: str,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
) -> Dict[str, Any]:
    """
    Return a W3C DID Core compliant DID Document for the given agent.

    Public endpoint -- no authentication required.
    """
    agent, card = await _get_agent_and_card(agent_did, db)
    return _build_did_document(agent, card)


@router.get(
    "/agents/{agent_did}/ad.json",
    summary="ANP Agent Description",
    response_description="ANP-compatible agent description",
)
async def get_agent_description(
    agent_did: str,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
) -> Dict[str, Any]:
    """
    Return an ANP-compatible Agent Description for the given agent.

    Public endpoint -- no authentication required.
    """
    agent, card = await _get_agent_and_card(agent_did, db)
    return _build_agent_description(agent, card)


# ---------------------------------------------------------------------------
# .well-known endpoint (mounted at root -- no /api/v1 prefix)
# ---------------------------------------------------------------------------

@well_known_router.get(
    "/.well-known/agent-descriptions",
    summary="ANP Agent Discovery",
    response_description="Paginated list of active agent descriptions",
)
async def list_agent_descriptions(
    limit: int = Query(20, ge=1, le=100, description="Max results per page"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    capability: Optional[str] = Query(None, description="Filter by capability"),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
) -> Dict[str, Any]:
    """
    Return a paginated, JSON-LD style listing of all active agent descriptions.

    Public endpoint -- no authentication required.
    Supports optional filtering by capability keyword.
    """
    # Base query: active agents with optional card join
    stmt = (
        select(Agent, AgentCard)
        .join(
            AgentCard,
            AgentCard.agent_did == Agent.did,
            isouter=True,
        )
        .where(Agent.status == "active")
        .where(or_(AgentCard.id.is_(None), AgentCard.unlisted.is_(False)))   # §DARKSYNC: dark agents are not described
    )

    # Optional capability filter (search in card_data JSON)
    if capability:
        from agentvault_registry.input_validators import escape_like
        escaped_cap = escape_like(capability)
        stmt = stmt.where(
            func.cast(AgentCard.card_data, String).ilike(f"%{escaped_cap}%")
        )

    # Count before pagination
    count_stmt = (
        select(func.count())
        .select_from(Agent)
        .join(
            AgentCard,
            AgentCard.agent_did == Agent.did,
            isouter=True,
        )
        .where(Agent.status == "active")
        .where(or_(AgentCard.id.is_(None), AgentCard.unlisted.is_(False)))   # §DARKSYNC
    )
    if capability:
        from agentvault_registry.input_validators import escape_like as _el
        escaped_cap2 = _el(capability)
        count_stmt = count_stmt.where(
            func.cast(AgentCard.card_data, String).ilike(f"%{escaped_cap2}%")
        )
    total = (await db.execute(count_stmt)).scalar() or 0

    # Paginate
    stmt = stmt.order_by(Agent.created_at.desc()).limit(limit).offset(offset)

    result = await db.execute(stmt)
    rows = result.all()

    agents = [_build_agent_description(agent, card) for agent, card in rows]

    return {
        "@context": "https://theprotocol.cloud/anp/v1",
        "agents": agents,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


# ---------------------------------------------------------------------------
# ANP Registration Models
# ---------------------------------------------------------------------------

class ANPRegisterRequest(BaseModel):
    """Optional body for the ANP register endpoint."""
    name: Optional[str] = Field(None, description="Human-friendly agent name")
    description: Optional[str] = Field(None, description="Agent description")
    capabilities: Optional[List[str]] = Field(
        None, description="List of agent capabilities"
    )


class ANPRegisterResponse(BaseModel):
    """Response from ANP agent registration."""
    agent_did: str = Field(..., description="The agent's DID")
    status: str = Field(..., description="Agent status (active, existing)")
    name: str = Field(..., description="Agent display name")
    is_new: bool = Field(..., description="True if agent was just auto-enrolled")
    message: str = Field(..., description="Human-readable status message")


# ---------------------------------------------------------------------------
# ANP Registration endpoint (mounted at /api/v1 prefix via router)
# ---------------------------------------------------------------------------

@router.post(
    "/anp/register",
    response_model=ANPRegisterResponse,
    summary="ANP Foreign Agent Registration",
    response_description="Agent info (newly enrolled or existing)",
    status_code=status.HTTP_200_OK,
)
async def anp_register(
    anp_identity: Annotated[
        Optional[DIDWbaIdentity], Depends(get_didwba_identity)
    ] = None,
    body: Optional[ANPRegisterRequest] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
) -> ANPRegisterResponse:
    """
    Register or retrieve a foreign agent via ANP DIDWba authentication.

    **Authentication**: Requires `Authorization: DIDWba` header.

    If the agent identified by the DID does not yet exist in this registry,
    it is auto-enrolled with a minimal profile. If the agent already exists,
    its current info is returned.

    The optional JSON body allows the caller to provide a name, description,
    and capabilities for the new agent card. If omitted, defaults are
    derived from the DID.
    """
    # Require DIDWba header
    if anp_identity is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="DIDWba Authorization header required for ANP registration",
            headers={"WWW-Authenticate": "DIDWba"},
        )

    did = anp_identity.did

    # Agent already exists — return current info
    if not anp_identity.is_new and anp_identity.agent is not None:
        agent = anp_identity.agent
        # Fetch agent card for the name
        card_result = await db.execute(
            select(AgentCard).where(AgentCard.agent_did == agent.did)
        )
        card = card_result.scalar_one_or_none()
        agent_name = card.name if card else f"Agent {agent.did}"

        return ANPRegisterResponse(
            agent_did=agent.did,
            status=agent.status,
            name=agent_name,
            is_new=False,
            message="Agent already registered in this registry",
        )

    # Auto-enroll the foreign agent
    try:
        agent = await auto_enroll_foreign_agent(
            db=db,
            did=did,
            public_key_jwk=anp_identity.public_key_jwk,
            name=body.name if body else None,
            description=body.description if body else None,
            capabilities=body.capabilities if body else None,
        )
    except ValueError as exc:
        # Race condition: agent was created between the DIDWba lookup and now
        logger.info(f"ANP register race condition for {did}: {exc}")
        existing = await db.execute(select(Agent).where(Agent.did == did))
        agent = existing.scalar_one_or_none()
        if agent is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Auto-enrollment failed: {exc}",
            )
        return ANPRegisterResponse(
            agent_did=agent.did,
            status=agent.status,
            name=f"Agent {agent.did}",
            is_new=False,
            message="Agent already registered (concurrent enrollment)",
        )

    # Derive name for response
    agent_name = body.name if (body and body.name) else f"External Agent ({did.split(':', 2)[-1]})"

    return ANPRegisterResponse(
        agent_did=agent.did,
        status="active",
        name=agent_name,
        is_new=True,
        message="Agent auto-enrolled via ANP DIDWba authentication",
    )
