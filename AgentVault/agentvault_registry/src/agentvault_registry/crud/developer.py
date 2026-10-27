# --- START OF FILE: agentvault_registry/src/agentvault_registry/crud/developer.py ---
import logging
import datetime
import uuid
from typing import Optional, List, Dict, Any, Union
import re

from sqlalchemy import select, update, func # Added func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import IntegrityError

from agentvault_registry import models, schemas, security
# --- ADDED: Import timedelta from datetime ---
from datetime import timedelta, timezone
# --- END ADDED ---


logger = logging.getLogger(__name__)

# Define constants
API_KEY_PREFIX = "avreg_"

async def get_developer_by_id(db: AsyncSession, developer_id: int) -> Optional[models.Developer]:
    """Get a developer by ID, with eager loading of agent cards.

    NOTE: swallows DB errors to None for backwards-compat with non-auth callers.
    For the AUTH path use get_developer_by_id_strict() — a transient DB error here
    returning None is indistinguishable from a genuinely-absent developer, which
    the auth layer turns into a spurious 401 → forced FE logout (fixed 2026-07-05).
    """
    try:
        # Use select() with options for async session
        stmt = (
            select(models.Developer)
            .where(models.Developer.id == developer_id)
            .options(
                selectinload(models.Developer.agent_cards),
                selectinload(models.Developer.api_keys)
            )
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()
    except Exception as e:
        logger.error(f"Error fetching developer ID {developer_id}: {e}", exc_info=True)
        return None


async def get_developer_by_id_strict(db: AsyncSession, developer_id: int) -> Optional[models.Developer]:
    """Auth-path developer lookup that RAISES on DB error instead of swallowing to
    None. A None result therefore unambiguously means 'developer does not exist'
    (→ legitimate 401); an infra/session fault propagates so the caller can map it
    to a 503 (retryable) rather than a spurious 401 that forces the FE to log out.

    §MCPTEST30 (V0553): the developer's own row and nothing it owns. It eager-loaded every agent card (card_data
    included) and every API key the developer holds, on EVERY authenticated request, so a request cost grew with the
    account: the sandbox frames' admin owns 6,712 cards (8.4 MB of card JSON) and 533 keys, and its /developers/me took
    0.6-1.8 s against 12 ms for an anonymous read (measured on sbx-alpha and sbx-beta, 2026-10-02); an MCP call paid it
    twice (the bridge's lookup and the route's). Nothing on the request path reads either collection (the one reader,
    the admin developer detail, loads its own developer with them); a route that needs them loads them itself.
    """
    result = await db.execute(select(models.Developer).where(models.Developer.id == developer_id))
    return result.scalar_one_or_none()


async def get_developer_by_id_lean(db: AsyncSession, developer_id: int) -> Optional[models.Developer]:
    """get_developer_by_id's contract (a DB error is logged and reads None) without its eager loads: for the request-path
    lookups that read only the developer's own columns (get_current_developer_optional, get_current_developer_unified).
    See get_developer_by_id_strict for the measurement (§MCPTEST30, V0553)."""
    try:
        result = await db.execute(select(models.Developer).where(models.Developer.id == developer_id))
        return result.scalar_one_or_none()
    except Exception as e:
        logger.error(f"Error fetching developer ID {developer_id}: {e}", exc_info=True)
        return None

async def get_developer_by_email(db: AsyncSession, email: str) -> Optional[models.Developer]:
    """Get a developer by email address."""
    try:
        stmt = select(models.Developer).where(func.lower(models.Developer.email) == email.lower()) # Case-insensitive lookup
        result = await db.execute(stmt)
        return result.scalar_one_or_none()
    except Exception as e:
        logger.error(f"Error fetching developer by email '{email}': {e}", exc_info=True)
        return None

async def get_developer_by_name(db: AsyncSession, name: str) -> Optional[models.Developer]:
    """Get a developer by name (case-insensitive). Used for pre-flight uniqueness check."""
    try:
        stmt = select(models.Developer).where(func.lower(models.Developer.name) == name.lower())
        result = await db.execute(stmt)
        return result.scalar_one_or_none()
    except Exception as e:
        logger.error(f"Error fetching developer by name '{name}': {e}", exc_info=True)
        return None

async def create_developer_with_hashed_details(
    db: AsyncSession, developer_data: models.Developer
) -> models.Developer:
    """
    Create a new developer record, directly taking a Developer model.
    Expects password to already be hashed.
    """
    try:
        db.add(developer_data)
        await db.commit()
        await db.refresh(developer_data)
        logger.info(f"Created new developer: {developer_data.email}")
        return developer_data
    except IntegrityError as e:
        await db.rollback()
        logger.error(f"Database constraint violated creating developer: {e}", exc_info=True)
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error creating developer: {e}", exc_info=True)
        raise

async def create_developer(db: AsyncSession, developer: schemas.DeveloperCreate) -> models.Developer:
    """
    Create a new developer record, hashing the provided password.
    """
    hashed_password = security.hash_password(developer.password.get_secret_value()) # Use get_secret_value()

    # Generate recovery keys and store a hash for EACH (§FESUITE: only the first was stored, so the person's second
    # and third keys never worked; security.hash_recovery_keys keeps one hash per key in the same column)
    recovery_keys = security.generate_recovery_keys()
    hashed_recovery_key = security.hash_recovery_keys(recovery_keys)

    # Generate a verification token
    verification_token = security.generate_verification_token()
    # --- CORRECTED: Use settings for expiry ---
    from agentvault_registry.config import settings # Import settings locally
    token_expiry = datetime.datetime.now(timezone.utc) + timedelta(hours=settings.EMAIL_VERIFICATION_TOKEN_EXPIRE_HOURS)
    # --- END CORRECTION ---


    # ToS consent (0120): stamp the version WE serve + now, only when the caller accepted — the
    # server owns the version string so the record cannot be spoofed by the client.
    tos_version = None
    tos_at = None
    if getattr(developer, "tos_accepted", False):
        tos_version = settings.TOS_VERSION
        tos_at = datetime.datetime.now(timezone.utc)

    # Create the Developer model instance
    db_developer = models.Developer(
        email=developer.email,
        name=developer.name,
        hashed_password=hashed_password,
        is_verified=False,
        email_verification_token=verification_token,
        verification_token_expires=token_expiry,
        hashed_recovery_key=hashed_recovery_key, # Store the hash
        tos_accepted_version=tos_version,
        tos_accepted_at=tos_at,
        created_at=datetime.datetime.now(timezone.utc)
    )

    created_dev = await create_developer_with_hashed_details(db, db_developer)
    # Attach recovery keys temporarily for the response (they are not stored in DB)
    setattr(created_dev, '_plain_recovery_keys', recovery_keys)
    return created_dev


async def get_developer_by_verification_token(db: AsyncSession, token: str) -> Optional[models.Developer]:
    """Get a developer by email verification token."""
    try:
        stmt = select(models.Developer).where(models.Developer.email_verification_token == token)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()
    except Exception as e:
        logger.error(f"Error fetching developer by verification token: {e}", exc_info=True)
        return None

async def verify_developer_email(db: AsyncSession, developer: models.Developer) -> bool:
    """Mark a developer's email as verified and clear the verification token."""
    try:
        developer.is_verified = True
        developer.email_verification_token = None
        developer.verification_token_expires = None # Clear expiry too
        # developer.verified_at = datetime.datetime.now(datetime.timezone.utc) # Add this field to model if desired

        db.add(developer)
        await db.commit()
        await db.refresh(developer)
        logger.info(f"Developer email verified: {developer.email}")
        return True
    except Exception as e:
        await db.rollback()
        logger.error(f"Error verifying developer email: {e}", exc_info=True)
        return False

async def create_api_key(
    db: AsyncSession, developer_id: int, prefix: str, hashed_key: str, description: Optional[str], # Made description optional
    key_sha256: Optional[str] = None,
    scopes: Optional[list] = None,
    expires_at: Optional[datetime.datetime] = None,
) -> Optional[models.DeveloperApiKey]:
    """Create a new API key for a developer.

    AL-4 (2026-07-24): scopes default to ['*'] (full developer authority, the
    grandfather default). expires_at is optional forced-rotation expiry (NULL =
    never); the mint endpoint sets it from API_KEY_DEFAULT_TTL_DAYS.
    """
    try:
        api_key = models.DeveloperApiKey(
            developer_id=developer_id,
            key_prefix=prefix,
            hashed_key=hashed_key,
            key_sha256=key_sha256,
            description=description,
            is_active=True,
            scopes=scopes if scopes else ["*"],
            expires_at=expires_at,
            created_at=datetime.datetime.now(datetime.timezone.utc)
        )

        db.add(api_key)
        await db.commit()
        await db.refresh(api_key)
        logger.info(f"Created new API key for developer ID {developer_id}")
        return api_key
    except SQLAlchemyError:
        # §MCPTEST30 (V0526, 2026-10-01): the database refusing a value the caller sent (a NUL in the key's name) became
        # None here, and both routes answered 500 "Failed to create API key", after reading an attribute the rollback had
        # expired (MissingGreenlet; round 9's write-hygiene probe on sbx-alpha, V0525). Raised to the SQLAlchemy handler,
        # which answers the caller's own value 422 (NUL_IN_TEXT, PARAM_OUT_OF_RANGE) and anything else 500 without its words.
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error creating API key for developer ID {developer_id}: {e}", exc_info=True)
        return None

async def get_api_key_row_by_plain_key(db: AsyncSession, plain_key: str) -> Optional[models.DeveloperApiKey]:
    """AL-4: return the DeveloperApiKey ROW (not the developer) for scope
    inspection. O(1) indexed lookup by sha256; active keys only. Does NOT touch
    last_used_at (read-only introspection). Returns None for unknown/inactive.

    D6-715: a database that cannot answer is raised (SQLAlchemyError), as get_developer_by_plain_api_key does, never
    turned into "no such row": a caller must not read the key's scope from a lookup that did not happen."""
    if not plain_key.startswith(API_KEY_PREFIX):
        return None
    try:
        key_sha = security.api_key_lookup_hash(plain_key)
        stmt = select(models.DeveloperApiKey).where(
            models.DeveloperApiKey.key_sha256 == key_sha,
            models.DeveloperApiKey.is_active == True,
        )
        return (await db.execute(stmt)).scalar_one_or_none()
    except SQLAlchemyError:
        try:
            await db.rollback()
        except Exception:
            pass
        raise
    except Exception as e:
        logger.warning(f"get_api_key_row_by_plain_key failed: {e}")
        return None


async def get_developer_by_plain_api_key(db: AsyncSession, plain_key: str) -> Optional[models.Developer]:
    """Get a developer by plain API key, verifying the hash match."""
    if not plain_key.startswith(API_KEY_PREFIX):
        logger.warning(f"Attempted access with invalid API key format")
        return None

    try:
        key_sha = security.api_key_lookup_hash(plain_key)

        # --- PRIMARY (O(1)): indexed lookup by the deterministic SHA-256. -------------
        # API keys are 256-bit random tokens, so a fast hash is cryptographically
        # sufficient to identify a key — no need to bcrypt-scan every row. The unique
        # index makes this O(1) for valid, invalid AND cold keys (an unknown key is an
        # index miss → instant reject), so there is no warm-up cost and no DoS amp.
        primary_stmt = (
            select(models.DeveloperApiKey)
            .where(
                models.DeveloperApiKey.key_sha256 == key_sha,
                models.DeveloperApiKey.is_active == True,
            )
            .options(selectinload(models.DeveloperApiKey.developer))
        )
        api_key = (await db.execute(primary_stmt)).scalar_one_or_none()
        if api_key is not None:
            # AL-4 (2026-07-24): reject expired keys. An expired key authenticates
            # as no key at all (same 401 as an unknown key). NULL expires_at =
            # never expires (every pre-0125 key + MCP bridge keys).
            _exp = getattr(api_key, "expires_at", None)
            if _exp is not None:
                if _exp.tzinfo is None:
                    _exp = _exp.replace(tzinfo=datetime.timezone.utc)
                if _exp < datetime.datetime.now(datetime.timezone.utc):
                    logger.warning(f"API key {api_key.id} rejected: expired at {_exp.isoformat()}")
                    return None
            # The unique-index equality on key_sha256 IS the match (256-bit collision
            # space) — authenticate and refresh last_used.
            api_key.last_used_at = datetime.datetime.now(datetime.timezone.utc)
            db.add(api_key)
            await db.commit()
            return api_key.developer

        # --- FALLBACK (legacy keys only): rows created before key_sha256 existed have
        # key_sha256 IS NULL and can only be matched by their bcrypt hash. Scan ONLY
        # those un-migrated rows and lazily backfill key_sha256 on a match, so each
        # legacy key pays the bcrypt cost at most once, then joins the O(1) path. As
        # keys re-auth or rotate, this set drains to empty and the scan disappears. ---
        legacy_stmt = (
            select(models.DeveloperApiKey)
            .where(
                models.DeveloperApiKey.key_prefix == API_KEY_PREFIX,
                models.DeveloperApiKey.is_active == True,
                models.DeveloperApiKey.key_sha256.is_(None),
            )
            .options(selectinload(models.DeveloperApiKey.developer))
        )
        legacy_keys = (await db.execute(legacy_stmt)).scalars().all()
        for legacy_key in legacy_keys:
            if security.verify_api_key(plain_key, legacy_key.hashed_key):
                legacy_key.key_sha256 = key_sha  # lazy backfill → next time hits PRIMARY
                legacy_key.last_used_at = datetime.datetime.now(datetime.timezone.utc)
                db.add(legacy_key)
                await db.commit()
                return legacy_key.developer

        logger.warning(f"No active API key found matching the provided key (prefix: {API_KEY_PREFIX}).")
        return None
    except SQLAlchemyError:
        # §FESUITE: a database that cannot answer ("too many clients already") is not "no such key". Returning None here
        # made every caller answer 401 for a valid key; the database error goes up and the caller says 503.
        try:
            await db.rollback()
        except Exception:
            pass
        raise
    except Exception as e:
        await db.rollback() # Rollback potential commit failure
        logger.error(f"Error validating API key: {e}", exc_info=True)
        return None

async def get_active_api_keys_for_developer(db: AsyncSession, developer_id: int) -> List[models.DeveloperApiKey]:
    """Get all active API keys for a developer."""
    try:
        stmt = (
            select(models.DeveloperApiKey)
            .where(
                models.DeveloperApiKey.developer_id == developer_id,
                models.DeveloperApiKey.is_active == True
            )
            .order_by(models.DeveloperApiKey.created_at.desc())
        )
        result = await db.execute(stmt)
        # --- CORRECTED: Removed await from scalars() ---
        scalars_result = result.scalars()
        # --- END CORRECTION ---
        keys = list(scalars_result.all())
        return keys
    except Exception as e:
        logger.error(f"Error fetching API keys for developer {developer_id}: {e}", exc_info=True)
        return []

async def deactivate_api_key(db: AsyncSession, developer_id: int, api_key_id: int) -> bool:
    """Deactivate an API key for a developer."""
    try:
        # Get the API key
        api_key = await db.get(models.DeveloperApiKey, api_key_id)

        # Check if API key exists and belongs to the developer
        if not api_key:
            logger.warning(f"API key ID {api_key_id} not found for deactivation")
            return False

        if api_key.developer_id != developer_id:
            logger.warning(f"API key ID {api_key_id} does not belong to developer {developer_id}")
            return False

        # If already inactive, nothing to do
        if not api_key.is_active:
            logger.info(f"API key ID {api_key_id} is already inactive")
            return True

        # Deactivate the key
        api_key.is_active = False
        # api_key.deactivated_at = datetime.datetime.now(datetime.timezone.utc) # Add this field if needed

        db.add(api_key)
        await db.commit()
        logger.info(f"Deactivated API key ID {api_key_id} for developer {developer_id}")
        return True
    except Exception as e:
        await db.rollback()
        logger.error(f"Error deactivating API key {api_key_id}: {e}", exc_info=True)
        return False

async def get_developer_by_reset_token(db: AsyncSession, token: str) -> Optional[models.Developer]:
    """Get a developer by their password reset token."""
    try:
        stmt = select(models.Developer).where(models.Developer.password_reset_token == token)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()
    except Exception as e:
        logger.error(f"Error fetching developer by reset token: {e}", exc_info=True)
        return None


async def set_password_reset_token(
    db: AsyncSession,
    developer: models.Developer,
    token: str,
    expires: datetime.datetime
) -> bool:
    """Store a password reset token + expiry on the developer record."""
    try:
        developer.password_reset_token = token
        developer.password_reset_token_expires = expires
        db.add(developer)
        await db.commit()
        logger.info(f"Password reset token set for developer ID {developer.id}")
        return True
    except Exception as e:
        await db.rollback()
        logger.error(f"Error setting reset token for developer {developer.id}: {e}", exc_info=True)
        return False


async def clear_password_reset_token(db: AsyncSession, developer: models.Developer) -> None:
    """Clear the password reset token after use or successful reset."""
    try:
        developer.password_reset_token = None
        developer.password_reset_token_expires = None
        db.add(developer)
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.error(f"Error clearing reset token for developer {developer.id}: {e}", exc_info=True)


async def get_developer_access_level(db: AsyncSession, developer_id: int) -> str:
    """
    Get a developer's access level. Currently just checks if they're verified,
    but will expand to include other levels (e.g., admin) in the future.

    Returns a string value: "none", "unverified", or "verified"
    """
    developer = await get_developer_by_id(db, developer_id)

    if not developer:
        return "none"

    if not developer.is_verified:
        return "unverified"

    # Default for verified users
    return "verified"
# --- END OF FILE: agentvault_registry/src/agentvault_registry/crud/developer.py ---