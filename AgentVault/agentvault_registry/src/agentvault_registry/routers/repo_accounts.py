"""Repository accounts on the public code host (V0667, order gwo_662c03447bcd627afa4a11e5; services/repo_accounts).

  GET  /api/v1/developers/me/repo-account     the developer's own: linked or not, the state, a pending leg with its reason and
                                              next try, and WHAT_IS_SHARED (the console shows it before the button)
  POST /api/v1/developers/me/repo-account     {username, confirm: true, accept_terms}: the link, only on the developer's own
                                              confirmation, accepting the Terms served now (Terms § 10.2: the code host is
                                              their § 5.12; the acceptance is recorded in the link's transaction); the
                                              one-time password is in this answer and nowhere else
  GET  /api/v1/admin/repo-accounts/stuck      the legs past MAX_ATTEMPTS (admin_platform): what the admin inbox lists
A refusal answers {"code", "detail"} with its status, as the code change routes do.
"""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from agentvault_registry import database
from agentvault_registry.security import get_current_developer, require_admin_flag
from agentvault_registry.services import repo_accounts as ra
from agentvault_registry.services.legal_acceptance import SUBJECT_DEVELOPER, record_acceptance

router = APIRouter(tags=["Repository accounts"])


class LinkIn(BaseModel):
    username: str = Field(..., max_length=64)
    confirm: bool = False
    accept_terms: str = Field("", max_length=40)


def _refused(r: ra.RepoAccountRefusal) -> JSONResponse:
    return JSONResponse(status_code=r.status, content={"code": r.code, "detail": r.sentence})


@router.get("/api/v1/developers/me/repo-account", summary="Your repository account on the code host")
async def my_repo_account(developer=Depends(get_current_developer), db=Depends(database.get_db)):
    return await ra.RepoAccounts(ra.DbStore(db)).status(developer.id)


@router.post("/api/v1/developers/me/repo-account", status_code=201, summary="Link a repository account (never automatic)")
async def link_repo_account(body: LinkIn, request: Request, developer=Depends(get_current_developer),
                            db=Depends(database.get_db)):
    flow = ra.RepoAccounts(ra.DbStore(db), ra.ForgejoClient())
    try:
        out = await flow.link(developer.id, body.model_dump())
    except ra.RepoAccountRefusal as r:
        return _refused(r)
    served = out.pop("terms_version")
    await record_acceptance(db, document="terms", subject_kind=SUBJECT_DEVELOPER, subject_id=str(developer.id),
                            via="repo_account_link", developer_id=developer.id, request=request, version=served)
    developer.tos_accepted_version = served
    developer.tos_accepted_at = dt.datetime.now(dt.timezone.utc)
    try:
        await db.commit()
    except Exception:  # noqa: BLE001 - the host user was made before this commit: it must not outlive a link not recorded
        await db.rollback()
        await flow.undo_link(out["username"])
        return _refused(ra.RepoAccountRefusal(503, "not_recorded", "the link could not be recorded: nothing was kept, try again"))
    return JSONResponse(status_code=201, content=out, headers={"Cache-Control": "no-store"})


@router.get("/api/v1/admin/repo-accounts/stuck", summary="Repository account legs that cannot land",
            dependencies=[Depends(require_admin_flag("admin_platform"))])
async def stuck_legs(db=Depends(database.get_db)):
    ops = await ra.RepoAccounts(ra.DbStore(db)).stuck_ops()
    return {"stuck": [{k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in o.items()} for o in ops]}
