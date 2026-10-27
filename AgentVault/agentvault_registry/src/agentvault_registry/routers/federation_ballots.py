"""§MEMBERSHIP phase D2 (2026-10-02, agentvault2-33): federal ballots, the routes (services/federation_ballot.py holds
the rules; plan section 2.7 is the contract).

At a HOST (the registry whose store holds the federation proposal), for its peers over the federation mTLS lane:
    GET  /api/v1/federation/governance/open        the open ballot proposals, with the registries that have cast
    POST /api/v1/federation/governance/ballots     deliver ONE signed ballot {envelope}; verified, then recorded
For this registry's admins and console:
    GET  /api/v1/governance/federation-ballots              open ballot proposals here and at the ACTIVE frame peers,
                                                            each with this registry's linked members' vote (fresh)
    GET  /api/v1/governance/federation/proposals/{id}/ballots   the ballots on a proposal THIS registry hosts, each whole
                                                            (the signed envelope), for the Senate floor (§MCPTEST30)
    GET  /api/v1/admin/federation/ballots/eligibility       who may cast here now, and why not (admin_platform)
    POST /api/v1/admin/federation/ballots/local-vote        open the members' vote that decides this registry's ballot
    POST /api/v1/admin/federation/ballots                   cast this registry's ballot (the members' result, or the
                                                            operator's choice where the registry has no members)
Every refusal is a JSONResponse {"error", "message", ...} with its own status.
"""
from __future__ import annotations

import copy
import datetime as _dt
import json
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Security
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .. import security
from ..core.federation_auth import _LICENSE_IDENTITY, require_peer_registry_identity
from ..database import get_db
from ..services import federation_ballot as fb
from ..services import membership as _membership

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Federation ballots"])
_ADMIN = security.require_admin_flag("admin_platform")


def _refused(r: fb.BallotRefusal) -> JSONResponse:
    return JSONResponse(status_code=r.status_code, content=r.body())


class BallotDelivery(BaseModel):
    envelope: Dict[str, Any] = Field(..., description="{ballot, alg: EdDSA, kid, signature} signed with the card key")


class LocalVoteIn(BaseModel):
    host: str = Field(default="self", max_length=200, description="'self' or the ACTIVE frame peer hosting the proposal")
    proposal_id: str = Field(..., min_length=8, max_length=64)
    duration_seconds: int = Field(default=3 * 86400, ge=3600, le=30 * 86400)


class CastIn(BaseModel):
    host: str = Field(default="self", max_length=200)
    proposal_id: str = Field(..., min_length=8, max_length=64)
    choice: Optional[str] = Field(default=None, pattern="^(for|against|abstain)$",
                                  description="Required where the registry has no members; otherwise the members decide")


# ── at the host, for its peers ──────────────────────────────────────────────

async def _open_here() -> List[Dict[str, Any]]:
    st, doc = await fb._es("GET", "/proposals?status=VOTING")
    rows = doc if isinstance(doc, list) else (doc or {}).get("proposals", []) if st == 200 else []
    me = fb.own_identity()
    out = []
    for p in rows:
        if not p.get("ballot_mode"):
            continue
        bst, bdoc = await fb._es("GET", f"/proposals/{p['id']}/ballots")
        cast = [b["registry_id"] for b in (bdoc or {}).get("ballots", [])] if bst == 200 else None
        out.append({"id": p["id"], "title": p.get("title"), "description": p.get("description"),
                    "policy_diff": p.get("policy_diff"), "end_timestamp": p.get("end_timestamp"),
                    "host": {"trust_domain": me["trust_domain"], "name": me["name"]}, "ballots_cast_by": cast})
    return out


@router.get("/api/v1/federation/governance/open", summary="Open ballot proposals at this host (federation peers)")
async def federation_open(caller: str = Depends(require_peer_registry_identity)):
    return {"proposals": await _open_here()}


