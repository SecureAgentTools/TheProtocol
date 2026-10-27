"""
Two-Factor Authentication Router for TheProtocol Registry
Implements TOTP-based 2FA with backup codes
"""

import logging
import json
import os
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, status, Body, Security
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

# Local imports
from agentvault_registry import schemas, models, security
from agentvault_registry.models import Developer
from agentvault_registry.database import get_db
from agentvault_registry.services import TwoFactorAuthService, TwoFactorResponse

# Import security utilities
from agentvault_registry.security import get_current_developer, create_access_token

logger = logging.getLogger(__name__)


def _two_factor_key() -> str:
    """Encryption key for TOTP secrets at rest (TWO_FACTOR_ENCRYPTION_KEY).

    Empty (default) → secrets stored as-is (legacy behavior). When set,
    encrypt_secret/decrypt_secret activate Fernet transparently; legacy
    plaintext rows keep working via decrypt_secret's fallback and are
    re-encrypted the next time the secret is written.
    """
    return os.getenv("TWO_FACTOR_ENCRYPTION_KEY", "")


router = APIRouter(
    prefix="/auth/2fa",
    # §pass56 PR-5: tags= dropped; main.py:include_router supplies "Two-Factor Authentication"
)


# --- Pydantic Schemas for 2FA ---
from pydantic import BaseModel, Field

class TwoFactorSetupRequest(BaseModel):
    """Request to initiate 2FA setup"""
    password: str = Field(..., description="Current password for verification")

class TwoFactorVerifyRequest(BaseModel):
    """Request to verify TOTP code"""
    code: str = Field(..., pattern="^[0-9]{6}$", description="6-digit TOTP code")

class TwoFactorDisableRequest(BaseModel):
    """Request to disable 2FA"""
    password: str = Field(..., description="Current password for verification")
    # D6-233: required. The password alone used to turn the second factor off (the code was checked only when sent), and
    # the 6-digit pattern refused every backup code (XXXX-XXXX) the handler then tried to read.
    code: str = Field(..., pattern=r"^(?:[0-9]{6}|[0-9A-Fa-f]{4}-?[0-9A-Fa-f]{4})$",
                      description="A current 6-digit authenticator code, or an unused backup code (XXXX-XXXX)")

class TwoFactorLoginRequest(BaseModel):
    """Request to complete login with 2FA"""
    partial_token: str = Field(..., description="Partial authentication token")
    code: str = Field(..., description="TOTP code or backup code")

class TwoFactorRecoveryRequest(BaseModel):
    """Request to use backup code"""
    partial_token: str = Field(..., description="Partial authentication token")
    backup_code: str = Field(..., description="Backup recovery code")

class BackupCodesRegenerateRequest(BaseModel):
    """Request to regenerate backup codes"""
    password: str = Field(..., description="Current password for verification")
    current_code: str = Field(..., pattern="^[0-9]{6}$", description="Current TOTP code")


# --- Helper Functions ---
async def verify_developer_password(developer: Developer, password: str) -> bool:
    """Verify developer's password (the same check as the login)."""
    return security.verify_password(password, developer.hashed_password)


# --- 2FA Setup Endpoints ---
@router.post("/setup", summary="Initialize 2FA Setup")
async def setup_two_factor(
    request: TwoFactorSetupRequest,
    current_developer: Developer = Security(get_current_developer),
    db: AsyncSession = Depends(get_db)
):
    """
    Initialize 2FA setup for the current user.
    Returns QR code and backup codes.
    User must verify with a code to complete setup.
    """
    try:
        # Check if 2FA is already enabled
        if current_developer.two_fa_enabled:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Two-factor authentication is already enabled"
            )
        
        # Verify password
        if not await verify_developer_password(current_developer, request.password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid password"
            )
        
        # Generate TOTP secret
        secret = TwoFactorAuthService.generate_secret()
        
        # Generate backup codes
        backup_codes = TwoFactorAuthService.generate_backup_codes()
        
        # Hash backup codes for storage
        hashed_codes = TwoFactorAuthService.hash_backup_codes(backup_codes)
        
        # Generate QR code (desktop path) AND the otpauth:// URI (§DISCREFINE):
        # a phone cannot scan its own screen, so enrolling from the device that
        # holds the authenticator needs a tap-to-add link, not an image.
        qr_code = TwoFactorAuthService.generate_qr_code(
            current_developer.email,
            secret
        )
        otpauth_uri = TwoFactorAuthService.provisioning_uri(
            current_developer.email,
            secret
        )
        
        # Store secret and backup codes (but don't enable 2FA yet)
        stmt = (
            update(Developer)
            .where(Developer.id == current_developer.id)
            .values(
                totp_secret=TwoFactorAuthService.encrypt_secret(secret, _two_factor_key()),
                backup_codes={"codes": hashed_codes, "created_at": datetime.now(timezone.utc).isoformat()}
            )
        )
        await db.execute(stmt)
        await db.commit()
        
        # Return setup data
        return TwoFactorResponse.setup_initiated(qr_code, secret, backup_codes, otpauth_uri)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error setting up 2FA for developer {current_developer.id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to initialize 2FA setup"
        )


