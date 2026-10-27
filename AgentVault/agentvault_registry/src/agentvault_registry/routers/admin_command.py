"""Galactic Command Center backend — registry directory + fleet status (GCC Phase 1).

The Command Center FE (views/GalacticCommand.vue) joins galactic-map nodes to
actionable targets through ONE canonical directory served here. The FE never
slugs names or guesses URLs — matching and addressing are server-owned.

Endpoints (both Commander-gated, ``admin_platform``):
  GET /admin/command/registry-directory
        Canonical per-registry directory: key, tier, currency, frame, capability
        hints, the console address. Built from ``peer_registries`` (ACTIVE) + self.
  GET /admin/command/fleet-status
        Bounded parallel ``/health`` probes (3s, no credentials forwarded) for
        self + every registry the operator names in ``COMMAND_RELAY_URL_MAP``.

§FEFRAME W4 (V0507): the admin relay (``/admin/peer/{key}/…``) and the legacy
frame-letter maps are gone. The relay reached only the retired frames (its
allowlist came from ``PEER_REGISTRY_{A,B,C}_URL`` / ``COMMAND_RELAY_URL_MAP`` at
``COMMAND_RELAY_SCOPE=fleet``, set on no live registry); a console now signs in
at a registry's own address (the frame manifest's ``console_url``).

NOTE on probe addressing (audited 2026-06-10, re-measured 2026-10-01): the
probe URL comes ONLY from operator env (``COMMAND_RELAY_URL_MAP``, key →
base_url), never from DB URLs: ``peer_registries.base_url`` points at the :8443
federation mTLS gateways (plain httpx cannot handshake those), and from inside a
registry container the frames answer at their public addresses while the
operators' ``*.op.theprotocol.cloud`` addresses refuse the connection, so a probe
of the manifest's addresses would report every operator down.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx
from fastapi import APIRouter, Depends, Security
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry import models, security
from agentvault_registry.core.registry_identity import get_software_version
from agentvault_registry.database import get_db
from agentvault_registry.core.federation_view import key_of as _manifest_key_of

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/command", tags=["Admin — Galactic Command"])

def _local_key() -> str:
    return (
        os.environ.get("REGISTRY_FEDERATION_NAME")
        or os.environ.get("REGISTRY_NAME")
        or "registry"
    ).strip().lower()


def _probe_url_map() -> Dict[str, str]:
    """``COMMAND_RELAY_URL_MAP`` (key → base_url): the registries the operator asks fleet-status to probe."""
    raw = os.getenv("COMMAND_RELAY_URL_MAP") or ""
    if not raw.strip():
        return {}
    try:
        m = json.loads(raw)
        return {str(k).strip().lower(): str(v).rstrip("/") for k, v in m.items() if v}
    except Exception as e:  # noqa: BLE001 — bad operator JSON must not 500 the API
        logger.warning(f"[command] COMMAND_RELAY_URL_MAP unparseable: {e}")
        return {}


def _card(p: models.PeerRegistry) -> Dict[str, Any]:
    c = getattr(p, "cached_registry_card", None)
    return c if isinstance(c, dict) else {}


def _tier_for(p: models.PeerRegistry) -> str:
    tier = str(_card(p).get("identity", {}).get("tier") or "").strip().lower()
    if tier:
        return tier
    pt = (p.peer_type or "").lower()
    if pt == "frame":
        return "sovereign-mainframe"
    return "cloud-operator"


def _currency_for(p: models.PeerRegistry) -> str:
    # §FEFRAME W2: the card's settlement currency or nothing; the AVT / BVT fallback named the retired frames'
    # units for every peer whose card had not been pulled (EU and ASIA peers among them).
    return str(_card(p).get("fees", {}).get("settlement_currency") or "").strip().upper()


def _capabilities(tier: str, peer_type: str, is_local: bool) -> List[str]:
    caps = ["observe"]
    if not is_local:
        caps.append("cross_teg_fund_target")
    if (peer_type or "").lower() in ("cloud_operator", "discovered") and not is_local:
        caps.append("op_lifecycle")  # op-type target; FE cross-checks manageability via /admin/cloud-operators
    if tier.endswith("mainframe"):
        # Frames keep their special functions (Commander doctrine): minting,
        # fiat genesis, compliance live ONLY on mainframe-tier registries.
        caps.extend(["mint", "fiat", "compliance"])
    return caps


def _entry(
    *, key: str, name: str, trust_domain: Optional[str], peer_type: str,
    tier: str, currency: str, hop: Optional[int], is_local: bool,
    card_version: Optional[str], card_pulled_at: Optional[str],
    manifest_entry: Optional[Dict[str, Any]] = None, frame_key: Optional[str] = None,
) -> Dict[str, Any]:
    me = manifest_entry or {}
    return {
        "key": key,
        "name": name,
        "trust_domain": trust_domain,
        # §FEFRAME W2: the frame this registry belongs to, by the frame manifest's key (a frame: itself; an operator:
        # its parent); null when the manifest does not know it (W4: no legacy letters any more)
        "frame": frame_key,
        # §FEFRAME W2: where a person opens it, and the ledger it streams (core/federation_view.py)
        "console_url": me.get("console_url"),
        "ws_url": me.get("ledger_ws"),
        # §FEFRAME W3: this registry's key in the frame manifest (the session hub's key); `key` stays the lowercased
        # peer-row name the command centre has always used, and the console registers the two as aliases
        "manifest_key": me.get("key") or _manifest_key_of(name),
        "tier": tier,
        "currency": currency,
        "peer_type": peer_type,
        "hop_distance": hop,
        "is_local": is_local,
        "card_software_version": card_version,
        "card_last_pulled_at": card_pulled_at,
        "capabilities": _capabilities(tier, peer_type, is_local),
        "match": {"names": sorted({name, key, name.lower()}), "trust_domain": trust_domain},
    }


@router.get("/registry-directory")
async def registry_directory(
    db: AsyncSession = Depends(get_db),
    _admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
) -> Dict[str, Any]:
    """Canonical registry directory for the Galactic Command Center."""
    local_key = _local_key()
    local_td = (os.environ.get("SPIRE_TRUST_DOMAIN") or "").strip().lower() or None
    # §FEFRAME W2: the local row's tier is the card builder's own (_build_tier: a cloud operator is "cloud-operator"),
    # not "sovereign-mainframe" for every registry without IS_CENTRAL_REGISTRY, which handed operators the
    # mint / fiat / compliance capability hints of a frame.
    try:
        from agentvault_registry.services.registry_card_builder import _build_tier
        local_tier = _build_tier() or "sovereign-mainframe"
    except Exception:  # noqa: BLE001
        local_tier = "mainframe" if os.environ.get("IS_CENTRAL_REGISTRY", "").lower() == "true" else "sovereign-mainframe"
    local_currency = (os.environ.get("FRAME_CURRENCY") or "").strip().upper()
    from agentvault_registry.core import federation_view as _fv
    _m = await _fv.manifest_now()
    _by_key: Dict[str, Dict[str, Any]] = {}
    if _m:
        for _e in [_m.get("self") or {}] + list(_m.get("peers") or []):
            if _e.get("key"):
                _by_key[_e["key"]] = _e
    _key_of = _fv.key_of

    def _frame_key(e: Optional[Dict[str, Any]]) -> Optional[str]:
        if not e:
            return None
        return e.get("key") if e.get("role") == "frame" else e.get("parent")
    _self_e = (_m or {}).get("self") or None

    entries: List[Dict[str, Any]] = [
        _entry(
            key=local_key, name=local_key, trust_domain=local_td, peer_type="local",
            tier=local_tier, currency=local_currency, hop=0, is_local=True,
            # P7: the local row carries the LIVE deploy tag (not a cached card) —
            # the FE uses it as the authoritative baseline for version-drift badges.
            card_version=get_software_version() or None, card_pulled_at=None,
            manifest_entry=_self_e, frame_key=_frame_key(_self_e),
        )
    ]

    rows = (
        (await db.execute(select(models.PeerRegistry).where(models.PeerRegistry.status == "ACTIVE")))
        .scalars()
        .all()
    )
    for p in rows:
        name = (p.name or "").strip()
        # §FEFRAME W2: a row named after THIS registry is a fan-out echo of itself, never a peer
        if not name or name.lower() == local_key or _key_of(name) == _key_of(local_key):
            continue
        card = _card(p)
        pulled = getattr(p, "card_last_pulled_at", None)
        entries.append(
            _entry(
                key=name.lower(),
                name=name,
                trust_domain=(p.trust_domain or None),
                peer_type=(p.peer_type or "discovered"),
                tier=_tier_for(p),
                currency=_currency_for(p),
                hop=getattr(p, "hop_distance", None),
                is_local=False,
                card_version=(card.get("identity", {}) or {}).get("software_version"),
                card_pulled_at=(pulled.isoformat() if pulled else None),
                manifest_entry=_by_key.get(_key_of(name)), frame_key=_frame_key(_by_key.get(_key_of(name))),
            )
        )

    return {"local_key": local_key, "registries": entries}


@router.get("/fleet-status")
async def fleet_status(
    db: AsyncSession = Depends(get_db),
    _admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
) -> Dict[str, Any]:
    """Credential-free /health probes for self + every ACTIVE peer the operator names in COMMAND_RELAY_URL_MAP."""
    targets: Dict[str, str] = {_local_key(): "http://localhost:8000"}
    url_map = _probe_url_map()
    rows = (
        (await db.execute(select(models.PeerRegistry.name).where(models.PeerRegistry.status == "ACTIVE")))
        .scalars()
        .all()
    )
    for name in rows:
        k = (name or "").strip().lower()
        if not k:
            continue
        url = url_map.get(k)
        if url:
            targets[k] = url

    async def probe(key: str, base: str) -> Tuple[str, Dict[str, Any]]:
        t0 = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=3.0, verify=True) as client:
                r = await client.get(f"{base}/health")
            return key, {
                "health": "up" if r.status_code == 200 else "degraded",
                "status_code": r.status_code,
                "latency_ms": round((time.monotonic() - t0) * 1000),
            }
        except Exception as e:  # noqa: BLE001 — a down peer is data, not an error
            return key, {"health": "down", "error": str(e)[:120], "latency_ms": round((time.monotonic() - t0) * 1000)}

    results = await asyncio.gather(*(probe(k, u) for k, u in targets.items()))
    return {"probed_at": time.time(), "status": {k: v for k, v in results}}


@router.get("/auditor-latest")
async def auditor_latest(
    _admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
) -> Dict[str, Any]:
    """GC2-1 (2026-06-12): server-side proxy to the independent supply auditor.

    The auditor (auditor.theprotocol.cloud) verifies the supply invariant
    ATOMICALLY per frame (frame-a / frame-b / frame-c keys, plus sbx-* which
    callers should ignore) — unlike the ES /supply-audit HTTP read, which can
    show cosmetic read-skew under load. It serves no CORS headers, so the
    cockpit's tri-frame Δ strip fetches it through this same-origin proxy.
    Read-only passthrough; admin-gated like the rest of the command surface.
    """
    url = os.getenv("AUDITOR_LATEST_URL", "https://auditor.theprotocol.cloud/api/auditor/latest")
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=4.0, verify=True) as client:
            r = await client.get(url)
        data = r.json() if r.status_code == 200 else None
        return {
            "ok": r.status_code == 200,
            "status_code": r.status_code,
            "latency_ms": round((time.monotonic() - t0) * 1000),
            "data": data,
        }
    except Exception as e:  # noqa: BLE001 — an unreachable auditor is data, not an error
        return {"ok": False, "error": str(e)[:160], "latency_ms": round((time.monotonic() - t0) * 1000), "data": None}
