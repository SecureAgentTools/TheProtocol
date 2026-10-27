"""
OPA shadow-mode comparison helper.

Sandbox-only since 2026-04-30. Compares Python authz decisions against OPA
policy decisions, logs the result for observability, increments Prometheus
counters (drop in for free when sandbox eventually gets a scraper), and —
when ``OPA_ENFORCE=true`` AND ``OPA_ENABLED=true`` — lets OPA tighten the
Python decision (Python AND OPA must allow). Default is shadow-only.

Defensive design: any error path falls back to ``python_decision``. Python
authz remains authoritative until Commander explicitly flips enforce on.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from collections import deque
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from agentvault_registry import opa_client

logger = logging.getLogger(__name__)

# ── §29 decision ring (2026-07-28) ───────────────────────────────────────────
# Bounded in-process history of shadow decisions INCLUDING the input that produced each.
# Prometheus keeps the totals; this keeps the evidence. Per-worker by construction (38
# gunicorn workers on a mainframe => a read samples one worker's view, which is honest for
# a divergence board and fine for a simulator corpus). Never persisted, never a DB write.
_RING_MAX = int(os.getenv("OPA_DECISION_RING", "500"))
_RING: "deque[Dict[str, Any]]" = deque(maxlen=_RING_MAX)


# ── Redis mirror (2026-07-28) ────────────────────────────────────────────────
# The in-process ring is PER-WORKER: with 32-38 gunicorn workers a console read samples ONE
# worker, so counts jump (observed 0/3/11/22) and a simulator corpus is a fraction of the real
# window. Mirroring into a Redis LIST gives every worker the same view, which is what the
# divergence board and the enforce-simulator actually need. Reuses the registry's existing Redis
# (already used for WS broadcast, the shared rate-limiter and RedisSyncDict).
# STRICTLY best-effort: fire-and-forget, every failure swallowed, and the local deque remains the
# fallback. An observability buffer must never be able to break an authz path.
_REDIS_KEY = os.getenv("OPA_DECISION_REDIS_KEY", "registry:opa:decisions")
_REDIS_ENABLED = os.getenv("OPA_DECISION_REDIS", "1").strip().lower() not in ("0", "false", "no")


async def _mirror_to_redis(entry: Dict[str, Any]) -> None:
    """LPUSH + LTRIM so the list self-caps at _RING_MAX. Never raises."""
    if not _REDIS_ENABLED:
        return
    try:
        from agentvault_registry.background_tasks.leader import get_redis
        r = await get_redis()
        if r is None:
            return
        pipe = r.pipeline()
        pipe.lpush(_REDIS_KEY, json.dumps(entry, default=str))
        pipe.ltrim(_REDIS_KEY, 0, _RING_MAX - 1)
        await pipe.execute()
    except Exception as exc:  # pragma: no cover
        logger.debug(f"[OPA-SHADOW] redis mirror failed (non-fatal): {exc!r}")


async def redis_decisions(limit: int = 200) -> Optional[list]:
    """Fleet-wide (all-worker) view, newest-first. None when Redis is unavailable so the caller
    can fall back to the local ring and SAY SO rather than silently show a partial window."""
    if not _REDIS_ENABLED:
        return None
    try:
        from agentvault_registry.background_tasks.leader import get_redis
        r = await get_redis()
        if r is None:
            return None
        raw = await r.lrange(_REDIS_KEY, 0, max(1, min(limit, _RING_MAX)) - 1)
        out = []
        for item in raw or []:
            try:
                out.append(json.loads(item))
            except Exception:
                continue
        return out
    except Exception as exc:
        logger.debug(f"[OPA-SHADOW] redis read failed (non-fatal): {exc!r}")
        return None


def _record_decision(policy_path, label, input_data, python_decision, opa_decision,
                     match, latency_ms) -> None:
    """Append one decision to the ring. Never raises — an observability buffer must not be
    able to break an authz path."""
    try:
        _RING.append({
            "ts": datetime.now(timezone.utc).isoformat(),
            "policy": policy_path,
            "label": label,
            "input": dict(input_data) if isinstance(input_data, dict) else {},
            "python": python_decision,
            "opa": opa_decision,
            "match": match,
            "latency_ms": latency_ms,
        })
        # Fire-and-forget so the mirror never sits on the caller's path.
        try:
            asyncio.get_running_loop().create_task(_mirror_to_redis(_RING[-1]))
        except RuntimeError:
            pass  # no running loop (sync context) -> local ring only, still correct
    except Exception as exc:  # pragma: no cover
        logger.debug(f"[OPA-SHADOW] ring append failed (non-fatal): {exc!r}")


def recent_decisions(limit: int = 200) -> list:
    """Newest-first snapshot for the admin API."""
    items = list(_RING)[-max(1, min(limit, _RING_MAX)):]
    return list(reversed(items))


def stats_for(items: list) -> Dict[str, Any]:
    """Divergence summary over ANY decision list (redis or worker-local)."""
    total = len(items)
    mismatches = sum(1 for i in items if i.get("match") is False)
    errors = sum(1 for i in items if i.get("opa") is None)
    lat = [i["latency_ms"] for i in items if isinstance(i.get("latency_ms"), (int, float))]
    return {
        "retained": total,
        "capacity": _RING_MAX,
        "mismatches": mismatches,
        "opa_errors": errors,
        "agreement_pct": (round(100.0 * (total - mismatches - errors) / total, 4) if total else None),
        "latency_ms_avg": (round(sum(lat) / len(lat), 2) if lat else None),
        "latency_ms_max": (round(max(lat), 2) if lat else None),
    }

# §2026-06-21 — hold references to fire-and-forget shadow-observation tasks so the
# event loop doesn't GC them mid-flight (idiomatic create_task pattern).
_SHADOW_TASKS: set = set()

# ── Prometheus counters ──────────────────────────────────────────────────
# First Counter/Histogram in the registry (Gauge precedent: agent_mtls.py:40).
# Sandbox-test runs --workers 2 without PROMETHEUS_MULTIPROC_DIR so values
# are per-worker; that's fine for ad-hoc curl-based smoke tests since there
# is no Prometheus scraper on sandbox anyway. Production registries set
# OPA_ENABLED=false so these will only ever be touched on sandbox.
try:
    from prometheus_client import Counter, Histogram

    OPA_DECISIONS_TOTAL = Counter(
        "opa_decisions_total",
        "OPA shadow-mode decisions",
        labelnames=["policy", "decision", "source"],
    )
    OPA_DECISION_LATENCY = Histogram(
        "opa_decision_latency_seconds",
        "OPA shadow-mode query latency",
        labelnames=["policy"],
        buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0),
    )
    _PROM_AVAILABLE = True
except ImportError:  # pragma: no cover — prometheus_client is in requirements
    _PROM_AVAILABLE = False
    OPA_DECISIONS_TOTAL = None  # type: ignore[assignment]
    OPA_DECISION_LATENCY = None  # type: ignore[assignment]


def opa_enforce() -> bool:
    """Stacked-flag: enforce only honored when OPA_ENABLED=true."""
    if not opa_client.opa_enabled():
        return False
    return os.getenv("OPA_ENFORCE", "false").lower() == "true"


def _decision_label(decision: Optional[bool]) -> str:
    if decision is True:
        return "allow"
    if decision is False:
        return "deny"
    return "error"


async def shadow_check(
    policy_path: str,
    input_data: Dict[str, Any],
    python_decision: bool,
    label: str,
) -> bool:
    """
    Compare Python decision against OPA decision. Return the effective decision.

    In shadow mode (default): always returns ``python_decision``. OPA is observed
    but never overrides Python. Mismatches are logged + counted.

    In enforce mode (OPA_ENABLED=true AND OPA_ENFORCE=true) AND OPA returned a
    boolean: returns ``python_decision AND opa_decision``. Both must allow. If
    OPA is unreachable the result falls back to ``python_decision`` (fail-open
    on shadow infrastructure error — Commander flips this later if desired).

    Never raises. Any failure inside this function is logged at debug and the
    function returns ``python_decision`` unchanged so request flow is preserved.

    ``label`` is a free-form tag (e.g. flag name, endpoint group) included in
    the structured log line for triage.
    """
    try:
        # Kill-switch fast path: true no-op. No counters, no logs, no httpx.
        if not opa_client.opa_enabled():
            return python_decision

        # Python decision counter — only when OPA is enabled.
        if _PROM_AVAILABLE:
            OPA_DECISIONS_TOTAL.labels(
                policy=policy_path,
                decision=_decision_label(python_decision),
                source="python",
            ).inc()

        async def _observe() -> Optional[bool]:
            """Query OPA, emit counters + the [OPA-SHADOW] log line, surface the
            decision into the per-request MCP audit contextvar. Returns OPA's boolean
            (or None). Touches NO database connection, so it is safe to run detached as
            a fire-and-forget background task in shadow mode."""
            body = await opa_client.query_opa(policy_path, input_data)
            opa_decision: Optional[bool]
            latency_ms: Optional[float] = None
            if isinstance(body, dict):
                raw = body.get("result")
                opa_decision = bool(raw) if isinstance(raw, bool) else None
                latency_ms = body.get("_latency_ms")
            else:
                opa_decision = None

            # OPA-side counter + latency.
            if _PROM_AVAILABLE:
                if opa_decision is None:
                    OPA_DECISIONS_TOTAL.labels(
                        policy=policy_path, decision="error", source="opa"
                    ).inc()
                else:
                    OPA_DECISIONS_TOTAL.labels(
                        policy=policy_path,
                        decision=_decision_label(opa_decision),
                        source="opa",
                    ).inc()
                if latency_ms is not None:
                    OPA_DECISION_LATENCY.labels(policy=policy_path).observe(latency_ms / 1000.0)

            match = (
                (opa_decision == python_decision) if isinstance(opa_decision, bool) else None
            )
            # §29 2026-07-28 — retain the decision WITH its input in a bounded in-process ring.
            # Counters carry totals but discard the input, and the input is precisely what the
            # divergence board and the enforce-impact simulator need: you cannot answer "what
            # breaks if I enforce this" by replaying a number. Bounded + in-memory on purpose:
            # no DB write on an authz path, and nothing to prune.
            _record_decision(policy_path, label, input_data, python_decision, opa_decision,
                             match, latency_ms)
            if _PROM_AVAILABLE and match is False:
                OPA_DECISIONS_TOTAL.labels(
                    policy=policy_path, decision=_decision_label(opa_decision), source="mismatch"
                ).inc()

            # Structured log — primary observability for sandbox (no Prom scraper there).
            logger.info(
                "[OPA-SHADOW] policy=%s label=%s python=%s opa=%s match=%s latency_ms=%s",
                policy_path,
                label,
                python_decision,
                "null" if opa_decision is None else str(opa_decision).lower(),
                "null" if match is None else str(match).lower(),
                "null" if latency_ms is None else f"{latency_ms:.1f}",
            )

            # §pass68 — surface this shadow decision into the per-request contextvar so
            # the MCP audit writer (mcp/audit.py) can include it. (In shadow fire-and-
            # forget the task runs in a copied context, so this is best-effort for the
            # audit row; the [OPA-SHADOW] log line above always carries it.)
            try:
                from .mcp.audit import mcp_opa_decision_var  # local import
                mcp_opa_decision_var.set({
                    "policy": policy_path,
                    "label": label,
                    "python": python_decision,
                    "opa": None if opa_decision is None else bool(opa_decision),
                    "match": match,
                    "latency_ms": None if latency_ms is None else round(latency_ms, 2),
                })
            except Exception:
                pass
            return opa_decision

        # ENFORCE mode (OPA_ENABLED && OPA_ENFORCE): the OPA decision is needed
        # synchronously to tighten the Python decision, so await it inline. Not active
        # in prod (OPA_ENFORCE=false). When enabled, the caller should release the
        # request's DB txn before this so even enforce never holds a connection across
        # the OPA network call.
        if opa_enforce():
            opa_decision = await _observe()
            if isinstance(opa_decision, bool):
                return python_decision and opa_decision
            return python_decision

        # SHADOW mode (default, LIVE on registry-a): FIRE-AND-FORGET. §2026-06-21 —
        # shadow observation must never sit on the request's critical path. Running it
        # inline held the request's DB transaction across the OPA call (added latency
        # now; idle-in-transaction reaps if OPA ever degrades past its 1s timeout). The
        # request returns python_decision immediately; the OPA observation runs detached
        # (it touches no DB connection).
        _t = asyncio.create_task(_observe())
        _SHADOW_TASKS.add(_t)
        _t.add_done_callback(_SHADOW_TASKS.discard)
        return python_decision
    except Exception as exc:
        # Defense in depth: a bug in shadow_check must never affect request flow.
        logger.debug(f"shadow_check suppressed error: {exc!r}")
        return python_decision


def ring_stats() -> Dict[str, Any]:
    """Worker-local summary (kept for callers that explicitly want this worker's view)."""
    return stats_for(list(_RING))


async def fleet_stats() -> Dict[str, Any]:
    """All-worker summary when Redis is reachable, else this worker's. `scope` says which, so a
    console never presents a one-worker sample as the whole picture."""
    items = await redis_decisions(_RING_MAX)
    if items is None:
        out = stats_for(list(_RING)); out["scope"] = "worker-local"; return out
    out = stats_for(items); out["scope"] = "fleet"; return out
