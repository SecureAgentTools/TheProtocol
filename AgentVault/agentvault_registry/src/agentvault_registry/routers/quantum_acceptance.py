"""V0660 (b): acceptance tests on Guild work orders and contracts v2 milestones (services/quantum_acceptance.py; the
receipt chain and the templates: services/quantum_receipts.py).

    POST /api/v1/quantum/acceptance                   the poster or the client names the acceptance test, before the run
    GET  /api/v1/quantum/acceptance/{rail}/{ref}      the agreement and the verdict recorded for it (public, as the
                                                      order's events are; hashes and the verdict only)
    POST /api/v1/quantum/verdicts                     a party hands in the receipt chain and the evidence; the registry
                                                      checks the chain and recomputes the verdict before it records it

No money moves here. The verdict decides whether the existing verify step (POST /api/v1/guild/orders/{oid}/verify) or
release step (POST /api/v1/contracts/v2/{cid}/milestones/{seq}/release) may settle. Every route answers only where
QUANTUM_WORKLOADS_MODE is shadow or on; under off they answer 403 with the switch's sentence, before the body or the path
is read, and are left out of the OpenAPI schema (main.py mounts this router with include_in_schema from the mode).
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry import models
from agentvault_registry.database import get_db
from agentvault_registry.routers.quantum_agent_cards import require_quantum_workloads_served
from agentvault_registry.security import get_current_agent
from agentvault_registry.services import quantum_acceptance as qa
from agentvault_registry.services import quantum_receipts as qr

logger = logging.getLogger(__name__)

class _SwitchFirstRoute(APIRoute):
    """Asks the switch before FastAPI parses the body or the path, so under off every request gets the switch's 403
    (a malformed body too), not a 422 that tells a caller the route is there."""

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def switch_first(request: Request):
            require_quantum_workloads_served()
            return await handler(request)
        return switch_first


router = APIRouter(prefix="/api/v1/quantum", tags=["Quantum workloads"], route_class=_SwitchFirstRoute,
                   dependencies=[Depends(require_quantum_workloads_served)])

Rail = Literal["guild_work_order", "contract_milestone"]


class AgreeIn(BaseModel):
    rail: Rail = Field(..., description="guild_work_order (a Guild work order) or contract_milestone (a contracts v2 "
                                        "milestone).")
    ref: str = Field(..., min_length=4, max_length=64, description="The order id (gwo_...) or the contract id (ctr_...).")
    seq: Optional[int] = Field(None, ge=1, le=100, description="The milestone's number, for a contract milestone.")
    agreement: Dict[str, Any] = Field(..., description="The acceptance test: template, problem (answer-check only), "
                                                       "params, the two error rates of a rung 2 test as decimal "
                                                       "strings, and optionally verifier and participants.")


class VerdictIn(BaseModel):
    rail: Rail
    ref: str = Field(..., min_length=4, max_length=64)
    seq: Optional[int] = Field(None, ge=1, le=100)
    chain: List[Dict[str, Any]] = Field(..., min_length=1, max_length=qr.MAX_STEPS,
                                        description="The receipt chain, from circuit_submitted to the verdict.")
    evidence: Dict[str, Any] = Field(..., description="What the template recomputes the verdict from (result, tests "
                                                      "and counts, or the repeat).")


def _rail_enabled(rail: str) -> None:
    """The rail's own switch, with its own sentence (a disabled rail settles nothing, so it agrees nothing)."""
    if rail == "guild_work_order":
        from agentvault_registry.routers.guild import _require_enabled
    else:
        from agentvault_registry.routers.contracts_v2 import _require_enabled
    _require_enabled()


def _seq_for(rail: str, seq: Optional[int]) -> Optional[int]:
    if rail == "contract_milestone" and seq is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="seq: a contract milestone is named by its number")
    if rail == "guild_work_order" and seq is not None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="seq: a work order has no milestones")
    return seq


async def _lock(db: AsyncSession, rail: str, ref: str, seq: Optional[int]) -> Dict[str, Any]:
    """The order, or the contract with the milestone, row-locked for this transaction (so two hand-ins record once)."""
    if rail == "guild_work_order":
        row = (await db.execute(text("SELECT * FROM guild_work_orders WHERE id = :r FOR UPDATE"),
                                {"r": ref})).mappings().first()
        if not row:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Order not found")
        return dict(row)
    c = (await db.execute(text("SELECT * FROM contracts WHERE id = :r"), {"r": ref})).mappings().first()
    if not c:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=(
            "Contract not found on this registry (a contract's acceptance test lives on its home registry)"))
    m = (await db.execute(text("SELECT * FROM contract_milestones WHERE contract_id = :r AND seq = :s FOR UPDATE"),
                          {"r": ref, "s": seq})).mappings().first()
    if not m:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Milestone not found")
    out = dict(c)
    out["_milestone"] = dict(m)
    return out


