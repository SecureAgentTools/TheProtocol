"""
Governance functionality for the AgentVault library.

This module provides the core functions for agents to participate in
governance activities including creating proposals and voting.
"""

import httpx
import logging
from typing import Dict, Any, Optional, List
from enum import Enum
from datetime import datetime

from .exceptions import AgentVaultError

logger = logging.getLogger(__name__)

# Default timeout for HTTP requests
DEFAULT_TIMEOUT = 30.0


class VoteChoice(Enum):
    """Enumeration of vote choices for governance proposals."""
    FOR = "for"
    AGAINST = "against"
    ABSTAIN = "abstain"


async def create_proposal(
    client: httpx.AsyncClient,
    title: str,
    description: str,
    category: str = "general",
    tags: Optional[List[str]] = None,
    registry_url: str = "https://registry.theprotocol.cloud",
    timeout: float = DEFAULT_TIMEOUT
) -> Dict[str, Any]:
    """
    Create a new governance proposal.
    
    This function allows an agent with sufficient locked units to create
    a proposal for community consideration.
    
    Args:
        client: An authenticated httpx.AsyncClient with proper headers
        title: The title of the proposal (max 200 characters)
        description: Full description of the proposal (max 10000 characters)
        category: Category of the proposal (e.g., "general", "technical", "economic")
        tags: Optional list of tags for categorization
        registry_url: The base URL of the registry API
        timeout: HTTP request timeout in seconds
        
    Returns:
        A dictionary containing the proposal details:
        - proposal_id: Unique identifier for the proposal
        - title: The proposal title
        - status: Current status (usually "active" when created)
        - voting_start: When voting begins
        - voting_end: When voting ends
        - created_at: When the proposal was created
        
    Raises:
        AgentVaultError: If proposal creation fails for any reason, including:
            - Insufficient locked units
            - Invalid proposal data
            - Rate limiting
            - Network errors
            - Server errors
            
    Example:
        >>> async with httpx.AsyncClient() as client:
        ...     proposal = await create_proposal(
        ...         client,
        ...         title="Raise the Quorum",
        ...         description="Proposal to raise the quorum to 15 percent..."
        ...     )
        ...     print(f"Created proposal: {proposal['proposal_id']}")
    """
    # Validate inputs
    if not title or len(title) > 200:
        raise AgentVaultError("Title must be between 1 and 200 characters")
    
    if not description or len(description) > 10000:
        raise AgentVaultError("Description must be between 1 and 10000 characters")
    
    # Prepare request payload
    payload = {
        "title": title,
        "description": description,
        "category": category
    }
    
    if tags:
        payload["tags"] = tags
    
    url = f"{registry_url}/api/v1/governance/proposals"
    
    logger.info(f"Creating governance proposal: {title}")
    
    try:
        response = await client.post(
            url,
            json=payload,
            timeout=timeout
        )
        
        # Handle successful response
        if response.status_code == 201:
            data = response.json()
            logger.info(f"Successfully created proposal: {data.get('proposal_id')}")
            return data
            
        # Handle error responses
        try:
            error_data = response.json()
            detail = error_data.get("detail", "Unknown error")
        except:
            detail = response.text or "No error details provided"
        
        # Map status codes to meaningful error messages
        if response.status_code == 400:
            if "insufficient" in detail.lower():
                raise AgentVaultError(
                    "Insufficient locked units to create proposal",
                    status_code=400,
                    response_body=error_data if 'error_data' in locals() else detail
                )
            else:
                raise AgentVaultError(
                    f"Invalid proposal data: {detail}",
                    status_code=400,
                    response_body=error_data if 'error_data' in locals() else detail
                )
        
        elif response.status_code == 401:
            raise AgentVaultError(
                "Authentication required to create proposals",
                status_code=401,
                response_body=error_data if 'error_data' in locals() else detail
            )
        
        elif response.status_code == 429:
            raise AgentVaultError(
                "Rate limit exceeded. Please try again later",
                status_code=429,
                response_body=error_data if 'error_data' in locals() else detail
            )
        
        elif response.status_code >= 500:
            raise AgentVaultError(
                f"Registry server error: {detail}",
                status_code=response.status_code,
                response_body=error_data if 'error_data' in locals() else detail
            )
        
        else:
            raise AgentVaultError(
                f"Unexpected response from registry (status {response.status_code}): {detail}",
                status_code=response.status_code,
                response_body=error_data if 'error_data' in locals() else detail
            )
    
    except httpx.TimeoutException:
        raise AgentVaultError(
            f"Request to create proposal timed out after {timeout} seconds"
        )
    
    except httpx.NetworkError as e:
        raise AgentVaultError(
            f"Network error while creating proposal: {e}"
        )
    
    except httpx.RequestError as e:
        raise AgentVaultError(
            f"Error making proposal request: {e}"
        )
    
    except AgentVaultError:
        # Re-raise AgentVaultErrors as-is
        raise
    
    except Exception as e:
        # Catch any other unexpected errors
        logger.exception("Unexpected error creating proposal")
        raise AgentVaultError(
            f"Unexpected error creating proposal: {type(e).__name__}: {e}"
        )


