"""
Locking commands for the AgentVault CLI.

This module provides commands for agents to lock and manage their units
through command-line interface.
"""

import asyncclick as click
import httpx
import logging
from decimal import Decimal
from typing import Optional

from .. import utils
from .. import config

# Import AgentVault library components
try:
    from agentvault import stake_tokens, unstake_tokens, get_staking_balance
    from agentvault.exceptions import AgentVaultError
    _agentvault_lib_imported = True
except ImportError:
    _agentvault_lib_imported = False
    AgentVaultError = Exception  # Fallback for type hints

logger = logging.getLogger(__name__)


@click.group("stake")
def stake_group():
    """
    Manage locked units in the AgentVault ecosystem.
    
    Provides commands for locking, unlocking, and checking balances.
    Locking units is required for participating in governance.
    """
    pass


@stake_group.command("deposit")
@click.argument("amount", type=str)
@click.option(
    "--registry-url",
    default=config.REGISTRY_API_BASE,
    help="Override the default registry API URL",
    show_default=True
)
@click.pass_context
async def stake_tokens_cmd(
    ctx: click.Context,
    amount: str,
    registry_url: str
):
    """
    Lock units to participate in the AgentVault ecosystem.
    
    AMOUNT: The amount of units to lock (e.g., "100.0" or "50.5")
    
    Locking units:
    - Enables participation in governance voting
    - Increases your voting power based on locked amount
    - May be subject to cooldown periods for unlocking
    
    Example:
        agentvault stake deposit 100.0
    """
    if not _agentvault_lib_imported:
        utils.display_error("Cannot lock units: Failed to import the 'agentvault' library.")
        ctx.exit(1)
    
    # Validate and parse amount
    try:
        amount_decimal = Decimal(amount)
        if amount_decimal <= 0:
            utils.display_error("Amount must be positive")
            ctx.exit(1)
    except Exception as e:
        utils.display_error(f"Invalid amount format: {e}")
        ctx.exit(1)
    
    utils.display_info(f"Preparing to lock {amount_decimal} units...")
    
    # Get authentication token
    try:
        auth_token = await _get_auth_token()
    except Exception as e:
        utils.display_error(f"Failed to obtain authentication: {e}")
        ctx.exit(1)
    
    # Create authenticated client
    headers = {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json"
    }
    
    try:
        async with httpx.AsyncClient(
            timeout=config.HTTP_TIMEOUT,
            headers=headers
        ) as client:
            result = await stake_tokens(
                client=client,
                amount=amount_decimal,
                registry_url=registry_url
            )
            
            # Display success
            utils.display_success(f"Successfully locked {result['amount_staked']} units!")
            utils.display_info(f"Transaction ID: {result['transaction_id']}")
            utils.display_info(f"New locked balance: {result['new_balance']} units")
            
            if 'voting_power' in result:
                utils.display_info(f"Your voting power: {result['voting_power']}")
            
    except AgentVaultError as e:
        utils.display_error(f"Locking failed: {e}")
        ctx.exit(1)
    except Exception as e:
        utils.display_error(f"Unexpected error during locking: {e}")
        logger.exception("Unexpected error in stake deposit command")
        ctx.exit(1)


@stake_group.command("withdraw")
@click.argument("amount", type=str)
@click.option(
    "--registry-url",
    default=config.REGISTRY_API_BASE,
    help="Override the default registry API URL",
    show_default=True
)
@click.pass_context
async def unstake_tokens_cmd(
    ctx: click.Context,
    amount: str,
    registry_url: str
):
    """
    Unlock units from the AgentVault ecosystem.
    
    AMOUNT: The amount of units to unlock (e.g., "50.0" or "25.5")
    
    Important notes:
    - Unlocked units may be subject to a cooldown period
    - During cooldown, units cannot be used or transferred
    - Your voting power will be reduced immediately
    
    Example:
        agentvault stake withdraw 50.0
    """
    if not _agentvault_lib_imported:
        utils.display_error("Cannot unlock units: Failed to import the 'agentvault' library.")
        ctx.exit(1)
    
    # Validate and parse amount
    try:
        amount_decimal = Decimal(amount)
        if amount_decimal <= 0:
            utils.display_error("Amount must be positive")
            ctx.exit(1)
    except Exception as e:
        utils.display_error(f"Invalid amount format: {e}")
        ctx.exit(1)
    
    utils.display_info(f"Preparing to unlock {amount_decimal} units...")
    
    # Get authentication token
    try:
        auth_token = await _get_auth_token()
    except Exception as e:
        utils.display_error(f"Failed to obtain authentication: {e}")
        ctx.exit(1)
    
    # Create authenticated client
    headers = {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json"
    }
    
    try:
        async with httpx.AsyncClient(
            timeout=config.HTTP_TIMEOUT,
            headers=headers
        ) as client:
            result = await unstake_tokens(
                client=client,
                amount=amount_decimal,
                registry_url=registry_url
            )
            
            # Display success
            utils.display_success(f"Successfully unlocked {result['amount_unstaked']} units!")
            utils.display_info(f"Transaction ID: {result['transaction_id']}")
            utils.display_info(f"New locked balance: {result['new_balance']} units")
            
            if 'cooldown_end' in result:
                utils.display_warning(f"⏱️  Cooldown period ends: {result['cooldown_end']}")
                utils.display_info("Units will be available for withdrawal after the cooldown period.")
            
    except AgentVaultError as e:
        utils.display_error(f"Unlocking failed: {e}")
        ctx.exit(1)
    except Exception as e:
        utils.display_error(f"Unexpected error during unlocking: {e}")
        logger.exception("Unexpected error in stake withdraw command")
        ctx.exit(1)


