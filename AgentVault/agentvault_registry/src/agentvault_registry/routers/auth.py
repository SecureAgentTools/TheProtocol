import logging
import secrets
from datetime import datetime, timedelta, timezone
# --- MODIFIED: Added Dict ---
from typing import List, Optional, Annotated, Dict
# --- END MODIFIED ---
import httpx  # For TEG Layer communication
from ..es_ssl_helper import get_httpx_verify


# --- MODIFIED: Added BackgroundTasks, Query, Response, JSONResponse ---
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks, Body, Query, Response # Added Response, BackgroundTasks
from fastapi.responses import RedirectResponse, JSONResponse # Added JSONResponse
# --- END MODIFIED ---
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

# Local imports
from agentvault_registry import schemas, models, security
from agentvault_registry.models import Developer
from agentvault_registry.database import get_db
from agentvault_registry.crud import developer as developer_crud # Use alias
from agentvault_registry.crud import agent as agent_crud # For agent authentication
# --- MODIFIED: Import send_verification_email ---
from agentvault_registry.email_utils import send_verification_email, send_password_reset_email # Added send_verification_email
# --- END MODIFIED ---
# --- ADDED: Import settings ---
from agentvault_registry.config import settings
# --- END ADDED ---


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/auth", # Set prefix for all routes in this file
    tags=["Authentication"]
)

# --- TEG Integration Helper ---
async def initialize_teg_account(developer_email: str, developer_id: int):
    """Initialize TEG account for newly verified developer"""
    from agentvault_registry.identifiers import developer_teg_did
    try:
        # Canonical developer wallet DID — single source of truth shared with all
        # developer-initiated TEG ops (identifiers.developer_teg_did). Previously
        # built did:theprotocol:{developer_id} → a phantom, never-used account.
        agent_id = developer_teg_did(developer_email)
        
        # Get TEG admin API key from settings
        teg_admin_key = settings.TEG_ADMIN_API_KEY
        teg_base_url = getattr(settings, 'TEG_API_BASE_URL', 'http://localhost:8001')
        
        async with httpx.AsyncClient(verify=get_httpx_verify()) as client:
            response = await client.post(
                f"{teg_base_url}/api/v1/agent/initialize-teg-account",
                json={
                    "agent_id": agent_id,
                    "initial_balance": "0",
                    "initial_reputation_score": 0
                },
                headers={
                    "Authorization": f"Bearer {teg_admin_key}",
                    "Content-Type": "application/json"
                },
                timeout=10.0
            )
            
            if response.status_code in [200, 409]:  # 409 means already exists, which is fine
                logger.info(f"TEG account initialized for developer {developer_email} (DID: {agent_id})")
                return True
            else:
                logger.error(f"Failed to initialize TEG account: {response.status_code} - {response.text}")
                return False
                
    except Exception as e:
        logger.error(f"Error initializing TEG account for {developer_email}: {e}")
        return False

# --- Profile Endpoint ---
@router.get("/profile", response_model=schemas.DeveloperProfile, summary="Get Current User Profile")
async def get_profile(
    current_developer: Developer = Depends(security.get_current_developer),
    db: AsyncSession = Depends(get_db)
):
    """
    Get the profile of the currently authenticated developer.
    """
    return schemas.DeveloperProfile(
        id=current_developer.id,
        name=current_developer.name,
        email=current_developer.email,
        organization=None,  # Not in the model yet
        role="admin" if current_developer.is_admin else "developer",  # Fix 1 (2026-04-21): was hardcoded commander email, now uses is_admin flag
        is_verified=current_developer.is_verified,
        is_admin=current_developer.is_admin,  # Added is_admin field
        created_at=current_developer.created_at
    )