@router.post("/verify", summary="Complete 2FA Setup")
async def verify_two_factor_setup(
    request: TwoFactorVerifyRequest,
    current_developer: Developer = Security(get_current_developer),
    db: AsyncSession = Depends(get_db)
):
    """
    Complete 2FA setup by verifying a TOTP code.
    This enables 2FA for the account.
    """
    try:
        # Check if 2FA is already enabled
        if current_developer.two_fa_enabled:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Two-factor authentication is already enabled"
            )
        
        # Check if setup was initiated (secret exists)
        if not current_developer.totp_secret:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Please initiate 2FA setup first"
            )
        
        # Decrypt and verify the TOTP code
        secret = TwoFactorAuthService.decrypt_secret(current_developer.totp_secret, _two_factor_key())
        
        if not TwoFactorAuthService.verify_token(secret, request.code):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid verification code"
            )
        
        # Enable 2FA
        stmt = (
            update(Developer)
            .where(Developer.id == current_developer.id)
            .values(
                two_fa_enabled=True,
                two_fa_verified_at=datetime.now(timezone.utc),
                two_fa_recovery_attempts=0
            )
        )
        await db.execute(stmt)
        await db.commit()
        
        # Log the event
        logger.info(f"2FA enabled for developer {current_developer.id} ({current_developer.email})")

        # §NOTIFV2 security.2fa_changed — call site 1 of 3 (self-enable). The other two are the
        # self-disable below and the admin force-disable in routers/admin_developers.py. The
        # account-deletion path also clears 2FA but is deliberately NOT wired: the account is gone,
        # and account.deleted is the event that actually happened there.
        try:
            import asyncio as _aio_n
            from agentvault_registry.background_tasks.push_notify import notify
            _aio_n.create_task(notify(
                "security.2fa_changed", [current_developer.id],
                title="Two-factor authentication enabled",
                message="2FA is now required to sign in to your account.",
                tags="lock", priority="high", click="/ui/#/settings"))
        except Exception:  # noqa: BLE001
            logger.debug("[NOTIFY] security.2fa_changed emit failed", exc_info=True)

        return TwoFactorResponse.setup_complete()
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error verifying 2FA setup for developer {current_developer.id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to verify 2FA setup"
        )


@router.post("/disable", summary="Disable 2FA")
async def disable_two_factor(
    request: TwoFactorDisableRequest,
    current_developer: Developer = Security(get_current_developer),
    db: AsyncSession = Depends(get_db)
):
    """
    Disable 2FA for the current user.
    Requires the password and a current TOTP code or an unused backup code.
    """
    try:
        # Check if 2FA is enabled
        if not current_developer.two_fa_enabled:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Two-factor authentication is not enabled"
            )

        # Verify password
        if not await verify_developer_password(current_developer, request.password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid password"
            )

        # D6-233: the second factor is always checked, under the same failure limit as the 2FA login (/validate).
        is_allowed, error_msg = TwoFactorAuthService.check_rate_limit(
            current_developer.two_fa_last_failure,
            current_developer.two_fa_recovery_attempts or 0
        )
        if not is_allowed:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=error_msg)

        # Verify the TOTP code, else a backup code (stored hashed in the XXXX-XXXX form it was issued in)
        secret = TwoFactorAuthService.decrypt_secret(current_developer.totp_secret, _two_factor_key())
        code_valid = TwoFactorAuthService.verify_token(secret, request.code)
        if not code_valid and current_developer.backup_codes:
            _plain = request.code.replace("-", "").upper()
            if len(_plain) == 8:
                code_valid, _ = TwoFactorAuthService.verify_backup_code(
                    f"{_plain[:4]}-{_plain[4:]}",
                    current_developer.backup_codes.get("codes", [])
                )
        if not code_valid:
            await db.execute(
                update(Developer)
                .where(Developer.id == current_developer.id)
                .values(
                    two_fa_recovery_attempts=(current_developer.two_fa_recovery_attempts or 0) + 1,
                    two_fa_last_failure=datetime.now(timezone.utc)
                )
            )
            await db.commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid verification code"
            )

        # Disable 2FA
        stmt = (
            update(Developer)
            .where(Developer.id == current_developer.id)
            .values(
                two_fa_enabled=False,
                totp_secret=None,
                backup_codes=None,
                two_fa_verified_at=None,
                two_fa_recovery_attempts=0,
                two_fa_last_failure=None
            )
        )
        await db.execute(stmt)
        await db.commit()
        
        # Log the event
        logger.info(f"2FA disabled for developer {current_developer.id} ({current_developer.email})")

        # §NOTIFV2 security.2fa_changed — call site 2 of 3 (self-disable). Losing a second factor
        # is exactly the change a compromised-account owner needs to hear about, so this one is
        # worth more than the enable.
        try:
            import asyncio as _aio_n
            from agentvault_registry.background_tasks.push_notify import notify
            _aio_n.create_task(notify(
                "security.2fa_changed", [current_developer.id],
                title="Two-factor authentication disabled",
                message="2FA was turned off for your account. If this wasn't you, re-enable it now.",
                tags="warning", priority="high", click="/ui/#/settings"))
        except Exception:  # noqa: BLE001
            logger.debug("[NOTIFY] security.2fa_changed emit failed", exc_info=True)

        return TwoFactorResponse.disabled()
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error disabling 2FA for developer {current_developer.id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to disable 2FA"
        )