@stake_group.command("balance")
@click.option(
    "--registry-url",
    default=config.REGISTRY_API_BASE,
    help="Override the default registry API URL",
    show_default=True
)
@click.option(
    "--detailed",
    is_flag=True,
    help="Show detailed breakdown of balances"
)
@click.pass_context
async def check_balance_cmd(
    ctx: click.Context,
    registry_url: str,
    detailed: bool
):
    """
    Check your current locked balance and status.
    
    Displays:
    - Current locked balance
    - Units in cooldown period
    - Available balance for locking
    - Current voting power
    
    Use --detailed for a complete breakdown.
    
    Example:
        agentvault stake balance
        agentvault stake balance --detailed
    """
    if not _agentvault_lib_imported:
        utils.display_error("Cannot check balance: Failed to import the 'agentvault' library.")
        ctx.exit(1)
    
    utils.display_info("Retrieving locked balance...")
    
    # Get authentication token
    try:
        auth_token = await _get_auth_token()
    except Exception as e:
        utils.display_error(f"Failed to obtain authentication: {e}")
        ctx.exit(1)
    
    # Create authenticated client
    headers = {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json"
    }
    
    try:
        async with httpx.AsyncClient(
            timeout=config.HTTP_TIMEOUT,
            headers=headers
        ) as client:
            balance = await get_staking_balance(
                client=client,
                registry_url=registry_url
            )
            
            # Display balance information
            utils.display_info("\n" + "=" * 60)
            utils.display_info("💰 LOCKED BALANCE SUMMARY")
            utils.display_info("=" * 60)
            
            # Basic balance info
            utils.display_info(f"Locked Balance: {balance['staked_balance']} units")
            
            if balance.get('pending_unstake', 0) > 0:
                utils.display_warning(f"Pending Unlock: {balance['pending_unstake']} units (in cooldown)")
            
            utils.display_info(f"Available Balance: {balance['available_balance']} units")
            utils.display_info(f"Total Balance: {balance['total_balance']} units")
            
            # Voting power
            if 'voting_power' in balance:
                utils.display_success(f"\n🗳️  Voting Power: {balance['voting_power']}")
            
            # Detailed view
            if detailed:
                utils.display_info("\n" + "-" * 60)
                utils.display_info("DETAILED BREAKDOWN")
                utils.display_info("-" * 60)
                
                # Show all fields from the response
                for key, value in balance.items():
                    if key not in ['staked_balance', 'pending_unstake', 'available_balance', 
                                  'total_balance', 'voting_power']:
                        utils.display_info(f"{key.replace('_', ' ').title()}: {value}")
            
            if 'last_updated' in balance:
                utils.display_info(f"\nLast Updated: {balance['last_updated']}")
            
            utils.display_info("=" * 60 + "\n")
            
    except AgentVaultError as e:
        utils.display_error(f"Failed to retrieve balance: {e}")
        ctx.exit(1)
    except Exception as e:
        utils.display_error(f"Unexpected error retrieving balance: {e}")
        logger.exception("Unexpected error in stake balance command")
        ctx.exit(1)


async def _get_auth_token() -> str:
    """
    Get authentication token for API requests.
    
    In a real implementation, this would:
    - Check for cached tokens
    - Initiate OAuth flow if needed
    - Return a valid bearer token
    
    For now, this is a placeholder that would integrate with
    the existing authentication system.
    """
    # TODO: Integrate with actual authentication system
    # This is a placeholder - in production, this would:
    # 1. Check for existing valid token
    # 2. Refresh if expired
    # 3. Initiate device flow if no token exists
    
    # For testing purposes, you might want to read from env var
    import os
    token = os.getenv("AGENTVAULT_AUTH_TOKEN")
    if not token:
        raise Exception(
            "No authentication token found. Please set AGENTVAULT_AUTH_TOKEN "
            "environment variable or implement proper OAuth flow."
        )
    return token
