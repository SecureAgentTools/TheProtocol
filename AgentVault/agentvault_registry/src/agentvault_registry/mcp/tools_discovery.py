"""
MCP Tier 1 — Public Discovery Tools (no authentication required).

These 6 tools expose TheProtocol's registry data for discovery and exploration.
Any MCP client can call these without authentication.

Tools:
  theprotocol.discoverRegistries   — Federated registry topology (via /public/topology)
  theprotocol.discoverAgents       — Search for agents by name/capability/DID (via /discover)
  theprotocol.getAgentProfile      — Get detailed profile for a specific agent (via /agents/by-did/{did})
  theprotocol.getNetworkStats      — Network health statistics and TVL  ⚠️ DB-DIRECT (documented exception)
  theprotocol.getGovernanceProposals — List Agent Senate governance proposals (via /governance/proposals)
  theprotocol.getLockPayoutTiers          — Current dynamic APY rates for staking (via /staking/apy-tiers)

§pass70 (2026-05-24) — Sprint 1 migration: 5 of 6 functions converted from direct-DB
SELECT to httpx GET against existing public/optional-auth registry endpoints. This
collapses parallel-gate maintenance: API-layer rate limit + audit + OPA + RFC 7807
now apply uniformly. Only `getNetworkStats` remains DB-direct: its 5-table aggregate
fan-out is cheaper as one DB transaction than 3 parallel HTTP calls, the data is
public, and no PII is exposed. See sessionlogs2026/STRATEGY_2026-05-24_MCP_UPGRADE_PLAN_v2.md
§Decision A.
"""
import base64
import hashlib
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

import httpx
from sqlalchemy import select, func

from ..config import settings
from ..database import get_db_context
from ..models import Agent, Stake, Dispute, GovernanceProposal
from ..services.dynamic_apy_engine import get_dynamic_apy_engine
from .auth_bridge import format_tool_exception
from .auth_bridge import mcp_http_client  # D6-514: every client to this registry carries the MCP relay proof
from .refusal import http_refusal  # §MCPTEST30: a refusal carries its reason
from ..core.path_segment import seg  # §MCPTEST30 V0523: a caller's value is one path segment, encoded

logger = logging.getLogger(__name__)

# Internal registry URL for httpx calls to our own API
REGISTRY_SELF_URL = getattr(settings, "REGISTRY_SELF_URL", "http://localhost:8000")
HTTPX_TIMEOUT = 15.0


async def discover_agents(
    query: str = "",
    capability: str = "",
    limit: int = 10,
    offset: int = 0,
    min_verified_jobs: int = 0,
    min_stars: float = 0.0,
) -> Dict[str, Any]:
    """
    Search for agents on TheProtocol by name, description, or DID.

    §pass70 — migrated to GET /api/v1/discover (public, optional-dev auth).
    §AGENTDISC #196 (2026-08-16) — machine buyers select workers by VERIFIED history:
    when min_verified_jobs/min_stars is set, the search rides the proof-ranked
    /agent-cards/discover surface (registry-attested track records, sort=proven) and
    each returned agent carries its track_record so the caller can read the CV it
    filtered on. Agents hiring agents check receipts before their principal's money moves.

    Args:
        query             : Search text — matches agent name, description, or DID
        capability        : Filter by agent capability tag (post-fetch client-side)
        limit             : Maximum results to return (default 10, max 50)
        offset            : Pagination offset (default 0)
        min_verified_jobs : Only agents with at least N registry-attested guild jobs
        min_stars         : Only agents whose attested average stars is at least this

    Returns:
        { "agents": [...], "total": int, "query": str, "limit": int, "offset": int }
        (+ "filters"/"ranking" when history filters are active)
    """
    limit = min(max(limit, 1), 50)
    offset = max(offset, 0)

    if (min_verified_jobs or 0) > 0 or (min_stars or 0) > 0:
        try:
            params: Dict[str, Any] = {"sort": "proven", "limit": 120, "offset": 0}
            if query:
                params["q"] = query[:100]
            async with mcp_http_client(timeout=HTTPX_TIMEOUT) as client:
                r = await client.get(
                    f"{REGISTRY_SELF_URL}/api/v1/agent-cards/discover", params=params)
            if r.status_code != 200:
                return {"error": http_refusal("discover endpoint", r),
                        "agents": [], "total": 0}
            items = r.json().get("items", [])
            cap_low = capability.lower() if capability else ""
            out = []
            for it in items:
                tr = it.get("track_record") or {}
                if int(tr.get("jobs") or 0) < int(min_verified_jobs or 0):
                    continue
                if (min_stars or 0) > 0 and float(tr.get("stars") or 0) < float(min_stars):
                    continue
                if cap_low and cap_low not in str(it.get("tags", [])).lower() \
                        and cap_low not in str(it.get("description", "")).lower():
                    continue
                out.append({
                    "did": it.get("agent_did") or it.get("did"),
                    "name": it.get("name"),
                    "description": it.get("description"),
                    "status": "active" if it.get("is_active", True) else "inactive",
                    "reputation_score": it.get("reputation_score") or 0,
                    "tags": it.get("tags", []),
                    "pricing": it.get("pricing"),
                    "origin_registry": it.get("origin_registry_name"),
                    "is_local": it.get("is_local"),
                    "track_record": it.get("track_record"),
                    "created_at": it.get("created_at"),
                    "last_active": it.get("last_active_at"),
                })
            total = len(out)
            return {
                "agents": out[offset:offset + limit],
                "total": total,
                "query": query, "limit": limit, "offset": offset,
                "filters": {"min_verified_jobs": min_verified_jobs, "min_stars": min_stars},
                "ranking": "proven",
                "note": "track_record figures are registry-attested; verify any engagement "
                        "via GET /api/v1/agents/{did}/track-record/receipts/{order_id}",
            }
        except httpx.TimeoutException:
            return {"error": "discoverAgents timed out", "agents": [], "total": 0}
        except Exception as e:  # noqa: BLE001
            logger.error(f"discoverAgents proven-filter error: {e}", exc_info=True)
            return {"error": str(e), "agents": [], "total": 0}

    # /api/v1/discover requires query length >= 3. Treat empty/short as "list all
    # active agents" — fall back to /agents/by-did pagination via a placeholder.
    effective_query = query if len(query) >= 3 else "did:"

    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT) as client:
            r = await client.get(
                f"{REGISTRY_SELF_URL}/api/v1/discover",
                params={"query": effective_query, "limit": limit, "offset": offset},
            )
        if r.status_code != 200:
            return {"error": http_refusal("discover endpoint", r), "agents": [], "total": 0}

        data = r.json()
        agents_raw = data.get("agents", [])

        # Optional client-side capability filter (HTTP endpoint doesn't support it)
        if capability:
            cap_low = capability.lower()
            agents_raw = [
                a for a in agents_raw
                if cap_low in str(a.get("tags", [])).lower()
                or cap_low in str(a.get("capabilities", {})).lower()
                or cap_low in str(a.get("description", "")).lower()
            ]

        # Map HTTP shape → MCP shape. Drop liquid_balance/staked_balance
        # (public discovery shouldn't leak balances; HTTP correctly omits them).
        agents_list = [
            {
                "did": a.get("did"),
                "name": a.get("name"),
                "description": a.get("description"),
                "status": a.get("status", "active"),
                "reputation_score": a.get("reputation_score", 0),
                "tags": a.get("tags", []),
                "capabilities": a.get("capabilities", {}),
                "pricing": a.get("pricing"),
                "created_at": a.get("created_at"),
                "last_active": a.get("last_active"),
            }
            for a in agents_raw
        ]

        return {
            "agents": agents_list,
            "total": data.get("total", len(agents_list)),
            "query": query,
            "limit": limit,
            "offset": offset,
        }

    except httpx.TimeoutException:
        return {"error": "discoverAgents timed out", "agents": [], "total": 0}
    except Exception as e:
        logger.error(f"discoverAgents error: {e}", exc_info=True)
        return {"error": str(e), "agents": [], "total": 0}


