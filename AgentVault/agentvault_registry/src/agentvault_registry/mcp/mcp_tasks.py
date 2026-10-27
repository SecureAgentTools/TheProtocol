"""
MCP async Tasks (spec 2025-11-25, experimental) — durable task-augmented
tools/call for the genuinely long-running tools (tool_metadata.task_tools).

Wire shape implemented (verified against the 2025-11-25 tasks spec):
  * tools/call with params.task={ttl} → CreateTaskResult {"task": {...}}
    (+ _meta "io.modelcontextprotocol/model-immediate-response").
  * tasks/get {taskId} → Task object (working|completed|failed|cancelled).
  * tasks/result {taskId} → the underlying CallToolResult, blocking until
    terminal (long-poll bounded by the request lifetime), stamped with
    _meta "io.modelcontextprotocol/related-task".
  * tasks/list {cursor?} → this requestor's tasks (auth-context bound).
  * tasks/cancel {taskId} → sticky cancelled (later completion is discarded).

Storage: shared Redis (background_tasks.leader.get_redis) so any gunicorn
worker can serve polls for a task executing in another worker; falls back to
an in-process dict when Redis is absent (single-worker dev only). Tasks are
BOUND to an authorization context (sha-256 of the bearer credential) — a
different credential polling the same taskId sees "not found", per spec
security requirements. Task IDs are uuid4 (122-bit, unguessable).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

DEFAULT_TTL_MS = 5 * 60 * 1000
MAX_TTL_MS = 15 * 60 * 1000
POLL_INTERVAL_MS = 1500
_LIST_PAGE = 50
_IDX_CAP = 100  # most-recent tasks kept per requestor

TASKS_CAPABILITY = {"list": {}, "cancel": {}, "requests": {"tools": {"call": {}}}}
RELATED_TASK_META = "io.modelcontextprotocol/related-task"
IMMEDIATE_RESPONSE_META = "io.modelcontextprotocol/model-immediate-response"

_TERMINAL = ("completed", "failed", "cancelled")

# In-process fallback store (dev / no-Redis only)
_local: Dict[str, Dict[str, Any]] = {}
_local_idx: Dict[str, List[str]] = {}


def ctx_hash(token: Optional[str]) -> str:
    return hashlib.sha256((token or "anonymous").encode()).hexdigest()[:32]


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def _redis():
    try:
        from agentvault_registry.background_tasks.leader import get_redis
        return await get_redis()
    except Exception:
        return None


def _key(task_id: str) -> str:
    return f"mcp:task:{task_id}"


def _idx_key(ctx: str) -> str:
    return f"mcp:tasks:idx:{ctx}"


async def _store(rec: Dict[str, Any]) -> None:
    ttl_s = max(60, int(rec["ttl"] / 1000))
    r = await _redis()
    if r is not None:
        await r.set(_key(rec["taskId"]), json.dumps(rec, default=str), ex=ttl_s)
    else:
        rec["_expires"] = time.time() + ttl_s
        _local[rec["taskId"]] = rec


async def _load(task_id: str) -> Optional[Dict[str, Any]]:
    r = await _redis()
    if r is not None:
        raw = await r.get(_key(task_id))
        if raw is None:
            return None
        return json.loads(raw)
    rec = _local.get(task_id)
    if rec and rec.get("_expires", 0) < time.time():
        _local.pop(task_id, None)
        return None
    return rec


async def _index(ctx: str, task_id: str, ttl_s: int) -> None:
    r = await _redis()
    if r is not None:
        k = _idx_key(ctx)
        await r.lpush(k, task_id)
        await r.ltrim(k, 0, _IDX_CAP - 1)
        await r.expire(k, max(ttl_s, 24 * 3600))
    else:
        _local_idx.setdefault(ctx, []).insert(0, task_id)
        del _local_idx[ctx][_IDX_CAP:]


def task_public(rec: Dict[str, Any]) -> Dict[str, Any]:
    """The wire Task object — never leaks ctx or the stored result."""
    out = {
        "taskId": rec["taskId"],
        "status": rec["status"],
        "createdAt": rec["createdAt"],
        "lastUpdatedAt": rec["lastUpdatedAt"],
        "ttl": rec["ttl"],
        "pollInterval": rec.get("pollInterval", POLL_INTERVAL_MS),
    }
    if rec.get("statusMessage"):
        out["statusMessage"] = rec["statusMessage"]
    return out


async def create_task(ctx: str, ttl_ms: Optional[int], tool_name: str) -> Dict[str, Any]:
    ttl = min(int(ttl_ms or DEFAULT_TTL_MS), MAX_TTL_MS)
    now = _now_iso()
    rec = {
        "taskId": str(uuid.uuid4()),
        "status": "working",
        "statusMessage": f"{tool_name} accepted; execution in progress.",
        "createdAt": now,
        "lastUpdatedAt": now,
        "ttl": ttl,
        "pollInterval": POLL_INTERVAL_MS,
        "ctx": ctx,
        "tool": tool_name,
        "result": None,
    }
    await _store(rec)
    await _index(ctx, rec["taskId"], int(ttl / 1000))
    return rec


async def finish_task(task_id: str, status: str, result: Optional[Dict[str, Any]] = None,
                      status_message: Optional[str] = None) -> None:
    rec = await _load(task_id)
    if rec is None:
        return
    if rec["status"] == "cancelled":
        return  # cancellation is sticky per spec — discard late completion
    rec["status"] = status
    rec["lastUpdatedAt"] = _now_iso()
    if status_message:
        rec["statusMessage"] = status_message
    elif status == "completed":
        rec["statusMessage"] = "Completed."
    if result is not None:
        rec["result"] = result
    await _store(rec)


async def get_task(task_id: str, ctx: str) -> Optional[Dict[str, Any]]:
    rec = await _load(task_id)
    if rec is None or rec.get("ctx") != ctx:
        return None  # unknown OR foreign context — indistinguishable by design
    return rec


async def cancel_task(task_id: str, ctx: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    rec = await get_task(task_id, ctx)
    if rec is None:
        return None, "Failed to cancel task: Task not found"
    if rec["status"] in _TERMINAL:
        return None, f"Cannot cancel task: already in terminal status '{rec['status']}'"
    rec["status"] = "cancelled"
    rec["statusMessage"] = "The task was cancelled by request."
    rec["lastUpdatedAt"] = _now_iso()
    await _store(rec)
    return rec, None


async def wait_result(task_id: str, ctx: str, max_wait_s: float = 540.0) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Block (poll the shared store) until the task is terminal, then return
    the record. Bounded by max_wait_s to stay inside the HTTP request budget;
    on bound-hit the client simply re-invokes tasks/result (spec-compatible:
    the call remains a blocking retrieval, we just chunk the blocking)."""
    deadline = time.monotonic() + max_wait_s
    while True:
        rec = await get_task(task_id, ctx)
        if rec is None:
            return None, "Failed to retrieve task: Task not found"
        if rec["status"] in _TERMINAL:
            return rec, None
        if time.monotonic() >= deadline:
            return None, "Task still executing — call tasks/result again (or poll tasks/get)"
        await asyncio.sleep(0.5)


