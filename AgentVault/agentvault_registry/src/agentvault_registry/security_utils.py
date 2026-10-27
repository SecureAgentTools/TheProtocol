"""
Advanced security utilities for AgentVault Registry
Implements rate limiting, JWT rotation, and security headers
"""

import secrets
import base64
import jwt
import redis.asyncio as redis
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, Tuple
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend
from fastapi import Request, Response, HTTPException
from fastapi.responses import JSONResponse
import logging

logger = logging.getLogger(__name__)


class SlidingWindowRateLimiter:
    """Redis-based sliding window rate limiter with precise control"""
    
    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
        self.lua_script = """
        local key = KEYS[1]
        local window_start = tonumber(ARGV[1])
        local now = tonumber(ARGV[2])
        local limit = tonumber(ARGV[3])
        local window_seconds = tonumber(ARGV[4])
        
        -- Remove old entries
        redis.call('ZREMRANGEBYSCORE', key, '-inf', window_start)
        
        -- Count current requests
        local current = redis.call('ZCARD', key)
        
        if current < limit then
            -- Add new request with unique score
            redis.call('ZADD', key, now, now .. ':' .. redis.call('INCR', 'counter'))
            redis.call('EXPIRE', key, window_seconds)
            return {1, current + 1, limit - current - 1}
        else
            -- Get oldest entry to calculate retry time
            local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
            local retry_after = window_seconds
            if oldest[2] then
                retry_after = math.ceil(oldest[2] + window_seconds - now)
            end
            return {0, current, 0, retry_after}
        end
        """
        self.script_sha = None
    
    async def initialize(self):
        """Load Lua script into Redis"""
        try:
            self.script_sha = await self.redis.script_load(self.lua_script)
        except Exception as e:
            logger.error(f"Failed to load rate limit script: {e}")
    
    async def is_allowed(
        self, 
        key: str, 
        limit: int, 
        window_seconds: int
    ) -> Tuple[bool, Dict[str, Any]]:
        """Check if request is allowed within rate limit"""
        now = datetime.now(timezone.utc).timestamp()
        window_start = now - window_seconds
        
        try:
            # Try to use cached script
            if self.script_sha:
                try:
                    result = await self.redis.evalsha(
                        self.script_sha, 1, key,
                        str(window_start), str(now), str(limit), str(window_seconds)
                    )
                except redis.NoScriptError:
                    self.script_sha = None
            
            # Fallback to eval if script not cached
            if not self.script_sha:
                result = await self.redis.eval(
                    self.lua_script, 1, key,
                    str(window_start), str(now), str(limit), str(window_seconds)
                )
            
            allowed = bool(result[0])
            current = int(result[1])
            remaining = int(result[2])
            retry_after = int(result[3]) if len(result) > 3 else window_seconds
            
            return allowed, {
                "allowed": allowed,
                "limit": limit,
                "remaining": remaining,
                "reset": int(now + window_seconds),
                "retry_after": retry_after if not allowed else None,
                "current": current
            }
            
        except Exception as e:
            logger.error(f"Rate limit check failed: {e}")
            # Fail open in case of Redis issues
            return True, {
                "allowed": True,
                "limit": limit,
                "remaining": limit,
                "error": str(e)
            }


