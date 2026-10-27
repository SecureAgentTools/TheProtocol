"""API endpoints for agent onboarding protocol."""
import re
import secrets
import asyncio
import hashlib
import os
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Dict, Any, List
from urllib.parse import urlparse
from fastapi import APIRouter, Depends, HTTPException, Header, Path, Body, status, Request
from pydantic import BaseModel, Field, AnyHttpUrl, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
import httpx
from ..es_ssl_helper import get_httpx_verify
import logging

from ..database import get_db
from .. import models, security
from ..models import Developer, OrganizationMember, Organization
from ..crud import bootstrap_token as bootstrap_crud
from ..crud import agent as agent_crud
from ..security import get_current_developer_unified
from ..config import settings
from ..core.network_profile import money_knob  # §MONEY-M2: the profile owns the floor
from ..event_emitter import get_event_emitter
from ..services import stepup
from fastapi.responses import JSONResponse

# OWL20-PREP: Event Store integration for onboarding audit trail
event_emitter = get_event_emitter()

router = APIRouter(prefix="/onboard", tags=["Onboarding"])

# Initialize rate limiter
# §RATEFIX: THE shared, Redis-backed limiter — the same object main.py puts on
# app.state, so these decorations are both enforced and shared across workers.
# A router-local Limiter() would be in-memory per worker AND invisible to the
# middleware; that is what made all 65 limits here meaningless.
from agentvault_registry.middleware.rate_limiter import shared_limiter as limiter
from agentvault_registry.core.card_stub import STUB_CARD_DESCRIPTION
from agentvault_registry.core.public_url import credential_home_url  # §FEFRAME W1

# Initialize logger
logger = logging.getLogger(__name__)

# ── §MONEY-M2 / R14 (2026-09-04): the genesis-grant treasury floor ──────────
# The grant is treasury-funded through the reward waterfall, and the waterfall
# is honest about running dry: it commits the legs it can and reports `partial`.
# What it cannot do is DECLINE. On today's ~1e9 supply that is fine; on a
# network whose whole supply is a few hundred thousand units, a burst of
# registrations empties the treasury one complete grant at a time, and the
# first person to find an empty treasury gets a `partial` grant — a worse
# outcome than being told the network is full.
#
# So: a floor. Below it the grant does not run at all and the status is
# `deferred` — not `failed`, because nothing failed.
#
# Default 0 ⇒ the check is skipped entirely ⇒ byte-inert on every node that has
# not opted in. The value belongs to the network profile (config/), never to a
# literal here.
try:
    from prometheus_client import Counter as _M2Counter
    GENESIS_GRANT_DEFERRED = _M2Counter(
        "registry_genesis_grant_deferred_total",
        "Genesis grants not funded because of the treasury floor",
        ["reason"],
    )
except Exception:  # noqa: BLE001 — metrics never break the money path
    GENESIS_GRANT_DEFERRED = None


def _count_deferral(reason: str) -> None:
    if GENESIS_GRANT_DEFERRED is not None:
        try:
            GENESIS_GRANT_DEFERRED.labels(reason=reason).inc()
        except Exception:  # noqa: BLE001
            pass


# FIXED: Import the enhanced version directly with alias to avoid name collision
try:
    from ..crud_agent_enhanced import create_agent as create_agent_db
    logger.info("🔥 Successfully imported enhanced_create_agent")
except ImportError as e:
    logger.warning(f"⚠️ Failed to import enhanced_create_agent: {e}")
    create_agent_db = agent_crud.create_agent


# --- Request/Response Models ---

class BootstrapTokenRequest(BaseModel):
    """
    Request model for bootstrap token creation.
    
    Used by authenticated developers to request a single-use bootstrap token
    that can be used to onboard a new agent.
    """
    agent_type_hint: Optional[str] = Field(None, description="Hint for the type of agent being created")
    requested_by: Optional[str] = Field(None, description="Identifier for the entity making the request")


class BootstrapTokenResponse(BaseModel):
    """
    Response model for bootstrap token creation.
    
    Contains the newly generated bootstrap token and its expiration information.
    The token must be used before it expires to successfully register an agent.
    """
    bootstrap_token: str = Field(..., description="Single-use bootstrap token")
    expires_in: int = Field(..., description="Token lifetime in seconds")
    expires_at: str = Field(..., description="ISO format expiration timestamp")


class AgentRegistrationRequest(BaseModel):
    """
    Request model for agent registration.
    
    Used by new agents to register themselves using a valid bootstrap token.
    The agent provides its desired DID method and optionally a public key
    and proof-of-work solution.
    """
    agent_did_method: str = Field(..., description="DID method (e.g., 'theprotocol')")
    public_key_jwk: Optional[Dict[str, Any]] = Field(None, description="Agent's public key in JWK format")
    proof_of_work_solution: Optional[str] = Field(None, description="Solution to PoW challenge if required")


class AgentRegistrationResponse(BaseModel):
    """
    Response model for agent registration.

    Contains the newly created agent's DID, OAuth credentials, and status
    information. The client_secret is only shown once and must be stored
    securely by the agent.
    """
    agent_did: str = Field(..., description="Newly created DID for the agent")
    client_id: str = Field(..., description="OAuth client ID for the agent")
    client_secret: str = Field(..., description="OAuth client secret (shown only once)")
    account_status: str = Field(..., description="Status of the agent account")
    initial_funding_status: str = Field(..., description="Status of initial token grant")
    faucet_transaction_id: str = Field(..., description="Transaction ID for faucet funding")


class ResetCredentialsRequest(BaseModel):
    """Request to reset agent OAuth credentials. Requires developer password, and a
    SECOND FACTOR from any developer who has one enrolled (§DISCREFINE)."""
    password: str = Field(..., description="Developer's current password for verification")
    totp_code: Optional[str] = Field(
        None, max_length=16,
        description="Current code from your authenticator app. Required if you have 2FA "
                    "enabled and are not approving this on your phone instead.",
    )
    challenge_id: Optional[str] = Field(
        None, max_length=44,
        description="Id of a step-up challenge you already approved on your phone "
                    "(Pocket → Approvals). Single-use and bound to THIS agent.",
    )


class ResetCredentialsResponse(BaseModel):
    """New agent credentials. The client_secret is shown ONCE — store it securely."""
    agent_did: str
    client_id: str = Field(..., description="New OAuth client ID")
    client_secret: str = Field(..., description="New OAuth client secret (shown only once)")
    previous_client_id: str = Field(..., description="Old client ID (now invalidated)")
    status: str
    warning: str
    # §FEFRAME W1: the credential's home (core/public_url.credential_home_url)
    registry_url: Optional[str] = Field(None, description="The registry where these credentials are used")


# --- Helper Functions ---

