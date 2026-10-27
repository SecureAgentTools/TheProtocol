"""§TESTBED (2026-09-19): the MCP tester view provisions this frame's SANDBOX through the frame runner.

His words 2026-09-19: "the sandbox provisioning should be also in the frontend mcp-tester view. there should be options
like 1 frame 2 federated frames for federation suite and a cloud operator all provisioned thru the proper lanes so the
tests will make sense. so just options to pick and you can see progress. and possible errors that would be already
enough." and "only kit sandbox for now".

A kit frame's registry mounts the runner's OPERATOR socket (never the full one). Where the runner's policy offers
sandboxes it serves the sandbox ops there, each for the calling frame only: the runner names the caller by the container
the call came from, never by the name in the request. The work is the export's own: frame-sandbox.py runs frame-up for
each sandbox, frame-federate for a pair (the second sandbox's admin approving through its own admin API) and each cloud
operator through its sandbox's own admin API, the way any operator joins a frame. Each sandbox then runs the MCP tester
against ITSELF, from its own console.

This router authenticates (admin_platform, the tester view's own flag), audits every act and every refusal to
security_audit_logs (a password never), and passes one request per route. A registry with no runner reachable, or a
runner that offers no sandboxes, answers `available: false` with the reason, so the view can say it rather than show an
empty panel.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, StrictBool
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry import security
from agentvault_registry.core.client_ip import effective_client_ip
from agentvault_registry.core.frame_slug import frame_slug
from agentvault_registry.database import get_db
from agentvault_registry.services import frame_runner_client as runner
from agentvault_registry.services.admin_audit import log_admin_action

logger = logging.getLogger(__name__)

platform_admin = security.require_admin_flag("admin_platform")

router = APIRouter(prefix="/api/v1/admin/mcp-tester/sandbox", tags=["Admin: MCP tester sandbox"])

JOB_FIELDS = ("id", "op", "name", "state", "created", "ended", "exit_code", "request")


class SandboxRequest(BaseModel):
    """What the panel offers: one sandbox (the lifecycle sweep) or two federated ones (the federation suite too), with or
    without a cloud operator on each. The runner owns every rule beyond the shape."""

    model_config = ConfigDict(extra="forbid")

    frames: Literal[1, 2] = 1
    operators: StrictBool = False


class RevealRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    which: Literal["a", "b"] = "a"


def _job(record: Any) -> Optional[Dict[str, Any]]:
    return {k: record.get(k) for k in JOB_FIELDS} if isinstance(record, dict) else None


async def _audit(db: AsyncSession, request: Request, admin: Any, action: str, target_id: str, *, outcome: str = "success",
                 severity: str = "warning", details: Optional[Dict[str, Any]] = None, error_message: Optional[str] = None) -> None:
    await log_admin_action(db, action=f"mcp_tester_sandbox.{action}", actor_id=str(getattr(admin, "id", "") or ""),
                           actor_ip=effective_client_ip(request), target_type="frame", target_id=target_id,
                           outcome=outcome, severity=severity, details=details or {}, error_message=error_message)


async def _act(db: AsyncSession, request: Request, admin: Any, action: str, op: str, *, details: Optional[Dict[str, Any]] = None,
               **fields: Any) -> Any:
    """An act: the runner's answer; a refusal or a failure is audited before it becomes the HTTP error."""
    frame = frame_slug()
    try:
        return await runner.call(op, timeout=runner.SHORT_TIMEOUT_S, frame=frame, **fields)
    except runner.RunnerRefused as exc:
        await _audit(db, request, admin, action, frame, outcome="refused", details=details, error_message=str(exc)[:500])
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"refused: {exc}")
    except runner.RunnerUnavailable as exc:
        await _audit(db, request, admin, action, frame, outcome="failure", details=details, error_message=str(exc)[:500])
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"runner unavailable: {exc}")
    except runner.RunnerError as exc:
        logger.error("[TESTBED] frame runner error on %s: %s", op, exc)
        await _audit(db, request, admin, action, frame, outcome="failure", details=details, error_message=str(exc)[:500])
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"runner error: {exc}")


