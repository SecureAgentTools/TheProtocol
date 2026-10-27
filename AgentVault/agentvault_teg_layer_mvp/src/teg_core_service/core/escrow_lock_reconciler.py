"""
Orphaned-escrow-lock reconciler (§P2 — 2026-06-02).

Periodic, leader-elected per TEG. Releases PHANTOM `locked_balance` left behind by
the cross-TEG 2PC escrow path (a lock placed via protocol._lock_funds that was never
released by complete/compensate). §P1a (idempotent _lock_funds) stops NEW duplicate-lock
orphans; this reconciler clears the EXISTING backlog + catches the rare worker-death /
COMMITTED-sweep-hole straggler.

SAFETY (the whole design):
  An agent's locked_balance can hold THREE things, all sharing the column:
    - staking  : registry stake → TEG `/lock` to receiver='SYSTEM_LOCK' with the REAL amount.
    - bridge   : SF-3 bridge collateral → reflected by wrapped_balance > 0.
    - escrow   : cross-TEG 2PC in-flight → protocol._lock_funds, receiver=self, amount=0.
  We ONLY touch PURE-ESCROW agents and release ONLY the non-in-flight escrow:
    candidate  := locked_balance > tol
                  AND net SYSTEM_LOCK stake (Σlock−Σunlock by amount) <= tol   (never staked)
                  AND wrapped_balance == 0                                      (no bridge)
    release    := locked_balance − in_flight_escrow   (un-expired non-terminal source rows)
  Real stakers (Ironhand Alpha 801M, SYBIL, …) are SKIPPED entirely — their
  registry/TEG/stake-lock references drift ~0.03% on heavy accounts, so their
  escrow residue is NOT reliably separable; leaving it is safe (Commander steer:
  "target non-staking agents only, NOT the real staking pool"). Verified read-only
  on prod Frame A: skips all stakers, releases only Ironhand Echo/Delta-class phantom.

Δ-safety: the release is a `locked_balance -= orphan` UPDATE tagged
`teg.entry_type='escrow_reconcile_release'` → the L1 journal trigger stamps it →
the L2 outbox emits kind='escrow_reconcile_release' → the ES projection routes it to
transit_net (NOT issued/destroyed) → the supply invariant stays Δ=0 by construction.

Modes:
  ESCROW_RECONCILER_ENABLED   default false  — master switch.
  ESCROW_RECONCILER_DRY_RUN   default true   — log what WOULD be released, mutate nothing.
                                               Flip to false ONLY after observing a dry-run.
  ESCROW_RECONCILER_INTERVAL_SEC   default 1800
  ESCROW_RECONCILER_TOLERANCE      default 0.000001
  ESCROW_RECONCILER_BATCH_LIMIT    default 200  (agents per cycle)
  ESCROW_RECONCILER_MAX_RELEASE_PER_AGENT  default 100000  (circuit-breaker: never
                                               release more than this from one agent
                                               in one pass — a guard against a logic bug
                                               draining a large balance).

Leader election: Redis SETNX 90s TTL on `teg_escrow_reconciler:{teg_id}`. Fail-closed.
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

from sqlalchemy import text

logger = logging.getLogger(__name__)

ENABLED = os.getenv("ESCROW_RECONCILER_ENABLED", "false").lower() in ("true", "1", "yes")
DRY_RUN = os.getenv("ESCROW_RECONCILER_DRY_RUN", "true").lower() in ("true", "1", "yes")
INTERVAL_SEC = int(os.getenv("ESCROW_RECONCILER_INTERVAL_SEC", "1800"))
TOLERANCE = Decimal(os.getenv("ESCROW_RECONCILER_TOLERANCE", "0.000001"))
BATCH_LIMIT = int(os.getenv("ESCROW_RECONCILER_BATCH_LIMIT", "200"))
MAX_RELEASE_PER_AGENT = Decimal(os.getenv("ESCROW_RECONCILER_MAX_RELEASE_PER_AGENT", "100000"))
LEADER_KEY_PREFIX = "teg_escrow_reconciler"
LEADER_LEASE_SEC = 90


# Prometheus (lazy, best-effort — mirrors core/cross_teg/sweeper.py).
try:
    from prometheus_client import Counter as _C, Gauge as _G

    RECON_CYCLE_TOTAL = _C("teg_escrow_reconcile_cycle_total", "Reconciler cycles (leader only)", ["teg_id"])
    RECON_RELEASED_TOTAL = _C("teg_escrow_reconcile_released_total", "Orphan escrow released (AVT)", ["teg_id"])
    RECON_AGENTS_TOTAL = _C("teg_escrow_reconcile_agents_total", "Agents reconciled", ["teg_id", "mode"])
    RECON_ERRORS_TOTAL = _C("teg_escrow_reconcile_errors_total", "Reconciler errors", ["teg_id", "reason"])
    RECON_PENDING = _G("teg_escrow_reconcile_pending_avt", "Phantom escrow detected pending release", ["teg_id"], multiprocess_mode="max")
    _METRICS = True
except Exception:  # pragma: no cover
    _METRICS = False


# Candidate detection (read-only) — exactly the logic verified on prod Frame A.
_CANDIDATE_SQL = text("""
    WITH stake AS (
        SELECT aid, SUM(samt) AS net_stake FROM (
            SELECT sender_agent_id AS aid, amount AS samt
              FROM teg_transactions WHERE transaction_type='lock'   AND receiver_agent_id='SYSTEM_LOCK'
            UNION ALL
            SELECT receiver_agent_id AS aid, -amount
              FROM teg_transactions WHERE transaction_type='unlock' AND sender_agent_id='SYSTEM_LOCK'
        ) t GROUP BY aid
    ),
    inflight AS (
        SELECT source_agent_id AS aid, SUM(amount) AS inflight_amt
          FROM cross_teg_transfers
         WHERE role='source' AND status IN ('INITIATED','FUNDS_LOCKED','COMMITTED')
           AND completed_at IS NULL AND expires_at > now()
         GROUP BY source_agent_id
    )
    SELECT p.agent_id,
           p.locked_balance,
           COALESCE(s.net_stake, 0)   AS stake_lock,
           COALESCE(i.inflight_amt, 0) AS inflight,
           COALESCE(p.wrapped_balance, 0) AS wrapped
      FROM agent_teg_profiles p
      LEFT JOIN stake s    ON s.aid = p.agent_id
      LEFT JOIN inflight i ON i.aid = p.agent_id
     WHERE p.locked_balance > :tol
       AND COALESCE(s.net_stake, 0)    <= :tol   -- pure-escrow only (never staked)
       AND COALESCE(p.wrapped_balance, 0) = 0    -- no bridge collateral
       AND (p.locked_balance - COALESCE(i.inflight_amt, 0)) > :tol
     ORDER BY (p.locked_balance - COALESCE(i.inflight_amt, 0)) DESC
     LIMIT :lim
