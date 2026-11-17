"""V0663, governed code, first slice (order gwo_58327a76b7e3ecf63140eb79): the routes of a code change. Thin: every rule
lives in services/code_changes (CodeChangeFlow over DbStore). A refusal answers its status with {"code", "detail"}.

  POST /api/v1/code-changes                          a member's agent proposes (a bounty posts a normal Guild order)
  GET  /api/v1/code-changes, /api/v1/code-changes/{cid}   public, as the ballot is
  POST /api/v1/code-changes/{cid}/reviews            a member developer reviews the accepted commit
  POST /api/v1/code-changes/{cid}/ballot             the proposer's agent opens the members' ballot
  POST /api/v1/admin/code-changes/{cid}/acceptance   admin_platform, not the proposer's or the worker's developer: the
                                                     host checker's signed record for a commit, verified here (V0664)
  POST /api/v1/admin/code-changes/{cid}/ballot       admin_platform: opens the ballot
  POST /api/v1/admin/code-changes/{cid}/veto         the maintainer's account (CODE_CHANGES_MAINTAINER): the veto (D4, F3)
  POST /api/v1/admin/code-changes/{cid}/go           the maintainer's account: the go, which ends the window
  POST /api/v1/admin/code-changes/{cid}/merged       admin_platform: a session records the merge of the voted commit
                                                     into a release branch that holds it (F8), on the checker's
                                                     signed release_line record
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, Security
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from agentvault_registry import database
from agentvault_registry.routers.utils import get_current_agent
from agentvault_registry.security import (get_current_developer, get_current_developer_optional, require_admin_flag,
                                          require_agent_permission)
from agentvault_registry.services import code_changes

router = APIRouter(tags=["Code changes"])
_ADMIN = require_admin_flag("admin_platform")


class ProposeIn(BaseModel):
    repository: str = Field(..., max_length=120)
    paths: List[str] = Field(..., max_length=code_changes.MAX_PATHS)
    title: str = Field(..., max_length=160)
    problem: str = Field(..., max_length=6000)
    bounty: Optional[float] = None
    currency: Optional[str] = Field(None, max_length=12)
    branch: Optional[str] = Field(None, max_length=200)
    commit: Optional[str] = Field(None, max_length=64)
    # V0666 D1: the slug of an organization's code distribution (its release line) to propose into; absent = the main line
    code_distribution: Optional[str] = Field(None, max_length=40)
    # V0666 D3: a line's change may name one room of the line's organization: its live card and state lines go there
    room_id: Optional[str] = Field(None, max_length=36)


class LineVoteIn(BaseModel):
    vote: bool


class AcceptanceIn(BaseModel):
    """V0664: the host checker's signed record for a commit (services/code_change_checker); nothing else is read."""
    signed: Optional[Dict[str, Any]] = None


class ReviewIn(BaseModel):
    verdict: str = Field(..., max_length=10)
    commit: str = Field(..., max_length=64)
    findings: str = Field("", max_length=4000)


class VetoIn(BaseModel):
    reason: str = Field("", max_length=1000)


class WithdrawIn(BaseModel):
    reason: str = Field("", max_length=400)


class MergedIn(BaseModel):
    commit: str = Field(..., max_length=64)
    into: str = Field(..., max_length=200)
    signed: Optional[Dict[str, Any]] = None     # V0664: the checker's signed word that `into` holds `commit`


def _refused(r: code_changes.CodeChangeRefusal) -> JSONResponse:
    return JSONResponse(status_code=r.status, content={"code": r.code, "detail": r.sentence})


def _admin_actor(admin: Any) -> Dict[str, Any]:
    return {"developer_id": getattr(admin, "id", None), "admin": True, "email": getattr(admin, "email", None)}


async def _run(step):
    try:
        return await step
    except code_changes.CodeChangeRefusal as r:
        return _refused(r)


@router.post("/api/v1/code-changes", status_code=201, summary="Propose a code change (a member's agent)")
async def propose(body: ProposeIn, agent=Depends(get_current_agent), db=Depends(database.get_db)):
    # V0667: with the code host open (REPO_ACCOUNTS_ENABLED) a code change needs the proposer's linked, active repository
    # account; the console greys its submit until then (room seq 5040). Asked before the flow runs.
    from agentvault_registry.services import repo_accounts
    try:
        await repo_accounts.RepoAccounts(repo_accounts.DbStore(db)).require_linked(agent.creator_developer_id)
    except repo_accounts.RepoAccountRefusal as r:
        return JSONResponse(status_code=r.status, content={"code": r.code, "detail": r.sentence})
    flow = code_changes.CodeChangeFlow(code_changes.store_for(db, agent=agent))
    actor = {"did": agent.did, "developer_id": agent.creator_developer_id}
    payload = body.model_dump()
    if payload.get("code_distribution") is None:
        payload.pop("code_distribution", None)        # the main line's body, as before
    out = await _run(flow.propose(actor, payload))
    return out if isinstance(out, JSONResponse) else JSONResponse(status_code=201, content=out)


