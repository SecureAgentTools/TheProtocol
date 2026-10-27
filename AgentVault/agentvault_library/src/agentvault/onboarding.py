"""
Agent onboarding functionality for the AgentVault library.

This module provides the core function for agents to register themselves
with the AgentVault Registry using a bootstrap token obtained by their creator.
"""

import httpx
import logging
from typing import Dict, Any, Tuple, Optional
from urllib.parse import urlparse

from .exceptions import OnboardingError

logger = logging.getLogger(__name__)

# Default timeout for HTTP requests
DEFAULT_TIMEOUT = 30.0


async def register_agent_with_bootstrap_token(
    registry_onboarding_url: str,
    bootstrap_token: str,
    did_method: str = "cos",
    pow_challenge_response: Optional[str] = None,
    timeout: float = DEFAULT_TIMEOUT
) -> Tuple[str, str, str]:
    """
    Register an agent with the AgentVault Registry using a bootstrap token.
    
    This function completes the second phase of the two-phase onboarding protocol.
    It exchanges a single-use bootstrap token for permanent agent credentials.
    
    Args:
        registry_onboarding_url: The full URL to the registry's onboarding endpoint
                                (e.g., "https://registry.theprotocol.cloud/api/v1/onboard/register")
        bootstrap_token: The single-use token obtained by the agent's creator
        did_method: The DID method to use for agent identity (default: "cos" for Concierge-OS)
        pow_challenge_response: Optional proof-of-work response if required by the registry
        timeout: HTTP request timeout in seconds
        
    Returns:
        A tuple of (agent_id, client_id, client_secret) representing the agent's
        new identity and OAuth2 credentials.
        
    Raises:
        OnboardingError: If registration fails for any reason, including:
            - Invalid or expired bootstrap token
            - Network errors
            - Server errors
            - Invalid DID method
            
    Example:
        >>> agent_id, client_id, client_secret = await register_agent_with_bootstrap_token(
        ...     "https://registry.theprotocol.cloud/api/v1/onboard/register",
        ...     "bst_a1b2c3d4_e5f6g7h8"
        ... )
        >>> print(f"Agent registered with ID: {agent_id}")
    """
    # Validate inputs
    if not registry_onboarding_url:
        raise OnboardingError("Registry onboarding URL cannot be empty")
    
    if not bootstrap_token:
        raise OnboardingError("Bootstrap token cannot be empty")
    
    # Validate URL format
    try:
        parsed_url = urlparse(registry_onboarding_url)
        if not parsed_url.scheme or not parsed_url.netloc:
            raise ValueError("Invalid URL format")
    except Exception as e:
        raise OnboardingError(f"Invalid registry URL: {e}")
    
    # Prepare request payload
    payload = {
        "agent_did_method": did_method
    }
    
    if pow_challenge_response:
        payload["proof_of_work_solution"] = pow_challenge_response
    
    # Prepare headers
    headers = {
        "Bootstrap-Token": bootstrap_token,
        "Content-Type": "application/json"
    }
    
    logger.info(f"Attempting to register agent with registry at {registry_onboarding_url}")
    
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                registry_onboarding_url,
                json=payload,
                headers=headers
            )
            
            # Log response status for debugging
            logger.debug(f"Registry response status: {response.status_code}")
            
            # Handle successful response
            if response.status_code == 201:
                try:
                    data = response.json()
                    
                    # Extract required fields
                    agent_did = data.get("agent_did")
                    client_id = data.get("client_id")
                    client_secret = data.get("client_secret")
                    
                    # Validate response data
                    if not all([agent_did, client_id, client_secret]):
                        missing_fields = []
                        if not agent_did:
                            missing_fields.append("agent_did")
                        if not client_id:
                            missing_fields.append("client_id")
                        if not client_secret:
                            missing_fields.append("client_secret")
                        
                        raise OnboardingError(
                            f"Registry response missing required fields: {', '.join(missing_fields)}",
                            status_code=201,
                            response_body=data
                        )
                    
                    logger.info(f"Successfully registered agent with DID: {agent_did}")
                    return agent_did, client_id, client_secret
                    
                except ValueError as e:
                    raise OnboardingError(
                        f"Invalid JSON response from registry: {e}",
                        status_code=response.status_code,
                        response_body=response.text
                    )
            
            # Handle error responses
            try:
                error_data = response.json()
                detail = error_data.get("detail", "Unknown error")
            except:
                detail = response.text or "No error details provided"
            
            # Map status codes to meaningful error messages
            if response.status_code == 400:
                if "expired" in detail.lower():
                    raise OnboardingError(
                        "Bootstrap token has expired",
                        status_code=400,
                        response_body=error_data if 'error_data' in locals() else detail
                    )
                elif "invalid" in detail.lower():
                    raise OnboardingError(
                        "Invalid bootstrap token",
                        status_code=400,
                        response_body=error_data if 'error_data' in locals() else detail
                    )
                elif "used" in detail.lower():
                    raise OnboardingError(
                        "Bootstrap token has already been used",
                        status_code=400,
                        response_body=error_data if 'error_data' in locals() else detail
                    )
                else:
                    raise OnboardingError(
                        f"Bad request: {detail}",
                        status_code=400,
                        response_body=error_data if 'error_data' in locals() else detail
                    )
            
            elif response.status_code == 401:
                raise OnboardingError(
                    "Missing or invalid Bootstrap-Token header",
                    status_code=401,
                    response_body=error_data if 'error_data' in locals() else detail
                )
            
            elif response.status_code == 422:
                raise OnboardingError(
                    f"Invalid request format: {detail}",
                    status_code=422,
                    response_body=error_data if 'error_data' in locals() else detail
                )
            
            elif response.status_code == 429:
                raise OnboardingError(
                    "Rate limit exceeded. Please try again later",
                    status_code=429,
                    response_body=error_data if 'error_data' in locals() else detail
                )
            
            elif response.status_code >= 500:
                raise OnboardingError(
                    f"Registry server error: {detail}",
                    status_code=response.status_code,
                    response_body=error_data if 'error_data' in locals() else detail
                )
            
            else:
                raise OnboardingError(
                    f"Unexpected response from registry (status {response.status_code}): {detail}",
                    status_code=response.status_code,
                    response_body=error_data if 'error_data' in locals() else detail
                )
    
    except httpx.TimeoutException:
        raise OnboardingError(
            f"Request to registry timed out after {timeout} seconds"
        )
    
    except httpx.NetworkError as e:
        raise OnboardingError(
            f"Network error while connecting to registry: {e}"
        )
    
    except httpx.RequestError as e:
        raise OnboardingError(
            f"Error making request to registry: {e}"
        )
    
    except OnboardingError:
        # Re-raise OnboardingErrors as-is
        raise
    
    except Exception as e:
        # Catch any other unexpected errors
        logger.exception("Unexpected error during agent registration")
        raise OnboardingError(
            f"Unexpected error during registration: {type(e).__name__}: {e}"
        )
