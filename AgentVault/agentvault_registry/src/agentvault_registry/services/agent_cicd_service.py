"""
Agent CI/CD Service
Manages CI/CD configurations for agents - infrastructure only, not execution!

IMPORTANT: We don't run agent code! We only:
1. Store pipeline configurations
2. Track versions
3. Send webhook triggers to agent infrastructure
4. Record deployment status updates
"""
import logging
import uuid
import json
import hashlib
import hmac
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any
from decimal import Decimal

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, and_, or_, func, text
from sqlalchemy.orm import selectinload

from ..models import Agent, Developer
from ..database import get_db
from ..config import settings
from ..background_tasks.agent_card_pullsync import trigger_pull_for_did
from ..event_emitter import get_event_emitter
from .webhook_service import WebhookUrlRefused, post_to_checked_address
from fastapi import HTTPException, status

logger = logging.getLogger(__name__)


# §pass47 A1 — best-effort CI/CD event emission. Failures NEVER raise — the
# service's database transaction is the source of truth, EventStore is audit.
async def _emit_cicd_event(event_type: str, agent_did: str, data: Dict[str, Any]) -> None:
    try:
        emitter = get_event_emitter()
        await emitter.emit(event_type=event_type, aggregate_id=agent_did, data=data)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[CICD-Event] emit {event_type} for {agent_did} failed: {e}")


async def webhook_url_refusal(url: Any) -> Optional[str]:
    """D6-842 (2026-10-26): why a pipeline's webhook URL may not be stored, or None when it may. The canonical webhook
    check (input_validators.validate_webhook_url: http(s), no literal internal address, no metadata host, a host that
    does not resolve to an internal address), as a developer webhook's has had since D6-760. The registry POSTs each
    deployment to this URL and recorded the start of a failed answer on the deployment, which the developer reads back,
    so an unchecked URL let a developer have the registry call an internal address. The send checks the URL again
    (_send_webhook), so a URL stored before this check, or one a path stored without it, is never called either."""
    from ..input_validators import avalidate_webhook_url
    if not isinstance(url, str) or len(url) > 500:
        return "a string of at most 500 characters"
    try:
        await avalidate_webhook_url(url)
    except ValueError as e:
        return str(e)
    return None


async def _refuse_unsafe_webhook_url(url: Any) -> None:
    """400 for a pipeline webhook URL webhook_url_refusal refuses (create, and update when the address changes)."""
    reason = await webhook_url_refusal(url)
    if reason:
        raise HTTPException(status_code=400, detail=f"Invalid webhook URL: {reason}")


# D6-842: the background tasks this service starts, held until they finish. The event loop keeps only a weak
# reference to a task, so one nobody holds can be collected before it finishes (a deployment left 'pending' for good).
_BACKGROUND_TASKS: set = set()


def _spawn(coro) -> "asyncio.Task":
    task = asyncio.create_task(coro)
    _BACKGROUND_TASKS.add(task)

    def _done(t: "asyncio.Task") -> None:
        _BACKGROUND_TASKS.discard(t)
        if not t.cancelled() and t.exception() is not None:
            logger.warning(f"[CICD] background task failed: {t.exception()!r}")

    task.add_done_callback(_done)
    return task


