"""
Metrics Collection Middleware for AgentVault Registry

This middleware tracks API requests made by agents and updates
metrics in real-time for performance monitoring and analytics.
"""
import time
import logging
import asyncio
from typing import Optional, Dict, Any
from datetime import datetime, timezone
from contextlib import asynccontextmanager

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
import jwt  # PyJWT (§DEPS: python-jose is gone)
from jwt import PyJWTError as JWTError

from ..database import get_db_context
from ..models import Agent, AgentMetrics, AgentRequest
from ..config import settings
from ..security import ALGORITHM

logger = logging.getLogger(__name__)

# Queue for async metric updates to avoid blocking requests
metrics_queue: asyncio.Queue = asyncio.Queue(maxsize=1000)


class MetricsCollectionMiddleware(BaseHTTPMiddleware):
    """
    Middleware to track agent API requests for metrics collection.
    
    This middleware:
    1. Extracts agent information from JWT tokens
    2. Tracks request timing and status codes
    3. Queues metrics for async database updates
    4. Does not block the request/response cycle
    """
    
    async def dispatch(self, request: Request, call_next):
        """Process request and collect metrics."""
        # Skip non-API routes and health checks
        if not request.url.path.startswith("/api/v1/") or request.url.path == "/api/v1/health":
            return await call_next(request)
        
        # Skip metrics endpoints to avoid recursion
        if "/metrics" in request.url.path:
            return await call_next(request)
        
        start_time = time.time()
        agent_info = None
        
        # Try to extract agent information from Authorization header
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]  # Remove "Bearer " prefix
            agent_info = await self._extract_agent_info(token)
            
            # Debug logging
            if agent_info:
                logger.info(f"Metrics middleware: Tracking request for agent {agent_info['agent_did']} to {request.url.path}")
            else:
                logger.debug(f"Metrics middleware: No agent info extracted for {request.url.path}")
        
        # Process the request
        response = await call_next(request)
        
        # Calculate response time
        response_time_ms = int((time.time() - start_time) * 1000)
        
        # If we have agent info, queue the metric update
        if agent_info and agent_info.get("agent_id"):
            metric_data = {
                "agent_id": agent_info["agent_id"],
                "agent_did": agent_info["agent_did"],
                "endpoint": str(request.url.path),
                "method": request.method,
                "status_code": response.status_code,
                "response_time_ms": response_time_ms,
                "timestamp": datetime.now(timezone.utc)
            }
            
            # Try to queue the metric, but don't block if queue is full
            try:
                metrics_queue.put_nowait(metric_data)
            except asyncio.QueueFull:
                logger.warning("Metrics queue is full, dropping metric")
        
        return response
    
    async def _extract_agent_info(self, token: str) -> Optional[Dict[str, Any]]:
        """Extract agent information from JWT token."""
        try:
            payload = jwt.decode(
                token,
                settings.API_KEY_SECRET,
                algorithms=[ALGORITHM]
            )
            
            # Debug: Log the entire payload
            logger.debug(f"JWT payload: {payload}")
            
            # Check if this is an agent token
            token_type = payload.get("type", "developer")  # Default to developer for backward compatibility
            logger.debug(f"Token type: {token_type}")
            
            if token_type == "agent":
                # Agent token
                agent_did = payload.get("sub")
                agent_id_str = payload.get("agent_id")
                
                # Convert agent_id from string to int
                agent_id = None
                if agent_id_str:
                    try:
                        agent_id = int(agent_id_str)
                    except (ValueError, TypeError):
                        logger.error(f"Invalid agent_id in token: {agent_id_str}")
                        agent_id = None
                
                logger.debug(f"Agent token found - DID: {agent_did}, ID: {agent_id} (from '{agent_id_str}')")
                
                if agent_did:
                    # If agent_id is missing, look it up from the database
                    if not agent_id:
                        try:
                            async with get_db_context() as db:
                                stmt = select(Agent).where(Agent.did == agent_did)
                                result = await db.execute(stmt)
                                agent = result.scalar_one_or_none()
                                if agent:
                                    agent_id = agent.id
                                    logger.debug(f"Found agent_id {agent_id} for DID {agent_did}")
                                else:
                                    logger.warning(f"Agent not found for DID: {agent_did}")
                                    return None
                        except Exception as e:
                            logger.error(f"Error looking up agent: {e}")
                            return None
                    
                    return {
                        "agent_id": agent_id,
                        "agent_did": agent_did
                    }
            else:
                logger.debug(f"Not an agent token, type is: {token_type}")
            
            return None
            
        except JWTError as e:
            logger.debug(f"JWT decode error: {e}")
            return None
        except Exception as e:
            logger.error(f"Error extracting agent info: {e}")
            return None


