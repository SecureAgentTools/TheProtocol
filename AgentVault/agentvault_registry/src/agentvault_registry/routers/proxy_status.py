"""V0664 consoles (C2, order gwo_ebaafc5c4af1fa3a6858e55d): a proxy's status. Thin: the rules are in services/proxy_status.

  POST /api/v1/agents/me/proxy-status        agent tier: the proxy's report as its own agent (16 KiB at most, names and counts only)
  GET  /api/v1/agents/{did}/proxy-status     developer tier: the report of an agent its developer created; anyone else: 404
  GET  /api/v1/developers/me/proxy-status    developer tier: the developer's agents that have reported, newest first (at most 200)
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Request, Security
from fastapi.responses import JSONResponse

from agentvault_registry import database, models
from agentvault_registry.security import get_current_agent, get_current_developer
from agentvault_registry.services import proxy_status as ps

router = APIRouter(tags=["Proxy status"])


def store_for(db: Any) -> Any:
    return ps.DbStore(db)


def _refusal(r: ps.Refusal) -> JSONResponse:
    return JSONResponse(status_code=r.status, content={"code": r.code, "detail": r.detail})


async def _body(request: Request) -> bytes:
    """The request's body, refused as soon as it passes the cap (a Content-Length above it is refused unread)."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > ps.MAX_BYTES:
        raise ps.Refusal(413, "too_large", f"A status report is at most {ps.MAX_BYTES // 1024} KiB")
    out = bytearray()
    async for chunk in request.stream():
        out += chunk
        if len(out) > ps.MAX_BYTES:
            raise ps.Refusal(413, "too_large", f"A status report is at most {ps.MAX_BYTES // 1024} KiB")
    return bytes(out)


@router.post("/api/v1/agents/me/proxy-status", summary="A proxy posts its status (names and counts only)")
async def post_proxy_status(request: Request, agent: models.Agent = Security(get_current_agent),
                            db: Any = Depends(database.get_db)):
    try:
        raw = await _body(request)
        try:
            body = json.loads(raw)
        except ValueError:
            raise ps.Refusal(422, "invalid_report", "report: not JSON") from None
        return await ps.report(store_for(db), agent.did, body)
    except ps.Refusal as r:
        return _refusal(r)


@router.get("/api/v1/developers/me/proxy-status", summary="The status of the developer's proxies that report")
async def my_proxy_statuses(developer: models.Developer = Depends(get_current_developer), db: Any = Depends(database.get_db)):
    return {"items": await ps.list_for_owner(store_for(db), developer.id)}


@router.get("/api/v1/agents/{did}/proxy-status", summary="An agent's last status report, to its owner")
async def get_proxy_status(did: str, developer: models.Developer = Depends(get_current_developer),
                           db: Any = Depends(database.get_db)):
    try:
        return await ps.read_for_owner(store_for(db), developer.id, did)
    except ps.Refusal as r:
        return _refusal(r)
