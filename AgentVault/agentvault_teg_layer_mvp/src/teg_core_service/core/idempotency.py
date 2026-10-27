"""Idempotency handling for critical operations

This module provides idempotency support for critical operations like:
- Token transfers
- Token issuance
- System transfers

It prevents duplicate processing of requests using idempotency keys.
"""
import hashlib
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from decimal import Decimal

from sqlalchemy.orm import Session
from sqlalchemy import Column, String, DateTime, Text, Boolean
from sqlalchemy.orm import declarative_base  # §DEPS: its home since SQLAlchemy 1.4; the ext.declarative alias is deprecated

from ..database.models import Base
from ..core.structured_logging import get_logger

logger = get_logger(__name__)


class IdempotencyRecord(Base):
    """Store idempotency records for request deduplication"""
    __tablename__ = "teg_idempotency_records"
    
    idempotency_key = Column(String(255), primary_key=True, index=True)
    operation_type = Column(String(50), nullable=False)  # transfer, issuance, etc.
    request_hash = Column(String(64), nullable=False)  # SHA256 of request params
    response_data = Column(Text, nullable=True)  # Stored as JSON
    status = Column(String(20), nullable=False, default="pending")  # pending, completed, failed
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.utcnow())
    completed_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=False)  # For cleanup
    
    def is_expired(self) -> bool:
        """Check if this idempotency record has expired"""
        return datetime.utcnow() > self.expires_at
    
    def mark_completed(self, response_data: Dict[str, Any]):
        """Mark this operation as completed with response data"""
        self.status = "completed"
        self.completed_at = datetime.utcnow()
        self.response_data = json.dumps(response_data, default=str)
    
    def mark_failed(self, error_data: Dict[str, Any]):
        """Mark this operation as failed with error data"""
        self.status = "failed"
        self.completed_at = datetime.utcnow()
        self.response_data = json.dumps({"error": error_data}, default=str)


class IdempotencyService:
    """Service for handling idempotent operations"""
    
    # Default TTL for idempotency records (24 hours)
    DEFAULT_TTL_HOURS = 24
    
    @staticmethod
    def generate_request_hash(operation_type: str, params: Dict[str, Any]) -> str:
        """Generate a hash of the request parameters for comparison"""
        # Sort params for consistent hashing
        sorted_params = json.dumps(params, sort_keys=True, default=str)
        content = f"{operation_type}:{sorted_params}"
        return hashlib.sha256(content.encode()).hexdigest()
    
    @staticmethod
    def check_and_create(
        db: Session,
        idempotency_key: str,
        operation_type: str,
        params: Dict[str, Any],
        ttl_hours: int = None
    ) -> Optional[Dict[str, Any]]:
        """
        Check if an operation with this idempotency key exists.
        
        Returns:
            - None if this is a new operation (record created)
            - Dict with previous response if operation was already completed
            - Raises exception if operation is pending or request differs
        """
        from ..core.error_handling import TEGException, ErrorCode
        
        if ttl_hours is None:
            ttl_hours = IdempotencyService.DEFAULT_TTL_HOURS
        
        request_hash = IdempotencyService.generate_request_hash(operation_type, params)
        expires_at = datetime.utcnow() + timedelta(hours=ttl_hours)
        
        # Check for existing record
        existing = db.query(IdempotencyRecord).filter(
            IdempotencyRecord.idempotency_key == idempotency_key
        ).first()
        
        if existing:
            # Check if expired
            if existing.is_expired():
                # Delete expired record and treat as new
                db.delete(existing)
                db.commit()
                existing = None
            else:
                # Check if parameters match
                if existing.request_hash != request_hash:
                    raise TEGException(
                        status_code=409,
                        error_code=ErrorCode.IDEM_CONFLICTING_REQUEST,
                        message="Idempotency key already used with different parameters",
                        metadata={
                            "idempotency_key": idempotency_key,
                            "operation_type": operation_type
                        }
                    )
                
                # Check status
                if existing.status == "completed":
                    # Return previous response
                    logger.info(
                        f"Returning cached response for idempotent request "
                        f"key={idempotency_key} op={operation_type}"
                    )
                    return json.loads(existing.response_data)
                
                elif existing.status == "pending":
                    # Another request is still processing
                    raise TEGException(
                        status_code=409,
                        error_code=ErrorCode.IDEM_DUPLICATE_REQUEST,
                        message="Request with this idempotency key is already being processed",
                        metadata={
                            "idempotency_key": idempotency_key,
                            "operation_type": operation_type
                        }
                    )
                
                elif existing.status == "failed":
                    # Previous request failed, allow retry by deleting record
                    db.delete(existing)
                    db.commit()
                    existing = None
        
        # Create new record
        if not existing:
            new_record = IdempotencyRecord(
                idempotency_key=idempotency_key,
                operation_type=operation_type,
                request_hash=request_hash,
                status="pending",
                expires_at=expires_at
            )
            db.add(new_record)
            db.commit()
            
            logger.info(
                f"Created new idempotency record key={idempotency_key} "
                f"op={operation_type}"
            )
        
        return None  # New operation
    
    @staticmethod
    def mark_completed(
        db: Session,
        idempotency_key: str,
        response_data: Dict[str, Any]
    ):
        """Mark an idempotent operation as completed"""
        record = db.query(IdempotencyRecord).filter(
            IdempotencyRecord.idempotency_key == idempotency_key
        ).first()
        
        if record:
            record.mark_completed(response_data)
            db.commit()
            
            logger.info(f"Marked idempotent operation as completed key={idempotency_key}")
    
    @staticmethod
    def mark_failed(
        db: Session,
        idempotency_key: str,
        error_data: Dict[str, Any]
    ):
        """Mark an idempotent operation as failed"""
        record = db.query(IdempotencyRecord).filter(
            IdempotencyRecord.idempotency_key == idempotency_key
        ).first()
        
        if record:
            record.mark_failed(error_data)
            db.commit()
            
            logger.warning(
                f"Marked idempotent operation as failed key={idempotency_key} "
                f"error={error_data}"
            )
    
    @staticmethod
    def cleanup_expired(db: Session) -> int:
        """Clean up expired idempotency records"""
        expired_count = db.query(IdempotencyRecord).filter(
            IdempotencyRecord.expires_at < datetime.utcnow()
        ).delete()
        
        if expired_count > 0:
            db.commit()
            logger.info(f"Cleaned up {expired_count} expired idempotency records")
        
        return expired_count


def idempotent_transfer_params(
    sender_id: str,
    receiver_id: str,
    amount: Decimal,
    message: Optional[str] = None
) -> Dict[str, Any]:
    """Create standardized parameters for transfer idempotency"""
    params = {
        "sender_id": sender_id,
        "receiver_id": receiver_id,
        "amount": str(amount)
    }
    if message:
        params["message"] = message
    return params


def idempotent_issuance_params(
    target_agent_id: str,
    amount: Decimal
) -> Dict[str, Any]:
    """Create standardized parameters for issuance idempotency"""
    return {
        "target_agent_id": target_agent_id,
        "amount": str(amount)
    }