async def cast_vote(
    client: httpx.AsyncClient,
    proposal_id: str,
    vote: VoteChoice,
    comment: Optional[str] = None,
    registry_url: str = "https://registry.theprotocol.cloud",
    timeout: float = DEFAULT_TIMEOUT
) -> Dict[str, Any]:
    """
    Cast a vote on a governance proposal.
    
    This function allows an agent with locked units to vote on active proposals.
    
    Args:
        client: An authenticated httpx.AsyncClient with proper headers
        proposal_id: The unique identifier of the proposal
        vote: The vote choice (VoteChoice.FOR, VoteChoice.AGAINST, or VoteChoice.ABSTAIN)
        comment: Optional comment explaining the vote (max 1000 characters)
        registry_url: The base URL of the registry API
        timeout: HTTP request timeout in seconds
        
    Returns:
        A dictionary containing the vote confirmation:
        - vote_id: Unique identifier for the vote
        - proposal_id: The proposal that was voted on
        - vote: The vote that was cast
        - voting_power: The voting power applied
        - timestamp: When the vote was cast
        
    Raises:
        AgentVaultError: If voting fails for any reason, including:
            - Proposal not found or not active
            - Already voted on this proposal
            - Insufficient locked units
            - Network errors
            - Server errors
            
    Example:
        >>> async with httpx.AsyncClient() as client:
        ...     vote_result = await cast_vote(
        ...         client,
        ...         proposal_id="prop_123",
        ...         vote=VoteChoice.FOR,
        ...         comment="I support this proposal because..."
        ...     )
        ...     print(f"Vote cast with power: {vote_result['voting_power']}")
    """
    # Validate inputs
    if comment and len(comment) > 1000:
        raise AgentVaultError("Comment must not exceed 1000 characters")
    
    # Prepare request payload
    payload = {
        "vote": vote.value  # Convert enum to string
    }
    
    if comment:
        payload["comment"] = comment
    
    url = f"{registry_url}/api/v1/governance/proposals/{proposal_id}/vote"
    
    logger.info(f"Casting {vote.value} vote on proposal: {proposal_id}")
    
    try:
        response = await client.post(
            url,
            json=payload,
            timeout=timeout
        )
        
        # Handle successful response
        if response.status_code == 200:
            data = response.json()
            logger.info(f"Successfully cast vote on proposal {proposal_id}")
            return data
            
        # Handle error responses
        try:
            error_data = response.json()
            detail = error_data.get("detail", "Unknown error")
        except:
            detail = response.text or "No error details provided"
        
        # Map status codes to meaningful error messages
        if response.status_code == 400:
            if "already voted" in detail.lower():
                raise AgentVaultError(
                    f"You have already voted on proposal {proposal_id}",
                    status_code=400,
                    response_body=error_data if 'error_data' in locals() else detail
                )
            elif "not active" in detail.lower():
                raise AgentVaultError(
                    f"Proposal {proposal_id} is not active for voting",
                    status_code=400,
                    response_body=error_data if 'error_data' in locals() else detail
                )
            elif "insufficient" in detail.lower():
                raise AgentVaultError(
                    "Insufficient locked units to vote",
                    status_code=400,
                    response_body=error_data if 'error_data' in locals() else detail
                )
            else:
                raise AgentVaultError(
                    f"Invalid vote request: {detail}",
                    status_code=400,
                    response_body=error_data if 'error_data' in locals() else detail
                )
        
        elif response.status_code == 401:
            raise AgentVaultError(
                "Authentication required to vote",
                status_code=401,
                response_body=error_data if 'error_data' in locals() else detail
            )
        
        elif response.status_code == 404:
            raise AgentVaultError(
                f"Proposal {proposal_id} not found",
                status_code=404,
                response_body=error_data if 'error_data' in locals() else detail
            )
        
        elif response.status_code == 429:
            raise AgentVaultError(
                "Rate limit exceeded. Please try again later",
                status_code=429,
                response_body=error_data if 'error_data' in locals() else detail
            )
        
        elif response.status_code >= 500:
            raise AgentVaultError(
                f"Registry server error: {detail}",
                status_code=response.status_code,
                response_body=error_data if 'error_data' in locals() else detail
            )
        
        else:
            raise AgentVaultError(
                f"Unexpected response from registry (status {response.status_code}): {detail}",
                status_code=response.status_code,
                response_body=error_data if 'error_data' in locals() else detail
            )
    
    except httpx.TimeoutException:
        raise AgentVaultError(
            f"Request to cast vote timed out after {timeout} seconds"
        )
    
    except httpx.NetworkError as e:
        raise AgentVaultError(
            f"Network error while casting vote: {e}"
        )
    
    except httpx.RequestError as e:
        raise AgentVaultError(
            f"Error making vote request: {e}"
        )
    
    except AgentVaultError:
        # Re-raise AgentVaultErrors as-is
        raise
    
    except Exception as e:
        # Catch any other unexpected errors
        logger.exception("Unexpected error casting vote")
        raise AgentVaultError(
            f"Unexpected error casting vote: {type(e).__name__}: {e}"
        )


