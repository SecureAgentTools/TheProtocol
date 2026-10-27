"""CROSS-FRAME CONTRACT worker (2026-07-26) — outbox emitter + digest reconciler.

Two jobs, one leader-elected loop, because both are cheap sweeps over small sets:

**Outbox (home side).** `contract_events` is written in the same transaction as every state
change, so it already is a transactional outbox. This sweep mirrors any cross-frame contract
whose committed trail has moved past `contracts.mirrored_seq`. Reading committed rows is the
whole point: a mirror can never describe a transition that rolled back, and no transition site
had to be touched to get that guarantee.

**Reconciler (peer side).** Cross-frame event fanout is best-effort by design. A contract is a
legal object and cannot rest on best-effort delivery, so this compares each open replica's
digest against the home frame's authoritative digest and re-pulls on mismatch.

    The event is the optimisation. THIS is the guarantee.

Both are status/metadata only. No money, no escrow, no authority — Δ-irrelevant.
"""
import asyncio
import logging

from sqlalchemy import text

from ..database import AsyncSessionLocal as async_session_factory
from ..services import contract_xframe as xf

logger = logging.getLogger(__name__)

_running = False
CYCLE_SECONDS = 60
BATCH = 100


async def _sweep_outbox(db) -> int:
    """Emit mirrors for committed transitions the peer has not been told about."""
    sent = 0
    for row in await xf.pending_mirrors(db, BATCH):
        env = await xf.emit_mirror(db, row["cid"], reason="outbox")
        if env is not None:
            await xf.mark_mirrored(db, row["cid"], row["max_seq"])
            sent += 1
    if sent:
        await db.commit()
    return sent


async def _reconcile_replicas(db) -> tuple:
    """Compare each open replica against home's digest; re-pull the ones that disagree."""
    from ..services.exchange_passport import peer_request  # peer mTLS, name-resolved

    checked = healed = stale = 0
    for r in await xf.open_replicas(db, BATCH):
        checked += 1
        try:
            status_code, body = await peer_request(
                db, r["home_registry"], "GET",
                f"/api/v1/federation/contract-digest?cid={r['cid']}",
            )
        except Exception:
            # Peer unreachable is not drift — leave the replica alone and try next cycle.
            continue
        if status_code != 200 or not isinstance(body, dict):
            continue
        if body.get("digest") == r["digest"]:
            # Agreed with home — record the check itself, not a content change.
            await xf.touch_replica(db, r["cid"])
            continue

        # Home disagrees. Take home's signed envelope as truth, or mark stale so the surface
        # can say so rather than presenting a figure we can no longer stand behind.
        env = body.get("envelope")
        if env and await xf.verify_envelope(db, env):
            if await xf.upsert_replica(db, env, verified=True):
                healed += 1
                continue
        await xf.mark_stale(db, r["cid"], True)
        stale += 1
    if checked or healed or stale:
        await db.commit()
    return checked, healed, stale


async def _bootstrap_from_peers(db) -> int:
    """Pull contracts addressed to us from every active peer.

    Push cannot bootstrap: a mirror emitted before this registry started listening is
    deduplicated on re-emission by its idempotency key and never arrives, and the reconciler
    only repairs replicas it already holds. This closes that hole, and doubles as the recovery
    path if the replica table is ever lost entirely.

    Runs every BOOTSTRAP_EVERY cycles rather than every cycle — it is a safety net, not a hot
    path, and it costs one call per peer.
    """
    from ..services.exchange_passport import peer_request

    adopted = 0
    peers = await xf.active_peer_names(db)
    for name in peers:
        try:
            code, body = await peer_request(db, name, "GET", "/api/v1/federation/contracts-for-peer")
        except Exception:
            continue
        if code != 200 or not isinstance(body, dict):
            continue
        for env in (body.get("contracts") or []):
            if await xf.verify_envelope(db, env):
                if await xf.upsert_replica(db, env, verified=True):
                    adopted += 1
            else:
                logger.warning("[XFRAME] bootstrap: unverifiable envelope from %s — skipped", name)
    if adopted:
        await db.commit()
    return adopted


_cycle_n = 0
BOOTSTRAP_EVERY = 5


async def _cycle():
    global _cycle_n
    try:
        async with async_session_factory() as db:
            sent = await _sweep_outbox(db)
            _cycle_n += 1
            adopted = 0
            if _cycle_n % BOOTSTRAP_EVERY == 1:
                adopted = await _bootstrap_from_peers(db)
                if adopted:
                    logger.info("[XFRAME] bootstrap adopted %d replica(s) from peers", adopted)
            checked, healed, stale = await _reconcile_replicas(db)
            if sent or healed or stale:
                logger.info(
                    "[XFRAME] mirrored=%d | reconciled: checked=%d healed=%d stale=%d",
                    sent, checked, healed, stale,
                )
            else:
                logger.debug("[XFRAME] nothing to do (checked=%d)", checked)
    except Exception:
        # §VITALS: re-raised so the cycle stamps `error`. The loop below still
        # catches and continues, so behaviour is unchanged — but a cycle that
        # failed no longer looks exactly like a cycle with nothing to do.
        logger.error("[XFRAME] cycle error", exc_info=True)
        raise


async def contract_xframe_loop():
    from .leader import try_acquire_leadership
    from . import vitals as _vitals
    global _running
    _running = True
    if not xf.enabled():
        logger.info("[XFRAME] worker idle (CONTRACTS_XFRAME_MODE=%s)", xf.mode())
    else:
        logger.info("[XFRAME] worker started (%ds cycle, mode=%s)", CYCLE_SECONDS, xf.mode())
    await _vitals.register(
        "contract_xframe", module=__name__, pattern="hand-rolled",
        interval_sec=CYCLE_SECONDS, enabled=xf.enabled(),
    )
    while _running:
        try:
            # Re-read the flag every cycle so the ratchet does not need a restart.
            if xf.enabled() and await try_acquire_leadership("contract_xframe"):
                async with _vitals.cycle("contract_xframe"):
                    await _cycle()
        except Exception:
            logger.error("[XFRAME] loop error", exc_info=True)
        await asyncio.sleep(CYCLE_SECONDS)


def stop_contract_xframe():
    global _running
    _running = False