# §DIDWIDEN (2026-09-06): the generator lives in identifiers.py (ONE rule for every
# fresh agent DID: create_agent, spawn, fiat onramp, bundle restore, clone). The name
# stays importable from here; the shape is a full uuid4 (122 random bits) instead of
# the 80-bit token_hex 8-4-4-4 that every DID minted before this date carries. Both
# shapes stay valid forever — a DID is an opaque string, nothing parses the suffix.
from ..identifiers import generate_agent_did, generate_local_agent_did  # noqa: E402  (re-export, keep the name)

try:
    from prometheus_client import Counter as _DidCounter
    DID_MINT_REMINT_TOTAL = _DidCounter(
        "registry_did_mint_remint_total",
        "Fresh agent DIDs re-minted because the candidate was already held locally "
        "(agents.did or a mirrored agent_cards.agent_did) — the mint-time collision net (§DIDWIDEN)",
        ["site"],
    )
except Exception:  # noqa: BLE001 — metrics never break onboarding
    DID_MINT_REMINT_TOTAL = None


def _count_remint(site: str) -> None:
    if DID_MINT_REMINT_TOTAL is not None:
        try:
            DID_MINT_REMINT_TOTAL.labels(site=site).inc()
        except Exception:  # noqa: BLE001
            pass


class DidMintCollision(RuntimeError):
    """Every candidate DID was already held locally — a broken RNG, not bad luck (2^-122 each)."""


DID_MINT_MAX_ATTEMPTS = 3


async def did_is_taken(db: AsyncSession, did: str) -> bool:
    """True when ANY local row already holds this DID.

    Two tables, because a mirror of a FOREIGN agent occupies agent_cards.agent_did
    (uix_agent_cards_agent_did) without an agents row: a native mint that collided
    with a mirrored foreign DID used to pass the agents insert and then die on the
    card link, leaving a half-made agent. That cross-frame case is the one this
    net exists for.
    """
    hit = (await db.execute(
        select(models.Agent.id).where(models.Agent.did == did).limit(1)
    )).first()
    if hit is not None:
        return True
    hit = (await db.execute(
        select(models.AgentCard.id).where(models.AgentCard.agent_did == did).limit(1)
    )).first()
    return hit is not None


async def mint_unique_agent_did(
    db: AsyncSession,
    did_method: str = "theprotocol",
    *,
    site: str = "create_agent",
    max_attempts: int = DID_MINT_MAX_ATTEMPTS,
) -> str:
    """Mint a DID that no local row holds; re-mint (counted, WARN) on a hit.

    ValueError (unsupported method) propagates unchanged — the 400 depends on it.
    The unique index on agents.did / agent_cards.agent_did stays the last word
    for the concurrent race; this is the pre-check that turns a 500 into a retry.
    """
    for attempt in range(1, max_attempts + 1):
        candidate = generate_local_agent_did(did_method)  # item 1: under this registry's issuer when set
        if not await did_is_taken(db, candidate):
            return candidate
        _count_remint(site)
        logger.warning(
            "[DID-MINT] candidate %s is already held locally (attempt %d/%d, site=%s) — re-minting",
            candidate, attempt, max_attempts, site,
        )
    raise DidMintCollision(
        f"{max_attempts} consecutive DID candidates were already held locally (site={site}); "
        "the random source is suspect — refusing to mint"
    )


def generate_client_credentials() -> tuple[str, str]:
    """
    Generate OAuth client credentials for an agent.
    
    Creates a unique client ID and a cryptographically secure client secret
    for use in OAuth 2.0 Client Credentials flow.
    
    Returns:
        tuple[str, str]: A tuple containing (client_id, client_secret)
        
    Example:
        >>> client_id, client_secret = generate_client_credentials()
        >>> print(client_id)  # 'agent-1234abcd5678efgh'
        >>> print(client_secret)  # 'tp_secret_<64-char-hex>'
    """
    client_id = f"agent-{secrets.token_hex(8)}"
    client_secret = f"tp_secret_{secrets.token_hex(32)}"
    return client_id, client_secret


def _leading_zero_bits(digest: bytes) -> int:
    """Count leading zero bits of a hash digest."""
    bits = 0
    for byte in digest:
        if byte == 0:
            bits += 8
            continue
        bits += 8 - byte.bit_length()
        break
    return bits


def validate_proof_of_work(solution: Optional[str]) -> bool:
    """
    Validate a stateless proof-of-work solution.

    Expected format: ``v1:{unix_ts}:{payload}:{nonce}`` where
      - sha256 over the FULL solution string has at least POW_DIFFICULTY_BITS
        (default 20) leading zero bits,
      - ``unix_ts`` is within POW_MAX_AGE_SECONDS (default 600) of server time
        (bounds the replay window; small forward clock skew tolerated).
    The payload is free-form; clients SHOULD use the agent host/name they are
    onboarding (a future version may bind it server-side).

    The field is optional unless POW_REQUIRED=true — absence is handled by the
    caller; this validates only non-empty solutions.
    """
    if not solution:
        return False
    try:
        version, ts_raw, _payload, _nonce = solution.split(":", 3)
        if version != "v1":
            return False
        ts = int(ts_raw)
    except (ValueError, AttributeError):
        return False
    max_age = int(os.getenv("POW_MAX_AGE_SECONDS", "600"))
    now = int(time.time())
    if not (now - max_age) <= ts <= (now + 120):
        return False
    difficulty = int(os.getenv("POW_DIFFICULTY_BITS", "20"))
    digest = hashlib.sha256(solution.encode("utf-8")).digest()
    return _leading_zero_bits(digest) >= difficulty


async def count_developer_agents(db: AsyncSession, developer_id: int) -> int:
    """
    Count total agents owned by a developer.
    
    Used to determine if an agent is the developer's first (eligible for genesis grant).
    """
    from sqlalchemy import select, func
    result = await db.execute(
        select(func.count()).select_from(models.Agent).where(
            models.Agent.creator_developer_id == developer_id
        )
    )
    return result.scalar_one()


async def org_agent_limit_reached(db: AsyncSession, org_id: str) -> bool:
    """§DOCSFIX D6-501 (2026-10-16): True when the organization holds as many agents as its `limits.max_agents`
    allows (100 when unset), the cap POST /organizations/{org_id}/agents/{agent_did}/assign enforces. The
    auto-assignment below asks it too: it filled a full organization past its limit."""
    from sqlalchemy import func
    limits = (await db.execute(
        select(Organization.limits).where(Organization.id == org_id)
    )).scalar_one_or_none()
    count = (await db.execute(
        select(func.count()).select_from(models.Agent).where(models.Agent.organization_id == org_id)
    )).scalar() or 0
    return count >= int(((limits or {}).get("max_agents") or 100))


