"""Enhanced structured logging for TEG Core Service

This module provides structured logging with:
- JSON format for production environments
- Contextual information (request ID, agent ID, etc.)
- Sensitive data filtering
- Performance metrics logging
"""
import logging
import sys
import json
from typing import Any, Dict, Optional
from datetime import datetime, timezone
from functools import wraps

try:
    import structlog
    STRUCTLOG_AVAILABLE = True
except ImportError:
    STRUCTLOG_AVAILABLE = False

from ..core.config import get_settings

settings = get_settings()


class SensitiveDataFilter(logging.Filter):
    """Filter to prevent sensitive data from being logged"""
    
    SENSITIVE_FIELDS = {
        'api_key', 'password', 'token', 'secret', 'authorization',
        'admin_api_key', 'avtp_system_api_key', 'bearer'
    }
    
    def filter(self, record: logging.LogRecord) -> bool:
        # Check message for sensitive patterns
        if hasattr(record, 'msg'):
            msg_lower = str(record.msg).lower()
            for field in self.SENSITIVE_FIELDS:
                if field in msg_lower:
                    # Redact sensitive information
                    record.msg = self._redact_sensitive(str(record.msg), field)
        
        # Check extra fields
        for key in list(record.__dict__.keys()):
            if key.lower() in self.SENSITIVE_FIELDS:
                record.__dict__[key] = "[REDACTED]"
        
        return True
    
    def _redact_sensitive(self, message: str, field: str) -> str:
        """Redact sensitive information from message"""
        import re
        # Simple pattern to find potential secrets after the field name
        pattern = rf"({field}['\"]?\s*[:=]\s*['\"]?)([^'\":\s]+)"
        return re.sub(pattern, r'\1[REDACTED]', message, flags=re.IGNORECASE)


def setup_logging():
    """Configure structured logging based on environment"""
    
    if STRUCTLOG_AVAILABLE and settings.log_format == "json":
        # Configure structlog for production
        structlog.configure(
            processors=[
                structlog.stdlib.filter_by_level,
                structlog.stdlib.add_logger_name,
                structlog.stdlib.add_log_level,
                structlog.stdlib.PositionalArgumentsFormatter(),
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
                structlog.processors.UnicodeDecoder(),
                structlog.processors.JSONRenderer()
            ],
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )
        
        # Configure standard logging to work with structlog
        logging.basicConfig(
            format="%(message)s",
            stream=sys.stdout,
            level=getattr(logging, settings.log_level.upper()),
        )
        
    else:
        # Fallback to standard JSON logging
        class JSONFormatter(logging.Formatter):
            def format(self, record):
                log_data = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "level": record.levelname,
                    "logger": record.name,
                    "message": record.getMessage(),
                    "module": record.module,
                    "function": record.funcName,
                    "line": record.lineno,
                }
                
                # Add extra fields
                for key, value in record.__dict__.items():
                    if key not in ['name', 'msg', 'args', 'created', 'filename', 
                                  'funcName', 'levelname', 'levelno', 'lineno', 
                                  'module', 'msecs', 'message', 'pathname', 'process',
                                  'processName', 'relativeCreated', 'thread', 'threadName']:
                        log_data[key] = value
                
                if record.exc_info:
                    log_data["exception"] = self.formatException(record.exc_info)
                
                return json.dumps(log_data)
        
        # Configure logging
        handler = logging.StreamHandler(sys.stdout)
        
        if settings.log_format == "json":
            handler.setFormatter(JSONFormatter())
        else:
            handler.setFormatter(
                logging.Formatter(
                    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
                )
            )
        
        # Add sensitive data filter
        handler.addFilter(SensitiveDataFilter())
        
        logging.basicConfig(
            level=getattr(logging, settings.log_level.upper()),
            handlers=[handler]
        )


def get_logger(name: str) -> Any:
    """Get a logger instance with structured logging support"""
    if STRUCTLOG_AVAILABLE and settings.log_format == "json":
        return structlog.get_logger(name)
    else:
        logger = logging.getLogger(name)
        # Ensure sensitive filter is applied
        if not any(isinstance(f, SensitiveDataFilter) for f in logger.filters):
            logger.addFilter(SensitiveDataFilter())
        return logger