@router.get("/api/v1/code-changes-authority", summary="Which registry governs code, and whether this one does (V0666)")
async def authority(db=Depends(database.get_db)):
    """The console reads this to show the sentence and its link, and no Submit, on a registry that does not govern code (services/code_authority)."""
    from agentvault_registry.services import code_authority
    if not code_authority.is_governing():
        await code_authority.warm_peer_link(db, code_authority.governing_name() or code_authority.DEFAULT_NAME)
    return code_authority.authority()


@router.get("/api/v1/code-changes", summary="Code changes, newest first")
async def list_changes(state: Optional[str] = Query(None, max_length=20), limit: int = Query(50, ge=1, le=200),
                       code_distribution: Optional[str] = Query(None, max_length=40,
                                                                description="a line's slug: its changes (V0666 D1)"),
                       upstream: bool = Query(False, description="only the main-line changes that carry a line's change upstream, with "
                                                                 "their provenance and their fate (V0667 D4)"),
                       db=Depends(database.get_db), reader=Depends(get_current_developer_optional)):
    """Public. V0666 D2: a signed-in reader also reads their own vote on a line's change (line_ballot.my_vote)."""
    me = getattr(reader, "id", None)
    store = code_changes.store_for(db)
    flow = code_changes.CodeChangeFlow(store)
    if code_distribution is not None:
        from agentvault_registry.services import code_distributions
        if not code_distributions.enabled():
            return JSONResponse(status_code=404, content={"detail": "Not Found"})
        dist = await store.distribution_by_slug(code_distribution)
        if not dist:
            return JSONResponse(status_code=404, content={"code": "not_found",
                                                          "detail": "no code distribution with that name"})
        rows = await store.list(state, limit, dist["id"])
        await store.prefetch(rows)
        return {"code_changes": [await flow.view(r["id"], me) for r in rows], "code_distribution": code_distribution}
    if upstream:
        from agentvault_registry.services import code_distributions
        if not code_distributions.enabled():
            return JSONResponse(status_code=404, content={"detail": "Not Found"})
        rows = await store.list(state, limit, None, True)
        await store.prefetch(rows)
        return {"code_changes": [await flow.view(r["id"]) for r in rows], "upstream": True}
    rows = await store.list(state, limit) if hasattr(store, "list") else [dict(r) for r in store.rows.values()]
    if hasattr(store, "prefetch"):
        await store.prefetch(rows)                    # V0665: every card's names in a few statements, before the cards are viewed
    return {"code_changes": [await flow.view(r["id"]) for r in rows]}


@router.get("/api/v1/code-changes/{cid}", summary="One code change: its record, reviews, ballot and veto window")
async def view(cid: str, db=Depends(database.get_db), reader=Depends(get_current_developer_optional)):
    """Public. V0666 D2: a signed-in reader also reads their own vote on a line's change (line_ballot.my_vote)."""
    return await _run(code_changes.CodeChangeFlow(code_changes.store_for(db)).view(cid, getattr(reader, "id", None)))


@router.post("/api/v1/code-changes/{cid}/reviews", summary="Review the accepted commit (a member developer)")
async def review(cid: str, body: ReviewIn, developer=Depends(get_current_developer), db=Depends(database.get_db)):
    flow = code_changes.CodeChangeFlow(code_changes.store_for(db))
    return await _run(flow.review({"developer_id": developer.id}, cid, body.model_dump()))


@router.post("/api/v1/code-changes/{cid}/ballot", summary="Open the members' ballot (the proposer's agent)")
async def open_ballot(cid: str, agent=Depends(get_current_agent), db=Depends(database.get_db)):
    flow = code_changes.CodeChangeFlow(code_changes.store_for(db, agent=agent))
    return await _run(flow.open_ballot({"did": agent.did, "developer_id": agent.creator_developer_id}, cid))


@router.post("/api/v1/code-changes/{cid}/withdraw", summary="Withdraw a change before its ballot (the proposer's agent)")
async def withdraw(cid: str, body: WithdrawIn = None, agent=Depends(get_current_agent), db=Depends(database.get_db)):
    """V0663 slice 2: a bounty returns to its poster through the Guild."""
    flow = code_changes.CodeChangeFlow(code_changes.store_for(db, agent=agent))
    return await _run(flow.withdraw({"did": agent.did, "developer_id": agent.creator_developer_id}, cid,
                                    (body or WithdrawIn()).model_dump()))


@router.post("/api/v1/admin/code-changes/{cid}/withdraw", summary="Withdraw a change before its ballot (a platform admin)")
async def admin_withdraw(cid: str, admin=Security(_ADMIN), body: WithdrawIn = None, db=Depends(database.get_db)):
    flow = code_changes.CodeChangeFlow(code_changes.store_for(db))
    return await _run(flow.withdraw(_admin_actor(admin), cid, (body or WithdrawIn()).model_dump()))


