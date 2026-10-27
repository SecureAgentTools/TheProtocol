"""
Two-Factor Authentication Service
Handles TOTP generation, verification, and backup codes
"""

# Conditional imports to prevent startup failure if packages not installed yet
try:
    import pyotp
    import qrcode
    TOTP_AVAILABLE = True
except ImportError:
    TOTP_AVAILABLE = False
    pyotp = None
    qrcode = None

import io
import os
import base64
import secrets
import hashlib
import time
from typing import List, Optional, Tuple, Dict
from datetime import datetime, timedelta, timezone
from agentvault_registry.core.secret_hash import hash_secret, verify_secret
from cryptography.fernet import Fernet

class TwoFactorAuthService:
    """Service for handling 2FA/TOTP operations"""
    
    # Configuration
    TOTP_ISSUER = "TheProtocol"
    TOTP_DIGITS = 6
    TOTP_INTERVAL = 30  # seconds
    BACKUP_CODE_COUNT = 10
    BACKUP_CODE_LENGTH = 8  # Will generate 8-character hex codes
    MAX_RECOVERY_ATTEMPTS = 5
    RATE_LIMIT_WINDOW_MINUTES = 15
    MAX_ATTEMPTS_PER_WINDOW = 5
    
    @staticmethod
    def generate_secret() -> str:
        """
        Generate a new TOTP secret
        Returns: Base32 encoded secret
        """
        if not TOTP_AVAILABLE:
            raise RuntimeError("TOTP functionality not available. Please install pyotp: pip install pyotp")
        return pyotp.random_base32()
    
    @staticmethod
    def generate_backup_codes(count: int = None) -> List[str]:
        """
        Generate backup recovery codes
        
        Args:
            count: Number of codes to generate (default: BACKUP_CODE_COUNT)
            
        Returns:
            List of backup codes
        """
        if count is None:
            count = TwoFactorAuthService.BACKUP_CODE_COUNT
            
        codes = []
        for _ in range(count):
            # Generate 8-character hex codes (easier to type than full hex)
            code = secrets.token_hex(4).upper()  # 4 bytes = 8 hex chars
            codes.append(f"{code[:4]}-{code[4:]}")  # Format as XXXX-XXXX
        
        return codes
    
    @staticmethod
    def hash_backup_codes(codes: List[str]) -> List[str]:
        """
        Hash backup codes for secure storage
        
        Args:
            codes: Plain text backup codes
            
        Returns:
            List of hashed codes
        """
        return [hash_secret(code) for code in codes]
    
    @staticmethod
    def verify_backup_code(code: str, hashed_codes: List[str]) -> Tuple[bool, Optional[str]]:
        """
        Verify a backup code against hashed codes
        
        Args:
            code: Plain text code to verify
            hashed_codes: List of hashed codes
            
        Returns:
            Tuple of (is_valid, matched_hash) where matched_hash is the hash that matched
        """
        for hashed_code in hashed_codes:
            if verify_secret(code, hashed_code):
                return True, hashed_code
        return False, None
    
    @staticmethod
    def provisioning_uri(email: str, secret: str, issuer: str = None) -> str:
        """The otpauth:// URI an authenticator app consumes.

        §DISCREFINE (2026-08-23): this was already being computed inside
        generate_qr_code and then thrown away, so enrolment offered a QR image
        and nothing else. A QR is unusable on the device it is displayed on —
        a phone cannot scan its own screen — which made phone-only enrolment a
        copy-the-secret-by-hand exercise. Returned now so the client can offer a
        TAP-TO-ADD link, which is the one-tap path on both iOS and Android.
        """
        if not TOTP_AVAILABLE:
            raise RuntimeError("TOTP functionality not available. Please install pyotp and qrcode: pip install pyotp qrcode[pil]")
        if issuer is None:
            issuer = TwoFactorAuthService.TOTP_ISSUER
        return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=issuer)

    @staticmethod
    def generate_qr_code(email: str, secret: str, issuer: str = None) -> str:
        """
        Generate QR code for authenticator apps
        
        Args:
            email: User's email address
            secret: TOTP secret
            issuer: Optional issuer name override
            
        Returns:
            Base64 encoded PNG image of QR code
        """
        if not TOTP_AVAILABLE:
            raise RuntimeError("TOTP functionality not available. Please install pyotp and qrcode: pip install pyotp qrcode[pil]")
            
        if issuer is None:
            issuer = TwoFactorAuthService.TOTP_ISSUER
            
        # Create TOTP URI for authenticator apps
        totp = pyotp.TOTP(secret)
        uri = totp.provisioning_uri(
            name=email,
            issuer_name=issuer
        )
        
        # Generate QR code
        qr = qrcode.QRCode(
            version=1,  # Controls size, 1 is smallest
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(uri)
        qr.make(fit=True)
        
        # Create image
        img = qr.make_image(fill_color="black", back_color="white")
        
        # Convert to base64
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)
        
        return base64.b64encode(buffer.getvalue()).decode('utf-8')
    
    @staticmethod
    def verify_token(secret: str, token: str, window: int = 1) -> bool:
        """
        Verify a TOTP token
        
        Args:
            secret: TOTP secret
            token: 6-digit token to verify
            window: Number of time windows to check (default: 1 = ±30 seconds)
            
        Returns:
            True if token is valid
        """
        if not TOTP_AVAILABLE:
            raise RuntimeError("TOTP functionality not available. Please install pyotp: pip install pyotp")
            
        if not token or not secret:
            return False
            
        # Remove any spaces or hyphens from token
        token = token.replace(' ', '').replace('-', '')
        
        # Verify token is 6 digits
        if not token.isdigit() or len(token) != TwoFactorAuthService.TOTP_DIGITS:
            return False
            
        totp = pyotp.TOTP(secret)
        return totp.verify(token, valid_window=window)
    
    @staticmethod
    def generate_provisioning_data(email: str, secret: str) -> Dict[str, str]:
        """
        Generate all data needed for 2FA setup
        
        Args:
            email: User's email
            secret: TOTP secret
            
        Returns:
            Dictionary with qr_code, secret, and manual_entry_key
        """
        return {
            "qr_code": TwoFactorAuthService.generate_qr_code(email, secret),
            "secret": secret,
            "manual_entry_key": TwoFactorAuthService.format_secret_for_display(secret),
            "issuer": TwoFactorAuthService.TOTP_ISSUER
        }
    
    @staticmethod
    def format_secret_for_display(secret: str) -> str:
        """
        Format secret for manual entry (space every 4 characters)
        
        Args:
            secret: TOTP secret
            
        Returns:
            Formatted secret
        """
        # Add spaces every 4 characters for easier manual entry
        return ' '.join([secret[i:i+4] for i in range(0, len(secret), 4)])
    
    @staticmethod
    def check_rate_limit(last_failure: Optional[datetime], 
                        recovery_attempts: int) -> Tuple[bool, Optional[str]]:
        """
        Check if user is rate limited
        
        Args:
            last_failure: Timestamp of last failed attempt
            recovery_attempts: Number of failed attempts
            
        Returns:
            Tuple of (is_allowed, error_message)
        """
        if recovery_attempts >= TwoFactorAuthService.MAX_RECOVERY_ATTEMPTS:
            if last_failure:
                time_since_failure = datetime.now(timezone.utc) - last_failure
                wait_time = timedelta(minutes=TwoFactorAuthService.RATE_LIMIT_WINDOW_MINUTES)
                
                if time_since_failure < wait_time:
                    remaining = (wait_time - time_since_failure).seconds // 60
                    return False, f"Too many failed attempts. Please try again in {remaining} minutes."
        
        return True, None
    
    @staticmethod
    def _get_fernet(encryption_key: str) -> Fernet:
        """Derive a Fernet key from the encryption_key string."""
        # Use SHA-256 to derive a 32-byte key, then base64-encode for Fernet
        key_bytes = hashlib.sha256(encryption_key.encode()).digest()
        return Fernet(base64.urlsafe_b64encode(key_bytes))

    @staticmethod
    def encrypt_secret(secret: str, encryption_key: str) -> str:
        """
        Encrypt TOTP secret for storage using Fernet symmetric encryption.

        When no encryption key is configured (empty string), stores the secret
        as-is. This allows the system to work before the totp_secret column is
        widened to support Fernet tokens (~180 chars). Once the column is
        varchar(255)+ and a real key is set, encryption activates automatically.

        Args:
            secret: Plain text secret
            encryption_key: Encryption key (from settings)

        Returns:
            Encrypted secret (Fernet token) or plain secret if no key configured
        """
        if not encryption_key:
            return secret
        f = TwoFactorAuthService._get_fernet(encryption_key)
        return f.encrypt(secret.encode()).decode()

    @staticmethod
    def decrypt_secret(encrypted_secret: str, encryption_key: str) -> str:
        """
        Decrypt TOTP secret from storage using Fernet symmetric decryption.

        Handles unencrypted secrets gracefully — if no key is configured or
        decryption fails, returns the secret as-is.

        Args:
            encrypted_secret: Encrypted secret (Fernet token) or plain secret
            encryption_key: Encryption key (from settings)

        Returns:
            Plain text secret
        """
        if not encryption_key:
            return encrypted_secret
        try:
            f = TwoFactorAuthService._get_fernet(encryption_key)
            return f.decrypt(encrypted_secret.encode()).decode()
        except Exception:
            # Fallback: secret was stored unencrypted (no key configured at
            # write time, or stored before encryption was enabled).
            return encrypted_secret
    
    # 2026-07-25 (§COCKPIT): BOTH halves of the partial-token pair were broken and could never
    # have worked together. generate signed with `settings.SECRET_KEY` — a field that does not
    # exist on Settings — so EVERY login by a 2FA-enabled developer raised AttributeError → 500
    # (surfaced the moment the Cockpit E2E enrolled 2FA and logged back in). verify, meanwhile,
    # base64-JSON-decoded a payload with `partial_auth`/`developer_id` keys that generate never
    # emitted. Both now speak the same signed JWT and use the real secret (API_KEY_SECRET, the
    # same one security.py binds as SECRET_KEY — imported from config to avoid a circular import).
    @staticmethod
    def generate_partial_token(developer_id: int, expires_in_minutes: int = 5) -> str:
        """
        Generate a signed partial authentication token for 2FA flow.
        Uses proper JWT with HMAC signature — not forgeable.
        """
        import jwt as pyjwt
        from agentvault_registry.config import settings

        payload = {
            "sub": str(developer_id),
            "purpose": "partial_2fa",
            "exp": int(time.time()) + (expires_in_minutes * 60)
        }
        return pyjwt.encode(payload, settings.API_KEY_SECRET, algorithm="HS256")

    @staticmethod
    def verify_partial_token(token: str) -> Optional[int]:
        """
        Verify and decode partial authentication token

        Args:
            token: Partial token to verify

        Returns:
            Developer ID if valid, None otherwise
        """
        try:
            import jwt as pyjwt
            from agentvault_registry.config import settings

            # Signature + `exp` are verified by the library; an unsigned or stale token raises.
            payload = pyjwt.decode(token, settings.API_KEY_SECRET, algorithms=["HS256"])
            if payload.get("purpose") != "partial_2fa":
                return None
            sub = payload.get("sub")
            return int(sub) if sub is not None else None
        except Exception:
            return None