@router.post("/api/v1/federation/governance/ballots", status_code=201,
             summary="Deliver this peer registry's one signed ballot (federation mTLS)")
async def federation_receive_ballot(body: BallotDelivery, caller: str = Depends(require_peer_registry_identity),
                                    db: AsyncSession = Depends(get_db)):
    if _LICENSE_IDENTITY.get() == caller or not caller.startswith("spiffe://"):
        return _refused(fb.BallotRefusal(403, "mtls_required", "a ballot is delivered over the federation mTLS lane."))
    try:
        return await fb.receive_ballot(db, caller, body.envelope)
    except fb.BallotRefusal as r:
        logger.warning("[BALLOT] refused from %s: %s %s", caller, r.error, r.message)
        return _refused(r)


# ── for this registry ───────────────────────────────────────────────────────

_OPEN_CACHE: Dict[str, Any] = {"at": 0.0, "doc": None}


@router.get("/api/v1/governance/federation-ballots",
            summary="Open ballot proposals at this registry and its ACTIVE frame peers (developer or agent token)")
async def federation_ballots_open(actor: dict = Depends(security.get_current_actor_for_read),
                                  db: AsyncSession = Depends(get_db)):
    if _OPEN_CACHE["doc"] is not None and time.monotonic() - _OPEN_CACHE["at"] < fb.OPEN_CACHE_SECONDS:
        return await _with_local_votes(db, _OPEN_CACHE["doc"])
    from .. import models as m
    from sqlalchemy import func, select
    from ..services.exchange_passport import PassportError, peer_request
    me = fb.own_identity()
    hosts: List[Dict[str, Any]] = [{"host": "self", "name": me["name"], "trust_domain": me["trust_domain"],
                                    "proposals": await _open_here(), "error": None}]
    frames = (await db.execute(select(m.PeerRegistry).where(func.upper(m.PeerRegistry.status) == "ACTIVE",
                                                            m.PeerRegistry.peer_type == "frame"))).scalars().all()
    for row in sorted(frames, key=lambda r: r.name.lower()):
        # the trust domain the members' vote and the cast derive their federation_ref from (row, else its card)
        entry = {"host": row.name, "name": row.name, "trust_domain": fb._row_identity(row)["trust_domain"],
                 "proposals": [], "error": None}
        try:
            st, doc = await peer_request(db, row.name, "GET", "/api/v1/federation/governance/open")
            if st == 200 and isinstance(doc, dict):
                entry["proposals"] = doc.get("proposals") or []
            else:
                entry["error"] = f"the host answered {st}"
        except PassportError as e:
            entry["error"] = str(e)[:200]
        hosts.append(entry)
    for h in hosts:
        for p in h["proposals"]:
            p["cast_here"] = None if p.get("ballots_cast_by") is None else me["id"] in p["ballots_cast_by"]
    doc = {"ballot_mode": fb.ballot_mode(), "registry_id": me["id"], "hosts": hosts,
           "as_of": _dt.datetime.now(_dt.timezone.utc).isoformat()}
    _OPEN_CACHE.update(at=time.monotonic(), doc=doc)
    return await _with_local_votes(db, doc)