async def get_agent_profile(agent_did: str) -> Dict[str, Any]:
    """
    Get a detailed profile for a specific agent by DID.

    §pass70 — migrated to GET /api/v1/agents/by-did/{did} (public, optional-dev auth).

    Args:
        agent_did : Agent DID (e.g. did:theprotocol:abc123...)

    Returns:
        Full agent profile including name, description, reputation, balances,
        status, card_data, and creation timestamps, plus recent_attestations:
        the agent's latest verified attestations (null when the listing could
        not be read). Returns {"error": "..."} if not found.
    """
    if not agent_did:
        return {"error": "agent_did is required"}

    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT) as client:
            r = await client.get(
                f"{REGISTRY_SELF_URL}/api/v1/agents/by-did/{seg(agent_did)}",
            )
            if r.status_code == 404:
                return {"error": f"Agent with DID '{agent_did}' not found"}
            if r.status_code != 200:
                return {"error": http_refusal("agents/by-did", r)}

            data = r.json()
            # Pass through the full response; HTTP returns a superset of what MCP needs
            # (16+ extra flare_* fields the LLM may find useful for sovereign rendering).
            if isinstance(data, dict):
                data["recent_attestations"] = await _recent_verified_attestations(client, agent_did)
        return data

    except httpx.TimeoutException:
        return {"error": "getAgentProfile timed out"}
    except Exception as e:
        logger.error(f"getAgentProfile error for DID {agent_did}: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


async def _recent_verified_attestations(client: httpx.AsyncClient, agent_did: str, limit: int = 5) -> Optional[List[Dict[str, Any]]]:
    """The agent's latest attestations that still hold, newest first, from the public listing.

    ZKP Phase 3: a profile shows what its agent has proven. The profile moved to
    /agents/by-did (§pass70), which does not carry them, so they are read here.
    The listing's `verified` filter keeps revoked and expired rows, and an entry
    here does not say it was revoked, so a reader would take it for a proof that
    still holds: both are left out. None when the listing cannot be read, so a
    caller can tell it from an agent that has proven nothing.
    """
    try:
        r = await client.get(
            f"{REGISTRY_SELF_URL}/api/v1/agents/by-did/{seg(agent_did)}/attestations",
            params={"verified": "true", "limit": 50},
        )
        if r.status_code != 200:
            logger.warning(f"getAgentProfile: the attestation listing for {agent_did} answered {r.status_code}")
            return None
        items = (r.json() or {}).get("items") or []
    except Exception as exc:
        logger.warning(f"getAgentProfile: the attestation listing for {agent_did} is unreadable: {exc}")
        return None
    now = datetime.now(timezone.utc)
    held = [item for item in items if isinstance(item, dict) and _still_holds(item, now)]
    keep = ("id", "circuit_id", "verified_at", "expires_at")
    return [{k: item.get(k) for k in keep} for item in held[:limit]]


def _still_holds(item: Dict[str, Any], now: datetime) -> bool:
    """Not revoked and not past its expiry. An expiry that cannot be read keeps the
    entry, which carries the raw value for the reader."""
    if item.get("revoked_at"):
        return False
    raw = item.get("expires_at")
    if not raw:
        return True
    try:
        when = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return True
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when > now


async def get_network_stats() -> Dict[str, Any]:
    """
    Get TheProtocol network health statistics.

    ⚠️ INTENTIONALLY DB-DIRECT (documented exception, §pass70 + STRATEGY v2 §Decision A):
    This tool aggregates across 5 tables (Agent, Stake, Dispute, GovernanceProposal,
    Developer) plus calls the dynamic_apy_engine. No single HTTP endpoint covers
    this union, and 3 parallel HTTP calls would cost more than one DB transaction.
    Data is public; no PII; no auth-leak risk. Auth gate: none (Tier 1).

    Returns:
        {
          "total_agents": int, "active_agents": int,
          "total_staked": str, "tvl_pct": float,
          "active_disputes": int, "active_proposals": int,
          "network_status": "healthy" | "circuit_breaker",
          ...
        }
    """
    try:
        async with get_db_context() as db:
            total_agents = await db.scalar(select(func.count(Agent.id))) or 0
            active_agents = await db.scalar(
                select(func.count(Agent.id)).where(Agent.status == "active")
            ) or 0

            total_staked = await db.scalar(
                select(func.coalesce(func.sum(Stake.amount), 0)).where(Stake.is_active == True)
            ) or 0
            total_staked_float = float(total_staked)

            active_disputes = await db.scalar(
                select(func.count(Dispute.id)).where(
                    Dispute.status.in_(["OPEN", "PENDING", "UNDER_REVIEW"])
                )
            ) or 0

            active_proposals = await db.scalar(
                select(func.count(GovernanceProposal.id)).where(
                    GovernanceProposal.status == "VOTING"
                )
            ) or 0

            engine = get_dynamic_apy_engine()
            tvl_pct = await engine.get_current_tvl_pct(db)
            circuit_breaker = engine.check_circuit_breaker(tvl_pct)

            return {
                "total_agents": total_agents,
                "active_agents": active_agents,
                "total_staked": str(total_staked_float),
                "tvl_pct": round(tvl_pct, 2),
                "active_disputes": active_disputes,
                "active_proposals": active_proposals,
                "network_status": "circuit_breaker" if circuit_breaker else "healthy",
                "platform": "TheProtocol",
                "description": "Sovereign AI Agent Registry: DID-based identity, units and fees, governance by membership or locks",
            }

    except Exception as e:
        logger.error(f"getNetworkStats error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


async def get_governance_proposals(
    status: str = "VOTING",
    limit: int = 10,
) -> Dict[str, Any]:
    """
    List governance proposals in the Agent Senate.

    §pass70 — migrated to GET /api/v1/governance/proposals (public endpoint).
    Tier 3 auth gate dropped (HTTP is public; restricting MCP was artificial).

    Args:
        status : Proposal status filter. One of:
                 'VOTING' (default), 'PASSED', 'FAILED', 'TALLIED', 'EXPIRED', or 'all'
        limit  : Maximum results (default 10, max 50)
    """
    limit = min(max(limit, 1), 50)

    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT) as client:
            r = await client.get(
                f"{REGISTRY_SELF_URL}/api/v1/governance/proposals",
                params={"include_closed": "true", "limit": limit, "offset": 0},
            )
        if r.status_code != 200:
            return {"error": http_refusal("governance/proposals", r), "proposals": [], "total": 0}

        proposals_raw = r.json()
        if not isinstance(proposals_raw, list):
            return {"error": "unexpected response shape from governance endpoint", "proposals": [], "total": 0}

        # Apply status filter client-side (HTTP returns all when include_closed=true)
        if status.lower() != "all":
            filter_status = status.upper()
            proposals_raw = [p for p in proposals_raw if p.get("status") == filter_status]

        # Truncate descriptions for LLM compactness (parity with pre-migration behavior)
        proposals_list = []
        for p in proposals_raw:
            desc = p.get("description", "") or ""
            proposals_list.append({
                "id": p.get("id"),
                "title": p.get("title"),
                "description": desc[:300] + "..." if len(desc) > 300 else desc,
                "status": p.get("status"),
                "proposal_type": p.get("proposal_type", "standard"),
                "proposer_did": p.get("proposer_did"),
                "votes_for": p.get("votes_for", 0),
                "votes_against": p.get("votes_against", 0),
                "total_voters": p.get("total_voters", 0),
                "quorum_percent": p.get("quorum_percent", 10.0),
                "pass_percent": p.get("pass_percent", 50.0),
                "created_at": p.get("created_at"),
                "end_timestamp": p.get("end_timestamp"),
            })

        return {
            "proposals": proposals_list,
            "total": len(proposals_list),
            "status_filter": status,
        }

    except httpx.TimeoutException:
        return {"error": "getGovernanceProposals timed out", "proposals": [], "total": 0}
    except Exception as e:
        logger.error(f"getGovernanceProposals error: {e}", exc_info=True)
        return {"error": str(e), "proposals": [], "total": 0}


async def discover_registries() -> Dict[str, Any]:
    """
    List federated registries known to this TheProtocol node.

    §pass70 — migrated to GET /api/v1/public/topology (fully public endpoint).
    Returns richer data than pre-migration: visual identity (orb color, sovereign
    variant, flare encirclement) per registry, plus hop_depth and trust_domain.

    Returns:
        {
          "registries": [
            { "peer_id": str, "name": str, "base_url": str,
              "trust_domain": str, "hop_depth": int,
              "visual": {...}, "fees_summary": {...}, ... }
          ],
          "total": <int>
        }
    """
    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT) as client:
            r = await client.get(f"{REGISTRY_SELF_URL}/api/v1/public/topology")
        if r.status_code != 200:
            return {"error": http_refusal("public/topology", r), "registries": [], "total": 0}

        data = r.json()
        registries_raw = data.get("registries", [])

        # Map HTTP shape → MCP shape. Preserve the rich visual + topology slice.
        registries_list = []
        for reg in registries_raw:
            entry = {
                "peer_id": reg.get("trust_domain") or reg.get("name"),
                "name": reg.get("name"),
                "base_url": reg.get("publicUrl"),
                "trust_domain": reg.get("trust_domain"),
                "hop_depth": reg.get("hopDepth"),
                "domain": reg.get("domain"),
                "visual": reg.get("visual"),
                "fees_summary": reg.get("fees_summary"),
                "card_etag": reg.get("card_etag"),
                "card_signature_verified": reg.get("card_signature_verified"),
                "status": "ACTIVE",  # /public/topology only lists active peers
            }
            registries_list.append(entry)

        return {
            "registries": registries_list,
            "total": len(registries_list),
        }

    except httpx.TimeoutException:
        return {"error": "discoverRegistries timed out", "registries": [], "total": 0}
    except Exception as e:
        logger.error(f"discoverRegistries error: {e}", exc_info=True)
        return {"error": str(e), "registries": [], "total": 0}


