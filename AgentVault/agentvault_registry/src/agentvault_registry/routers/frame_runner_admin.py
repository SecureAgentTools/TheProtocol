"""§FRAMEPROV P3 (2026-09-13): the host frame runner, behind the platform admin flag.

His words 2026-09-13: "application ui is public. management/admin view is private needs platform admin flag"; the new
frame's admin credential is shown once; Start/Stop for frames the runner did not build retire. This router replaces
routers/frame_demo.py, whose launcher ran a privileged nsenter container through the docker socket: root on the host
behind admin_federation.

Every route passes one request to the runner (services/frame_runner_client.py). The runner validates, refuses and
executes; this router authenticates (admin_platform, mainframe only), writes every act to security_audit_logs (a
refusal too, the credential never), and forwards only what the admin view uses. A job's argv, pid and secrets path
stay on the host.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry import security
from agentvault_registry.core.client_ip import effective_client_ip
from agentvault_registry.core.mainframe_gate import require_mainframe_only
from agentvault_registry.database import get_db
from agentvault_registry.services import frame_runner_client as runner
from agentvault_registry.services.admin_audit import log_admin_action

logger = logging.getLogger(__name__)

# One dependency object, so every route asks the same flag and a test can replace exactly this gate.
platform_admin = security.require_admin_flag("admin_platform")

router = APIRouter(
    prefix="/api/v1/admin/frame-runner",
    tags=["Admin: frame runner"],
    dependencies=[Depends(require_mainframe_only)],
)

# ⚠ `refused` AND `reason` ARE WHAT MAKE A FAILED JOB READABLE. Without them the console had the fact of a
# failure and no way to show its cause: the reason lived only in the runner's stdout.log and this registry's own
# log, so Frame Management showed "failed 9s" with every step "not run" for a job that had extracted a bundle,
# updated SVID SANs, written the env and the markers, chowned the ACL and then failed at compose up.
# `refused` says WHICH (exit 3, nothing was written, safe to re-run); `reason` says WHAT. The runner redacts the
# reason at write time; this rail only carries it.
JOB_FIELDS = ("id", "op", "name", "state", "created", "ended", "exit_code", "request", "refused", "reason")
FRAME_FIELDS = ("name", "state", "stack_dir", "spec", "built_by_job", "created", "updated", "revealed_at")
# A transport bound that keeps a request well under the runner's 64 KB line; the rules themselves are the runner's.
TEXT_BOUND = 2000


class FrameSpec(BaseModel):
    """The runner's closed spec (SPEC_FIELDS in frame_runner.py). Shapes here; the runner owns every rule and refusal,
    so a name, a ticker or an image is judged in one place."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., max_length=TEXT_BOUND)
    frame_label: str = Field(..., max_length=TEXT_BOUND)
    ticker: str = Field(..., max_length=TEXT_BOUND)
    currency_name: str = Field(..., max_length=TEXT_BOUND)
    mint: StrictInt = 1_000_000
    theme: Literal["neural", "sovereign"] = "neural"
    description: str = Field(..., max_length=TEXT_BOUND)
    operator_label: str = Field(..., max_length=TEXT_BOUND)
    location_label: str = Field(..., max_length=TEXT_BOUND)
    lat: float
    lng: float
    website: str = Field("", max_length=TEXT_BOUND)
    registry_image: str = Field(..., max_length=TEXT_BOUND)
    teg_image: str = Field(..., max_length=TEXT_BOUND)


class ResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_step: str = Field(..., max_length=64)


def _pick(record: Any, fields: tuple) -> Optional[Dict[str, Any]]:
    if not isinstance(record, dict):
        return None
    return {key: record.get(key) for key in fields}


def _refused(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"refused: {exc}")


def _unavailable(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"runner unavailable: {exc}")


def _failed(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"runner error: {exc}")


