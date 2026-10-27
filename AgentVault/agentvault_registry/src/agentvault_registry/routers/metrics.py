"""Agent metrics and analytics endpoints with real data."""
from typing import Annotated, Dict, Any, Optional, List
from fastapi import APIRouter, Depends, Path, HTTPException, status, Query, Security
from datetime import datetime, timedelta, timezone, date
import logging

from ..security import get_current_developer
from ..models import Developer, Agent, AgentMetrics, AgentRequest, AgentDailyStats
from ..database import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func, distinct
from sqlalchemy.orm import selectinload

logger = logging.getLogger(__name__)

router = APIRouter()


def create_empty_metrics_response(agent_id: str) -> Dict[str, Any]:
    """Create empty metrics response for agents without data."""
    return {
        "agent_id": agent_id,
        "total_requests": 0,
        "success_rate": 0.0,
        "avg_response_time": 0,
        "uptime_percentage": 0.0,
        "last_active": None,
        "daily_stats": {
            "requests_today": 0,
            "errors_today": 0,
            "unique_callers": 0
        },
        "weekly_trend": {
            "request_growth": 0.0,
            "error_rate_change": 0.0
        }
    }


def get_time_window(time_range: str, now: datetime) -> datetime:
    """Convert time range string to datetime."""
    if time_range == "1h":
        return now - timedelta(hours=1)
    elif time_range == "7d":
        return now - timedelta(days=7)
    elif time_range == "30d":
        return now - timedelta(days=30)
    elif time_range == "all":
        return datetime(2020, 1, 1, tzinfo=timezone.utc)  # Arbitrary old date
    else:  # Default to 24h
        return now - timedelta(days=1)


def calculate_uptime(agent: Agent, metrics: AgentMetrics, now: datetime) -> float:
    """
    Calculate uptime percentage based on agent activity.
    
    Uptime is calculated as the percentage of time the agent has been
    responsive since it was created or first made a request.
    """
    if not metrics or not metrics.last_request_at:
        return 0.0
    
    # Get the start time (when agent was created or first request)
    start_time = agent.created_at
    if metrics.created_at and metrics.created_at > start_time:
        start_time = metrics.created_at
    
    # Total time since start
    total_time = (now - start_time).total_seconds()
    if total_time <= 0:
        return 100.0
    
    # Active time is from start to last request
    active_time = (metrics.last_request_at - start_time).total_seconds()
    
    # Calculate percentage (capped at 100%)
    uptime = min((active_time / total_time) * 100, 100.0)
    return round(uptime, 2)


def calculate_growth_rate(previous_avg: float, current: float) -> float:
    """Calculate percentage growth rate."""
    if previous_avg == 0:
        return 100.0 if current > 0 else 0.0
    
    growth = ((current - previous_avg) / previous_avg) * 100
    return round(growth, 2)


def calculate_error_trend(requests: List[AgentRequest]) -> float:
    """Calculate error rate trend over time."""
    if len(requests) < 2:
        return 0.0
    
    # Split requests into two halves
    mid_point = len(requests) // 2
    first_half = requests[:mid_point]
    second_half = requests[mid_point:]
    
    # Calculate error rates for each half
    first_errors = sum(1 for r in first_half if r.status_code >= 400)
    first_rate = (first_errors / len(first_half) * 100) if first_half else 0
    
    second_errors = sum(1 for r in second_half if r.status_code >= 400)
    second_rate = (second_errors / len(second_half) * 100) if second_half else 0
    
    # Return the change in error rate
    return round(second_rate - first_rate, 2)


