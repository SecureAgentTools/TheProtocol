"""
Export/Import API endpoints for Agent Configuration Portability
These endpoints extend the agents router with export/import functionality
"""

import asyncio
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status, Response, Query, Security
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from agentvault_registry.database import get_db
from agentvault_registry.models import Agent, Developer
from agentvault_registry.security import get_current_developer
from agentvault_registry.schemas import BaseModel, Field
from agentvault_registry.services.export_import_service import export_import_service
from agentvault_registry.routers.websocket import send_notification, manager

logger = logging.getLogger(__name__)

# Create a sub-router for export/import operations

def _agent_created_notice(agent_did: str, via: str, **extra) -> None:
    """§TWOAGENT (2026-09-24): agent.created, owner-scoped, after the commit. Subscribable and documented, it was
    dispatched by nothing; an import and a clone are new agents of the caller."""
    try:
        from ..background_tasks.reactor_helpers import dispatch_webhook_for_agents
        asyncio.create_task(dispatch_webhook_for_agents(
            "agent.created", {"agent_did": agent_did, "created_via": via, **extra}, [agent_did],
            source_label=f"agents.{via}"))
    except Exception as e:  # noqa: BLE001 — a notice is advisory; the agent exists
        logger.warning(f"agent.created webhook not scheduled for {agent_did}: {e}")

router = APIRouter(
    # §pass56 PR-5: tags= dropped; main.py:include_router supplies "Agent Export/Import"
)


# --- Request/Response Models ---

class ExportOptions(BaseModel):
    """Options for agent export"""
    include_metrics: bool = Field(False, description="Include performance metrics in export")
    include_versions: bool = Field(True, description="Include version history in export")


class ImportOptions(BaseModel):
    """Options for agent import"""
    conflict_resolution: str = Field(
        "skip",
        pattern="^(skip|rename|overwrite)$",
        description="How to handle DID conflicts: skip, rename, or overwrite"
    )
    dry_run: bool = Field(False, description="Validate import without actually importing")


class ImportRequest(BaseModel):
    """Request body for agent import"""
    export_data: Dict[str, Any] = Field(..., description="Exported agent configuration")
    options: ImportOptions = Field(default_factory=ImportOptions, description="Import options")


class ExportResponse(BaseModel):
    """Response for agent export"""
    export_version: str = Field(..., description="Export format version")
    export_timestamp: str = Field(..., description="ISO format export timestamp")
    export_id: str = Field(..., description="Unique export identifier")
    agent: Dict[str, Any] = Field(..., description="Agent configuration")
    metadata: Dict[str, Any] = Field(..., description="Export metadata")
    agent_card: Optional[Dict[str, Any]] = Field(None, description="Agent card data")
    capabilities: Optional[list] = Field(None, description="Agent capabilities")
    endpoints: Optional[list] = Field(None, description="Agent endpoints")
    tags: Optional[list] = Field(None, description="Agent tags")
    versions: Optional[list] = Field(None, description="Version history")
    metrics: Optional[Dict[str, Any]] = Field(None, description="Performance metrics")


class ImportResponse(BaseModel):
    """Response for agent import"""
    success: bool = Field(..., description="Whether import was successful")
    agent_did: Optional[str] = Field(None, description="DID of imported agent")
    warnings: list = Field(default_factory=list, description="Import warnings")
    errors: list = Field(default_factory=list, description="Import errors")
    statistics: Dict[str, int] = Field(
        default_factory=dict,
        description="Import statistics (capabilities_imported, etc.)"
    )
    # The service mints fresh credentials on every import (the secret is stored hashed) —
    # without this field the model silently dropped them, leaving imported agents with
    # unusable credentials until a manual reset.
    new_credentials: Optional[Dict[str, str]] = Field(
        None, description="Fresh client credentials for the imported agent — the secret is shown ONCE and cannot be retrieved again")


class BulkExportRequest(BaseModel):
    """Request for bulk agent export"""
    agent_dids: list[str] = Field(..., description="List of agent DIDs to export")
    options: ExportOptions = Field(default_factory=ExportOptions, description="Export options")


class BulkExportResponse(BaseModel):
    """Response for bulk agent export"""
    export_id: str = Field(..., description="Bulk export identifier")
    export_timestamp: str = Field(..., description="ISO format export timestamp")
    total_agents: int = Field(..., description="Total number of agents exported")
    successful_exports: int = Field(..., description="Number of successful exports")
    failed_exports: int = Field(..., description="Number of failed exports")
    agents: list[Dict[str, Any]] = Field(..., description="Exported agent configurations")
    errors: list[Dict[str, str]] = Field(default_factory=list, description="Export errors by agent")


# --- Export Endpoints ---