async def _owe_genesis_grant(agent_did: str, amount, err: Exception, fallback: str) -> tuple[str, str]:
    """§LEDGERGATE (V0598): a grant the TEG could not pay is OWED, not lost. It goes into genesis_grants_owed (migration
    0188), which background_tasks/genesis_grant_retry pays with this creation's own idempotency key once the ledger
    records again, and the creation answers `deferred`. Its own short transaction (the caller's session is the agent's
    creation); if even that cannot be written, the old answer (`failed`), loudly: the grant is then lost unless granted
    by hand."""
    from agentvault_registry.services.ledger_unavailable import refusal_from_error
    reason = "ledger_unavailable" if refusal_from_error(err) is not None else "teg_error"
    try:
        from sqlalchemy.dialects.postgresql import insert as _pg_insert
        from ..database import get_db_context
        async with get_db_context() as odb:
            await odb.execute(_pg_insert(models.GenesisGrantOwed).values(
                agent_did=agent_did, amount=Decimal(str(amount)), reason=reason,
                last_error=f"{type(err).__name__}: {err}"[:500],
            ).on_conflict_do_nothing(index_elements=["agent_did"]))
            await odb.commit()
    except Exception as oe:  # noqa: BLE001 — the owed record must never break the creation
        logger.error("[genesis-owed] could not record the owed grant of %s (%s): it is LOST unless granted by hand",
                     agent_did, oe)
        return "failed", f"{fallback}_{secrets.token_hex(8)}"
    logger.warning("[genesis-owed] the grant of %s is owed (%s): genesis_grant_retry pays it once the ledger records",
                   agent_did, reason)
    return "deferred", f"deferred_{reason}"


async def mint_genesis_grant(agent_did: str, db=None) -> tuple[str, str]:
    """
    Phase 2 (2026-05-08): Fund genesis grant via the reward waterfall.
    §REWARDEVENTS (2026-08-11): rides the shared reward-funding rail —
    deterministic Idempotency-Key genesis-{agent_did} (a retried create can
    never double-grant), one TokensTransferred per waterfall leg, and the
    registry balance cache synced from TEG truth on completed AND exhausted
    (the TEG commits partial legs by documented design; this caller now
    honors its "caller must reconcile" contract instead of recording
    treasury_failed over committed money — the §FUNNELSMOKE frame-b drain).

    Waterfall source order stays a per-reason TEG policy
    (reward_funding_waterfall system_config); nothing here assumes which
    sources contributed.

    Returns:
        tuple: (funding_status, transaction_id)
        funding_status: completed | partial | failed
    """
    grant_amount = getattr(settings, 'GENESIS_GRANT_AMOUNT', '1000.0')

    from ..services.reward_funding import fund_reward_via_waterfall
    from ..teg_client import TEGClientError

    # §MONEY-M2 / R14 — the treasury floor. 0 (the default) skips this entirely.
    floor = money_knob("GENESIS_GRANT_TREASURY_FLOOR", "0")
    if floor > 0:
        try:
            from ..teg_client import get_teg_client
            _info = await get_teg_client().get_treasury_info()
            treasury = Decimal(str(_info.get("treasury_balance", "0")))
        except Exception as e:  # noqa: BLE001 — TEGClientError and connection class
            # THREE states, not two. "Could not read the treasury" is neither
            # above the floor nor below it, and collapsing it into either is a
            # lie. Fail OPEN — a transient TEG read must never stop a person's
            # first agent — but say so at ERROR and count it, because a guard
            # whose failures are invisible is not a guard.
            logger.error(
                "[genesis-floor] treasury unreadable (%s) — granting anyway; "
                "the floor could NOT be enforced for %s", e, agent_did
            )
            _count_deferral("floor_unreadable")
        else:
            remaining = treasury - Decimal(str(grant_amount))
            if remaining < floor:
                logger.warning(
                    "[genesis-floor] DEFERRED for %s: treasury %s - grant %s = %s, "
                    "below the floor %s", agent_did, treasury, grant_amount, remaining, floor
                )
                _count_deferral("below_floor")
                return "deferred", "deferred_treasury_floor"
            logger.info(
                "[genesis-floor] ok for %s: treasury %s leaves %s above the floor %s",
                agent_did, treasury, remaining, floor
            )
    try:
        res = await fund_reward_via_waterfall(
            db,
            target_agent_did=agent_did,
            amount=grant_amount,
            reason="genesis_grant",
            reference_id=f"onboard-{agent_did}",
            idempotency_key=f"genesis-{agent_did}",
        )
    except TEGClientError as e:
        logger.error(f"Genesis grant failed for {agent_did}: {e}")
        return await _owe_genesis_grant(agent_did, grant_amount, e, "treasury_failed")
    except Exception as e:  # noqa: BLE001 — connection-class failures
        logger.error(f"Genesis grant connection error for {agent_did}: {e}")
        return await _owe_genesis_grant(agent_did, grant_amount, e, "treasury_error")

    if db is not None:
        # Persist the cache sync (the helper mutates, never commits).
        await db.commit()

    tx_id = res["first_transaction_id"] or "unknown"
    if res["status"] == "completed":
        logger.info(
            f"Genesis grant of {grant_amount} AVT funded for {agent_did} "
            f"(tx: {tx_id}, funded_via: {[l.get('source') for l in res['legs']]}, "
            f"events: {res['events_emitted']})"
        )
        return "completed", tx_id
    # Exhausted: partial legs are committed + emitted + synced — say so.
    logger.error(
        f"Genesis grant PARTIAL for {agent_did}: funded {res['funded_amount']} "
        f"of {grant_amount} (shortfall {res['shortfall']}) — legs committed, "
        f"events emitted, balance synced"
    )
    return "partial", tx_id


async def create_teg_profile_for_agent(agent_did: str) -> None:
    """
    Create a TEG profile for a newly registered agent.
    
    This function makes a server-to-server call to the TEG Layer's internal
    API to create an economic profile for the agent. This ensures the agent
    can participate in the token economy immediately after registration.
    
    Args:
        agent_did: The DID of the newly registered agent
        
    Raises:
        Exception: If the TEG profile creation fails
    """
    # Get TEG API configuration from settings
    # FIXED: Use correct TEG Layer container hostname instead of localhost
    teg_api_base_url = getattr(settings, 'TEG_API_BASE_URL', 'http://teg-layer:8080')
    # FIXED: Use the correct admin API key as defined in docker-compose.yml
    teg_admin_api_key = settings.TEG_ADMIN_API_KEY
    
    async with httpx.AsyncClient(verify=get_httpx_verify()) as client:
        try:
            response = await client.post(
                f"{teg_api_base_url}/api/v1/internal/create-agent-profile",
                json={"agent_did": agent_did},
                headers={
                    "Authorization": f"Bearer {teg_admin_api_key}"
                },
                timeout=10.0
            )
            
            if response.status_code not in [200, 201]:
                # Log the error for debugging
                error_detail = response.text
                try:
                    error_data = response.json()
                    error_detail = error_data.get("detail", error_detail)
                except:
                    pass
                raise Exception(f"TEG profile creation failed: {response.status_code} - {error_detail}")
                
        except httpx.RequestError as e:
            raise Exception(f"TEG API connection error: {e}")


