"""Security middleware for TEG Core Service

This module provides security-focused middleware including:
- Security headers for all API responses
- Request ID tracking for auditability
- Request size limiting
- Response time tracking
"""
import time
import uuid
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from ..core.secure_config import get_settings

settings = get_settings()


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses"""
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Generate request ID for tracking
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        
        # Track request timing
        start_time = time.time()
        
        # Process request
        response = await call_next(request)
        
        # Calculate processing time
        process_time = time.time() - start_time
        
        # Add security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time"] = str(process_time)
        
        # HSTS for production
        if settings.environment == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        
        # Remove server header if present
        response.headers.pop("Server", None)
        
        # Add CORS headers based on configuration
        if settings.cors_allowed_origins != ["*"]:
            # In production with specific origins
            response.headers["Access-Control-Allow-Credentials"] = "true"
        
        return response


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Enforce request size limits"""
    
    def __init__(self, app: ASGIApp, max_size: int = None):
        super().__init__(app)
        self.max_size = max_size or settings.max_request_size
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Check content length header
        content_length = request.headers.get("content-length")
        
        if content_length:
            content_length = int(content_length)
            if content_length > self.max_size:
                return Response(
                    content=f"Request body too large. Maximum size: {self.max_size} bytes",
                    status_code=413
                )
        
        return await call_next(request)
