import logging
from datetime import timezone
import uuid
import math
import datetime
import os
import json # Keep json import for cast
from typing import Optional, List, Dict, Any, Tuple

from sqlalchemy import select, func, or_, cast, Text, and_, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError, SQLAlchemyError # Import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

# Import local models and schemas with absolute imports
from agentvault_registry import models, schemas
from pydantic import ValidationError as PydanticValidationError

# Import the AgentCard model from the core library for validation
try:
    from agentvault import AgentCard as AgentCardModel
    _agentvault_lib_available = True
except ImportError:
    AgentCardModel = None # type: ignore
    _agentvault_lib_available = False
    logging.warning("Could not import 'agentvault' library. Agent Card validation during CRUD operations will be skipped.")

logger = logging.getLogger(__name__)


def card_validation_sentence(e: Exception) -> str:
    """§TWOAGENT #12/#22 (2026-09-23): what is wrong with a card, where, on one line: `loc: message; loc: message`.
    The refusal used to be pydantic's multi-line repr, carrying the rejected input and an external docs URL, and the
    RFC 7807 envelope repeated all of it; the validate route answered "An internal error occurred" instead."""
    try:
        parts = []
        for err in e.errors():  # type: ignore[attr-defined]
            loc = ".".join(str(x) for x in (err.get("loc") or ())) or "card"
            msg = str(err.get("msg") or "invalid")
            if msg.startswith("Value error, "):
                msg = msg[len("Value error, "):]
            parts.append(f"{loc}: {msg}")
        if not parts:
            raise ValueError("no errors listed")
        more = f" (and {len(parts) - 10} more)" if len(parts) > 10 else ""
        return "; ".join(parts[:10]) + more
    except Exception:  # noqa: BLE001 — never let the sentence builder hide the refusal
        return "the card does not match the Agent Card schema"


