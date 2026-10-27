# --- MODIFIED: Import asyncclick only ---
import asyncclick as aclick # Use asyncclick for all CLI functionality
# --- END MODIFIED ---
import logging
import asyncio # Keep asyncio import

# --- Basic Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Main CLI Group (Async) ---
# --- MODIFIED: Use asyncclick group ---
@aclick.group()
@aclick.version_option(package_name="agentvault-cli", prog_name="agentvault_cli")
async def cli(): # Keep this async
# --- END MODIFIED ---
    """
    AgentVault CLI: Interact with the AgentVault ecosystem.
    """
    pass

# --- Command Imports and Registration ---
# Import commands AFTER defining the group
from .commands import config # config now uses standard click
from .commands import discover
from .commands import run
from .commands import agent
from .commands import stake
from .commands import govern

# --- MODIFIED: Add config_group directly ---
cli.add_command(config.config_group) # Add the synchronous group
# --- END MODIFIED ---
cli.add_command(discover.discover_command) # discover_command is async
cli.add_command(run.run_command) # run_command is async
cli.add_command(agent.agent_group) # agent_group with onboarding command
cli.add_command(stake.stake_group) # stake_group with locking commands
cli.add_command(govern.govern_group) # govern_group with governance commands

# --- ADDED: Entry Point Check ---
if __name__ == "__main__":
    # --- MODIFIED: asyncclick entry point ---
    cli.main()
    # --- END MODIFIED ---
# --- END ADDED ---
