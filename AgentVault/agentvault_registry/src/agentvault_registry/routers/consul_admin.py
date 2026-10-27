"""
CONSUL — Compliance Oversight, Network Surveillance, Unified Lockdown
Admin router for the federation compliance monitoring dashboard.

Routes:
  GET   /api/v1/admin/federation/compliance/overview
  GET   /api/v1/admin/federation/compliance/peers/{peer_id}
  GET   /api/v1/admin/federation/compliance/events
  GET   /api/v1/admin/federation/compliance/enforcement-mode
  POST  /api/v1/admin/federation/compliance/enforcement-mode
  POST  /api/v1/admin/federation/compliance/peers/{peer_id}/poll-now
  GET   /api/v1/admin/federation/compliance/preview-quarantine

All endpoints require an admin JWT (is_admin=True).

The CONSUL frontend at /ui#/admin/compliance consumes these endpoints.
Quarantine / lift-quarantine / blacklist mutations still live on the existing
enforcement_admin router at /api/v1/admin/enforcement/registries/{peer_id}/*.
"""
import hashlib
import json
import logging
import os
import re as _re
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status, Security
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry import models
from agentvault_registry.background_tasks.compliance_poller import (
    MODE_OFF,
    MODE_DRY_RUN,
    MODE_ENFORCING,
    VALID_MODES,
    POLL_INTERVAL_SECONDS,
    get_compliance_poller,
    read_enforcement_mode,
)
from agentvault_registry.config import settings
from agentvault_registry.core.base_network_params import (
    BOUNDED_PARAMS,
    DriftSeverity,
    GRACE_PERIOD_HOURS,
    LOCKED_PARAMS,
    PARAM_SEVERITY,
)
from agentvault_registry.database import get_db
from agentvault_registry.event_emitter import get_event_emitter
from agentvault_registry.models import (
    Developer,
    FederatedRegistryCompliance,
    PeerRegistry,
    RegistryOperatingState,
    REGISTRY_STATE_SINGLETON_ID,
)
from agentvault_registry import security
import asyncio as _asyncio
from agentvault_registry.services.diagnostics.probe import get_probe
from agentvault_registry.services.diagnostics.targets import list_targets as list_diag_targets
from agentvault_registry.services.federation_policy_validator import (
    FederationPolicyValidator,
)
from agentvault_registry.es_ssl_helper import get_httpx_verify

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/admin/federation/compliance",
    tags=["CONSUL — Federation Compliance"],
    dependencies=[Security(security.require_admin_flag("admin_platform"))],
)


# ── Schemas ───────────────────────────────────────────────────────────────────

class EnforcementModeRead(BaseModel):
    mode: str = Field(..., description="off | dry_run | enforcing")
    enforcement_env_flag: bool = Field(
        ..., description="Value of FEDERATION_ENFORCEMENT_ACTIVE env var"
    )
    is_central_registry_env_flag: bool = Field(
        ..., description="Value of IS_CENTRAL_REGISTRY env var"
    )
    effective_enforcement: bool = Field(
        ...,
        description="True only when mode=enforcing AND both env flags allow it (live quarantines).",
    )
    last_changed_at: Optional[str] = None
    last_changed_by: Optional[str] = None


class EnforcementModeWrite(BaseModel):
    mode: Literal["off", "dry_run", "enforcing"]
    reason: str = Field(..., min_length=5, max_length=500, description="Audit reason for change")


class PeerComplianceRow(BaseModel):
    # Command Center slug (e.g., "registry-a", "frame-b", "op-berlin"). Always present.
    operator_id: str
    display_name: str
    frame: str
    role: str  # "mainframe" | "operator"
    cloud_url: Optional[str] = None
    # PeerRegistry mapping — may be None if this live target hasn't been Phase-2-admitted yet
    peer_registry_id: Optional[int] = None
    peer_name: Optional[str] = None
    peer_url: Optional[str] = None
    peer_status: Optional[str] = None
    has_compliance_record: bool
    federation_status: Optional[str] = None
    compliance_score: Optional[float] = None
    drift_events_count: Optional[int] = None
    consecutive_poll_failures: Optional[int] = None
    last_poll_at: Optional[str] = None
    last_hash_mismatch_at: Optional[str] = None
    quarantine_reason: Optional[str] = None
    quarantine_since: Optional[str] = None
    grace_expires: Optional[str] = None
    admitted_at: Optional[str] = None
    # §TRUSTCHAIN: the stored baseline and where it came from — an admin's email for a Phase 2
    # admission, "compliance_poller:first_sight" for a baseline recorded from the peer's own hash
    baseline_hash: Optional[str] = None
    baseline_source: Optional[str] = None
    # §MCPTEST30 (V0561): who the peer is, the way a cross-frame operation resolves it (spiffe_canonical.
    # resolve_target_trust_domain's order: the peer row's column, its signed card, the topology cache), and the frame of
    # this federation that shares its trust domain with that frame's settlement currency. The console's roster groups by
    # trust_domain and badges by these; before V0561 none was sent, so every peer read "identity pending" and "Unmapped".
    trust_domain: Optional[str] = None
    resolution_state: Optional[Literal["resolved", "unidentified"]] = None
    resolution_source: Optional[Literal["column", "card", "bfs", "unresolved"]] = None
    home_frame: Optional[str] = None
    currency_zone: Optional[str] = None


class ComplianceOverview(BaseModel):
    mode: str
    enforcement_env_flag: bool
    is_central_registry_env_flag: bool
    effective_enforcement: bool
    poller_enabled: bool
    poll_interval_seconds: int
    peers_total: int
    peers_with_compliance: int
    peers_federated: int
    peers_quarantined: int
    peers_blacklisted: int
    peers_never_polled: int
    peers_unreachable_streak: int
    peers: List[PeerComplianceRow]
    # Reachability (2026-07-24): compliance tracked licence/policy adherence and had no
    # notion of whether a corridor actually carries traffic — which is how frame-c ran with
    # 6 of 16 peers for seven weeks while every surface read healthy. Optional so older
    # clients keep parsing.
    reachability: Optional[Dict[str, Any]] = None


class PolicyDiffEntry(BaseModel):
    path: str
    stored_value: Any = None
    live_value: Any = None
    match: bool
    severity: Optional[str] = None


class PeerDetail(BaseModel):
    peer_registry_id: int
    peer_name: str
    peer_url: str
    peer_status: str
    federation_status: Optional[str]
    compliance_score: Optional[float]
    drift_events_count: Optional[int]
    consecutive_poll_failures: Optional[int]
    last_poll_at: Optional[str]
    last_hash_mismatch_at: Optional[str]
    quarantine_reason: Optional[str]
    quarantine_since: Optional[str]
    quarantine_events: Optional[List[Dict[str, Any]]] = None
    admitted_policy_hash: Optional[str] = None
    live_policy_hash: Optional[str] = None
    hash_match: Optional[bool] = None
    live_policy_fetched: bool
    live_fetch_error: Optional[str] = None
    admitted_policy_json: Optional[Dict[str, Any]] = None
    live_policy_json: Optional[Dict[str, Any]] = None
    diff: Optional[List[PolicyDiffEntry]] = None
    # §TRUSTCHAIN: where the stored baseline came from (an admin email = Phase 2 admission,
    # "compliance_poller:first_sight" = recorded from the peer's own published hash) and the hash itself
    baseline_source: Optional[str] = None
    baseline_hash: Optional[str] = None
    # §MCPTEST30 (V0561): what the peer says about the two documents (its own counters, reported, never trusted to excuse
    # a drift): the same version and source on both sides with a new hash is a release that changed a shipped default
    admitted_policy_version: Optional[int] = None
    admitted_policy_source: Optional[str] = None
    live_policy_version: Optional[int] = None
    live_policy_source: Optional[str] = None


class PreviewQuarantineRow(BaseModel):
    operator_id: str
    display_name: str
    frame: str
    role: str
    peer_registry_id: Optional[int] = None
    peer_name: Optional[str] = None
    peer_url: Optional[str] = None
    has_compliance_record: bool
    reachable: Optional[bool] = None
    hash_match: Optional[bool] = None
    would_action: str  # "none" | "quarantine_critical" | "quarantine_high_48h" | "quarantine_medium_7d" | "quarantine_low_14d" | "unreachable_strike" | "skipped"
    severity: Optional[str] = None
    grace_hours: Optional[int] = None
    detail: Optional[str] = None
    # §MCPTEST30 (V0561): the trust domain the console places the row by (the peer row's column, else its signed card)
    trust_domain: Optional[str] = None


class PreviewQuarantineResponse(BaseModel):
    generated_at: str
    mode_at_check: str
    total_peers: int
    would_quarantine_count: int
    would_noop_count: int
    skipped_count: int
    peers: List[PreviewQuarantineRow]


class PollNowRequest(BaseModel):
    dry_run_only: bool = Field(
        True,
        description=(
            "If True, the poll runs in a forced dry-run mode regardless of the "
            "persisted enforcement mode. Default True to keep admin previews safe."
        ),
    )


class TrustBundleFrame(BaseModel):
    """One frame of this federation (this registry, or an ACTIVE peer the frame manifest calls a frame)."""
    trust_domain: str
    name: Optional[str] = None
    ca_count: int = Field(0, description="CA certificates of this frame in THIS registry's own trust bundle")


