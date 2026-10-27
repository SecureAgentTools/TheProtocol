"""Admin API for canary transfer system observability + control.

Endpoints under `/api/v1/admin/canary/*` — all require admin_platform flag.

  GET  /admin/canary/status                      — full dashboard snapshot
  GET  /admin/canary/results                      — recent test results (filterable)
  POST /admin/canary/fire                          — manually trigger a path
  POST /admin/canary/path/{id}/toggle              — enable/disable a path
  POST /admin/canary/maintenance                   — global or per-path maintenance window

The status endpoint aggregates: paths matrix, 24h pass-rate per path, agents
with TEG balances (estimated from last test), supply Δ, and a 5-min health
window. Frontend AdminCanaries.vue refreshes this every 10s.
"""
from __future__ import annotations

import datetime
import os
import uuid
from typing import Optional, List, Dict, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status, Security
from sqlalchemy import select, func, and_, or_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models, security
from ..database import get_db
from ..es_ssl_helper import get_httpx_verify


router = APIRouter(prefix="/admin/canary", tags=["Admin — Canary"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _supply_delta() -> Dict[str, Any]:
    """Fetch supply Δ for both frames (best-effort — None on failure)."""
    out = {"frame_a": None, "frame_b": None}
    es_a = os.environ.get("EVENT_STORE_URL", "http://event-store:8200")
    es_b = os.environ.get("EVENT_STORE_B_URL", "http://frame-b-event-store:8200")
    try:
        async with httpx.AsyncClient(timeout=2.0, verify=get_httpx_verify()) as c:
            try:
                r = await c.get(f"{es_a}/api/v1/projections/supply-audit")
                if r.status_code == 200:
                    out["frame_a"] = r.json().get("delta")
            except Exception:
                pass
            try:
                r = await c.get(f"{es_b}/api/v1/projections/supply-audit")
                if r.status_code == 200:
                    out["frame_b"] = r.json().get("delta")
            except Exception:
                pass
    except Exception:
        pass
    return out


async def _agents_with_balances(db: AsyncSession) -> List[Dict[str, Any]]:
    """Return canary agents + estimated TEG balances (best-effort).

    Balance estimation is approximate — derived from agent_teg_profiles on the
    LOCAL TEG only. For agents on remote TEGs, balance is unknown from this
    registry's perspective. Frontend should display 'remote' marker.
    """
    result = await db.execute(
        select(models.CanaryAgent).order_by(models.CanaryAgent.frame, models.CanaryAgent.registry_id)
    )
    agents = list(result.scalars().all())

    return [
        {
            "id": a.id,
            "name": a.notes or a.agent_did[:30],
            "agent_did": a.agent_did,
            "client_id": a.client_id,
            "registry_id": a.registry_id,
            "registry_url": a.registry_url,
            "frame": a.frame,
            "is_active": a.is_active,
            "prefund_amount": str(a.prefund_amount),
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in agents
    ]


async def _path_stats(
    db: AsyncSession,
    window_minutes: int = 1440,  # 24h
) -> Dict[int, Dict[str, Any]]:
    """Aggregate test results per path over the given window."""
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=window_minutes)
    rows = await db.execute(
        select(
            models.CanaryTestResult.path_id,
            models.CanaryTestResult.outcome,
            func.count().label("n"),
            func.avg(models.CanaryTestResult.total_latency_ms).label("avg_latency"),
            func.max(models.CanaryTestResult.total_latency_ms).label("max_latency"),
            func.min(models.CanaryTestResult.total_latency_ms).label("min_latency"),
        )
        .where(models.CanaryTestResult.fired_at >= cutoff)
        .group_by(models.CanaryTestResult.path_id, models.CanaryTestResult.outcome)
    )
    stats: Dict[int, Dict[str, Any]] = {}
    for r in rows:
        path_id, outcome, n, avg_lat, max_lat, min_lat = r
        s = stats.setdefault(path_id, {"passed": 0, "failed": 0, "fired": 0, "total": 0, "avg_latency_ms": None, "max_latency_ms": None, "min_latency_ms": None})
        s[outcome] = n or 0
        s["total"] = s["passed"] + s["failed"] + s["fired"]
        if outcome == "passed" and avg_lat is not None:
            s["avg_latency_ms"] = int(avg_lat)
            s["max_latency_ms"] = int(max_lat) if max_lat else None
            s["min_latency_ms"] = int(min_lat) if min_lat else None

    for s in stats.values():
        if s["total"] > 0 and s["passed"] + s["failed"] > 0:
            s["pass_rate"] = round(s["passed"] / max(1, s["passed"] + s["failed"]) * 100, 1)
        else:
            s["pass_rate"] = None
    return stats


async def _last_result_per_path(db: AsyncSession) -> Dict[int, Dict[str, Any]]:
    """Most recent test result per path (any outcome)."""
    subq = (
        select(
            models.CanaryTestResult.path_id,
            func.max(models.CanaryTestResult.fired_at).label("max_fired"),
        )
        .group_by(models.CanaryTestResult.path_id)
        .subquery()
    )
    rows = await db.execute(
        select(models.CanaryTestResult)
        .join(
            subq,
            and_(
                models.CanaryTestResult.path_id == subq.c.path_id,
                models.CanaryTestResult.fired_at == subq.c.max_fired,
            ),
        )
    )
    out: Dict[int, Dict[str, Any]] = {}
    for r in rows.scalars().all():
        out[r.path_id] = {
            "test_id": r.test_id,
            "outcome": r.outcome,
            "fired_at": r.fired_at.isoformat() if r.fired_at else None,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            "http_status": r.http_status,
            "http_latency_ms": r.http_latency_ms,
            "total_latency_ms": r.total_latency_ms,
            "transfer_id": r.transfer_id,
            "failure_type": r.failure_type,
            "failure_detail": r.failure_detail,
        }
    return out


# ---------------------------------------------------------------------------
# GET /admin/canary/status
# ---------------------------------------------------------------------------

@router.get("/status", summary="Full canary system dashboard snapshot")
async def canary_status(
    db: AsyncSession = Depends(get_db),
    _admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    """Single-call snapshot for the AdminCanaries dashboard.

    Returns:
      - summary: total_paths, active_paths, pass_rate_24h_avg, pending_count,
                 tests_per_minute_5m, delta_frame_a, delta_frame_b
      - paths: per-path matrix with sender/receiver agent details + 24h stats
      - agents: canary agents + metadata
      - recent_failures: last 10 failed tests across all paths
    """
    paths_result = await db.execute(
        select(models.CanaryPath).order_by(models.CanaryPath.id)
    )
    paths = list(paths_result.scalars().all())

    agents_result = await db.execute(select(models.CanaryAgent))
    agents_by_id = {a.id: a for a in agents_result.scalars().all()}

    stats_24h = await _path_stats(db, window_minutes=1440)
    stats_5m = await _path_stats(db, window_minutes=5)
    last_result = await _last_result_per_path(db)

    # 5-minute pending count
    pending_cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=5)
    pending_q = await db.execute(
        select(func.count())
        .select_from(models.CanaryTestResult)
        .where(
            models.CanaryTestResult.outcome == "fired",
            models.CanaryTestResult.fired_at >= pending_cutoff,
        )
    )
    pending_count = pending_q.scalar() or 0

    # Recent failures
    fail_q = await db.execute(
        select(models.CanaryTestResult)
        .where(models.CanaryTestResult.outcome == "failed")
        .order_by(desc(models.CanaryTestResult.fired_at))
        .limit(10)
    )
    recent_failures = []
    for r in fail_q.scalars().all():
        recent_failures.append({
            "test_id": r.test_id,
            "path_id": r.path_id,
            "fired_at": r.fired_at.isoformat() if r.fired_at else None,
            "backend": r.backend,
            "sender_did": r.sender_did,
            "receiver_did": r.receiver_did,
            "failure_type": r.failure_type,
            "failure_detail": r.failure_detail,
            "http_status": r.http_status,
        })

    paths_out = []
    overall_pass = 0
    overall_fail = 0
    for p in paths:
        sender = agents_by_id.get(p.sender_agent_id)
        receiver = agents_by_id.get(p.receiver_agent_id)
        s24 = stats_24h.get(p.id, {"passed": 0, "failed": 0, "fired": 0, "total": 0, "pass_rate": None, "avg_latency_ms": None})
        last = last_result.get(p.id)
        overall_pass += s24.get("passed", 0)
        overall_fail += s24.get("failed", 0)

        paths_out.append({
            "id": p.id,
            "path_id": p.path_id,
            "sender_name": (sender.notes if sender else None),
            "sender_did": sender.agent_did if sender else None,
            "receiver_name": (receiver.notes if receiver else None),
            "receiver_did": receiver.agent_did if receiver else None,
            "backend": p.backend,
            "amount": str(p.amount),
            "interval_sec": p.interval_sec,
            "slo_http_ms": p.slo_http_ms,
            "slo_settled_sec": p.slo_settled_sec,
            "is_active": p.is_active,
            "stats_24h": s24,
            "stats_5m": stats_5m.get(p.id, {"passed": 0, "failed": 0, "fired": 0}),
            "last_result": last,
            "frame_pair": f"{sender.frame if sender else '?'}->{receiver.frame if receiver else '?'}",
        })

    delta = await _supply_delta()
    overall_total = overall_pass + overall_fail
    summary = {
        "total_paths": len(paths),
        "active_paths": sum(1 for p in paths if p.is_active),
        "pass_rate_24h": round(overall_pass / max(1, overall_total) * 100, 1) if overall_total else None,
        "passes_24h": overall_pass,
        "failures_24h": overall_fail,
        "pending_count": pending_count,
        "tests_per_minute_5m": round(sum(s.get("total", 0) for s in stats_5m.values()) / 5.0, 1),
        "delta_frame_a": delta["frame_a"],
        "delta_frame_b": delta["frame_b"],
        "snapshot_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }

    agents_data = await _agents_with_balances(db)

    return {
        "summary": summary,
        "paths": paths_out,
        "agents": agents_data,
        "recent_failures": recent_failures,
    }


# ---------------------------------------------------------------------------
# GET /admin/canary/results
# ---------------------------------------------------------------------------

@router.get("/results", summary="Recent canary test results (filterable)")
async def canary_results(
    path_id: Optional[int] = Query(None, description="Filter by path id"),
    outcome: Optional[str] = Query(None, pattern="^(fired|passed|failed)$"),
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    _admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    q = select(models.CanaryTestResult).order_by(desc(models.CanaryTestResult.fired_at)).limit(limit)
    if path_id is not None:
        q = q.where(models.CanaryTestResult.path_id == path_id)
    if outcome:
        q = q.where(models.CanaryTestResult.outcome == outcome)
    rows = await db.execute(q)
    return [
        {
            "id": r.id,
            "test_id": r.test_id,
            "path_id": r.path_id,
            "fired_at": r.fired_at.isoformat() if r.fired_at else None,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            "backend": r.backend,
            "sender_did": r.sender_did,
            "receiver_did": r.receiver_did,
            "amount": str(r.amount),
            "transfer_id": r.transfer_id,
            "http_status": r.http_status,
            "http_latency_ms": r.http_latency_ms,
            "total_latency_ms": r.total_latency_ms,
            "phase_latencies": r.phase_latencies,
            "outcome": r.outcome,
            "failure_type": r.failure_type,
            "failure_detail": r.failure_detail,
        }
        for r in rows.scalars().all()
    ]


# ---------------------------------------------------------------------------
# POST /admin/canary/path/{id}/toggle
# ---------------------------------------------------------------------------

@router.post("/path/{path_id}/toggle", summary="Toggle canary path active state")
async def canary_path_toggle(
    path_id: int,
    db: AsyncSession = Depends(get_db),
    _admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    r = await db.execute(select(models.CanaryPath).where(models.CanaryPath.id == path_id))
    p = r.scalar_one_or_none()
    if p is None:
        raise HTTPException(404, "Canary path not found")
    p.is_active = not p.is_active
    await db.commit()
    return {"id": p.id, "path_id": p.path_id, "is_active": p.is_active}


# ---------------------------------------------------------------------------
# POST /admin/canary/maintenance
# ---------------------------------------------------------------------------

@router.post("/maintenance", summary="Set maintenance window (disable paths temporarily)")
async def canary_maintenance(
    payload: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    _admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    """Disable all paths (or a subset) for maintenance.

    Body: { "scope": "all" | [path_id, ...], "enable": false (default) }
    """
    scope = payload.get("scope", "all")
    enable = bool(payload.get("enable", False))

    q = select(models.CanaryPath)
    if scope != "all":
        if not isinstance(scope, list):
            raise HTTPException(400, "scope must be 'all' or a list of path ids")
        q = q.where(models.CanaryPath.id.in_(scope))
    rows = await db.execute(q)
    n = 0
    for p in rows.scalars().all():
        p.is_active = enable
        n += 1
    await db.commit()
    return {"updated_paths": n, "enable": enable}


# ---------------------------------------------------------------------------
# POST /admin/canary/fire — manual fire of a single path
# ---------------------------------------------------------------------------

async def fire_would_not_run() -> Optional[str]:
    """Why a manual fire on this registry would not run, or None when its canary runner fires local paths: the runner
    (canary_runner._run_cycle) fires nothing without CANARY_ENABLED and CANARY_RUNNER_ENABLED, never self-schedules as a
    follower, and skips every fire while the fleet is paused (a Redis key; Redis unreadable reads as not paused, as
    the runner reads it)."""
    from ..background_tasks import canary_runner as runner
    if not (runner.CANARY_ENABLED and runner.CANARY_RUNNER_ENABLED):
        return "No canary runner runs on this registry, so nothing would fire the path."
    if runner.CANARY_RUNNER_MODE == "follower":
        return ("This registry's canary runner is a follower: it fires a path only when its master dispatches it, "
                "on the master's schedule.")
    try:
        from ..background_tasks.leader import get_redis
        redis = await get_redis()
        if redis is not None and await redis.get(runner.CANARY_FLEET_PAUSED_KEY):
            return "The canary fleet is paused: no path fires until it is resumed."
    except Exception:
        pass
    return None


@router.post("/fire", summary="Manually fire a canary transfer (bypasses interval)")
async def canary_fire(
    payload: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    _admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    """Fire one canary transfer immediately by clearing the runner's last-fire
    timestamp for that path. Next runner cycle (within 5s) will fire it.

    Body: { "path_id": <int> }
    """
    path_id = payload.get("path_id")
    if not isinstance(path_id, int):
        raise HTTPException(400, "path_id (int) is required")
    r = await db.execute(select(models.CanaryPath).where(models.CanaryPath.id == path_id))
    p = r.scalar_one_or_none()
    if p is None:
        raise HTTPException(404, "Canary path not found")
    # §MCPTEST30 V0637: say so when no runner here would fire the path. The answer promised a fire within 5 s on a
    # follower (every cloud operator), on a registry without a runner and on a paused fleet, where the runner's cycle
    # returns before firing anything, so the fire never came (found by the MCP tester's operator sweep).
    not_here = await fire_would_not_run()
    if not_here:
        raise HTTPException(409, not_here)

    # Best-effort: clear runner's in-memory cache via Redis side-channel
    try:
        from ..background_tasks.leader import get_redis
        redis = await get_redis()
        if redis is not None:
            await redis.publish("canary_runner_force_fire", str(path_id))
    except Exception:
        pass
    return {
        "path_id": path_id,
        "scheduled": True,
        "message": "Path will fire on next runner cycle (within 5s)",
    }


# ---------------------------------------------------------------------------
# §V0045 Canary Cockpit — fleet control plane (meaningful on the master/registry-a;
# harmless no-ops elsewhere). One flag pauses ALL scheduling (local + dispatched);
# /fleet/status is the single pane for the cockpit's scheduling health.
# ---------------------------------------------------------------------------

@router.post("/fleet/pause", summary="Cockpit: pause ALL canary scheduling (master flag)")
async def canary_fleet_pause(
    _admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    """Silences the scheduler on THIS registry. On the master that silences the whole
    fleet (locals + remote dispatches) — the one-button silent box. Redis-only by
    design: a Redis flush RESUMES canaries (fail-open-to-monitoring). Symmetric —
    never touches canary_paths.is_active (config preserved exactly)."""
    from ..background_tasks.leader import get_redis
    from ..background_tasks.canary_runner import CANARY_FLEET_PAUSED_KEY, CANARY_RUNNER_MODE
    redis = await get_redis()
    if redis is None:
        raise HTTPException(status_code=503, detail="Redis unavailable — cannot set fleet pause")
    await redis.set(CANARY_FLEET_PAUSED_KEY, datetime.datetime.now(datetime.timezone.utc).isoformat())
    return {"paused": True, "mode": CANARY_RUNNER_MODE,
            "note": "scheduler skips all local fires + remote dispatches within 1 tick (≤5s)"}


@router.post("/fleet/resume", summary="Cockpit: resume canary scheduling (clears the master flag)")
async def canary_fleet_resume(
    _admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    from ..background_tasks.leader import get_redis
    from ..background_tasks.canary_runner import CANARY_FLEET_PAUSED_KEY, CANARY_RUNNER_MODE
    redis = await get_redis()
    if redis is None:
        raise HTTPException(status_code=503, detail="Redis unavailable — cannot clear fleet pause")
    await redis.delete(CANARY_FLEET_PAUSED_KEY)
    return {"paused": False, "mode": CANARY_RUNNER_MODE}


@router.get("/fleet/status", summary="Cockpit: fleet scheduling status (mode, pause, dispatch health)")
async def canary_fleet_status(
    db: AsyncSession = Depends(get_db),
    _admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    """Single pane for the cockpit: mode + pause flag, local path counts, every remote
    schedule row, and 24h dispatch outcomes per home (the dispatched-vs-executed
    conservation view; per-path pass-rates stay on each registry's /admin/canary/status)."""
    from ..background_tasks.leader import get_redis
    from ..background_tasks.canary_runner import CANARY_FLEET_PAUSED_KEY, CANARY_RUNNER_MODE
    paused_at = None
    try:
        redis = await get_redis()
        if redis is not None:
            v = await redis.get(CANARY_FLEET_PAUSED_KEY)
            if v is not None:
                paused_at = v.decode() if isinstance(v, (bytes, bytearray)) else str(v)
    except Exception:
        pass

    local_active = (await db.execute(
        select(func.count()).select_from(models.CanaryPath).where(models.CanaryPath.is_active == True)
    )).scalar() or 0
    local_total = (await db.execute(
        select(func.count()).select_from(models.CanaryPath)
    )).scalar() or 0

    rrows = (await db.execute(
        select(models.CanaryRemotePath).order_by(
            models.CanaryRemotePath.home_registry, models.CanaryRemotePath.remote_path_id
        )
    )).scalars().all()

    since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=24)
    agg: Dict[str, Dict[str, int]] = {}
    for home, outcome, n in (await db.execute(
        select(models.CanaryDispatch.home_registry, models.CanaryDispatch.outcome, func.count())
        .where(models.CanaryDispatch.dispatched_at >= since)
        .group_by(models.CanaryDispatch.home_registry, models.CanaryDispatch.outcome)
    )).all():
        agg.setdefault(home, {})[outcome] = int(n)

    # §V0046 — per-path latest dispatch (PG DISTINCT ON) so the cockpit UI shows each
    # federated path's live state without N queries.
    last_by_key: Dict[Any, Any] = {}
    try:
        for d in (await db.execute(
            select(models.CanaryDispatch).order_by(
                models.CanaryDispatch.home_registry,
                models.CanaryDispatch.remote_path_id,
                models.CanaryDispatch.dispatched_at.desc(),
            ).distinct(models.CanaryDispatch.home_registry, models.CanaryDispatch.remote_path_id)
        )).scalars().all():
            last_by_key[(d.home_registry, d.remote_path_id)] = d
    except Exception:
        last_by_key = {}

    def _ld(r):
        d = last_by_key.get((r.home_registry, r.remote_path_id))
        if d is None:
            return None
        return {
            "outcome": d.outcome,
            "dispatched_at": d.dispatched_at.isoformat() if d.dispatched_at else None,
            "http_status": d.http_status,
            "latency_ms": d.latency_ms,
            "error": (d.error or "")[:160] or None,
            "test_id": d.test_id,
        }

    return {
        "mode": CANARY_RUNNER_MODE,
        "fleet_paused": bool(paused_at),
        "paused_at": paused_at,
        "local_paths": {"active": int(local_active), "total": int(local_total)},
        "remote_paths": [
            {
                "id": r.id, "home_registry": r.home_registry,
                "remote_path_id": r.remote_path_id, "path_label": r.path_label,
                "interval_sec": r.interval_sec, "is_active": r.is_active,
                "notes": r.notes, "last_dispatch": _ld(r),
            } for r in rrows
        ],
        "dispatch_24h_by_home": agg,
    }


@router.post("/fleet/remote-paths", summary="Cockpit: upsert master schedule rows for peer-homed paths")
async def canary_fleet_upsert_remote_paths(
    payload: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    _admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    """Body: {"paths": [{home_registry, remote_path_id, path_label?, interval_sec?, is_active?, notes?}]}.
    home_registry must match a peer_registries.name (case-insensitive) — that's how the
    dispatcher resolves the federation mTLS target. Upsert on (home_registry, remote_path_id)."""
    rows = (payload or {}).get("paths") or []
    upserted = 0
    for r in rows:
        home = str(r.get("home_registry") or "").strip()
        try:
            rpid = int(r.get("remote_path_id") or 0)
        except (TypeError, ValueError):
            continue
        if not home or rpid <= 0:
            continue
        existing = (await db.execute(
            select(models.CanaryRemotePath).where(
                models.CanaryRemotePath.home_registry == home,
                models.CanaryRemotePath.remote_path_id == rpid,
            )
        )).scalar_one_or_none()
        if existing is None:
            existing = models.CanaryRemotePath(
                home_registry=home, remote_path_id=rpid,
                path_label=str(r.get("path_label") or f"{home}#{rpid}")[:128],
            )
            db.add(existing)
        if r.get("path_label"):
            existing.path_label = str(r.get("path_label"))[:128]
        if r.get("interval_sec"):
            existing.interval_sec = max(15, int(r.get("interval_sec")))
        if "is_active" in r:
            existing.is_active = bool(r.get("is_active"))
        if r.get("notes") is not None:
            existing.notes = str(r.get("notes"))
        upserted += 1
    await db.commit()
    return {"upserted": upserted}