# --- API Endpoints ---

@router.get("/agent-card-template", summary="Example Agent Card (copy-paste starting point)")
async def agent_card_template():
    """
    Return a complete, VALID example Agent Card to use as the starting point for
    POST /onboard/create_agent. Copy this, edit the fields, and submit the
    `agent_card` (keep `agent_did_method: "theprotocol"`). Every field shown is
    required by the A2A AgentCard schema: omitting any of them returns a 400.
    """
    return {
        "agent_did_method": "theprotocol",
        "agent_card": {
            "protocolVersion": "0.3.0",
            "humanReadableId": "your-org/your-agent",
            "agentVersion": "1.0.0",
            "name": "Your Agent Name",
            "description": "A clear description of what your agent does.",
            "url": "https://your-host.example.com/a2a",
            "provider": {"name": "Your Org", "url": "https://your-org.example.com"},
            "capabilities": {"streaming": False},
            "defaultInputModes": ["text/plain"],
            "defaultOutputModes": ["text/plain"],
            "skills": [
                {"id": "example-skill", "name": "Example Skill",
                 "description": "What this skill does."}
            ],
            "authSchemes": [{"scheme": "none"}],
        },
    }


@router.post("/bootstrap/request-token", response_model=BootstrapTokenResponse)
@limiter.limit("20/minute")  # Beta: 20/min generous for real use. API test runner uses admin (bypasses limits).
async def request_bootstrap_token(
    token_request: BootstrapTokenRequest,
    request: Request,  # Required for rate limiting - parameter must be named 'request'
    current_developer: Developer = Depends(get_current_developer_unified),
    db: AsyncSession = Depends(get_db)
) -> BootstrapTokenResponse:
    """
    Request a single-use bootstrap token for creating a new agent. Requires a verified developer's token (an
    unverified developer gets 403). The bootstrap token expires after `BOOTSTRAP_TOKEN_LIFETIME` seconds (300 by
    default) and is sent as the `Bootstrap-Token` header of POST /api/v1/onboard/create_agent. Rate-limited to 20
    requests a minute.
    """
    # Check if developer is verified
    if not current_developer.is_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only verified developers can request bootstrap tokens"
        )
    
    # Rate limiting is now implemented via the @limiter.limit decorator above
    
    # Create the bootstrap token
    token_lifetime_seconds = settings.BOOTSTRAP_TOKEN_LIFETIME
    
    # D6-283: the row keeps only the token's hash; the plain token is handed out here, once.
    token, plain_token = await bootstrap_crud.create_bootstrap_token(
        db=db,
        creator_developer_id=current_developer.id,
        agent_type_hint=token_request.agent_type_hint,
        requested_by=token_request.requested_by,
        token_lifetime_seconds=token_lifetime_seconds
    )

    # Format the response
    return BootstrapTokenResponse(
        bootstrap_token=plain_token,
        expires_in=token_lifetime_seconds,
        expires_at=token.expires_at.isoformat()
    )


@router.post("/register", response_model=AgentRegistrationResponse, status_code=status.HTTP_410_GONE, deprecated=True)
@limiter.limit("60/minute")
async def register_agent(
    registration_request: AgentRegistrationRequest,
    request: Request,
    bootstrap_token: str = Header(..., alias="Bootstrap-Token"),
    db: AsyncSession = Depends(get_db)
) -> AgentRegistrationResponse:
    """
    [DISABLED] This endpoint has been permanently disabled.

    Use POST /api/v1/onboard/create_agent instead: it creates agents with
    proper Agent Cards (name, description, provider, capabilities).

    Headless agents without discoverable metadata are no longer permitted.
    """
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=(
            "This endpoint has been disabled. Headless agents without Agent Cards "
            "are no longer permitted. Use POST /api/v1/onboard/create_agent instead, "
            "which requires a valid Agent Card with name, description, provider, "
            "and capabilities. See: https://theprotocol.cloud/docs/onboarding"
        ),
    )
    # Dead code removed — endpoint raises 410 GONE above. Use /onboard/create_agent instead.


# --- ADDED: New Unified Agent Creation Endpoint ---
class CreateAgentRequest(BaseModel):
    """
    Request model for unified agent creation.

    Two onboarding paths (mutually exclusive at the request level):

      LEGACY: pass full `agent_card` (the registry stores it verbatim then
              canonicalises). Triggers a deprecation_warning in the response.

      OPTION C (preferred): pass `agent_host` only. The registry creates a
              minimal stub card pointing at the host, returns credentials,
              and the agent_card_pullsync worker pulls the real card from
              `<host>/.well-known/agent-card.json` shortly after.

    Section §pass36 (2026-05-17) — Option C Phase 5a.
    """
    agent_did_method: str = Field(..., description="DID method (e.g., 'theprotocol')")
    public_key_jwk: Optional[Dict[str, Any]] = Field(None, description="Agent's public key in JWK format")
    proof_of_work_solution: Optional[str] = Field(None, description="Solution to PoW challenge if required")
    agent_card: Optional[Dict[str, Any]] = Field(
        None,
        description="LEGACY: Complete Agent Card JSON conforming to A2A schema. Deprecated in favor of agent_host (Option C). Mutually exclusive with agent_host.",
    )
    agent_host: Optional[AnyHttpUrl] = Field(
        None,
        description="OPTION C: Public hostname where the agent will serve /.well-known/agent-card.json. Server builds a stub card; the pull-sync worker populates the real fields once the agent is deployed. Mutually exclusive with agent_card.",
    )

    @model_validator(mode="after")
    def _at_least_one_card_path(self) -> "CreateAgentRequest":
        """At least one of agent_card / agent_host must be set.

        BOTH may be set (AgentForge path): the agent_card content is stored
        verbatim (legacy/UX behaviour), and agent_host is recorded so the
        pull-sync worker knows where to fetch the agent's well-known once
        deployed. The Phase 4 backfill SQL aligns supportedInterfaces[0].url
        to agent_host on stored card_data when both are provided.
        """
        if self.agent_card is None and self.agent_host is None:
            raise ValueError(
                "Provide `agent_card` (legacy), `agent_host` (Option C, preferred), "
                "or both."
            )
        return self


def _slug_from_url(url: str) -> str:
    """Derive a stable human-readable id from a URL host (used for stub cards).

    Example: https://my-agent.theprotocol.cloud/foo → my-agent-theprotocol-cloud
    """
    try:
        p = urlparse(url)
        host = (p.hostname or "agent").lower()
    except Exception:
        host = "agent"
    slug = re.sub(r"[^a-z0-9]+", "-", host).strip("-") or "agent"
    return slug[:60]