class TrustBundleOpRow(BaseModel):
    """One cloud operator's gateway: does its mTLS client-CA bundle trust each frame's CA?

    `error` is set (and `trusts` left empty) when the gateway's bundle could not be read — that op never 500s the
    whole matrix. §MCPTEST30 (V0561): keyed by trust domain, the federation's actual frames, not the retired A/B/C.
    """
    op: str
    frame: Optional[str] = None
    trusts: Dict[str, Optional[bool]] = Field(default_factory=dict)
    complete: Optional[bool] = None
    missing: List[str] = Field(default_factory=list)
    error: Optional[str] = None


class TrustBundleMatrix(BaseModel):
    scanned_at: str
    source: str = Field(..., description="Where the frames' reference CA sets were read: this registry's own trust bundle")
    frames: List[TrustBundleFrame] = Field(default_factory=list)
    total: int
    complete: int
    drift: int
    errors: int = Field(0, description="Number of ops whose bundle could not be read")
    frame_ca_error: Optional[str] = Field(
        None,
        description=(
            "Set when this registry's own trust bundle holds no CA of a frame of the federation: cross-frame mTLS from "
            "that frame is refused HERE, and the per-op flags for that frame are not measured."
        ),
    )
    gateways_readable: bool = Field(True, description="False when this registry cannot read its operators' gateway bundles")
    gateways_unreadable_reason: Optional[str] = None
    ops: List[TrustBundleOpRow]


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_singleton_state(db: AsyncSession) -> RegistryOperatingState:
    result = await db.execute(
        select(RegistryOperatingState).where(
            RegistryOperatingState.id == REGISTRY_STATE_SINGLETON_ID
        )
    )
    state = result.scalar_one_or_none()
    if state is None:
        # Create the singleton row if the f036 seeder didn't run
        state = RegistryOperatingState(id=REGISTRY_STATE_SINGLETON_ID)
        db.add(state)
        await db.commit()
        await db.refresh(state)
    return state


def _effective_enforcement(mode: str) -> bool:
    return (
        mode == MODE_ENFORCING
        and bool(getattr(settings, "FEDERATION_ENFORCEMENT_ACTIVE", False))
        and bool(getattr(settings, "IS_CENTRAL_REGISTRY", False))
    )


def _peer_slug(peer: PeerRegistry) -> str:
    """The operator_id a peer row with no diagnostics target goes by: its name, slugged."""
    return _re.sub(r"[^a-z0-9]+", "-", (peer.name or f"peer-{peer.id}").lower()).strip("-") or f"peer-{peer.id}"


def _peer_only_target(peer: PeerRegistry) -> Dict[str, Any]:
    """A peer row as a target: named by the peer itself — its name as the slug, its trust domain as the frame, its
    type as the role, its base URL as the address. The overview's peer-only rows and the per-operator detail both
    take it from here, so an operator_id the overview lists is one the detail can resolve."""
    slug = _peer_slug(peer)
    return {"operator_id": slug, "display_name": peer.name or slug, "frame": peer.trust_domain or peer.name or "?",
            "role": peer.peer_type or "peer", "cloud_url": peer.base_url, "containers": {}}


def _peer_only_row(peer: PeerRegistry, compliance: Optional[FederatedRegistryCompliance]) -> "PeerComplianceRow":
    """A peer_registries row with no diagnostics target behind it (every peer of a sovereign frame): the same
    row shape as a target's."""
    return _target_to_row(_peer_only_target(peer), peer, compliance)


def _target_to_row(
    target: Dict[str, Any],
    peer: Optional[PeerRegistry],
    compliance: Optional[FederatedRegistryCompliance],
) -> PeerComplianceRow:
    return PeerComplianceRow(
        operator_id=target["operator_id"],
        display_name=target.get("display_name") or target["operator_id"],
        frame=target.get("frame") or "?",
        role=target.get("role") or "operator",
        cloud_url=target.get("cloud_url"),
        peer_registry_id=peer.id if peer else None,
        peer_name=peer.name if peer else None,
        peer_url=peer.base_url if peer else None,
        peer_status=peer.status if peer else None,
        has_compliance_record=compliance is not None,
        federation_status=getattr(compliance, "federation_status", None),
        compliance_score=getattr(compliance, "compliance_score", None),
        drift_events_count=getattr(compliance, "drift_events_count", None),
        consecutive_poll_failures=getattr(compliance, "consecutive_poll_failures", None),
        last_poll_at=(
            compliance.last_poll_at.isoformat()
            if compliance and compliance.last_poll_at
            else None
        ),
        last_hash_mismatch_at=(
            compliance.last_hash_mismatch_at.isoformat()
            if compliance and compliance.last_hash_mismatch_at
            else None
        ),
        quarantine_reason=getattr(compliance, "quarantine_reason", None),
        quarantine_since=(
            compliance.quarantine_since.isoformat()
            if compliance and compliance.quarantine_since
            else None
        ),
        grace_expires=(
            compliance.quarantine_grace_expires.isoformat()
            if compliance and compliance.quarantine_grace_expires
            else None
        ),
        admitted_at=(
            compliance.admitted_at.isoformat()
            if compliance and getattr(compliance, "admitted_at", None)
            else None
        ),
        baseline_hash=getattr(compliance, "policy_hash", None),
        baseline_source=getattr(compliance, "admitted_by", None),
    )


# ── Peer identity (§MCPTEST30, V0561) ─────────────────────────────────────────

def _identity_of(peer: Optional[PeerRegistry], names: List[str], topology: Dict[str, str]) -> tuple:
    """(trust_domain, source) by the cross-frame resolver's order (services/spiffe_canonical.resolve_target_trust_domain):
    the peer row's trust_domain column, then its signed cached card, then the topology cache by name. (None,
    'unresolved') when none answers: a cross-frame financial operation to that peer would be refused."""
    from agentvault_registry.services.spiffe_canonical import _normalize_name, card_trust_domain
    if peer is not None and (peer.trust_domain or "").strip():
        return peer.trust_domain.strip().lower(), "column"
    if peer is not None:
        td = card_trust_domain(peer)
        if td:
            return td, "card"
    for n in names:
        td = topology.get(_normalize_name(n or ""))
        if td:
            return td, "bfs"
    return None, "unresolved"


def _frames_by_trust_domain(peers: List[PeerRegistry]) -> Dict[str, Dict[str, Optional[str]]]:
    """{trust domain: {name, currency}} for every frame of this federation: this registry when it is a frame, and every
    ACTIVE peer row the frame manifest would call a frame (core/federation_view: the same entries, the same role rule, a
    name shown from a verified card only). A peer is placed in the frame that shares its trust domain (a frame and its
    operators share one). Pure: it reads the rows the caller already loaded, never the database."""
    from agentvault_registry.core import federation_view as fv
    entries = [fv.self_entry()]
    for p in peers:
        if (p.status or "").upper() != "ACTIVE":
            continue
        card = p.cached_registry_card if isinstance(p.cached_registry_card, dict) else None
        e = fv.entry_from_card(card, name=p.name or "", base_url=p.base_url, peer_type=p.peer_type,
                               verified=bool(getattr(p, "card_signature_verified", False)) and card is not None)
        if not e.get("trust_domain") and (p.trust_domain or "").strip():
            e["trust_domain"] = p.trust_domain.strip().lower()
        entries.append(e)
    out: Dict[str, Dict[str, Optional[str]]] = {}
    for e in fv.resolve_parents(entries):
        if e.get("role") == fv.ROLE_FRAME and e.get("trust_domain"):
            out.setdefault(e["trust_domain"], {"name": e.get("display_name") or e.get("name"), "currency": e.get("currency")})
    return out


async def _topology_trust_domains() -> Dict[str, str]:
    """{normalized registry name: trust domain} from the topology cache the cross-frame resolver reads third
    (routers/agent_locations). A read of the cache only, bounded at 3 s: the overview never starts a topology walk.
    {} when the cache cannot be read (the row then says 'unresolved', never a guessed domain)."""
    from agentvault_registry.services.spiffe_canonical import _normalize_name
    try:
        from agentvault_registry.routers.agent_locations import _load_trusted_cache_from_redis
        regs, _ts = await _asyncio.wait_for(_load_trusted_cache_from_redis(), timeout=3.0)
    except Exception as exc:  # noqa: BLE001
        logger.info("[CONSUL] topology cache unavailable for peer identity: %s", exc)
        return {}
    out: Dict[str, str] = {}
    for r in regs or []:
        if isinstance(r, dict) and r.get("name") and r.get("trust_domain"):
            out.setdefault(_normalize_name(str(r["name"])), str(r["trust_domain"]).strip().lower())
    return out


def _with_identity(row: "PeerComplianceRow", peer: Optional[PeerRegistry], frames: Dict[str, Dict[str, Optional[str]]],
                   topology: Dict[str, str]) -> "PeerComplianceRow":
    td, source = _identity_of(peer, [row.peer_name or "", row.display_name, row.operator_id], topology)
    home = frames.get(td) if td else None
    return row.model_copy(update={
        "trust_domain": td,
        "resolution_state": "resolved" if td else "unidentified",
        "resolution_source": source,
        "home_frame": (home or {}).get("name"),
        "currency_zone": (home or {}).get("currency"),
    })