async def _ask(op: str, *, timeout: float = runner.SHORT_TIMEOUT_S, **fields: Any) -> Any:
    """A read: the runner's answer, or the HTTP status that says why there is none."""
    try:
        return await runner.call(op, timeout=timeout, **fields)
    except runner.RunnerRefused as exc:
        raise _refused(exc)
    except runner.RunnerUnavailable as exc:
        raise _unavailable(exc)
    except runner.RunnerError as exc:
        logger.error("[FRAMEPROV] frame runner error on %s: %s", op, exc)
        raise _failed(exc)


async def _audit(db: AsyncSession, request: Request, admin: Any, action: str, target_type: str, target_id: str, *,
                 outcome: str = "success", severity: str = "info", details: Optional[Dict[str, Any]] = None,
                 error_message: Optional[str] = None) -> None:
    await log_admin_action(
        db,
        action=f"frame_runner.{action}",
        actor_id=str(getattr(admin, "id", "") or ""),
        actor_ip=effective_client_ip(request),
        target_type=target_type,
        target_id=target_id,
        outcome=outcome,
        severity=severity,
        details=details or {},
        error_message=error_message,
    )   # the auditor commits its row itself, so a refusal row survives get_db's rollback on the HTTPException


async def _act(db: AsyncSession, request: Request, admin: Any, action: str, target_type: str, target_id: str, op: str,
               *, severity: str = "warning", timeout: float = runner.SHORT_TIMEOUT_S,
               details: Optional[Dict[str, Any]] = None, **fields: Any) -> Any:
    """An act: the runner's answer. A refusal or a failure is audited before it becomes the HTTP error."""
    try:
        return await runner.call(op, timeout=timeout, **fields)
    except runner.RunnerRefused as exc:
        await _audit(db, request, admin, action, target_type, target_id, outcome="refused", severity=severity,
                     details=details, error_message=str(exc)[:500])
        raise _refused(exc)
    except runner.RunnerUnavailable as exc:
        await _audit(db, request, admin, action, target_type, target_id, outcome="failure", severity=severity,
                     details=details, error_message=str(exc)[:500])
        raise _unavailable(exc)
    except runner.RunnerError as exc:
        logger.error("[FRAMEPROV] frame runner error on %s %s: %s", op, target_id, exc)
        await _audit(db, request, admin, action, target_type, target_id, outcome="failure", severity=severity,
                     details=details, error_message=str(exc)[:500])
        raise _failed(exc)


@router.get("/status")
async def runner_status(admin: Any = Depends(platform_admin)) -> Dict[str, Any]:
    """The runner's frames and recent jobs. A registry that cannot reach the runner answers `available: false` with
    the reason: that is a fact about this node, not an error. So does a registry whose socket refuses these two reads
    (§MCPTEST30 V0562, 45's first admin sweep of sbx-beta: a registry holding only the operator socket is served
    operator_* ops and nothing else, and the page showed the 409 as an error)."""
    try:
        info = await runner.call("ping")
        state = await runner.call("status")
    except runner.RunnerUnavailable as exc:
        return {"available": False, "reason": str(exc), "runner": None, "active": None, "jobs": [], "frames": []}
    except runner.RunnerRefused as exc:
        return {"available": False, "reason": f"this registry's runner socket does not serve frame work ({exc})",
                "runner": None, "active": None, "jobs": [], "frames": []}
    except runner.RunnerError as exc:
        logger.error("[FRAMEPROV] frame runner error on status: %s", exc)
        raise _failed(exc)
    return {
        "available": True,
        "reason": None,
        "runner": info,
        "active": _pick(state.get("active"), JOB_FIELDS),
        "jobs": [_pick(job, JOB_FIELDS) for job in state.get("jobs") or []],
        "frames": [_pick(frame, FRAME_FIELDS) for frame in state.get("frames") or []],
    }


@router.post("/plan")
async def plan_frame(spec: FrameSpec, admin: Any = Depends(platform_admin)) -> Any:
    """The standup driver's read-only plan for this spec, run on the host: refusals, warnings and derived values."""
    return await _ask("plan", timeout=runner.LONG_TIMEOUT_S, spec=spec.model_dump())


