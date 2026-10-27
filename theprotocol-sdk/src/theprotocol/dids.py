"""
Agent DID shapes, as the registries issue and accept them.

Since the issuer namespace a registry issues ``did:theprotocol:<issuer>:<uuid4>``: the issuer is the issuing
frame's SPIFFE trust domain (lowercase, DNS-shaped), so two frames cannot issue the same DID. Older shapes stay
valid for life: ``did:theprotocol:<uuid4>``, the 8-4-4-4 legacy suffix, ``did:cos:<id>`` and the deterministic
system DIDs, whose second segment (``treasury``, ``operator``, ...) is never an issuer.

This module mirrors the registry's own rule (``agentvault_registry/identifiers.py``) so an SDK and the registry
it talks to read a DID the same way.
"""

import re
from typing import Optional, Tuple

_HEX = "[0-9a-f]"
UUID4_RE = re.compile(rf"^{_HEX}{{8}}-{_HEX}{{4}}-4{_HEX}{{3}}-[89ab]{_HEX}{{3}}-{_HEX}{{12}}$")
ISSUER_RE = re.compile(r"^[a-z0-9]([a-z0-9.-]{0,61}[a-z0-9])?$")
RESERVED_ISSUERS = frozenset({
    "operator", "cloud", "org", "agora-gateway", "developer", "api-tester", "system", "teg",
    "treasury", "gateway", "fx", "fee", "fee_collector", "admin", "registry", "frame", "template",
})


def valid_issuer(issuer: object) -> bool:
    """True for a DNS-shaped, lowercase issuer that is not a reserved system segment."""
    return isinstance(issuer, str) and bool(ISSUER_RE.match(issuer)) and issuer not in RESERVED_ISSUERS


def split_agent_did(did: str) -> Tuple[Optional[str], Optional[str], str]:
    """``(method, issuer or None, method-specific id)``.

    did:theprotocol:eu.theprotocol.cloud:<uuid4> -> ("theprotocol", "eu.theprotocol.cloud", "<uuid4>")
    did:theprotocol:<uuid4>                      -> ("theprotocol", None, "<uuid4>")
    """
    parts = (did or "").split(":")
    if len(parts) < 3 or parts[0] != "did":
        return None, None, did or ""
    method = parts[1]
    if len(parts) >= 4 and valid_issuer(parts[2]):
        return method, parts[2], ":".join(parts[3:])
    return method, None, ":".join(parts[2:])


def did_from_spiffe_path(sanitized: str) -> str:
    """Read a DID back from the path segment of an agent SVID (``spiffe://<td>/agent/<sanitized>``).

    The registry writes a DID into the path with every colon as a hyphen. The method and the scheme are the
    first two hyphens; an issuer DID's third colon is restored when the tail is a uuid4 and the head a valid
    issuer, the same rule the registry uses to read it back.

    did-theprotocol-eu.theprotocol.cloud-<uuid4> -> did:theprotocol:eu.theprotocol.cloud:<uuid4>
    did-theprotocol-4c783710-64d5-f8c3-3f6c      -> did:theprotocol:4c783710-64d5-f8c3-3f6c
    """
    parts = sanitized.split("-", 2)
    if len(parts) >= 3:
        rest = parts[2]
        if len(rest) > 37 and rest[-37] == "-":
            head, tail = rest[:-37], rest[-36:]
            if UUID4_RE.match(tail) and valid_issuer(head):
                rest = f"{head}:{tail}"
        return f"{parts[0]}:{parts[1]}:{rest}"
    return sanitized.replace("-", ":")


__all__ = [
    "UUID4_RE", "ISSUER_RE", "RESERVED_ISSUERS",
    "valid_issuer", "split_agent_did", "did_from_spiffe_path",
]