def _build_stub_card_data(agent_host: str, provider_name: Optional[str]) -> Dict[str, Any]:
    """Build a minimal v1.0 AgentCard pointing at the agent's well-known host.

    The pull-sync worker (Phase 3) will overwrite agent-owned fields once the
    agent's own `/.well-known/agent-card.json` is reachable. Registry-owned
    fields (federation_metadata, flare) survive the merge.
    """
    host = str(agent_host).rstrip("/")
    slug = _slug_from_url(host)
    return {
        "protocolVersion": "1.0",
        "humanReadableId": slug,
        "agentVersion": "1.0.0",
        "name": slug,
        "description": STUB_CARD_DESCRIPTION,
        "url": host,  # v0.3 alias for backwards-compat
        "preferredTransport": "JSONRPC",
        "supportedInterfaces": [
            {
                "url": host,
                "protocolBinding": "JSONRPC",
                "protocolVersion": "1.0",
            }
        ],
        "securitySchemes": {
            "agent_jwt": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}
        },
        "security": [{"agent_jwt": []}],
        "provider": {"name": provider_name or "Pending"},
        "capabilities": {"streaming": False},
    }


class CreateAgentResponse(BaseModel):
    """
    Response model for unified agent creation.

    Contains both the agent credentials and the created Agent Card information.
    """
    # Agent registration info
    agent_did: str = Field(..., description="Newly created DID for the agent")
    client_id: str = Field(..., description="OAuth client ID for the agent")
    client_secret: str = Field(..., description="OAuth client secret (shown only once)")
    # §FEFRAME W1: the credential's home (core/public_url.credential_home_url)
    registry_url: Optional[str] = Field(None, description="The registry where these credentials are used")
    account_status: str = Field(..., description="Status of the agent account")
    initial_funding_status: str = Field(..., description="Status of initial token grant")
    faucet_transaction_id: str = Field(..., description="Transaction ID for faucet funding")
    # Agent Card info
    agent_card_id: str = Field(..., description="UUID of the created Agent Card")
    agent_card_name: str = Field(..., description="Name from the Agent Card")
    # Q-C W5 (2026-05-12): did-jwt server-issued private key (Commander Q3).
    # Populated ONLY when A2A_DID_JWT_AUTOGEN=true AND caller did NOT supply
    # public_key_jwk. Shown ONCE per Q3 — same lifecycle as client_secret.
    did_jwt_private_key: Optional[str] = Field(
        None,
        description="EdDSA PKCS#8 PEM (Q-C W5 server-generated). Returned only when server auto-generated the keypair; shown ONCE. Use with theprotocol.auth.did_jwt.mint_did_jwt to sign offline JWTs.",
    )
    did_jwt_public_key_jwk: Optional[Dict[str, Any]] = Field(
        None,
        description="EdDSA public JWK persisted on the agent row (server-generated case). Same key advertised by GET /api/v1/agents/{did}/public-key.",
    )
    # §pass36 Option C Phase 5a — set on the new agent_host path so operators
    # know the stub card will be replaced once the agent's well-known is up.
    requires_well_known_fetch: bool = Field(
        False,
        description="True when the agent was registered via `agent_host` (Option C). Indicates the stored card is a stub awaiting pull-sync from the agent's /.well-known/agent-card.json.",
    )
    # §pass36 Option C Phase 5a — surfaced on the legacy agent_card path.
    deprecation_warning: Optional[str] = Field(
        None,
        description="Set when the request used the legacy `agent_card` payload. Migrate to `agent_host` (Option C) for A2A v1.0 §4.1.2 compliance.",
    )
    # §pass47 O1 — organization auto-link result.
    organization_id: Optional[str] = Field(
        None,
        description="The organization the agent was auto-assigned to (developer was a member of exactly one org). NULL when the developer is in zero or multiple orgs, or when that org is at its agent limit (`limits.max_agents`).",
    )
    available_orgs: Optional[List[Dict[str, Any]]] = Field(
        None,
        description="Populated when the developer is a member of >1 organization. Caller should pick one and POST /api/v1/organizations/{org_id}/agents/{agent_did}/assign to finalize.",
    )