class LogContext:
    """Context manager for adding contextual information to logs"""
    
    def __init__(self, logger: Any, **kwargs):
        self.logger = logger
        self.context = kwargs
        self.bound_logger = None
    
    def __enter__(self):
        if STRUCTLOG_AVAILABLE and hasattr(self.logger, 'bind'):
            self.bound_logger = self.logger.bind(**self.context)
            return self.bound_logger
        else:
            # For standard logging, we'll add context to each log call
            return ContextualLogger(self.logger, self.context)
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.bound_logger and hasattr(self.bound_logger, 'unbind'):
            try:
                self.bound_logger.unbind(*self.context.keys())
            except:
                pass  # Ignore unbind errors


class ContextualLogger:
    """Wrapper for standard logger to add context"""
    
    def __init__(self, logger: logging.Logger, context: Dict[str, Any]):
        self.logger = logger
        self.context = context
    
    def _log(self, level: str, msg: str, *args, **kwargs):
        extra = kwargs.get('extra', {})
        extra.update(self.context)
        kwargs['extra'] = extra
        getattr(self.logger, level)(msg, *args, **kwargs)
    
    def debug(self, msg: str, *args, **kwargs):
        self._log('debug', msg, *args, **kwargs)
    
    def info(self, msg: str, *args, **kwargs):
        self._log('info', msg, *args, **kwargs)
    
    def warning(self, msg: str, *args, **kwargs):
        self._log('warning', msg, *args, **kwargs)
    
    def error(self, msg: str, *args, **kwargs):
        self._log('error', msg, *args, **kwargs)
    
    def critical(self, msg: str, *args, **kwargs):
        self._log('critical', msg, *args, **kwargs)


def log_performance(operation: str):
    """Decorator to log operation performance"""
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            import time
            logger = get_logger(func.__module__)
            start_time = time.time()
            
            try:
                result = await func(*args, **kwargs)
                duration = time.time() - start_time
                
                with LogContext(logger, operation=operation, duration=duration, status="success"):
                    # 2026-05-04: demoted INFO → DEBUG. Per-call success logs
                    # added ~70 lines/min on busy TEGs (canary hits
                    # get_agent_teg_status frequently). Failure path stays at
                    # ERROR — operational signal preserved.
                    logger.debug(f"{operation} completed")
                
                return result
            
            except Exception as e:
                duration = time.time() - start_time
                
                with LogContext(logger, operation=operation, duration=duration, status="error", error=str(e)):
                    logger.error(f"{operation} failed", exc_info=True)
                
                raise
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            import time
            logger = get_logger(func.__module__)
            start_time = time.time()
            
            try:
                result = func(*args, **kwargs)
                duration = time.time() - start_time
                
                with LogContext(logger, operation=operation, duration=duration, status="success"):
                    # 2026-05-04: demoted INFO → DEBUG. Per-call success logs
                    # added ~70 lines/min on busy TEGs (canary hits
                    # get_agent_teg_status frequently). Failure path stays at
                    # ERROR — operational signal preserved.
                    logger.debug(f"{operation} completed")
                
                return result
            
            except Exception as e:
                duration = time.time() - start_time
                
                with LogContext(logger, operation=operation, duration=duration, status="error", error=str(e)):
                    logger.error(f"{operation} failed", exc_info=True)
                
                raise
        
        # Return appropriate wrapper based on function type
        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator


# Transaction logging helpers
def log_transaction(logger: Any, transaction_type: str, transaction_data: Dict[str, Any]):
    """Log transaction with structured data"""
    # Remove sensitive fields
    safe_data = {k: v for k, v in transaction_data.items() 
                 if k.lower() not in SensitiveDataFilter.SENSITIVE_FIELDS}
    
    with LogContext(
        logger,
        transaction_type=transaction_type,
        transaction_id=safe_data.get('transaction_id'),
        sender_id=safe_data.get('sender_agent_id'),
        receiver_id=safe_data.get('receiver_agent_id'),
        amount=str(safe_data.get('amount', 0)),
        status=safe_data.get('status')
    ):
        logger.info(f"Transaction {transaction_type} processed")


def log_api_request(logger: Any, method: str, path: str, agent_id: Optional[str] = None):
    """Log API request with context"""
    with LogContext(
        logger,
        http_method=method,
        path=path,
        agent_id=agent_id
    ):
        logger.info(f"API request: {method} {path}")


def log_api_response(logger: Any, status_code: int, duration: float):
    """Log API response with metrics"""
    with LogContext(
        logger,
        status_code=status_code,
        duration_ms=round(duration * 1000, 2)
    ):
        logger.info(f"API response: {status_code}")