def _is_self_echo(peer: PeerRegistry) -> bool:
    """A peer row naming this registry itself (the fan-out echoes every registry's card back to it: measured on the
    sandbox 2026-10-03, sbxalphaop and sbxbetaop each hold an ACTIVE `discovered` row for themselves). The frame
    manifest's own rule (core/federation_view.dedupe_peers): the same key, or the same public host."""
    from agentvault_registry.core import federation_view as fv
    me = fv.self_entry()
    if fv.key_of(peer.name) == me.get("key"):
        return True
    host = fv.host_of(me.get("public_url"))
    return bool(host) and fv.host_of(peer.base_url) == host


async def _peer_targets(db: AsyncSession) -> List[Dict[str, Any]]:
    """The Command Center's targets that are peers of this registry. §MCPTEST30 (V0564): since V0562 that list opens with
    this registry itself (`self`), which is no peer of its own: measured after V0563 on the sandbox and on production,
    every registry's compliance page listed itself as a target never admitted (sbx-alpha: 6 targets where it federates
    with 5) and the quarantine preview read its own policy as a peer's. Every read of the targets here goes through this."""
    return [t for t in await list_diag_targets(db) if not t.get("self")]


def _target_base_url(target: Dict[str, Any]) -> Optional[str]:
    """Public base URL to hit the target's /admin/federation/policy-compliance endpoint."""
    if target.get("cloud_url"):
        return target["cloud_url"]
    # Mainframes have an event_store_public_url hint but no explicit registry URL;
    # fall back to well-known production URLs.
    op_id = target["operator_id"]
    if op_id == "registry-a":
        return "https://api.theprotocol.cloud"
    if op_id == "frame-b":
        return "https://frame-b.theprotocol.cloud"
    # §57 sweep (2026-07-30): Frame C was missing here even though §CONSULFIX
    # already added it to the trust-domain resolver in this same file — the
    # "A and B enumerated, C forgotten" shape survives a targeted fix unless
    # every A/B pair in the file is checked. Frame C is a PROD mainframe.
    if op_id == "frame-c":
        return "https://frame-c.theprotocol.cloud"
    return None


def _match_peer_registry(
    target: Dict[str, Any],
    peers_by_key: Dict[str, PeerRegistry],
) -> Optional[PeerRegistry]:
    """Best-effort mapping from a Docker target to a PeerRegistry row.
    Keys tried: operator_id (slug), target display_name (case-insensitive), target base_url."""
    op_id = target["operator_id"].lower()
    name = (target.get("display_name") or "").lower()
    base = (_target_base_url(target) or "").lower().rstrip("/")
    for key, peer in peers_by_key.items():
        if key == op_id or key == name:
            return peer
        # URL prefix match (peer.base_url may have different port/path)
        peer_base = (peer.base_url or "").lower().rstrip("/")
        if base and peer_base and (peer_base.startswith(base) or base.startswith(peer_base)):
            return peer
    return None


def _index_peers(peers: List[PeerRegistry]) -> Dict[str, PeerRegistry]:
    idx: Dict[str, PeerRegistry] = {}
    for p in peers:
        if p.name:
            idx[p.name.lower()] = p
            # also index by slugified name
            slug = p.name.lower().replace(" ", "-")
            idx[slug] = p
    return idx


# ── Frame-membership probe (cached) ───────────────────────────────────────────
# The diagnostics targets module hard-codes frame="A" for all cloud operators
# because it pre-dates Frame B. Fix in the CONSUL layer by probing each
# operator container's SPIRE_TRUST_DOMAIN env var. Cached per process lifetime.

_frame_cache: Dict[str, str] = {}
_frame_cache_lock = _asyncio.Lock()


def _infer_frame_from_trust_domain(trust_domain: Optional[str]) -> str:
    """Map a SPIRE trust domain to its frame letter.

    §CONSULFIX (2026-07-27): Frame C was missing, so all four frame-c cloud-ops
    (abudhabi/doha/riyadh/telaviv) rendered as `?` in the CONSUL frame column, the
    trust-bundle matrix and the "UNMAPPED" target group — even though they are fully
    federated and green. Live values: `agentvault.com` (A), `frame-b.theprotocol.cloud` (B),
    `frame-c.theprotocol.cloud` (C). Note the docstring above this block already admitted the
    helper "pre-dates Frame B" and was patched once for B; C then repeated the omission.
    Frame checks come FIRST because a future frame domain could also contain a substring of
    the Frame A domain.
    """
    td = (trust_domain or "").lower()
    if "frame-b" in td:
        return "B"
    if "frame-c" in td:
        return "C"
    if "agentvault.com" in td:
        return "A"
    return "?"


async def _probe_operator_frame(container_name: str) -> str:
    """Return 'A' | 'B' | '?' based on the operator container's SPIRE_TRUST_DOMAIN."""
    if container_name in _frame_cache:
        return _frame_cache[container_name]
    probe = get_probe()

    def _sync() -> str:
        try:
            client = probe._client_sync()
            container = client.containers.get(container_name)
            env = container.attrs.get("Config", {}).get("Env", []) or []
            for entry in env:
                if entry.startswith("SPIRE_TRUST_DOMAIN="):
                    return _infer_frame_from_trust_domain(entry.split("=", 1)[1])
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"[CONSUL] frame probe failed for {container_name}: {exc}")
        return "?"

    frame = await _asyncio.to_thread(_sync)
    async with _frame_cache_lock:
        _frame_cache[container_name] = frame
    return frame


async def _resolve_frame(target: Dict[str, Any]) -> str:
    """Resolve the target's frame from live container env (operators) or the
    hardcoded mainframe field."""
    if target.get("role") == "mainframe":
        return target.get("frame") or "?"
    registry_container = (target.get("containers") or {}).get("registry")
    if not registry_container:
        return target.get("frame") or "?"
    return await _probe_operator_frame(registry_container)


async def _fetch_live_policy(
    base_url: str, timeout_seconds: float = 10.0, full: bool = False
) -> tuple[Optional[str], Optional[Dict[str, Any]], Optional[str]]:
    """
    Fetch the peer's /policy-compliance endpoint.
    Returns (policy_hash, policy_json_or_none, error_message_or_none).
    The live endpoint currently returns only the hash, so policy_json_or_none
    will typically be None — the UI falls back to showing the admitted JSON only.
    With full=True the second element is the whole answer (hash, version, source, timestamp) instead (§MCPTEST30, V0561).
    """
    # Federation-namespaced endpoint — mTLS-auth'd via the peer's :8443 sidecar
    # (require_peer_registry_identity), the SAME path compliance_poller uses. NOT the
    # admin-JWT endpoint (/api/v1/admin/federation/policy-compliance): a cert-only client
    # has no admin JWT, so that one 401s. Identical response shape (policy_hash). [2026-05-29]
    url = f"{base_url.rstrip('/')}/api/v1/federation/policy-compliance"
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds, verify=get_httpx_verify()) as client:
            resp = await client.get(url)
        if resp.status_code != 200:
            return (None, None, f"HTTP {resp.status_code}")
        data = resp.json()
        return (data.get("policy_hash") or None, data if full else data.get("policy_json"), None)
    except (httpx.ConnectError, httpx.TimeoutException, httpx.RequestError) as exc:
        return (None, None, f"{type(exc).__name__}: {exc}")
    except Exception as exc:  # noqa: BLE001
        return (None, None, f"unexpected: {exc}")


def _deep_get(d: Dict[str, Any], path: str) -> Any:
    node: Any = d
    for key in path.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(key)
        if node is None:
            return None
    return node


def _build_diff(
    admitted_json: Optional[Dict[str, Any]],
    live_json: Optional[Dict[str, Any]],
) -> List[PolicyDiffEntry]:
    """
    Compare admitted vs live JSON against every LOCKED_PARAMS path.
    Only called when both admitted and live JSONs are available.
    """
    if not admitted_json or not live_json:
        return []
    entries: List[PolicyDiffEntry] = []
    for path in LOCKED_PARAMS.keys():
        stored = _deep_get(admitted_json, path)
        live = _deep_get(live_json, path)
        match = stored == live
        severity_obj = PARAM_SEVERITY.get(path)
        entries.append(
            PolicyDiffEntry(
                path=path,
                stored_value=stored,
                live_value=live,
                match=match,
                severity=severity_obj.value if severity_obj else None,
            )
        )
    return entries


def _would_action_for_severity(sev: DriftSeverity) -> tuple[str, int]:
    grace_hours = GRACE_PERIOD_HOURS.get(sev, 48)
    if grace_hours == 0:
        return ("quarantine_critical", 0)
    if sev == DriftSeverity.HIGH:
        return ("quarantine_high_48h", grace_hours)
    if sev == DriftSeverity.MEDIUM:
        return ("quarantine_medium_7d", grace_hours)
    return ("quarantine_low_14d", grace_hours)


# ── Cross-frame trust-bundle drift (ports federation_trust_drift_scan.sh) ──────
# For every cloud-op, assert its federation gateway's mTLS client-CA bundle
# (/certs/bundle.0.pem inside cloud-op-op-<slug>-nginx-federation) trusts ALL
# THREE frame SPIRE CAs. A missing frame CA == that op rejects cross-frame
# clients from that frame (nginx "400 No required SSL certificate was sent") →
# AGORA passport 502s. The 3 frame CA reference sets are read live from the
# local SPIRE server, so rotating fingerprints are handled automatically.