async def _with_local_votes(db: AsyncSession, doc: Dict[str, Any]) -> Dict[str, Any]:
    """§MCPTEST30 (V0557): each open proposal with this registry's members' vote on it, read NOW from this registry's own
    database (the cached part is only what the peers answered). The console needs it to tell "open their vote" from
    "their vote is open until ..." from "cast their result"; the link is governance_proposals.federation_ref, the same
    `<host trust domain>/<proposal id>` the local-vote and cast routes derive. A copy: the cache is never annotated."""
    from .. import models as m
    from sqlalchemy import select
    out = copy.deepcopy(doc)
    by_ref: Dict[str, Dict[str, Any]] = {}
    for h in out.get("hosts") or []:
        for p in h.get("proposals") or []:
            if isinstance(p, dict) and p.get("id"):
                by_ref[fb.federation_ref(h.get("trust_domain") or "", str(p["id"]))] = p
    rows = []
    if by_ref:
        rows = (await db.execute(select(m.GovernanceProposal.id, m.GovernanceProposal.end_timestamp,
                                        m.GovernanceProposal.federation_ref)
                                 .where(m.GovernanceProposal.federation_ref.in_(list(by_ref))))).all()
    now = fb.now_utc()
    for p in by_ref.values():
        p["local_vote"] = None
    for lid, end, ref in rows:
        if end is not None and end.tzinfo is None:
            end = end.replace(tzinfo=_dt.timezone.utc)
        by_ref[ref]["local_vote"] = {"local_proposal_id": lid, "ends_at": end.isoformat() if end else None,
                                     "open": bool(end and end > now)}
    return out


def _envelope(raw: Any) -> Optional[Dict[str, Any]]:
    """The signed ballot as the host received it ({ballot, alg, kid, signature}); the store keeps it as JSON text."""
    if isinstance(raw, dict):
        return raw
    try:
        v = json.loads(raw or "")
    except (TypeError, ValueError):
        return None
    return v if isinstance(v, dict) else None


@router.get("/api/v1/governance/federation/proposals/{proposal_id}/ballots",
            summary="The registry ballots on a federation proposal this registry hosts (developer or agent token)")
async def federation_proposal_ballots(proposal_id: str, actor: dict = Depends(security.get_current_actor_for_read),
                                      db: AsyncSession = Depends(get_db)):
    """
    Every ballot on a federation proposal this registry hosts, whole, with its signed envelope, so anyone signed in
    can check it against the casting registry's published card key (/.well-known/registry-jwks.json).
    `verified_at_receipt` is true for every row: the host verifies each ballot before storing it. Never cached. A
    proposal this registry does not hold answers 404 `not_hosted_here`, naming a host only when this registry sees
    the proposal in a frame peer's open list.

    \f
    §MCPTEST30 (V0557, to agentvault2-33's spec): every ballot WHOLE, its signed envelope included, so anyone signed in
    can check it against the casting registry's published card key (/.well-known/registry-jwks.json); a ballot is
    more than a claim only because of that signature, and it carries no secret (the basis holds aggregates).
    `verified_at_receipt` is true for every row: the host verified each ballot before its store took it, and an
    unverified ballot never reaches the store. Never cached: a ballot can land any second.
    A proposal this registry's store does not hold answers 404 not_hosted_here, naming a host only when this registry
    SEES the proposal in a frame peer's open list (a closed one is in no list, and a guessed host would be a claim
    this registry never observed).
    """
    try:
        uuid.UUID(proposal_id)
    except ValueError:
        return JSONResponse(status_code=422, content={"error": "bad_proposal_id",
                                                      "message": "a federation proposal id is a UUID."})
    me = fb.own_identity()
    st, p = await fb._es("GET", f"/proposals/{proposal_id}")
    if st == 404:
        seen = None
        open_doc = await federation_ballots_open(actor, db)
        for h in open_doc.get("hosts") or []:
            if h.get("host") != "self" and any(str(x.get("id")) == proposal_id for x in h.get("proposals") or []):
                seen = {"name": h.get("name"), "trust_domain": h.get("trust_domain")}
                break
        body: Dict[str, Any] = {"error": "not_hosted_here",
                                "message": "this registry's store does not hold this federation proposal."}
        if seen:
            body["host"] = seen
        return JSONResponse(status_code=404, content=body)
    if st != 200 or not isinstance(p, dict):
        return _refused(fb.BallotRefusal(502, "store_unreadable", f"the store answered {st}."))
    bst, bdoc = await fb._es("GET", f"/proposals/{proposal_id}/ballots")
    if bst != 200 or not isinstance(bdoc, dict):
        return _refused(fb.BallotRefusal(502, "store_unreadable", f"the store answered {bst} for the ballots."))
    ballots = [{"registry_id": b.get("registry_id"), "choice": b.get("choice"), "basis": b.get("basis"),
                "eligibility": b.get("eligibility"), "cast_at": b.get("cast_at"),
                "envelope": _envelope(b.get("ballot_jws")), "verified_at_receipt": True}
               for b in bdoc.get("ballots") or [] if isinstance(b, dict)]
    return {"proposal_id": proposal_id, "host": {"trust_domain": me["trust_domain"], "name": me["name"], "id": me["id"]},
            "ballot_mode": bool(p.get("ballot_mode")), "status": p.get("status"),
            "ballot_summary": p.get("ballot_summary"), "ballots": ballots}


