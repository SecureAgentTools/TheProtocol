"""
Secure configuration management for AgentVault Registry
Uses Pydantic Settings for validation and type safety
"""

import os
import json
import sys
from typing import List, Optional
from pathlib import Path

from pydantic import Field, SecretStr, validator, ValidationError
from pydantic_settings import BaseSettings


def read_secret(secret_name: str) -> Optional[str]:
    """Read secret from Docker secrets mount point or environment"""
    # Try Docker secret first
    secret_file = Path(f"/run/secrets/{secret_name}")
    if secret_file.exists():
        return secret_file.read_text().strip()
    
    # Try environment variable file reference
    env_file_var = f"{secret_name.upper()}_FILE"
    if env_file_var in os.environ:
        file_path = Path(os.environ[env_file_var])
        if file_path.exists():
            return file_path.read_text().strip()
    
    # Development fallback - environment variable
    return os.environ.get(secret_name.upper())


class AgentVaultSettings(BaseSettings):
    """Secure configuration for AgentVault Registry API"""
    
    # Environment
    environment: str = Field(
        default="development",
        description="Deployment environment (development, staging, production)"
    )
    
    # Database Configuration - NO DEFAULTS for credentials
    database_url: SecretStr = Field(
        ...,
        description="PostgreSQL connection URL"
    )
    
    # Security Configuration
    api_key_secret: SecretStr = Field(
        ...,
        description="Secret key for API key generation and JWT signing"
    )
    
    # Admin Configuration
    admin_email: Optional[str] = Field(
        default=None,
        description="Initial admin email (for bootstrap only)"
    )
    
    admin_name: Optional[str] = Field(
        default="Administrator",
        description="Initial admin name"
    )
    
    initial_admin_password: Optional[SecretStr] = Field(
        default=None,
        description="Initial admin password (for bootstrap only)"
    )
    
    # CORS Configuration
    allowed_origins: List[str] = Field(
        default_factory=list,
        description="Allowed CORS origins"
    )
    
    # Rate Limiting
    rate_limit_requests: int = Field(
        default=100,
        description="Number of requests allowed per hour"
    )
    
    rate_limit_enabled: bool = Field(
        default=True,
        description="Enable rate limiting"
    )
    
    # Email Configuration
    mail_server: Optional[str] = Field(
        default=None,
        description="SMTP server hostname"
    )
    
    mail_port: int = Field(
        default=587,
        description="SMTP server port"
    )
    
    mail_username: Optional[str] = Field(
        default=None,
        description="SMTP username"
    )
    
    mail_password: Optional[SecretStr] = Field(
        default=None,
        description="SMTP password"
    )
    
    mail_from: Optional[str] = Field(
        default=None,
        description="Default sender email"
    )
    
    mail_from_name: str = Field(
        default="AgentVault Registry",
        description="Default sender name"
    )
    
    mail_starttls: bool = Field(
        default=True,
        description="Use STARTTLS for email"
    )
    
    mail_ssl_tls: bool = Field(
        default=False,
        description="Use SSL/TLS for email"
    )
    
    # Logging
    log_level: str = Field(
        default="INFO",
        description="Logging level"
    )
    
    # Token Configuration
    access_token_expire_minutes: int = Field(
        default=90,  # §pass73.3.5 — aligned with primary config.py default. Tripled from old 30min (was 60 here, 30 there — split brain). Env-overridable.
        description="Access token expiration time in minutes"
    )
    
    refresh_token_expire_days: int = Field(
        default=7,
        description="Refresh token expiration time in days"
    )
    
    # Redis Configuration (for advanced rate limiting)
    redis_url: Optional[SecretStr] = Field(
        default=None,
        description="Redis connection URL for rate limiting and caching"
    )
    
    # TEG Integration Configuration
    teg_api_base_url: str = Field(
        default="https://localhost:8001",
        description="TEG Layer API base URL"
    )
    
    jwt_svid_signing_key: Optional[SecretStr] = Field(
        default=None,
        description="Signing key for JWT-SVID tokens (MVP only)"
    )
    
    @validator('allowed_origins', pre=True)
    def parse_cors_origins(cls, v):
        """Parse CORS origins from string or list"""
        if isinstance(v, str):
            # Parse JSON string or comma-separated list
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return [origin.strip() for origin in v.split(',') if origin.strip()]
        return v
    
    @validator('allowed_origins')
    def set_default_origins(cls, v, values):
        """Set environment-specific default origins"""
        if not v:
            env = values.get('environment', 'development')
            if env == 'production':
                # In production, CORS must be explicitly configured
                raise ValueError(
                    "ALLOWED_ORIGINS must be explicitly set in production"
                )
            elif env == 'staging':
                return ['https://staging.agentvault.com']
            else:
                # Development defaults
                return ['http://localhost:3000', 'http://localhost:8080']
        return v
    
    @validator('api_key_secret')
    def validate_api_key_secret(cls, v):
        """Ensure API key secret is strong enough"""
        secret = v.get_secret_value()
        if len(secret) < 32:
            raise ValueError(
                "API_KEY_SECRET must be at least 32 characters long. "
                "Generate with: openssl rand -hex 32"
            )
        return v
    
    @validator('mail_password', 'initial_admin_password')
    def validate_passwords(cls, v):
        """Validate password strength"""
        if v is None:
            return v
        password = v.get_secret_value()
        if len(password) < 12:
            raise ValueError("Password must be at least 12 characters long")
        return v
    
    @property
    def is_email_configured(self) -> bool:
        """Check if email is properly configured"""
        return all([
            self.mail_server,
            self.mail_username,
            self.mail_password,
            self.mail_from
        ])
    
    @property
    def database_url_safe(self) -> str:
        """Get database URL with masked password for logging"""
        url = self.database_url.get_secret_value()
        # Mask password in URL
        import re
        return re.sub(
            r'://([^:]+):([^@]+)@',
            r'://\1:****@',
            url
        )
    
    class Config:
        env_file = '.env'
        case_sensitive = False
        extra = 'ignore'  # Allow extra env vars like teg_admin_api_key
        
        @classmethod
        def customise_sources(
            cls,
            init_settings,
            env_settings,
            file_secret_settings,
        ):
            # Add Docker secrets support
            def docker_secrets_settings(settings):
                """Load settings from Docker secrets"""
                updates = {}
                
                # Map of setting names to secret names
                secret_mappings = {
                    'database_url': 'database_url',
                    'api_key_secret': 'api_key_secret',
                    'mail_password': 'mail_password',
                    'initial_admin_password': 'admin_password',
                    'redis_url': 'redis_url'
                }
                
                for setting_name, secret_name in secret_mappings.items():
                    secret_value = read_secret(secret_name)
                    if secret_value:
                        updates[setting_name] = secret_value
                
                return updates
            
            return (
                init_settings,
                docker_secrets_settings,
                env_settings,
                file_secret_settings,
            )


# Initialize settings with validation
try:
    settings = AgentVaultSettings()
except ValidationError as e:
    print("Configuration Error!")
    print("=" * 60)
    for error in e.errors():
        field = '.'.join(str(x) for x in error['loc'])
        print(f"  {field}: {error['msg']}")
    print("=" * 60)
    print("\nPlease check your environment variables or .env file")
    print("Required variables:")
    print("  - DATABASE_URL: PostgreSQL connection string")
    print("  - API_KEY_SECRET: At least 32 characters (use: openssl rand -hex 32)")
    print("\nFor production, also set:")
    print("  - ALLOWED_ORIGINS: Comma-separated list of allowed origins")
    sys.exit(1)


# Log configuration status (without sensitive data)
if __name__ == "__main__":
    print("Configuration loaded successfully!")
    print(f"Environment: {settings.environment}")
    print(f"Database URL: {settings.database_url_safe}")
    print(f"Email configured: {settings.is_email_configured}")
    print(f"CORS origins: {settings.allowed_origins}")
    print(f"Rate limiting: {settings.rate_limit_enabled} ({settings.rate_limit_requests}/hour)")