@router.post(
    "/register",
    # --- MODIFIED: Changed back to 201 success, updated responses ---
    response_model=schemas.RegistrationResponse,
    status_code=status.HTTP_201_CREATED, # Back to 201
    summary="Register a new developer account",
    responses={
        status.HTTP_201_CREATED: {"description": "Registration successful, verification email sent."},
        status.HTTP_400_BAD_REQUEST: {"description": "Email already registered."},
        status.HTTP_409_CONFLICT: {"description": "Username (developer name) already exists."},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "Email service not configured."},
    }
    # --- END MODIFIED ---
)
async def register_developer(
    # --- MODIFIED: Parameters are used again ---
    background_tasks: BackgroundTasks,
    developer_in: schemas.DeveloperCreate = Body(...),
    db: AsyncSession = Depends(get_db)
    # --- END MODIFIED ---
):
    """
    Handles new developer registration. Creates account, generates keys, sends verification email.
    """
    # --- REMOVED: Temporary Disabling Logic ---
    # logger.warning("Registration endpoint called while temporarily disabled.")
    # raise HTTPException(
    #     status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
    #     detail="Registration is temporarily disabled pending email service activation. Please check back later."
    # )
    # --- END REMOVED ---

    # --- Reinstated Original Logic ---
    logger.info(f"Registration attempt for email: {developer_in.email}")
    existing_developer = await developer_crud.get_developer_by_email(db, email=developer_in.email)
    if existing_developer:
        logger.warning(f"Registration failed: Email '{developer_in.email}' already registered.")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered.",
        )

    try:
        # CRUD function handles hashing, token generation, recovery keys
        created_developer = await developer_crud.create_developer(db=db, developer=developer_in)
        plain_recovery_keys = getattr(created_developer, '_plain_recovery_keys', []) # Retrieve keys set by CRUD

        # Send verification email in the background
        # --- ADDED: Check if email sending is configured ---
        if settings.MAIL_SERVER and settings.MAIL_USERNAME and settings.MAIL_FROM:
            background_tasks.add_task(
                send_verification_email,
                to_email=created_developer.email,
                username=created_developer.name,
                token=created_developer.email_verification_token
            )
            message = "Registration successful. Please check your email to verify your account."
        else:
            logger.warning("Email settings not configured. Skipping verification email sending.")
            # Add instructions for manual verification if needed (e.g., admin action or different flow)
            message = "Registration successful (email verification skipped due to server config). Contact admin if needed."
        # --- END ADDED ---

        return schemas.RegistrationResponse(
            message=message,
            recovery_keys=plain_recovery_keys
        )

    except IntegrityError: # Catch potential name conflict from DB
        await db.rollback()
        logger.warning(f"Registration failed: Username (developer name) '{developer_in.name}' likely already exists.")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, # Use 409 Conflict
            detail="Username or email already exists.",
        )
    except Exception as e:
        await db.rollback() # Ensure rollback on any other error during creation
        logger.exception(f"Unexpected error during registration for email {developer_in.email}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred during registration.",
        )
    # --- End Reinstated Original Logic ---


