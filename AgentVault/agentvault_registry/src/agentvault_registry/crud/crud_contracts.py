"""
CRUD operations for the Refactoring & Upgrade Contract (RUC) system.

This module provides database operations for managing contracts in the Agent Workshop
where Upgrader Agents perform code modifications for Client Agents.
"""

from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_

from ..models import RefactoringUpgradeContract


async def create_contract(
    db: AsyncSession,
    client_agent_did: str,
    scope_description: str,
    source_code_repo_url: str,
    source_code_branch: str,
    acceptance_criteria: Dict[str, Any],
    payment_amount: int
) -> RefactoringUpgradeContract:
    """
    Create a new Refactoring & Upgrade Contract (RUC).
    
    Args:
        db: Database session
        client_agent_did: DID of the agent requesting the work
        scope_description: Description of the work to be done
        source_code_repo_url: Git repository URL of the Client Agent's code
        source_code_branch: Specific branch to work on
        acceptance_criteria: JSON defining conditions for success
        payment_amount: Agreed payment for successful completion
        
    Returns:
        The newly created RefactoringUpgradeContract object
    """
    db_contract = RefactoringUpgradeContract(
        client_agent_did=client_agent_did,
        scope_description=scope_description,
        source_code_repo_url=source_code_repo_url,
        source_code_branch=source_code_branch,
        acceptance_criteria=acceptance_criteria,
        payment_amount=payment_amount,
        status="PROPOSED"
    )
    db.add(db_contract)
    await db.commit()
    await db.refresh(db_contract)
    return db_contract


async def get_contract_by_id(
    db: AsyncSession,
    contract_id: int
) -> Optional[RefactoringUpgradeContract]:
    """
    Retrieve a contract by its ID.
    
    Args:
        db: Database session
        contract_id: ID of the contract to retrieve
        
    Returns:
        The RefactoringUpgradeContract object if found, None otherwise
    """
    query = select(RefactoringUpgradeContract).where(
        RefactoringUpgradeContract.id == contract_id
    )
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def accept_contract(
    db: AsyncSession,
    contract_id: int,
    upgrader_agent_did: str,
    access_credentials_id: str
) -> Optional[RefactoringUpgradeContract]:
    """
    Accept a proposed contract and assign it to an Upgrader Agent.

    X14 fix: SELECT FOR UPDATE row-level lock prevents the race where two
    upgraders both pass the PROPOSED check and both write to the row.

    Args:
        db: Database session
        contract_id: ID of the contract to accept
        upgrader_agent_did: DID of the agent accepting the work
        access_credentials_id: Reference to temporary Git access credentials

    Returns:
        The updated RefactoringUpgradeContract object if found and was PROPOSED, None otherwise
    """
    query = select(RefactoringUpgradeContract).where(
        and_(
            RefactoringUpgradeContract.id == contract_id,
            RefactoringUpgradeContract.status == "PROPOSED"
        )
    ).with_for_update()
    result = await db.execute(query)
    contract = result.scalar_one_or_none()
    if not contract:
        return None

    contract.upgrader_agent_did = upgrader_agent_did
    contract.access_credentials_id = access_credentials_id
    contract.status = "ACCEPTED"
    contract.accepted_at = datetime.now(timezone.utc)
    contract.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(contract)
    return contract


async def update_contract_status(
    db: AsyncSession,
    contract_id: int,
    new_status: str,
    pr_url: Optional[str] = None
) -> Optional[RefactoringUpgradeContract]:
    """
    Update the status of a contract.
    
    Args:
        db: Database session
        contract_id: ID of the contract to update
        new_status: New status value
        pr_url: Optional pull request URL when submitting work
        
    Returns:
        The updated RefactoringUpgradeContract object if found, None otherwise
    """
    query = select(RefactoringUpgradeContract).where(
        RefactoringUpgradeContract.id == contract_id
    )
    result = await db.execute(query)
    contract = result.scalar_one_or_none()
    if not contract:
        return None
    
    contract.status = new_status
    contract.updated_at = datetime.now(timezone.utc)
    
    if pr_url:
        contract.pr_url = pr_url
    
    if new_status == "COMPLETED":
        contract.completed_at = datetime.now(timezone.utc)
    
    await db.commit()
    await db.refresh(contract)
    return contract


