"""MCP tools: the quantum workload extension on agent cards (V0660 (a)), three public reads (tier 1).

    discoverQuantumAgents       GET /api/v1/agent-cards/discover with quantum_only and the quantum filters
    getQuantumWorkload          GET /api/v1/quantum/agents/{did}
    getQuantumWorkloadSchema    GET /api/v1/quantum/workload-extension

Listed only where QUANTUM_WORKLOADS_MODE is shadow or on (mcp/tool_switches.py). Called by name under off, each answers
the switch's sentence: the two quantum routes refuse with it (403), and discovery under off does not read the quantum
filters at all, so the search tool reads the echo (applied_filters carries quantum_only only where the filters ran)
and says so rather than handing back an unfiltered page as if it were the answer.

The spec: PRODUCTION_DOCS/SPECS/Quantum_Agent_Card_Extension_v1.0.md (services/quantum_agent_card.py holds the rules).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

from .auth_bridge import format_tool_exception
from .auth_bridge import mcp_http_client  # D6-514: every client to this registry carries the MCP relay proof
from .refusal import refusal_reason
from .tools_discovery import REGISTRY_SELF_URL
from ..core.path_segment import seg
from ..services import quantum_agent_card as _qac

logger = logging.getLogger(__name__)
_TIMEOUT = 15.0

ROLES = ["provider", "compiler", "mitigator", "verifier", "router", "meter"]
KINDS = ["qpu", "simulator", "emulator"]
MODALITIES = ["superconducting", "trapped-ion", "neutral-atom", "photonic", "spin", "annealer", "simulator"]


async def _get(path: str, params: Optional[Dict[str, Any]] = None) -> Any:
    try:
        async with mcp_http_client(timeout=_TIMEOUT) as client:
            return await client.get(f"{REGISTRY_SELF_URL}{path}", params=params)
    except httpx.TimeoutException:
        return {"error": f"GET {path} timed out"}
    except Exception as e:  # noqa: BLE001: every failure reaches the caller as a sentence
        logger.error("quantum tool GET %s error: %s", path, e, exc_info=True)
        return {"error": format_tool_exception(e)}


def _answer(r: Any) -> Dict[str, Any]:
    if isinstance(r, dict):
        return r
    if r.status_code == 200:
        try:
            data = r.json()
        except ValueError:
            return {"error": "HTTP 200: the registry's answer was not JSON"}
        return data if isinstance(data, dict) else {"items": data}
    return {"error": f"HTTP {r.status_code}: {refusal_reason(r)}"}


def _whole(name: str, value: Any, lo: int, hi: int) -> Any:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return {"error": f"{name} must be a whole number from {lo} to {hi} (got {value!r})"}
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        return {"error": f"{name} must be a whole number from {lo} to {hi} (got {str(value)[:40]!r})"}
    if n < lo or n > hi:
        return {"error": f"{name} must be a whole number from {lo} to {hi} (got {n})"}
    return n


async def discover_quantum_agents(
    modality: str = "",
    kind: str = "",
    role: str = "",
    min_qubits: Optional[int] = None,
    format: str = "",  # noqa: A002 (the spec's own word for a circuit format)
    jurisdiction: str = "",
    rung: Optional[int] = None,
    query: str = "",
    limit: int = 10,
    offset: int = 0,
) -> Dict[str, Any]:
    """Agents whose card carries the quantum workload extension, filtered by what their backends state."""
    lim = _whole("limit", limit if limit is not None else 10, 1, 50)
    off = _whole("offset", offset if offset is not None else 0, 0, 1_000_000)
    qub = _whole("min_qubits", min_qubits, 1, 10_000_000)
    rng = _whole("rung", rung, 1, 3)
    for v in (lim, off, qub, rng):
        if isinstance(v, dict):
            return v
    params: Dict[str, Any] = {"quantum_only": "true", "limit": lim or 10, "offset": off or 0}
    for key, value in (("quantum_modality", modality), ("quantum_kind", kind), ("quantum_role", role),
                       ("quantum_format", format), ("quantum_jurisdiction", jurisdiction)):
        if isinstance(value, str) and value.strip():
            params[key] = value.strip()
    if qub is not None:
        params["quantum_min_qubits"] = str(qub)
    if rng is not None:
        params["quantum_rung"] = str(rng)
    if isinstance(query, str) and query.strip():
        params["q"] = query.strip()[:100]
    data = _answer(await _get("/api/v1/agent-cards/discover", params))
    if "error" in data:
        return data
    applied = data.get("applied_filters") if isinstance(data.get("applied_filters"), dict) else {}
    if "quantum_only" not in applied:
        # the registry did not read the quantum filters (QUANTUM_WORKLOADS_MODE=off, or a registry before V0660):
        # the page it answered is unfiltered, so it is not the answer
        return {"error": _qac.OFF_SENTENCE}
    agents: List[Dict[str, Any]] = []
    for it in data.get("items") or []:
        if not isinstance(it, dict):
            continue
        agents.append({
            "did": it.get("agent_did") or it.get("did"),
            "name": it.get("name"),
            "description": it.get("description"),
            "origin_registry": it.get("origin_registry_name"),
            "is_local": it.get("is_local"),
            "quantum": it.get("quantum"),
            "pricing": it.get("pricing"),
            "settlement_currency": it.get("settlement_currency"),
            "endpoint_health": it.get("endpoint_health"),
        })
    facets = data.get("facets") if isinstance(data.get("facets"), dict) else {}
    return {
        "agents": agents,
        "total": data.get("total", len(agents)),
        "has_more": bool(data.get("has_more")),
        "facets": facets.get("quantum"),
        "filters": {k: v for k, v in applied.items() if k.startswith("quantum_") and v is not None},
        "limit": lim or 10,
        "offset": off or 0,
        "note": "The facts are each provider's signed claims with their as_of; getQuantumWorkload reads one card's "
                "extension with this registry's check and how old each fact is.",
    }


async def get_quantum_workload(did: str = "") -> Dict[str, Any]:
    """One agent's quantum workload extension, this registry's check of it, its index facets and the facts' ages."""
    if not isinstance(did, str) or not did.strip():
        return {"error": "did is required (the agent's DID)"}
    return _answer(await _get(f"/api/v1/quantum/agents/{seg(did.strip())}"))