@router.post("/login", summary="Developer Login")
async def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: AsyncSession = Depends(get_db)
):
    """
    Handles developer login using email and password (OAuth2 Password Flow).
    If 2FA is enabled, returns a partial token for 2FA validation.
    Otherwise, returns a JWT access token.
    """
    logger.info(f"Login attempt for user: {form_data.username}") # username field holds email
    developer = await developer_crud.get_developer_by_email(db, email=form_data.username)

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Incorrect email or password",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if not developer:
        logger.warning(f"Login failed: Developer not found for email {form_data.username}")
        raise credentials_exception

    # --- MODIFIED: Allow login even if not verified, but maybe add warning? ---
    # We need login to work so users can potentially resend verification later if needed.
    # Let's remove the strict verification check *during login* for now.
    # if not developer.is_verified:
    #      logger.warning(f"Login failed: Developer email {form_data.username} not verified.")
    #      # Provide slightly different message for unverified user for better UX, but still 401
    #      raise HTTPException(
    #         status_code=status.HTTP_401_UNAUTHORIZED, # Still 401, but different detail
    #         detail="Email address not verified. Please check your inbox.",
    #         headers={"WWW-Authenticate": "Bearer"},
    #     )
    # --- END MODIFIED ---


    if not security.verify_password(form_data.password, developer.hashed_password):
        logger.warning(f"Login failed: Invalid password for email {form_data.username}")
        raise credentials_exception

    # Password is valid, check if 2FA is enabled
    if developer.two_fa_enabled:
        # Import TwoFactorAuthService
        from agentvault_registry.services import TwoFactorAuthService, TwoFactorResponse
        
        # Generate partial token for 2FA flow
        partial_token = TwoFactorAuthService.generate_partial_token(developer.id)
        logger.info(f"2FA required for developer ID: {developer.id}")
        
        # Return 2FA challenge response
        return TwoFactorResponse.verification_required(partial_token)
    
    # No 2FA, create full JWT
    access_token_expires = timedelta(minutes=security.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = security.create_access_token(
        data={"sub": str(developer.id)}, expires_delta=access_token_expires
    )
    logger.info(f"Login successful for developer ID: {developer.id}")
    return schemas.Token(access_token=access_token, token_type="bearer")

# --- Logout Endpoint ---
@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Logout")
async def logout():
    """
    Logout endpoint for consistency.
    
    Since we're using JWT tokens, there's no server-side session to invalidate.
    The client should remove the token from local storage.
    This endpoint exists mainly for API consistency and future extensions.
    """
    logger.info("Logout endpoint called")
    # In a JWT-based system, logout is typically handled client-side
    # by removing the token from storage. This endpoint exists for:
    # 1. API consistency
    # 2. Future extensions (e.g., token blacklisting)
    # 3. Logging/auditing purposes
    return Response(status_code=status.HTTP_204_NO_CONTENT)

# --- Email Verification Endpoint ---
@router.get("/verify-email", summary="Verify Email Address", response_description="Email verification status", response_model=Dict[str, str])
async def verify_email(token: str = Query(...), db: AsyncSession = Depends(get_db)):
    """Handles the email verification link clicked by the user."""
    logger.info(f"Received email verification request with token prefix: {token[:6]}...")
    developer = await developer_crud.get_developer_by_verification_token(db, token=token)

    error_msg = "Invalid or expired verification token."
    if not developer:
        logger.warning(f"Verification failed: Token not found.")
        # --- MODIFIED: Redirect on failure ---
        # raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error_msg)
        return RedirectResponse(url="/ui/verify-failed", status_code=status.HTTP_303_SEE_OTHER)
        # --- END MODIFIED ---

    if developer.is_verified:
        logger.info(f"Email '{developer.email}' already verified.")
        # --- MODIFIED: Redirect on success (already verified) ---
        # return JSONResponse(content={"status": "already_verified"})
        return RedirectResponse(url="/ui/verify-success?status=already_verified", status_code=status.HTTP_303_SEE_OTHER)
        # --- END MODIFIED ---


    if developer.verification_token_expires is None or developer.verification_token_expires < datetime.now(timezone.utc):
        logger.warning(f"Verification failed: Token expired for email {developer.email}.")
        # Optionally allow resending verification?
        # --- MODIFIED: Redirect on failure ---
        # raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error_msg)
        return RedirectResponse(url="/ui/verify-failed?reason=expired", status_code=status.HTTP_303_SEE_OTHER)
        # --- END MODIFIED ---

    # Token is valid, mark as verified
    developer.is_verified = True
    developer.email_verification_token = None
    developer.verification_token_expires = None
    try:
        db.add(developer)
        await db.flush()
        # §R55: the flag lives in a ROW; the peers only re-pull the CARDS. Touch them.
        from agentvault_registry.services.card_touch import touch_developer_native_cards
        await touch_developer_native_cards(db, developer.id, reason="email verified (legacy route)")
        await db.commit()
        logger.info(f"Email successfully verified for developer: {developer.email} (ID: {developer.id})")
        
        # Initialize TEG account for the newly verified developer
        teg_initialized = await initialize_teg_account(developer.email, developer.id)
        if not teg_initialized:
            logger.warning(f"TEG account initialization failed for {developer.email}, but email verification succeeded")
        
        # --- MODIFIED: Redirect on success ---
        # return JSONResponse(content={"status": "verified"})
        return RedirectResponse(url="/ui/verify-success", status_code=status.HTTP_303_SEE_OTHER)
        # --- END MODIFIED ---
    except Exception as e:
        await db.rollback()
        logger.exception(f"Database error during email verification for {developer.email}")
        # --- MODIFIED: Redirect on failure ---
        # raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update verification status.")
        return RedirectResponse(url="/ui/verify-failed?reason=dberror", status_code=status.HTTP_303_SEE_OTHER)
        # --- END MODIFIED ---

# --- Recovery Key Flow Endpoints ---
@router.post("/recover-account", response_model=schemas.Token, summary="Recover Account via Recovery Key")
async def recover_account_with_key(
    recover_in: schemas.PasswordResetRecover,
    db: AsyncSession = Depends(get_db)
):
    """
    Verifies email and recovery key, returns a short-lived token for setting a new password.
    """
    logger.info(f"Account recovery attempt for email: {recover_in.email}")
    developer = await developer_crud.get_developer_by_email(db, email=recover_in.email)

    error_exception = HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Invalid email or recovery key.",
    )

    if not developer or not developer.is_verified:
        logger.warning(f"Recovery failed: Developer not found or not verified for email {recover_in.email}.")
        raise error_exception # Don't reveal which part failed

    if not developer.hashed_recovery_key:
        logger.error(f"Recovery failed: Developer {developer.id} has no recovery key hash stored.")
        raise error_exception # Should not happen if generated on registration

    if not security.verify_recovery_key(recover_in.recovery_key, developer.hashed_recovery_key):
        logger.warning(f"Recovery failed: Invalid recovery key provided for developer {developer.id}.")
        raise error_exception

    # Recovery key is valid, issue temporary password-set token
    temp_token_expires = timedelta(minutes=5) # Short expiry
    temp_token = security.create_access_token(
        data={"sub": str(developer.id), "purpose": "password-set"},
        expires_delta=temp_token_expires
    )
    logger.info(f"Recovery key verified for developer {developer.id}. Issuing temporary password-set token.")
    return schemas.Token(access_token=temp_token, token_type="bearer")


