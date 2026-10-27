"""
Simplified logging configuration for TEG Core Service
Using standard Python logging instead of structlog for now
"""
import json
import logging
import sys
import time
from contextvars import ContextVar
from typing import Any, Dict, Optional
from uuid import uuid4

from ..core.secure_config import get_settings

settings = get_settings()

# Context variable for request tracking
request_id_var: ContextVar[Optional[str]] = ContextVar("request_id", default=None)


def add_request_id(record):
    """Add request ID to log records"""
    request_id = request_id_var.get()
    if request_id:
        record.request_id = request_id
    else:
        record.request_id = None
    return True


class AppContextFilter(logging.Filter):
    """Add application context to log records"""
    def filter(self, record):
        record.app_name = settings.app_name
        record.app_version = settings.app_version
        record.environment = settings.environment
        add_request_id(record)
        return True


def setup_logging():
    """Configure standard logging based on environment"""
    
    # Set up basic configuration
    log_level = getattr(logging, settings.log_level.upper())
    
    # Create formatter
    if settings.log_format == "json":
        # Simple JSON-like format
        formatter = logging.Formatter(
            '{"time": "%(asctime)s", "level": "%(levelname)s", "name": "%(name)s", '
            '"message": "%(message)s", "app_name": "%(app_name)s", '
            '"app_version": "%(app_version)s", "environment": "%(environment)s"}'
        )
    else:
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Create console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(AppContextFilter())

    root_logger.addHandler(console_handler)

    # 2026-05-04: silence the SQLAlchemy + asyncpg engine loggers. With
    # log_level=INFO the root logger propagates to sqlalchemy.engine.Engine,
    # which emits BEGIN/<query>/COMMIT/ROLLBACK for every transaction (~8
    # log lines per request, ~90 lines per request on frame-b-teg). At
    # cluster scale this drowned ~1.6k real-error lines/min and made
    # operational triage hard. WARNING preserves real DB errors (operational
    # errors, integrity violations, deadlocks) while dropping the per-query
    # noise. For ad-hoc debugging, override per-engine via echo=True or set
    # SQLALCHEMY_LOG_LEVEL=INFO env (not yet wired — TODO if needed).
    for noisy in (
        "sqlalchemy.engine",
        "sqlalchemy.engine.Engine",
        "sqlalchemy.pool",
        "sqlalchemy.dialects",
        "asyncpg",
    ):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Get a configured logger instance"""
    return logging.getLogger(name)


# Performance logging utilities
class LoggedTimer:
    """Context manager for timing operations"""
    
    def __init__(self, logger: logging.Logger, operation: str):
        self.logger = logger
        self.operation = operation
        self.start_time = None
    
    def __enter__(self):
        self.start_time = time.time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        duration_ms = int((time.time() - self.start_time) * 1000)
        
        if exc_type is None:
            self.logger.info(
                f"{self.operation}_completed - duration_ms: {duration_ms}"
            )
        else:
            self.logger.error(
                f"{self.operation}_failed - duration_ms: {duration_ms}, error: {exc_type.__name__}: {str(exc_val)}"
            )


# Security event logging
class SecurityLogger:
    """Specialized logger for security events"""
    
    def __init__(self):
        self.logger = get_logger("security")
    
    def log_authentication_success(self, agent_id: str, endpoint: str):
        """Log successful authentication"""
        self.logger.info(
            f"authentication_success - agent_id: {agent_id}, endpoint: {endpoint}"
        )
    
    def log_authentication_failure(self, reason: str, endpoint: str, token_prefix: Optional[str] = None):
        """Log authentication failure"""
        self.logger.warning(
            f"authentication_failure - reason: {reason}, endpoint: {endpoint}, token_prefix: {token_prefix}"
        )
    
    def log_authorization_failure(self, agent_id: str, endpoint: str, required_role: str):
        """Log authorization failure"""
        self.logger.warning(
            f"authorization_failure - agent_id: {agent_id}, endpoint: {endpoint}, required_role: {required_role}"
        )
    
    def log_admin_action(self, action: str, target: Optional[str] = None, details: Optional[Dict] = None):
        """Log admin actions"""
        self.logger.info(
            f"admin_action - action: {action}, target: {target}, details: {details}"
        )
    
    def log_suspicious_activity(self, activity_type: str, agent_id: Optional[str] = None, details: Optional[Dict] = None):
        """Log suspicious activity"""
        self.logger.warning(
            f"suspicious_activity - type: {activity_type}, agent_id: {agent_id}, details: {details}"
        )


# Transaction logging
class TransactionLogger:
    """Specialized logger for transaction events"""
    
    def __init__(self):
        self.logger = get_logger("transactions")
    
    def log_transfer_initiated(self, sender: str, receiver: str, amount: str, fee: str):
        """Log transfer initiation"""
        self.logger.info(
            f"transfer_initiated - sender: {sender}, receiver: {receiver}, amount: {amount}, fee: {fee}"
        )
    
    def log_transfer_completed(self, transaction_id: str, sender: str, receiver: str, amount: str, fee: str):
        """Log successful transfer"""
        self.logger.info(
            f"transfer_completed - transaction_id: {transaction_id}, sender: {sender}, receiver: {receiver}, amount: {amount}, fee: {fee}"
        )
    
    def log_transfer_failed(self, sender: str, receiver: str, amount: str, reason: str):
        """Log failed transfer"""
        self.logger.error(
            f"transfer_failed - sender: {sender}, receiver: {receiver}, amount: {amount}, reason: {reason}"
        )
    
    def log_issuance(self, target: str, amount: str, issuer: str, reason: str):
        """Log token issuance"""
        self.logger.info(
            f"token_issuance - target: {target}, amount: {amount}, issuer: {issuer}, reason: {reason}"
        )


# API logging middleware
async def log_request_middleware(request, call_next):
    """Middleware to log API requests and responses"""
    # Generate request ID
    request_id = str(uuid4())
    request_id_var.set(request_id)
    
    logger = get_logger("api")
    
    # Log request — DEBUG level: uvicorn's access log already covers
    # method/path/status. The middleware's value-add (request_id correlation,
    # contextual filtering) only matters during active debugging. Demoted
    # 2026-05-04 from INFO to drop ~120 lines/min/TEG of redundant chatter.
    logger.debug(
        f"request_received - method: {request.method}, path: {request.url.path}, client_host: {request.client.host if request.client else None}"
    )

    # Time the request
    start_time = time.time()

    try:
        response = await call_next(request)
        duration_ms = int((time.time() - start_time) * 1000)

        # Log response — DEBUG level (see comment on request_received above).
        logger.debug(
            f"request_completed - method: {request.method}, path: {request.url.path}, status_code: {response.status_code}, duration_ms: {duration_ms}"
        )
        
        # Add request ID to response headers
        response.headers["X-Request-ID"] = request_id
        
        return response
    
    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        
        logger.error(
            f"request_failed - method: {request.method}, path: {request.url.path}, duration_ms: {duration_ms}, error: {type(e).__name__}: {str(e)}"
        )
        
        raise
    
    finally:
        # Clear request ID
        request_id_var.set(None)


# Export commonly used items
__all__ = [
    "setup_logging",
    "get_logger",
    "LoggedTimer",
    "SecurityLogger",
    "TransactionLogger",
    "log_request_middleware",
    "request_id_var"
]