_CERT_PEM_RE = _re.compile(
    r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----",
    _re.DOTALL,
)


def _fingerprints_of_pem(pem_text: str) -> set[str]:
    """Return the set of SHA-256 fingerprints (hex, no colons, lowercase) of
    every CERTIFICATE block in `pem_text`. Pure-Python via `cryptography`."""
    fps: set[str] = set()
    if not pem_text or "-----BEGIN CERTIFICATE-----" not in pem_text:
        return fps
    try:
        from cryptography import x509
        from cryptography.hazmat.backends import default_backend
        from cryptography.hazmat.primitives import hashes
    except Exception as exc:  # noqa: BLE001 — cryptography is a hard dep, but be defensive
        logger.warning(f"[CONSUL trust-matrix] cryptography import failed: {exc}")
        return fps
    for block in _CERT_PEM_RE.findall(pem_text):
        try:
            cert = x509.load_pem_x509_certificate(block.encode("utf-8"), default_backend())
            fps.add(cert.fingerprint(hashes.SHA256()).hex().lower())
        except Exception as exc:  # noqa: BLE001 — skip an unparseable cert, keep the rest
            logger.debug(f"[CONSUL trust-matrix] cert parse skip: {exc}")
    return fps


def _bundle_path() -> str:
    """This registry's own trust bundle. V0562: the reader lives in services/trust_bundle (the Command Center's own-frame
    check reads it too); the name stays here, where the V0561 roll driver's live check imports it."""
    from agentvault_registry.services import trust_bundle
    return trust_bundle.bundle_path()


def _ca_sets_by_trust_domain(pem_text: str) -> Dict[str, set]:
    """{trust domain: {sha256 fingerprints}} of the CA certificates in `pem_text` (services/trust_bundle, V0562)."""
    from agentvault_registry.services import trust_bundle
    return trust_bundle.ca_sets_by_trust_domain(pem_text)


def _gateways_unreadable_reason() -> Optional[str]:
    """None when this registry can read its operators' gateway containers (a Docker socket); else why it cannot."""
    if os.getenv("DOCKER_HOST") or os.path.exists("/var/run/docker.sock"):
        return None
    return ("this registry holds no Docker socket (F6), so it cannot read its operators' gateway bundles; whether each "
            "peer answers over mTLS is the corridors section's measurement")


_OP_FED_GATEWAY_RE = _re.compile(r"^cloud-op-op-(?P<slug>.+)-nginx-federation$")


def _op_slug_from_gateway(container_name: str) -> Optional[str]:
    m = _OP_FED_GATEWAY_RE.match(container_name)
    return m.group("slug") if m else None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get(
    "/enforcement-mode",
    response_model=EnforcementModeRead,
    summary="Read current CONSUL enforcement mode",
)
async def read_mode(db: AsyncSession = Depends(get_db)) -> EnforcementModeRead:
    state = await _get_singleton_state(db)
    mode = state.compliance_enforcement_mode or MODE_OFF
    return EnforcementModeRead(
        mode=mode,
        enforcement_env_flag=bool(getattr(settings, "FEDERATION_ENFORCEMENT_ACTIVE", False)),
        is_central_registry_env_flag=bool(getattr(settings, "IS_CENTRAL_REGISTRY", False)),
        effective_enforcement=_effective_enforcement(mode),
        last_changed_at=(
            state.compliance_mode_updated_at.isoformat()
            if state.compliance_mode_updated_at
            else None
        ),
        last_changed_by=state.compliance_mode_updated_by,
    )


