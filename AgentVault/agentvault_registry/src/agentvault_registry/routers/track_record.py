"""§AGENTDISC #186 — public track-record attestation endpoints (2026-08-16).

Public by design: everything served here is already publicly derivable from the guild
board (orders, bounties, settled timelines) — this surface just makes it VERIFIABLE.
CORS is open (like card-export) so #193's verify-at-origin can fetch cross-origin.

  GET /api/v1/agents/{did}/track-record
      → { did, summary, recent[], credential_pubkey, attested_by }
      200 with a zeroed summary for a known agent with no history (honest zero);
      404 only when the DID is neither a local agent nor present in the guild books.

  GET /api/v1/agents/{did}/track-record/receipts/{order_id}
      → the verifiable receipt for one engagement (local: canonical subset + digest +
        deterministically re-issued Ed25519 credential; traveled: the stored
        ingestion-verified bundle + verify-at-origin pointer).
"""
from __future__ import annotations

import logging
import os
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry.database import get_db
from agentvault_registry.services import track_record
from agentvault_registry.services.guild_reputation import credential_pubkey

logger = logging.getLogger(__name__)

router = APIRouter()

_CACHE_HEADERS = {
    "Cache-Control": "public, max-age=60, stale-while-revalidate=120",
    "Access-Control-Allow-Origin": "*",
}


def _attested_by() -> dict:
    from agentvault_registry.core.public_url import public_base_url_static
    return {
        "registry": os.environ.get("REGISTRY_NAME") or None,
        "url": public_base_url_static(),
    }


_EMPTY_SUMMARY = {
    "jobs_verified": 0, "local_jobs": 0, "traveled_jobs": 0,
    "avg_stars": None, "five_star": 0,
    "on_time": {"met": 0, "of": 0},
    "disputes": {"total": 0, "lost": 0},
    "volume": [],
    "cross_registry_jobs": 0, "distinct_hosts": 0,
    "distinct_posters": 0, "repeat_poster_jobs": 0,
    "first_verified_at": None, "last_verified_at": None,
}


@router.get(
    "/agents/{did:path}/track-record/receipts/{order_id}",
    summary="Verifiable receipt for one engagement (public)",
)
async def get_track_record_receipt(
    did: str = Path(..., description="Worker agent DID"),
    order_id: str = Path(..., max_length=40),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    from fastapi.responses import JSONResponse
    receipt = await track_record.build_local_receipt(db, did, order_id)
    if receipt is None:
        receipt = await track_record.build_traveled_receipt(db, did, order_id)
    if receipt is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            detail="No verifiable engagement for this DID and order")
    receipt["attested_by"] = _attested_by()
    return JSONResponse(receipt, headers={**_CACHE_HEADERS,
                                          "Cache-Control": "public, max-age=300"})


@router.get(
    "/agents/{did:path}/track-record/threshold",
    summary="Signed threshold attestation (public): discloses only the threshold",
)
async def get_threshold_attestation(
    did: str = Path(..., description="Worker agent DID"),
    min_jobs: int = Query(1, ge=1, le=10000),
    min_stars: float = Query(0.0, ge=0.0, le=5.0),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    """
    An Ed25519-signed attestation, by the registry, that this agent's registry-attested record meets `min_jobs` and
    `min_stars`, without disclosing counts, amounts, clients or engagements. It is a signed threshold attestation,
    not a zero-knowledge proof. A record below the threshold answers 409. Verifiable offline against the attestation
    signer's public key, like the work credentials. Public, no auth.

    \f
    §AGENTDISC #194 — the discretion lane: an Ed25519-SIGNED attestation that this
    agent's registry-attested record MEETS `min_jobs`/`min_stars`, WITHOUT disclosing
    counts, amounts, clients, or engagements. Honest naming: this is a signed
    threshold attestation by the registry, not a zero-knowledge proof — the true ZK
    aggregate circuit (`proof_of_reputation`, Noir) remains the documented handoff
    and slots into this same endpoint when compiled. A record below the threshold
    returns 409 (inherent to any threshold claim). Offline-verifiable against the
    attestation signer pubkey, exactly like work credentials.
    """
    from fastapi.responses import JSONResponse
    from datetime import datetime, timezone
    summaries = await track_record.track_record_summaries(db, [did])
    s = summaries.get(did)
    meets = bool(
        s
        and s["jobs_verified"] >= min_jobs
        and (min_stars <= 0 or (s["avg_stars"] is not None and s["avg_stars"] >= min_stars))
    )
    if not meets:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail="The attested record does not meet the requested threshold")
    claim = {
        "kind": "guild.threshold.v1",
        "worker_did": did,
        "min_jobs": int(min_jobs),
        "min_stars": float(min_stars),
        "meets": True,
        "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "attested_by": _attested_by().get("url"),
    }
    try:
        from agentvault_registry.services.attestation_signer import sign_bundle
        bundle = sign_bundle(claim)
    except Exception:  # noqa: BLE001
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="Attestation signer unavailable")
    return JSONResponse({
        "attestation": bundle,
        "credential_pubkey": credential_pubkey(),
        "zk_note": "signed threshold attestation; the ZK aggregate circuit is a documented handoff",
    }, headers={**_CACHE_HEADERS, "Cache-Control": "public, max-age=30"})


@router.get(
    "/agents/{did:path}/track-record",
    summary="Registry-attested guild work history (public)",
)
async def get_track_record(
    did: str = Path(..., description="Worker agent DID"),
    recent: int = Query(5, ge=0, le=25, description="How many recent engagement rows to include"),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    from fastapi.responses import JSONResponse
    summaries = await track_record.track_record_summaries(db, [did])
    summary = summaries.get(did)
    if summary is None:
        known = (await db.execute(
            text("SELECT 1 FROM agents WHERE did = :d"), {"d": did})).scalar()
        if not known:
            raise HTTPException(status.HTTP_404_NOT_FOUND,
                                detail="Unknown agent DID (no agent row, no guild history)")
        summary = dict(_EMPTY_SUMMARY)
    rows = await track_record.track_record_detail(db, did, limit=recent) if recent else []

    # §AGENTDISC #197 — liveness as a hireability signal, honestly bounded by what the
    # registry actually observes: the health checker's probe outcome (agents.last_health)
    # and the real heartbeat (last_active_at). No uptime percentages or latency medians
    # are fabricated — that history is not persisted. null when the DID has no agents row
    # (federated mirrors heartbeat on their home frame).
    liveness = None
    lrow = (await db.execute(text("""
        SELECT last_health, last_active_at,
               (last_active_at IS NOT NULL AND last_active_at > now() - interval '24 hours') AS live_24h
        FROM agents WHERE did = :d
    """), {"d": did})).first()
    if lrow:
        liveness = {
            "probe": lrow[0],
            "last_seen": lrow[1].isoformat() if lrow[1] else None,
            "live_24h": bool(lrow[2]),
        }

    return JSONResponse({
        "did": did,
        "summary": summary,
        "recent": rows,
        "liveness": liveness,
        "credential_pubkey": credential_pubkey(),
        "attested_by": _attested_by(),
        "receipt_kind": track_record.RECEIPT_KIND,
    }, headers=_CACHE_HEADERS)