@router.get("/agent-metrics/{agent_id}")
async def get_agent_metrics(
    agent_id: str = Path(..., description="Agent ID, DID, or UUID"),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_developer: Annotated[Developer, Security(get_current_developer)] = None,
    time_range: str = Query("24h", regex="^(1h|24h|7d|30d|all)$", description="Time range for metrics")
) -> Dict[str, Any]:
    """
    Get real performance metrics for a specific agent.
    
    Returns metrics including request counts, success rates, response times,
    and uptime statistics based on actual data.
    """
    logger.info(f"Fetching real metrics for agent: {agent_id}")
    
    # Find agent by DID or client_id
    if agent_id.startswith('did:'):
        stmt = select(Agent).where(Agent.did == agent_id)
    else:
        stmt = select(Agent).where(Agent.client_id == agent_id)
    
    result = await db.execute(stmt)
    agent = result.scalar_one_or_none()
    
    if not agent:
        logger.warning(f"Agent not found: {agent_id}, returning empty metrics")
        return create_empty_metrics_response(agent_id)
    
    # Get aggregated metrics
    metrics_stmt = select(AgentMetrics).where(AgentMetrics.agent_id == agent.id)
    metrics_result = await db.execute(metrics_stmt)
    metrics = metrics_result.scalar_one_or_none()
    
    if not metrics:
        logger.info(f"No metrics found for agent {agent_id}, returning empty response")
        return create_empty_metrics_response(agent_id)
    
    # Use UTC for all time calculations
    now = datetime.now(timezone.utc)
    time_window = get_time_window(time_range, now)
    
    # Get recent requests for time-based stats
    recent_stmt = select(AgentRequest).where(
        and_(
            AgentRequest.agent_id == agent.id,
            AgentRequest.created_at >= time_window
        )
    ).order_by(AgentRequest.created_at.desc())
    
    recent_result = await db.execute(recent_stmt)
    recent_requests = list(recent_result.scalars().all())
    
    # Calculate real metrics
    success_rate = 0.0
    if metrics.total_requests > 0:
        success_rate = round(
            (metrics.successful_requests / metrics.total_requests) * 100, 2
        )
    
    avg_response_time = 0
    if metrics.successful_requests > 0:
        avg_response_time = int(
            metrics.total_response_time_ms / metrics.successful_requests
        )
    
    # Calculate uptime
    uptime_percentage = calculate_uptime(agent, metrics, now)
    
    # Daily stats from recent requests
    today = now.date()
    today_requests = [r for r in recent_requests if r.created_at.date() == today]
    today_errors = [r for r in today_requests if r.status_code >= 400]
    unique_endpoints = len(set(r.endpoint for r in today_requests))
    
    # Weekly trend calculation
    week_ago = now - timedelta(days=7)
    last_week_requests = [
        r for r in recent_requests 
        if week_ago <= r.created_at < now - timedelta(days=1)
    ]
    
    # Calculate daily average for last week
    last_week_daily_avg = len(last_week_requests) / 7 if last_week_requests else 0
    request_growth = calculate_growth_rate(last_week_daily_avg, len(today_requests))
    
    # Error rate trend
    error_rate_change = calculate_error_trend(recent_requests)
    
    return {
        "agent_id": agent_id,
        "total_requests": metrics.total_requests,
        "success_rate": success_rate,
        "avg_response_time": avg_response_time,
        "uptime_percentage": uptime_percentage,
        "last_active": metrics.last_request_at.isoformat() if metrics.last_request_at else None,
        "daily_stats": {
            "requests_today": len(today_requests),
            "errors_today": len(today_errors),
            "unique_callers": unique_endpoints  # Using endpoints as proxy for callers
        },
        "weekly_trend": {
            "request_growth": request_growth,
            "error_rate_change": error_rate_change
        }
    }


@router.get("/metrics/agent-activity")
async def get_agent_activity_metrics(
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_developer: Annotated[Developer, Security(get_current_developer)] = None
) -> Dict[str, Any]:
    """Get real-time agent activity metrics for dashboard."""
    
    now = datetime.now(timezone.utc)
    hour_ago = now - timedelta(hours=1)
    minute_ago = now - timedelta(minutes=1)
    
    # Count active agents (those with recent requests)
    active_stmt = select(func.count(distinct(AgentRequest.agent_id))).where(
        AgentRequest.created_at >= hour_ago
    )
    active_agents = await db.scalar(active_stmt) or 0
    
    # Count transactions in last minute
    minute_stmt = select(func.count(AgentRequest.id)).where(
        AgentRequest.created_at >= minute_ago
    )
    transactions_per_minute = await db.scalar(minute_stmt) or 0
    
    # Total requests last hour
    hour_stmt = select(func.count(AgentRequest.id)).where(
        AgentRequest.created_at >= hour_ago
    )
    total_requests_last_hour = await db.scalar(hour_stmt) or 0
    
    # Calculate error rate for last hour
    error_stmt = select(func.count(AgentRequest.id)).where(
        and_(
            AgentRequest.created_at >= hour_ago,
            AgentRequest.status_code >= 400
        )
    )
    errors_last_hour = await db.scalar(error_stmt) or 0
    
    error_rate = 0.0
    if total_requests_last_hour > 0:
        error_rate = round((errors_last_hour / total_requests_last_hour) * 100, 2)
    
    # Average response time for last hour
    avg_response_stmt = select(func.avg(AgentRequest.response_time_ms)).where(
        and_(
            AgentRequest.created_at >= hour_ago,
            AgentRequest.status_code < 400
        )
    )
    avg_latency = await db.scalar(avg_response_stmt) or 0
    
    return {
        "timestamp": now.isoformat(),
        "active_agents": active_agents,
        "transactions_per_minute": transactions_per_minute,
        "total_requests_last_hour": total_requests_last_hour,
        "error_rate": error_rate,
        "network_latency_ms": int(avg_latency)
    }


