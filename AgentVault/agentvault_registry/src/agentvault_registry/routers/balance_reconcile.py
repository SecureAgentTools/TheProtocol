"""Balance Reconcile — multi-op-aware ES↔TEG drift (report-only legs).

§2026-06-18. An agent can hold REAL custody across MULTIPLE op TEGs of a frame
(sim multi-op funding; AGORA passport trading), and the EventStore
``materialized_balances`` row is the AGGREGATE across those ops. So the reconciler
sums an agent's ``token_balance`` across ALL of a frame's op TEGs and compares the
sum to the ES aggregate — reading a SINGLE TEG falsely flags every multi-op agent
(this faked a −72.6M reading; summed correctly it was a real −4,414).

The Galactic Command Center orchestrates the cross-op fan-out (it already holds the
per-op credential vault and does proven ``peerGet``). These two endpoints expose the
local primitives the GCC needs — one leg + the aggregate:

  GET /admin/balance-reconcile/local        — THIS registry's local TEG balances (one op leg)
  GET /admin/balance-reconcile/es-balances  — THIS frame's ES materialized_balances (the aggregate)

Read-only, admin-gated. Phase-2 adds a backend conductor + MCP tool + converge-gated
resync (resync-agent). Depends on the TEG primitive GET /api/v1/admin/all-agent-balances.
"""
import os

import httpx
from fastapi import APIRouter, HTTPException, Security

from agentvault_registry import models, security
from agentvault_registry.es_ssl_helper import get_httpx_verify

router = APIRouter()


def _teg_base() -> str:
    return os.getenv("TEG_API_BASE_URL", "http://teg-layer:8080").rstrip("/")


def _es_base() -> str:
    return (
        os.getenv("EVENT_STORE_PUBLIC_URL")
        or os.getenv("EVENT_STORE_URL")
        or "http://event-store:8000"
    ).rstrip("/")


@router.get(
    "/admin/balance-reconcile/local",
    summary="This registry's local TEG balances (one reconciler leg)",
)
async def balance_reconcile_local(
    current_developer: models.Developer = Security(security.require_admin_flag("admin_treasury")),
):
    """Proxy the local TEG's bulk balances — the token-custody truth for THIS op.

    The GCC fans out to every frame-family op's ``/local``, sums ``token_balance``
    per DID across ops, and compares the sum to ``/es-balances``. Read-only.
    """
    key = os.getenv("TEG_ADMIN_API_KEY", "")
    try:
        async with httpx.AsyncClient(timeout=20.0, verify=get_httpx_verify()) as client:
            resp = await client.get(
                f"{_teg_base()}/api/v1/admin/all-agent-balances",
                headers={"Authorization": f"Bearer {key}"},
            )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"local TEG unreachable: {exc}")
    if resp.status_code != 200:
        raise HTTPException(
            status_code=502, detail=f"local TEG all-agent-balances HTTP {resp.status_code}"
        )
    return resp.json()


@router.get(
    "/admin/balance-reconcile/es-balances",
    summary="This frame's ES materialized_balances (reconciler aggregate)",
)
async def balance_reconcile_es_balances(
    current_developer: models.Developer = Security(security.require_admin_flag("admin_treasury")),
):
    """Proxy the frame EventStore raw ``materialized_balances`` — the aggregate the
    op legs sum to. Same source the balance-reconciliation guard reads. Read-only.
    """
    key = os.getenv("EVENT_STORE_API_KEY", os.getenv("EVENT_STORE_INTERNAL_KEY", ""))
    try:
        async with httpx.AsyncClient(timeout=30.0, verify=get_httpx_verify()) as client:
            resp = await client.get(
                f"{_es_base()}/api/v1/projections/materialized-balances",
                headers={"X-Internal-Key": key},
            )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"ES unreachable: {exc}")
    if resp.status_code != 200:
        raise HTTPException(
            status_code=502, detail=f"ES materialized-balances HTTP {resp.status_code}"
        )
    return resp.json()
