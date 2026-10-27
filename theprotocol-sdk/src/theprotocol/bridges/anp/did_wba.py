"""
DID:WBA Method Implementation.

Spec: https://agent-network-protocol.com/en/specs/03-did-wba-method-specification/

did:wba:<domain>:<path> resolves to https://<domain>/<path>/did.json
did:wba:<domain> resolves to https://<domain>/.well-known/did.json

Supports:
  - DID creation (generate keypair + DID document)
  - DID resolution (fetch DID document from HTTPS URL)
  - DID document generation for TheProtocol agents
"""

import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import quote as url_quote

logger = logging.getLogger(__name__)

from ...dids import UUID4_RE, split_agent_did, valid_issuer

@dataclass
class KeyPair:
    """An Ed25519 keypair for DID authentication."""
    private_key_bytes: bytes
    public_key_bytes: bytes
    kid: str = ""

    @classmethod
    def generate(cls) -> "KeyPair":
        """Generate a new Ed25519 keypair."""
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        private_key = Ed25519PrivateKey.generate()
        public_key = private_key.public_key()

        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat, PrivateFormat, NoEncryption
        priv_bytes = private_key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
        pub_bytes = public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)

        # KID = base64url of SHA-256 of public key
        import base64
        kid = base64.urlsafe_b64encode(hashlib.sha256(pub_bytes).digest()).decode().rstrip("=")

        return cls(private_key_bytes=priv_bytes, public_key_bytes=pub_bytes, kid=kid)

    @property
    def public_key_multibase(self) -> str:
        """Encode public key as multibase (z prefix = base58btc)."""
        import base64
        # Multicodec prefix for Ed25519 pub key: 0xed01
        prefixed = b'\xed\x01' + self.public_key_bytes
        # Base58btc encoding with 'z' prefix
        return "z" + _base58_encode(prefixed)

    @property
    def public_jwk(self) -> Dict[str, str]:
        """Export public key as JWK."""
        import base64
        return {
            "kty": "OKP",
            "crv": "Ed25519",
            "x": base64.urlsafe_b64encode(self.public_key_bytes).decode().rstrip("="),
            "kid": self.kid,
        }

    def sign(self, data: bytes) -> bytes:
        """Sign data with the private key."""
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        private_key = Ed25519PrivateKey.from_private_bytes(self.private_key_bytes)
        return private_key.sign(data)

    def verify(self, signature: bytes, data: bytes) -> bool:
        """Verify a signature against the public key."""
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        public_key = Ed25519PublicKey.from_public_bytes(self.public_key_bytes)
        try:
            public_key.verify(signature, data)
            return True
        except Exception:
            return False

    def to_dict(self) -> Dict[str, str]:
        """Serialize keypair for storage."""
        import base64
        return {
            "private_key": base64.b64encode(self.private_key_bytes).decode(),
            "public_key": base64.b64encode(self.public_key_bytes).decode(),
            "kid": self.kid,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, str]) -> "KeyPair":
        """Deserialize keypair from storage."""
        import base64
        return cls(
            private_key_bytes=base64.b64decode(data["private_key"]),
            public_key_bytes=base64.b64decode(data["public_key"]),
            kid=data.get("kid", ""),
        )


@dataclass
class DIDDocument:
    """W3C DID Document for did:wba method."""
    did: str
    verification_methods: List[Dict] = field(default_factory=list)
    authentication: List[str] = field(default_factory=list)
    service: List[Dict] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "@context": [
                "https://www.w3.org/ns/did/v1",
                "https://w3id.org/security/suites/jws-2020/v1",
            ],
            "id": self.did,
            "verificationMethod": self.verification_methods,
            "authentication": self.authentication,
            "service": self.service,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


def did_wba_from_cos(did_cos: str, domain: str = "api.theprotocol.cloud") -> str:
    """
    Map an agent DID to its did:wba name.

    did:theprotocol:<issuer>:<uuid4> → did:wba:<issuer>:<uuid4>
        The DID names its frame, so the did:wba keeps it: the method prefix swapped, which is the name a
        registry recognises when an ANP agent signs with DIDWba (since 0.7.5; ``domain`` is not used).
    did:cos:abc-123 → did:wba:api.theprotocol.cloud:agents:abc-123
        Every other shape maps as it always has.
    """
    method, issuer, rest = split_agent_did(did_cos)
    if method == "theprotocol" and issuer and UUID4_RE.match(rest):
        return f"did:wba:{issuer}:{rest}"
    agent_id = did_cos.replace("did:cos:", "")
    return f"did:wba:{domain}:agents:{agent_id}"


