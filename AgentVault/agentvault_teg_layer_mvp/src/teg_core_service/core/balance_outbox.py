"""
§pass73.3.19 L2 — Balance outbox emitter (CQRS transactional outbox).
=======================================================================
Tails `balance_ledger_journal` (L1 — complete-by-construction trigger on agent_teg_profiles) and
projects each atomic TEG transaction (grouped by `txid`) into the EventStore as exactly ONE
idempotent `LedgerBalanceChanged` event, then stamps `emitted_at`. This is the SINGLE writer of the
ES balance projection — supply is conserved by the per-txid net (net>0=issuance, <0=destruction,
==0=transfer/stake/fee). See sessionlogs2026/DESIGN_2026-05-29_AAA_BALANCE_INTEGRITY_CQRS_OUTBOX.md.

Correctness invariants:
  - A txid group is emitted WHOLE (never split across two events) — else a zero-sum transfer split
    into +half/-half would misclassify as issuance+destruction. We select whole groups, oldest first.
  - Idempotency key `ledger-tx-{teg_id}-{txid}` → ES UNIQUE(idempotency_key) makes re-emits no-ops
    (409 → success). emitted_at is stamped only after the emit lands, so a crash mid-cycle just retries.
  - §PG18XID (2026-09-29): a txid is unique only within ONE database cluster. A restore into a new cluster
    (a Postgres major moved by dump/restore, a disaster-recovery restore) restarts txid_current() near 750,
    and a group whose txid an EARLIER journal row already carries would reuse an old key: the store's Kafka
    consumer skips it as a duplicate without comparing payloads, so the balance change never reaches the
    projection and nothing reports it (sbx-alpha 2026-09-29: 74 groups, 37 accounts, supply delta still 0).
    Such a group is keyed `ledger-tx-{teg_id}-{txid}-j{first journal id}` instead. The test is exact and
    stable: a different transaction of the same cluster never shares a txid, and the earlier rows are
    history that cannot change, so a retry computes the same key. While the counter is below the journal's
    own history the outbox also says so every cycle (log + gauge); the operator's fix is to move the
    counter past it (tests/test_balance_outbox_txid_reuse.py).

Leader-elected (Redis SETNX, fail-closed) — mirrors core/cross_teg/sweeper.py.
DISABLED by default (`TEG_BALANCE_OUTBOX_ENABLED`): only enable WITH the projection single-writer
cutover + re-baseline, otherwise the legacy typed events AND LedgerBalanceChanged double-count.
"""
from __future__ import annotations

import asyncio
import logging
import os
import socket
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional

from sqlalchemy import bindparam, text

from . import ledger_health as _lh

logger = logging.getLogger(__name__)

OUTBOX_ENABLED = os.getenv("TEG_BALANCE_OUTBOX_ENABLED", "false").lower() == "true"
INTERVAL_SEC = int(os.getenv("TEG_BALANCE_OUTBOX_INTERVAL_SEC", "5"))
GROUP_LIMIT = int(os.getenv("TEG_BALANCE_OUTBOX_GROUP_LIMIT", "200"))  # whole txid-groups per cycle
# §LEDGERGATE: a cycle stops after this many groups running could not reach the store (a hanging store would otherwise
# hold a cycle for GROUP_LIMIT x the 10 s emit timeout, and the ledger's health would go unmeasured all that time).
BREAK_AFTER_FAILS = max(1, int(os.getenv("TEG_BALANCE_OUTBOX_BREAK_AFTER_FAILS", "3")))
LEADER_KEY_PREFIX = "teg_balance_outbox"
LEADER_LEASE_SEC = 90


def _teg_id() -> str:
    return os.getenv("TEG_ID") or os.getenv("REGISTRY_NAME") or socket.gethostname()


# Prometheus (lazy, best-effort — mirrors the sweeper's pattern).
try:
    from prometheus_client import Counter as _C, Gauge as _G

    OUTBOX_CYCLE_TOTAL = _C("teg_balance_outbox_cycle_total", "Outbox cycles run (leader only)", ["teg_id"])
    OUTBOX_GROUPS_TOTAL = _C("teg_balance_outbox_groups_total", "LedgerBalanceChanged events emitted", ["teg_id"])
    OUTBOX_ROWS_TOTAL = _C("teg_balance_outbox_rows_total", "Journal rows projected", ["teg_id"])
    OUTBOX_ERRORS_TOTAL = _C("teg_balance_outbox_errors_total", "Outbox errors", ["teg_id", "reason"])
    OUTBOX_BACKLOG = _G("teg_balance_outbox_backlog", "Unemitted journal rows", ["teg_id"], multiprocess_mode="max")
    OUTBOX_TXID_BEHIND = _G("teg_balance_outbox_txid_behind_history",
                            "1 while this database's transaction counter is below its own journal's highest txid "
                            "(a restore into a new cluster restarted it)", ["teg_id"], multiprocess_mode="max")
    _METRICS = True