@router.post(
    "/enforcement-mode",
    response_model=EnforcementModeRead,
    summary="Set CONSUL enforcement mode (kill switch)",
)
async def set_mode(
    request: EnforcementModeWrite,
    db: AsyncSession = Depends(get_db),
    admin: Developer = Security(security.require_admin_flag("admin_platform")),
) -> EnforcementModeRead:
    if request.mode not in VALID_MODES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"mode must be one of {VALID_MODES}",
        )

    state = await _get_singleton_state(db)
    previous = state.compliance_enforcement_mode

    if previous == request.mode:
        logger.info(
            f"[CONSUL] enforcement-mode unchanged (already '{request.mode}') — "
            f"requested by {admin.email}"
        )
    else:
        state.compliance_enforcement_mode = request.mode
        state.compliance_mode_updated_at = datetime.now(timezone.utc)
        state.compliance_mode_updated_by = admin.email
        await db.commit()
        await db.refresh(state)

        try:
            emitter = get_event_emitter()
            await emitter.emit(
                event_type="ComplianceEnforcementModeChanged",
                aggregate_id="system",
                aggregate_type="Registry",
                data={
                    "previous_mode": previous,
                    "new_mode": request.mode,
                    "reason": request.reason,
                    "changed_by": admin.email,
                    "enforcement_env_flag": bool(
                        getattr(settings, "FEDERATION_ENFORCEMENT_ACTIVE", False)
                    ),
                    "is_central_registry_env_flag": bool(
                        getattr(settings, "IS_CENTRAL_REGISTRY", False)
                    ),
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                f"[CONSUL] Failed to emit ComplianceEnforcementModeChanged "
                f"(non-fatal): {exc}"
            )

        logger.warning(
            f"[CONSUL] enforcement-mode changed: {previous} → {request.mode} "
            f"by {admin.email}: {request.reason}"
        )

    return EnforcementModeRead(
        mode=state.compliance_enforcement_mode,
        enforcement_env_flag=bool(
            getattr(settings, "FEDERATION_ENFORCEMENT_ACTIVE", False)
        ),
        is_central_registry_env_flag=bool(
            getattr(settings, "IS_CENTRAL_REGISTRY", False)
        ),
        effective_enforcement=_effective_enforcement(state.compliance_enforcement_mode),
        last_changed_at=(
            state.compliance_mode_updated_at.isoformat()
            if state.compliance_mode_updated_at
            else None
        ),
        last_changed_by=state.compliance_mode_updated_by,
    )


@router.get(
    "/reachability",
    summary="Federation corridor reachability — which peers actually answer, and why not",
)
async def get_reachability(
    include_ok: bool = True,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Per-peer corridor health with a diagnosis.

    Separate from /overview so the FE, an operator, or a probe can ask the narrow question
    cheaply. States: OK · STALE · NEVER_SYNCED · UNREACHABLE · PENDING. NEVER_SYNCED is the
    one that matters most — it is the state that hid the frame-c trust-domain gap for seven
    weeks behind ACTIVE + failures=0.
    """
    from agentvault_registry.services import federation_reachability
    return await federation_reachability.build_report(db, include_ok=include_ok)


@router.get(
    "/overview",
    response_model=ComplianceOverview,
    summary="CONSUL fleet overview — live 2-mainframe + N-operator topology from Docker discovery",
)
async def get_overview(db: AsyncSession = Depends(get_db)) -> ComplianceOverview:
    state = await _get_singleton_state(db)
    mode = state.compliance_enforcement_mode or MODE_OFF

    # Discover the live federation: mainframes (registry-a, frame-b) if their
    # container exists + every running cloud-op-*-registry. This matches the
    # Command Center view and excludes legacy INACTIVE peer_registries rows.
    targets = await _peer_targets(db)

    peers_result = await db.execute(select(PeerRegistry))
    all_peers = list(peers_result.scalars().all())
    peers_by_key = _index_peers(all_peers)

    compliance_result = await db.execute(select(FederatedRegistryCompliance))
    compliances_by_peer_id = {
        row.peer_registry_id: row for row in compliance_result.scalars().all()
    }

    rows: List[PeerComplianceRow] = []
    counters = {
        "peers_federated": 0,
        "peers_quarantined": 0,
        "peers_blacklisted": 0,
        "peers_never_polled": 0,
        "peers_unreachable_streak": 0,
    }
    compliance_matched = 0

    def _count(compliance: Optional[FederatedRegistryCompliance]) -> None:
        nonlocal compliance_matched
        if compliance is None:
            return
        compliance_matched += 1
        fstatus = compliance.federation_status
        if fstatus == "federated":
            counters["peers_federated"] += 1
        elif fstatus in ("quarantined", "soft_quarantined"):
            counters["peers_quarantined"] += 1
        elif fstatus == "blacklisted":
            counters["peers_blacklisted"] += 1
        if compliance.last_poll_at is None:
            counters["peers_never_polled"] += 1
        if (compliance.consecutive_poll_failures or 0) >= 1:
            counters["peers_unreachable_streak"] += 1

    row_peers: List[Optional[PeerRegistry]] = []
    for target in targets:
        # Override frame from the live container env (fixes diagnostics hardcode)
        target = {**target, "frame": await _resolve_frame(target)}
        peer = _match_peer_registry(target, peers_by_key)
        compliance = compliances_by_peer_id.get(peer.id) if peer else None
        _count(compliance)
        rows.append(_target_to_row(target, peer, compliance))
        row_peers.append(peer)
    # §FRAMEKIT P3.1 (2026-09-12): the rows above come from the diagnostics TARGETS (Command Center slugs),
    # which a sovereign frame does not have — EU and ASIA listed NO peers here while ten baseline rows
    # existed (§TRUSTCHAIN, named not fixed). Every ACTIVE peer row the targets did not match, and every
    # peer that holds a compliance record whatever its status, is a row of its own.
    seen_peer_ids = {r.peer_registry_id for r in rows if r.peer_registry_id}
    for peer in sorted(all_peers, key=lambda p_: p_.id):
        if peer.id in seen_peer_ids:
            continue
        compliance = compliances_by_peer_id.get(peer.id)
        if compliance is None and (peer.status or "").upper() != "ACTIVE":
            continue
        # §MCPTEST30 (V0561): a registry's row for itself (the fan-out's echo) is not a peer of it; one that holds a
        # compliance record stays, so nothing the poller wrote disappears from this page unseen
        if compliance is None and _is_self_echo(peer):
            continue
        _count(compliance)
        rows.append(_peer_only_row(peer, compliance))
        row_peers.append(peer)

    # §MCPTEST30 (V0561): each row's identity, by the cross-frame resolver's order; the topology cache is read only when
    # the column and the card both leave a row unresolved
    frames = _frames_by_trust_domain(all_peers)
    topology: Dict[str, str] = {}
    if any(_identity_of(p_, [], {})[0] is None for p_ in row_peers):
        topology = await _topology_trust_domains()
    rows = [_with_identity(r, p_, frames, topology) for r, p_ in zip(rows, row_peers)]

    # Reachability is derived from peer_registries rows the federation fan-out already
    # stamps; it never dials a peer itself, so the overview stays a cheap read.
    try:
        from agentvault_registry.services import federation_reachability
        reachability = await federation_reachability.build_report(db, include_ok=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[CONSUL] reachability block unavailable: %s", exc)
        reachability = None

    return ComplianceOverview(
        reachability=reachability,
        mode=mode,
        enforcement_env_flag=bool(
            getattr(settings, "FEDERATION_ENFORCEMENT_ACTIVE", False)
        ),
        is_central_registry_env_flag=bool(
            getattr(settings, "IS_CENTRAL_REGISTRY", False)
        ),
        effective_enforcement=_effective_enforcement(mode),
        poller_enabled=bool(getattr(settings, "IS_CENTRAL_REGISTRY", False)),
        poll_interval_seconds=POLL_INTERVAL_SECONDS,
        peers_total=len(rows),   # §FRAMEKIT P3.1: every row, not only the diagnostics targets
        peers_with_compliance=compliance_matched,
        peers=rows,
        **counters,
    )


class PeerDetailExtended(PeerDetail):
    operator_id: str
    display_name: str
    frame: str
    role: str
    has_compliance_record: bool


@router.get(
    "/peers/by-operator/{operator_id}",
    response_model=PeerDetailExtended,
    summary="Per-target CONSUL detail by operator slug (live Docker-discovered)",
)
async def get_peer_detail_by_operator(
    operator_id: str, db: AsyncSession = Depends(get_db)
) -> PeerDetailExtended:
    targets = await _peer_targets(db)
    target = next((t for t in targets if t["operator_id"] == operator_id), None)
    peers_result = await db.execute(select(PeerRegistry))
    all_peers = list(peers_result.scalars().all())
    peers_by_key = _index_peers(all_peers)
    if target is not None:
        target = {**target, "frame": await _resolve_frame(target)}
        peer = _match_peer_registry(target, peers_by_key)
    else:
        # §MCPTEST30 (2026-10-01): the overview lists every peer row no target matched too (§FRAMEKIT P3.1), named by
        # _peer_slug, so an operator_id it advertised answered 404 here (measured on the sandbox: the MCP tester took
        # the overview's first row with a compliance record and the detail could not find it). Resolve the same rows.
        matched = set()
        for t in targets:
            m = _match_peer_registry({**t, "frame": await _resolve_frame(t)}, peers_by_key)
            if m is not None:
                matched.add(m.id)
        peer = next((p_ for p_ in sorted(all_peers, key=lambda p_: p_.id)
                     if p_.id not in matched and _peer_slug(p_) == operator_id), None)
        if peer is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"operator_id={operator_id!r} is neither a live Docker-discovered target nor a peer row",
            )
        target = _peer_only_target(peer)

    compliance = None
    if peer is not None:
        c_result = await db.execute(
            select(FederatedRegistryCompliance).where(
                FederatedRegistryCompliance.peer_registry_id == peer.id
            )
        )
        compliance = c_result.scalar_one_or_none()

    base_url = _target_base_url(target) or (peer.base_url if peer else None)
    live_hash: Optional[str] = None
    live_json: Optional[Dict[str, Any]] = None
    live_version: Any = None
    live_source: Optional[str] = None
    fetch_error: Optional[str] = None
    if target.get("role") == "mainframe":
        # Mainframes are the POLLER, not the polled — and there's no mTLS-forwarding path to
        # probe one over its public :443 URL. Skip the live probe entirely (avoids the
        # spurious "unreachable · HTTP 401"); the UI already states compliance N/A here. [2026-05-29]
        pass
    else:
        # Probe the peer's :8443 mTLS SIDECAR URL so our SVID is forwarded + validated by the
        # federation endpoint. The public :443 URL (Option C, ssl_verify_client off) cannot
        # carry the client cert → 401. peer.base_url is the canonical :8443 form. [2026-05-29]
        probe_url = (peer.base_url if peer else None) or base_url
        if probe_url:
            live_hash, live_answer, fetch_error = await _fetch_live_policy(probe_url, full=True)
            if isinstance(live_answer, dict):
                live_version, live_source = live_answer.get("policy_version"), live_answer.get("policy_source")
                live_json = live_answer.get("policy_json") if isinstance(live_answer.get("policy_json"), dict) else None
        else:
            fetch_error = "no base URL available"

    admitted_json = compliance.policy_json if compliance else None
    admitted_hash = compliance.policy_hash if compliance else None
    hash_match: Optional[bool] = None
    if admitted_hash and live_hash:
        hash_match = admitted_hash == live_hash
    # §TRUSTCHAIN: a first-sight baseline stores the observation (hash, version, source), not the
    # peer's policy document, so there is nothing to diff field by field; the hash comparison
    # above is the whole check for such a row.
    # §MCPTEST30 (V0561): an ACCEPTED baseline is an observation record too (BASELINE_ACCEPTED), never a document to diff
    _first_sight = bool(admitted_json) and admitted_json.get("baseline_source") in ("compliance_poller:first_sight", BASELINE_ACCEPTED)
    diff = _build_diff(admitted_json, live_json) if admitted_json and live_json and not _first_sight else None
    try:
        live_version_int = int(live_version) if live_version is not None else None
    except (TypeError, ValueError):
        live_version_int = None

    return PeerDetailExtended(
        operator_id=target["operator_id"],
        display_name=target.get("display_name") or target["operator_id"],
        frame=target.get("frame") or "?",
        role=target.get("role") or "operator",
        has_compliance_record=compliance is not None,
        baseline_source=getattr(compliance, "admitted_by", None),
        baseline_hash=getattr(compliance, "policy_hash", None),
        peer_registry_id=peer.id if peer else 0,  # 0 sentinel when not mapped
        peer_name=peer.name if peer else (target.get("display_name") or target["operator_id"]),
        peer_url=peer.base_url if peer else (base_url or ""),
        peer_status=peer.status if peer else "LIVE",
        federation_status=getattr(compliance, "federation_status", None),
        compliance_score=getattr(compliance, "compliance_score", None),
        drift_events_count=getattr(compliance, "drift_events_count", None),
        consecutive_poll_failures=getattr(compliance, "consecutive_poll_failures", None),
        last_poll_at=(
            compliance.last_poll_at.isoformat()
            if compliance and compliance.last_poll_at
            else None
        ),
        last_hash_mismatch_at=(
            compliance.last_hash_mismatch_at.isoformat()
            if compliance and compliance.last_hash_mismatch_at
            else None
        ),
        quarantine_reason=getattr(compliance, "quarantine_reason", None),
        quarantine_since=(
            compliance.quarantine_since.isoformat()
            if compliance and compliance.quarantine_since
            else None
        ),
        quarantine_events=(
            list(compliance.quarantine_events or []) if compliance else None
        ),
        admitted_policy_hash=admitted_hash,
        live_policy_hash=live_hash,
        hash_match=hash_match,
        live_policy_fetched=live_hash is not None,
        live_fetch_error=fetch_error,
        admitted_policy_json=admitted_json,
        live_policy_json=live_json,
        diff=diff,
        admitted_policy_version=getattr(compliance, "policy_version", None),
        admitted_policy_source=(admitted_json or {}).get("policy_source") if isinstance(admitted_json, dict) else None,
        live_policy_version=live_version_int,
        live_policy_source=live_source,
    )


@router.get(
    "/peers/{peer_id}",
    response_model=PeerDetail,
    summary="Per-peer detail by PeerRegistry.id (integer) — legacy shape, kept for admitted peers",
)
async def get_peer_detail(
    peer_id: int, db: AsyncSession = Depends(get_db)
) -> PeerDetail:
    peer_result = await db.execute(
        select(PeerRegistry).where(PeerRegistry.id == peer_id)
    )
    peer = peer_result.scalar_one_or_none()
    if peer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"peer_registry_id={peer_id} not found",
        )

    compliance_result = await db.execute(
        select(FederatedRegistryCompliance).where(
            FederatedRegistryCompliance.peer_registry_id == peer_id
        )
    )
    compliance = compliance_result.scalar_one_or_none()

    live_hash, live_json, fetch_error = await _fetch_live_policy(peer.base_url)

    admitted_json = compliance.policy_json if compliance else None
    admitted_hash = compliance.policy_hash if compliance else None

    hash_match: Optional[bool] = None
    if admitted_hash and live_hash:
        hash_match = admitted_hash == live_hash

    # §TRUSTCHAIN: a first-sight baseline stores the observation (hash, version, source), not the
    # peer's policy document, so there is nothing to diff field by field; the hash comparison
    # above is the whole check for such a row.
    # §MCPTEST30 (V0561): an ACCEPTED baseline is an observation record too (BASELINE_ACCEPTED), never a document to diff
    _first_sight = bool(admitted_json) and admitted_json.get("baseline_source") in ("compliance_poller:first_sight", BASELINE_ACCEPTED)
    diff = _build_diff(admitted_json, live_json) if admitted_json and live_json and not _first_sight else None

    return PeerDetail(
        peer_registry_id=peer.id,
        peer_name=peer.name,
        peer_url=peer.base_url,
        peer_status=peer.status,
        baseline_source=getattr(compliance, "admitted_by", None),
        baseline_hash=getattr(compliance, "policy_hash", None),
        federation_status=getattr(compliance, "federation_status", None),
        compliance_score=getattr(compliance, "compliance_score", None),
        drift_events_count=getattr(compliance, "drift_events_count", None),
        consecutive_poll_failures=getattr(compliance, "consecutive_poll_failures", None),
        last_poll_at=(
            compliance.last_poll_at.isoformat()
            if compliance and compliance.last_poll_at
            else None
        ),
        last_hash_mismatch_at=(
            compliance.last_hash_mismatch_at.isoformat()
            if compliance and compliance.last_hash_mismatch_at
            else None
        ),
        quarantine_reason=getattr(compliance, "quarantine_reason", None),
        quarantine_since=(
            compliance.quarantine_since.isoformat()
            if compliance and compliance.quarantine_since
            else None
        ),
        quarantine_events=(
            list(compliance.quarantine_events or []) if compliance else None
        ),
        admitted_policy_hash=admitted_hash,
        live_policy_hash=live_hash,
        hash_match=hash_match,
        live_policy_fetched=live_hash is not None,
        live_fetch_error=fetch_error,
        admitted_policy_json=admitted_json,
        live_policy_json=live_json,
        diff=diff,
    )


@router.get(
    "/events",
    summary="Tail of recent CONSUL compliance events from the EventStore",
)
async def list_events(
    limit: int = Query(50, ge=1, le=500),
    event_types: Optional[str] = Query(
        None,
        description=(
            "Comma-separated event types to filter. Defaults to the CONSUL event types: ComplianceDryRunDrift, "
            "ComplianceEnforcementModeChanged, CompliancePollCycleCompleted, ComplianceBaselineRecorded, "
            "ComplianceBaselineAccepted, RegistryQuarantined, RegistryQuarantineLifted, RegistryBlacklisted."
        ),
    ),
):
    default_types = [
        "ComplianceDryRunDrift",
        "ComplianceEnforcementModeChanged",
        "CompliancePollCycleCompleted",
        # §MCPTEST30 (V0561): a baseline's arrival (first sight) and its acceptance by an admin are compliance events too
        "ComplianceBaselineRecorded",
        "ComplianceBaselineAccepted",
        "RegistryQuarantined",
        "RegistryQuarantineLifted",
        "RegistryBlacklisted",
    ]
    types = (
        [t.strip() for t in event_types.split(",") if t.strip()]
        if event_types
        else default_types
    )

    event_store_url = (
        getattr(settings, "EVENT_STORE_URL", None)
        or "http://event-store:8200"
    )
    internal_key = (
        getattr(settings, "EVENT_STORE_API_KEY", None)
        or getattr(settings, "EVENT_STORE_INTERNAL_KEY", None)
    )
    headers: Dict[str, str] = {}
    if internal_key:
        headers["X-Internal-Key"] = internal_key

    all_events: List[Dict[str, Any]] = []
    per_type_limit = max(10, limit // max(1, len(types)))
    # §MCPTEST30 (V0561): a type the store did not answer is NAMED, never dropped. An unreachable store used to read as
    # an empty ledger, and the console explained the empty list as "the poller has not run, or mode is off".
    unreadable: List[Dict[str, str]] = []
    async with httpx.AsyncClient(timeout=10.0, headers=headers, verify=get_httpx_verify()) as client:
        for t in types:
            try:
                resp = await client.get(
                    f"{event_store_url.rstrip('/')}/api/v1/events/",
                    params={"event_type": t, "limit": per_type_limit},
                )
                if resp.status_code != 200:
                    unreadable.append({"event_type": t, "reason": f"HTTP {resp.status_code}"})
                    continue
                body = resp.json()
                items = body.get("events") if isinstance(body, dict) else body
                if isinstance(items, list):
                    all_events.extend(items)
                else:
                    unreadable.append({"event_type": t, "reason": "the store answered without a list"})
            except Exception as exc:  # noqa: BLE001
                unreadable.append({"event_type": t, "reason": f"{type(exc).__name__}: {str(exc)[:120]}"})
    if unreadable:
        logger.warning("[CONSUL] %d of %d compliance event types unreadable: %s", len(unreadable), len(types),
                       ", ".join(f"{u['event_type']} ({u['reason']})" for u in unreadable))

    all_events.sort(key=lambda e: str(e.get("timestamp") or ""), reverse=True)
    out: Dict[str, Any] = {"total": len(all_events[:limit]), "events": all_events[:limit], "unreadable": unreadable}
    if unreadable and len(unreadable) == len(types):
        # one cause for all of them is said once (the PART 1 rule: state a shared cause ONCE)
        reasons = {u["reason"] for u in unreadable}
        out["error"] = (f"the event store could not be read ({next(iter(reasons))})" if len(reasons) == 1
                        else "the event store could not be read for any compliance event type")
    return out


@router.get(
    "/drifts",
    summary="Recent FederationStateDriftDetected events from EventStore",
)
async def list_drifts(
    limit: int = Query(50, ge=1, le=500),
    drift_type: Optional[str] = Query(
        None,
        description=(
            "Filter to one drift_type value. Common: license_revoked_operator_active, "
            "operator_revoked_license_active, peer_inactive_license_active, "
            "frame_bundle_stale."
        ),
    ),
    db: AsyncSession = Depends(get_db),
):
    """Returns recent FederationStateDriftDetected events with optional
    client-side filter on drift_type. Used by the CONSUL drift panel and
    by the flow_drift_detection_complete quality gate.

    Daily idempotency at emission means re-running drift-scan multiple times
    in one UTC day produces no new rows; use `limit` to control how far back.
    """
    event_store_url = (
        getattr(settings, "EVENT_STORE_URL", None)
        or "http://event-store:8200"
    )
    internal_key = (
        getattr(settings, "EVENT_STORE_API_KEY", None)
        or getattr(settings, "EVENT_STORE_INTERNAL_KEY", None)
    )
    headers: Dict[str, str] = {}
    if internal_key:
        headers["X-Internal-Key"] = internal_key

    fetch_limit = limit if not drift_type else min(limit * 4, 500)

    events: List[Dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(timeout=10.0, headers=headers, verify=get_httpx_verify()) as client:
            resp = await client.get(
                f"{event_store_url.rstrip('/')}/api/v1/events/",
                params={"event_type": "FederationStateDriftDetected", "limit": fetch_limit},
            )
            if resp.status_code != 200:
                # §MCPTEST30 (V0561): a refusal is not an empty ledger
                logger.warning(f"[CONSUL] drift fetch answered HTTP {resp.status_code}")
                return {"total": 0, "by_type": {}, "drifts": [],
                        "error": f"the event store answered HTTP {resp.status_code}"}
            body = resp.json()
            events = body.get("events") if isinstance(body, dict) else body or []
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[CONSUL] drift fetch failed: {exc}")
        return {"total": 0, "by_type": {}, "drifts": [], "error": f"the event store could not be read ({str(exc)[:200]})"}

    if drift_type:
        events = [
            e for e in events
            if isinstance(e, dict) and (e.get("data") or {}).get("drift_type") == drift_type
        ]

    events = events[:limit]

    by_type: Dict[str, int] = {}
    for e in events:
        data = e.get("data") or {} if isinstance(e, dict) else {}
        dt = data.get("drift_type") or "?"
        by_type[dt] = by_type.get(dt, 0) + 1

    # §MCPTEST30 (V0561): name the peer a drift is about, and say whether it is still a peer. The events carry a bare
    # peer id; measured on the sandbox 2026-10-03, 25 of 40 rows named peers 5, 17 and 18, all INACTIVE for weeks, and
    # read like live problems ("peer=18 ACTIVE but federation_sync can't reach").
    ids = set()
    for e in events:
        pid = (e.get("data") or {}).get("peer_id") if isinstance(e, dict) else None
        try:
            ids.add(int(pid))
        except (TypeError, ValueError):
            pass
    if ids:
        try:
            rows = (await db.execute(select(PeerRegistry).where(PeerRegistry.id.in_(sorted(ids))))).scalars().all()
            known = {p_.id: p_ for p_ in rows}
            for e in events:
                if not isinstance(e, dict):
                    continue
                try:
                    pid = int((e.get("data") or {}).get("peer_id"))
                except (TypeError, ValueError):
                    continue
                p_ = known.get(pid)
                e["peer"] = ({"id": pid, "name": p_.name, "status": p_.status} if p_ is not None
                             else {"id": pid, "name": None, "status": "DELETED"})
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[CONSUL] drift peer names unavailable: {exc}")

    return {
        "total": len(events),
        "by_type": by_type,
        "drifts": events,
    }


@router.post(
    "/peers/{peer_id}/poll-now",
    summary="Force a single peer's compliance poll cycle (dry-run default)",
)
async def poll_peer_now(
    peer_id: int,
    request: Optional[PollNowRequest] = None,
    admin: Developer = Security(security.require_admin_flag("admin_platform")),
):
    dry_run_only = True if request is None else request.dry_run_only
    poller = get_compliance_poller()
    result = await poller.force_single_peer_poll(peer_id, dry_run_only=dry_run_only)
    logger.info(
        f"[CONSUL] force_single_peer_poll(peer_id={peer_id}, "
        f"dry_run_only={dry_run_only}) by {admin.email} → {result}"
    )
    # §MCPTEST30 (V0550): a peer that does not exist is a 404, not a 200 whose body says "error" (agentvault2-45 found
    # it pinning pollPeerComplianceNow: the sweep's nonexistent peer read as a success). A skip stays a 200: the peer is
    # there and the poller declined, which is an answer.
    if isinstance(result, dict) and result.get("status") == "error" and str(result.get("detail", "")).endswith("not found"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(result.get("detail")))
    return result


# ── Accept a peer's current policy as its baseline (§MCPTEST30, V0561) ─────────
# A peer's policy hash covers its RESOLVED policy document, the shipped defaults included, so a release that changes a
# default moves the hash of every peer running it (measured on the sandbox 2026-10-03: Sandbox Beta, a factory-default
# policy at version 0, and sbxalphaop, version 72 both before and after, each drifted from its first-sight baseline and
# the poller reported a HIGH drift every cycle, "would quarantine" in enforcing mode). The only way to move a baseline
# was lift-quarantine, which takes a hand-typed hash, no reason, and reports "quarantine lifted" for a peer that was
# never quarantined. This route makes the peer's CURRENT policy the baseline: read the way the poller reads it, refused
# unless it is exactly the hash the admin reviewed, with a reason, and recorded on the ledger.

BASELINE_ACCEPTED = "admin:accepted"


class AcceptBaselineRequest(BaseModel):
    expected_hash: str = Field(
        ..., min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$",
        description="The policy hash the admin reviewed (the peer's live hash). Refused when the peer now publishes another.",
    )
    reason: str = Field(..., min_length=5, max_length=500, description="Why this policy is accepted (kept on the ledger)")


def accept_baseline_on(
    compliance: FederatedRegistryCompliance, data: Dict[str, Any], *, admin_email: str, reason: str,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Pure: make the peer's policy-compliance answer `data` the stored baseline of `compliance`, and return the
    event payload. The drift history stays (drift_events_count, last_hash_mismatch_at): accepting a policy does not
    unsay that it changed."""
    now = now or datetime.now(timezone.utc)
    try:
        version = int(data.get("policy_version") or 0)
    except (TypeError, ValueError):
        version = 0
    previous_hash = compliance.policy_hash
    previous_version = compliance.policy_version
    new_hash = str(data["policy_hash"])
    compliance.policy_hash = new_hash
    compliance.policy_version = version
    compliance.policy_json = {
        "baseline_source": BASELINE_ACCEPTED,
        "policy_hash": new_hash,
        "policy_version": version,
        "policy_source": data.get("policy_source"),
        "registry_did": data.get("registry_did"),
        "observed_at": now.isoformat(),
        "accepted_by": admin_email,
        "reason": reason,
        "previous_hash": previous_hash,
        "previous_version": previous_version,
    }
    compliance.admitted_by = admin_email
    compliance.admitted_at = now
    return {
        "peer_registry_id": compliance.peer_registry_id,
        "previous_hash": previous_hash,
        "previous_version": previous_version,
        "new_hash": new_hash,
        "policy_version": version,
        "policy_source": data.get("policy_source"),
        "reason": reason,
        "accepted_by": admin_email,
        "baseline_source": BASELINE_ACCEPTED,
    }


@router.post(
    "/peers/{peer_id}/accept-baseline",
    summary="Accept a federated peer's current policy as its baseline (after a drift you reviewed)",
)
async def accept_peer_baseline(
    peer_id: int,
    request: AcceptBaselineRequest,
    db: AsyncSession = Depends(get_db),
    admin: Developer = Security(security.require_admin_flag("admin_enforcement")),
) -> Dict[str, Any]:
    peer = (await db.execute(select(PeerRegistry).where(PeerRegistry.id == peer_id))).scalar_one_or_none()
    if peer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"peer {peer_id} not found")
    compliance = (await db.execute(
        select(FederatedRegistryCompliance).where(FederatedRegistryCompliance.peer_registry_id == peer_id)
    )).scalar_one_or_none()
    if compliance is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"peer {peer_id} has no baseline yet: the poller records one from its first answer",
        )
    if compliance.federation_status != "federated":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(f"peer {peer_id} is {compliance.federation_status}: a quarantined peer returns through "
                    f"lift-quarantine, and a blacklisted one does not return from the API"),
        )
    if (peer.status or "").upper() != "ACTIVE":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail=f"peer {peer_id} is {peer.status}: the poller does not read it, so there is nothing to accept")
    try:
        data, fetch_error = await get_compliance_poller()._fetch_policy_compliance(peer)
    except (httpx.ConnectError, httpx.TimeoutException, httpx.RequestError) as exc:
        data, fetch_error = None, f"{type(exc).__name__}: {exc}"
    if data is None:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY,
                            detail=f"peer {peer_id} did not answer its policy-compliance endpoint ({fetch_error})")
    live = str(data.get("policy_hash") or "")
    if live != request.expected_hash:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(f"peer {peer_id} now publishes {live[:16]}…, not the {request.expected_hash[:16]}… you reviewed: "
                    f"read its policy again before accepting it"),
        )
    if live == compliance.policy_hash:
        return {"status": "unchanged", "peer_registry_id": peer_id, "baseline_hash": live,
                "baseline_source": compliance.admitted_by}
    payload = accept_baseline_on(compliance, data, admin_email=admin.email, reason=request.reason)
    payload["peer_name"] = peer.name
    payload["peer_url"] = peer.base_url
    await db.commit()
    ledger_recorded = True
    try:
        await get_event_emitter().emit(
            event_type="ComplianceBaselineAccepted",
            aggregate_id=str(peer_id),
            aggregate_type="FederatedRegistry",
            data=payload,
        )
    except Exception as exc:  # noqa: BLE001
        ledger_recorded = False
        logger.error("[CONSUL] ComplianceBaselineAccepted not emitted (the baseline IS stored): %s", exc)
    logger.warning(
        f"[CONSUL] baseline accepted for peer {peer_id} ({peer.name}) by {admin.email}: "
        f"{(payload['previous_hash'] or '')[:16]}… -> {live[:16]}… ({request.reason})"
    )
    # the answer says whether the ledger holds the record: a stored baseline with no event is a change nobody can audit
    return {"status": "accepted", "ledger_recorded": ledger_recorded, **payload}


