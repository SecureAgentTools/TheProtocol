"""
routers/registry_health.py — Public Registry Health Profile Endpoints

Endpoints:
  GET /api/v1/federation/registries                          (public — list all federated)
  GET /api/v1/federation/registry/{peer_id_or_name}/health-profile  (public — per-registry profile)
  GET /api/v1/admin/federation/policy-compliance             (admin — this registry's compliance hash)
  GET /api/v1/admin/federation/self-health                   (admin — full economic + reputation data)

Phase 1: structural/status fields only.
Phase 3a: adds economic_health + reputation_graph with 5-minute module-level cache.

Author: OWL-24 (Phase 1) / OWL-26 (Phase 3a)
Date: 2026-03-12
"""
import httpx
from ..es_ssl_helper import get_httpx_verify
import logging
import time
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Security
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import get_db
from ..models import (
    FederatedRegistryCompliance, PeerRegistry,
    Agent, Stake, GlobalTrustVector, Dispute,
    EnforcementAction, AuditorFlagLog,
    StakingDistribution, RegistryOperatingState,
    REGISTRY_STATE_SINGLETON_ID,
)
from .. import security

# ── Module-level cache (5-minute TTL) ─────────────────────────────────────────
# Key: "economic" / "reputation" — always this registry's own data.
# Economic health hits TEG over HTTP so we cache aggressively.
_cache: Dict[str, Any] = {}
_CACHE_TTL: int = 300  # seconds


def _cache_get(key: str) -> Optional[Any]:
    """Return cached value if present and not expired, else None."""
    entry = _cache.get(key)
    if entry and (time.monotonic() - entry["ts"]) < _CACHE_TTL:
        return entry["val"]
    return None


def _cache_set(key: str, val: Any) -> None:
    _cache[key] = {"val": val, "ts": time.monotonic()}

logger = logging.getLogger(__name__)

# TEG connection constants (same pattern as teg_integration.py)
_TEG_BASE_URL: str = getattr(settings, "TEG_API_BASE_URL", "http://teg-layer:8080")
_TEG_ADMIN_KEY: str = getattr(settings, "TEG_ADMIN_API_KEY", "")

router = APIRouter(tags=["Registry Health"])


# ── Economic + Reputation Data Helpers ─────────────────────────────────

async def _fetch_teg_treasury_balance() -> Optional[Decimal]:
    """
    Call TEG admin API to get treasury balance.
    Returns None on any error (graceful degradation).
    """
    try:
        async with httpx.AsyncClient(timeout=5.0, verify=get_httpx_verify()) as client:
            resp = await client.get(
                f"{_TEG_BASE_URL}/api/v1/admin/treasury/balance",
                headers={"Authorization": f"Bearer {_TEG_ADMIN_KEY}"},
            )
            if resp.status_code == 200:
                data = resp.json()
                # TEG may return {"balance": "12345.67"} or {"treasury_balance": ...}
                raw = data.get("balance") or data.get("treasury_balance") or data.get("amount")
                if raw is not None:
                    return Decimal(str(raw))
    except Exception as exc:
        logger.debug(f"[HealthProfile] TEG treasury fetch failed (non-fatal): {exc}")
    return None