async def create_agent_card(
    db: AsyncSession, developer_id: int, card_create: schemas.AgentCardCreate
) -> Optional[models.AgentCard]:
    logger.info(f"Attempting to create Agent Card for developer ID: {developer_id}")
    if not _agentvault_lib_available or AgentCardModel is None:
        logger.warning("Skipping Agent Card validation as 'agentvault' library is not available.")
        validated_data = card_create.card_data
    else:
        try:
            validated_card_model = AgentCardModel.model_validate(card_create.card_data)
            validated_data = validated_card_model.model_dump(mode='json', by_alias=True)
            logger.debug("Agent Card data successfully validated against core model.")
        except PydanticValidationError as e:
            sentence = card_validation_sentence(e)
            logger.info("Agent Card refused (schema): %s", sentence)   # a caller's card, not a server fault
            raise ValueError(f"Invalid Agent Card data provided: {sentence}") from e
        except Exception as e:
             logger.error(f"Unexpected error during Agent Card validation: {e}", exc_info=True)
             raise ValueError(f"Unexpected error validating Agent Card data: {e}") from e
    # Q-C W2 (2026-05-12): canonicalize to A2A v1.0 shape on every write.
    # Idempotent. Adds securitySchemes/security/supportedInterfaces while keeping
    # v0.3 fields (authSchemes, url, etc.) for the 6-month transition window
    # (Commander Q5 signoff). Migration 0053 backfilled existing rows.
    try:
        from ..services.a2a_v1.compat import canonicalize_card_data
        validated_data = canonicalize_card_data(validated_data)
        logger.debug("Agent Card canonicalized to A2A v1.0 shape (Q-C W2).")
    except Exception as e:
        logger.warning(f"A2A v1.0 canonicalization failed (non-fatal, falling back to v0.3 shape): {e}")
    # §TWOAGENT #10: the bond, enforcement and listing extensions are stated by this registry at every read, never
    # by the owner; a copy in the submitted card is dropped here (`services/home_extensions.py`).
    from ..services.home_extensions import strip_home_extensions
    validated_data = strip_home_extensions(validated_data)
    # ── Strict field validation (beyond Pydantic schema) ──────────────────
    # Reject whitespace-only, empty, or missing critical fields.
    _errors = []
    name = (validated_data.get("name") or "").strip()
    description = (validated_data.get("description") or "").strip()
    provider = validated_data.get("provider") or {}
    provider_name = (provider.get("name") or "").strip() if isinstance(provider, dict) else ""
    hri = (validated_data.get("humanReadableId") or "").strip()

    if not name:
        _errors.append("'name' is required and cannot be empty. Give your agent a descriptive name like 'Trading Sentinel' or 'Data Oracle'.")
    elif len(name) < 2:
        _errors.append(f"'name' must be at least 2 characters (got {len(name)}). Use a descriptive agent name.")
    elif len(name) > 200:
        _errors.append(f"'name' must not exceed 200 characters (got {len(name)}).")

    if not description:
        _errors.append("'description' is required. Add at least 5 characters explaining what your agent does, e.g. 'Monitors token prices and executes trades based on market signals'.")
    elif len(description) < 5:
        _errors.append(f"'description' must be at least 5 characters (got {len(description)}). Describe your agent's purpose and capabilities.")

    if not provider_name:
        _errors.append("'provider.name' is required. Set this to your organization or developer name, e.g. 'Acme Labs'.")

    if not hri:
        _errors.append("'humanReadableId' is required. Use a URL-friendly slug like 'my-agent' or 'org/agent-name'.")

    if _errors:
        detail = "; ".join(_errors)
        logger.warning(f"Agent Card rejected — {detail}")
        raise ValueError(f"Agent card validation failed: {detail}")

    # Store trimmed values back
    validated_data["name"] = name
    validated_data["description"] = description
    if isinstance(provider, dict):
        provider["name"] = provider_name
        validated_data["provider"] = provider

    # Stamp federation_metadata.origin_registry_name at creation time so the
    # cross-registry resolver's PASS-1 exact match works without waiting for
    # federation_sync to fill it in on export. Uses the same helper that the
    # export path uses, so values are consistent.
    try:
        from ..routers.federation_sync import _get_display_name
        _origin = await _get_display_name(db)
        if _origin:
            _fed_meta = validated_data.setdefault("federation_metadata", {})
            if not _fed_meta.get("origin_registry_name"):
                _fed_meta["origin_registry_name"] = _origin
    except Exception as _e:
        logger.warning(
            f"Could not stamp origin_registry_name on new agent card: {_e}"
        )

    # §FRAMELIC (2026-09-07) — a SERVICE ACCOUNT's agents are out of discovery by construction.
    # His word: hide the eigentrust sim agents, the FX router and their kind. `unlisted`
    # (§DISCREFINE) already removes a card from the page, the facets AND the tag counts while
    # leaving a direct DID lookup working; what was missing was the thing that SETS it. Reading
    # it off the OWNING developer means nobody has to remember at each mint, and a service
    # account that gains an agent tomorrow is covered too. A failed read must never block a
    # mint, so it falls back to the listed default — the visible, recoverable direction.
    _unlisted_at_birth = False
    try:
        _owner = await db.get(models.Developer, developer_id)
        _unlisted_at_birth = bool(getattr(_owner, "agents_unlisted_by_default", False))
    except Exception as _e:  # noqa: BLE001
        logger.warning(f"Could not read agents_unlisted_by_default for developer {developer_id}: {_e}")
    if _unlisted_at_birth:
        logger.info(
            f"Agent card '{name}' starts UNLISTED — developer {developer_id} is a service account"
        )

    db_agent_card = models.AgentCard(
        developer_id=developer_id, card_data=validated_data, name=name,
        description=description, is_active=True, unlisted=_unlisted_at_birth
    )
    db.add(db_agent_card)
    try:
        await db.commit()
        await db.refresh(db_agent_card)
        logger.info(f"Successfully created Agent Card '{name}' with ID: {db_agent_card.id}")
        return db_agent_card
    except IntegrityError as e:
        await db.rollback()
        logger.error(f"Database integrity error creating agent card '{name}': {e}", exc_info=True)
        raise ValueError(f"Database error creating agent card: {e}") from e
    except Exception as e:
        await db.rollback()
        logger.error(f"Unexpected database error creating agent card '{name}': {e}", exc_info=True)
        raise ValueError(f"Unexpected database error: {e}") from e

async def get_agent_card(db: AsyncSession, card_id: uuid.UUID) -> Optional[models.AgentCard]:
    logger.info(f"Fetching Agent Card by UUID: {card_id}")
    stmt = (
        select(models.AgentCard)
        .options(selectinload(models.AgentCard.developer)) # Eager load developer
        .where(models.AgentCard.id == card_id)
    )
    result = await db.execute(stmt)
    card = result.scalar_one_or_none()
    if card:
        logger.info(f"Found Agent Card: {card.name} (Developer ID: {card.developer_id})")
    else:
        logger.warning(f"Agent Card with UUID {card_id} not found.")
    return card