async def _record(db: AsyncSession, rail: str, ref: str, etype: str, actor: str, payload: Dict[str, Any]) -> None:
    if rail == "guild_work_order":
        from agentvault_registry.routers.guild import _audit, _next_seq
        await _audit(db, ref, await _next_seq(db, ref), etype, actor, payload)
    else:
        from agentvault_registry.services import contract_settlement as cs
        await cs.audit(db, ref, await cs.next_seq(db, ref), etype, actor, payload)


@router.post("/acceptance", summary="Name the acceptance test of a work order or a milestone, before the run")
async def agree(body: AgreeIn, agent: models.Agent = Depends(get_current_agent), db: AsyncSession = Depends(get_db)):
    """The party who pays names the acceptance test before any work is awarded or accepted: the poster of an open work
    order, or the client of a draft or offered contract for a pending milestone. The registry writes the work into the
    agreement (`work`: rail, ref and the milestone's seq) and records it once, in the rail's own event log, with its
    digest; the answer carries both, and the run's first receipt step names that digest. No money moves."""
    seq = _seq_for(body.rail, body.seq)
    _rail_enabled(body.rail)
    work = qa.work_of(body.rail, body.ref, seq)
    if "work" in body.agreement and body.agreement["work"] != work:
        named = json.dumps(body.agreement["work"], sort_keys=True, default=str)[:200]
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=(
            f"quantum_acceptance_invalid: work: the agreement names other work ({named}); this request agrees the "
            f"test of {json.dumps(work, sort_keys=True)}"))
    # the agreement as it is recorded: with the work it settles, so its digest names that work
    agreement = {**body.agreement, "work": work}
    problems = qr.check_agreement(agreement)
    if not problems and len(qr.canonical(agreement)) > qa.MAX_AGREEMENT_BYTES:
        problems = [f"the agreement is larger than {qa.MAX_AGREEMENT_BYTES} bytes"]
    if problems:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="quantum_acceptance_invalid: " + "; ".join(problems[:10]))
    pins = qr.pinned_keys(agreement)
    local = await qa.local_dids(db, pins)
    if local:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="quantum_acceptance_invalid: " + "; ".join(qa.pin_problems(local)[:10]))
    row = await _lock(db, body.rail, body.ref, seq)
    if body.rail == "guild_work_order":
        if row["poster_did"] != agent.did:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Only the poster names the acceptance test")
        if row["status"] != "open":
            raise HTTPException(status.HTTP_409_CONFLICT, detail=(
                f"Order is {row['status']}: an acceptance test is agreed before the work is awarded"))
        from agentvault_registry.routers.guild import _parse_eval_bounty
        if _parse_eval_bounty(row.get("spec") or ""):
            raise HTTPException(status.HTTP_409_CONFLICT, detail=(
                "this order settles by its eval bounty (its spec names one); it takes no second acceptance test"))
    else:
        if row["client_did"] != agent.did:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Only the client names the acceptance test")
        if row["status"] not in ("draft", "offered") or row.get("legacy_ruc_id") is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, detail=(
                f"Contract is {row['status']}: an acceptance test is agreed before the provider accepts"))
        if row["_milestone"].get("status") != "pending":
            raise HTTPException(status.HTTP_409_CONFLICT, detail=f"Milestone {seq} is {row['_milestone'].get('status')}")
    existing, _verdict = await qa.recorded(db, body.rail, body.ref, seq)
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=(
            f"quantum_acceptance_recorded: this {'milestone' if seq else 'order'} already has its acceptance test "
            f"({existing.get('template')}, {existing.get('acceptance_digest')})"))
    digest = qr.digest_of(agreement)
    payload: Dict[str, Any] = {"acceptance_digest": digest, "template": agreement["template"],
                               "rung": qr.TEMPLATES[agreement["template"]]["rung"], "agreement": agreement}
    if seq is not None:
        payload["milestone"] = seq
    await _record(db, body.rail, body.ref, qa.AGREED_EVENT, agent.did, payload)
    await db.commit()
    logger.info("[QUANTUM] %s %s%s: acceptance test %s agreed by %s (%s)", body.rail, body.ref,
                f" m{seq}" if seq else "", payload["template"], agent.did, digest)
    return {"rail": body.rail, "ref": body.ref, "seq": seq, "acceptance_digest": digest,
            "template": payload["template"], "rung": payload["rung"], "agreement": agreement}