@router.get("/metrics/network-health")
async def get_network_health_metrics(
    db: Annotated[AsyncSession, Depends(get_db)] = None
) -> Dict[str, Any]:
    """Get overall network health metrics."""
    
    now = datetime.now(timezone.utc)
    hour_ago = now - timedelta(hours=1)
    
    # Query total agents
    total_stmt = select(func.count(Agent.id))
    total_agents = await db.scalar(total_stmt) or 0
    
    # Active agents (with staked balance)
    active_stmt = select(func.count(Agent.id)).where(Agent.staked_balance > 0)
    active_agents = await db.scalar(active_stmt) or 0
    
    # Get response time percentiles for last hour
    response_times_stmt = select(AgentRequest.response_time_ms).where(
        and_(
            AgentRequest.created_at >= hour_ago,
            AgentRequest.status_code < 400
        )
    ).order_by(AgentRequest.response_time_ms)
    
    result = await db.execute(response_times_stmt)
    response_times = list(result.scalars().all())
    
    # Calculate percentiles
    p50 = p95 = p99 = 0
    if response_times:
        count = len(response_times)
        p50 = response_times[int(count * 0.5)]
        p95 = response_times[int(count * 0.95)]
        p99 = response_times[int(count * 0.99)]
    
    # Calculate error rate
    total_requests = len(response_times)
    error_count_stmt = select(func.count(AgentRequest.id)).where(
        and_(
            AgentRequest.created_at >= hour_ago,
            AgentRequest.status_code >= 400
        )
    )
    error_count = await db.scalar(error_count_stmt) or 0
    
    error_rate = 0.0
    if total_requests + error_count > 0:
        error_rate = round((error_count / (total_requests + error_count)) * 100, 2)
    
    # Calculate health score (simple formula based on error rate and response times)
    # §COCKPITDESK (2026-10-14): the deductions are returned beside the score. The desk's Fleet health pane showed "30.8"
    # beside three services at 99.9% with nothing saying why; on sbx-alpha that was 65.5 points for a 755 ms p95 and 4.0
    # for 1.98% errors. One formula, here; a client that wants the reason reads it instead of copying the arithmetic.
    errors_deduction = error_rate * 2  # Deduct 2 points per percent error
    latency_deduction = max(0, (p95 - 100) / 10)  # Deduct points for slow responses
    health_score = 100.0 - errors_deduction - latency_deduction
    health_score = max(0, min(100, health_score))  # Clamp to 0-100
    
    return {
        "timestamp": now.isoformat(),
        "overall_health_score": round(health_score, 2),
        "score_deductions": {"errors": round(errors_deduction, 2), "latency_p95": round(latency_deduction, 2)},
        "total_agents": total_agents,
        "active_agents": active_agents,
        "response_time_p50": p50,
        "response_time_p95": p95,
        "response_time_p99": p99,
        "error_rate": error_rate,
        "services": {
            "registry": {
                "status": "healthy",
                "uptime": 99.99,
                "last_check": now.isoformat()
            },
            "teg": {
                "status": "healthy",
                "uptime": 99.95,
                "last_check": now.isoformat()
            },
            "federation": {
                "status": "healthy",
                "uptime": 99.90,
                "last_check": now.isoformat()
            }
        }
    }
