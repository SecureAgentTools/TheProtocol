"""CRUD operations for BootstrapToken model."""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
from sqlalchemy import select, and_, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import BootstrapToken
from ..config import settings


def _hash_token(token_value: str) -> str:
    """SHA-256 hash of a bootstrap token value (P23-001 — Issue 1)."""
    return hashlib.sha256(token_value.encode("utf-8")).hexdigest()


def _stored_marker(token_hash: str) -> str:
    """D6-283: what the legacy `token_value` column (NOT NULL, UNIQUE) holds for a token: a marker derived from its
    hash, never the token. The token itself exists only in the response that hands it out; the row keeps its hash."""
    return f"sha256:{token_hash}"


def _same_hash(row: Optional[BootstrapToken], incoming_hash: str) -> bool:
    """The row's stored hash equals the presented token's, compared in constant time."""
    stored = getattr(row, "token_value_hash", None) if row is not None else None
    return bool(stored) and secrets.compare_digest(str(stored), incoming_hash)


async def create_bootstrap_token(
    db: AsyncSession,
    creator_developer_id: int,
    agent_type_hint: Optional[str] = None,
    requested_by: Optional[str] = None,
    token_lifetime_seconds: int = 300
) -> Tuple[BootstrapToken, str]:
    """
    Create a new bootstrap token for agent onboarding.

    D6-283: returns ``(row, plain_token)``. The row stores only the token's SHA-256 hash (and a marker derived from
    it in the legacy column); the plain token is returned to the caller once and kept nowhere.

    Args:
        db: Database session
        creator_developer_id: ID of the developer creating the token
        agent_type_hint: Optional hint about the type of agent being created
        requested_by: Optional identifier for the entity making the request
        token_lifetime_seconds: Token lifetime in seconds (default: 300 = 5 minutes)

    Returns:
        (the created BootstrapToken row, the plain token to hand out once)
    """
    # Generate a secure random token
    # Format: bst_<random_hex>_<additional_random>
    token_value = f"bst_{secrets.token_hex(8)}_{secrets.token_hex(16)}"

    # Calculate expiration time
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=token_lifetime_seconds)

    # D6-283: only the hash is stored. P23-001 kept the plaintext "for one cycle" beside it and that cycle never
    # ended; the legacy column now holds a marker derived from the hash (it cannot be NULL without a migration).
    token_hash = _hash_token(token_value)
    bootstrap_token = BootstrapToken(
        token_value=_stored_marker(token_hash),
        token_value_hash=token_hash,
        creator_developer_id=creator_developer_id,
        agent_type_hint=agent_type_hint,
        requested_by=requested_by,
        expires_at=expires_at,
        is_used=False  # Explicitly set to False for new tokens
    )

    db.add(bootstrap_token)
    await db.commit()
    await db.refresh(bootstrap_token)

    return bootstrap_token, token_value


async def get_active_bootstrap_token_by_value(
    db: AsyncSession,
    token_value: str
) -> Optional[BootstrapToken]:
    """
    Retrieve an active (unexpired and unused) bootstrap token by its value.

    D6-283: the lookup is by the token's SHA-256 hash only, confirmed in constant time. The plaintext fallback for
    tokens issued before the hash column (P23-001, 2026-04-30) is gone: those lived five minutes.

    Args:
        db: Database session
        token_value: The token value to look up

    Returns:
        BootstrapToken if found and active, None otherwise
    """
    incoming_hash = _hash_token(token_value)
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(BootstrapToken).where(
            and_(
                BootstrapToken.token_value_hash == incoming_hash,
                BootstrapToken.used_at.is_(None),
                BootstrapToken.is_used == False,
                BootstrapToken.expires_at > now,
            )
        )
    )
    token = result.scalar_one_or_none()
    return token if _same_hash(token, incoming_hash) else None


async def get_bootstrap_token_by_value(
    db: AsyncSession,
    token_value: str
) -> Optional[BootstrapToken]:
    """D6-283: the bootstrap token this value names, in any state (used, expired), by its hash; None if unknown.

    create_agent asks it to tell a used token (409) from an unknown or expired one (401)."""
    incoming_hash = _hash_token(token_value)
    result = await db.execute(
        select(BootstrapToken).where(BootstrapToken.token_value_hash == incoming_hash)
    )
    token = result.scalar_one_or_none()
    return token if _same_hash(token, incoming_hash) else None


async def mark_bootstrap_token_as_used(
    db: AsyncSession,
    token_id: int,
    agent_did: str,
    agent_id: Optional[int] = None
) -> bool:
    """
    Mark a bootstrap token as used by recording when and by whom.
    
    Args:
        db: Database session
        token_id: ID of the token to mark as used
        agent_did: DID of the agent that used the token
        agent_id: Optional ID of the created agent
    
    Returns:
        True if token was successfully marked as used, False otherwise
    """
    values_to_update = {
        "used_at": datetime.now(timezone.utc),
        "used_by_agent_did": agent_did,
        "is_used": True  # Mark the token as used
    }
    
    # Note: agent_id is passed but not used since the model doesn't have this field
    # We only track the DID of the agent that used the token
    
    result = await db.execute(
        update(BootstrapToken)
        .where(
            and_(
                BootstrapToken.id == token_id,
                BootstrapToken.used_at.is_(None),  # Only update if not already used
                BootstrapToken.is_used == False  # Also check is_used flag
            )
        )
        .values(**values_to_update)
    )
    
    await db.commit()
    
    # Return True if a row was updated
    return result.rowcount > 0
