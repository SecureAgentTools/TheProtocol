"""MCP Tester admin router (Phase 5 + 6) — frontend-facing wrapper around
the `flow_mcp_lifecycle_complete` regression suite.

The MCP Tester is SANDBOX-ONLY: regardless of which registry hosts this
router, the underlying flow always targets `agentvault_registry_test`
(port 8002). The existing /admin/api-test/test-flow endpoint already
enforces that via `API_TEST_TARGET_URL` + the runner's hard-coded
`get_target("sandbox")` call.

This router adds an async-runtime layer:
  - POST /admin/mcp-tester/run         → spawn background sweep, return run_id
  - GET  /admin/mcp-tester/runs        → list recent runs
  - GET  /admin/mcp-tester/runs/{id}   → poll a single run
  - GET  /admin/mcp-tester/runs/{id}/stream  → SSE: live log lines
  - GET  /admin/mcp-tester/latest      → last completed run summary

Auth: admin developer JWT (is_admin=True). Frontend route is admin-only.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import ssl
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import aiohttp
import httpx
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Security, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from urllib.parse import quote, urlparse
import jwt  # PyJWT (§DEPS: python-jose is gone)
from jwt import PyJWTError as JWTError

from agentvault_registry import models, security
from agentvault_registry.background_tasks.leader import get_redis
from agentvault_registry.core import ledger_names   # W4: an event's old and new names are one event
from agentvault_registry.core.policy_marks import POLICY_DENIED_MARK as _POLICY_DENIED_MARK
from agentvault_registry.crud import developer as developer_crud
from agentvault_registry.database import get_db
from agentvault_registry.es_ssl_helper import get_es_ssl_context

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prometheus instrumentation (2026-05-26 strict-mode roll)
# ---------------------------------------------------------------------------
# `mcp_tester_strict_pass_rate{target,frame}` — fraction of tools healthy in
# the last completed sweep on this target. Auto-alerts if pass rate drops
# below baseline after a deploy. Companion gauges track raw totals + the
# strict-mode failure categories so we can attribute regressions.
try:
    from prometheus_client import Gauge as _Gauge, Counter as _Counter

    # §MCPTEST30 V0536: every series names its suite (`flow`). The console runs several suites against one target
    # (the MCP sweep, the federation suite, the two cloud-op sweeps) and they live on different floors (round 10: 97.7 %,
    # 99.5 %, 87.7 %), so a gauge keyed by target alone read whichever suite ran last: a per-environment threshold would
    # have fired on every change of suite.
    MCP_TESTER_PASS_RATE = _Gauge(
        "mcp_tester_strict_pass_rate",
        "Fraction (0-1) of MCP tools healthy in the last completed sweep (strict mode).",
        labelnames=["target", "frame", "flow"],
    )
    MCP_TESTER_TOTAL = _Gauge(
        "mcp_tester_last_total",
        "Total MCP tools exercised in the last sweep.",
        labelnames=["target", "frame", "flow"],
    )
    MCP_TESTER_HEALTHY = _Gauge(
        "mcp_tester_last_healthy",
        "Number of healthy tools in the last sweep.",
        labelnames=["target", "frame", "flow"],
    )
    MCP_TESTER_TIER_DRIFT = _Gauge(
        "mcp_tester_last_tier_drift",
        "Tools that surfaced auth-tier drift in the last sweep.",
        labelnames=["target", "frame", "flow"],
    )
    MCP_TESTER_CONTRACT_GAP = _Gauge(
        "mcp_tester_last_contract_gap",
        "Tools that failed with 'contract gap' (no shape assertion possible).",
        labelnames=["target", "frame", "flow"],
    )
    # ── Phase F gauges (Gap-1, Gap-2, Gap-4, Gap-3) ─────────────────────
    MCP_TESTER_AUTH_MATRIX_VIOLATIONS = _Gauge(
        "mcp_tester_last_auth_matrix_violations",
        "Tools that accepted wrong-tier auth (privilege-escalation regression).",
        labelnames=["target", "frame", "flow"],
    )
    MCP_TESTER_CROSS_FRAME_DRIFT = _Gauge(
        "mcp_tester_last_cross_frame_drift",
        "Tools where Frame A and Frame B response shapes differ.",
        labelnames=["target", "frame", "flow"],
    )
    MCP_TESTER_LATENCY_REGRESSIONS = _Gauge(
        "mcp_tester_last_latency_regressions",
        "Tools that ran 2x slower than the prior-3 median baseline.",
        labelnames=["target", "frame", "flow"],
    )
    MCP_TESTER_WRAPPER_DRIFT = _Gauge(
        "mcp_tester_last_wrapper_drift",
        "Wrappers whose inputSchema diverges from the FastAPI route signature.",
        labelnames=["target", "frame", "flow"],
    )
    # ── emission_integrity HONESTY flag (2026-06-26) ───────────────────
    # The strict pass-rate can read 98%+/0-fail while cross-frame settlement
    # is silently dead (initiate-only ES assertions + LOCAL-only shape diffs).
    # This gauge surfaces a DEGRADED/WARN signal the pass-rate can't see.
    #   0 = ok · 1 = warn (couldn't verify) · 2 = degraded (integrity broken)
    MCP_TESTER_EMISSION_INTEGRITY = _Gauge(
        "mcp_tester_last_emission_integrity",
        "Emission/cross-frame integrity of the last sweep (0=ok, 1=warn, 2=degraded).",
        labelnames=["target", "frame", "flow"],
    )
    MCP_TESTER_RUNS = _Counter(
        "mcp_tester_runs_total",
        "Number of MCP tester sweeps started.",
        labelnames=["target", "frame", "flow", "outcome"],   # outcome: completed|failed
    )
    _MCP_PROM_AVAILABLE = True
except ImportError:  # pragma: no cover
    _MCP_PROM_AVAILABLE = False
    MCP_TESTER_PASS_RATE = None      # type: ignore[assignment]
    MCP_TESTER_TOTAL = None           # type: ignore[assignment]
    MCP_TESTER_HEALTHY = None         # type: ignore[assignment]
    MCP_TESTER_TIER_DRIFT = None      # type: ignore[assignment]
    MCP_TESTER_CONTRACT_GAP = None    # type: ignore[assignment]
    MCP_TESTER_EMISSION_INTEGRITY = None  # type: ignore[assignment]
    MCP_TESTER_RUNS = None            # type: ignore[assignment]


def _emit_mcp_metrics(target: str, frame: str, summary: dict, *, flow: str) -> None:
    """Write strict-mode sweep summary into Prometheus gauges/counters.

    Safe to call even when prometheus_client isn't installed (no-ops).
    """
    if not _MCP_PROM_AVAILABLE:
        return
    try:
        total = int(summary.get("total", 0) or 0)
        healthy = int(summary.get("healthy", 0) or 0)
        tier_drift = int(summary.get("tier_drift", 0) or 0)
        contract_gap = int(summary.get("contract_gap", 0) or 0)
        rate = (healthy / total) if total > 0 else 0.0
        MCP_TESTER_PASS_RATE.labels(target=target, frame=frame, flow=flow).set(rate)
        MCP_TESTER_TOTAL.labels(target=target, frame=frame, flow=flow).set(total)
        MCP_TESTER_HEALTHY.labels(target=target, frame=frame, flow=flow).set(healthy)
        MCP_TESTER_TIER_DRIFT.labels(target=target, frame=frame, flow=flow).set(tier_drift)
        MCP_TESTER_CONTRACT_GAP.labels(target=target, frame=frame, flow=flow).set(contract_gap)
        # Phase F gauges
        MCP_TESTER_AUTH_MATRIX_VIOLATIONS.labels(target=target, frame=frame, flow=flow).set(
            int(summary.get("auth_matrix_violations", 0) or 0))
        MCP_TESTER_CROSS_FRAME_DRIFT.labels(target=target, frame=frame, flow=flow).set(
            int(summary.get("cross_frame_drift", 0) or 0))
        MCP_TESTER_LATENCY_REGRESSIONS.labels(target=target, frame=frame, flow=flow).set(
            int(summary.get("latency_regressions", 0) or 0))
        MCP_TESTER_WRAPPER_DRIFT.labels(target=target, frame=frame, flow=flow).set(
            int(summary.get("wrapper_drift", 0) or 0))
        # emission_integrity HONESTY flag (2026-06-26): ok=0 / warn=1 / degraded=2.
        if MCP_TESTER_EMISSION_INTEGRITY is not None:
            _integrity_map = {"ok": 0, "warn": 1, "degraded": 2}
            MCP_TESTER_EMISSION_INTEGRITY.labels(target=target, frame=frame, flow=flow).set(
                _integrity_map.get(
                    str(summary.get("emission_integrity_status", "ok")).lower(), 0))
    except Exception as e:
        logger.debug(f"[mcp-tester] prom emit failed: {e!r}")


def vacuity_verdict(summary, flow_error, target):
    """None when the sweep really measured something; otherwise the sentence that says it did not.

    §EVTYPES gave this a floor on `tool_count <= 0` — a sweep that listed nothing. 2026-09-23 found the other half:
    the nightly federation run listed **572** tools and JUDGED none of them (passed 0, failed 0, skipped 572), because
    a rotated operator password had been left behind in one of its carriers. `tool_count` counts the roster, not the
    work, so the floor stayed silent and the run was stored `status: completed, error: null` — a refusal filed as a
    clean night. The predicate that matters is *how many did you judge*, not *how many did you intend to*.

    And the reason already existed: the suite's own result carries it (`credential preflight failed for 1 of 8
    registry/ies … password_env=API_TEST_FED_ALPHA_PASSWORD`), and the caller threw it away by overwriting `error`
    with None. So the only surviving copy was a log line in the TARGET registry — the sweep is dispatched to the
    target and its python runs THERE, which is why the console that launched it had zero `[FederationSuite]` lines
    to show. Carry the flow's own sentence; never make an operator guess which container to read.
    """
    measured = int((summary or {}).get("tool_count") or 0)
    judged = int((summary or {}).get("passed") or 0) + int((summary or {}).get("failed") or 0)
    if measured <= 0:
        return (f"VACUOUS RUN: the sweep measured 0 tools against {target} — nothing was tested, so a 0-failure "
                f"result proves nothing. Check that the target registry is reachable and running (a stale DNS name "
                f"for a stopped container resolves but answers nothing).")
    if judged <= 0:
        tail = (f" The flow said: {str(flow_error)[:600]}" if flow_error else
                " The flow gave no reason; the cause is in the TARGET registry's log, not in the console that "
                "launched this sweep.")
        return (f"VACUOUS RUN: {measured} tool(s) were listed and NONE was judged (passed 0, failed 0, skipped "
                f"{(summary or {}).get('skipped') or 0}) against {target} — the sweep refused before it measured "
                f"anything, so a 0-failure result proves nothing.{tail}")
    return None


router = APIRouter(prefix="/admin/mcp-tester", tags=["MCP Tester"])


# ---------------------------------------------------------------------------
# Run state — Redis-backed so all 8 sandbox workers + N prod workers share
# ---------------------------------------------------------------------------
#
# Keys:
#   mcp_tester:runs:index            → sorted set of run_ids by started_at
#   mcp_tester:run:{run_id}          → hash with status/started_at/.../summary
#   mcp_tester:run:{run_id}:logs     → list of JSON-encoded {ts,msg}
#   mcp_tester:run:{run_id}:results  → JSON-encoded list of slim row dicts
#   mcp_tester:run:{run_id}:bugfinds → JSON-encoded list
#   mcp_tester:run:{run_id}:hardfail → JSON-encoded list
#   mcp_tester:run:{run_id}:skipped  → JSON-encoded list
#
# TTL: 30 days on every key (his word 2026-09-12, raised from 3). Index is a sorted set with
# a capped size that HARD-DELETES the oldest run's keys when exceeded — so the cap, not
# just the TTL, decides how far back the history goes. Measured 2026-09-12: one completed
# sweep is 7 keys / 1.15 MB, so a nightly at 03:00 UTC costs ~34 MB per 30 days and the
# 60-run cap ~69 MB. Both are env-overridable so they can be retuned without a rebuild.

_REDIS_PREFIX = "mcp_tester"
_MAX_HISTORY = int(os.getenv("MCP_TESTER_MAX_HISTORY", "60"))   # ≥30 nightlies + manual runs
_MAX_LOG_LINES = 2000
_RUN_TTL = int(os.getenv("MCP_TESTER_RUN_TTL_S", str(365 * 86400)))  # 365 days (his word 2026-09-16: "make it 365
# days"). ⚠ The store is a CACHE: the frame's redis runs --save "" --appendonly no with a 128mb allkeys-lru ceiling, so a
# restart empties it and pressure can evict a run regardless of this TTL (measured 2026-09-16: a redis recreate took the
# history from nine runs to two). scripts/mcp_tester_cron.py archives each finished run to disk for that reason.

# ── Phase F.2 — Latency baseline (Gap-2) ───────────────────────────────
# Per-suite, per-tool circular buffer of last-N elapsed_ms values (_suite_key: the flow and the target). Used to detect
# regressions where a tool drifts from 50ms → 500ms over several deploys
# without anyone noticing. The E.2 catastrophic 30s timeout would have
# flagged this MUCH earlier had the baseline existed.
_LATENCY_HISTORY_LEN = 10
_LATENCY_REGRESSION_THRESHOLD = 2.0   # 2x slower than median = regression
_LATENCY_BASELINE_MIN_SAMPLES = 3     # need ≥3 prior samples to declare regression
_LATENCY_RUN_FACTOR_MIN_TOOLS = 20    # §MCPTEST30 (V0544): the run's own slowdown needs this many baselined tools
_LATENCY_TTL = 30 * 86400             # 30-day retention on baseline entries


def _suite_key(flow_name: str, target_url: str) -> str:
    """§MCPTEST30 V0536: the latency baseline belongs to ONE suite against ONE target.

    It was keyed by tool and a frame guess, so every suite the console runs shared one buffer per tool. The cloud-op
    sweeps reach their tools through an operator registry and are slower than the main sweep by design: round 10's
    cloud-op alpha run (9b5d52c12a3048ea) flagged 27 "latency regressions" (listToolsets 3206 ms against the main
    sweep's 86 ms, 37x) that were two suites taking turns, while each pushed its own times into the other's median."""
    host = (urlparse(target_url or "").netloc or target_url or "?").lower()
    return f"{flow_name or 'unknown'}@{host}"


def _frame_label(target_url: str) -> str:
    """The `frame` label of a sandbox target, read from the host that names it. It tested for "test-b" or "8003" (the
    retired tier's names), so a sweep of sbx-beta-registry was labelled sandbox-a."""
    host = (urlparse(target_url or "").netloc or target_url or "").lower()
    return "sandbox-b" if ("beta" in host or "test-b" in host or host.endswith(":8003")) else "sandbox-a"


async def _record_latency_baseline(
    suite: str, results: List[dict], out: Optional[Dict[str, Any]] = None,
) -> int:
    """For each healthy result, append elapsed_ms to the suite's per-tool baseline +
    flag rows where current > 2.0x median(prior_N), measured against the run's own
    slowdown. Returns count of regressed tools. Safe no-op when Redis is unavailable.
    Only baselines HEALTHY runs — failures skew the median (a 30s timeout has
    elapsed=30000 which would poison the buffer).

    §MCPTEST30 (V0544): a box under load slows every tool at once. Round 11's strict run
    (186f01a3a7794b12) flagged 125 "latency regressions" while a build ran beside it, and
    the cloud-op runs 46 and 29: that measured the box, not the tools. The run's own
    slowdown is the median of every baselined tool's ratio to its baseline (from
    _LATENCY_RUN_FACTOR_MIN_TOOLS tools; never below 1.0, so a fast run tightens
    nothing), and a tool regresses only beyond twice THAT. `out["run_factor"]` names it.
    """
    r = await get_redis()
    if r is None:
        return 0
    measured = []   # (row, elapsed, key, median or None)
    for row in results:
        tool = row.get("tool", "")
        elapsed = int(row.get("elapsed", 0) or 0)
        if not tool or elapsed <= 0 or not row.get("healthy"):
            continue
        key = _rk("latency", suite, tool)
        median = None
        try:
            prior = await r.lrange(key, 0, _LATENCY_BASELINE_MIN_SAMPLES - 1)
            prior_vals = []
            for x in prior:
                if not x:
                    continue
                xs = x.decode() if isinstance(x, (bytes, bytearray)) else str(x)
                if xs.isdigit():
                    prior_vals.append(int(xs))
            if len(prior_vals) >= _LATENCY_BASELINE_MIN_SAMPLES:
                median = sorted(prior_vals)[len(prior_vals) // 2] or None
        except Exception:
            pass  # baseline is advisory; never blocks the sweep
        measured.append((row, elapsed, key, median))
    ratios = sorted(e / m for _r, e, _k, m in measured if m)
    factor = ratios[len(ratios) // 2] if len(ratios) >= _LATENCY_RUN_FACTOR_MIN_TOOLS else 1.0
    factor = max(1.0, factor)
    if out is not None:
        out["run_factor"] = round(factor, 2)
        out["baselined_tools"] = len(ratios)
    regressions = 0
    for row, elapsed, key, median in measured:
        if median and elapsed > median * _LATENCY_REGRESSION_THRESHOLD * factor:
            regressions += 1
            row["latency_regression"] = True
            row["latency_baseline_ms"] = median
        try:
            await r.lpush(key, str(elapsed))
            await r.ltrim(key, 0, _LATENCY_HISTORY_LEN - 1)
            await r.expire(key, _LATENCY_TTL)
        except Exception:
            pass  # baseline is advisory; never blocks the sweep
    return regressions


def _rk(*parts: str) -> str:
    return ":".join((_REDIS_PREFIX, *parts))


def _truncate_response_excerpt(raw: Any, max_bytes: int = 2048) -> Any:
    """Cap the response payload size for FE display.

    The flow_mcp_lifecycle captures full result_excerpt in
    ContractOutcome.result_excerpt — could be megabytes for some tools.
    Truncate to ~2KB so Redis payload + FE renderer stay fast. Keeps the
    dict structure if possible; falls back to a `_truncated` envelope.
    """
    if raw is None:
        return None
    try:
        encoded = json.dumps(raw)
        if len(encoded) <= max_bytes:
            return raw
        return {
            "_truncated": True,
            "_original_bytes": len(encoded),
            "_preview": encoded[:max_bytes] + "…",
        }
    except (TypeError, ValueError):
        return {"_unparseable": True, "_repr": repr(raw)[:max_bytes]}


async def _redis_or_die():
    r = await get_redis()
    if r is None:
        raise HTTPException(
            status_code=503,
            detail="MCP Tester requires Redis (REDIS_URL not configured)",
        )
    return r


async def _save_run_meta(run_id: str, run: Dict[str, Any]) -> None:
    """Persist run metadata to Redis (hash of non-list fields)."""
    r = await get_redis()
    if r is None:
        return
    # Serialize: status / started_at / finished_at / developer_id / error / summary (JSON)
    fields: Dict[str, str] = {
        "run_id":      run_id,
        "status":      str(run.get("status", "")),
        "started_at":  json.dumps(run.get("started_at")),
        "finished_at": json.dumps(run.get("finished_at")),
        "developer_id": str(run.get("developer_id") or ""),
        # §pass73.3.19: which suite this run executed (FE shows it + filters).
        "flow_name":   str(run.get("flow_name") or _DEFAULT_FLOW_NAME),
        "flow_label":  str(run.get("flow_label") or ""),
        "summary":     json.dumps(run.get("summary")),
        "error":       json.dumps(run.get("error")),
    }
    await r.hset(_rk("run", run_id), mapping=fields)
    await r.expire(_rk("run", run_id), _RUN_TTL)
    # Add to sorted index
    started = float(run.get("started_at") or 0)
    await r.zadd(_rk("runs", "index"), {run_id: started})
    # Cap the index
    total = await r.zcard(_rk("runs", "index"))
    if total > _MAX_HISTORY:
        # Drop oldest
        to_drop = await r.zrange(_rk("runs", "index"), 0, total - _MAX_HISTORY - 1)
        if to_drop:
            await r.zrem(_rk("runs", "index"), *to_drop)
            for rid in to_drop:
                rid_str = rid.decode() if isinstance(rid, bytes) else rid
                await r.delete(_rk("run", rid_str),
                                _rk("run", rid_str, "logs"),
                                _rk("run", rid_str, "results"),
                                _rk("run", rid_str, "bugfinds"),
                                _rk("run", rid_str, "hardfail"),
                                _rk("run", rid_str, "skipped"),
                                _rk("run", rid_str, "polideny"))


async def _load_run_meta(run_id: str) -> Optional[Dict[str, Any]]:
    r = await get_redis()
    if r is None:
        return None
    fields = await r.hgetall(_rk("run", run_id))
    if not fields:
        return None
    # Decode bytes keys/values
    out: Dict[str, Any] = {}
    for k, v in fields.items():
        kk = k.decode() if isinstance(k, bytes) else k
        vv = v.decode() if isinstance(v, bytes) else v
        if kk in ("started_at", "finished_at", "summary", "error"):
            try:
                out[kk] = json.loads(vv) if vv else None
            except Exception:
                out[kk] = None
        else:
            out[kk] = vv
    out["developer_id"] = int(out["developer_id"]) if out.get("developer_id") and out["developer_id"].isdigit() else None
    return out


async def _append_log(run_id: str, msg: str) -> None:
    r = await get_redis()
    if r is None:
        return
    entry = json.dumps({"ts": time.time(), "msg": msg})
    await r.rpush(_rk("run", run_id, "logs"), entry)
    await r.ltrim(_rk("run", run_id, "logs"), -_MAX_LOG_LINES, -1)
    await r.expire(_rk("run", run_id, "logs"), _RUN_TTL)


async def _load_logs(run_id: str) -> List[Dict[str, Any]]:
    r = await get_redis()
    if r is None:
        return []
    raw = await r.lrange(_rk("run", run_id, "logs"), 0, -1)
    out: List[Dict[str, Any]] = []
    for line in raw:
        try:
            ll = line.decode() if isinstance(line, bytes) else line
            out.append(json.loads(ll))
        except Exception:
            pass
    return out


async def _save_list(run_id: str, key: str, items: List[Dict[str, Any]]) -> None:
    r = await get_redis()
    if r is None:
        return
    await r.set(_rk("run", run_id, key), json.dumps(items), ex=_RUN_TTL)


async def _load_list(run_id: str, key: str) -> List[Dict[str, Any]]:
    r = await get_redis()
    if r is None:
        return []
    raw = await r.get(_rk("run", run_id, key))
    if not raw:
        return []
    try:
        rr = raw.decode() if isinstance(raw, bytes) else raw
        return json.loads(rr) or []
    except Exception:
        return []


async def _list_recent_run_ids(limit: int = _MAX_HISTORY) -> List[str]:
    r = await get_redis()
    if r is None:
        return []
    raw = await r.zrevrange(_rk("runs", "index"), 0, limit - 1)
    return [(rid.decode() if isinstance(rid, bytes) else rid) for rid in raw]

# Target URL — same env var the existing api-tester uses. In sandbox-A this is
# http://localhost:8000 (the runner reaches into sandbox containers via docker
# exec internally). In Frame A this is normally also pointed at the registry's
# own loopback, but the FLOW runner hard-codes `get_target("sandbox")` which
# expands to `agentvault_registry_test` regardless — so the flow always lands
# in sandbox. This invariant is documented + tested separately.
API_TEST_TARGET_URL = os.environ.get("API_TEST_TARGET_URL", "http://localhost:8000")

# Default sweep — the canonical full MCP regression
_DEFAULT_FLOW_NAME = "flow_mcp_lifecycle_complete"

# §pass73.3.19: flows runnable from the MCP-tester FE view. Each gets the same
# Redis-backed run record + live-log heartbeat + SSE + history. Previously only
# the strict MCP-tester flow was wired here, so the federation suite + cloud-op
# sweeps (fired via /api-test/test-flow) were invisible in the view. flow_name →
# UI label. Summary shape is normalized in _execute_sweep_background (the
# federation suite returns a nested flow_values.summary, the others are flat).
_SUPPORTED_FLOWS = {
    # §RESIDUES C5 (2026-09-13): the label once carried a tool count as a LITERAL ("682 tools") while the sweep
    # measured 759 — two numbers for one population, one of them a fossil. The count is `summary.tool_count`;
    # a label never states it.
    "flow_mcp_lifecycle_complete":                     "MCP Tester — sandbox-A",
    "flow_federation_suite_complete":                  "Federation Suite (multi-registry)",
    # §MCPTEST30 (V0637): the two keys keep the names of operators retired in September (the history is filed under
    # them); the labels name the operator that answers, by its frame (each run records its own name: operator_slug)
    "flow_mcp_lifecycle_cloudop_sandboxalpha_complete": "Cloud-op MCP: the operator under Sandbox Alpha",
    "flow_mcp_lifecycle_cloudop_sandboxdelta_complete": "Cloud-op MCP: the operator under Sandbox Beta",
}


# §FRAMELIC (2026-09-07, findings row 136) — the sandbox TIER is not one hardcoded name.
# `registry-test` / `localhost:8002` was the 2026-05 sandbox; the tier is now sbx-alpha (8150) and
# sbx-beta (8250), and the next one will be something else again. A frame whose console drives the
# tester at a sandbox it does not RECOGNISE silently loses sandbox-mode request bodies — the tester
# still runs, so nothing fails loudly, it just tests less. Env-driven, with the old two kept so
# nothing that works today stops working.
_SANDBOX_TARGET_HINTS = tuple(
    h.strip().lower() for h in os.environ.get(
        "API_TEST_SANDBOX_TARGET_HINTS",
        "registry-test,localhost:8002,sbx-alpha,sbx-beta,:8150,:8250,sandbox-a,sandbox-b,sandbox-c",
    ).split(",") if h.strip()
)


def _pass_depth(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    """§MCPTEST30 (V0549): how deep the passing tool rows reach. A pass is a 2xx or a refusal, against a contract a
    person wrote or the default one (§FANCLAIM left a default-contract refusal as thin coverage: the tool dispatched
    and its route refused the sweep's nonexistent target). Round 15's strict run on V0547: 374 + 132 + 100 + 99 of
    705 passing tool rows, and the headline counted all four alike. A reading, never a verdict; rows that are not
    tool calls (probes, federation tests) are outside it."""
    out = {"success_contract": 0, "success_default": 0, "refusal_contract": 0, "refusal_default": 0}
    for r in rows or []:
        if not (r.get("healthy") and not r.get("skipped") and not r.get("skip_reason")
                and str(r.get("tool") or "").startswith("theprotocol_")):
            continue
        st = r.get("status")
        kind = "success" if isinstance(st, int) and 200 <= st < 300 else "refusal"
        out[f"{kind}_{'contract' if r.get('has_explicit_contract') else 'default'}"] += 1
    return out


# ── a pass that was only a refusal ─────────────────────────────────────────────────────────────────────────────────
# §MCPTEST30 (V0636; his question of 2026-10-19, "is this like second calls on an endpoint that was already successfully
# tested ... because this seems completely cheated otherwise", and his word of 2026-10-24 to close the gaps): a tool row
# passes on a refusal when its route refuses the sweep's input as its contract says (a 404 for an agent that does not
# exist). That shows the route refuses; it never shows the tool does its job. Where nothing else in the run answered 2xx
# for the same tool (its own row, an `admin_effect:` row, a probe family's row), the pass was the tool's only test: V0635's
# run 9bc6416cf52d41c5 passed 204 tools that way, and its 97.18% read 78.1% without them. Such a row counts as not
# measured: in the summary's four classes, in the not-measured list and on the row itself. The target's own count is
# kept beside it (`target_counts`).
_REFUSAL_ONLY_REASON = ("refusal only: the tool passed on a refusal and nothing in this run reached its success path; a "
                        "refusal shows the route refuses, never that the tool does its job")


def refusal_only_reason(row: Dict[str, Any]) -> str:
    """§MCPTEST30 (V0643): what a refusal-only row says: its by-design reason where the target's flow names one
    (api_tests/contracts/refusal_reasons.py, `declared_unmeasured` on the row), else the generic sentence."""
    declared = str(row.get("declared_unmeasured") or "").strip()
    if declared:
        return "refusal only, by design: " + declared + "; the refusal is measured, the success path is not"
    return _REFUSAL_ONLY_REASON


def _tool_base(label: Any) -> str:
    """The tool a row speaks for: `theprotocol_rotateAgentCredentials`, `admin_effect: rotateAgentCredentials` and
    `refusal: rotateAgentCredentials unknown agent` all speak for rotateAgentCredentials."""
    s = str(label or "")
    if not s.startswith("theprotocol_") and ": " in s:
        s = s.split(": ", 1)[1]
    s = s.strip()
    if s.startswith("theprotocol_"):
        s = s[len("theprotocol_"):]
    m = re.match(r"[A-Za-z0-9]+", s)
    return m.group(0) if m else s


def _passing(row: Dict[str, Any]) -> bool:
    return bool(row.get("healthy")) and not row.get("skipped") and not row.get("skip_reason")


def _is_2xx(status: Any) -> bool:
    return isinstance(status, int) and 200 <= status < 300


def _refusal_only(rows: Optional[List[Dict[str, Any]]]) -> List[int]:
    """The indices of the tool rows that passed on a refusal (any status but a 2xx, as `_pass_depth` reads a refusal)
    while no passing row of the run answered 2xx for their tool. A row held to a switch the target turned off is left
    to that switch's own account (its refusal is the documented answer there)."""
    rows = rows or []
    succeeded = {_tool_base(r.get("tool")) for r in rows if isinstance(r, dict) and _passing(r) and _is_2xx(r.get("status"))}
    out: List[int] = []
    for i, r in enumerate(rows):
        if not isinstance(r, dict):
            continue
        label = str(r.get("tool") or "")
        if (label.startswith("theprotocol_") and _passing(r) and not r.get("switched_off")
                and not _is_2xx(r.get("status")) and _tool_base(label) not in succeeded):
            out.append(i)
    return out


def _apply_refusal_only(rows: List[Dict[str, Any]], summary: Dict[str, Any],
                        skipped: List[Dict[str, Any]]) -> int:
    """Moves the refusal-only rows from passed to not measured: the row (`refusal_only`, `skipped`, its reason), the
    not-measured list, and the summary's counts and rate, which the target's own count is kept beside. Returns how
    many rows it moved."""
    idx = _refusal_only(rows)
    summary["target_counts"] = {k: summary.get(k) for k in ("passed", "skipped", "pass_pct")}
    for i in idx:
        r = rows[i]
        why = refusal_only_reason(r)
        r["refusal_only"] = True
        r["skipped"] = True
        r["skip_reason"] = why
        skipped.append({"tool": r.get("tool") or "", "reason": why})
    n = len(idx)
    summary["refusal_only"] = n
    if n:
        summary["passed"] = max(0, int(summary.get("passed") or 0) - n)
        summary["skipped"] = int(summary.get("skipped") or 0) + n
        total = int(summary.get("tool_count") or 0)
        summary["pass_pct"] = round(summary["passed"] * 100.0 / total, 2) if total else 0
    return n


def _detectors_measured(fv: Optional[Dict[str, Any]]) -> Dict[str, bool]:
    """§MCPTEST30 (V0541): which of the three drift detectors this run measured, each by its own evidence.

    The summary defaulted every detector's count to 0 whatever the suite ran, and the Drift tab read 0 as clean: it
    printed "every tool rejects the wrong tier" over 0 of 0 probes (the federation suite runs no matrix) and "wrappers
    match their routes" for the cloud-op sweeps, which declare F3 and F4 off (`skip_axes_disabled`). A suite says what
    it measured: the wrapper/route check that it ran and returned, the A↔B walk the tools it compared, the matrix its
    probe count."""
    fv = fv or {}
    off = set(fv.get("skip_axes_disabled") or [])

    def _n(key: str) -> int:
        try:
            return int(fv.get(key) or 0)
        except (TypeError, ValueError):
            return 0
    # a target before V0541 does not say; its run is read the way this router read it then
    wrapper = (fv.get("wrapper_drift_measured") is True) if "wrapper_drift_measured" in fv else ("wrapper_drift" in fv)
    cross = (_n("cross_frame_compared") > 0) if "cross_frame_compared" in fv else ("cross_frame_drift" in fv)
    return {
        "wrapper_route": wrapper and "F3_wrapper_drift" not in off,
        "cross_frame": cross and "F4_cross_frame_parity" not in off,
        "auth_matrix": _n("auth_matrix_total") > 0,
    }


def _detector_axes(tool: str, fv: Optional[Dict[str, Any]], det: Dict[str, bool], violators: Set[str],
                   cross_drift: Set[str], wrapper_drift: Set[str]) -> Dict[str, Dict[str, str]]:
    """§MCPTEST30 (V0541): a row's three drift axes. A row passes an axis only where the detector measured that tool:
    every row read "rejected all 3 wrong-tier credentials" and "wrapper inputSchema matches route signature" whether
    or not the run probed it (a public tool has no wrong tier; the cloud-op and federation suites run no wrapper/route
    check), and an A↔B "pass" said "(or not probed cross-frame)" itself. A target that does not list what it probed
    (an image before V0541) keeps the run-level reading."""
    fv = fv or {}
    out: Dict[str, Dict[str, str]] = {}
    probed = fv.get("auth_matrix_probed_tools")
    if tool in violators:
        out["wrong_tier_rejection"] = {"state": "fail",
                                       "detail": "accepted a wrong-tier credential — privilege-escalation regression"}
    elif not det.get("auth_matrix"):
        out["wrong_tier_rejection"] = {"state": "na", "detail": "this run measured no wrong-tier matrix"}
    elif isinstance(probed, list) and tool not in set(probed):
        out["wrong_tier_rejection"] = {"state": "na",
                                       "detail": "not probed with a wrong-tier credential (a public tool has no wrong "
                                                 "tier, or its contract opts out)"}
    else:
        out["wrong_tier_rejection"] = {"state": "pass",
                                       "detail": "rejected every wrong-tier credential it was probed with (401/403)"}
    compared = fv.get("cross_frame_compared_tools")
    if tool in cross_drift:
        out["cross_frame_parity"] = {"state": "fail", "detail": "the target and its peer frame answered different shapes"}
    elif not det.get("cross_frame"):
        out["cross_frame_parity"] = {"state": "na", "detail": "this run compared no tool across frames"}
    elif isinstance(compared, list) and tool not in set(compared):
        out["cross_frame_parity"] = {"state": "na", "detail": "not among the tools compared across frames"}
    else:
        out["cross_frame_parity"] = {"state": "pass", "detail": "the target and its peer frame answered the same shape"}
    # §MCPTEST30 (V0547): since V0547 the check is the request survey (api_tests/contracts/wrapper_route_survey.py): a row
    # passes where its tool was surveyed and its route took the request; a named exception of the build gate is not
    # graded either way. A target before V0547 names no source and keeps the static check's words.
    survey = bool(fv.get("wrapper_drift_source"))
    surveyed = fv.get("wrapper_drift_surveyed_tools")
    known = {k.get("tool"): str(k.get("reason") or "") for k in (fv.get("wrapper_drift_known") or [])
             if isinstance(k, dict)}
    peer_only = {k.get("tool") for k in (fv.get("wrapper_peer_route") or []) if isinstance(k, dict)}
    if tool in wrapper_drift:
        found = next((d for d in (fv.get("wrapper_drift_details") or [])
                      if isinstance(d, dict) and d.get("tool") == tool), {})
        out["wrapper_route_drift"] = {"state": "fail", "detail": (
            f"its route refuses the request it sends ({found.get('detail') or ', '.join(found.get('classes') or [])})"
            [:240] if survey else "wrapper inputSchema diverges from FastAPI route signature")}
    elif not det.get("wrapper_route"):
        out["wrapper_route_drift"] = {"state": "na", "detail": "this run did not check wrappers against their routes"}
    elif tool in known:
        out["wrapper_route_drift"] = {"state": "na", "detail": f"a named exception of the build gate: {known[tool]}"[:240]}
    elif tool in peer_only:
        out["wrapper_route_drift"] = {"state": "na", "detail": "its route authenticates only a federation peer: no MCP "
                                                               "caller can succeed (reported, his decision)"}
    elif survey and isinstance(surveyed, list) and tool not in set(surveyed):
        out["wrapper_route_drift"] = {"state": "na", "detail": "not among the tools the request survey called"}
    elif survey:
        out["wrapper_route_drift"] = {"state": "pass",
                                      "detail": "its request passes its route's own validation (the request survey)"}
    else:
        out["wrapper_route_drift"] = {"state": "pass", "detail": "wrapper inputSchema matches route signature"}
    return out


def _is_sandbox_target() -> bool:
    """True if API_TEST_TARGET_URL points at a sandbox registry (any of the tier)."""
    t = (API_TEST_TARGET_URL or "").lower()
    return any(h in t for h in _SANDBOX_TARGET_HINTS)


# ─────────────────────────────────────────────────────────────────────────────
# 2026-06-02 emission-coverage fix (Commander-approved "Real ES poll")
# The strict-mode event_emission axis previously INFERRED emission from a
# tool-name financial-prefix + healthy heuristic and NEVER queried the
# EventStore — so real emitters like tegSystemTransfer/castVote/agentHeartbeat
# were mislabeled "does not emit", and the financial-prefix "pass" verified
# nothing. This catalogue + helper make the axis poll the sandbox ES for real.
# Every event_type below was LIVE-verified present in eventstore_test; tools
# NOT listed render axis 'na' (we don't claim emission we can't verify). The
# api_tests engine (_phase_c expect_events) is the sibling per-call enforcer.
# ─────────────────────────────────────────────────────────────────────────────
_EMIT_MAP: Dict[str, List[str]] = {
    # Catalogue grounded in `event_emission_policies` (168 rows) ∩ event_types
    # actually active in eventstore_test ∩ MCP tools exercised in the sweep.
    # Each event_type LIVE-verified present in ES. na when the tool's call isn't
    # 2xx (no emission expected). Background/reactor/system event types in the
    # policy table that no MCP tool triggers (LedgerBalanceChanged, Hagrid*,
    # CompliancePoll*, CrossFrame*, RewardsDistributed, …) are intentionally absent.
    # ── Transfers (TokensTransferred is canary-flooded → DID-match, see _EMIT_CANARY_NOISY) ──
    "transferUnits":                 ["TokensTransferred"],
    "tegSystemTransfer":              ["TokensTransferred"],
    "tegCrossRegistryTransferDirect": ["TokensTransferred"],
    "settlePayment":                  ["TokensTransferred"],
    # ── §EVTYPES 2026-09-05: derived MECHANICALLY, not guessed. tool -> endpoint
    #    (mcp/ TOOL_DISPATCH + the helper's path, matched on HTTP METHOD) -> the
    #    event_type its route handler emits (routers/ AST). Method matching is
    #    load-bearing: without it a GET tool inherits the POST route's events and
    #    every one becomes a false MISS (getAdminBroadcasts -> AdminBroadcastSent).
    #    Only types LIVE-observed in the sandbox ES are listed, and only emits that
    #    are UNCONDITIONAL in their handler; guarded ones went to _EMIT_CONDITIONAL.
    "deleteMyAgent":                  ["AgentStatusChanged"],
    "acceptContractFederated":        ["ContractAgreed"],            # §TWOAGENT V0437: the contracts v2 provider rail
    "submitContractMilestone":        ["ContractMilestoneSubmitted"],
    "submitContractWorkFederated":    ["ContractMilestoneSubmitted"],  # same
    "createMalpracticeDispute":       ["DisputeFiled"],
    # ── §EVTYPES conditional emitters (see _EMIT_CONDITIONAL) ──
    "crossTegBalanceSync":            ["CrossRegistryTransferCompleted", "TokensTransferred"],
    "forceRegisterAgentCard":         ["CommanderFlaggedDrift"],
    "suspendOperator":                ["FederationLicenseSuspended"],
    "reinstateOperator":              ["FederationLicenseReinstated"],
    "tegTreasuryIssue":                ["TokensIssued"],
    "tegTreasuryReceive":             ["TreasurySlashReceived"],
    # ── Staking ──
    "lockUnits":                    ["TokensStaked"],
    "unlockUnits":                  ["TokensUnstaked"],
    # ── Governance ──
    "createProposal":                 ["ProposalCreated"],
    "castVote":                       ["VoteCast"],
    "tallyProposal":                  ["ProposalTallied"],
    # ── Payment ──
    "authorizePayment":               ["A2APaymentAuthorized"],
    # ── Agent lifecycle ──
    "agentHeartbeat":                 ["AgentHeartbeat"],
    "enableMtls":                     ["AgentMtlsEnrolled"],
    "cloneAgent":                     ["AgentCloned"],
    "importAgent":                    ["AgentImported"],
    "exportAgentDev":                 ["AgentExported"],
    # ── Reputation / attestation ──
    "depositReputationBond":          ["ReputationBondDeposited"],
    "submitAttestation":              ["AttestationSubmitted"],
    # ── Funding ──
    "submitFundingRequest":           ["FundingRequestCreated"],
    # ── Organizations ──
    "createOrganization":             ["OrganizationCreated"],
    "deleteOrganization":             ["OrganizationDeleted"],
    "inviteOrganizationMember":       ["OrganizationMemberInvited"],
    # ── Pipelines (CI/CD) ──
    "createPipeline":                 ["PipelineCreated"],
    "updatePipeline":                 ["PipelineUpdated"],
    "deletePipeline":                 ["PipelineDeleted"],
    # ── Versions / deployments (CI/CD) ──
    "createVersion":                  ["VersionCreated"],
    "activateVersion":                ["VersionActivated"],
    "rollbackVersion":                ["VersionRolledBack"],
    "triggerDeployment":              ["DeploymentTriggered"],
    "updateDeploymentStatus":         ["DeploymentStatusUpdated"],
    # ── Admin agent lifecycle (es_event_verifier-authoritative; mostly 4xx→na
    #    in the sweep without a live target, verified pass when 2xx) ──
    # §CLOUDOPMCP2 2026-09-05 — suspendAgent / reinstateAgentEnforcement REMOVED.
    # MEASURED: both MCP tools post to /admin/enforcement/agents/{did}/{suspend,
    # reinstate} (routers/enforcement_admin.py:258,320), which emit NOTIFICATIONS
    # ("agent.suspended"/"agent.reinstated") and NO EventStore event; the
    # coordinated_suspension service emits none either. `AgentSuspended` is emitted
    # by a DIFFERENT route — bulk_suspend_agents (admin_agents.py:944), mapped below.
    # ⚠ §EVTYPES 2026-09-05 CORRECTION: this comment used to end "and `AgentReinstated`
    # has NO live emitter anywhere in the tree (only test files name it)". That is
    # WRONG and was wrong when written: bulk_reinstate_agents emits it via
    # `emit_agent_reinstated` (admin_agents.py:1032), the exact twin of the suspend
    # half already mapped here. The claim held only for the ENFORCEMENT route the
    # paragraph is about. The federation suite's emission_coverage_ratchet is what
    # exposed it — AgentReinstated showed up as NEW_uncovered while a live emitter
    # sat ten lines from the one this map already knew about.
    # While the ES poll was blind these read `unknown` and nobody
    # noticed; the moment the axis could see, they would have become FALSE MISSES.
    "bulkSuspendAgents":              ["AgentSuspended"],
    "bulkReinstateAgents":            ["AgentReinstated"],
    "disableMyMtls":                  ["AgentMtlsRevoked"],
    "forceMtlsEnroll":                ["AgentMtlsEnrolled"],
    "transferAgentOwnership":         ["AgentOwnershipTransferred"],
    "rotateAgentCredentials":         ["AgentCredentialsRotated"],
    # ── Admin funding / policy / snapshot / federation ──
    "approveFunding":                 ["FundingRequestApproved"],
    "rejectFunding":                  ["FundingRequestRejected"],
    "setEventEmissionPolicy":         ["EventEmissionPolicyUpdated"],
    "triggerProjectionSnapshot":      ["ProjectionSnapshot"],
    "bulkRefreshAgentCards":          ["AdminBulkRefreshCards"],
    "completeAdmission":              ["RegistryFederated"],
    "deactivatePeerRegistry":         ["PeerRegistryDeactivated"],
    "updatePeerSlashConfig":          ["PeerSlashConfigUpdated"],
    "rejectFrameInvitation":          ["FrameInvitationRejected"],
    # ── Contracts (es_event_verifier-authoritative; 4xx→na without a live contract) ──
    "acceptContract":                 ["ContractAccepted"],
    "submitContractWork":             ["ContractWorkSubmitted"],
    "approveContractCompletion":      ["ContractCompleted"],
    "markContractFailed":             ["ContractFailed"],
    # ── Guild (§CLOUDOPMCP2 2026-09-05: the WHOLE family was unmapped, so the sweep
    #    called these tools and verified nothing. Each emit site read from routers/guild.py) ──
    "guildPostOrder":                 ["GuildOrderPosted"],      # guild.py:187
    "guildBid":                       ["GuildBidPlaced"],        # guild.py:428
    "guildAward":                     ["GuildOrderAwarded"],     # guild.py:495
    "guildSubmitWork":                ["GuildWorkSubmitted"],    # guild.py:540
    "guildVerify":                    ["GuildOrderSettled"],     # guild.py:690
    "guildCancelOrder":               ["GuildOrderCancelled"],   # guild.py:1005
    # ── AGORA exchange (same gap; emit sites in services/exchange_service.py).
    #    ExchangeDividendPaid is deliberately NOT mapped to declareAgoraDistribution:
    #    it fires later, only once `remaining == 0` (:3685), so it is a follow-on of
    #    the payout loop and not something the declaring call guarantees. ──
    "createAgoraListing":          ["ExchangeListingCreated"],    # :814
    "adminAgoraApproveListing":    ["ExchangeListingApproved"],   # :884
    "placeAgoraOrder":             ["ExchangeOrderPlaced"],       # :2614
    "cancelAgoraOrder":            ["ExchangeOrderCancelled"],    # :2783
    "declareAgoraDistribution":        ["ExchangeDividendDeclared"],  # :2973
    # ── Disputes ──
    "submitDispute":                  ["DisputeFiled"],
    "submitDisputeEvidence":          ["EvidenceSubmitted"],
    # ── Developer / account admin (all 4xx→na in sweep without a real target) ──
    "suspendDeveloper":               ["DeveloperSuspended"],
    "reinstateDeveloper":             ["DeveloperReinstated"],
    "softDeleteDeveloper":            ["DeveloperDeleted"],
    "disableDeveloper2FA":            ["DeveloperDisable2FA"],
    "forceEmailVerify":               ["DeveloperForceEmailVerify"],
    "forceDeveloperPasswordReset":    ["DeveloperForcePasswordReset"],
    "revokeDeveloperApiKeys":         ["DeveloperRevokeApiKeys"],
    "updateDeveloperAdminFlags":      ["DeveloperAdminFlagsChanged"],
    "requestAccountDeletion":         ["AccountDeletionRequested"],
    "rotateAgentSigningKey":          ["AgentSigningKeyRotated"],
    "resetAgentCredentialsOnboard":   ["AgentCredentialReset"],
    "deleteAdminAgent":               ["AgentHardDeleted"],
    "acknowledgeAgentFlag":           ["AgentFlagAcknowledged"],
    # ── Admin broadcasts ──
    "composeBroadcast":               ["AdminBroadcastSent"],
    "updateBroadcast":                ["AdminBroadcastEdited"],
    "retractBroadcast":               ["AdminBroadcastRetracted"],
    # ── Organization membership ──
    "acceptOrgInvitation":            ["OrganizationMemberJoined"],
    "removeOrganizationMember":       ["OrganizationMemberRemoved"],
    # ── Disputes / enforcement / attestation revoke / slash ──
    "resolveTegDispute":              ["DisputeResolved"],
    "recordAgentOffense":             ["EnforcementActionCreated"],
    "slashAgent":                ["DisputeSlash"],
    "agentRevokeAttestation":         ["AttestationRevoked"],
    "adminRevokeAttestation":         ["AttestationRevoked"],
    # ── Treasury cross-TEG fund ──
    "tegCrossTegFund":                ["CrossTEGTreasuryFunded"],
    # ── Registry quarantine / blacklist (admin) ──
    "quarantineRegistry":             ["RegistryQuarantined"],
    "liftQuarantine":                 ["RegistryQuarantineLifted"],
    "blacklistRegistry":              ["RegistryBlacklisted"],
    # ── Frame invitations / federation lifecycle (admin) ──
    "createFrameInvitation":          ["FrameInvitationRequested"],
    "approveFrameInvitation":         ["FrameInvitationApproved"],
    "finalizeFrameInvitation":        ["FrameFederationEstablished"],
    "revokeFrame":                    ["FrameFederationRevoked"],
    "suspendFederationLicense":       ["FederationLicenseSuspended"],
    "reinstateFederationLicense":     ["FederationLicenseReinstated"],
    # ── Agent / onboard creation (high-freq → DID-matched, see _EMIT_CANARY_NOISY) ──
    "createAgent":                    ["AgentCreated"],
    "submitOnboardRegister":          ["AgentOnboarded"],
    # ── Reputation signal (eigentrust background also emits → DID-matched) ──
    "applyReputationSignal":          ["ReputationChanged"],
    # ── Bundles (.tpb marketplace) — emission WIRED 2026-06-02 in routers/bundles.py
    #    (was declared-but-unwired: policy rows existed, handlers made 0 emit calls,
    #    prod ES had 0 bundle events ever). Now event-sourced → verifiable. ──
    "createBundle":                   ["BundleCreated"],
    "forkBundle":                     ["BundleCreated"],
    "deleteBundle":                   ["BundleDeleted"],
    "downloadBundle":                 ["BundleDownloaded"],
    "rateBundle":                     ["BundleRated"],
    "reportBundle":                   ["BundleReported"],
    # ── Operator access (admin) ──
    "revokeOperatorAccess":           ["OperatorApplicationRevoked"],
    # ── Bridge / federation-policy / provisioning (source-confirmed emitters;
    #    4xx→na in sweep without live prerequisites, auto-verified if they 2xx) ──
    "bridgeTransfer":                 ["TokensBridgeLocked"],
    "bridgeUnlock":                   ["TokensBridgeUnlocked"],
    "bridgeRedeem":                   ["TokensBridgeUnlocked"],
    "bridgeIssueWrapped":              ["WrappedTokensMinted"],
    "setFederationComplianceEnforcementMode": ["ComplianceEnforcementModeChanged"],
    "federationPolicyUpdateRequest":  ["FederationPolicyUpdated"],
    "giftProvisioning":               ["ProvisioningGifted"],
    # §MEMBERSHIP phase B (V0551): the commons seasons' audit events (services/commons.py; registry-emitted,
    # skip_in_projection). An award's money is counted by its own ledger rows; CommonsAwardPaid is one per recipient
    # paid, so a pay with nothing to pay emits none (_EMIT_CONDITIONAL).
    "adminCommonsOpenSeason":         ["CommonsSeasonOpened"],
    "adminCommonsCloseSeason":        ["CommonsSeasonClosed"],
    "adminCommonsPaySeason":          ["CommonsAwardPaid"],
}
# High-frequency types ALSO emitted by canaries/other agents → presence-since-
# run-start is NOT sufficient (would false-pass). Require a sweep-agent DID in
# the event payload for these. CAVEAT: only types whose payload actually CARRIES
# a matchable DID qualify — TokensTransferred has from/to. TokensStaked does NOT
# (payload is amount/pool_id/transaction_id/lock_period_days) AND it isn't
# canary-noisy (canaries don't stake), so it stays presence-based. Low-freq
# types accept presence (the sweep is the only producer in sandbox).
_EMIT_CANARY_NOISY = {"TokensTransferred", "AgentCreated", "AgentOnboarded", "ReputationChanged"}
# §CLOUDOPMCP2 2026-09-05 — CONDITIONAL emitters: tools whose event fires per unit
# of work DONE, not per 2xx. `bulkSuspendAgents` emits `AgentSuspended` inside its
# per-agent loop AFTER a successful suspend (admin_agents.py:944), and it carries no
# explicit contract, so the sweep calls it with default args, suspends nobody, and
# correctly emits nothing. Mapping it plainly made the very first corrected-map run
# report a REAL MISS that was not real. For these the axis is `na` WITH THE REASON --
# the third state, "could not know", never a silent pass: the sweep does not control
# whether the call did any work, so it has nothing to assert. Add here only after
# reading the emit site and confirming it sits inside a success branch.
# Tools whose emit is GUARDED in the handler (emits only when work was actually
# done), so an absent event is not a defect. §EVTYPES 2026-09-05 added five whose
# guard was confirmed by AST nesting at the exact emit line -- mapping them hard
# would have manufactured five false MISSes, the mistake bulkSuspendAgents taught.
_EMIT_CONDITIONAL = {
    "bulkSuspendAgents",       # emits inside the per-agent success loop
    "bulkReinstateAgents",     # same shape: emits inside the per-agent success loop
    "crossTegBalanceSync",     # CrossRegistryTransferCompleted/TokensTransferred only on drift
    "forceRegisterAgentCard",  # CommanderFlaggedDrift only when drift is flagged
    "suspendOperator",         # FederationLicenseSuspended only if a license exists
    "reinstateOperator",       # FederationLicenseReinstated only if a license exists
    "tegTreasuryIssue",         # TokensIssued behind the mint-proxy branch
    "tegTreasuryReceive",      # TreasurySlashReceived behind the slash-return branch
    # §TWOAGENT V0437: the contracts v2 provider rail emits where the contract LIVES. On a contract homed on another
    # frame (a replica here) the event lands in the home frame's store, not the target's, so an absence is not a defect.
    "acceptContractFederated",
    "submitContractWorkFederated",
    "adminCommonsPaySeason",   # §MEMBERSHIP (V0551): CommonsAwardPaid only per recipient actually paid
}
def _did_no_work(row: Dict[str, Any]) -> Optional[str]:
    """§MCPTEST30 (2026-09-30): the reason a 2xx row did NO work, when its own answer says so, else None.

    Several routes refuse inside an HTTP 200 (`{"success": false, "errors": [...]}`: an import dry run, a bundle
    restore of a bundle that is not there). The emission axis took every 2xx for work done and waited for the
    event, so the cloud-op sweep of 2026-09-30 reported "REAL MISS: AgentImported ... silent NO-OP" for a dry run
    that correctly emitted nothing. The route's own `success: false` is the evidence; the axis reads it."""
    ex = row.get("response_excerpt")
    if isinstance(ex, dict) and ex.get("success") is False:
        errs = ex.get("errors")
        return ("the call answered success=false" + (f" ({str(errs)[:120]})" if errs else "")
                + " — nothing was done, so there is no event to expect")
    return None


# §EMITDIAG 2026-09-07 — HIS REPORT: "ES query unavailable for A2APaymentAuthorized,
# i think this is emitted. i am sure." It was: 1,228 rows in sbx-alpha's EventStore.
# THE EVENTSTORE TO POLL IS A PROPERTY OF THE *TARGET*, NOT OF THE CONSOLE.
# The sweep executes against API_TEST_TARGET_URL, so its events land in THAT frame's
# store. A console driving another frame (EU --tester-console → sbx-alpha) had no
# API_TEST_EVENT_STORE_URL of its own and fell to the literal `event-store-test`,
# a hostname retired with the old sandbox tier: every poll raised gaierror, every
# type went 'unknown', and 93 rows reported "ES query unavailable" about a store
# nobody had asked for. A literal default is a second, independently-rottable copy
# of a fact the target already carries — the one-fact-two-places class.
def _derive_es_url_from_target(target_url: str) -> str:
    """§TRUSTCHAIN P4.6: ONE rule, in core/es_url_for_target.py (shared with the api-tester and its
    event verifier). Kept as a name because the tester and its tests call it."""
    from ..core.es_url_for_target import es_url_for_target
    return es_url_for_target(target_url)


_EMIT_ES_URL = (os.getenv("API_TEST_EVENT_STORE_URL")
                or _derive_es_url_from_target(API_TEST_TARGET_URL)).rstrip("/")
# §PROXYKEY 2026-09-11: no literal default (it matched no live EventStore key); unset = unreadable, said so.
_EMIT_ES_KEY = os.getenv("API_TEST_EVENT_STORE_API_KEY", "")
# §CLOUDOPMCP2 2026-09-05 — how long to keep ASKING the EventStore for an expected
# event before calling it missing. A single snapshot at run-end races async emitters
# (TEG balance outbox, reactors, eventstore_balance_sync); with a window, "missing"
# means "still absent after this many seconds", which is a claim about the SYSTEM
# rather than about when we happened to look. 0 disables the wait (one pass only).
_EMIT_SETTLE_S = float(os.getenv("API_TEST_EMIT_SETTLE_S", "25"))
_EMIT_SETTLE_STEP_S = float(os.getenv("API_TEST_EMIT_SETTLE_STEP_S", "2.5"))
# §V0135: shared secret that authenticates the proxied api-test sweep on
# registry-test (registry-a's forwarded admin bearer is invalid there — different
# JWT secret). Mirrors _EMIT_ES_KEY; must match registry-test's value.
# §PROXYKEY 2026-09-11: ONE reader (`core/api_test_proxy_key`), no default, refused by shape.
# The literal default that stood here was the live key on every node, sender and receiver alike.
from ..core.api_test_proxy_key import presented_key_ok as _proxy_key_ok, proxy_headers as _proxy_headers  # noqa: E402
_DID_RE = re.compile(r"did:[a-z]+:(?:[a-z0-9][a-z0-9.-]{0,61}[a-z0-9]:)?[0-9a-fA-F-]{6,}")  # §DIDWIDEN: tolerate <issuer>:

# ── emission_integrity HONESTY flag (2026-06-26) ───────────────────────────
# The sandbox-B EventStore (receiver frame) — plain internal HTTP, same hostname
# the cross-frame replication path uses (NOT the nginx mTLS gateway). Used to
# confirm a cross-frame transfer actually CREDITED the B frame, not just opened
# 2PC on A. The nginx :8443 gateways are the mTLS surface the registry probes
# with verification to catch expired/rotated SPIRE bundles (the documented
# CERTIFICATE_VERIFY_FAILED break).
# §EMITDIAG-4 2026-09-07 — THE SAME ROT, THREE MORE TIMES. Fixing the A-side store
# left its three siblings pointing at the retired tier, and the first EU-driven run
# said so: `es_reachable` and `supply_transit` WARNed "sandbox-B EventStore
# unreachable" while `mtls_handshake` named `nginx-event-store-test:8443` inside a
# DNS error. "Unreachable" is a claim about the network and it was false — no
# address was ever configured. Widening a callee does not narrow the questions its
# callers ask (§FANOUTFIX): after fixing one site, grep the others.
_EMIT_ES_B_URL = os.getenv("API_TEST_EVENT_STORE_B_URL", "").rstrip("/")
# §EMITKEY 2026-09-05: each frame's EventStore authenticates with its OWN
# internal key. One shared key works only on a tier where both frames share one
# (the retired sandbox tier did). Where they differ, every B-side poll 403s and
# _es_count returns None, so all four cross-frame checks silently read
# "unknown" — indistinguishable from "the transfer never settled". Defaults to
# _EMIT_ES_KEY, so a single-key tier behaves exactly as it did before.
_EMIT_ES_B_KEY = os.getenv("API_TEST_EVENT_STORE_B_API_KEY", _EMIT_ES_KEY)
# ⚠ 2026-09-27: SUPERSEDED IN PART. Every frame of this network now ships `<frame>-nginx-event-store:8443` (the
# sandbox pair included); a console still cannot verify another trust domain's gateway, so with these unset the
# check asks the TARGET (`/es-mtls-handshake`, §PEERVANTAGE), which verifies its own with its own SVID.
# §EMITDIAG-4: unset by default. `nginx-event-store-test` is Frame A's old sandbox
# gateway; THE CURRENT SANDBOX TIER SHIPS NO ES mTLS GATEWAY CONTAINER AT ALL (only
# `sbx-*-nginx-federation` and `-nginx-teg`), so this check has been probing a host
# that cannot exist, on every run and on both drivers, and reporting it as a gateway
# being down. A check with no target is NOT APPLICABLE — a third state, not a
# failure — and "unreachable" about a thing never configured is the invented-cause
# class wearing a network costume.
_ES_MTLS_GW_A = os.getenv("API_TEST_ES_MTLS_GATEWAY_A", "").rstrip("/")
_ES_MTLS_GW_B = os.getenv("API_TEST_ES_MTLS_GATEWAY_B", "").rstrip("/")
# transit_net asymmetry tolerance — the auditor notes ±1-2 cosmetic read-skew
# under cross-frame load; anything beyond that is a real stuck-in-transit tell.
_TRANSIT_ASYMMETRY_TOL = float(os.getenv("API_TEST_TRANSIT_ASYMMETRY_TOL", "2.0"))


def _es_verify():
    """§TESTBED (2026-09-19): the TLS context every read of a target's store uses: the SPIRE bundle and the system roots,
    presenting this registry's own SVID. A kit frame's store listens only behind its mTLS gateway (measured: nothing on
    :8200, the gateway answers the SVID), so a client without the certificate could not read it at all; over a plain
    http store (the network's sandbox pair) the context is unused."""
    from ..es_ssl_helper import get_httpx_verify
    return get_httpx_verify()


def _es_key_for(base_url: str) -> str:
    """Pick the internal key belonging to the EventStore actually being polled."""
    return _EMIT_ES_B_KEY if base_url.rstrip("/") == _EMIT_ES_B_URL else _EMIT_ES_KEY


def _emit_satisfied(event_type: str, seen: Optional[Dict[str, bool]]) -> bool:
    """ONE rule for 'this event type has landed', used by BOTH the settle-poller and
    the per-row verdict. Two copies of this predicate drifting apart is how a row
    reads MISS while the poller thinks it is satisfied."""
    if not seen:
        return False
    if event_type in _EMIT_CANARY_NOISY:
        return bool(seen.get("matched"))
    return bool(seen.get("present") or seen.get("matched"))


async def _peer_facts_via_target(cli: httpx.AsyncClient, since_iso: str) -> Optional[Dict[str, Any]]:
    """Ask the TARGET for its own peer-EventStore facts. None when unavailable.

    §PEERVANTAGE. Deliberately best-effort and silent-on-failure at the call site's
    level, because the CALLER already reports an honest NOT-MEASURED when this
    returns nothing — a relay that raises would convert a missing route into a
    broken check, which is the opposite of the point."""
    if not API_TEST_TARGET_URL:
        return None
    try:
        resp = await cli.get(
            f"{API_TEST_TARGET_URL}/api/v1/admin/mcp-tester/peer-es-facts",
            params={"since": since_iso},
            headers=_proxy_headers(),
        )
        if resp.status_code != 200:
            return None
        body = resp.json() or {}
        return body if body.get("reachable") else None
    except Exception:
        return None


def _local_read_note(emit_diag: Optional[Dict[str, str]]) -> str:
    """" · local events <how they were read>" when the TARGET read this run's own store for the console (V0542's
    relay), else "". §MCPTEST30 (V0545): the relay filled the reading, but `local_emission` and `es_reachable` still
    said "ES-VERIFIED" / "both EventStores reachable" as if this console had looked; a reader then goes looking for a
    route the console does not have. The run log said it once; the verdicts now say it too."""
    via = (emit_diag or {}).get("__via_target__")
    return f" · local events {via}" if via else ""


async def _emissions_via_target(since_iso: str, sweep_dids: set, expect_types: Sequence[str],
                                flow_name: str) -> Optional[Tuple[Dict[str, Dict[str, bool]], Dict[str, str]]]:
    """Ask the TARGET to run the emission poll for this flow; None when it cannot answer.

    §MCPTEST30 (V0542). A cloud-op delta sweep's events land in its operator's parent store, sbx-beta's, and EU's
    console cannot resolve that name ("Temporary failure in name resolution" on every type), so every delta run read
    NOTHING VERIFIED while its peer facts, relayed through the target since §PEERVANTAGE, read fine. The target reaches
    the store; this asks it the same question. Best-effort like `_peer_facts_via_target`: a relay that fails leaves the
    caller's honest unreadable reading in place."""
    if not API_TEST_TARGET_URL:
        return None
    try:
        async with httpx.AsyncClient(verify=_es_verify(), timeout=_EMIT_SETTLE_S + 60) as cli:
            resp = await cli.post(
                f"{API_TEST_TARGET_URL}/api/v1/admin/mcp-tester/emissions-via-target",
                json={"since": since_iso, "dids": sorted(str(d) for d in sweep_dids)[:_RELAY_MAX_DIDS],
                      "expect_types": [str(t) for t in expect_types], "flow_name": flow_name or ""},
                headers=_proxy_headers(),
            )
        if resp.status_code != 200:
            return None
        body = resp.json() or {}
        seen, diag = body.get("seen"), body.get("diag")
        if not isinstance(seen, dict) or not seen:
            return None
        out = {str(k): {"present": bool(v.get("present")), "matched": bool(v.get("matched"))}
               for k, v in seen.items() if isinstance(v, dict)}
        return out, {str(k): str(v)[:300] for k, v in (diag or {}).items()} if isinstance(diag, dict) else {}
    except Exception:
        return None


_RELAY_MAX_DIDS = 5000


async def _es_count_at(cli: httpx.AsyncClient, base_url: str, event_type: str,
                       since_iso: str) -> Optional[int]:
    """Count locally-emitted events of `event_type` since `since_iso`. None = unreadable.

    §PEERVANTAGE: module scope on purpose — the relay endpoint and
    `_compute_emission_integrity` must count the same way, and a second copy of a
    read is how two callers start disagreeing about the same store."""
    try:
        resp = await cli.get(
            f"{base_url}/api/v1/events/export",
            params={"since": since_iso, "event_type": event_type, "limit": 500},
            headers={"X-Internal-Key": _es_key_for(base_url)},
        )
        if resp.status_code != 200:
            return None
        body = resp.json()
        evs = body.get("events", body) if isinstance(body, dict) else body
        return len(evs) if isinstance(evs, list) else None
    except Exception:
        return None


async def _supply_transit_at(cli: httpx.AsyncClient, base_url: str):
    """(transit_net, delta) from a frame's supply-audit, or (None, None)."""
    try:
        resp = await cli.get(
            f"{base_url}/api/v1/projections/supply-audit",
            headers={"X-Internal-Key": _es_key_for(base_url)},
        )
        if resp.status_code != 200:
            return None, None
        body = resp.json() or {}
        return float(body.get("transit_net", 0.0)), float(body.get("delta", 0.0))
    except Exception:
        return None, None


def _first_emit_reason(diag: Optional[Dict[str, str]]) -> str:
    """The most common per-type reason in a diag map, for a ONE-LINE verdict.

    §EMITDIAG: when every type failed for the same reason (a dead hostname, a bad
    key), repeating it per row is noise; naming it once is the finding. Reserved
    `__`-keys are book-keeping, not reasons."""
    if not diag:
        return ""
    reasons = [v for k, v in diag.items() if not k.startswith("__") and v]
    if not reasons:
        return ""
    top = max(set(reasons), key=reasons.count)
    n = reasons.count(top)
    return f"{top} ({n} event-type(s))" if n > 1 else top


# §MCPTEST30 (2026-09-30): the store a cloud-op sweep's events land in is the OPERATOR'S PARENT frame's (an operator
# has no EventStore of its own; api_tests/multiframe_helpers.SANDBOX_OPERATOR_TARGETS names each one's parent). For
# sandboxalpha that is the target frame's own store, which is why it read right; sandboxdelta is parented under
# sandbox-B, and its 2026-09-30 sweep reported 8 "REAL MISS" emitters (createOrganization, submitFundingRequest, ...)
# whose events were sitting in sbx-beta's store (OrganizationCreated x2 in the window, none in sbx-alpha's).
_FLOW_EMISSION_STORE = {"flow_mcp_lifecycle_cloudop_sandboxdelta_complete": "B"}


def _emission_store_for(flow_name: str) -> Tuple[str, str]:
    """(url, internal key) of the store whose events this flow's calls produce; the target's by default."""
    if _FLOW_EMISSION_STORE.get(flow_name or "") == "B" and _EMIT_ES_B_URL:
        return _EMIT_ES_B_URL, _EMIT_ES_B_KEY
    return _EMIT_ES_URL, _EMIT_ES_KEY


async def _collect_emissions(
    since_iso: str,
    sweep_dids: set,
    *,
    expect_types: Optional[Sequence[str]] = None,
    diag: Optional[Dict[str, str]] = None,
    flow_name: str = "",
) -> Dict[str, Dict[str, bool]]:
    """Poll the sandbox EventStore for every event_type the emit-catalogue
    declares, since the sweep started. Returns
        {event_type: {"present": bool, "matched": bool}}
    `matched` = ≥1 event of that type carries a sweep-agent DID anywhere in its
    payload (disambiguates canary/background noise). Best-effort: a type left
    absent (ES error) renders the axis 'unknown', never a false 'fail'.

    §EMITDIAG 2026-09-07: an unreadable type now records WHY in `diag` (a caller-
    owned dict, `{event_type: reason}` plus the reserved keys `__url__`/`__cause__`).
    A bare `continue` collapsed four different failures — wrong hostname, bad key,
    timeout, empty store — into the single word "unavailable", so the axis could
    state what it observed but never what it could not distinguish. A probe may
    report what it saw; it must not leave the reader to invent the cause.
    """
    want_types = sorted({t for types in _EMIT_MAP.values() for t in types})
    out: Dict[str, Dict[str, bool]] = {}
    diag = {} if diag is None else diag
    _es_url, _es_key = _emission_store_for(flow_name)
    diag["__url__"] = _es_url or "(unset — could not derive from API_TEST_TARGET_URL)"
    if not _es_url:
        # Nothing to poll, and saying so BY NAME beats 93 rows of "unavailable".
        diag["__cause__"] = (
            f"no EventStore configured for target {API_TEST_TARGET_URL} — set "
            f"API_TEST_EVENT_STORE_URL on this registry (the target's own store, "
            f"not this console's)"
        )
        for et in want_types:
            diag[et] = "no EventStore configured"
        return out

    async def _poll(cli: httpx.AsyncClient, types: Sequence[str]) -> None:
        """One pass over `types`, writing into `out`. A non-200 leaves the type
        ABSENT from `out` (→ 'unknown'), never a false 'fail' — but it records the
        REASON in `diag` so 'unknown' can name its own cause."""
        for et in types:
            # W4 (agentvault2-aa, 2026-10-25): the event under each name it may be written under (TokensTransferred and
            # UnitsTransferred), merged under the name this map keys it by. A name whose read fails leaves the verdict
            # unknown unless the event was found under another (a sighting is a sighting; an absence needs every read)
            events: List[Any] = []
            unread = False
            for _name in ledger_names.live_names(et):
                try:
                    resp = await cli.get(
                        f"{_es_url}/api/v1/events/export",
                        params={"since": since_iso, "event_type": _name, "limit": 500},
                        headers={"X-Internal-Key": _es_key},
                    )
                    if resp.status_code != 200:
                        diag[et] = f"HTTP {resp.status_code} from {_es_url}"
                        unread = True
                        continue
                    got = resp.json()
                    if isinstance(got, dict):
                        got = got.get("events", [])
                    if not isinstance(got, list):
                        diag[et] = f"HTTP 200 but body was {type(got).__name__}, not a list"
                        unread = True
                        continue
                    events.extend(got)
                except Exception as _e:
                    diag[et] = f"{type(_e).__name__}: {_e}"[:200]
                    unread = True
                    continue
            if unread and not events:
                continue
            matched = False
            if sweep_dids:
                for ev in events:
                    # §MCPTEST30 (V0638): the event's own subject too. ReputationChanged names its agent only in
                    # aggregate_id (its data: old_score, new_score, reason), so a match on data alone could never
                    # see a sweep's signal, and every applyReputationSignal that answered 2xx read as a miss
                    blob = json.dumps([ev.get("aggregate_id"), ev.get("data") or ev], default=str)
                    if any(d in blob for d in sweep_dids):
                        matched = True
                        break
            if unread and not matched and sweep_dids and et in _EMIT_CANARY_NOISY:
                continue                    # a DID-matched type: only a match is a verdict while a read failed
            out[et] = {"present": len(events) > 0, "matched": matched}
            diag.pop(et, None)              # a later pass that SUCCEEDS clears the reason

    try:
        # §SOVKIT T5 (2026-09-14): the target store's TLS context (SPIRE bundle + system roots + the SVID), never verify=False
        from ..es_ssl_helper import get_httpx_verify
        async with httpx.AsyncClient(verify=get_httpx_verify(), timeout=6) as cli:
            await _poll(cli, want_types)
            if not out:
                # §MCPTEST30 (V0542): not one type was readable (the store's name does not resolve from this node,
                # or every read was refused): there is nothing to settle against, and waiting out the settle window
                # on failing reads only delays the caller, which asks the target (`_emissions_via_target`)
                return out

            # §CLOUDOPMCP2 2026-09-05 — SETTLE WINDOW (his instruction: "the expected
            # events are queried in the ES ... a little later ... only this can proof
            # if the event landed").
            # A SINGLE snapshot taken the instant the sweep ends races every
            # asynchronous emitter in the system — the TEG balance outbox, the
            # reactor framework, eventstore_balance_sync — so a slow-but-correct
            # emission reads as a MISS and latency masquerades as a silent NO-OP.
            # The opposite error matters too: without a wait, "absent" is a claim
            # about WHEN we looked, not about whether the event exists.
            # So: re-ask the EventStore for exactly the types some 2xx call is still
            # WAITING ON, until they land or the window closes. A miss then means
            # "still absent after N seconds", which is a claim worth making.
            # Only EXPECTED types are re-polled — re-polling all 93 would spend the
            # whole window waiting on types nothing in this run should have emitted.
            if expect_types:
                deadline = time.monotonic() + _EMIT_SETTLE_S
                pending = [t for t in dict.fromkeys(expect_types)
                           if not _emit_satisfied(t, out.get(t))]
                while pending and time.monotonic() < deadline:
                    await asyncio.sleep(_EMIT_SETTLE_STEP_S)
                    await _poll(cli, pending)
                    pending = [t for t in pending if not _emit_satisfied(t, out.get(t))]
                if pending:
                    logger.info(
                        "[mcp-tester] emission settle window (%.0fs) closed with %d "
                        "expected type(s) still absent: %s",
                        _EMIT_SETTLE_S, len(pending), ",".join(sorted(pending)[:10]),
                    )
    except Exception:
        pass
    return out


# ─────────────────────────────────────────────────────────────────────────────
# emission_integrity HONESTY flag (2026-06-26)
# ─────────────────────────────────────────────────────────────────────────────
# WHY: the MCP federation suite reads ~98.6%/0-fail even though sandbox
# cross-frame settlement has been DEAD for ~3 weeks. It passes DISHONESTLY:
#   (1) `cross_frame_drift` is a response-SHAPE diff of two LOCAL reads — it
#       never queries an ES, never crosses A↔B.
#   (2) the cross-frame lifecycle asserts only `CrossFrameTransferInitiated`
#       (lands on the LOCAL ES the instant 2PC opens, pre-mTLS) — NOT
#       `CrossFrameTransferSettled` / the B-frame credit.
# This computes a SEPARATE, visible DEGRADED/WARN signal from real ES polls +
# an mTLS handshake — WITHOUT touching the per-row pass/fail or the run status
# ("completed" stays "completed"; rows stay their color). Every check is fully
# defensive: any exception → that check is `warn` ("probe failed"), never an
# unhandled raise that would break the run.
class _MtlsCheckDone(Exception):
    """Control-flow sentinel: the mTLS verdict is already decided (no gateway to
    probe). A bare `return` will not do — the checks after this one still have to run
    — and falling into the generic `except` would relabel a deliberate NOT-MEASURED
    as `probe failed`."""


def _build_mtls_probe_ctx() -> Optional[ssl.SSLContext]:
    """SSL context for verifying the ES mTLS gateways (:8443).

    Prefers the registry's own cached ES context (es_ssl_helper). That helper
    returns None when EVENT_STORE_URL is plain-HTTP (the sandbox case) even
    though the :8443 gateways DO present SPIRE server certs — so fall back to
    building a context straight off the on-disk SPIRE bundle. Returns None only
    when no bundle exists at all (→ the check degrades to 'warn', never a false
    'degraded')."""
    try:
        ctx = get_es_ssl_context()
        if ctx is not None:
            return ctx
    except Exception:
        pass
    try:
        cert_dir = os.getenv("SVID_CERT_DIR", os.getenv("CERT_DIR", "/certs"))
        bundle = os.path.join(cert_dir, "bundle.0.pem")
        cert = os.path.join(cert_dir, "svid.0.pem")
        key = os.path.join(cert_dir, "svid.0.key")
        if not os.path.exists(bundle):
            return None
        ctx = ssl.create_default_context(cafile=bundle)
        try:
            ctx.load_default_certs(ssl.Purpose.SERVER_AUTH)
        except Exception:
            pass
        if os.path.exists(cert) and os.path.exists(key):
            ctx.load_cert_chain(cert, key)
        return ctx
    except Exception:
        return None


# The two answers that are a certificate break, whichever side's certificate it was.
_CERT_BREAKS = ("cert_fail", "client_cert_refused")
# nginx's own page when `ssl_verify_client on` refuses the CLIENT's certificate after the handshake completed:
# "400 No required SSL certificate was sent" (none presented) or "400 The SSL certificate error" (not trusted).
_NGINX_CLIENT_CERT_REFUSAL = re.compile(r"<title>\s*(400[^<]*SSL certificate[^<]*?)\s*</title>", re.IGNORECASE)


def _classify_http_answer(status: int, body: str) -> Tuple[str, str]:
    """An HTTP answer proves the handshake completed and the SERVER's certificate verified; it does not prove the
    CLIENT's was accepted. nginx with `ssl_verify_client on` completes the handshake and then answers 400 naming the
    certificate, which "any HTTP answer = tls_ok" read as a pass (agentvault2-41's review of 52be7f5e, 2026-09-27)."""
    if status == 400:
        m = _NGINX_CLIENT_CERT_REFUSAL.search(body or "")
        if m:
            return "client_cert_refused", m.group(1)
    return "tls_ok", str(status)


def _svid_on_disk() -> bool:
    """Whether this node holds the SVID its TLS contexts present as a client certificate (the path `es_ssl_helper` and
    `_build_mtls_probe_ctx` both load it from). Without one, a refused client certificate is the probe's own gap."""
    cert_dir = os.getenv("SVID_CERT_DIR", os.getenv("CERT_DIR", "/certs"))
    return all(os.path.exists(os.path.join(cert_dir, f)) for f in ("svid.0.pem", "svid.0.key"))


async def _probe_gateway(url: str, ctx: Optional[ssl.SSLContext]) -> Tuple[str, str]:
    """ONE classifier for the console's probe and the target's: ("tls_ok", status) when the handshake completed and the
    gateway did not refuse the client certificate, ("client_cert_refused", nginx's sentence) when it did,
    ("cert_fail", why) when the server's certificate failed verification, ("unreachable", why) otherwise."""
    try:
        connector = aiohttp.TCPConnector(ssl=ctx) if ctx else aiohttp.TCPConnector()
        async with aiohttp.ClientSession(connector=connector, timeout=aiohttp.ClientTimeout(total=6)) as s:
            async with s.get(f"{url}/health") as resp:
                body = (await resp.content.read(2048)).decode("utf-8", "replace") if resp.status == 400 else ""
                return _classify_http_answer(resp.status, body)
    except (aiohttp.ClientConnectorCertificateError, aiohttp.ClientConnectorSSLError, ssl.SSLError) as e:
        return "cert_fail", str(e)[:160]
    except Exception as e:
        return "unreachable", f"{type(e).__name__}: {str(e)[:120]}"


def _own_es_gateway() -> str:
    """This node's OWN EventStore mTLS gateway: its https EVENT_STORE_URL (the frame's nginx-event-store:8443), "" when
    the node writes to its store over plain http and so has no gateway to verify."""
    url = (os.getenv("EVENT_STORE_URL") or "").strip().rstrip("/")
    return url if url.startswith("https://") else ""


async def _own_gateway_handshake() -> Dict[str, Any]:
    """§PEERVANTAGE for the mTLS check (2026-09-27, his ask on run b487126bc7274966): the handshake a console cannot verify
    (another trust domain) measured from the node that owns the gateway, with its own SVID and bundle. Four answers:
    tls_ok, cert_fail, unreachable, not_applicable."""
    gw = _own_es_gateway()
    if not gw:
        return {"gateway": None, "result": "not_applicable", "presented_client_cert": False,
                "detail": "this node writes to its store over plain http (EVENT_STORE_URL is not https): no gateway"}
    ctx = _build_mtls_probe_ctx()
    if ctx is None:
        return {"gateway": gw, "result": "not_applicable", "presented_client_cert": False,
                "detail": "no SPIRE bundle on this node"}
    presented = _svid_on_disk()
    result, detail = await _probe_gateway(gw, ctx)
    return {"gateway": gw, "result": result, "detail": detail, "presented_client_cert": presented}


def _grade_target_handshake(status_code: Optional[int], body: Any) -> Tuple[str, str]:
    """The check's (status, detail) from the TARGET's answer to /es-mtls-handshake. A target that does not serve the probe
    (an image older than it: 404) or answers nothing readable stays an honest NOT MEASURED, never a failure."""
    if status_code == 404:
        return "warn", ("the target does not serve the handshake probe (its image predates it), and this console has no "
                        "gateway of its own configured: NOT MEASURED, not failing")
    if status_code == 401:
        return "warn", ("the target refused this console's proxy key (API_TEST_PROXY_INTERNAL_KEY unset, refused by shape, "
                        "or different on one side; the answer cannot say which): NOT MEASURED, not failing")
    if status_code != 200 or not isinstance(body, dict):
        return "warn", f"the target's handshake probe answered HTTP {status_code}: NOT MEASURED, not failing"
    gw, result, detail = body.get("gateway"), body.get("result"), str(body.get("detail") or "")[:200]
    presented = body.get("presented_client_cert") is True
    if result == "tls_ok":
        how = ("its own SVID and SPIRE bundle" if presented
               else "its SPIRE bundle (no client certificate presented, and the gateway asked for none)")
        return "ok", f"ES mTLS gateway handshake verified FROM THE TARGET with {how}: {gw} answered HTTP {detail}"
    if result == "client_cert_refused" and presented:
        return "degraded", (f"the target's own ES mTLS gateway {gw} REFUSED the target's own client certificate (its "
                            f"SVID) after the handshake: {detail}")
    if result == "client_cert_refused":
        return "warn", (f"the target's own ES mTLS gateway {gw} requires a client certificate and the target held no "
                        f"SVID to present ({detail}): NOT MEASURED, not failing")
    if result == "cert_fail":
        return "degraded", (f"the target's own ES mTLS gateway {gw} FAILED certificate verification with the target's "
                            f"own bundle (same trust domain: an expired or rotated SPIRE bundle): {detail}")
    if result == "unreachable":
        return "warn", f"the target's own ES mTLS gateway {gw} is unreachable from the target: {detail}"
    return "warn", f"the target has no ES mTLS gateway to verify ({detail}): NOT MEASURED, not failing"


async def _compute_emission_integrity(
    run_start: float,
    flow_values: Dict[str, Any],
    summary: Dict[str, Any],
    slim_results: List[Dict[str, Any]],
    sweep_dids: Optional[set] = None,
    emit_seen: Optional[Dict[str, Dict[str, bool]]] = None,
    emit_diag: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Honest emission / cross-frame integrity verdict for the sweep.

    Returns
        {"status": "ok"|"warn"|"degraded",
         "checks": {<name>: {"status": ..., "detail": "..."}, ...},
         "summary": "<one-line>"}

    Overall status = degraded if ANY check is degraded, else warn if ANY check
    is warn, else ok. EVERY check is defensive — a probe exception yields a
    `warn` for that check, never a raise. This NEVER mutates pass/fail rows or
    the run status; it is a sidecar honesty signal.
    """
    since_iso = datetime.fromtimestamp(run_start, timezone.utc).isoformat()
    emit_seen = emit_seen or {}
    emit_diag = emit_diag or {}
    # §EMITDIAG: one sentence naming the store and why it could not be read, so a
    # WARN points at the instrument's configuration instead of at the rails.
    _es_why = (emit_diag.get("__cause__") or _first_emit_reason(emit_diag) or "")
    _es_where = f" [store={emit_diag.get('__url__', '?')}"  + (f" · {_es_why}" if _es_why else "") + "]"
    # ⚠ bound OUTSIDE the f-string on purpose: a multi-line expression inside f-string
    # braces is valid on the HOST's python 3.12 (PEP 701) and a SyntaxError on the
    # image's 3.11 — a host-side py_compile cannot see it, the in-image one can.
    _es_named = _EMIT_ES_URL or f"unset — no store derivable from {API_TEST_TARGET_URL}"
    checks: Dict[str, Dict[str, str]] = {}

    async def _es_count_foreign(cli: httpx.AsyncClient, base_url: str, event_type: str) -> Optional[int]:
        """Count REPLICATED (foreign) events of `event_type` since run-start.

        §MCPTEST-MCP10b. `_es_count` reads /events/export, which returns only
        LOCALLY-emitted rows. A cross-frame settle is emitted by the RECEIVER
        and reaches the sender's EventStore through replication, landing in
        `foreign_events` — so a sender that never emits its own settle looks,
        to /events/export alone, exactly like a transfer that never settled.
        MEASURED on sandbox-A: 0 local Settled, and `foreign_events` carrying
        the settle at 16:17:54.229485 — the same millisecond sandbox-B wrote it.
        """
        try:
            resp = await cli.get(
                f"{base_url}/api/v1/events/foreign",
                params={"since": since_iso, "event_type": event_type, "limit": 500},
                headers={"X-Internal-Key": _es_key_for(base_url)},
            )
            if resp.status_code != 200:
                return None
            events = resp.json()
            if isinstance(events, dict):
                events = events.get("events", [])
            if not isinstance(events, list):
                return None
            return len(events)
        except Exception:
            return None

    async def _es_count(cli: httpx.AsyncClient, base_url: str, event_type: str) -> Optional[int]:
        """Count events of `event_type` on `base_url`'s ES since run-start.
        Mirrors _collect_emissions' /events/export poll. None = unreadable."""
        try:
            resp = await cli.get(
                f"{base_url}/api/v1/events/export",
                params={"since": since_iso, "event_type": event_type, "limit": 500},
                headers={"X-Internal-Key": _es_key_for(base_url)},
            )
            if resp.status_code != 200:
                return None
            events = resp.json()
            if isinstance(events, dict):
                events = events.get("events", [])
            if not isinstance(events, list):
                return None
            return len(events)
        except Exception:
            return None

    async def _supply_transit(cli: httpx.AsyncClient, base_url: str):
        """Return (transit_net, delta) floats from a frame's supply-audit, or
        (None, None) on any failure."""
        try:
            resp = await cli.get(
                f"{base_url}/api/v1/projections/supply-audit",
                headers={"X-Internal-Key": _es_key_for(base_url)},
            )
            if resp.status_code != 200:
                return None, None
            body = resp.json() or {}
            return float(body.get("transit_net", 0.0)), float(body.get("delta", 0.0))
        except Exception:
            return None, None

    # Shared counts harvested once so several checks can reuse them.
    a_init = a_settled = a_refunded = None   # local (A) cross-frame counts
    b_settled = None                          # receiver-frame (B) settled count
    a_transit = b_transit = None
    a_settled_foreign = None
    a_delta = b_delta = None

    try:
        async with httpx.AsyncClient(verify=_es_verify(), timeout=8) as cli:
            a_init     = await _es_count(cli, _EMIT_ES_URL, "CrossFrameTransferInitiated")
            a_settled  = await _es_count(cli, _EMIT_ES_URL, "CrossFrameTransferSettled")
            a_refunded = await _es_count(cli, _EMIT_ES_URL, "CrossFrameTransferRefunded")
            b_settled  = await _es_count(cli, _EMIT_ES_B_URL, "CrossFrameTransferSettled")
            a_settled_foreign = await _es_count_foreign(cli, _EMIT_ES_URL, "CrossFrameTransferSettled")
            a_transit, a_delta = await _supply_transit(cli, _EMIT_ES_URL)
            b_transit, b_delta = await _supply_transit(cli, _EMIT_ES_B_URL)
            # §PEERVANTAGE: if THIS console cannot see the peer store, ask the TARGET,
            # which by construction can — it is the frame whose peer that store is.
            # Only on failure: a console that CAN read it directly keeps doing so, so
            # the relay adds a hop for nobody who does not need one.
            if b_settled is None and b_transit is None:
                _relayed = await _peer_facts_via_target(cli, since_iso)
                if _relayed:
                    b_settled = _relayed.get("settled_count")
                    b_transit = _relayed.get("transit_net")
                    b_delta   = _relayed.get("delta")
                    _b_via = _relayed.get("store")
                    emit_diag["__peer_via_target__"] = (
                        f"peer facts read THROUGH {API_TEST_TARGET_URL} "
                        f"(store {_b_via}) — this console has no route of its own")
    except Exception as e:
        logger.debug(f"[mcp-tester] emission_integrity ES-poll setup failed: {e!r}")

    async def _settlement_appeared_on_recheck() -> bool:
        """One delayed re-read before calling a settlement dead.

        §MCPTEST-MCP10d. The settle is emitted by the RECEIVER and replicates
        back; the emission probe runs immediately after the sweep, so a transfer
        that settles a second later reads as "never settled" on the first look.
        Run 17875517 flipped to `degraded` for exactly that reason while the
        previous run — same code, same path — read `warn`. Classifying on a
        single unmeasured read is the mistake this whole pass has been unwinding.
        """
        try:
            await asyncio.sleep(6)
            async with httpx.AsyncClient(verify=_es_verify(), timeout=8) as c2:
                for base, fn in ((_EMIT_ES_URL, _es_count), (_EMIT_ES_URL, _es_count_foreign),
                                 (_EMIT_ES_B_URL, _es_count)):
                    n = await fn(c2, base, "CrossFrameTransferSettled")
                    if (n or 0) > 0:
                        return True
        except Exception:
            pass
        return False

    # ── Check 1: crossframe_settlement (LOCAL ES — A) ──────────────────────
    try:
        if a_init is None or a_settled is None or a_refunded is None:
            checks["crossframe_settlement"] = {
                "status": "warn",
                # §EMITDIAG-2: the store was NAMED BY A LITERAL here too — the same
                # retired hostname, in the sentence a reader trusts to tell them
                # which store failed. Found by the in-image content gate expecting
                # one occurrence and getting four. Name the one actually read.
                "detail": ("could not read local EventStore "
                           f"({_es_named}) — cross-frame settlement unverified"),
            }
        elif a_init > 0 and a_settled == 0 and (a_settled_foreign or 0) == 0 and (b_settled or 0) == 0 \
                and not await _settlement_appeared_on_recheck():
            checks["crossframe_settlement"] = {
                "status": "degraded",
                "detail": f"cross-frame transfers initiate but NEVER settle "
                          f"({a_init} initiated / 0 settled locally / 0 replicated / "
                          f"0 on the receiver / {a_refunded} refunded since run-start) "
                          f"— 2PC opens then stalls (the dead-settlement break)",
            }
        elif a_init > 0 and a_settled == 0:
            # §MCPTEST-MCP10b — SETTLED, just not emitted locally by the sender.
            # This branch used to be folded into "NEVER settle" above, which was
            # false and contradicted this check's own sibling
            # (`receiver_credit_b` reported OK about the SAME transfer). The
            # settle exists: the receiver emitted it and it replicated into this
            # frame's `foreign_events`. What is genuinely different from prod is
            # that prod's sender ALSO emits its own Settled locally
            # (frame-a holds 221,888 `agentvault.com -> frame-b` rows,
            # source_service=registry) off the synchronous 2PC commit, and the
            # sandbox sender does not — its `cross_teg_transfers` row stays
            # FUNDS_LOCKED. That is worth surfacing, but it is a sender-side
            # bookkeeping gap, not a failure to settle, and calling it
            # "never settles" overstates it.
            checks["crossframe_settlement"] = {
                "status": "warn",
                "detail": f"settled, but NOT by a local sender-side emit "
                          f"({a_init} initiated / 0 local / {a_settled_foreign or 0} replicated "
                          f"into foreign_events / {b_settled or 0} on the receiver / "
                          f"{a_refunded} refunded). Value moved and the receiver credited; "
                          f"the sender never wrote its own Settled and its cross_teg row "
                          f"stays FUNDS_LOCKED (prod emits it off the synchronous 2PC commit).",
            }
        elif a_init > 0 and a_refunded > a_settled:
            checks["crossframe_settlement"] = {
                "status": "degraded",
                "detail": f"cross-frame refunds dominate settlements "
                          f"({a_init} initiated / {a_settled} settled / {a_refunded} refunded "
                          f"since run-start) — settlement path failing",
            }
        elif a_init > 0 and a_refunded > 0.10 * (a_settled + a_refunded):
            checks["crossframe_settlement"] = {
                "status": "warn",
                "detail": f"elevated cross-frame refund rate "
                          f"({a_init} initiated / {a_settled} settled / {a_refunded} refunded, "
                          f"{100.0 * a_refunded / max(1, a_settled + a_refunded):.0f}% refunds "
                          f"since run-start) — settlement degrading",
            }
        elif a_init == 0:
            checks["crossframe_settlement"] = {
                "status": "ok",
                "detail": "no cross-frame transfers initiated since run-start "
                          "(0 — nothing to settle this sweep)",
            }
        else:
            checks["crossframe_settlement"] = {
                "status": "ok",
                "detail": f"{a_init} initiated / {a_settled} settled / {a_refunded} refunded "
                          f"(<10% refunds — incl. the intentionally-down sandbox-c path) — "
                          f"cross-frame 2PC closing healthy",
            }
    except Exception as e:
        checks["crossframe_settlement"] = {"status": "warn", "detail": f"probe failed: {e!r}"}

    # ── Check 2: receiver_credit_b (sandbox-B ES) ──────────────────────────
    try:
        if a_init is None:
            checks["receiver_credit_b"] = {
                "status": "warn",
                "detail": "local ES unreadable — cannot tell if a cross-frame transfer "
                          "occurred, so receiver-credit on B is unverified",
            }
        elif a_init == 0:
            checks["receiver_credit_b"] = {
                "status": "ok",
                "detail": "no cross-frame transfer occurred this sweep — nothing for "
                          "sandbox-B to credit",
            }
        elif b_settled is None:
            checks["receiver_credit_b"] = {
                "status": "warn",
                "detail": f"sandbox-A initiated {a_init} cross-frame transfer(s) but "
                          f"sandbox-B EventStore ({_EMIT_ES_B_URL}) is unreachable — "
                          f"receiver credit unverifiable (B isolated?)",
            }
        elif b_settled == 0:
            checks["receiver_credit_b"] = {
                "status": "degraded",
                "detail": f"sandbox-A initiated {a_init} cross-frame transfer(s) but sandbox-B "
                          f"shows 0 CrossFrameTransferSettled since run-start — the receiver "
                          f"frame was NEVER credited (settlement is dead, not just slow)",
            }
        else:
            checks["receiver_credit_b"] = {
                "status": "ok",
                "detail": f"sandbox-B shows {b_settled} CrossFrameTransferSettled since "
                          f"run-start ({a_init} initiated on A) — receiver credited",
            }
    except Exception as e:
        checks["receiver_credit_b"] = {"status": "warn", "detail": f"probe failed: {e!r}"}

    # ── Check 3: local_emission (promote the per-row event_emission axis) ───
    # Surface REAL MISSES (2xx call that emitted nothing) HERE as a degraded
    # integrity signal — WITHOUT flipping the offending row red.
    # §CLOUDOPMCP2 2026-09-05 — THIS CHECK COUNTED ONLY `fail`, so "no misses" and
    # "nothing was ever checked" produced the SAME green. Proven from the archive:
    # runs 46b6f346 and 590046e1 reported the identical sentence "every run-caused
    # 2xx emitter landed its EventStore event" while `es_reachable` was WARN and the
    # ES poll was 403ing on every event type — every row was `unknown`, zero rows
    # were `fail`, so the check said ok. The `all()`-over-empty trap wearing a
    # different hat. It now reports the POPULATION it actually verified, and refuses
    # to say ok on a verified count of zero.
    try:
        _emit_states: Dict[str, int] = {}
        miss_tools: List[str] = []
        for r in (slim_results or []):
            axis = ((r.get("axes") or {}).get("event_emission") or {})
            _s = axis.get("state")
            if _s:
                _emit_states[_s] = _emit_states.get(_s, 0) + 1
            if _s == "fail":
                miss_tools.append(r.get("tool", "") or "?")
        _verified = _emit_states.get("pass", 0)
        _unknown = _emit_states.get("unknown", 0)
        _pop = (f"verified={_verified} miss={len(miss_tools)} unknown={_unknown} "
                f"na={_emit_states.get('na', 0)} skip={_emit_states.get('skip', 0)}")
        if miss_tools:
            _shown = ", ".join(miss_tools[:8]) + (f" (+{len(miss_tools) - 8} more)" if len(miss_tools) > 8 else "")
            checks["local_emission"] = {
                "status": "degraded",
                "detail": f"{len(miss_tools)} tool(s) returned 2xx but emitted NO EventStore "
                          f"event (silent NO-OP / routing drop): {_shown} · {_pop}" + _local_read_note(emit_diag),
            }
        elif _verified == 0 and _unknown == 0 and _emit_states and not any(
                k not in ("na", "skip") for k in _emit_states):
            # §MCPTEST30 (2026-09-30): NO row was an emitter to check at all (every row na or skipped), which is a
            # different fact from "emitters ran and none was confirmed". The federation suite is the standing case:
            # its rows are TESTS, not tool calls, and every one read na, so each of its runs in the history carried a
            # "NOTHING VERIFIED" warn about a population that does not exist here (its emission coverage is its own
            # event tests: event_matrix, value_events, event_contract). Said as what it is, and not a warn.
            checks["local_emission"] = {
                "status": "na",
                "detail": f"no row of this run is a call to a known EventStore emitter, so there was nothing to "
                          f"verify here ({_pop})",
            }
        elif _verified == 0:
            # No row was actually confirmed against the EventStore. Saying "ok" here
            # is the exact failure this check was written to catch, aimed at itself.
            checks["local_emission"] = {
                "status": "warn",
                "detail": f"NOTHING VERIFIED — no 2xx emitter row was confirmed against the "
                          f"EventStore, so 'no misses' means 'nothing was looked at' ({_pop})."
                          + _es_where,
            }
        else:
            checks["local_emission"] = {
                "status": "ok",
                "detail": f"{_verified} 2xx emitter row(s) ES-VERIFIED, 0 real misses ({_pop})"
                          + _local_read_note(emit_diag),
            }
    except Exception as e:
        checks["local_emission"] = {"status": "warn", "detail": f"probe failed: {e!r}"}

    # ── Check 4: es_reachable (don't claim green if we couldn't even look) ──
    try:
        a_unreadable = (len(emit_seen) == 0)
        b_unreadable = (b_settled is None)
        b_unconfigured = not _EMIT_ES_B_URL
        # §PEERVANTAGE: bound BEFORE the chain, not spliced into the middle of it.
        # My first edit opened a SECOND if-chain after `elif a_unreadable`, so the
        # a-unreadable verdicts were written and then overwritten a few lines later —
        # a branch that runs in addition to, rather than instead of, its siblings.
        # Caught by reading the whole block instead of the hunk.
        _via = emit_diag.get("__peer_via_target__")
        if a_unreadable and b_unreadable:
            checks["es_reachable"] = {
                "status": "warn",
                "detail": "neither EventStore returned readable events — emission could "
                          "not be verified at all (not claiming green)" + _es_where,
            }
        elif a_unreadable:
            checks["es_reachable"] = {
                "status": "warn",
                "detail": "local EventStore returned no readable event-types — "
                          "emission largely unverified (not claiming green)" + _es_where,
            }
        elif not b_unreadable and _via:
            checks["es_reachable"] = {
                "status": "ok",
                "detail": f"both EventStores readable — {_via}" + _local_read_note(emit_diag),
            }
        elif b_unreadable and b_unconfigured:
            # NOT the same finding as a store that is down, and it printed as one.
            checks["es_reachable"] = {
                "status": "warn",
                "detail": ("no peer EventStore configured for this console "
                           "(API_TEST_EVENT_STORE_B_URL unset) — receiver-frame emission "
                           "NOT MEASURED: a gap in this console's setup, not a dead peer"
                           + _es_where),
            }
        elif b_unreadable:
            checks["es_reachable"] = {
                "status": "warn",
                "detail": f"sandbox-B EventStore ({_EMIT_ES_B_URL}) unreachable — "
                          "receiver-frame emission unverified (not claiming green)" + _es_where,
            }
        else:
            checks["es_reachable"] = {
                "status": "ok",
                "detail": f"both EventStores reachable ({len(emit_seen)} A event-types read, "
                          f"B settled-count readable)" + _local_read_note(emit_diag),
            }
    except Exception as e:
        checks["es_reachable"] = {"status": "warn", "detail": f"probe failed: {e!r}"}

    # ── Check 5: supply_transit (cross-frame transit_net asymmetry) ────────
    # Δ=0 is currency-blind self-consistency WITHIN each frame — it cannot see
    # cross-frame value stuck in transit. The real tell is A.transit_net +
    # B.transit_net diverging from 0: what left A as transit should have arrived
    # at B as transit. A persistent non-zero sum = stuck/lost cross-frame value.
    try:
        if a_transit is None or b_transit is None:
            checks["supply_transit"] = {
                "status": "warn",
                "detail": "supply-audit unavailable on "
                          + ("A" if a_transit is None else "")
                          + ("+B" if (a_transit is None and b_transit is None) else
                             ("B" if b_transit is None else ""))
                          + " — transit_net asymmetry unverified",
            }
        else:
            asym = abs(a_transit + b_transit)
            _base = (f"A.transit_net={a_transit:.2f} (Δ={a_delta:.4f}) · "
                     f"B.transit_net={b_transit:.2f} (Δ={b_delta:.4f}) · sum={a_transit + b_transit:.2f}")
            # The supply INVARIANT is Δ (per-frame net_supply == circulating). Δ≈0 means
            # the books balance: a large transit_net is STRUCTURAL cross-frame accounting
            # (FX triangle + cumulative flow), NOT stuck value. Genuine stuck/uncredited
            # cross-frame transfers are caught by the STRONG signals (crossframe_settlement
            # + receiver_credit_b). So flag a real Δ breach here, not the structural number.
            _delta_tol = max(_TRANSIT_ASYMMETRY_TOL, 5.0)  # absorb non-atomic read-skew
            if (a_delta is not None and abs(a_delta) > _delta_tol) or \
               (b_delta is not None and abs(b_delta) > _delta_tol):
                checks["supply_transit"] = {
                    "status": "degraded",
                    "detail": f"supply invariant BREACHED (A Δ={a_delta} / B Δ={b_delta} "
                              f"> tol {_delta_tol}) — real lost/stuck value. {_base}",
                }
            else:
                checks["supply_transit"] = {
                    "status": "ok",
                    "detail": f"supply invariant holds on both frames (Δ≈0); transit_net "
                              f"asymmetry {asym:.2f} is structural cross-frame accounting. {_base}",
                }
    except Exception as e:
        checks["supply_transit"] = {"status": "warn", "detail": f"probe failed: {e!r}"}

    # ── Check 6: mtls_handshake (verified TLS to the ES mTLS gateways) ──────
    # Highest-value: directly catches the expired/rotated SPIRE bundle break
    # (the 128 CERTIFICATE_VERIFY_FAILED/6h). The SAME-trust-domain gateway
    # (sandbox-A `nginx-event-store-test`) is authoritative — the registry's
    # bundle can actually validate it, so a cert failure there is a REAL expired
    # bundle (green when fresh, degraded when expired). The peer gateway
    # (sandbox-B) is cross-trust-domain: a verify failure there is EXPECTED
    # isolation (already surfaced by receiver_credit_b), so it is reported but
    # does NOT drive degraded — keeping this check honest once A is healed.
    try:
        if not (_ES_MTLS_GW_A or _ES_MTLS_GW_B):
            # §PEERVANTAGE (2026-09-27): no gateway configured HERE, and a console cannot verify another trust domain's
            # gateway anyway; the TARGET owns its gateway and the SVID + bundle that verify it, so it is asked instead.
            # Same client as the peer-es-facts relay (`_peer_facts_via_target`): same target, same key, same TLS context.
            _st, _det = "warn", ("no ES mTLS gateway configured for this console and no target to ask "
                                 "(API_TEST_TARGET_URL unset): NOT MEASURED, not failing")
            if API_TEST_TARGET_URL:
                try:
                    async with httpx.AsyncClient(verify=_es_verify(), timeout=15) as _cli:
                        _resp = await _cli.get(f"{API_TEST_TARGET_URL}/api/v1/admin/mcp-tester/es-mtls-handshake",
                                               headers=_proxy_headers())
                    _body = None
                    if _resp.status_code == 200:
                        try:
                            _body = _resp.json()
                        except ValueError:
                            _body = None
                    _st, _det = _grade_target_handshake(_resp.status_code, _body)
                except Exception as _e:
                    _det = (f"no ES mTLS gateway configured for this console and the target could not be asked "
                            f"({type(_e).__name__}): NOT MEASURED, not failing")
            checks["mtls_handshake"] = {"status": _st, "detail": _det}
            raise _MtlsCheckDone()
        probe_ctx = _build_mtls_probe_ctx()

        a_gw = await _probe_gateway(_ES_MTLS_GW_A, probe_ctx)
        b_gw = await _probe_gateway(_ES_MTLS_GW_B, probe_ctx)
        _gw_detail = (f"sandbox-A({_ES_MTLS_GW_A}): {a_gw[0]}[{a_gw[1]}] · "
                      f"sandbox-B({_ES_MTLS_GW_B}): {b_gw[0]}[{b_gw[1]}] "
                      f"(B cross-trust-domain failure is expected isolation, not the driver)")
        if probe_ctx is None:
            checks["mtls_handshake"] = {
                "status": "warn",
                "detail": "no SPIRE bundle on disk — cannot verify ES gateway mTLS. " + _gw_detail,
            }
        elif a_gw[0] in _CERT_BREAKS and _is_sandbox_target():
            # §MCPTEST-MCP10d — THE PREMISE ABOVE IS FALSE WHEN WE ARE PROXYING.
            # The comment claims sandbox-A is "same-trust-domain … the registry's
            # bundle can actually validate it". That holds only when the checker
            # IS sandbox-A's registry. This router runs on registry-a, whose SPIRE
            # bundle is the PROD `agentvault.com` domain, while sandbox-A's ES is
            # signed by sandbox-A's own SPIRE server — so the handshake can never
            # verify from here, no matter how fresh either bundle is.
            # MEASURED: from INSIDE registry-test,
            #   openssl s_client -connect nginx-event-store-test:8443 \
            #                    -CAfile /certs/bundle.0.pem  ->  "Verify return code: 0 (ok)"
            # while the same gateway fails from registry-a. The bundle was never
            # expired; the vantage point was wrong. This is precisely the
            # "expected isolation" the check already grants sandbox-B, applied
            # consistently instead of only to the peer.
            checks["mtls_handshake"] = {
                "status": "warn",
                "detail": "cross-trust-domain probe: this registry verifies against its "
                          "OWN SPIRE bundle and the target ES belongs to the sandbox "
                          "trust domain, so a verify failure here proves nothing about "
                          "the sandbox bundle (verified OK from inside the sandbox "
                          "registry itself). " + _gw_detail,
            }
        elif a_gw[0] == "client_cert_refused" and not _svid_on_disk():
            checks["mtls_handshake"] = {
                "status": "warn",
                "detail": ("the gateway requires a client certificate and this registry holds no SVID to present: "
                           "NOT MEASURED, not failing. " + _gw_detail),
            }
        elif a_gw[0] == "client_cert_refused":
            checks["mtls_handshake"] = {
                "status": "degraded",
                "detail": ("sandbox-A ES mTLS gateway REFUSED this registry's client certificate (its SVID) after "
                           "the handshake. " + _gw_detail),
            }
        elif a_gw[0] == "cert_fail":
            checks["mtls_handshake"] = {
                "status": "degraded",
                "detail": "sandbox-A ES mTLS gateway CERTIFICATE VERIFY FAILED — expired / "
                          "rotated SPIRE bundle (the documented break). " + _gw_detail,
            }
        elif a_gw[0] == "unreachable":
            checks["mtls_handshake"] = {
                "status": "warn",
                "detail": "sandbox-A ES mTLS gateway unreachable. " + _gw_detail,
            }
        else:
            checks["mtls_handshake"] = {
                "status": "ok",
                "detail": "ES mTLS gateway handshake verified (SPIRE bundle valid). " + _gw_detail,
            }
    except _MtlsCheckDone:
        pass          # the verdict is already set — a control-flow exit, not a failure
    except Exception as e:
        checks["mtls_handshake"] = {"status": "warn", "detail": f"probe failed: {e!r}"}

    # ── Aggregate ──────────────────────────────────────────────────────────
    states = [c.get("status") for c in checks.values()]
    if "degraded" in states:
        overall = "degraded"
    elif "warn" in states:
        overall = "warn"
    else:
        overall = "ok"

    degraded_names = [k for k, v in checks.items() if v.get("status") == "degraded"]
    warn_names = [k for k, v in checks.items() if v.get("status") == "warn"]
    try:
        _pp = float(summary.get("pass_pct", 0) or 0)
    except Exception:
        _pp = 0.0
    if overall == "degraded":
        one_line = (f"DEGRADED — {', '.join(degraded_names)} broke; cross-frame/emission "
                    f"integrity is compromised despite the {_pp:.2f}% strict pass-rate")
    elif overall == "warn":
        one_line = (f"WARN — {', '.join(warn_names)} could not be verified "
                    f"(not claiming green at {_pp:.2f}% pass-rate)")
    else:
        one_line = "OK — emission + cross-frame settlement verified end-to-end"

    return {"status": overall, "checks": checks, "summary": one_line}


async def _execute_sweep_background(run_id: str, dev_jwt: str, dev_id: int,
                                     flow_name: str = _DEFAULT_FLOW_NAME) -> None:
    """Background task: POST to /admin/api-test/test-flow + capture full result.

    All state goes to Redis so any worker can poll/stream this run. `flow_name`
    selects which suite to run (§pass73.3.19) — see _SUPPORTED_FLOWS.
    """
    started = time.time()
    flow_label = _SUPPORTED_FLOWS.get(flow_name, flow_name)
    base_meta = {
        "run_id":       run_id,
        "status":       "running",
        "started_at":   started,
        "finished_at":  None,
        "developer_id": dev_id,
        "flow_name":    flow_name,
        "flow_label":   flow_label,
        "summary":      None,
        "error":        None,
    }
    await _save_run_meta(run_id, base_meta)
    await _append_log(run_id, f"Spawning sweep '{flow_label}' ({flow_name}) against /admin/api-test/test-flow")
    await _append_log(run_id, f"Target: {API_TEST_TARGET_URL} (sandbox={_is_sandbox_target()})")

    # ── Live progress poller ───────────────────────────────────────────────
    # The test-flow endpoint is blocking ~22min. To keep the UI live we poll
    # /api-test/flow-values every 5s and emit a heartbeat log line. The
    # heartbeat tracks tool_count / passed / failed / skipped as they tick
    # upward, plus elapsed time. Cancelled when the sweep returns.
    async def _heartbeat() -> None:
        # Emit a status line every 6 seconds. Reads two sources:
        # (a) Redis key `mcp_tester:progress` — the lifecycle writes
        #     {last_tool, completed, total} on every tool start, so we can
        #     surface "now testing tool_name (N/T)" in real time.
        # (b) /api-test/flow-values fallback — for the FINAL summary stats
        #     that only get set at the end of the sweep.
        # If both are empty we still emit an "in flight" ping so the log
        # never freezes.
        last_logged_tool = None
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0)) as hb_client:
            while True:
                try:
                    await asyncio.sleep(6.0)
                    elapsed = int(time.time() - started)
                    mins, secs = divmod(elapsed, 60)

                    # ── Source A: Redis live-progress ────────────────────
                    last_tool = ""
                    phase = ""
                    done = 0
                    total = 0
                    try:
                        r = await get_redis()
                        if r is not None:
                            raw = await r.hgetall("mcp_tester:progress")
                            if raw:
                                decoded = {
                                    (k.decode() if isinstance(k, bytes) else k):
                                    (v.decode() if isinstance(v, bytes) else v)
                                    for k, v in raw.items()
                                }
                                last_tool = decoded.get("last_tool", "")
                                phase     = decoded.get("phase", "")
                                try:
                                    done  = int(decoded.get("completed", 0))
                                    total = int(decoded.get("total", 0))
                                except (TypeError, ValueError):
                                    pass
                    except Exception:
                        pass

                    # ── Source B: flow-values fallback ───────────────────
                    try:
                        fv_resp = await hb_client.get(
                            f"{API_TEST_TARGET_URL}/api/v1/admin/api-test/flow-values",
                            headers={"Authorization": f"Bearer {dev_jwt}"},
                        )
                        fv = (fv_resp.json() or {}).get("values", {}) if fv_resp.status_code == 200 else {}
                    except Exception:
                        fv = {}

                    passed     = fv.get("passed", 0)
                    failed     = fv.get("failed", 0)
                    skipped    = fv.get("skipped", 0)
                    fv_total   = fv.get("tool_count", 0)

                    # Build the heartbeat line, preferring live-progress info.
                    # We log every iteration so the user sees motion; the
                    # phase + tool change at their natural cadence so the
                    # stream stays informative without spamming the same line.
                    if last_tool:
                        prog = f"{done}/{total}" if total else f"#{done}"
                        prefix = phase if phase else "Sweep"
                        await _append_log(
                            run_id,
                            f"{prefix} [{prog}] · {last_tool} · elapsed {mins}m{secs:02d}s",
                        )
                        last_logged_tool = last_tool
                    elif phase:
                        await _append_log(
                            run_id,
                            f"{phase} · elapsed {mins}m{secs:02d}s",
                        )
                    elif fv_total:
                        await _append_log(
                            run_id,
                            f"Progress: {passed}/{fv_total} passed · {skipped} skipped · "
                            f"{failed} failed · elapsed {mins}m{secs:02d}s",
                        )
                    else:
                        await _append_log(
                            run_id,
                            f"Sweep in flight · elapsed {mins}m{secs:02d}s",
                        )
                except asyncio.CancelledError:
                    return
                except Exception as hb_e:
                    # Heartbeat must NEVER kill the sweep — swallow and continue.
                    try:
                        await _append_log(run_id, f"[heartbeat] swallowed {hb_e!r}")
                    except Exception:
                        pass

    hb_task = asyncio.create_task(_heartbeat())

    try:
        # Long timeout — full sweep is ~22 min. Add headroom.
        async with httpx.AsyncClient(timeout=httpx.Timeout(float(os.getenv("MCP_TESTER_SWEEP_TIMEOUT_S", "5400")), connect=10.0)) as client:
            await _append_log(run_id, f"POST /api/v1/admin/api-test/test-flow (flow={flow_name}) → starting sweep")
            r = await client.post(
                f"{API_TEST_TARGET_URL}/api/v1/admin/api-test/test-flow",
                json={"flow_name": flow_name},
                headers={"Authorization": f"Bearer {dev_jwt}",
                         "Content-Type": "application/json",
                         # §V0135: the forwarded bearer is invalid on registry-test
                         # (separate JWT secret); this shared key is what actually
                         # authenticates the proxied sweep cross-registry. §PROXYKEY:
                         # omitted when this console holds no usable key.
                         **_proxy_headers()},
            )
            # Stop the heartbeat — sweep complete.
            hb_task.cancel()
            try:
                await hb_task
            except (asyncio.CancelledError, Exception):
                pass
            await _append_log(run_id, f"Sweep returned HTTP {r.status_code} after "
                                          f"{int(time.time() - started)}s")
            if r.status_code != 200:
                base_meta["status"]      = "failed"
                base_meta["finished_at"] = time.time()
                base_meta["error"]       = f"HTTP {r.status_code}: {r.text[:300]}"
                await _save_run_meta(run_id, base_meta)
                return

            data = r.json()
            fv = data.get("flow_values", {}) or {}
            results = data.get("results", []) or []

            # §pass73.3.19 — normalize counts across the 3 flow shapes:
            #  - mcp-lifecycle / cloud-op: flat {tool_count,passed,skipped,failed,pass_pct}
            #  - federation suite: nested flow_values.summary {total,passed,failed,
            #    skipped,errored,pass_pct} — `errored` (test exceptions) counts as failed.
            _fed = fv.get("summary") if isinstance(fv.get("summary"), dict) else None
            if _fed:
                _counts = {
                    "tool_count": _fed.get("total", 0),
                    "passed":     _fed.get("passed", 0),
                    "failed":     (_fed.get("failed", 0) or 0) + (_fed.get("errored", 0) or 0),
                    "skipped":    _fed.get("skipped", 0),
                    # The federation suite has no deny-list concept — it never
                    # refuses a test on operating-rule grounds. 0 is the truth
                    # here, not a missing value.
                    "policy_denied": 0,
                    "pass_pct":   _fed.get("pass_pct", 0),
                    "wall_s":     round((_fed.get("total_wall_ms", 0) or 0) / 1000.0, 1) or fv.get("wall_s", 0),
                }
            else:
                _counts = {
                    "tool_count": fv.get("tool_count", 0),
                    "passed":     fv.get("passed", 0),
                    "failed":     fv.get("failed", 0),
                    "skipped":    fv.get("skipped", 0),
                    # §MCPTEST-MCP10: the flow splits refused-by-standing-order
                    # from could-not-test (§MCPTEST-MCP9) and emits both. This
                    # mapper copied a fixed key list and dropped policy_denied,
                    # so the split existed in the runner and was invisible in
                    # every consumer — the field-mapper silent-drop class again
                    # (§EXCISION-10 / §MCPTEST-FE2).
                    "policy_denied": fv.get("policy_denied", 0),
                    "pass_pct":   fv.get("pass_pct", 0),
                    "wall_s":     fv.get("wall_s", 0),
                }

            # Tool/test label: mcp-lifecycle rows carry responseData.tool; federation
            # rows carry the test name in `name` (no tool key). Fall back to `name`.
            def _row_label(rr: Dict[str, Any]) -> str:
                return (rr.get("responseData") or {}).get("tool") or rr.get("name", "") or ""

            bug_finds = [
                {"tool": _row_label(rr),
                 "error": (rr.get("error") or "")}
                for rr in results
                if "BUG-FIND" in (rr.get("error") or "")
            ]
            # §NIGHTLYTRUTH (2026-09-14): a red row carries its captured state, and a row red BY DESIGN
            # (the test declares `expected_red=<finding>`) is listed apart from the new reds.
            hard_fails, expected_reds = _split_red_rows(results, _row_label)
            # §MCPTEST-MCP2 2026-08-08: this used to filter on `expected_failure`
            # alone. The mcp-lifecycle flow marks a skip with `skip_reason` on the
            # outcome and does NOT set expected_failure, so the predicate matched
            # nothing and the endpoint shipped `skipped: []` while the summary
            # reported 48 — a skip COUNT with no list, which makes the single
            # biggest remaining block of non-passing tools unactionable.
            # (`pass_pct = passed/tool_count` and skips count against it, so those
            # 48 are exactly what stands between ~95.8% and 98%.)
            # Catch a row that carries EITHER signal.
            _skip_rows = [
                {"tool": _row_label(rr),
                 "reason": ((rr.get("responseData") or {}).get("skip_reason") or "")}
                for rr in results
                if rr.get("expected_failure")
                or rr.get("skipped")
                or ((rr.get("responseData") or {}).get("skip_reason"))
            ]
            # §MCPTEST-MCP10 — split the LIST the same way §MCPTEST-MCP9 split the
            # COUNT. A tool refused by a standing operating rule (provisioning,
            # teardown, sim start/stop, canary fleet pause) is not a coverage
            # hole, and listing it under "not executed" reads as one.
            skipped = [s for s in _skip_rows
                       if _POLICY_DENIED_MARK not in (s["reason"] or "")]
            policy_denied_rows = [s for s in _skip_rows
                                  if _POLICY_DENIED_MARK in (s["reason"] or "")]

            summary = {
                "flow_name":          flow_name,
                "flow_label":         flow_label,
                "tool_count":         _counts["tool_count"],
                "explicit_contracts": fv.get("explicit_contracts", 0),
                "default_contracts":  fv.get("default_contracts", 0),
                "passed":             _counts["passed"],
                "skipped":            _counts["skipped"],
                "policy_denied":      _counts["policy_denied"],
                "failed":             _counts["failed"],
                "tier_drift":         fv.get("tier_drift", 0),
                "contract_gap":       fv.get("contract_gap", 0),
                "pass_pct":           _counts["pass_pct"],
                "wall_s":             _counts["wall_s"],
                "bug_finds":          len(bug_finds),
                "hard_failures":      len(hard_fails),
                "expected_red":       len(expected_reds),
                "target":             API_TEST_TARGET_URL,
                "is_sandbox":         _is_sandbox_target(),
                # §MCPTEST30 (V0541): which drift detectors ran; a count below is a reading only where its own is true
                "detectors":              _detectors_measured(fv),
                "cross_frame_compared":   fv.get("cross_frame_compared"),
                # Phase F additions
                "auth_matrix_total":      fv.get("auth_matrix_total", 0),
                "auth_matrix_violations": fv.get("auth_matrix_violations", 0),
                # §MCPTEST-MCP10 — probes that could not be measured, kept
                # out of the violation count (an unreachable probe is not an
                # accept). Carried here because the last field the runner
                # emitted and this mapper dropped was policy_denied.
                "auth_matrix_inconclusive": fv.get("auth_matrix_inconclusive", 0),
                "auth_matrix_failed_tools": fv.get("auth_matrix_failed_tools", []),
                "cross_frame_drift":      fv.get("cross_frame_drift", 0),
                "cross_frame_drift_details": fv.get("cross_frame_drift_details", []),
                "consistency_violations": fv.get("consistency_violations", 0),
                "latency_regressions":    fv.get("latency_regressions", 0),
                "wrapper_drift":          fv.get("wrapper_drift", 0),
                "wrapper_drift_details":  fv.get("wrapper_drift_details", []),
                # §MCPTEST30 (V0547): the request survey's own account (a target before V0547 sends none of these)
                "wrapper_drift_known":    fv.get("wrapper_drift_known", []),
                "wrapper_peer_route":     fv.get("wrapper_peer_route", []),
                "wrapper_drift_surveyed": fv.get("wrapper_drift_surveyed"),
                "wrapper_drift_reason":   fv.get("wrapper_drift_reason"),
                "wrapper_drift_source":   fv.get("wrapper_drift_source"),
                # §MCPTEST30 (V0550): what the target switched off and the rows held to those refusals (mcp_switches.py;
                # a target before V0550 sends none of these, and the page then shows nothing)
                "target_switches":        fv.get("target_switches"),
                "target_switches_read":   fv.get("target_switches_read"),
                "switched_off_rows":      fv.get("switched_off_rows", []),
            }

            # Build slim_results FIRST so latency baseline can mutate
            # individual rows with regression flags before persistence.
            slim_results = [
                {
                    # §pass73.3.19: use _row_label so federation-suite rows (which
                    # carry the test name in `name`, not responseData.tool) render
                    # in the FE "All tools" table instead of showing blank.
                    "tool":     _row_label(rr),
                    "tier":     (rr.get("authRequired") or ""),
                    "healthy":  bool(rr.get("healthy")),
                    "skipped":  bool(rr.get("expected_failure")),
                    "status":   rr.get("statusCode"),
                    "elapsed":  (rr.get("responseData") or {}).get("elapsed_ms", 0),
                    "error":    (rr.get("error") or "")[:300] if rr.get("error") else None,
                    "skip_reason": ((rr.get("responseData") or {}).get("skip_reason") or "") or None,
                    # pass73.3.19 Pass 6 (2026-05-28) — actual call response
                    # so the FE can show real payload on click. Truncate to
                    # ~2KB to keep Redis payload small. Federation rows have no
                    # result_excerpt → fall back to the full outcome dict so the
                    # detail panel still shows the captured state (drift, etc.).
                    "response_excerpt": _truncate_response_excerpt(
                        (rr.get("responseData") or {}).get("result_excerpt")
                        or rr.get("responseData")
                    ),
                    "has_explicit_contract": bool(
                        (rr.get("responseData") or {}).get("has_explicit_contract")
                    ),
                    # §MCPTEST30 (V0550): the switch this row was held to, or None
                    "switched_off": (rr.get("responseData") or {}).get("switched_off"),
                    # §MCPTEST30 (V0643): a refusal-only row's by-design reason, from the target's flow (or None)
                    "declared_unmeasured": (rr.get("responseData") or {}).get("declared_unmeasured"),
                }
                for rr in results
            ]

            # §MCPTEST30 (V0636): a pass that was only a refusal counts as not measured (the MCP-family flows; the
            # federation suite has no tool rows), before pass_depth reads what passed
            if not _fed:
                _ro = _apply_refusal_only(slim_results, summary, skipped)
                if _ro:
                    await _append_log(run_id, f"{_ro} tool rows passed on a refusal alone: counted as not measured "
                                              f"(the target counted {summary['target_counts']['pass_pct']}%, "
                                              f"this run reads {summary['pass_pct']}%)")
            summary["pass_depth"] = _pass_depth(slim_results)   # §MCPTEST30 (V0549)

            # ── pass73.3.19 fix-#6 (2026-05-28) — per-row 12-axis dict ──
            # The backend already computes 4 of the 6 "pending" axes as
            # SUMMARY aggregates (auth-matrix violators, cross-frame drift,
            # wrapper drift, latency regressions). Reverse-index those into
            # the per-row payload so the FE can show real pass/fail/skip
            # per axis instead of "backend computes but doesn't surface".
            #
            # The remaining 3 axes (side_effect, event_emission, audit_log)
            # are computed during contract assertion (flow_mcp_lifecycle
            # _assert_full_contract). For tools that emit events / mutate
            # state, the assertion ran but its per-axis outcome is folded
            # into `healthy` — surfacing those individually requires
            # extending ContractOutcome (deferred to next batch). For now
            # we infer from healthy + tool-name mutation prefix.
            _MUTATION_PREFIXES = (
                "create", "update", "delete", "transfer", "stake", "unstake",
                "submit", "revoke", "approve", "reject", "set", "enable",
                "disable", "suspend", "reinstate", "patch", "equip",
                "unequip", "customize", "rotate", "claim", "settle",
                "release", "authorize", "burn", "mint",
            )
            wrapper_drift_tools = {
                d.get("tool", "") for d in (fv.get("wrapper_drift_details") or [])
                if d.get("tool")
            }
            cross_frame_drift_tools = {
                d.get("tool", "") for d in (fv.get("cross_frame_drift_details") or [])
                if d.get("tool")
            }
            _detectors = _detectors_measured(fv)
            # auth_matrix_failed_tools entries are "tool(wrong-tier→status)"
            auth_matrix_violator_tools = set()
            for entry in (fv.get("auth_matrix_failed_tools") or []):
                if isinstance(entry, str) and "(" in entry:
                    auth_matrix_violator_tools.add(entry.split("(", 1)[0])
                elif isinstance(entry, str):
                    auth_matrix_violator_tools.add(entry)

            # ── Real ES emission poll (2026-06-02) — replaces the inference
            # heuristic below. One query per emit-type since the sweep started;
            # sweep DIDs harvested from every tool response so a sweep-emitted
            # event (e.g. TokensTransferred from the sentinel) can be told apart
            # from canary noise. Best-effort — failures degrade to 'unknown'.
            _since_iso = datetime.fromtimestamp(started, timezone.utc).isoformat()
            try:
                _sweep_dids = set(_DID_RE.findall(json.dumps(results, default=str)[:2_000_000]))
            except Exception:
                _sweep_dids = set()
            # §CLOUDOPMCP2 2026-09-05 — work out what this run is actually WAITING ON
            # before asking, so the settle window is spent re-polling those types and
            # not the 90-odd nothing in this run should have emitted. Same predicate
            # the per-row verdict uses below (2xx + a known emitter + not skipped) —
            # if these two ever disagree, a row waits on a type the poller never
            # re-asked for and reads MISS at the first snapshot.
            _expect_types: List[str] = []
            for _r in slim_results:
                _op = (_r.get("tool", "") or "").replace("theprotocol_", "")
                _ts = _EMIT_MAP.get(_op)
                # a conditional emitter is never "expected": waiting 25s for an event
                # the call was never obliged to produce spends the window on nothing
                if not _ts or _r.get("skipped") or _op in _EMIT_CONDITIONAL or _did_no_work(_r):
                    continue
                _stc = _r.get("status")
                if isinstance(_stc, int) and 200 <= int(_stc) < 300:
                    _expect_types.extend(_ts)
            _expect_types = sorted(set(_expect_types))

            _emit_diag: Dict[str, str] = {}
            _emit_seen = await _collect_emissions(
                _since_iso, _sweep_dids, expect_types=_expect_types, diag=_emit_diag, flow_name=flow_name)
            if not _emit_seen:
                # §MCPTEST30 (V0542): this console read nothing from the store; the target may reach it
                _relayed = await _emissions_via_target(_since_iso, _sweep_dids, _expect_types, flow_name)
                if _relayed:
                    _cause_here = _emit_diag.get("__cause__") or _first_emit_reason(_emit_diag) or "unreadable"
                    _emit_seen, _emit_diag = _relayed
                    _emit_diag["__via_target__"] = (
                        f"read THROUGH {API_TEST_TARGET_URL} (store {_emit_diag.get('__url__', '?')}): this console "
                        f"could not ({_cause_here[:120]})")
                    await _append_log(run_id, f"Emission ES-poll {_emit_diag['__via_target__']}")
            _still = [t for t in _expect_types if not _emit_satisfied(t, _emit_seen.get(t))]
            await _append_log(run_id, f"Emission ES-poll: {len(_emit_seen)} event-types checked, "
                                      f"{len(_sweep_dids)} sweep DIDs harvested, "
                                      f"{len(_expect_types)} expected by 2xx calls, "
                                      f"{len(_still)} still absent after a "
                                      f"{_EMIT_SETTLE_S:.0f}s settle window"
                                      + (f": {','.join(_still[:6])}" if _still else ""))
            if _emit_diag.get("__cause__") or len(_emit_seen) == 0:
                # Name the store and the cause ONCE, in the run log, rather than
                # leaving the reader to infer it from N identical row details.
                await _append_log(
                    run_id,
                    f"Emission ES-poll UNREADABLE — store={_emit_diag.get('__url__', '?')} · "
                    f"cause={_emit_diag.get('__cause__') or _first_emit_reason(_emit_diag) or 'unknown'}")

            for r in slim_results:
                tool_full = r.get("tool", "")
                tool_op = tool_full.replace("theprotocol_", "")
                is_mutation = any(tool_op.startswith(p) for p in _MUTATION_PREFIXES)
                healthy = bool(r.get("healthy"))
                row_skipped = bool(r.get("skipped"))
                # Axis status: 'pass' | 'fail' | 'skip' | 'unknown' | 'na'
                axes: Dict[str, Dict[str, str]] = {}

                # — Wrong-tier rejection · cross-frame parity · wrapper/route drift (§MCPTEST30, V0541: measured or n/a) —
                axes.update(_detector_axes(tool_full, fv, _detectors, auth_matrix_violator_tools,
                                           cross_frame_drift_tools, wrapper_drift_tools))

                # — Read-after-write side-effect (inferred from healthy + mutation prefix) —
                if row_skipped:
                    axes["side_effect"] = {"state": "skip", "detail": "tool was skipped"}
                elif not is_mutation:
                    axes["side_effect"] = {"state": "na", "detail": "read-only tool — no side-effect to verify"}
                elif healthy:
                    axes["side_effect"] = {
                        "state":  "pass",
                        "detail": "inferred from contract pass — side_effect_assert succeeded if contract had one",
                    }
                else:
                    axes["side_effect"] = {
                        "state":  "fail",
                        "detail": "mutation tool unhealthy — side-effect not verifiable",
                    }

                # — Audit log row (inferred from healthy + mutation prefix) —
                if row_skipped:
                    axes["audit_log_row"] = {"state": "skip", "detail": "tool was skipped"}
                elif not is_mutation:
                    axes["audit_log_row"] = {"state": "na", "detail": "read-only tool — no audit row expected"}
                elif healthy:
                    axes["audit_log_row"] = {
                        "state":  "pass",
                        "detail": "inferred from contract pass — audit-row check succeeded if expected",
                    }
                else:
                    axes["audit_log_row"] = {
                        "state":  "fail",
                        "detail": "mutation tool unhealthy — audit-row not verifiable",
                    }

                # — EventStore emission (2026-06-02: REAL ES poll, not inference) —
                _emit_types = _EMIT_MAP.get(tool_op)
                if row_skipped:
                    axes["event_emission"] = {"state": "skip", "detail": "tool was skipped"}
                elif not _emit_types:
                    axes["event_emission"] = {"state": "na", "detail": "not a known EventStore emitter"}
                elif not (isinstance(r.get("status"), int) and 200 <= int(r.get("status")) < 300):
                    # NB: `healthy` is True even on coverage-fan 4xx probes, so
                    # gate on real 2xx — a non-2xx call emits nothing to verify.
                    axes["event_emission"] = {"state": "na", "detail": f"call not 2xx (status={r.get('status')}) — no emission expected"}
                elif _did_no_work(r):
                    axes["event_emission"] = {"state": "na", "detail": _did_no_work(r)}
                else:
                    _miss: List[str] = []
                    _hit: List[str] = []
                    _unk: List[str] = []
                    for _et in _emit_types:
                        _seen = _emit_seen.get(_et)
                        if _seen is None:
                            _unk.append(_et)
                            continue
                        # ONE rule, shared with the settle-poller (_emit_satisfied)
                        (_hit if _emit_satisfied(_et, _seen) else _miss).append(_et)
                    if _miss and tool_op in _EMIT_CONDITIONAL:
                        axes["event_emission"] = {
                            "state":  "na",
                            "detail": f"conditional emitter — {','.join(_miss)} fires per unit of "
                                      f"work done, not per 2xx, and this call did none "
                                      f"(nothing to assert, not a miss)",
                        }
                    elif _miss:
                        axes["event_emission"] = {
                            "state":  "fail",
                            "detail": f"REAL MISS: {','.join(_miss)} still absent from the "
                                      f"EventStore {_EMIT_SETTLE_S:.0f}s after the sweep "
                                      f"(call was 2xx, the ES was re-asked until the settle "
                                      f"window closed — silent NO-OP / routing drop, not latency)",
                        }
                    elif _unk and not _hit:
                        # §EMITDIAG: an 'unknown' that cannot say WHY sends the reader
                        # to the rail instead of to the instrument. Name the store and
                        # the reason the poll gave.
                        _why = _emit_diag.get("__cause__") or "; ".join(
                            dict.fromkeys(_emit_diag.get(_e, "") for _e in _unk if _emit_diag.get(_e))
                        )
                        axes["event_emission"] = {
                            "state":  "unknown",
                            "detail": (f"ES query unavailable for {','.join(_unk)} "
                                       f"(store={_emit_diag.get('__url__', '?')}"
                                       + (f" · {_why}" if _why else "") + ")"),
                        }
                    else:
                        _didm = " (sweep-DID matched)" if any(e in _EMIT_CANARY_NOISY for e in _hit) else ""
                        axes["event_emission"] = {
                            "state":  "pass",
                            "detail": f"ES-verified: {','.join(_hit)} emitted since run-start{_didm}",
                        }

                r["axes"] = axes

            # ── Phase F.2 — Latency baseline (Gap-2) ─────────────────
            # Run BEFORE Prom emit so the gauge is set correctly. Mutates
            # `slim_results` in-place to tag regressed rows.
            _frame = _frame_label(API_TEST_TARGET_URL)
            try:
                _lat: Dict[str, Any] = {}
                latency_regressions = await _record_latency_baseline(
                    _suite_key(flow_name, API_TEST_TARGET_URL), slim_results, out=_lat)
                summary["latency_regressions"] = latency_regressions
                # §MCPTEST30 (V0544): how much slower than its baseline the whole run ran (the box, not a tool)
                summary["latency_run_factor"] = _lat.get("run_factor")
                summary["latency_baselined_tools"] = _lat.get("baselined_tools")
                # pass73.3.19 fix-#1 (2026-05-28): surface WHICH tools regressed
                # so the FE can render a list, not just a count. Slim shape so
                # the summary stays under Redis TTL+payload budget.
                summary["latency_regressions_details"] = [
                    {
                        "tool":     r.get("tool", ""),
                        "elapsed":  int(r.get("elapsed", 0) or 0),
                        "baseline_ms": int(r.get("latency_baseline_ms", 0) or 0),
                        "factor":   round(
                            (int(r.get("elapsed", 0) or 0) / int(r.get("latency_baseline_ms", 1) or 1)),
                            2,
                        ),
                    }
                    for r in slim_results
                    if r.get("latency_regression")
                ]
            except Exception as _e:
                logger.debug(f"[mcp-tester] latency baseline failed: {_e!r}")

            # ── emission_integrity HONESTY flag (2026-06-26) ─────────
            # Sidecar verdict from real ES polls + an mTLS handshake. NEVER
            # flips a row red and NEVER changes the run status — it surfaces a
            # DEGRADED/WARN signal the strict pass-rate is blind to (dead
            # cross-frame settlement, silent emission NO-OPs, expired SPIRE
            # bundles). Fully defensive: a failure degrades to a 'warn' verdict,
            # it can never break the sweep.
            try:
                summary["emission_integrity"] = await _compute_emission_integrity(
                    run_start=started,
                    flow_values=fv,
                    summary=summary,
                    slim_results=slim_results,
                    sweep_dids=_sweep_dids,
                    emit_seen=_emit_seen,
                    emit_diag=_emit_diag,
                )
                _ei = summary["emission_integrity"]
                await _append_log(
                    run_id,
                    f"Emission integrity: {_ei.get('status', '?').upper()} — {_ei.get('summary', '')}",
                )
            except Exception as _e:
                logger.debug(f"[mcp-tester] emission_integrity failed: {_e!r}")
                summary["emission_integrity"] = {
                    "status": "warn",
                    "checks": {},
                    "summary": f"integrity probe failed: {_e!r}",
                }

            await _append_log(run_id,
                f"Done. passed={summary['passed']} skipped={summary['skipped']} "
                f"failed={summary['failed']} tier_drift={summary['tier_drift']} "
                f"contract_gap={summary['contract_gap']} "
                f"auth_matrix_violations={summary.get('auth_matrix_violations', 0)} "
                f"cross_frame_drift={summary.get('cross_frame_drift', 0)} "
                f"latency_regressions={summary.get('latency_regressions', 0)} "
                f"wrapper_drift={summary.get('wrapper_drift', 0)} "
                f"bug_finds={summary['bug_finds']} wall={summary['wall_s']}s")

            # Emit strict-mode Prometheus gauges (2026-05-26 doctrine).
            try:
                _emit_mcp_metrics(
                    target=API_TEST_TARGET_URL,
                    frame=_frame,
                    flow=flow_name,
                    summary={
                        "total":        fv.get("tool_count", 0),
                        "healthy":      fv.get("passed", 0),
                        "tier_drift":   fv.get("tier_drift", 0),
                        "contract_gap": fv.get("contract_gap", 0),
                        # Phase F additions
                        "auth_matrix_violations": summary.get("auth_matrix_violations", 0),
                        "cross_frame_drift":      summary.get("cross_frame_drift", 0),
                        "latency_regressions":    summary.get("latency_regressions", 0),
                        "wrapper_drift":          summary.get("wrapper_drift", 0),
                        # emission_integrity HONESTY flag → gauge (ok/warn/degraded → 0/1/2)
                        "emission_integrity_status": (summary.get("emission_integrity") or {}).get("status", "ok"),
                    },
                )
                if _MCP_PROM_AVAILABLE and MCP_TESTER_RUNS is not None:
                    MCP_TESTER_RUNS.labels(target=API_TEST_TARGET_URL, frame=_frame, flow=flow_name, outcome="completed").inc()
            except Exception as _e:
                logger.debug(f"[mcp-tester] prom emit failed: {_e!r}")

            await _save_list(run_id, "bugfinds", bug_finds)
            await _save_list(run_id, "hardfail", hard_fails)
            await _save_list(run_id, "expectedred", expected_reds)
            await _save_list(run_id, "skipped",  skipped)
            await _save_list(run_id, "polideny", policy_denied_rows)
            await _save_list(run_id, "results",  slim_results)

            # §EVTYPES 2026-09-05 — VACUOUS-RUN FLOOR.
            # A sweep that measured NOTHING must not report success. The native
            # /run path proxies to API_TEST_TARGET_URL; on both fresh sandbox
            # frames that still names `registry-test`, a container Exited three
            # weeks ago whose DNS entry lingers — so the proxy fails, every list
            # comes back empty, and the run reported
            #   status=completed passed=0 failed=0 skipped=0 pass_pct=0
            # which reads like a clean run and is actually zero coverage. Same
            # shape as `all()` over an empty list: the absence of failures is not
            # evidence of success. Fail loudly, and name the target, because the
            # target is what is wrong when this fires.
            _flow_error = data.get("error") if isinstance(data, dict) else None
            _vac = vacuity_verdict(summary, _flow_error, API_TEST_TARGET_URL)
            if _vac:
                await _append_log(run_id, _vac)
                logger.error("[mcp-tester] %s", _vac)
                base_meta["status"]      = "failed"
                base_meta["finished_at"] = time.time()
                base_meta["summary"]     = summary
                base_meta["error"]       = _vac
                await _save_run_meta(run_id, base_meta)
                return

            base_meta["status"]      = "completed"
            base_meta["finished_at"] = time.time()
            base_meta["summary"]     = summary
            # carry the FLOW's own sentence rather than overwriting it with None: a run that completed while the
            # flow had something to say is exactly the case that used to leave the reason only in another
            # container's log (2026-09-23).
            base_meta["error"]       = (str(_flow_error)[:1000] if _flow_error else None)
            await _save_run_meta(run_id, base_meta)

    except Exception as e:
        # Cancel heartbeat on failure path too — otherwise it logs forever.
        try:
            hb_task.cancel()
            try:
                await hb_task
            except (asyncio.CancelledError, Exception):
                pass
        except Exception:
            pass
        logger.exception("MCP tester run %s failed: %s", run_id, e)
        await _append_log(run_id, f"EXCEPTION: {e!r}")
        base_meta["status"]      = "failed"
        base_meta["finished_at"] = time.time()
        base_meta["error"]       = repr(e)
        await _save_run_meta(run_id, base_meta)


# ---------------------------------------------------------------------------
# Auth gate — admin only
# ---------------------------------------------------------------------------

def _require_admin(dev: models.Developer) -> models.Developer:
    if not dev or not security.admin_credential(dev):   # §POCKETPAIR: a scoped key is not admin
        raise HTTPException(status_code=403, detail="MCP Tester requires admin")
    return dev


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

def _container_boot_epoch() -> Optional[float]:
    """Epoch seconds at which THIS container's PID 1 started, or None.

    /proc/1/stat field 22 is PID 1's start time in clock ticks since the HOST
    booted, and /proc/uptime is the host's uptime — both readable inside the
    container, so the pair yields PID 1's wall-clock start. All gunicorn workers
    share PID 1, so this is the whole container's boot, not one worker's: a
    worker respawned by max-requests must NOT make a live sibling's sweep look
    dead. Returns None on any surprise, which keeps the old behaviour.
    """
    try:
        with open("/proc/uptime") as f:
            host_up = float(f.read().split()[0])
        with open("/proc/1/stat") as f:
            fields = f.read().rsplit(")", 1)[1].split()
        ticks = float(fields[19])                       # field 22, 0-based after comm
        hz = os.sysconf("SC_CLK_TCK") or 100
        return (time.time() - host_up) + (ticks / hz)
    except Exception:                                    # noqa: BLE001
        return None


@router.post("/run", summary="Kick off an MCP regression sweep (sandbox-only)")
async def run_sweep(
    request: Request,
    current_developer: models.Developer = Security(security.get_current_developer),
) -> Dict[str, Any]:
    """Spawn a background sweep that targets the sandbox.

    Returns `{run_id, started_at, target, is_sandbox}` immediately. Use
    /runs/{run_id} to poll status, or /runs/{run_id}/stream for SSE logs.
    """
    _require_admin(current_developer)

    # Sandbox-only enforcement
    if not _is_sandbox_target():
        raise HTTPException(
            status_code=400,
            detail=(
                "MCP Tester refuses to run because API_TEST_TARGET_URL "
                f"({API_TEST_TARGET_URL!r}) is not a sandbox endpoint. "
                "Expected 'registry-test' or 'localhost:8002' in target URL."
            ),
        )

    # §TESTBED P1: a production frame whose tester would target ITSELF (the kit default) says so here, in words, rather
    # than proxying to its own registry and relaying that registry's refusal
    from ..core.frame_posture import targets_itself, test_execution_refusal
    _refusal = test_execution_refusal()
    if _refusal and targets_itself(API_TEST_TARGET_URL):
        raise HTTPException(status_code=400, detail=_refusal)

    # Extract the caller's bearer for the proxied call
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required")
    dev_jwt = auth_header.split(" ", 1)[1]

    # §pass73.3.19: optional flow_name selects which suite to run (MCP tester /
    # federation suite / cloud-op sweeps). Defaults to the strict MCP tester.
    flow_name = _DEFAULT_FLOW_NAME
    try:
        body = await request.json()
        if isinstance(body, dict) and body.get("flow_name"):
            flow_name = str(body["flow_name"])
    except Exception:
        pass
    if flow_name not in _SUPPORTED_FLOWS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported flow_name {flow_name!r}. Expected one of: {list(_SUPPORTED_FLOWS)}",
        )

    # Redis required for cross-worker state
    await _redis_or_die()

    now = time.time()

    # §single-flight guard (2026-05-31): refuse to launch a duplicate sweep of the
    # same flow while one is already in flight. The MCP bridge / FE client times out
    # ~30s while /run is still doing setup and RETRIES → a 2nd concurrent sweep of the
    # same flow. Two concurrent sweeps contend on the sandbox registry and inflate
    # per-tool latency 2-2.5x until BOTH exceed the ReadTimeout ceiling and fail.
    # Dedupe: if a queued/running sweep of this flow exists within the timeout window,
    # return it instead of starting another. (Stale/zombie runs past the window never block.)
    _sweep_ttl = float(os.getenv("MCP_TESTER_SWEEP_TIMEOUT_S", "5400"))
    for _rid in await _list_recent_run_ids(limit=20):
        _m = await _load_run_meta(_rid)
        if not _m or _m.get("flow_name") != flow_name:
            continue
        if _m.get("status") not in ("queued", "running"):
            continue
        _started = _m.get("started_at") or 0
        if (now - _started) > _sweep_ttl:
            continue  # stale/zombie past the timeout window — never block on it
        # §EVTYPES 2026-09-05: a run that predates THIS CONTAINER's PID 1 cannot
        # still be running — the process that owned it is gone. Without this, a
        # sweep killed by a recreate stays `running` in Redis and blocks the flow
        # for the full 90-minute TTL. Measured today: a sync-triggered restart
        # landed mid-suite, and the next launch got 409 against a run whose
        # process had died minutes earlier. Same predicate shape as the pgbouncer
        # `backend_start` recycle — compare against the OWNER's boot, not a clock.
        _boot = _container_boot_epoch()
        if _boot and _started < _boot:
            logger.warning(
                "[mcp-tester] single-flight: ignoring run %s (started %.0fs before "
                "this container's PID 1) — its process died with the restart",
                _rid, _boot - _started)
            continue
        logger.warning(
            "[mcp-tester] single-flight: flow=%s already in flight as %s (age %.0fs); "
            "returning existing run instead of launching a duplicate concurrent sweep",
            flow_name, _rid, now - _started,
        )
        return {
            "run_id":       _rid,
            "started_at":   _started,
            "target":       API_TEST_TARGET_URL,
            "is_sandbox":   _is_sandbox_target(),
            "flow_name":    flow_name,
            "deduplicated": True,
        }

    run_id = uuid.uuid4().hex[:16]
    await _save_run_meta(run_id, {
        "status":       "queued",
        "started_at":   now,
        "finished_at":  None,
        "developer_id": current_developer.id,
        "flow_name":    flow_name,
        "flow_label":   _SUPPORTED_FLOWS.get(flow_name, flow_name),
        "summary":      None,
        "error":        None,
    })
    asyncio.create_task(_execute_sweep_background(run_id, dev_jwt, current_developer.id, flow_name))

    logger.info("[mcp-tester] run %s started by dev=%s flow=%s", run_id, current_developer.id, flow_name)
    return {
        "run_id":     run_id,
        "started_at": now,
        "target":     API_TEST_TARGET_URL,
        "is_sandbox": _is_sandbox_target(),
        "flow_name":  flow_name,
        "flow_label": _SUPPORTED_FLOWS.get(flow_name, flow_name),
        "supported_flows": _SUPPORTED_FLOWS,
        "status":     "queued",
    }


@router.get("/peer-es-facts", summary="This node's view of ITS OWN peer EventStore")
async def peer_es_facts(request: Request) -> Dict[str, Any]:
    """§PEERVANTAGE 2026-09-07 — ANSWER THE QUESTION FROM A VANTAGE POINT THAT CAN SEE IT.

    `es_reachable` and `supply_transit` read the PEER (sandbox-B) EventStore. A
    console driving another frame cannot: measured, `eu-registry` shares no network
    with `sbx-beta-event-store`, and that store's host port is bound to 127.0.0.1 so
    there is no bridge route either — while the TARGET reaches it fine (200, events
    returned). The peer store was healthy the whole time; the console was the wrong
    place to ask. Same class as the mTLS check's own docstring: "verified OK from
    inside the sandbox registry itself".

    So the console asks the target for the facts it cannot see, and this returns them.

    ⚠ IT TAKES NO ADDRESS, DELIBERATELY. A relay that fetches a URL the caller
    supplies is an SSRF surface wearing a test-harness costume; this reads only the
    peer store THIS node is already configured with, so the worst a caller can do is
    learn counts from a store the node reads on its own anyway. Authenticated by the
    same shared key that already authenticates the proxied sweep — the console's
    forwarded bearer is invalid cross-registry (§V0135).
    """
    if not _proxy_key_ok(request.headers.get("X-Internal-Key")):
        raise HTTPException(status_code=401, detail="internal key required")
    if not _EMIT_ES_B_URL:
        return {"store": None, "reachable": False,
                "reason": "no peer EventStore configured on this node "
                          "(API_TEST_EVENT_STORE_B_URL unset)"}
    since_iso = request.query_params.get("since") or datetime.fromtimestamp(
        time.time() - 3600, timezone.utc).isoformat()
    out: Dict[str, Any] = {"store": _EMIT_ES_B_URL, "reachable": False, "reason": None}
    try:
        async with httpx.AsyncClient(verify=_es_verify(), timeout=8) as cli:
            out["settled_count"] = await _es_count_at(
                cli, _EMIT_ES_B_URL, "CrossFrameTransferSettled", since_iso)
            t, d = await _supply_transit_at(cli, _EMIT_ES_B_URL)
            out["transit_net"], out["delta"] = t, d
            out["reachable"] = out["settled_count"] is not None or t is not None
            if not out["reachable"]:
                out["reason"] = "peer store configured but returned nothing readable"
    except Exception as e:
        out["reason"] = f"{type(e).__name__}: {str(e)[:160]}"
    return out


@router.post("/emissions-via-target", summary="This node's emission poll of the store a flow's events land in")
async def emissions_via_target(request: Request) -> Dict[str, Any]:
    """§MCPTEST30 (V0542): the emission poll, answered from the vantage point that can see the store.

    A console driving this node may not reach the store a sweep's events land in (a cloud-op delta sweep's are its
    operator's parent's, sbx-beta's; EU's console cannot resolve that name). This node can, and answers the poll the
    console would have run: per event type, whether one landed since `since` and whether one names a sweep DID.

    ⚠ IT TAKES NO ADDRESS, as `peer-es-facts`: the store is the one this node maps the named flow to
    (`_emission_store_for`), so a caller learns booleans about a store this node reads on its own anyway. The same
    shared key authenticates it.
    """
    if not _proxy_key_ok(request.headers.get("X-Internal-Key")):
        raise HTTPException(status_code=401, detail="internal key required")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="a JSON body is required")
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="the body must be a JSON object")
    dids = [d for d in (body.get("dids") or []) if isinstance(d, str) and 0 < len(d) <= 300]
    if len(dids) > _RELAY_MAX_DIDS:
        raise HTTPException(status_code=422, detail=f"at most {_RELAY_MAX_DIDS} sweep DIDs")
    types = [t for t in (body.get("expect_types") or []) if isinstance(t, str) and 0 < len(t) <= 120]
    since_iso = str(body.get("since") or "") or datetime.fromtimestamp(time.time() - 3600, timezone.utc).isoformat()
    diag: Dict[str, str] = {}
    seen = await _collect_emissions(since_iso, set(dids), expect_types=types, diag=diag,
                                    flow_name=str(body.get("flow_name") or ""))
    return {"seen": seen, "diag": diag}


@router.get("/es-mtls-handshake", summary="This node's own EventStore mTLS gateway handshake")
async def es_mtls_handshake(request: Request) -> Dict[str, Any]:
    """§PEERVANTAGE for the emission-integrity mTLS check (2026-09-27). ⚠ IT TAKES NO ADDRESS: it probes only this node's
    own gateway (its https EVENT_STORE_URL), so it cannot be pointed at another host. Same shared key as peer-es-facts."""
    if not _proxy_key_ok(request.headers.get("X-Internal-Key")):
        raise HTTPException(status_code=401, detail="internal key required")
    return await _own_gateway_handshake()


@router.get("/flows", summary="List the suites runnable from the MCP-tester view")
async def list_flows(
    current_developer: models.Developer = Security(security.get_current_developer),
) -> Dict[str, Any]:
    """Return the flow_name → label map the FE uses to populate its run selector.

    §MCPTEST30 (V0541): and this console's own posture, its target and whether that target is a sandbox. The page read
    both from the newest run in History that had a summary; a console suite run recorded there (summary.target
    "Sandbox Alpha", no is_sandbox) made it print "Refusing to run ... not a sandbox endpoint" over a sweep that was
    running against sbx-alpha. A fact about this console is answered by this console."""
    _require_admin(current_developer)
    return {
        "flows": [{"flow_name": k, "label": v} for k, v in _SUPPORTED_FLOWS.items()],
        "default": _DEFAULT_FLOW_NAME,
        "target": API_TEST_TARGET_URL,
        "is_sandbox": _is_sandbox_target(),
    }


@router.post("/refire-single", summary="Re-fire a single MCP tool (instant)")
async def refire_single(
    request: Request,
    body: Dict[str, Any],
    current_developer: models.Developer = Security(security.get_current_developer),
) -> Dict[str, Any]:
    """Invoke one MCP tool and return a slim result row.

    Body: ``{"tool": "theprotocol_<name>", "args": {...optional}, "tier": "admin"}``

    Returns the same shape as a row in `results[]`:
    ``{tool, tier, healthy, skipped, status, elapsed, error, response_data}``

    Implementation:
    - For admin tools (or tier="admin"): POST to /mcp/admin/rpc with caller JWT
    - For public tools: POST to /mcp/rpc with caller JWT
    - Times the wall-clock; reports HTTP + structured outcome

    Sandbox-only enforcement matches `/run`. Same admin guard.
    """
    _require_admin(current_developer)
    if not _is_sandbox_target():
        raise HTTPException(
            status_code=400,
            detail=f"MCP Tester refuses non-sandbox target {API_TEST_TARGET_URL!r}",
        )

    tool = str(body.get("tool", "")).strip()
    if not tool:
        raise HTTPException(status_code=400, detail="missing 'tool' in body")
    if not tool.startswith("theprotocol_"):
        raise HTTPException(
            status_code=400,
            detail="tool name must start with 'theprotocol_' (canonical MCP namespace)",
        )

    args   = body.get("args") or {}
    tier   = (body.get("tier") or "").lower()

    # Auth header carry-through for the proxied invocation
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required")
    dev_jwt = auth_header.split(" ", 1)[1]

    # Pick public or admin RPC endpoint. If tier hint missing, default to
    # public first; if 404/method-not-found we retry admin.
    base = API_TEST_TARGET_URL.rstrip("/")
    public_url = f"{base}/mcp/rpc"
    admin_url  = f"{base}/mcp/admin/rpc"

    rpc_envelope = {
        "jsonrpc": "2.0",
        "id": uuid.uuid4().hex[:8],
        "method": "tools/call",
        "params": {
            "name": tool[len("theprotocol_"):],  # MCP expects raw tool name
            "arguments": args,
        },
    }

    started = time.time()
    response_data: Any = None
    healthy = False
    skipped = False
    error: Optional[str] = None
    status_code = 0
    used_url = ""

    async with httpx.AsyncClient(timeout=httpx.Timeout(45.0, connect=5.0)) as cli:
        urls = [admin_url, public_url] if tier == "admin" else [public_url, admin_url]
        for u in urls:
            used_url = u
            try:
                r = await cli.post(
                    u, json=rpc_envelope,
                    headers={"Authorization": f"Bearer {dev_jwt}"},
                )
                status_code = r.status_code
                if r.status_code == 200:
                    try:
                        j = r.json()
                    except Exception:
                        j = {"raw": r.text[:500]}
                    response_data = j
                    # MCP error envelope: {"error": {"code": ..., "message": ...}}
                    if isinstance(j, dict) and "error" in j and j["error"]:
                        err = j["error"]
                        error = (err.get("message") if isinstance(err, dict) else str(err))[:400]
                        # if "Method not found" → try next URL
                        if isinstance(err, dict) and err.get("code") in (-32601, -32602):
                            continue
                    else:
                        healthy = True
                    break
                elif r.status_code in (404, 405):
                    # tool not registered at this RPC — try next
                    continue
                else:
                    error = f"HTTP {r.status_code}: {r.text[:300]}"
                    break
            except Exception as e:
                error = f"{type(e).__name__}: {str(e)[:300]}"
                continue

    elapsed_ms = int((time.time() - started) * 1000)

    logger.info(
        "[mcp-tester refire] tool=%s healthy=%s status=%s elapsed=%sms by dev=%s",
        tool, healthy, status_code, elapsed_ms, current_developer.id,
    )

    return {
        "tool":          tool,
        "tier":          tier or ("admin" if "admin" in used_url else "public"),
        "healthy":       healthy,
        "skipped":       skipped,
        "status":        status_code,
        "elapsed":       elapsed_ms,
        "error":         error,
        "response_data": response_data,
        "rpc_url":       used_url,
    }


@router.get("/runs", summary="List recent MCP tester runs")
async def list_runs(
    current_developer: models.Developer = Security(security.get_current_developer),
) -> Dict[str, Any]:
    _require_admin(current_developer)
    run_ids = await _list_recent_run_ids()
    items: List[Dict[str, Any]] = []
    for rid in run_ids:
        meta = await _load_run_meta(rid)
        if not meta:
            continue
        items.append({
            "run_id":       meta.get("run_id"),
            "status":       meta.get("status"),
            "started_at":   meta.get("started_at"),
            "finished_at":  meta.get("finished_at"),
            # surface the stored failure reason in the LIST so a failed run is
            # diagnosable without the (heavier) single-run GET — e.g. "ReadTimeout('')".
            "error":        meta.get("error"),
            "summary":      meta.get("summary"),
            "developer_id": meta.get("developer_id"),
            # §pass73.3.19 — surface suite identity so the FE History "Suite"
            # column can tag each run (federation / cloud-op / mcp).
            "flow_name":    meta.get("flow_name"),
            "flow_label":   meta.get("flow_label"),
        })
    return {"runs": items, "total": len(items)}


@router.get("/latest", summary="Get the latest run (if any)")
async def latest_run(
    current_developer: models.Developer = Security(security.get_current_developer),
) -> Dict[str, Any]:
    _require_admin(current_developer)
    ids = await _list_recent_run_ids(limit=1)
    if not ids:
        return {"run": None}
    return {"run": await _full_run_payload(ids[0])}


async def _full_run_payload(run_id: str) -> Optional[Dict[str, Any]]:
    meta = await _load_run_meta(run_id)
    if not meta:
        return None
    logs = await _load_logs(run_id)
    bug_finds = await _load_list(run_id, "bugfinds")
    hard_fails = await _load_list(run_id, "hardfail")
    expected_reds = await _load_list(run_id, "expectedred")
    skipped = await _load_list(run_id, "skipped")
    policy_denied = await _load_list(run_id, "polideny")
    results = await _load_list(run_id, "results")
    return {
        **meta,
        "log_lines": logs,
        "bug_finds": bug_finds,
        "hard_fails": hard_fails,
        "expected_reds": expected_reds,
        "skipped":   skipped,
        # §MCPTEST-MCP10 — refused-by-standing-order, kept apart from `skipped`
        # (coverage holes). Empty on pre-MCP10 runs, which is honest: those runs
        # conflated the two and we cannot retroactively separate them.
        "policy_denied": policy_denied,
        "results":   results,
    }


@router.get("/runs/{run_id}", summary="Get a single MCP tester run")
async def get_run(
    run_id: str,
    current_developer: models.Developer = Security(security.get_current_developer),
    include_results: bool = False,
) -> Dict[str, Any]:
    _require_admin(current_developer)
    payload = await _full_run_payload(run_id)
    if not payload:
        raise HTTPException(status_code=404, detail=f"run {run_id} not found")
    if not include_results:
        payload.pop("results", None)
    return payload


@router.get("/runs/{run_id}/stream", summary="SSE stream of log lines for a run")
async def stream_run(
    run_id: str,
    current_developer: models.Developer = Security(security.get_current_developer),
):
    """SSE: tails Redis log list for the run. Closes when status flips to
    'completed' or 'failed'."""
    _require_admin(current_developer)
    meta = await _load_run_meta(run_id)
    if not meta:
        raise HTTPException(status_code=404, detail=f"run {run_id} not found")

    async def _gen():
        last_idx = 0
        while True:
            lines = await _load_logs(run_id)
            meta_now = await _load_run_meta(run_id)
            if not meta_now:
                yield "event: error\ndata: run vanished\n\n"
                return
            status = meta_now.get("status")
            summary = meta_now.get("summary")

            # Emit new lines
            if last_idx < len(lines):
                for entry in lines[last_idx:]:
                    yield f"event: log\ndata: {entry.get('msg', '')}\n\n"
                last_idx = len(lines)

            # Emit periodic heartbeat + status
            yield f"event: status\ndata: {status}\n\n"

            if status in ("completed", "failed"):
                if summary:
                    yield f"event: summary\ndata: {json.dumps(summary)}\n\n"
                yield "event: done\ndata: done\n\n"
                return

            await asyncio.sleep(1.5)

    return StreamingResponse(_gen(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# Sandbox EventStore live-stream proxy
# ---------------------------------------------------------------------------
# Why this exists:
#
# The frontend EventStore stream card needs to work from ANY origin —
# sandbox-a.theprotocol.cloud, localhost:8002, prod admin viewing remote
# diagnostics, etc. The browser cannot:
#   (a) reach event-store-test:8200 (docker-internal hostname)
#   (b) reach 127.0.0.1:8204 (loopback-only host port, only same-host)
#   (c) mint a JWT-SVID (no SPIRE workload API in a browser)
#
# Sandbox EventStore is plain HTTP+JWT-SVID-token (no mTLS sidecar deployed
# unlike prod). The registry container CAN reach both — it's on the docker
# network and already mints JWT-SVIDs for reactor WS subscriptions.
#
# So: this endpoint bridges. Browser opens SSE to /event-stream over plain
# HTTPS (cookie/header/query-string auth like the existing log stream).
# Backend opens an aiohttp WS to event-store-test:8200/ws/events with a
# minted JWT-SVID (same code path as reactor_base._ws_url()). Each upstream
# event becomes one downstream SSE frame.

def _es_stream_source() -> Tuple[str, str]:
    """The store the tester's live panel streams, as (base URL, why). §MCPTEST30 (V0541): the TARGET's store, like every
    other probe of the sweep (§EMITDIAG). The panel built its URL from this node's own EVENT_STORE_URL, so on EU's
    console, whose sweeps run against sbx-alpha, the card headed "Sandbox EventStore" streamed EU's own production store
    (its agents' heartbeats) while the sweep's events landed in sbx-alpha's. The target's store is _EMIT_ES_URL
    (API_TEST_EVENT_STORE_URL, else derived from API_TEST_TARGET_URL), the one the emission check polls; this node's own
    store is the fallback only where no target store can be named."""
    if _EMIT_ES_URL:
        return _EMIT_ES_URL, "target"
    return os.getenv("EVENT_STORE_URL", "http://event-store:8200").rstrip("/"), "own"


def _es_stream_host(url: str) -> str:
    """host:port of a store URL, for the panel and the log (never the URL: a token rides its query)."""
    p = urlparse(url or "")
    return f"{p.hostname or '?'}:{p.port}" if p.port else (p.hostname or "?")


def _build_es_ws_url() -> str:
    """Mirror reactor_base._ws_url() — pick JWT-SVID or shared-secret based
    on env, build the EventStore WS URL with the auth token query param.
    §MCPTEST30 (V0541): the target's store first (`_es_stream_source`), with the key the emission check reads it with."""
    src, why = _es_stream_source()
    if why == "target":
        base = src.replace("http://", "ws://").replace("https://", "wss://") + "/ws/events"
        return f"{base}?token={quote(_EMIT_ES_KEY, safe='')}" if _EMIT_ES_KEY else base
    es_url = src
    base = (
        es_url.rstrip("/")
            .replace("http://", "ws://")
            .replace("https://", "wss://")
        + "/ws/events"
    )

    token = ""
    mode = os.getenv("EVENTSTORE_WS_AUTH_MODE", "shared-secret").lower()
    if mode == "jwt-svid":
        try:
            from agentvault_registry.identity.svid_client import svid_client
            audience = os.getenv(
                "EVENTSTORE_JWT_AUDIENCE",
                "spiffe://sandbox-a.test/eventstore",
            )
            jwt_token = svid_client.get_jwt_svid(audience=audience)
            if jwt_token:
                token = jwt_token
        except Exception as e:
            logger.warning(f"[mcp-tester ES-proxy] JWT-SVID mint failed: {e!r}")

    if not token:
        token = (
            os.getenv("EVENT_STORE_INTERNAL_API_KEY")
            or os.getenv("EVENT_STORE_API_KEY")
            or os.getenv("INTERNAL_API_KEY")
            or ""
        )

    return f"{base}?token={quote(token, safe='')}" if token else base


def _bounded_state(st: Any, limit: int = 400) -> Any:
    """A captured state small enough for a run record: dicts and lists cut, strings capped."""
    if isinstance(st, dict):
        return {str(k): _bounded_state(v, limit) for k, v in list(st.items())[:40]}
    if isinstance(st, (list, tuple)):
        return [_bounded_state(v, limit) for v in list(st)[:20]]
    if isinstance(st, str):
        return st if len(st) <= limit else st[:limit] + "…"
    if st is None or isinstance(st, (bool, int, float)):
        return st
    return str(st)[:limit]


def _hard_fail_row(label: str, rr: Dict[str, Any]) -> Dict[str, Any]:
    """§NIGHTLYTRUTH (2026-09-14): a red row carries the state its test captured.

    The federation suite keeps `last_state` on a failed outcome (`responseData.last_state`), and this
    projection used to keep only the tool and the error sentence, so a nightly row whose reason was
    "budget 30.0s exhausted after 10 attempts" could not be classified without re-driving the test. A row
    a test declared red by design (`expected_red=<finding>`) carries that declaration too.
    """
    row: Dict[str, Any] = {"tool": label, "error": (rr.get("error") or "")}
    rd = rr.get("responseData")
    if isinstance(rd, dict):
        if rd.get("last_state") is not None:
            row["last_state"] = _bounded_state(rd["last_state"])
        if rd.get("expected_red"):
            row["expected_red"] = str(rd["expected_red"])
    return row


def _split_red_rows(results: List[Dict[str, Any]], label_of) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """The failed rows, split into the NEW reds and the ones red BY DESIGN (declared `expected_red`).

    A row red by design is documented, not clean: it is listed on its own so the summary can say
    "red as documented" apart from "red, new", and the day its finding lands the declaration goes and
    the row must pass. Skips (`expected_failure`) are neither.
    """
    hard: List[Dict[str, Any]] = []
    expected: List[Dict[str, Any]] = []
    for rr in results:
        if rr.get("healthy") or rr.get("expected_failure"):
            continue
        row = _hard_fail_row(label_of(rr), rr)
        (expected if row.get("expected_red") else hard).append(row)
    return hard, expected


SSE_QUERY_TOKEN_REFUSED = (
    "a query-string access_token is not accepted on this stream: access logs record the request line whole. "
    "Send `Authorization: Bearer <jwt>` (the console reads these streams with fetch, not EventSource)."
)


async def _resolve_admin_from_header(
    request: Request,
    access_token: Optional[str],
    db: AsyncSession,
) -> models.Developer:
    """§RELEASEHARDEN D2 (2026-09-14) — the SSE streams take the JWT from the Authorization header ONLY.

    This used to accept `?access_token=` because a browser EventSource cannot send a header; uvicorn
    then wrote the admin JWT into the container log on every stream open. The console now reads these
    streams with a fetch-based reader that sends the header (`services/sse.ts`). The query parameter is
    still declared on the routes so a stale caller gets this sentence instead of a bare "missing token".
    The minimal slice of `verify_access_token_required` stays duplicated here on purpose: this auth path
    is obvious and self-contained."""
    if access_token:
        raise HTTPException(status_code=401, detail=SSE_QUERY_TOKEN_REFUSED)
    token = ""
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:]
    if not token:
        raise HTTPException(status_code=401, detail="missing token")
    try:
        payload = jwt.decode(token, security.SECRET_KEY, algorithms=[security.ALGORITHM])
        dev_id = int(payload.get("sub", 0))
    except (JWTError, ValueError, TypeError):
        raise HTTPException(status_code=401, detail="invalid token")
    if not dev_id:
        raise HTTPException(status_code=401, detail="invalid token")
    dev = await developer_crud.get_developer_by_id(db, dev_id)
    if not dev or not security.admin_credential(dev):   # §POCKETPAIR: a scoped key is not admin
        raise HTTPException(status_code=403, detail="admin required")
    return dev


def _build_es_b_ws_url() -> str:
    """Build the sandbox-B EventStore WS URL for the multi-frame SSE proxy.

    pass73.3.19 Pass 7 fix (2026-05-28): The obvious choice — EVENT_STORE_B_URL
    (`https://nginx-event-store-test-b:8443`) — is the nginx mTLS GATEWAY.
    That gateway runs `ssl_verify_client on` against sandbox-B's SPIRE trust
    bundle. The registry's SSE-proxy SSL context carries sandbox-A's bundle,
    NOT the federated sandbox-b.test bundle — so the handshake fails with
    `unable to get local issuer certificate` (server-cert) and HTTP 400
    (missing client cert). This is the cross-trust-domain boundary working
    as designed; we should NOT punch through it from the registry.

    Instead use the DIRECT internal docker hostname `event-store-test-b:8200`
    — same path that ES↔ES cross-frame replication uses (CROSS_FRAME_PEERS).
    Sandbox-B ES has EVENTSTORE_WS_AUTH_REQUIRED=false on the internal port,
    so plain ws:// with no mTLS works. Verified reachable from registry-test.
    """
    # §EMITDIAG-4b: the FOURTH site of the same rot, found because the build's own
    # printed expectation (<=6 occurrences) came out 13 and I checked the real
    # property — "is a retired hostname still an os.getenv DEFAULT?" — instead of
    # waving the number through. A printed number is not a gate. Prefer the peer
    # store this console is actually configured with; fall back to nothing rather
    # than to a tier that no longer exists (an empty base yields no socket, and the
    # caller reports that, instead of dialling a host that cannot resolve).
    internal = (os.getenv("EVENT_STORE_B_INTERNAL_URL")
                or _EMIT_ES_B_URL
                or "")
    if not internal:
        return ""
    base = (
        internal.rstrip("/")
            .replace("http://", "ws://")
            .replace("https://", "wss://")
        + "/ws/events"
    )
    # Token is optional (B has WS auth disabled on internal port) but include
    # it if present so this still works if B ever flips auth on.
    token = (
        os.getenv("EVENT_STORE_INTERNAL_API_KEY")
        or os.getenv("EVENT_STORE_API_KEY")
        or ""
    )
    return f"{base}?token={quote(token, safe='')}" if token else base


@router.get("/event-stream-multi",
            summary="SSE proxy: multi-frame live events (sandbox-A + sandbox-B)")
async def event_stream_proxy_multi(
    request: Request,
    access_token: Optional[str] = Query(None),
    frames: str = Query("a,b", description="Comma-separated frames to subscribe to"),
    db: AsyncSession = Depends(get_db),
):
    """Combined SSE for both sandbox-A and sandbox-B EventStore feeds.

    Each frame's WS is opened server-side via mTLS (same code path as
    /event-stream). Each event is tagged with `_frame: "A" | "B"` before
    being forwarded down the SSE pipe. Browser sees one ordered stream
    with origin metadata so the FE can color-code by frame.

    `?frames=a` → A only · `?frames=a,b` → both · `?frames=b` → B only
    """
    await _resolve_admin_from_header(request, access_token, db)

    wanted = set(f.strip().lower() for f in (frames or "a,b").split(",") if f.strip())
    do_a = "a" in wanted
    do_b = "b" in wanted
    if not (do_a or do_b):
        raise HTTPException(status_code=400, detail="frames must include 'a' and/or 'b'")

    # Each upstream connection runs as a sibling task; both feed the same
    # SSE pipe via an asyncio.Queue.
    queue: asyncio.Queue = asyncio.Queue(maxsize=2000)
    tasks: List[asyncio.Task] = []
    SSL_OPT = get_es_ssl_context()

    async def _pump(frame_label: str, ws_url: str):
        backoff = 0.5
        while True:
            if await request.is_disconnected():
                return
            try:
                connector = aiohttp.TCPConnector(ssl=SSL_OPT) if SSL_OPT else None
                async with aiohttp.ClientSession(connector=connector) as session:
                    async with session.ws_connect(ws_url, heartbeat=30.0) as ws:
                        backoff = 0.5
                        await ws.send_json({"action": "subscribe", "channel": "events:all"})
                        await queue.put(("upstream-open", frame_label))
                        while True:
                            if await request.is_disconnected():
                                return
                            try:
                                msg = await asyncio.wait_for(ws.receive(), timeout=30.0)
                            except asyncio.TimeoutError:
                                await queue.put(("ping", frame_label))
                                continue
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                # Tag with frame inline so receiver doesn't need
                                # to track which task it came from.
                                payload = msg.data.replace("\n", " ")
                                await queue.put(("event", (frame_label, payload)))
                            elif msg.type in (aiohttp.WSMsgType.ERROR,
                                              aiohttp.WSMsgType.CLOSED,
                                              aiohttp.WSMsgType.CLOSING):
                                await queue.put(("upstream-close", frame_label))
                                break
            except Exception as e:
                await queue.put(("upstream-error", f"{frame_label}:{type(e).__name__}"))
            await asyncio.sleep(min(backoff, 5.0))
            backoff = min(backoff * 1.5, 5.0)

    if do_a:
        tasks.append(asyncio.create_task(_pump("A", _build_es_ws_url())))
    if do_b:
        # §EMITDIAG-4b: an EMPTY url means no peer store is configured for this
        # console. Pumping it would loop a connect-fail forever against a hostname
        # from the retired tier; skipping it and saying so is the same third state
        # the es_reachable check now carries.
        _b_ws = _build_es_b_ws_url()
        if _b_ws:
            tasks.append(asyncio.create_task(_pump("B", _b_ws)))
        else:
            logger.info("[mcp-tester] no peer EventStore configured "
                        "(EVENT_STORE_B_INTERNAL_URL / API_TEST_EVENT_STORE_B_URL unset) "
                        "— the B stream is NOT MEASURED for this console, not down")

    async def _gen():
        yield "event: connected\ndata: ok\n\n"
        # §MCPTEST30 (V0541): which stores the panel shows (host:port only)
        if do_a:
            _a_src, _a_why = _es_stream_source()
            yield f"event: source\ndata: A {_es_stream_host(_a_src)} {_a_why}\n\n"
        if do_b and _b_ws:
            yield f"event: source\ndata: B {_es_stream_host(_b_ws)} peer\n\n"
        try:
            while True:
                if await request.is_disconnected():
                    return
                try:
                    kind, payload = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue
                if kind == "event":
                    frame_label, raw_payload = payload
                    yield f"event: event\ndata: {raw_payload}\nid: {frame_label}\n\n"
                elif kind == "upstream-open":
                    yield f"event: upstream-open\ndata: {payload}\n\n"
                elif kind == "upstream-close":
                    yield f"event: upstream-close\ndata: {payload}\n\n"
                elif kind == "upstream-error":
                    yield f"event: upstream-error\ndata: {payload}\n\n"
                elif kind == "ping":
                    yield f": ping {payload}\n\n"
        finally:
            for t in tasks:
                t.cancel()

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/event-stream",
            summary="SSE proxy: live events from the sandbox EventStore")
async def event_stream_proxy(
    request: Request,
    access_token: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """SSE forwarder for the sandbox EventStore WebSocket feed.

    Each upstream event is emitted as one SSE frame:
        event: event
        data: {<raw event json>}

    Closes when the browser disconnects, when the upstream WS dies for too
    long, or when admin auth fails. Auto-reconnects to the upstream once
    per second on transient failures so the browser experience stays smooth
    across EventStore restarts.
    """
    await _resolve_admin_from_header(request, access_token, db)

    # §MCPTEST30 (V0541): the store's host:port, never its URL (the token rides the query, and aiohttp's handshake
    # errors repeat the request URL)
    _src, _why = _es_stream_source()
    es_url_for_log = _es_stream_host(_src)

    async def _gen():
        # Emit one immediate frame so the browser EventSource gets onopen
        # right away. Prevents the UI from sitting on CONNECTING for the
        # entire upstream handshake.
        yield "event: connected\ndata: ok\n\n"
        # §MCPTEST30 (V0541): which store the panel shows, so its heading can name it
        yield f"event: source\ndata: A {es_url_for_log} {_why}\n\n"

        backoff = 0.5
        while True:
            if await request.is_disconnected():
                logger.info("[mcp-tester ES-proxy] client disconnected")
                return
            try:
                ws_url = _build_es_ws_url()
                ssl_ctx = get_es_ssl_context()
                connector = aiohttp.TCPConnector(ssl=ssl_ctx) if ssl_ctx else None
                async with aiohttp.ClientSession(connector=connector) as session:
                    async with session.ws_connect(ws_url, heartbeat=30.0) as ws:
                        backoff = 0.5
                        await ws.send_json({"action": "subscribe", "channel": "events:all"})
                        yield "event: upstream-open\ndata: subscribed\n\n"
                        while True:
                            if await request.is_disconnected():
                                logger.info("[mcp-tester ES-proxy] client disconnected mid-stream")
                                return
                            try:
                                msg = await asyncio.wait_for(ws.receive(), timeout=30.0)
                            except asyncio.TimeoutError:
                                # Comment line keeps the SSE pipe warm
                                yield ": ping\n\n"
                                continue
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                # Forward raw; frontend already has the
                                # deep-find parser for ES event shapes.
                                # SSE requires a single line per `data:` —
                                # ES messages don't contain newlines but be
                                # defensive.
                                payload = msg.data.replace("\n", " ")
                                yield f"event: event\ndata: {payload}\n\n"
                            elif msg.type in (
                                aiohttp.WSMsgType.ERROR,
                                aiohttp.WSMsgType.CLOSED,
                                aiohttp.WSMsgType.CLOSING,
                            ):
                                logger.info(
                                    f"[mcp-tester ES-proxy] upstream WS {msg.type.name}, will reconnect"
                                )
                                yield f"event: upstream-close\ndata: {msg.type.name}\n\n"
                                break
            except Exception as e:
                logger.warning(
                    f"[mcp-tester ES-proxy] upstream {es_url_for_log} error: {type(e).__name__}"
                )
                yield f"event: upstream-error\ndata: {type(e).__name__}\n\n"

            # Reconnect with bounded backoff
            await asyncio.sleep(min(backoff, 5.0))
            backoff = min(backoff * 1.5, 5.0)

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # nginx: don't buffer SSE
        },
    )