""")

# Per-agent recompute under the profile row lock (race-safe re-verify of stake + in-flight).
_RECHECK_STAKE_SQL = text("""
    SELECT COALESCE(SUM(samt), 0) FROM (
        SELECT amount AS samt FROM teg_transactions
          WHERE transaction_type='lock'   AND receiver_agent_id='SYSTEM_LOCK' AND sender_agent_id=:aid
        UNION ALL
        SELECT -amount FROM teg_transactions
          WHERE transaction_type='unlock' AND sender_agent_id='SYSTEM_LOCK' AND receiver_agent_id=:aid
    ) t
""")
_RECHECK_INFLIGHT_SQL = text("""
    SELECT COALESCE(SUM(amount), 0) FROM cross_teg_transfers
     WHERE source_agent_id=:aid AND role='source'
       AND status IN ('INITIATED','FUNDS_LOCKED','COMMITTED')
       AND completed_at IS NULL AND expires_at > now()
""")


class EscrowLockReconciler:
    """Periodic, leader-elected reconciler that releases orphaned escrow locks."""

    def __init__(self, teg_id: str, db_session_factory):
        self.teg_id = teg_id
        self.db_session_factory = db_session_factory
        self.running = False
        self.task: Optional[asyncio.Task] = None
        self.worker_id = f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"
        self._is_leader_now = False
        self._last_cycle_iso: Optional[str] = None
        self._last_stats: Dict[str, str] = {"checked": "0", "released_agents": "0", "released_avt": "0", "errors": "0", "dry_run": str(DRY_RUN)}
        self._emitter = None

    # --------------------------------------------------------------- session
    def _session(self):
        gen = self.db_session_factory()
        return next(gen), gen

    def _close(self, gen):
        try:
            next(gen)
        except StopIteration:
            pass

    # --------------------------------------------------------------- lifecycle
    async def start(self) -> None:
        if not ENABLED:
            logger.info("[EscrowReconciler] disabled via ESCROW_RECONCILER_ENABLED — skipping start")
            return
        if self.running:
            return
        try:
            from ..event_emitter import _fetch_teg_policies
            await _fetch_teg_policies()
        except Exception as e:
            logger.debug(f"[EscrowReconciler] preflight policy fetch failed: {e}")
        self.running = True
        self.task = asyncio.create_task(self._run_loop())
        logger.info(
            f"[EscrowReconciler] starting (teg_id={self.teg_id}, dry_run={DRY_RUN}, "
            f"interval={INTERVAL_SEC}s, batch={BATCH_LIMIT}, worker={self.worker_id})"
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
        logger.info("[EscrowReconciler] stopped")

    async def _run_loop(self) -> None:
        await asyncio.sleep(8)  # cold-start settle (after the sweeper/outbox)
        while self.running:
            try:
                if await self._acquire_leader():
                    self._is_leader_now = True
                    await self._cycle_once()
                else:
                    self._is_leader_now = False
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"[EscrowReconciler] loop error: {e}", exc_info=True)
                if _METRICS:
                    try:
                        RECON_ERRORS_TOTAL.labels(teg_id=self.teg_id, reason="loop").inc()
                    except Exception:
                        pass
            await asyncio.sleep(INTERVAL_SEC)

    async def _acquire_leader(self) -> bool:
        try:
            from ..redis_client import get_redis
            redis = await get_redis()
            if redis is None:
                return False  # fail-closed
            key = f"{LEADER_KEY_PREFIX}:{self.teg_id}"
            current = await redis.get(key)
            if current is None:
                return bool(await redis.set(key, self.worker_id, ex=LEADER_LEASE_SEC, nx=True))
            if current == self.worker_id:
                await redis.expire(key, LEADER_LEASE_SEC)
                return True
            return False
        except Exception as e:
            logger.debug(f"[EscrowReconciler] leader acquire failed: {e}")
            return False

    # --------------------------------------------------------------- cycle
    async def _cycle_once(self) -> None:
        t0 = time.time()
        session, gen = self._session()
        checked = 0
        released_agents = 0
        released_avt = Decimal("0")
        pending_avt = Decimal("0")
        errors = 0
        try:
            rows = session.execute(_CANDIDATE_SQL, {"tol": TOLERANCE, "lim": BATCH_LIMIT}).fetchall()
            checked = len(rows)
            for (agent_id, locked, stake_lock, inflight, wrapped) in rows:
                orphan = Decimal(str(locked)) - Decimal(str(inflight))
                pending_avt += orphan
                try:
                    rel = self._release_one(agent_id, orphan)
                    if rel > 0:
                        released_agents += 1
                        released_avt += rel
                except Exception as e:
                    errors += 1
                    logger.error(f"[EscrowReconciler] release failed for {agent_id}: {e}", exc_info=True)
                    if _METRICS:
                        try:
                            RECON_ERRORS_TOTAL.labels(teg_id=self.teg_id, reason="release").inc()
                        except Exception:
                            pass
        finally:
            self._close(gen)

        # §V0045 F1 — repair pass for NEGATIVE locked_balance (double-release victims).
        # locked_balance < 0 is never legitimate (it is escrow/stake bookkeeping); clamp
        # to 0 under a row lock + audit event. Same Δ-neutrality as the orphan release
        # (no token movement). Honors DRY_RUN.
        clamped_agents = 0
        clamped_avt = Decimal("0")
        try:
            clamped_agents, clamped_avt = self._clamp_negative_locks()
        except Exception as e:
            errors += 1
            logger.error(f"[EscrowReconciler] negative-lock clamp pass failed: {e}", exc_info=True)

        dur_ms = int((time.time() - t0) * 1000)
        self._last_cycle_iso = datetime.now(timezone.utc).isoformat()
        self._last_stats = {
            "checked": str(checked), "released_agents": str(released_agents),
            "released_avt": str(released_avt), "errors": str(errors), "dry_run": str(DRY_RUN),
            "negative_clamped_agents": str(clamped_agents), "negative_clamped_avt": str(clamped_avt),
        }
        if _METRICS:
            try:
                RECON_CYCLE_TOTAL.labels(teg_id=self.teg_id).inc()
                RECON_PENDING.labels(teg_id=self.teg_id).set(float(pending_avt))
                if released_avt > 0:
                    RECON_RELEASED_TOTAL.labels(teg_id=self.teg_id).inc(float(released_avt))
                if released_agents:
                    RECON_AGENTS_TOTAL.labels(teg_id=self.teg_id, mode=("dry" if DRY_RUN else "live")).inc(released_agents)
            except Exception:
                pass
        level = logger.warning if (released_agents or errors or (DRY_RUN and pending_avt > TOLERANCE)) else logger.info
        level(
            f"[EscrowReconciler] cycle dry_run={DRY_RUN}: checked={checked} "
            f"{'WOULD_release' if DRY_RUN else 'released'}={released_agents} agents / {released_avt} AVT, "
            f"pending_detected={pending_avt} AVT, errors={errors}, {dur_ms}ms"
        )

    def _clamp_negative_locks(self) -> tuple:
        """§V0045 F1 — floor negative locked_balance rows to 0 (double-release repair).

        A negative lock means MORE was released than ever locked (the complete-then-
        expiry-compensate race fixed in cross_teg/protocol.py this same version). The
        residue inflates the agent's spendable headroom; clamping to 0 restores the
        invariant locked_balance >= 0. Unambiguous (no stake/in-flight check needed —
        no legitimate writer ever takes it below zero). Returns (agents, total_clamped).
        """
        from ..database.models import AgentTEGProfile
        from sqlalchemy import select as _select, text as _text

        out_agents, out_total = 0, Decimal("0")
        session, gen = self._session()
        try:
            rows = session.execute(_text(
                "SELECT agent_id FROM agent_teg_profiles WHERE locked_balance < -:tol "
                "ORDER BY locked_balance ASC LIMIT :lim"
            ), {"tol": TOLERANCE, "lim": BATCH_LIMIT}).fetchall()
        finally:
            self._close(gen)

        for (agent_id,) in rows:
            session, gen = self._session()
            try:
                profile = session.execute(
                    _select(AgentTEGProfile).where(AgentTEGProfile.agent_id == agent_id).with_for_update()
                ).scalar_one_or_none()
                if profile is None:
                    self._close(gen)
                    continue
                locked = Decimal(str(profile.locked_balance or 0))
                if locked >= 0:  # repaired meanwhile
                    session.rollback(); self._close(gen)
                    continue
                if DRY_RUN:
                    logger.warning(
                        f"[EscrowReconciler][DRY_RUN] WOULD clamp NEGATIVE lock {locked} → 0 for {agent_id}"
                    )
                    session.rollback(); self._close(gen)
                    continue
                session.execute(_text(
                    "SELECT set_config('teg.entry_type','escrow_negative_lock_clamp',true),"
                    " set_config('teg.entry_ref',:r,true)"
                ), {"r": agent_id})
                profile.locked_balance = Decimal("0")
                session.commit()
                self._close(gen)
                out_agents += 1
                out_total += -locked
                logger.warning(
                    f"[EscrowReconciler] CLAMPED NEGATIVE lock for {agent_id}: {locked} → 0 "
                    f"(double-release residue repaired)"
                )
                asyncio.create_task(self._emit_audit_negative(agent_id, locked))
            except Exception:
                try:
                    session.rollback()
                except Exception:
                    pass
                self._close(gen)
                raise
        return out_agents, out_total

    async def _emit_audit_negative(self, agent_id: str, locked_before: Decimal) -> None:
        try:
            if self._emitter is None:
                from ..event_emitter import EventEmitter
                self._emitter = EventEmitter(
                    event_store_url=os.getenv("EVENT_STORE_URL", "http://event-store:8200"),
                    internal_api_key=os.getenv("EVENT_STORE_API_KEY", ""),
                    source_service=f"teg-{self.teg_id}",
                )
            await self._emitter.emit(
                event_type="NegativeEscrowLockClamped",
                aggregate_id=agent_id,
                aggregate_type="AgentTEGProfile",
                data={
                    "agent_did": agent_id, "locked_before": str(locked_before),
                    "locked_after": "0", "teg_id": self.teg_id,
                    "reconciler_worker": self.worker_id,
                },
            )
        except Exception as e:
            logger.debug(f"[EscrowReconciler] negative-clamp audit emit failed: {e}")

    def _release_one(self, agent_id: str, detected_orphan: Decimal) -> Decimal:
        """Release one agent's orphaned escrow under a row lock, re-verifying safety.
        Returns the amount released (0 in dry-run / if conditions no longer hold)."""
        from ..database.models import AgentTEGProfile
        from sqlalchemy import select as _select

        session, gen = self._session()
        try:
            # §B-tag this txn so the journal/ES route the release to transit_net (Δ-safe).
            session.execute(text(
                "SELECT set_config('teg.entry_type','escrow_reconcile_release',true),"
                " set_config('teg.entry_ref',:r,true)"
            ), {"r": str(agent_id)[:160]})

            profile = session.execute(
                _select(AgentTEGProfile).where(AgentTEGProfile.agent_id == agent_id).with_for_update()
            ).scalar_one_or_none()
            if profile is None:
                self._close(gen)
                return Decimal("0")

            # Re-verify under lock: still pure-escrow + recompute orphan.
            stake_lock = Decimal(str(session.execute(_RECHECK_STAKE_SQL, {"aid": agent_id}).scalar() or 0))
            wrapped = Decimal(str(getattr(profile, "wrapped_balance", 0) or 0))
            inflight = Decimal(str(session.execute(_RECHECK_INFLIGHT_SQL, {"aid": agent_id}).scalar() or 0))
            locked = Decimal(str(profile.locked_balance or 0))
            orphan = locked - inflight

            if stake_lock > TOLERANCE or wrapped > 0:
                logger.info(f"[EscrowReconciler] {agent_id} no longer pure-escrow (stake={stake_lock} wrapped={wrapped}) — skip")
                session.rollback(); self._close(gen)
                return Decimal("0")
            if orphan <= TOLERANCE:
                session.rollback(); self._close(gen)
                return Decimal("0")
            # Circuit-breaker: never release more than the cap from one agent in one pass.
            if orphan > MAX_RELEASE_PER_AGENT:
                logger.warning(
                    f"[EscrowReconciler] {agent_id} orphan {orphan} exceeds MAX_RELEASE_PER_AGENT "
                    f"{MAX_RELEASE_PER_AGENT} — capping to the max this pass (investigate)."
                )
                orphan = MAX_RELEASE_PER_AGENT
            if orphan > locked:  # never underflow
                orphan = locked

            if DRY_RUN:
                logger.warning(
                    f"[EscrowReconciler][DRY_RUN] WOULD release {orphan} AVT phantom escrow from "
                    f"{agent_id} (locked {locked} → {locked - orphan}; stake=0 wrapped=0 inflight={inflight})"
                )
                session.rollback(); self._close(gen)
                return Decimal("0")

            profile.locked_balance = locked - orphan
            session.commit()
            logger.warning(
                f"[EscrowReconciler] RELEASED {orphan} AVT phantom escrow from {agent_id} "
                f"(locked {locked} → {locked - orphan})"
            )
            self._close(gen)
            # Best-effort audit event to the EventStore.
            asyncio.create_task(self._emit_audit(agent_id, orphan, locked, inflight))
            return orphan
        except Exception:
            try:
                session.rollback()
            except Exception:
                pass
            self._close(gen)
            raise

    async def _emit_audit(self, agent_id: str, released: Decimal, locked_before: Decimal, inflight: Decimal) -> None:
        try:
            if self._emitter is None:
                from ..event_emitter import EventEmitter
                self._emitter = EventEmitter(
                    event_store_url=os.getenv("EVENT_STORE_URL", "http://event-store:8200"),
                    internal_api_key=os.getenv("EVENT_STORE_API_KEY", ""),
                    source_service=f"teg-{self.teg_id}",
                )
            await self._emitter.emit(
                event_type="OrphanedEscrowLockReleased",
                aggregate_id=agent_id,
                aggregate_type="AgentTEGProfile",
                data={
                    "agent_did": agent_id, "released_avt": str(released),
                    "locked_before": str(locked_before), "locked_after": str(locked_before - released),
                    "inflight_excluded": str(inflight), "teg_id": self.teg_id,
                    "reconciler_worker": self.worker_id,
                },
            )
        except Exception as e:
            logger.debug(f"[EscrowReconciler] audit emit failed: {e}")

    def snapshot(self) -> Dict:
        return {
            "teg_id": self.teg_id, "worker_id": self.worker_id, "is_leader": self._is_leader_now,
            "enabled": ENABLED, "dry_run": DRY_RUN, "interval_sec": INTERVAL_SEC,
            "last_cycle_iso": self._last_cycle_iso, "last_stats": dict(self._last_stats),
        }


# ── Module-level singleton (mirrors the sweeper's start_/stop_ pattern) ──────────
_recon: Optional[EscrowLockReconciler] = None


def get_escrow_reconciler() -> Optional[EscrowLockReconciler]:
    return _recon


async def start_escrow_reconciler(teg_id: str, db_session_factory) -> None:
    global _recon
    if _recon is not None:
        return
    _recon = EscrowLockReconciler(teg_id, db_session_factory)
    await _recon.start()


async def stop_escrow_reconciler() -> None:
    global _recon
    if _recon is None:
        return
    await _recon.stop()
    _recon = None
