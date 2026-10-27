"""
Admin CLI commands for AgentVault Registry

This module provides command-line tools for administrative tasks such as
granting and revoking admin privileges.
"""
import asyncio
import logging
from typing import Optional

import typer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import AsyncSessionLocal
from ..models import Developer

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create Typer app
app = typer.Typer(help="AgentVault Registry Admin CLI")


async def _grant_admin_role(email: str) -> None:
    """Internal async function to grant admin role to a developer"""
    async_session_maker = AsyncSessionLocal
    
    async with async_session_maker() as session:
        # Find the developer by email
        stmt = select(Developer).where(Developer.email == email)
        result = await session.execute(stmt)
        developer = result.scalar_one_or_none()
        
        if not developer:
            logger.error(f"Developer not found with email: {email}")
            raise typer.Exit(code=1)
        
        if developer.is_admin:
            logger.info(f"Developer {email} is already an admin")
            return
        
        # Grant admin role
        developer.is_admin = True
        await session.commit()
        
        logger.info(f"Successfully granted admin role to developer: {email} (ID: {developer.id})")


async def _revoke_admin_role(email: str) -> None:
    """Internal async function to revoke admin role from a developer"""
    async_session_maker = AsyncSessionLocal
    
    async with async_session_maker() as session:
        # Find the developer by email
        stmt = select(Developer).where(Developer.email == email)
        result = await session.execute(stmt)
        developer = result.scalar_one_or_none()
        
        if not developer:
            logger.error(f"Developer not found with email: {email}")
            raise typer.Exit(code=1)
        
        if not developer.is_admin:
            logger.info(f"Developer {email} is not an admin")
            return
        
        # Revoke admin role
        developer.is_admin = False
        await session.commit()
        
        logger.info(f"Successfully revoked admin role from developer: {email} (ID: {developer.id})")


async def _list_admins() -> None:
    """Internal async function to list all admin developers"""
    async_session_maker = AsyncSessionLocal
    
    async with async_session_maker() as session:
        # Find all admin developers
        stmt = select(Developer).where(Developer.is_admin == True)
        result = await session.execute(stmt)
        admins = result.scalars().all()
        
        if not admins:
            logger.info("No admin developers found")
            return
        
        logger.info(f"Found {len(admins)} admin developer(s):")
        for admin in admins:
            logger.info(f"  - {admin.email} (ID: {admin.id}, Name: {admin.name})")


@app.command()
def grant_admin_role(
    email: str = typer.Argument(..., help="Email address of the developer to grant admin role")
) -> None:
    """
    Grant admin role to a developer by email address.
    
    Example:
        python -m agentvault_registry.cli.admin grant-admin-role user@example.com
    """
    typer.echo(f"Granting admin role to developer with email: {email}")
    asyncio.run(_grant_admin_role(email))


@app.command()
def revoke_admin_role(
    email: str = typer.Argument(..., help="Email address of the developer to revoke admin role")
) -> None:
    """
    Revoke admin role from a developer by email address.
    
    Example:
        python -m agentvault_registry.cli.admin revoke-admin-role user@example.com
    """
    typer.echo(f"Revoking admin role from developer with email: {email}")
    asyncio.run(_revoke_admin_role(email))


@app.command()
def list_admins() -> None:
    """
    List all developers with admin privileges.
    
    Example:
        python -m agentvault_registry.cli.admin list-admins
    """
    typer.echo("Listing all admin developers...")
    asyncio.run(_list_admins())


if __name__ == "__main__":
    app()