@router.get("/api/v1/admin/federation/ballots/eligibility", summary="Who may cast a ballot here now (admin_platform)")
async def federation_ballot_eligibility(admin=Security(_ADMIN), db: AsyncSession = Depends(get_db)):
    return {"rule": fb.track_record_rule(), "registries": await fb.eligibility(db)}


async def _resolve_host(db: AsyncSession, host: str) -> Dict[str, str]:
    if (host or "self").strip().lower() in ("self", ""):
        me = fb.own_identity()
        return {"self": "1", "name": me["name"], "trust_domain": me["trust_domain"]}
    from .. import models as m
    from sqlalchemy import func, select
    rows = (await db.execute(select(m.PeerRegistry).where(func.lower(m.PeerRegistry.name) == host.strip().lower(),
                                                          func.upper(m.PeerRegistry.status) == "ACTIVE",
                                                          m.PeerRegistry.peer_type == "frame"))).scalars().all()
    if len(rows) != 1:
        raise fb.BallotRefusal(404, "unknown_host", f"no single ACTIVE frame peer named {host!r}.")
    ident = fb._row_identity(rows[0])
    return {"name": rows[0].name, "trust_domain": ident["trust_domain"]}


async def _host_open_proposal(db: AsyncSession, host: Dict[str, str], proposal_id: str) -> Dict[str, Any]:
    if host.get("self"):
        p = await fb.host_proposal(proposal_id)
        fb._assert_open(p)
        return p
    from ..services.exchange_passport import PassportError, peer_request
    try:
        st, doc = await peer_request(db, host["name"], "GET", "/api/v1/federation/governance/open")
    except PassportError as e:
        raise fb.BallotRefusal(502, "host_unreachable", str(e)[:200])
    p = next((x for x in (doc or {}).get("proposals", []) if str(x.get("id")) == str(proposal_id)), None) if st == 200 else None
    if p is None:
        raise fb.BallotRefusal(404, "proposal_not_open", "the host lists no open ballot proposal with this id.")
    return p


@router.post("/api/v1/admin/federation/ballots/local-vote", status_code=201,
             summary="Open the members' vote that decides this registry's ballot (admin_platform)")