@router.get("/acceptance/{rail}/{ref}", summary="The acceptance test of a work order or a milestone, and its verdict")
async def read_acceptance(rail: Rail = Path(...), ref: str = Path(..., min_length=4, max_length=64),
                          seq: Optional[int] = Query(None, ge=1, le=100), db: AsyncSession = Depends(get_db)):
    """The agreement (so a verifier, and a buyer checking offline, holds the exact bytes the run was bound to) and the
    verdict recorded under it: hashes and the verdict, never circuits, counts or results. Public, as an order's events
    are."""
    seq = _seq_for(rail, seq)
    agreement, verdict = await qa.recorded(db, rail, ref, seq)
    if agreement is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=(
            f"no_quantum_acceptance: {ref}{f' milestone {seq}' if seq else ''} has no acceptance test on this registry"))
    return {"rail": rail, "ref": ref, "seq": seq, "acceptance_digest": agreement.get("acceptance_digest"),
            "template": agreement.get("template"), "rung": agreement.get("rung"),
            "agreement": agreement.get("agreement"), "verdict": verdict}


@router.post("/verdicts", summary="Hand in a job's receipt chain and evidence; the registry checks it and records "
                                  "the verdict")
async def hand_in_verdict(body: VerdictIn, agent: models.Agent = Depends(get_current_agent),
                          db: AsyncSession = Depends(get_db)):
    """A party to delivered work (the poster or the worker of a submitted order; the client or the provider of a
    submitted milestone) hands in the chain and the evidence. The registry checks who signed each step against the
    parties of record (services/quantum_acceptance.role_problems), every step's link, signature and key (registered here
    for its participant, or pinned in the agreement for a DID that is not an agent here), that the agreement names
    this work, and recomputes the verdict under the agreement;
    the verifier's signed verdict must be that one. It records hashes and the verdict, once per agreement, and the
    verify or release step then settles on it. No money moves here."""
    seq = _seq_for(body.rail, body.seq)
    _rail_enabled(body.rail)
    try:
        size = len(json.dumps({"chain": body.chain, "evidence": body.evidence}, separators=(",", ":")))
    except (TypeError, ValueError):
        size = qa.MAX_SUBMISSION_BYTES + 1
    if size > qa.MAX_SUBMISSION_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            detail=f"the chain and the evidence are larger than {qa.MAX_SUBMISSION_BYTES} bytes")
    row = await _lock(db, body.rail, body.ref, seq)
    if body.rail == "guild_work_order":
        parties, state, wanted = (row["poster_did"], row.get("worker_did")), row["status"], "submitted"
    else:
        parties, state, wanted = (row["client_did"], row.get("provider_did")), row["_milestone"].get("status"), \
            "submitted"
    if agent.did not in parties:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Only a party to the work hands in its verdict")
    if state != wanted:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"The work is {state}: a verdict follows its delivery")
    recorded_agreement, verdict = await qa.recorded(db, body.rail, body.ref, seq)
    if recorded_agreement is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="no_quantum_acceptance: this work has no acceptance test")
    if verdict is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=(
            f"quantum_verdict_recorded: a verdict is recorded for this acceptance test (passed="
            f"{str(verdict.get('passed')).lower()}); one run settles it"))
    agreement = recorded_agreement.get("agreement")
    repeat = body.evidence.get("repeat_chain") if isinstance(body.evidence, dict) else None
    problems = qa.role_problems(agreement, body.chain, body.evidence, payer=parties[0], worker=parties[1])
    problems += qa.pin_problems(await qa.local_dids(db, qr.pinned_keys(agreement or {})))
    if not problems:
        keys = await qa.registered_keys(db, qr.participants_of(body.chain, repeat))
        report = qr.check_job(agreement, body.chain, body.evidence, keys=keys,
                              work=qa.work_of(body.rail, body.ref, seq))
        problems = report.problems
    if problems:
        await db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="quantum_receipt_refused: " + "; ".join(problems[:10])
                            + (f" (and {len(problems) - 10} more)" if len(problems) > 10 else ""))
    payload = report.verdict()
    if seq is not None:
        payload["milestone"] = seq
    await _record(db, body.rail, body.ref, qa.VERDICT_EVENT, agent.did, payload)
    await db.commit()
    logger.info("[QUANTUM] %s %s%s: verdict recorded passed=%s (%s, head %s)", body.rail, body.ref,
                f" m{seq}" if seq else "", report.passed, report.template, payload.get("head"))
    return {"recorded": True, "rail": body.rail, "ref": body.ref, "seq": seq, **report.as_dict()}