async def get_agent_card_by_human_readable_id(db: AsyncSession, human_readable_id: str) -> Optional[models.AgentCard]:
    """Retrieves an Agent Card by its humanReadableId field in card_data."""
    logger.info(f"Fetching Agent Card by humanReadableId: {human_readable_id}")
    try:
        # First try to find the card ID using raw SQL
        find_id_query = text("""
        SELECT id FROM agent_cards 
        WHERE LOWER(card_data->>'humanReadableId') = LOWER(:hri)
        LIMIT 1
        """)
        
        id_result = await db.execute(find_id_query, {"hri": human_readable_id})
        card_id = id_result.scalar_one_or_none()
        
        if card_id:
            # Now use get_agent_card which properly loads the ORM object
            return await get_agent_card(db, card_id)
        else:
            logger.warning(f"Agent Card with humanReadableId '{human_readable_id}' not found.")
            return None
    except Exception as e:
        logger.error(f"Error fetching Agent Card by humanReadableId '{human_readable_id}': {e}", exc_info=True)
        return None

async def list_agent_cards(
    db: AsyncSession,
    skip: int = 0,
    limit: int = 100,
    active_only: bool = True,
    search: Optional[str] = None,
    tags: Optional[List[str]] = None,
    developer_id: Optional[int] = None,
    has_tee: Optional[bool] = None,
    tee_type: Optional[str] = None,
    native_only: bool = False,
    updated_since: Optional[datetime.datetime] = None,
    listed_only: bool = False,
) -> Tuple[List[models.AgentCard], int]:
    """List agent cards with pagination + filters.

    §pass10 (2026-05-15) — Added `native_only`. When True, excludes cards
    synced from peer registries (federation_metadata.source_registry or
    first_synced_from set). Used by the list endpoint when include_federated=true
    to prevent peer-sync activity (which constantly bumps `updated_at` on
    synced rows) from burying native cards beyond the limit.

    §DIRFEED (2026-09-06) — Added `updated_since`: the cursor an external INDEX walks. It is
    INCLUSIVE (`>=`) on purpose — two rows can share a microsecond, and an exclusive bound
    would drop the second one for good; a client that compares epochs re-reads the boundary
    row and loses nothing. With a cursor the ordering flips to updated_at ASC so a walk is
    monotone (the default DESC order is a "newest first" list, not a feed).
    """
    logger.info(f"Listing agent cards: skip={skip}, limit={limit}, active={active_only}, search='{search}', tags={tags}, owner={developer_id}, has_tee={has_tee}, tee_type='{tee_type}', native_only={native_only}")

    # Base query
    base_stmt = select(models.AgentCard).options(selectinload(models.AgentCard.developer))

    # Count query (applies filters before counting)
    count_stmt_base = select(func.count(models.AgentCard.id)).select_from(models.AgentCard)

    # Apply filters to both queries
    filters = []
    if active_only:
        filters.append(models.AgentCard.is_active == True)
    if developer_id is not None:
        filters.append(models.AgentCard.developer_id == developer_id)
    if search:
        search_term = f"%{search.lower()}%"
        filters.append(
            or_(
                func.lower(models.AgentCard.name).like(search_term),
                func.lower(models.AgentCard.description).like(search_term),
            )
        )
    if tags:
        filters.append(models.AgentCard.card_data['tags'].cast(JSONB).contains(tags))

    # §pass10 (2026-05-15) — exclude peer-synced cards when native_only=True.
    # A card is NATIVE iff neither source_registry nor first_synced_from is
    # set in federation_metadata. Uses raw-SQL because chained JSONB-path
    # `.astext` on SQLAlchemy ORM expression doesn't compile through
    # multiple indexers. The text fragment is parameterless so no injection
    # surface. JSONB `->>` returns NULL when key absent.
    if native_only:
        filters.append(
            text("(card_data->'federation_metadata'->>'source_registry') IS NULL"
                 " AND (card_data->'federation_metadata'->>'first_synced_from') IS NULL")
        )

    # §DIRFEED (2026-09-06) — the index cursor. Inclusive bound, see the docstring.
    if updated_since is not None:
        filters.append(models.AgentCard.updated_at >= updated_since)

    # §DARKSYNC (2026-09-22) — an UNLISTED (dark) card is not in discovery, native or mirror. The public list is a
    # discovery surface (the Directory's feed, the globe, MCP listAgentCards), and it listed dark cards until now.
    if listed_only:
        filters.append(models.AgentCard.unlisted.is_(False))

    # TEE Filters
    if has_tee is not None:
        if has_tee:
            filters.append(models.AgentCard.card_data['capabilities']['teeDetails'] != None)
            filters.append(models.AgentCard.card_data['capabilities']['teeDetails'].cast(JSONB) != cast(json.dumps(None), JSONB))
        else:
            filters.append(or_(
                 models.AgentCard.card_data['capabilities']['teeDetails'] == None,
                 models.AgentCard.card_data['capabilities']['teeDetails'].cast(JSONB) == cast(json.dumps(None), JSONB)
            ))
    
    # For TEE type, use sub-query with raw SQL for reliable behavior
    if tee_type:
        # Find IDs of cards with matching TEE type first
        tee_sql = text("""
        SELECT id FROM agent_cards 
        WHERE LOWER(card_data->'capabilities'->'teeDetails'->>'type') = LOWER(:tee_type)
        """)
        tee_result = await db.execute(tee_sql, {"tee_type": tee_type})
        tee_card_ids = [row[0] for row in tee_result.fetchall()]
        
        if tee_card_ids:
            filters.append(models.AgentCard.id.in_(tee_card_ids))
        else:
            # If no matches, return empty result
            return [], 0

    # Apply collected filters
    if filters:
        base_stmt = base_stmt.where(and_(*filters))
        count_stmt_base = count_stmt_base.where(and_(*filters))

    # Get total count. §MCPTEST30 (V0546): a database error here and below is raised, never answered as an empty page.
    # Both reads returned ([], 0) for ANY failure, so a database at its connection ceiling, or a value the database
    # refused (round 14's type probe sent an offset of 2**63), read as "no agents" with HTTP 200: to the public list and to
    # a peer's federation query alike, and a peer cannot tell that from a frame with nothing to share. The session
    # dependency logs it (one line for a caller's value) and the errors module answers it by its cause (422 / 503 / 500).
    count_result = await db.execute(count_stmt_base)
    total_items = count_result.scalar_one_or_none() or 0

    logger.debug(f"Total matching agent cards found: {total_items}")

    # Apply ordering, offset, and limit for the final result set
    final_stmt = (
        base_stmt
        .options(selectinload(models.AgentCard.developer))
        # §DIRFEED: a cursor walk is ASC (monotone in the cursor); the plain list stays newest-first.
        # §DIRFEED-2: `id` is the TIEBREAK, and it is load-bearing — `updated_at` is not unique (95 active
        # cards on EU share 68 distinct instants), and an ORDER BY that does not totally order the rows lets
        # Postgres arrange the equal-keyed ones differently for a different LIMIT/OFFSET plan. Measured before
        # this: paging natives_only in two pages of four returned two rows TWICE and never returned two others,
        # while two identical calls agreed with each other — so a skip-based walk silently double-counts and
        # drops, and the two errors cancel in a COUNT (a walk of 5,380 cards graded itself "exact"). The
        # inclusive ASC cursor needs it for the same reason: rows sharing an instant must have a stable order
        # within the page, or the cursor's own re-read cannot tell which ones it has already seen.
        .order_by(
            models.AgentCard.updated_at.asc() if updated_since is not None else models.AgentCard.updated_at.desc(),
            models.AgentCard.id.asc(),
        )
        .offset(skip)
        .limit(limit)
    )

    result = await db.execute(final_stmt)
    items = list(result.scalars().all())
    logger.info(f"Retrieved {len(items)} agent cards for the current page.")
    return items, total_items


