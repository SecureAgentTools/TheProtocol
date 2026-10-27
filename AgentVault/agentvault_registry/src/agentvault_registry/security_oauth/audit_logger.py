"""
Security Audit Logging Module.

Provides comprehensive audit logging for security events
in the cross-registry OAuth system.
"""

import logging
import json
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from enum import Enum
import uuid
from contextvars import ContextVar
from collections import defaultdict

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import Column, String, DateTime, Text, Enum as SQLEnum
from sqlalchemy.orm import declarative_base  # §DEPS: its home since SQLAlchemy 1.4; the ext.declarative alias is deprecated

from ..config import settings

logger = logging.getLogger(__name__)

# Context variable for correlation ID tracking
correlation_id_var: ContextVar[Optional[str]] = ContextVar('correlation_id', default=None)


class SecurityEventType(str, Enum):
    """Types of security events to audit."""
    TOKEN_EXCHANGE_REQUEST = "token_exchange_request"
    TOKEN_EXCHANGE_SUCCESS = "token_exchange_success"
    TOKEN_EXCHANGE_FAILURE = "token_exchange_failure"
    TOKEN_INTROSPECTION = "token_introspection"
    TOKEN_REVOCATION = "token_revocation"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    INVALID_SCOPE = "invalid_scope"
    JTI_REUSE_ATTEMPT = "jti_reuse_attempt"
    UNAUTHORIZED_ACCESS = "unauthorized_access"
    CROSS_TEG_TRANSFER_INITIATED = "cross_teg_transfer_initiated"
    CROSS_TEG_TRANSFER_COMPLETED = "cross_teg_transfer_completed"
    CROSS_TEG_TRANSFER_FAILED = "cross_teg_transfer_failed"
    SUSPICIOUS_ACTIVITY = "suspicious_activity"
    # §pass68 (2026-05-23) — MCP per-tool audit logging. Schema added by
    # alembic 0082_mcp_audit_event_types. mcp_tool_invoked covers both
    # successful and auth-failed tool calls (outcome field distinguishes);
    # mcp_tool_failed is for unhandled dispatch exceptions; admin_read_mcp_audit
    # is written into the TARGET developer's log when admin queries someone
    # else's MCP audit (self-watching admin pattern).
    MCP_TOOL_INVOKED = "mcp_tool_invoked"
    MCP_TOOL_FAILED = "mcp_tool_failed"
    ADMIN_READ_MCP_AUDIT = "admin_read_mcp_audit"


Base = declarative_base()


