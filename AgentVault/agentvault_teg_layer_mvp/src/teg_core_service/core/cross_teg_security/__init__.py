"""
Security module for TEG Layer.

Provides security monitoring and anomaly detection for cross-TEG operations.
"""

from .cross_teg_monitor import (
    TransferPattern,
    CrossTEGSecurityMonitor,
    cross_teg_security_monitor,
    initialize_security_monitor,
    default_alert_handler
)

__all__ = [
    "TransferPattern",
    "CrossTEGSecurityMonitor",
    "cross_teg_security_monitor",
    "initialize_security_monitor",
    "default_alert_handler"
]
