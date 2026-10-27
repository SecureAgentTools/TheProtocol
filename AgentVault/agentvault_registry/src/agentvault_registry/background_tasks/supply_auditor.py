"""
Background Task: Supply Auditor (Phase 2b — D-FED-11)

Runs every 60 seconds on every registry instance (not central-only).
Checks the global supply invariant:

    EventStore projection total ≈ Registry DB balance total

If delta exceeds BALANCE_TOLERANCE (1.0 AVT):
  - Emits SupplyInvariantBreach event to EventStore
  - If FEDERATION_ENFORCEMENT_ACTIVE=True: triggers EventStore lockdown

During beta (FEDERATION_ENFORCEMENT_ACTIVE=False):
  - Logs CRITICAL but does NOT trigger lockdown
  - Provides monitoring visibility without operational disruption

EventStore ground truth: GET {EVENT_STORE_URL}/api/v1/projections/balances
  Returns: { total_liquid: float, total_staked: float, agents: [...] }

Registry DB check: SELECT SUM(liquid_balance + staked_balance) FROM agents
"""
import asyncio
import logging
import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional

import httpx
from sqlalchemy import select, func

from ..database import get_db_context
from ..models import Agent
from ..event_emitter import get_event_emitter
from ..config import settings
from ..es_ssl_helper import get_httpx_verify  # prod-aligned dual-mode SSL
from ._worker_base import BackgroundWorker
from ..core.path_segment import seg  # §MCPTEST30 V0523: a caller's value is one path segment, encoded

logger = logging.getLogger(__name__)

AUDIT_INTERVAL_SECONDS = 60
BALANCE_TOLERANCE = Decimal("0.0")    # f037 Option 4: Zero tolerance — self-consistent ES audit has no race condition


# §pass28 Phase 4 — Prometheus metrics (lazy, best-effort).
try:
    from prometheus_client import Counter as _SACounter, Gauge as _SAGauge

    SUPPLY_AUDIT_CYCLE_TOTAL = _SACounter(
        "supply_audit_cycle_total",
        "Supply auditor cycles run (leader only)",
        labelnames=["registry_id"],
    )
    SUPPLY_AUDIT_BREACHES_TOTAL = _SACounter(
        "supply_audit_breaches_total",
        "Supply invariant breaches detected by the auditor",
        labelnames=["registry_id"],
    )
    SUPPLY_AUDIT_ERRORS_TOTAL = _SACounter(
        "supply_audit_errors_total",
        "Auditor cycle errors (HTTP, parse, etc.)",
        labelnames=["registry_id", "reason"],
    )
    SUPPLY_AUDIT_LAST_DELTA = _SAGauge(
        "supply_audit_last_delta",
        "Most recent audit's |delta| (the frame's unit). 0 == healthy.",
        labelnames=["registry_id"],
        multiprocess_mode="max",
    )
    SUPPLY_AUDIT_NET_SUPPLY = _SAGauge(
        "supply_audit_net_supply",
        "Most recent net_supply (tokens_issued - tokens_destroyed) in the frame's unit",
        labelnames=["registry_id"],
        multiprocess_mode="max",
    )
    SUPPLY_AUDIT_CIRCULATING = _SAGauge(
        "supply_audit_circulating",
        "Most recent total_circulating in the frame's unit",
        labelnames=["registry_id"],
        multiprocess_mode="max",
    )
except Exception:  # pragma: no cover
    SUPPLY_AUDIT_CYCLE_TOTAL = None
    SUPPLY_AUDIT_BREACHES_TOTAL = None
    SUPPLY_AUDIT_ERRORS_TOTAL = None
    SUPPLY_AUDIT_LAST_DELTA = None
    SUPPLY_AUDIT_NET_SUPPLY = None
    SUPPLY_AUDIT_CIRCULATING = None


_REGISTRY_ID_LABEL = os.getenv("REGISTRY_NAME", "registry-a")


