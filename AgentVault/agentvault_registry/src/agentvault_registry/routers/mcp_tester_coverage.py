"""V0663 (order gwo_0b31c0b849ebd207102d8bf4, his suggestion 7): the MCP tester's coverage, per tool and per target.

From the latest completed run the tester holds for each target (a target is one suite against one target URL,
`mcp_tester._suite_key`; the federation suite has no tool rows and is none), each tool the run lists is one of
  failed        a row of the tool failed: said first, a failure is never folded into coverage
  success       a passing 2xx anywhere in the run (its own row, an `admin_effect:` or `earned:` row, a probe family)
  refusal_only  it passed on a refusal alone: the router's own rule (`_refusal_only`, recomputed for a run before V0636)
                and the flag a run since V0636 stores on the row, with the row's reason (`refusal_only_reason`: the
                declared by-design reason where the target's flow names one)
  not_measured  nothing of it passed (skipped, switched off), with the reason the row gives
A tool a target does not list is `not_listed` there and counted nowhere. Counts are per target and never summed: the
same tool is refusal-only on one target and earned on another (sessionlogs2026/CLASSIFICATION_2026-11-13_MCP_REFUSAL_ONLY.md),
so a sum would count it twice or hide it. A newer run of a target that is still in flight (or failed) is named beside the
run that was read. Only a read of what the tester stored; no tool is called.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from fastapi import APIRouter, Security

from .. import models, security
from .mcp_tester import (
    API_TEST_TARGET_URL, _DEFAULT_FLOW_NAME, _MAX_HISTORY, _SUPPORTED_FLOWS, _is_2xx, _list_recent_run_ids, _load_list,
    _load_run_meta, _passing, _refusal_only, _require_admin, _suite_key, _tool_base, refusal_only_reason,
)

router = APIRouter(prefix="/admin/mcp-tester", tags=["MCP Tester"])

CLASS_RANK = {"failed": 0, "refusal_only": 1, "not_measured": 2, "success": 3, "not_listed": 4}   # the worst first
_REASON_MAX = 400
_FALLBACK_RUNS = 3   # a completed run whose rows expired: read the next older completed run of the same target


def _clip(s: str) -> str:
    s = " ".join(str(s or "").split())
    return s if len(s) <= _REASON_MAX else s[:_REASON_MAX - 1] + "…"


def _is_tool_row(r: Any) -> bool:
    return isinstance(r, dict) and str(r.get("tool") or "").startswith("theprotocol_")


def _unmeasured_reason(own: Sequence[Dict[str, Any]]) -> str:
    for r in own:
        if r.get("switched_off"):
            why = f"switched off on this target ({r['switched_off']})"
            return _clip(f"{why}: {r['skip_reason']}" if r.get("skip_reason") else why)
    for r in own:
        if r.get("skip_reason"):
            return _clip(r["skip_reason"])
    return "nothing of it passed in this run, and its rows give no reason"


def classify_run(rows: Optional[Sequence[Dict[str, Any]]]) -> Dict[str, Dict[str, Any]]:
    """Each tool the run lists (its `theprotocol_` rows), one class, the reason the run gives, its status and tier."""
    rows = [r for r in (rows or []) if isinstance(r, dict)]
    own_rows: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        if _is_tool_row(r):
            own_rows.setdefault(_tool_base(r.get("tool")), []).append(r)
    succeeded = {_tool_base(r.get("tool")) for r in rows if _passing(r) and _is_2xx(r.get("status"))}
    failed: Dict[str, str] = {}
    for r in rows:
        if not r.get("healthy") and not r.get("skipped"):
            label = str(r.get("tool") or "")
            err = r.get("error") or f"answered {r.get('status')}"
            failed.setdefault(_tool_base(label), _clip(err if _is_tool_row(r) else f"{label}: {err}"))
    recomputed = {_tool_base(rows[i].get("tool")) for i in _refusal_only(rows)}   # a run before V0636 has no flag

    out: Dict[str, Dict[str, Any]] = {}
    for tool, own in own_rows.items():
        flagged = next((r for r in own if r.get("refusal_only")), None)
        if tool in failed:
            cls, reason = "failed", failed[tool]
        elif tool in succeeded:
            cls, reason = "success", ""
        elif flagged is not None or tool in recomputed:
            cls = "refusal_only"
            subject = flagged or own[0]
            reason = _clip(subject.get("skip_reason") if flagged and flagged.get("skip_reason") else refusal_only_reason(subject))
        else:
            cls, reason = "not_measured", _unmeasured_reason(own)
        out[tool] = {"class": cls, "reason": reason, "status": (flagged or own[0]).get("status"),
                     "tier": next((r.get("tier") for r in own if r.get("tier")), "")}
    return out


def pick_runs(metas: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The latest completed MCP run per target (metas newest first, as the index answers), with the older completed
    runs of the same target to fall back on, and the newest run that is not completed when it is newer than the one
    read. A run with no summary yet (queued, running) names the tester's own target."""
    chosen: Dict[str, Dict[str, Any]] = {}
    newer: Dict[str, Dict[str, Any]] = {}
    for m in metas or []:
        if not isinstance(m, dict):
            continue
        flow = str(m.get("flow_name") or "")
        if not flow.startswith("flow_mcp_lifecycle"):
            continue
        summary = m.get("summary") if isinstance(m.get("summary"), dict) else {}
        target = str(summary.get("target") or API_TEST_TARGET_URL)
        key = _suite_key(flow, target)
        if m.get("status") != "completed":
            if key not in chosen:
                newer.setdefault(key, {"run_id": m.get("run_id"), "status": m.get("status"), "started_at": m.get("started_at")})
            continue
        entry = {
            "key": key,
            "run_id": m.get("run_id"),
            "flow_name": flow,
            "label": str(m.get("flow_label") or _SUPPORTED_FLOWS.get(flow, flow)),
            "target": key.split("@", 1)[1],
            "started_at": m.get("started_at"),
            "finished_at": m.get("finished_at"),
            "target_counts": summary.get("target_counts"),
            "pass_pct": summary.get("pass_pct"),
        }
        if key in chosen:
            if len(chosen[key]["fallbacks"]) < _FALLBACK_RUNS:
                chosen[key]["fallbacks"].append(entry)
            continue
        chosen[key] = {**entry, "newer": newer.get(key), "fallbacks": []}
    return sorted(chosen.values(), key=lambda e: (e["flow_name"] != _DEFAULT_FLOW_NAME, -(e.get("started_at") or 0)))


