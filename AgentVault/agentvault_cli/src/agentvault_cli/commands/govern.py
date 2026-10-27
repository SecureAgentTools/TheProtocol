"""
Governance commands for the AgentVault CLI.

This module provides commands for agents to participate in governance
including creating proposals and voting.
"""

import asyncclick as click
import httpx
import logging
from typing import Optional, List
import json

from .. import utils
from .. import config

# Import AgentVault library components
try:
    from agentvault import (
        create_proposal, cast_vote, get_proposal, list_proposals,
        VoteChoice
    )
    from agentvault.exceptions import AgentVaultError
    _agentvault_lib_imported = True
except ImportError:
    _agentvault_lib_imported = False
    AgentVaultError = Exception  # Fallback for type hints
    # Create dummy VoteChoice for type hints
    class VoteChoice:
        FOR = "for"
        AGAINST = "against"
        ABSTAIN = "abstain"

logger = logging.getLogger(__name__)


@click.group("govern")
def govern_group():
    """
    Participate in AgentVault governance.
    
    Create proposals, vote on active proposals, and view governance activity.
    Requires locked units for participation.
    """
    pass


@govern_group.command("create-proposal")
@click.option(
    "--title",
    required=True,
    help="Title of the proposal (max 200 characters)"
)
@click.option(
    "--description",
    required=True,
    help="Full description of the proposal"
)
@click.option(
    "--category",
    default="general",
    help="Category (general, technical, economic)",
    show_default=True
)
@click.option(
    "--tags",
    multiple=True,
    help="Tags for categorization (can be used multiple times)"
)
@click.option(
    "--registry-url",
    default=config.REGISTRY_API_BASE,
    help="Override the default registry API URL",
    show_default=True
)
@click.pass_context
async def create_proposal_cmd(
    ctx: click.Context,
    title: str,
    description: str,
    category: str,
    tags: tuple,
    registry_url: str
):
    """
    Create a new governance proposal.
    
    Requires sufficient locked units to create proposals.
    
    Examples:
        agentvault govern create-proposal --title "Raise the quorum" --description "Proposal to raise the quorum to 15%"
        
        agentvault govern create-proposal \\
            --title "Add new feature" \\
            --description "Detailed proposal for adding X feature..." \\
            --category technical \\
            --tags feature --tags enhancement
    """
    if not _agentvault_lib_imported:
        utils.display_error("Cannot create proposal: Failed to import the 'agentvault' library.")
        ctx.exit(1)
    
    # Validate inputs
    if len(title) > 200:
        utils.display_error("Title must not exceed 200 characters")
        ctx.exit(1)
    
    if len(description) > 10000:
        utils.display_error("Description must not exceed 10000 characters")
        ctx.exit(1)
    
    utils.display_info("Creating governance proposal...")
    utils.display_info(f"Title: {title}")
    utils.display_info(f"Category: {category}")
    if tags:
        utils.display_info(f"Tags: {', '.join(tags)}")
    
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
            result = await create_proposal(
                client=client,
                title=title,
                description=description,
                category=category,
                tags=list(tags) if tags else None,
                registry_url=registry_url
            )
            
            # Display success
            utils.display_success("\n✅ Proposal created successfully!")
            utils.display_info("\n" + "=" * 70)
            utils.display_info("PROPOSAL DETAILS")
            utils.display_info("=" * 70)
            utils.display_info(f"Proposal ID: {result['proposal_id']}")
            utils.display_info(f"Title: {result['title']}")
            utils.display_info(f"Status: {result['status']}")
            utils.display_info(f"Voting Start: {result['voting_start']}")
            utils.display_info(f"Voting End: {result['voting_end']}")
            utils.display_info("=" * 70)
            
            utils.display_info("\n📢 Share this proposal ID with the community to gather votes!")
            utils.display_info(f"   Command: agentvault govern vote {result['proposal_id']} --for")
            
    except AgentVaultError as e:
        utils.display_error(f"Failed to create proposal: {e}")
        ctx.exit(1)
    except Exception as e:
        utils.display_error(f"Unexpected error creating proposal: {e}")
        logger.exception("Unexpected error in govern create-proposal command")
        ctx.exit(1)


