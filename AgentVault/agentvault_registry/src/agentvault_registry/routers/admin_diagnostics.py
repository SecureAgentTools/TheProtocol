"""Command Center diagnostics router (admin-only).

Phase 1A endpoints:
  GET  /api/v1/admin/diagnostics/targets        — list operators + frames
  GET  /api/v1/admin/diagnostics/checks         — describe available checks
  POST /api/v1/admin/diagnostics/run            — run subset of (checks × targets)
  POST /api/v1/admin/diagnostics/run-all        — run all checks against one target

Phase 1C/1D will add /config/{target}, action endpoints, and /ws.
"""

import asyncio
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Security
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry import models
from agentvault_registry.database import get_db
from agentvault_registry import security

from agentvault_registry.services.diagnostics import (
    actions as action_module,
    audit,
    cache,
    config_reader,
)
from agentvault_registry.services.diagnostics.checks import (
    all_descriptors,
    applies_to,
    get_runner,
    known_check_ids,
)
from agentvault_registry.services.diagnostics.probe import get_probe
from agentvault_registry.services.diagnostics.schemas import (
    ActionRequest,
    ActionResult,
    CheckDescriptor,
    CheckResult,
    RunAllRequest,
    RunRequest,
    TargetSummary,
)
from agentvault_registry.services.diagnostics.targets import (
    empty_summary,
    get_target,
    list_targets,
    why_no_containers,
    why_no_targets,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/admin/diagnostics",
    tags=["Command Center"],
    dependencies=[Security(security.require_admin_flag("admin_platform"))],
)


@router.get("/targets", summary="List all diagnostic targets")
async def get_targets(
    db: AsyncSession = Depends(get_db),
) -> dict:
    targets = await list_targets(db)
    summaries = []
    for t in targets:
        summary = empty_summary(t)
        # Pull cached results so the overview grid lights up on cold load.
        cached: list[CheckResult] = []
        for check_id in known_check_ids():
            if not applies_to(check_id, t):
                continue
            r = await cache.get_cached(check_id, t["operator_id"])
            if r:
                cached.append(r.truncate_evidence())
        summary.check_results = cached
        if cached:
            summary.last_snapshot_at = max(r.checked_at for r in cached)
            summary.status = _aggregate_status([r.status for r in cached])
        summaries.append(summary.model_dump(mode="json"))
    # §MCPTEST30 (V0561): an empty list says why (the console shows it instead of a red 0% ring over nothing).
    # V0562: the list always holds this registry itself (is_self), so the reason says why it holds no OPERATOR.
    operators = [x for x in summaries if not x.get("is_self")]
    code, sentence = (None, None) if operators else why_no_targets()
    c_code, c_sentence = why_no_containers() or (None, None)
    return {"targets": summaries, "count": len(summaries), "reason": sentence, "reason_code": code,
            "containers_reason": c_sentence, "containers_reason_code": c_code}


@router.get("/checks", summary="List all available diagnostic checks")
async def get_checks() -> dict:
    descriptors: list[CheckDescriptor] = all_descriptors()
    return {"checks": [d.model_dump() for d in descriptors], "count": len(descriptors)}


