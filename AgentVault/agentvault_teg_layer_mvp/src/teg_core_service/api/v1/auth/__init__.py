"""Authentication module for TEG Layer API

Part of REQ-INT-V1AUTH-001: Enterprise-Grade Authentication Bridge
"""

from .token_exchange import (
    router as token_exchange_router,
    verify_teg_access_token,
    verify_token,
    TokenRequest,
    TokenResponse,
    TokenIntrospectionResponse
)

__all__ = [
    "token_exchange_router",
    "verify_teg_access_token",
    "verify_token",
    "TokenRequest",
    "TokenResponse", 
    "TokenIntrospectionResponse"
]