async def submit_contract_work(
    db: AsyncSession,
    contract_id: int,
    pr_url: str
) -> Optional[RefactoringUpgradeContract]:
    """
    Submit completed work for a contract by providing a pull request URL.
    
    Args:
        db: Database session
        contract_id: ID of the contract
        pr_url: URL of the pull request containing the work
        
    Returns:
        The updated RefactoringUpgradeContract object if found and was IN_PROGRESS, None otherwise
    """
    # X14 fix: SELECT FOR UPDATE
    query = select(RefactoringUpgradeContract).where(
        and_(
            RefactoringUpgradeContract.id == contract_id,
            RefactoringUpgradeContract.status.in_(["ACCEPTED", "IN_PROGRESS"])
        )
    ).with_for_update()
    result = await db.execute(query)
    contract = result.scalar_one_or_none()
    if not contract:
        return None

    contract.pr_url = pr_url
    contract.status = "PENDING_MERGE"
    contract.updated_at = datetime.now(timezone.utc)
    
    await db.commit()
    await db.refresh(contract)
    return contract


async def approve_contract_completion(
    db: AsyncSession,
    contract_id: int
) -> Optional[RefactoringUpgradeContract]:
    """
    Approve the completion of a contract after successful validation.
    
    Args:
        db: Database session
        contract_id: ID of the contract to approve
        
    Returns:
        The updated RefactoringUpgradeContract object if found and was PENDING_MERGE, None otherwise
    """
    # X14 fix: SELECT FOR UPDATE prevents concurrent approve from both passing PENDING_MERGE.
    query = select(RefactoringUpgradeContract).where(
        and_(
            RefactoringUpgradeContract.id == contract_id,
            RefactoringUpgradeContract.status == "PENDING_MERGE"
        )
    ).with_for_update()
    result = await db.execute(query)
    contract = result.scalar_one_or_none()
    if not contract:
        return None

    contract.status = "COMPLETED"
    contract.completed_at = datetime.now(timezone.utc)
    contract.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(contract)

    # NOTE: payment is now handled in the router BEFORE this function is called.
    # This function only flips status PENDING_MERGE → COMPLETED atomically.
    return contract


async def get_contracts_by_agent(
    db: AsyncSession,
    agent_did: str,
    role: Optional[str] = None  # "client", "upgrader", or None for both
) -> List[RefactoringUpgradeContract]:
    """
    Retrieve all contracts involving a specific agent.
    
    Args:
        db: Database session
        agent_did: DID of the agent
        role: Optional filter for the agent's role in contracts
        
    Returns:
        List of RefactoringUpgradeContract objects involving the agent
    """
    query = select(RefactoringUpgradeContract)
    
    if role == "client":
        query = query.where(RefactoringUpgradeContract.client_agent_did == agent_did)
    elif role == "upgrader":
        query = query.where(RefactoringUpgradeContract.upgrader_agent_did == agent_did)
    else:
        # Get contracts where agent is either client or upgrader
        query = query.where(
            or_(
                RefactoringUpgradeContract.client_agent_did == agent_did,
                RefactoringUpgradeContract.upgrader_agent_did == agent_did
            )
        )
    
    query = query.order_by(RefactoringUpgradeContract.created_at.desc())
    result = await db.execute(query)
    return result.scalars().all()


async def get_available_contracts(
    db: AsyncSession,
    limit: int = 20
) -> List[RefactoringUpgradeContract]:
    """
    Retrieve available contracts that are still in PROPOSED status.
    
    Args:
        db: Database session
        limit: Maximum number of contracts to return
        
    Returns:
        List of available RefactoringUpgradeContract objects
    """
    query = select(RefactoringUpgradeContract).where(
        RefactoringUpgradeContract.status == "PROPOSED"
    ).order_by(
        RefactoringUpgradeContract.created_at.desc()
    ).limit(limit)
    
    result = await db.execute(query)
    return result.scalars().all()


async def mark_contract_failed(
    db: AsyncSession,
    contract_id: int,
    reason: Optional[str] = None
) -> Optional[RefactoringUpgradeContract]:
    """
    Mark a contract as failed.
    
    Args:
        db: Database session
        contract_id: ID of the contract to mark as failed
        reason: Optional reason for failure
        
    Returns:
        The updated RefactoringUpgradeContract object if found, None otherwise
    """
    query = select(RefactoringUpgradeContract).where(
        RefactoringUpgradeContract.id == contract_id
    )
    result = await db.execute(query)
    contract = result.scalar_one_or_none()
    if not contract:
        return None
    
    contract.status = "FAILED"
    contract.updated_at = datetime.now(timezone.utc)
    
    # Note: In a complete implementation, we might store the failure reason
    # in a separate field or in a related table
    
    await db.commit()
    await db.refresh(contract)
    return contract