def native_did_from_wba(did_wba: str, domain: str = "api.theprotocol.cloud") -> Optional[str]:
    """
    The registry DID a did:wba name stands for (the reverse of ``did_wba_from_cos``).

    did:wba:<issuer>:<uuid4> → did:theprotocol:<issuer>:<uuid4>
    did:wba:api.theprotocol.cloud:agents:abc-123 → did:cos:abc-123 (as ``did_cos_from_wba``)
    Returns None for a did:wba that is neither.
    """
    if did_wba.startswith("did:wba:"):
        head, sep, tail = did_wba[len("did:wba:"):].partition(":")
        if sep and valid_issuer(head) and UUID4_RE.match(tail):
            return f"did:theprotocol:{head}:{tail}"
    return did_cos_from_wba(did_wba, domain)


def did_cos_from_wba(did_wba: str, domain: str = "api.theprotocol.cloud") -> Optional[str]:
    """
    Map a did:wba identifier back to did:cos, if it belongs to our domain.

    did:wba:api.theprotocol.cloud:agents:abc-123 → did:cos:abc-123
    Returns None if the DID doesn't belong to our domain.
    """
    prefix = f"did:wba:{domain}:agents:"
    if did_wba.startswith(prefix):
        agent_id = did_wba[len(prefix):]
        return f"did:cos:{agent_id}"
    return None


def did_wba_to_url(did: str) -> str:
    """
    Resolve a did:wba to its DID Document URL.

    did:wba:example.com → https://example.com/.well-known/did.json
    did:wba:example.com:user:alice → https://example.com/user/alice/did.json
    did:wba:example.com%3A8800:user:alice → https://example.com:8800/user/alice/did.json
    """
    if not did.startswith("did:wba:"):
        raise ValueError(f"Not a did:wba: {did}")

    remainder = did[8:]  # Strip "did:wba:"
    parts = remainder.split(":")

    # First part is domain (may contain %3A for port)
    domain = parts[0].replace("%3A", ":")
    path_parts = parts[1:] if len(parts) > 1 else []

    if path_parts:
        path = "/".join(path_parts)
        return f"https://{domain}/{path}/did.json"
    else:
        return f"https://{domain}/.well-known/did.json"


def create_did_wba(
    agent_did_cos: str,
    keypair: KeyPair,
    domain: str = "api.theprotocol.cloud",
    agent_description_url: Optional[str] = None,
) -> DIDDocument:
    """
    Create a DID Document for a TheProtocol agent.

    Maps did:cos:xxx to did:wba:domain:agents:xxx and generates
    a W3C-compliant DID Document with Ed25519 verification method.
    """
    did_wba = did_wba_from_cos(agent_did_cos, domain)
    agent_id = agent_did_cos.replace("did:cos:", "")

    vm_id = f"{did_wba}#{keypair.kid}"

    verification_method = {
        "id": vm_id,
        "type": "Ed25519VerificationKey2018",
        "controller": did_wba,
        "publicKeyJwk": keypair.public_jwk,
    }

    services = []
    ad_url = agent_description_url or f"https://{domain}/agents/{agent_id}/ad.json"
    services.append({
        "id": f"{did_wba}#ad",
        "type": "AgentDescription",
        "serviceEndpoint": ad_url,
    })

    return DIDDocument(
        did=did_wba,
        verification_methods=[verification_method],
        authentication=[vm_id],
        service=services,
    )


async def resolve_did_wba(did: str) -> Optional[DIDDocument]:
    """
    Resolve a did:wba by fetching the DID Document from its HTTPS URL.

    Returns None if resolution fails.
    """
    import httpx

    url = did_wba_to_url(did)
    logger.debug(f"Resolving {did} → {url}")

    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()

            doc = DIDDocument(
                did=data.get("id", did),
                verification_methods=data.get("verificationMethod", []),
                authentication=data.get("authentication", []),
                service=data.get("service", []),
            )
            return doc
    except Exception as e:
        logger.error(f"Failed to resolve {did}: {e}")
        return None


def _base58_encode(data: bytes) -> str:
    """Base58 (Bitcoin alphabet) encoding."""
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    num = int.from_bytes(data, 'big')
    result = []
    while num > 0:
        num, rem = divmod(num, 58)
        result.append(alphabet[rem])
    # Handle leading zeros
    for byte in data:
        if byte == 0:
            result.append(alphabet[0])
        else:
            break
    return ''.join(reversed(result))