@router.post("/run", summary="Run a subset of (checks × targets)")
async def run_subset(
    request: RunRequest,
    current_admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    check_ids = request.check_ids or known_check_ids()
    target_ids = request.targets
    if not target_ids:
        raise HTTPException(status_code=400, detail="targets must not be empty")

    target_dicts = []
    for tid in target_ids:
        t = await get_target(db, tid)
        if t:
            target_dicts.append(t)
    if not target_dicts:
        raise HTTPException(status_code=404, detail="no matching targets")

    results = await _execute_matrix(check_ids, target_dicts, force=request.force, actor=current_admin.email)
    return {"results": [r.model_dump(mode="json") for r in results], "count": len(results)}


@router.post("/run-all", summary="Run all applicable checks against one target")
async def run_all(
    request: RunAllRequest,
    current_admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    target = await get_target(db, request.target)
    if not target:
        raise HTTPException(status_code=404, detail=f"target {request.target!r} not found")
    results = await _execute_matrix(known_check_ids(), [target], force=request.force, actor=current_admin.email)
    return {
        "target": request.target,
        "results": [r.model_dump(mode="json") for r in results],
        "count": len(results),
        "total_latency_ms": sum(r.latency_ms for r in results),
    }


# ─── internals ───────────────────────────────────────────────────────────


async def _execute_matrix(
    check_ids: list[str],
    targets: list[dict],
    force: bool,
    actor: Optional[str],
) -> list[CheckResult]:
    probe = get_probe()
    coros = []
    plan: list[tuple[str, dict]] = []
    for t in targets:
        for cid in check_ids:
            if not applies_to(cid, t):
                continue
            plan.append((cid, t))
            coros.append(_run_one(cid, t, probe, force=force, actor=actor))
    raw_results = await asyncio.gather(*coros, return_exceptions=True)
    results: list[CheckResult] = []
    for (cid, t), raw in zip(plan, raw_results):
        if isinstance(raw, BaseException):
            logger.warning(f"[diag] {cid}@{t['operator_id']} raised: {raw}")
            results.append(
                CheckResult(
                    check_id=cid,
                    target=t["operator_id"],
                    status="fail",
                    latency_ms=0,
                    summary=f"check raised: {str(raw)[:120]}",
                    evidence=str(raw)[:1024],
                )
            )
        else:
            results.append(raw)
    return results


async def _run_one(
    check_id: str,
    target: dict,
    probe,
    force: bool,
    actor: Optional[str],
) -> CheckResult:
    if not force:
        cached = await cache.get_cached(check_id, target["operator_id"])
        if cached:
            return cached.truncate_evidence()
    runner = get_runner(check_id)
    if not runner:
        return CheckResult(
            check_id=check_id,
            target=target["operator_id"],
            status="unknown",
            latency_ms=0,
            summary=f"unknown check_id {check_id!r}",
        )
    result: CheckResult = await runner(target, probe)
    result.truncate_evidence()
    await cache.set_cached(result)
    audit.emit_probe(
        target=target["operator_id"],
        check_id=check_id,
        status=result.status,
        summary=result.summary,
        actor_email=actor,
    )
    return result


def _aggregate_status(statuses: list[str]) -> str:
    if not statuses:
        return "unknown"
    if "fail" in statuses:
        return "down"
    if "warn" in statuses:
        return "degraded"
    # Treat 'unknown' as neutral: as long as we have at least one 'ok'
    # signal and no fail/warn, the target is healthy.
    if any(s == "ok" for s in statuses):
        return "healthy"
    return "unknown"


# ─── config viewer ───────────────────────────────────────────────────────


@router.get("/config/{target_id}", summary="Read masked config slices for a target")
async def get_config(
    target_id: str,
    sections: str = "docker,env,nginx,spire,partner_tegs",
    db: AsyncSession = Depends(get_db),
) -> dict:
    target = await get_target(db, target_id)
    if not target:
        raise HTTPException(status_code=404, detail=f"target {target_id!r} not found")
    requested = {s.strip() for s in sections.split(",") if s.strip()}
    probe = get_probe()
    out: dict[str, Any] = {"target": target_id}
    if "docker" in requested:
        out["docker"] = await config_reader.read_docker_section(target, probe)
    if "env" in requested:
        out["env"] = await config_reader.read_env_section(target, probe, role="registry")
    if "nginx" in requested:
        out["nginx"] = await config_reader.read_nginx_section(target, probe)
    if "spire" in requested:
        out["spire"] = await config_reader.read_spire_section(target, probe)
    if "partner_tegs" in requested:
        out["partner_tegs"] = await config_reader.read_partner_tegs(target, probe)
    return out


# ─── remediation actions ─────────────────────────────────────────────────


@router.get("/actions", summary="List available remediation actions")
async def list_actions() -> dict:
    out = []
    for action_id in action_module.known_action_ids():
        entry = action_module.get_action(action_id)
        if entry:
            out.append(
                {
                    "action_id": action_id,
                    "description": entry["description"],
                    "destructive": entry["destructive"],
                    "post_check": entry["post_check"],
                    "requires_confirmation": True,
                }
            )
    return {"actions": out, "count": len(out)}


@router.post("/actions/{action_id}", summary="Run a remediation action against a target")
async def invoke_action(
    action_id: str,
    request: ActionRequest,
    current_admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    target = await get_target(db, request.target)
    if not target:
        raise HTTPException(status_code=404, detail=f"target {request.target!r} not found")
    entry = action_module.get_action(action_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"unknown action {action_id!r}")

    probe = get_probe()
    result = await action_module.run_action(
        action_id=action_id,
        target=target,
        probe=probe,
        dry_run=request.dry_run,
        actor=current_admin.email,
    )

    # Re-run the triggering check so the UI can immediately reflect outcome.
    triggered: Optional[CheckResult] = None
    post_check = entry.get("post_check")
    if post_check and not request.dry_run:
        await cache.invalidate(post_check, target["operator_id"])
        triggered = await _run_one(
            check_id=post_check,
            target=target,
            probe=probe,
            force=True,
            actor=current_admin.email,
        )
        result.triggered_check = triggered

    return result.model_dump(mode="json")


# Re-export types so tests can import from this module directly

# ── §CCFIX (2026-07-28) — PROBE HISTORY ────────────────────────────────────────
# The Commander asked for "a history persistent for the drift runs so we can actually debug
# this monitoring". It turned out the history was ALREADY being written and simply never
# surfaced: services/diagnostics/audit.py::emit_probe has been emitting a CommandCenterProbe
# event for every single check execution since 2026-04-18 (2,897 events at the time of
# writing). So this is a READ endpoint over the existing immutable ledger — no new table, no
# migration, and three months of retrospective history available immediately.
#
# It also answers "i reran the drift scans, different outcome again": `flapping` groups by
# (check_id, target) and reports every pair that produced more than one distinct status in the
# window. That is the difference between "this check is failing" and "this check is unstable",
# which is exactly what was impossible to tell from a single live run.
@router.get("/history", summary="Probe history from the event ledger (drift/flap debugging)")
async def probe_history(
    hours: int = 72,
    check_id: Optional[str] = None,
    target: Optional[str] = None,
    limit: int = 2000,
    admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
) -> dict[str, Any]:
    """Recent CommandCenterProbe events + a per-(check,target) stability summary."""
    import os as _os
    from collections import defaultdict as _dd
    import httpx as _httpx
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz

    es_url = _os.environ.get("EVENT_STORE_URL", "http://event-store:8200")
    key = _os.environ.get("EVENT_STORE_INTERNAL_KEY", "")
    headers = {"X-Internal-Key": key} if key else {}
    hours = max(1, min(int(hours or 72), 24 * 30))
    limit = max(1, min(int(limit or 2000), 10000))

    events: list = []
    try:
        # EVENT_STORE_URL is https://nginx-event-store:8443 — mTLS behind SPIRE, so a plain
        # client fails CERTIFICATE_VERIFY_FAILED. get_httpx_verify() is the project's helper
        # for exactly this (same one whose missing import caused two silent NameErrors today).
        from agentvault_registry.es_ssl_helper import get_httpx_verify
        async with _httpx.AsyncClient(timeout=8.0, verify=get_httpx_verify()) as client:
            r = await client.get(
                f"{es_url}/api/v1/events/",
                params={"event_type": "CommandCenterProbe", "limit": limit},
                headers=headers,
            )
            if r.status_code == 200:
                events = r.json() or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("[diag-history] EventStore read failed: %s", exc)
        # Honest empty result — never a fabricated "all clear".
        return {"available": False, "error": str(exc)[:200], "runs": [], "flapping": []}

    cutoff = _dt.now(_tz.utc) - _td(hours=hours)
    rows = []
    for ev in events:
        d = ev.get("data") or {}
        ts = ev.get("timestamp") or ev.get("created_at") or ""
        try:
            when = _dt.fromisoformat(str(ts).replace("Z", "+00:00"))
            if when < cutoff:
                continue
        except Exception:  # noqa: BLE001
            when = None
        cid, tgt = d.get("check_id"), d.get("target") or ev.get("aggregate_id")
        if check_id and cid != check_id:
            continue
        if target and tgt != target:
            continue
        rows.append({
            "at": ts, "check_id": cid, "target": tgt,
            "status": d.get("status"), "summary": d.get("summary"),
        })

    seen: dict = _dd(list)
    for r_ in rows:
        seen[(r_["check_id"], r_["target"])].append(r_)
    flapping = []
    for (cid, tgt), items in seen.items():
        statuses = [i["status"] for i in items]
        distinct = sorted({s for s in statuses if s})
        if len(distinct) > 1:
            ordered = sorted(items, key=lambda i: i["at"] or "")
            flapping.append({
                "check_id": cid, "target": tgt, "runs": len(items),
                "distinct_statuses": distinct,
                "transitions": sum(
                    1 for a, b in zip(ordered, ordered[1:]) if a["status"] != b["status"]
                ),
                "latest": ordered[-1]["status"] if ordered else None,
            })
    flapping.sort(key=lambda f: (-f["transitions"], -f["runs"]))
    return {
        "available": True,
        "window_hours": hours,
        "source": "eventstore:CommandCenterProbe",
        "total_events_scanned": len(events),
        "runs_in_window": len(rows),
        "distinct_pairs": len(seen),
        "flapping_pairs": len(flapping),
        "flapping": flapping[:100],
        "runs": rows[:500],
    }


__all__ = [
    "router",
    "CheckResult",
    "TargetSummary",
    "ActionResult",
]
