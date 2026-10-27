"""§MCPTEST30 (V0555, 2026-10-03, agentvault2-09): the console suite's history, apart from the MCP tester's.

The console suite (§FESUITE: Playwright lifecycles over this console, desktop and phone, against a sandbox frame) runs on
the host (scripts/fesuite/run.py), not from a console, so nothing here starts a run: the runner RECORDS each run it made,
here, and the console-suite page reads it. His word 2026-10-03: "make sure to make the frontend suite runs also visible.
if it makes sense make a new test page for it".

Why not the MCP tester's history: that history holds 60 runs in all (MCP_TESTER_MAX_HISTORY) and the nightly fills it
(EU held 60 of 60 on 2026-10-03), while the suite is run many times a day, mostly a few lifecycles at a time (a wording
check, one page): recorded there, a day of those would push the MCP runs out. So its own index, its own cap, and a
record shaped for its own question (which lifecycle, on which screen, did what) rather than the MCP tester's tiles.

    POST /admin/console-suite/runs          record one run the runner made (admin; idempotent on run_id)
    GET  /admin/console-suite/runs          the newest runs, metadata only (admin)
    GET  /admin/console-suite/runs/{id}     one run: summary, scope, lifecycles, step rows, lists, log (admin)

A record is DATA, never code or markup: every field is typed and bounded here (strings cut, lists capped, unknown keys
dropped), so a runner bug cannot store something the page cannot draw. Like the MCP tester's, the store is the frame's
Redis, a cache (a restart empties it): the runner keeps every run on disk and `scripts/fesuite/record_history.py`
records them again.
"""
from __future__ import annotations

import datetime as _dt
import json
import logging
import math
import os
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request, Security

from agentvault_registry import models, security
from agentvault_registry.background_tasks.leader import get_redis

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/console-suite", tags=["Console Suite"])

FLOW_NAME = "flow_playwright_console_lifecycles"
_REDIS_PREFIX = "console_suite"
_MAX_HISTORY = int(os.getenv("CONSOLE_SUITE_MAX_HISTORY", "120"))
# the newest whole-suite runs (scope.full) are never the ones the cap drops (V0558): on 2026-10-03 EU held 120 of 120 runs
# and not one whole-suite run, because a morning of one-lifecycle wording checks had pushed every one of them out
_KEEP_WHOLE = int(os.getenv("CONSOLE_SUITE_KEEP_WHOLE", "20"))
_RUN_TTL = int(os.getenv("CONSOLE_SUITE_RUN_TTL_S", str(365 * 86400)))
# a whole-suite run measured 2026-10-02 is 270 KB as the runner writes it (628 step rows); the cap leaves room for a suite
# twice that size and refuses a body nobody should be sending
_MAX_BODY_BYTES = int(os.getenv("CONSOLE_SUITE_MAX_BODY_BYTES", str(4 * 1024 * 1024)))
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{3,79}$")

_MAX_RESULTS = 3000
_MAX_LIFECYCLES = 300
_MAX_LIST = 1000
_MAX_LOG = 400
_LISTS = ("bug_finds", "hard_fails", "expected_reds", "skipped", "policy_denied")


def _rk(*parts: str) -> str:
    return ":".join((_REDIS_PREFIX, *parts))


def _require_admin(dev: models.Developer) -> models.Developer:
    if not dev or not security.admin_credential(dev):   # §POCKETPAIR: a scoped key is not admin
        raise HTTPException(status_code=403, detail="The console suite's history requires admin")
    return dev


async def _redis():
    r = await get_redis()
    if r is None:
        raise HTTPException(status_code=503, detail="The console suite's history requires Redis (REDIS_URL not configured)")
    return r


def _s(v: Any, n: int) -> Optional[str]:
    """A string field, cut to n characters; anything else that is not None is written as text."""
    if v is None:
        return None
    t = v if isinstance(v, str) else json.dumps(v, default=str) if isinstance(v, (dict, list)) else str(v)
    return t if len(t) <= n else t[: n - 1] + "…"


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v) if math.isfinite(float(v)) else None
    return None


def _int(v: Any) -> Optional[int]:
    f = _num(v)
    return int(f) if f is not None else None


def _epoch(v: Any) -> Optional[float]:
    """The runner writes ISO text; the MCP tester's history keeps Unix seconds. This history keeps seconds too."""
    if isinstance(v, str) and v:
        try:
            return _dt.datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return _num(v)


def _scalars(d: Any, *, max_keys: int = 60, max_str: int = 200) -> Dict[str, Any]:
    """A flat object of numbers, booleans, short strings and None; nested values are dropped."""
    out: Dict[str, Any] = {}
    if not isinstance(d, dict):
        return out
    for k, v in list(d.items())[:max_keys]:
        if not isinstance(k, str) or len(k) > 60:
            continue
        if v is None or isinstance(v, bool):
            out[k] = v
        elif isinstance(v, (int, float)):
            f = _num(v)
            if f is not None:
                out[k] = v
        elif isinstance(v, str):
            out[k] = _s(v, max_str)
    return out