# Most recent cycle stats — populated by _audit_cycle, read by snapshot().
_LAST_CYCLE_STATS: Dict[str, Any] = {
    "status": None,                  # "OK" | "BREACH" | "UNKNOWN" | None
    "delta": "0",                    # str-encoded Decimal
    "net_supply": "0",
    "total_circulating": "0",
    "tokens_issued": "0",
    "tokens_destroyed": "0",
    "tokens_fees": "0",
    "last_audit_iso": None,
    "consecutive_failures": 0,
}


class SupplyAuditor(BackgroundWorker):
    """
    Continuous supply invariant checker (§pass28 Phase 4: BackgroundWorker).
    Compares EventStore projection totals against Registry DB totals.
    """

    worker_id = "supply_auditor"
    leader_key = "supply_auditor"
    interval_sec = AUDIT_INTERVAL_SECONDS
    cold_start_delay_sec = 3

    def __init__(self):
        super().__init__()
        self._consecutive_failures = 0

    async def _cycle_once(self) -> None:
        await self._audit_cycle()
        self._stats = dict(_LAST_CYCLE_STATS)

    def _get_internal_key(self) -> str:
        """Read internal API key from environment (matches event_emitter.py logic)."""
        return os.getenv(
            "EVENT_STORE_API_KEY",
            os.getenv(
                "EVENT_STORE_INTERNAL_KEY",
                "",
            ),
        )

    async def _get_event_store_total(self) -> Optional[Decimal]:
        """
        Fetch total agent balances from EventStore /projections/balances.
        Excludes system treasury DIDs — treasury is a system reserve account,
        not a registered agent, so it must not be part of the supply invariant.
        Returns sum of all non-treasury agent balances as Decimal, or None on failure.
        """
        try:
            async with httpx.AsyncClient(timeout=5.0, verify=get_httpx_verify()) as client:
                resp = await client.get(
                    f"{settings.EVENT_STORE_URL}/api/v1/projections/balances",
                    headers={"X-Internal-Key": self._get_internal_key()},
                )

            if resp.status_code != 200:
                logger.warning(
                    f"[SupplyAuditor] EventStore /projections/balances "
                    f"returned {resp.status_code}"
                )
                return None

            data = resp.json()
            agents = data.get("agents", [])

            # Exclude treasury and system accounts from the invariant check.
            # Treasury is a system reserve that only exists in TEG, never as a
            # registered agent in the registry DB.
            excluded_prefixes = (
                "did:theprotocol:teg_system_treasury",
                "system",
            )
            total = Decimal("0")
            for agent in agents:
                agent_did = agent.get("agent_did", "")
                if agent_did.startswith(excluded_prefixes):
                    continue
                liquid = Decimal(str(agent.get("liquid_balance", 0)))
                staked = Decimal(str(agent.get("staked_balance", 0)))
                total += liquid + staked

            return total

        except Exception as exc:
            logger.warning(
                f"[SupplyAuditor] Failed to fetch EventStore totals: {exc}"
            )
            return None

    async def _get_registry_db_total(self) -> Optional[Decimal]:
        """
        Get total agent balances from Registry DB.
        f037: First syncs all agent balances from TEG to ensure DB cache is fresh.
        """
        try:
            async with get_db_context() as db:
                # f037: Sync all local agent balances from TEG before summing
                await self._sync_balances_from_teg(db)

                result = await db.execute(
                    select(func.sum(Agent.liquid_balance + Agent.staked_balance))
                )
                total = result.scalar()
                return Decimal(str(total or 0))
        except Exception as exc:
            logger.warning(
                f"[SupplyAuditor] Failed to fetch Registry DB totals: {exc}"
            )
            return None

    async def _sync_balances_from_teg(self, db) -> None:
        """
        f037: Sync all local agent balances from TEG (source of truth) to Registry DB.
        Ensures the DB cache is fresh before the invariant check.
        """
        teg_url = os.getenv("TEG_API_BASE_URL", "http://teg-layer:8080")
        teg_admin_key = os.getenv("TEG_ADMIN_API_KEY", "")
        if not teg_admin_key:
            return

        try:
            # Get all agents from DB
            result = await db.execute(select(Agent).where(Agent.status == "active"))
            agents = result.scalars().all()

            async with httpx.AsyncClient(timeout=8.0, verify=get_httpx_verify()) as client:
                for agent in agents:
                    try:
                        resp = await client.get(
                            f"{teg_url}/api/v1/agent/{seg(agent.did)}/teg-status",
                            headers={"Authorization": f"Bearer {teg_admin_key}"}
                        )
                        if resp.status_code == 200:
                            bal_data = resp.json()
                            teg_balance = Decimal(str(bal_data.get("balance", 0)))
                            if agent.liquid_balance != teg_balance:
                                agent.liquid_balance = teg_balance
                    except Exception:
                        pass  # Skip individual agent sync failures

                await db.commit()
                logger.debug(f"[SupplyAuditor] Synced {len(agents)} agent balances from TEG")
        except Exception as e:
            logger.debug(f"[SupplyAuditor] TEG balance sync failed (non-fatal): {e}")

    async def _trigger_eventstore_lockdown(self, reason: str) -> None:
        """POST to EventStore /api/v1/system/lockdown."""
        try:
            async with httpx.AsyncClient(timeout=5.0, verify=get_httpx_verify()) as client:
                resp = await client.post(
                    f"{settings.EVENT_STORE_URL}/api/v1/system/lockdown",
                    json={"reason": reason, "triggered_by": "supply_auditor"},
                    headers={"X-Internal-Key": self._get_internal_key()},
                )

            if resp.status_code == 200:
                logger.critical(
                    f"[SupplyAuditor] 🔒 EventStore LOCKDOWN triggered: {reason}"
                )
            else:
                logger.error(
                    f"[SupplyAuditor] Lockdown call failed: "
                    f"{resp.status_code} {resp.text}"
                )
        except Exception as exc:
            logger.error(f"[SupplyAuditor] Failed to trigger lockdown: {exc}")

    async def _get_local_agent_dids(self) -> Optional[set]:
        """Get the set of agent DIDs registered in this registry's local DB."""
        try:
            async with get_db_context() as db:
                result = await db.execute(select(Agent.did))
                return {row[0] for row in result.all() if row[0]}
        except Exception as exc:
            logger.warning(
                f"[SupplyAuditor] Failed to fetch local agent DIDs: {exc}"
            )
            return None

    async def _get_event_store_total_for_dids(self, local_dids: set) -> Optional[Decimal]:
        """
        Fetch EventStore balances but only sum agents that exist in this
        registry's local DB. In a shared EventStore topology, each registry
        must only audit its own agents to avoid false breach alerts.
        """
        try:
            async with httpx.AsyncClient(timeout=5.0, verify=get_httpx_verify()) as client:
                resp = await client.get(
                    f"{settings.EVENT_STORE_URL}/api/v1/projections/balances",
                    headers={"X-Internal-Key": self._get_internal_key()},
                )

            if resp.status_code != 200:
                logger.warning(
                    f"[SupplyAuditor] EventStore /projections/balances "
                    f"returned {resp.status_code}"
                )
                return None

            data = resp.json()
            agents = data.get("agents", [])

            excluded_prefixes = (
                "did:theprotocol:teg_system_treasury",
                "system",
            )
            total = Decimal("0")
            for agent in agents:
                agent_did = agent.get("agent_did", "")
                if agent_did.startswith(excluded_prefixes):
                    continue
                # Only count agents that belong to THIS registry
                if agent_did not in local_dids:
                    continue
                liquid = Decimal(str(agent.get("liquid_balance", 0)))
                staked = Decimal(str(agent.get("staked_balance", 0)))
                total += liquid + staked

            return total

        except Exception as exc:
            logger.warning(
                f"[SupplyAuditor] Failed to fetch EventStore totals: {exc}"
            )
            return None

    async def _audit_cycle(self) -> None:
        """
        Single audit cycle.

        f037 (Option 4): Self-consistent supply conservation check.
        Queries the EventStore's /supply-audit endpoint which verifies
        tokens_issued == tokens_circulating entirely within the ES.
        No cross-system comparison — no race condition.

        NOTE: The old cross-system check (ES vs Registry DB) is preserved
        in _audit_cycle_legacy() for future federated registry use — when
        dockerized registries ship to third parties, they'll need a local
        ES-vs-DB check as a first line of defense. Currently disabled.
        """
        # f037: Use self-consistent ES audit only. Legacy check disabled.
        # To re-enable legacy: uncomment _audit_cycle_legacy() call below.
        # await self._audit_cycle_legacy()
        try:
            async with httpx.AsyncClient(timeout=10.0, verify=get_httpx_verify()) as client:
                resp = await client.get(
                    f"{settings.EVENT_STORE_URL}/api/v1/projections/supply-audit",
                    headers={"X-Internal-Key": self._get_internal_key()},
                )

            if resp.status_code != 200:
                self._consecutive_failures += 1
                _LAST_CYCLE_STATS["consecutive_failures"] = self._consecutive_failures
                if SUPPLY_AUDIT_ERRORS_TOTAL is not None:
                    try:
                        SUPPLY_AUDIT_ERRORS_TOTAL.labels(
                            registry_id=_REGISTRY_ID_LABEL,
                            reason=f"http_{resp.status_code}",
                        ).inc()
                    except Exception:
                        pass
                if self._consecutive_failures >= 5:
                    # WARNING not ERROR — avoids tripping high-error-rate alerts
                    # on sandboxes where EventStore projections may not exist
                    logger.warning(
                        "[SupplyAuditor] EventStore supply-audit returned %s (%d consecutive)",
                        resp.status_code, self._consecutive_failures,
                    )
                return

            audit = resp.json()
            self._consecutive_failures = 0

            delta = Decimal(str(audit.get("delta", 0)))
            status = audit.get("status", "UNKNOWN")

            # §pass28 Phase 4 — record snapshot + bump metrics on every cycle.
            net_supply = audit.get("net_supply", 0)
            total_circulating = audit.get("total_circulating", 0)
            _LAST_CYCLE_STATS.update({
                "status": status,
                "delta": str(delta),
                "net_supply": str(net_supply),
                "total_circulating": str(total_circulating),
                "tokens_issued": str(audit.get("tokens_issued", 0)),
                "tokens_destroyed": str(audit.get("tokens_destroyed", 0)),
                "tokens_fees": str(audit.get("tokens_fees_collected", 0)),
                "last_audit_iso": datetime.now(timezone.utc).isoformat(),
                "consecutive_failures": 0,
            })
            if SUPPLY_AUDIT_CYCLE_TOTAL is not None:
                try:
                    SUPPLY_AUDIT_CYCLE_TOTAL.labels(registry_id=_REGISTRY_ID_LABEL).inc()
                    SUPPLY_AUDIT_LAST_DELTA.labels(registry_id=_REGISTRY_ID_LABEL).set(float(abs(delta)))
                    SUPPLY_AUDIT_NET_SUPPLY.labels(registry_id=_REGISTRY_ID_LABEL).set(float(net_supply))
                    SUPPLY_AUDIT_CIRCULATING.labels(registry_id=_REGISTRY_ID_LABEL).set(float(total_circulating))
                except Exception:
                    pass

            if status == "OK":
                logger.debug(
                    f"[SupplyAuditor] Supply OK — issued={audit.get('net_supply',0):.0f} "
                    f"circulating={audit.get('total_circulating',0):.0f} delta={delta}"
                )
                return

            # BREACH — supply conservation violated
            if SUPPLY_AUDIT_BREACHES_TOTAL is not None:
                try:
                    SUPPLY_AUDIT_BREACHES_TOTAL.labels(registry_id=_REGISTRY_ID_LABEL).inc()
                except Exception:
                    pass
            logger.critical(
                f"[SupplyAuditor] ⚠️  SUPPLY INVARIANT BREACH! "
                f"net_supply={audit.get('net_supply',0):.2f}, "
                f"circulating={audit.get('total_circulating',0):.2f}, "
                f"delta={delta}"
            )

            emitter = get_event_emitter()
            await emitter.emit(
                event_type="SupplyInvariantBreach",
                aggregate_id="system",
                aggregate_type="Registry",
                data={
                    "net_supply": str(audit.get("net_supply", 0)),
                    "total_circulating": str(audit.get("total_circulating", 0)),
                    "tokens_issued": str(audit.get("tokens_issued", 0)),
                    "tokens_destroyed": str(audit.get("tokens_destroyed", 0)),
                    "tokens_fees": str(audit.get("tokens_fees_collected", 0)),
                    "delta": str(delta),
                    "tolerance": "0.0",
                    "auto_lockdown": settings.FEDERATION_ENFORCEMENT_ACTIVE,
                    "detected_at": datetime.now(timezone.utc).isoformat(),
                    "audit_type": "self_consistent_es",
                },
            )

            if settings.FEDERATION_ENFORCEMENT_ACTIVE:
                await self._trigger_eventstore_lockdown(
                    reason=f"Supply invariant breach: delta={delta}"
                )
            else:
                logger.warning(
                    "[SupplyAuditor] ENFORCEMENT_INACTIVE: EventStore lockdown "
                    "NOT triggered. Set FEDERATION_ENFORCEMENT_ACTIVE=true to enable."
                )

        except Exception as exc:
            self._consecutive_failures += 1
            _LAST_CYCLE_STATS["consecutive_failures"] = self._consecutive_failures
            if SUPPLY_AUDIT_ERRORS_TOTAL is not None:
                try:
                    SUPPLY_AUDIT_ERRORS_TOTAL.labels(
                        registry_id=_REGISTRY_ID_LABEL, reason="audit_exception"
                    ).inc()
                except Exception:
                    pass
            logger.warning(f"[SupplyAuditor] Audit cycle failed: {exc}")
            if self._consecutive_failures >= 5:
                logger.error("[SupplyAuditor] 5+ consecutive failures")

    async def _audit_cycle_legacy(self) -> None:
        """
        LEGACY: Cross-system audit (ES projection vs Registry DB).
        Disabled in favor of self-consistent ES audit (Option 4).
        Preserved for future federated registry dockerized deployments
        where operators need a local ES-vs-DB check.
        """
        local_dids = await self._get_local_agent_dids()
        if not local_dids:
            return
        es_total = await self._get_event_store_total_for_dids(local_dids)
        if es_total is None:
            return
        reg_total = await self._get_registry_db_total()
        if reg_total is None:
            return
        delta = abs(es_total - reg_total)
        if delta > BALANCE_TOLERANCE:
            logger.warning(
                f"[SupplyAuditor:Legacy] ES={es_total}, DB={reg_total}, delta={delta}"
            )

    # `start()` / `stop()` are inherited from BackgroundWorker. Lifecycle
    # logging at start (interval/tolerance/enforcement) is preserved via
    # an override that wraps the base:
    async def start(self) -> None:
        logger.info(
            f"[SupplyAuditor] Started ({AUDIT_INTERVAL_SECONDS}-second interval). "
            f"Tolerance: {BALANCE_TOLERANCE} AVT. "
            f"Enforcement active: {settings.FEDERATION_ENFORCEMENT_ACTIVE}"
        )
        await super().start()


# ── Module-level singleton ────────────────────────────────────────────────────

_auditor: Optional[SupplyAuditor] = None


def get_supply_auditor() -> SupplyAuditor:
    global _auditor
    if _auditor is None:
        _auditor = SupplyAuditor()
    return _auditor


async def start_supply_auditor() -> None:
    """Called from main.py startup — always runs (not central-registry-only)."""
    await get_supply_auditor().start()


async def stop_supply_auditor() -> None:
    """Called from main.py shutdown."""
    await get_supply_auditor().stop()


def get_last_cycle_stats() -> Dict[str, Any]:
    """Read-only access to most recent audit stats (for admin endpoint)."""
    return dict(_LAST_CYCLE_STATS)