async def federation_ballot_local_vote(body: LocalVoteIn, admin=Security(_ADMIN), db: AsyncSession = Depends(get_db)):
    from .. import models as m
    try:
        if not _membership.member_mode() or await _membership.network_points(db) <= 0:
            raise fb.BallotRefusal(409, "no_members", "this registry has no members to decide; its operator casts the "
                                                      "ballot (POST /api/v1/admin/federation/ballots with a choice).")
        host = await _resolve_host(db, body.host)
        p = await _host_open_proposal(db, host, body.proposal_id)
        host_end = _dt.datetime.fromisoformat(str(p["end_timestamp"]).replace("Z", "+00:00"))
        now = _dt.datetime.now(_dt.timezone.utc)
        end = min(now + _dt.timedelta(seconds=body.duration_seconds), host_end - _dt.timedelta(minutes=15))
        if end <= now + _dt.timedelta(minutes=30):
            raise fb.BallotRefusal(409, "too_late", "the federation proposal ends too soon for a members' vote; "
                                                    "the operator may still cast within its window.")
        me = fb.own_identity()
        ref = fb.federation_ref(host["trust_domain"], body.proposal_id)
        local = m.GovernanceProposal(
            proposer_did=me["id"], title=f"Federation ballot: {p.get('title') or body.proposal_id}"[:200],
            description=(f"This registry's one ballot in federation proposal {body.proposal_id} at "
                         f"{host['trust_domain']}. Members vote here; the result becomes the ballot "
                         f"(for, against, or abstain on a tie).\n\n{(p.get('description') or '')[:3000]}"),
            status="VOTING", proposal_type="federation_ballot", policy_diff=None, end_timestamp=end, federation_ref=ref)
        db.add(local)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            raise fb.BallotRefusal(409, "local_vote_exists", "a members' vote for this federation proposal exists.")
        await db.refresh(local)
    except fb.BallotRefusal as r:
        return _refused(r)
    return {"local_proposal_id": local.id, "federation_ref": ref, "ends_at": end.isoformat(),
            "host": host["trust_domain"], "proposal_id": body.proposal_id}


@router.post("/api/v1/admin/federation/ballots", status_code=201,
             summary="Cast this registry's ballot in a federation ballot proposal (admin_platform)")
async def federation_ballot_cast(body: CastIn, admin=Security(_ADMIN), db: AsyncSession = Depends(get_db)):
    try:
        host = await _resolve_host(db, body.host)
        await _host_open_proposal(db, host, body.proposal_id)
        ref = fb.federation_ref(host["trust_domain"], body.proposal_id)
        if _membership.member_mode() and await _membership.network_points(db) > 0:
            basis = await fb.member_basis(db, ref)
            if basis is None:
                raise fb.BallotRefusal(409, "members_must_vote", "this registry has members: open their vote first "
                                                                 "(POST /api/v1/admin/federation/ballots/local-vote).")
            choice = basis.pop("choice")
            if body.choice and body.choice != choice:
                raise fb.BallotRefusal(409, "members_decided", f"the members decided {choice}; the operator does not "
                                                               "override them.", members_decided=choice)
        else:
            if not body.choice:
                raise fb.BallotRefusal(422, "choice_required", "this registry has no members: the operator's choice "
                                                               "is the ballot (for, against or abstain).")
            choice, basis = body.choice, {"mode": "operator"}
        me = fb.own_identity()
        ballot = fb.build_ballot(proposal_id=body.proposal_id, host=host, voter=me, choice=choice, basis=basis)
        envelope = await fb.sign_ballot(db, ballot)
        if host.get("self"):
            judged = next(e for e in await fb.eligibility(db) if e["kind"] == "self")
            if not judged["eligible"]:
                raise fb.BallotRefusal(403, "not_eligible", "this registry may not cast a ballot here now.",
                                       reasons=judged["reasons"])
            stored = await fb.record_ballot(body.proposal_id, envelope, judged)
            _OPEN_CACHE["doc"] = None       # this worker's next read shows the ballot it just cast (§MCPTEST30)
            return {"recorded": True, "host": "self", "choice": choice, "basis": basis, "store": stored}
        from ..services.exchange_passport import PassportError, peer_request
        try:
            st, answer = await peer_request(db, host["name"], "POST", "/api/v1/federation/governance/ballots",
                                            {"envelope": envelope})
        except PassportError as e:
            raise fb.BallotRefusal(502, "host_unreachable", str(e)[:200])
        if st not in (200, 201):
            raise fb.BallotRefusal(st if 400 <= st < 600 else 502, "host_refused", "the host refused the ballot.",
                                   host_answer=answer)
        _OPEN_CACHE["doc"] = None
        return {"recorded": True, "host": host["name"], "choice": choice, "basis": basis, "host_answer": answer}
    except fb.BallotRefusal as r:
        return _refused(r)