# Helper class for 2FA responses
class TwoFactorResponse:
    """Standardized response format for 2FA operations"""
    
    @staticmethod
    def setup_initiated(qr_code: str, secret: str, backup_codes: List[str],
                        otpauth_uri: str = "") -> dict:
        """Response for 2FA setup initiation.

        `otpauth_uri` (§DISCREFINE) is the tap-to-add link for phone enrolment;
        `secret_raw` is the unspaced secret for a copy button. `secret` keeps its
        spaced display form so existing clients render exactly as before.
        """
        return {
            "status": "setup_required",
            "qr_code": f"data:image/png;base64,{qr_code}",
            "secret": TwoFactorAuthService.format_secret_for_display(secret),
            "secret_raw": secret,
            "otpauth_uri": otpauth_uri,
            "backup_codes": backup_codes,
            "message": "Scan the QR code, or tap to add it on this device, then verify with a code"
        }
    
    @staticmethod
    def setup_complete() -> dict:
        """Response for successful 2FA setup"""
        return {
            "status": "enabled",
            "message": "Two-factor authentication has been successfully enabled"
        }
    
    @staticmethod
    def verification_required(partial_token: str) -> dict:
        """Response when 2FA verification is needed"""
        return {
            "status": "2fa_required",
            "partial_token": partial_token,
            "message": "Please enter your 2FA code to complete login"
        }
    
    @staticmethod
    def disabled() -> dict:
        """Response for successful 2FA disable"""
        return {
            "status": "disabled",
            "message": "Two-factor authentication has been disabled"
        }
    
    @staticmethod
    def error(message: str) -> dict:
        """Response for 2FA errors"""
        return {
            "status": "error",
            "message": message
        }
