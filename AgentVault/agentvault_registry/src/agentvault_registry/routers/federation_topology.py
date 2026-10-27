"""Federation Topology Admin Endpoint (2026-04-21, WS1.5 of federation polish).

One read-only admin endpoint that returns the enriched tier-bucketed topology
plus admin-only metadata (license status, drift flags, Bayesian trust, health
detail). Pairs with the public ``/api/v1/public/topology`` endpoint — this one
is strictly for operators browsing the federation admin view.

    GET /api/v1/admin/federation/topology-overview
        — admin_federation flag required. Returns tier buckets + per-peer admin
          fields + a summary block (drift_count, peers_by_type, ...).

Drift detection reuses the pure function from license_drift_monitor so all
rules live in one place.
"""
import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

try:
    from prometheus_client import Gauge
    SPIRE_BUNDLE_AGE = Gauge(
        "spire_federated_bundle_age_seconds",
        "Wall-clock age (seconds since cert NotBefore) of each federated SPIRE bundle. "
        "Closes §pass53 silent-drift gap — alerts can fire on > 432000 (5d).",
        ["trust_domain"],
        multiprocess_mode='livemostrecent',
    )
    SPIRE_BUNDLE_EXPIRES_IN = Gauge(
        "spire_federated_bundle_expires_in_seconds",
        "Seconds until cert NotAfter for each federated SPIRE bundle. Negative = expired.",
        ["trust_domain"],
        multiprocess_mode='livemostrecent',
    )
    SPIRE_BUNDLE_HEALTH = Gauge(
        "spire_federated_bundle_health",
        "Bundle health bucket: 0=fresh, 1=overdue, 2=critical, 3=unknown.",
        ["trust_domain"],
        multiprocess_mode='livemostrecent',
    )
except Exception:  # pragma: no cover — Prom client optional at import time
    SPIRE_BUNDLE_AGE = None
    SPIRE_BUNDLE_EXPIRES_IN = None
    SPIRE_BUNDLE_HEALTH = None

import httpx
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Security