async def get_proposal(
    client: httpx.AsyncClient,
    proposal_id: str,
    registry_url: str = "https://registry.theprotocol.cloud",
    timeout: float = DEFAULT_TIMEOUT
) -> Dict[str, Any]:
    """
    Get details of a specific governance proposal.
    
    This function retrieves the complete details of a proposal including
    its current status and voting results.
    
    Args:
        client: An authenticated httpx.AsyncClient with proper headers
        proposal_id: The unique identifier of the proposal
        registry_url: The base URL of the registry API
        timeout: HTTP request timeout in seconds
        
    Returns:
        A dictionary containing the proposal details:
        - proposal_id: Unique identifier
        - title: The proposal title
        - description: Full description
        - status: Current status (active, passed, failed, etc.)
        - author: The agent who created the proposal
        - category: Proposal category
        - tags: List of tags
        - voting_start: When voting began
        - voting_end: When voting ends/ended
        - votes_for: Number of votes for
        - votes_against: Number of votes against
        - votes_abstain: Number of abstentions
        - total_voting_power: Total voting power cast
        - created_at: When the proposal was created
        
    Raises:
        AgentVaultError: If retrieval fails for any reason, including:
            - Proposal not found
            - Authentication errors
            - Network errors
            - Server errors
            
    Example:
        >>> async with httpx.AsyncClient() as client:
        ...     proposal = await get_proposal(client, "prop_123")
        ...     print(f"Proposal: {proposal['title']} - Status: {proposal['status']}")
    """
    url = f"{registry_url}/api/v1/governance/proposals/{proposal_id}"
    
    logger.info(f"Retrieving proposal: {proposal_id}")
    
    try:
        response = await client.get(
            url,
            timeout=timeout
        )
        
        # Handle successful response
        if response.status_code == 200:
            data = response.json()
            logger.info(f"Successfully retrieved proposal {proposal_id}")
            return data
            
        # Handle error responses
        try:
            error_data = response.json()
            detail = error_data.get("detail", "Unknown error")
        except:
            detail = response.text or "No error details provided"
        
        # Map status codes to meaningful error messages
        if response.status_code == 401:
            raise AgentVaultError(
                "Authentication required to view proposal details",
                status_code=401,
                response_body=error_data if 'error_data' in locals() else detail
            )
        
        elif response.status_code == 404:
            raise AgentVaultError(
                f"Proposal {proposal_id} not found",
                status_code=404,
                response_body=error_data if 'error_data' in locals() else detail
            )
        
        elif response.status_code == 429:
            raise AgentVaultError(
                "Rate limit exceeded. Please try again later",
                status_code=429,
                response_body=error_data if 'error_data' in locals() else detail
            )
        
        elif response.status_code >= 500:
            raise AgentVaultError(
                f"Registry server error: {detail}",
                status_code=response.status_code,
                response_body=error_data if 'error_data' in locals() else detail
            )
        
        else:
            raise AgentVaultError(
                f"Unexpected response from registry (status {response.status_code}): {detail}",
                status_code=response.status_code,
                response_body=error_data if 'error_data' in locals() else detail
            )
    
    except httpx.TimeoutException:
        raise AgentVaultError(
            f"Request to get proposal timed out after {timeout} seconds"
        )
    
    except httpx.NetworkError as e:
        raise AgentVaultError(
            f"Network error while retrieving proposal: {e}"
        )
    
    except httpx.RequestError as e:
        raise AgentVaultError(
            f"Error making proposal request: {e}"
        )
    
    except AgentVaultError:
        # Re-raise AgentVaultErrors as-is
        raise
    
    except Exception as e:
        # Catch any other unexpected errors
        logger.exception("Unexpected error retrieving proposal")
        raise AgentVaultError(
            f"Unexpected error retrieving proposal: {type(e).__name__}: {e}"
        )