async def update_agent_card(
    db: AsyncSession, db_card: models.AgentCard, card_update: schemas.AgentCardUpdate
) -> Optional[models.AgentCard]:
    logger.info(f"Attempting to update Agent Card ID: {db_card.id}")
    update_data_provided = False
    if card_update.card_data is not None:
        update_data_provided = True
        logger.debug(f"Updating card_data for Agent Card ID: {db_card.id}")
        if not isinstance(card_update.card_data, dict): raise ValueError("Provided card_data for update must be a dictionary.")
        existing_data = db_card.card_data or {}
        merged_data = {**existing_data, **card_update.card_data}
        if not _agentvault_lib_available or AgentCardModel is None:
             logger.warning("Skipping Agent Card validation as 'agentvault' library is not available.")
             validated_data = merged_data
        else:
            try:
                validated_card_model = AgentCardModel.model_validate(merged_data)
                validated_data = validated_card_model.model_dump(mode='json', by_alias=True)
                logger.debug("Merged Agent Card data successfully validated.")
            except PydanticValidationError as e:
                sentence = card_validation_sentence(e)
                logger.info("Merged Agent Card refused (schema): %s", sentence)
                raise ValueError(f"Invalid merged Agent Card data provided for update: {sentence}") from e
            except Exception as e:
                logger.error(f"Unexpected error during merged Agent Card update validation: {e}", exc_info=True)
                raise ValueError(f"Unexpected error validating merged Agent Card data: {e}") from e
        # Q-C W2: canonicalize updates to A2A v1.0 shape (idempotent).
        try:
            from ..services.a2a_v1.compat import canonicalize_card_data
            validated_data = canonicalize_card_data(validated_data)
            logger.debug("Updated Agent Card canonicalized to A2A v1.0 shape (Q-C W2).")
        except Exception as e:
            logger.warning(f"A2A v1.0 canonicalization on update failed (non-fatal): {e}")
        # §TWOAGENT #10: an update that echoes a read (which states the home extensions) must not persist them.
        from ..services.home_extensions import strip_home_extensions
        validated_data = strip_home_extensions(validated_data)
        db_card.card_data = validated_data
        try:
            db_card.name = validated_data.get("name")
            db_card.description = validated_data.get("description")
            if not db_card.name: raise ValueError("Validated card data for update is missing the required 'name' field.")
        except Exception as e:
            logger.error(f"Failed to extract required fields from updated card data: {e}", exc_info=True)
            raise ValueError(f"Could not extract required fields from updated card data: {e}") from e
    if card_update.is_active is not None:
        if db_card.is_active != card_update.is_active:
             update_data_provided = True
             logger.debug(f"Updating is_active status for Agent Card ID {db_card.id} to {card_update.is_active}")
             db_card.is_active = card_update.is_active
    if update_data_provided:
        try:
            db.add(db_card)
            await db.commit()
            await db.refresh(db_card)
            logger.info(f"Successfully updated Agent Card ID: {db_card.id}.")
            return db_card
        except Exception as e:
            await db.rollback()
            logger.error(f"Database error updating agent card {db_card.id}: {e}", exc_info=True)
            raise ValueError(f"Database error updating agent card: {e}") from e
    else:
        logger.debug(f"No update data provided or no changes needed for Agent Card ID: {db_card.id}. Returning existing object.")
        return db_card

