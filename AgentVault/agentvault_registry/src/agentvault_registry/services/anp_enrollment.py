"""
ANP Foreign Agent Auto-Enrollment Service.

When an external agent (e.g., did:wba:beeai.org:agent-42) authenticates via
DIDWba and does not yet exist in this registry, this service auto-enrolls them:

  1. Creates an Agent record (did, generated client_id, hashed dummy secret)
  2. Creates a minimal AgentCard with name/description derived from the DID
  3. Creates a TEG economic profile so the agent can hold tokens
  4. Emits AgentAutoEnrolled event to the Event Store (fire-and-forget)

Foreign agents authenticate exclusively via DIDWba — they never receive a
client_secret (it is generated but never disclosed).
"""

import asyncio
import logging
import secrets
import uuid
from typing import Optional, Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..models import Agent, AgentCard
from ..security import hash_password
from ..es_ssl_helper import get_httpx_verify
from ..event_emitter import get_event_emitter

logger = logging.getLogger(__name__)


def _derive_name_from_did(did: str) -> str:
    """
    Derive a human-readable name from a DID.

    Examples:
        did:wba:beeai.org:agent-42  → "External Agent (beeai.org:agent-42)"
        did:wba:example.com:agents:bot-1 → "External Agent (example.com:agents:bot-1)"
        did:key:z6Mk...             → "External Agent (z6Mk...)"
    """
    # Strip the "did:<method>:" prefix to get the identifier portion
    parts = did.split(":", 2)  # ["did", "method", "rest"]
    if len(parts) >= 3:
        identifier = parts[2]
    else:
        identifier = did
    return f"External Agent ({identifier})"


def _derive_url_from_did(did: str) -> Optional[str]:
    """
    Attempt to derive a URL from a did:wba DID.

    did:wba:example.com:agent-42 → https://example.com
    Returns None for non-web DIDs.
    """
    if not did.startswith("did:wba:"):
        return None
    rest = did[len("did:wba:"):]
    # First segment (before any colon) is the domain
    domain = rest.split(":")[0] if ":" in rest else rest
    if "." in domain:
        return f"https://{domain}"
    return None


async def auto_enroll_foreign_agent(
    db: AsyncSession,
    did: str,
    public_key_jwk: Optional[Dict[str, Any]] = None,
    name: Optional[str] = None,
    description: Optional[str] = None,
    capabilities: Optional[list] = None,
) -> Agent:
    """
    Auto-enroll a foreign agent identified by DID.

    This is a simplified onboarding path — no bootstrap token, no developer
    auth required. The agent is assigned to developer_id=1 (Commander /
    system account) and gets a generated client_id with a hashed dummy
    secret (they will never use client credentials — they auth via DIDWba).

    Args:
        db: Async database session
        did: The agent's DID (e.g. did:wba:beeai.org:agent-42)
        public_key_jwk: Optional Ed25519 public key in JWK format
        name: Optional human-friendly name (defaults to DID-derived name)
        description: Optional description
        capabilities: Optional list of capabilities for the agent card

    Returns:
        The created Agent ORM instance.

    Raises:
        ValueError: If an agent with this DID already exists.
    """
    # Guard: check for existing agent
    existing = await db.execute(select(Agent).where(Agent.did == did))
    if existing.scalar_one_or_none() is not None:
        raise ValueError(f"Agent with DID {did} already exists")

    # Generate credentials (secret is never revealed to the foreign agent)
    client_id = f"agent-{secrets.token_hex(8)}"
    client_secret = f"tp_secret_{secrets.token_hex(32)}"
    hashed_secret = hash_password(client_secret)

    # Derive defaults
    agent_name = name or _derive_name_from_did(did)
    agent_description = description or "Auto-enrolled via ANP DIDWba authentication"
    agent_url = _derive_url_from_did(did)

    # 1. Create Agent record
    agent = Agent(
        did=did,
        client_id=client_id,
        hashed_client_secret=hashed_secret,
        creator_developer_id=1,  # Commander — system-enrolled
        public_key_jwk=public_key_jwk,
        status="active",
    )
    db.add(agent)
    await db.flush()  # Get agent.id without committing yet

    # 2. Create minimal AgentCard
    card_data: Dict[str, Any] = {
        "name": agent_name,
        "description": agent_description,
        "did": did,
        "capabilities": capabilities or [],
        "protocol": "anp",
        "version": "1.0",
        "auto_enrolled": True,
    }
    if agent_url:
        card_data["url"] = agent_url

    agent_card = AgentCard(
        id=uuid.uuid4(),
        developer_id=1,  # Commander — system-enrolled
        agent_did=did,
        card_data=card_data,
        name=agent_name,
        description=agent_description,
        is_active=True,
    )
    db.add(agent_card)

    # Commit both together
    await db.commit()
    await db.refresh(agent)
    await db.refresh(agent_card)

    logger.info(
        f"ANP auto-enrolled foreign agent: did={did}, "
        f"client_id={client_id}, card_id={agent_card.id}"
    )

    # 3. Create TEG profile (fire-and-forget, same as normal onboarding)
    asyncio.create_task(_create_teg_profile(did))

    # 4. Emit AgentAutoEnrolled event (fire-and-forget)
    event_emitter = get_event_emitter()
    asyncio.create_task(
        event_emitter.emit(
            event_type="AgentAutoEnrolled",
            aggregate_id=did,
            data={
                "agent_did": did,
                "source": "anp_didwba",
                "auto_enrolled": True,
                "agent_card_id": str(agent_card.id),
                "agent_card_name": agent_name,
                "has_public_key": public_key_jwk is not None,
            },
            idempotency_key=f"agent_auto_enrolled:{did}",
        )
    )

    return agent


async def _create_teg_profile(agent_did: str) -> None:
    """
    Create a TEG economic profile for the auto-enrolled agent.
    Fire-and-forget — failures are logged but don't block enrollment.
    """
    try:
        import httpx
        from ..config import settings

        teg_api_base_url = getattr(
            settings, "TEG_API_BASE_URL", "http://teg-layer:8080"
        )
        teg_admin_api_key = settings.TEG_ADMIN_API_KEY

        async with httpx.AsyncClient(verify=get_httpx_verify()) as client:
            response = await client.post(
                f"{teg_api_base_url}/api/v1/internal/create-agent-profile",
                json={"agent_did": agent_did},
                headers={"Authorization": f"Bearer {teg_admin_api_key}"},
                timeout=10.0,
            )
            if response.status_code in (200, 201):
                logger.info(
                    f"TEG profile created for auto-enrolled agent: {agent_did}"
                )
            else:
                logger.warning(
                    f"TEG profile creation returned {response.status_code} "
                    f"for {agent_did}: {response.text[:200]}"
                )
    except Exception as exc:
        logger.error(
            f"Failed to create TEG profile for auto-enrolled agent "
            f"{agent_did}: {exc}"
        )