@router.post("/create_agent", response_model=CreateAgentResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")  # Beta: nobody creates 10 agents/min legitimately
async def create_agent(
    creation_request: CreateAgentRequest,
    request: Request,
    bootstrap_token: str = Header(..., alias="Bootstrap-Token"),
    db: AsyncSession = Depends(get_db)
) -> CreateAgentResponse:
    """
    Create a new agent with both credentials and Agent Card.
    
    This unified endpoint ensures every agent has discoverable metadata
    by requiring a valid Agent Card at creation time.
    """
    # Validate the bootstrap token
    token = await bootstrap_crud.get_active_bootstrap_token_by_value(db, bootstrap_token)
    
    if not token:
        # Check if token exists but is already used (D6-283: by its hash; no plaintext is stored to compare with)
        existing_token = await bootstrap_crud.get_bootstrap_token_by_value(db, bootstrap_token)

        if existing_token and existing_token.is_used:
            # Token was already used - return 409
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Bootstrap token has already been used"
            )
        else:
            # Token doesn't exist or is expired
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired bootstrap token"
            )
    
    # Proof-of-work: validate whenever provided; require only when POW_REQUIRED=true.
    pow_required = os.getenv("POW_REQUIRED", "false").lower() in ("1", "true", "yes")
    if pow_required and not creation_request.proof_of_work_solution:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "proof_of_work_solution is required by this registry. Format: "
                "'v1:{unix_ts}:{payload}:{nonce}' with sha256(solution) leading zero bits "
                ">= POW_DIFFICULTY_BITS."
            ),
        )
    if creation_request.proof_of_work_solution and not validate_proof_of_work(creation_request.proof_of_work_solution):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid proof-of-work solution"
        )
    
    # Generate agent DID
    try:
        agent_did = await mint_unique_agent_did(db, creation_request.agent_did_method, site="create_agent")
    except DidMintCollision as e:
        logger.error(f"create_agent: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    except ValueError as e:
        logger.warning(f"create_agent: rejected agent_did_method={creation_request.agent_did_method!r}: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{e}. Supported values for agent_did_method: 'theprotocol' (default) or 'cos' (legacy)."
        )
    
    # Generate OAuth credentials
    client_id, client_secret = generate_client_credentials()

    # Import required modules
    from ..crud import agent_card as card_crud
    from .. import schemas

    # ─── §pass36 Option C Phase 5a/5b (2026-05-17) — Inverted bootstrap ─────
    # Three paths, all converge on `card_data_to_persist`:
    #   1. agent_card only (legacy)      → store verbatim, flag deprecation
    #   2. agent_host only (Option C)    → build stub, pull-sync converges later
    #   3. agent_card + agent_host       → AgentForge path: store agent_card
    #                                       verbatim (UX preserved), agent_host
    #                                       drives later pull-sync alignment.
    sent_legacy_card = creation_request.agent_card is not None
    sent_agent_host = creation_request.agent_host is not None
    used_legacy_path = sent_legacy_card and not sent_agent_host
    if sent_legacy_card:
        # If agent_host was also sent, ensure stored card's supportedInterfaces[0].url
        # points at the agent_host (operators usually want this consistent).
        card_data_to_persist = dict(creation_request.agent_card)  # shallow copy
        if sent_agent_host:
            host = str(creation_request.agent_host).rstrip("/")
            iface_list = card_data_to_persist.get("supportedInterfaces") or []
            if iface_list and isinstance(iface_list, list) and isinstance(iface_list[0], dict):
                # Replace only if the existing URL doesn't already point at agent_host.
                if iface_list[0].get("url", "").split("/", 3)[:3] != host.split("/", 3)[:3]:
                    iface_list[0]["url"] = host
                    card_data_to_persist["supportedInterfaces"] = iface_list
            card_data_to_persist["url"] = host  # legacy v0.3 alias too
    else:
        # Resolve provider name from the bootstrap-token's creator developer.
        provider_name: Optional[str] = None
        try:
            dev_row = await db.execute(
                select(Developer).where(Developer.id == token.creator_developer_id)
            )
            dev_obj = dev_row.scalar_one_or_none()
            if dev_obj:
                provider_name = (
                    getattr(dev_obj, "display_name", None) or dev_obj.email.split("@")[0]
                )
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[Option C] provider_name lookup failed (non-fatal): {e}")
        card_data_to_persist = _build_stub_card_data(
            str(creation_request.agent_host),
            provider_name,
        )

    # ─── Q-C W5 (2026-05-12) — did-jwt EdDSA keygen, Commander Q3/Q4 ────────
    # If caller did NOT supply their own public_key_jwk AND env A2A_DID_JWT_AUTOGEN
    # is true, the server generates an Ed25519 keypair, stores the public JWK on
    # the agent row, and returns the PRIVATE PEM in the response ONCE.
    # Also adds the did-jwt-self-signed extension to the agent card so verifiers
    # know to look up the public key via GET /agents/{did}/public-key.
    effective_public_jwk = creation_request.public_key_jwk
    did_jwt_private_pem: Optional[str] = None

    if effective_public_jwk is None:
        try:
            from ..services.a2a_v1.did_jwt import (
                autogen_enabled as _did_jwt_autogen_enabled,
                generate_eddsa_keypair as _generate_eddsa_keypair,
                ensure_did_jwt_extension as _ensure_did_jwt_extension,
            )
            if _did_jwt_autogen_enabled():
                effective_public_jwk, did_jwt_private_pem = _generate_eddsa_keypair()
                # Idempotently add the did-jwt-self-signed extension to the card
                # so peer verifiers know to look up the public key.
                card_data_to_persist = _ensure_did_jwt_extension(card_data_to_persist)
                logger.info(
                    f"[Q-C W5] Server-generated EdDSA keypair for new agent (did pending). "
                    f"Public JWK will be persisted; private key returned ONCE in response."
                )
        except Exception as e:
            logger.warning(f"[Q-C W5] did-jwt autogen skipped (non-fatal): {e}")
    # ─── END Q-C W5 ────────────────────────────────────────────────────────

    # Store the agent registration in the database
    # commit=False so the card failure below can actually undo this (§FRAMELIC row 151).
    # The row is committed at the card-link step; nothing outside this session reads the
    # agent before then (the TEG profile call is ~130 lines further down, after the commit).
    created_agent = await create_agent_db(
        db=db,
        did=agent_did,
        client_id=client_id,
        client_secret=client_secret,
        public_key_jwk=effective_public_jwk,
        creator_developer_id=token.creator_developer_id,
        commit=False,
    )

    # Create the Agent Card using proper schema
    try:
        agent_card = await card_crud.create_agent_card(
            db=db,
            developer_id=token.creator_developer_id,
            card_create=schemas.AgentCardCreate(card_data=card_data_to_persist)
        )
    except ValueError as e:
        await db.rollback()
        logger.error(f"Agent Card validation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid agent card: {str(e)}"
        )
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to create Agent Card: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create agent card: {str(e)}"
        )
    
    # --- OWL22 OPTION B: Link the card to the agent via agent_did ---
    try:
        agent_card.agent_did = agent_did
        db.add(agent_card)
        await db.commit()
        await db.refresh(agent_card)
        logger.info(f"Linked Agent Card {agent_card.id} to agent DID: {agent_did}")
    except Exception as e:
        logger.error(f"Failed to link agent_did to card: {e}")
        # Non-fatal: card exists but linkage failed. Backfill can fix later.
    # --- END OWL22 ---
    
    # Mark the bootstrap token as used and associate with the created agent
    await bootstrap_crud.mark_bootstrap_token_as_used(
        db=db,
        token_id=token.id,
        agent_did=agent_did,
        agent_id=created_agent.id
    )

    # ── IRONKEY: seed DEFAULT BIRTH ROLES (2026-07-08, Commander directive) ──
    # New agents must be able to transact — including cross-registry settle. Post-mig-0107
    # agents were born with NO roles → BASE-only under enforce (couldn't even teg.transfer).
    # Under RBAC off/shadow these rows are inert (fleet-safe); under enforce (frame-c) they
    # give newborns a sane default. Env AGENT_RBAC_DEFAULT_ROLES (csv), default
    # "trader,client" (teg.transfer, teg.transfer_xreg, a2a.pay, contracts.engage,
    # exchange.trade/ipo, fx.quote, disputes.file). Empty string ⇒ seed nothing.
    # `legacy-full` is NEVER seedable from env (least-privilege ratchet stays meaningful).
    try:
        from sqlalchemy import text as sa_text
        from agentvault_registry.agent_authz import ROLE_PERMISSIONS
        _birth_roles = [r.strip() for r in os.getenv("AGENT_RBAC_DEFAULT_ROLES", "trader,client").split(",") if r.strip()]
        _birth_roles = [r for r in _birth_roles if r in ROLE_PERMISSIONS and r != "legacy-full"]
        for _r in _birth_roles:
            await db.execute(sa_text(
                "INSERT INTO agent_role_grants (agent_did, grant_type, value, granted_by_dev_id) "
                "VALUES (:did, 'role', :val, :dev) ON CONFLICT (agent_did, grant_type, value) DO NOTHING"
            ), {"did": agent_did, "val": _r, "dev": token.creator_developer_id})
        if _birth_roles:
            await db.commit()
            logger.info(f"[IRONKEY] seeded default birth roles {_birth_roles} for {agent_did}")
    except Exception as e:  # noqa: BLE001 — role seeding must never block agent creation
        logger.warning(f"[IRONKEY] default birth-role seed failed for {agent_did}: {e}")

    # §pass47 O1 — auto-link agent to developer's organization (single-org only).
    # If the developer is in exactly one active org, set Agent.organization_id.
    # If they're in multiple, leave NULL and surface available_orgs in response;
    # caller must POST /organizations/{org_id}/agents/{agent_did}/assign explicitly.
    assigned_organization_id: Optional[str] = None
    available_orgs_list: Optional[List[Dict[str, Any]]] = None
    try:
        org_rows = await db.execute(
            select(Organization.id, Organization.name, Organization.slug)
            .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
            .where(
                OrganizationMember.developer_id == token.creator_developer_id,
                OrganizationMember.is_active.is_(True),
                Organization.is_active.is_(True),
            )
        )
        orgs = list(org_rows.all())
        if len(orgs) == 1 and await org_agent_limit_reached(db, orgs[0].id):
            # §DOCSFIX D6-501: the organization is full; the agent is created unassigned, as the assign route
            # would refuse it (409). The owner can make room and assign it there.
            logger.info(f"[Org-Link] Org {orgs[0].id} is at its agent limit: agent {agent_did} left unassigned")
        elif len(orgs) == 1:
            assigned_organization_id = orgs[0].id
            created_agent.organization_id = assigned_organization_id
            db.add(created_agent)
            await db.commit()
            logger.info(
                f"[Org-Link] Auto-assigned agent {agent_did} to org "
                f"{assigned_organization_id} (developer={token.creator_developer_id})"
            )
            # Track A5 — the org's configured default authority slice rides the
            # auto-assignment (same shared writer as the assign route / bulk).
            # Best-effort: a grant failure never blocks agent creation.
            try:
                from sqlalchemy import text as _text
                from agentvault_registry.services.org_policy import default_authority_slice
                from agentvault_registry.services.org_authz import grant_org_slice
                srow = (await db.execute(_text(
                    "SELECT settings FROM organizations WHERE id = :oid"),
                    {"oid": assigned_organization_id})).first()
                slice_name = default_authority_slice(srow[0] if srow and isinstance(srow[0], dict) else {})
                if slice_name:
                    await grant_org_slice(db, org_slug=orgs[0].slug, agent_dids=[agent_did],
                                          role=slice_name, granted_by=token.creator_developer_id)
                    await db.commit()
                    logger.info(f"[ORG-AUTHORITY] default slice {slice_name} auto-granted to "
                                f"{agent_did} at onboarding")
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[ORG-AUTHORITY] onboarding default-slice grant failed for {agent_did}: {e}")
        elif len(orgs) > 1:
            available_orgs_list = [
                {"id": o.id, "name": o.name, "slug": o.slug} for o in orgs
            ]
            logger.info(
                f"[Org-Link] Developer {token.creator_developer_id} in {len(orgs)} orgs — "
                f"agent {agent_did} left unassigned, surfacing available_orgs"
            )
    except Exception as e:  # noqa: BLE001
        # Non-fatal — agent creation succeeds even if org lookup fails.
        logger.warning(f"[Org-Link] Auto-link skipped for {agent_did}: {e}")

    # Create TEG profile for the new agent
    logger.info(f"Attempting to create TEG profile for new agent: {agent_did}")
    try:
        await create_teg_profile_for_agent(agent_did)
        logger.info(f"Successfully requested TEG profile creation for agent: {agent_did}")
    except Exception as e:
        logger.error(f"Failed to create TEG profile for agent {agent_did}: {e}")
        # Note: Not failing the registration to maintain backward compatibility
    
    # OWL20-PREP: Emit AgentOnboarded to Event Store (registry-side creation record)
    import asyncio
    asyncio.create_task(event_emitter.emit(
        event_type="AgentOnboarded",
        aggregate_id=agent_did,
        data={
            "agent_did": agent_did,
            "developer_id": token.creator_developer_id,
            "agent_card_id": str(agent_card.id),
            "agent_card_name": agent_card.name,
            "did_method": creation_request.agent_did_method,
            "has_public_key": creation_request.public_key_jwk is not None
        }
    ))
    
    # Genesis Grant: Mint tokens for the developer's FIRST agent only
    initial_funding_status = "not_eligible"
    faucet_transaction_id = "none"
    
    genesis_enabled = getattr(settings, 'GENESIS_GRANT_ENABLED', True)
    if genesis_enabled:
        try:
            agent_count = await count_developer_agents(db, token.creator_developer_id)
            logger.info(f"Developer {token.creator_developer_id} now has {agent_count} agent(s)")
            
            if agent_count == 1:
                # This is the developer's first agent — mint genesis grant
                grant_amount = getattr(settings, 'GENESIS_GRANT_AMOUNT', '1000.0')
                logger.info(f"First agent for developer {token.creator_developer_id} — minting {grant_amount} AVT genesis grant")
                # §REWARDEVENTS: the shared rail emits per-leg TokensTransferred,
                # syncs the cached balance from TEG truth (completed AND partial),
                # and dedups via Idempotency-Key genesis-{agent_did}.
                initial_funding_status, faucet_transaction_id = await mint_genesis_grant(agent_did, db)
            else:
                logger.info(f"Developer {token.creator_developer_id} already has {agent_count} agents — no genesis grant")
                initial_funding_status = "not_first_agent"
        except Exception as e:
            logger.error(f"Genesis grant check failed for agent {agent_did}: {e}")
            initial_funding_status = "error"
            faucet_transaction_id = f"grant_error_{secrets.token_hex(8)}"
    
    # §pass36 Option C Phase 5a/5b — one-shot pull-sync when agent_host was sent.
    # Best-effort: if the agent's container isn't up yet (typical), the pull
    # will fail; the 6h background worker picks it up later. We retry once
    # after 30s to handle fast "bootstrap → deploy" loops.
    if sent_agent_host:
        try:
            from ..background_tasks.agent_card_pullsync import trigger_pull_for_did
            asyncio.create_task(_one_shot_pullsync_with_retry(agent_did, trigger_pull_for_did))
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[Option C] one-shot pullsync schedule failed (non-fatal): {e}")

    # §TWOAGENT (2026-09-24): agent.created was subscribable, documented (the API reference's own example event) and
    # dispatched by nothing, so a developer following the docs subscribed to an event that never came. Owner-scoped,
    # after every commit above, the way A1 fired agent.deleted.
    try:
        from ..background_tasks.reactor_helpers import dispatch_webhook_for_agents
        asyncio.create_task(dispatch_webhook_for_agents(
            "agent.created",
            {"agent_did": agent_did, "name": agent_card.name, "agent_card_id": str(agent_card.id),
             "created_via": "onboarding"},
            [agent_did], source_label="onboarding.create_agent"))
    except Exception as e:  # noqa: BLE001 — a notice is advisory; the agent exists
        logger.warning(f"agent.created webhook not scheduled for {agent_did}: {e}")

    # Return the combined response
    return CreateAgentResponse(
        agent_did=agent_did,
        client_id=client_id,
        client_secret=client_secret,
        registry_url=credential_home_url(),
        did_jwt_private_key=did_jwt_private_pem,
        did_jwt_public_key_jwk=effective_public_jwk if did_jwt_private_pem else None,
        account_status="active",
        initial_funding_status=initial_funding_status,
        faucet_transaction_id=faucet_transaction_id,
        agent_card_id=str(agent_card.id),
        agent_card_name=agent_card.name,
        requires_well_known_fetch=sent_agent_host,
        organization_id=assigned_organization_id,
        available_orgs=available_orgs_list,
        deprecation_warning=(
            "Legacy `agent_card` payload is deprecated. Migrate to `agent_host` "
            "(Option C) — the registry will pull your card from "
            "`<host>/.well-known/agent-card.json` per A2A v1.0 §4.1.2."
            if used_legacy_path else None
        ),
    )


