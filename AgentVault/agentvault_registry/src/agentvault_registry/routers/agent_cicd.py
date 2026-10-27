"""
Agent CI/CD Router
API endpoints for managing agent CI/CD pipelines, versions, and deployments.

This provides infrastructure for agents to define their CI/CD processes.
Agents run the actual CI/CD on their own infrastructure - we just coordinate.
"""
import asyncio
import json
import uuid
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Body, Path, status, Security
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from ..database import get_db
from ..security import admin_credential, get_current_agent, get_current_developer, require_agent_permission
from ..services.agent_cicd_service import agent_cicd_service
from ..models import Developer

logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["Agent CI/CD"],
    responses={
        404: {"description": "Not found"},
        401: {"description": "Unauthorized"},
        400: {"description": "Bad request"}
    }
)


# ==================== Request Body Models (§pass47 A3) ====================
# Replaced opaque `Dict[str, Any] = Body(...)` shapes that 500'd on KeyError.
# Service layer still accepts Dict[str, Any]; routers convert via model_dump
# (exclude_unset preserves "missing-vs-explicit-null" semantics for service
# pattern `'field' in data` guards).

class _BaseBody(BaseModel):
    model_config = ConfigDict(extra="allow")  # tolerate unknown keys; service ignores them


class CreatePipelineBody(_BaseBody):
    pipeline_name: str = Field(..., min_length=1, max_length=255)
    pipeline_config: Dict[str, Any]
    trigger_type: Optional[str] = None
    webhook_url: Optional[str] = None
    webhook_secret: Optional[str] = None
    is_active: Optional[bool] = True
    environment_vars: Optional[Dict[str, Any]] = None
    notification_config: Optional[Dict[str, Any]] = None


class UpdatePipelineBody(_BaseBody):
    pipeline_name: Optional[str] = None
    pipeline_config: Optional[Dict[str, Any]] = None
    trigger_type: Optional[str] = None
    webhook_url: Optional[str] = None
    webhook_secret: Optional[str] = None
    is_active: Optional[bool] = None
    environment_vars: Optional[Dict[str, Any]] = None
    notification_config: Optional[Dict[str, Any]] = None


class CreateVersionBody(_BaseBody):
    version: str = Field(..., min_length=1, max_length=64)
    commit_hash: Optional[str] = None
    release_notes: Optional[str] = None
    changelog: Optional[str] = None
    artifacts: Optional[Dict[str, Any]] = None
    config_snapshot: Optional[Dict[str, Any]] = None
    is_stable: Optional[bool] = False


class TriggerDeploymentBody(_BaseBody):
    pipeline_id: Optional[str] = None
    version_id: Optional[str] = None
    environment: str = "production"


class UpdateDeploymentStatusBody(_BaseBody):
    status: str = Field(..., min_length=1, max_length=32)
    logs: Optional[str] = None
    error_message: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class AppendDeploymentLogsBody(_BaseBody):
    # `logs` historically accepts a str or list-of-dicts; keep Any to preserve compat.
    logs: Optional[Any] = None


class CreateTemplateBody(_BaseBody):
    name: str = Field(..., min_length=1, max_length=255)
    category: str = Field(..., min_length=1, max_length=64)
    template_config: Dict[str, Any]
    description: Optional[str] = None
    price_teg: Optional[int] = 0
    tags: Optional[List[str]] = None
    is_official: Optional[bool] = False


class PurchaseTemplateBody(_BaseBody):
    buyer_did: str = Field(..., min_length=1)


# ==================== Pipeline Management ====================

@router.post("/agents/{agent_did}/pipelines")
async def create_pipeline(
    agent_did: str = Path(..., description="Agent DID"),
    pipeline_data: CreatePipelineBody = Body(...),
    db: AsyncSession = Depends(get_db),
    current_developer: Developer = Security(get_current_developer)
):
    """
    Create a new CI/CD pipeline configuration for an agent.

    The pipeline configuration defines the build/test/deploy steps that will
    be executed on the agent's own infrastructure when triggered.
    """
    try:
        result = await agent_cicd_service.create_pipeline(
            db, agent_did, pipeline_data.model_dump(exclude_unset=True), current_developer.id
        )
        return result
    except HTTPException:
        raise
    except SQLAlchemyError:
        # pass73.3.19: let the global SQLAlchemy handler classify DB input errors
        # (e.g. a non-UUID path param → asyncpg DataError) as 422 instead of this
        # blanket 500. Genuine DB errors still surface as 500 via that handler.
        raise
    except Exception as e:
        logger.error(f"Error creating pipeline: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/agents/{agent_did}/pipelines")