async def get_quantum_workload_schema() -> Dict[str, Any]:
    """The extension's URI, version, spec name and JSON Schema, and this frame's mode."""
    return _answer(await _get("/api/v1/quantum/workload-extension"))


_LISTED = (" Listed where this registry's QUANTUM_WORKLOADS_MODE is shadow or on; under off it answers the switch's "
           "sentence.")

QUANTUM_TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "name": "theprotocol_discoverQuantumAgents",
        "description": ("Find quantum workload agents (providers, compilers, mitigators, verifiers, routers, meters) by "
                        "what their cards state: backend modality and kind, physical qubits, circuit formats, "
                        "jurisdiction and the verification rungs offered. Each result carries its index facets; the "
                        "facts are the provider's signed claims, each with its as_of. Public." + _LISTED),
        "inputSchema": {"type": "object", "properties": {
            "modality": {"type": "string", "enum": MODALITIES, "description": "A backend of this modality"},
            "kind": {"type": "string", "enum": KINDS, "description": "A backend of this kind"},
            "role": {"type": "string", "enum": ROLES, "description": "An agent that holds this role"},
            "min_qubits": {"type": "integer", "minimum": 1, "maximum": 10000000,
                           "description": "A backend with at least this many physical qubits"},
            "format": {"type": "string", "maxLength": 32, "pattern": "^[A-Za-z0-9.-]{1,32}$",
                       "description": "A backend that takes this circuit format (openqasm3, qir, ...)"},
            "jurisdiction": {"type": "string", "maxLength": 9, "pattern": "^(EU|EEA|[A-Za-z]{2}(-[A-Za-z0-9]{1,3})?)$",
                             "description": "A backend under this jurisdiction code (DE, US-CA, EU)"},
            "rung": {"type": "integer", "enum": [1, 2, 3], "description": "A verification rung the agent offers"},
            "query": {"type": "string", "maxLength": 100, "description": "Words in the name, description or tags"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
            "offset": {"type": "integer", "minimum": 0, "default": 0},
        }},
    },
    {
        "name": "theprotocol_getQuantumWorkload",
        "description": ("One agent's quantum workload extension as its card states it: roles, backends with device "
                        "facts, metering, evidence and data terms; this registry's check of it against the spec; the "
                        "index facets discovery reads; and how old each backend's facts are at this read. Public."
                        + _LISTED),
        "inputSchema": {"type": "object", "properties": {
            "did": {"type": "string", "minLength": 8, "maxLength": 200, "description": "The agent's DID"},
        }, "required": ["did"]},
    },
    {
        "name": "theprotocol_getQuantumWorkloadSchema",
        "description": ("The quantum workload agent card extension this registry checks cards against: its URI, "
                        "version, spec name and JSON Schema, and this frame's QUANTUM_WORKLOADS_MODE. A provider can "
                        "validate an extension it generates from its own device description against these bytes. "
                        "Public." + _LISTED),
        "inputSchema": {"type": "object", "properties": {}},
    },
]

QUANTUM_TOOL_NAMES = frozenset(t["name"] for t in QUANTUM_TOOL_SCHEMAS)
