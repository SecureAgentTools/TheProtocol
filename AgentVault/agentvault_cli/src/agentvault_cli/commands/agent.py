"""
Agent-related commands for the AgentVault CLI.

This module provides commands for agent management including the onboarding
process that allows creators to generate bootstrap tokens for their agents.
"""

import asyncclick as click
import httpx
import asyncio
import logging
import json
from typing import Optional, Dict, Any
from datetime import datetime
import webbrowser
import urllib.parse

from .. import utils
from .. import config

logger = logging.getLogger(__name__)


@click.group("agent")
def agent_group():
    """
    Manage agents and their lifecycle in the AgentVault ecosystem.
    
    Provides commands for agent onboarding, registration, and management.
    """
    pass


@agent_group.command("onboard")
@click.option(
    "--registry-url",
    default=config.REGISTRY_API_BASE,
    help="Override the default registry API URL",
    show_default=True
)
@click.option(
    "--agent-type",
    default=None,
    help="Optional hint about the type of agent being onboarded"
)
@click.option(
    "--requested-by",
    default=None,
    help="Optional identifier for the entity requesting the token"
)
@click.option(
    "--no-browser",
    is_flag=True,
    help="Don't automatically open the browser for authentication"
)
async def onboard_agent(
    registry_url: str,
    agent_type: Optional[str],
    requested_by: Optional[str],
    no_browser: bool
):
    """
    Generate a bootstrap token for onboarding a new agent.
    
    This command implements the OAuth 2.0 Device Authorization Flow to
    authenticate the creator, then requests a bootstrap token from the
    AgentVault Registry that can be used to register a new agent.
    
    The bootstrap token is single-use and time-limited (default: 5 minutes).
    """
    utils.display_info("Starting agent onboarding process...")
    
    # Step 1: Initiate Device Authorization Flow
    try:
        device_code_data = await _request_device_code()
    except Exception as e:
        utils.display_error(f"Failed to initiate device authorization: {e}")
        raise click.ClickException("Device authorization failed")
    
    # Display user instructions
    utils.display_info("\n" + "=" * 60)
    utils.display_info("AUTHENTICATION REQUIRED")
    utils.display_info("=" * 60)
    utils.display_info(f"Please visit: {device_code_data['verification_uri']}")
    utils.display_info(f"And enter code: {device_code_data['user_code']}")
    utils.display_info("=" * 60 + "\n")
    
    # Optionally open browser
    if not no_browser:
        try:
            webbrowser.open(device_code_data['verification_uri'])
            utils.display_info("Browser opened automatically. If it didn't work, please visit the URL manually.")
        except Exception:
            utils.display_info("Could not open browser automatically. Please visit the URL manually.")
    
    # Step 2: Poll for token
    utils.display_info("Waiting for authentication...")
    try:
        access_token = await _poll_for_token(
            device_code_data['device_code'],
            device_code_data.get('interval', 5)
        )
    except Exception as e:
        utils.display_error(f"Authentication failed: {e}")
        raise click.ClickException("Failed to obtain access token")
    
    utils.display_success("Authentication successful!")
    
    # Step 3: Request bootstrap token
    utils.display_info("Requesting bootstrap token from registry...")
    try:
        bootstrap_data = await _request_bootstrap_token(
            registry_url,
            access_token,
            agent_type,
            requested_by
        )
    except Exception as e:
        utils.display_error(f"Failed to obtain bootstrap token: {e}")
        raise click.ClickException("Bootstrap token request failed")
    
    # Display results
    utils.display_info("\n" + "=" * 80)
    utils.display_success("BOOTSTRAP TOKEN GENERATED SUCCESSFULLY")
    utils.display_info("=" * 80)
    
    # Format expiration time
    expires_at = datetime.fromisoformat(bootstrap_data['expires_at'].replace('Z', '+00:00'))
    expires_in_seconds = int((expires_at - datetime.utcnow()).total_seconds())
    
    # Display token info in a secure, highlighted manner
    utils.display_info("\n🔐 Bootstrap Token (KEEP THIS SECRET):")
    utils.display_warning(f"   {bootstrap_data['bootstrap_token']}")
    
    utils.display_info("\n🔗 Onboarding URL:")
    utils.display_info(f"   {bootstrap_data['onboarding_url']}")
    
    utils.display_info(f"\n⏱️  Token expires in: {expires_in_seconds} seconds")
    utils.display_info(f"   Expiration time: {expires_at.isoformat()}")
    
    if bootstrap_data.get('agent_type_hint'):
        utils.display_info(f"\n📋 Agent type hint: {bootstrap_data['agent_type_hint']}")
    
    utils.display_info("\n" + "=" * 80)
    utils.display_warning("\n⚠️  IMPORTANT: This token is single-use and will expire!")
    utils.display_info("Share this token and URL with your agent to complete registration.")
    utils.display_info("\nYour agent should use the agentvault_library.register_agent_with_bootstrap_token()")
    utils.display_info("function to complete the onboarding process.\n")