def coverage_view(pairs: Sequence[Tuple[Dict[str, Any], Sequence[Dict[str, Any]]]]) -> Dict[str, Any]:
    """Per target its counts (never summed), per tool its class on each target (`not_listed` where a target does not
    list it), the worst first."""
    targets: List[Dict[str, Any]] = []
    per_tool: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for picked, rows in pairs:
        classes = classify_run(rows)
        counts = {"tools": len(classes), "failed": 0, "success": 0, "refusal_only": 0, "not_measured": 0}
        for tool, c in classes.items():
            counts[c["class"]] += 1
            per_tool.setdefault(tool, {})[picked["key"]] = c
        targets.append({k: v for k, v in picked.items() if k != "fallbacks"} | {"counts": counts})
    keys = [t["key"] for t in targets]
    tools = []
    for tool, seen in per_tool.items():
        by_target = {k: ({kk: vv for kk, vv in seen[k].items() if kk != "tier"} if k in seen else {"class": "not_listed"})
                     for k in keys}
        tools.append({"tool": tool, "tier": next((c["tier"] for c in seen.values() if c.get("tier")), ""),
                      "worst": min((c["class"] for c in by_target.values()), key=CLASS_RANK.__getitem__),
                      "by_target": by_target})
    tools.sort(key=lambda t: (CLASS_RANK[t["worst"]], t["tool"].lower()))
    return {"targets": targets, "tools": tools}


async def _load_metas(limit: int = _MAX_HISTORY) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for run_id in await _list_recent_run_ids(limit):
        meta = await _load_run_meta(run_id)
        if meta:
            out.append(meta)
    return out


async def _load_rows(run_id: str) -> List[Dict[str, Any]]:
    return await _load_list(run_id, "results")


@router.get("/coverage", summary="Per tool, per target: success, refusal only, not measured or failed (latest runs)")
async def coverage(
    current_developer: models.Developer = Security(security.get_current_developer),
) -> Dict[str, Any]:
    _require_admin(current_developer)
    pairs: List[Tuple[Dict[str, Any], List[Dict[str, Any]]]] = []
    for picked in pick_runs(await _load_metas()):
        for candidate in [picked, *picked.get("fallbacks", [])]:
            rows = await _load_rows(candidate["run_id"])
            if rows:
                read = picked if candidate is picked else {**candidate, "newer": picked.get("newer"),
                                                           "rows_expired": picked["run_id"]}
                pairs.append((read, rows))
                break
    view = coverage_view(pairs)
    view["note"] = None if view["targets"] else (
        "The tester holds no completed MCP run with its rows: run a sweep (the federation suite has no tool rows).")
    return view