def _entry(x: Any) -> Optional[Dict[str, Any]]:
    """One entry of a run's lists ({tool, error | reason}); the MCP tester's page reads `.tool` of each."""
    if isinstance(x, dict) and isinstance(x.get("tool"), str):
        return {"tool": _s(x["tool"], 200), "error": _s(x.get("error"), 1500), "reason": _s(x.get("reason"), 800)}
    if isinstance(x, str) and x:            # an older reporter wrote "tool: text"
        tool, _, text = x.partition(": ")
        return {"tool": _s(tool, 200), "error": _s(text, 1500) or None, "reason": None}
    return None


def _row(x: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(x, dict) or not isinstance(x.get("tool"), str):
        return None
    return {
        "tool": _s(x["tool"], 200), "tier": _s(x.get("tier"), 40),
        "healthy": x.get("healthy") if isinstance(x.get("healthy"), bool) else None,
        "skipped": bool(x.get("skipped")), "status": _s(x.get("status"), 40), "elapsed": _num(x.get("elapsed")),
        "error": _s(x.get("error"), 1500), "skip_reason": _s(x.get("skip_reason"), 800),
        "response_excerpt": _s(x.get("response_excerpt"), 400), "kind": _s(x.get("kind"), 20),
    }


def _lifecycle(x: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(x, dict) or not isinstance(x.get("lifecycle"), str):
        return None
    cap = x.get("capture") if isinstance(x.get("capture"), dict) else {}
    unexpected = [_s(u, 300) for u in (cap.get("unexpected") or [])[:10] if u is not None] if isinstance(
        cap.get("unexpected"), list) else []
    capture = {k: _int(v) for k, v in cap.items() if isinstance(k, str) and _int(v) is not None and not isinstance(v, bool)}
    a11y = x.get("a11y")
    return {
        "lifecycle": _s(x["lifecycle"], 200), "project": _s(x.get("project"), 40), "status": _s(x.get("status"), 20),
        "duration_s": _num(x.get("duration_s")), "steps": _int(x.get("steps")),
        "capture": dict(capture, unexpected=unexpected),
        "a11y": _scalars(a11y, max_keys=20) if isinstance(a11y, dict) else None,
    }


def normalise(run: Dict[str, Any]) -> Dict[str, Any]:
    """The record this history keeps of one run, built field by field from what the runner sent (pure, unit-tested)."""
    rid = run.get("run_id")
    if not isinstance(rid, str) or not _RUN_ID.match(rid):
        raise ValueError("run_id: 4 to 80 characters of letters, digits and ._:- (the runner's fes-<stamp>-<hex>)")
    if run.get("flow_name") != FLOW_NAME:
        raise ValueError(f"flow_name: this history keeps the console suite's runs ({FLOW_NAME}) only")
    started = _epoch(run.get("started_at"))
    if started is None:
        raise ValueError("started_at: a time (ISO text or Unix seconds)")
    rec: Dict[str, Any] = {
        "run_id": rid, "flow_name": FLOW_NAME, "flow_label": _s(run.get("flow_label"), 120),
        "status": _s(run.get("status"), 32) or "completed", "error": _s(run.get("error"), 1500),
        "started_at": started, "finished_at": _epoch(run.get("finished_at")),
        "summary": _scalars(run.get("summary")), "scope": _scalars(run.get("scope"), max_keys=20),
        "lifecycles": [y for y in (_lifecycle(x) for x in (run.get("lifecycles") or [])[:_MAX_LIFECYCLES]) if y],
        "results": [y for y in (_row(x) for x in (run.get("results") or [])[:_MAX_RESULTS]) if y],
        "log_lines": [{"ts": _s(x.get("ts"), 40), "msg": _s(x.get("msg"), 500)}
                      for x in (run.get("log_lines") or [])[:_MAX_LOG] if isinstance(x, dict)],
    }
    for k in _LISTS:
        rec[k] = [y for y in (_entry(x) for x in (run.get(k) or [])[:_MAX_LIST]) if y]
    return rec


def meta_of(rec: Dict[str, Any]) -> Dict[str, Any]:
    """What the run list shows of a run (the page asks for the rest when it opens one)."""
    keep = ("run_id", "flow_name", "flow_label", "status", "error", "started_at", "finished_at", "summary", "scope")
    m = {k: rec.get(k) for k in keep}
    lcs = rec.get("lifecycles") or []
    m["lifecycle_names"] = sorted({str(x.get("lifecycle")) for x in lcs})[:60]
    m["projects"] = sorted({str(x.get("project")) for x in lcs if x.get("project")})
    return m


def _decode(v: Any) -> Optional[str]:
    if v is None:
        return None
    return v.decode() if isinstance(v, bytes) else str(v)


@router.post("/runs", summary="Record one console-suite run (the runner's; admin)")
async def record_run(
    request: Request,
    replace: bool = False,
    current_developer: models.Developer = Security(security.get_current_developer),
) -> Dict[str, Any]:
    _require_admin(current_developer)
    raw = await request.body()
    if len(raw) > _MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail=f"a run of {len(raw)} bytes is over this history's {_MAX_BODY_BYTES}")
    try:
        body = json.loads(raw)
    except ValueError:
        raise HTTPException(status_code=422, detail="the body is not JSON")
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="the body is one run (a JSON object)")
    try:
        rec = normalise(body)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    r = await _redis()
    rid = rec["run_id"]
    if not replace and await r.exists(_rk("run", rid)):
        return {"status": "exists", "run_id": rid}
    blob, meta = json.dumps(rec, separators=(",", ":")), json.dumps(meta_of(rec), separators=(",", ":"))
    await r.set(_rk("run", rid), blob, ex=_RUN_TTL)
    await r.set(_rk("meta", rid), meta, ex=_RUN_TTL)
    await r.zadd(_rk("runs", "index"), {rid: rec["started_at"]})
    total = await r.zcard(_rk("runs", "index"))
    dropped: List[str] = []
    if total > _MAX_HISTORY:
        dropped = await _evictions(r, int(total), int(total) - _MAX_HISTORY)
        if dropped:
            await r.zrem(_rk("runs", "index"), *dropped)
            await r.delete(*[_rk(kind, d) for d in dropped for kind in ("run", "meta")])
    logger.info("console suite: recorded run %s (%d B, %d step rows, %d lifecycle rows)%s", rid, len(blob),
                len(rec["results"]), len(rec["lifecycles"]), f"; dropped the oldest {len(dropped)}" if dropped else "")
    return {"status": "replaced" if replace else "recorded", "run_id": rid, "bytes": len(blob), "dropped": len(dropped)}


