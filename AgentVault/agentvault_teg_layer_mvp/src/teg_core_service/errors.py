# POLISH-001: Unified Error Schema Implementation for TEG Layer
# teg_core_service/errors.py

import logging
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, Request, HTTPException, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from pydantic import BaseModel
from .core.logging import request_id_var

logger = logging.getLogger(__name__)


class ErrorDetail(BaseModel):
    """Unified error response schema for all API errors."""
    detail: str
    type: Optional[str] = None
    code: Optional[str] = None
    field: Optional[str] = None
    field_errors: Optional[Dict[str, List[str]]] = None
    context: Optional[Dict[str, Any]] = None
    request_id: Optional[str] = None


class ErrorResponse(BaseModel):
    """Standard error response wrapper."""
    error: ErrorDetail


# §pass56 PR-9: status → human title (RFC 7807 'title' field)
_STATUS_TITLE_MAP = {
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    409: "Conflict",
    410: "Gone",
    422: "Validation Error",
    429: "Too Many Requests",
    500: "Internal Server Error",
    502: "Bad Gateway",
    503: "Service Unavailable",
    504: "Gateway Timeout",
}


def create_error_response(
    detail: str,
    status_code: int,
    error_type: Optional[str] = None,
    error_code: Optional[str] = None,
    field: Optional[str] = None,
    field_errors: Optional[Dict[str, List[str]]] = None,
    context: Optional[Dict[str, Any]] = None,
    request_id: Optional[str] = None,
    request: Optional[Request] = None,
) -> JSONResponse:
    """Create a standardized JSON error response.

    §pass56 PR-9 — DUAL-EMIT (sandbox test). Body carries the legacy `detail`
    field at top level (preserves existing TEG client behavior) AND RFC 7807
    standard fields. Content-Type set to `application/problem+json`.

    Pivot to hard-cut if dual-emit causes regression on sandbox; see
    PLAN_2026-05-20_PASS56_SANDBOX.md.
    """
    if request_id is None:
        try:
            request_id = request_id_var.get()
        except Exception:
            request_id = None

    body: Dict[str, Any] = {
        # Legacy minimal shape (TEG callers tolerate just `detail`)
        "detail": detail,
        # RFC 7807 standard fields
        "type":   f"https://docs.theprotocol.cloud/errors/{error_type or 'error'}",
        "title":  _STATUS_TITLE_MAP.get(status_code, "Error"),
        "status": status_code,
    }
    if request is not None:
        try:
            body["instance"] = str(request.url.path)
        except Exception:
            pass
    if request_id:
        body["request_id"] = request_id
    if error_code:
        body["code"] = error_code
    if field:
        body["field"] = field
    if field_errors:
        body["field_errors"] = field_errors
    if context:
        body["context"] = context

    return JSONResponse(
        status_code=status_code,
        content=body,
        media_type="application/problem+json",
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Handle FastAPI HTTPException with unified error schema."""
    logger.warning(
        f"HTTP exception on {request.method} {request.url.path}: "
        f"{exc.status_code} - {exc.detail}"
    )
    
    # Map common status codes to error types
    error_type_map = {
        400: "bad_request",
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        409: "conflict",
        422: "validation_error",
        429: "rate_limit_exceeded",
        500: "internal_server_error",
        503: "service_unavailable"
    }
    
    error_type = error_type_map.get(exc.status_code, "error")
    
    # Extract additional context from headers if present
    context = {}
    if hasattr(exc, 'headers') and exc.headers:
        context['headers'] = dict(exc.headers)
    
    return create_error_response(
        detail=exc.detail,
        status_code=exc.status_code,
        error_type=error_type,
        context=context if context else None,
        request=request,
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Handle Pydantic validation errors with unified error schema."""
    logger.warning(
        f"Validation error on {request.method} {request.url.path}: {exc.errors()}"
    )
    
    # Format validation errors
    field_errors: Dict[str, List[str]] = {}
    errors = []
    
    for error in exc.errors():
        # Skip 'body' in the location path
        field_path = ".".join(str(loc) for loc in error['loc'][1:] if loc != 'body')
        
        if not field_path:
            field_path = "body"
            
        if field_path not in field_errors:
            field_errors[field_path] = []
        
        field_errors[field_path].append(error['msg'])
        
        errors.append({
            "field": field_path,
            "message": error['msg'],
            "type": error['type']
        })
    
    # Use the first error as the main detail
    main_error = errors[0] if errors else {"message": "Validation error"}
    
    # Determine error code based on field
    error_code = "VALIDATION_ERROR"
    if "agent_id" in str(field_errors):
        error_code = "INVALID_AGENT_ID"
    elif "amount" in str(field_errors):
        error_code = "INVALID_AMOUNT"
    elif "did" in str(field_errors):
        error_code = "INVALID_DID"
    
    return create_error_response(
        detail="Request validation failed",
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        error_type="validation_error",
        error_code=error_code,
        field=main_error.get("field"),
        field_errors=field_errors,
        request=request,
    )


async def starlette_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Handle Starlette HTTPException with unified error schema."""
    return await http_exception_handler(
        request, 
        HTTPException(status_code=exc.status_code, detail=exc.detail)
    )


async def integrity_error_handler(request: Request, exc: IntegrityError) -> JSONResponse:
    """Handle database integrity errors with unified error schema."""
    logger.error(f"Database integrity error on {request.method} {request.url.path}: {exc}")
    
    # Parse common integrity constraints
    detail = "Database constraint violation"
    error_code = "INTEGRITY_ERROR"
    
    error_str = str(exc).lower()
    
    if "unique constraint" in error_str or "duplicate key" in error_str:
        detail = "A record with this value already exists"
        error_code = "DUPLICATE_ENTRY"
    elif "foreign key constraint" in error_str:
        detail = "Referenced record does not exist"
        error_code = "FOREIGN_KEY_VIOLATION"
    elif "not null constraint" in error_str:
        detail = "Required field is missing"
        error_code = "NULL_CONSTRAINT_VIOLATION"
    elif "check constraint" in error_str:
        detail = "Value does not meet constraint requirements"
        error_code = "CHECK_CONSTRAINT_VIOLATION"
    
    return create_error_response(
        detail=detail,
        status_code=status.HTTP_409_CONFLICT,
        error_type="conflict",
        error_code=error_code,
        request=request,
    )


async def sqlalchemy_error_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    """Handle general SQLAlchemy errors with unified error schema."""
    logger.error(f"Database error on {request.method} {request.url.path}: {exc}")
    
    return create_error_response(
        detail="A database error occurred",
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        error_type="database_error",
        error_code="DATABASE_ERROR",
        request=request,
    )


async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle any unhandled exceptions with unified error schema."""
    logger.exception(f"Unhandled exception on {request.method} {request.url.path}: {exc}")
    
    return create_error_response(
        detail="An unexpected error occurred",
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        error_type="internal_server_error",
        error_code="INTERNAL_ERROR",
        request=request,
    )


def register_error_handlers(app: FastAPI) -> None:
    """Register all error handlers with the FastAPI application."""
    # Remove existing handlers first
    app.exception_handlers.clear()
    
    # Register unified handlers
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(StarletteHTTPException, starlette_exception_handler)
    app.add_exception_handler(IntegrityError, integrity_error_handler)
    app.add_exception_handler(SQLAlchemyError, sqlalchemy_error_handler)
    app.add_exception_handler(Exception, general_exception_handler)
    
    logger.info("Unified error handlers registered for TEG layer")


# Custom exception classes for specific error scenarios
class TEGException(HTTPException):
    """Base exception for TEG-specific errors."""
    def __init__(
        self,
        detail: str,
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        error_code: Optional[str] = None
    ):
        super().__init__(status_code=status_code, detail=detail)
        self.error_code = error_code


class InsufficientFundsError(TEGException):
    """Raised when an agent has insufficient funds."""
    def __init__(self, agent_id: str, required: str, available: str):
        super().__init__(
            detail=f"Insufficient funds for agent {agent_id}. Required: {required}, Available: {available}",
            status_code=status.HTTP_400_BAD_REQUEST,
            error_code="INSUFFICIENT_FUNDS"
        )


class AgentNotFoundError(TEGException):
    """Raised when an agent is not found."""
    def __init__(self, agent_id: str):
        super().__init__(
            detail=f"Agent with ID '{agent_id}' not found",
            status_code=status.HTTP_404_NOT_FOUND,
            error_code="AGENT_NOT_FOUND"
        )


class TransactionNotFoundError(TEGException):
    """Raised when a transaction is not found."""
    def __init__(self, transaction_id: str):
        super().__init__(
            detail=f"Transaction with ID '{transaction_id}' not found",
            status_code=status.HTTP_404_NOT_FOUND,
            error_code="TRANSACTION_NOT_FOUND"
        )


class DuplicateTransactionError(TEGException):
    """Raised when a duplicate transaction is attempted."""
    def __init__(self, idempotency_key: str):
        super().__init__(
            detail=f"Duplicate transaction with idempotency key '{idempotency_key}'",
            status_code=status.HTTP_409_CONFLICT,
            error_code="DUPLICATE_TRANSACTION"
        )


class InvalidAttestationError(TEGException):
    """Raised when an attestation is invalid."""
    def __init__(self, detail: str):
        super().__init__(
            detail=detail,
            status_code=status.HTTP_400_BAD_REQUEST,
            error_code="INVALID_ATTESTATION"
        )


class PolicyViolationError(TEGException):
    """Raised when a policy is violated."""
    def __init__(self, policy_name: str, detail: str):
        super().__init__(
            detail=f"Policy '{policy_name}' violated: {detail}",
            status_code=status.HTTP_403_FORBIDDEN,
            error_code="POLICY_VIOLATION"
        )


class DisputeResolutionError(TEGException):
    """Raised when there's an error in dispute resolution."""
    def __init__(self, detail: str):
        super().__init__(
            detail=detail,
            status_code=status.HTTP_400_BAD_REQUEST,
            error_code="DISPUTE_RESOLUTION_ERROR"
        )


class ExternalServiceError(TEGException):
    """Raised when an external service fails."""
    def __init__(self, service_name: str, detail: str):
        super().__init__(
            detail=f"External service '{service_name}' error: {detail}",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            error_code="EXTERNAL_SERVICE_ERROR"
        )
