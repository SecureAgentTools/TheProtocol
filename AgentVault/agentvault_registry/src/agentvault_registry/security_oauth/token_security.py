"""
Token Security Module for Cross-Registry OAuth.

Implements enhanced token security features:
- Single-use token enforcement
- Token revocation lists
- Scope validation
- Expiry tracking
"""

import logging
from typing import Optional, Dict, Any, Set, List
from datetime import datetime, timedelta, timezone
from collections import defaultdict
import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, and_
from sqlalchemy.orm import selectinload

from ..models import OAuthTokenExchange
from ..config import settings

logger = logging.getLogger(__name__)


class TokenSecurityManager:
    """
    Manages enhanced security features for OAuth tokens.
    
    Features:
    - Single-use token tracking (JTI)
    - Token revocation list
    - Scope enforcement
    - Rate limiting per client
    """
    
    def __init__(self):
        # In-memory tracking for performance
        self._used_jtis: Set[str] = set()
        self._revoked_tokens: Set[str] = set()
        self._rate_limit_counters: Dict[str, List[datetime]] = defaultdict(list)
        
        # Configuration
        self.jti_cleanup_interval = 3600  # 1 hour
        self.max_jti_age = timedelta(hours=24)
        self.rate_limit_window = timedelta(hours=1)
        self.max_exchanges_per_hour = settings.OAUTH_MAX_TOKEN_EXCHANGES_PER_HOUR or 100
        
        # Start cleanup task
        self._cleanup_task = None
    
    async def start(self):
        """Start the security manager and cleanup tasks."""
        logger.info("Starting TokenSecurityManager")
        self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
    
    async def stop(self):
        """Stop the security manager and cleanup tasks."""
        logger.info("Stopping TokenSecurityManager")
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
    
    async def validate_jti(self, jti: str, token_exp: datetime) -> bool:
        """
        Validate that a JTI (JWT ID) has not been used before.
        
        Args:
            jti: The JWT ID to validate
            token_exp: Token expiration time
            
        Returns:
            True if JTI is valid (not used), False otherwise
        """
        if not jti:
            logger.warning("Token missing JTI for single-use enforcement")
            return False
        
        if jti in self._used_jtis:
            logger.warning(f"JTI already used: {jti}")
            return False
        
        # Mark as used
        self._used_jtis.add(jti)
        
        # Schedule removal after expiration
        asyncio.create_task(self._remove_jti_after_expiry(jti, token_exp))
        
        return True
    
    async def _remove_jti_after_expiry(self, jti: str, exp_time: datetime):
        """Remove JTI from tracking after token expires."""
        wait_seconds = max(0, (exp_time - datetime.now(timezone.utc)).total_seconds())
        await asyncio.sleep(wait_seconds + 60)  # Add 1 minute buffer
        
        if jti in self._used_jtis:
            self._used_jtis.discard(jti)
            logger.debug(f"Removed expired JTI from tracking: {jti}")
    
    async def check_token_revoked(self, token_id: str) -> bool:
        """
        Check if a token has been revoked.
        
        Args:
            token_id: The token ID to check
            
        Returns:
            True if token is revoked, False otherwise
        """
        return token_id in self._revoked_tokens
    
    async def revoke_token(self, token_id: str, reason: str = ""):
        """
        Add a token to the revocation list.
        
        Args:
            token_id: The token ID to revoke
            reason: Optional reason for revocation
        """
        self._revoked_tokens.add(token_id)
        logger.info(f"Token revoked: {token_id}, reason: {reason}")
        
        # TODO: In production, persist to database
        # This would involve creating a token_revocations table
    
    async def check_rate_limit(self, client_id: str) -> bool:
        """
        Check if a client has exceeded rate limits.
        
        Args:
            client_id: The client ID to check
            
        Returns:
            True if within limits, False if exceeded
        """
        now = datetime.now(timezone.utc)
        
        # Clean old entries
        self._rate_limit_counters[client_id] = [
            timestamp for timestamp in self._rate_limit_counters[client_id]
            if now - timestamp < self.rate_limit_window
        ]
        
        # Check limit
        if len(self._rate_limit_counters[client_id]) >= self.max_exchanges_per_hour:
            logger.warning(
                f"Rate limit exceeded for client {client_id}: "
                f"{len(self._rate_limit_counters[client_id])} requests in last hour"
            )
            return False
        
        # Record this request
        self._rate_limit_counters[client_id].append(now)
        return True
    
    def validate_token_scope(
        self,
        requested_scope: str,
        allowed_operations: List[str]
    ) -> bool:
        """
        Validate that requested scope is allowed.
        
        Args:
            requested_scope: The scope requested in token exchange
            allowed_operations: List of allowed operations for this client
            
        Returns:
            True if scope is valid, False otherwise
        """
        # Define valid scopes
        valid_scopes = {
            "token_exchange": ["read", "write", "exchange"],
            "introspection": ["introspect"],
            "teg:transfer:execute": ["transfer", "execute"],
            "teg:balance:read": ["balance", "read"],
            "teg:reputation:read": ["reputation", "read"]
        }
        
        # Check if requested scope is in allowed operations
        scope_parts = requested_scope.split(":")
        operation = scope_parts[0] if scope_parts else ""
        
        if operation not in allowed_operations:
            logger.warning(
                f"Scope '{requested_scope}' not in allowed operations: {allowed_operations}"
            )
            return False
        
        # Validate scope format
        if requested_scope not in valid_scopes:
            logger.warning(f"Invalid scope format: {requested_scope}")
            return False
        
        return True
    
    async def record_token_exchange(
        self,
        db: AsyncSession,
        exchange_id: str,
        source_registry: str,
        target_registry: str,
        token_jti: str,
        scope: str
    ):
        """
        Record a token exchange for audit purposes.
        
        Args:
            db: Database session
            exchange_id: Unique exchange ID
            source_registry: Source registry URL
            target_registry: Target registry URL
            token_jti: JTI of the exchanged token
            scope: Scope of the token
        """
        try:
            # Update the exchange record with security metadata
            result = await db.execute(
                select(OAuthTokenExchange).where(
                    OAuthTokenExchange.exchange_id == exchange_id
                )
            )
            exchange = result.scalar_one_or_none()
            
            if exchange:
                exchange.token_jti = token_jti
                exchange.security_metadata = {
                    "jti": token_jti,
                    "scope": scope,
                    "validated_at": datetime.now(timezone.utc).isoformat(),
                    "single_use_enforced": True
                }
                await db.commit()
                
        except Exception as e:
            logger.error(f"Failed to record token exchange security metadata: {str(e)}")
    
    async def get_client_exchange_history(
        self,
        db: AsyncSession,
        client_id: str,
        hours: int = 24
    ) -> List[Dict[str, Any]]:
        """
        Get token exchange history for a client.
        
        Args:
            db: Database session
            client_id: Client ID to query
            hours: Number of hours to look back
            
        Returns:
            List of exchange records
        """
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        
        result = await db.execute(
            select(OAuthTokenExchange)
            .where(
                and_(
                    OAuthTokenExchange.source_registry == client_id,
                    OAuthTokenExchange.created_at >= since
                )
            )
            .order_by(OAuthTokenExchange.created_at.desc())
        )
        
        exchanges = result.scalars().all()
        
        return [
            {
                "exchange_id": ex.exchange_id,
                "target_registry": ex.target_registry,
                "scope": ex.scope,
                "created_at": ex.created_at,
                "expires_at": ex.expires_at,
                "status": ex.status,
                "single_use": ex.single_use
            }
            for ex in exchanges
        ]
    
    async def _periodic_cleanup(self):
        """Periodic cleanup of expired tracking data."""
        while True:
            try:
                await asyncio.sleep(self.jti_cleanup_interval)
                
                # Clean rate limit counters
                now = datetime.now(timezone.utc)
                for client_id in list(self._rate_limit_counters.keys()):
                    self._rate_limit_counters[client_id] = [
                        timestamp for timestamp in self._rate_limit_counters[client_id]
                        if now - timestamp < self.rate_limit_window
                    ]
                    
                    # Remove empty entries
                    if not self._rate_limit_counters[client_id]:
                        del self._rate_limit_counters[client_id]
                
                logger.debug(
                    f"Security cleanup completed. "
                    f"Tracking {len(self._used_jtis)} JTIs, "
                    f"{len(self._revoked_tokens)} revoked tokens, "
                    f"{len(self._rate_limit_counters)} rate limit entries"
                )
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in periodic cleanup: {str(e)}")


# Global instance
token_security_manager = TokenSecurityManager()


async def initialize_token_security():
    """Initialize the token security manager."""
    await token_security_manager.start()


async def shutdown_token_security():
    """Shutdown the token security manager."""
    await token_security_manager.stop()
