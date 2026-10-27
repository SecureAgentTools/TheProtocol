"""§MEMBERSHIP phase B (2026-10-02): the commons routes (services/commons.py holds the rules).

    GET  /api/v1/commons/seasons                       public: the seasons, newest first
    GET  /api/v1/commons/seasons/{id}                  public: one season; ballots published once it closes
    GET  /api/v1/commons/seasons/{id}/mine             developer or agent token: the caller's submissions and ballot
    POST /api/v1/commons/seasons/{id}/submissions      agent token: submit work already done, with evidence
    POST /api/v1/commons/seasons/{id}/ballot           agent token, members only: spread up to 100 points
    POST /api/v1/admin/commons/seasons                 admin_treasury: open a season (its budget is published)
    POST /api/v1/admin/commons/seasons/{id}/close      admin_treasury: fix the tally
    POST /api/v1/admin/commons/seasons/{id}/strike     admin_treasury: remove a submission whose evidence fails
    POST /api/v1/admin/commons/seasons/{id}/pay        admin_treasury: pay the awards through the waterfall (a failed
                                                       payment is re-sent by the next run inside its retry window)
    POST /api/v1/admin/commons/seasons/{id}/awards/{award_id}/write-off
                                                       admin_treasury: settle a failed award a run will not re-send
    POST /api/v1/admin/commons/seasons/{id}/cancel     admin_treasury: cancel before anything is paid

Every refusal is a JSONResponse with {"error", "message", ...} and its own status, answered before any broad except;
where COMMONS_ENABLED is off every route answers 403 commons_disabled ("... is not enabled on this registry").
A ballot is confirmed by its human where GOVERNANCE_PRESENCE_MODE asks (428 step_up_required, the vote's body).
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import logging
from decimal import Decimal
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, Path, Query, Security
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry import security
from agentvault_registry.database import get_db
from agentvault_registry.models import Agent, Developer
from agentvault_registry.routers.utils import get_current_agent
from agentvault_registry.services import commons as _commons
from agentvault_registry.services import governance_presence as _presence
from agentvault_registry.services import membership as _membership

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Commons"])


def _refused(r: _commons.CommonsRefusal) -> JSONResponse:
    return JSONResponse(status_code=r.status_code, content=r.body())


class EvidenceItem(BaseModel):
    type: str = Field(..., max_length=24, description="guild_order | url | commit | ticket | document | other")
    ref: str = Field(..., min_length=1, max_length=200, description="The order id, commit, ticket or a short label")
    url: Optional[str] = Field(default=None, max_length=500)


class SubmissionIn(BaseModel):
    kind: str = Field(..., max_length=24, description="guild_order | change | translation | operations | help | other")
    title: str = Field(..., min_length=3, max_length=200)
    description: str = Field(default="", max_length=4000)
    evidence: List[EvidenceItem] = Field(..., min_length=1, max_length=10)


class BallotIn(BaseModel):
    allocations: Dict[str, int] = Field(..., description="submission id -> points; at most 100 in all")
    totp_code: Optional[str] = Field(default=None, max_length=16)
    challenge_id: Optional[str] = Field(default=None, max_length=44)


class SeasonOpenIn(BaseModel):
    title: str = Field(default="", max_length=160)
    ends_at: Optional[_dt.datetime] = Field(default=None, description="When the season closes (UTC)")
    duration_days: Optional[int] = Field(default=None, ge=1, le=120, description="Instead of ends_at")
    seed: Decimal = Field(default=Decimal(0), ge=0, description="Added from the treasury, in the frame's unit")
    fee_share_percent: Optional[Decimal] = Field(default=None, ge=0, le=100,
                                                 description="Defaults to COMMONS_FEE_SHARE_PERCENT")


class StrikeIn(BaseModel):
    submission_id: int = Field(..., gt=0)
    reason: str = Field(..., min_length=5, max_length=240)


class CancelIn(BaseModel):
    reason: str = Field(..., min_length=5, max_length=240)


class WriteOffIn(BaseModel):
    reason: str = Field(..., min_length=5, max_length=240,
                        description="Why the award is settled without a commons payment (kept on the award)")


# ── public ──────────────────────────────────────────────────────────────────

@router.get("/api/v1/commons/seasons", summary="The commons seasons of this registry, newest first (public)")
async def list_seasons(limit: int = Query(20, ge=1, le=100), db: AsyncSession = Depends(get_db)):
    if not _commons.commons_enabled():
        return _refused(_commons.CommonsRefusal(403, "commons_disabled", _commons.DISABLED_SENTENCE))
    return {"seasons": await _commons.list_seasons(db, limit), "currency": _commons.currency()}


@router.get("/api/v1/commons/seasons/{season_id}", summary="One season: budget, rules, submissions, results (public)")
async def get_season(season_id: int = Path(..., gt=0), db: AsyncSession = Depends(get_db)):
    try:
        _commons.require_enabled()
        return await _commons.season_detail(db, season_id)
    except _commons.CommonsRefusal as r:
        return _refused(r)


@router.get("/api/v1/commons/seasons/{season_id}/mine",
            summary="The caller's own side of a season: their submissions and their current ballot "
                    "(developer or agent token)")
async def get_my_season_view(season_id: int = Path(..., gt=0), actor: dict = Depends(security.get_current_actor_for_read),
                             db: AsyncSession = Depends(get_db)):
    """The public detail with the viewer filled in: `my_submissions` are the caller's developer's submissions and
    `my_ballot` is the ballot a member would replace (so a replaced ballot starts from the old one).
    The viewer is a DEVELOPER, as everywhere in membership: the developer token's own, or an agent token's developer."""
    dev_id = (actor["developer"].id if actor.get("kind") == "developer" else actor["agent"].creator_developer_id)
    try:
        _commons.require_enabled()
        detail = await _commons.season_detail(db, season_id, viewer_developer_id=dev_id)
    except _commons.CommonsRefusal as r:
        return _refused(r)
    return {"season_id": detail["id"], "status": detail["status"],
            "my_submissions": [x for x in detail["submissions"] if x["mine"]],
            "my_ballot": detail["my_ballot"],
            "is_member": (await _membership.weight_points_for(db, dev_id)) > 0}


# ── agents ──────────────────────────────────────────────────────────────────

@router.post("/api/v1/commons/seasons/{season_id}/submissions", status_code=201,
             summary="Submit work already done to the season, with its evidence (agent token)")
async def submit_work(body: SubmissionIn, season_id: int = Path(..., gt=0),
                      agent: Agent = Security(get_current_agent), db: AsyncSession = Depends(get_db)):
    try:
        x = await _commons.submit(db, agent=agent, season_id=season_id, kind=body.kind, title=body.title,
                                  description=body.description, evidence=[e.model_dump() for e in body.evidence])
    except _commons.CommonsRefusal as r:
        return _refused(r)
    return {"id": x.id, "season_id": x.season_id, "kind": x.kind, "title": x.title, "status": x.status,
            "submitter_did": x.submitter_did, "evidence": x.evidence}


@router.post("/api/v1/commons/seasons/{season_id}/ballot",
             summary="Spread up to 100 points over the season's submissions (members; replaceable until the close)")
async def cast_ballot(body: BallotIn, season_id: int = Path(..., gt=0),
                      agent: Agent = Security(get_current_agent), db: AsyncSession = Depends(get_db)):
    try:
        season, clean, total, dev_id = await _commons.validate_ballot(db, agent=agent, season_id=season_id,
                                                                      allocations=body.allocations)
    except _commons.CommonsRefusal as r:
        return _refused(r)
    challenge_used: Optional[str] = None
    if _membership.presence_mode() != "off":
        developer = await db.get(Developer, dev_id)
        digest = _commons.ballot_digest(clean)
        ok, http_status, payload = await _presence.require_presence(
            db, developer, action_type="commons.ballot", action_ref=f"season:{season.id}:{digest}",
            facts={"action": "Cast a commons ballot", "kind": "commons.ballot", "registry": _presence.registry_label(),
                   "season_id": season.id, "season_title": season.title, "total_points": total,
                   "submissions": len(clean), "allocation_digest": digest},
            totp_code=body.totp_code, challenge_id=body.challenge_id,
        )
        if not ok:
            await db.commit()  # a freshly minted challenge must outlive this refusal
            chid = ((payload or {}).get("step_up") or {}).get("challenge_id")
            if chid:
                asyncio.create_task(_presence.announce_challenge(
                    dev_id, chid, action_type="commons.ballot", title="Confirm your commons ballot",
                    message=f"Approve your ballot for season #{season.id} in Pocket, Approvals."))
            return JSONResponse(status_code=http_status, content=payload)
        challenge_used = body.challenge_id
    return await _commons.store_ballot(db, season_id=season.id, developer_id=dev_id, voter_did=agent.did,
                                       allocations=clean, total=total, challenge_id=challenge_used)


# ── admin ───────────────────────────────────────────────────────────────────

_ADMIN = security.require_admin_flag("admin_treasury")


@router.post("/api/v1/admin/commons/seasons", status_code=201, summary="Open a commons season (admin_treasury)")
async def open_season(body: SeasonOpenIn, admin: Developer = Security(_ADMIN), db: AsyncSession = Depends(get_db)):
    now = _commons.now_utc()
    ends_at = body.ends_at
    if ends_at is None:
        ends_at = now + _dt.timedelta(days=body.duration_days or 30)
    elif ends_at.tzinfo is None:
        ends_at = ends_at.replace(tzinfo=_dt.timezone.utc)
    try:
        s = await _commons.open_season(db, admin_id=admin.id, title=body.title, ends_at=ends_at, seed=body.seed,
                                       share_percent=body.fee_share_percent)
    except _commons.CommonsRefusal as r:
        return _refused(r)
    return _commons.season_summary(s)


@router.post("/api/v1/admin/commons/seasons/{season_id}/close", summary="Close a season and fix its tally (admin_treasury)")
async def close_season(season_id: int = Path(..., gt=0), admin: Developer = Security(_ADMIN),
                       db: AsyncSession = Depends(get_db)):
    try:
        s = await _commons.close_season(db, admin_id=admin.id, season_id=season_id)
        return await _commons.season_detail(db, s.id)
    except _commons.CommonsRefusal as r:
        return _refused(r)


@router.post("/api/v1/admin/commons/seasons/{season_id}/strike",
             summary="Strike a submission whose evidence does not hold (admin_treasury)")
async def strike_submission(body: StrikeIn, season_id: int = Path(..., gt=0), admin: Developer = Security(_ADMIN),
                            db: AsyncSession = Depends(get_db)):
    try:
        x = await _commons.strike(db, admin_id=admin.id, season_id=season_id, submission_id=body.submission_id,
                                  reason=body.reason)
    except _commons.CommonsRefusal as r:
        return _refused(r)
    return {"id": x.id, "status": x.status, "struck_reason": x.struck_reason}


@router.post("/api/v1/admin/commons/seasons/{season_id}/pay",
             summary="Pay a closed season's awards through the payout funding waterfall (admin_treasury)")
async def pay_season(season_id: int = Path(..., gt=0), admin: Developer = Security(_ADMIN),
                     db: AsyncSession = Depends(get_db)):
    try:
        return await _commons.pay_season(db, admin_id=admin.id, season_id=season_id)
    except _commons.CommonsRefusal as r:
        return _refused(r)


@router.post("/api/v1/admin/commons/seasons/{season_id}/awards/{award_id}/write-off",
             summary="Settle a failed award without a commons payment (admin_treasury)")
async def write_off_award(body: WriteOffIn, season_id: int = Path(..., gt=0), award_id: int = Path(..., gt=0),
                          admin: Developer = Security(_ADMIN), db: AsyncSession = Depends(get_db)):
    try:
        a, left = await _commons.write_off_award(db, admin_id=admin.id, season_id=season_id, award_id=award_id,
                                                 reason=body.reason)
    except _commons.CommonsRefusal as r:
        return _refused(r)
    return {"id": a.id, "season_id": a.season_id, "recipient_did": a.recipient_did, "status": a.status,
            "written_off_reason": a.written_off_reason, "first_attempt_at": _commons._iso(a.attempted_at),
            "unpaid_awards": left}


@router.post("/api/v1/admin/commons/seasons/{season_id}/cancel", summary="Cancel a season nothing was paid from (admin_treasury)")
async def cancel_season(body: CancelIn, season_id: int = Path(..., gt=0), admin: Developer = Security(_ADMIN),
                        db: AsyncSession = Depends(get_db)):
    try:
        s = await _commons.cancel_season(db, admin_id=admin.id, season_id=season_id, reason=body.reason)
    except _commons.CommonsRefusal as r:
        return _refused(r)
    return _commons.season_summary(s)
