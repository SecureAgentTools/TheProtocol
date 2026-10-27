"""
Extended Token schema to support 2FA flow
"""

from pydantic import BaseModel, Field
from typing import Optional, Literal

class TokenWithTwoFactor(BaseModel):
    """Extended Token schema that supports 2FA flow"""
    access_token: str = Field(..., description="JWT access token (empty string if 2FA required)")
    token_type: Literal["bearer"] = "bearer"
    expires_in: Optional[int] = Field(None, description="Token expiration time in seconds")
    refresh_token: Optional[str] = Field(None, description="Refresh token for obtaining new access tokens")
    
    # 2FA specific fields
    requires_2fa: Optional[bool] = Field(None, description="Whether 2FA verification is required")
    partial_token: Optional[str] = Field(None, description="Partial token for 2FA validation")
    developer_id: Optional[int] = Field(None, description="Developer ID for 2FA session")
    message: Optional[str] = Field(None, description="Status message")

    # PUSH LOGIN (2026-07-25): the password was correct, but this account requires an approval
    # from its enrolled phone. No access token is issued until that approval is redeemed.
    requires_push_approval: Optional[bool] = Field(None, description="Whether phone approval is required")
    approval_id: Optional[str] = Field(None, description="Push-login approval to poll/redeem")
    approval_expires_in: Optional[int] = Field(None, description="Seconds until the approval expires")

    # Operator bootstrap — force password change
    must_change_password: Optional[bool] = Field(None, description="Whether the developer must change their password before admin operations")