@router.post("/jobs")
async def start_standup(spec: FrameSpec, request: Request, db: AsyncSession = Depends(get_db),
                        admin: Any = Depends(platform_admin)) -> Any:
    """Starts a standup. The runner plans again on the host first and starts nothing its plan refuses; that answer is
    `started: false` with the plan."""
    facts = {"ticker": spec.ticker, "registry_image": spec.registry_image, "teg_image": spec.teg_image}
    result = await _act(db, request, admin, "standup", "frame", spec.name, "standup", timeout=runner.LONG_TIMEOUT_S,
                        details=facts, spec=spec.model_dump())
    started = bool(result.get("started"))
    refusals = [str(r) for r in ((result.get("plan") or {}).get("refusals") or [])]
    await _audit(db, request, admin, "standup", "frame", spec.name, outcome="success" if started else "refused",
                 severity="warning", details={**facts, "started": started, "job_id": (result.get("job") or {}).get("id")},
                 error_message=None if started else ("; ".join(refusals) or "the plan refused")[:500])
    return result


@router.get("/jobs/{job_id}")
async def job_status(job_id: str = Path(..., max_length=64), admin: Any = Depends(platform_admin)) -> Dict[str, Any]:
    result = await _ask("status", job_id=job_id)
    return {"job": _pick(result.get("job"), JOB_FIELDS), "last_event": result.get("last_event")}


@router.get("/jobs/{job_id}/events")
async def job_events(job_id: str = Path(..., max_length=64), after: int = Query(0, ge=0),
                     admin: Any = Depends(platform_admin)) -> Any:
    """The job's progress lines from `after` on, and the cursor to ask from next."""
    return await _ask("events", job_id=job_id, after=after)


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(request: Request, job_id: str = Path(..., max_length=64), db: AsyncSession = Depends(get_db),
                     admin: Any = Depends(platform_admin)) -> Any:
    result = await _act(db, request, admin, "cancel", "frame_runner_job", job_id, "cancel", job_id=job_id)
    await _audit(db, request, admin, "cancel", "frame_runner_job", job_id, severity="warning")
    return result


@router.post("/frames/{name}/resume")
async def resume_frame(body: ResumeRequest, request: Request, name: str = Path(..., max_length=64),
                       db: AsyncSession = Depends(get_db), admin: Any = Depends(platform_admin)) -> Any:
    """Runs a frame this runner built again from a step, with its own stack, ports and secrets (a step that issues units
    never runs twice: the driver's resume rule)."""
    details = {"from_step": body.from_step}
    result = await _act(db, request, admin, "resume", "frame", name, "resume", details=details, name=name,
                        from_step=body.from_step)
    await _audit(db, request, admin, "resume", "frame", name, severity="warning",
                 details={**details, "job_id": (result.get("job") or {}).get("id")})
    return result


@router.post("/frames/{name}/teardown")
async def teardown_frame(request: Request, name: str = Path(..., max_length=64), db: AsyncSession = Depends(get_db),
                         admin: Any = Depends(platform_admin)) -> Any:
    """Tears down a frame this runner built. The runner refuses any other frame and every protected name."""
    result = await _act(db, request, admin, "teardown", "frame", name, "teardown", name=name)
    await _audit(db, request, admin, "teardown", "frame", name, severity="warning",
                 details={"job_id": (result.get("job") or {}).get("id")})
    return result


@router.post("/frames/{name}/reveal")
async def reveal_admin_credential(request: Request, response: Response, name: str = Path(..., max_length=64),
                                  db: AsyncSession = Depends(get_db), admin: Any = Depends(platform_admin)) -> Dict[str, Any]:
    """Hands the new frame's admin credential over once (his word: show once). The runner deletes its copy as it
    answers; the frame's own env on the host still holds it. The audit row records the hand-over, never the password."""
    result = await _act(db, request, admin, "reveal", "frame", name, "reveal", name=name)
    await _audit(db, request, admin, "reveal", "frame", name, severity="warning",
                 details={"admin_email": result.get("admin_email")})
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return {"admin_email": result.get("admin_email"), "admin_password": result.get("admin_password"),
            "console": result.get("console")}
