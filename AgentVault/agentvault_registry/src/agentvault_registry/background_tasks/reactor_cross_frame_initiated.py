"""
Reactor: CrossFrameTransferInitiated → receiver-side credit + Settled emit
==========================================================================
Receiver-frame reactor for the async cross-frame transfer path
(`TEG_CROSS_FRAME_BACKEND=async`). Catches `CrossFrameTransferInitiated`
events that arrived via the foreign_events Pub/Sub bridge, credits the
local recipient via TEG, records the inbound row, and emits Settled back
through the same bus so the sender frame's reactor can clear pending.

Filter: only acts when `target_frame` matches THIS frame's trust domain.
Cross-frame events for other frames are skipped silently.

Idempotency:
- INSERT cross_frame_transfers_inbound ON CONFLICT (id) DO NOTHING.
- TEG /cross-teg/credit-async dedups on transfer_id at the TEG layer.
- ES dedup on idempotency_key=xfer-{id} handles event re-emission.
- Reactor framework dedup-ring (256 entries) absorbs WS replay.

D6-801 (2026-10-17): no credit from a quarantined peer. The event names only its sender's trust domain
(`source_frame`), so the reactor asks, before it credits, whether this registry holds a registry of that trust domain
in quarantine, soft quarantine or blacklisted (federation_license_gate.quarantined_trust_domain; one read per trust
domain every REACTOR_CROSS_FRAME_QUARANTINE_TTL_SEC, default 30 s). If it does, nothing is credited: the transfer is
recorded REFUSED (an inbound row with status 'refused', and a warning naming the registry and its state), no Settled
is sent, and the sender's saga refunds its sender at its timeout. A refused transfer is never credited later, even
when the quarantine has been lifted by then (its sender may already be refunded), and the Refunded reactor reverses
only a credited row. When the compliance state cannot be read, nothing is credited and nothing is recorded: the
handler raises, and the event is handled again later.
"""
from __future__ import annotations

import asyncio
import logging
import os
from decimal import Decimal
from typing import Optional

import httpx
from ..es_ssl_helper import get_httpx_verify
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from .. import models
from ..database import get_db_context
from ..event_emitter import get_event_emitter
from .reactor_base import EventStoreReactor

logger = logging.getLogger(__name__)


def _this_frame_trust_domain() -> str:
    """The local frame's SPIRE trust domain. Set via env in compose.

    Frame A: agentvault.com
    Frame B: frame-b.theprotocol.cloud
    Sandbox A: sandbox-a.test
    Sandbox B: sandbox-b.test
    """
    return os.getenv("SPIRE_TRUST_DOMAIN", "agentvault.com")


# ---------------------------------------------------------------------------
# Vector B (2026-05-04) — Bulk credit-async proxy
# ---------------------------------------------------------------------------
# Mirrors the TEGBulkProxy pattern at routers/teg_integration.py:92. When
# REACTOR_CREDIT_ASYNC_BULK_ENABLED=true, handle_event enqueues the credit-async
# payload + awaits a future resolved when the batch flushes. Per-leader-process
# buffer (reactor is leader-elected, so all events for this op flow through one
# process — no fragmentation per feedback_per_worker_buffer_doesnt_batch.md).
#
# Default OFF → handle_event falls back to the existing per-event single-call
# path. Image deploy is zero-behavior-change; behavior activates only when env
# flag flipped on the registry container.

_BULK_ENABLED = os.environ.get("REACTOR_CREDIT_ASYNC_BULK_ENABLED", "false").lower() == "true"
_BULK_MAX_SIZE = int(os.environ.get("REACTOR_CREDIT_ASYNC_BATCH_MAX", "50"))
_BULK_FLUSH_MS = int(os.environ.get("REACTOR_CREDIT_ASYNC_FLUSH_MS", "100"))
_BULK_SUBMIT_TIMEOUT_S = int(os.environ.get("REACTOR_CREDIT_ASYNC_SUBMIT_TIMEOUT_S", "30"))


