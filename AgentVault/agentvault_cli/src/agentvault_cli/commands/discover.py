import asyncclick as click
import httpx
import logging
from typing import Optional, List, Dict, Any

# Import local utilities
from .. import utils

# Import agent card utilities and KeyManager from the library
from agentvault.agent_card_utils import discover_agents_federated
from agentvault.key_manager import KeyManager

logger = logging.getLogger(__name__)

# Placeholder for the default registry URL.
# TODO: Make this configurable, perhaps via a config file or environment variable.
DEFAULT_REGISTRY_URL = "http://localhost:8000" # Default for local development

@click.command("discover")
@click.argument("search_query", required=False, type=str)
@click.option(
    "--registry",
    "registry_url",
    default=DEFAULT_REGISTRY_URL,
    help="URL of the AgentVault Registry API.",
    show_default=True,
    envvar="AGENTVAULT_REGISTRY_URL" # Allow overriding via env var
)
@click.option(
    "--limit",
    default=25,
    type=click.IntRange(1, 100),
    help="Maximum number of results per page.",
    show_default=True
)
@click.option(
    "--offset",
    default=0,
    type=click.IntRange(0),
    help="Number of results to skip (for pagination).",
    show_default=True
)
@click.option(
    "--federated/--no-federated",
    default=False,
    help="Enable federated discovery across peer registries.",
    show_default=True
)
@click.pass_context # Pass context for exiting on error
async def discover_command(
    ctx: click.Context,
    search_query: Optional[str],
    registry_url: str,
    limit: int,
    offset: int,
    federated: bool
):
    """
    Discover agents listed in the AgentVault Registry.

    Optionally provide a SEARCH_QUERY to filter agents by name or description.
    
    Use --federated to search across all active peer registries in addition to the central registry.
    """
    if federated:
        utils.display_info(f"Discovering agents from central registry and peer registries: {registry_url}")
    else:
        utils.display_info(f"Discovering agents from registry: {registry_url}")
    
    if search_query:
        utils.display_info(f"Searching for: '{search_query}'")

    api_endpoint = f"{registry_url.rstrip('/')}/api/v1/agent-cards"
    params: Dict[str, Any] = {
        "limit": limit,
        "offset": offset,
        "active_only": True # Default to searching active agents
    }
    if search_query:
        params["search"] = search_query

    try:
        async with httpx.AsyncClient() as client:
            if federated:
                # Use federated discovery
                try:
                    # Initialize KeyManager
                    key_manager = KeyManager()
                    
                    # Call federated discovery function
                    items = await discover_agents_federated(
                        client=client,
                        central_registry_url=registry_url,
                        key_manager=key_manager,
                        search_query=search_query,
                        limit_per_registry=limit,
                        offset_per_registry=offset
                    )
                    
                    if not items:
                        utils.display_info("No matching agents found across all registries.")
                        return
                    
                    # Prepare data for table display with origin registry column
                    table_data = [
                        [
                            item.get("id"),
                            item.get("name"),
                            item.get("description", ""),
                            item.get("origin_registry_name", "Unknown")
                        ]
                        for item in items
                    ]
                    
                    # Count items by registry
                    registry_counts = {}
                    for item in items:
                        origin = item.get("origin_registry_name", "Unknown")
                        registry_counts[origin] = registry_counts.get(origin, 0) + 1
                    
                    utils.display_table(
                        f"Found Agents (Federated Search)",
                        ["ID", "Name", "Description", "Origin Registry"],
                        table_data
                    )
                    
                    # Display summary
                    utils.display_info(f"\nTotal agents found: {len(items)}")
                    for registry, count in registry_counts.items():
                        utils.display_info(f"  - {registry}: {count} agents")
                    
                except Exception as e:
                    utils.display_error(f"Federated discovery failed: {e}")
                    logger.exception("Error in federated discovery")
                    ctx.exit(1)
            
            else:
                # Use standard non-federated discovery
                response = await client.get(api_endpoint, params=params, timeout=15.0)

                # Check for HTTP errors
                if response.status_code != 200:
                    utils.display_error(f"Registry API request failed (Status {response.status_code}):")
                    try:
                        # Try to display error detail from response if available
                        error_detail = response.json().get("detail", response.text)
                        utils.display_error(f"  Detail: {error_detail}")
                    except Exception:
                        utils.display_error(f"  Response: {response.text[:500]}") # Show raw text on JSON error
                    ctx.exit(1)

                # Process successful response
                try:
                    data = response.json()
                    items = data.get("items", [])
                    pagination = data.get("pagination")

                    if not items:
                        utils.display_info("No matching agents found.")
                        return

                    # Prepare data for table display
                    table_data = [
                        [item.get("id"), item.get("name"), item.get("description", "")]
                        for item in items
                    ]
                    utils.display_table(
                        f"Found Agents (Page {pagination.get('current_page', '?') if pagination else '?'})",
                        ["ID", "Name", "Description"],
                        table_data
                    )

                    # Display pagination info
                    if pagination:
                        utils.display_info(
                            f"\nShowing {len(items)} items (offset {pagination.get('offset', 0)}) "
                            f"out of {pagination.get('total_items', 0)} total. "
                            f"Page {pagination.get('current_page', '?')} of {pagination.get('total_pages', '?')}."
                        )
                        if pagination.get('offset', 0) + limit < pagination.get('total_items', 0):
                             next_offset = pagination.get('offset', 0) + limit
                             utils.display_info(f"Hint: Use '--offset {next_offset}' to view the next page.")
                    else:
                        utils.display_warning("Pagination information missing in registry response.")

                except Exception as e: # Catch JSON decoding errors or unexpected structure
                    utils.display_error(f"Failed to parse registry response: {e}")
                    logger.error(f"Response text: {response.text[:500]}...") # Log partial response
                    ctx.exit(1)

    except httpx.RequestError as e:
        utils.display_error(f"Network error connecting to registry at {registry_url}: {e}")
        ctx.exit(1)
    except Exception as e:
        utils.display_error(f"An unexpected error occurred during discovery: {e}")
        logger.exception("Unexpected error in discover command")
        ctx.exit(1)
