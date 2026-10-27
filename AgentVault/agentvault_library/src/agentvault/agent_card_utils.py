"""
Utilities for loading, parsing, and validating A2A Agent Cards.
"""

import json
import httpx
import pathlib
import logging
from typing import Dict, Any, Optional, List

# Import Pydantic for validation errors
import pydantic
# --- ADDED: Import respx exceptions if available (for testing) ---
try:
    import respx
    from respx.mock import MockError as RespxMockError
except ImportError:
    respx = None # type: ignore
    RespxMockError = Exception # Fallback type
# --- END ADDED ---

# Import local models and exceptions
from .models.agent_card import AgentCard
from .exceptions import (
    AgentCardError,
    AgentCardValidationError,
    AgentCardFetchError,
)
from .key_manager import KeyManager

logger = logging.getLogger(__name__)


async def discover_agents_federated(
    client: httpx.AsyncClient,
    central_registry_url: str,
    key_manager: KeyManager,
    search_query: Optional[str] = None,
    tags: Optional[List[str]] = None,
    limit_per_registry: int = 10,
    offset_per_registry: int = 0,
    **kwargs
) -> List[Dict[str, Any]]:
    """
    Performs federated discovery across the central registry and all active peer registries.
    
    Args:
        client: An httpx.AsyncClient instance for making HTTP requests
        central_registry_url: Base URL of the central AgentVault Registry
        key_manager: KeyManager instance for handling peer registry authentication
        search_query: Optional search string to filter agents
        tags: Optional list of tags to filter agents
        limit_per_registry: Maximum results to fetch from each registry
        offset_per_registry: Number of results to skip from each registry
        **kwargs: Additional query parameters to pass to discovery endpoints
    
    Returns:
        A list of agent card summaries from all registries, each with an 'origin_registry_name' field
    
    Raises:
        AgentCardFetchError: For network-related errors with the central registry
        AgentCardError: For other unexpected errors
    """
    results = []
    
    # Base query parameters
    base_params = {
        "limit": limit_per_registry,
        "offset": offset_per_registry,
        "active_only": True,
        **kwargs  # Allow additional parameters
    }
    
    if search_query:
        base_params["search"] = search_query
    
    if tags:
        base_params["tags"] = ",".join(tags)
    
    # Step 1: Fetch results from the central registry
    logger.info(f"Querying central registry at {central_registry_url}")
    try:
        central_api_url = f"{central_registry_url.rstrip('/')}/api/v1/agent-cards"
        response = await client.get(central_api_url, params=base_params)
        response.raise_for_status()
        
        central_data = response.json()
        central_items = central_data.get("items", [])
        
        # Add origin registry name to each item
        for item in central_items:
            item["origin_registry_name"] = "Local"
        
        results.extend(central_items)
        logger.info(f"Retrieved {len(central_items)} agents from central registry")
        
    except httpx.HTTPStatusError as e:
        raise AgentCardFetchError(
            f"Failed to fetch from central registry. Status: {e.response.status_code}",
            status_code=e.response.status_code,
            response_body=e.response.text
        ) from e
    except httpx.RequestError as e:
        raise AgentCardFetchError(
            f"Network error fetching from central registry: {e}"
        ) from e
    except Exception as e:
        raise AgentCardError(
            f"Unexpected error fetching from central registry: {e}"
        ) from e
    
    # Step 2: Fetch list of active peer registries
    logger.info("Fetching list of active peer registries")
    try:
        peers_api_url = f"{central_registry_url.rstrip('/')}/api/v1/federation/peers"
        response = await client.get(peers_api_url)
        response.raise_for_status()
        
        peers_data = response.json()
        active_peers = peers_data.get("items", [])
        logger.info(f"Found {len(active_peers)} active peer registries")
        
    except httpx.HTTPStatusError as e:
        logger.warning(
            f"Failed to fetch peer registries list. Status: {e.response.status_code}. "
            "Continuing with central registry results only."
        )
        return results
    except httpx.RequestError as e:
        logger.warning(
            f"Network error fetching peer registries list: {e}. "
            "Continuing with central registry results only."
        )
        return results
    except Exception as e:
        logger.warning(
            f"Unexpected error fetching peer registries: {e}. "
            "Continuing with central registry results only."
        )
        return results
    
    # Step 3: Query each active peer registry
    for peer in active_peers:
        peer_name = peer.get("name", "Unknown")
        peer_base_url = peer.get("base_url", "")
        peer_id = peer.get("id")
        discovery_auth_info = peer.get("discovery_auth_info", {})
        
        if not peer_base_url:
            logger.warning(f"Peer registry '{peer_name}' has no base_url, skipping")
            continue
        
        logger.info(f"Querying peer: {peer_name} at {peer_base_url}")
        
        # Prepare authentication headers
        auth_headers = {}
        auth_type = discovery_auth_info.get("type", "none")
        
        # Construct service_id for KeyManager
        service_id = f"peer_registry:{peer_id}" if peer_id else f"peer_registry:{peer_name}"
        
        if auth_type == "api_key":
            # API Key authentication
            api_key = key_manager.get_key(service_id)
            if not api_key:
                logger.warning(
                    f"No API key found for peer '{peer_name}' (service_id: {service_id}). "
                    f"Skipping this peer. Configure with: agentvault config set {service_id} --key <API_KEY>"
                )
                continue
            
            header_name = discovery_auth_info.get("api_key_header_name", "X-API-Key")
            auth_headers[header_name] = api_key
            
        elif auth_type == "oauth2_client_credentials":
            # OAuth2 client credentials flow
            client_id = key_manager.get_oauth_client_id(service_id)
            client_secret = key_manager.get_oauth_client_secret(service_id)
            
            if not client_id or not client_secret:
                logger.warning(
                    f"OAuth credentials not found for peer '{peer_name}' (service_id: {service_id}). "
                    f"Skipping this peer. Configure with: agentvault config set {service_id} --oauth-configure"
                )
                continue
            
            # Perform OAuth2 token request
            token_url = discovery_auth_info.get("token_url")
            if not token_url:
                logger.warning(f"No token_url in discovery_auth_info for peer '{peer_name}', skipping")
                continue
            
            try:
                token_data = {
                    "grant_type": "client_credentials",
                    "client_id": client_id,
                    "client_secret": client_secret
                }
                
                # Add required scopes if specified
                required_scopes = discovery_auth_info.get("required_scopes", [])
                if required_scopes:
                    token_data["scope"] = " ".join(required_scopes)
                
                token_response = await client.post(token_url, data=token_data)
                token_response.raise_for_status()
                
                token_info = token_response.json()
                access_token = token_info.get("access_token")
                
                if not access_token:
                    logger.warning(f"No access_token in OAuth response for peer '{peer_name}', skipping")
                    continue
                
                auth_headers["Authorization"] = f"Bearer {access_token}"
                
            except Exception as e:
                logger.warning(f"OAuth token acquisition failed for peer '{peer_name}': {e}, skipping")
                continue
        
        elif auth_type != "none":
            logger.warning(f"Unknown auth type '{auth_type}' for peer '{peer_name}', skipping")
            continue
        
        # Query the peer registry
        try:
            peer_api_url = f"{peer_base_url.rstrip('/')}/api/v1/agent-cards"
            headers = {**auth_headers}  # Copy auth headers
            
            peer_response = await client.get(
                peer_api_url,
                params=base_params,
                headers=headers,
                timeout=15.0  # Reasonable timeout for peer queries
            )
            peer_response.raise_for_status()
            
            peer_data = peer_response.json()
            peer_items = peer_data.get("items", [])
            
            # Add origin registry name to each item
            for item in peer_items:
                item["origin_registry_name"] = peer_name
            
            results.extend(peer_items)
            logger.info(f"Retrieved {len(peer_items)} agents from peer '{peer_name}'")
            
        except httpx.HTTPStatusError as e:
            logger.error(
                f"HTTP error querying peer '{peer_name}': "
                f"Status {e.response.status_code}, skipping this peer"
            )
        except httpx.RequestError as e:
            logger.error(f"Network error querying peer '{peer_name}': {e}, skipping this peer")
        except Exception as e:
            logger.error(f"Unexpected error querying peer '{peer_name}': {e}, skipping this peer")
    
    logger.info(f"Federated discovery complete. Total agents found: {len(results)}")
    return results