except Exception:  # pragma: no cover
    _METRICS = False


def ledger_event_key(teg_id: str, txid: Optional[int], first_id: int, reuses_history: bool) -> str:
    """The idempotency key of one txid group's LedgerBalanceChanged (§PG18XID: see the module docstring)."""
    if txid is None:
        return f"ledger-tx-{teg_id}-null-{first_id}"
    if reuses_history:
        return f"ledger-tx-{teg_id}-{txid}-j{first_id}"
    return f"ledger-tx-{teg_id}-{txid}"


# Whole txid groups, oldest first by min(id), each with the §PG18XID flag: does an EARLIER journal row (a smaller
# id) carry the same txid? Only a transaction of a previous cluster can, so it is exact; ix_blj_txid serves it.
SELECT_GROUPS_SQL = text("""
    WITH grp AS (
        SELECT txid, MIN(id) AS first_id
        FROM balance_ledger_journal
        WHERE emitted_at IS NULL
        GROUP BY txid
        ORDER BY first_id
        LIMIT :glim
    ), flagged AS (
        SELECT txid, first_id,
               (txid IS NOT NULL AND EXISTS (
                    SELECT 1 FROM balance_ledger_journal o WHERE o.txid = grp.txid AND o.id < grp.first_id
               )) AS reuses_history
        FROM grp
    )
    SELECT j.id, j.agent_id, j.txid, j.delta_liquid, j.delta_locked, j.entry_type,
           flagged.first_id, flagged.reuses_history
    FROM balance_ledger_journal j
    JOIN flagged ON (j.txid IS NOT DISTINCT FROM flagged.txid)
    WHERE j.emitted_at IS NULL
    ORDER BY flagged.first_id, j.id
""")

# The next transaction id this cluster will assign against the journal's highest txid. In one cluster every
# assigned txid is below the next one, so "next <= highest" happens only after the counter restarted.
COUNTER_SQL = text("""
    SELECT pg_snapshot_xmax(pg_current_snapshot())::text::bigint AS next_txid,
           (SELECT max(txid) FROM balance_ledger_journal) AS journal_max
""")


async def counter_behind_history(db) -> tuple:
    """(behind, next_txid, journal_max) for this database."""
    row = (await db.execute(COUNTER_SQL)).one()
    next_txid, journal_max = int(row[0]), (int(row[1]) if row[1] is not None else None)
    return (journal_max is not None and next_txid <= journal_max), next_txid, journal_max


