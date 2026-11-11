"""V0660 (a): the quantum workload extension's public reads (services/quantum_agent_card.py; the spec is the stack's
PRODUCTION_DOCS/SPECS/Quantum_Agent_Card_Extension_v1.0.md).

    GET /api/v1/quantum/workload-extension     the extension's URI, version, spec name and JSON Schema, and this frame's
                                               mode (a generator validates against the same bytes this registry does)
    GET /api/v1/quantum/agents/{agent_did}     one agent's extension as its card states it: the params, this registry's
                                               check of them, the index facets discovery reads, and how old each
                                               backend's facts are at this read

The search is GET /api/v1/agent-cards/discover with its quantum filters. Both routes answer only where the frame serves
the extension (QUANTUM_WORKLOADS_MODE shadow or on). Under off they answer 403 with the switch's sentence and are left
out of the OpenAPI schema (main.py mounts this router with include_in_schema from the mode). Reads only: nothing here
writes, and a direct DID lookup is not enumeration (an unlisted card answers its own DID, as every card read does).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry import database, models
from agentvault_registry.core.quantum_mode import quantum_workloads_mode
from agentvault_registry.services import quantum_agent_card as _qac
from agentvault_registry.services.home_extensions import is_native

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/quantum", tags=["Quantum workloads"])


def require_quantum_workloads_served() -> None:
    """403 with the switch's sentence where QUANTUM_WORKLOADS_MODE is off (read per call)."""
    if not _qac.served():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_qac.OFF_SENTENCE)


@router.get(
    "/workload-extension",
    summary="The quantum workload extension: URI, version and JSON Schema",
    description="The A2A agent card extension this registry checks quantum workload cards against, with its JSON Schema "
                "and this frame's QUANTUM_WORKLOADS_MODE. Public.",
    dependencies=[Depends(require_quantum_workloads_served)],
)
async def get_quantum_workload_extension() -> Dict[str, Any]:
    return {
        "uri": _qac.EXTENSION_URI,
        "version": _qac.EXTENSION_VERSION,
        "spec": _qac.SPEC_NAME,
        "schema_sha256": _qac.SCHEMA_SHA256,
        "mode": quantum_workloads_mode(),
        "placement": "top-level extensions[] of the agent card, one entry",
        "schema": _qac.schema(),
    }


async def _card_for(db: AsyncSession, did: str) -> Optional[models.AgentCard]:
    """The active card for the DID: this registry's own when it holds one, else the newest mirror."""
    rows = (await db.execute(
        select(models.AgentCard)
        .where(models.AgentCard.agent_did == did, models.AgentCard.is_active == True)  # noqa: E712
        .order_by(models.AgentCard.updated_at.desc())
        .limit(10)
    )).scalars().all()
    native = [r for r in rows if is_native(r.card_data)]
    return (native or list(rows) or [None])[0]


@router.get(
    "/agents/{agent_did}",
    summary="One agent's quantum workload extension, checked and indexed",
    description="The quantum workload extension the agent's card states, this registry's check of it, the facets "
                "discovery indexes, and the age of each backend's facts at this read. Public.",
    dependencies=[Depends(require_quantum_workloads_served)],
)
async def get_agent_quantum_workload(
    agent_did: str = Path(..., min_length=8, max_length=200, description="The agent's DID."),
    db: AsyncSession = Depends(database.get_db),
) -> Dict[str, Any]:
    card = await _card_for(db, agent_did)
    if card is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"agent_card_not_found: no active agent card for {agent_did} on this registry.")
    cd = card.card_data if isinstance(card.card_data, dict) else {}
    ext = _qac.extension_from_card(cd)
    if ext is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"no_quantum_workload: the card of {agent_did} carries no quantum workload "
                                   "extension in its top-level extensions[].")
    params = ext.get("params") if isinstance(ext.get("params"), dict) else None
    local = is_native(cd)
    fm = cd.get("federation_metadata") if isinstance(cd.get("federation_metadata"), dict) else {}
    problems = _qac.check(cd)
    return {
        "agent_did": agent_did,
        "card_id": str(card.id),
        "name": card.name,
        "is_local": local,
        "origin": "Local" if local else (fm.get("origin_registry_name") or fm.get("source_registry") or "Federated"),
        "uri": _qac.EXTENSION_URI,
        "version": (params or {}).get("version"),
        "spec": _qac.SPEC_NAME,
        "required": bool(ext.get("required")),
        "params": params,
        # this registry's reading of the spec; a mirror's home is the registry that checks its writes
        "check": {"valid": not problems, "problems": problems, "mode": quantum_workloads_mode()},
        "index": _qac.facets(params),
        "freshness": _qac.freshness(params),
    }