async def _build_economic_health(db: AsyncSession) -> Dict[str, Any]:
    """
    Build the economic_health dict from local DB + TEG HTTP call.
    All failures are swallowed — missing fields become None.
    """
    now = datetime.now(timezone.utc)
    cutoff_90d = now - timedelta(days=90)
    cutoff_30d = now - timedelta(days=30)
    cutoff_7d  = now - timedelta(days=7)

    result: Dict[str, Any] = {}

    # — total_staked_avt: SUM(stakes.amount WHERE is_active=True)
    try:
        row = await db.execute(
            select(func.sum(Stake.amount)).where(Stake.is_active == True)
        )
        val = row.scalar_one_or_none()
        result["total_staked_avt"] = float(val) if val is not None else 0.0
    except Exception as e:
        logger.debug(f"[HealthProfile] total_staked query failed: {e}")
        result["total_staked_avt"] = None

    # — active_agents: COUNT(agents WHERE status='active')
    try:
        row = await db.execute(
            select(func.count(Agent.id)).where(Agent.status == "active")
        )
        result["active_agents"] = row.scalar_one_or_none() or 0
    except Exception as e:
        logger.debug(f"[HealthProfile] active_agents query failed: {e}")
        result["active_agents"] = None

    # — avg_eigentrust_score: AVG(global_trust_vectors.global_trust)
    try:
        row = await db.execute(select(func.avg(GlobalTrustVector.global_trust)))
        val = row.scalar_one_or_none()
        result["avg_eigentrust_score"] = round(float(val), 4) if val is not None else 0.0
    except Exception as e:
        logger.debug(f"[HealthProfile] avg_eigentrust query failed: {e}")
        result["avg_eigentrust_score"] = None

    # — dispute_resolution_rate: CLOSED / total in last 90d
    try:
        row_total = await db.execute(
            select(func.count(Dispute.id)).where(Dispute.created_at >= cutoff_90d)
        )
        total_90d = row_total.scalar_one_or_none() or 0

        row_closed = await db.execute(
            select(func.count(Dispute.id)).where(
                Dispute.created_at >= cutoff_90d,
                Dispute.status == "CLOSED",
            )
        )
        closed_90d = row_closed.scalar_one_or_none() or 0

        result["dispute_resolution_rate"] = (
            round(closed_90d / total_90d, 4) if total_90d > 0 else 1.0
        )
    except Exception as e:
        logger.debug(f"[HealthProfile] dispute_resolution_rate query failed: {e}")
        result["dispute_resolution_rate"] = None

    # — enforcement_actions_30d
    try:
        row = await db.execute(
            select(func.count(EnforcementAction.id)).where(
                EnforcementAction.created_at >= cutoff_30d
            )
        )
        result["enforcement_actions_30d"] = row.scalar_one_or_none() or 0
    except Exception as e:
        logger.debug(f"[HealthProfile] enforcement_actions_30d query failed: {e}")
        result["enforcement_actions_30d"] = None

    # — zero_distribution_events_30d: from RegistryOperatingState singleton. §FEELOCK: the value is
    #   the D-FED-10 streak (consecutive owed-and-unfunded distribution days), re-derived from the
    #   ledger; the field keeps its published name.
    try:
        row = await db.execute(
            select(RegistryOperatingState).where(
                RegistryOperatingState.id == REGISTRY_STATE_SINGLETON_ID
            )
        )
        state = row.scalar_one_or_none()
        _streak = state.treasury_zero_days if state else 0
        # §TRUSTCHAIN P4.5: the field is named for what it carries; the old key stays ONE release as
        # an alias so a peer reading last week's shape keeps parsing, then goes.
        result["treasury_unfunded_streak_days"] = _streak
        result["zero_distribution_events_30d"] = _streak  # alias, retire after 2026-10-12
    except Exception as e:
        logger.debug(f"[HealthProfile] registry_operating_state query failed: {e}")
        result["treasury_unfunded_streak_days"] = None
        result["zero_distribution_events_30d"] = None

    # — avg_daily_obligation: AVG(total_distributed) from last 7 completed distributions
    try:
        row = await db.execute(
            select(func.avg(StakingDistribution.total_distributed)).where(
                StakingDistribution.status == "completed",
                StakingDistribution.distribution_date >= cutoff_7d.date(),
            )
        )
        avg_daily = row.scalar_one_or_none()
        avg_daily_float = float(avg_daily) if avg_daily else 0.0
    except Exception as e:
        logger.debug(f"[HealthProfile] avg_daily_obligation query failed: {e}")
        avg_daily_float = 0.0

    result["avg_daily_reward_obligation"] = round(avg_daily_float, 2)

    # — treasury_balance_avt + treasury_days_buffer (requires TEG HTTP call)
    treasury_bal = await _fetch_teg_treasury_balance()
    if treasury_bal is not None:
        result["treasury_balance_avt"] = float(treasury_bal)
        result["treasury_days_buffer"] = (
            round(float(treasury_bal) / avg_daily_float, 1)
            if avg_daily_float > 0
            else None
        )
    else:
        result["treasury_balance_avt"] = None
        result["treasury_days_buffer"] = None

    return result