async def delete_agent_card(db: AsyncSession, card_id: uuid.UUID) -> bool:
    logger.info(f"Attempting to soft delete (deactivate) agent card ID: {card_id}")
    db_card = await get_agent_card(db, card_id)
    if db_card:
        if not db_card.is_active:
            logger.warning(f"Agent Card {card_id} is already inactive.")
            return True
        db_card.is_active = False
        try:
            db.add(db_card)
            await db.commit()
            await db.refresh(db_card)
            logger.info(f"Successfully deactivated Agent Card ID: {card_id}.")
            return True
        except Exception as e:
            await db.rollback()
            logger.error(f"Error deactivating agent card {card_id}: {e}", exc_info=True)
            return False


async def validate_agent_card_schema(card_data: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """
    Validates an Agent Card against the schema.
    Returns: (is_valid, error_message)
    """
    if not _agentvault_lib_available or AgentCardModel is None:
        logger.warning("Skipping Agent Card validation as 'agentvault' library is not available.")
        # Basic validation when library not available
        # P0-1 FIX (OWL22): Accept both protocolVersion (v0.3.0+) and legacy schemaVersion
        required_fields = ['name', 'description', 'humanReadableId', 
                         'agentVersion', 'url', 'provider', 'capabilities', 'authSchemes']
        if 'protocolVersion' not in card_data and 'schemaVersion' not in card_data:
            return False, "Missing required field: protocolVersion (or legacy schemaVersion)"
        for field in required_fields:
            if field not in card_data:
                return False, f"Missing required field: {field}"
        return True, None
    
    try:
        validated_card_model = AgentCardModel.model_validate(card_data)
        return True, None
    except PydanticValidationError as e:
        sentence = card_validation_sentence(e)
        logger.info("Agent Card refused (schema): %s", sentence)
        return False, sentence
    except Exception as e:
        logger.error(f"Unexpected error during Agent Card validation: {e}")
        return False, f"Unexpected validation error: {e}"