# --- 2FA Login Endpoints ---
@router.post("/validate", summary="Validate 2FA Code During Login")
async def validate_two_factor(
    request: TwoFactorLoginRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Complete login by providing 2FA code.
    Called after successful password authentication.
    """
    try:
        # Verify partial token
        developer_id = TwoFactorAuthService.verify_partial_token(request.partial_token)
        if not developer_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired partial token"
            )
        
        # Get developer
        stmt = select(Developer).where(Developer.id == developer_id)
        result = await db.execute(stmt)
        developer = result.scalar_one_or_none()
        
        if not developer or not developer.two_fa_enabled:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid request"
            )
        
        # Check rate limiting
        is_allowed, error_msg = TwoFactorAuthService.check_rate_limit(
            developer.two_fa_last_failure,
            developer.two_fa_recovery_attempts
        )
        if not is_allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=error_msg
            )
        
        # Verify TOTP code
        secret = TwoFactorAuthService.decrypt_secret(developer.totp_secret, _two_factor_key())
        
        if TwoFactorAuthService.verify_token(secret, request.code):
            # Reset failure counter
            stmt = (
                update(Developer)
                .where(Developer.id == developer.id)
                .values(
                    two_fa_recovery_attempts=0,
                    two_fa_last_failure=None
                )
            )
            await db.execute(stmt)
            await db.commit()
            
            # Generate full access token with developer ID as subject
            # AL-1: stamp token_version for revocation parity with password login.
            access_token = create_access_token(
                data={"sub": str(developer.id)},  # Use developer ID, not email
                token_version=getattr(developer, "token_version", 0),
            )
            
            logger.info(f"2FA login successful for developer {developer.id}")
            
            return {
                "access_token": access_token,
                "token_type": "bearer",
                # §FEFRAME W1: the same session a password login gets. Without a refresh token a 2FA session could not
                # refresh and ended hard at the access token's expiry (90 min), and "remember me" did nothing.
                "refresh_token": security.create_refresh_token(
                    developer.id, token_version=getattr(developer, "token_version", 0)),
                "developer": {
                    "id": developer.id,
                    "email": developer.email,
                    "name": developer.name,
                    "is_admin": developer.is_admin
                }
            }
        else:
            # Increment failure counter
            stmt = (
                update(Developer)
                .where(Developer.id == developer.id)
                .values(
                    two_fa_recovery_attempts=developer.two_fa_recovery_attempts + 1,
                    two_fa_last_failure=datetime.now(timezone.utc)
                )
            )
            await db.execute(stmt)
            await db.commit()
            
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid verification code"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error validating 2FA: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to validate 2FA"
        )


@router.post("/recover", summary="Use Backup Code")
async def recover_with_backup_code(
    request: TwoFactorRecoveryRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Complete login using a backup recovery code.
    The used backup code will be invalidated.
    """
    try:
        # Verify partial token
        developer_id = TwoFactorAuthService.verify_partial_token(request.partial_token)
        if not developer_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired partial token"
            )
        
        # Get developer
        stmt = select(Developer).where(Developer.id == developer_id)
        result = await db.execute(stmt)
        developer = result.scalar_one_or_none()
        
        if not developer or not developer.two_fa_enabled:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid request"
            )
        
        # Check rate limiting
        is_allowed, error_msg = TwoFactorAuthService.check_rate_limit(
            developer.two_fa_last_failure,
            developer.two_fa_recovery_attempts
        )
        if not is_allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=error_msg
            )
        
        # Verify backup code
        if not developer.backup_codes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No backup codes available"
            )
        
        hashed_codes = developer.backup_codes.get("codes", [])
        is_valid, matched_hash = TwoFactorAuthService.verify_backup_code(
            request.backup_code,  # Keep original format - codes are hashed WITH hyphens
            hashed_codes
        )
        
        if is_valid:
            # Remove used backup code
            remaining_codes = [h for h in hashed_codes if h != matched_hash]
            
            # Update developer with remaining codes
            stmt = (
                update(Developer)
                .where(Developer.id == developer.id)
                .values(
                    backup_codes={
                        "codes": remaining_codes,
                        "created_at": developer.backup_codes.get("created_at"),
                        "used_at": datetime.now(timezone.utc).isoformat()
                    },
                    two_fa_recovery_attempts=0,
                    two_fa_last_failure=None
                )
            )
            await db.execute(stmt)
            await db.commit()
            
            # Generate full access token with developer ID as subject
            # AL-1: stamp token_version for revocation parity with password login.
            access_token = create_access_token(
                data={"sub": str(developer.id)},  # Use developer ID, not email
                token_version=getattr(developer, "token_version", 0),
            )
            
            logger.info(f"2FA recovery successful for developer {developer.id}")
            
            # Warn if low on backup codes
            warning = None
            if len(remaining_codes) <= 2:
                warning = f"Only {len(remaining_codes)} backup codes remaining. Consider regenerating."
            
            return {
                "access_token": access_token,
                "token_type": "bearer",
                # §FEFRAME W1: a backup-code login is a full session too (see /validate)
                "refresh_token": security.create_refresh_token(
                    developer.id, token_version=getattr(developer, "token_version", 0)),
                "developer": {
                    "id": developer.id,
                    "email": developer.email,
                    "name": developer.name,
                    "is_admin": developer.is_admin
                },
                "warning": warning
            }
        else:
            # Increment failure counter
            stmt = (
                update(Developer)
                .where(Developer.id == developer.id)
                .values(
                    two_fa_recovery_attempts=developer.two_fa_recovery_attempts + 1,
                    two_fa_last_failure=datetime.now(timezone.utc)
                )
            )
            await db.execute(stmt)
            await db.commit()
            
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid backup code"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error recovering with backup code: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to recover with backup code"
        )