async def _build_reputation_graph(
    db: AsyncSession,
    avg_eigentrust: Optional[float],
) -> Dict[str, Any]:
    """
    Build the reputation_graph dict from local DB.
    Bucketed trust rank derived from avg_eigentrust passed in.
    """
    now = datetime.now(timezone.utc)
    cutoff_30d = now - timedelta(days=30)
    result: Dict[str, Any] = {}

    # — global_trust_rank: bucket from avg_eigentrust
    if avg_eigentrust is not None:
        if avg_eigentrust >= 0.7:
            result["global_trust_rank"] = "A"
        elif avg_eigentrust >= 0.5:
            result["global_trust_rank"] = "B"
        elif avg_eigentrust >= 0.3:
            result["global_trust_rank"] = "C"
        else:
            result["global_trust_rank"] = "D"
    else:
        result["global_trust_rank"] = None

    # — collusion_alerts_30d
    try:
        row = await db.execute(
            select(func.count(AuditorFlagLog.id)).where(
                AuditorFlagLog.flag_type.ilike("%collusion%"),
                AuditorFlagLog.created_at >= cutoff_30d,
            )
        )
        result["collusion_alerts_30d"] = row.scalar_one_or_none() or 0
    except Exception as e:
        logger.debug(f"[HealthProfile] collusion_alerts query failed: {e}")
        result["collusion_alerts_30d"] = None

    # — sybil_incidents: distinct flagged agents with any sybil flag (all-time)
    try:
        row = await db.execute(
            select(func.count(func.distinct(AuditorFlagLog.flagged_agent_did))).where(
                AuditorFlagLog.flag_type.ilike("%sybil%")
            )
        )
        result["sybil_incidents"] = row.scalar_one_or_none() or 0
    except Exception as e:
        logger.debug(f"[HealthProfile] sybil_incidents query failed: {e}")
        result["sybil_incidents"] = None

    return result


# ── Response Schemas ──────────────────────────────────────────────────────────

class RegistryHealthProfile(BaseModel):
    registry_id: int
    registry_name: str
    registry_url: str
    registry_did: Optional[str]
    federation_status: str
    compliance_score: float
    policy_drift_events: int
    quarantine_events: List[Any]
    quarantine_reason: Optional[str]
    quarantine_since: Optional[str]
    admitted_at: Optional[str]
    last_polled_at: Optional[str]
    # §DIRFEED (2026-09-06) — ADMISSION, as opposed to compliance. `federation_status` above is the compliance
    # poller's verdict and reads "unknown" wherever that poller has never run (every node that is not a central
    # registry). The two facts an external index actually needs are the peer ROW's own: is this peer still
    # federated with us (status), and did we federate/license it at all or merely hear of it through someone
    # else's fan-out (peer_type: frame | cloud_operator | discovered). Without them a directory cannot tell an
    # ACTIVE peer from a deactivated one — and deactivation, never deletion, is how a peer is stopped here.
    peer_status: Optional[str] = None
    peer_type: Optional[str] = None
    # …and the address a CLIENT can use. `registry_url` above is `base_url`, which for a peer we federated with
    # or licensed is the mTLS federation address (`…:8443`, the host SNI router) — never a public API. The
    # peer's own SIGNED card declares where the public API lives; that is what an index must dial, and it is
    # already cached here. Null when we hold no card for that peer yet.
    public_url: Optional[str] = None
    # §DISCOTRUST — THIS FRAME'S OWN verdict on that peer, for a caller deciding whether to deal
    # with an agent it hosts. Present ONLY for an authenticated caller: the verdict is formed from
    # settlements this frame witnessed itself, and publishing it to anonymous third parties would
    # make this registry a credit bureau on its peers. A member asking "should I engage this
    # provider" is asking THIS frame for ITS opinion, which is the whole point of holding one.
    # Null for anonymous callers, and null is not "trusted". "Identified" means a DEVELOPER or an
    # AGENT token (§TRUSTCHAIN 2026-09-12: the viewer is `get_current_actor_for_read_optional`;
    # before that it was the developer-only dependency, so the agent journal 45 is about got none).
    trust: Optional[Dict[str, Any]] = None
    # Phase 3a fields (None in Phase 1)
    economic_health: Optional[Dict[str, Any]] = None
    reputation_graph: Optional[Dict[str, Any]] = None


class PolicyComplianceResponse(BaseModel):
    registry_did: Optional[str]
    policy_version: int
    policy_hash: str
    timestamp: str
    # §TRUSTCHAIN: "factory_default" | "amended" — the third state journal 45 publishes on the card
    policy_source: Optional[str] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _card_public_url(peer: PeerRegistry) -> Optional[str]:
    """The public API address the peer's OWN signed card declares (identity.public_url). Never derived from the
    federation address by dropping a port: a template is how a name becomes a lie (§DIDWIDEN's presenter class)."""
    card = getattr(peer, "cached_registry_card", None)
    if not isinstance(card, dict):
        return None
    url = ((card.get("identity") or {}) if isinstance(card.get("identity"), dict) else {}).get("public_url")
    return str(url).strip() or None if isinstance(url, str) and url.strip() else None