def parse_agent_card_from_dict(data: Dict[str, Any]) -> AgentCard:
    """
    Parses and validates Agent Card data from a dictionary.

    Args:
        data: A dictionary containing the Agent Card data.

    Returns:
        A validated AgentCard Pydantic model instance.

    Raises:
        AgentCardValidationError: If the provided data fails Pydantic validation.
        AgentCardError: For any other unexpected errors during parsing.
    """
    try:
        # Use Pydantic V2's model_validate method
        agent_card = AgentCard.model_validate(data)
        return agent_card
    except pydantic.ValidationError as e:
        # Wrap Pydantic's error in our custom exception
        raise AgentCardValidationError(f"Agent Card validation failed: {e}") from e
    except Exception as e:
        # Catch any other unexpected errors during parsing
        raise AgentCardError(f"An unexpected error occurred parsing the Agent Card data: {e}") from e


def load_agent_card_from_file(file_path: pathlib.Path) -> AgentCard:
    """
    Loads, parses, and validates an Agent Card from a local JSON file.

    Args:
        file_path: A pathlib.Path object pointing to the JSON file.

    Returns:
        A validated AgentCard Pydantic model instance.

    Raises:
        AgentCardError: If the file does not exist, is not a file,
                        cannot be read, or is not valid JSON.
        AgentCardValidationError: If the JSON content fails Agent Card validation.
    """
    if not isinstance(file_path, pathlib.Path):
         # Ensure input is a Path object for consistency
         file_path = pathlib.Path(file_path)

    if not file_path.exists():
        raise AgentCardError(f"Agent Card file not found at: {file_path}")
    if not file_path.is_file():
        raise AgentCardError(f"Path exists but is not a file: {file_path}")

    try:
        # Read the file content
        raw_content = file_path.read_text(encoding='utf-8')
        # Parse the JSON content
        data = json.loads(raw_content)
    except IOError as e:
        raise AgentCardError(f"Failed to read Agent Card file '{file_path}': {e}") from e
    except json.JSONDecodeError as e:
        raise AgentCardError(f"Failed to decode JSON from Agent Card file '{file_path}': {e}") from e
    except Exception as e:
        # Catch other potential errors during file reading/parsing
        raise AgentCardError(f"An unexpected error occurred loading Agent Card file '{file_path}': {e}") from e

    # Validate the loaded data using the dictionary parser
    return parse_agent_card_from_dict(data)


