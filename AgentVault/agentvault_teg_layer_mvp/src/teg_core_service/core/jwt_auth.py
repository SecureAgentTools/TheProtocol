"""JWT Authentication utilities for TEG Core Service"""
import jwt
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
from pydantic import BaseModel

from .secure_config import get_settings

settings = get_settings()


class TokenData(BaseModel):
    """JWT Token payload structure"""
    agent_id: str
    exp: datetime
    iat: datetime
    token_type: str = "teg_access"
    
    
class JWTService:
    """Service for creating and validating JWT tokens"""
    
    def __init__(self):
        self.secret_key = settings.teg_token_signing_key.get_secret_value()
        self.algorithm = "HS256"
        self.access_token_expire_minutes = 15
        
    def create_access_token(
        self, 
        agent_id: str, 
        expires_delta: Optional[timedelta] = None
    ) -> str:
        """Create a JWT access token for an agent"""
        if expires_delta:
            expire = datetime.now(timezone.utc) + expires_delta
        else:
            expire = datetime.now(timezone.utc) + timedelta(
                minutes=self.access_token_expire_minutes
            )
            
        payload = {
            "agent_id": agent_id,
            "exp": expire,
            "iat": datetime.now(timezone.utc),
            "token_type": "teg_access"
        }
        
        return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)
    
    def verify_token(self, token: str) -> Optional[str]:
        """
        Verify JWT token and return agent_id if valid.
        
        Returns None if token is invalid, expired, or wrong type.
        No exceptions are raised - returns None for any validation failure.
        """
        try:
            payload = jwt.decode(
                token, 
                self.secret_key, 
                algorithms=[self.algorithm]
            )
            
            # Verify token type
            if payload.get("token_type") != "teg_access":
                return None
                
            return payload.get("agent_id")
            
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None
        except Exception:
            # Catch any other errors to ensure we return None
            return None


# Singleton instance
jwt_service = JWTService()
