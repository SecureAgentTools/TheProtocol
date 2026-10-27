"""
TITANIUM VAULT D3: Background task for settlement saga timeout detection.

Runs every 5 minutes. Finds cross-registry settlements that have exceeded
the 72-hour saga deadline and triggers compensating events (timeout + rollback).

Also sweeps async cross-frame transfers (TEG_CROSS_FRAME_BACKEND=async,
2026-05-03): locked rows past their 5-min timeout get refunded via TEG +
emit CrossFrameTransferRefunded as a compensating event.

Uses the same async db context pattern as staking_distributor.py.
"""
import asyncio
import datetime
import logging
import os
import time
import uuid
from decimal import Decimal
from typing import Any, Dict, Optional

import httpx
from ..es_ssl_helper import get_httpx_verify
from sqlalchemy import select, update, and_

from .. import models
from ..database import get_db_context
from ..event_emitter import get_event_emitter
from ..services.settlement_saga import get_settlement_saga
from ._worker_base import BackgroundWorker

logger = logging.getLogger(__name__)


def _refund_txid(transfer_id: str) -> str:
    """§PlanB-②: deterministic, collision-free refund-leg id (distinct from
    transfer_id — the SEND leg holds that on this same TEG). Used as BOTH the
    refund leg's transaction_id (via /refund-async) AND the refund
    TokensTransferred.data.transaction_id, so the listed refund leg resolves
    in getTegTransactionDetail."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"theprotocol:cross_frame_refund:{transfer_id}"))


# §pass27 Phase 3 — Prometheus metrics (lazy, best-effort).
try:
    from prometheus_client import Counter as _SCounter, Gauge as _SGauge

    SAGA_CYCLE_TOTAL = _SCounter(
        "saga_timeout_checker_cycle_total",
        "Saga-timeout-checker cycles run (leader only)",
        labelnames=["registry_id", "cycle_kind"],
    )
    SAGA_SETTLEMENT_TIMED_OUT_TOTAL = _SCounter(
        "saga_settlement_timed_out_total",
        "Settlements past 72h deadline timed out by the saga checker",
        labelnames=["registry_id"],
    )
    SAGA_CROSS_FRAME_REFUNDED_TOTAL = _SCounter(
        "saga_cross_frame_refunded_total",
        "Cross-frame transfers refunded via the saga sweep",
        labelnames=["registry_id", "source_frame", "target_frame"],
    )
    SAGA_PENDING_TIMEOUTS = _SGauge(
        "saga_pending_timeouts",
        "Current backlog of rows past deadline awaiting sweep",
        labelnames=["registry_id", "cycle_kind"],
        multiprocess_mode="max",
    )
    SAGA_TIMEOUT_CHECKER_ERRORS_TOTAL = _SCounter(
        "saga_timeout_checker_errors_total",
        "Errors during a saga-timeout cycle",
        labelnames=["registry_id", "cycle_kind", "reason"],
    )
    SAGA_CROSS_FRAME_REFUND_DEFERRED_TOTAL = _SCounter(
        "saga_cross_frame_refund_deferred_total",
        "Timed-out cross-frame transfers not refunded in a cycle because the pre-refund settled scan could not read the "
        "EventStore (they stay locked and the next cycle asks again)",
        labelnames=["registry_id"],
    )
except Exception:  # pragma: no cover
    SAGA_CYCLE_TOTAL = None
    SAGA_SETTLEMENT_TIMED_OUT_TOTAL = None
    SAGA_CROSS_FRAME_REFUNDED_TOTAL = None
    SAGA_PENDING_TIMEOUTS = None
    SAGA_TIMEOUT_CHECKER_ERRORS_TOTAL = None
    SAGA_CROSS_FRAME_REFUND_DEFERRED_TOTAL = None


_REGISTRY_ID_LABEL = os.getenv("REGISTRY_NAME", "registry-a")


async def _emit_settlement_saga_timed_out(timed_out_ids: list) -> None:
    """Audit emit for the settlement-saga path's new event type."""
    try:
        emitter = get_event_emitter()
        if emitter is None:
            return
        local_frame = os.environ.get("SPIRE_TRUST_DOMAIN", "agentvault.com")
        for sid in timed_out_ids:
            await emitter.emit(
                event_type="SettlementSagaTimedOut",
                aggregate_id=str(sid),
                aggregate_type="Settlement",
                idempotency_key=f"saga-timeout-{sid}",
                data={
                    "settlement_id": str(sid),
                    "registry_id": _REGISTRY_ID_LABEL,
                    "source_frame": local_frame,
                    "detected_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                },
            )
    except Exception as e:  # noqa: BLE001
        # §S4 pass 3 (2026-09-05): this was logger.debug - a lost audit event was invisible everywhere.
        # The timeout itself already committed; the ledger not hearing about it is a WARNING and a
        # counted reason, never a silent debug line.
        logger.warning(f"[SagaTimeout] settlement audit emit failed for {sid}: {e.__class__.__name__}: {e}")
        if SAGA_TIMEOUT_CHECKER_ERRORS_TOTAL is not None:
            try:
                SAGA_TIMEOUT_CHECKER_ERRORS_TOTAL.labels(
                    registry_id=_REGISTRY_ID_LABEL, cycle_kind="settlement", reason="audit_emit_failed",
                ).inc()
            except Exception:  # noqa: BLE001
                pass


# Most recent cycle stats — populated by the loop, read by snapshot().
_LAST_CYCLE_STATS: Dict[str, Any] = {
    "settlements_timed_out": 0,
    "cross_frame_refunded": 0,
    "cross_frame_refund_deferred": 0,
    "cross_frame_pending": 0,
    "errors": 0,
    "last_settlement_cycle_iso": None,
    "last_cross_frame_cycle_iso": None,
}

# Check interval: every 5 minutes (settlement saga); cross-frame sweep is
# bundled into the same cycle but works on a 5-min row deadline.
CHECK_INTERVAL_SECONDS = 300

# Async cross-frame: lighter-weight cycle for snappier refunds. Triggers
# inside the same loop but the cross-frame deadline is the row's timeout_at,
# so an inner 60s tick is fine — saga still leader-elected.
CROSS_FRAME_CHECK_INTERVAL_SECONDS = 60


class SagaTimeoutChecker(BackgroundWorker):
    """Saga + cross-frame timeout checker (§pass27 Phase 3: BackgroundWorker).

    Dual cadence:
      - Cross-frame sweep on every cycle (interval_sec = 60s).
      - Settlement-saga timeout check every Nth cycle (N = 5min / 60s = 5).

    Runs on BOTH registry-a and frame-b-registry (no env flag — default-on).
    """

    worker_id = "saga_timeout_checker"
    leader_key = "saga_timeout_checker"
    interval_sec = CROSS_FRAME_CHECK_INTERVAL_SECONDS
    cold_start_delay_sec = 5

    def __init__(self) -> None:
        super().__init__()
        self._ticks = 0
        self._ticks_per_saga_run = max(
            1, CHECK_INTERVAL_SECONDS // CROSS_FRAME_CHECK_INTERVAL_SECONDS
        )

    async def _cycle_once(self) -> None:
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # Cross-frame sweep — always on inner tick.
        cf_refunded = 0
        try:
            refunded = await check_cross_frame_timeouts()
            cf_refunded = len(refunded or [])
            _LAST_CYCLE_STATS["cross_frame_refunded"] = cf_refunded
            _LAST_CYCLE_STATS["last_cross_frame_cycle_iso"] = now_iso
            if SAGA_CYCLE_TOTAL is not None:
                try:
                    SAGA_CYCLE_TOTAL.labels(
                        registry_id=_REGISTRY_ID_LABEL, cycle_kind="cross_frame"
                    ).inc()
                except Exception:
                    pass
        except Exception as e:  # noqa: BLE001
            logger.error(f"[SagaTimeout] cross-frame sweep error: {e}", exc_info=True)
            _LAST_CYCLE_STATS["errors"] = _LAST_CYCLE_STATS.get("errors", 0) + 1
            if SAGA_TIMEOUT_CHECKER_ERRORS_TOTAL is not None:
                try:
                    SAGA_TIMEOUT_CHECKER_ERRORS_TOTAL.labels(
                        registry_id=_REGISTRY_ID_LABEL,
                        cycle_kind="cross_frame",
                        reason="exception",
                    ).inc()
                except Exception:
                    pass

        # Refresh pending-cross-frame gauge from DB (cheap COUNT query).
        try:
            now = datetime.datetime.now(datetime.timezone.utc)
            async with get_db_context() as db:
                from sqlalchemy import func as _func
                cf_pending = await db.scalar(
                    select(_func.count(models.CrossFrameTransfer.id)).where(
                        models.CrossFrameTransfer.status == "locked",
                        models.CrossFrameTransfer.timeout_at < now,
                    )
                )
                _LAST_CYCLE_STATS["cross_frame_pending"] = int(cf_pending or 0)
                if SAGA_PENDING_TIMEOUTS is not None:
                    try:
                        SAGA_PENDING_TIMEOUTS.labels(
                            registry_id=_REGISTRY_ID_LABEL, cycle_kind="cross_frame"
                        ).set(int(cf_pending or 0))
                    except Exception:
                        pass
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[SagaTimeout] cross-frame pending gauge refresh failed: {e}")

        # Settlement saga path — runs every Nth tick.
        if self._ticks % self._ticks_per_saga_run == 0:
            try:
                saga = get_settlement_saga()
                async with get_db_context() as db:
                    timed_out_ids = await saga.check_timeouts(db)
                if timed_out_ids:
                    logger.warning(
                        f"[SagaTimeout] {len(timed_out_ids)} settlements "
                        f"timed out: {timed_out_ids}"
                    )
                    if SAGA_SETTLEMENT_TIMED_OUT_TOTAL is not None:
                        try:
                            SAGA_SETTLEMENT_TIMED_OUT_TOTAL.labels(
                                registry_id=_REGISTRY_ID_LABEL
                            ).inc(len(timed_out_ids))
                        except Exception:
                            pass
                    await _emit_settlement_saga_timed_out(timed_out_ids)
                _LAST_CYCLE_STATS["settlements_timed_out"] = len(timed_out_ids or [])
                _LAST_CYCLE_STATS["last_settlement_cycle_iso"] = now_iso
                if SAGA_CYCLE_TOTAL is not None:
                    try:
                        SAGA_CYCLE_TOTAL.labels(
                            registry_id=_REGISTRY_ID_LABEL, cycle_kind="settlement"
                        ).inc()
                    except Exception:
                        pass
            except Exception as e:
                logger.error(f"[SagaTimeout] Settlement check error: {e}", exc_info=True)
                _LAST_CYCLE_STATS["errors"] = _LAST_CYCLE_STATS.get("errors", 0) + 1
                if SAGA_TIMEOUT_CHECKER_ERRORS_TOTAL is not None:
                    try:
                        SAGA_TIMEOUT_CHECKER_ERRORS_TOTAL.labels(
                            registry_id=_REGISTRY_ID_LABEL,
                            cycle_kind="settlement",
                            reason="exception",
                        ).inc()
                    except Exception:
                        pass

        self._ticks += 1
        self._stats = dict(_LAST_CYCLE_STATS)

    # Legacy API retained for any external callers (settlement_saga tests).
    async def check_once(self):
        await self._cycle_once()


# ---------------------------------------------------------------------------
# Async cross-frame transfer sweep (TEG_CROSS_FRAME_BACKEND=async, 2026-05-03)
# ---------------------------------------------------------------------------

# 2026-05-02: bounded concurrency for parallel saga refunds. Inside the
# leader-elected sweep, refunds were sequential (one TEG round-trip + DB
# update + 2 event emits per row, ~150-200ms each). At limit=100 the sweep
# took ~20s; effective drain rate ~100 rows/min/registry, leaving lock
# backlog under saturation. Parallelising via asyncio.gather + semaphore
# gives ~CONCURRENCY× speedup. Each row's UPDATE has WHERE status='locked'
# so concurrent attempts are race-safe.
_SAGA_REFUND_CONCURRENCY = int(os.environ.get("SAGA_REFUND_CONCURRENCY", "20"))
_SAGA_REFUND_BATCH = int(os.environ.get("SAGA_REFUND_BATCH", "500"))

# Vector A (2026-05-04) — adaptive saga concurrency. When enabled, the per-cycle
# semaphore size is computed from the cluster-wide Settled-event arrival rate
# (read from Redis counters set by reactor_cross_frame_settled). When credit-async
# is healthy, saga can refund faster; when starving, saga backs off automatically
# so it doesn't compete for receiver TEG workers.
_SAGA_ADAPTIVE_CONC_ENABLED = os.environ.get("SAGA_ADAPTIVE_CONC_ENABLED", "false").lower() == "true"
_SAGA_ADAPTIVE_RATE_DIVISOR = int(os.environ.get("SAGA_ADAPTIVE_RATE_DIVISOR", "30"))
_SAGA_ADAPTIVE_MIN_CONC = int(os.environ.get("SAGA_ADAPTIVE_MIN_CONC", "1"))
_SAGA_ADAPTIVE_MAX_CONC = int(os.environ.get("SAGA_ADAPTIVE_MAX_CONC", "20"))
_SAGA_ADAPTIVE_LOOKBACK_BUCKETS = int(os.environ.get("SAGA_ADAPTIVE_LOOKBACK_BUCKETS", "5"))


async def _refund_one_cross_frame_row(
    row,
    now,
    teg_base: str,
    teg_admin_key: str,
    local_trust_domain: str,
    sem: asyncio.Semaphore,
) -> Optional[str]:
    """Refund a single timed-out cross_frame_transfer row. Returns transfer_id
    on success, None on race / failure. Idempotent via WHERE status='locked'."""
    async with sem:
        try:
            # 1. Refund via local TEG (idempotent on transfer_id).
            async with httpx.AsyncClient(timeout=10.0, verify=get_httpx_verify()) as client:
                resp = await client.post(
                    f"{teg_base}/api/v1/cross-teg/refund-async",
                    json={
                        "transfer_id": row.id,
                        "sender_did": row.sender_did,
                        "amount": str(row.amount),
                        "reversal_txid": _refund_txid(row.id),  # §PlanB-②: refund leg PK (≠ transfer_id)
                    },
                    headers={"Authorization": f"Bearer {teg_admin_key}"},
                )
            if resp.status_code not in (200, 201):
                logger.warning(
                    f"[CrossFrameTimeout] TEG refund-async returned "
                    f"{resp.status_code} for transfer_id={row.id}: {resp.text[:200]}"
                )
                return None

            # 2. Mark row refunded.
            async with get_db_context() as db:
                update_result = await db.execute(
                    update(models.CrossFrameTransfer)
                    .where(
                        models.CrossFrameTransfer.id == row.id,
                        models.CrossFrameTransfer.status == "locked",
                    )
                    .values(status="refunded", refunded_at=now)
                    .returning(models.CrossFrameTransfer.id)
                )
                marked = update_result.scalar_one_or_none()
                if marked is None:
                    # Race: someone else (e.g. a slow Settled event) already
                    # cleared the row. TEG refund was idempotent so no
                    # double-credit risk; just skip emission.
                    await db.commit()
                    logger.info(
                        f"[CrossFrameTimeout] Race on transfer_id={row.id} "
                        f"(no longer locked) — skipping emit"
                    )
                    return None

                # 3. Restore sender's registry-side liquid_balance fast path.
                agent = (await db.execute(
                    select(models.Agent).where(models.Agent.did == row.sender_did)
                )).scalar_one_or_none()
                if agent is not None and agent.liquid_balance is not None:
                    agent.liquid_balance = (agent.liquid_balance or Decimal("0")) + row.amount
                await db.commit()

            # 4. Emit reverse TokensTransferred + CrossFrameTransferRefunded.
            #    Distinct idempotency_keys: when these two events emitted concurrently
            #    with the same key, the EventStore dedup dropped one. If the
            #    Refunded event was the one dropped, the receiver-frame's
            #    compensating reactor never fired and any partial credit
            #    stayed on the receiver — silent supply skew. Same fix as the
            #    initiation path: per-event-type idem-keys.
            emitter = get_event_emitter()
            if emitter is not None:
                tt_refund_idem = f"refund-{row.id}"
                refunded_idem = f"refunded-{row.id}"
                await emitter.emit(
                    event_type="TokensTransferred",
                    aggregate_id=row.sender_did,
                    aggregate_type="Transfer",
                    data={
                        "from": row.receiver_did,
                        "to": row.sender_did,
                        "amount": str(row.amount),
                        "transaction_id": _refund_txid(row.id),  # §PlanB-②: == refund leg PK (≠ transfer_id)
                        "memo": "cross_frame_async_refund",
                    },
                    idempotency_key=tt_refund_idem,
                )
                await emitter.emit(
                    event_type="CrossFrameTransferRefunded",
                    aggregate_id=row.sender_did,
                    aggregate_type="Transfer",
                    data={
                        "transfer_id": row.id,
                        "sender_did": row.sender_did,
                        "receiver_did": row.receiver_did,
                        "source_frame": local_trust_domain,
                        "target_frame": row.target_frame,
                        "amount": str(row.amount),
                        "reason": "timeout_5min_no_settled_event",
                    },
                    idempotency_key=refunded_idem,
                )

            logger.warning(
                f"[CrossFrameTimeout] REFUNDED transfer_id={row.id} "
                f"sender={row.sender_did[-12:]} amount={row.amount} "
                f"(target_frame={row.target_frame})"
            )
            if SAGA_CROSS_FRAME_REFUNDED_TOTAL is not None:
                try:
                    SAGA_CROSS_FRAME_REFUNDED_TOTAL.labels(
                        registry_id=_REGISTRY_ID_LABEL,
                        source_frame=local_trust_domain or "unknown",
                        target_frame=(row.target_frame or "unknown"),
                    ).inc()
                except Exception:
                    pass
            return row.id
        except Exception as e:
            logger.error(
                f"[CrossFrameTimeout] Failed to refund transfer_id={row.id}: {e}"
            )
            return None


async def _compute_adaptive_concurrency(local_frame: str) -> int:
    """Read last N minute-buckets of Settled rate from Redis; scale concurrency.
    Falls back to static _SAGA_REFUND_CONCURRENCY if disabled or Redis unreachable.

    Formula: target = clamp(MIN, MAX, rate_per_min // RATE_DIVISOR).
    With defaults (divisor=30, min=1, max=20): 150/min → 5, 300/min → 10, 50/min → 1.
    """
    if not _SAGA_ADAPTIVE_CONC_ENABLED:
        return _SAGA_REFUND_CONCURRENCY
    try:
        from .leader import get_redis
        r = await get_redis()
        if r is None:
            return _SAGA_REFUND_CONCURRENCY
        now_bucket = int(time.time() // 60)
        keys = [
            f"cross_frame_settled_rate:{local_frame}:{now_bucket - i}"
            for i in range(_SAGA_ADAPTIVE_LOOKBACK_BUCKETS)
        ]
        values = await r.mget(*keys)
        total = sum(int(v) for v in values if v is not None)
        rate_per_min = total / max(1, _SAGA_ADAPTIVE_LOOKBACK_BUCKETS)
        target = max(
            _SAGA_ADAPTIVE_MIN_CONC,
            min(_SAGA_ADAPTIVE_MAX_CONC, int(rate_per_min // _SAGA_ADAPTIVE_RATE_DIVISOR)),
        )
        logger.debug(
            f"[CrossFrameTimeout] adaptive_conc: rate={rate_per_min:.1f}/min "
            f"target={target} (divisor={_SAGA_ADAPTIVE_RATE_DIVISOR}, "
            f"min={_SAGA_ADAPTIVE_MIN_CONC}, max={_SAGA_ADAPTIVE_MAX_CONC})"
        )
        return target
    except Exception as e:
        logger.warning(f"[CrossFrameTimeout] adaptive_conc fallback to static: {e}")
        return _SAGA_REFUND_CONCURRENCY


async def _find_settled_transfer_ids(transfer_ids: list) -> Optional[set]:
    """AAA+ §pass33 (2026-05-17) — pre-refund safety net.

    Before refunding a batch of "timed-out" transfers, query EventStore for
    CrossFrameTransferSettled events matching any of the candidate
    transfer_ids. If found, the transfer actually settled — the local
    reactor missed the WS broadcast (typically during a registry rebuild
    when WS subscription opens AFTER Settled was emitted). The polling
    backstop SHOULD catch these but has been observed to miss bursts of
    events delivered during the reactor restart window (78 false refunds
    in 24h prior to this fix).

    Defense-in-depth: fetches from BOTH `/events/export` (local Settled
    events) and `/events/foreign` (Settled events replicated from the
    other frame via SF-4) in parallel. A transfer with Settled in either
    table is recoverable.

    Returns a set of transfer_ids that have a Settled event somewhere, or None when the store could not be read completely
    (no credential, a failed or refused read of either table). §SOVKIT-2, his decision 2026-09-14 ("3 yes"): the saga waits
    and asks again instead of refunding on a scan that could not see the store. The old answer on a failure, an empty set,
    read as "nothing settled" and refunded transfers the receiving frame may already have credited.
    """
    if not transfer_ids:
        return set()
    es_url = os.environ.get("EVENT_STORE_URL", "http://event-store:8200")
    api_key = (
        os.environ.get("EVENT_STORE_INTERNAL_API_KEY")
        or os.environ.get("EVENT_STORE_API_KEY")
        or os.environ.get("INTERNAL_API_KEY")
        or ""
    )
    federation_license = os.environ.get("FEDERATION_LICENSE_KEY", "")
    headers: Dict[str, str] = {}
    if api_key:
        headers["X-Internal-Key"] = api_key
    if federation_license:
        headers["X-Federation-License"] = federation_license

    # mTLS auth on top, for callers that have SPIRE SVIDs mounted.
    # §pass35 chose verify=True because a cloud operator's store is the LE-signed public edge
    # (events.theprotocol.cloud), where a SPIRE-bundle-only verify failed every scan and refunded
    # transfers that had settled. §SOVKIT T5 (2026-09-14): a frame's own registry reaches its store
    # through the frame's mTLS sidecar, whose server certificate is SPIRE-issued, and verify=True failed
    # THAT on every scan, with the same false refunds. es_ssl_helper's context trusts the SPIRE bundle
    # AND the system roots and carries the SVID, so both addresses verify through one value.
    cert_dir = os.environ.get("SVID_CERT_DIR", os.environ.get("CERT_DIR", "/certs"))
    has_svid = os.path.exists(os.path.join(cert_dir, "svid.0.pem")) and os.path.exists(os.path.join(cert_dir, "svid.0.key"))
    client_kwargs: Dict[str, Any] = {"timeout": 10.0, "verify": get_httpx_verify()}

    # No auth available → the check cannot run, so it decides nothing (§SOVKIT-2: the rows wait instead of being refunded).
    if not headers and not (es_url.startswith("https://") and has_svid):
        logger.warning(
            "[SagaPreRefund] No EventStore auth available (no key, and no SVID over https): the settled check cannot run; "
            f"{len(transfer_ids)} timed-out transfer(s) wait for a readable scan"
        )
        return None

    # Look back: cover the full timeout window + a buffer. Cross-frame
    # SAGA_CROSS_FRAME_TIMEOUT_MIN defaults to 15min on registry-a / 30min on
    # cloud-ops; +5min buffer is comfortable margin.
    timeout_min = int(os.environ.get("SAGA_CROSS_FRAME_TIMEOUT_MIN", "15"))
    lookback_min = timeout_min + 5
    since_iso = (
        datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(minutes=lookback_min)
    ).isoformat()

    params = {
        "since": since_iso,
        # §pass35.5 (2026-05-17) — EventStore's /events/{export,foreign}
        # endpoints validate limit<=1000 (Pydantic Field(le=1000)). The prior
        # value 5000 silently returned HTTP 422 on every cloud-op pre-refund
        # query → empty settled set → false refunds. Cap at 1000; the lookback
        # window is 35 min so we'd need >28 settled events/minute on a single
        # path to overflow, which doesn't happen in steady state.
        "limit": 1000,
        "event_type": "CrossFrameTransferSettled",
    }
    tid_set = set(transfer_ids)
    settled: set = set()

    try:
        async with httpx.AsyncClient(**client_kwargs) as client:
            local_coro = client.get(f"{es_url}/api/v1/events/export", params=params, headers=headers)
            foreign_coro = client.get(f"{es_url}/api/v1/events/foreign", params=params, headers=headers)
            results = await asyncio.gather(local_coro, foreign_coro, return_exceptions=True)
        failures: list = []
        for table, resp in zip(("export", "foreign"), results):
            if isinstance(resp, Exception):
                failures.append(f"{table}: {type(resp).__name__}")
                continue
            if resp.status_code != 200:
                failures.append(f"{table}: HTTP {resp.status_code}")
                continue
            try:
                events = resp.json()
                if not isinstance(events, list):
                    failures.append(f"{table}: not a list")
                    continue
                for ev in events:
                    data = ev.get("data") or {}
                    tid = data.get("transfer_id")
                    if tid in tid_set:
                        settled.add(tid)
            except Exception as parse_error:
                failures.append(f"{table}: {type(parse_error).__name__}")
                continue
        # §SOVKIT T5 (2026-09-14): a failed read was `continue`d without a trace, so a scan that could not see the
        # store and a scan that found nothing settled returned the same empty set. §SOVKIT-2 (his decision 2026-09-14):
        # a scan missing either table decides nothing; the peer's Settled events live in the foreign table.
        if failures:
            logger.warning(
                f"[SagaPreRefund] EventStore settled scan {'UNREADABLE' if len(failures) == 2 else 'partial'} "
                f"({'; '.join(failures)}) for {len(tid_set)} timed-out transfer(s); they wait for the next cycle instead "
                f"of being refunded on a scan that could not see the store"
            )
            return None
    except Exception as e:
        logger.warning(f"[SagaPreRefund] EventStore query failed: {e}; the timed-out transfers wait for the next cycle")
        return None
    return settled


async def _mark_row_settled_from_event(row, now, local_trust_domain: str) -> Optional[str]:
    """Mark a locked row as settled because EventStore has a Settled event
    for it (reactor missed the WS broadcast). Mirrors
    `reactor_cross_frame_settled.handle_event` idempotency: WHERE status='locked'
    so concurrent refund/reactor races are race-safe.

    Returns row.id on success, None on race / no-op.
    """
    async with get_db_context() as db:
        update_result = await db.execute(
            update(models.CrossFrameTransfer)
            .where(
                models.CrossFrameTransfer.id == row.id,
                models.CrossFrameTransfer.status == "locked",
            )
            .values(status="settled", settled_at=now)
            .returning(models.CrossFrameTransfer.id)
        )
        marked = update_result.scalar_one_or_none()
        await db.commit()
    if marked is None:
        return None
    logger.warning(
        f"[SagaPreRefund] RECOVERED transfer_id={row.id} — Settled event found "
        f"in EventStore but reactor missed it. Marked settled (would have been "
        f"falsely refunded). frame={local_trust_domain}→{row.target_frame}"
    )
    return row.id


async def check_cross_frame_timeouts() -> list:
    """Find locked cross_frame_transfers past their 5-min timeout, refund them.

    For each timed-out row:
      1. AAA+ pre-refund check — query EventStore for matching Settled event.
         If found, mark settled directly (do not refund). This catches the
         race where the local reactor missed the Settled WS broadcast
         (typically during registry rebuild restart windows).
      2. Otherwise: call local TEG /cross-teg/refund-async — restores
         sender balance.
      3. UPDATE row status='refunded'.
      4. Restore sender's registry-side liquid_balance (best-effort fast
         path; BalanceSyncReactor will eventually reconcile via the
         reverse TokensTransferred event we emit next).
      5. Emit TokensTransferred reverse + CrossFrameTransferRefunded.
         The Refunded event propagates via SF-4 + Pub/Sub bridge to the
         receiver frame, where reactor_cross_frame_refunded reverses any
         credit (compensating action — preserves supply invariant Δ=0
         across both frames even when receiver had already settled but the
         Settled event was lost in transit).

    2026-05-02: per-row work runs in parallel (asyncio.gather, bounded by
    `_SAGA_REFUND_CONCURRENCY` semaphore). Batch size raised to
    `_SAGA_REFUND_BATCH` since we can drain it in a few seconds.

    Returns list of refunded transfer_ids (settled-recoveries NOT included).
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    teg_base = os.environ.get("TEG_API_BASE_URL", "http://teg-layer:8080")
    teg_admin_key = os.environ.get("TEG_ADMIN_API_KEY", "")
    local_trust_domain = os.environ.get("SPIRE_TRUST_DOMAIN", "agentvault.com")

    async with get_db_context() as db:
        result = await db.execute(
            select(models.CrossFrameTransfer).where(
                and_(
                    models.CrossFrameTransfer.status == "locked",
                    models.CrossFrameTransfer.timeout_at < now,
                )
            ).limit(_SAGA_REFUND_BATCH)
        )
        rows = result.scalars().all()

    if not rows:
        return []

    # AAA+ §pass33 — pre-refund Settled scan. Query EventStore once for the
    # whole batch; transfers found settled get a free upgrade to status='settled'
    # without going through the refund/compensation cycle.
    candidate_tids = [row.id for row in rows]
    settled_tids = await _find_settled_transfer_ids(candidate_tids)
    if settled_tids is None:
        # §SOVKIT-2 (his decision 2026-09-14, "3 yes"): a scan that could not read the store decides nothing. Refunding on
        # it pays the sender back for transfers the receiving frame may already have credited (value on both frames);
        # waiting costs the sender time. The rows stay locked and the next cycle asks again.
        _LAST_CYCLE_STATS["cross_frame_refund_deferred"] = len(rows)
        if SAGA_CROSS_FRAME_REFUND_DEFERRED_TOTAL is not None:
            try:
                SAGA_CROSS_FRAME_REFUND_DEFERRED_TOTAL.labels(registry_id=_REGISTRY_ID_LABEL).inc(len(rows))
            except Exception:
                pass
        logger.warning(
            f"[CrossFrameTimeout] {len(rows)} locked transfer(s) past timeout NOT refunded this cycle: the settled scan "
            f"could not read the EventStore; they stay locked and the next cycle asks again"
        )
        return []
    _LAST_CYCLE_STATS["cross_frame_refund_deferred"] = 0
    if settled_tids:
        recovered = 0
        for row in rows:
            if row.id in settled_tids:
                marked = await _mark_row_settled_from_event(row, now, local_trust_domain)
                if marked is not None:
                    recovered += 1
        if recovered:
            logger.warning(
                f"[SagaPreRefund] Recovered {recovered}/{len(settled_tids)} "
                f"locked rows via EventStore Settled scan (would have been "
                f"falsely refunded)."
            )

    # Re-read locked rows AFTER the pre-refund recovery; rows whose status
    # advanced to 'settled' will fall out of the WHERE clause naturally.
    rows_to_refund = [r for r in rows if r.id not in settled_tids]
    if not rows_to_refund:
        return []

    conc = await _compute_adaptive_concurrency(local_trust_domain)

    logger.warning(
        f"[CrossFrameTimeout] {len(rows_to_refund)} locked transfers past timeout — "
        f"refunding (concurrency={conc}, "
        f"adaptive={'on' if _SAGA_ADAPTIVE_CONC_ENABLED else 'off'})"
    )

    sem = asyncio.Semaphore(conc)
    results = await asyncio.gather(
        *[
            _refund_one_cross_frame_row(
                row, now, teg_base, teg_admin_key, local_trust_domain, sem
            )
            for row in rows_to_refund
        ],
        return_exceptions=True,
    )
    refunded_ids = [r for r in results if isinstance(r, str)]
    return refunded_ids


# Module-level singleton
_checker: Optional[SagaTimeoutChecker] = None


async def start_saga_timeout_checker():
    """Start the saga timeout checker (called from main.py startup)."""
    global _checker
    if _checker is None:
        _checker = SagaTimeoutChecker()
    await _checker.start()


async def stop_saga_timeout_checker():
    """Stop the saga timeout checker (called from main.py shutdown)."""
    global _checker
    if _checker:
        await _checker.stop()


def get_saga_timeout_checker() -> Optional[SagaTimeoutChecker]:
    """Accessor for admin endpoints (returns None pre-start)."""
    return _checker


def get_last_cycle_stats() -> Dict[str, Any]:
    """Read-only access to most recent cycle stats."""
    return dict(_LAST_CYCLE_STATS)