from ..es_ssl_helper import get_httpx_verify
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry import models, security
from agentvault_registry.database import get_db
from agentvault_registry.core.path_segment import seg  # §MCPTEST30 V0526: a value in a store/TEG URL path is one encoded segment (round 9: a malformed id read as an outage)
from agentvault_registry.background_tasks.license_drift_monitor import (
    detect_drift_for_operator,
    detect_drift_for_frame,
    _derive_operator_did_from_app,
    TOPOLOGY_STALENESS_SECONDS,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Federation Topology Admin"])


def _peer_base(
    r: models.PeerRegistry,
    *,
    spire_bundle_active: Optional[bool] = None,
) -> Dict[str, Any]:
    """Common peer row shape. `spire_bundle_active` is populated for frame peers
    only (None for operators/others). Derived from SPIRE state by the caller —
    see `topology_overview()` for the pre-fetch block."""
    last_seen = getattr(r, "last_seen_in_topology_at", None)
    out: Dict[str, Any] = {
        "id": r.id,
        "name": r.name,
        "base_url": r.base_url,
        "status": r.status,
        "peer_type": r.peer_type,
        "hop_distance": r.hop_distance,
        "discovered_at": r.discovered_at.isoformat() if r.discovered_at else None,
        "registered_at": r.registered_at.isoformat() if r.registered_at else None,
        "approved_at": r.approved_at.isoformat() if r.approved_at else None,
        "last_synced_at": r.last_synced_at.isoformat() if r.last_synced_at else None,
        "operator_did": r.operator_did,
        "trust_domain": r.trust_domain,
        "parent_registry_id": r.parent_registry_id,
        "last_seen_in_topology_at": last_seen.isoformat() if last_seen else None,
        "bfs_reachable": bool(
            last_seen
            and (datetime.now(timezone.utc) - last_seen).total_seconds()
            <= TOPOLOGY_STALENESS_SECONDS
        ),
    }
    # §2026-06-29 — carry the v0.3 card visual directly on the admin-overview peer
    # so the FE renders each peer's flare encirclement from its OWN cached card,
    # independent of whether the peer also appears in /public/topology registries[]
    # (which only carries BFS-seeded peers). Fixes op-newyork/op-losangeles: cached
    # card present (flare sakura/lighthouse) but absent from the public BFS list →
    # FE merge `if (!v) return peer` left visual=null → no encirclement ring.
    # 🔴 findings row 182 (2026-09-07) — THE JUNE FIX CARRIED ONE FIELD AND LEFT ITS SIBLINGS.
    # The reasoning above is exactly right and applies verbatim to the REST of the v0.3 slice:
    # the FE's `mergeV03IntoBuckets` backfills `visual`, `fees_summary`, `card_etag`,
    # `card_signature_verified` and `trust_domain` from /public/topology registries[], and that
    # list only carries BFS-seeded peers — so for any peer absent from it, only the field carried
    # HERE survives. Measured on EU: asia's card is cached AND `card_signature_verified = t` in
    # the database, asia is absent from registries[], and the console therefore showed `no card`,
    # `Card ETag —`, `Signature verified UNKNOWN` and "No fee data published in this peer's
    # Registry Card" — while this registry held a verified card for it. Its avatar rendered,
    # because `visual` was the one field June carried.
    #
    # Same shape as findings row 169 an hour earlier: a widening that reached the callee and not
    # the siblings asking the same question. Carry the whole slice, from the SAME cached card.
    _rc = r.cached_registry_card if isinstance(r.cached_registry_card, dict) else None
    # 🔴 findings row 190 — AN ICON URL IS SAME-ORIGIN TO THE REGISTRY THAT PUBLISHED IT, AND
    # THE CONSOLE IS A DIFFERENT ORIGIN. The upload endpoint deliberately returns a same-origin
    # path ("Same-origin enforced: returned URL is always on this registry's host"), so a peer's
    # `visual.icon_url` is `/static/registry-cards/<slug>/icon.png` ON THAT PEER. The FE renders
    # it straight into <img :src>, which resolves against the CONSOLE's origin — 404, every peer,
    # always. Measured: EU's console 404s on amsterdam's icon AND on asia's, while both files
    # serve 200 from their own hosts. I reported this fixed after checking the API returned an
    # icon_url, which was true and was not the question — the question is whether a BROWSER can
    # fetch it. Resolve it HERE so `peer.visual.icon_url` is absolute and the FE needs no second
    # key that could drift out of step (the `fees` vs `fees_summary` lesson, one row up).
    _visual = (_rc.get("visual") if isinstance(_rc, dict) else None) or None
    if isinstance(_visual, dict):
        _icon = str(_visual.get("icon_url") or "")
        if _icon.startswith("/"):
            from urllib.parse import urlparse as _up
            try:
                _pp = _up(r.base_url or "")
                # the peer's WEB origin: its hostname on 443, never base_url's mTLS port
                _origin = f"{_pp.scheme}://{_pp.hostname}" if _pp.hostname and "." in _pp.hostname else ""
            except Exception:  # noqa: BLE001
                _origin = ""
            _visual = {**_visual, "icon_url": (_origin + _icon) if _origin else None}
    out["visual"] = _visual
    out["card_etag"] = getattr(r, "card_etag", None) or None
    # findings row 187b — NO CARD IS NOT AN UNSIGNED CARD. The column defaults to false, so a
    # peer we have never pulled reported verified=False and the console asserted "UNSIGNED"
    # about a card it does not have — a verdict that cannot tell two states apart (row 171).
    # Null means UNKNOWN: only a card we hold can be called signed or unsigned.
    out["card_signature_verified"] = (
        bool(getattr(r, "card_signature_verified", False)) if _rc is not None else None
    )
    out["card_last_pulled_at"] = (
        r.card_last_pulled_at.isoformat() if getattr(r, "card_last_pulled_at", None) else None
    )
    # `fees_summary` is the name the FE merge and the drawer read; the public builder calls the
    # same slice `fees`. Emit the FE's name so the two callers stop disagreeing.
    _fees = (_rc.get("fees") if isinstance(_rc, dict) else None) or {}
    out["fees_summary"] = {
        "intra_registry": (_fees.get("intra_registry") or {}).get("base_rate_percent"),
        "cross_registry": (_fees.get("cross_registry") or {}).get("base_rate_percent"),
    } if _fees else None
    if r.peer_type == "frame":
        # None means "we couldn't query SPIRE this call" (don't assume either way).
        # True/False = authoritative SPIRE presence (federation + bundle).
        out["spire_bundle_active"] = spire_bundle_active
    return out


def _peer_admin_extras(
    r: models.PeerRegistry,
    lic: Optional[models.FederationLicense],
    app: Optional[models.OperatorApplication],
    drift_flags: List[str],
) -> Dict[str, Any]:
    return {
        # License block
        "license_id": lic.id if lic else None,
        "license_status": lic.status if lic else None,
        "license_key_prefix": lic.license_key_prefix if lic else None,
        "license_suspended_at": (
            lic.suspended_at.isoformat() if lic and getattr(lic, "suspended_at", None) else None
        ),
        "license_suspended_reason": (
            getattr(lic, "suspended_reason", None) if lic else None
        ),
        "license_revoked_at": (
            lic.revoked_at.isoformat() if lic and lic.revoked_at else None
        ),
        "license_revoked_reason": lic.revoked_reason if lic else None,
        "federation_tier": lic.federation_tier if lic else None,
        # Operator application block
        "application_id": app.id if app else None,
        "application_status": app.status if app else None,
        "cloud_hosted": bool(getattr(app, "cloud_hosted", False)) if app else False,
        "cloud_url": getattr(app, "cloud_url", None) if app else None,
        "cloud_provisioned_at": (
            app.cloud_provisioned_at.isoformat()
            if app and getattr(app, "cloud_provisioned_at", None) else None
        ),
        "cloud_torn_down_at": (
            app.cloud_torn_down_at.isoformat()
            if app and getattr(app, "cloud_torn_down_at", None) else None
        ),
        # Health
        "health_check_failure_count": r.health_check_failure_count or 0,
        "last_health_check_attempt_at": (
            r.last_health_check_attempt_at.isoformat()
            if r.last_health_check_attempt_at else None
        ),
        "healthy": (r.health_check_failure_count or 0) < 3,
        # Bayesian trust (f030)
        "total_interactions": r.total_interactions or 0,
        "disputes_lost_with": r.disputes_lost_with or 0,
        "bayesian_discount": float(r.bayesian_discount) if r.bayesian_discount is not None else 1.0,
        "last_interaction_at": (
            r.last_interaction_at.isoformat() if r.last_interaction_at else None
        ),
        # §TRUSTPOLICY (2026-09-11) — the number alone is not readable. 0.500 is
        # the Beta(1,1) prior: it means NO EVIDENCE, and on a screen it reads as
        # "half trusted", which is the opposite of what it says. Measured on EU:
        # hochiminh and shenzhen sat at exactly 0.5000 with zero interactions
        # while the INACTIVE `ASIA` ghost sat at the column default 1.0, also
        # with zero interactions — one pair looking terrible and the other
        # looking perfect for the very same reason. `trust` travels with the
        # number so no caller has to interpret it again.
        "trust": _peer_trust_block(r),
        # Drift
        "drift_flags": drift_flags,
        "has_drift": len(drift_flags) > 0,
    }


def _peer_trust_block(r, policy=None) -> Dict[str, Any]:
    """Delegates to the ONE implementation in services/peer_trust_policy.

    This used to hold the body. It was lifted into the service when /discover needed the same
    verdict, because two surfaces computing trust separately is exactly the defect §TRUSTPOLICY
    was opened to close.
    """
    from ..services import peer_trust_policy as ptp
    return ptp.trust_block(r, policy)


@router.get(
    "/admin/federation/peer-trust",
    # ⚠ `admin_platform`, NOT `admin_federation`, because this endpoint's consumer is the CONSUL
    # page (/admin/compliance) and every other endpoint that page calls requires admin_platform.
    # §DRIFTSKIP hit the mirror image of this on the same route — the guard said `federation` while
    # the backend enforced `admin_platform`, so a federation-only admin passed the guard and then
    # 403'd on the whole screen. Here the failure would have been quieter and worse: the panel
    # swallows its own load error by design, so the section would simply not appear and the page
    # would look complete. A peer-trust surface that is ABSENT is indistinguishable from a frame
    # that has no peers to worry about.
    # The verdict stays reachable to a federation-only admin on /federation, whose
    # topology-overview rail does require admin_federation.
    dependencies=[Security(security.require_admin_flag("admin_platform"))],
)
async def peer_trust_overview(
    db: AsyncSession = Depends(get_db),
    settlement_id: Optional[str] = Query(
        None, pattern=r"^[A-Za-z0-9-]{8,64}$",
        description="§SUITES1018: also report for which peer rows this one settlement was counted "
                    "(`settlement.counted_for`); `settlement.readable` is false when the claim store cannot answer"),
) -> Dict[str, Any]:
    """§TRUSTPOLICY — what this frame thinks of its peers, and what it does about it.

    One place an operator can answer three questions that used to need the
    source: which peers am I withholding from, on what evidence, and is this
    frame actually acting or only watching.

    ⚠ `posture.mode` is reported beside every verdict on purpose. In `observe`
    the states are real and nothing is refused, and a reader who sees
    "restricted" without seeing the mode would reasonably conclude the peer had
    already lost something.
    """
    from ..models import PeerRegistry
    from ..services import peer_trust_policy as ptp
    from ..services.frame_policy import load as load_frame_policy

    policy = await load_frame_policy(db)
    rows = (await db.execute(
        select(PeerRegistry).order_by(PeerRegistry.id)
    )).scalars().all()

    peers, by_state = [], {}
    for r in rows:
        v = ptp.evaluate(r, policy)
        by_state[v.state] = by_state.get(v.state, 0) + 1
        peers.append({
            "id": r.id, "name": r.name, "peer_type": r.peer_type, "status": r.status,
            "total_interactions": r.total_interactions or 0,
            "disputes_lost_with": r.disputes_lost_with or 0,
            "bayesian_discount": (float(r.bayesian_discount)
                                  if r.bayesian_discount is not None else None),
            "last_interaction_at": (r.last_interaction_at.isoformat()
                                    if r.last_interaction_at else None),
            "label": ptp.describe(v),
            **v.to_dict(),
        })

    settlement = None
    if settlement_id:
        # §SUITES1018: for which rows the peer-trust recorder counted THIS settlement (its own claim keys, one exact
        # lookup per row). A counter's movement alone cannot say whose settlement moved it: any traffic between the two
        # registries moves the same counter.
        from ..background_tasks.leader import get_redis
        from ..background_tasks.reactor_peer_trust_observed import observation_key
        counted, readable = [], True
        try:
            rds = await get_redis()
            if rds is None:
                readable = False
            else:
                for r in rows:
                    if await rds.exists(observation_key(settlement_id, int(r.id))):
                        counted.append(r.name)
        except Exception:  # noqa: BLE001 - an unreadable claim store is a third state, not "counted for none"
            readable = False
        settlement = {"id": settlement_id, "readable": readable, "counted_for": counted if readable else None}

    return {
        **({"settlement": settlement} if settlement is not None else {}),
        "posture": {
            "mode": policy.get("peer_trust.mode", "observe"),
            "min_interactions": policy.get("peer_trust.min_interactions", 10),
            "warn_below": policy.get("peer_trust.warn_below", 0.70),
            "restrict_below": policy.get("peer_trust.restrict_below", 0.50),
            "suspend_below": policy.get("peer_trust.suspend_below", 0.30),
            "recover_margin": policy.get("peer_trust.recover_margin", 0.05),
            "policy_version": policy.version,
            "policy_source": policy.source,
            "declared": policy.posture(tuple(
                f"peer_trust.{k}" for k in
                ("mode", "min_interactions", "warn_below", "restrict_below",
                 "suspend_below", "recover_margin"))),
        },
        "by_state": by_state,
        "peers": peers,
        "note": ("A score of 0.5 is the Beta(1,1) prior: no evidence either way, not half "
                 "trust. Peers below min_interactions are UNMEASURED and are never acted on."),
    }


@router.get(
    "/admin/federation/topology-overview",
    dependencies=[Security(security.require_admin_flag("admin_federation"))],
)
async def topology_overview(
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Tier-bucketed federation topology with admin-only metadata.

    Response shape:
        {
          "frames":           [ { peer_base, admin_extras, trust_domain } ],
          "direct_peers":     [ { peer_base, admin_extras } ],
          "discovered":       [ { peer_base, admin_extras, parent_name } ],
          "cloud_operators":  [ { peer_base, admin_extras, application_id, cloud_url } ],
          "summary": {
            "total_peers":             int,
            "peers_by_type":           { frame, direct_peer, discovered, cloud_operator },
            "license_status_breakdown":{ active, suspended, revoked, none },
            "drift_count":             int,
            "oldest_discovered_at":    ISO8601 | null,
            "healthy_count":           int,
          }
        }
    """
    # §pass66 (2026-05-22) — stale operator cleanup. Torn-down ops have
    # peer_registries.status='INACTIVE' (set by teardown_cloud_operator in
    # cloud_provisioner.py). Previously this admin overview surfaced ALL
    # peer_registry rows including INACTIVE → Mission Control + Federation
    # admin tabs kept showing torn-down ops as if still federated. Same
    # leak hits public topology (main.py:_build_topology_tiers). Filter
    # both at the SQL layer — DB is the single source of truth.
    peer_rows = (
        await db.execute(
            select(models.PeerRegistry).where(models.PeerRegistry.status == "ACTIVE")
        )
    ).scalars().all()
    lic_rows = (await db.execute(select(models.FederationLicense))).scalars().all()
    app_rows = (
        await db.execute(
            select(models.OperatorApplication).where(
                models.OperatorApplication.cloud_torn_down_at.is_(None)
            )
        )
    ).scalars().all()

    lic_by_did = {l.operator_did: l for l in lic_rows if l.operator_did}
    lic_by_name = {l.operator_name: l for l in lic_rows if l.operator_name}
    app_by_name = {a.name: a for a in app_rows}
    peers_by_id = {p.id: p for p in peer_rows}

    # Pre-fetch SPIRE state once per request so every frame row in the response
    # + drift check shares the same snapshot. Two docker exec calls total.
    # If either fails we surface spire_bundle_active=None per-frame and skip
    # the drift contribution — don't false-positive on our own tooling outage.
    spire_federations: set = set()
    spire_bundles: set = set()
    spire_queryable = True
    bundle_freshness_by_td: Dict[str, dict] = {}
    # §pass55 bilateral: fetch SPIRE state when ANY peer has a non-local
    # trust_domain (frame OR direct_peer with cross-td federation). Previously
    # gated only on frame-type peers, which left Frame B (whose Registry-A row
    # is direct_peer) without bundle-freshness checks.
    _mgr_for_gate = None
    try:
        from agentvault_registry.services.frame_trust_manager import get_frame_trust_manager
        _mgr_for_gate = get_frame_trust_manager()
        _local_td_lower = (_mgr_for_gate.local_trust_domain or "").lower()
    except Exception:
        _local_td_lower = ""
    has_cross_td_peers = any(
        (p.trust_domain or "").lower()
        and (p.trust_domain or "").lower() != _local_td_lower
        and (p.peer_type or "") in ("frame", "direct_peer")
        for p in peer_rows
    )
    # Retain has_frame_peers symbol for downstream conditionals
    has_frame_peers = has_cross_td_peers
    if has_cross_td_peers:
        try:
            from agentvault_registry.services.frame_trust_manager import get_frame_trust_manager
            mgr = get_frame_trust_manager()
            fed_list, fed_err = await mgr.list_federation_relationships()
            bun_list, bun_err = await mgr.list_federated_trust_domains()
            if fed_err or bun_err:
                logger.warning(
                    f"[TopologyOverview] SPIRE query failed — frame rows will have "
                    f"spire_bundle_active=None. federation_err={fed_err!r} bundle_err={bun_err!r}"
                )
                spire_queryable = False
            else:
                spire_federations = {td.lower() for td in fed_list}
                spire_bundles = {td.lower() for td in bun_list}
                # Fetch freshness for every imported peer bundle in parallel.
                # Closes the §pass53 gap: existence ≠ freshness. We need cert
                # not_before to compute age; a stale-but-present bundle is the
                # silent failure mode the 4d drift exposed.
                #
                # §pass55 bilateral fix: include any peer with non-local
                # trust_domain (frame OR direct_peer). On Frame B, Registry-A
                # was historically classified as direct_peer despite being a
                # cross-trust-domain bilateral relationship — the previous
                # filter on peer_type='frame' skipped it, leaving Frame B blind
                # to Frame A's bundle freshness. SPIRE-level trust was already
                # bilateral; this just widens the UI/metric layer to match.
                _local_td = (mgr.local_trust_domain or "").lower()
                frame_tds = [
                    (p.trust_domain or "").lower()
                    for p in peer_rows
                    if (p.trust_domain or "")
                    and (p.trust_domain or "").lower() != _local_td
                    and (p.peer_type or "") in ("frame", "direct_peer")
                ]
                if frame_tds:
                    fresh_results = await asyncio.gather(
                        *(mgr.get_bundle_freshness(td) for td in frame_tds),
                        return_exceptions=True,
                    )
                    for td, fr in zip(frame_tds, fresh_results):
                        if isinstance(fr, Exception):
                            bundle_freshness_by_td[td] = {"trust_domain": td, "error": str(fr)}
                        else:
                            bundle_freshness_by_td[td] = fr.to_dict()
        except Exception as e:
            logger.warning(
                f"[TopologyOverview] SPIRE manager error — frame rows will have "
                f"spire_bundle_active=None: {e}",
                exc_info=True,
            )
            spire_queryable = False

    def _spire_bundle_active(peer: models.PeerRegistry) -> Optional[bool]:
        if not spire_queryable:
            return None
        td = (peer.trust_domain or "").lower()
        if not td:
            return None
        return (td in spire_federations) and (td in spire_bundles)

    def _resolve_license(peer, app):
        """Try peer.operator_did → license.operator_name → derive from app."""
        if peer.operator_did and peer.operator_did in lic_by_did:
            return lic_by_did[peer.operator_did]
        if peer.name and peer.name in lic_by_name:
            return lic_by_name[peer.name]
        if app is not None:
            try:
                derived_did = _derive_operator_did_from_app(app)
                if derived_did in lic_by_did:
                    return lic_by_did[derived_did]
            except Exception:
                pass
        return None

    frames: List[Dict[str, Any]] = []
    direct_peers: List[Dict[str, Any]] = []
    discovered: List[Dict[str, Any]] = []
    cloud_operators: List[Dict[str, Any]] = []
    peers_by_type: Dict[str, int] = {
        "frame": 0, "direct_peer": 0, "discovered": 0, "cloud_operator": 0,
    }
    license_breakdown: Dict[str, int] = {
        "active": 0, "suspended": 0, "revoked": 0, "none": 0,
    }
    drift_count = 0
    healthy_count = 0
    oldest_discovered: Optional[str] = None

    for r in peer_rows:
        app = app_by_name.get(r.name)
        lic = _resolve_license(r, app)
        drift_flags: List[str] = (
            detect_drift_for_operator(app, lic, r) if (app or lic) else []
        )
        # Frame-specific drift — adds `frame_bundle_stale` if SPIRE is missing
        # the federation relationship OR the trust bundle for this trust domain.
        # Runs IN ADDITION to operator drift so frames with legacy license rows
        # (none today but reserved) also surface operator-side drift.
        # If SPIRE isn't queryable this cycle, skip the frame contribution —
        # don't false-positive on our own tooling outage.
        # §pass55: also runs for direct_peer with non-local trust_domain
        # (bilateral case — Frame B's Registry-A row).
        _peer_td = (r.trust_domain or "").lower()
        _is_cross_td_peer = (
            has_cross_td_peers
            and (r.peer_type or "") in ("frame", "direct_peer")
            and bool(_peer_td)
            and _peer_td != _local_td_lower
        )
        if _is_cross_td_peer and spire_queryable:
            has_fed = _peer_td in spire_federations
            has_bun = _peer_td in spire_bundles
            # §BUNDLECLOCK (2026-09-09) — ONE RULE, BOTH CALLERS, SAME ANSWER.
            # This route already computes bundle_freshness a few lines above for the UI, and the
            # hourly drift monitor now reads the same clock. Feeding it in HERE is what stops the
            # admin page and the alarm from disagreeing about the same frame — the "one fact
            # computed in two places" class, and precisely how a present-but-EXPIRED bundle
            # stayed invisible: this page could see it, the alarm could not.
            _fr_for_rule = bundle_freshness_by_td.get(_peer_td) or {}
            if r.peer_type == "frame":
                drift_flags = list(set(
                    drift_flags
                    + detect_drift_for_frame(
                        r, spire_has_federation=has_fed, spire_has_bundle=has_bun,
                        bundle_expires_in_seconds=_fr_for_rule.get("expires_in_seconds"),
                        bundle_freshness_error=_fr_for_rule.get("error"),
                    )
                ))
            # §pass54: bundle freshness — flip drift flag if bundle is overdue
            # for refresh OR within 24h of expiry. Closes the 4d silent-drift
            # gap §pass53 root-caused.
            fr = bundle_freshness_by_td.get(_peer_td)
            if fr and not fr.get("error"):
                if fr.get("refresh_critical"):
                    drift_flags = list(set(drift_flags + ["frame_bundle_refresh_critical"]))
                elif fr.get("refresh_overdue"):
                    drift_flags = list(set(drift_flags + ["frame_bundle_refresh_overdue"]))
        if drift_flags:
            drift_count += 1
        if (r.health_check_failure_count or 0) < 3:
            healthy_count += 1

        pt = r.peer_type or "direct_peer"
        peers_by_type[pt] = peers_by_type.get(pt, 0) + 1

        lic_status_key = lic.status if lic else "none"
        license_breakdown[lic_status_key] = license_breakdown.get(lic_status_key, 0) + 1

        if r.discovered_at is not None:
            iso = r.discovered_at.isoformat()
            if oldest_discovered is None or iso < oldest_discovered:
                oldest_discovered = iso

        base = _peer_base(r, spire_bundle_active=_spire_bundle_active(r))
        extras = _peer_admin_extras(r, lic, app, drift_flags)
        row = {**base, **extras}
        # §pass55: attach bundle_freshness to ANY peer with non-local trust_domain
        # (frame or direct_peer). On Frame B, Registry-A is a direct_peer with
        # trust_domain=agentvault.com — bilateral with Frame A's frame-typed
        # row for Frame-B but classified differently. The pill should render
        # on both ends. See sessionlogs2026/SESSION_LOG_2026-05-20_PASS55*.
        if pt in ("frame", "direct_peer"):
            td = (r.trust_domain or "").lower()
            if td and td in bundle_freshness_by_td:
                row["bundle_freshness"] = bundle_freshness_by_td.get(td)

        if pt == "frame":
            frames.append(row)
        elif pt == "cloud_operator":
            # Chain-federated cloud ops (hop >= 2) have a parent peer — surface
            # it so the UI can render "via op-berlin" without a second call.
            if r.parent_registry_id:
                parent = peers_by_id.get(r.parent_registry_id)
                row["parent_name"] = parent.name if parent else None
            else:
                row["parent_name"] = None
            cloud_operators.append(row)
        elif pt == "discovered":
            parent = peers_by_id.get(r.parent_registry_id) if r.parent_registry_id else None
            row["parent_name"] = parent.name if parent else None
            discovered.append(row)
        else:
            direct_peers.append(row)

    # Deterministic sort for UI stability
    for bucket in (frames, direct_peers, discovered, cloud_operators):
        bucket.sort(key=lambda p: (p.get("hop_distance") or 99, p.get("name") or ""))

    # §pass54: bundle freshness summary across all frame peers. Buckets are
    # mutually-exclusive against `fresh` — `overdue` >120h since not_before,
    # `critical` >144h OR <24h to expiry, `unknown` if SPIRE query failed.
    bundles_fresh = 0
    bundles_overdue = 0
    bundles_critical = 0
    bundles_unknown = 0
    oldest_bundle_age_seconds: Optional[float] = None
    for td_key, fr in bundle_freshness_by_td.items():
        if fr.get("error"):
            bundles_unknown += 1
            if SPIRE_BUNDLE_HEALTH is not None:
                SPIRE_BUNDLE_HEALTH.labels(trust_domain=td_key).set(3)
            continue
        if fr.get("refresh_critical"):
            bundles_critical += 1
            health = 2
        elif fr.get("refresh_overdue"):
            bundles_overdue += 1
            health = 1
        else:
            bundles_fresh += 1
            health = 0
        age = fr.get("age_seconds")
        exp_in = fr.get("expires_in_seconds")
        if isinstance(age, (int, float)) and (oldest_bundle_age_seconds is None or age > oldest_bundle_age_seconds):
            oldest_bundle_age_seconds = age
        if SPIRE_BUNDLE_AGE is not None and isinstance(age, (int, float)):
            SPIRE_BUNDLE_AGE.labels(trust_domain=td_key).set(age)
        if SPIRE_BUNDLE_EXPIRES_IN is not None and isinstance(exp_in, (int, float)):
            SPIRE_BUNDLE_EXPIRES_IN.labels(trust_domain=td_key).set(exp_in)
        if SPIRE_BUNDLE_HEALTH is not None:
            SPIRE_BUNDLE_HEALTH.labels(trust_domain=td_key).set(health)

    return {
        "frames": frames,
        "direct_peers": direct_peers,
        "discovered": discovered,
        "cloud_operators": cloud_operators,
        "summary": {
            "total_peers": len(peer_rows),
            "peers_by_type": peers_by_type,
            "license_status_breakdown": license_breakdown,
            "drift_count": drift_count,
            "oldest_discovered_at": oldest_discovered,
            "healthy_count": healthy_count,
            # §pass54 bundle freshness rollup
            "bundles_fresh": bundles_fresh,
            "bundles_overdue": bundles_overdue,
            "bundles_critical": bundles_critical,
            "bundles_unknown": bundles_unknown,
            "oldest_bundle_age_seconds": oldest_bundle_age_seconds,
        },
    }


@router.get(
    "/admin/federation/topology/peers/{peer_id}/events",
    dependencies=[Security(security.require_admin_flag("admin_federation"))],
)
async def peer_events(
    peer_id: int = Path(..., ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Recent events touching a peer.

    Looks up the peer's three identifiers (peer_registry:{id},
    federation_license:{id}, operator_application:{id}) and queries the
    EventStore's /aggregate/{aggregate_id} endpoint for each. Merges, dedups,
    sorts by timestamp desc, returns the top ``limit``.
    """
    peer = (await db.execute(select(models.PeerRegistry).where(models.PeerRegistry.id == peer_id))).scalar_one_or_none()
    if peer is None:
        raise HTTPException(status_code=404, detail="Peer not found")

    # Resolve associated identifiers
    aggregate_ids: List[str] = [f"peer_registry:{peer.id}"]
    if peer.operator_did:
        lic = (await db.execute(
            select(models.FederationLicense).where(models.FederationLicense.operator_did == peer.operator_did)
        )).scalar_one_or_none()
        if lic is not None:
            aggregate_ids.append(f"federation_license:{lic.id}")
    app = (await db.execute(
        select(models.OperatorApplication).where(models.OperatorApplication.name == peer.name)
    )).scalar_one_or_none()
    if app is not None:
        aggregate_ids.append(f"operator_application:{app.id}")

    es_url = os.getenv("EVENT_STORE_URL", "http://event-store:8200").rstrip("/")
    internal_key = os.getenv("EVENT_STORE_INTERNAL_KEY") or os.getenv("INTERNAL_API_KEY", "")
    headers = {"X-Internal-Key": internal_key} if internal_key else {}

    all_events: List[Dict[str, Any]] = []
    seen: set = set()
    # §SOVKIT T5 (2026-09-14): was verify=False with no certificate, which the frame's mTLS sidecar refuses (an empty timeline)
    async with httpx.AsyncClient(timeout=5.0, verify=get_httpx_verify()) as client:
        for agg_id in aggregate_ids:
            try:
                r = await client.get(
                    f"{es_url}/api/v1/events/aggregate/{seg(agg_id)}",
                    headers=headers,
                )
                if r.status_code == 200:
                    body = r.json()
                    items = body if isinstance(body, list) else body.get("items", []) if isinstance(body, dict) else []
                    for ev in items[:limit]:
                        ev_id = ev.get("id") or f"{ev.get('event_type', '')}-{ev.get('timestamp', '')}"
                        if ev_id in seen:
                            continue
                        seen.add(ev_id)
                        all_events.append(ev)
            except Exception as exc:
                logger.debug(f"[topology.peer_events] EventStore fetch failed for {agg_id}: {exc}")

    all_events.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
    return {
        "peer_id": peer.id,
        "peer_name": peer.name,
        "aggregate_ids": aggregate_ids,
        "events": all_events[:limit],
        "count": len(all_events[:limit]),
    }


@router.post(
    "/admin/federation/topology/peers/{peer_id}/probe",
    dependencies=[Security(security.require_admin_flag("admin_federation"))],
)
async def peer_probe(
    peer_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Probe a peer's reachability with a HEAD/GET against its base URL.

    Best-effort live test — does not modify ``health_check_failure_count``
    (the background health checker owns that counter).
    """
    import time as _time
    peer = (await db.execute(select(models.PeerRegistry).where(models.PeerRegistry.id == peer_id))).scalar_one_or_none()
    if peer is None:
        raise HTTPException(status_code=404, detail="Peer not found")
    if not peer.base_url:
        return {"ok": False, "error": "Peer has no base_url"}

    # Strip federation port (8443) and try /health first; fall back to base URL.
    candidates: List[str] = []
    base = peer.base_url.rstrip("/")
    candidates.append(f"{base}/health")
    if ":8443" in base:
        no_port = base.replace(":8443", "")
        candidates.append(f"{no_port}/health")
    candidates.append(base)

    # §MCPTEST30 (V0636): every candidate is tried until one reads ok. The probe returned the FIRST answer, and a frame's
    # base_url is its federation address (:8443), whose /health answers 400 to a caller without a client certificate,
    # so every frame and operator peer read ok=false (measured on sbx-alpha: its three active peers, each on :8443) and
    # the next candidate, the console host without the port, was never asked. With none ok, the first answer stands.
    first: Optional[Dict[str, Any]] = None
    async with httpx.AsyncClient(timeout=4.0, verify=False, follow_redirects=True) as client:
        for url in candidates:
            t0 = _time.monotonic()
            try:
                r = await client.get(url)
                ms = int((_time.monotonic() - t0) * 1000)
                answer = {
                    "ok": 200 <= r.status_code < 400,
                    "status_code": r.status_code,
                    "url": url,
                    "latency_ms": ms,
                    "body_preview": (r.text or "")[:200],
                }
                if answer["ok"]:
                    return answer
                first = first or answer
            except Exception as exc:
                continue

    if first is not None:
        return {**first, "tried": candidates}
    return {"ok": False, "error": "All probe endpoints unreachable", "tried": candidates}


# ── §pass62 Federation Discovery — Local Registry drawer support ────────────
# Three endpoints that populate the Local Registry drawer with real data
# instead of the empty defaults the pseudo-peer (id=0) had before. Pattern
# mirrors the per-peer endpoints above but targets the registry-itself
# (no peer_id arg — implicit "self").
#
# Endpoints:
#   GET /admin/registry-stats          — agent/developer/peer counts, uptime
#   GET /admin/operator-lifecycle      — local registry's own application/license/cloud/spire layers
#   GET /admin/federation/local-events — recent ES events for aggregate_id="registry:self"
import time as _time

_STARTUP_T0 = _time.monotonic()


@router.get(
    "/admin/registry-stats",
    dependencies=[Security(security.require_admin_flag("admin_federation"))],
)
async def registry_stats(db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """Counts + uptime for the LOCAL registry (the one this code runs in).

    Used by Federation Discovery / Federation Network tab to populate the
    Local Registry drawer (peer.id===0). Without this endpoint the drawer
    showed empty defaults because the pseudo-peer had no real backing row.
    """
    from sqlalchemy import func as _func
    agent_count = (await db.execute(
        select(_func.count(models.Agent.id))
    )).scalar_one()
    developer_count = (await db.execute(
        select(_func.count(models.Developer.id))
    )).scalar_one()
    agent_card_count = (await db.execute(
        select(_func.count(models.AgentCard.id))
    )).scalar_one()
    peer_count_active = (await db.execute(
        select(_func.count(models.PeerRegistry.id))
        .where(models.PeerRegistry.status == "ACTIVE")
    )).scalar_one()
    peer_count_total = (await db.execute(
        select(_func.count(models.PeerRegistry.id))
    )).scalar_one()
    uptime_seconds = int(_time.monotonic() - _STARTUP_T0)
    return {
        "agent_count": int(agent_count or 0),
        "agent_card_count": int(agent_card_count or 0),
        "developer_count": int(developer_count or 0),
        "peer_count_active": int(peer_count_active or 0),
        "peer_count_total": int(peer_count_total or 0),
        "uptime_seconds": uptime_seconds,
        "registry_name": os.getenv("REGISTRY_NAME", "Local Registry"),
        "trust_domain": os.getenv("SPIRE_TRUST_DOMAIN", ""),
        "is_central_registry": os.getenv("IS_CENTRAL_REGISTRY", "false").lower() == "true",
        "is_genesis": os.getenv("FIAT_GENESIS_REGISTRY", "false").lower() == "true",
    }


@router.get(
    "/admin/operator-lifecycle",
    dependencies=[Security(security.require_admin_flag("admin_federation"))],
)
async def local_operator_lifecycle(db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """Lifecycle layers (APPLICATION/LICENSE/PEER/CLOUD/SPIRE) for the LOCAL registry.

    Mirrors the shape of the per-peer lifecycle pane so the shared drawer
    component can render Local + Peer with identical UI. Where the local
    registry has no record (e.g. mainframes have no OperatorApplication of
    their own), the field is null with `status='self_hosted'`.
    """
    registry_name = os.getenv("REGISTRY_NAME", "")
    trust_domain = os.getenv("SPIRE_TRUST_DOMAIN", "")
    is_central = os.getenv("IS_CENTRAL_REGISTRY", "false").lower() == "true"
    cloud_hosted_env = os.getenv("CLOUD_HOSTED", "false").lower() == "true"

    # APPLICATION layer — only set if a matching OperatorApplication exists
    application: Dict[str, Any] = {"status": "self_hosted", "id": None}
    app_row = None
    if registry_name:
        app_row = (await db.execute(
            select(models.OperatorApplication).where(models.OperatorApplication.name == registry_name)
        )).scalar_one_or_none()
    if app_row is not None:
        application = {
            "id": str(app_row.id),
            "name": app_row.name,
            "status": app_row.status,
            "created_at": app_row.created_at.isoformat() if app_row.created_at else None,
        }

    # LICENSE layer — derive from app row if present, else self_hosted
    license_layer: Dict[str, Any] = {"status": "self_hosted", "id": None}
    if app_row is not None and getattr(app_row, "operator_did", None):
        lic = (await db.execute(
            select(models.FederationLicense).where(
                models.FederationLicense.operator_did == app_row.operator_did
            )
        )).scalar_one_or_none()
        if lic is not None:
            license_layer = {
                "id": str(lic.id),
                "status": lic.status,
                "key_prefix": getattr(lic, "key_prefix", None),
                "issued_at": lic.issued_at.isoformat() if getattr(lic, "issued_at", None) else None,
                "expires_at": lic.expires_at.isoformat() if getattr(lic, "expires_at", None) else None,
                "suspended_reason": getattr(lic, "suspended_reason", None),
                "revoked_reason": getattr(lic, "revoked_reason", None),
            }

    # PEER_REGISTRY layer — the local registry is "self" (id=0 pseudo)
    peer_registry_layer = {
        "id": 0,
        "status": "ACTIVE",
        "name": registry_name or "Local Registry",
        "hop_distance": 0,
        "is_local": True,
    }

    # CLOUD_STACK layer — only relevant for cloud-op registries
    cloud_stack: Dict[str, Any] = {"hosted": cloud_hosted_env}
    if cloud_hosted_env:
        cloud_stack["url"] = os.getenv("PUBLIC_BASE_URL", "")
        cloud_stack["status"] = "live"

    # SPIRE_TRUST_BUNDLE layer — local SPIRE info
    spire_layer: Dict[str, Any] = {
        "trust_domain": trust_domain or None,
        "spire_server": os.getenv("SPIRE_SERVER_ADDRESS", ""),
        "active": bool(trust_domain),
    }
    if trust_domain:
        spire_layer["spiffe_id"] = f"spiffe://{trust_domain}"

    return {
        "registry_name": registry_name or "Local Registry",
        "is_central_registry": is_central,
        "is_local": True,
        "application": application,
        "license": license_layer,
        "peer_registry": peer_registry_layer,
        "cloud_stack": cloud_stack,
        "spire_bundle": spire_layer,
    }


@router.get(
    "/admin/federation/local-events",
    dependencies=[Security(security.require_admin_flag("admin_federation"))],
)
async def local_registry_events(
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Recent federation events touching the LOCAL registry (aggregate_id='registry:self').

    Mirrors ``/admin/federation/topology/peers/{peer_id}/events`` but queries
    self-aggregate IDs. Also pulls registry_card-related events + SPIRE bundle
    events for the local trust domain so the Local drawer's Events tab is
    meaningful instead of empty.
    """
    aggregate_ids: List[str] = ["registry:self", "registry:local"]
    trust_domain = os.getenv("SPIRE_TRUST_DOMAIN", "")
    if trust_domain:
        aggregate_ids.append(f"spire_bundle:{trust_domain}")
        aggregate_ids.append(f"registry_card:{trust_domain}")
    registry_name = os.getenv("REGISTRY_NAME", "")
    if registry_name:
        aggregate_ids.append(f"registry:{registry_name}")

    es_url = os.getenv("EVENT_STORE_URL", "http://event-store:8200").rstrip("/")
    internal_key = os.getenv("EVENT_STORE_INTERNAL_KEY") or os.getenv("INTERNAL_API_KEY", "")
    headers = {"X-Internal-Key": internal_key} if internal_key else {}

    all_events: List[Dict[str, Any]] = []
    seen: set = set()
    # §SOVKIT T5 (2026-09-14): was verify=False with no certificate, which the frame's mTLS sidecar refuses (an empty timeline)
    async with httpx.AsyncClient(timeout=5.0, verify=get_httpx_verify()) as client:
        for agg_id in aggregate_ids:
            try:
                r = await client.get(
                    f"{es_url}/api/v1/events/aggregate/{seg(agg_id)}",
                    headers=headers,
                )
                if r.status_code == 200:
                    body = r.json()
                    items = body if isinstance(body, list) else body.get("items", []) if isinstance(body, dict) else []
                    for ev in items[:limit]:
                        ev_id = ev.get("id") or f"{ev.get('event_type', '')}-{ev.get('timestamp', '')}"
                        if ev_id in seen:
                            continue
                        seen.add(ev_id)
                        all_events.append(ev)
            except Exception as exc:
                logger.debug(f"[topology.local_events] EventStore fetch failed for {agg_id}: {exc}")

    # Also pull any RegistryCardUpdated / FederationStateDriftDetected events
    # filtered by event-type rather than aggregate (some events use mixed agg ids)
    type_filters = [
        "RegistryCardUpdated",
        "RegistrySigningKeyRotated",
        "SpireBundleRefreshed",
        "FederationStateDriftDetected",
        "PeerRegistryUrlAutoCorrected",
    ]
    # §SOVKIT T5 (2026-09-14): was verify=False with no certificate, which the frame's mTLS sidecar refuses
    async with httpx.AsyncClient(timeout=5.0, verify=get_httpx_verify()) as client:
        try:
            # §VITALS 2026-09-04, two silent defects in one call:
            #  · the path needs its TRAILING SLASH (without it the ES vhost
            #    redirects to http://…:80 and the fetch dies in ConnectError,
            #    caught below at DEBUG — the panel just stayed empty);
            #  · `event_types` (plural) IS NOT A PARAMETER. FastAPI drops unknown
            #    query params, so the filter never applied, and with no
            #    `event_type` the endpoint's default is ASC — it would have
            #    returned the 30 OLDEST events in the store, not the newest.
            # Newest-first with a client-side filter is one request and says what
            # it means.
            r = await client.get(
                f"{es_url}/api/v1/events/",
                params={"limit": 200, "sort_order": "desc"},
                headers=headers,
            )
            if r.status_code in (301, 302, 307, 308):
                logger.warning(
                    "[topology.local_events] EventStore answered %s -> %s; not following "
                    "a redirect that drops the scheme", r.status_code, r.headers.get("location", "?")
                )
            if r.status_code == 200:
                body = r.json()
                items = body if isinstance(body, list) else body.get("items", []) if isinstance(body, dict) else []
                _wanted = set(type_filters)
                items = [e for e in items if e.get("event_type") in _wanted]
                for ev in items[:30]:
                    ev_id = ev.get("id") or f"{ev.get('event_type', '')}-{ev.get('timestamp', '')}"
                    if ev_id in seen:
                        continue
                    seen.add(ev_id)
                    all_events.append(ev)
        except Exception as exc:
            logger.debug(f"[topology.local_events] EventStore type-filter fetch failed: {exc}")

    all_events.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
    return {
        "registry": registry_name or "Local Registry",
        "aggregate_ids": aggregate_ids,
        "events": all_events[:limit],
        "count": len(all_events[:limit]),
    }
