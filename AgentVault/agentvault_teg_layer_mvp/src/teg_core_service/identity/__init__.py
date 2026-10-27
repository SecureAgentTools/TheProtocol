"""Identity management for TEG Core Service

This module provides SPIFFE/SPIRE identity integration for the TEG Core Service,
including SVID management and mTLS authentication.
"""

from .svid_manager import svid_manager, SVIDManager
from .spiffe_auth import (
    SPIFFEAuthMiddleware,
    get_client_spiffe_id,
    require_spiffe_id
)

__all__ = [
    'svid_manager',
    'SVIDManager',
    'SPIFFEAuthMiddleware',
    'get_client_spiffe_id',
    'require_spiffe_id'
]