@govern_group.command("vote")
@click.argument("proposal_id")
@click.option(
    "--for",
    "vote_for",
    is_flag=True,
    help="Vote in favor of the proposal"
)
@click.option(
    "--against",
    "vote_against", 
    is_flag=True,
    help="Vote against the proposal"
)
@click.option(
    "--abstain",
    "vote_abstain",
    is_flag=True,
    help="Abstain from voting (counts for quorum)"
)
@click.option(
    "--comment",
    help="Optional comment explaining your vote (max 1000 chars)"
)
@click.option(
    "--registry-url",
    default=config.REGISTRY_API_BASE,
    help="Override the default registry API URL",
    show_default=True
)
@click.pass_context
async def vote_cmd(
    ctx: click.Context,
    proposal_id: str,
    vote_for: bool,
    vote_against: bool,
    vote_abstain: bool,
    comment: Optional[str],
    registry_url: str
):
    """
    Cast a vote on an active governance proposal.
    
    PROPOSAL_ID: The unique identifier of the proposal to vote on
    
    You must specify exactly one of: --for, --against, or --abstain
    
    Your voting power is determined by your locked balance.
    
    Examples:
        agentvault govern vote prop_123 --for
        agentvault govern vote prop_456 --against --comment "I disagree because..."
        agentvault govern vote prop_789 --abstain
    """
    if not _agentvault_lib_imported:
        utils.display_error("Cannot vote: Failed to import the 'agentvault' library.")
        ctx.exit(1)
    
    # Validate vote choice
    vote_count = sum([vote_for, vote_against, vote_abstain])
    if vote_count != 1:
        utils.display_error("You must specify exactly one of: --for, --against, or --abstain")
        ctx.exit(1)
    
    # Determine vote choice
    if vote_for:
        vote_choice = VoteChoice.FOR
        vote_display = "FOR"
    elif vote_against:
        vote_choice = VoteChoice.AGAINST
        vote_display = "AGAINST"
    else:
        vote_choice = VoteChoice.ABSTAIN
        vote_display = "ABSTAIN"
    
    # Validate comment length
    if comment and len(comment) > 1000:
        utils.display_error("Comment must not exceed 1000 characters")
        ctx.exit(1)
    
    utils.display_info(f"Preparing to vote {vote_display} on proposal: {proposal_id}")
    
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
            # First, get proposal details to show what we're voting on
            try:
                proposal = await get_proposal(
                    client=client,
                    proposal_id=proposal_id,
                    registry_url=registry_url
                )
                utils.display_info(f"\nProposal: {proposal['title']}")
                utils.display_info(f"Status: {proposal['status']}")
            except:
                # Continue even if we can't get proposal details
                pass
            
            # Cast the vote
            result = await cast_vote(
                client=client,
                proposal_id=proposal_id,
                vote=vote_choice,
                comment=comment,
                registry_url=registry_url
            )
            
            # Display success
            utils.display_success(f"\n✅ Vote cast successfully!")
            utils.display_info(f"Vote ID: {result['vote_id']}")
            utils.display_info(f"Your vote: {vote_display}")
            utils.display_info(f"Voting power applied: {result['voting_power']}")
            
            if comment:
                utils.display_info(f"Comment recorded: {comment[:50]}{'...' if len(comment) > 50 else ''}")
            
    except AgentVaultError as e:
        utils.display_error(f"Failed to cast vote: {e}")
        ctx.exit(1)
    except Exception as e:
        utils.display_error(f"Unexpected error casting vote: {e}")
        logger.exception("Unexpected error in govern vote command")
        ctx.exit(1)


@govern_group.command("show")
@click.argument("proposal_id")
@click.option(
    "--registry-url",
    default=config.REGISTRY_API_BASE,
    help="Override the default registry API URL",
    show_default=True
)
@click.pass_context
async def show_proposal_cmd(
    ctx: click.Context,
    proposal_id: str,
    registry_url: str
):
    """
    Show detailed information about a specific proposal.
    
    PROPOSAL_ID: The unique identifier of the proposal
    
    Displays full proposal details including current voting results.
    
    Example:
        agentvault govern show prop_123
    """
    if not _agentvault_lib_imported:
        utils.display_error("Cannot show proposal: Failed to import the 'agentvault' library.")
        ctx.exit(1)
    
    utils.display_info(f"Retrieving proposal: {proposal_id}")
    
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
            proposal = await get_proposal(
                client=client,
                proposal_id=proposal_id,
                registry_url=registry_url
            )
            
            # Display proposal details
            utils.display_info("\n" + "=" * 80)
            utils.display_info("PROPOSAL DETAILS")
            utils.display_info("=" * 80)
            
            # Basic info
            utils.display_info(f"ID: {proposal['proposal_id']}")
            utils.display_info(f"Title: {proposal['title']}")
            utils.display_info(f"Status: {proposal['status']}")
            utils.display_info(f"Author: {proposal['author']}")
            utils.display_info(f"Category: {proposal['category']}")
            
            if proposal.get('tags'):
                utils.display_info(f"Tags: {', '.join(proposal['tags'])}")
            
            # Description
            utils.display_info("\nDescription:")
            utils.display_info("-" * 80)
            # Wrap long descriptions
            desc_lines = proposal['description'].split('\n')
            for line in desc_lines:
                if len(line) > 78:
                    # Simple word wrap
                    words = line.split()
                    current_line = ""
                    for word in words:
                        if len(current_line) + len(word) + 1 <= 78:
                            current_line += word + " "
                        else:
                            utils.display_info(current_line.strip())
                            current_line = word + " "
                    if current_line:
                        utils.display_info(current_line.strip())
                else:
                    utils.display_info(line)
            
            # Voting period
            utils.display_info("\nVoting Period:")
            utils.display_info(f"Start: {proposal['voting_start']}")
            utils.display_info(f"End: {proposal['voting_end']}")
            
            # Current results
            utils.display_info("\nCurrent Voting Results:")
            utils.display_info("-" * 40)
            
            total_votes = (proposal.get('votes_for', 0) + 
                          proposal.get('votes_against', 0) + 
                          proposal.get('votes_abstain', 0))
            
            if total_votes > 0:
                for_pct = (proposal.get('votes_for', 0) / total_votes) * 100
                against_pct = (proposal.get('votes_against', 0) / total_votes) * 100
                abstain_pct = (proposal.get('votes_abstain', 0) / total_votes) * 100
                
                utils.display_success(f"✅ For: {proposal.get('votes_for', 0)} ({for_pct:.1f}%)")
                utils.display_error(f"❌ Against: {proposal.get('votes_against', 0)} ({against_pct:.1f}%)")
                utils.display_info(f"🤷 Abstain: {proposal.get('votes_abstain', 0)} ({abstain_pct:.1f}%)")
            else:
                utils.display_info("No votes cast yet")
            
            utils.display_info(f"\nTotal Voting Power: {proposal.get('total_voting_power', 0)}")
            
            # Additional info
            utils.display_info(f"\nCreated: {proposal['created_at']}")
            utils.display_info("=" * 80)
            
    except AgentVaultError as e:
        utils.display_error(f"Failed to retrieve proposal: {e}")
        ctx.exit(1)
    except Exception as e:
        utils.display_error(f"Unexpected error retrieving proposal: {e}")
        logger.exception("Unexpected error in govern show command")
        ctx.exit(1)