@router.get(
    "/agents/{agent_did}/export",
    response_model=ExportResponse,
    summary="Export Agent Configuration",
    description="Export an agent's configuration for backup or migration purposes"
)
async def export_agent(
    agent_did: str,
    include_metrics: bool = Query(False, description="Include performance metrics"),
    include_versions: bool = Query(True, description="Include version history"),
    current_developer: Developer = Security(get_current_developer),
    db: AsyncSession = Depends(get_db)
) -> ExportResponse:
    """
    Export an agent's complete configuration.
    
    This endpoint exports all non-sensitive agent data including:
    - Core agent configuration
    - Agent card (if exists)
    - Capabilities and endpoints
    - Tags and metadata
    - Optional: Version history and performance metrics
    
    Sensitive data like API keys and secrets are automatically excluded.
    
    Returns:
        Exportable agent configuration package
    """
    try:
        logger.info(f"Developer {current_developer.id} exporting agent {agent_did}")
        
        export_data = await export_import_service.export_agent(
            agent_did=agent_did,
            developer_id=current_developer.id,
            db=db,
            include_metrics=include_metrics,
            include_versions=include_versions
        )
        
        # Send WebSocket notification
        await manager.broadcast({
            "type": "agent.exported",
            "data": {
                "agent_did": agent_did,
                "developer_id": current_developer.id,
                "export_id": export_data["export_id"],
                "timestamp": export_data["export_timestamp"]
            }
        }, audience=f"user_{current_developer.id}")
        
        logger.info(f"Successfully exported agent {agent_did} with export_id {export_data['export_id']}")
        
        return ExportResponse(**export_data)
        
    except ValueError as e:
        logger.error(f"Export failed for agent {agent_did}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="An internal error occurred"
        )
    except Exception as e:
        logger.error(f"Unexpected error exporting agent {agent_did}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to export agent configuration"
        )


@router.post(
    "/agents/export/bulk",
    response_model=BulkExportResponse,
    summary="Bulk Export Agents",
    description="Export multiple agents in a single operation"
)
async def bulk_export_agents(
    request: BulkExportRequest,
    current_developer: Developer = Security(get_current_developer),
    db: AsyncSession = Depends(get_db)
) -> BulkExportResponse:
    """
    Export multiple agents at once.
    
    Useful for backing up all agents or migrating multiple agents together.
    Each agent is exported individually and errors for one agent don't affect others.
    
    Returns:
        Bulk export package with all successfully exported agents
    """
    import uuid
    
    logger.info(f"Developer {current_developer.id} bulk exporting {len(request.agent_dids)} agents")
    
    export_id = str(uuid.uuid4())
    export_timestamp = datetime.now(timezone.utc).isoformat()
    agents = []
    errors = []
    successful = 0
    
    for agent_did in request.agent_dids:
        try:
            export_data = await export_import_service.export_agent(
                agent_did=agent_did,
                developer_id=current_developer.id,
                db=db,
                include_metrics=request.options.include_metrics,
                include_versions=request.options.include_versions
            )
            agents.append(export_data)
            successful += 1
            
        except Exception as e:
            logger.error(f"Failed to export agent {agent_did}: {str(e)}")
            errors.append({
                "agent_did": agent_did,
                "error": str(e)
            })
    
    logger.info(f"Bulk export completed: {successful}/{len(request.agent_dids)} successful")
    
    return BulkExportResponse(
        export_id=export_id,
        export_timestamp=export_timestamp,
        total_agents=len(request.agent_dids),
        successful_exports=successful,
        failed_exports=len(errors),
        agents=agents,
        errors=errors
    )


# --- Import Endpoints ---