async def metrics_processor():
    """
    Background task to process queued metrics and update the database.
    
    This runs continuously, processing metrics from the queue and
    updating both the aggregated metrics and individual request logs.
    """
    logger.info("Starting metrics processor background task")
    
    while True:
        try:
            # Wait for metrics with timeout
            metric_data = await asyncio.wait_for(
                metrics_queue.get(),
                timeout=5.0  # Check every 5 seconds even if queue is empty
            )
            
            # Process the metric
            await process_metric(metric_data)
            
        except asyncio.TimeoutError:
            # No metrics to process, continue
            continue
        except Exception as e:
            logger.error(f"Error in metrics processor: {e}")
            await asyncio.sleep(1)  # Brief pause on error


async def process_metric(metric_data: Dict[str, Any]):
    """
    Process a single metric update.
    
    Updates both the aggregated AgentMetrics table and creates
    an entry in the AgentRequest log table.
    """
    try:
        async with get_db_context() as db:
            agent_id = metric_data["agent_id"]
            
            # First, ensure AgentMetrics record exists
            metrics_stmt = select(AgentMetrics).where(
                AgentMetrics.agent_id == agent_id
            )
            result = await db.execute(metrics_stmt)
            agent_metrics = result.scalar_one_or_none()
            
            if not agent_metrics:
                # Create new metrics record. §MCPTEST30 (V0551): in a savepoint, because two first requests of a NEW
                # agent can both read no row and both insert: the loser met ix_agent_metrics_agent_id, its whole
                # transaction rolled back (its metric and its request log lost) and an ERROR with a traceback was
                # logged (sbx-alpha 2026-10-02 16:55Z, twice, while new agents voted). The loser now reads the
                # winner's row and counts its request on it.
                try:
                    async with db.begin_nested():
                        agent_metrics = AgentMetrics(
                            agent_id=agent_id,
                            agent_did=metric_data["agent_did"],
                            total_requests=0,
                            successful_requests=0,
                            failed_requests=0,
                            total_response_time_ms=0
                        )
                        db.add(agent_metrics)
                        await db.flush()
                except IntegrityError:
                    agent_metrics = (await db.execute(metrics_stmt)).scalar_one()
            
            # Update aggregated metrics
            is_success = metric_data["status_code"] < 400
            
            agent_metrics.total_requests += 1
            if is_success:
                agent_metrics.successful_requests += 1
                agent_metrics.total_response_time_ms += metric_data["response_time_ms"]
            else:
                agent_metrics.failed_requests += 1
            
            agent_metrics.last_request_at = metric_data["timestamp"]
            agent_metrics.last_updated = metric_data["timestamp"]
            
            # Create request log entry
            request_log = AgentRequest(
                agent_id=agent_id,
                agent_did=metric_data["agent_did"],
                endpoint=metric_data["endpoint"],
                method=metric_data["method"],
                status_code=metric_data["status_code"],
                response_time_ms=metric_data["response_time_ms"],
                created_at=metric_data["timestamp"]
            )
            db.add(request_log)
            
            # Also update the agent's last_active_at
            agent_update_stmt = (
                update(Agent)
                .where(Agent.id == agent_id)
                .values(last_active_at=metric_data["timestamp"])
            )
            await db.execute(agent_update_stmt)
            
            # Commit all changes
            await db.commit()
            
            logger.debug(
                f"Updated metrics for agent {metric_data['agent_did']}: "
                f"{metric_data['method']} {metric_data['endpoint']} "
                f"({metric_data['status_code']}) in {metric_data['response_time_ms']}ms"
            )
            
    except Exception as e:
        logger.error(f"Error processing metric: {e}")


# Export the middleware class and processor
__all__ = ["MetricsCollectionMiddleware", "metrics_processor"]