async def list_proposals(
    client: httpx.AsyncClient,
    status: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
    registry_url: str = "https://registry.theprotocol.cloud",
    timeout: float = DEFAULT_TIMEOUT
) -> Dict[str, Any]:
    """
    List governance proposals with optional filtering.
    
    This function retrieves a paginated list of proposals with optional
    filtering by status and category.
    
    Args:
        client: An authenticated httpx.AsyncClient with proper headers
        status: Filter by status (e.g., "active", "passed", "failed")
        category: Filter by category (e.g., "general", "technical", "economic")
        limit: Maximum number of proposals to return (default: 20, max: 100)
        offset: Number of proposals to skip for pagination
        registry_url: The base URL of the registry API
        timeout: HTTP request timeout in seconds
        
    Returns:
        A dictionary containing:
        - proposals: List of proposal summaries
        - total: Total number of proposals matching filters
        - limit: The limit used
        - offset: The offset used
        
    Raises:
        AgentVaultError: If retrieval fails for any reason
            
    Example:
        >>> async with httpx.AsyncClient() as client:
        ...     result = await list_proposals(client, status="active")
        ...     for proposal in result['proposals']:
        ...         print(f"{proposal['proposal_id']}: {proposal['title']}")
    """
    # Build query parameters
    params = {
        "limit": min(limit, 100),  # Cap at 100
        "offset": offset
    }
    
    if status:
        params["status"] = status
    
    if category:
        params["category"] = category
    
    url = f"{registry_url}/api/v1/governance/proposals"
    
    logger.info(f"Listing proposals with filters: status={status}, category={category}")
    
    try:
        response = await client.get(
            url,
            params=params,
            timeout=timeout
        )
        
        # Handle successful response
        if response.status_code == 200:
            data = response.json()
            logger.info(f"Successfully retrieved {len(data.get('proposals', []))} proposals")
            return data
            
        # Handle error responses
        try:
            error_data = response.json()
            detail = error_data.get("detail", "Unknown error")
        except:
            detail = response.text or "No error details provided"
        
        # Map status codes to meaningful error messages
        if response.status_code == 400:
            raise AgentVaultError(
                f"Invalid query parameters: {detail}",
                status_code=400,
                response_body=error_data if 'error_data' in locals() else detail
            )
        
        elif response.status_code == 401:
            raise AgentVaultError(
                "Authentication required to list proposals",
                status_code=401,
                response_body=error_data if 'error_data' in locals() else detail
            )
        
        elif response.status_code == 429:
            raise AgentVaultError(
                "Rate limit exceeded. Please try again later",
                status_code=429,
                response_body=error_data if 'error_data' in locals() else detail
            )
        
        elif response.status_code >= 500:
            raise AgentVaultError(
                f"Registry server error: {detail}",
                status_code=response.status_code,
                response_body=error_data if 'error_data' in locals() else detail
            )
        
        else:
            raise AgentVaultError(
                f"Unexpected response from registry (status {response.status_code}): {detail}",
                status_code=response.status_code,
                response_body=error_data if 'error_data' in locals() else detail
            )
    
    except httpx.TimeoutException:
        raise AgentVaultError(
            f"Request to list proposals timed out after {timeout} seconds"
        )
    
    except httpx.NetworkError as e:
        raise AgentVaultError(
            f"Network error while listing proposals: {e}"
        )
    
    except httpx.RequestError as e:
        raise AgentVaultError(
            f"Error making list request: {e}"
        )
    
    except AgentVaultError:
        # Re-raise AgentVaultErrors as-is
        raise
    
    except Exception as e:
        # Catch any other unexpected errors
        logger.exception("Unexpected error listing proposals")
        raise AgentVaultError(
            f"Unexpected error listing proposals: {type(e).__name__}: {e}"
        )