async def list_tasks(ctx: str, cursor: Optional[str]) -> Tuple[Dict[str, Any], Optional[str]]:
    try:
        offset = int(cursor) if cursor else 0
        if offset < 0:
            raise ValueError
    except (TypeError, ValueError):
        return {}, "Invalid cursor"
    r = await _redis()
    if r is not None:
        ids = await r.lrange(_idx_key(ctx), offset, offset + _LIST_PAGE - 1)
        ids = [i.decode() if isinstance(i, bytes) else i for i in ids]
        more = (await r.llen(_idx_key(ctx))) > offset + _LIST_PAGE
    else:
        all_ids = _local_idx.get(ctx, [])
        ids = all_ids[offset:offset + _LIST_PAGE]
        more = len(all_ids) > offset + _LIST_PAGE
    tasks: List[Dict[str, Any]] = []
    for tid in ids:
        rec = await _load(tid)
        if rec is not None and rec.get("ctx") == ctx:
            tasks.append(task_public(rec))
    out: Dict[str, Any] = {"tasks": tasks}
    if more:
        out["nextCursor"] = str(offset + _LIST_PAGE)
    return out, None


def spawn(task_id: str, coro_factory) -> None:
    """Run the underlying tool call in the background; terminal-state the
    task from its outcome. isError=true in the CallToolResult → failed,
    matching the spec's tool-call failure rule."""

    async def _runner():
        try:
            result = await coro_factory()
            failed = bool(isinstance(result, dict) and result.get("isError"))
            await finish_task(
                task_id,
                "failed" if failed else "completed",
                result=result,
                status_message="Tool reported an error." if failed else None,
            )
        except Exception as exc:  # noqa: BLE001 — task boundary
            logger.warning("MCP task %s failed: %r", task_id, exc)
            try:
                await finish_task(task_id, "failed", status_message=f"Execution failed: {exc}")
            except Exception:
                pass

    asyncio.create_task(_runner())