class SecurityAuditLog(Base):
    """Security audit log database model."""
    __tablename__ = "security_audit_logs"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    # §pass47 C4 — column is TIMESTAMP WITHOUT TIME ZONE in this DB;
    # supply naive UTC to avoid "can't subtract offset-naive and offset-aware".
    timestamp = Column(
        DateTime, nullable=False,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
    )
    # §pass47 C4 — name explicit so SQLAlchemy doesn't default to "securityeventtype"
    # (the DB enum is "security_event_type"). Without this, every INSERT errored
    # with "type securityeventtype does not exist" — pre-existing bug surfaced
    # when C4 wired the helper into the rotate-signing-key endpoint.
    event_type = Column(
        SQLEnum(
            SecurityEventType,
            name="security_event_type",
            create_type=False,
            # DB enum values are lowercase ("suspicious_activity"); Python enum
            # NAMES are uppercase. Tell SQLAlchemy to serialize the VALUES.
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False, index=True,
    )
    correlation_id = Column(String(36), nullable=True, index=True)
    
    # Actor information
    actor_type = Column(String(50), nullable=True)  # "registry", "agent", "admin"
    actor_id = Column(String(255), nullable=True, index=True)
    actor_ip = Column(String(45), nullable=True)  # Support IPv6
    
    # Target information
    target_type = Column(String(50), nullable=True)  # "token", "agent", "transfer"
    target_id = Column(String(255), nullable=True)
    
    # Event details
    action = Column(String(100), nullable=False)
    outcome = Column(String(50), nullable=False)  # "success", "failure", "error"
    severity = Column(String(20), nullable=False)  # "info", "warning", "error", "critical"
    
    # Additional context
    details = Column(Text, nullable=True)  # JSON string
    error_message = Column(String(500), nullable=True)
    
    # Request metadata
    request_id = Column(String(36), nullable=True)
    user_agent = Column(String(500), nullable=True)
    
    # Indexes for common queries
    __table_args__ = (
        {"extend_existing": True},  # Allow redefinition in development
    )


def clip_to_columns(values: Dict[str, Any]) -> List[Dict[str, Any]]:
    """§MCPTEST30 (V0545): clip each string to its column's declared length, in place; returns what was clipped.

    A value longer than its column made the whole INSERT fail ("value too long for type character varying(255)"), so the
    row was lost: one tester sweep lost an admin read of another developer's MCP audit log because the actor it asked
    for was a 300-character probe value (sbx-alpha, 2026-10-02 04:07:41Z). Any caller could keep its own call out of the
    log that way, with a long id, a long user agent or a long request id. A clipped value keeps its head and ends in an
    ellipsis; the row's details name each clipped column and its original length."""
    clipped: List[Dict[str, Any]] = []
    for name, value in list(values.items()):
        if not isinstance(value, str):
            continue
        column = SecurityAuditLog.__table__.c.get(name)
        limit = getattr(getattr(column, "type", None), "length", None)
        if limit and len(value) > limit:
            values[name] = value[: limit - 1] + "\u2026"
            clipped.append({"column": name, "length": len(value)})
    return clipped


class SecurityAuditor:
    """
    Handles security audit logging with correlation tracking.
    
    Features:
    - Structured security event logging
    - Correlation ID tracking across distributed systems
    - Anomaly detection hooks
    - Export capabilities for SIEM integration
    """
    
    def __init__(self, service_name: str = "registry"):
        self.service_name = service_name
        self._event_counters: Dict[SecurityEventType, int] = defaultdict(int)
        self._anomaly_thresholds = {
            SecurityEventType.TOKEN_EXCHANGE_FAILURE: 10,  # per minute
            SecurityEventType.RATE_LIMIT_EXCEEDED: 5,
            SecurityEventType.JTI_REUSE_ATTEMPT: 3,
            SecurityEventType.UNAUTHORIZED_ACCESS: 5
        }
    
    def set_correlation_id(self, correlation_id: Optional[str] = None) -> str:
        """
        Set correlation ID for current context.
        
        Args:
            correlation_id: Optional correlation ID. If not provided, generates new one.
            
        Returns:
            The correlation ID that was set
        """
        if not correlation_id:
            correlation_id = str(uuid.uuid4())
        
        correlation_id_var.set(correlation_id)
        return correlation_id
    
    def get_correlation_id(self) -> Optional[str]:
        """Get current correlation ID from context."""
        return correlation_id_var.get()
    
    async def log_event(
        self,
        db: AsyncSession,
        event_type: SecurityEventType,
        action: str,
        outcome: str,
        severity: str = "info",
        actor_type: Optional[str] = None,
        actor_id: Optional[str] = None,
        actor_ip: Optional[str] = None,
        target_type: Optional[str] = None,
        target_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
        request_id: Optional[str] = None,
        user_agent: Optional[str] = None
    ):
        """
        Log a security event to the audit log.
        
        Args:
            db: Database session
            event_type: Type of security event
            action: Action being performed
            outcome: Outcome of the action
            severity: Severity level
            actor_type: Type of actor (registry, agent, admin)
            actor_id: ID of the actor
            actor_ip: IP address of the actor
            target_type: Type of target
            target_id: ID of the target
            details: Additional event details
            error_message: Error message if applicable
            request_id: Request ID for tracing
            user_agent: User agent string
        """
        try:
            # Create audit log entry
            values: Dict[str, Any] = dict(
                correlation_id=self.get_correlation_id(),
                actor_type=actor_type,
                actor_id=actor_id,
                actor_ip=actor_ip,
                target_type=target_type,
                target_id=target_id,
                action=action,
                outcome=outcome,
                severity=severity,
                error_message=error_message,
                request_id=request_id,
                user_agent=user_agent,
            )
            clipped = clip_to_columns(values)
            if clipped:
                details = {**(details or {}), "clipped": clipped}
            audit_entry = SecurityAuditLog(
                event_type=event_type,
                details=json.dumps(details, default=str) if details else None,
                **values,
            )
            
            db.add(audit_entry)
            await db.commit()
            
            # Update counters for anomaly detection
            self._event_counters[event_type] += 1
            
            # Check for anomalies
            await self._check_anomalies(event_type)
            
            # Log to standard logger as well
            log_message = (
                f"SECURITY_AUDIT: {event_type.value} - "
                f"Action: {action}, Outcome: {outcome}, "
                f"Actor: {actor_type}/{actor_id}, "
                f"Target: {target_type}/{target_id}"
            )
            
            if severity == "critical":
                logger.critical(log_message)
            elif severity == "error":
                logger.error(log_message)
            elif severity == "warning":
                logger.warning(log_message)
            else:
                logger.info(log_message)
                
        except Exception as e:
            # §MCPTEST30 (V0545): a failed flush leaves the session unusable until it is rolled back, so the caller's next
            # write failed too ("This Session's transaction has been rolled back due to a previous exception during
            # flush"); and the error's text carries the INSERT's parameters (the row's details), so only its first line
            # is logged.
            try:
                await db.rollback()
            except Exception:  # noqa: BLE001
                pass
            first = (str(e).splitlines() or [""])[0][:300]
            logger.error(f"Failed to write security audit log ({getattr(event_type, 'value', event_type)}): "
                         f"{type(e).__name__}: {first}")
    
    async def log_token_exchange(
        self,
        db: AsyncSession,
        source_registry: str,
        target_registry: str,
        scope: str,
        success: bool,
        actor_ip: Optional[str] = None,
        error: Optional[str] = None
    ):
        """Log a token exchange event."""
        await self.log_event(
            db=db,
            event_type=(
                SecurityEventType.TOKEN_EXCHANGE_SUCCESS
                if success
                else SecurityEventType.TOKEN_EXCHANGE_FAILURE
            ),
            action="token_exchange",
            outcome="success" if success else "failure",
            severity="info" if success else "warning",
            actor_type="registry",
            actor_id=source_registry,
            actor_ip=actor_ip,
            target_type="registry",
            target_id=target_registry,
            details={
                "scope": scope,
                "service": self.service_name
            },
            error_message=error
        )
    
    async def log_rate_limit_exceeded(
        self,
        db: AsyncSession,
        client_id: str,
        request_count: int,
        window_minutes: int,
        actor_ip: Optional[str] = None
    ):
        """Log a rate limit exceeded event."""
        await self.log_event(
            db=db,
            event_type=SecurityEventType.RATE_LIMIT_EXCEEDED,
            action="rate_limit_check",
            outcome="exceeded",
            severity="warning",
            actor_type="client",
            actor_id=client_id,
            actor_ip=actor_ip,
            details={
                "request_count": request_count,
                "window_minutes": window_minutes,
                "limit": settings.OAUTH_MAX_TOKEN_EXCHANGES_PER_HOUR
            }
        )
    
    async def log_jti_reuse(
        self,
        db: AsyncSession,
        jti: str,
        token_issuer: str,
        actor_ip: Optional[str] = None
    ):
        """Log a JTI reuse attempt."""
        await self.log_event(
            db=db,
            event_type=SecurityEventType.JTI_REUSE_ATTEMPT,
            action="token_validation",
            outcome="jti_reused",
            severity="error",
            actor_type="token",
            actor_id=token_issuer,
            actor_ip=actor_ip,
            target_type="jti",
            target_id=jti,
            details={
                "security_violation": "single_use_token_reused"
            }
        )
    
    async def log_cross_teg_transfer(
        self,
        db: AsyncSession,
        transfer_id: str,
        source_agent: str,
        target_agent: str,
        amount: str,
        status: str,
        source_teg: Optional[str] = None,
        target_teg: Optional[str] = None,
        error: Optional[str] = None
    ):
        """Log a cross-TEG transfer event."""
        event_type_map = {
            "initiated": SecurityEventType.CROSS_TEG_TRANSFER_INITIATED,
            "completed": SecurityEventType.CROSS_TEG_TRANSFER_COMPLETED,
            "failed": SecurityEventType.CROSS_TEG_TRANSFER_FAILED
        }
        
        await self.log_event(
            db=db,
            event_type=event_type_map.get(status, SecurityEventType.CROSS_TEG_TRANSFER_INITIATED),
            action="cross_teg_transfer",
            outcome=status,
            severity="info" if status == "completed" else "warning" if status == "failed" else "info",
            actor_type="agent",
            actor_id=source_agent,
            target_type="agent",
            target_id=target_agent,
            details={
                "transfer_id": transfer_id,
                "amount": amount,
                "source_teg": source_teg,
                "target_teg": target_teg
            },
            error_message=error
        )
    
    async def _check_anomalies(self, event_type: SecurityEventType):
        """Check for anomalous patterns in security events."""
        if event_type in self._anomaly_thresholds:
            threshold = self._anomaly_thresholds[event_type]
            count = self._event_counters[event_type]
            
            if count >= threshold:
                logger.critical(
                    f"SECURITY ANOMALY DETECTED: {event_type.value} "
                    f"occurred {count} times (threshold: {threshold})"
                )
                
                # Reset counter
                self._event_counters[event_type] = 0
                
                # TODO: Trigger alerts, notifications, or automated responses
    
    async def export_audit_logs(
        self,
        db: AsyncSession,
        start_time: datetime,
        end_time: datetime,
        format: str = "json"
    ) -> str:
        """
        Export audit logs for SIEM integration.
        
        Args:
            db: Database session
            start_time: Start of time range
            end_time: End of time range
            format: Export format (json, csv, cef)
            
        Returns:
            Exported data as string
        """
        # Implementation would query logs and format for export
        # This is a placeholder for SIEM integration
        pass


# Global auditor instance
security_auditor = SecurityAuditor()


# Correlation ID middleware helper
async def with_correlation_id(correlation_id: Optional[str] = None):
    """Context manager for correlation ID tracking."""
    class CorrelationContext:
        def __init__(self, cid: Optional[str]):
            self.correlation_id = cid
            self.token = None
        
        def __enter__(self):
            self.token = correlation_id_var.set(
                self.correlation_id or str(uuid.uuid4())
            )
            return correlation_id_var.get()
        
        def __exit__(self, exc_type, exc_val, exc_tb):
            if self.token:
                correlation_id_var.reset(self.token)
    
    return CorrelationContext(correlation_id)