async def _evictions(r: Any, total: int, excess: int) -> List[str]:
    """The oldest runs past the cap, never one of the newest _KEEP_WHOLE whole-suite runs (scope.full true). A run whose
    metadata the cache let go counts as a part run (it can only be dropped). If every candidate is protected the history
    keeps more than the cap, by at most _KEEP_WHOLE."""
    ordered = [d for d in (_decode(x) for x in await r.zrange(_rk("runs", "index"), 0, total - 1)) if d]   # oldest first
    whole: List[str] = []
    for rid in ordered:
        raw = await r.get(_rk("meta", rid))
        try:
            m = json.loads(raw) if raw else {}
        except ValueError:
            m = {}
        if isinstance(m, dict) and isinstance(m.get("scope"), dict) and m["scope"].get("full") is True:
            whole.append(rid)
    protected = set(whole[-_KEEP_WHOLE:]) if _KEEP_WHOLE > 0 else set()
    return [d for d in ordered if d not in protected][:max(0, excess)]


@router.get("/runs", summary="The newest console-suite runs (admin)")
async def list_runs(
    limit: int = 60,
    current_developer: models.Developer = Security(security.get_current_developer),
) -> Dict[str, Any]:
    _require_admin(current_developer)
    r = await _redis()
    limit = max(1, min(int(limit), _MAX_HISTORY))
    ids = [d for d in (_decode(x) for x in await r.zrevrange(_rk("runs", "index"), 0, limit - 1)) if d]
    runs: List[Dict[str, Any]] = []
    gone: List[str] = []
    for rid in ids:
        m = _decode(await r.get(_rk("meta", rid)))
        if m is None:
            gone.append(rid)       # the cache let it go (TTL or eviction); the index forgets it too
            continue
        try:
            runs.append(json.loads(m))
        except ValueError:
            gone.append(rid)
    if gone:
        await r.zrem(_rk("runs", "index"), *gone)
    total = await r.zcard(_rk("runs", "index"))
    return {"runs": runs, "total": int(total or 0), "cap": _MAX_HISTORY}


@router.get("/runs/{run_id}", summary="One console-suite run (admin)")
async def get_run(
    run_id: str,
    current_developer: models.Developer = Security(security.get_current_developer),
) -> Dict[str, Any]:
    _require_admin(current_developer)
    if not _RUN_ID.match(run_id or ""):
        raise HTTPException(status_code=404, detail=f"run {run_id} not found")
    r = await _redis()
    blob = _decode(await r.get(_rk("run", run_id)))
    if blob is None:
        raise HTTPException(status_code=404, detail=f"run {run_id} not found (this history keeps {_MAX_HISTORY} runs)")
    return json.loads(blob)