class _CreditAsyncBulkProxy:
    """Per-leader-process buffer + periodic flush task. Each submit() returns
    a future resolved when its payload's batch lands at receiver TEG."""

    def __init__(self) -> None:
        self._buf: list = []  # list of (payload_dict, asyncio.Future)
        self._lock = asyncio.Lock()
        self._flush_task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._flush_task = asyncio.create_task(self._periodic_flush())
        logger.info(
            f"[CreditAsyncBulk] started (batch_max={_BULK_MAX_SIZE}, "
            f"flush_ms={_BULK_FLUSH_MS}, submit_timeout_s={_BULK_SUBMIT_TIMEOUT_S})"
        )

    async def stop(self) -> None:
        self._running = False
        if self._flush_task is not None:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
            self._flush_task = None
        # Drain any leftover items so awaiting submits don't hang
        try:
            await self._flush(force=True)
        except Exception as e:
            logger.warning(f"[CreditAsyncBulk] drain on stop failed: {e}")
        logger.info("[CreditAsyncBulk] stopped")

    async def submit(self, payload: dict) -> dict:
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        async with self._lock:
            self._buf.append((payload, fut))
            buf_len = len(self._buf)
        if buf_len >= _BULK_MAX_SIZE:
            asyncio.create_task(self._flush(force=True))
        return await asyncio.wait_for(fut, timeout=_BULK_SUBMIT_TIMEOUT_S)

    async def _periodic_flush(self) -> None:
        # Timer firing means: flush whatever's pending now. force=True so single
        # events (light load) don't sit in the buffer waiting for it to fill to
        # _BULK_MAX_SIZE — they get drained on the next tick. The size-cap path
        # in submit() already triggers immediate force=True flush when full, so
        # high-load behavior is unchanged.
        while self._running:
            try:
                await asyncio.sleep(_BULK_FLUSH_MS / 1000.0)
                await self._flush(force=True)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"[CreditAsyncBulk] periodic flush error: {e}")

    async def _flush(self, force: bool) -> None:
        async with self._lock:
            if not self._buf:
                return
            if not force and len(self._buf) < _BULK_MAX_SIZE:
                return
            batch = self._buf
            self._buf = []

        teg_url = os.getenv("TEG_API_BASE_URL", "http://teg-layer:8080")
        teg_key = os.getenv("TEG_ADMIN_API_KEY", "")
        try:
            async with httpx.AsyncClient(timeout=30.0, verify=get_httpx_verify()) as client:
                resp = await client.post(
                    f"{teg_url}/api/v1/cross-teg/credit-async-bulk",
                    json={"transfers": [p for p, _ in batch]},
                    headers={"Authorization": f"Bearer {teg_key}"},
                )
            if resp.status_code not in (200, 201):
                err = RuntimeError(f"bulk {resp.status_code}: {resp.text[:200]}")
                for _, f in batch:
                    if not f.done():
                        f.set_exception(err)
                logger.warning(
                    f"[CreditAsyncBulk] flush failed: HTTP {resp.status_code} "
                    f"batch_size={len(batch)}"
                )
                return
            data = resp.json()
            by_tid = {
                r["transfer_id"]: r
                for r in data.get("results", [])
                if r and r.get("transfer_id")
            }
            n_ok = 0
            n_err = 0
            for payload, f in batch:
                if f.done():
                    continue
                tid = payload.get("transfer_id")
                row = by_tid.get(tid)
                if row is None:
                    f.set_exception(RuntimeError(f"no result for {tid}"))
                    n_err += 1
                elif row.get("status") == "error":
                    f.set_exception(RuntimeError(row.get("error", "unknown")))
                    n_err += 1
                else:
                    f.set_result(row)
                    n_ok += 1
            logger.info(
                f"[CreditAsyncBulk] flushed batch_size={len(batch)} "
                f"ok={n_ok} err={n_err} force={force}"
            )
        except Exception as e:
            for _, f in batch:
                if not f.done():
                    f.set_exception(e)
            logger.error(f"[CreditAsyncBulk] flush exception: {e}")


_proxy: Optional[_CreditAsyncBulkProxy] = None


async def _get_proxy() -> Optional[_CreditAsyncBulkProxy]:
    """Lazy-init the bulk proxy on first call. Returns None when feature flag
    is off, so callers fall through to the legacy per-event path."""
    global _proxy
    if not _BULK_ENABLED:
        return None
    if _proxy is None:
        _proxy = _CreditAsyncBulkProxy()
        await _proxy.start()
    return _proxy


