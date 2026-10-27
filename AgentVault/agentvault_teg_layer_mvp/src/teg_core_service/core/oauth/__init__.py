"""OAuth federation support for TEG Core Service"""
from .multi_issuer_jwt import (
    MultiIssuerJWTService,
    MultiIssuerAuthMiddleware,
    create_multi_issuer_jwt_service,
    TrustedRegistry,
    TokenClaims,
)

__all__ = [
    "MultiIssuerJWTService",
    "MultiIssuerAuthMiddleware", 
    "create_multi_issuer_jwt_service",
    "TrustedRegistry",
    "TokenClaims",
]