async def _request_device_code() -> Dict[str, Any]:
    """Request a device code from the OAuth authorization server."""
    async with httpx.AsyncClient(timeout=config.HTTP_TIMEOUT) as client:
        response = await client.post(
            config.OAUTH_DEVICE_AUTH_URL,
            data={
                "client_id": config.OAUTH_CLIENT_ID,
                "scope": "registry:write"
            }
        )
        
        if response.status_code != 200:
            raise Exception(f"Server returned {response.status_code}: {response.text}")
        
        return response.json()


async def _poll_for_token(device_code: str, interval: int) -> str:
    """Poll the OAuth token endpoint until the user completes authentication."""
    async with httpx.AsyncClient(timeout=config.HTTP_TIMEOUT) as client:
        while True:
            try:
                response = await client.post(
                    config.OAUTH_TOKEN_URL,
                    data={
                        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                        "device_code": device_code,
                        "client_id": config.OAUTH_CLIENT_ID
                    }
                )
                
                data = response.json()
                
                if response.status_code == 200:
                    return data['access_token']
                
                error = data.get('error')
                if error == 'authorization_pending':
                    # User hasn't authorized yet, keep polling
                    await asyncio.sleep(interval)
                    continue
                elif error == 'slow_down':
                    # Increase polling interval
                    interval += 5
                    await asyncio.sleep(interval)
                    continue
                elif error == 'expired_token':
                    raise Exception("The device code has expired. Please restart the process.")
                elif error == 'access_denied':
                    raise Exception("Authorization was denied by the user.")
                else:
                    raise Exception(f"OAuth error: {error} - {data.get('error_description', '')}")
                    
            except httpx.TimeoutException:
                utils.display_warning("Request timed out, retrying...")
                await asyncio.sleep(interval)
                continue
            except httpx.RequestError as e:
                utils.display_warning(f"Network error: {e}, retrying...")
                await asyncio.sleep(interval)
                continue


async def _request_bootstrap_token(
    registry_url: str,
    access_token: str,
    agent_type: Optional[str],
    requested_by: Optional[str]
) -> Dict[str, Any]:
    """Request a bootstrap token from the registry API."""
    url = f"{registry_url}/api/v1/onboard/bootstrap/request-token"
    
    # Build request payload
    payload = {}
    if agent_type:
        payload['agent_type_hint'] = agent_type
    if requested_by:
        payload['requested_by'] = requested_by
    
    async with httpx.AsyncClient(timeout=config.HTTP_TIMEOUT) as client:
        response = await client.post(
            url,
            json=payload,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }
        )
        
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 401:
            raise Exception("Authentication failed. Your access token may be invalid.")
        elif response.status_code == 403:
            error_detail = response.json().get('detail', 'Unknown error')
            raise Exception(f"Permission denied: {error_detail}")
        elif response.status_code == 429:
            raise Exception("Rate limit exceeded. Please try again later.")
        else:
            error_detail = response.json().get('detail', response.text)
            raise Exception(f"Server returned {response.status_code}: {error_detail}")