class AgentCICDService:
    """
    Manages CI/CD configurations for agents.
    IMPORTANT: We don't run anything! We just:
    1. Store configurations
    2. Track versions
    3. Send webhooks to agent infrastructure
    4. Record status updates
    """
    
    def __init__(self):
        self.webhook_timeout = 30  # seconds
        self.max_retries = 3
        
    # ==================== Pipeline Management ====================
    
    async def create_pipeline(
        self,
        db: AsyncSession,
        agent_did: str,
        pipeline_data: Dict[str, Any],
        developer_id: int
    ) -> Dict[str, Any]:
        """Create a new CI/CD pipeline configuration for an agent."""
        
        # Verify agent exists and developer has permission
        agent = await self._get_agent_with_permission(db, agent_did, developer_id)
        
        # Check for duplicate pipeline name
        existing = await db.execute(
            text("""SELECT COUNT(*) FROM agent_pipelines 
                    WHERE agent_did = :did AND pipeline_name = :name"""),
            {'did': agent_did, 'name': pipeline_data['pipeline_name']}
        )
        if existing.scalar() > 0:
            raise HTTPException(status_code=400, detail=f"Pipeline '{pipeline_data['pipeline_name']}' already exists")
        
        # Generate webhook secret if webhook URL provided
        webhook_secret = None
        if pipeline_data.get('webhook_url'):
            await _refuse_unsafe_webhook_url(pipeline_data['webhook_url'])
            webhook_secret = self._generate_webhook_secret()
        
        # Create pipeline record
        pipeline_id = str(uuid.uuid4())
        await db.execute(
            text("""
                INSERT INTO agent_pipelines 
                (id, agent_did, pipeline_name, pipeline_config, trigger_type, 
                 webhook_url, webhook_secret, is_active, environment_vars, 
                 notification_config, created_by, created_at, updated_at)
                VALUES 
                (:id, :agent_did, :name, :config, :trigger, :webhook_url, 
                 :webhook_secret, :is_active, :env_vars, :notifications, 
                 :created_by, NOW(), NOW())
            """),
            {
                'id': pipeline_id,
                'agent_did': agent_did,
                'name': pipeline_data['pipeline_name'],
                'config': json.dumps(pipeline_data.get('pipeline_config', {})),
                'trigger': pipeline_data.get('trigger_type', 'manual'),
                'webhook_url': pipeline_data.get('webhook_url'),
                'webhook_secret': webhook_secret,
                'is_active': pipeline_data.get('is_active', True),
                'env_vars': json.dumps(pipeline_data.get('environment_vars', {})),
                'notifications': json.dumps(pipeline_data.get('notification_config', {})),
                'created_by': developer_id
            }
        )
        
        # Log event for audit trail
        logger.info(f"Pipeline created: {pipeline_id} for agent {agent_did}")
        
        # Enable CI/CD for agent (if column exists)
        try:
            await db.execute(
                text("UPDATE agents SET cicd_enabled = true WHERE did = :agent_did"),
                {'agent_did': agent_did}
            )
        except Exception as e:
            # Column might not exist yet, ignore
            logger.debug(f"Could not update cicd_enabled: {e}")
        
        await db.commit()

        # §pass47 A1 — CI/CD audit trail.
        await _emit_cicd_event("PipelineCreated", agent_did, {
            "pipeline_id": pipeline_id,
            "pipeline_name": pipeline_data['pipeline_name'],
            "trigger_type": pipeline_data.get('trigger_type', 'manual'),
            "developer_id": developer_id,
        })

        return {
            'pipeline_id': pipeline_id,
            'webhook_secret': webhook_secret,
            'message': 'Pipeline created successfully'
        }

    async def get_pipelines(
        self,
        db: AsyncSession,
        agent_did: str,
        developer_id: int,
        include_inactive: bool = False,
    ) -> List[Dict[str, Any]]:
        """Get all pipelines for an agent.

        Phase F.2 (2026-05-26): by default returns only `is_active=True` rows.
        Soft-deleted pipelines (deactivated via delete_pipeline when deployments
        exist) are HIDDEN from the default list — they used to leak through,
        making it look like delete was a NO-OP from the caller's perspective.
        Pass `include_inactive=True` to see soft-deleted history.
        """
        # Verify permission
        await self._get_agent_with_permission(db, agent_did, developer_id)

        if include_inactive:
            sql = text("""
                SELECT id, pipeline_name, pipeline_config, trigger_type,
                       webhook_url, is_active, created_at, updated_at
                FROM agent_pipelines
                WHERE agent_did = :agent_did
                ORDER BY created_at DESC
            """)
        else:
            sql = text("""
                SELECT id, pipeline_name, pipeline_config, trigger_type,
                       webhook_url, is_active, created_at, updated_at
                FROM agent_pipelines
                WHERE agent_did = :agent_did AND is_active = TRUE
                ORDER BY created_at DESC
            """)
        result = await db.execute(sql, {'agent_did': agent_did})
        
        pipelines = []
        for row in result:
            pipelines.append({
                'id': str(row.id),
                'pipeline_name': row.pipeline_name,
                'pipeline_config': row.pipeline_config if isinstance(row.pipeline_config, dict) else json.loads(row.pipeline_config) if row.pipeline_config else {},
                'trigger_type': row.trigger_type,
                'webhook_url': row.webhook_url,
                'is_active': row.is_active,
                'created_at': row.created_at.isoformat(),
                'updated_at': row.updated_at.isoformat()
            })
        
        return pipelines
    
    async def update_pipeline(
        self,
        db: AsyncSession,
        agent_did: str,
        pipeline_id: str,
        pipeline_data: Dict[str, Any],
        developer_id: int
    ) -> Dict[str, Any]:
        """Update a CI/CD pipeline configuration."""
        
        # Verify permission
        await self._get_agent_with_permission(db, agent_did, developer_id)
        
        # Check pipeline exists (and read the address its secret belongs to)
        existing = await db.execute(
            text("""
                SELECT webhook_url FROM agent_pipelines
                WHERE id = :pipeline_id AND agent_did = :agent_did
            """),
            {'pipeline_id': pipeline_id, 'agent_did': agent_did}
        )
        row = existing.first()
        if row is None:
            raise HTTPException(status_code=404, detail="Pipeline not found")
        current_webhook_url = row[0]
        new_webhook_secret = None
        
        # Build update query dynamically based on provided fields
        update_fields = []
        params = {'pipeline_id': pipeline_id, 'agent_did': agent_did}
        
        if 'pipeline_name' in pipeline_data:
            update_fields.append("pipeline_name = :pipeline_name")
            params['pipeline_name'] = pipeline_data['pipeline_name']
        
        if 'pipeline_config' in pipeline_data:
            update_fields.append("pipeline_config = :pipeline_config")
            params['pipeline_config'] = json.dumps(pipeline_data['pipeline_config'])
        
        if 'trigger_type' in pipeline_data:
            update_fields.append("trigger_type = :trigger_type")
            params['trigger_type'] = pipeline_data['trigger_type']
        
        if 'webhook_url' in pipeline_data:
            update_fields.append("webhook_url = :webhook_url")
            params['webhook_url'] = pipeline_data['webhook_url']
            # §FESUITE: a new secret only when the address CHANGES, and returned once (as create returns it). Before,
            # every save that carried the unchanged URL rotated the secret and returned nothing, so editing a pipeline
            # silently broke the webhook it had configured.
            if pipeline_data['webhook_url'] and pipeline_data['webhook_url'] != current_webhook_url:
                # D6-842: a new address is checked like a new pipeline's; an unchanged one is checked when it is sent
                await _refuse_unsafe_webhook_url(pipeline_data['webhook_url'])
                new_webhook_secret = self._generate_webhook_secret()
                update_fields.append("webhook_secret = :webhook_secret")
                params['webhook_secret'] = new_webhook_secret
        
        if 'is_active' in pipeline_data:
            update_fields.append("is_active = :is_active")
            params['is_active'] = pipeline_data['is_active']
        
        if 'environment_vars' in pipeline_data:
            update_fields.append("environment_vars = :environment_vars")
            params['environment_vars'] = json.dumps(pipeline_data['environment_vars'])
        
        if 'notification_config' in pipeline_data:
            update_fields.append("notification_config = :notification_config")
            params['notification_config'] = json.dumps(pipeline_data['notification_config'])
        
        if not update_fields:
            raise HTTPException(status_code=400, detail="No fields to update")
        
        # Always update the updated_at timestamp
        update_fields.append("updated_at = NOW()")
        
        # Execute update
        await db.execute(
            text(f"""
                UPDATE agent_pipelines
                SET {', '.join(update_fields)}
                WHERE id = :pipeline_id AND agent_did = :agent_did
            """),
            params
        )
        
        await db.commit()

        # Log event for audit trail
        logger.info(f"Pipeline updated: {pipeline_id} for agent {agent_did}")

        # §pass47 A1
        await _emit_cicd_event("PipelineUpdated", agent_did, {
            "pipeline_id": pipeline_id,
            "updated_fields": [f.split('=', 1)[0].strip() for f in update_fields if '=' in f and 'NOW()' not in f],
            "developer_id": developer_id,
        })

        out = {
            'message': 'Pipeline updated successfully',
            'pipeline_id': pipeline_id
        }
        if new_webhook_secret:
            out['webhook_secret'] = new_webhook_secret   # shown once, like create's
        return out

    async def delete_pipeline(
        self,
        db: AsyncSession,
        agent_did: str,
        pipeline_id: str,
        developer_id: int
    ) -> Dict[str, Any]:
        """Delete a CI/CD pipeline."""
        
        # Verify permission
        await self._get_agent_with_permission(db, agent_did, developer_id)
        
        # Check if pipeline exists and get its name for logging
        result = await db.execute(
            text("""
                SELECT pipeline_name FROM agent_pipelines 
                WHERE id = :pipeline_id AND agent_did = :agent_did
            """),
            {'pipeline_id': pipeline_id, 'agent_did': agent_did}
        )
        
        pipeline = result.first()
        if not pipeline:
            raise HTTPException(status_code=404, detail="Pipeline not found")
        
        # Check if there are any deployments using this pipeline
        deployment_count_result = await db.execute(
            text("""
                SELECT COUNT(*) FROM agent_deployments
                WHERE pipeline_id = :pipeline_id
            """),
            {'pipeline_id': pipeline_id}
        )
        deployment_count = deployment_count_result.scalar() or 0  # §pass47 A1 — capture once

        if deployment_count > 0:
            # Soft delete - mark as inactive instead of deleting
            await db.execute(
                text("""
                    UPDATE agent_pipelines
                    SET is_active = false, updated_at = NOW()
                    WHERE id = :pipeline_id AND agent_did = :agent_did
                """),
                {'pipeline_id': pipeline_id, 'agent_did': agent_did}
            )
            message = f"Pipeline '{pipeline.pipeline_name}' deactivated (has deployment history)"
        else:
            # Hard delete - no deployment history
            await db.execute(
                text("""
                    DELETE FROM agent_pipelines
                    WHERE id = :pipeline_id AND agent_did = :agent_did
                """),
                {'pipeline_id': pipeline_id, 'agent_did': agent_did}
            )
            message = f"Pipeline '{pipeline.pipeline_name}' deleted successfully"
        
        await db.commit()

        # Log event for audit trail
        logger.info(f"Pipeline deleted/deactivated: {pipeline_id} for agent {agent_did}")

        # §pass47 A1 — emit Deleted (event reflects intent; service may have
        # soft-deleted to preserve deployment history).
        await _emit_cicd_event("PipelineDeleted", agent_did, {
            "pipeline_id": pipeline_id,
            "pipeline_name": pipeline.pipeline_name,
            "soft_deleted": deployment_count > 0,
            "developer_id": developer_id,
        })

        return {
            'message': message,
            'pipeline_id': pipeline_id
        }

    # ==================== Version Management ====================
    
    async def create_version(
        self,
        db: AsyncSession,
        agent_did: str,
        version_data: Dict[str, Any],
        developer_id: int
    ) -> Dict[str, Any]:
        """Register a new version for an agent."""
        
        # Verify permission
        await self._get_agent_with_permission(db, agent_did, developer_id)
        
        # Check for duplicate version
        existing = await db.execute(
            text("""
                SELECT COUNT(*) FROM agent_versions
                WHERE agent_did = :agent_did AND version = :version
            """),
            {'agent_did': agent_did, 'version': version_data['version']}
        )
        if existing.scalar() > 0:
            raise HTTPException(status_code=400, detail=f"Version {version_data['version']} already exists")
        
        # A6 (2026-07-24): capture the RESTORABLE registry-side config — the
        # agent card. This was `{}` ("TODO export/import service"), which made
        # every rollback a version-switch that restored nothing.
        config_snapshot = {}
        try:
            _card_row = await db.execute(
                text("SELECT card_data FROM agent_cards WHERE agent_did = :d"),
                {'d': agent_did}
            )
            _card = _card_row.first()
            if _card and _card[0]:
                config_snapshot = {
                    "card_data": _card[0],
                    "captured_at": datetime.now(timezone.utc).isoformat(),
                }
        except Exception as _snap_err:
            logger.warning(f"[CICD] card snapshot failed for {agent_did} (non-fatal): {_snap_err}")
        
        # Create version record
        version_id = str(uuid.uuid4())
        await db.execute(
            text("""
                INSERT INTO agent_versions
                (id, agent_did, version, changelog, configuration,
                 config_snapshot, is_current, is_stable, published_at, created_at)
                VALUES
                (:id, :agent_did, :version, :changelog, :configuration,
                 :config_snapshot, false, :is_stable, NOW(), NOW())
            """),
            {
                'id': version_id,
                'agent_did': agent_did,
                'version': version_data['version'],
                'changelog': version_data.get('release_notes', ''),  # Map release_notes to changelog
                'configuration': json.dumps({  # Combine artifacts and other config
                    'artifacts': version_data.get('artifacts', {}),
                    'metadata': version_data.get('metadata', {})
                }),
                'config_snapshot': json.dumps(config_snapshot) if config_snapshot else None,
                'is_stable': version_data.get('is_stable', True)
            }
        )
        
        # Log event for audit trail
        logger.info(f"Version created: {version_id} ({version_data['version']}) for agent {agent_did}")

        await db.commit()

        # §pass47 A1
        await _emit_cicd_event("VersionCreated", agent_did, {
            "version_id": version_id,
            "version": version_data['version'],
            "is_stable": version_data.get('is_stable', True),
            "developer_id": developer_id,
        })

        return {
            'version_id': version_id,
            'message': f"Version {version_data['version']} registered successfully"
        }

    async def activate_version(
        self,
        db: AsyncSession,
        agent_did: str,
        version_id: str,
        developer_id: int
    ) -> Dict[str, Any]:
        """Set a version as the active deployment."""
        
        # Verify permission
        await self._get_agent_with_permission(db, agent_did, developer_id)
        
        # Deactivate all other versions
        await db.execute(
            text("""
                UPDATE agent_versions 
                SET is_current = false 
                WHERE agent_did = :agent_did
            """),
            {'agent_did': agent_did}
        )
        
        # Activate specified version
        result = await db.execute(
            text("""
                UPDATE agent_versions 
                SET is_current = true 
                WHERE id = :version_id AND agent_did = :agent_did
                RETURNING version
            """),
            {'version_id': version_id, 'agent_did': agent_did}
        )
        
        version = result.scalar()
        if not version:
            raise HTTPException(status_code=404, detail="Version not found")
        
        # Log event for audit trail
        logger.info(f"Version activated: {version_id} ({version}) for agent {agent_did}")

        await db.commit()

        # §pass47 A1
        await _emit_cicd_event("VersionActivated", agent_did, {
            "version_id": version_id,
            "version": version,
            "developer_id": developer_id,
        })

        return {
            # A7 (2026-07-24): honest wording — activation is a registry-side
            # record + card pull-sync nudge; agents self-host, so the actual
            # deploy executes on the agent's own infrastructure.
            'message': (
                f"Version {version} activated (registry record updated; "
                f"deployment executes on the agent's own infrastructure)"
            )
        }

    async def rollback_version(
        self,
        db: AsyncSession,
        agent_did: str,
        target_version_id: str,
        developer_id: int
    ) -> Dict[str, Any]:
        """Rollback to a previous version using the stored configuration snapshot."""
        
        # Verify permission
        await self._get_agent_with_permission(db, agent_did, developer_id)
        
        # Get target version with config snapshot
        result = await db.execute(
            text("""
                SELECT version, config_snapshot 
                FROM agent_versions
                WHERE id = :version_id AND agent_did = :agent_did
            """),
            {'version_id': target_version_id, 'agent_did': agent_did}
        )
        
        row = result.first()
        if not row:
            raise HTTPException(status_code=404, detail="Version not found")
        
        version = row.version
        config_snapshot = row.config_snapshot if isinstance(row.config_snapshot, dict) else json.loads(row.config_snapshot) if row.config_snapshot else None
        
        # A6 (2026-07-24): actually restore the snapshot. Rollback used to read
        # the snapshot, discard it, and report success while restoring nothing.
        restored_config = False
        if not config_snapshot or not config_snapshot.get("card_data"):
            logger.warning(f"No configuration snapshot for version {target_version_id}, performing version switch only")
        else:
            try:
                # §TWOAGENT #10: a snapshot is owner content; the home extensions are stated at read, never restored.
                from .home_extensions import strip_home_extensions
                _res = await db.execute(
                    text("""
                        UPDATE agent_cards
                        SET card_data = CAST(:cd AS JSONB), updated_at = NOW()
                        WHERE agent_did = :d
                    """),
                    {'cd': json.dumps(strip_home_extensions(config_snapshot["card_data"])), 'd': agent_did}
                )
                restored_config = getattr(_res, "rowcount", 0) > 0
                logger.info(
                    f"[CICD] rollback restored card snapshot for {agent_did} "
                    f"(target v{version}, restored={restored_config})"
                )
            except Exception as _restore_err:
                logger.error(f"[CICD] card restore failed for {agent_did}: {_restore_err}")
        
        # Activate the rolled-back version
        await self.activate_version(db, agent_did, target_version_id, developer_id)
        
        # Update rollback count
        await db.execute(
            text("""
                UPDATE agent_versions 
                SET rollback_count = rollback_count + 1
                WHERE id = :version_id
            """),
            {'version_id': target_version_id}
        )
        
        # Log event for audit trail
        logger.info(f"Version rolled back: {target_version_id} ({version}) for agent {agent_did}")

        await db.commit()

        # §pass47 A1
        await _emit_cicd_event("VersionRolledBack", agent_did, {
            "target_version_id": target_version_id,
            "version": version,
            "developer_id": developer_id,
            "config_restored": restored_config,
        })

        return {
            'message': (
                f"Successfully rolled back to version {version}"
                + ("" if restored_config else " (version switch only — no config snapshot to restore)")
            ),
            'config_restored': restored_config,
        }
    
    # ==================== Deployment Management ====================

    async def _fire_pull_sync(self, agent_did: str) -> None:
        # §pass47 A2 — best-effort one-shot card pull after a deployment success.
        # Fire-and-forget; failures are logged, never raised to the API caller.
        try:
            result = await trigger_pull_for_did(agent_did)
            status_ = result.get("status")
            if status_ not in ("ok", "skipped"):
                logger.info(
                    f"[CICD→PullSync] {agent_did}: {status_} {result.get('reason','')}"
                )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[CICD→PullSync] {agent_did}: {e}")

    async def trigger_deployment(
        self,
        db: AsyncSession,
        agent_did: str,
        pipeline_id: Optional[str],
        developer_id: int,
        environment: str = 'production',
        version_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Trigger a deployment for an agent.

        Two modes:
        - With pipeline_id: sends webhook to agent's external infrastructure (pipeline-driven)
        - Without pipeline_id (manual mode): creates a completed deployment record immediately,
          useful for tracking version activations without an external pipeline.
        """
        
        # Verify permission
        await self._get_agent_with_permission(db, agent_did, developer_id)

        # ── MANUAL MODE: no pipeline_id provided ─────────────────────────────
        if not pipeline_id:
            # Resolve version: explicit version_id > active version
            if version_id:
                version_result = await db.execute(
                    text("""
                        SELECT id, version FROM agent_versions
                        WHERE id = :version_id AND agent_did = :agent_did
                        LIMIT 1
                    """),
                    {'version_id': version_id, 'agent_did': agent_did}
                )
            else:
                version_result = await db.execute(
                    text("""
                        SELECT id, version FROM agent_versions
                        WHERE agent_did = :agent_did AND is_current = true
                        LIMIT 1
                    """),
                    {'agent_did': agent_did}
                )

            version_row = version_result.first()
            version_label = version_row.version if version_row else 'unknown'
            resolved_version_id = str(version_row.id) if version_row else None

            # Create a manual deployment record (no webhook, immediately success)
            deployment_id = str(uuid.uuid4())
            await db.execute(
                text("""
                    INSERT INTO agent_deployments
                    (id, agent_did, pipeline_id, version_id, deployment_type, environment,
                     status, triggered_by, trigger_source, started_at, completed_at, duration_seconds)
                    VALUES
                    (:id, :agent_did, NULL, :version_id, 'manual', :environment,
                     'success', :triggered_by, 'api_manual', NOW(), NOW(), 0)
                """),
                {
                    'id': deployment_id,
                    'agent_did': agent_did,
                    'version_id': resolved_version_id,
                    'environment': environment,
                    'triggered_by': developer_id
                }
            )

            await db.commit()

            logger.info(f"Manual deployment recorded: {deployment_id} for agent {agent_did} (version {version_label})")

            # §pass47 A1 + A2 — emit audit event, then nudge pull-sync.
            await _emit_cicd_event("DeploymentTriggered", agent_did, {
                "deployment_id": deployment_id,
                "deployment_type": "manual",
                "version": version_label,
                "version_id": resolved_version_id,
                "environment": environment,
                "developer_id": developer_id,
            })
            _spawn(self._fire_pull_sync(agent_did))

            return {
                'deployment_id': deployment_id,
                'status': 'success',
                'message': f'Manual deployment recorded for version {version_label}',
                'deployment_type': 'manual'
            }

        # ── PIPELINE MODE: pipeline_id provided ──────────────────────────────
        
        # Get pipeline configuration
        result = await db.execute(
            text("""
                SELECT pipeline_name, pipeline_config, webhook_url, webhook_secret
                FROM agent_pipelines
                WHERE id = :pipeline_id AND agent_did = :agent_did AND is_active = true
            """),
            {'pipeline_id': pipeline_id, 'agent_did': agent_did}
        )
        
        pipeline = result.first()
        if not pipeline:
            raise HTTPException(status_code=404, detail="Active pipeline not found")
        
        if not pipeline.webhook_url:
            raise HTTPException(status_code=400, detail="Pipeline has no webhook URL configured")
        
        # Resolve version: explicit version_id > active version
        if version_id:
            version_result = await db.execute(
                text("""
                    SELECT id, version FROM agent_versions
                    WHERE id = :version_id AND agent_did = :agent_did
                    LIMIT 1
                """),
                {'version_id': version_id, 'agent_did': agent_did}
            )
        else:
            version_result = await db.execute(
                text("""
                    SELECT id, version FROM agent_versions
                    WHERE agent_did = :agent_did AND is_current = true
                    LIMIT 1
                """),
                {'agent_did': agent_did}
            )
        
        version_row = version_result.first()
        if not version_row:
            raise HTTPException(status_code=400, detail="No active version found")
        
        # Create deployment record
        deployment_id = str(uuid.uuid4())
        await db.execute(
            text("""
                INSERT INTO agent_deployments
                (id, agent_did, pipeline_id, version_id, deployment_type, environment,
                 status, triggered_by, trigger_source, started_at)
                VALUES
                (:id, :agent_did, :pipeline_id, :version_id, 'deploy', :environment,
                 'pending', :triggered_by, 'api', NOW())
            """),
            {
                'id': deployment_id,
                'agent_did': agent_did,
                'pipeline_id': pipeline_id,
                'version_id': str(version_row.id),
                'environment': environment,
                'triggered_by': developer_id
            }
        )
        
        await db.commit()
        
        # Send webhook to agent's infrastructure
        # Handle pipeline_config which might be dict or JSON string from DB
        pipeline_config = pipeline.pipeline_config
        if pipeline_config and not isinstance(pipeline_config, dict):
            try:
                pipeline_config = json.loads(pipeline_config)
            except (json.JSONDecodeError, TypeError):
                pipeline_config = {}
        elif not pipeline_config:
            pipeline_config = {}
            
        webhook_payload = {
            'deployment_id': deployment_id,
            'agent_did': agent_did,
            'pipeline_name': pipeline.pipeline_name,
            'pipeline_config': pipeline_config,
            'version': version_row.version,
            'environment': environment,
            'callback_url': f"{settings.BASE_URL}/api/v1/agents/{agent_did}/deployments/{deployment_id}/status"
        }
        
        # Sign webhook if secret exists
        headers = {}
        if pipeline.webhook_secret:
            signature = self._sign_webhook(webhook_payload, pipeline.webhook_secret)
            headers['X-AgentVault-Signature'] = signature
        
        # Send webhook asynchronously (held until it finishes, D6-842)
        _spawn(
            self._send_webhook(
                db, deployment_id, pipeline.webhook_url, webhook_payload, headers
            )
        )
        
        # Log event for audit trail
        logger.info(f"Deployment triggered: {deployment_id} for agent {agent_did}")

        # §pass47 A1 — emit audit. Pull-sync is deferred until
        # update_deployment_status reports success (via webhook callback).
        await _emit_cicd_event("DeploymentTriggered", agent_did, {
            "deployment_id": deployment_id,
            "deployment_type": "pipeline",
            "pipeline_id": pipeline_id,
            "pipeline_name": pipeline.pipeline_name,
            "version": version_row.version,
            "version_id": str(version_row.id),
            "environment": environment,
            "developer_id": developer_id,
        })

        return {
            'deployment_id': deployment_id,
            'status': 'pending',
            'message': 'Deployment triggered successfully',
            'callback_url': webhook_payload['callback_url']
        }
    
    async def update_deployment_status(
        self,
        db: AsyncSession,
        deployment_id: str,
        status_update: Dict[str, Any],
        *,
        agent_did: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Update deployment status (called by agent's webhook).

        §MCPTEST30 (2026-10-01): `agent_did` binds the deployment to the agent whose permission the route checked (a
        deployment of another agent answers 404), and a status update that carries no `logs` keeps the logs the
        deployment has (it set them to NULL, erasing every appended line on the routine success report)."""
        
        # Verify deployment exists (and, when the route names one, that it is this agent's)
        result = await db.execute(
            text("""
                SELECT agent_did, status, started_at
                FROM agent_deployments
                WHERE id = :deployment_id
                  AND (CAST(:agent_did AS TEXT) IS NULL OR agent_did = :agent_did)
            """),
            {'deployment_id': deployment_id, 'agent_did': agent_did}
        )
        
        deployment = result.first()
        if not deployment:
            raise HTTPException(status_code=404, detail="Deployment not found")
        
        # Calculate duration if completed
        duration = None
        completed_at = None
        if status_update['status'] in ['success', 'failed', 'cancelled']:
            completed_at = datetime.now(timezone.utc)
            duration = int((completed_at - deployment.started_at).total_seconds())
        
        # Update deployment record
        await db.execute(
            text("""
                UPDATE agent_deployments
                SET status = :status,
                    logs = COALESCE(:logs, logs),
                    error_message = :error_message,
                    completed_at = :completed_at,
                    duration_seconds = :duration,
                    webhook_response = :webhook_response
                WHERE id = :deployment_id
            """),
            {
                'deployment_id': deployment_id,
                'status': status_update['status'],
                'logs': status_update.get('logs'),
                'error_message': status_update.get('error_message'),
                'completed_at': completed_at,
                'duration': duration,
                'webhook_response': json.dumps(status_update.get('metadata', {}))
            }
        )
        
        # Update agent deployment metrics
        if status_update['status'] == 'success':
            await db.execute(
                text("""
                    UPDATE agents
                    SET last_deployment_at = NOW(),
                        total_deployments = total_deployments + 1,
                        deployment_success_rate = (
                            SELECT CAST(COUNT(CASE WHEN status = 'success' THEN 1 END) AS NUMERIC) * 100.0 / 
                                   CAST(COUNT(*) AS NUMERIC)
                            FROM agent_deployments
                            WHERE agent_did = :agent_did AND status IN ('success', 'failed')
                        )
                    WHERE did = :agent_did
                """),
                {'agent_did': deployment.agent_did}
            )
        
        # Store webhook update
        await db.execute(
            text("""
                INSERT INTO deployment_webhooks
                (id, deployment_id, webhook_type, payload, received_at, processed)
                VALUES
                (:id, :deployment_id, 'status_update', :payload, NOW(), true)
            """),
            {
                'id': str(uuid.uuid4()),
                'deployment_id': deployment_id,
                'payload': json.dumps(status_update)
            }
        )
        
        # Log event for audit trail
        logger.info(f"Deployment {status_update['status']}: {deployment_id} for agent {deployment.agent_did}")

        await db.commit()

        # §pass47 A1 — emit audit for every status change.
        await _emit_cicd_event("DeploymentStatusUpdated", deployment.agent_did, {
            "deployment_id": deployment_id,
            "status": status_update.get('status'),
            "duration_seconds": duration,
            "has_error": bool(status_update.get('error_message')),
        })

        # §pass47 A2 — pipeline deployment reached success via webhook callback; nudge pull-sync.
        if status_update.get('status') == 'success':
            _spawn(self._fire_pull_sync(deployment.agent_did))

        return {
            'message': f"Deployment status updated to {status_update['status']}"
        }
    
    # ==================== Template Marketplace ====================
    
    async def create_template(
        self,
        db: AsyncSession,
        template_data: Dict[str, Any],
        author_did: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a pipeline template for the marketplace."""
        
        template_id = str(uuid.uuid4())
        await db.execute(
            text("""
                INSERT INTO pipeline_templates
                (id, name, description, category, template_config, price_teg,
                 author_did, tags, is_official, created_at)
                VALUES
                (:id, :name, :description, :category, :config, :price,
                 :author, :tags, :is_official, NOW())
            """),
            {
                'id': template_id,
                'name': template_data['name'],
                'description': template_data.get('description'),
                'category': template_data['category'],
                'config': json.dumps(template_data['template_config']),
                'price': template_data.get('price_teg', 0),
                'author': author_did,
                'tags': template_data.get('tags', []),
                'is_official': template_data.get('is_official', False)
            }
        )
        
        await db.commit()
        
        return {
            'template_id': template_id,
            'message': 'Template created successfully'
        }
    
    async def purchase_template(
        self,
        db: AsyncSession,
        template_id: str,
        buyer_did: str,
        developer_id: int
    ) -> Dict[str, Any]:
        """Purchase a pipeline template from the marketplace.

        Paid templates charge the BUYER AGENT real value in the frame's own currency
        over the TEG rail (Commander directive 2026-07-24 — the old code minted a fake
        ``teg_tx_…`` id and delivered every "paid" template free, seller unpaid)."""

        # Verify buyer has permission (returns the agent row — the paying wallet)
        buyer_agent = await self._get_agent_with_permission(db, buyer_did, developer_id)

        # Get template details (author_did = the seller wallet; NULL = official template)
        result = await db.execute(
            text("""
                SELECT name, price_teg, template_config, author_did
                FROM pipeline_templates
                WHERE id = :template_id
            """),
            {'template_id': template_id}
        )
        
        template = result.first()
        if not template:
            raise HTTPException(status_code=404, detail="Template not found")
        
        # Check if already purchased
        existing = await db.execute(
            text("""
                SELECT COUNT(*) FROM pipeline_purchases
                WHERE template_id = :template_id AND buyer_did = :buyer_did
            """),
            {'template_id': template_id, 'buyer_did': buyer_did}
        )
        
        if existing.scalar() > 0:
            return {
                'message': 'Template already purchased',
                'template_config': template.template_config if isinstance(template.template_config, dict) else json.loads(template.template_config)
            }
        
        # Process payment if not free — REAL charge in the frame's currency (rule 13:
        # existing TEG rails only). Payment happens BEFORE the purchase row; a crash
        # between the two is safe because the rail call carries a durable per-purchase
        # Idempotency-Key — the retry replays from cache instead of charging twice.
        transaction_id = None
        if template.price_teg and template.price_teg > 0:
            transaction_id = await self._pay_for_template(
                buyer_agent, template_id, template.author_did, template.price_teg, template.name)
        
        # Record purchase
        await db.execute(
            text("""
                INSERT INTO pipeline_purchases
                (id, template_id, buyer_did, price_paid_teg, transaction_id, purchased_at)
                VALUES
                (:id, :template_id, :buyer_did, :price, :tx_id, NOW())
            """),
            {
                'id': str(uuid.uuid4()),
                'template_id': template_id,
                'buyer_did': buyer_did,
                'price': template.price_teg,
                'tx_id': transaction_id
            }
        )
        
        # Update download count
        await db.execute(
            text("""
                UPDATE pipeline_templates
                SET downloads = downloads + 1
                WHERE id = :template_id
            """),
            {'template_id': template_id}
        )
        
        await db.commit()
        
        return {
            'message': 'Template purchased successfully',
            'template_config': template.template_config if isinstance(template.template_config, dict) else json.loads(template.template_config) if template.template_config else {},
            'transaction_id': transaction_id
        }
    
    # ==================== Helper Methods ====================
    
    async def _pay_for_template(self, buyer_agent, template_id: str, author_did, price, template_name: str) -> str:
        """Charge the buyer agent ``price`` in the FRAME's own currency for a paid template.

        Rule-13: all value rides existing TEG rails — no new money path.
          * author_did set  → buyer → author via TEG ``/token/transfer`` (standard p2p;
            the normal transfer fee applies, the seller receives price − fee)
          * author_did NULL → official template: buyer → system treasury via the
            fee-free admin ``/treasury/receive`` (the guild escrow-deposit pattern)
        Exactly-once: both rails claim the durable Idempotency-Key
        ``cicd-tpl-{template_id}-{buyer_did}`` in ``teg_idempotency_records`` inside the
        money transaction, so a crash-retry between payment and the purchase-row insert
        replays from cache instead of double-charging. Raises 402 on decline — the
        purchase is never recorded unpaid."""
        from decimal import Decimal as _D
        import httpx as _httpx
        from fastapi import HTTPException as _HTTPX_EX
        from agentvault_registry.routers.teg_integration import (
            TEG_API_BASE_URL, TEG_API_V1_PREFIX, TEG_ADMIN_API_KEY,
            get_teg_token_for_agent, get_httpx_verify,
        )
        if author_did and author_did == buyer_agent.did:
            # The author "buying" their own template — nothing to move, still unlocks.
            return "self_purchase_no_charge"
        idem = f"cicd-tpl-{template_id}-{buyer_agent.did}"
        try:
            async with _httpx.AsyncClient(verify=get_httpx_verify()) as client:
                if author_did:
                    token = await get_teg_token_for_agent(buyer_agent.id, buyer_agent.did)
                    resp = await client.post(
                        f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}/token/transfer",
                        json={"receiver_agent_id": author_did, "amount": str(_D(price)),
                              "message": f"cicd_template:{template_id}"},
                        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": idem},
                        timeout=15.0,
                    )
                else:
                    resp = await client.post(
                        f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}/admin/treasury/receive",
                        json={"source_agent_id": buyer_agent.did, "amount": str(_D(price)),
                              "reason": "cicd_template", "reference_id": f"cicd-tpl:{template_id}"},
                        headers={"Authorization": f"Bearer {TEG_ADMIN_API_KEY}", "Idempotency-Key": idem},
                        timeout=15.0,
                    )
        except _httpx.RequestError as e:
            logger.error(f"[CICD-PAY] TEG unreachable for template {template_id}: {e}")
            raise _HTTPX_EX(status_code=502, detail="Template payment failed: ledger unreachable — not charged, retry")
        if resp.status_code not in (200, 201):
            # §LEDGERGATE (V0598): the TEG's ledger gate refused the payment (nothing moved): 503, the sentence,
            # Retry-After, never 402 (the buyer's purse is not the reason)
            from agentvault_registry.services.ledger_unavailable import ledger_refusal
            _refusal = ledger_refusal(resp)
            if _refusal is not None:
                raise _refusal
            try:
                detail = resp.json().get("detail") or resp.json().get("message") or resp.text[:160]
            except Exception:  # noqa: BLE001
                detail = resp.text[:160]
            logger.warning(f"[CICD-PAY] payment declined for template {template_id} buyer {buyer_agent.did}: "
                           f"{resp.status_code} {detail}")
            raise _HTTPX_EX(status_code=402, detail=f"Template payment failed: {detail}")
        data = resp.json()
        tx = data.get("transaction_id") or "unknown"
        logger.info(f"[CICD-PAY] {price} charged for template '{template_name}' ({template_id}): "
                    f"buyer={buyer_agent.did} → {'author ' + author_did if author_did else 'treasury'} tx={tx}")
        return tx

    async def _get_agent_with_permission(
        self,
        db: AsyncSession,
        agent_did: str,
        developer_id: int
    ) -> Agent:
        """Verify agent exists and developer has permission.

        §pass47 O2 — Permission rule (was a TODO since f040 shipped):
          * Caller is the original creator of the agent, OR
          * Agent belongs to an organization AND caller holds at least the `member` role in it (the organization's own
            role check, OrganizationService.check_member_permission: its owner, or an active member of weight >= 1).
        Either condition alone is sufficient; otherwise 403.

        §SECFIX D6-499 (2026-10-16): any ACTIVE membership passed, a guest's included, so a guest could create and
        delete pipelines, publish, activate and roll back versions, trigger deployments and drive the agent's relay. A
        guest reads the organization; its CI/CD, the organization's summary included, starts at `member`.
        """

        result = await db.execute(
            select(Agent).where(Agent.did == agent_did)
        )
        agent = result.scalar_one_or_none()

        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent {agent_did} not found")

        is_creator = agent.creator_developer_id == developer_id

        is_org_member = False
        if not is_creator and agent.organization_id:
            from .organization_service import OrganizationService
            is_org_member = await OrganizationService.check_member_permission(
                db, str(agent.organization_id), developer_id, "member")

        if not (is_creator or is_org_member):
            raise HTTPException(
                status_code=403,
                detail="Pipeline operations on this agent require ownership, or a member role or above in its organization",
            )

        return agent
    
    def _generate_webhook_secret(self) -> str:
        """Generate a secure webhook secret."""
        return hashlib.sha256(uuid.uuid4().bytes).hexdigest()
    
    def _sign_webhook(self, payload: Dict[str, Any], secret: str) -> str:
        """Sign webhook payload with HMAC-SHA256."""
        payload_bytes = json.dumps(payload, sort_keys=True).encode()
        signature = hmac.new(
            secret.encode(),
            payload_bytes,
            hashlib.sha256
        ).hexdigest()
        return f"sha256={signature}"
    
    async def _send_webhook(
        self,
        db: AsyncSession,  # kept for backward signature compat; not used (we open fresh sessions per attempt)
        deployment_id: str,
        url: str,
        payload: Dict[str, Any],
        headers: Dict[str, str]
    ):
        """Send webhook to agent's infrastructure (async background task).

        §pass47 A7 — Retry policy:
          * Up to 5 attempts on network errors / 5xx responses.
          * Exponential backoff: 2s · 8s · 32s · 128s · 512s (~12 min total).
          * 2xx → success, mark 'running'.
          * 4xx → immediate fail (caller bug, retries won't help).
          * Exhausted retries → fail with last error.
          * D6-842: a URL the address check refuses → immediate fail, nothing sent.
        Each attempt opens its own DB session so the caller request's session
        can be safely closed.

        D6-842 (2026-10-26): each attempt goes through the developer webhook's delivery (webhook_service.
        post_to_checked_address, SEC-14): the URL is checked at the moment of sending and the request connects only to
        an address that check approved. It used to be a plain POST to the stored URL, which no check had ever seen.
        """
        from ..database import AsyncSessionLocal as _SessionLocal

        BACKOFF_SECONDS = (2, 8, 32, 128, 512)
        agent_did = payload.get("agent_did", "")  # for event aggregate_id
        last_error: Optional[str] = None

        for attempt, delay in enumerate(BACKOFF_SECONDS, start=1):
            try:
                request = httpx.Request("POST", url, json=payload, headers=headers)
                async with httpx.AsyncClient(timeout=self.webhook_timeout) as client:
                    response = await post_to_checked_address(
                        client, url, request.content,
                        {**headers, "Content-Type": request.headers["Content-Type"]},
                    )

                # 2xx — success.
                if 200 <= response.status_code < 300:
                    async with _SessionLocal() as session:
                        await session.execute(
                            text("""
                                UPDATE agent_deployments
                                SET status = 'running'
                                WHERE id = :deployment_id AND status = 'pending'
                            """),
                            {'deployment_id': deployment_id},
                        )
                        await session.commit()
                    if attempt > 1:
                        logger.info(
                            f"[CICD-Webhook] deployment={deployment_id} succeeded on attempt {attempt}"
                        )
                    return

                # 4xx — caller bug, no retries.
                if 400 <= response.status_code < 500:
                    last_error = f"4xx (no retry): {response.status_code} {response.text[:200]}"
                    logger.warning(f"[CICD-Webhook] deployment={deployment_id} {last_error}")
                    break

                # 5xx — retryable.
                last_error = f"5xx: {response.status_code} {response.text[:200]}"
                logger.warning(
                    f"[CICD-Webhook] deployment={deployment_id} attempt {attempt}/5 → {last_error}"
                )
            except WebhookUrlRefused as e:
                # nothing was sent: the reason is the check's, and retrying cannot change it
                last_error = f"refused (no retry): {e}"
                logger.warning(f"[CICD-Webhook] deployment={deployment_id} {last_error}")
                break
            except Exception as e:
                last_error = f"network: {e}"
                logger.warning(
                    f"[CICD-Webhook] deployment={deployment_id} attempt {attempt}/5 → {last_error}"
                )

            # Backoff before next attempt (unless this was the last attempt).
            if attempt < len(BACKOFF_SECONDS):
                await asyncio.sleep(delay)

        # All attempts exhausted (or 4xx short-circuit) — mark failed.
        async with _SessionLocal() as session:
            await session.execute(
                text("""
                    UPDATE agent_deployments
                    SET status = 'failed',
                        error_message = :error,
                        completed_at = NOW()
                    WHERE id = :deployment_id AND status = 'pending'
                """),
                {
                    'deployment_id': deployment_id,
                    'error': f"Webhook delivery exhausted: {last_error}",
                },
            )
            await session.commit()
        # §pass47 A7 — observability event (only fires on final exhaustion;
        # intermediate retries are visible via logs only to avoid event spam).
        await _emit_cicd_event("DeploymentWebhookExhausted", agent_did, {
            "deployment_id": deployment_id,
            "attempts": len(BACKOFF_SECONDS),
            "last_error": last_error,
        })


# Singleton instance
agent_cicd_service = AgentCICDService()