async def get_apy_rates() -> Dict[str, Any]:
    """
    Get current dynamic APY rates for staking on TheProtocol.

    §pass70 — migrated to GET /api/v1/staking/apy-tiers (public endpoint).

    Returns:
        { "tiers": [{lockPeriod, label, apy, baseApy, lockPremium, minAmount, description}],
          "metadata": {...} }
    """
    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT) as client:
            r = await client.get(f"{REGISTRY_SELF_URL}/api/v1/staking/apy-tiers")
        if r.status_code != 200:
            return {"error": http_refusal("staking/apy-tiers", r)}
        return r.json()

    except httpx.TimeoutException:
        return {"error": "getLockPayoutTiers timed out"}
    except Exception as e:
        logger.error(f"getLockPayoutTiers error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


# ===========================================================================
# §pass70 Sprint 3 — Wave 3 (Tier 1 public): 6 new
# ===========================================================================

async def get_registry_card() -> Dict[str, Any]:
    """Fetch this registry's self-describing v0.6 card (identity, capabilities, fees, sovereignty, signature)."""
    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT) as client:
            r = await client.get(f"{REGISTRY_SELF_URL}/.well-known/registry-card.json")
        if r.status_code != 200:
            return {"error": http_refusal(".well-known/registry-card.json", r)}
        return r.json()
    except Exception as e:
        logger.error(f"getRegistryCard error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


async def get_fiat_tiers() -> Dict[str, Any]:
    """The fiat on-ramp's tier table; 503 where the on-ramp is switched off (fiat_onramp_enabled)."""
    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT) as client:
            r = await client.get(f"{REGISTRY_SELF_URL}/api/v1/fiat/tiers")
        if r.status_code != 200:
            return {"error": http_refusal("fiat/tiers", r)}
        return r.json()
    except Exception as e:
        logger.error(f"getFiatTiers error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


async def get_fiat_providers() -> Dict[str, Any]:
    """List enabled fiat payment providers (Stripe, Mollie) for this registry."""
    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT) as client:
            r = await client.get(f"{REGISTRY_SELF_URL}/api/v1/fiat/providers")
        if r.status_code != 200:
            return {"error": http_refusal("fiat/providers", r)}
        return r.json()
    except Exception as e:
        logger.error(f"getFiatProviders error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


async def get_fiat_quote(eur_amount: str) -> Dict[str, Any]:
    """The fiat on-ramp's quote for an EUR amount (no payment provider is called); 503 where the on-ramp is off."""
    if not eur_amount:
        return {"error": "eur_amount is required"}
    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT) as client:
            r = await client.post(
                f"{REGISTRY_SELF_URL}/api/v1/fiat/quote",
                json={"eur_amount": eur_amount},
                headers={"Content-Type": "application/json"},
            )
        if r.status_code != 200:
            return {"error": f"fiat/quote returned HTTP {r.status_code}: {r.text[:200]}"}
        return r.json()
    except Exception as e:
        logger.error(f"getFiatQuote error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


async def get_staking_global_stats() -> Dict[str, Any]:
    """Global staking aggregate: units locked, the configured tiers, stakers, and what any reward program has paid."""
    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT) as client:
            r = await client.get(f"{REGISTRY_SELF_URL}/api/v1/staking/global-stats")
        if r.status_code != 200:
            return {"error": http_refusal("staking/global-stats", r)}
        return r.json()
    except Exception as e:
        logger.error(f"getLockStats error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


async def get_network_health() -> Dict[str, Any]:
    """Network health metrics: overall_health_score, agent counts, response time percentiles, per-service status."""
    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT) as client:
            r = await client.get(f"{REGISTRY_SELF_URL}/api/v1/metrics/network-health")
        if r.status_code != 200:
            return {"error": http_refusal("metrics/network-health", r)}
        return r.json()
    except Exception as e:
        logger.error(f"getNetworkHealth error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


# ===========================================================================
# §pass70 Sprint 4 — Tier 1 public (1 new)
# ===========================================================================

async def get_federation_info() -> Dict[str, Any]:
    """Federation identity + capabilities for this registry (is_mainframe, trust_domain, federation_status, peer_count)."""
    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT) as client:
            r = await client.get(f"{REGISTRY_SELF_URL}/api/v1/federation/info")
        if r.status_code != 200:
            return {"error": http_refusal("federation/info", r)}
        return r.json()
    except Exception as e:
        logger.error(f"getFederationInfo error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


# ===========================================================================
# §pass70 Sprint 5 — Tier 1 public (1 new)
# ===========================================================================

async def get_attestation_signing_pubkey() -> Dict[str, Any]:
    """Ed25519 public key + pubkey_id + issuer_registry that signs this registry's attestation bundles.

    With it anyone can check offline that a bundle came from this registry unchanged. The proof inside a bundle is
    checked separately, with `bb verify` against the circuit's verification key (GET /api/v1/circuits/{id}/vk)."""
    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT) as client:
            r = await client.get(f"{REGISTRY_SELF_URL}/api/v1/attestations/signing-pubkey")
        if r.status_code != 200:
            return {"error": http_refusal("attestations/signing-pubkey", r)}
        return r.json()
    except Exception as e:
        logger.error(f"getAttestationSigningPubkey error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


# ===========================================================================
# §pass70 Sprint 6 — Tier 1 public (6 new)
# ===========================================================================

async def _public_get(path: str, params: Optional[Dict[str, Any]] = None, op_name: str = "") -> Dict[str, Any]:
    """Helper: GET against the registry with no auth (Tier 1 public)."""
    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT) as client:
            r = await client.get(f"{REGISTRY_SELF_URL}{path}", params=params or {})
        if r.status_code != 200:
            # B6, the public lane (§BATCH4 addendum, found by agentvault2-07): server.py renders ANY dict
            # carrying `error` as a pure tool failure and drops the body, so the RFC 7807 detail (the gate
            # phrase, the 403 reason) never reached a public caller. Same contract as the admin wrappers.
            return {"status_code": r.status_code, "upstream_error": http_refusal(f"{op_name or path}", r),
                    "body": (r.text or "")[:300], "path": path}
        return r.json()
    except Exception as e:
        logger.error(f"{op_name or path} error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


async def get_achievement_catalog() -> Dict[str, Any]:
    """List the achievement catalog (badges, names, descriptions, payouts in units). Returns {achievements:[], total}. Public, no auth."""
    return await _public_get("/api/v1/achievements/catalog", op_name="getAchievementCatalog")


async def get_attestation_health() -> Dict[str, Any]:
    """Attestation service health check. Returns {status: 'healthy', service}. Public — no auth."""
    return await _public_get("/api/v1/attestations/health", op_name="getAttestationHealth")


async def get_circuits() -> Dict[str, Any]:
    """Catalog of the zero-knowledge circuits this registry serves. Public, no auth.

    The four v2.0.0 circuits are status "active", each with its public inputs, its one public output (a Poseidon2
    commitment), the policy limits this registry enforces, and acir_url, source_url, nargo_toml_url, vk_url and
    metadata_url. The four v1.0.0 ids are status "retired" with superseded_by naming the v2.0.0 circuit."""
    return await _public_get("/api/v1/circuits/", op_name="getCircuits")


async def get_staking_distributions(limit: int = 30) -> Dict[str, Any]:
    """List the recent runs of the reward distributor for locked units. Public, no auth."""
    body = await _public_get(
        "/api/v1/staking/rewards/distributions",
        params={"limit": min(max(int(limit), 1), 100)},
        op_name="getLockPayoutRuns",
    )
    if isinstance(body, list):
        return {"distributions": body, "total": len(body)}
    return body


async def get_staking_distribution_stats() -> Dict[str, Any]:
    """Aggregate staking-distribution stats: total_distributed (lifetime), distribution_count, unique_stakers_rewarded, last_distribution. Public — no auth."""
    return await _public_get("/api/v1/staking/rewards/stats/summary", op_name="getLockPayoutStats")


async def reverify_attestation(attestation_id: str) -> Dict[str, Any]:
    """Re-run the verification of a stored attestation: its proof bytes and stated public inputs go through the same
    checks as on submit (inputs bound to the proof, policy limits, then bb verify). Answers with {attestation_id, circuit_id,
    verified, re_verified_at, public_inputs, failure_reason, revoked, expired}; a revoked or expired attestation, and a
    row with no proof bytes (proof_of_reputation), answer verified false with the reason. Public, no auth."""
    if not attestation_id:
        return {"error": "attestation_id is required"}
    return await _public_get(
        f"/api/v1/attestations/{seg(attestation_id)}/verify",
        op_name="reverifyAttestation",
    )


# ===========================================================================
# §pass70 Sprint 8 — Tier 1 public (1 new)
# ===========================================================================

async def get_system_activity_feed(limit: int = 50) -> Dict[str, Any]:
    """Aggregate system activity feed (recent registry/agent/economic events). Returns {items:[], total}. Public — no auth."""
    return await _public_get(
        "/api/v1/system/activity-feed",
        params={"limit": min(max(int(limit), 1), 50)},
        op_name="getSystemActivityFeed",
    )


# ===========================================================================
# §pass70 Sprint 9 — Tier 1 public (10 new)
# ===========================================================================

async def get_circuit_acir(circuit_id: str) -> Dict[str, Any]:
    """Fetch a circuit's compiled ACIR bytecode (what `bb prove -b` takes) and report its size, content type and first
    100 bytes as hex (preview_b64). Use a v2.0.0 id; the retired v1.0.0 ids may have no bytecode. Public, no auth."""
    if not circuit_id:
        return {"error": "circuit_id is required"}
    # ACIR endpoint may return binary — wrap as raw text/size
    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT) as client:
            r = await client.get(f"{REGISTRY_SELF_URL}/api/v1/circuits/{seg(circuit_id)}/acir")
        if r.status_code != 200:
            return {"error": http_refusal(f"circuits/{circuit_id}/acir", r)}
        return {"circuit_id": circuit_id, "content_type": r.headers.get("content-type"), "size_bytes": len(r.content), "preview_b64": (r.content[:100].hex() if r.content else "")}
    except Exception as e:
        logger.error(f"getCircuitACIR error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


async def get_circuit_source(circuit_id: str) -> Dict[str, Any]:
    """Download Noir circuit source (main.nr) for a ZKP circuit. Public — no auth. Returns source code as text."""
    if not circuit_id:
        return {"error": "circuit_id is required"}
    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT) as client:
            r = await client.get(f"{REGISTRY_SELF_URL}/api/v1/circuits/{seg(circuit_id)}/source")
        if r.status_code != 200:
            return {"error": http_refusal(f"circuits/{circuit_id}/source", r)}
        return {"circuit_id": circuit_id, "language": "noir", "source": r.text}
    except Exception as e:
        logger.error(f"getCircuitSource error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


async def get_circuit_nargo_toml(circuit_id: str) -> Dict[str, Any]:
    """Download Nargo.toml manifest for a ZKP circuit. Public — no auth."""
    if not circuit_id:
        return {"error": "circuit_id is required"}
    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT) as client:
            r = await client.get(f"{REGISTRY_SELF_URL}/api/v1/circuits/{seg(circuit_id)}/nargo-toml")
        if r.status_code != 200:
            return {"error": http_refusal(f"circuits/{circuit_id}/nargo-toml", r)}
        return {"circuit_id": circuit_id, "nargo_toml": r.text}
    except Exception as e:
        logger.error(f"getCircuitNargoToml error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


async def get_circuit_verification_key(circuit_id: str) -> Dict[str, Any]:
    """Fetch a circuit's UltraHonk verification key (base64) and its sha256. With an attestation's proof bytes and
    public inputs it lets anyone run `bb verify` offline, without trusting this registry. Use a v2.0.0 id; retired
    v1.0.0 circuits publish no key. Public, no auth."""
    if not circuit_id:
        return {"error": "circuit_id is required"}
    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT) as client:
            r = await client.get(f"{REGISTRY_SELF_URL}/api/v1/circuits/{seg(circuit_id)}/vk")
        if r.status_code != 200:
            return {"error": http_refusal(f"circuits/{circuit_id}/vk", r)}
        return {
            "circuit_id": circuit_id,
            "verification_key_b64": base64.b64encode(r.content).decode("ascii"),
            "size_bytes": len(r.content),
            "sha256": hashlib.sha256(r.content).hexdigest(),
        }
    except Exception as e:
        logger.error(f"getCircuitVerificationKey error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


async def get_circuit_metadata(circuit_id: str) -> Dict[str, Any]:
    """Fetch a circuit's metadata: its statement, public inputs and outputs, private inputs, limits, the policy
    limits this registry enforces (policy_in_force) and the sha256 of its verification key. Public, no auth."""
    if not circuit_id:
        return {"error": "circuit_id is required"}
    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT) as client:
            r = await client.get(f"{REGISTRY_SELF_URL}/api/v1/circuits/{seg(circuit_id)}/metadata")
        if r.status_code != 200:
            return {"error": http_refusal(f"circuits/{circuit_id}/metadata", r)}
        return {"circuit_id": circuit_id, "metadata": r.json()}
    except Exception as e:
        logger.error(f"getCircuitMetadata error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


async def get_pipeline_templates() -> Dict[str, Any]:
    """List CI/CD pipeline templates available for agents. Public — no auth."""
    return await _public_get("/api/v1/pipeline-templates", op_name="getPipelineTemplates")


async def get_agent_by_did(did: str) -> Dict[str, Any]:
    """Get agent profile by DID (public profile view, no PII). Public — no auth."""
    if not did:
        return {"error": "did is required"}
    return await _public_get(f"/api/v1/agents/by-did/{seg(did)}", op_name="getAgentByDID")


async def get_agent_card_export(did: str) -> Dict[str, Any]:
    """Export the canonical Agent Card for an agent (per §pass36 agent-as-canonical-card-source). Public — no auth."""
    if not did:
        return {"error": "did is required"}
    return await _public_get(f"/api/v1/agents/{seg(did)}/card-export", op_name="getAgentCardExport")


async def get_agent_public_key(did: str) -> Dict[str, Any]:
    """Get an agent's did-jwt public key (JWK, algorithm, extension URI); 404 when it registered none. Public, no auth."""
    if not did:
        return {"error": "did is required"}
    return await _public_get(f"/api/v1/agents/{seg(did)}/public-key", op_name="getAgentPublicKey")


async def get_teg_price() -> Dict[str, Any]:
    """Answers that units carry no price (the route keeps its keys for older clients). Public, no auth."""
    return await _public_get("/api/v1/teg/price", op_name="getTegPrice")


async def get_teg_reputation_rankings(limit: int = 50) -> Dict[str, Any]:
    """Agents ranked by the TEG's own reputation score (moved by reputation signals, audit flags and an administrator's
    recalculation), each with its tier and verified track record. Not the EigenTrust score. Public, no auth."""
    return await _public_get(
        "/api/v1/teg/reputation/rankings",
        params={"limit": min(max(int(limit), 1), 200)},
        op_name="getTegReputationRankings",
    )


async def get_agent_locations() -> Dict[str, Any]:
    """Get agent locations for globe visualization (lat/lng/agent_did pairs). Public — no auth."""
    return await _public_get("/api/v1/agents/locations/", op_name="getAgentLocations")


# ===========================================================================
# §pass70 Sprint 10 — Tier 1 public (2 new)
# ===========================================================================

async def get_fiat_stats_public() -> Dict[str, Any]:
    """Anonymized aggregate statistics of the fiat on-ramp; 503 where the on-ramp is off. Public, no auth."""
    return await _public_get("/api/v1/fiat/stats/public", op_name="getFiatStatsPublic")


async def get_auth_registration_config() -> Dict[str, Any]:
    """Public auth registration configuration (invite-code required? captcha? email-verify flow?). Public — no auth."""
    return await _public_get("/api/v1/auth/registration-config", op_name="getAuthRegistrationConfig")


# ===========================================================================
# §pass70 Sprint 11 — Tier 1 public (3 new)
# ===========================================================================

async def get_agent_flare(did: str) -> Dict[str, Any]:
    """Get an agent's flare (cosmetic visual badge — encirclement variant, corner badge, overlay) by DID. Public — no auth."""
    if not did:
        return {"error": "did is required"}
    return await _public_get(f"/api/v1/fiat/flare/agent/{seg(did)}", op_name="getAgentFlare")


async def get_developer_flare(developer_id: int) -> Dict[str, Any]:
    """Get a developer's flare (cosmetic visual badge tier) by id. Public — no auth."""
    if developer_id is None:
        return {"error": "developer_id is required"}
    return await _public_get(f"/api/v1/fiat/flare/developer/{int(developer_id)}", op_name="getDeveloperFlare")


async def get_staking_apy_tiers_teg() -> Dict[str, Any]:
    """The TEG's staking tiers (none where staking or its rewards are off). Public, no auth."""
    return await _public_get("/api/v1/teg/staking/apy-tiers", op_name="getLockPayoutTiersTeg")


# ===========================================================================
# §pass70 Sprint 12 — Tier 1 public (8 new — federation + SPIRE)
# ===========================================================================

async def get_federation_health_check() -> Dict[str, Any]:
    """Federation subsystem health check. Public — no auth."""
    return await _public_get("/api/v1/federation/health-check", op_name="getFederationHealthCheck")


async def get_federation_network_stats() -> Dict[str, Any]:
    """Aggregate federation network statistics (peer count, agent count, total volume). Public."""
    return await _public_get("/api/v1/federation/network-stats", op_name="getFederationNetworkStats")


async def list_federation_registries() -> Dict[str, Any]:
    """List all federated registries known to this node (public view). Public — no auth.

    Returns {registries: [...], total: N}. Wrapping in envelope for MCP-client
    shape stability (upstream may return list or auth-error dict).
    """
    body = await _public_get("/api/v1/federation/registries", op_name="listFederationRegistries")
    if isinstance(body, list):
        return {"registries": body, "total": len(body)}
    if isinstance(body, dict):
        if "registries" in body:
            body.setdefault("total", len(body.get("registries") or []))
            return body
        return body  # §MCPTEST30 (V0548): the failure as it came; it used to read as an empty list
    return {"error": "listFederationRegistries: the route answered neither a list nor an object"}


async def list_federation_agent_cards(limit: int = 100, since: Optional[str] = None) -> Dict[str, Any]:
    """List agent cards visible via federation (cross-registry agent index), changed since `since` (the feed's own
    cursor, an ISO timestamp).

    Returns {agent_cards: [...], total: N, limit}. §MCPTEST30 (2026-10-01): the survey's UNDECLARED class: the feed reads `since`, never
    `offset`, so every page was the first.
    §MCPTEST30 (V0547): its route authenticates only a federation PEER (mTLS, the internal secret or a federation licence),
    which no MCP caller holds, so it answers the refusal; it used to turn that 401 into an empty list for every caller."""
    params: Dict[str, Any] = {"limit": min(max(int(limit), 1), 500)}
    if since:
        params["since"] = since
    body = await _public_get("/api/v1/federation/agent-cards", params=params, op_name="listFederationAgentCards")
    if isinstance(body, list):
        return {"agent_cards": body, "total": len(body), "limit": limit}
    if isinstance(body, dict):
        if "agent_cards" in body:
            body.setdefault("total", len(body.get("agent_cards") or []))
            return body
        return body   # the refusal (_public_get's envelope) or an answer of another shape, as it came
    return {"error": "listFederationAgentCards: the feed answered neither a list nor an object"}


async def list_federation_registry_cards() -> Dict[str, Any]:
    """List the Registry Cards from all federated peers.

    Returns {registry_cards: [...], total: N}.
    §MCPTEST30 (V0547): its route authenticates only a federation PEER (mTLS, the internal secret or a federation licence),
    which no MCP caller holds, so it answers the refusal; it used to turn that 401 into an empty list for every caller.
    """
    body = await _public_get("/api/v1/federation/registry-cards", op_name="listFederationRegistryCards")
    if isinstance(body, list):
        return {"registry_cards": body, "total": len(body)}
    if isinstance(body, dict):
        if "registry_cards" in body:
            body.setdefault("total", len(body.get("registry_cards") or []))
            return body
        return body   # the refusal (_public_get's envelope) or an answer of another shape, as it came
    return {"error": "listFederationRegistryCards: the feed answered neither a list nor an object"}


async def get_federation_policy_compliance() -> Dict[str, Any]:
    """Federation policy compliance summary (per-peer adherence to fee/policy commitments).

    Returns {peers: [...], total: N} when scoped per-peer, or whatever
    envelope the upstream emits. Wrapped so MCP clients see a dict.
    §MCPTEST30 (V0547): its route authenticates only a federation PEER (mTLS, the internal secret or a federation licence),
    which no MCP caller holds, so it answers the refusal; it used to turn that 401 into an empty list for every caller.
    """
    body = await _public_get("/api/v1/federation/policy-compliance", op_name="getFederationPolicyCompliance")
    if isinstance(body, list):
        return {"peers": body, "total": len(body)}
    if isinstance(body, dict):
        if "peers" in body:
            body.setdefault("total", len(body.get("peers") or []))
            return body
        return body   # the refusal (_public_get's envelope) or an answer of another shape, as it came
    return {"error": "getFederationPolicyCompliance: the route answered neither a list nor an object"}


async def get_federation_registry_health_profile(peer_id_or_name: str) -> Dict[str, Any]:
    """Detailed health profile for a single federated peer (latency, uptime, drift history). Public — no auth."""
    if not peer_id_or_name:
        return {"error": "peer_id_or_name is required"}
    return await _public_get(f"/api/v1/federation/registry/{seg(peer_id_or_name)}/health-profile", op_name="getFederationRegistryHealthProfile")


async def get_spire_jwks() -> Dict[str, Any]:
    """SPIRE JWKS for this registry (JWT public keys used by SPIRE for federation auth). Public — no auth."""
    return await _public_get("/api/v1/spire/jwks", op_name="getSpireJWKS")


# ===========================================================================
# §pass70 Sprint 17 — Tier 1 public (8 new)
# ===========================================================================

async def list_agent_cards(limit: int = 100, offset: int = 0) -> Dict[str, Any]:
    """List agent cards on this registry (canonical agent metadata). Public — no auth."""
    # §MCPTEST30 (2026-10-01): the survey's UNDECLARED class: the route pages by `skip`; `offset` was dropped, so page 2 was page 1
    return await _public_get("/api/v1/agent-cards/", params={"limit": min(max(int(limit), 1), 500), "skip": max(int(offset), 0)}, op_name="listAgentCards")


async def get_agent_card_by_hri(human_readable_id: str) -> Dict[str, Any]:
    """Get agent card by Human-Readable ID (HRI). Public — no auth."""
    if not human_readable_id:
        return {"error": "human_readable_id is required"}
    return await _public_get("/api/v1/agent-cards/by-hri", params={"hri": human_readable_id}, op_name="getAgentCardByHRI")


async def get_agent_card_by_human_readable_id(human_readable_id: str) -> Dict[str, Any]:
    """Get agent card by HRI path-form (alternative to query-form by-hri). Public — no auth."""
    if not human_readable_id:
        return {"error": "human_readable_id is required"}
    return await _public_get(f"/api/v1/agent-cards/id/{seg(human_readable_id)}", op_name="getAgentCardByHumanReadableId")


async def get_agent_card_by_id(card_id: str) -> Dict[str, Any]:
    """Get agent card by id (canonical). Public — no auth."""
    if not card_id:
        return {"error": "card_id is required"}
    return await _public_get(f"/api/v1/agent-cards/{seg(card_id)}", op_name="getAgentCardById")


async def get_community_announcements(auth: Any) -> Dict[str, Any]:
    """Get the community page's announcements (active broadcasts, newest first). Developer JWT.

    Returns {announcements: [...], total: N}.

    §MCPTEST30 (V0538): GET /community/announcements authenticates a developer and this tool sent no credential, then
    turned the 401 into an empty feed, so every caller was told there were no announcements (round 10 read it as a
    pass). It sends the caller's token now, and a refusal is an error, never an empty list."""
    from agentvault_registry.mcp.tools_developer import _dev_request
    body = await _dev_request(auth, "GET", "/api/v1/community/announcements")
    if isinstance(body, list):
        return {"announcements": body, "total": len(body)}
    if isinstance(body, dict) and "announcements" in body:
        body.setdefault("total", len(body.get("announcements") or []))
        return body
    if isinstance(body, dict) and body.get("error"):
        return body
    return {"error": "getCommunityAnnouncements: the feed answered neither a list nor {announcements}"}


async def get_downloads_manifest() -> Dict[str, Any]:
    """Get downloads manifest (available client SDK + bridge artifacts with versions/hashes). Public — no auth."""
    return await _public_get("/api/v1/downloads/manifest", op_name="getDownloadsManifest")


async def get_stack_health() -> Dict[str, Any]:
    """Get stack-level health snapshot (registry + TEG + EventStore + SPIRE roll-up). Public — no auth."""
    return await _public_get("/api/v1/stack-health", op_name="getStackHealth")


async def get_activity_feed_by_type(event_type: str, limit: int = 50) -> Dict[str, Any]:
    """Get system activity feed filtered by a specific event_type. Public — no auth."""
    if not event_type:
        return {"error": "event_type is required"}
    return await _public_get(f"/api/v1/system/activity-feed/by-type/{seg(event_type)}", params={"limit": min(max(int(limit), 1), 50)}, op_name="getActivityFeedByType")


# ===========================================================================
# §pass70 Sprint 18 — Tier 1 public (21 new — agents subpaths + auth public + .well-known)
# ===========================================================================

async def _public_post(path: str, json_body: Optional[Dict[str, Any]] = None, op_name: str = "") -> Dict[str, Any]:
    """Helper: POST against registry with no auth (public mutations like password reset)."""
    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT) as client:
            r = await client.post(f"{REGISTRY_SELF_URL}{path}", json=json_body or {})
        if r.status_code not in (200, 201, 202, 204):
            return {"error": http_refusal(f"{op_name or path}", r), "body": (r.text or "")[:300]}
        try:
            return r.json()
        except Exception:
            return {"status": "ok"}
    except Exception as e:
        logger.error(f"{op_name or path} error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


async def get_agent_locations_operator() -> Dict[str, Any]:
    """Get registry operator location (lat/lng + city for the operator who runs this registry). Public."""
    return await _public_get("/api/v1/agents/locations/operator", op_name="getAgentLocationsOperator")


async def get_agent_locations_emission_policies() -> Dict[str, Any]:
    """Get event emission policies (internal cluster sync — public read for transparency). Public."""
    return await _public_get("/api/v1/agents/locations/emission-policies", op_name="getAgentLocationsEmissionPolicies")


async def get_agent_locations_trusted_registries() -> Dict[str, Any]:
    """Get trusted federated registry URLs (internal — public for transparency). Public."""
    return await _public_get("/api/v1/agents/locations/trusted-registries", op_name="getAgentLocationsTrustedRegistries")


async def get_agent_attestations_by_did(agent_did: str, limit: int = 50) -> Dict[str, Any]:
    """List attestations for an agent by DID (public Phase 1). Public."""
    if not agent_did:
        return {"error": "agent_did is required"}
    return await _public_get(f"/api/v1/agents/by-did/{seg(agent_did)}/attestations", params={"limit": min(max(int(limit), 1), 200)}, op_name="getAgentAttestationsByDID")


async def get_agent_attestation_schedules_by_did(agent_did: str) -> Dict[str, Any]:
    """List attestation schedules for an agent by DID (public Phase 5). Public."""
    if not agent_did:
        return {"error": "agent_did is required"}
    return await _public_get(f"/api/v1/agents/by-did/{seg(agent_did)}/attestation-schedules", op_name="getAgentAttestationSchedulesByDID")


async def get_agent_anp(agent_did: str) -> Dict[str, Any]:
    """ANP (Agent Network Protocol) description for an agent. Public."""
    if not agent_did:
        return {"error": "agent_did is required"}
    return await _public_get(f"/api/v1/agents/{seg(agent_did)}/ad.json", op_name="getAgentANP")


async def get_agent_did_doc(agent_did: str) -> Dict[str, Any]:
    """W3C DID document for an agent (DID standard resolution). Public."""
    if not agent_did:
        return {"error": "agent_did is required"}
    return await _public_get(f"/api/v1/agents/{seg(agent_did)}/did.json", op_name="getAgentDIDDoc")


async def get_public_showcase_agents() -> Dict[str, Any]:
    """List showcase agents for the public landing page. Public."""
    return await _public_get("/api/v1/public/showcase/agents", op_name="getPublicShowcaseAgents")


async def get_public_event_store_recent(limit: int = 50) -> Dict[str, Any]:
    """Public view of recent EventStore events (public-safe subset). Public.

    Returns {events: [...], total: N}.
    """
    body = await _public_get("/api/v1/public/eventstore-recent",
                              params={"limit": min(max(int(limit), 1), 200)},
                              op_name="getPublicEventStoreRecent")
    if isinstance(body, list):
        return {"events": body, "total": len(body)}
    if isinstance(body, dict):
        if "events" in body:
            body.setdefault("total", len(body.get("events") or []))
            return body
        return body  # §MCPTEST30 (V0548): the failure as it came; it used to read as an empty list
    return {"error": "getPublicEventStoreRecent: the route answered neither a list nor an object"}


async def get_public_event_store_stats() -> Dict[str, Any]:
    """Public EventStore aggregate stats (total events, unique agents). Public."""
    return await _public_get("/api/v1/public/eventstore-stats", op_name="getPublicEventStoreStats")


async def get_well_known_registry_card() -> Dict[str, Any]:
    """Get this registry's full Registry Card v0.6 from /.well-known/. Public canonical surface."""
    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT) as client:
            r = await client.get(f"{REGISTRY_SELF_URL}/.well-known/registry-card.json")
        if r.status_code != 200:
            return {"error": http_refusal("/.well-known/registry-card.json", r)}
        return r.json()
    except Exception as e:
        logger.error(f"getWellKnownRegistryCard error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


async def get_well_known_dev_jwks() -> Dict[str, Any]:
    """Get developer JWKS from /.well-known/ (used for verifying developer-signed payloads). Public."""
    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT) as client:
            r = await client.get(f"{REGISTRY_SELF_URL}/.well-known/dev-jwks.json")
        if r.status_code != 200:
            return {"error": http_refusal("/.well-known/dev-jwks.json", r)}
        return r.json()
    except Exception as e:
        logger.error(f"getWellKnownDevJwks error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


async def get_fiat_purchase_session(session_id: str) -> Dict[str, Any]:
    """Get fiat purchase status by Stripe session_id (public-by-session-id for success-page polling). Public."""
    if not session_id:
        return {"error": "session_id is required"}
    return await _public_get(f"/api/v1/fiat/purchase/{seg(session_id)}", op_name="getFiatPurchaseSession")


# Auth public mutations (login/recovery flow — no JWT required)

async def auth_register(email: str, password: str, name: Optional[str] = None, invite_code: Optional[str] = None) -> Dict[str, Any]:
    """DESTRUCTIVE: register a new developer account. Public — no auth required.

    `name` is the unique developer display name (API requires it, min 3 chars).
    If omitted it is derived from the email local-part so the tool stays usable
    from a 2-field (email+password) call.
    """
    if not email or not password:
        return {"error": "email and password are required"}
    if not name or not str(name).strip():
        local = (email.split("@")[0] or "dev").strip()
        name = local if len(local) >= 3 else f"{local}-dev"
    body: Dict[str, Any] = {"name": name, "email": email, "password": password}
    if invite_code:
        body["invite_code"] = invite_code
    return await _public_post("/api/v1/auth/register", json_body=body, op_name="authRegister")


async def auth_forgot_password(email: str) -> Dict[str, Any]:
    """DESTRUCTIVE: request a password reset email. Public — no auth required."""
    if not email:
        return {"error": "email is required"}
    return await _public_post("/api/v1/auth/forgot-password", json_body={"email": email}, op_name="authForgotPassword")


async def auth_reset_password(token: str, new_password: str) -> Dict[str, Any]:
    """DESTRUCTIVE: reset password via emailed token. Public — no auth required."""
    if not token or not new_password:
        return {"error": "token and new_password are required"}
    return await _public_post("/api/v1/auth/reset-password", json_body={"token": token, "new_password": new_password}, op_name="authResetPassword")


async def auth_set_new_password(token: str, new_password: str) -> Dict[str, Any]:
    """DESTRUCTIVE: set new password after recovery flow. Public — no auth required."""
    if not token or not new_password:
        return {"error": "token and new_password are required"}
    # §MCPTEST30 (2026-10-01): the survey's BODY_UNDECLARED class: the route reads the recovery token as a BEARER (verify_temp_password_token); in the
    # body it was dropped and every call answered 401
    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT) as client:
            r = await client.post(f"{REGISTRY_SELF_URL}/api/v1/auth/set-new-password", json={"new_password": new_password},
                                  headers={"Authorization": f"Bearer {token}"})
        if r.status_code not in (200, 201):
            return {"error": http_refusal("authSetNewPassword", r), "body": (r.text or "")[:300]}
        return r.json()
    except Exception as e:  # noqa: BLE001
        return {"error": format_tool_exception(e)}


