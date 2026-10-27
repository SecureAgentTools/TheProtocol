"""§BATCH7 (2026-09-05) — the fresh network, introduced on production's landing page.

`GET /api/v1/public/fresh-network` returns live facts about the fresh frames named in FRESH_NETWORK_JSON
(a list of {name, currency, currency_name, console, registry_url, es_url, status_url, role}), read
server-side with a short cache so the landing page never fetches cross-origin: the registry card's
version, the supply audit's delta/status, the bond config. Every leg is best-effort and reports its own
third state (`reachable: false`) instead of failing the section. Nothing here moves money or writes.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/public", tags=["Public"])

_CACHE: Dict[str, Any] = {"ts": 0.0, "body": None}
_TTL = 20.0


def strip_of(entry: Dict[str, Any]) -> str:
    """The ledger strip a FRESH_NETWORK_JSON entry belongs to: "sandbox" when it says so, otherwise "main"."""
    return "sandbox" if str((entry or {}).get("strip") or "").strip().lower() == "sandbox" else "main"


def _frames_cfg() -> List[Dict[str, Any]]:
    raw = (os.getenv("FRESH_NETWORK_JSON", "") or "").strip()
    if not raw:
        return []
    try:
        val = json.loads(raw)
        return [f for f in val if isinstance(f, dict) and f.get("name")] if isinstance(val, list) else []
    except Exception as e:  # noqa: BLE001
        logger.warning("[fresh-network] FRESH_NETWORK_JSON unparsable: %s", e)
        return []


async def _get_json(client: httpx.AsyncClient, url: str) -> Optional[Dict[str, Any]]:
    try:
        r = await client.get(url)
        if r.status_code == 200:
            return r.json()
    except Exception:  # noqa: BLE001
        return None
    return None


async def _frame_facts(client: httpx.AsyncClient, f: Dict[str, Any]) -> Dict[str, Any]:
    reg = (f.get("registry_url") or "").rstrip("/")
    es = (f.get("es_url") or "").rstrip("/")
    card, audit, bond = await asyncio.gather(
        _get_json(client, f"{reg}/.well-known/registry-card.json") if reg else asyncio.sleep(0, result=None),
        # §FEFRAME W2: a frame named by the manifest has no store address here; its PUBLIC supply seal answers
        _get_json(client, f"{es}/api/v1/projections/supply-audit") if es else
        (_get_json(client, f"{reg}/api/v1/public/supply-invariant") if reg else asyncio.sleep(0, result=None)),
        _get_json(client, f"{reg}/api/v1/reputation-bond/config") if reg else asyncio.sleep(0, result=None),
    )
    ident = (card or {}).get("identity") or {}
    # §DIDWIDEN follow-up (his eye 2026-09-06: "eu frame is not located in brüssels on the landingpage"): no card
    # has ever carried identity.location — the registry card's location lives in the OPERATOR block
    # (operator.location_label + latitude/longitude, Registry Card v0.3 "authoritative for operator location").
    oper = (card or {}).get("operator") or {}
    _loc = ident.get("location") if isinstance(ident.get("location"), dict) else {}
    out = {
        "name": f.get("name"), "currency": f.get("currency"), "currency_name": f.get("currency_name"),
        "role": f.get("role"), "console": f.get("console") or reg, "status_url": f.get("status_url"),
        "registry_url": reg, "es_url": es,
        "reachable": card is not None,
        "version": ident.get("software_version"), "registry_name": ident.get("registry_name"),
        "location": _loc.get("label") or oper.get("location_label") or None,
        "latitude": oper.get("latitude") if oper.get("latitude") is not None else _loc.get("latitude"),
        "longitude": oper.get("longitude") if oper.get("longitude") is not None else _loc.get("longitude"),
        "supply": None, "bond": None,
        # §BATCH9 (his word 2026-09-06: the fresh pair is NOT promoted — "list them under sandbox and wire the
        # new sandboxes also"): the group the landing page files a frame under, the same-origin ledger socket the
        # apex proxies for it, and its operators — all data, so a new sandbox frame is one JSON entry, never an FE edit.
        "group": str(f.get("group") or "sandbox"), "ws_path": f.get("ws_path"), "slug": f.get("slug"),
        # §FEFRAME W2: a manifest-derived frame's absolute ledger socket (env entries name a same-origin ws_path)
        "ws_url": f.get("ws_url"), "source": f.get("source") or "env",
        "operators": list(f.get("operators") or []),
        # §AGORASIM-2 (2026-09-22, his words: "add the sandbox live event ledgers as collapsed thing like the live
        # ledger has on the frontpage"): the folded ledger strip the landing page files this frame under. Only
        # "sandbox" is a strip of its own; anything else is the main live ledger.
        "strip": strip_of(f),
    }
    if audit:
        out["supply"] = {k: audit.get(k) for k in ("delta", "status", "total_circulating", "tokens_issued")}
    if bond:
        out["bond"] = {k: bond.get(k) for k in ("mode", "amount", "currency")}
    return out


async def _frames_from_manifest() -> List[Dict[str, Any]]:
    """§FEFRAME W2: with no FRESH_NETWORK_JSON (the sandbox, every operator) the frames are the frame manifest's
    (core/federation_view.py): this registry's federation as the server knows it, each at its PUBLIC origin (so the
    facts are read the way any outsider would) with its absolute ledger socket. The env stays an override: EU's
    hand-set list (with its folded sandbox strip) is served as before."""
    from agentvault_registry.core import federation_view as fv
    m = await fv.manifest_now()
    if not m:
        return []
    out: List[Dict[str, Any]] = []
    for e in [m.get("self") or {}] + list(m.get("peers") or []):
        if e.get("role") != "frame" or not e.get("public_url"):
            continue
        out.append({"name": e.get("display_name") or e.get("name"), "slug": e.get("key"), "currency": e.get("currency"),
                    "currency_name": e.get("currency_name"), "role": "frame", "console": e.get("console_url"),
                    "registry_url": e.get("public_url"), "es_url": "", "status_url": None,
                    "group": "main", "strip": "main", "ws_url": e.get("ledger_ws"), "source": "manifest"})
    return out


@router.get("/fresh-network", summary="The fresh network: live facts about the fresh frames (public, cached)")
async def fresh_network() -> Dict[str, Any]:
    now = time.time()
    if _CACHE["body"] is not None and now - _CACHE["ts"] < _TTL:
        return _CACHE["body"]
    frames = _frames_cfg() or await _frames_from_manifest()
    if not frames:
        body = {"enabled": False, "frames": [], "as_of": now}
        _CACHE.update(ts=now, body=body)
        return body
    async with httpx.AsyncClient(timeout=6.0, follow_redirects=False) as client:
        facts = await asyncio.gather(*[_frame_facts(client, f) for f in frames])
    body = {"enabled": True, "frames": list(facts), "as_of": now}
    _CACHE.update(ts=now, body=body)
    return body
