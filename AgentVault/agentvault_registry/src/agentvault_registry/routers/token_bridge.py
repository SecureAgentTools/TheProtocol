"""SF-3's Token Bridge, RETIRED (V0651 (p), order gwo_b109ec1d4454d0db66ef6d32, agentvault2-14, 2026-10-31).

The maintainer's decision, typed in session-tester's session about 11:43Z (relayed in the room, seq 143), answering
"retire or fix the token bridge tools": "retire." It was D8's first entry (the legacy money surfaces retired behind
flags since 2026-09-05), off on the public network, on only on the sandbox.

Every /api/v1/bridge/* route answers 410 Gone with one sentence, on every registry and whatever TOKEN_BRIDGE_ENABLED
says (it is a retired switch: services/env_catalog.RETIRED). The routes take no body and run no dependency, so the 410
is what every caller reads (never a 422 or a 403 first). Nothing was deleted: bridge_transactions and its rows, and the
bridge's event types and their emission-policy rows, stay as history; the TEG's own bridge endpoints are unchanged, and
the expiry worker (background_tasks/bridge_expiry.py, the unlock path for an expired lock) keeps running and finds
nothing to do. The census read before (2026-10-31 12:47Z, all 11 standing frames): no open transfer and no wrapped
balance anywhere; Frame A's nine April rows are terminal (the residue named for the maintainer is in the delivery).
"""
from fastapi import APIRouter, HTTPException, status

RETIRED_SENTENCE = (
    "The token bridge is retired (V0651, the maintainer's decision of 2026-10-31): wrapped transfers between frames are "
    "gone on every registry. Move units between frames with POST /api/v1/teg/cross-registry-transfer, or across "
    "currencies through the FX route. The bridge's history (bridge_transactions) is kept and stays readable by an "
    "admin."
)

router = APIRouter(prefix="/api/v1/bridge", tags=["Token Bridge (retired)"])


def _gone() -> None:
    raise HTTPException(status_code=status.HTTP_410_GONE, detail=RETIRED_SENTENCE)


@router.post("/transfer", status_code=status.HTTP_410_GONE, deprecated=True, summary="Retired (V0651): 410 Gone")
async def bridge_transfer() -> None:
    """Retired in V0651: answers 410 Gone."""
    _gone()


@router.post("/mint-wrapped", status_code=status.HTTP_410_GONE, deprecated=True, summary="Retired (V0651): 410 Gone")
async def bridge_mint_wrapped() -> None:
    """Retired in V0651: answers 410 Gone."""
    _gone()


@router.post("/redeem", status_code=status.HTTP_410_GONE, deprecated=True, summary="Retired (V0651): 410 Gone")
async def bridge_redeem() -> None:
    """Retired in V0651: answers 410 Gone."""
    _gone()


@router.post("/unlock", status_code=status.HTTP_410_GONE, deprecated=True, summary="Retired (V0651): 410 Gone")
async def bridge_unlock_endpoint() -> None:
    """Retired in V0651: answers 410 Gone."""
    _gone()


@router.post("/confirm-lock", status_code=status.HTTP_410_GONE, deprecated=True, summary="Retired (V0651): 410 Gone")
async def bridge_confirm_lock() -> None:
    """Retired in V0651: answers 410 Gone."""
    _gone()


@router.get("/status/{bridge_tx_id}", status_code=status.HTTP_410_GONE, deprecated=True,
            summary="Retired (V0651): 410 Gone")
async def bridge_status(bridge_tx_id: str) -> None:
    """Retired in V0651: answers 410 Gone (the history stays in bridge_transactions, for an admin)."""
    _gone()
