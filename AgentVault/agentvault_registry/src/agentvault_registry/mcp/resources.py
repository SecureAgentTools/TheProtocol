"""
MCP Resources (spec 2025-11-25) — readable, URI-addressed context objects.

Exposes the registry's self-describing identity + live network state so a
connecting agent can READ who we are without burning tool calls:

    theprotocol://registry/card          — signed Registry Card v0.6
    theprotocol://registry/solvency-card — signed AGORA Solvency Card (if venue)
    theprotocol://registry/jwks          — registry signing JWKS
    theprotocol://registry/openapi       — full OpenAPI document
    theprotocol://network/stats          — live network statistics
    theprotocol://agent/{did}/card       — resource TEMPLATE: any agent's card

All read-only; the well-known family is fetched over the registry's own
public routes (same paths the fleet serves externally), stats reuses the
existing discovery tool. subscribe/listChanged are NOT advertised (v1).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

import httpx

from .tools_discovery import REGISTRY_SELF_URL, get_agent_profile, get_network_stats

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(8.0, connect=3.0)
# §MCPTEST30 (V0644): each worker builds the OpenAPI document on its first read (2.5 to 3.7 s on a quiet box), and under
# the V0643 pair proof's load the build outlasted 8 s: resources/read answered -32603 (nt261026x2, 2026-10-26). The
# tester waits 60 s for a read.
_OPENAPI_TIMEOUT = httpx.Timeout(30.0, connect=3.0)

# Static catalog (uri → route or handler marker). description doubles as the
# LLM-facing hint, mirroring the tool-description style.
RESOURCE_DEFS: List[Dict[str, str]] = [
    {
        "uri": "theprotocol://registry/card",
        "name": "registry-card",
        "title": "Registry Card (v0.6, EdDSA-signed)",
        "description": "This registry's signed self-description: identity, operator location, capabilities, fees, federation + AGORA venue flags.",
        "mimeType": "application/json",
    },
    {
        "uri": "theprotocol://registry/solvency-card",
        "name": "solvency-card",
        "title": "AGORA Solvency Card (signed)",
        "description": "Registry-signed exchange solvency attestation (launch allocation integrity, treasury solvency, distribution coverage). 404 on non-venue registries.",
        "mimeType": "application/json",
    },
    {
        "uri": "theprotocol://registry/jwks",
        "name": "registry-jwks",
        "title": "Registry Signing Keys (JWKS)",
        "description": "Public JWKS used to verify this registry's card and stock-card signatures.",
        "mimeType": "application/json",
    },
    {
        "uri": "theprotocol://registry/openapi",
        "name": "openapi",
        "title": "Full OpenAPI Document",
        "description": "Complete OpenAPI 3 schema of the registry HTTP API (large; fetch on demand).",
        "mimeType": "application/json",
    },
    {
        "uri": "theprotocol://network/stats",
        "name": "network-stats",
        "title": "Live Network Statistics",
        "description": "Current agent/developer/stake/governance counts for this registry, computed live.",
        "mimeType": "application/json",
    },
]

RESOURCE_TEMPLATES: List[Dict[str, str]] = [
    {
        "uriTemplate": "theprotocol://agent/{did}/card",
        "name": "agent-card",
        "title": "Agent Card by DID",
        "description": "Full public profile/card of any agent, addressed by its DID (e.g. theprotocol://agent/did:theprotocol:abc123/card).",
        "mimeType": "application/json",
    },
]

try:
    from agentvault_registry.config import settings as _settings
    _API_V1 = _settings.API_V1_STR
except Exception:  # noqa: BLE001 — the config's own default
    _API_V1 = "/api/v1"


class ResourceNotFound(str):
    """A resources/read error that is the CLIENT's miss (no such resource here): JSON-RPC -32002, HTTP 404.
    Any other error string is a failure on this side: -32603, HTTP 500 (§MCPTEST30)."""


def error_code(err: str) -> int:
    return -32002 if isinstance(err, ResourceNotFound) else -32603


_WELL_KNOWN_ROUTES = {
    "theprotocol://registry/card": "/.well-known/registry-card.json",
    "theprotocol://registry/solvency-card": "/.well-known/solvency-card.json",
    "theprotocol://registry/jwks": "/.well-known/registry-jwks.json",
    # §MCPTEST30 (2026-10-01): /openapi.json answers 308 to {API_V1_STR}/openapi.json since §pass52 PR-12, and this
    # fetch follows no redirect, so the advertised OpenAPI resource was unreadable on every registry.
    "theprotocol://registry/openapi": f"{_API_V1}/openapi.json",
}


def list_resources() -> Dict[str, Any]:
    return {"resources": RESOURCE_DEFS}


def list_templates() -> Dict[str, Any]:
    return {"resourceTemplates": RESOURCE_TEMPLATES}


def _contents(uri: str, payload: Any) -> Dict[str, Any]:
    text = payload if isinstance(payload, str) else json.dumps(payload, indent=2, default=str)
    return {"contents": [{"uri": uri, "mimeType": "application/json", "text": text}]}


async def read_resource(uri: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Resolve a resource URI → ({"contents": [...]}, None) or (None, error msg).
    Error msg → JSON-RPC -32002 (resource not found) at the RPC layer."""
    uri = (uri or "").strip()

    if uri in _WELL_KNOWN_ROUTES:
        route = _WELL_KNOWN_ROUTES[uri]
        try:
            timeout = _OPENAPI_TIMEOUT if uri == "theprotocol://registry/openapi" else _TIMEOUT
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.get(f"{REGISTRY_SELF_URL}{route}")
        except Exception as exc:
            # the class names a timeout; an httpx timeout's own text is often empty
            return None, f"resource fetch failed for {uri}: {type(exc).__name__}: {exc}"
        if r.status_code == 404:
            return None, ResourceNotFound(f"{uri} is not served by this registry (HTTP 404 on {route})")
        if r.status_code != 200:
            return None, f"{uri} unavailable (HTTP {r.status_code} on {route})"
        return _contents(uri, r.text), None

    if uri == "theprotocol://network/stats":
        stats = await get_network_stats()
        return _contents(uri, stats), None

    # Template: theprotocol://agent/{did}/card
    if uri.startswith("theprotocol://agent/") and uri.endswith("/card"):
        did = uri[len("theprotocol://agent/"):-len("/card")]
        if not did:
            return None, ResourceNotFound("empty DID in agent card URI")
        profile = await get_agent_profile(agent_did=did)
        if isinstance(profile, dict) and profile.get("error"):
            return None, ResourceNotFound(f"agent card not found for {did}: {profile['error']}")
        return _contents(uri, profile), None

    return None, ResourceNotFound(f"unknown resource URI: {uri}")
