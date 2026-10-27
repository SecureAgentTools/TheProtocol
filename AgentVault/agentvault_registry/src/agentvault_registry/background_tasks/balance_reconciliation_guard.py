"""
Background Task: Balance Reconciliation Guard (§pass73.3.19 L3b — AAA+ balance integrity BACKSTOP)
=================================================================================================
Thin, convergent safety-net that verifies the EventStore balance projection still equals the TEG
ledger — the declared source of truth (`agent_teg_profiles.token_balance`).

Under the CQRS outbox architecture (L1 journal → L2 outbox → LedgerBalanceChanged → single-writer
projection), `materialized_balances` equals TEG **by construction**, so this guard should find ZERO
drift. It exists to ALARM if that guarantee ever breaks (an L1/L2/projection bug or a re-baseline
race) and to optionally auto-heal small residue. It is NOT the primary mechanism — it is the backstop.

Each cycle, for each LOCAL non-system agent:
    drift = teg_liquid (truth, via /teg-status)  −  es_liquid (the RAW materialized_balances row)
Read source = `GET /api/v1/projections/materialized-balances` (the authoritative table verbatim) —
NOT get_all_balances(), whose zero-filtering + replay fallback caused the §pass73.3.19 non-convergence.

Converge-before-emit: a drift is acted on ONLY if it persisted across the PREVIOUS and CURRENT cycle
(same sign) — transient projection lag (drift gone next cycle) is ignored, so the guard never loops.

Correction (rare): under single-writer mode the projection ignores legacy BalanceCorrected events, so
the guard heals via `POST /api/v1/projections/resync-agent` (sets the projection row to TEG truth,
preserves staked, adjusts supply Δ-safe). Per-agent heal count is capped — if an agent needs healing
repeatedly it is escalated to manual review + WARN (a recurring heal means a real upstream gap to FIX,
not paper over).

Self-heal policy (Commander-locked 2026-05-29):
  - sandbox: BALANCE_RECONCILE_AUTO_MODE=all  → auto-heal any persistent drift.
  - prod:    BALANCE_RECONCILE_AUTO_MODE=threshold (factory default) → auto-heal |drift| <=
             BALANCE_RECONCILE_AUTO_APPROVE_MAX; larger → manual review.

Leader-elected via the shared BackgroundWorker/Redis framework (one active per process group).
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple

import httpx
from sqlalchemy import select, text

from ..database import get_db_context
from ..models import Agent
from ..config import settings
from ..es_ssl_helper import get_httpx_verify
from ._worker_base import BackgroundWorker
from ..core.path_segment import seg  # §MCPTEST30 V0523: a caller's value is one path segment, encoded

logger = logging.getLogger(__name__)

RECON_INTERVAL_SECONDS = int(os.getenv("BALANCE_RECONCILE_INTERVAL_SEC", "120"))
MAX_HEALS_PER_AGENT = int(os.getenv("BALANCE_RECONCILE_MAX_HEALS_PER_AGENT", "3"))
EPSILON = Decimal("0.000001")  # sub-micro-AVT noise floor; below this = matched

# System / non-agent accounts that legitimately diverge (genesis treasury, fee collector).
EXCLUDED_PREFIXES = (
    "did:theprotocol:teg_system_treasury",
    "teg:system:",
    "system",
)

# Last-cycle summary (mirrored to Redis by the base) — read by the admin API.
_LAST_RECON_STATS: Dict[str, Any] = {
    "last_cycle_iso": None,
    "agents_checked": 0,
    "drifted": 0,
    "persistent": 0,
    "transient": 0,
    "auto_healed": 0,
    "pending_review": 0,
    "max_abs_drift": "0",
    "total_abs_drift": "0",
}

# Prometheus (lazy, best-effort).
try:
    from prometheus_client import Counter as _Counter, Gauge as _Gauge

    RECON_CYCLE_TOTAL = _Counter(
        "balance_reconcile_cycle_total", "Reconciliation guard cycles run (leader only)",
        labelnames=["registry_id"])
    RECON_AUTO_CORRECTED_TOTAL = _Counter(
        "balance_reconcile_auto_corrected_total", "Persistent-drift resync heals applied",
        labelnames=["registry_id"])
    RECON_DRIFT_AGENTS = _Gauge(
        "balance_reconcile_drift_agents", "Agents with materialized≠TEG at last cycle",
        labelnames=["registry_id"])
    RECON_PERSISTENT_AGENTS = _Gauge(
        "balance_reconcile_persistent_agents", "Agents drifted across two consecutive cycles",
        labelnames=["registry_id"])
    RECON_PENDING_REVIEW = _Gauge(
        "balance_reconcile_pending_review", "Drift corrections awaiting manual review",
        labelnames=["registry_id"])
    RECON_MAX_DRIFT = _Gauge(
        "balance_reconcile_max_abs_drift", "Largest |TEG−materialized| at last cycle (the frame's unit)",
        labelnames=["registry_id"])
    _METRICS = True
except Exception:  # pragma: no cover
    _METRICS = False


# Idempotent review-queue table (registry DB). Above-threshold / recurring drift pending a human.
_REVIEW_DDL = """
CREATE TABLE IF NOT EXISTS balance_reconciliation_reviews (
    id            BIGSERIAL PRIMARY KEY,
    agent_did     VARCHAR(255) NOT NULL,
    teg_liquid    NUMERIC(36, 18) NOT NULL,
    es_liquid     NUMERIC(36, 18) NOT NULL,
    drift         NUMERIC(36, 18) NOT NULL,
    status        VARCHAR(24) NOT NULL DEFAULT 'pending',  -- pending | approved | rejected
    detected_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at   TIMESTAMPTZ,
    resolved_by   VARCHAR(255),
    note          TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_brr_agent_pending
    ON balance_reconciliation_reviews(agent_did) WHERE status = 'pending';
"""


def _default_policy() -> Dict[str, Any]:
    return {
        # OFF by default (opt-in per frame at cutover). Rolling the new image fleet-wide must NOT
        # auto-start the guard on prod registries before their ES is cut over — it would compare the
        # legacy (drifted) projection vs TEG and prematurely resync prod balances. Sandbox-A sets it
        # true explicitly in compose.
        "enabled": os.getenv("BALANCE_RECONCILE_ENABLED", "false").lower() in ("true", "1", "yes"),
        "auto_mode": os.getenv("BALANCE_RECONCILE_AUTO_MODE", "threshold"),
        "auto_approve_max": os.getenv("BALANCE_RECONCILE_AUTO_APPROVE_MAX", "10.0"),
    }


class BalanceReconciliationGuard(BackgroundWorker):
    worker_id = "balance_reconciliation_guard"
    leader_key = "balance_reconciliation_guard"
    interval_sec = RECON_INTERVAL_SECONDS
    cold_start_delay_sec = 15  # let projections settle after boot

    def __init__(self):
        super().__init__()
        self._review_table_ready = False
        # converge-before-emit state: did -> last-cycle drift (only |drift|>EPSILON entries)
        self._prev_drift: Dict[str, Decimal] = {}
        # per-agent lifetime heal count — escalate to review if it keeps needing healing
        self._heal_count: Dict[str, int] = {}

    async def _cycle_once(self) -> None:
        await self._reconcile_cycle()
        self._stats = dict(_LAST_RECON_STATS)

    def _internal_key(self) -> str:
        return os.getenv("EVENT_STORE_API_KEY", os.getenv("EVENT_STORE_INTERNAL_KEY", ""))

    def _es_base(self) -> str:
        # Use the DIRECT internal ES URL for bulk read + resync. The nginx https path (EVENT_STORE_URL)
        # 502s on the large all-agents materialized response (proxy buffers); the outbox already writes
        # direct for the same reason. Falls back to EVENT_STORE_URL if the public URL isn't set.
        return (os.getenv("EVENT_STORE_PUBLIC_URL") or settings.EVENT_STORE_URL).rstrip("/")

    async def _load_policy(self) -> Dict[str, Any]:
        # Env-only until the live-editable config table ships with the admin router.
        return _default_policy()

    async def _ensure_review_table(self) -> None:
        if self._review_table_ready:
            return
        try:
            async with get_db_context() as db:
                for stmt in _REVIEW_DDL.strip().split(";"):
                    if stmt.strip():
                        await db.execute(text(stmt))
                await db.commit()
            self._review_table_ready = True
        except Exception as exc:
            logger.warning(f"[ReconGuard] review-table init failed (non-fatal): {exc}")

    async def _local_dids(self) -> set:
        async with get_db_context() as db:
            res = await db.execute(select(Agent.did).where(Agent.status == "active"))
            return {r[0] for r in res.all() if r[0]}

    async def _es_balance_map(self) -> Optional[Dict[str, Tuple[Decimal, Decimal]]]:
        """RAW materialized_balances (the authoritative projection) → {did: (liquid, staked)}.
        Reads the dedicated raw endpoint, NOT get_all_balances() (which filtered zeros + fell back
        to replay — the original non-convergence root cause)."""
        try:
            async with httpx.AsyncClient(timeout=20.0, verify=get_httpx_verify()) as client:
                resp = await client.get(
                    f"{self._es_base()}/api/v1/projections/materialized-balances",
                    headers={"X-Internal-Key": self._internal_key()},
                )
            if resp.status_code != 200:
                logger.warning(f"[ReconGuard] ES /materialized-balances → {resp.status_code}")
                return None
            out: Dict[str, Tuple[Decimal, Decimal]] = {}
            for a in resp.json().get("agents", []):
                did = a.get("agent_did", "")
                if did:
                    out[did] = (Decimal(str(a.get("liquid_balance", 0))), Decimal(str(a.get("staked_balance", 0))))
            return out
        except Exception as exc:
            logger.warning(f"[ReconGuard] ES materialized-balances fetch failed: {exc}")
            return None

    async def _teg_liquid(self, client: httpx.AsyncClient, teg_url: str, teg_key: str, did: str) -> Optional[Decimal]:
        try:
            resp = await client.get(
                f"{teg_url}/api/v1/agent/{seg(did)}/teg-status",
                headers={"Authorization": f"Bearer {teg_key}"},
            )
            if resp.status_code != 200:
                return None
            return Decimal(str(resp.json().get("balance", 0)))
        except Exception:
            return None

    async def _resync(self, did: str, teg_liquid: Decimal, keep_staked: Decimal) -> bool:
        """Δ-safe targeted heal: set materialized[did].liquid = TEG truth, preserve staked.
        (Under single-writer the projection ignores BalanceCorrected, so we fix the row directly.)"""
        try:
            async with httpx.AsyncClient(timeout=10.0, verify=get_httpx_verify()) as client:
                resp = await client.post(
                    f"{self._es_base()}/api/v1/projections/resync-agent",
                    headers={"X-Internal-Key": self._internal_key()},
                    json={"agent_did": did, "liquid_balance": str(teg_liquid), "staked_balance": str(keep_staked)},
                )
            return resp.status_code == 200
        except Exception as exc:
            logger.warning(f"[ReconGuard] resync failed for {did[-12:]}: {exc}")
            return False

    async def _queue_review(self, did: str, teg_liquid: Decimal, es_liquid: Decimal, drift: Decimal) -> None:
        try:
            async with get_db_context() as db:
                await db.execute(text("""
                    INSERT INTO balance_reconciliation_reviews (agent_did, teg_liquid, es_liquid, drift)
                    VALUES (:did, :teg, :es, :drift)
                    ON CONFLICT (agent_did) WHERE status='pending'
                    DO UPDATE SET teg_liquid=:teg, es_liquid=:es, drift=:drift, detected_at=now()
                """), {"did": did, "teg": str(teg_liquid), "es": str(es_liquid), "drift": str(drift)})
                await db.commit()
        except Exception as exc:
            logger.warning(f"[ReconGuard] queue_review failed for {did[-12:]}: {exc}")

    async def _reconcile_cycle(self) -> None:
        rid = self._registry_id  # base sets this (str) from REGISTRY_NAME env
        if _METRICS:
            RECON_CYCLE_TOTAL.labels(registry_id=rid).inc()

        policy = await self._load_policy()
        if not policy.get("enabled", True):
            return
        await self._ensure_review_table()

        auto_mode = policy.get("auto_mode", "threshold")
        try:
            auto_max = Decimal(str(policy.get("auto_approve_max", "10.0")))
        except Exception:
            auto_max = Decimal("10.0")

        local = await self._local_dids()
        es = await self._es_balance_map()
        if es is None or not local:
            return

        teg_url = os.getenv("TEG_API_BASE_URL", "http://teg-layer:8080")
        teg_key = os.getenv("TEG_ADMIN_API_KEY", "")
        if not teg_key:
            logger.warning("[ReconGuard] no TEG_ADMIN_API_KEY — cannot read source of truth")
            return

        targets = [d for d in local if not any(d.startswith(p) for p in EXCLUDED_PREFIXES)]
        BATCH = 50

        # Phase 1: read TEG truth (parallel) → current drift map (liquid axis).
        checked = 0
        cur_drift: Dict[str, Decimal] = {}
        teg_liq_map: Dict[str, Decimal] = {}
        async with httpx.AsyncClient(timeout=8.0, verify=get_httpx_verify()) as client:
            for i in range(0, len(targets), BATCH):
                chunk = targets[i:i + BATCH]
                fetched = await asyncio.gather(
                    *(self._teg_liquid(client, teg_url, teg_key, did) for did in chunk),
                    return_exceptions=True,
                )
                for did, teg_liquid in zip(chunk, fetched):
                    if isinstance(teg_liquid, BaseException) or teg_liquid is None:
                        continue
                    checked += 1
                    es_liquid, _ = es.get(did, (Decimal("0"), Decimal("0")))
                    drift = teg_liquid - es_liquid
                    if abs(drift) > EPSILON:
                        cur_drift[did] = drift
                        teg_liq_map[did] = teg_liquid

        # Phase 2: converge-before-emit — act only on drift that PERSISTED across both cycles (same sign).
        persistent = {
            did: d for did, d in cur_drift.items()
            if did in self._prev_drift and ((self._prev_drift[did] > 0) == (d > 0))
        }
        transient = len(cur_drift) - len(persistent)

        max_abs = max((abs(d) for d in cur_drift.values()), default=Decimal("0"))
        total_abs = sum((abs(d) for d in cur_drift.values()), Decimal("0"))
        healed = pending = 0

        # Phase 3: heal small persistent drift (rare) / escalate big-or-recurring to review.
        for did, drift in persistent.items():
            adrift = abs(drift)
            teg_liquid = teg_liq_map[did]
            es_liquid, es_staked = es.get(did, (Decimal("0"), Decimal("0")))
            prior_heals = self._heal_count.get(did, 0)
            auto = (auto_mode == "all") or (adrift <= auto_max)
            if auto and prior_heals < MAX_HEALS_PER_AGENT:
                if await self._resync(did, teg_liquid, es_staked):
                    healed += 1
                    self._heal_count[did] = prior_heals + 1
                    if _METRICS:
                        RECON_AUTO_CORRECTED_TOTAL.labels(registry_id=rid).inc()
                    logger.warning(
                        f"[ReconGuard] resync-heal {did[-12:]}: ES liquid {es_liquid} → {teg_liquid} "
                        f"(Δ{drift}) [heal #{prior_heals + 1}] — by-construction guarantee slipped; investigate L1/L2 if recurring")
                else:
                    await self._queue_review(did, teg_liquid, es_liquid, drift)
                    pending += 1
            else:
                await self._queue_review(did, teg_liquid, es_liquid, drift)
                pending += 1
                reason = "exceeds auto_max" if not auto else f"recurring (>{MAX_HEALS_PER_AGENT} heals)"
                logger.warning(
                    f"[ReconGuard] MANUAL REVIEW {did[-12:]}: drift {drift} {reason} "
                    f"(ES {es_liquid} vs TEG {teg_liquid}) — queued; FIX upstream L1/L2 gap")

        # Phase 4: remember this cycle's drift for the next convergence check.
        self._prev_drift = cur_drift

        _LAST_RECON_STATS.update({
            "last_cycle_iso": datetime.now(timezone.utc).isoformat(),
            "agents_checked": checked,
            "drifted": len(cur_drift),
            "persistent": len(persistent),
            "transient": transient,
            "auto_healed": healed,
            "pending_review": pending,
            "max_abs_drift": str(max_abs),
            "total_abs_drift": str(total_abs),
        })
        if _METRICS:
            RECON_DRIFT_AGENTS.labels(registry_id=rid).set(float(len(cur_drift)))
            RECON_PERSISTENT_AGENTS.labels(registry_id=rid).set(float(len(persistent)))
            RECON_PENDING_REVIEW.labels(registry_id=rid).set(float(pending))
            RECON_MAX_DRIFT.labels(registry_id=rid).set(float(max_abs))
        if cur_drift or healed or pending:
            logger.info(
                f"[ReconGuard] cycle: checked={checked} drifted={len(cur_drift)} "
                f"persistent={len(persistent)} transient={transient} healed={healed} "
                f"pending={pending} max|Δ|={max_abs}")


# ── Module-level singleton (mirrors supply_auditor) ────────────────────────────
_guard: Optional[BalanceReconciliationGuard] = None


def get_balance_reconciliation_guard() -> BalanceReconciliationGuard:
    global _guard
    if _guard is None:
        _guard = BalanceReconciliationGuard()
    return _guard


async def start_balance_reconciliation_guard() -> None:
    logger.info(
        f"[ReconGuard] Started ({RECON_INTERVAL_SECONDS}s interval, converge-before-emit). "
        f"Backstop: reads RAW materialized_balances vs TEG truth; heals via Δ-safe resync.")
    await get_balance_reconciliation_guard().start()


async def stop_balance_reconciliation_guard() -> None:
    g = get_balance_reconciliation_guard()
    await g.stop()
