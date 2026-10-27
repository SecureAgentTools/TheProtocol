"""
DIDWba Authentication — Create and verify ANP auth headers.

Spec: ANP DID:WBA authentication handshake.

Flow:
  1. Client builds payload: { nonce, timestamp, service, did }
  2. JCS canonicalize → SHA-256 → sign with private key → base64url
  3. Send as: Authorization: DIDWba did="...", nonce="...", timestamp="...", verification_method="...", signature="..."
  4. Server resolves DID document, finds public key, verifies signature
  5. Server issues JWT Bearer token for subsequent requests
"""

import base64
import datetime
import hashlib
import json
import logging
import secrets
from typing import Dict, Optional, Tuple

from .did_wba import DIDDocument, KeyPair, resolve_did_wba

logger = logging.getLogger(__name__)


def _jcs_canonicalize(obj: Dict) -> bytes:
    """
    JSON Canonicalization Scheme (RFC 8785).
    Simplified: sort keys, no whitespace, ensure consistent number formatting.
    """
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64url_decode(s: str) -> bytes:
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s)


def create_didwba_auth_header(
    did: str,
    keypair: KeyPair,
    service_domain: str,
    verification_method_fragment: Optional[str] = None,
) -> str:
    """
    Create a DIDWba Authorization header value.

    Args:
        did: The agent's did:wba identifier
        keypair: The agent's Ed25519 keypair
        service_domain: The target service domain (e.g., "example.com")
        verification_method_fragment: Key fragment ID (defaults to keypair.kid)

    Returns:
        The full Authorization header value, e.g.:
        DIDWba did="did:wba:...", nonce="abc", timestamp="2024-...", verification_method="key-1", signature="..."
    """
    nonce = secrets.token_urlsafe(16)
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    vm_fragment = verification_method_fragment or keypair.kid

    # Build signature payload
    payload = {
        "nonce": nonce,
        "timestamp": timestamp,
        "service": service_domain,
        "did": did,
    }

    # JCS canonicalize → SHA-256 → sign
    canonical = _jcs_canonicalize(payload)
    digest = hashlib.sha256(canonical).digest()
    signature = keypair.sign(digest)
    sig_b64 = _b64url_encode(signature)

    header = (
        f'DIDWba did="{did}", '
        f'nonce="{nonce}", '
        f'timestamp="{timestamp}", '
        f'verification_method="{vm_fragment}", '
        f'signature="{sig_b64}"'
    )
    return header


def parse_didwba_auth_header(header_value: str) -> Optional[Dict[str, str]]:
    """
    Parse a DIDWba Authorization header into its components.

    Returns dict with keys: did, nonce, timestamp, verification_method, signature
    Or None if parsing fails.
    """
    if not header_value.startswith("DIDWba "):
        return None

    parts_str = header_value[7:]  # Strip "DIDWba "
    result = {}

    # Parse key="value" pairs
    import re
    for match in re.finditer(r'(\w+)="([^"]*)"', parts_str):
        result[match.group(1)] = match.group(2)

    required = {"did", "nonce", "timestamp", "verification_method", "signature"}
    if not required.issubset(result.keys()):
        logger.warning(f"DIDWba header missing required fields. Got: {set(result.keys())}, need: {required}")
        return None

    return result


async def verify_didwba_auth_header(
    header_value: str,
    expected_service: str,
    max_age_seconds: int = 60,
    did_document: Optional[DIDDocument] = None,
) -> Optional[str]:
    """
    Verify a DIDWba Authorization header.

    Args:
        header_value: The full Authorization header value
        expected_service: The expected service domain
        max_age_seconds: Maximum age of timestamp (default 60s)
        did_document: Pre-resolved DID document (if None, will resolve via HTTPS)

    Returns:
        The authenticated DID string if valid, None otherwise.
    """
    parsed = parse_didwba_auth_header(header_value)
    if not parsed:
        logger.warning("Failed to parse DIDWba header")
        return None

    did = parsed["did"]
    nonce = parsed["nonce"]
    timestamp_str = parsed["timestamp"]
    vm_fragment = parsed["verification_method"]
    signature_b64 = parsed["signature"]

    # Check timestamp freshness
    try:
        ts = datetime.datetime.strptime(timestamp_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
        age = (datetime.datetime.now(datetime.timezone.utc) - ts).total_seconds()
        if abs(age) > max_age_seconds:
            logger.warning(f"DIDWba timestamp too old: {age}s (max {max_age_seconds}s)")
            return None
    except ValueError:
        logger.warning(f"Invalid timestamp format: {timestamp_str}")
        return None

    # Resolve DID document if not provided
    doc = did_document
    if doc is None:
        doc = await resolve_did_wba(did)
    if doc is None:
        logger.warning(f"Could not resolve DID document for {did}")
        return None

    # Find verification method
    public_key_jwk = None
    for vm in doc.verification_methods:
        vm_id = vm.get("id", "")
        # Match by fragment (the part after #)
        if vm_id.endswith(f"#{vm_fragment}") or vm_id == f"{did}#{vm_fragment}":
            public_key_jwk = vm.get("publicKeyJwk")
            break

    if not public_key_jwk:
        logger.warning(f"Verification method '{vm_fragment}' not found in DID document for {did}")
        return None

    # Reconstruct and verify signature
    payload = {
        "nonce": nonce,
        "timestamp": timestamp_str,
        "service": expected_service,
        "did": did,
    }
    canonical = _jcs_canonicalize(payload)
    digest = hashlib.sha256(canonical).digest()

    try:
        signature = _b64url_decode(signature_b64)

        # Extract public key from JWK
        crv = public_key_jwk.get("crv", "")
        x_b64 = public_key_jwk.get("x", "")
        pub_bytes = _b64url_decode(x_b64)

        if crv == "Ed25519":
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
            public_key = Ed25519PublicKey.from_public_bytes(pub_bytes)
            public_key.verify(signature, digest)
            logger.info(f"DIDWba signature verified for {did}")
            return did
        else:
            logger.warning(f"Unsupported key curve: {crv}")
            return None

    except Exception as e:
        logger.warning(f"DIDWba signature verification failed for {did}: {e}")
        return None
