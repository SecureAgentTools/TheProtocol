import logging
from typing import Optional, Dict, Any

from fastapi import APIRouter, HTTPException, status, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import pydantic

# Import local schemas and models
from agentvault_registry import schemas
from agentvault_registry.models import Agent
from agentvault_registry.database import get_db
from agentvault_registry.security import verify_agent_token, agent_token_refusal, agent_token_refusal_exception

# Import the AgentCard model from the core library for validation
try:
    from agentvault import AgentCard as AgentCardModel
    _agentvault_lib_available = True
except ImportError:
    AgentCardModel = None # type: ignore
    _agentvault_lib_available = False
    logging.warning("Could not import 'agentvault' library. Agent Card validation endpoint will skip validation.")


logger = logging.getLogger(__name__)

router = APIRouter()


async def get_current_agent(
    db: AsyncSession = Depends(get_db),
    token_data: dict = Depends(verify_agent_token)
) -> Agent:
    """
    Dependency to get the current authenticated agent.
    
    This function extracts the agent information from the current authenticated token.
    It expects an agent authentication token.
    
    Returns:
        Agent: The current authenticated agent
        
    Raises:
        HTTPException: If the agent is not found
    """
    # Get the agent DID from the token data
    agent_did = token_data.get("did")
    if not agent_did:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token"
        )
    
    # Fetch the agent from the database
    stmt = select(Agent).where(Agent.did == agent_did)
    result = await db.execute(stmt)
    agent = result.scalar_one_or_none()
    
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found"
        )
    
    if agent.status in ("suspended", "revoked"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Agent account is {agent.status}"
        )

    # §FEFRAME W3: an owner session token ends with the session that minted it; D6-281: a token minted from the agent's
    # credential ends when that credential is reset or rotated (security.agent_token_refusal asks both)
    owner_why = await agent_token_refusal(db, token_data, agent)
    if owner_why:
        raise agent_token_refusal_exception(token_data, owner_why)

    return agent

@router.post(
    "/validate-card",
    response_model=schemas.AgentCardValidationResponse,
    summary="Validate Agent Card Data",
    description="Validates the provided JSON data against the official TheProtocol Agent Card schema.",
    # §pass56 PR-5: tags= dropped; main.py:include_router supplies "Utilities"
)
async def validate_agent_card(
    request: schemas.AgentCardValidationRequest
) -> schemas.AgentCardValidationResponse:
    """
    Validates Agent Card JSON data.

    - **request**: The request body containing the `card_data` dictionary.
    """
    logger.info("Received request to validate agent card data.")

    if not _agentvault_lib_available or AgentCardModel is None:
        logger.warning("Skipping validation as core 'agentvault' library is unavailable.")
        return schemas.AgentCardValidationResponse(
            is_valid=True, # Treat as valid if we can't check
            detail="Validation skipped: Core library not available.",
            validated_card_data=request.card_data # Return original data
        )

    try:
        # Layer 1: Pydantic schema validation (agentvault library)
        validated_card = AgentCardModel.model_validate(request.card_data)
        validated_data = validated_card.model_dump(mode='json', by_alias=True)
        logger.info("Agent card schema validation passed.")

        # Layer 2: Strict field validation (matches create_agent_card in crud)
        _errors = []
        name = (validated_data.get("name") or "").strip()
        description = (validated_data.get("description") or "").strip()
        provider = validated_data.get("provider") or {}
        provider_name = (provider.get("name") or "").strip() if isinstance(provider, dict) else ""
        hri = (validated_data.get("humanReadableId") or "").strip()

        if not name:
            _errors.append("'name' is required and cannot be empty or whitespace-only")
        elif len(name) < 2:
            _errors.append("'name' must be at least 2 characters")
        elif len(name) > 200:
            _errors.append("'name' must not exceed 200 characters")

        if not description:
            _errors.append("'description' is required and cannot be empty. Add at least 5 characters explaining what your agent does.")
        elif len(description) < 5:
            _errors.append(f"'description' must be at least 5 characters (currently {len(description)}). Describe what your agent does.")

        if not provider_name:
            _errors.append("'provider.name' is required. Set this to your organization or developer name.")

        if not hri:
            _errors.append("'humanReadableId' is required. Use a URL-friendly slug like 'my-agent' or 'org/agent-name'.")

        if _errors:
            detail = "Card schema is valid but fails strict field checks:\n" + "\n".join(f"  - {e}" for e in _errors)
            return schemas.AgentCardValidationResponse(
                is_valid=False,
                detail=detail,
                validated_card_data=validated_data,
            )

        return schemas.AgentCardValidationResponse(
            is_valid=True,
            validated_card_data=validated_data,
        )
    except pydantic.ValidationError as e:
        # §TWOAGENT #12 (2026-09-23): this is the route whose job is to say what is wrong with a card, and it answered
        # "An internal error occurred" for every schema-invalid one.
        from agentvault_registry.crud.agent_card import card_validation_sentence
        sentence = card_validation_sentence(e)
        logger.info("Agent card data validation refused: %s", sentence)
        return schemas.AgentCardValidationResponse(
            is_valid=False,
            detail=sentence
        )
    except Exception as e:
        logger.exception("Unexpected error during agent card validation.")
        return schemas.AgentCardValidationResponse(
            is_valid=False,
            detail=f"An unexpected error occurred during validation: {type(e).__name__}"
        )