# Vector C (2026-05-04) — Local agent DID cache.
# Every cross-frame Initiated event fans out to ALL receiver-side registries
# on the frame (mainframe + 4 ops). Only the registry that owns the receiver
# should credit; the others must filter the event out. Previously each reactor
# did a per-event DB SELECT against `agents` to check locality — 4-of-5 of
# those are wasted lookups under sustained sim load (saturates pgbouncer pool
# and queues the productive 1-of-5 dispatch behind 4 doomed lookups).
#
# Fix: cache the local agents' DIDs as an in-memory set, refreshed every
# `LOCAL_AGENTS_REFRESH_SEC` (default 60). handle_event short-circuits before
# DB hit when receiver_did is not in the cache. Empty cache (e.g., first 60s
# after restart) falls through to DB — no behavior change while warming up.
_LOCAL_AGENTS_REFRESH_SEC = int(os.environ.get("REACTOR_LOCAL_AGENTS_REFRESH_SEC", "60"))

# D6-801: how long one trust domain's quarantine verdict is reused before the compliance state is read again
_QUARANTINE_TTL_SEC = float(os.environ.get("REACTOR_CROSS_FRAME_QUARANTINE_TTL_SEC", "30"))


class CrossFrameInitiatedReactor(EventStoreReactor):
    event_type = "CrossFrameTransferInitiated"
    leader_key = "reactor_cross_frame_initiated"
    name = "CrossFrameInitiated"
    # 2026-05-16: Tighten polling-backstop to 10s for cross-frame reactors.
    # Canary cross-frame paths have SLO=60s + 30s grace = 90s deadline. The
    # base 30s interval risks a single WS-missed event blowing the SLO. 10s
    # keeps missed events well inside the deadline. Env-overridable.
    polling_backstop_interval_seconds = int(
        os.environ.get("REACTOR_CROSS_FRAME_POLLING_BACKSTOP_INTERVAL_SEC", "10")
    )

    def __init__(self) -> None:
        super().__init__()
        self._local_agent_dids: frozenset = frozenset()
        self._cache_refresh_task: Optional[asyncio.Task] = None
        self._quarantine_cache: dict = {}   # D6-801: trust domain -> (verdict, monotonic time read)

    async def _source_quarantine(self, db, source_frame: str):
        """D6-801: (registry name, state) when this registry holds a registry of the credit's source trust domain in
        quarantine, soft quarantine or blacklisted, else None; read once per trust domain per _QUARANTINE_TTL_SEC.
        Raises when the compliance state cannot be read (then nothing is credited and the event is handled again
        later); a failed read is never cached."""
        import time
        td = (source_frame or "").strip().lower()
        now = time.monotonic()
        cached = self._quarantine_cache.get(td)
        if cached is not None and now - cached[1] < _QUARANTINE_TTL_SEC:
            return cached[0]
        from ..services.federation_license_gate import quarantined_trust_domain
        verdict = await quarantined_trust_domain(db, td)
        self._quarantine_cache[td] = (verdict, now)
        return verdict

    async def _refresh_local_agent_dids(self) -> None:
        try:
            async with get_db_context() as db:
                rows = await db.execute(select(models.Agent.did))
                dids = {r[0] for r in rows.fetchall() if r[0]}
            self._local_agent_dids = frozenset(dids)
            logger.info(
                f"[Reactor:{self.name}] Refreshed local agent DID cache "
                f"size={len(self._local_agent_dids)}"
            )
        except Exception as e:
            logger.warning(
                f"[Reactor:{self.name}] local agent DID cache refresh failed: {e}"
            )

    async def _refresh_loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(_LOCAL_AGENTS_REFRESH_SEC)
                await self._refresh_local_agent_dids()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"[Reactor:{self.name}] cache refresh loop error: {e}")

    async def start(self) -> None:
        # Populate cache BEFORE WS loop starts so first-batch events get the
        # short-circuit. If this fails, fall through to DB lookup mode.
        await self._refresh_local_agent_dids()
        await super().start()
        self._cache_refresh_task = asyncio.create_task(self._refresh_loop())

    async def stop(self) -> None:
        if self._cache_refresh_task is not None:
            self._cache_refresh_task.cancel()
            try:
                await self._cache_refresh_task
            except asyncio.CancelledError:
                pass
            self._cache_refresh_task = None
        await super().stop()

    async def handle_event(self, event_data: dict) -> None:
        target_frame = event_data.get("target_frame", "")
        local_frame = _this_frame_trust_domain()
        if target_frame != local_frame:
            logger.debug(
                f"[Reactor:{self.name}] Skip — target_frame={target_frame} "
                f"!= local={local_frame}"
            )
            return

        transfer_id = event_data.get("transfer_id", "")
        sender_did = event_data.get("sender_did", "")
        receiver_did = event_data.get("receiver_did", "")
        source_frame = event_data.get("source_frame", "")
        amount_str = event_data.get("amount", "0")
        if not (transfer_id and sender_did and receiver_did and source_frame):
            logger.warning(
                f"[Reactor:{self.name}] Malformed payload — missing required "
                f"fields. transfer_id={transfer_id}"
            )
            return

        try:
            amount = Decimal(str(amount_str))
        except Exception:
            logger.warning(
                f"[Reactor:{self.name}] Malformed amount={amount_str} "
                f"transfer_id={transfer_id}"
            )
            return

        idem_key = f"xfer-{transfer_id}"

        # Vector C: cache short-circuit. If the cache is populated and this DID
        # isn't in it, this registry doesn't own the receiver — skip without
        # touching the DB. Eliminates 4-of-5 wasted DB SELECTs at the receiver
        # frame and unblocks the productive registry's pool. Empty cache (just
        # after restart) falls through to DB lookup below.
        if self._local_agent_dids and receiver_did not in self._local_agent_dids:
            return

        # 1. Verify the receiver agent exists locally FIRST. Only the
        #    registry that owns the recipient should handle the credit;
        #    every other registry on this frame's EventStore subscription
        #    fan-out (mainframe + N operators) sees this same event and
        #    must skip silently. No DB write yet — keeps non-recipient
        #    registries clean of orphan rows.
        async with get_db_context() as db:
            agent = (await db.execute(
                select(models.Agent).where(models.Agent.did == receiver_did)
            )).scalar_one_or_none()
        if agent is None:
            logger.debug(
                f"[Reactor:{self.name}] Receiver did={receiver_did} not local — skip"
            )
            return

        # 1b. D6-801: no credit from a peer this registry holds in quarantine (the event names only the sender's trust
        #     domain), and never a credit of a transfer this registry refused. A compliance state that cannot be read
        #     raises here: nothing is credited, and the event is handled again later.
        async with get_db_context() as db:
            prior = await db.get(models.CrossFrameTransferInbound, transfer_id)
            if prior is not None and prior.status == "refused":
                logger.info(
                    f"[Reactor:{self.name}] transfer_id={transfer_id} was refused here earlier — not credited"
                )
                return
            quarantined = await self._source_quarantine(db, source_frame)
        if quarantined is not None:
            q_name, q_state = quarantined
            async with get_db_context() as db:
                await db.execute(
                    pg_insert(models.CrossFrameTransferInbound)
                    .values(
                        id=transfer_id,
                        sender_did=sender_did,
                        receiver_did=receiver_did,
                        source_frame=source_frame,
                        amount=amount,
                        status="refused",
                        idempotency_key=idem_key,
                    )
                    .on_conflict_do_nothing(index_elements=["id"])
                )
                await db.commit()
            logger.warning(
                f"[Reactor:{self.name}] REFUSED inbound credit transfer_id={transfer_id} amount={amount} "
                f"from {source_frame} to {receiver_did}: registry {q_name} of that trust domain is {q_state} on this "
                f"registry. Nothing credited, no Settled sent; the sender's saga refunds its sender at its timeout."
            )
            return

        # 2. Credit the recipient via the receiver TEG. The TEG endpoint is
        #    idempotent on transfer_id and emits TokensTransferred via the
        #    existing transfer_service_enhanced monkey-patch path.
        #
        # Vector B (2026-05-04): when REACTOR_CREDIT_ASYNC_BULK_ENABLED=true the
        # _CreditAsyncBulkProxy batches N events into one POST to
        # /credit-async-bulk; otherwise we fall through to the legacy
        # per-event single-call path below.
        proxy = await _get_proxy()
        if proxy is not None:
            try:
                await proxy.submit({
                    "transfer_id": transfer_id,
                    "sender_did": sender_did,
                    "receiver_did": receiver_did,
                    "source_frame": source_frame,
                    "amount": str(amount),
                    "idempotency_key": idem_key,
                })
            except Exception as e:
                logger.warning(
                    f"[Reactor:{self.name}] bulk credit-async failed for "
                    f"transfer_id={transfer_id}: {e}. Sender saga will refund at timeout."
                )
                raise  # reactor framework counts as error; saga backstops at deadline
        else:
            teg_url = os.getenv("TEG_API_BASE_URL", "http://teg-layer:8080")
            teg_key = os.getenv("TEG_ADMIN_API_KEY", "")
            try:
                async with httpx.AsyncClient(timeout=10.0, verify=get_httpx_verify()) as client:
                    resp = await client.post(
                        f"{teg_url}/api/v1/cross-teg/credit-async",
                        json={
                            "transfer_id": transfer_id,
                            "sender_did": sender_did,
                            "receiver_did": receiver_did,
                            "source_frame": source_frame,
                            "amount": str(amount),
                            "idempotency_key": idem_key,
                        },
                        headers={"Authorization": f"Bearer {teg_key}"},
                    )
            except Exception as e:
                logger.warning(
                    f"[Reactor:{self.name}] TEG credit-async failed for "
                    f"transfer_id={transfer_id}: {e}. Sender saga will refund at timeout."
                )
                raise  # re-raise so reactor framework counts as error + retries on next replay

            if resp.status_code not in (200, 201):
                logger.warning(
                    f"[Reactor:{self.name}] TEG credit-async returned {resp.status_code} "
                    f"for transfer_id={transfer_id}: {resp.text[:200]}"
                )
                raise RuntimeError(
                    f"TEG credit-async non-2xx: {resp.status_code}"
                )

        # 3. Record the inbound row AFTER the TEG credit succeeded. ON
        #    CONFLICT absorbs replays (TEG was already idempotent above).
        async with get_db_context() as db:
            stmt = (
                pg_insert(models.CrossFrameTransferInbound)
                .values(
                    id=transfer_id,
                    sender_did=sender_did,
                    receiver_did=receiver_did,
                    source_frame=source_frame,
                    amount=amount,
                    status="credited",
                    idempotency_key=idem_key,
                )
                .on_conflict_do_nothing(index_elements=["id"])
            )
            await db.execute(stmt)
            await db.commit()

        # 4. Emit CrossFrameTransferSettled — propagates back to sender frame
        #    via SF-4 → Pub/Sub bridge → sender's reactor_cross_frame_settled.
        #
        # 2026-05-16: Propagate `memo` from the source Initiated event. The
        # canary validator uses memo as a fallback to resolve test_id when
        # the canary_xfer:<transfer_id> reverse-index hasn't been written yet
        # (race: Settled can land on the validator BEFORE canary_runner gets
        # the HTTP response and writes the reverse-index). The Initiated emit
        # already carries memo for the same reason; symmetric here closes the
        # last hole that caused false-positive canary failures on fast-emit
        # paths like paris→registry-a:intra. Reactor_canary_validator's
        # _extract_memo + canary- prefix check resolves test_id transparently
        # when memo flows through.
        source_memo = event_data.get("memo")
        emitter = get_event_emitter()
        if emitter is not None:
            await emitter.emit(
                event_type="CrossFrameTransferSettled",
                aggregate_id=sender_did,
                aggregate_type="Transfer",
                data={
                    "transfer_id": transfer_id,
                    # §PlanB-②: carry transaction_id == transfer_id so the receiver's
                    # cross_teg_receive leg (PK=transfer_id) resolves in
                    # getTegTransactionDetail. The async receiver frame has no local
                    # TokensTransferred (the credit comes via the bridged sender event),
                    # so this audit event is the receive leg's by-transaction anchor.
                    # Δ-neutral: CrossFrameTransferSettled is skip_in_projection / has no
                    # balance branch in the projection.
                    "transaction_id": transfer_id,
                    "sender_did": sender_did,
                    "receiver_did": receiver_did,
                    "source_frame": source_frame,
                    "target_frame": local_frame,
                    "amount": str(amount),
                    "memo": source_memo,
                },
                idempotency_key=f"settled-{transfer_id}",
            )

        logger.info(
            f"[Reactor:{self.name}] Credited transfer_id={transfer_id} "
            f"{sender_did[-12:]} → {receiver_did[-12:]} amount={amount} "
            f"frame={source_frame}→{local_frame}"
        )


# ----------------------------------------------------------------------- module API

_instance: Optional[CrossFrameInitiatedReactor] = None


async def start() -> None:
    global _instance
    if _instance is None:
        _instance = CrossFrameInitiatedReactor()
    await _instance.start()


async def stop() -> None:
    global _instance, _proxy
    if _instance is not None:
        await _instance.stop()
        _instance = None
    if _proxy is not None:
        await _proxy.stop()
        _proxy = None
