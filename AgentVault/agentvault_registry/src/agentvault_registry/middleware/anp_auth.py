"""
DIDWba Authorization Middleware for ANP (Agent Network Protocol).

DIDWba is the ANP authentication scheme where agents sign HTTP requests
with Ed25519 keys. The Authorization header format is:

    Authorization: DIDWba did="did:wba:example.com:agent123", nonce="abc123",
                   timestamp="2026-03-17T00:00:00Z", signature="base64sig"

This module provides an OPTIONAL FastAPI dependency that:
  - Parses the Authorization: DIDWba header
  - Verifies timestamp freshness (5-minute replay window)
  - Looks up agent by DID (did:wba: and mapped did:cos: / did:theprotocol:)
  - If agent exists: verifies signature against stored public key
  - If agent doesn't exist: returns parsed info with is_new=True
  - Returns None if no DIDWba header present (fallback to existing auth)

Usage in endpoints:
    @router.get("/example")
    async def example(
        anp_identity: Optional[DIDWbaIdentity] = Depends(get_didwba_identity),
    ):
        if anp_identity is None:
            # No DIDWba header — fall back to normal auth
            ...
"""

import base64
import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any

from fastapi import Request, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db, AsyncSessionLocal
from ..models import Agent

logger = logging.getLogger(__name__)

# Maximum age of a DIDWba timestamp before it's rejected (replay protection)
DIDWBA_MAX_AGE_SECONDS = 300  # 5 minutes


@dataclass
class DIDWbaIdentity:
    """Parsed and (optionally) verified DIDWba identity."""

    did: str
    nonce: str
    timestamp: str
    signature: str
    is_new: bool = False  # True when agent not found in local registry
    agent: Optional[Any] = field(default=None, repr=False)  # Agent ORM object if found
    public_key_jwk: Optional[Dict[str, Any]] = None  # From DID resolution or header


# ---------------------------------------------------------------------------
# Header parsing
# ---------------------------------------------------------------------------

_DIDWBA_PARAM_RE = re.compile(
    r'(\w+)\s*=\s*"([^"]*)"'
)


def _parse_didwba_header(auth_header: str) -> Optional[Dict[str, str]]:
    """
    Parse an Authorization header with the DIDWba scheme.

    Returns a dict with keys: did, nonce, timestamp, signature
    or None if the header doesn't use the DIDWba scheme.
    """
    if not auth_header.startswith("DIDWba "):
        return None

    params_str = auth_header[len("DIDWba "):]
    params: Dict[str, str] = {}
    for match in _DIDWBA_PARAM_RE.finditer(params_str):
        params[match.group(1)] = match.group(2)

    required = {"did", "nonce", "timestamp", "signature"}
    if not required.issubset(params.keys()):
        missing = required - params.keys()
        logger.warning(f"DIDWba header missing required params: {missing}")
        return None

    return params


# ---------------------------------------------------------------------------
# Timestamp verification
# ---------------------------------------------------------------------------

def _verify_timestamp(timestamp_str: str) -> bool:
    """
    Verify the DIDWba timestamp is within the acceptable window.

    Accepts ISO 8601 format (with or without trailing Z / +00:00).
    Returns True if within DIDWBA_MAX_AGE_SECONDS of now.
    """
    try:
        # Handle common ISO formats
        ts = timestamp_str.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(ts)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)

        now = datetime.now(timezone.utc)
        delta = abs((now - parsed).total_seconds())
        if delta > DIDWBA_MAX_AGE_SECONDS:
            logger.warning(
                f"DIDWba timestamp too old/new: delta={delta:.1f}s "
                f"(max={DIDWBA_MAX_AGE_SECONDS}s)"
            )
            return False
        return True
    except (ValueError, TypeError) as exc:
        logger.warning(f"DIDWba timestamp parse error: {exc}")
        return False


# ---------------------------------------------------------------------------
# Signature verification (Ed25519 via public_key_jwk)
# ---------------------------------------------------------------------------