class JWTKeyManager:
    """Manages JWT key rotation with RSA key pairs"""
    
    def __init__(self, key_dir: Path = Path("/app/data/keys")):
        self.key_dir = key_dir
        self.key_dir.mkdir(parents=True, exist_ok=True)
        self.keys: Dict[str, Dict[str, Any]] = {}
        self.current_key_id: Optional[str] = None
        self.max_keys = 3
    
    async def initialize(self):
        """Load existing keys or generate new ones"""
        # Load existing keys
        for key_file in self.key_dir.glob("*.pem"):
            key_id = key_file.stem
            try:
                private_key = self._load_private_key(key_file)
                creation_time = datetime.fromtimestamp(
                    key_file.stat().st_mtime, 
                    tz=timezone.utc
                )
                self.keys[key_id] = {
                    "private_key": private_key,
                    "public_key": private_key.public_key(),
                    "created_at": creation_time,
                    "file_path": key_file
                }
            except Exception as e:
                logger.error(f"Failed to load key {key_id}: {e}")
        
        # Generate new key if none exist
        if not self.keys:
            await self.rotate_keys()
        else:
            # Use the newest key
            self.current_key_id = max(
                self.keys.keys(),
                key=lambda k: self.keys[k]["created_at"]
            )
    
    def _load_private_key(self, key_path: Path):
        """Load private key from file"""
        with open(key_path, "rb") as f:
            return serialization.load_pem_private_key(
                f.read(),
                password=None,
                backend=default_backend()
            )
    
    async def rotate_keys(self):
        """Generate new RSA key pair for JWT signing"""
        key_id = f"key_{int(datetime.now(timezone.utc).timestamp())}"
        
        # Generate RSA key pair
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
            backend=default_backend()
        )
        
        # Save private key
        key_path = self.key_dir / f"{key_id}.pem"
        with open(key_path, "wb") as f:
            f.write(
                private_key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.PKCS8,
                    encryption_algorithm=serialization.NoEncryption()
                )
            )
        
        # Set secure permissions
        key_path.chmod(0o600)
        
        # Store key information
        self.keys[key_id] = {
            "private_key": private_key,
            "public_key": private_key.public_key(),
            "created_at": datetime.now(timezone.utc),
            "file_path": key_path
        }
        
        self.current_key_id = key_id
        
        # Remove old keys
        await self._cleanup_old_keys()
        
        logger.info(f"Rotated JWT keys, new key ID: {key_id}")
    
    async def _cleanup_old_keys(self):
        """Remove old keys keeping only the most recent ones"""
        if len(self.keys) <= self.max_keys:
            return
        
        # Sort by creation time
        sorted_keys = sorted(
            self.keys.items(),
            key=lambda x: x[1]["created_at"]
        )
        
        # Remove oldest keys
        for key_id, key_info in sorted_keys[:-self.max_keys]:
            try:
                key_info["file_path"].unlink()
                del self.keys[key_id]
                logger.info(f"Removed old key: {key_id}")
            except Exception as e:
                logger.error(f"Failed to remove old key {key_id}: {e}")
    
    def create_token(self, payload: Dict[str, Any], expires_delta: timedelta) -> str:
        """Create JWT with current key"""
        if not self.current_key_id:
            raise RuntimeError("No JWT signing key available")
        
        now = datetime.now(timezone.utc)
        payload.update({
            "iat": now,
            "exp": now + expires_delta,
            "kid": self.current_key_id
        })
        
        return jwt.encode(
            payload,
            self.keys[self.current_key_id]["private_key"],
            algorithm="RS256",
            headers={"kid": self.current_key_id}
        )
    
    def verify_token(self, token: str) -> Dict[str, Any]:
        """Verify JWT token using appropriate key"""
        # Decode header to get key ID
        header = jwt.get_unverified_header(token)
        key_id = header.get("kid")
        
        if not key_id or key_id not in self.keys:
            raise jwt.InvalidKeyError("Unknown key ID")
        
        return jwt.decode(
            token,
            self.keys[key_id]["public_key"],
            algorithms=["RS256"],
            options={"verify_exp": True}
        )
    
    def get_jwks(self) -> Dict[str, Any]:
        """Get JSON Web Key Set for public key distribution"""
        jwks = {"keys": []}
        
        for key_id, key_info in self.keys.items():
            public_key = key_info["public_key"]
            public_numbers = public_key.public_numbers()
            
            # Convert to base64url format
            def int_to_base64url(n: int) -> str:
                byte_length = (n.bit_length() + 7) // 8
                return base64.urlsafe_b64encode(n.to_bytes(byte_length, 'big')).rstrip(b'=').decode()
            
            jwk = {
                "kty": "RSA",
                "use": "sig",
                "kid": key_id,
                "n": int_to_base64url(public_numbers.n),
                "e": int_to_base64url(public_numbers.e),
                "alg": "RS256"
            }
            jwks["keys"].append(jwk)
        
        return jwks


def add_security_headers(response: Response):
    """Add comprehensive security headers to response"""
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    
    # Content Security Policy
    csp = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: https:; "
        "font-src 'self'; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self';"
    )
    response.headers["Content-Security-Policy"] = csp
    
    # HSTS (always add — we're behind nginx HTTPS)
    response.headers["Strict-Transport-Security"] = (
        "max-age=63072000; includeSubDomains; preload"
    )
    
    return response


async def security_middleware(request: Request, call_next):
    """Comprehensive security middleware"""
    # Add request ID for tracing
    request_id = request.headers.get("X-Request-ID", secrets.token_urlsafe(16))
    
    # Log request
    logger.info(
        f"Request: {request.method} {request.url.path} "
        f"from {request.client.host if request.client else 'unknown'} "
        f"[{request_id}]"
    )
    
    # Process request
    start_time = datetime.now()
    response = await call_next(request)
    duration = (datetime.now() - start_time).total_seconds()
    
    # Add security headers
    add_security_headers(response)
    
    # Add custom headers
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Response-Time"] = f"{duration:.3f}"
    
    # Log response
    logger.info(
        f"Response: {response.status_code} "
        f"for {request.method} {request.url.path} "
        f"[{request_id}] ({duration:.3f}s)"
    )
    
    return response


def validate_password_strength(password: str) -> Tuple[bool, Optional[str]]:
    """Validate password meets security requirements"""
    if len(password) < 12:
        return False, "Password must be at least 12 characters long"
    
    has_upper = any(c.isupper() for c in password)
    has_lower = any(c.islower() for c in password)
    has_digit = any(c.isdigit() for c in password)
    has_special = any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in password)
    
    if not all([has_upper, has_lower, has_digit, has_special]):
        return False, (
            "Password must contain uppercase, lowercase, "
            "digit, and special character"
        )
    
    # Check for common patterns
    common_patterns = [
        "password", "123456", "qwerty", "admin", "letmein",
        "welcome", "monkey", "dragon", "master", "superman"
    ]
    
    password_lower = password.lower()
    for pattern in common_patterns:
        if pattern in password_lower:
            return False, "Password contains common pattern"
    
    return True, None


def generate_secure_token(length: int = 32) -> str:
    """Generate cryptographically secure token"""
    return secrets.token_urlsafe(length)


def generate_api_key() -> str:
    """Generate secure API key with prefix"""
    prefix = "av_"
    key = secrets.token_urlsafe(32)
    return f"{prefix}{key}"