@govern_group.command("list")
@click.option(
    "--status",
    type=click.Choice(["active", "passed", "failed", "pending", "all"]),
    default="active",
    help="Filter by proposal status",
    show_default=True
)
@click.option(
    "--category",
    type=click.Choice(["general", "technical", "economic", "all"]),
    default="all",
    help="Filter by proposal category",
    show_default=True
)
@click.option(
    "--limit",
    type=int,
    default=20,
    help="Maximum number of proposals to show",
    show_default=True
)
@click.option(
    "--offset",
    type=int,
    default=0,
    help="Number of proposals to skip (for pagination)",
    show_default=True
)
@click.option(
    "--registry-url",
    default=config.REGISTRY_API_BASE,
    help="Override the default registry API URL",
    show_default=True
)
@click.pass_context
async def list_proposals_cmd(
    ctx: click.Context,
    status: str,
    category: str,
    limit: int,
    offset: int,
    registry_url: str
):
    """
    List governance proposals with optional filtering.
    
    Examples:
        agentvault govern list                        # List active proposals
        agentvault govern list --status all           # List all proposals
        agentvault govern list --category technical   # List technical proposals
        agentvault govern list --limit 50            # Show more proposals
    """
    if not _agentvault_lib_imported:
        utils.display_error("Cannot list proposals: Failed to import the 'agentvault' library.")
        ctx.exit(1)
    
    # Prepare filters
    status_filter = None if status == "all" else status
    category_filter = None if category == "all" else category
    
    utils.display_info(f"Listing proposals (status: {status}, category: {category})...")
    
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
            result = await list_proposals(
                client=client,
                status=status_filter,
                category=category_filter,
                limit=limit,
                offset=offset,
                registry_url=registry_url
            )
            
            proposals = result.get('proposals', [])
            total = result.get('total', 0)
            
            if not proposals:
                utils.display_info("No proposals found matching the criteria.")
                return
            
            # Display proposals in a table
            utils.display_info(f"\nShowing {len(proposals)} of {total} proposals")
            utils.display_info("=" * 100)
            
            # Table headers
            headers_list = ["ID", "Title", "Status", "Category", "For/Against", "Created"]
            data = []
            
            for prop in proposals:
                # Calculate vote summary
                votes_for = prop.get('votes_for', 0)
                votes_against = prop.get('votes_against', 0)
                vote_summary = f"{votes_for}/{votes_against}"
                
                # Truncate title if too long
                title = prop['title']
                if len(title) > 40:
                    title = title[:37] + "..."
                
                # Format created date
                created = prop.get('created_at', '')
                if 'T' in created:
                    created = created.split('T')[0]  # Just show date
                
                data.append([
                    prop['proposal_id'],
                    title,
                    prop['status'],
                    prop.get('category', 'general'),
                    vote_summary,
                    created
                ])
            
            utils.display_table("Governance Proposals", headers_list, data)
            
            # Pagination info
            if total > limit:
                current_page = (offset // limit) + 1
                total_pages = (total + limit - 1) // limit
                utils.display_info(f"\nPage {current_page} of {total_pages}")
                
                if offset + limit < total:
                    utils.display_info(f"Next page: --offset {offset + limit}")
                if offset > 0:
                    utils.display_info(f"Previous page: --offset {max(0, offset - limit)}")
            
            utils.display_info("\nUse 'agentvault govern show <proposal_id>' to view full details")
            
    except AgentVaultError as e:
        utils.display_error(f"Failed to list proposals: {e}")
        ctx.exit(1)
    except Exception as e:
        utils.display_error(f"Unexpected error listing proposals: {e}")
        logger.exception("Unexpected error in govern list command")
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