async def list_pipelines(
    agent_did: str = Path(..., description="Agent DID"),
    db: AsyncSession = Depends(get_db),
    current_developer: Developer = Security(get_current_developer)
):
    """Get all CI/CD pipelines for an agent."""
    try:
        pipelines = await agent_cicd_service.get_pipelines(
            db, agent_did, current_developer.id
        )
        return {"pipelines": pipelines}
    except HTTPException:
        raise
    except SQLAlchemyError:
        # pass73.3.19: let the global SQLAlchemy handler classify DB input errors
        # (e.g. a non-UUID path param → asyncpg DataError) as 422 instead of this
        # blanket 500. Genuine DB errors still surface as 500 via that handler.
        raise
    except Exception as e:
        logger.error(f"Error listing pipelines: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put("/agents/{agent_did}/pipelines/{pipeline_id}")
async def update_pipeline(
    agent_did: str = Path(..., description="Agent DID"),
    pipeline_id: str = Path(..., description="Pipeline ID"),
    pipeline_data: UpdatePipelineBody = Body(...),
    db: AsyncSession = Depends(get_db),
    current_developer: Developer = Security(get_current_developer)
):
    """Update a CI/CD pipeline configuration."""
    try:
        result = await agent_cicd_service.update_pipeline(
            db, agent_did, pipeline_id, pipeline_data.model_dump(exclude_unset=True), current_developer.id
        )
        return result
    except HTTPException:
        raise
    except SQLAlchemyError:
        # pass73.3.19: let the global SQLAlchemy handler classify DB input errors
        # (e.g. a non-UUID path param → asyncpg DataError) as 422 instead of this
        # blanket 500. Genuine DB errors still surface as 500 via that handler.
        raise
    except Exception as e:
        logger.error(f"Error updating pipeline: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/agents/{agent_did}/pipelines/{pipeline_id}")
async def delete_pipeline(
    agent_did: str = Path(..., description="Agent DID"),
    pipeline_id: str = Path(..., description="Pipeline ID"),
    db: AsyncSession = Depends(get_db),
    current_developer: Developer = Security(get_current_developer)
):
    """Delete a CI/CD pipeline."""
    try:
        result = await agent_cicd_service.delete_pipeline(
            db, agent_did, pipeline_id, current_developer.id
        )
        return result
    except HTTPException:
        raise
    except SQLAlchemyError:
        # pass73.3.19: let the global SQLAlchemy handler classify DB input errors
        # (e.g. a non-UUID path param → asyncpg DataError) as 422 instead of this
        # blanket 500. Genuine DB errors still surface as 500 via that handler.
        raise
    except Exception as e:
        logger.error(f"Error deleting pipeline: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ==================== Version Management ====================

@router.post("/agents/{agent_did}/versions")
async def create_version(
    agent_did: str = Path(..., description="Agent DID"),
    version_data: CreateVersionBody = Body(...),
    db: AsyncSession = Depends(get_db),
    current_developer: Developer = Security(get_current_developer)
):
    """
    Register a new version for an agent.

    This creates a snapshot of the current agent configuration that can be
    used for rollbacks. The version can later be activated for deployment.
    """
    try:
        result = await agent_cicd_service.create_version(
            db, agent_did, version_data.model_dump(exclude_unset=True), current_developer.id
        )
        return result
    except HTTPException:
        raise
    except SQLAlchemyError:
        # pass73.3.19: let the global SQLAlchemy handler classify DB input errors
        # (e.g. a non-UUID path param → asyncpg DataError) as 422 instead of this
        # blanket 500. Genuine DB errors still surface as 500 via that handler.
        raise
    except Exception as e:
        logger.error(f"Error creating version: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/agents/self/version")
async def create_version_as_agent(
    version_data: CreateVersionBody = Body(...),
    agent=Depends(require_agent_permission("cicd.version")),
    db: AsyncSession = Depends(get_db),
):
    """GÖDEL FORGE: a harness commits a NEW VERSION of its OWN code line under ``cicd.version``.

    The version is keyed to the agent's own DID and owned by its creator developer (spawn
    inherits it), so a self-improving agent can snapshot each variant it produces without a
    developer-JWT round-trip. Byte-inert under ``AGENT_RBAC_MODE=off`` (any agent); enforced
    only where the permission is granted/delegated. Distinct literal path (``/agents/self/version``,
    singular), no collision with ``/agents/{agent_did}/versions`` (plural)."""
    try:
        return await agent_cicd_service.create_version(
            db, agent.did, version_data.model_dump(exclude_unset=True), agent.creator_developer_id
        )
    except HTTPException:
        raise
    except SQLAlchemyError:
        raise
    except Exception as e:  # noqa: BLE001
        logger.error(f"Error creating self version: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/agents/{agent_did}/versions")
async def list_versions(
    agent_did: str = Path(..., description="Agent DID"),
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_developer: Developer = Security(get_current_developer)
):
    """Get all versions for an agent."""
    try:
        # Verify permission
        await agent_cicd_service._get_agent_with_permission(
            db, agent_did, current_developer.id
        )
        
        # Get versions
        result = await db.execute(
            text("""
                SELECT id, version, changelog, is_current, 
                       is_stable, deployment_count, rollback_count, created_at, configuration
                FROM agent_versions
                WHERE agent_did = :agent_did
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            {'agent_did': agent_did, 'limit': limit, 'offset': offset}
        )
        
        versions = []
        for row in result:
            # Extract artifacts from configuration JSON if present
            config = row.configuration if isinstance(row.configuration, dict) else json.loads(row.configuration) if row.configuration else {}
            
            versions.append({
                'id': str(row.id),
                'version': row.version,
                'release_notes': row.changelog,  # Map changelog back to release_notes for API
                'is_active': row.is_current,  # Map is_current to is_active for API
                'is_stable': row.is_stable,
                'deployment_count': row.deployment_count,
                'rollback_count': row.rollback_count,
                'created_at': row.created_at.isoformat(),
                'artifacts': config.get('artifacts', {})
            })
        
        return {"versions": versions}
        
    except HTTPException:
        raise
    except SQLAlchemyError:
        # pass73.3.19: let the global SQLAlchemy handler classify DB input errors
        # (e.g. a non-UUID path param → asyncpg DataError) as 422 instead of this
        # blanket 500. Genuine DB errors still surface as 500 via that handler.
        raise
    except Exception as e:
        logger.error(f"Error listing versions: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/agents/self/versions/{version_id}/activate")
async def activate_version_as_agent(
    version_id: str = Path(..., description="Version ID"),
    agent=Depends(require_agent_permission("cicd.version")),
    db: AsyncSession = Depends(get_db),
):
    """GÖDEL FORGE: a harness ADOPTS its winning variant: activates one of its OWN versions
    under ``cicd.version`` (birth-token attenuable), completing the self-improvement loop
    (commit → eval → adopt) without a developer round-trip. Literal ``/agents/self/…`` path:
    no collision with the dev-tier ``/agents/{agent_did}/…`` route below."""
    try:
        return await agent_cicd_service.activate_version(
            db, agent.did, version_id, agent.creator_developer_id
        )
    except HTTPException:
        raise
    except SQLAlchemyError:
        raise
    except Exception as e:  # noqa: BLE001
        logger.error(f"Error activating self version: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/agents/self/rotate-signing-key")
async def rotate_own_signing_key(
    agent=Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """GÖDEL FORGE: an agent rotates ITS OWN Ed25519 signing key. Exists so an
    independently-operated verifier daemon can sign verdicts holding ONLY its verifiers'
    client credentials; no admin key ever leaves the origin operator. Identity self-service
    (same trust shape as ``/agent/enable-mtls``): plain agent auth, own key only. Mirrors the
    admin rotation exactly: same tables, grace window, event."""
    import datetime as _dt
    from sqlalchemy import func as _func
    from .. import models as _models
    from .agent_signing_keys_admin import _generate_eddsa, _GRACE_DAYS
    did = agent.did
    seq_q = await db.execute(select(_func.coalesce(_func.max(_models.AgentSigningKey.rotation_seq), 0))
                             .where(_models.AgentSigningKey.agent_did == did))
    new_seq = int(seq_q.scalar() or 0) + 1
    keys = _generate_eddsa()
    now = _dt.datetime.now(_dt.timezone.utc)
    grace_until = now + _dt.timedelta(days=_GRACE_DAYS)
    db.add(_models.AgentSigningKey(agent_did=did, rotation_seq=new_seq, public_jwk=keys["public_jwk"],
                                   algorithm="EdDSA", created_at=now, expires_at=None))
    if new_seq > 1:
        prev_q = await db.execute(select(_models.AgentSigningKey).where(
            _models.AgentSigningKey.agent_did == did,
            _models.AgentSigningKey.expires_at.is_(None),
            _models.AgentSigningKey.rotation_seq != new_seq))
        for prev in prev_q.scalars().all():
            prev.expires_at = grace_until
            db.add(prev)
    ares = await db.execute(select(_models.Agent).where(_models.Agent.did == did))
    arow = ares.scalar_one_or_none()
    if arow is not None:
        arow.public_key_jwk = keys["public_jwk"]
        db.add(arow)
    await db.commit()
    try:
        from ..event_emitter import get_event_emitter
        get_event_emitter().emit_background(
            event_type="AgentSigningKeyRotated", aggregate_id=did,
            data={"rotation_seq": new_seq, "self_service": True},
            idempotency_key=f"selfrot-{did}-{new_seq}")
    except Exception:  # noqa: BLE001
        logger.debug("AgentSigningKeyRotated emit skipped", exc_info=True)
    return {"agent_did": did, "rotation_seq": new_seq, "private_pem": keys["private_pem"],
            "public_jwk": keys["public_jwk"], "old_key_grace_until": grace_until.isoformat(),
            "shown_once": True}


@router.post("/agents/{agent_did}/versions/{version_id}/activate")
async def activate_version(
    agent_did: str = Path(..., description="Agent DID"),
    version_id: str = Path(..., description="Version ID"),
    db: AsyncSession = Depends(get_db),
    current_developer: Developer = Security(get_current_developer)
):
    """Set a version as the active deployment."""
    try:
        result = await agent_cicd_service.activate_version(
            db, agent_did, version_id, current_developer.id
        )
        return result
    except HTTPException:
        raise
    except SQLAlchemyError:
        # pass73.3.19: let the global SQLAlchemy handler classify DB input errors
        # (e.g. a non-UUID path param → asyncpg DataError) as 422 instead of this
        # blanket 500. Genuine DB errors still surface as 500 via that handler.
        raise
    except Exception as e:
        logger.error(f"Error activating version: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# §pass49 B2 — DELETE a version. Admin-only; refuses if is_current=true OR
# if any deployment references it (FK protects). Useful for cleaning test
# pollution; production version retention is unaffected because the gate
# blocks live versions.
@router.delete("/agents/{agent_did}/versions/{version_id}")
async def delete_version(
    agent_did: str = Path(..., description="Agent DID"),
    version_id: str = Path(..., description="Version ID"),
    db: AsyncSession = Depends(get_db),
    current_developer: Developer = Security(get_current_developer)
):
    """Delete a version. Refuses if `is_current=true` or any deployment references it.

    Same permission check as other version ops (creator OR org-member).
    """
    try:
        await agent_cicd_service._get_agent_with_permission(db, agent_did, current_developer.id)

        # Confirm version exists + capture is_current
        chk = await db.execute(
            text("SELECT version, is_current FROM agent_versions WHERE id = :vid AND agent_did = :did"),
            {"vid": version_id, "did": agent_did},
        )
        row = chk.first()
        if not row:
            raise HTTPException(status_code=404, detail="Version not found")
        if row.is_current:
            raise HTTPException(status_code=409, detail="Cannot delete the current version; activate another version first.")

        # Block if any deployment references this version (FK).
        dep_count = await db.execute(
            text("SELECT COUNT(*) FROM agent_deployments WHERE version_id = :vid"),
            {"vid": version_id},
        )
        n = dep_count.scalar() or 0
        if n > 0:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot delete: {n} deployment(s) reference this version. Delete deployments first or keep the version for audit history.",
            )

        await db.execute(
            text("DELETE FROM agent_versions WHERE id = :vid AND agent_did = :did"),
            {"vid": version_id, "did": agent_did},
        )
        await db.commit()
        return {"status": "deleted", "version_id": version_id, "version": row.version}
    except HTTPException:
        raise
    except SQLAlchemyError:
        # pass73.3.19: let the global SQLAlchemy handler classify DB input errors
        # (e.g. a non-UUID path param → asyncpg DataError) as 422 instead of this
        # blanket 500. Genuine DB errors still surface as 500 via that handler.
        raise
    except Exception as e:
        logger.error(f"Error deleting version: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/agents/{agent_did}/versions/{version_id}/rollback")
async def rollback_version(
    agent_did: str = Path(..., description="Agent DID"),
    version_id: str = Path(..., description="Version ID to rollback to"),
    db: AsyncSession = Depends(get_db),
    current_developer: Developer = Security(get_current_developer)
):
    """
    Rollback to a previous version.
    
    This uses the configuration snapshot stored with the version to restore
    the agent to its previous state.
    """
    try:
        result = await agent_cicd_service.rollback_version(
            db, agent_did, version_id, current_developer.id
        )
        return result
    except HTTPException:
        raise
    except SQLAlchemyError:
        # pass73.3.19: let the global SQLAlchemy handler classify DB input errors
        # (e.g. a non-UUID path param → asyncpg DataError) as 422 instead of this
        # blanket 500. Genuine DB errors still surface as 500 via that handler.
        raise
    except Exception as e:
        logger.error(f"Error rolling back version: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ==================== Deployment Management ====================

@router.post("/agents/{agent_did}/deployments")
async def trigger_deployment(
    agent_did: str = Path(..., description="Agent DID"),
    deployment_data: TriggerDeploymentBody = Body(default_factory=TriggerDeploymentBody),
    db: AsyncSession = Depends(get_db),
    current_developer: Developer = Security(get_current_developer)
):
    """
    Trigger a deployment for an agent.

    - If pipeline_id is provided and the pipeline has a webhook_url, sends a webhook
      to the agent's infrastructure to start the deployment process.
    - If pipeline_id is omitted (or pipeline has no webhook), creates a 'manual'
      deployment record immediately in 'success' state, useful for tracking
      version activations without an external pipeline.

    The agent will run the pipeline on their own infrastructure and report back
    the status via the /deployments/{id}/status callback endpoint.
    """
    try:
        result = await agent_cicd_service.trigger_deployment(
            db,
            agent_did,
            deployment_data.pipeline_id,
            current_developer.id,
            deployment_data.environment,
            deployment_data.version_id,
        )
        return result
    except HTTPException:
        raise
    except SQLAlchemyError:
        # pass73.3.19: let the global SQLAlchemy handler classify DB input errors
        # (e.g. a non-UUID path param → asyncpg DataError) as 422 instead of this
        # blanket 500. Genuine DB errors still surface as 500 via that handler.
        raise
    except Exception as e:
        logger.error(f"Error triggering deployment: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/agents/{agent_did}/deployments")
async def list_deployments(
    agent_did: str = Path(..., description="Agent DID"),
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
    environment: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_developer: Developer = Security(get_current_developer)
):
    """Get deployment history for an agent."""
    try:
        # Verify permission
        await agent_cicd_service._get_agent_with_permission(
            db, agent_did, current_developer.id
        )
        
        # Build query
        query = """
            SELECT d.id, d.deployment_type, d.environment, d.status,
                   d.started_at, d.completed_at, d.duration_seconds,
                   d.error_message, v.version,
                   p.pipeline_name
            FROM agent_deployments d
            LEFT JOIN agent_versions v ON d.version_id = v.id
            LEFT JOIN agent_pipelines p ON d.pipeline_id = p.id
            WHERE d.agent_did = :agent_did
        """
        
        params = {'agent_did': agent_did}
        
        if environment:
            query += " AND d.environment = :environment"
            params['environment'] = environment
        
        if status:
            query += " AND d.status = :status"
            params['status'] = status
        
        query += " ORDER BY d.started_at DESC LIMIT :limit OFFSET :offset"
        params['limit'] = limit
        params['offset'] = offset
        
        result = await db.execute(text(query), params)
        
        deployments = []
        for row in result:
            deployments.append({
                'id': str(row.id),
                'deployment_type': row.deployment_type,
                'environment': row.environment,
                'status': row.status,
                'version': row.version,
                'pipeline_name': row.pipeline_name,
                'started_at': row.started_at.isoformat(),
                'completed_at': row.completed_at.isoformat() if row.completed_at else None,
                'duration_seconds': row.duration_seconds,
                'error_message': row.error_message
            })
        
        return {"deployments": deployments}
        
    except HTTPException:
        raise
    except SQLAlchemyError:
        # pass73.3.19: let the global SQLAlchemy handler classify DB input errors
        # (e.g. a non-UUID path param → asyncpg DataError) as 422 instead of this
        # blanket 500. Genuine DB errors still surface as 500 via that handler.
        raise
    except Exception as e:
        logger.error(f"Error listing deployments: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/agents/{agent_did}/deployments/{deployment_id}")
async def get_deployment(
    agent_did: str = Path(..., description="Agent DID"),
    deployment_id: uuid.UUID = Path(..., description="Deployment ID (a UUID)"),
    db: AsyncSession = Depends(get_db),
    current_developer: Developer = Security(get_current_developer)
):
    """
    Get detailed information about a specific deployment. The id is a UUID: a malformed id answers 422.

    \f
    Get detailed information about a specific deployment.

    The id is typed as a UUID (§DEPS V0477): a malformed id is a 422 from the path's own validation and never reaches
    Postgres, where it raised a DataError the global handler turned into the same 422 after a round trip and a log line
    (agentvault2-a4 traced the lifecycle sweep's noise to it).
    """
    try:
        # Verify permission
        await agent_cicd_service._get_agent_with_permission(
            db, agent_did, current_developer.id
        )
        
        # Get deployment details
        result = await db.execute(
            text("""
                SELECT d.*, v.version, p.pipeline_name
                FROM agent_deployments d
                LEFT JOIN agent_versions v ON d.version_id = v.id
                LEFT JOIN agent_pipelines p ON d.pipeline_id = p.id
                WHERE d.id = :deployment_id AND d.agent_did = :agent_did
            """),
            {'deployment_id': str(deployment_id), 'agent_did': agent_did}
        )
        
        row = result.first()
        if not row:
            raise HTTPException(status_code=404, detail="Deployment not found")
        
        return {
            'id': str(row.id),
            'agent_did': row.agent_did,
            'deployment_type': row.deployment_type,
            'environment': row.environment,
            'status': row.status,
            'version': row.version,
            'pipeline_name': row.pipeline_name,
            'started_at': row.started_at.isoformat(),
            'completed_at': row.completed_at.isoformat() if row.completed_at else None,
            'duration_seconds': row.duration_seconds,
            'logs': row.logs,
            'error_message': row.error_message,
            'trigger_source': row.trigger_source
        }
        
    except HTTPException:
        raise
    except SQLAlchemyError:
        # pass73.3.19: let the global SQLAlchemy handler classify DB input errors
        # (e.g. a non-UUID path param → asyncpg DataError) as 422 instead of this
        # blanket 500. Genuine DB errors still surface as 500 via that handler.
        raise
    except Exception as e:
        logger.error(f"Error getting deployment: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/agents/{agent_did}/deployments/{deployment_id}/status")
async def update_deployment_status(
    agent_did: str = Path(..., description="Agent DID"),
    deployment_id: uuid.UUID = Path(..., description="Deployment ID (a UUID)"),
    status_update: UpdateDeploymentStatusBody = Body(...),
    current_developer: Developer = Security(get_current_developer),
    db: AsyncSession = Depends(get_db)
):
    """
    Update a deployment's status: the webhook the agent's infrastructure calls to report progress. The caller must
    be the agent's creator or an active member of its organization (the rule of every CI/CD route), and the
    deployment must be this agent's.

    \f
    Update deployment status (webhook endpoint for agents).

    This endpoint is called by the agent's infrastructure to report
    deployment progress and status.

    §MCPTEST30 (2026-10-01): it took a developer JWT and never used it, and the service looked the deployment up by id
    alone, so any developer rewrote (and, with no `logs` in the body, wiped) any deployment whose id they held. The caller
    now meets the rule every other CI/CD route uses (creator, or an active member of the agent's organization), and the
    deployment must be this agent's.
    """
    try:
        await agent_cicd_service._get_agent_with_permission(db, agent_did, current_developer.id)
        result = await agent_cicd_service.update_deployment_status(
            db, str(deployment_id), status_update.model_dump(exclude_unset=True), agent_did=agent_did
        )
        return result
    except HTTPException:
        raise
    except SQLAlchemyError:
        # pass73.3.19: let the global SQLAlchemy handler classify DB input errors
        # (e.g. a non-UUID path param → asyncpg DataError) as 422 instead of this
        # blanket 500. Genuine DB errors still surface as 500 via that handler.
        raise
    except Exception as e:
        logger.error(f"Error updating deployment status: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/agents/{agent_did}/deployments/{deployment_id}/logs")
async def append_deployment_logs(
    agent_did: str = Path(..., description="Agent DID"),
    deployment_id: uuid.UUID = Path(..., description="Deployment ID (a UUID)"),
    log_data: AppendDeploymentLogsBody = Body(default_factory=AppendDeploymentLogsBody),
    current_developer: Developer = Security(get_current_developer),
    db: AsyncSession = Depends(get_db)
):
    """
    Append logs to a deployment (a webhook for the agent's infrastructure). The caller must be allowed to act for
    the agent (the CI/CD rule), checked before anything is written.

    \f
    Append logs to a deployment (webhook endpoint for agents).

    §MCPTEST30 (2026-10-01): the caller must be allowed to act for the agent (the CI/CD rule), checked before anything is
    written; it took a developer JWT and never used it.
    """
    try:
        await agent_cicd_service._get_agent_with_permission(db, agent_did, current_developer.id)
        # P8.24b: Verify deployment exists before INSERT to avoid FK constraint violation
        check = await db.execute(
            text("SELECT id FROM agent_deployments WHERE id = :deployment_id AND agent_did = :agent_did"),
            {'deployment_id': str(deployment_id), 'agent_did': agent_did}
        )
        if not check.first():
            raise HTTPException(status_code=404, detail="Deployment not found")

        # Handle different log formats
        logs_to_append = log_data.logs or ''
        
        # If logs is a list of objects, convert to string
        if isinstance(logs_to_append, list):
            log_lines = []
            for entry in logs_to_append:
                if isinstance(entry, dict):
                    # Format: [timestamp] LEVEL: message
                    timestamp = entry.get('timestamp', '')
                    level = entry.get('level', 'INFO')
                    message = entry.get('message', '')
                    log_lines.append(f"[{timestamp}] {level}: {message}")
                else:
                    log_lines.append(str(entry))
            logs_to_append = '\n'.join(log_lines) + '\n'
        elif not isinstance(logs_to_append, str):
            logs_to_append = str(logs_to_append)
        
        # Append logs to existing
        await db.execute(
            text("""
                UPDATE agent_deployments
                SET logs = COALESCE(logs, '') || :new_logs
                WHERE id = :deployment_id AND agent_did = :agent_did
            """),
            {
                'deployment_id': str(deployment_id),
                'agent_did': agent_did,
                'new_logs': logs_to_append
            }
        )
        
        # Store webhook
        await db.execute(
            text("""
                INSERT INTO deployment_webhooks
                (id, deployment_id, webhook_type, payload, received_at, processed)
                VALUES
                (:id, :deployment_id, 'log_append', :payload, NOW(), true)
            """),
            {
                'id': str(uuid.uuid4()),
                'deployment_id': str(deployment_id),
                'payload': json.dumps(log_data.model_dump(exclude_unset=True))
            }
        )
        
        await db.commit()
        
        return {"message": "Logs appended successfully"}
    
    except HTTPException:
        raise
    except SQLAlchemyError:
        # pass73.3.19: let the global SQLAlchemy handler classify DB input errors
        # (e.g. a non-UUID path param → asyncpg DataError) as 422 instead of this
        # blanket 500. Genuine DB errors still surface as 500 via that handler.
        raise
    except Exception as e:
        logger.error(f"Error appending logs: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ==================== Template Marketplace ====================

@router.get("/pipeline-templates")
async def list_templates(
    category: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    sort_by: str = Query("downloads", regex="^(downloads|rating|price|created)$"),
    db: AsyncSession = Depends(get_db)
):
    """Browse pipeline templates in the marketplace."""
    try:
        query = """
            SELECT id, name, description, category, price_teg, author_did,
                   downloads, rating, tags, is_official, created_at
            FROM pipeline_templates
            WHERE 1=1
        """
        
        params = {}
        
        if category:
            query += " AND category = :category"
            params['category'] = category
        
        # Add sorting
        if sort_by == "downloads":
            query += " ORDER BY downloads DESC"
        elif sort_by == "rating":
            query += " ORDER BY rating DESC NULLS LAST"
        elif sort_by == "price":
            query += " ORDER BY price_teg ASC"
        else:
            query += " ORDER BY created_at DESC"
        
        query += " LIMIT :limit OFFSET :offset"
        params['limit'] = limit
        params['offset'] = offset
        
        result = await db.execute(text(query), params)
        
        templates = []
        for row in result:
            templates.append({
                'id': str(row.id),
                'name': row.name,
                'description': row.description,
                'category': row.category,
                'price_teg': row.price_teg,
                'author_did': row.author_did,
                'downloads': row.downloads,
                'rating': float(row.rating) if row.rating else None,
                'tags': row.tags,
                'is_official': row.is_official,
                'created_at': row.created_at.isoformat()
            })
        
        return {"templates": templates}
        
    except Exception as e:
        logger.error(f"Error listing templates: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/pipeline-templates")
async def create_template(
    template_data: CreateTemplateBody = Body(...),
    db: AsyncSession = Depends(get_db),
    current_developer: Developer = Security(get_current_developer)
):
    """Create a new pipeline template for the marketplace."""
    # D6-843 (2026-10-26): `is_official` marks a template as the frame's own (the template lists show it); it was taken
    # from any developer's body, so anyone could publish an "official" template. Only an administrator sets it now, on
    # an admin credential (admin_credential: an admin's scoped key does not reach it, D6-057)
    if template_data.is_official and not admin_credential(current_developer):
        raise HTTPException(status_code=403,
                            detail="is_official: only an administrator marks a pipeline template official")
    try:
        # TODO: Get author DID from developer's agent
        result = await agent_cicd_service.create_template(
            db, template_data.model_dump(exclude_unset=True), author_did=None
        )
        return result
    except HTTPException:
        raise
    except SQLAlchemyError:
        # pass73.3.19: let the global SQLAlchemy handler classify DB input errors
        # (e.g. a non-UUID path param → asyncpg DataError) as 422 instead of this
        # blanket 500. Genuine DB errors still surface as 500 via that handler.
        raise
    except Exception as e:
        logger.error(f"Error creating template: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/pipeline-templates/{template_id}/purchase")
async def purchase_template(
    template_id: str = Path(..., description="Template ID"),
    purchase_data: PurchaseTemplateBody = Body(...),
    db: AsyncSession = Depends(get_db),
    current_developer: Developer = Security(get_current_developer)
):
    """Purchase a pipeline template from the marketplace."""
    try:
        result = await agent_cicd_service.purchase_template(
            db, template_id, purchase_data.buyer_did, current_developer.id
        )
        return result
    except HTTPException:
        raise
    except SQLAlchemyError:
        # pass73.3.19: let the global SQLAlchemy handler classify DB input errors
        # (e.g. a non-UUID path param → asyncpg DataError) as 422 instead of this
        # blanket 500. Genuine DB errors still surface as 500 via that handler.
        raise
    except Exception as e:
        logger.error(f"Error purchasing template: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/pipeline-templates/{template_id}/download")
async def download_template(
    template_id: str = Path(..., description="Template ID"),
    db: AsyncSession = Depends(get_db),
    current_developer: Developer = Security(get_current_developer)
):
    """Download a purchased pipeline template."""
    try:
        result = await db.execute(
            text("""
                SELECT name, description, template_config, author_did, price_teg
                FROM pipeline_templates
                WHERE id = :template_id
            """),
            {'template_id': template_id}
        )

        template = result.first()
        if not template:
            raise HTTPException(status_code=404, detail="Template not found")

        # Purchase gate: free templates and your own templates download freely; a PAID
        # template needs a pipeline_purchases row from one of this developer's agents.
        try:
            price = float(template.price_teg or 0)
        except (TypeError, ValueError):
            price = 0.0
        if price > 0:
            is_author = (await db.execute(text(
                "SELECT 1 FROM agents WHERE did = :a AND creator_developer_id = :d LIMIT 1"
            ), {"a": template.author_did, "d": current_developer.id})).first() is not None
            purchased = is_author or (await db.execute(text(
                "SELECT 1 FROM pipeline_purchases WHERE template_id = :t AND buyer_did IN "
                "(SELECT did FROM agents WHERE creator_developer_id = :d) LIMIT 1"
            ), {"t": template_id, "d": current_developer.id})).first() is not None
            if not purchased:
                raise HTTPException(status_code=402,
                                    detail="Template not purchased — buy it first (author and free templates download without purchase)")

        config = template.template_config
        if config is None:
            config = {}
        elif not isinstance(config, dict):
            try:
                config = json.loads(config)
            except (json.JSONDecodeError, TypeError):
                config = {}

        return {
            'name': template.name,
            'description': template.description,
            'template_config': config or {},
            'author_did': template.author_did
        }
        
    except HTTPException:
        raise
    except SQLAlchemyError:
        # pass73.3.19: let the global SQLAlchemy handler classify DB input errors
        # (e.g. a non-UUID path param → asyncpg DataError) as 422 instead of this
        # blanket 500. Genuine DB errors still surface as 500 via that handler.
        raise
    except Exception as e:
        logger.error(f"Error downloading template: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ==================== Statistics ====================

@router.get("/agents/{agent_did}/cicd-stats")
async def get_cicd_stats(
    agent_did: str = Path(..., description="Agent DID"),
    db: AsyncSession = Depends(get_db),
    current_developer: Developer = Security(get_current_developer)
):
    """Get CI/CD statistics for an agent."""
    try:
        # Verify permission
        await agent_cicd_service._get_agent_with_permission(
            db, agent_did, current_developer.id
        )
        
        # Get agent stats
        agent_result = await db.execute(
            text("""
                SELECT cicd_enabled, last_deployment_at, deployment_success_rate,
                       total_deployments
                FROM agents
                WHERE did = :agent_did
            """),
            {'agent_did': agent_did}
        )
        
        agent = agent_result.first()
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        
        # Get deployment stats
        stats_result = await db.execute(
            text("""
                SELECT 
                    COUNT(*) as total_deployments,
                    COUNT(CASE WHEN status = 'success' THEN 1 END) as successful,
                    COUNT(CASE WHEN status = 'failed' THEN 1 END) as failed,
                    AVG(duration_seconds) as avg_duration,
                    MAX(started_at) as last_deployment
                FROM agent_deployments
                WHERE agent_did = :agent_did
            """),
            {'agent_did': agent_did}
        )
        
        stats = stats_result.first()
        
        return {
            'cicd_enabled': agent.cicd_enabled,
            'last_deployment_at': agent.last_deployment_at.isoformat() if agent.last_deployment_at else None,
            'deployment_success_rate': float(agent.deployment_success_rate) if agent.deployment_success_rate else 0,
            'total_deployments': agent.total_deployments,
            'statistics': {
                'total': stats.total_deployments,
                'successful': stats.successful,
                'failed': stats.failed,
                'avg_duration_seconds': float(stats.avg_duration) if stats.avg_duration else 0,
                'last_deployment': stats.last_deployment.isoformat() if stats.last_deployment else None
            }
        }
        
    except HTTPException:
        raise
    except SQLAlchemyError:
        # pass73.3.19: let the global SQLAlchemy handler classify DB input errors
        # (e.g. a non-UUID path param → asyncpg DataError) as 422 instead of this
        # blanket 500. Genuine DB errors still surface as 500 via that handler.
        raise
    except Exception as e:
        logger.error(f"Error getting CI/CD stats: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ── Relay Proxy Endpoints ──

async def _owned_relay_url(agent_did: str, developer: Any, db: AsyncSession) -> str:
    """The relay address of an agent the caller may operate, SSRF-guarded; refuses otherwise.

    §FESUITE (2026-10-01): both relay routes reached ANY agent's relay for ANY signed-in developer (start, stop and
    restart included), and dialled whatever the agent card declared, an internal address included. The rule is the
    CI/CD service's own (`_get_agent_with_permission`: the agent's creator, or an active member of its organization;
    404 / 403 otherwise), and the relay address is the card's endpoint, developer-supplied data, so it takes the buy
    rail's guard (`assert_callable_endpoint`: https, no credentials, public addresses only)."""
    from ..services.service_purchase import UnsafeEndpoint, assert_callable_endpoint

    await agent_cicd_service._get_agent_with_permission(db, agent_did, developer.id)
    relay_url = await _get_relay_url(agent_did, db)
    if not relay_url:
        raise HTTPException(404, "No relay configured for this agent")
    try:
        # it resolves the host: off the event loop
        await asyncio.to_thread(assert_callable_endpoint, relay_url)
    except UnsafeEndpoint as e:
        raise HTTPException(422, str(e))
    return relay_url


async def _relay_call(relay_url: str, agent_did: str, tool: str, arguments: Dict, timeout: float) -> Any:
    """One relay MCP tool call: the relay's result, or a 502 that says what came back instead.

    §MCPTEST30 (V0541): both relay routes returned `{}` with 200 for any JSON answer that was not a relay result (a
    missing `result` read as an empty one). An operator's sentinel declares its card at the operator's own public host
    (https://<operator>/agents/<name>), that host answers the relay path with its own 404 body, and the status route
    reported a relay with nothing to say (round 11, cloud-op alpha run 5d85e2dfd5404824)."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(f"{relay_url}/mcp/relay/rpc", json={
                "jsonrpc": "2.0", "id": 1,
                "method": "tools/call",
                "params": {"name": tool, "arguments": arguments},
            })
        data = resp.json()
    except Exception as e:
        # the relay is upstream: its silence is a 502, and its exception text (an internal address, a stack) stays here
        logger.warning(f"[relay] {agent_did}: the relay did not answer {tool}: {e}")
        raise HTTPException(502, "The agent's relay did not answer")
    result = data.get("result") if isinstance(data, dict) else None
    content = result.get("content") if isinstance(result, dict) else None
    text = content[0].get("text") if isinstance(content, list) and content and isinstance(content[0], dict) else None
    if resp.status_code != 200 or not isinstance(text, str):
        logger.warning(f"[relay] {agent_did}: the address answered {tool} with HTTP {resp.status_code}, not a relay result")
        raise HTTPException(502, f"The agent's address answered, but not as a relay (HTTP {resp.status_code})")
    try:
        return json.loads(text)
    except ValueError:
        raise HTTPException(502, "The agent's relay answered with something that is not JSON")


@router.get("/{agent_did}/relay/status")
async def relay_status(
    agent_did: str = Path(...),
    developer: Any = Security(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Proxy relay_status MCP tool call to the agent's relay (the agent's owner only; see _owned_relay_url)."""
    relay_url = await _owned_relay_url(agent_did, developer, db)
    return await _relay_call(relay_url, agent_did, "relay_status", {}, 5)


@router.post("/{agent_did}/relay/action")
async def relay_action(
    agent_did: str = Path(...),
    body: Dict = Body(...),
    developer: Any = Security(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Proxy a relay MCP tool call (relay_start, relay_stop, relay_restart); the agent's owner only (_owned_relay_url)."""
    tool = body.get("tool", "")
    if tool not in ("relay_start", "relay_stop", "relay_restart"):
        raise HTTPException(400, f"Invalid relay tool: {tool}")
    relay_url = await _owned_relay_url(agent_did, developer, db)
    return await _relay_call(relay_url, agent_did, tool, body.get("arguments", {}), 30)


async def _get_relay_url(agent_did: str, db: AsyncSession) -> Optional[str]:
    """Get the relay URL for an agent from its agent card URL."""
    from agentvault_registry.models import Agent

    result = await db.execute(select(Agent).where(Agent.did == agent_did))
    agent = result.scalar_one_or_none()
    if not agent:
        return None

    # Check if agent has an agent card with a URL
    try:
        from agentvault_registry.models import AgentCard as AgentCardModel
        card_result = await db.execute(
            select(AgentCardModel).where(AgentCardModel.agent_did == agent.did)
        )
        card = card_result.scalar_one_or_none()
        if card and (card.card_data or {}).get('url', ''):
            # The relay URL is the agent card URL's base (without /a2a path)
            url = str((card.card_data or {}).get('url', ''))
            # Strip /a2a or /a2a/ suffix to get relay base
            for suffix in ("/a2a/", "/a2a", "/"):
                if url.endswith(suffix):
                    url = url[:-len(suffix)]
                    break
            return url
    except Exception:
        pass

    return None