def _verify_signature(
    did: str,
    nonce: str,
    timestamp: str,
    signature_b64: str,
    public_key_jwk: Optional[Dict[str, Any]],
) -> bool:
    """
    Verify the DIDWba Ed25519 signature.

    The signed payload is: "did={did}&nonce={nonce}&timestamp={timestamp}"
    encoded as UTF-8.

    Returns True if signature is valid, False otherwise.
    If no public key is available, returns False (caller should treat agent
    as unverifiable but may still auto-enroll).
    """
    if not public_key_jwk:
        logger.debug(f"No public key available for DIDWba verification of {did}")
        return False

    try:
        # Only Ed25519 (OKP/Ed25519) keys are supported for DIDWba
        kty = public_key_jwk.get("kty")
        crv = public_key_jwk.get("crv")
        x_b64 = public_key_jwk.get("x")

        if kty != "OKP" or crv != "Ed25519" or not x_b64:
            logger.warning(
                f"DIDWba: unsupported key type kty={kty} crv={crv} for {did}"
            )
            return False

        # Decode public key bytes from base64url
        # Pad to multiple of 4
        padding = 4 - len(x_b64) % 4
        if padding != 4:
            x_b64 += "=" * padding
        pub_bytes = base64.urlsafe_b64decode(x_b64)

        # Build the signing payload
        payload = f"did={did}&nonce={nonce}&timestamp={timestamp}".encode("utf-8")

        # Decode signature
        sig_padding = 4 - len(signature_b64) % 4
        if sig_padding != 4:
            signature_b64 += "=" * sig_padding
        sig_bytes = base64.urlsafe_b64decode(signature_b64)

        # Use cryptography library for Ed25519 verification
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PublicKey,
        )
        from cryptography.exceptions import InvalidSignature

        public_key = Ed25519PublicKey.from_public_bytes(pub_bytes)
        public_key.verify(sig_bytes, payload)
        return True

    except ImportError:
        logger.warning(
            "DIDWba signature verification requires 'cryptography' package. "
            "Install with: pip install cryptography"
        )
        return False
    except InvalidSignature:
        logger.warning(f"DIDWba: invalid signature for {did}")
        return False
    except Exception as exc:
        logger.warning(f"DIDWba signature verification error for {did}: {exc}")
        return False


# ---------------------------------------------------------------------------
# Agent lookup
# ---------------------------------------------------------------------------

async def _lookup_agent_by_did(
    did: str, db: AsyncSession
) -> Optional[Agent]:
    """
    Look up an agent by DID.  Checks the literal DID first, then attempts
    common DID method mappings (did:wba: ↔ did:cos: ↔ did:theprotocol:).
    """
    # Direct lookup
    result = await db.execute(select(Agent).where(Agent.did == did))
    agent = result.scalar_one_or_none()
    if agent:
        return agent

    # Try alternative DID forms
    # did:wba:example.com:agent-42 → check if a mapped did:cos: or did:theprotocol: exists
    # This is a soft mapping — exact mapping tables can be added later.
    alternatives = []
    if did.startswith("did:wba:"):
        suffix = did[len("did:wba:"):]
        alternatives.append(f"did:cos:{suffix}")
        alternatives.append(f"did:theprotocol:{suffix}")
    elif did.startswith("did:cos:"):
        suffix = did[len("did:cos:"):]
        alternatives.append(f"did:wba:{suffix}")
        alternatives.append(f"did:theprotocol:{suffix}")
    elif did.startswith("did:theprotocol:"):
        suffix = did[len("did:theprotocol:"):]
        alternatives.append(f"did:wba:{suffix}")
        alternatives.append(f"did:cos:{suffix}")

    for alt_did in alternatives:
        result = await db.execute(select(Agent).where(Agent.did == alt_did))
        agent = result.scalar_one_or_none()
        if agent:
            logger.info(f"DIDWba: resolved {did} → mapped agent {agent.did}")
            return agent

    return None


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------

async def get_didwba_identity(request: Request) -> Optional[DIDWbaIdentity]:
    """
    FastAPI dependency that extracts and verifies a DIDWba Authorization header.

    Returns:
        DIDWbaIdentity if a valid DIDWba header is present.
        None if no DIDWba header is present (allows fallback to other auth).

    Raises:
        HTTPException 401 if header is present but malformed or timestamp expired.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("DIDWba "):
        return None

    # Parse header
    params = _parse_didwba_header(auth_header)
    if params is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed DIDWba Authorization header — "
                   "required: did, nonce, timestamp, signature",
        )

    did = params["did"]
    nonce = params["nonce"]
    timestamp = params["timestamp"]
    signature = params["signature"]

    # Verify timestamp freshness (replay protection)
    if not _verify_timestamp(timestamp):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"DIDWba timestamp expired or too far in the future "
                   f"(max age: {DIDWBA_MAX_AGE_SECONDS}s)",
        )

    # Look up agent in DB
    async with AsyncSessionLocal() as db:
        agent = await _lookup_agent_by_did(did, db)

        if agent is not None:
            # Agent exists — verify signature against stored public key
            sig_valid = _verify_signature(
                did, nonce, timestamp, signature, agent.public_key_jwk
            )
            if not sig_valid and agent.public_key_jwk:
                # Has a key but signature didn't match — reject
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="DIDWba signature verification failed",
                )
            # If no public key stored, we accept on trust (legacy agent)

            return DIDWbaIdentity(
                did=did,
                nonce=nonce,
                timestamp=timestamp,
                signature=signature,
                is_new=False,
                agent=agent,
                public_key_jwk=agent.public_key_jwk,
            )
        else:
            # Agent not found — mark as new for potential auto-enrollment
            return DIDWbaIdentity(
                did=did,
                nonce=nonce,
                timestamp=timestamp,
                signature=signature,
                is_new=True,
                agent=None,
                public_key_jwk=None,
            )