@router.get("")
async def sandbox_status(admin: Any = Depends(platform_admin)) -> Dict[str, Any]:
    """This frame's sandboxes, the last sandbox job and its last event, the topologies with their memory estimates and
    the host's headroom; or `available: false` and why (no runner reachable, sandboxes not offered, this frame IS a
    sandbox)."""
    frame = frame_slug()
    try:
        result = await runner.call("sandbox_status", timeout=runner.SHORT_TIMEOUT_S, frame=frame)
    except runner.RunnerUnavailable as exc:
        return {"available": False, "frame": frame, "reason": "no_runner", "why": str(exc)}
    except runner.RunnerRefused as exc:
        why = str(exc)
        # a sandbox's own console: the runner refuses it by name ("<frame> is itself the sandbox of <parent>"), and the
        # view says where it stands instead of repeating the refusal (the one place that sentence is parsed)
        m = re.search(r"is itself the sandbox of ([a-z][a-z0-9-]*)", why)
        if m:
            return {"available": False, "frame": frame, "reason": "is_sandbox", "parent": m.group(1), "why": why}
        return {"available": False, "frame": frame, "reason": "refused", "why": why}
    except runner.RunnerError as exc:
        logger.error("[TESTBED] frame runner error on sandbox_status: %s", exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"runner error: {exc}")
    result = dict(result or {})
    result["job"] = _job(result.get("job"))
    return {"available": True, **result}


@router.post("")
async def sandbox_up(body: SandboxRequest, request: Request, db: AsyncSession = Depends(get_db),
                     admin: Any = Depends(platform_admin)) -> Dict[str, Any]:
    """Start the sandbox job. It runs on the host, minutes long; the view follows it through /jobs/{id}/events."""
    details = {"frames": body.frames, "operators": body.operators}
    result = await _act(db, request, admin, "up", "sandbox_up", details=details, frames=body.frames, operators=body.operators)
    job = _job((result or {}).get("job"))
    await _audit(db, request, admin, "up", frame_slug(), details={**details, "job_id": (job or {}).get("id")})
    return {"started": bool((result or {}).get("started")), "job": job}


@router.post("/teardown")
async def sandbox_down(request: Request, db: AsyncSession = Depends(get_db), admin: Any = Depends(platform_admin)) -> Dict[str, Any]:
    """Remove this frame's sandboxes: their operators through their own admin API, then each sandbox (frame-down)."""
    result = await _act(db, request, admin, "teardown", "sandbox_down")
    job = _job((result or {}).get("job"))
    await _audit(db, request, admin, "teardown", frame_slug(), details={"job_id": (job or {}).get("id")})
    return {"started": bool((result or {}).get("started")), "job": job}


@router.get("/jobs/{job_id}/events")
async def sandbox_events(job_id: str = Path(..., pattern=r"^[0-9a-f]{16}$"), after: int = Query(0, ge=0, le=1_000_000),
                         admin: Any = Depends(platform_admin)) -> Dict[str, Any]:
    frame = frame_slug()
    try:
        result = await runner.call("sandbox_events", timeout=runner.SHORT_TIMEOUT_S, frame=frame, job_id=job_id, after=after)
    except runner.RunnerRefused as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"refused: {exc}")
    except runner.RunnerUnavailable as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"runner unavailable: {exc}")
    except runner.RunnerError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"runner error: {exc}")
    result = dict(result or {})
    result["job"] = _job(result.get("job"))
    return result


@router.post("/reveal")
async def sandbox_reveal(body: RevealRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db),
                         admin: Any = Depends(platform_admin)) -> Dict[str, Any]:
    """The admin login of one sandbox, so the person who provisioned it can open its console and its tester. The audit
    row names the sandbox and the address, never the password; the answer is not cached."""
    result = await _act(db, request, admin, "reveal", "sandbox_reveal", details={"which": body.which}, which=body.which)
    await _audit(db, request, admin, "reveal", frame_slug(), details={"which": body.which, "sandbox": result.get("sandbox"),
                                                                      "email": result.get("email")})
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return {"sandbox": result.get("sandbox"), "console": result.get("console"), "email": result.get("email"),
            "password": result.get("password")}
