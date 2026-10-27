"""
Locking functionality for the AgentVault library.

This module provides the core functions for agents to lock and manage
their units within the AgentVault ecosystem.
"""

import httpx
import logging
from typing import Dict, Any, Optional
from decimal import Decimal

from .exceptions import AgentVaultError

logger = logging.getLogger(__name__)

# Default timeout for HTTP requests
DEFAULT_TIMEOUT = 30.0


async def stake_tokens(
    client: httpx.AsyncClient,
    amount: Decimal,
    registry_url: str = "https://registry.theprotocol.cloud",
    timeout: float = DEFAULT_TIMEOUT
) -> Dict[str, Any]:
    """
    Lock units in the AgentVault ecosystem.
    
    This function allows an agent to lock their units, which is required
    for participation in governance and other advanced features.
    
    Args:
        client: An authenticated httpx.AsyncClient with proper headers
        amount: The amount of units to lock (as Decimal for precision)
        registry_url: The base URL of the registry API
        timeout: HTTP request timeout in seconds
        
    Returns:
        A dictionary containing the lock transaction details:
        - transaction_id: Unique identifier for the lock transaction
        - amount_staked: The amount that was locked
        - new_balance: The new locked balance after this transaction
        - timestamp: When the locking occurred
        
    Raises:
        AgentVaultError: If locking fails for any reason, including:
            - Insufficient balance
            - Invalid amount
            - Network errors
            - Server errors
            
    Example:
        >>> async with httpx.AsyncClient() as client:
        ...     result = await stake_tokens(client, Decimal("100.0"))
        ...     print(f"Locked {result['amount_staked']} units")
    """
    if amount <= 0:
        raise AgentVaultError("Lock amount must be positive")
    
    # Prepare request payload
    payload = {
        "amount": str(amount)  # Convert Decimal to string for JSON serialization
    }
    
    url = f"{registry_url}/api/v1/staking/stake"
    
    logger.info(f"Attempting to lock {amount} units")
    
    try:
        response = await client.post(
            url,
            json=payload,
            timeout=timeout
        )
        
        # Handle successful response
        if response.status_code == 200:
            data = response.json()
            logger.info(f"Successfully locked {amount} units. Transaction ID: {data.get('transaction_id')}")
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
                    f"Insufficient balance to lock {amount} units",
                    status_code=400,
                    response_body=error_data if 'error_data' in locals() else detail
                )
            else:
                raise AgentVaultError(
                    f"Invalid lock request: {detail}",
                    status_code=400,
                    response_body=error_data if 'error_data' in locals() else detail
                )
        
        elif response.status_code == 401:
            raise AgentVaultError(
                "Authentication required for locking",
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
            f"Request to lock units timed out after {timeout} seconds"
        )
    
    except httpx.NetworkError as e:
        raise AgentVaultError(
            f"Network error while locking units: {e}"
        )
    
    except httpx.RequestError as e:
        raise AgentVaultError(
            f"Error making lock request: {e}"
        )
    
    except AgentVaultError:
        # Re-raise AgentVaultErrors as-is
        raise
    
    except Exception as e:
        # Catch any other unexpected errors
        logger.exception("Unexpected error during locking")
        raise AgentVaultError(
            f"Unexpected error during locking: {type(e).__name__}: {e}"
        )