@router.post("/api/v1/admin/code-changes/{cid}/acceptance", summary="Take the host checker's signed record for a commit")
async def record_acceptance(cid: str, admin=Security(_ADMIN), body: AcceptanceIn = None, db=Depends(database.get_db)):
    flow = code_changes.CodeChangeFlow(code_changes.store_for(db))
    return await _run(flow.record_acceptance(_admin_actor(admin), cid, (body or AcceptanceIn()).model_dump()))


@router.post("/api/v1/admin/code-changes/{cid}/ballot", summary="Open the members' ballot (a platform admin)")
async def admin_open_ballot(cid: str, admin=Security(_ADMIN), db=Depends(database.get_db)):
    return await _run(code_changes.CodeChangeFlow(code_changes.store_for(db)).open_ballot(_admin_actor(admin), cid))


@router.post("/api/v1/admin/code-changes/{cid}/veto", summary="The maintainer's veto, inside the window (his account only)")
async def veto(cid: str, admin=Security(_ADMIN), body: VetoIn = None, db=Depends(database.get_db)):
    flow = code_changes.CodeChangeFlow(code_changes.store_for(db))
    return await _run(flow.veto(_admin_actor(admin), cid, (body or VetoIn()).model_dump()))


@router.post("/api/v1/admin/code-changes/{cid}/go", summary="The maintainer's go, which ends the veto window (his account only)")
async def go(cid: str, admin=Security(_ADMIN), db=Depends(database.get_db)):
    return await _run(code_changes.CodeChangeFlow(code_changes.store_for(db)).go(_admin_actor(admin), cid))


@router.post("/api/v1/admin/code-changes/{cid}/merged", summary="Record the merge of the voted commit")
async def merged(cid: str, admin=Security(_ADMIN), body: MergedIn = None, db=Depends(database.get_db)):
    flow = code_changes.CodeChangeFlow(code_changes.store_for(db))
    return await _run(flow.record_merge(_admin_actor(admin), cid, (body or MergedIn(commit="", into="")).model_dump()))


# -- V0666 D1: a code distribution's own steps on a change (CODE_DISTRIBUTIONS_ENABLED; off, each answers 404) --

def _line_switch() -> None:
    from fastapi import HTTPException
    from agentvault_registry.services import code_distributions
    if not code_distributions.enabled():
        raise HTTPException(status_code=404, detail="Not Found")


@router.post("/api/v1/code-changes/{cid}/code-distribution-vote", dependencies=[Depends(_line_switch)],
             summary="A decider's vote on a code distribution's change (an organization's release line, not an AGORA payout)")
async def line_vote(cid: str, body: LineVoteIn, agent=Security(require_agent_permission("gov.vote")),
                    db=Depends(database.get_db)):
    """The main line's agent gate (gov.vote, an active agent); one vote per developer, never changed."""
    flow = code_changes.CodeChangeFlow(code_changes.store_for(db, agent=agent))
    return await _run(flow.line_vote({"did": agent.did, "developer_id": agent.creator_developer_id}, cid,
                                     body.model_dump()))


@router.post("/api/v1/code-changes/{cid}/upstream", status_code=201, dependencies=[Depends(_line_switch)],
             summary="Propose a merged change of an organization's code distribution upstream, to the main code, with its history (a decider's agent)")
async def propose_upstream(cid: str, agent=Depends(get_current_agent), db=Depends(database.get_db)):
    """V0667 D4. A normal main-line Code change for the same commit: the checker signs it again, the frame decides it. With the code host
    open the proposer needs their linked repository account, as for any code change."""
    from agentvault_registry.services import repo_accounts
    try:
        await repo_accounts.RepoAccounts(repo_accounts.DbStore(db)).require_linked(agent.creator_developer_id)
    except repo_accounts.RepoAccountRefusal as r:
        return JSONResponse(status_code=r.status, content={"code": r.code, "detail": r.sentence})
    flow = code_changes.CodeChangeFlow(code_changes.store_for(db, agent=agent))
    out = await _run(flow.propose_upstream({"did": agent.did, "developer_id": agent.creator_developer_id}, cid))
    return out if isinstance(out, JSONResponse) else JSONResponse(status_code=201, content=out)


@router.post("/api/v1/code-changes/{cid}/code-distribution-veto", dependencies=[Depends(_line_switch)],
             summary="The organization owner's veto on its code distribution's passed change, inside the veto window")
async def line_owner_veto(cid: str, body: VetoIn = None, developer=Depends(get_current_developer),
                          db=Depends(database.get_db)):
    flow = code_changes.CodeChangeFlow(code_changes.store_for(db))
    return await _run(flow.line_owner_veto({"developer_id": developer.id}, cid, (body or VetoIn()).model_dump()))


@router.post("/api/v1/code-changes/{cid}/code-distribution-go", dependencies=[Depends(_line_switch)],
             summary="The organization owner's go on its code distribution's passed change (it never shortens the platform's veto window)")
async def line_owner_go(cid: str, developer=Depends(get_current_developer), db=Depends(database.get_db)):
    flow = code_changes.CodeChangeFlow(code_changes.store_for(db))
    return await _run(flow.line_owner_go({"developer_id": developer.id}, cid))
