"""The exact effective emission-policy configuration of this frame (W3, agentvault2-d6, 2026-10-25; his word: "a fe page
to check the exact configuration from the fe. i really need it visualized").

GET /api/v1/admin/event-emission-policies/effective returns build_view(): one matrix row per event type (every row of
the event_emission_policies table, every type the code emits per core/event_catalog.py, every type this frame's event
store holds), each saying what the registry's gate does with it, what the TEG's gate does, what the projection does,
how often the store holds it, how often the registry's shadow mode would have refused it, and its findings; the modes;
and, per peer frame, where the peer's rows differ from these.

What each column is derived from, so the page never claims more than was read:
- registry: this table and event_emitter.emission_policy_mode(); a type with no row is allowed ("off"), allowed and
  counted ("shadow") or refused ("enforce"); a row's emit_from_registry=false is refused in every mode.
- teg: the TEG's own rules applied to this table (the TEG reads these rows from the registry): a row's emit_from_teg,
  no row refused (the TEG fails closed), LedgerBalanceChanged always allowed. The TEG's environment is not readable from
  here: its fallback TEG_BLOCKED_EVENT_TYPES applies only while it cannot read the registry, and the view says so.
- projection: "balance" for the types the event store's balance projection counts (LedgerBalanceChanged and
  event_emitter.BALANCE_MOVING_EVENT_TYPES), "skipped" where the row's skip_in_projection is set, else "audit".
- store: the event store's own per-type counts (/api/v1/projections/stats, refreshed there every minute); "store_read"
  says when they could not be read, and then no type claims to be absent from the store.
- shadow: the counts the registry's workers wrote to Redis (the last 7 days of activity); null when Redis was not read.
- drift: each ACTIVE frame or operator peer's public /api/v1/agents/locations/emission-policies, read over the peer
  client the FX keeper uses (the frame's SVID on https); a peer that could not be read is named with the reason.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models
from ..core.event_catalog import REGISTRY_EMITS, TEG_ALWAYS_ALLOWED, TEG_EMITS

logger = logging.getLogger(__name__)

PROJECTION_BALANCE_EXTRA = frozenset({"LedgerBalanceChanged"})   # the single-writer projection's own input
PEER_TYPES = ("frame", "cloud_operator")
PEER_TIMEOUT = 8.0
PEER_PATH = "/api/v1/agents/locations/emission-policies"   # public on every registry (routers/agent_locations)
MAX_PEERS = 24

FINDING_TEXT = {
    "emitted-without-row": "emitted by this code, no row: the registry's gate decides by its mode, the TEG refuses it",
    "registry-emits-refused": "the registry emits it, its gate refuses it, and the TEG does not record it: the event is lost",
    "teg-emits-refused": "the TEG emits it, its gate refuses it, and the registry does not record it: the event is lost",
    "both-may-emit": "the row lets both the registry and the TEG emit it: one event could be recorded twice",
    "balance-type-skipped": "a balance-moving type the projection is told to skip: the event store refuses such writes",
    "row-without-emitter": "a row no code here emits (an agent's own events, a retired feature, or a test row)",
    "in-store-without-row": "in this frame's store with no row: the event store logs it as an unknown type",
    "shadow-would-refuse": "the registry's shadow mode counted emits that enforce would refuse",
}


def _registry_gate(row: Optional[dict], mode: str, emits: bool) -> str:
    if row is None:
        return {"off": "no-row-allowed", "shadow": "no-row-shadow", "enforce": "no-row-refused"}.get(mode, "no-row-shadow")
    return "allow" if row["emit_from_registry"] else "refuse"


def _teg_gate(event_type: str, row: Optional[dict]) -> str:
    if event_type in TEG_ALWAYS_ALLOWED:
        return "always-allowed"
    if row is None:
        return "no-row-refused"
    return "allow" if row["emit_from_teg"] else "refuse"


def _projection(event_type: str, row: Optional[dict], balance_types: frozenset) -> str:
    if row is not None and row["skip_in_projection"]:
        return "skipped"
    if event_type in balance_types or event_type in PROJECTION_BALANCE_EXTRA:
        return "balance"
    return "audit"


def matrix(rows: Dict[str, dict], *, mode: str, balance_types: frozenset, store_counts: Optional[Dict[str, int]],
           shadow: Optional[Dict[str, int]]) -> List[Dict[str, Any]]:
    """The pure part (no I/O): one entry per type in the rows, the catalog and the store."""
    types = set(rows) | REGISTRY_EMITS | TEG_EMITS | set(store_counts or {})
    out = []
    for t in sorted(types):
        row = rows.get(t)
        reg_emits, teg_emits = t in REGISTRY_EMITS, t in TEG_EMITS
        reg_gate, teg_gate = _registry_gate(row, mode, reg_emits), _teg_gate(t, row)
        proj = _projection(t, row, balance_types)
        findings = []
        if row is None and (reg_emits or (teg_emits and t not in TEG_ALWAYS_ALLOWED)):
            findings.append("emitted-without-row")
        # a refusal is a finding only where no other emitter records the event (TokensTransferred: the TEG emits it,
        # its gate refuses it, the registry records it, by design)
        reg_ok = reg_gate in ("allow", "no-row-allowed", "no-row-shadow")
        teg_ok = teg_gate in ("allow", "always-allowed")
        if reg_emits and not reg_ok and not (teg_emits and teg_ok):
            findings.append("registry-emits-refused")
        if teg_emits and not teg_ok and not (reg_emits and reg_ok):
            findings.append("teg-emits-refused")
        if row is not None and row["emit_from_registry"] and row["emit_from_teg"] and reg_emits and teg_emits:
            findings.append("both-may-emit")
        if row is not None and row["skip_in_projection"] and (t in balance_types or t in PROJECTION_BALANCE_EXTRA):
            findings.append("balance-type-skipped")
        if row is not None and not reg_emits and not teg_emits:
            findings.append("row-without-emitter")
        if store_counts is not None and row is None and store_counts.get(t):
            findings.append("in-store-without-row")
        would = (shadow or {}).get(t, 0)
        if would:
            findings.append("shadow-would-refuse")
        out.append({
            "event_type": t,
            "row": row,
            "emitted_by": [x for x, e in (("registry", reg_emits), ("teg", teg_emits)) if e],
            "registry": reg_gate,
            "teg": teg_gate,
            "projection": proj,
            "balance_moving": t in balance_types or t in PROJECTION_BALANCE_EXTRA,
            "store_count": None if store_counts is None else int(store_counts.get(t, 0)),
            "shadow_would_refuse": None if shadow is None else int(would),
            "findings": findings,
        })
    return out


def drift(here: Dict[str, dict], there: Dict[str, dict]) -> Dict[str, Any]:
    keys = ("emit_from_registry", "emit_from_teg", "skip_in_projection")
    differing = []
    for t in sorted(set(here) & set(there)):
        a = {k: bool(here[t].get(k)) for k in keys}
        b = {k: bool(there[t].get(k)) for k in keys}
        if a != b:
            differing.append({"event_type": t, "here": a, "there": b})
    return {"only_here": sorted(set(here) - set(there)), "only_there": sorted(set(there) - set(here)),
            "differing": differing}


async def _rows(db: AsyncSession) -> Dict[str, dict]:
    result = await db.execute(select(models.EventEmissionPolicy).order_by(models.EventEmissionPolicy.event_type))
    return {
        r.event_type: {
            "emit_from_registry": bool(r.emit_from_registry),
            "emit_from_teg": bool(r.emit_from_teg),
            "skip_in_projection": bool(r.skip_in_projection),
            "description": r.description,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }
        for r in result.scalars().all()
    }


async def _store_counts() -> tuple[Optional[Dict[str, int]], str]:
    import httpx
    from ..es_ssl_helper import get_httpx_verify
    url = os.getenv("EVENT_STORE_URL", "http://event-store:8200").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=10.0, verify=get_httpx_verify()) as client:
            r = await client.get(f"{url}/api/v1/projections/stats",
                                 headers={"X-Internal-Key": os.getenv("EVENT_STORE_API_KEY", "")})
        if r.status_code != 200:
            return None, f"the event store answered {r.status_code}"
        counts = (r.json() or {}).get("event_counts")
        if not isinstance(counts, dict) or not counts:
            return None, "the event store's stats carried no per-type counts (its cache may be warming)"
        return {str(k): int(v) for k, v in counts.items()}, "ok"
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"[:200]


async def _peer_rows(peer) -> tuple[Optional[Dict[str, dict]], str]:
    # D6-845: the read goes to the peer's PUBLIC address. Its internal mTLS lane (the peer's nginx-federation) routes only
    # the federation paths and answered 404 here for every peer, so the page read "not read" everywhere; the route is
    # public and unauthenticated on the peer's own host. The client is the one every other public peer read uses
    # (routers/agent_locations: verified TLS, no redirects, a name that resolves to this host dialled through its public
    # address with the name verified).
    from ..routers.agent_locations import _crawl_client, _crawl_get, _get_public_url
    pub = _get_public_url((peer.base_url or "").rstrip("/"))
    if not pub:
        return None, "no public address"
    try:
        async with _crawl_client(PEER_TIMEOUT) as client:
            r = await _crawl_get(client, pub, PEER_PATH)
        if r.status_code != 200:
            return None, f"answered {r.status_code} at {pub}"
        pol = (r.json() or {}).get("policies")
        if not isinstance(pol, list):
            return None, "no policies list in the answer"
        return {str(p.get("event_type")): p for p in pol if p.get("event_type")}, "ok"
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"[:160]


async def _drift_all(db: AsyncSession, here: Dict[str, dict]) -> List[Dict[str, Any]]:
    res = await db.execute(select(models.PeerRegistry).where(models.PeerRegistry.status == "ACTIVE"))
    peers = [p for p in res.scalars().all() if (getattr(p, "peer_type", None) or "") in PEER_TYPES][:MAX_PEERS]

    async def one(p):
        rows, why = await _peer_rows(p)
        entry = {"peer": p.name, "peer_type": getattr(p, "peer_type", None), "read": why}
        if rows is not None:
            entry.update(drift(here, rows))
        return entry

    return list(await asyncio.gather(*(one(p) for p in peers)))


async def build_view(db: AsyncSession, *, include_drift: bool = True) -> Dict[str, Any]:
    from .. import event_emitter as ee
    rows = await _rows(db)
    state = ee.emission_policy_state()
    mode = state["mode"]
    balance = frozenset(ee.BALANCE_MOVING_EVENT_TYPES)
    (store, store_read), shadow = await asyncio.gather(_store_counts(), ee.shadow_counts())
    m = matrix(rows, mode=mode, balance_types=balance, store_counts=store, shadow=shadow)
    by_finding: Dict[str, List[str]] = {}
    for e in m:
        for f in e["findings"]:
            by_finding.setdefault(f, []).append(e["event_type"])
    view: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "modes": {
            "registry": {
                "mode": mode,
                "no_row": {"off": "allowed", "shadow": "allowed, counted and logged as a refusal enforce would make",
                           "enforce": "refused"}[mode],
                "policy_table": {"rows": len(rows), "this_worker_cached": state["rows_cached"],
                                 "this_worker_loaded_at": state["loaded_at"], "this_worker_load_error": state["load_error"]},
                "set_by": "EVENT_EMITTER_POLICY_MODE (EVENT_EMITTER_FAIL_CLOSED=true means enforce)",
            },
            "teg": {
                "mode": "fail-closed",
                "no_row": "refused",
                "always_allowed": sorted(TEG_ALWAYS_ALLOWED),
                "derived": "from the TEG's rules applied to these rows (the TEG reads them from this registry); its "
                           "fallback TEG_BLOCKED_EVENT_TYPES applies only while it cannot read them, and is not readable here",
            },
            "projection": {"balance_types": sorted(balance | PROJECTION_BALANCE_EXTRA),
                           "skipped": sorted(t for t, r in rows.items() if r["skip_in_projection"])},
        },
        "catalog": {"registry": len(REGISTRY_EMITS), "teg": len(TEG_EMITS)},
        "store_read": store_read,
        "shadow_read": "ok" if shadow is not None else "Redis was not read: the shadow counts are unknown",
        "matrix": m,
        "summary": {
            "types": len(m),
            "rows": len(rows),
            "findings": {k: len(v) for k, v in sorted(by_finding.items())},
            "by_finding": {k: sorted(v) for k, v in sorted(by_finding.items())},
            "finding_text": FINDING_TEXT,
        },
    }
    if include_drift:
        try:
            view["drift"] = await _drift_all(db, rows)
        except Exception as e:  # noqa: BLE001
            view["drift"] = [{"peer": None, "read": f"{type(e).__name__}: {e}"[:200]}]
    return view