def _peer_to_profile(
    peer: PeerRegistry,
    compliance: Optional[FederatedRegistryCompliance],
) -> RegistryHealthProfile:
    """Assemble a RegistryHealthProfile from ORM objects."""
    if compliance:
        fed_status = compliance.federation_status
        score = compliance.compliance_score
        drift_count = compliance.drift_events_count
        q_events = compliance.quarantine_events or []
        q_reason = compliance.quarantine_reason
        q_since = compliance.quarantine_since.isoformat() if compliance.quarantine_since else None
        admitted = compliance.admitted_at.isoformat() if compliance.admitted_at else None
        last_poll = compliance.last_poll_at.isoformat() if compliance.last_poll_at else None
    else:
        fed_status = "unknown"
        score = 0.0
        drift_count = 0
        q_events = []
        q_reason = None
        q_since = None
        admitted = None
        last_poll = None

    op_did = peer.discovery_auth_info.get("operator_did") if peer.discovery_auth_info else None

    return RegistryHealthProfile(
        registry_id=peer.id,
        registry_name=peer.name,
        registry_url=peer.base_url,
        registry_did=op_did,
        federation_status=fed_status,
        peer_status=getattr(peer, "status", None),          # §DIRFEED — ACTIVE / INACTIVE / PENDING_APPROVAL / REJECTED
        peer_type=getattr(peer, "peer_type", None),         # §DIRFEED — frame / cloud_operator / discovered
        public_url=_card_public_url(peer),                  # §DIRFEED — from the peer's own signed card
        compliance_score=score,
        policy_drift_events=drift_count,
        quarantine_events=q_events,
        quarantine_reason=q_reason,
        quarantine_since=q_since,
        admitted_at=admitted,
        last_polled_at=last_poll,
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get(
    "/api/v1/federation/registries",
    response_model=List[RegistryHealthProfile],
    summary="List all federated peer registries with health status (public)",
)
async def list_federated_registries(
    status_filter: Optional[str] = Query(
        None,
        description="Filter by federation_status: federated | quarantined | blacklisted | all"
    ),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    viewer=Depends(security.get_current_actor_for_read_optional),
):
    """
    Public endpoint: no auth required.
    Lists peer registries that are ACTIVE in PeerRegistry with their compliance state.
    """
    stmt = select(PeerRegistry).where(PeerRegistry.status == "ACTIVE")
    result = await db.execute(stmt)
    peers = result.scalars().all()

    # Resolve the frame's policy ONCE. The thresholds are the same for every peer in this list, and
    # reading the row per peer would make a 5-peer page do 5 identical loads.
    _policy = None
    if viewer is not None:
        try:
            from ..services import frame_policy as fp
            _policy = await fp.load(db)
        except Exception:  # noqa: BLE001
            _policy = None

    profiles = []
    for peer in peers:
        comp_result = await db.execute(
            select(FederatedRegistryCompliance).where(
                FederatedRegistryCompliance.peer_registry_id == peer.id
            )
        )
        compliance = comp_result.scalar_one_or_none()

        profile = _peer_to_profile(peer, compliance)

        # §DISCOTRUST — attach this frame's peer-trust verdict for a caller who has identified
        # themselves. One implementation, in services/peer_trust_policy: a second copy here is the
        # defect §TRUSTPOLICY existed to close.
        if viewer is not None:
            try:
                from ..services import peer_trust_policy as ptp
                profile.trust = ptp.trust_block(peer, _policy)
            except Exception:  # noqa: BLE001
                profile.trust = {"state": "unavailable", "label": "Trust state unavailable"}

        # Apply status filter
        if status_filter and status_filter != "all":
            if profile.federation_status != status_filter:
                continue

        profiles.append(profile)

    # Paginate
    offset = (page - 1) * per_page
    return profiles[offset : offset + per_page]


@router.get(
    "/api/v1/federation/registry/{peer_id_or_name}/health-profile",
    response_model=RegistryHealthProfile,
    summary="Get health profile for a specific federated registry (public)",
)
async def get_registry_health_profile(
    peer_id_or_name: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Public transparency endpoint.
    Accepts peer registry integer ID or name as path param.

    It also returns economic_health and reputation_graph
    populated from this registry's own DB + TEG.
    Results cached for 5 minutes per request (TEG HTTP avoidance).
    """
    # Try integer ID first, then name
    peer = None
    if peer_id_or_name.isdigit():
        peer_result = await db.execute(
            select(PeerRegistry).where(PeerRegistry.id == int(peer_id_or_name))
        )
        peer = peer_result.scalar_one_or_none()

    if not peer:
        peer_result = await db.execute(
            select(PeerRegistry).where(PeerRegistry.name == peer_id_or_name)
        )
        peer = peer_result.scalar_one_or_none()

    if not peer:
        raise HTTPException(status_code=404, detail="Registry not found")

    comp_result = await db.execute(
        select(FederatedRegistryCompliance).where(
            FederatedRegistryCompliance.peer_registry_id == peer.id
        )
    )
    compliance = comp_result.scalar_one_or_none()

    profile = _peer_to_profile(peer, compliance)

    # — Phase 3a: populate economic + reputation data (cached)
    eco = _cache_get("economic")
    if eco is None:
        try:
            eco = await _build_economic_health(db)
            _cache_set("economic", eco)
        except Exception as exc:
            logger.warning(f"[HealthProfile] economic_health build failed: {exc}")
            eco = None

    profile.economic_health = eco

    rep = _cache_get("reputation")
    if rep is None:
        try:
            avg_eigen = eco.get("avg_eigentrust_score") if eco else None
            rep = await _build_reputation_graph(db, avg_eigentrust=avg_eigen)
            _cache_set("reputation", rep)
        except Exception as exc:
            logger.warning(f"[HealthProfile] reputation_graph build failed: {exc}")
            rep = None

    profile.reputation_graph = rep

    return profile


@router.get(
    "/api/v1/admin/federation/self-health",
    response_model=RegistryHealthProfile,
    summary="Full economic + reputation health profile for THIS registry (admin, no cache)",
)
async def get_self_health(
    db: AsyncSession = Depends(get_db),
    _admin=Security(security.require_admin_flag("admin_platform")),
):
    """
    Admin-only endpoint. Returns THIS registry's health profile with fully
    populated economic_health and reputation_graph.
    Always fresh — bypasses the 5-minute cache.
    """
    # Build a synthetic RegistryHealthProfile for self
    registry_name = getattr(settings, "REGISTRY_NAME", "This Registry")
    registry_url = str(getattr(settings, "BASE_URL", "http://localhost:8000"))

    from ..crud.crud_enforcement import get_active_policy
    from ..models import REGISTRY_STATE_SINGLETON_ID

    # Get own compliance state if this registry is a peer on another registry
    # (self may not have a PeerRegistry row — use defaults)
    profile = RegistryHealthProfile(
        registry_id=0,
        registry_name=registry_name,
        registry_url=registry_url,
        registry_did=getattr(settings, "REGISTRY_DID", None),
        federation_status="self",
        peer_status="ACTIVE",      # §DIRFEED — this row is the registry itself, never a peer row
        peer_type="self",
        public_url=registry_url,
        compliance_score=100.0,
        policy_drift_events=0,
        quarantine_events=[],
        quarantine_reason=None,
        quarantine_since=None,
        admitted_at=None,
        last_polled_at=None,
    )

    # — Economic health (always fresh for admin)
    try:
        profile.economic_health = await _build_economic_health(db)
    except Exception as exc:
        logger.error(f"[self-health] economic_health build failed: {exc}")
        profile.economic_health = None

    # — Reputation graph (always fresh for admin)
    try:
        avg_eigen = (
            profile.economic_health.get("avg_eigentrust_score")
            if profile.economic_health
            else None
        )
        profile.reputation_graph = await _build_reputation_graph(
            db, avg_eigentrust=avg_eigen
        )
    except Exception as exc:
        logger.error(f"[self-health] reputation_graph build failed: {exc}")
        profile.reputation_graph = None

    return profile


@router.get(
    "/api/v1/admin/federation/policy-compliance",
    response_model=PolicyComplianceResponse,
    summary="Return THIS registry's policy hash (used by genesis poller)",
)
async def get_own_policy_compliance(
    db: AsyncSession = Depends(get_db),
    _admin=Security(security.require_admin_flag("admin_platform")),
):
    """
    Admin endpoint — returns the current active policy's canonical SHA-256 hash.
    The genesis registry's compliance_poller fetches this endpoint from each peer
    and compares it against the hash stored at admission.

    Phase 1: Hash only (no ED25519 signature).
    Phase 3b upgrade: adds ED25519 signature on the hash.
    """
    # §TRUSTCHAIN (2026-09-12): the same ONE hash the signed card publishes and the
    # federation-namespaced twin serves (see routers/federation_sync.py, same date). This used
    # to hash the RAW row, which on an amended frame is not the document the frame runs.
    from ..services import frame_policy as fp

    policy = await fp.load(db)

    # Try to get our own DID from settings (may not be set in dev)
    registry_did = getattr(settings, "REGISTRY_DID", None)

    return PolicyComplianceResponse(
        registry_did=registry_did,
        policy_version=policy.version,
        policy_source=policy.source,
        policy_hash=policy.hash(),
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