@router.get(
    "/preview-quarantine",
    response_model=PreviewQuarantineResponse,
    summary="Simulate what the compliance poller would do under enforcing mode, peer by peer",
)
async def preview_quarantine(
    db: AsyncSession = Depends(get_db),
) -> PreviewQuarantineResponse:
    """§MCPTEST30 (V0561): the population is the POLLER'S (compliance_poller._poll_cycle reads every ACTIVE peer row),
    plus any diagnostics target. It used to walk only the diagnostics targets, which a frame without a Docker socket
    (every F6 frame) does not have: Sandbox Alpha previewed one operator of the three peers its poller reads. A peer is
    read the way the poller reads it (its mTLS reader), so the preview cannot disagree with the next cycle about
    whether the peer answered."""
    state = await _get_singleton_state(db)
    mode = state.compliance_enforcement_mode or MODE_OFF

    targets = await _peer_targets(db)

    peers_result = await db.execute(select(PeerRegistry))
    all_peers = list(peers_result.scalars().all())
    peers_by_key = _index_peers(all_peers)

    compliance_result = await db.execute(select(FederatedRegistryCompliance))
    compliances_by_peer_id = {
        row.peer_registry_id: row for row in compliance_result.scalars().all()
    }

    # (target, peer, compliance) — the targets first, then every ACTIVE peer row no target matched
    candidates: List[tuple] = []
    seen: set = set()
    for target in targets:
        target = {**target, "frame": await _resolve_frame(target)}
        peer = _match_peer_registry(target, peers_by_key)
        if peer is not None:
            seen.add(peer.id)
        candidates.append((target, peer, compliances_by_peer_id.get(peer.id) if peer else None))
    for peer in sorted(all_peers, key=lambda p_: p_.id):
        if peer.id in seen or (peer.status or "").upper() != "ACTIVE":
            continue
        compliance = compliances_by_peer_id.get(peer.id)
        if compliance is None and _is_self_echo(peer):
            continue
        candidates.append((_peer_only_target(peer), peer, compliance))

    poller = get_compliance_poller()
    sem = _asyncio.Semaphore(4)

    async def _live_hash(peer: Optional[PeerRegistry], fallback_url: Optional[str]) -> tuple:
        async with sem:
            if peer is not None and peer.base_url:
                try:
                    data, err = await poller._fetch_policy_compliance(peer)
                except (httpx.ConnectError, httpx.TimeoutException, httpx.RequestError) as exc:
                    return None, f"{type(exc).__name__}: {exc}"
                except Exception as exc:  # noqa: BLE001
                    return None, f"unexpected: {exc}"
                return ((data or {}).get("policy_hash") or None), err
            if fallback_url:
                live, _json, err = await _fetch_live_policy(fallback_url)
                return live, err
            return None, "no resolvable base URL"

    async def _row(target: Dict[str, Any], peer: Optional[PeerRegistry],
                   compliance: Optional[FederatedRegistryCompliance]) -> PreviewQuarantineRow:
        op_id = target["operator_id"]
        role = target.get("role") or "operator"
        base = _target_base_url(target)
        common = {
            "operator_id": op_id,
            "display_name": target.get("display_name") or op_id,
            "frame": target.get("frame") or "?",
            "role": role,
            "peer_registry_id": peer.id if peer else None,
            "peer_name": peer.name if peer else None,
            "peer_url": peer.base_url if peer else base,
            "has_compliance_record": compliance is not None,
            "trust_domain": _identity_of(peer, [], {})[0],
        }
        # Mainframes are the pollers, not the polled
        if role == "mainframe":
            return PreviewQuarantineRow(**common, would_action="skipped",
                                        detail="this is a mainframe (poller, not polled)")
        if compliance is None:
            return PreviewQuarantineRow(**common, would_action="skipped",
                                        detail="no baseline yet: the poller records one from the peer's first answer")
        if compliance.federation_status == "blacklisted":
            return PreviewQuarantineRow(**common, would_action="skipped",
                                        detail="peer is blacklisted: the poller skips it")
        live_hash, fetch_error = await _live_hash(peer, base)
        if live_hash is None:
            strike = (compliance.consecutive_poll_failures or 0) + 1
            if strike >= 3 and compliance.federation_status == "federated":
                action, grace = _would_action_for_severity(DriftSeverity.HIGH)
                return PreviewQuarantineRow(
                    **common, reachable=False, would_action=action, severity=DriftSeverity.HIGH.value,
                    grace_hours=grace,
                    detail=f"unreachable ({fetch_error or 'no hash'}): this would be failure {strike} in a row, the third quarantines",
                )
            return PreviewQuarantineRow(**common, reachable=False, would_action="none",
                                        detail=f"unreachable ({fetch_error or 'no hash'}): failure {strike} of 3, no quarantine yet")
        stored_hash = compliance.policy_hash or ""
        if stored_hash == live_hash:
            return PreviewQuarantineRow(**common, reachable=True, hash_match=True, would_action="none",
                                        detail="the live hash matches the baseline")
        if compliance.federation_status != "federated":
            return PreviewQuarantineRow(
                **common, reachable=True, hash_match=False, would_action="none",
                detail=f"hash differs, but the peer is {compliance.federation_status}: no new action",
            )
        if compliance.in_grace_period():
            return PreviewQuarantineRow(
                **common, reachable=True, hash_match=False, would_action="none",
                detail=f"hash differs, inside the grace period until {compliance.quarantine_grace_expires.isoformat()}",
            )
        action, grace = _would_action_for_severity(DriftSeverity.HIGH)
        return PreviewQuarantineRow(
            **common, reachable=True, hash_match=False, would_action=action, severity=DriftSeverity.HIGH.value,
            grace_hours=grace,
            detail=f"live hash {live_hash[:16]}… differs from the baseline {stored_hash[:16]}…",
        )

    rows: List[PreviewQuarantineRow] = list(await _asyncio.gather(*(_row(t, p_, c) for t, p_, c in candidates)))
    would_count = sum(1 for r in rows if r.would_action.startswith("quarantine"))
    skipped_count = sum(1 for r in rows if r.would_action == "skipped")
    noop_count = len(rows) - would_count - skipped_count

    return PreviewQuarantineResponse(
        generated_at=datetime.now(timezone.utc).isoformat(),
        mode_at_check=mode,
        total_peers=len(rows),
        would_quarantine_count=would_count,
        would_noop_count=noop_count,
        skipped_count=skipped_count,
        peers=rows,
    )


