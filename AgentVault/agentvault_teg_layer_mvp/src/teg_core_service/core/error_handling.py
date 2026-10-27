"""Enhanced error handling with structured error codes

This module provides a consistent error handling system with:
- Standardized error codes for common scenarios
- Structured error responses
- Detailed error tracking for debugging
"""
from enum import Enum
from typing import Optional, Dict, Any

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel


class ErrorCode(str, Enum):
    """Standardized error codes for TEG system"""
    # Authentication/Authorization
    AUTH_INVALID_TOKEN = "AUTH_001"
    AUTH_TOKEN_EXPIRED = "AUTH_002"
    AUTH_INSUFFICIENT_PERMISSIONS = "AUTH_003"
    AUTH_AGENT_SUSPENDED = "AUTH_004"
    AUTH_FORBIDDEN = "AUTH_005"
    
    # Validation
    VALIDATION_INVALID_INPUT = "VAL_001"
    VALIDATION_AMOUNT_TOO_LOW = "VAL_002"
    VALIDATION_AMOUNT_TOO_HIGH = "VAL_003"
    VALIDATION_INVALID_AGENT_ID = "VAL_004"
    VALIDATION_INVALID_TRANSACTION_ID = "VAL_005"
    
    # Business Logic
    BIZ_INSUFFICIENT_BALANCE = "BIZ_001"
    BIZ_SELF_TRANSFER = "BIZ_002"
    BIZ_AGENT_NOT_FOUND = "BIZ_003"
    BIZ_TRANSACTION_NOT_FOUND = "BIZ_004"
    BIZ_REPUTATION_ALREADY_SIGNALED = "BIZ_005"
    BIZ_INVALID_TRANSACTION_STATE = "BIZ_006"
    BIZ_FEE_CONFIG_MISSING = "BIZ_007"
    
    # System
    SYS_DATABASE_ERROR = "SYS_001"
    SYS_EXTERNAL_SERVICE_ERROR = "SYS_002"
    SYS_INTERNAL_ERROR = "SYS_003"
    SYS_RATE_LIMIT_EXCEEDED = "SYS_004"
    
    # Idempotency
    IDEM_DUPLICATE_REQUEST = "IDEM_001"
    IDEM_CONFLICTING_REQUEST = "IDEM_002"


class ErrorDetail(BaseModel):
    """Structured error response model"""
    error_code: str
    message: str
    detail: Optional[str] = None
    request_id: Optional[str] = None
    timestamp: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class TEGException(HTTPException):
    """Enhanced exception with error codes"""
    
    def __init__(
        self,
        status_code: int,
        error_code: ErrorCode,
        message: str,
        detail: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.error_code = error_code
        self.message = message
        self.detail_info = detail
        self.metadata = metadata
        super().__init__(status_code=status_code, detail=message)


async def teg_exception_handler(request: Request, exc: TEGException) -> JSONResponse:
    """Custom exception handler for TEGException"""
    from datetime import datetime, timezone
    
    error_detail = ErrorDetail(
        error_code=exc.error_code.value,
        message=exc.message,
        detail=exc.detail_info,
        request_id=getattr(request.state, "request_id", None),
        timestamp=datetime.now(timezone.utc).isoformat(),
        metadata=exc.metadata
    )
    
    return JSONResponse(
        status_code=exc.status_code,
        content=error_detail.dict(exclude_none=True)
    )


# Convenience functions for common errors
def insufficient_balance_error(
    current_balance: str,
    required_amount: str,
    fee_amount: Optional[str] = None
) -> TEGException:
    """Create insufficient balance error with details"""
    metadata = {
        "current_balance": current_balance,
        "required_amount": required_amount
    }
    if fee_amount:
        metadata["fee_amount"] = fee_amount
    
    return TEGException(
        status_code=400,
        error_code=ErrorCode.BIZ_INSUFFICIENT_BALANCE,
        message="Insufficient balance for transfer",
        detail=f"Current balance: {current_balance}, Required: {required_amount}",
        metadata=metadata
    )


def validation_error(
    field: str,
    value: Any,
    constraint: str
) -> TEGException:
    """Create validation error with field details"""
    return TEGException(
        status_code=400,
        error_code=ErrorCode.VALIDATION_INVALID_INPUT,
        message=f"Invalid value for field '{field}'",
        detail=f"Value '{value}' violates constraint: {constraint}",
        metadata={"field": field, "value": str(value), "constraint": constraint}
    )


def agent_not_found_error(agent_id: str) -> TEGException:
    """Create agent not found error"""
    return TEGException(
        status_code=404,
        error_code=ErrorCode.BIZ_AGENT_NOT_FOUND,
        message=f"Agent not found",
        detail=f"Agent with ID '{agent_id}' does not exist",
        metadata={"agent_id": agent_id}
    )


def transaction_not_found_error(transaction_id: str) -> TEGException:
    """Create transaction not found error"""
    return TEGException(
        status_code=404,
        error_code=ErrorCode.BIZ_TRANSACTION_NOT_FOUND,
        message=f"Transaction not found",
        detail=f"Transaction with ID '{transaction_id}' does not exist",
        metadata={"transaction_id": transaction_id}
    )
