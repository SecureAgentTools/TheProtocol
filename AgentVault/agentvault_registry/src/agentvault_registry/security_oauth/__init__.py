"""
Security module for cross-registry OAuth.

Provides enhanced security features including:
- Token security management
- Audit logging
- Rate limiting
- Anomaly detection
"""

from .token_security import (
    TokenSecurityManager,
    token_security_manager,
    initialize_token_security,
    shutdown_token_security
)

from .audit_logger import (
    SecurityEventType,
    SecurityAuditLog,
    SecurityAuditor,
    security_auditor,
    with_correlation_id,
    correlation_id_var
)

# Import constants directly from config
from ..config import settings
SECRET_KEY = settings.API_KEY_SECRET
ALGORITHM = "HS256"

__all__ = [
    # Token Security
    "TokenSecurityManager",
    "token_security_manager",
    "initialize_token_security",
    "shutdown_token_security",
    
    # Audit Logging
    "SecurityEventType",
    "SecurityAuditLog",
    "SecurityAuditor",
    "security_auditor",
    "with_correlation_id",
    "correlation_id_var",
    
    # Constants
    "SECRET_KEY",
    "ALGORITHM"
]