@router.post("/backup-codes", summary="Regenerate Backup Codes")
async def regenerate_backup_codes(
    request: BackupCodesRegenerateRequest,
    current_developer: Developer = Security(get_current_developer),
    db: AsyncSession = Depends(get_db)
):
    """
    Generate new backup codes.
    Requires password and current TOTP code.
    This will invalidate all existing backup codes.
    """
    try:
        # Check if 2FA is enabled
        if not current_developer.two_fa_enabled:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Two-factor authentication is not enabled"
            )
        
        # Verify password
        if not await verify_developer_password(current_developer, request.password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid password"
            )
        
        # Verify TOTP code
        secret = TwoFactorAuthService.decrypt_secret(current_developer.totp_secret, _two_factor_key())
        if not TwoFactorAuthService.verify_token(secret, request.current_code):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid verification code"
            )
        
        # Generate new backup codes
        backup_codes = TwoFactorAuthService.generate_backup_codes()
        
        # Hash backup codes for storage
        hashed_codes = TwoFactorAuthService.hash_backup_codes(backup_codes)
        
        # Update developer with new codes
        stmt = (
            update(Developer)
            .where(Developer.id == current_developer.id)
            .values(
                backup_codes={
                    "codes": hashed_codes,
                    "created_at": datetime.now(timezone.utc).isoformat()
                }
            )
        )
        await db.execute(stmt)
        await db.commit()
        
        logger.info(f"Backup codes regenerated for developer {current_developer.id}")
        
        return {
            "backup_codes": backup_codes,
            "message": "New backup codes generated. Save these in a secure location."
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error regenerating backup codes for developer {current_developer.id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to regenerate backup codes"
        )


@router.get("/status", summary="Get 2FA Status")
async def get_two_factor_status(
    current_developer: Developer = Security(get_current_developer),
    db: AsyncSession = Depends(get_db)
):
    """
    Get the current 2FA status for the authenticated user.
    """
    backup_codes_count = 0
    if current_developer.backup_codes:
        backup_codes_count = len(current_developer.backup_codes.get("codes", []))
    
    return {
        "enabled": current_developer.two_fa_enabled,
        "verified_at": current_developer.two_fa_verified_at.isoformat() if current_developer.two_fa_verified_at else None,
        "backup_codes_remaining": backup_codes_count if current_developer.two_fa_enabled else None
    }
