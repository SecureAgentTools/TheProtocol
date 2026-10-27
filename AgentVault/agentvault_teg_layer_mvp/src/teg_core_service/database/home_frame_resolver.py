"""Home-frame resolver — determines an agent's home frame from federation metadata.

Used by the TEG home-frame guard to prevent dual-profile creation across sovereign
frames. Each agent has a single "home" frame (where its DID was originally
registered); cross-frame credits should land on the home frame's TEG, not on the
sibling frame's TEG that happens to receive the cross-frame saga.

Resolution path:
  1. In-process LRU cache (10k entries, 1h TTL on hits)
  2. Redis cache (cluster-wide, 5-min TTL — covers cache misses across workers)
  3. HTTP RPC to local registry's internal home-frame endpoint
  4. Fallback: None (caller decides — typically falls back to local create + log)

Scaling: bulk RPC accepts up to 500 DIDs per call; the registry endpoint is a
single SQL `WHERE agent_did IN (...)` against an indexed unique column, so the
hot path is O(N) round-trips with N=ceil(batch/500).

The resolver is gated by `TEG_HOME_FRAME_GUARD_ENABLED=true|false`. When false,
all callers receive None (treating every agent as home-here, preserving today's
behavior).
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Dict, List, Optional, Set

import httpx

from ..ssl_helper import get_httpx_verify

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Master kill switch. When false, all resolves return None → callers fall back
# to local create. This lets us ship the code dark and flip it on after
# consolidation completes.
GUARD_ENABLED: bool = os.environ.get("TEG_HOME_FRAME_GUARD_ENABLED", "false").lower() == "true"

# Local trust_domain — the authoritative identity of THIS TEG's frame. Read
# from SPIRE_TRUST_DOMAIN env (set per-deployment in compose). The resolver
# compares an agent's home trust_domain to this; if they differ → raise.
LOCAL_TRUST_DOMAIN: str = os.environ.get("SPIRE_TRUST_DOMAIN", "agentvault.com").lower()

# Compatibility alias for older callers using "A"/"B" labels. Derived once.
LOCAL_FRAME: str = "B" if "frame-b" in LOCAL_TRUST_DOMAIN else "A"

# Local registry URL — the resolver queries this registry's agent_cards table.
_REGISTRY_URL: str = os.environ.get("REGISTRY_URL", "http://registry-a:8000").rstrip("/")

# Cache parameters — tuned for 1M-agent scale.
_INPROC_CACHE_MAX: int = int(os.environ.get("HOME_FRAME_CACHE_MAX", "10000"))
_HIT_TTL_SECONDS: int = int(os.environ.get("HOME_FRAME_HIT_TTL", "3600"))
_MISS_TTL_SECONDS: int = int(os.environ.get("HOME_FRAME_MISS_TTL", "30"))
_RPC_BATCH_MAX: int = 500
_RPC_TIMEOUT_SECONDS: float = float(os.environ.get("HOME_FRAME_RPC_TIMEOUT", "5.0"))

# Optional Redis tier (currently in-process only — keep simple for first ship).
# Cross-worker safety comes from the registry endpoint being authoritative.

# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


class AgentNotHomeError(Exception):
    """Raised when get_or_create is asked to provision a profile on a TEG whose
    trust_domain (frame) is not the agent's home trust_domain.

    Callers should propagate this; FastAPI handler converts to 409 Conflict.
    The existing reactor's `agents`-table check should already prevent legitimate
    cross-frame credits from hitting this path; the guard is defense-in-depth
    for sim/admin/legacy code paths.
    """

    def __init__(
        self,
        agent_id: str,
        home_frame: str,
        this_frame: str,
    ):
        self.agent_id = agent_id
        # Both fields can be a trust_domain string (e.g. "agentvault.com")
        # or a short label ("A"/"B"). Compatible with older callers.
        self.home_frame = home_frame
        self.this_frame = this_frame
        super().__init__(
            f"Agent {agent_id} home is {home_frame}, but this TEG is on "
            f"{this_frame}. Cross-frame credit must land on the home TEG."
        )


# ---------------------------------------------------------------------------
# In-process cache (bounded LRU)
# ---------------------------------------------------------------------------


class _LRUCache:
    """Tiny LRU implementation tuned for our access pattern.

    `set()` evicts oldest when over capacity. Each entry has its own expiry.
    We avoid heavy deps (cachetools) — this is a hot path on every credit.
    """

    __slots__ = ("_data", "_max")

    def __init__(self, max_entries: int):
        self._data: Dict[str, tuple] = {}
        self._max = max_entries

    def get(self, key: str) -> Optional[str]:
        entry = self._data.get(key)
        if entry is None:
            return None
        value, expires_at, sentinel = entry
        if expires_at < time.monotonic():
            self._data.pop(key, None)
            return None
        # promote to MRU
        self._data.pop(key)
        self._data[key] = entry
        return sentinel  # may be None for negative-cache hits — caller checks

    def has(self, key: str) -> bool:
        entry = self._data.get(key)
        if entry is None:
            return False
        if entry[1] < time.monotonic():
            self._data.pop(key, None)
            return False
        return True

    def set(self, key: str, value: Optional[str], ttl: int) -> None:
        # `value` may be None for negative cache (DID not in registry yet).
        # We still store it so we don't hammer the registry repeatedly.
        if len(self._data) >= self._max and key not in self._data:
            # evict oldest (insertion-ordered dict)
            oldest = next(iter(self._data))
            self._data.pop(oldest, None)
        self._data[key] = (value, time.monotonic() + ttl, value)

    def clear(self) -> None:
        self._data.clear()


_cache = _LRUCache(_INPROC_CACHE_MAX)


# ---------------------------------------------------------------------------
# SPIFFE → frame mapping
# ---------------------------------------------------------------------------


def _spiffe_to_frame(spiffe_id: Optional[str]) -> Optional[str]:
    """Map a SPIFFE source identity to its frame label ("A" or "B").

    Returns None if we can't classify (caller falls back to LOCAL_FRAME).
    """
    if not spiffe_id:
        return None
    s = spiffe_id.lower()
    # frame-b.theprotocol.cloud → Frame B
    if "frame-b.theprotocol.cloud" in s or "frame-b" in s:
        return "B"
    # agentvault.com → Frame A (default — most operators)
    if "agentvault.com" in s:
        return "A"
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def resolve_home_frame(agent_id: str) -> Optional[str]:
    """Resolve a single agent's home frame.

    Returns "A", "B", or None (unknown). When the guard is disabled, always
    returns None.

    Caching: in-process LRU + RPC fallback.
    """
    if not GUARD_ENABLED:
        return None
    cached = _cache.get(agent_id)
    if cached is not None or _cache.has(agent_id):
        return cached
    result = await resolve_home_frames([agent_id])
    return result.get(agent_id)


async def resolve_home_frames(agent_ids: List[str]) -> Dict[str, Optional[str]]:
    """Bulk resolver — returns a mapping from agent_id → "A"|"B"|None.

    Semantics:
      - "A" / "B": authoritative home frame from federation_metadata
      - None: agent_id has no card in the local registry (race window, defunct,
              or this DID has never been seen). Caller falls back to local.

    The bulk path is the hot path for `_credit_async_bulk_async`. Don't call
    this on every single credit — pass the full receiver_dids batch.
    """
    if not GUARD_ENABLED or not agent_ids:
        return {aid: None for aid in agent_ids}

    out: Dict[str, Optional[str]] = {}
    uncached: List[str] = []
    for aid in agent_ids:
        # try cache (positive or negative)
        if _cache.has(aid):
            out[aid] = _cache.get(aid)
        else:
            uncached.append(aid)

    if not uncached:
        return out

    # Bulk RPC — chunk if needed
    rpc_results: Dict[str, Optional[str]] = {}
    for i in range(0, len(uncached), _RPC_BATCH_MAX):
        chunk = uncached[i : i + _RPC_BATCH_MAX]
        try:
            chunk_result = await _bulk_rpc(chunk)
            rpc_results.update(chunk_result)
        except Exception as exc:
            logger.warning(
                f"[HomeFrameResolver] RPC failed for chunk of {len(chunk)} DIDs: "
                f"{type(exc).__name__}: {exc}. Falling back to LOCAL_FRAME for all."
            )
            # On RPC failure, return None for the chunk (caller falls back).
            # Don't cache failures aggressively (short TTL).
            for aid in chunk:
                rpc_results[aid] = None

    # Cache results
    for aid in uncached:
        frame = rpc_results.get(aid)
        if frame is None:
            _cache.set(aid, None, _MISS_TTL_SECONDS)
        else:
            _cache.set(aid, frame, _HIT_TTL_SECONDS)
        out[aid] = frame

    return out


async def _bulk_rpc(dids: List[str]) -> Dict[str, Optional[str]]:
    """Call the registry's bulk home-frame endpoint.

    Auth: same pattern as `agent_locations.get_emission_policies_internal` —
    no auth, relies on docker network isolation. The endpoint returns only
    derived metadata (home frame label) which is non-sensitive.
    """
    url = f"{_REGISTRY_URL}/api/v1/internal/agents/home-trust-domains"
    # §pass69.1 (T1.2c): verify= picks SPIRE bundle for internal HTTPS, system CA
    # for public, no-op for plain HTTP. Safe across all REGISTRY_URL forms.
    async with httpx.AsyncClient(timeout=_RPC_TIMEOUT_SECONDS, verify=get_httpx_verify()) as client:
        resp = await client.post(url, json={"dids": dids})
        resp.raise_for_status()
        body = resp.json()

    home_trust_domains = body.get("home_trust_domains", {})
    # Normalize: registry may return native source as null/empty → LOCAL_TRUST_DOMAIN
    out: Dict[str, Optional[str]] = {}
    for did in dids:
        v = home_trust_domains.get(did)
        if v is None:
            # DID not in agent_cards — unknown
            out[did] = None
        elif v == "" or v == "native":
            # Native to local registry — home is the local TEG's trust_domain
            out[did] = LOCAL_TRUST_DOMAIN
        else:
            out[did] = v.lower()
    return out


def cache_clear() -> None:
    """Test/admin helper — drop all cached entries."""
    _cache.clear()


def is_system_account(agent_id: str) -> bool:
    """System accounts (fee_collector, treasury) are not subject to the guard.

    They have no federation_metadata source; their home is wherever they're
    used. Callers should check this before calling resolve_*.
    """
    if not agent_id:
        return False
    aid = agent_id.lower()
    return (
        aid.startswith("teg:system:")
        or aid.startswith("did:teg:")
        or aid in {"system", "treasury", "fee_collector", "mint", "mint_authority"}
    )


# ---------------------------------------------------------------------------
# Guard helpers — call BEFORE creating an AgentTEGProfile() inline
# ---------------------------------------------------------------------------


def _sync_bulk_rpc(dids: List[str]) -> Dict[str, Optional[str]]:
    """Synchronous version of `_bulk_rpc` for sync code paths."""
    url = f"{_REGISTRY_URL}/api/v1/internal/agents/home-trust-domains"
    # §pass69.1 (T1.2c): see _bulk_rpc above for verify= rationale.
    with httpx.Client(timeout=_RPC_TIMEOUT_SECONDS, verify=get_httpx_verify()) as client:
        resp = client.post(url, json={"dids": dids})
        resp.raise_for_status()
        body = resp.json()
    home_trust_domains = body.get("home_trust_domains", {})
    out: Dict[str, Optional[str]] = {}
    for did in dids:
        v = home_trust_domains.get(did)
        if v is None:
            out[did] = None
        elif v == "" or v == "native":
            out[did] = LOCAL_TRUST_DOMAIN
        else:
            out[did] = v.lower()
    return out


def _resolve_one_sync(agent_id: str) -> Optional[str]:
    """Single-DID sync resolver with cache."""
    if not GUARD_ENABLED:
        return None
    if _cache.has(agent_id):
        return _cache.get(agent_id)
    try:
        result = _sync_bulk_rpc([agent_id])
    except Exception as exc:
        logger.warning(
            f"[HomeFrameResolver:sync] RPC failed for {agent_id}: "
            f"{type(exc).__name__}: {exc}"
        )
        return None
    frame = result.get(agent_id)
    if frame is None:
        _cache.set(agent_id, None, _MISS_TTL_SECONDS)
    else:
        _cache.set(agent_id, frame, _HIT_TTL_SECONDS)
    return frame


def check_home_or_raise(agent_id: str) -> None:
    """Sync guard — raises `AgentNotHomeError` if `agent_id`'s home is not the
    local frame. Returns silently when:
      - guard is disabled (`TEG_HOME_FRAME_GUARD_ENABLED=false`, default)
      - agent is a system account (fee_collector / treasury / etc.)
      - resolver can't determine home (returns None — caller falls back to local)
      - home is already the local frame
    """
    if not GUARD_ENABLED:
        return
    if is_system_account(agent_id):
        return
    home = _resolve_one_sync(agent_id)
    if home is None:
        # Resolver couldn't classify (RPC down / no card / unknown source).
        # Fall back to allowing local create — daily reconciler picks up orphans.
        logger.debug(
            f"[HomeFrameGuard] {agent_id} home unknown — allowing local create"
        )
        return
    if home != LOCAL_TRUST_DOMAIN:
        raise AgentNotHomeError(
            agent_id=agent_id, home_frame=home, this_frame=LOCAL_TRUST_DOMAIN
        )


async def async_check_home_or_raise(agent_id: str) -> None:
    """Async equivalent of `check_home_or_raise`. Use in async code paths
    (cross_teg_router endpoints, async credit/lock paths)."""
    if not GUARD_ENABLED:
        return
    if is_system_account(agent_id):
        return
    home = await resolve_home_frame(agent_id)
    if home is None:
        logger.debug(
            f"[HomeFrameGuard:async] {agent_id} home unknown — allowing local create"
        )
        return
    if home != LOCAL_FRAME:
        raise AgentNotHomeError(
            agent_id=agent_id, home_frame=home, this_frame=LOCAL_FRAME
        )


async def async_check_home_or_raise_bulk(agent_ids: List[str]) -> None:
    """Async bulk variant — single RPC for many DIDs, raises on the first
    non-local-home agent. Caller should pre-filter system accounts.

    For partial-success handling (some DIDs OK, others not), call
    `resolve_home_frames` directly and inspect the dict.
    """
    if not GUARD_ENABLED:
        return
    targets = [a for a in agent_ids if not is_system_account(a)]
    if not targets:
        return
    home_map = await resolve_home_frames(targets)
    for aid in targets:
        home = home_map.get(aid)
        if home is None:
            continue
        if home != LOCAL_TRUST_DOMAIN:
            raise AgentNotHomeError(
                agent_id=aid, home_frame=home, this_frame=LOCAL_TRUST_DOMAIN
            )