class BalanceOutboxEmitter:
    """Leader-elected emitter: balance_ledger_journal → LedgerBalanceChanged → ES."""

    def __init__(self):
        self.teg_id = _teg_id()
        self.running = False
        self.task: Optional[asyncio.Task] = None
        self.worker_id = f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"
        self._emitter = None
        self._is_leader_now = False
        self._last_cycle_iso: Optional[str] = None
        self._last_stats: Dict[str, int] = {"groups": 0, "rows": 0, "errors": 0, "backlog": 0}
        self._behind_logged_at = 0.0   # §PG18XID: the counter warning is logged at most every 10 minutes
        # §LEDGERGATE: the ledger's health, measured by the leader each cycle and published for the gate
        self._health = _lh.HealthTracker(interval_s=INTERVAL_SEC)
        self._health_logged = (_lh.OK, "ok")

    # ---------------------------------------------------------------- lifecycle
    async def start(self) -> None:
        if not OUTBOX_ENABLED:
            logger.info("[BalanceOutbox] disabled via TEG_BALANCE_OUTBOX_ENABLED — skipping start")
            return
        if self.running:
            return
        # Preflight: make sure LedgerBalanceChanged is emit-able immediately (it is seeded allowed at
        # event_emitter import; this also pulls any registry policy row).
        try:
            from ..event_emitter import _fetch_teg_policies
            await _fetch_teg_policies()
        except Exception as e:
            logger.debug(f"[BalanceOutbox] preflight policy fetch failed: {e}")
        self.running = True
        self.task = asyncio.create_task(self._run_loop())
        logger.info(
            f"[BalanceOutbox] starting (teg_id={self.teg_id}, interval={INTERVAL_SEC}s, "
            f"group_limit={GROUP_LIMIT}, worker={self.worker_id})"
        )

    async def stop(self) -> None:
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None
        try:
            from ..redis_client import get_redis
            redis = await get_redis()
            if redis is not None:
                key = f"{LEADER_KEY_PREFIX}:{self.teg_id}"
                if (await redis.get(key)) == self.worker_id:
                    await redis.delete(key)
        except Exception:
            pass
        logger.info("[BalanceOutbox] stopped")

    # ---------------------------------------------------------------- main loop
    async def _run_loop(self) -> None:
        await asyncio.sleep(5)  # cold-start settle
        while self.running:
            try:
                if await self._acquire_leader():
                    if not self._is_leader_now:
                        await self._seed_health()
                    self._is_leader_now = True
                    await self._cycle_once()
                else:
                    self._is_leader_now = False
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"[BalanceOutbox] loop error: {e}", exc_info=True)
                if _METRICS:
                    try:
                        OUTBOX_ERRORS_TOTAL.labels(teg_id=self.teg_id, reason="loop").inc()
                    except Exception:
                        pass
            await asyncio.sleep(INTERVAL_SEC)

    async def _acquire_leader(self) -> bool:
        try:
            from ..redis_client import get_redis
            redis = await get_redis()
            if redis is None:
                return False  # fail-closed: no Redis → no leader → skip (idempotency would dedup anyway)
            key = f"{LEADER_KEY_PREFIX}:{self.teg_id}"
            current = await redis.get(key)
            if current is None:
                return bool(await redis.set(key, self.worker_id, ex=LEADER_LEASE_SEC, nx=True))
            if current == self.worker_id:
                await redis.expire(key, LEADER_LEASE_SEC)
                return True
            return False
        except Exception as e:
            logger.debug(f"[BalanceOutbox] leader acquire failed: {e}")
            return False

    def _get_emitter(self):
        if self._emitter is None:
            from ..event_emitter import EventEmitter
            self._emitter = EventEmitter(
                event_store_url=os.getenv("EVENT_STORE_URL", "http://event-store:8200"),
                internal_api_key=os.getenv("EVENT_STORE_API_KEY", ""),
                source_service="teg-balance-outbox",
            )
        return self._emitter

    # ---------------------------------------------------------------- cycle
    async def _cycle_once(self) -> None:
        from ..database.db_session import AsyncSessionLocal
        if AsyncSessionLocal is None:
            return
        t0 = time.time()

        # Select WHOLE txid-groups (never split a group across cycles), oldest first by min(id).
        # NULL txid (only possible for legacy pre-v2 rows) is grouped together as one — harmless
        # post-rebaseline since the v2 trigger always sets txid_current().
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(SELECT_GROUPS_SQL, {"glim": GROUP_LIMIT})).fetchall()
            try:
                behind, next_txid, journal_max = await counter_behind_history(db)
            except Exception as e:
                behind, next_txid, journal_max = False, None, None
                logger.debug(f"[BalanceOutbox] counter check failed: {e}")
            if behind and time.time() - self._behind_logged_at >= 600:
                self._behind_logged_at = time.time()
                logger.error(
                    f"[BalanceOutbox] this database's transaction counter (next {next_txid}) is below its own "
                    f"journal's highest txid ({journal_max}): a restore into a new cluster restarted it. Groups that "
                    f"reuse an old txid are keyed -j<first id> so none is lost; move the counter past {journal_max} "
                    f"to end this (§PG18XID)."
                )
            if _METRICS:
                try:
                    OUTBOX_TXID_BEHIND.labels(teg_id=self.teg_id).set(1.0 if behind else 0.0)
                except Exception:
                    pass
            if _METRICS:
                try:
                    bk = (await db.execute(
                        text("SELECT count(*) FROM balance_ledger_journal WHERE emitted_at IS NULL")
                    )).scalar()
                    OUTBOX_BACKLOG.labels(teg_id=self.teg_id).set(float(bk or 0))
                except Exception:
                    pass

        if not rows:
            self._last_cycle_iso = datetime.now(timezone.utc).isoformat()
            await self._measure_health(_lh.Observation(cycle_ms=int((time.time() - t0) * 1000)), [])
            return

        # Build ordered whole-groups.
        order: List = []
        groups: Dict = {}
        for (rid, agent_id, txid, dl, dk, etype, first_id, reuses_history) in rows:
            gkey = txid if txid is not None else "__null__"
            if gkey not in groups:
                groups[gkey] = {"txid": txid, "ids": [], "entries": [], "net": Decimal("0"), "kinds": set(),
                                "first_id": first_id, "reuses_history": bool(reuses_history)}
                order.append(gkey)
            dld = Decimal(str(dl or 0))
            dkd = Decimal(str(dk or 0))
            groups[gkey]["ids"].append(rid)
            groups[gkey]["entries"].append(
                {"agent_did": agent_id, "delta_liquid": str(dld), "delta_staked": str(dkd)}
            )
            groups[gkey]["net"] += (dld + dkd)
            # §B: collect the journal entry_type(s) for this txid group → emit a supply `kind`
            # so the ES projection books only genuine mint/burn into issued/destroyed and routes
            # transfers / stakes / fees / cross-frame legs to transit_net. 'unknown' stays untagged.
            if etype and etype != "unknown":
                groups[gkey]["kinds"].add(etype)

        emitter = self._get_emitter()
        emitted_ids: List[int] = []
        n_groups = n_rows = n_err = n_reused = 0
        n_attempted = n_unreachable = 0
        rejected_txids: List[Optional[int]] = []
        unreachable_run = 0
        for gkey in order:
            g = groups[gkey]
            n_attempted += 1
            idem = ledger_event_key(self.teg_id, g["txid"], g["first_id"], g["reuses_history"])
            if g["reuses_history"]:
                n_reused += 1
            # §B: one txid = one logical TEG op → its rows share a kind. Single known type →
            # that kind; none → 'unknown'; (defensively) multiple → 'mixed'. Only mint / dispute_comp
            # / slash / burn move supply in the ES projection; everything else → transit_net.
            _kinds = g["kinds"]
            kind = next(iter(_kinds)) if len(_kinds) == 1 else ("mixed" if _kinds else "unknown")
            ok = False
            try:
                emitter.last_status = None
            except Exception:  # pragma: no cover
                pass
            try:
                ok = await emitter.emit(
                    event_type="LedgerBalanceChanged",
                    aggregate_id=idem,
                    aggregate_type="Ledger",
                    data={
                        "txid": g["txid"],
                        "frame": self.teg_id,
                        "entries": g["entries"],
                        "net": str(g["net"]),
                        "kind": kind,
                    },
                    idempotency_key=idem,
                )
            except Exception as e:
                logger.warning(f"[BalanceOutbox] emit failed for {idem}: {e}")
                n_err += 1
                if _METRICS:
                    try:
                        OUTBOX_ERRORS_TOTAL.labels(teg_id=self.teg_id, reason="emit").inc()
                    except Exception:
                        pass
            if ok:
                n_groups += 1
                n_rows += len(g["ids"])
                emitted_ids.extend(g["ids"])
                unreachable_run = 0
            # else: leave the whole group unemitted; retried next cycle.
            elif _lh.classify_failure(getattr(emitter, "last_status", None)) == "rejected":
                rejected_txids.append(g["txid"])   # the store read it and refused its content: not an outage
                unreachable_run = 0
            else:
                n_unreachable += 1
                unreachable_run += 1
                if unreachable_run >= BREAK_AFTER_FAILS:
                    left = len(order) - n_attempted
                    if left:
                        logger.warning(f"[BalanceOutbox] {unreachable_run} groups running could not reach the store; "
                                       f"{left} more wait for the next cycle")
                    break

        if emitted_ids:
            stamp = text("UPDATE balance_ledger_journal SET emitted_at=now() WHERE id IN :ids").bindparams(
                bindparam("ids", expanding=True)
            )
            async with AsyncSessionLocal() as db:
                await db.execute(stamp, {"ids": emitted_ids})
                await db.commit()

        dur = int((time.time() - t0) * 1000)
        self._last_cycle_iso = datetime.now(timezone.utc).isoformat()
        self._last_stats = {"groups": n_groups, "rows": n_rows, "errors": n_err, "backlog": len(rows),
                            "rejected": len(rejected_txids), "unreachable": n_unreachable}
        await self._measure_health(
            _lh.Observation(attempted=n_attempted, emitted=n_groups, emitted_rows=n_rows, rejected=len(rejected_txids),
                            unreachable=n_unreachable, cycle_ms=dur),
            rejected_txids,
        )
        if _METRICS:
            try:
                OUTBOX_CYCLE_TOTAL.labels(teg_id=self.teg_id).inc()
                if n_groups:
                    OUTBOX_GROUPS_TOTAL.labels(teg_id=self.teg_id).inc(n_groups)
                if n_rows:
                    OUTBOX_ROWS_TOTAL.labels(teg_id=self.teg_id).inc(n_rows)
            except Exception:
                pass
        if n_reused:
            logger.warning(f"[BalanceOutbox] {n_reused} group(s) reuse a txid an earlier journal row carries "
                           f"(a restarted counter, §PG18XID): keyed -j<first id>")
            if _METRICS:
                try:
                    OUTBOX_ERRORS_TOTAL.labels(teg_id=self.teg_id, reason="txid_reused").inc(n_reused)
                except Exception:
                    pass
        if n_groups or n_err:
            logger.info(
                f"[BalanceOutbox] cycle: emitted {n_groups} groups / {n_rows} rows, "
                f"errors={n_err}, in {dur}ms"
            )

    # ---------------------------------------------------------------- §LEDGERGATE: the ledger's health
    async def _seed_health(self) -> None:
        """A worker that becomes leader carries on from the published verdict, so a change of leader does not
        reset the hysteresis (an unhealthy ledger is not called ok by the first cycle of a new leader)."""
        try:
            from ..redis_client import get_redis
            body, _why = await _lh.read(await get_redis(), self.teg_id)
        except Exception:  # noqa: BLE001
            body = None
        if not body:
            return
        h = self._health
        h.state = body.get("state", _lh.OK)
        h.reason = str(body.get("reason") or h.state)
        try:
            h.failed_cycles = int(body.get("failed_cycles") or 0)
            h.since = float(body.get("since") or h.since)
            lg = body.get("last_good_emit")
            h.last_good_emit = float(lg) if lg is not None else None
        except (TypeError, ValueError):
            pass

    async def _measure_health(self, obs: "_lh.Observation", rejected_txids: List[Optional[int]]) -> None:
        """Measure the journal after the cycle, fold it into the verdict, publish it. Never raises: the ledger's
        health is a reading, and a failed reading must not stop the outbox (the gate reads a missing verdict as
        the journal's own state)."""
        from ..database.db_session import AsyncSessionLocal
        try:
            async with AsyncSessionLocal() as db:
                row = (await db.execute(text(_lh.WAITING_SQL),
                                        {"stuck": _lh.stuck_param(rejected_txids)})).fetchone()
            obs.waiting_rows, obs.oldest_waiting_age_s, obs.stuck_rows, obs.oldest_stuck_age_s = \
                _lh.waiting_from_row(row or ())
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[BalanceOutbox] the ledger's health was not measured: {type(e).__name__}: {e}")
            return
        snap = self._health.observe(obs)
        try:
            from ..redis_client import get_redis
            await _lh.publish(await get_redis(), self.teg_id, snap, self.worker_id, INTERVAL_SEC)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[BalanceOutbox] the ledger's health was not published: {e}")
        _lh.set_gauges(self.teg_id, snap)
        now = (snap["state"], snap["reason"])
        if now != self._health_logged:
            log = logger.info if snap["state"] == _lh.OK else logger.warning
            log(f"[BalanceOutbox] the ledger is {snap['state']} ({snap['reason']}): {snap['waiting_rows']} rows "
                f"waiting, the oldest {snap['oldest_waiting_age_s']} s; {snap['stuck_rows']} rows of groups the "
                f"store rejected; {snap['failed_cycles']} failed cycles running")
            self._health_logged = now

    def health(self) -> Dict:
        """This worker's last verdict (the leader's is the one in Redis)."""
        return self._health.snapshot()

    def snapshot(self) -> Dict:
        return {
            "teg_id": self.teg_id,
            "worker_id": self.worker_id,
            "is_leader": self._is_leader_now,
            "last_cycle_iso": self._last_cycle_iso,
            "enabled": OUTBOX_ENABLED,
            **self._last_stats,
        }


# ── Module-level singleton (mirrors the sweeper's start_/stop_ pattern) ──────────
_outbox: Optional[BalanceOutboxEmitter] = None


def get_balance_outbox() -> Optional[BalanceOutboxEmitter]:
    return _outbox


async def start_balance_outbox() -> None:
    global _outbox
    if _outbox is None:
        _outbox = BalanceOutboxEmitter()
    await _outbox.start()


async def stop_balance_outbox() -> None:
    global _outbox
    if _outbox is not None:
        await _outbox.stop()
