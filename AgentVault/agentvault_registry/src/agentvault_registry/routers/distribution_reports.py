"""V0667 D7 (order gwo_0f317438b7dfc6dfacd3e9b7): the signed report of a release line and the signed record of one of its changes (services/distribution_report). Read-only, behind
CODE_DISTRIBUTIONS_ENABLED (off, each answers 404). Readers: the organization's members (not guests) and platform admins; for anyone else the line has nothing to show.

  GET /api/v1/code-distributions/{slug}/report                  the signed report (add ?download=1 for a file named <release>.report.json)
  GET /api/v1/code-distributions/{slug}/records/{cid}           the signed record of one change of the line (cc_... or ct_...)
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from agentvault_registry import database
from agentvault_registry.routers.code_distributions import _is_admin, _switch
from agentvault_registry.security import get_current_developer
from agentvault_registry.services import code_distributions, content_changes, distribution_report

router = APIRouter(tags=["Code distributions"], dependencies=[Depends(_switch)])


def _refusal(status: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"code": code, "detail": detail})


async def _line(db: Any, developer: Any, slug: str):
    """(line, None) for a reader who may read it, else (None, the refusal)."""
    store = content_changes.store_for(db)
    dist = await store.distribution_by_slug(slug)
    if not dist:
        return None, _refusal(404, "not_found", "no code distribution with that name")
    if _is_admin(developer):
        return dist, None
    role = (await store.org_members(dist["organization_id"])).get(developer.id)
    if role is None:
        return None, _refusal(404, "not_found", "no code distribution with that name")
    if role not in code_distributions.ORG_PROPOSING_ROLES:
        return None, _refusal(403, "guest", "the report of a release line is read by the organization's members, not its guests")
    return dist, None


def _send(envelope: Dict[str, Any], filename: Optional[str]) -> JSONResponse:
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'} if filename else None
    return JSONResponse(status_code=200, content=envelope, headers=headers)


@router.get("/api/v1/code-distributions/{slug}/report", summary="The signed report of a release line: every change, who proposed, reviewed and voted, our checker's records (members, admins)")
async def report(slug: str, download: bool = Query(False), developer=Depends(get_current_developer), db=Depends(database.get_db)):
    dist, refusal = await _line(db, developer, slug)
    if refusal is not None:
        return refusal
    body = await distribution_report.build_report(db, dist)
    release = distribution_report.release_name(dist)
    return _send(await distribution_report.sign(db, distribution_report.REPORT_KIND, release, body), f"{release}.report.json" if download else None)


@router.get("/api/v1/code-distributions/{slug}/records/{cid}", summary="The signed record of one change of a release line (members, admins)")
async def record(slug: str, cid: str, download: bool = Query(False), developer=Depends(get_current_developer), db=Depends(database.get_db)):
    dist, refusal = await _line(db, developer, slug)
    if refusal is not None:
        return refusal
    body = await distribution_report.build_record(db, dist, cid)
    if body is None:
        return _refusal(404, "not_found", "no change of that id on this release line")
    return _send(await distribution_report.sign(db, distribution_report.RECORD_KIND, cid, body), f"{cid}.record.json" if download else None)
