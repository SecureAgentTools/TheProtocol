"""§RELEASECHANNEL: the admin's view of the signed release channel, and the rollout they schedule themselves.

    GET    /api/v1/admin/release-channel/status     what this registry runs, what the channel lists, the last check,
                                                    the scheduled window, and whether the public pull is on
    POST   /api/v1/admin/release-channel/check      read the channel now (verified the same way the worker does)
    PUT    /api/v1/admin/release-channel/schedule   {"version": ..., "at": "<ISO 8601, future>", "note": ...}
    DELETE /api/v1/admin/release-channel/schedule

Scheduling records the admin's decision and the reminder the checker will send when the window is due. It moves
nothing: the rollout itself is the host command the page prints (`tp update --apply` for an operator, `frame-update.py`
for a frame), run by the person who owns the host.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Security
from pydantic import BaseModel, Field

from agentvault_registry import security
from agentvault_registry.core import release_channel as rc
from agentvault_registry.models import Developer

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/release-channel", tags=["Admin — Release channel"])


class ScheduleBody(BaseModel):
    version: str = Field(..., min_length=1, max_length=64)
    at: str = Field(..., min_length=1, max_length=40, description="ISO 8601 with offset or Z, in the future")
    note: Optional[str] = Field(None, max_length=400)


def _status_doc() -> Dict[str, Any]:
    # held against the build that runs now (rc.current_view): a registry updated since the last check is not told it
    # is behind on the release it runs, nor handed the command to apply it
    st = rc.current_view(rc.load_state())
    st["enabled"] = rc.check_enabled()
    st["channel_url"] = rc.channel_url()
    st["public_pull"] = rc.public_pull_enabled()
    st["public_namespace"] = rc.public_namespace()
    from agentvault_registry.background_tasks.release_channel_checker import rollout_command, _node_kind
    kind = _node_kind()
    st["node_kind"] = kind
    newest = (st.get("newer") or [{}])[0] or {}
    st["rollout_command"] = rollout_command(kind, newest.get("version")) if newest.get("version") else None
    return st


@router.get("/status")
async def release_channel_status(
    _admin: Developer = Security(security.require_admin_flag("admin_platform")),
) -> Dict[str, Any]:
    return _status_doc()


@router.post("/check")
async def release_channel_check_now(
    admin: Developer = Security(security.require_admin_flag("admin_platform")),
) -> Dict[str, Any]:
    from agentvault_registry.background_tasks.release_channel_checker import check_once
    logger.info("[release-channel] check requested by admin %s", admin.email)
    await check_once(notify=True)
    return _status_doc()


@router.put("/schedule")
async def release_channel_schedule(
    body: ScheduleBody,
    admin: Developer = Security(security.require_admin_flag("admin_platform")),
) -> Dict[str, Any]:
    try:
        at = datetime.fromisoformat(body.at.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=422, detail="`at` must be an ISO 8601 date-time with an offset or Z")
    if at.tzinfo is None:
        raise HTTPException(status_code=422, detail="`at` needs a UTC offset (or Z)")
    if at <= datetime.now(timezone.utc):
        raise HTTPException(status_code=422, detail="`at` must be in the future")
    state = rc.load_state()
    view = rc.current_view(state)
    known = {(r or {}).get("version") for r in (view.get("newer") or [])}
    if body.version not in known:
        listed = {(r or {}).get("version") for r in (state.get("newer") or [])} | {(state.get("latest") or {}).get("version")}
        running = (view.get("running") or {}).get("kit_version") or (view.get("running") or {}).get("software_version")
        why = (f"this registry already runs {running} or a later release" if body.version in listed
               else "it is not a release the channel lists for this registry")
        raise HTTPException(status_code=422, detail=f"{body.version} cannot be scheduled: {why} (newer releases: "
                                                    f"{sorted(v for v in known if v) or 'none'})")
    state["schedule"] = {"version": body.version, "at": at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                         "note": (body.note or "").strip() or None, "set_by": admin.email, "set_at": rc.now_iso(),
                         "reminded_at": None}
    rc.save_state(state)
    logger.info("[release-channel] rollout to %s scheduled for %s by %s", body.version, state["schedule"]["at"], admin.email)
    return _status_doc()


@router.delete("/schedule")
async def release_channel_unschedule(
    admin: Developer = Security(security.require_admin_flag("admin_platform")),
) -> Dict[str, Any]:
    state = rc.load_state()
    if state.get("schedule"):
        logger.info("[release-channel] schedule for %s cleared by %s", state["schedule"].get("version"), admin.email)
    state["schedule"] = None
    rc.save_state(state)
    return _status_doc()