async def fetch_agent_card_from_url(
    url: str,
    http_client: Optional[httpx.AsyncClient] = None
) -> AgentCard:
    """
    Fetches, parses, and validates an Agent Card from a URL.

    Args:
        url: The URL to fetch the Agent Card JSON from.
        http_client: An optional httpx.AsyncClient instance for making the request.
                     If None, a temporary client will be created.

    Returns:
        A validated AgentCard Pydantic model instance.

    Raises:
        AgentCardFetchError: If there's a network error, the server returns a non-2xx
                             status code, or the response is not valid JSON.
                             This wraps httpx.RequestError and httpx.HTTPStatusError.
        AgentCardValidationError: If the fetched JSON content fails Agent Card validation.
        AgentCardError: For other unexpected errors during fetch/parse.
    """
    client_to_use: httpx.AsyncClient

    async def _fetch(client: httpx.AsyncClient):
        try:
            response = await client.get(url) # Can raise httpx.RequestError

            # Check for non-successful status codes first
            response.raise_for_status() # Can raise httpx.HTTPStatusError

            # Try parsing the JSON response
            try:
                data = response.json()
            except json.JSONDecodeError as e:
                # --- MODIFIED: Raise AgentCardFetchError here ---
                # This was the missing part causing the test failure
                raise AgentCardFetchError(f"Failed to decode JSON response from URL '{url}': {e}") from e
                # --- END MODIFIED ---

            # Validate the fetched data using the dictionary parser
            # Let AgentCardValidationError or AgentCardError propagate if raised
            return parse_agent_card_from_dict(data)

        # --- REVISED Exception Handling Order (Again) ---
        except httpx.HTTPStatusError as e:
            # Wrap HTTP status errors (4xx/5xx) specifically
            raise AgentCardFetchError(
                f"Failed to fetch Agent Card from URL '{url}'. Status: {e.response.status_code}. Response: {e.response.text}",
                status_code=e.response.status_code,
                response_body=e.response.text
            ) from e
        except httpx.RequestError as e:
            # Wrap network-related errors (DNS, connection, timeout, etc.)
            raise AgentCardFetchError(f"Network error fetching Agent Card from URL '{url}': {e}") from e
        # --- ADDED: Catch AgentCardFetchError specifically ---
        except AgentCardFetchError:
             # Re-raise fetch errors (like the JSON decode one) directly
             raise
        # --- END ADDED ---
        except AgentCardValidationError:
             # Re-raise validation errors directly if they came from parse_agent_card_from_dict
             raise
        except AgentCardError as e:
             # Re-raise other card-specific parsing errors
             raise AgentCardError(f"An error occurred processing the Agent Card data from '{url}': {e}") from e
        # --- ADDED: Catch respx errors specifically if respx is available ---
        except RespxMockError as e:
             # Let respx errors propagate during testing
             raise e
        # --- END ADDED ---
        except Exception as e:
            # Catch any other unexpected errors during fetch/parse and wrap
            raise AgentCardError(f"An unexpected error occurred fetching/processing Agent Card from '{url}': {e}") from e
        # --- END REVISED ---

    if http_client:
        return await _fetch(http_client)
    else:
        # Create a temporary client if none was provided
        async with httpx.AsyncClient() as temp_client:
            return await _fetch(temp_client)

#
