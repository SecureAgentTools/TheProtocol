"""TEG Stream Proxy — cross-worker shared-buffer batching for /teg/transfer.

Replaces the in-memory per-worker `TEGBulkProxy` with a Redis-Streams +
Pub/Sub fanout pattern that lets all uvicorn workers feed a single
buffer drained by one leader-elected flusher per operator.

Architecture:
    Worker.submit()  → XADD tp:txq:<reg>
                              ↓
                   [Single Leader-Elected Flusher]
                    XREADGROUP COUNT=200 BLOCK=100ms
                    POST /api/v1/token/transfer/bulk
                    PUBLISH tp:txres:<reg>:<reply_to> {req_id, result}
                    XACK
                              ↓
                    Worker.subscriber resolves _pending[req_id] Future.

Backwards compatible: enabled with TEG_BULK_PROXY_BACKEND=stream. When
the env var is unset (or set to anything else), this module's submit
path is never reached and traffic flows through the legacy
`TEGBulkProxy` (in-memory) or direct httpx path.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

import httpx
import redis.asyncio as aioredis
from ..es_ssl_helper import get_httpx_verify, spire_trust_loaded, svid_stamp

from agentvault_registry.background_tasks.leader import (
    WORKER_ID,
    get_redis,
    release_leadership,
    renew_leadership,
    try_acquire_leadership,
)
from agentvault_registry.services import teg_stream_metrics as _m

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ config

def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (ValueError, TypeError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (ValueError, TypeError):
        return default


STREAM_BATCH_CAP = _env_int("TEG_STREAM_BATCH_CAP", 200)
STREAM_BLOCK_MS = _env_int("TEG_STREAM_BLOCK_MS", 100)
STREAM_MAXLEN = _env_int("TEG_STREAM_MAXLEN", 5000)
STREAM_SETTLE_TIMEOUT_S = _env_float("TEG_STREAM_SETTLE_TIMEOUT_S", 30.0)
STREAM_DEDUP_TTL_S = _env_int("TEG_STREAM_DEDUP_TTL_S", 60)
STREAM_LEADER_RETRY_S = _env_float("TEG_STREAM_LEADER_RETRY_S", 5.0)
STREAM_RENEW_THRESHOLD_S = _env_float("TEG_STREAM_RENEW_THRESHOLD_S", 14.0)
# Linger: if first XREADGROUP returns fewer than MIN_BATCH entries, sleep
# LINGER_MS and re-read (non-blocking) to accumulate more before POSTing.
# Trades small tail latency for much better batch sizes under moderate load.
# 0 = disabled (legacy behaviour).
STREAM_LINGER_MS = _env_int("TEG_STREAM_LINGER_MS", 50)
STREAM_LINGER_MIN_BATCH = _env_int("TEG_STREAM_LINGER_MIN_BATCH", 20)

CONSUMER_GROUP = "cg-flusher"
CONSUMER_NAME = "consumer-flusher"
LEADER_LOCK = "tx_flusher"

TEG_API_BASE_URL = os.getenv("TEG_API_BASE_URL", "http://teg-layer:8080")
TEG_API_V1_PREFIX = "/api/v1"


def _registry_slug() -> str:
    return os.getenv("REGISTRY_NAME", "registry")


def _stream_key() -> str:
    return f"tp:txq:{_registry_slug()}"


def _result_channel(reply_to: str) -> str:
    return f"tp:txres:{_registry_slug()}:{reply_to}"


def _dedup_key(req_id: str) -> str:
    return f"tx_done:{req_id}"


# ----------------------------------------------------------------- errors

class StreamUnavailableError(Exception):
    """Raised when the stream backend can't take a submit, or gave no result for one.

    §REPATLANE-5 (V0606): `enqueued` says whether the transfer may be in the stream. The caller falls back to another
    backend ONLY when it is not: an entry the XADD wrote is still drained by the flusher after this worker stopped
    waiting (a timeout, a shutdown), so a fallback would send the same transfer to the TEG a second time. An XADD that
    raised a Redis error reply was refused (not enqueued); one that lost its connection may have been written."""

    def __init__(self, message: str = "", *, enqueued: bool = False):
        super().__init__(message)
        self.enqueued = enqueued


# --------------------------------------------------------- per-worker state

class _SharedState:
    """Per-worker pending-future registry shared by submit and subscriber."""

    def __init__(self) -> None:
        self._pending: Dict[str, asyncio.Future] = {}

    def add(self, req_id: str, fut: asyncio.Future) -> None:
        self._pending[req_id] = fut
        _m.set_pending_size(len(self._pending))

    def pop(self, req_id: str) -> Optional[asyncio.Future]:
        fut = self._pending.pop(req_id, None)
        _m.set_pending_size(len(self._pending))
        return fut

    def fail_all(self, exc: Exception) -> int:
        n = 0
        for _req, fut in list(self._pending.items()):
            if not fut.done():
                fut.set_exception(exc)
                n += 1
        self._pending.clear()
        _m.set_pending_size(0)
        return n

    def __len__(self) -> int:
        return len(self._pending)


_state = _SharedState()


# ---------------------------------------------------------- TEG http client

_teg_http_client: Optional[httpx.AsyncClient] = None
_teg_http_client_stamp: tuple = ()


def _get_teg_client() -> httpx.AsyncClient:
    # Mirrors the mtime self-healing pattern in es_ssl_helper.get_es_ssl_context().
    # The helper rebuilds _CACHED_CTX when the SPIRE SVID rotates, but a long-lived
    # httpx.AsyncClient binds its context at construction — so without this check
    # the cached client keeps presenting the original cert until the worker dies
    # (frame-b-registry: 3h51m after start vs nginx-teg sidecar's ssl_verify_client on).
    # §SVIDRACE (V0639): keyed on the cert, the key and the bundle, and recorded only for a SPIRE context (the rule of
    # routers/teg_integration._get_teg_client).
    global _teg_http_client, _teg_http_client_stamp
    stamp = svid_stamp()

    rotated = (
        bool(stamp)
        and stamp != _teg_http_client_stamp
        and _teg_http_client is not None
    )
    if rotated:
        try:
            asyncio.get_running_loop().create_task(_teg_http_client.aclose())
        except RuntimeError:
            pass
        _teg_http_client = None

    if _teg_http_client is None or _teg_http_client.is_closed:
        verify = get_httpx_verify()
        _teg_http_client = httpx.AsyncClient(
            limits=httpx.Limits(max_connections=200, max_keepalive_connections=50),
            timeout=httpx.Timeout(30.0, connect=5.0),
            verify=verify,
        )
        _teg_http_client_stamp = stamp if spire_trust_loaded(verify, stamp) else ()
    return _teg_http_client


def _admin_key() -> str:
    return os.getenv("TEG_ADMIN_API_KEY", "")


# ---------------------------------------------------------- TEGStreamProxy

class TEGStreamProxy:
    """Submit a transfer, await its result via Pub/Sub fanout."""

    def __init__(self) -> None:
        self._started = False

    async def start(self) -> None:
        r = await get_redis()
        if r is None:
            logger.warning("[TEGStreamProxy] Redis unavailable on start — submit() will degrade")
            return
        stream_key = _stream_key()
        try:
            await r.xgroup_create(stream_key, CONSUMER_GROUP, id="$", mkstream=True)
            logger.info(
                "[TEGStreamProxy] Created consumer group '%s' on %s",
                CONSUMER_GROUP, stream_key,
            )
        except aioredis.ResponseError as e:
            if "BUSYGROUP" in str(e):
                logger.info(
                    "[TEGStreamProxy] Consumer group '%s' already exists on %s",
                    CONSUMER_GROUP, stream_key,
                )
            else:
                raise
        self._started = True

    async def stop(self) -> None:
        n = _state.fail_all(StreamUnavailableError("Stream proxy stopping", enqueued=True))
        if n:
            logger.warning("[TEGStreamProxy] Cancelled %d in-flight submits on shutdown", n)
        self._started = False

    async def submit(
        self,
        sender_did: str,
        receiver_did: str,
        amount: str,
        fee_amount: str,
        message: Optional[str],
        teg_token: str,  # interface parity; unused (admin key used)
    ) -> dict:
        r = await get_redis()
        if r is None or not self._started:
            _m.inc_submit("redis_unavailable")
            raise StreamUnavailableError("Redis or stream proxy not available")

        req_id = uuid.uuid4().hex
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        _state.add(req_id, fut)

        payload: Dict[str, str] = {
            "req_id": req_id,
            "reply_to": WORKER_ID,
            "submitted_ms": str(int(time.time() * 1000)),
            "sender_did": sender_did,
            "receiver_did": receiver_did,
            "amount": str(amount),
            "fee_amount": str(fee_amount or "0"),
            "message": message or "",
        }

        t0 = time.monotonic()
        try:
            try:
                await r.xadd(_stream_key(), payload, maxlen=STREAM_MAXLEN, approximate=True)
            except Exception as e:
                _state.pop(req_id)
                _m.inc_submit("error")
                raise StreamUnavailableError(
                    f"XADD failed: {e}", enqueued=not isinstance(e, aioredis.ResponseError)) from e

            _m.inc_submit("enqueued")

            try:
                return await asyncio.wait_for(fut, timeout=STREAM_SETTLE_TIMEOUT_S)
            except asyncio.TimeoutError as e:
                _state.pop(req_id)
                _m.inc_submit("timeout")
                raise StreamUnavailableError(
                    f"No result within {STREAM_SETTLE_TIMEOUT_S}s (req_id={req_id})", enqueued=True
                ) from e
        finally:
            _m.observe_request_duration(time.monotonic() - t0)


# ------------------------------------------------------- TEGStreamSubscriber

class TEGStreamSubscriber:
    """Long-lived Pub/Sub consumer: subscribes once, resolves Futures on message."""

    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info(
            "[TEGStreamSubscriber] Started, channel=%s",
            _result_channel(WORKER_ID),
        )

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("[TEGStreamSubscriber] Stopped")

    async def _loop(self) -> None:
        from agentvault_registry.services.pubsub_backoff import jittered
        backoff = 0.5
        channel = _result_channel(WORKER_ID)
        while self._running:
            pubsub = None
            try:
                r = await get_redis()
                if r is None:
                    await asyncio.sleep(jittered(backoff))
                    backoff = min(backoff * 2, 30.0)
                    continue
                pubsub = r.pubsub()
                await pubsub.subscribe(channel)
                logger.info(
                    "[TEGStreamSubscriber] Subscribed channel=%s worker=%s",
                    channel, WORKER_ID,
                )
                backoff = 0.5
                async for msg in pubsub.listen():
                    if not self._running:
                        break
                    if msg.get("type") != "message":
                        continue
                    self._handle_message(msg.get("data"))
            except asyncio.CancelledError:
                raise
            except Exception as e:
                # Jittered: 38 workers x 16 registries used to retry on the same tick and
                # re-create the very outage they were recovering from.
                wait = jittered(backoff)
                logger.warning(
                    "[TEGStreamSubscriber] reconnect after error: %s (waiting %.2fs, ceiling %.1fs)",
                    e, wait, backoff,
                )
                await asyncio.sleep(wait)
                backoff = min(backoff * 2, 30.0)
            finally:
                if pubsub is not None:
                    try:
                        await pubsub.unsubscribe(channel)
                        await pubsub.close()
                    except Exception:
                        pass

    def _handle_message(self, raw: Any) -> None:
        try:
            if isinstance(raw, (bytes, bytearray)):
                raw = raw.decode("utf-8", errors="replace")
            payload = json.loads(raw) if isinstance(raw, str) else raw
            if not isinstance(payload, dict):
                _m.inc_pubsub_resolved("parse_error")
                return
            req_id = payload.get("req_id")
            if not req_id:
                _m.inc_pubsub_resolved("parse_error")
                return
            fut = _state.pop(req_id)
            if fut is None or fut.done():
                _m.inc_pubsub_resolved("no_pending")
                return
            if payload.get("ok"):
                fut.set_result(payload.get("result", {}))
            else:
                fut.set_exception(ValueError(payload.get("error", "Transfer failed via stream")))
            _m.inc_pubsub_resolved("resolved")
        except Exception as e:
            logger.debug("[TEGStreamSubscriber] handle_message error: %s", e)
            _m.inc_pubsub_resolved("parse_error")


# ---------------------------------------------------------- TEGStreamFlusher

class TEGStreamFlusher:
    """Leader-elected: drains the stream, POSTs bulk to TEG, fans results back."""

    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._outer_loop())
        logger.info("[TEGStreamFlusher] Started (leader-elected)")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        try:
            await release_leadership(LEADER_LOCK)
        except Exception:
            pass
        logger.info("[TEGStreamFlusher] Stopped")

    async def _outer_loop(self) -> None:
        from agentvault_registry.background_tasks import vitals as _vitals
        await _vitals.register(LEADER_LOCK, module=__name__, pattern="subscriber",
                               interval_sec=STREAM_RENEW_THRESHOLD_S, enabled=True)
        while self._running:
            try:
                if await try_acquire_leadership(LEADER_LOCK):
                    await self._inner_loop()
                else:
                    await asyncio.sleep(STREAM_LEADER_RETRY_S)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning("[TEGStreamFlusher] outer loop error: %s", e)
                await asyncio.sleep(1.0)

    async def _inner_loop(self) -> None:
        # §VITALS: a stream flusher holds its lease for as long as it is leader, so
        # the renewal is the heartbeat — see recent_events_ring for the same reasoning.
        from agentvault_registry.background_tasks import vitals as _vitals
        last_renew = time.monotonic()
        last_xlen_sample = 0.0

        # Reclaim PEL entries from any prior leader before reading new ones.
        await self._drain_pel()

        while self._running:
            r = await get_redis()
            if r is None:
                await asyncio.sleep(1.0)
                continue
            stream_key = _stream_key()

            now = time.monotonic()
            if now - last_renew >= STREAM_RENEW_THRESHOLD_S:
                if not await renew_leadership(LEADER_LOCK):
                    # Orderly handover, not a failure.
                    logger.info("[TEGStreamFlusher] lost leadership, returning to outer loop")
                    return
                last_renew = now
                await _vitals.stamp(LEADER_LOCK, _vitals.OUTCOME_OK,
                                    stats={"state": "streaming"})

            if now - last_xlen_sample > 1.0:
                try:
                    _m.set_xlen(await r.xlen(stream_key))
                except Exception:
                    pass
                last_xlen_sample = now

            try:
                resp = await r.xreadgroup(
                    CONSUMER_GROUP,
                    CONSUMER_NAME,
                    {stream_key: ">"},
                    count=STREAM_BATCH_CAP,
                    block=STREAM_BLOCK_MS,
                )
            except Exception as e:
                logger.warning("[TEGStreamFlusher] XREADGROUP error: %s", e)
                await asyncio.sleep(0.5)
                continue

            if not resp:
                continue

            entries: List[Tuple[Any, dict]] = []
            for _stream_name, msgs in resp:
                for entry_id, fields in msgs:
                    entries.append((entry_id, fields))

            # Linger: if the first read returned a small batch, wait briefly
            # and re-read non-blocking to accumulate more before POSTing. The
            # XREADGROUP under-load returns immediately with whatever is
            # currently in the stream, so without linger we ship tiny batches
            # at moderate arrival rates. Trades up to LINGER_MS of tail
            # latency for batch sizes up to the cap.
            if (
                STREAM_LINGER_MS > 0
                and 0 < len(entries) < STREAM_LINGER_MIN_BATCH
                and len(entries) < STREAM_BATCH_CAP
            ):
                await asyncio.sleep(STREAM_LINGER_MS / 1000.0)
                try:
                    resp2 = await r.xreadgroup(
                        CONSUMER_GROUP,
                        CONSUMER_NAME,
                        {stream_key: ">"},
                        count=STREAM_BATCH_CAP - len(entries),
                        block=0,  # immediate, don't wait again
                    )
                    for _stream_name, msgs in resp2 or []:
                        for entry_id, fields in msgs:
                            entries.append((entry_id, fields))
                except Exception as e:
                    logger.debug("[TEGStreamFlusher] linger XREADGROUP error: %s", e)

            if entries:
                await self._process_batch(entries, r)

    async def _drain_pel(self) -> None:
        r = await get_redis()
        if r is None:
            return
        stream_key = _stream_key()
        while self._running:
            try:
                resp = await r.xreadgroup(
                    CONSUMER_GROUP,
                    CONSUMER_NAME,
                    {stream_key: "0"},
                    count=STREAM_BATCH_CAP,
                )
            except Exception as e:
                logger.warning("[TEGStreamFlusher] PEL drain XREADGROUP error: %s", e)
                return
            if not resp:
                return
            entries: List[Tuple[Any, dict]] = []
            for _stream_name, msgs in resp:
                for entry_id, fields in msgs:
                    entries.append((entry_id, fields))
            if not entries:
                return
            logger.info(
                "[TEGStreamFlusher] Reclaimed %d PEL entries on leader-acquire",
                len(entries),
            )
            await self._process_batch(entries, r)

    async def _process_batch(
        self, entries: List[Tuple[Any, dict]], r: aioredis.Redis
    ) -> None:
        t0 = time.monotonic()

        # Per-entry dedup via SET NX tx_done:<req_id>; lets us reclaim PEL safely.
        to_process: List[Tuple[Any, Dict[str, str]]] = []
        already_done_ids: List[Any] = []
        for entry_id, fields in entries:
            f = _decode_fields(fields)
            req_id = f.get("req_id", "")
            if not req_id:
                already_done_ids.append(entry_id)
                continue
            try:
                won = await r.set(_dedup_key(req_id), "1", nx=True, ex=STREAM_DEDUP_TTL_S)
            except Exception:
                won = True  # fail-open: better dup than drop
            if won:
                to_process.append((entry_id, f))
            else:
                already_done_ids.append(entry_id)

        stream_key = _stream_key()
        if already_done_ids:
            await self._xack_all(stream_key, already_done_ids, r)

        if not to_process:
            return

        transfers = []
        for _eid, f in to_process:
            entry: Dict[str, Any] = {
                "sender_agent_id": f.get("sender_did", ""),
                "receiver_agent_id": f.get("receiver_did", ""),
                "amount": f.get("amount", "0"),
            }
            fee = f.get("fee_amount", "0")
            if fee and fee != "0":
                entry["fee_amount"] = fee
            msg = f.get("message", "")
            if msg:
                entry["message"] = msg
            transfers.append(entry)

        client = _get_teg_client()
        try:
            response = await client.post(
                f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}/token/transfer/bulk",
                json={"transfers": transfers},
                headers={"Authorization": f"Bearer {_admin_key()}"},
                timeout=30.0,
            )
        except Exception as exc:
            logger.error("[TEGStreamFlusher] TEG bulk POST exception: %s", exc)
            await self._publish_failure_for_all(to_process, str(exc), r)
            await self._xack_all(stream_key, [eid for eid, _ in to_process], r)
            _m.inc_flush("exception")
            _m.observe_flush_size(len(to_process))
            _m.observe_flush_duration(time.monotonic() - t0)
            return

        if response.status_code != 200:
            err = f"TEG bulk returned {response.status_code}: {response.text[:200]}"
            logger.error("[TEGStreamFlusher] %s", err)
            await self._publish_failure_for_all(to_process, err, r)
            await self._xack_all(stream_key, [eid for eid, _ in to_process], r)
            _m.inc_flush("teg_5xx")
            _m.observe_flush_size(len(to_process))
            _m.observe_flush_duration(time.monotonic() - t0)
            return

        try:
            data = response.json()
        except Exception as exc:
            logger.error("[TEGStreamFlusher] TEG bulk JSON decode failed: %s", exc)
            await self._publish_failure_for_all(to_process, "Bad TEG response", r)
            await self._xack_all(stream_key, [eid for eid, _ in to_process], r)
            _m.inc_flush("exception")
            _m.observe_flush_size(len(to_process))
            _m.observe_flush_duration(time.monotonic() - t0)
            return

        results = data.get("results", []) or []

        for i, (entry_id, f) in enumerate(to_process):
            req_id = f.get("req_id", "")
            reply_to = f.get("reply_to", "")
            if i < len(results):
                result = results[i]
                if result.get("status") == "completed":
                    await self._publish(
                        _result_channel(reply_to),
                        {"req_id": req_id, "ok": True, "result": result},
                        r,
                    )
                    self._emit_events_safe(f, result)
                else:
                    err = result.get("error") or "Transfer failed in bulk"
                    await self._publish(
                        _result_channel(reply_to),
                        {"req_id": req_id, "ok": False, "error": err},
                        r,
                    )
            else:
                await self._publish(
                    _result_channel(reply_to),
                    {"req_id": req_id, "ok": False, "error": "No result returned from TEG"},
                    r,
                )

        await self._xack_all(stream_key, [eid for eid, _ in to_process], r)

        elapsed = time.monotonic() - t0
        _m.inc_flush("ok")
        _m.observe_flush_size(len(to_process))
        _m.observe_flush_duration(elapsed)
        logger.info(
            "[TEGStreamFlusher] flushed batch=%d in %.0fms",
            len(to_process), elapsed * 1000,
        )

    async def _publish(self, channel: str, payload: dict, r: aioredis.Redis) -> None:
        try:
            await r.publish(channel, json.dumps(payload))
        except Exception as e:
            logger.debug("[TEGStreamFlusher] publish error on %s: %s", channel, e)

    async def _publish_failure_for_all(
        self, entries: List[Tuple[Any, Dict[str, str]]], err: str, r: aioredis.Redis,
    ) -> None:
        for _eid, f in entries:
            await self._publish(
                _result_channel(f.get("reply_to", "")),
                {"req_id": f.get("req_id", ""), "ok": False, "error": err},
                r,
            )

    async def _xack_all(
        self, stream_key: str, ids: List[Any], r: aioredis.Redis,
    ) -> None:
        if not ids:
            return
        try:
            await r.xack(stream_key, CONSUMER_GROUP, *ids)
        except Exception as e:
            logger.debug("[TEGStreamFlusher] xack error: %s", e)

    def _emit_events_safe(self, fields: Dict[str, str], result: dict) -> None:
        """Mirror of TEGBulkProxy._flush event emission — keeps audit parity."""
        try:
            from agentvault_registry.event_emitter import get_event_emitter

            emitter = get_event_emitter()
            if not emitter:
                return
            tx_id = result.get("transaction_id", "")
            sender_did = fields.get("sender_did", "")
            receiver_did = fields.get("receiver_did", "")
            amount = fields.get("amount", "0")
            message = fields.get("message", "")
            fee_amount = fields.get("fee_amount", "0")

            emitter.emit_background(
                event_type="TokensTransferred",
                aggregate_id=sender_did,
                data={
                    "from": sender_did,
                    "to": receiver_did,
                    "amount": amount,
                    "transaction_id": tx_id,
                    "memo": message or "",
                },
                idempotency_key=f"xfer-{tx_id}" if tx_id else None,
            )

            try:
                fee_dec = Decimal(str(fee_amount or "0"))
            except (InvalidOperation, ValueError, TypeError):
                fee_dec = Decimal("0")
            if fee_dec > Decimal("0"):
                emitter.emit_background(
                    event_type="TransactionFeeCollected",
                    aggregate_id=sender_did,
                    data={
                        "agent_did": sender_did,
                        "fee_amount": str(fee_amount),
                        "transaction_id": tx_id,
                        "transfer_amount": amount,
                        "rate_pct": 0.0,
                    },
                    idempotency_key=f"fee-{tx_id}" if tx_id else None,
                )
        except Exception as exc:  # noqa: BLE001
            # §SILENT (2026-09-14): the emits above are fire-and-forget (their own failures are reported
            # by the emitter's background wrapper); what this handler catches is a scheduling failure,
            # and a transfer whose ledger events were never even scheduled is the one Δ cannot see.
            logger.error("[EMIT-LOST] TEGStreamFlusher could not schedule the ledger events for tx=%s: %s",
                         result.get("transaction_id", "?") if isinstance(result, dict) else "?", exc)


# ----------------------------------------------------------------- helpers

def _decode_fields(fields: Any) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not isinstance(fields, dict):
        return out
    for k, v in fields.items():
        if isinstance(k, (bytes, bytearray)):
            k = k.decode("utf-8", errors="replace")
        if isinstance(v, (bytes, bytearray)):
            v = v.decode("utf-8", errors="replace")
        out[str(k)] = "" if v is None else str(v)
    return out


# ------------------------------------------------------------- singletons

_proxy: Optional[TEGStreamProxy] = None
_subscriber: Optional[TEGStreamSubscriber] = None
_flusher: Optional[TEGStreamFlusher] = None


def get_teg_stream_proxy() -> Optional[TEGStreamProxy]:
    return _proxy


async def start_teg_stream_proxy() -> None:
    """Start the stream proxy stack if TEG_BULK_PROXY_BACKEND=stream."""
    global _proxy, _subscriber, _flusher
    backend = (os.getenv("TEG_BULK_PROXY_BACKEND", "") or "").strip().lower()
    if backend != "stream":
        logger.info(
            "[TEGStreamProxy] Disabled (TEG_BULK_PROXY_BACKEND=%s)",
            backend or "unset",
        )
        return
    if _proxy is not None:
        return
    _proxy = TEGStreamProxy()
    await _proxy.start()
    _subscriber = TEGStreamSubscriber()
    await _subscriber.start()
    _flusher = TEGStreamFlusher()
    await _flusher.start()
    logger.info(
        "[TEGStreamProxy] Started (cap=%d block_ms=%d maxlen=%d settle_to=%.1fs)",
        STREAM_BATCH_CAP, STREAM_BLOCK_MS, STREAM_MAXLEN, STREAM_SETTLE_TIMEOUT_S,
    )


async def stop_teg_stream_proxy() -> None:
    global _proxy, _subscriber, _flusher
    if _flusher is not None:
        await _flusher.stop()
        _flusher = None
    if _subscriber is not None:
        await _subscriber.stop()
        _subscriber = None
    if _proxy is not None:
        await _proxy.stop()
        _proxy = None