async def auth_recover_account(email: str, recovery_key: str) -> Dict[str, Any]:
    """Recover account via recovery key. Public — no auth required."""
    if not email or not recovery_key:
        return {"error": "email and recovery_key are required"}
    return await _public_post("/api/v1/auth/recover-account", json_body={"email": email, "recovery_key": recovery_key}, op_name="authRecoverAccount")


async def auth_resend_verification(email: str) -> Dict[str, Any]:
    """Resend email verification link. Public — no auth required."""
    if not email:
        return {"error": "email is required"}
    return await _public_post("/api/v1/auth/resend-verification", json_body={"email": email}, op_name="authResendVerification")


async def auth_verify_email(token: str) -> Dict[str, Any]:
    """Verify email address via emailed token. Public — no auth required (token IS the auth)."""
    if not token:
        return {"error": "token is required"}
    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT) as client:
            r = await client.get(f"{REGISTRY_SELF_URL}/api/v1/auth/verify-email", params={"token": token})
        if r.status_code == 303:
            # §MCPTEST30 (V0514): the route answers EVERY verification with a 303 to the console's email-verification
            # page and puts the outcome in that link's query: status=success (already=true when the address was
            # verified before) or status=failed with a reason. Read as a refusal, a SUCCESSFUL verification through this
            # tool said "Error", and a failed one lost its reason.
            from urllib.parse import parse_qs
            loc = r.headers.get("location") or ""
            q = parse_qs(loc.split("?", 1)[1]) if "?" in loc else {}
            outcome = (q.get("status") or [""])[0]
            if outcome == "success":
                return {"verified": True, "already_verified": (q.get("already") or [""])[0] == "true"}
            if outcome == "failed":
                return {"error": f"auth/verify-email returned HTTP 303: verification failed "
                                 f"({(q.get('reason') or ['unknown'])[0]})"}
        if r.status_code not in (200, 201):
            return {"error": http_refusal("auth/verify-email", r), "body": (r.text or "")[:300]}
        return r.json()
    except Exception as e:
        logger.error(f"authVerifyEmail error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


async def auth_validate_2fa(login_token: str, code: str) -> Dict[str, Any]:
    """Validate 2FA TOTP code during login flow. Public — login_token (the login's partial token) is the gate."""
    if not login_token or not code:
        return {"error": "login_token and code are required"}
    return await _public_post("/api/v1/auth/2fa/validate", json_body={"partial_token": login_token, "code": code}, op_name="authValidate2FA")


# ===========================================================================
# §pass70 Sprint 19 — Tier 1 public (4 new)
# ===========================================================================

async def get_mcp_stdio_bridge_js() -> Dict[str, Any]:
    """Download MCP stdio bridge JavaScript artifact. Public."""
    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT) as client:
            r = await client.get(f"{REGISTRY_SELF_URL}/api/v1/downloads/mcp-stdio-bridge.js")
        if r.status_code != 200:
            return {"error": http_refusal("downloads/mcp-stdio-bridge.js", r)}
        return {"content_type": r.headers.get("content-type"), "size_bytes": len(r.text), "preview": r.text[:1500]}
    except Exception as e:
        logger.error(f"getMcpStdioBridgeJs error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


async def get_mcp_stdio_bridge_admin_js() -> Dict[str, Any]:
    """Download MCP admin stdio bridge JavaScript artifact. Public."""
    try:
        async with mcp_http_client(timeout=HTTPX_TIMEOUT) as client:
            r = await client.get(f"{REGISTRY_SELF_URL}/api/v1/downloads/mcp-stdio-bridge-admin.js")
        if r.status_code != 200:
            return {"error": http_refusal("downloads/mcp-stdio-bridge-admin.js", r)}
        return {"content_type": r.headers.get("content-type"), "size_bytes": len(r.text), "preview": r.text[:1500]}
    except Exception as e:
        logger.error(f"getMcpStdioBridgeAdminJs error: {e}", exc_info=True)
        return {"error": format_tool_exception(e)}


async def get_public_registry_config() -> Dict[str, Any]:
    """Get public registry configuration (operator-visible config, no secrets). Public."""
    return await _public_get("/api/v1/public/registry-config", op_name="getPublicRegistryConfig")


async def verify_public_attestation_bundle(bundle: Dict[str, Any], issuer_pubkey_b64: Optional[str] = None) -> Dict[str, Any]:
    """Check a signed attestation bundle's Ed25519 signature: against this registry's own key, or against
    issuer_pubkey_b64 when given (a bundle from another registry). It does not run bb: to check the proof itself,
    run `bb verify` on the bundle's proof bytes with the circuit's verification key (/api/v1/circuits/{id}/vk).
    Public."""
    if not isinstance(bundle, dict):
        return {"error": "bundle must be an object"}
    body: Dict[str, Any] = {"bundle": bundle}
    if issuer_pubkey_b64:
        body["issuer_pubkey_b64"] = issuer_pubkey_b64
    return await _public_post("/api/v1/public/attestations/verify-bundle", json_body=body, op_name="verifyPublicAttestationBundle")


# ===========================================================================
# §pass70 Sprint 20 — Tier 1 public (5 new)
# ===========================================================================

async def get_public_showcase_call(service: str, input: str, task_type: Optional[str] = None) -> Dict[str, Any]:
    """Call a public showcase agent service (the landing page's demo call; rate-limited per IP, no auth). Public."""
    if not service:
        return {"error": "service is required (see getPublicShowcaseAgents)"}
    body: Dict[str, Any] = {"service": service, "input": input or ""}
    if task_type:
        body["task_type"] = task_type
    return await _public_post("/api/v1/public/showcase/call", json_body=body, op_name="getPublicShowcaseCall")


async def auth_recover_2fa(login_token: str, backup_code: str) -> Dict[str, Any]:
    """Use a backup code to bypass 2FA during login. Public — login_token (the login's partial token) is the gate."""
    if not login_token or not backup_code:
        return {"error": "login_token and backup_code are required"}
    return await _public_post("/api/v1/auth/2fa/recover", json_body={"partial_token": login_token, "backup_code": backup_code}, op_name="authRecover2FA")


async def list_public_operator_applications() -> Dict[str, Any]:
    """This registry publishes no list of operator applications: its /operator-applications route takes submissions
    (POST) only. The tool used to GET it, meet 405 and answer an empty list, which read as "nobody has applied"."""
    return {"error": "no public listing of operator applications exists on this registry "
                     "(/api/v1/operator-applications accepts submissions only)",
            "applications": None, "total": None}


async def get_agent_by_did_alt(did: str) -> Dict[str, Any]:
    """Get agent by DID via alt path (deprecated synonym for getAgentByDID). Public."""
    if not did:
        return {"error": "did is required"}
    return await _public_get(f"/api/v1/agents/did/{seg(did)}", op_name="getAgentByDIDAlt")


# ===========================================================================
# §pass70 Sprint 21 — Tier 1 public (7 new — arena game)
# ===========================================================================

_ARENA_STATUS = {"waiting": lambda m: not m.get("started"), "active": lambda m: m.get("started") and not m.get("finished"),
                  "finished": lambda m: bool(m.get("finished"))}


async def list_arena_matches(limit: int = 50, status: Optional[str] = None) -> Dict[str, Any]:
    """List arena matches (game matches between agents), active first. Public — no auth.

    §MCPTEST30 (2026-10-01): the survey's UNDECLARED class: the route takes no parameter (it serves every match), so `limit` and `status`
    were dropped; both are applied here now, `status` read from the match's own started/finished flags."""
    if status and status not in _ARENA_STATUS:
        return {"error": f"status must be one of {', '.join(_ARENA_STATUS)}"}
    body = await _public_get("/api/v1/arena/matches", op_name="listArenaMatches")
    rows = body.get("matches") if isinstance(body, dict) else None
    if isinstance(rows, list):
        if status:
            rows = [m for m in rows if isinstance(m, dict) and _ARENA_STATUS[status](m)]
        return {**body, "matches": rows[:min(max(int(limit), 1), 500)], "total": len(rows)}
    return body


async def get_arena_match(match_id: str) -> Dict[str, Any]:
    """Get a single arena match by id. Public."""
    if not match_id:
        return {"error": "match_id is required"}
    return await _public_get(f"/api/v1/arena/matches/{seg(match_id)}", op_name="getArenaMatch")


async def get_arena_match_bets(match_id: str) -> Dict[str, Any]:
    """List bets on an arena match. Public."""
    if not match_id:
        return {"error": "match_id is required"}
    return await _public_get(f"/api/v1/arena/matches/{seg(match_id)}/bets", op_name="getArenaMatchBets")


async def get_arena_match_map(match_id: str) -> Dict[str, Any]:
    """Get the map/layout for an arena match. Public."""
    if not match_id:
        return {"error": "match_id is required"}
    return await _public_get(f"/api/v1/arena/matches/{seg(match_id)}/map", op_name="getArenaMatchMap")


async def get_arena_leaderboard(game_type: str) -> Dict[str, Any]:
    """Get leaderboard for a specific arena game type (snake/td/trading/etc.). Public."""
    if not game_type:
        return {"error": "game_type is required"}
    return await _public_get(f"/api/v1/arena/leaderboard/{seg(game_type)}", op_name="getArenaLeaderboard")


async def get_arena_agent_stats(agent_did: str) -> Dict[str, Any]:
    """Get arena stats for an agent (matches played, wins, ELO). Public."""
    if not agent_did:
        return {"error": "agent_did is required"}
    return await _public_get(f"/api/v1/arena/agent-stats/{seg(agent_did)}", op_name="getArenaAgentStats")


async def create_arena_match(auth, match_config: Dict[str, Any]) -> Dict[str, Any]:
    """Create a new Robo Wars match filled with bots. Administrators only (D6-634): the route refuses any other
    developer, so this tool is developer-tier and forwards the caller's credential. The route reads `mode` and
    `add_bots` as query parameters (it sizes the match from add_bots); the tool used to post them as a body the
    route never read."""
    if not isinstance(match_config, dict):
        return {"error": "match_config must be an object"}
    from .tools_developer import _dev_request  # local: tools_developer is the developer-credential helper
    params = {k: match_config[k] for k in ("mode", "add_bots") if match_config.get(k) is not None}
    return await _dev_request(auth, "POST", "/api/v1/arena/matches", params=params or None)


# ---------------------------------------------------------------------------
# GÖDEL FORGE — public arena reads (batch-3 FG2-6). 403 body when the arena is dark.
# ---------------------------------------------------------------------------

async def get_forge_status() -> Dict[str, Any]:
    """Arena flags + counts (verifier pool, quorum scores, lineage forks). 403 when dark."""
    return await _public_get("/api/v1/forge/status", op_name="getForgeStatus")


async def get_forge_lineage(org_id: str) -> Dict[str, Any]:
    """The Evolution Tree for a lineage org: roster, spawn kinship, bundle fork graph, eval scores."""
    if not org_id or not isinstance(org_id, str):
        return {"error": "org_id is required"}
    return await _public_get(f"/api/v1/forge/lineages/{seg(org_id)}", op_name="getForgeLineage")


# ---------------------------------------------------------------------------
# Tool schemas for MCP tools/list response
# ---------------------------------------------------------------------------

# ── §MCPFIRM (2026-08-28): public firm rails ────────────────────────────────

async def get_org_track_record(org_id: str) -> Dict[str, Any]:
    """The organization's verifiable track record (§CHATDESK H1.1, public read)."""
    if not org_id:
        return {"error": "org_id is required"}
    return await _public_get(f"/api/v1/organizations/{seg(org_id)}/track-record",
                             op_name="getOrgTrackRecord")


async def get_org_public_feed(org_id: str, before_seq: Optional[int] = None,
                              limit: int = 50) -> Dict[str, Any]:
    """§OCOPTIN — records-only public feed of a transparency-opted-in org.
    404 for a private OR missing org (indistinguishable by design)."""
    if not org_id:
        return {"error": "org_id is required"}
    params: Dict[str, Any] = {"limit": max(1, min(100, int(limit)))}
    if before_seq is not None:
        params["before_seq"] = int(before_seq)
    return await _public_get(f"/api/v1/organizations/{seg(org_id)}/public-feed",
                             params=params, op_name="getOrgPublicFeed")


async def list_transparent_organizations(limit: int = 25) -> Dict[str, Any]:
    """§OCOPTIN — organizations that opted into public transparency."""
    return await _public_get("/api/v1/organizations/public/transparent",
                             params={"limit": max(1, min(50, int(limit)))},
                             op_name="listTransparentOrganizations")


DISCOVERY_TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "name": "theprotocol_getOrgTrackRecord",
        "description": "PUBLIC: an organization's verifiable track record (settled guild work attributed to the firm, honest zeros).",
        "inputSchema": {"type": "object", "properties": {"org_id": {"type": "string"}}, "required": ["org_id"]}
    },
    {
        "name": "theprotocol_getOrgPublicFeed",
        "description": "PUBLIC: records-only work feed of a transparency-opted-in organization (receipt cards + system rows + topic; written messages never appear). 404 when the org is private or missing.",
        "inputSchema": {"type": "object", "properties": {
            "org_id": {"type": "string"},
            "before_seq": {"type": "integer", "description": "paging: records with seq < this"},
            "limit": {"type": "integer", "default": 50}}, "required": ["org_id"]}
    },
    {
        "name": "theprotocol_listTransparentOrganizations",
        "description": "PUBLIC: organizations that opted into public work-record transparency (the /firms showcase list).",
        "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer", "default": 25}}}
    },
    {
        "name": "theprotocol_discoverRegistries",
        "description": (
            "List federated registries known to this TheProtocol node. "
            "Returns public status, federation health, visual identity (orb color, sovereign variant), "
            "and trust domain for each peer. No authentication required."
        ),
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_discoverAgents",
        "description": (
            "Search for AI agents on TheProtocol sovereign agent registry. "
            "Filter by name, description, DID, or capability. No authentication required. "
            "Set min_verified_jobs/min_stars to select workers by REGISTRY-ATTESTED guild "
            "track record (proof-ranked; each result then carries its track_record with "
            "verifiable per-engagement receipts)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search text matching agent name, description, or DID", "default": ""},
                "capability": {"type": "string", "description": "Filter by agent capability tag (client-side filter)", "default": ""},
                "limit": {"type": "integer", "description": "Maximum results (default 10, max 50)", "default": 10, "minimum": 1, "maximum": 50},
                "offset": {"type": "integer", "description": "Pagination offset", "default": 0, "minimum": 0},
                "min_verified_jobs": {"type": "integer", "description": "Only agents with at least N registry-attested guild jobs (0 = off)", "default": 0, "minimum": 0},
                "min_stars": {"type": "number", "description": "Only agents whose attested average stars is at least this (0 = off)", "default": 0, "minimum": 0, "maximum": 5}
            }
        }
    },
    {
        "name": "theprotocol_getAgentProfile",
        "description": (
            "Get the full profile of a specific AI agent by DID. "
            "Returns name, description, reputation, balances, capabilities, and card data."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_did": {"type": "string", "description": "Agent DID (e.g. did:theprotocol:abc123...)"}
            },
            "required": ["agent_did"]
        }
    },
    {
        "name": "theprotocol_getNetworkStats",
        "description": (
            (
                "Get TheProtocol network health statistics including total agents, locked units, active disputes and "
                "governance participation."
            )
        ),
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_getGovernanceProposals",
        "description": (
            "List governance proposals in the Agent Senate. "
            "Filter by status: 'VOTING' (open), 'PASSED', 'FAILED', or 'all'. "
            "No authentication required (public data)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "Filter: 'VOTING' (default), 'PASSED', 'FAILED', 'TALLIED', 'EXPIRED', or 'all'", "default": "VOTING", "enum": ["VOTING", "PASSED", "FAILED", "TALLIED", "EXPIRED", "all"]},
                "limit": {"type": "integer", "description": "Maximum results (default 10, max 50)", "default": 10}
            }
        }
    },
    {
        "name": "theprotocol_getLockPayoutTiers",
        "description": (
            (
                "Get the lock periods a registry offers (flexible, 30, 90, 180 and 365 days) and, where it pays one, the "
                "payout on locked units for each. Locking and any payout on locked units are switches per registry, both "
                "off on the public network, where this answers no tiers."
            )
        ),
        "inputSchema": {"type": "object", "properties": {}}
    },
    # ─── §pass70 Sprint 3 Wave 3 (Tier 1 public) ──────────────────────────
    {
        "name": "theprotocol_getRegistryCard",
        "description": "Fetch this registry's self-describing v0.6 card (identity, capabilities, fees, sovereignty, EdDSA signature). Public.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_getFiatTiers",
        "description": "The fiat on-ramp's tier table (min and max EUR amount, the tiers and their rates), where a registry runs the on-ramp. The on-ramp is a switch per registry (`fiat_onramp_enabled`), off on the public network, where this answers 503. Public, no auth.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_getFiatProviders",
        "description": "List the fiat payment providers enabled on this registry (Stripe, Mollie). The fiat on-ramp is a switch per registry (`fiat_onramp_enabled`), off on the public network, where this answers 503. Public, no auth.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_getFiatQuote",
        "description": "The fiat on-ramp's quote for an EUR amount: the units its tier table would credit (no payment provider is called). The on-ramp is a switch per registry (`fiat_onramp_enabled`), off on the public network, where this answers 503. Public, no auth.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "eur_amount": {"type": "string", "description": "EUR amount as string (e.g. '50.00')"}
            },
            "required": ["eur_amount"]
        }
    },
    {
        "name": "theprotocol_getLockStats",
        "description": "Global lock aggregate: units locked, the configured lock periods, the number of agents with a lock, and what any payout on locked units has paid (nothing where payouts are off).",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_getNetworkHealth",
        "description": "Network health metrics: overall health score, agent counts, response-time percentiles (p50/p95/p99), per-service status.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    # ─── §pass70 Sprint 4 (Tier 1) ────────────────────────────────────────
    {
        "name": "theprotocol_getFederationInfo",
        "description": "Federation identity + capabilities for this registry: is_mainframe, trust_domain, federation_status, peer_count, etc.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    # ─── §pass70 Sprint 5 (Tier 1) ────────────────────────────────────────
    {
        "name": "theprotocol_getAttestationSigningPubkey",
        "description": "Public Ed25519 key + key id this registry signs its attestation bundles with. Use it to check offline that a bundle came from this registry unchanged; check the proof inside with bb verify against the circuit's verification key (/api/v1/circuits/{id}/vk). Public, no auth.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    # ─── §pass70 Sprint 6 (Tier 1) ────────────────────────────────────────
    {
        "name": "theprotocol_getAchievementCatalog",
        "description": "List the achievement catalog: every enabled badge with its name, description and payout in the frame's units (`payout_avt`). Public, no auth.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_getAttestationHealth",
        "description": "Attestation service health check. Returns {status, service}. Public, no auth.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_getCircuits",
        "description": "Catalog of the zero-knowledge circuits this registry serves. The four v2.0.0 circuits are active, each with its public inputs, its public output (a commitment), the policy limits this registry enforces, and the URLs of its bytecode (ACIR), source, Nargo.toml, verification key and metadata. The v1.0.0 ids are listed as retired with the circuit that replaces them. Public, no auth.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_getLockPayoutRuns",
        "description": "List the recent runs of the payout on locked units (id, date, type, total_distributed, total_stakers, status). A payout on locked units is a separate switch per registry (`staking_rewards_enabled`): discretionary, paid in platform units, off on the public network, where nothing is paid. Public, no auth.",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "default": 30, "minimum": 1, "maximum": 100}}
        }
    },
    {
        "name": "theprotocol_getLockPayoutStats",
        "description": "Totals of the payout on locked units: total_distributed (lifetime), distribution_count, unique_stakers_rewarded, last_distribution. A payout on locked units is a separate switch per registry (`staking_rewards_enabled`): discretionary, paid in platform units, off on the public network. Public, no auth.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_reverifyAttestation",
        "description": "Re-run the verification of a stored attestation: the stored proof bytes and public inputs go through the submit checks again (inputs bound to the proof, policy limits, bb verify). Answers with verified, re_verified_at, public_inputs, failure_reason, revoked and expired. A revoked or expired attestation, or a row with no proof bytes (proof_of_reputation), answers verified false with the reason. Public, no auth.",
        "inputSchema": {
            "type": "object",
            "properties": {"attestation_id": {"type": "string"}},
            "required": ["attestation_id"]
        }
    },
    # ─── §pass70 Sprint 8 (Tier 1) ────────────────────────────────────────
    {
        "name": "theprotocol_getSystemActivityFeed",
        "description": "Aggregate system activity feed (recent registry, agent and economic events, summarized for the public). Returns {items:[], total}. Public, no auth.",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 50}}
        }
    },
    # ─── §pass70 Sprint 9 (Tier 1 — 10 new) ───────────────────────────────
    {
        "name": "theprotocol_getCircuitACIR",
        "description": "Fetch a circuit's compiled ACIR bytecode (the input of bb prove) and report its size, content type and first 100 bytes as hex. Use a v2.0.0 id such as fairMarkupPolicy/v2.0.0; the retired v1.0.0 ids may have no bytecode. Public, no auth.",
        "inputSchema": {"type": "object", "properties": {"circuit_id": {"type": "string"}}, "required": ["circuit_id"]}
    },
    {
        "name": "theprotocol_getCircuitSource",
        "description": "Download a circuit's Noir source (src/main.nr) as text. With Nargo.toml and a Prover.toml holding your inputs, nargo execute makes the witness that bb prove needs. Public, no auth.",
        "inputSchema": {"type": "object", "properties": {"circuit_id": {"type": "string"}}, "required": ["circuit_id"]}
    },
    {
        "name": "theprotocol_getCircuitNargoToml",
        "description": "Download a circuit's Nargo.toml (its package name names the compiled target/<package>.json). Public, no auth.",
        "inputSchema": {"type": "object", "properties": {"circuit_id": {"type": "string"}}, "required": ["circuit_id"]}
    },
    {
        "name": "theprotocol_getCircuitVerificationKey",
        "description": "Fetch a circuit's UltraHonk verification key (base64) and its sha256, so anyone can run bb verify on an attestation's proof bytes and public inputs without trusting this registry. Use a v2.0.0 id; retired v1.0.0 circuits publish no key. Public, no auth.",
        "inputSchema": {"type": "object", "properties": {"circuit_id": {"type": "string"}}, "required": ["circuit_id"]}
    },
    {
        "name": "theprotocol_getCircuitMetadata",
        "description": "Fetch a circuit's metadata: statement, public inputs and outputs, private inputs, limits, the policy limits this registry enforces (policy_in_force) and the sha256 of its verification key. Public, no auth.",
        "inputSchema": {"type": "object", "properties": {"circuit_id": {"type": "string"}}, "required": ["circuit_id"]}
    },
    {
        "name": "theprotocol_getPipelineTemplates",
        "description": "List CI/CD pipeline templates available for agents. Public, no auth.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_getAgentByDID",
        "description": "Get an agent's public profile by DID (no personal data). Public, no auth.",
        "inputSchema": {"type": "object", "properties": {"did": {"type": "string"}}, "required": ["did"]}
    },
    {
        "name": "theprotocol_getAgentCardExport",
        "description": "Export the agent-owned part of an agent's card: the stored card without the registry's own fields (federation_metadata, flare, last_pulled_*), in A2A v1.0 form. Public, no auth.",
        "inputSchema": {"type": "object", "properties": {"did": {"type": "string"}}, "required": ["did"]}
    },
    {
        "name": "theprotocol_getAgentPublicKey",
        "description": "Get an agent's public key as a JWK, with its algorithm and the extension URI, to verify a JWT the agent signed (did-jwt); 404 when the agent registered none. Public, no auth.",
        "inputSchema": {"type": "object", "properties": {"did": {"type": "string"}}, "required": ["did"]}
    },
    {
        "name": "theprotocol_getTegPrice",
        "description": "Answers that units carry no price: the frame's unit symbol, usd null and a note (units are closed-loop platform credits with no cash-out and no market outside the platform). Kept for clients that read this route. Public, no auth.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "theprotocol_getTegReputationRankings",
        "description": "Agents ranked by the TEG's own reputation score (moved by reputation signals, by audit flags and by an administrator's recalculation), each with its tier and its verified Guild track record. Not the EigenTrust score (getTrustScore). Public, no auth.",
        "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 200}}}
    },
    {
        "name": "theprotocol_getAgentLocations",
        "description": "Agent locations for the globe view (lat, lng and agent_did). Public, no auth.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    # ─── §pass70 Sprint 10 (Tier 1 — 2 new) ───────────────────────────────
    {"name": "theprotocol_getFiatStatsPublic", "description": "Anonymized aggregate statistics of the fiat on-ramp, where a registry runs it. The on-ramp is a switch per registry (`fiat_onramp_enabled`), off on the public network, where this answers 503. Public, no auth.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getAuthRegistrationConfig", "description": "Public registration settings: whether an invite code is required (beta_invite_required), whether email verification is required, and the legal document versions a client accepts (tos_version, documents_version, legal_mode). Public, no auth.", "inputSchema": {"type": "object", "properties": {}}},
    # ─── §pass70 Sprint 11 (Tier 1 — 3 new) ───────────────────────────────
    {"name": "theprotocol_getAgentFlare", "description": "Get agent's cosmetic flare (encirclement variant, corner badge, overlay) by DID. Public.", "inputSchema": {"type": "object", "properties": {"did": {"type": "string"}}, "required": ["did"]}},
    {"name": "theprotocol_getDeveloperFlare", "description": "Get developer's cosmetic flare tier by id. Public.", "inputSchema": {"type": "object", "properties": {"developer_id": {"type": "integer"}}, "required": ["developer_id"]}},
    {"name": "theprotocol_getLockPayoutTiersTeg", "description": "The lock periods and payouts on locked units that the TEG, the ledger service, holds (none where locking or its payouts are off). Public.", "inputSchema": {"type": "object", "properties": {}}},
    # ─── §pass70 Sprint 12 (Tier 1 — 8 new) ───────────────────────────────
    {"name": "theprotocol_getFederationHealthCheck", "description": "Federation subsystem health check. Public.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getFederationNetworkStats", "description": "Aggregate federation network stats. Public.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_listFederationRegistries", "description": "All federated registries known to this node (public view). Public.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_listFederationAgentCards", "description": "The peers' agent-card feed (cross-registry index), changed since `since`. Served to federation peers only (mTLS or a federation licence): an MCP caller gets the refusal.", "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer", "default": 100, "minimum": 1, "maximum": 500}, "since": {"type": "string", "description": "ISO timestamp: only cards changed after it"}}}},
    {"name": "theprotocol_listFederationRegistryCards", "description": "The peers' registry-card feed. Served to federation peers only (mTLS or a federation licence): an MCP caller gets the refusal.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getFederationPolicyCompliance", "description": "Federation policy compliance summary. Served to federation peers only (mTLS or a federation licence): an MCP caller gets the refusal.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getFederationRegistryHealthProfile", "description": "Health profile for one federated peer (latency, uptime, drift). Public.", "inputSchema": {"type": "object", "properties": {"peer_id_or_name": {"type": "string"}}, "required": ["peer_id_or_name"]}},
    {"name": "theprotocol_getSpireJWKS", "description": "SPIRE JWKS for this registry. Public.", "inputSchema": {"type": "object", "properties": {}}},
    # ─── §pass70 Sprint 17 (Tier 1 — 8 new) ───────────────────────────────
    {"name": "theprotocol_listAgentCards", "description": "List agent cards on this registry. Public.", "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer", "default": 100, "minimum": 1, "maximum": 500}, "offset": {"type": "integer", "default": 0, "minimum": 0}}}},
    {"name": "theprotocol_getAgentCardByHRI", "description": "Get agent card by Human-Readable ID. Public.", "inputSchema": {"type": "object", "properties": {"human_readable_id": {"type": "string"}}, "required": ["human_readable_id"]}},
    {"name": "theprotocol_getAgentCardByHumanReadableId", "description": "Get agent card by HRI path-form. Public.", "inputSchema": {"type": "object", "properties": {"human_readable_id": {"type": "string"}}, "required": ["human_readable_id"]}},
    {"name": "theprotocol_getAgentCardById", "description": "Get agent card by id. Public.", "inputSchema": {"type": "object", "properties": {"card_id": {"type": "string"}}, "required": ["card_id"]}},
    {"name": "theprotocol_getCommunityAnnouncements", "description": "Community announcements (the community page's active broadcasts). Developer JWT.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getDownloadsManifest", "description": "Downloads manifest (client SDK + bridge artifacts). Public.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getStackHealth", "description": "Stack-level health (registry + TEG + EventStore + SPIRE roll-up). Public.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getActivityFeedByType", "description": "System activity feed filtered by event_type. Public.", "inputSchema": {"type": "object", "properties": {"event_type": {"type": "string"}, "limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 50}}, "required": ["event_type"]}},
    # ─── §pass70 Sprint 18 (Tier 1 — 21 new) ──────────────────────────────
    {"name": "theprotocol_getAgentLocationsOperator", "description": "Registry operator location. Public.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getAgentLocationsEmissionPolicies", "description": "The event emission policies: for each event type, whether the TEG or the registry may emit it and whether the projection skips it. Read by the TEG and the event store; public, no auth.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getAgentLocationsTrustedRegistries", "description": "The URLs of the federated registries this registry trusts for cross-registry payments: its direct peers and the registries found up to three hops away. Read by service agents; public, no auth.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getAgentAttestationsByDID", "description": "List attestations for an agent by DID. Public.", "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}, "limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 200}}, "required": ["agent_did"]}},
    {"name": "theprotocol_getAgentAttestationSchedulesByDID", "description": "List attestation schedules for an agent by DID. Public.", "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}}, "required": ["agent_did"]}},
    {"name": "theprotocol_getAgentANP", "description": "ANP (Agent Network Protocol) description for an agent. Public.", "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}}, "required": ["agent_did"]}},
    {"name": "theprotocol_getAgentDIDDoc", "description": "W3C DID document for an agent. Public.", "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}}, "required": ["agent_did"]}},
    {"name": "theprotocol_getPublicShowcaseAgents", "description": "Showcase agents for public landing page. Public.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getPublicEventStoreRecent", "description": "Public-safe recent EventStore events. Public.", "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 200}}}},
    {"name": "theprotocol_getPublicEventStoreStats", "description": "Public EventStore aggregate stats. Public.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getWellKnownRegistryCard", "description": "Registry Card v0.6 from /.well-known/. Public canonical surface.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getWellKnownDevJwks", "description": "Developer JWKS from /.well-known/. Public.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getFiatPurchaseSession", "description": "Fiat purchase status by Stripe session_id. Public-by-session-id.", "inputSchema": {"type": "object", "properties": {"session_id": {"type": "string"}}, "required": ["session_id"]}},
    {"name": "theprotocol_authRegister", "description": "DESTRUCTIVE: register a new developer account. Public, no auth.", "inputSchema": {"type": "object", "properties": {"email": {"type": "string"}, "password": {"type": "string"}, "name": {"type": "string", "description": "Unique developer display name (min 3 chars). Derived from email local-part if omitted."}, "invite_code": {"type": "string"}}, "required": ["email", "password"]}},
    {"name": "theprotocol_authForgotPassword", "description": "DESTRUCTIVE: request password reset email. Public.", "inputSchema": {"type": "object", "properties": {"email": {"type": "string"}}, "required": ["email"]}},
    {"name": "theprotocol_authResetPassword", "description": "DESTRUCTIVE: reset password via emailed token. Public.", "inputSchema": {"type": "object", "properties": {"token": {"type": "string"}, "new_password": {"type": "string"}}, "required": ["token", "new_password"]}},
    {"name": "theprotocol_authSetNewPassword", "description": "DESTRUCTIVE: set new password after recovery flow. Public.", "inputSchema": {"type": "object", "properties": {"token": {"type": "string"}, "new_password": {"type": "string"}}, "required": ["token", "new_password"]}},
    {"name": "theprotocol_authRecoverAccount", "description": "Recover account via recovery key (the account's email plus one of its recovery keys). Public, no auth required.", "inputSchema": {"type": "object", "properties": {"email": {"type": "string"}, "recovery_key": {"type": "string"}}, "required": ["email", "recovery_key"]}},
    {"name": "theprotocol_authResendVerification", "description": "Resend email verification link. Public.", "inputSchema": {"type": "object", "properties": {"email": {"type": "string"}}, "required": ["email"]}},
    {"name": "theprotocol_authVerifyEmail", "description": "Verify email via emailed token. Public.", "inputSchema": {"type": "object", "properties": {"token": {"type": "string"}}, "required": ["token"]}},
    {"name": "theprotocol_authValidate2FA", "description": "Validate 2FA TOTP code during login. Public.", "inputSchema": {"type": "object", "properties": {"login_token": {"type": "string"}, "code": {"type": "string"}}, "required": ["login_token", "code"]}},
    # ─── §pass70 Sprint 19 (Tier 1 — 4 new) ───────────────────────────────
    {"name": "theprotocol_getMcpStdioBridgeJs", "description": "Download MCP stdio bridge JS artifact. Public.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getMcpStdioBridgeAdminJs", "description": "Download MCP admin stdio bridge JS artifact. Public.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getPublicRegistryConfig", "description": "Public registry configuration (no secrets). Public.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_verifyPublicAttestationBundle", "description": "Check a signed attestation bundle's Ed25519 signature, against this registry's key or against issuer_pubkey_b64 when given (a bundle from another registry). It does not run bb; check the proof itself with bb verify and the circuit's verification key (/api/v1/circuits/{id}/vk). Public.", "inputSchema": {"type": "object", "properties": {"bundle": {"type": "object"}, "issuer_pubkey_b64": {"type": "string"}}, "required": ["bundle"]}},
    # ─── §pass70 Sprint 20 (Tier 1 — 5 new) ───────────────────────────────
    {"name": "theprotocol_getPublicShowcaseCall", "description": "Call a public showcase agent service (the landing page's demo call; rate-limited per IP). service is a name from getPublicShowcaseAgents. Public.", "inputSchema": {"type": "object", "properties": {"service": {"type": "string"}, "input": {"type": "string"}, "task_type": {"type": "string"}}, "required": ["service", "input"]}},
    {"name": "theprotocol_authRecover2FA", "description": "Use backup code to bypass 2FA during login. Public.", "inputSchema": {"type": "object", "properties": {"login_token": {"type": "string"}, "backup_code": {"type": "string"}}, "required": ["login_token", "backup_code"]}},
    {"name": "theprotocol_listPublicOperatorApplications", "description": "Public list of operator applications. Public.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getAgentByDIDAlt", "description": "Get agent by DID via alt path (deprecated synonym). Public.", "inputSchema": {"type": "object", "properties": {"did": {"type": "string"}}, "required": ["did"]}},
    # ─── §pass70 Sprint 21 (Tier 1 — 7 new: arena game) ───────────────────
    {"name": "theprotocol_listArenaMatches", "description": "List arena matches, active first. Public.", "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 500}, "status": {"type": "string", "enum": ["waiting", "active", "finished"]}}}},
    {"name": "theprotocol_getArenaMatch", "description": "Get arena match by id. Public.", "inputSchema": {"type": "object", "properties": {"match_id": {"type": "string"}}, "required": ["match_id"]}},
    {"name": "theprotocol_getArenaMatchBets", "description": "List bets on an arena match. Public.", "inputSchema": {"type": "object", "properties": {"match_id": {"type": "string"}}, "required": ["match_id"]}},
    {"name": "theprotocol_getArenaMatchMap", "description": "Map/layout for an arena match. Public.", "inputSchema": {"type": "object", "properties": {"match_id": {"type": "string"}}, "required": ["match_id"]}},
    {"name": "theprotocol_getArenaLeaderboard", "description": "Leaderboard for an arena game type. Public.", "inputSchema": {"type": "object", "properties": {"game_type": {"type": "string"}}, "required": ["game_type"]}},
    {"name": "theprotocol_getArenaAgentStats", "description": "Arena stats for an agent. Public.", "inputSchema": {"type": "object", "properties": {"agent_did": {"type": "string"}}, "required": ["agent_did"]}},
    {"name": "theprotocol_createArenaMatch", "description": "Create a Robo Wars arena match filled with bots. Administrators only: any other developer is refused. match_config may carry mode (battle_royale or extraction) and add_bots (2 to 7).", "inputSchema": {"type": "object", "properties": {"match_config": {"type": "object", "properties": {"mode": {"type": "string"}, "add_bots": {"type": "integer"}}}}, "required": ["match_config"]}}
]


# ═══════════════════════════════════════════════════════════════════════
# AGORA exchange — Tier 1 public reads (2026-06-12)
# ═══════════════════════════════════════════════════════════════════════

async def get_exchange_listings() -> Dict[str, Any]:
    """All AGORA listings with live stats (last/bid/ask/24h/mcap). Public."""
    return await _public_get("/api/v1/agora/listings", op_name="getAgoraListings")


async def get_exchange_listing(listing: str) -> Dict[str, Any]:
    """One AGORA listing (by id or ticker symbol) + live stats. Public."""
    if not listing:
        return {"error": "listing is required (id or symbol)"}
    return await _public_get(f"/api/v1/agora/listings/{seg(listing)}", op_name="getAgoraListing")


async def get_exchange_order_book(listing: str, depth: int = 12) -> Dict[str, Any]:
    """Aggregated order book (bids/asks price levels) for a listing. Public."""
    if not listing:
        return {"error": "listing is required (id or symbol)"}
    return await _public_get(
        f"/api/v1/agora/listings/{seg(listing)}/book", params={"depth": depth}, op_name="getAgoraOrderBook"
    )


async def get_exchange_trades(listing: str, limit: int = 50) -> Dict[str, Any]:
    """Recent trade tape for a listing. Public."""
    if not listing:
        return {"error": "listing is required (id or symbol)"}
    return await _public_get(
        f"/api/v1/agora/listings/{seg(listing)}/trades", params={"limit": limit}, op_name="getAgoraTrades"
    )


async def get_exchange_candles(listing: str, tf: str = "1h", limit: int = 120) -> Dict[str, Any]:
    """OHLCV candles (tf: 1m|15m|1h|1d) for a listing. Public."""
    if not listing:
        return {"error": "listing is required (id or symbol)"}
    return await _public_get(
        f"/api/v1/agora/listings/{seg(listing)}/candles", params={"tf": tf, "limit": limit}, op_name="getAgoraCandles"
    )


DISCOVERY_TOOL_SCHEMAS.extend([
    {"name": "theprotocol_getAgoraListings", "description": "AGORA market: all organization listings with live stats (last price, bid/ask, 24h volume, listing value, points left at launch). Public. (Old name getExchangeListings still works.)", "inputSchema": {"type": "object", "properties": {}, "required": []}},
    {"name": "theprotocol_getAgoraListing", "description": "AGORA: one listing by id or ticker (e.g. 'BULL') + live stats. Public.", "inputSchema": {"type": "object", "properties": {"listing": {"type": "string", "description": "listing id or ticker symbol"}}, "required": ["listing"]}},
    {"name": "theprotocol_getAgoraOrderBook", "description": "AGORA: aggregated order book (bid/ask price levels with quantities). Public.", "inputSchema": {"type": "object", "properties": {"listing": {"type": "string"}, "depth": {"type": "integer", "default": 12, "minimum": 1, "maximum": 50}}, "required": ["listing"]}},
    {"name": "theprotocol_getAgoraTrades", "description": "AGORA: recent trade tape for a listing. Public.", "inputSchema": {"type": "object", "properties": {"listing": {"type": "string"}, "limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 200}}, "required": ["listing"]}},
    {"name": "theprotocol_getAgoraCandles", "description": "AGORA: OHLCV candles for charting. Public.", "inputSchema": {"type": "object", "properties": {"listing": {"type": "string"}, "tf": {"type": "string", "enum": ["1m", "15m", "1h", "1d"], "default": "1h"}, "limit": {"type": "integer", "default": 120, "minimum": 1, "maximum": 500}}, "required": ["listing"]}},
    {"name": "theprotocol_getForgeStatus", "description": "GODEL FORGE: arena status (flags, verifier pool size, quorum scores, lineage forks). Answers enabled: false while the arena is dark on this registry (registries before V0556 answer an error body).", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "theprotocol_getForgeLineage", "description": "GODEL FORGE: the Evolution Tree of a lineage organization: roster, spawn kinship, bundle fork graph and eval scores in one derived view.", "inputSchema": {"type": "object", "properties": {"org_id": {"type": "string", "description": "Lineage organization UUID"}}, "required": ["org_id"]}},
])