@router.post("/set-new-password", summary="Set New Password After Recovery", response_model=Dict[str, str])
async def set_new_password_after_recovery(
    set_in: schemas.PasswordSetNew = Body(...), # Keep embed=True if needed, or remove if not
    # Dependencies last
    db: AsyncSession = Depends(get_db),
    developer_id: int = Depends(security.verify_temp_password_token)
):
    """
    Sets a new password using the temporary token obtained via recovery key flow.
    Invalidates the used recovery key hash.
    Expects the request body to be: {"new_password": "..."}
    """
    logger.info(f"Setting new password for developer ID: {developer_id} after recovery.")
    developer = await developer_crud.get_developer_by_id(db, developer_id=developer_id)
    if not developer:
        # Should not happen if token was valid, but check defensively
        logger.error(f"Set new password failed: Developer {developer_id} not found after token verification.")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Developer not found.")

    # --- FIXED: Extract plain string from SecretStr before hashing ---
    new_hashed_password = security.hash_password(set_in.new_password.get_secret_value())
    # --- END FIXED ---

    # Update password and invalidate recovery key hash
    developer.hashed_password = new_hashed_password
    developer.hashed_recovery_key = None # Invalidate recovery key after use
    developer.updated_at = datetime.now(timezone.utc)

    try:
        db.add(developer)
        await db.commit()
        logger.info(f"Successfully set new password and invalidated recovery key for developer {developer_id}.")
        return {"message": "Password updated successfully."}
    except Exception as e:
        await db.rollback()
        logger.exception(f"Database error setting new password for developer {developer_id}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update password.")


# --- Placeholder for Email Password Reset Endpoints ---
# @router.post("/request-password-reset") ...
# @router.post("/reset-password") ...


# --- ADDED: Agent OAuth 2.0 Token Endpoint ---
@router.post(
    "/agent/token",
    response_model=schemas.Token,
    summary="Agent Token (OAuth2 Client Credentials)",
    responses={
        status.HTTP_200_OK: {"description": "Successful authentication, returns access token."},
        status.HTTP_401_UNAUTHORIZED: {"description": "Invalid client credentials."},
    }
)
async def agent_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db)
):
    """
    OAuth 2.0 Client Credentials flow for agents.
    
    Agents authenticate using their client_id (as username) and client_secret (as password).
    Returns a JWT access token containing the agent's DID in the 'sub' claim.
    
    Note: Using OAuth2PasswordRequestForm for compatibility, but interpreting fields as:
    - username: client_id
    - password: client_secret
    """
    logger.info(f"Agent token request for client_id: {form_data.username}")
    
    # Verify agent credentials
    agent = await agent_crud.verify_agent_credentials(
        db=db,
        client_id=form_data.username,  # username field holds client_id
        client_secret=form_data.password  # password field holds client_secret
    )
    
    if not agent:
        logger.warning(f"Agent authentication failed for client_id: {form_data.username}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid client credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Create JWT with agent's DID as subject
    access_token_expires = timedelta(minutes=security.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = security.create_access_token(
        data=security.agent_token_claims(agent),   # D6-281: bound to the credential (`cv`)
        expires_delta=access_token_expires
    )
    
    logger.info(f"Agent authentication successful for DID: {agent.did} (client_id: {agent.client_id})")
    return schemas.Token(access_token=access_token, token_type="bearer")
# --- END ADDED ---