@router.get(
    "/trust-bundle-matrix",
    response_model=TrustBundleMatrix,
    summary="Cross-frame trust bundles: does this registry, and each of its operators' gateways, trust every frame's CA?",
)
async def trust_bundle_matrix(db: AsyncSession = Depends(get_db)) -> TrustBundleMatrix:
    """READ-ONLY. §MCPTEST30 (V0561): the frames are THIS federation's (the frame manifest's rule: this registry when it is
    a frame, and every ACTIVE peer the manifest calls a frame), and their reference CA sets are read from this
    registry's own trust bundle by the SPIFFE trust domain each CA names. It used to compare against the retired
    Frame A/B/C trust domains read from a SPIRE container by name, so on every frame since it reported "could not read
    reference CA set for: agentvault.com, frame-b…, frame-c…" and measured nothing.

    A frame of the federation whose CA this registry's own bundle lacks is reported in `frame_ca_error`: cross-frame mTLS
    from that frame is refused here. Each operator gateway's bundle is read through the Docker socket when this registry
    has one (`gateways_readable` false otherwise, with the reason); an op whose bundle cannot be read gets
    `{error: ...}` and never 500s the whole call.
    """
    scanned_at = datetime.now(timezone.utc).isoformat()
    source = _bundle_path()
    all_peers = list((await db.execute(select(PeerRegistry))).scalars().all())
    frames_by_td = _frames_by_trust_domain(all_peers)

    try:
        with open(source, "r", encoding="utf-8") as fh:
            own = _ca_sets_by_trust_domain(fh.read())
        read_error = None
    except OSError as exc:
        own, read_error = {}, f"this registry's trust bundle could not be read ({exc.strerror or exc})"
    frames = [TrustBundleFrame(trust_domain=td, name=meta.get("name"), ca_count=len(own.get(td, ())))
              for td, meta in sorted(frames_by_td.items(), key=lambda kv: (kv[1].get("name") or kv[0]).lower())]
    missing_here = [f.trust_domain for f in frames if not f.ca_count]
    frame_ca_error = read_error or (
        f"this registry's own trust bundle holds no CA of: {', '.join(missing_here)}" if missing_here else None)

    rows: List[TrustBundleOpRow] = []
    unreadable = _gateways_unreadable_reason()
    if unreadable is None:
        # Operators carry a `nginx_federation` container; mainframes are skipped (their federation is host nginx).
        targets = await _peer_targets(db)
        peers_by_key = _index_peers(all_peers)
        probe = get_probe()
        for t in targets:
            gateway = (t.get("containers") or {}).get("nginx_federation")
            if t.get("role") != "operator" or not gateway:
                continue
            op_label = _op_slug_from_gateway(gateway) or t.get("operator_id") or gateway
            td, _src = _identity_of(_match_peer_registry(t, peers_by_key), [], {})
            frame = (frames_by_td.get(td) or {}).get("name") or td
            rc, output = await probe.exec_in(gateway, ["cat", "/certs/bundle.0.pem"], timeout=10)
            if rc != 0:
                rows.append(TrustBundleOpRow(op=op_label, frame=frame,
                                             error=f"could not read /certs/bundle.0.pem (rc={rc}): {(output or '').strip()[:160]}"))
                continue
            op_fps = _fingerprints_of_pem(output)
            if not op_fps:
                rows.append(TrustBundleOpRow(op=op_label, frame=frame, error="bundle.0.pem contained no parseable CA certs"))
                continue
            # a frame whose reference set this registry lacks is NOT MEASURED for the op (None), never "missing"
            trusts = {f.trust_domain: (bool(own[f.trust_domain] & op_fps) if f.ca_count else None) for f in frames}
            missing = [d for d, v in trusts.items() if v is False]
            rows.append(TrustBundleOpRow(op=op_label, frame=frame, trusts=trusts, missing=missing,
                                         complete=(not missing) if all(v is not None for v in trusts.values()) else None))
        rows.sort(key=lambda r: r.op)

    return TrustBundleMatrix(
        scanned_at=scanned_at,
        source=source,
        frames=frames,
        total=len(rows),
        complete=sum(1 for r in rows if r.complete),
        drift=sum(1 for r in rows if r.missing),
        errors=sum(1 for r in rows if r.error),
        frame_ca_error=frame_ca_error,
        gateways_readable=unreadable is None,
        gateways_unreadable_reason=unreadable,
        ops=rows,
    )