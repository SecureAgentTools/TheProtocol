"""CROSS-FRAME CONTRACTS — inbound mirror reactor (2026-07-26).

Consumes `ContractMirrored` from the event bus and materialises a local READ-ONLY replica of a
contract that lives on another frame.

Two rules this reactor will not bend:

**Verify before storing.** The envelope carries the home frame's Ed25519 signature over the
contract's content digest. An envelope that does not verify against the home's published JWKS is
dropped and counted — never stored. A replica whose provenance cannot be established is worse
than no replica, because the interface would present it as fact.

**Store only what is ours to store.** A mirror addressed to a different peer is ignored. The bus
is shared; that a message reached us is not evidence it was meant for us.

CQRS discipline (the framework rule): this handler calls commands and emits NOTHING. The peer's
reconciler, not another event, is what repairs drift.
"""
import logging
from typing import Optional

from .reactor_base import EventStoreReactor

logger = logging.getLogger(__name__)

_instances: Optional[list] = None


class ContractMirroredReactor(EventStoreReactor):
    event_type = "ContractMirrored"
    leader_key = "reactor_contract_mirrored"
    name = "XFrame:ContractMirrored"

    async def handle_event(self, event_data: dict) -> None:
        from agentvault_registry.database import AsyncSessionLocal
        from agentvault_registry.services import contract_xframe as xf

        if not xf.enabled():
            return

        payload = (event_data or {}).get("payload") or {}
        cid = payload.get("cid")
        target = (event_data or {}).get("peer_registry")
        me = xf.self_federation_name()

        if not cid:
            return
        # Addressed to someone else — the bus is shared, delivery is not intent.
        if target and me and target != me:
            logger.debug("[XFRAME] ignoring mirror for %s (addressed to %s, we are %s)",
                         cid, target, me)
            return
        # Our own emission coming back around. Home already has the truth.
        if payload.get("home_registry") == me:
            return

        async with AsyncSessionLocal() as db:
            ok = await xf.verify_envelope(db, event_data)
            if not ok:
                logger.warning("[XFRAME] REJECTED unverifiable mirror cid=%s home=%s — not stored",
                               cid, payload.get("home_registry"))
                return
            wrote = await xf.upsert_replica(db, event_data, verified=True)
            await db.commit()
            if wrote:
                logger.info("[XFRAME] replica %s cid=%s status=%s seq=%s (home=%s)",
                            "updated", cid, payload.get("status"), payload.get("seq"),
                            payload.get("home_registry"))
            else:
                # Older sequence than what we hold: the bus makes no ordering promise across
                # frames, so this is expected and is exactly what the seq guard is for.
                logger.debug("[XFRAME] mirror for %s ignored as stale (seq=%s)",
                             cid, payload.get("seq"))


async def start() -> None:
    global _instances
    if _instances is None:
        _instances = [ContractMirroredReactor()]
    for r in _instances:
        await r.start()