async def _one_shot_pullsync_with_retry(agent_did: str, trigger_fn) -> None:
    """§pass36 Option C Phase 5a — try to pull immediately + once 30s later.

    Catches the common "bootstrap-then-deploy" race where the agent's
    container takes a moment to come up after bootstrap credentials are issued.
    """
    try:
        # Immediate attempt
        await trigger_fn(agent_did)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[Option C] first pull attempt for {agent_did} failed (non-fatal): {e}")
    await asyncio.sleep(30)
    try:
        await trigger_fn(agent_did)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[Option C] 30s-retry pull for {agent_did} failed (non-fatal): {e}")


# --- Agent Credential Reset ---

@router.post(
    "/agents/{agent_did}/reset-credentials",
    response_model=ResetCredentialsResponse,
    summary="Reset Agent OAuth Credentials",
    description="Generates new client_id and client_secret for an agent. "
                "Requires developer authentication + password confirmation. "
                "Old credentials are immediately invalidated. "
                "Rate limited to 3 resets per hour.",
    tags=["Agent Management"],
)
@limiter.limit("3/hour")
async def reset_agent_credentials(
    request: Request,
    agent_did: str = Path(..., description="Agent DID to reset credentials for"),
    request_body: ResetCredentialsRequest = Body(...),
    current_developer: models.Developer = Depends(get_current_developer_unified),
    db: AsyncSession = Depends(get_db),
):
    """
    Secure credential reset for agents. Three-layer security:
    1. Developer JWT authentication (session)
    2. Ownership verification (creator_developer_id)
    3. Password confirmation (prevents session hijack)

    The new client_secret is returned ONCE in this response.
    The old client_id is immediately invalidated.
    An AgentCredentialReset event is emitted to the EventStore for audit.
    """
    # 1. Verify developer password
    if not security.verify_password(request_body.password, current_developer.hashed_password):
        logger.warning(f"[CREDENTIAL RESET] Invalid password attempt for agent {agent_did} by developer {current_developer.id}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid password. Credential reset requires your current account password.",
        )

    # 2. Fetch agent by DID
    result = await db.execute(select(models.Agent).where(models.Agent.did == agent_did))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    # 3. Verify ownership
    if agent.creator_developer_id != current_developer.id:
        logger.warning(
            f"[CREDENTIAL RESET] Ownership violation: developer {current_developer.id} "
            f"attempted to reset agent {agent_did} owned by developer {agent.creator_developer_id}"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not own this agent. Only the creator can reset credentials.",
        )

    # 3b. SECOND FACTOR (§DISCREFINE 2026-08-23). A password is one secret, and the
    # thing being handed out here is another agent's whole identity. Any developer
    # who HAS a factor must use it; a developer who has none is unaffected, because
    # demanding a proof nobody can produce is a lockout, not a control. Placed after
    # the ownership check so a stranger can neither mint a challenge against someone
    # else's agent nor learn from the response that it exists.
    # The human name lives on the CARD, not on `agents` (which has no name column
    # at all). The facts are what the phone renders before a fingerprint, so the
    # name is worth one small read; a card-less agent falls back to its DID.
    _card_name = (await db.execute(
        select(models.AgentCard.name).where(models.AgentCard.agent_did == agent_did).limit(1)
    )).scalar_one_or_none()
    stepup_ok, stepup_payload = await stepup.require(
        db, current_developer,
        action_type="agent.reset_credentials",
        action_ref=agent_did,
        facts={
            "action": "Reset agent credentials",
            "agent_did": agent_did,
            "agent_name": _card_name or agent_did,
            "consequence": "The current client_secret stops working immediately.",
        },
        totp_code=request_body.totp_code,
        challenge_id=request_body.challenge_id,
    )
    if not stepup_ok:
        # The challenge was just minted, so it must survive this failed request —
        # otherwise the phone lights up for a confirm whose row was rolled back.
        await db.commit()
        logger.warning(
            f"[CREDENTIAL RESET] step-up required for developer {current_developer.id} "
            f"on agent {agent_did}: {(stepup_payload or {}).get('reason')}"
        )
        # A JSONResponse, NOT an HTTPException: the RFC 7807 handler json.dumps() a
        # dict detail into a STRING (errors.py:157), which would force every client to
        # parse JSON out of a message field to find the challenge id. Returning the
        # response directly also bypasses response_model validation, which is correct
        # here — this is not a ResetCredentialsResponse.
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={
                "error": "step_up_required",
                "message": "Confirm this on your phone, or send a current authenticator code.",
                "step_up": stepup_payload,
            },
        )

    # 4. Verify agent is active
    if agent.status in ("suspended", "revoked"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot reset credentials for agent with status '{agent.status}'.",
        )

    # 5. Generate new credentials
    old_client_id = agent.client_id
    new_client_id, new_client_secret = generate_client_credentials()
    new_hashed_secret = security.hash_password(new_client_secret)

    # 6. Atomic DB update
    agent.client_id = new_client_id
    agent.hashed_client_secret = new_hashed_secret
    db.add(agent)
    await db.commit()

    # 7. Emit audit event (fire-and-forget, non-blocking)
    try:
        emitter = get_event_emitter()
        asyncio.create_task(emitter.emit(
            event_type="AgentCredentialReset",
            aggregate_id=agent_did,
            data={
                "agent_did": agent_did,
                "old_client_id": old_client_id,
                "new_client_id": new_client_id,
                "reset_by_developer_id": current_developer.id,
                "reset_by_email": current_developer.name,
            },
            idempotency_key=f"credential_reset:{agent_did}:{new_client_id}",
        ))
    except Exception as e:
        logger.warning(f"[CREDENTIAL RESET] Event emission failed (non-fatal): {e}")

    # 8. Log (NO secrets in logs)
    logger.info(
        f"[CREDENTIAL RESET] Agent {agent_did} credentials reset successfully. "
        f"Old client_id={old_client_id}, new client_id={new_client_id}, "
        f"by developer {current_developer.id} ({current_developer.name})"
    )

    # 9. Return new credentials (shown ONCE)
    return ResetCredentialsResponse(
        agent_did=agent_did,
        client_id=new_client_id,
        client_secret=new_client_secret,
        previous_client_id=old_client_id,
        status="credentials_reset",
        warning="Store these credentials securely. They will not be shown again.",
        registry_url=credential_home_url(),
    )