async def unstake_tokens(
    client: httpx.AsyncClient,
    amount: Decimal,
    registry_url: str = "https://registry.theprotocol.cloud",
    timeout: float = DEFAULT_TIMEOUT
) -> Dict[str, Any]:
    """
    Unlock units from the AgentVault ecosystem.
    
    This function allows an agent to unlock their previously locked units.
    Note that there may be a cooldown period before units become available.
    
    Args:
        client: An authenticated httpx.AsyncClient with proper headers
        amount: The amount of units to unlock (as Decimal for precision)
        registry_url: The base URL of the registry API
        timeout: HTTP request timeout in seconds
        
    Returns:
        A dictionary containing the unlock transaction details:
        - transaction_id: Unique identifier for the unlock transaction
        - amount_unstaked: The amount that was unlocked
        - new_balance: The new locked balance after this transaction
        - cooldown_end: When the units will be available for withdrawal
        - timestamp: When the unlocking occurred
        
    Raises:
        AgentVaultError: If unlocking fails for any reason, including:
            - Insufficient locked balance
            - Invalid amount
            - Network errors
            - Server errors
            
    Example:
        >>> async with httpx.AsyncClient() as client:
        ...     result = await unstake_tokens(client, Decimal("50.0"))
        ...     print(f"Unlocked {result['amount_unstaked']} units")
    """
    if amount <= 0:
        raise AgentVaultError("Unlock amount must be positive")
    
    # Prepare request payload
    payload = {
        "amount": str(amount)  # Convert Decimal to string for JSON serialization
    }
    
    url = f"{registry_url}/api/v1/staking/unstake"
    
    logger.info(f"Attempting to unlock {amount} units")
    
    try:
        response = await client.post(
            url,
            json=payload,
            timeout=timeout
        )
        
        # Handle successful response
        if response.status_code == 200:
            data = response.json()
            logger.info(f"Successfully unlocked {amount} units. Transaction ID: {data.get('transaction_id')}")
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
                    f"Insufficient locked balance to unlock {amount} units",
                    status_code=400,
                    response_body=error_data if 'error_data' in locals() else detail
                )
            else:
                raise AgentVaultError(
                    f"Invalid unlock request: {detail}",
                    status_code=400,
                    response_body=error_data if 'error_data' in locals() else detail
                )
        
        elif response.status_code == 401:
            raise AgentVaultError(
                "Authentication required for unlocking",
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
            f"Request to unlock units timed out after {timeout} seconds"
        )
    
    except httpx.NetworkError as e:
        raise AgentVaultError(
            f"Network error while unlocking units: {e}"
        )
    
    except httpx.RequestError as e:
        raise AgentVaultError(
            f"Error making unlock request: {e}"
        )
    
    except AgentVaultError:
        # Re-raise AgentVaultErrors as-is
        raise
    
    except Exception as e:
        # Catch any other unexpected errors
        logger.exception("Unexpected error during unlocking")
        raise AgentVaultError(
            f"Unexpected error during unlocking: {type(e).__name__}: {e}"
        )


async def get_staking_balance(
    client: httpx.AsyncClient,
    registry_url: str = "https://registry.theprotocol.cloud",
    timeout: float = DEFAULT_TIMEOUT
) -> Dict[str, Any]:
    """
    Get the current locked balance and status for an agent.
    
    This function retrieves the complete lock status including locked balance,
    pending unlocks, and available balance.
    
    Args:
        client: An authenticated httpx.AsyncClient with proper headers
        registry_url: The base URL of the registry API
        timeout: HTTP request timeout in seconds
        
    Returns:
        A dictionary containing the lock status:
        - staked_balance: Current amount of locked units
        - pending_unstake: Amount of units in cooldown period
        - available_balance: Amount of units available for locking
        - total_balance: Total balance (locked + pending + available)
        - voting_power: Current voting power in governance
        - last_updated: When the balance was last updated
        
    Raises:
        AgentVaultError: If retrieval fails for any reason, including:
            - Authentication errors
            - Network errors
            - Server errors
            
    Example:
        >>> async with httpx.AsyncClient() as client:
        ...     balance = await get_staking_balance(client)
        ...     print(f"Locked: {balance['staked_balance']} units")
    """
    url = f"{registry_url}/api/v1/staking/balance"
    
    logger.info("Retrieving locked balance")
    
    try:
        response = await client.get(
            url,
            timeout=timeout
        )
        
        # Handle successful response
        if response.status_code == 200:
            data = response.json()
            logger.info(f"Successfully retrieved locked balance: {data.get('staked_balance')} locked")
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
                "Authentication required to view locked balance",
                status_code=401,
                response_body=error_data if 'error_data' in locals() else detail
            )
        
        elif response.status_code == 404:
            raise AgentVaultError(
                "Agent not found or has no lock history",
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
            f"Request to get locked balance timed out after {timeout} seconds"
        )
    
    except httpx.NetworkError as e:
        raise AgentVaultError(
            f"Network error while retrieving locked balance: {e}"
        )
    
    except httpx.RequestError as e:
        raise AgentVaultError(
            f"Error making balance request: {e}"
        )
    
    except AgentVaultError:
        # Re-raise AgentVaultErrors as-is
        raise
    
    except Exception as e:
        # Catch any other unexpected errors
        logger.exception("Unexpected error retrieving locked balance")
        raise AgentVaultError(
            f"Unexpected error retrieving balance: {type(e).__name__}: {e}"
        )