@router.post(
    "/agents/import",
    response_model=ImportResponse,
    summary="Import Agent Configuration",
    description="Import an agent from an exported configuration"
)
async def import_agent(
    request: ImportRequest,
    current_developer: Developer = Security(get_current_developer),
    db: AsyncSession = Depends(get_db)
) -> ImportResponse:
    """
    Import an agent from exported configuration.
    
    This endpoint allows importing agents that were previously exported.
    It includes validation, conflict resolution, and optional dry-run mode.
    
    Conflict resolution options:
    - skip: Don't import if agent DID already exists
    - rename: Generate new DID if conflict exists
    - overwrite: Replace existing agent (only if owned by same developer)
    
    Args:
        request: Import configuration and options
        
    Returns:
        Import result with success status and any warnings/errors
    """
    try:
        logger.info(
            f"Developer {current_developer.id} importing agent "
            f"(dry_run={request.options.dry_run}, conflict={request.options.conflict_resolution})"
        )
        
        agent, report = await export_import_service.import_agent(
            import_data=request.export_data,
            developer_id=current_developer.id,
            db=db,
            conflict_resolution=request.options.conflict_resolution,
            dry_run=request.options.dry_run
        )
        
        if report["success"] and not request.options.dry_run:
            # Send WebSocket notification
            await manager.broadcast({
                "type": "agent.imported",
                "data": {
                    "agent_did": report["agent_did"],
                    "developer_id": current_developer.id,
                    "original_did": request.export_data["metadata"]["original_did"],
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
            }, audience=f"user_{current_developer.id}")
            
            logger.info(f"Successfully imported agent {report['agent_did']}")
            _agent_created_notice(report["agent_did"], "import",
                                  original_did=request.export_data["metadata"]["original_did"])
        
        return ImportResponse(**report)
        
    except Exception as e:
        logger.error(f"Import failed: {str(e)}")
        return ImportResponse(
            success=False,
            errors=[str(e)]
        )


@router.post(
    "/agents/import/validate",
    response_model=ImportResponse,
    summary="Validate Agent Import",
    description="Validate an agent import without actually importing"
)
async def validate_import(
    request: ImportRequest,
    current_developer: Developer = Security(get_current_developer),
    db: AsyncSession = Depends(get_db)
) -> ImportResponse:
    """
    Validate an agent import without performing the actual import.
    
    This is equivalent to calling the import endpoint with dry_run=true.
    Useful for checking if an import will succeed before actually doing it.
    
    Returns:
        Validation report with any warnings or errors
    """
    # Force dry_run mode
    request.options.dry_run = True
    
    logger.info(f"Developer {current_developer.id} validating agent import")
    
    agent, report = await export_import_service.import_agent(
        import_data=request.export_data,
        developer_id=current_developer.id,
        db=db,
        conflict_resolution=request.options.conflict_resolution,
        dry_run=True
    )
    
    return ImportResponse(**report)


@router.post(
    "/agents/{agent_did}/clone",
    response_model=ImportResponse,
    summary="Clone Agent",
    description="Create a copy of an existing agent with a new DID"
)
async def clone_agent(
    agent_did: str,
    new_name: Optional[str] = Query(None, description="Name for the cloned agent"),
    current_developer: Developer = Security(get_current_developer),
    db: AsyncSession = Depends(get_db)
) -> ImportResponse:
    """
    Clone an existing agent to create a new copy.
    
    This is a convenience endpoint that combines export and import with rename.
    The cloned agent will have a new DID and can optionally have a new name.
    
    Args:
        agent_did: DID of the agent to clone
        new_name: Optional new name for the clone
        
    Returns:
        Import result for the cloned agent
    """
    try:
        logger.info(f"Developer {current_developer.id} cloning agent {agent_did}")
        
        # Use the service's clone method which handles everything including event emission
        agent, report = await export_import_service.clone_agent(
            agent_did=agent_did,
            developer_id=current_developer.id,
            db=db,
            new_name=new_name
        )
        
        if report["success"]:
            logger.info(f"Successfully cloned agent {agent_did} to {report['agent_did']}")
            
            # Send WebSocket notification
            await manager.broadcast({
                "type": "agent.cloned",
                "data": {
                    "original_did": agent_did,
                    "clone_did": report["agent_did"],
                    "developer_id": current_developer.id,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
            }, audience=f"user_{current_developer.id}")
            _agent_created_notice(report["agent_did"], "clone", original_did=agent_did)
        
        return ImportResponse(**report)

    # §MCPTEST30 (2026-09-30): every failure used to answer HTTP 200 with success=false, so a clone of an agent that
    # does not exist (or is not the caller's) read as a success to anything that checks the status, the MCP tester
    # included (measured on the sandbox operator: "Clone failed ... not found or access denied", then "POST .../clone
    # 200"). The export route beside it already maps the same service error to 404; the clone now answers the same way.
    except ValueError as e:
        logger.error(f"Clone failed for agent {agent_did}: {str(e)}")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Agent not found or access denied")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Clone failed for agent {agent_did}: {str(e)}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="Failed to clone agent")


# --- Template Endpoints ---

@router.get(
    "/agents/templates/{template_id}",
    response_model=ExportResponse,
    summary="Get Agent Template",
    description="Get a pre-configured agent template"
)
async def get_agent_template(
    template_id: str,
    current_developer: Developer = Security(get_current_developer),
    db: AsyncSession = Depends(get_db)
) -> ExportResponse:
    """
    Get a pre-configured agent template.
    
    Templates are pre-built agent configurations for common use cases.
    They can be imported like any other exported agent.
    
    Available templates:
    - web-scraper: Web scraping agent template
    - api-gateway: API gateway agent template
    - data-processor: Data processing agent template
    - chatbot: Conversational AI agent template
    - monitoring: System monitoring agent template
    
    Returns:
        Template configuration ready for import
    """
    import uuid
    
    # Define templates (in production, these would be in a database)
    templates = {
        "web-scraper": {
            "name": "Web Scraper Agent",
            "description": "Agent configured for web scraping tasks",
            "agent_type": "scraper",
            "configuration": {
                "max_depth": 3,
                "rate_limit": 10,
                "user_agent": "AgentVault-Scraper/1.0"
            },
            "capabilities": [
                {
                    "name": "html_parsing",
                    "description": "Parse HTML content",
                    "category": "parsing"
                },
                {
                    "name": "link_extraction",
                    "description": "Extract links from pages",
                    "category": "extraction"
                }
            ]
        },
        "api-gateway": {
            "name": "API Gateway Agent",
            "description": "Agent configured as an API gateway",
            "agent_type": "gateway",
            "configuration": {
                "rate_limit": 1000,
                "cache_ttl": 300,
                "retry_attempts": 3
            },
            "capabilities": [
                {
                    "name": "request_routing",
                    "description": "Route API requests",
                    "category": "networking"
                },
                {
                    "name": "response_caching",
                    "description": "Cache API responses",
                    "category": "performance"
                }
            ]
        },
        "data-processor": {
            "name": "Data Processor Agent",
            "description": "Agent configured for data processing",
            "agent_type": "processor",
            "configuration": {
                "batch_size": 100,
                "parallel_workers": 4,
                "error_threshold": 0.05
            },
            "capabilities": [
                {
                    "name": "data_transformation",
                    "description": "Transform data formats",
                    "category": "processing"
                },
                {
                    "name": "data_validation",
                    "description": "Validate data quality",
                    "category": "quality"
                }
            ]
        },
        "chatbot": {
            "name": "Chatbot Agent",
            "description": "Conversational AI agent",
            "agent_type": "chatbot",
            "configuration": {
                "model": "gpt-3.5-turbo",
                "temperature": 0.7,
                "max_tokens": 150
            },
            "capabilities": [
                {
                    "name": "natural_language",
                    "description": "Process natural language",
                    "category": "ai"
                },
                {
                    "name": "context_management",
                    "description": "Manage conversation context",
                    "category": "conversation"
                }
            ]
        },
        "monitoring": {
            "name": "Monitoring Agent",
            "description": "System monitoring agent",
            "agent_type": "monitor",
            "configuration": {
                "check_interval": 60,
                "alert_threshold": 0.95,
                "metrics_retention": 86400
            },
            "capabilities": [
                {
                    "name": "health_check",
                    "description": "Perform health checks",
                    "category": "monitoring"
                },
                {
                    "name": "alert_generation",
                    "description": "Generate alerts",
                    "category": "alerting"
                }
            ]
        }
    }
    
    if template_id not in templates:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Template '{template_id}' not found"
        )
    
    template = templates[template_id]
    
    # Create export format
    export_data = {
        "export_version": "1.0.0",
        "export_timestamp": datetime.now(timezone.utc).isoformat(),
        "export_id": str(uuid.uuid4()),
        "agent": {
            "did": f"did:template:{template_id}",
            "name": template["name"],
            "description": template["description"],
            "agent_type": template["agent_type"],
            "status": "inactive",
            "version": "1.0.0",
            "configuration": template["configuration"],
            "metadata": {
                "template": True,
                "template_id": template_id
            }
        },
        "capabilities": template.get("capabilities", []),
        "metadata": {
            "original_did": f"did:template:{template_id}",
            "template": True,
            "template_id": template_id
        }
    }
    
    logger.info(f"Developer {current_developer.id} retrieved template {template_id}")
    
    return ExportResponse(**export_data)


@router.get(
    "/agents/templates",
    summary="List Agent Templates",
    description="List all available agent templates"
)
async def list_agent_templates(
    current_developer: Developer = Security(get_current_developer)
) -> Dict[str, Any]:
    """
    List all available agent templates.
    
    Returns a list of templates with their descriptions and categories.
    """
    templates = [
        {
            "id": "web-scraper",
            "name": "Web Scraper Agent",
            "description": "Agent configured for web scraping tasks",
            "category": "data-collection"
        },
        {
            "id": "api-gateway",
            "name": "API Gateway Agent",
            "description": "Agent configured as an API gateway",
            "category": "infrastructure"
        },
        {
            "id": "data-processor",
            "name": "Data Processor Agent",
            "description": "Agent configured for data processing",
            "category": "analytics"
        },
        {
            "id": "chatbot",
            "name": "Chatbot Agent",
            "description": "Conversational AI agent",
            "category": "ai"
        },
        {
            "id": "monitoring",
            "name": "Monitoring Agent",
            "description": "System monitoring agent",
            "category": "operations"
        }
    ]
    
    logger.info(f"Developer {current_developer.id} listed templates")
    
    return {
        "templates": templates,
        "total": len(templates)
    }
