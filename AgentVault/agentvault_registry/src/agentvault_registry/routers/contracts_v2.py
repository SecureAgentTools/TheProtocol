"""THE CONTRACT SPINE — router (P2/P3, 2026-07-25 · SPEC_2026-07-25_CONTRACT_SPINE_V2).

A contract is a typed, ESCROWED-AT-AGREED, MILESTONED agreement between two agents — the settlement
object every origination surface mints into: direct bilateral, agent-discovery "Engage" (this
file), THE GUILD (mirror hooks in guild.py), and templates (contract_templates.py). Replaces the
RUC, whose fatal flaw was money first touched AFTER the work; the old /contracts/* routes live on
as a thin adapter over this spine.

Money: the SHARED escrow rail only (services/escrow.py → TEG treasury, `ctrref:{cid}:{leg}`,
zero-sum, Δ=0 by construction, rule-13). Ordering doctrine on every money move: CLAIM the status
transition first (guarded UPDATE, committed), THEN the leg — a racer sees the claimed status and
cannot re-pay; the TEG durable rail (Idempotency-Key == ref) is the crash backstop that lets the
reaper re-drive exactly-once. `total_amount == 0` = agreement-only (MOU/NDA/framework form):
identical lifecycle, no escrow, no legs — the institutional capability (§P4.5).

Lifecycle: draft → offered → agreed → in_progress → completed | disputed | cancelled | expired
Gated CONTRACTS_V2_ENABLED (default OFF fleet-wide; frame-c canary). Reads never emit (I-C8).
"""
import datetime as _dt
import json
import logging
import os
import secrets
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Security, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry import models
from agentvault_registry.database import get_db
from agentvault_registry.security import (
    admin_credential, get_current_agent, get_current_developer, get_current_actor_for_read,
    require_agent_permission, enforce_agent_spend,
)
from agentvault_registry.services import escrow
from agentvault_registry.services import contract_settlement as cs
from agentvault_registry.services import liability as liab
from agentvault_registry.services import reputation_bond as _rb
from agentvault_registry.services import enforcement_propagation as _ep  # §ENFPROP

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Contracts v2"])

_Q = Decimal("0.0000000001")
_FRAME_CCY = (os.environ.get("FRAME_CURRENCY", "AVT") or "AVT").strip().upper() or "AVT"
CONTRACT_TYPES = {"work_order", "service", "license", "retainer", "custom"}
_MAX_MILESTONES = 50
_MAX_TERMS_BYTES = 100_000


def contracts_v2_enabled() -> bool:
    return os.getenv("CONTRACTS_V2_ENABLED", "false").strip().lower() == "true"


def _require_enabled():
    if not contracts_v2_enabled():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="The contract spine is disabled on this registry")


def _fee_bps() -> int:
    try:
        return max(0, min(2000, int(os.getenv("CONTRACT_FEE_BPS", "0"))))
    except ValueError:
        return 0


def _dec(v, field: str) -> Decimal:
    try:
        d = Decimal(str(v)).quantize(_Q)
    except (InvalidOperation, TypeError, ValueError):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{field}: not a number")
    if d < 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{field}: must be >= 0")
    return d


def _validate_terms(terms: Optional[dict]) -> Optional[dict]:
    """Size cap + the §P4.5 annex convention: attachments ride as {name,url,sha256} REFERENCES
    (the document itself stays in the client's DMS/ERP; the hash is pinned in the agreement)."""
    if terms is None:
        return None
    if not isinstance(terms, dict):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="terms must be an object")
    if len(json.dumps(terms, default=str)) > _MAX_TERMS_BYTES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="terms too large (100KB cap)")
    atts = terms.get("attachments")
    if atts is not None:
        if not isinstance(atts, list) or len(atts) > 50:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="attachments: list of <=50")
        for a in atts:
            if (not isinstance(a, dict) or not a.get("name") or not a.get("url")
                    or not isinstance(a.get("sha256"), str) or len(a["sha256"]) != 64):
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="each attachment needs {name, url, sha256(64-hex)} — documents ride as references")
    return terms


# ── the shared minting core (used by create / engage / templates.instantiate / RUC adapter) ──

async def mint_contract(
    db: AsyncSession, *, client_did: str, title: str, total_amount: Decimal,
    contract_type: str = "work_order", terms: Optional[dict] = None,
    currency: Optional[str] = None, milestones: Optional[List[dict]] = None,
    provider_did: Optional[str] = None, deadline_seconds: Optional[int] = None,
    offer_expires_seconds: Optional[int] = None, draft: bool = False,
    origin_surface: str = "direct", origin_ref: Optional[str] = None,
    template_version_id: Optional[str] = None, template_royalty_bps: Optional[int] = None,
    template_price_paid: Optional[Decimal] = None,
    fee_bps: Optional[int] = None, legacy_ruc_id: Optional[int] = None,
    counterparty_home_registry: Optional[str] = None,
    actor_did: Optional[str] = None, request: Optional[Request] = None,
    enforce_spend: bool = True,
) -> dict:
    """Validate + insert a contract with its milestones (I-C6: Σ == total). NO money moves here —
    escrow fires at accept (I-C4). The IRONKEY spend caveat fires HERE for client-authored offers
    (the client is the actor committing the amount)."""
    from agentvault_registry.input_validators import validate_safe_text
    title = validate_safe_text(title, "title")[:200]
    if not title.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="title required")
    if contract_type not in CONTRACT_TYPES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=f"contract_type must be one of {sorted(CONTRACT_TYPES)}")
    ccy = (currency or _FRAME_CCY).strip().upper()
    if ccy != _FRAME_CCY:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=f"currency must be this frame's settlement currency ({_FRAME_CCY})")
    terms = _validate_terms(terms)
    total = total_amount.quantize(_Q)
    if provider_did and provider_did == client_did:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="client and provider must differ")

    # milestones: validate or synthesize exactly one (uniform release path, incl. zero-total)
    ms = milestones or [{"title": "Full delivery", "amount": str(total)}]
    if len(ms) > _MAX_MILESTONES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"max {_MAX_MILESTONES} milestones")
    norm, msum = [], Decimal("0")
    for i, m in enumerate(ms, start=1):
        amt = _dec(m.get("amount", 0), f"milestones[{i}].amount")
        mtitle = validate_safe_text(str(m.get("title") or f"Milestone {i}"), "milestone.title")[:200]
        due = None
        if m.get("due_seconds"):
            due = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(seconds=int(m["due_seconds"]))
        norm.append({"seq": i, "title": mtitle, "amount": amt,
                     "terms": m.get("terms") if isinstance(m.get("terms"), dict) else None, "due_at": due})
        msum += amt
    if msum != total:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=f"milestone amounts must sum EXACTLY to total_amount ({msum} != {total})")

    if enforce_spend and total > 0:
        await enforce_agent_spend(db, client_did, total, currency=ccy,
                                  counterparty_did=provider_did, request=request)

    cid = "ctr_" + secrets.token_hex(12)
    now = _dt.datetime.now(_dt.timezone.utc)
    deadline = now + _dt.timedelta(seconds=deadline_seconds) if deadline_seconds else None
    if not draft:
        if offer_expires_seconds is not None:
            ttl = offer_expires_seconds
        else:
            # §ORGPOLICY: an org can set its own default offer expiry for its agents' contracts.
            from agentvault_registry.services import org_policy
            _os = await org_policy.get_org_settings(db, client_did)
            _days = _os.get("contract_offer_ttl_days")
            ttl = (int(_days) if isinstance(_days, int) and _days > 0
                   else int(os.getenv("CONTRACT_OFFER_TTL_DAYS", "30"))) * 86400
        offer_expires = now + _dt.timedelta(seconds=ttl) if ttl > 0 else None
    else:
        offer_expires = None
    st = "draft" if draft else "offered"

    await db.execute(text("""
        INSERT INTO contracts (id, legacy_ruc_id, contract_type, origin_surface, origin_ref,
            client_did, provider_did, title, terms, currency, total_amount, fee_bps,
            template_version_id, template_royalty_bps, template_price_paid,
            status, deadline, offer_expires_at, counterparty_home_registry, updated_at)
        VALUES (:id,:lr,:ct,:os,:orf,:cd,:pd,:t,CAST(:tm AS JSONB),:cy,:ta,:fb,:tv,:tr,:tp,
                :st,:dl,:oe,:hr, now())
    """), {"id": cid, "lr": legacy_ruc_id, "ct": contract_type, "os": origin_surface,
           "orf": origin_ref, "cd": client_did, "pd": provider_did, "t": title,
           "tm": json.dumps(terms) if terms is not None else None, "cy": ccy, "ta": total,
           "fb": _fee_bps() if fee_bps is None else max(0, min(2000, int(fee_bps))),
           "tv": template_version_id, "tr": template_royalty_bps, "tp": template_price_paid,
           "st": st, "dl": deadline, "oe": offer_expires, "hr": counterparty_home_registry})
    for m in norm:
        await db.execute(text("""
            INSERT INTO contract_milestones (id, contract_id, seq, title, terms, amount, due_at)
            VALUES (:id,:c,:s,:t,CAST(:tm AS JSONB),:a,:d)
        """), {"id": "ctm_" + secrets.token_hex(12), "c": cid, "s": m["seq"], "t": m["title"],
               "tm": json.dumps(m["terms"]) if m["terms"] else None, "a": m["amount"], "d": m["due_at"]})
    await cs.audit(db, cid, 1, "created", actor_did or client_did,
                   {"origin": origin_surface, "type": contract_type, "total": str(total),
                    "currency": ccy, "milestones": len(norm), "provider": provider_did})
    if st == "offered":
        await cs.audit(db, cid, 2, "offered", actor_did or client_did, {})
    await db.commit()

    c = await cs.load_contract(db, cid)
    if st == "offered":
        cs.emit("ContractOffered", cid, {"client": client_did, "provider": provider_did,
                                         "total": str(total), "currency": ccy, "origin": origin_surface})
        cs.webhook("contract.offered", c)
    logger.info("[CONTRACT] %s minted by %s origin=%s total=%s %s status=%s",
                cid, client_did, origin_surface, total, ccy, st)
    return c


# ── schemas (inline, guild precedent) ────────────────────────────────────────────────────────

class MilestoneIn(BaseModel):
    title: Optional[str] = Field(None, max_length=200)
    amount: Any = Field(0)
    terms: Optional[Dict[str, Any]] = None
    due_seconds: Optional[int] = Field(None, ge=60, le=366 * 86400)


class ContractCreateIn(BaseModel):
    title: str = Field(..., max_length=200)
    contract_type: str = Field("work_order", max_length=32)
    terms: Optional[Dict[str, Any]] = None
    total_amount: Any = Field(0)
    currency: Optional[str] = Field(None, max_length=12)
    milestones: Optional[List[MilestoneIn]] = None
    provider_did: Optional[str] = Field(None, max_length=120)  # set = private offer; NULL = open
    deadline_seconds: Optional[int] = Field(None, ge=60, le=366 * 86400)
    offer_expires_seconds: Optional[int] = Field(None, ge=60, le=366 * 86400)
    draft: bool = False


class SubmitIn(BaseModel):
    deliverable: Optional[Dict[str, Any]] = None


class ReleaseIn(BaseModel):
    stars: Optional[int] = Field(None, ge=1, le=5)


class RejectIn(BaseModel):
    reason: Optional[str] = Field(None, max_length=500)


class ResolveIn(BaseModel):
    provider_pct: int = Field(..., ge=0, le=100)
    note: Optional[str] = Field(None, max_length=500)


class EngageIn(BaseModel):
    total_amount: Optional[Any] = None          # override the card's price (else card price)
    message: Optional[str] = Field(None, max_length=2000)
    deadline_seconds: Optional[int] = Field(None, ge=60, le=366 * 86400)
    # §DEALTHREADS — open (or reuse) the client↔provider DM and post the offer
    # card into it. DEFAULT OFF (Commander's call): an offer is a decision, and
    # so is the conversation. Nothing else about the offer changes.
    open_thread: bool = False


# ── lifecycle ────────────────────────────────────────────────────────────────────────────────

async def _party_of_record(db: AsyncSession, agent, request) -> str:
    """§SUBAGENT-LIABILITY (D6-274): the party of record for the caller. A walletless HAND (an anchored child presenting
    its anchored birth token) acts for its wallet-holding principal, so the principal is the client or the provider a
    contract books and compares; anyone else is themself. The same seam the legacy create and accept and this router's
    release use (services/spawn_anchor.resolve_spend_purse_agent, which also records the hand as evidence); byte-inert
    when the anchor is off or no anchored hand acted. Before this, create, offer, accept, submit, reject, cancel and
    engage here compared and booked the hand itself, and create, accept and engage asked no liability gate for the
    principal a hand binds."""
    from agentvault_registry.services.spawn_anchor import resolve_spend_purse_agent
    await _hand_capability(db, agent, request)
    _purse, did = await resolve_spend_purse_agent(db, agent, request)
    return did


async def _hand_capability(db: AsyncSession, agent, request) -> None:
    """D6-274 (V0639): resolve the X-Capability-Token a caller presents on a route that asks no permission. Only
    require_agent_permission resolved it (onto request.state.ironkey_capability, which spawn_anchor reads), so behind
    get_current_agent (offer, submit, release, reject, cancel) and the detail read a hand was itself: since V0638 books
    its principal, it was no party to the contract it had just made (measured on sbx-alpha 2026-10-24 19:45Z: create
    200 for the principal, then cancel and read 403 "Not a party to this contract"), and the release's hand path
    (§SUBAGENT-LIABILITY P1/P2, with its liability gate) had never run. Resolved here exactly as
    require_agent_permission resolves it (the same modes; resolve_capability: held by this caller, live, its caveats
    intersected with the issuer's current authority), and kept only when it carries contracts.engage, the permission
    create, accept and engage ask: a hand acts for its principal on these routes only while its token lets it engage.
    A token that does not resolve leaves the caller itself (fail-closed to self, as spawn_anchor); never raises."""
    state = getattr(request, "state", None)
    if state is None or getattr(state, "ironkey_capability", None) is not None:
        return
    headers = getattr(request, "headers", None)
    tok = headers.get("X-Capability-Token") if headers is not None else None
    if not tok or not tok.startswith("att_"):
        return
    try:
        from agentvault_registry.agent_authz import agent_delegation_mode, agent_rbac_mode
        if agent_rbac_mode() == "off" or agent_delegation_mode() == "off":
            return   # require_agent_permission resolves no token in these modes either
        from agentvault_registry.agent_delegation import resolve_capability
        cap, reason = await resolve_capability(db, tok, agent.did)
    except Exception as exc:  # noqa: BLE001 - a resolver error leaves the caller itself, never a 500
        logger.warning("[D6-274] capability resolve failed did=%s: %r", getattr(agent, "did", "?"), exc)
        return
    if cap is None:
        logger.info("[D6-274] capability not resolved did=%s reason=%s: the caller acts as itself",
                    getattr(agent, "did", "?"), reason)
        return
    if "contracts.engage" not in (cap.get("permissions") or ()):
        logger.info("[D6-274] capability %s carries no contracts.engage: did=%s acts as itself",
                    cap.get("id"), getattr(agent, "did", "?"))
        return
    state.ironkey_capability = cap


async def _read_party(db: AsyncSession, actor: dict, request) -> Optional[str]:
    """The party an AGENT reader reads as (D6-274): itself, or the principal its anchored birth token acts for."""
    if actor.get("kind") != "agent" or not actor.get("agent_did"):
        return None
    import types as _types
    return await _party_of_record(db, _types.SimpleNamespace(did=actor["agent_did"]), request)


@router.post("/api/v1/contracts/v2", summary="Create a contract (client-authored offer)")
async def create_contract_v2(body: ContractCreateIn, request: Request,
                             agent: models.Agent = Security(require_agent_permission("contracts.engage")),
                             db: AsyncSession = Depends(get_db)):
    _require_enabled()
    # §TWOAGENT (2026-09-23) — a provider homed on ANOTHER registry is routed exactly as /engage routes it, or
    # refused with /engage's reason. This path never passed `counterparty_home_registry`, so an offer to a foreign
    # provider minted here with no replica at the provider's home: measured EU -> ASIA, 200 `offered`, no row in
    # ASIA's contract_replicas 25 s later — an offer the provider can never see or accept (the stranded offer
    # §HIRECOHERE's 409 exists to prevent, reached through the other door). A DID with no card here keeps the
    # old behaviour (the mint decides).
    counterparty_home = None
    if body.provider_did:
        try:
            _card, _nm, _src, _src_name = await _load_card(db, body.provider_did)
        except HTTPException:
            _src, _src_name = None, None
            # §TWOAGENT R-16 (2026-09-23): no active card AND no agent here means nobody can ever see this offer, let
            # alone accept it (measured on the sandbox: a create to such a DID answered 200 `offered`). Refuse it.
            if not (await db.execute(text("SELECT 1 FROM agents WHERE did = :d"), {"d": body.provider_did})).first():
                raise HTTPException(
                    status.HTTP_404_NOT_FOUND,
                    detail=("No agent with this DID is known on this registry (no card here, and no mirror of one "
                            "homed elsewhere), so an offer to it could never be seen or accepted. Check the DID: "
                            "discoverAgents finds the agents this registry knows."))
        if _src is not None:
            counterparty_home, _reason = await _foreign_contract_home(db, _src, _src_name)
            if not counterparty_home:
                raise HTTPException(status.HTTP_409_CONFLICT, detail=_reason)
    client_did = await _party_of_record(db, agent, request)
    total = _dec(body.total_amount, "total_amount")
    if client_did != agent.did:  # a walletless hand is binding its principal: the principal is gated (legacy create)
        await liab.check_liability_gate(db, client_did, "contracts.engage", action_ref="contract-create",
                                        amount=total, currency=_FRAME_CCY,   # mint_contract refuses any other
                                        counterparty_did=body.provider_did, acting_hand_did=agent.did,
                                        presence=liab.presence_from_request(request),
                                        counterparty_home_registry=counterparty_home)
    c = await mint_contract(
        db, client_did=client_did, title=body.title, total_amount=total,
        contract_type=body.contract_type, terms=body.terms, currency=body.currency,
        milestones=[m.model_dump() for m in body.milestones] if body.milestones else None,
        provider_did=body.provider_did, deadline_seconds=body.deadline_seconds,
        offer_expires_seconds=body.offer_expires_seconds, draft=body.draft,
        origin_surface="direct", counterparty_home_registry=counterparty_home,
        actor_did=agent.did, request=request)
    return _contract_out(c)


@router.post("/api/v1/contracts/v2/{cid}/offer", summary="Publish a draft (client)")
async def offer_contract(cid: str, request: Request = None, agent: models.Agent = Depends(get_current_agent),
                         db: AsyncSession = Depends(get_db)):
    _require_enabled()
    c = await _must_load(db, cid)
    if c["client_did"] not in (agent.did, await _party_of_record(db, agent, request)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Only the client can offer")
    ttl = int(os.getenv("CONTRACT_OFFER_TTL_DAYS", "30")) * 86400
    res = await db.execute(text(
        "UPDATE contracts SET status='offered', offer_expires_at=now() + make_interval(secs => :t), "
        "updated_at=now() WHERE id=:c AND status='draft'"), {"c": cid, "t": ttl})
    if getattr(res, "rowcount", 0) == 0:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"Contract is {c['status']}, not draft")
    await cs.audit(db, cid, await cs.next_seq(db, cid), "offered", agent.did, {})
    await db.commit()
    c = await cs.load_contract(db, cid)
    cs.emit("ContractOffered", cid, {"client": c["client_did"], "total": str(c["total_amount"])})
    cs.webhook("contract.offered", c)
    return _contract_out(c)


@router.post("/api/v1/contracts/v2/{cid}/accept",
             summary="Accept an offer (provider); this escrows the client's funds")
async def accept_contract_v2(cid: str, request: Request,
                             agent: models.Agent = Security(require_agent_permission("contracts.engage")),
                             db: AsyncSession = Depends(get_db)):
    _require_enabled()
    # §TWOAGENT G2 (2026-09-23): a contract offered from ANOTHER frame lives here only as a replica. The provider acts
    # on its own registry, which gates it (it is local here) and couriers the command to the contract's home.
    provider_did = await _party_of_record(db, agent, request)   # D6-274: a hand accepts for its principal
    rep = await _replica_row(db, cid)
    c = None
    if rep is None:
        c = await _must_load(db, cid)
        if c["client_did"] in (agent.did, provider_did):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="A client cannot accept their own contract")
    # §REPBOND — accepting as the provider is a provider act: the bond gate applies (to the provider of record).
    await _rb.gate(db, provider_did, site="contract_accept")
    await _ep.gate(db, provider_did, site="contract_accept")
    if provider_did != agent.did:  # a hand is agreeing to deliver for its principal: gate the principal (legacy accept)
        src = c or rep
        await liab.check_liability_gate(db, provider_did, "contracts.engage", action_ref=f"contract-accept:{cid}",
                                        amount=src.get("total_amount") or 0,
                                        currency=src.get("currency") or _FRAME_CCY,
                                        counterparty_did=src.get("client_did"),
                                        counterparty_home_registry=(c or {}).get("counterparty_home_registry"),
                                        acting_hand_did=agent.did,
                                        presence=liab.presence_from_request(request))
    if rep is not None:
        return await _relay_to_home(db, rep, provider_did, "offer.accept", cid=cid)
    return _contract_out(await accept_as(db, cid, provider_did))


async def accept_as(db: AsyncSession, cid: str, provider_did: str) -> dict:
    """The provider's ACCEPT, applied at the frame that holds the escrow: claim offered→agreed, then escrow the
    client's funds. Called by the local route (after the provider's own authentication and gates) and by the
    cross-frame relay (§TWOAGENT G2, routers/contract_federation.py: the provider's own registry authenticated and
    gated its agent and couriered the command; the gates run again there against the provider's mirrored card)."""
    c = await _must_load(db, cid)
    if c["client_did"] == provider_did:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="A client cannot accept their own contract")
    if c["provider_did"] and c["provider_did"] != provider_did:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="This offer names a different provider")
    was_open = c["provider_did"] is None
    # CLAIM offered→agreed FIRST (guarded+committed) — only one accepter wins; money moves after.
    res = await db.execute(text(
        "UPDATE contracts SET status='agreed', provider_did=:p, agreed_at=now(), updated_at=now() "
        "WHERE id=:c AND status='offered' AND (provider_did IS NULL OR provider_did=:p)"),
        {"c": cid, "p": provider_did})
    if getattr(res, "rowcount", 0) == 0:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Offer is no longer open")
    await cs.audit(db, cid, await cs.next_seq(db, cid), "agreed", provider_did, {"open_offer": was_open})
    await db.commit()

    total = Decimal(str(c["total_amount"]))
    if total > 0:
        try:
            await escrow.escrow_deposit(c["client_did"], total, f"ctrref:{cid}:hold",
                                        reason="contract_escrow")
            await db.execute(text(
                "UPDATE contracts SET escrow_ref=:r, updated_at=now() WHERE id=:c"),
                {"r": f"ctrref:{cid}", "c": cid})
            await cs.audit(db, cid, await cs.next_seq(db, cid), "escrowed", None,
                           {"amount": str(total), "ref": f"ctrref:{cid}:hold"})
            await db.commit()
        except escrow.EscrowError as e:
            # guarded revert: the claim is ours, nobody else could advance past 'agreed'
            await db.execute(text(
                "UPDATE contracts SET status='offered', provider_did=CASE WHEN :open THEN NULL "
                "ELSE provider_did END, agreed_at=NULL, updated_at=now() "
                "WHERE id=:c AND status='agreed' AND escrow_ref IS NULL"),
                {"c": cid, "open": was_open})
            await cs.audit(db, cid, await cs.next_seq(db, cid), "escrow_failed", provider_did,
                           {"error": e.message[:300]})
            await db.commit()
            from agentvault_registry.services.ledger_unavailable import refusal_from_error  # §LEDGERGATE (V0598)
            raise refusal_from_error(e) or HTTPException(
                status.HTTP_402_PAYMENT_REQUIRED, detail=f"Escrow failed (client has insufficient balance?): {e.message}")
    # P4: a template's usage_count counts REAL agreements, not clicks
    if c.get("template_version_id"):
        await db.execute(text("""
            UPDATE contract_templates SET usage_count = usage_count + 1, updated_at=now()
            WHERE id = (SELECT template_id FROM contract_template_versions WHERE id=:v)
        """), {"v": c["template_version_id"]})
        await db.commit()
    c = await cs.load_contract(db, cid)
    cs.emit("ContractAgreed", cid, {"client": c["client_did"], "provider": provider_did,
                                    "total": str(total), "currency": c["currency"],
                                    "escrowed": bool(c.get("escrow_ref"))})
    cs.webhook("contract.agreed", c)
    # §DEALTHREADS — accepted card into an EXISTING deal thread only (post-commit, best-effort)
    from agentvault_registry.services import deal_thread_events as dte
    await dte.post_accepted(db, c)
    return c


@router.post("/api/v1/contracts/v2/{cid}/milestones/{seq}/submit",
             summary="Deliver a milestone (provider)")
async def submit_milestone(cid: str, seq: int, body: SubmitIn, request: Request = None,
                           agent: models.Agent = Depends(get_current_agent),
                           db: AsyncSession = Depends(get_db)):
    _require_enabled()
    party = await _party_of_record(db, agent, request)   # D6-274: a hand delivers for its principal
    rep = await _replica_row(db, cid)
    if rep is not None:  # §TWOAGENT G2: the contract lives on another frame; courier the delivery there
        actor = agent.did if rep.get("provider_did") == agent.did else party
        return await _relay_to_home(db, rep, actor, "milestone.submit", cid=cid,
                                    payload={"seq": seq, "deliverable": body.deliverable or {}})
    c = await _must_load(db, cid)
    actor = agent.did if c["provider_did"] == agent.did else party
    return await submit_as(db, cid, seq, actor, body.deliverable or {})


async def submit_as(db: AsyncSession, cid: str, seq: int, provider_did: str, deliverable: dict) -> dict:
    """The provider's DELIVERY of a milestone, applied at the contract's home (local route and §TWOAGENT G2 relay)."""
    c = await _must_load(db, cid)
    if c["provider_did"] != provider_did:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Only the provider can submit")
    if c["status"] not in ("agreed", "in_progress"):
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"Contract is {c['status']}")
    lowest = (await db.execute(text(
        "SELECT MIN(seq) FROM contract_milestones WHERE contract_id=:c AND status='pending'"),
        {"c": cid})).scalar()
    if lowest is None or int(lowest) != seq:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail=f"Milestones release in order — next submittable is {lowest}")
    res = await db.execute(text(
        "UPDATE contract_milestones SET status='submitted', submitted_at=now(), "
        "deliverable=CAST(:d AS JSONB) WHERE contract_id=:c AND seq=:s AND status='pending'"),
        {"c": cid, "s": seq, "d": json.dumps(deliverable or {})})
    if getattr(res, "rowcount", 0) == 0:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Milestone is no longer pending")
    await db.execute(text(
        "UPDATE contracts SET status='in_progress', updated_at=now() WHERE id=:c AND status='agreed'"),
        {"c": cid})
    await cs.audit(db, cid, await cs.next_seq(db, cid), "milestone_submitted", provider_did, {"seq": seq})
    await db.commit()
    cs.emit("ContractMilestoneSubmitted", cid, {"seq": seq, "by": provider_did})
    cs.webhook("contract.milestone_submitted", c, {"seq": seq})
    # §DEALTHREADS — the delivery card (existing thread only; best-effort)
    from agentvault_registry.services import deal_thread_events as dte
    mtitle = (await db.execute(text(
        "SELECT title FROM contract_milestones WHERE contract_id=:c AND seq=:s"),
        {"c": cid, "s": seq})).scalar()
    await dte.post_milestone(db, c, seq, title=mtitle)
    return {"ok": True, "contract_id": cid, "seq": seq, "status": "submitted"}


@router.post("/api/v1/contracts/v2/{cid}/milestones/{seq}/release",
             summary="Approve + pay a milestone from escrow (client)")
async def release_milestone(cid: str, seq: int, body: ReleaseIn, request: Request,
                            agent: models.Agent = Depends(get_current_agent),
                            db: AsyncSession = Depends(get_db)):
    _require_enabled()
    c = await _must_load(db, cid)
    # §SUBAGENT-LIABILITY P1/P2 — a walletless HAND may release for its principal-client (the contract
    # is booked under the wallet-holding principal, so client_did is the principal). Resolve the acting
    # party's principal; byte-INERT when the anchor is off / no hand acted (party_did == agent.did).
    party_did = await _party_of_record(db, agent, request)   # D6-274 (V0639): the token resolved here too
    if c["client_did"] not in (agent.did, party_did):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Only the client can release")
    # §SUBAGENT-LIABILITY gate — fires ONLY when a HAND releases for its principal. A walletless hand
    # paying out a milestone must have its principal (the client of record) human-underwritten
    # (enforce → 403, shadow → log, off → no-op). A NORMAL agent releasing its OWN contract is never
    # gated (party_did == agent.did): enforce here means only "a hand needs its human's mandate", so
    # ordinary contract flows are untouched. Graduated autonomy: a hand's release at/above
    # LIABILITY_PRESENCE_THRESHOLD_AVT steps up to a live presence proof. Pre-claim on purpose: an
    # enforce-block leaves the milestone untouched; the acting hand is evidence. (This deliberately
    # scopes the original Cockpit "every release needs a liable human" gate down to hands-only; a full
    # Cockpit-Card ratchet can re-widen it later — a Commander decision.)
    _m0 = await cs.load_milestone(db, cid, seq)
    if party_did != agent.did:
        # §FACTS2 — the summary the human signs names its UNIT and its COUNTERPARTY.
        # currency comes from the CONTRACT's own column, not from this frame's env:
        # the label must come from the same place the number does (§FOREIGNACT), and
        # for a cross-frame contract the frame's currency is the wrong answer.
        # The counterparty of a release is the PROVIDER — the party about to be paid.
        await liab.check_liability_gate(
            db, c["client_did"], "contracts.engage", action_ref=f"{cid}:m{seq}",
            # the Decimal straight from the row — see liability.money_str: a float
            # round-trip here would be what turns "42.50" into "42.5" in the record
            # the human signs.
            amount=(_m0["amount"] if _m0 else c.get("total_amount")) or 0,
            currency=c.get("currency") or _FRAME_CCY,
            counterparty_did=c.get("provider_did"),
            counterparty_home_registry=c.get("counterparty_home_registry"),
            acting_hand_did=agent.did,
            presence=liab.presence_from_request(request))
    # §29 LIVE CALL SITE for I8 `contract_settlement_ok`. §XFRAME's rule is that a contract
    # settles ONLY on the frame holding its escrow — two frames both able to release is a
    # double-spend awaiting a partition. Replicas are read-only couriers and live in
    # `contract_replicas`; a home contract lives in `contracts`. So if THIS node holds a
    # replica row for this cid and is nonetheless about to release money, that is the exact
    # condition the rule forbids. Nothing in Python cross-checks the two tables here.
    try:
        from agentvault_registry import opa_shadow as _opa
        _rep = (await db.execute(text(
            "SELECT home_registry FROM contract_replicas WHERE cid = :c LIMIT 1"),
            {"c": cid})).first()
        _executing = os.getenv("REGISTRY_FEDERATION_NAME", "") or os.getenv("REGISTRY_NAME", "")
        await _opa.shadow_check(
            "agentvault/invariants/contract_settlement_ok",
            {
                "is_replica": _rep is not None,
                "escrow_frame": (_rep[0] if _rep else _executing),
                "executing_frame": _executing,
                "actor_is_party": True,   # client_did == agent.did asserted above
            },
            True, f"contracts.release_milestone:{cid}")
    except Exception:
        pass   # observability must never block or break a settlement
    m = await cs.load_milestone(db, cid, seq)
    if not m:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Milestone not found")
    if Decimal(str(m["amount"])) > 0 and not c.get("escrow_ref"):
        # migrated-legacy agreed rows carry no escrow — money must not leave the treasury for them
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail="No escrow is held for this contract (legacy row?) — cancel and re-create")
    # CLAIM submitted→releasing FIRST (+ dated audit in the SAME commit — the reaper age-gates on it)
    res = await db.execute(text(
        "UPDATE contract_milestones SET status='releasing' WHERE contract_id=:c AND seq=:s "
        "AND status='submitted'"), {"c": cid, "s": seq})
    if getattr(res, "rowcount", 0) == 0:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail="Milestone is not submitted (already releasing/released?)")
    await cs.audit(db, cid, await cs.next_seq(db, cid), "releasing", agent.did, {"seq": seq})
    await db.commit()
    m = await cs.load_milestone(db, cid, seq)
    # §XHIRE — a cross-registry provider is paid by staging through the CLIENT
    # onto /teg/cross-registry-transfer, which needs the client's OWN bearer on
    # this very request (the legacy release at contracts.py:484 already forwards
    # it; without it drive_release honestly 409s on any hr-set contract).
    out = await cs.drive_release(db, c, m, actor_did=agent.did, stars=body.stars,
                                 auth_header=request.headers.get("Authorization", "") if request else "")
    return {"ok": True, "contract_id": cid, **out}


@router.post("/api/v1/contracts/v2/{cid}/milestones/{seq}/reject",
             summary="Reject a delivered milestone → dispute (client)")
async def reject_milestone(cid: str, seq: int, body: RejectIn, request: Request = None,
                           agent: models.Agent = Depends(get_current_agent),
                           db: AsyncSession = Depends(get_db)):
    _require_enabled()
    c = await _must_load(db, cid)
    if c["client_did"] not in (agent.did, await _party_of_record(db, agent, request)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Only the client can reject")
    res = await db.execute(text(
        "UPDATE contract_milestones SET status='rejected' WHERE contract_id=:c AND seq=:s "
        "AND status='submitted'"), {"c": cid, "s": seq})
    if getattr(res, "rowcount", 0) == 0:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Milestone is not submitted")
    claimed = await db.execute(text(
        "UPDATE contracts SET status='disputed', updated_at=now() WHERE id=:c "
        "AND status IN ('agreed','in_progress')"), {"c": cid})
    await db.commit()
    ddr_id = None
    if getattr(claimed, "rowcount", 0) > 0:
        ddr_id = await _file_ddr(db, c["client_did"], c["provider_did"], cid)
    await cs.audit(db, cid, await cs.next_seq(db, cid), "disputed", agent.did,
                   {"seq": seq, "reason": (body.reason or "rejected")[:300], "ddr_dispute": ddr_id})
    await db.commit()
    cs.emit("ContractDisputed", cid, {"seq": seq, "by": agent.did, "ddr_dispute": ddr_id})
    cs.webhook("contract.disputed", c, {"seq": seq, "ddr_dispute_id": ddr_id})
    return {"ok": True, "contract_id": cid, "status": "disputed", "ddr_dispute_id": ddr_id}


@router.post("/api/v1/contracts/v2/{cid}/cancel", summary="Withdraw / cancel (rules per state)")
async def cancel_contract_v2(cid: str, request: Request = None, agent: models.Agent = Depends(get_current_agent),
                             db: AsyncSession = Depends(get_db)):
    _require_enabled()
    party = await _party_of_record(db, agent, request)   # D6-274: a hand cancels for its principal
    rep = await _replica_row(db, cid)
    if rep is not None:  # §TWOAGENT G2: only the provider can act from here; the client acts at the contract's home
        actor = agent.did if rep.get("provider_did") == agent.did else party
        return await _relay_to_home(db, rep, actor, "contract.cancel", cid=cid)
    c = await _must_load(db, cid)
    actor = agent.did if agent.did in (c["client_did"], c["provider_did"]) else party
    return await cancel_as(db, cid, actor)


async def cancel_as(db: AsyncSession, cid: str, actor_did: str) -> dict:
    """Withdraw / cancel under the per-state rules, applied at the contract's home (local route and §TWOAGENT G2 relay)."""
    c = await _must_load(db, cid)
    is_client, is_provider = c["client_did"] == actor_did, c["provider_did"] == actor_did
    if not (is_client or is_provider):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Not a party to this contract")
    if c["status"] in ("draft", "offered"):
        if not is_client:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Only the client can withdraw an offer")
        res = await db.execute(text(
            "UPDATE contracts SET status='cancelled', cancelled_at=now(), updated_at=now() "
            "WHERE id=:c AND status IN ('draft','offered')"), {"c": cid})
        if getattr(res, "rowcount", 0) == 0:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="No longer withdrawable")
        await cs.audit(db, cid, await cs.next_seq(db, cid), "cancelled", actor_did, {"phase": "offer"})
        await db.commit()
        cs.emit("ContractCancelled", cid, {"by": actor_did, "phase": "offer"})
        cs.webhook("contract.cancelled", c)
        return {"ok": True, "contract_id": cid, "status": "cancelled", "refund": "0"}
    if c["status"] not in ("agreed", "in_progress"):
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"Contract is {c['status']}")
    # §MCPTEST30 (2026-10-01): nobody cancels while a milestone is `releasing` (a release in flight, or a cross-registry
    # stage held for admin with its funds already with the client): refund_remainder counts it as unreleased and would
    # pay it a second time.
    releasing = (await db.execute(text(
        "SELECT COUNT(*) FROM contract_milestones WHERE contract_id=:c AND status='releasing'"),
        {"c": cid})).scalar() or 0
    if releasing:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail="A milestone release is in flight; the contract cannot be cancelled until it settles")
    if is_client:
        # a client cannot cancel out from under submitted work — release it or reject→dispute
        submitted = (await db.execute(text(
            "SELECT COUNT(*) FROM contract_milestones WHERE contract_id=:c AND status='submitted'"),
            {"c": cid})).scalar() or 0
        if submitted:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                detail="Deliveries are awaiting review — release or reject them first")
    # CLAIM →cancelled FIRST, then refund the unreleased remainder to the client (one leg)
    res = await db.execute(text(
        "UPDATE contracts SET status='cancelled', cancelled_at=now(), updated_at=now() "
        "WHERE id=:c AND status IN ('agreed','in_progress')"), {"c": cid})
    if getattr(res, "rowcount", 0) == 0:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="No longer cancellable")
    await cs.audit(db, cid, await cs.next_seq(db, cid), "cancelling", actor_did, {})
    await db.commit()
    refunded = await cs.refund_remainder(db, c, leg="refund")
    await cs.audit(db, cid, await cs.next_seq(db, cid), "cancelled", actor_did,
                   {"refunded": str(refunded)})
    await db.commit()
    cs.emit("ContractCancelled", cid, {"by": actor_did, "refunded": str(refunded)})
    cs.webhook("contract.cancelled", c, {"refunded": str(refunded)})
    return {"ok": True, "contract_id": cid, "status": "cancelled", "refund": str(refunded)}


# ── reads (never emit — I-C8) ────────────────────────────────────────────────────────────────

@router.get("/api/v1/contracts/v2", summary="Browse OPEN offers (public within auth)")
async def list_open_offers(limit: int = 20, cursor: Optional[str] = None,
                           contract_type: Optional[str] = None,
                           actor: dict = Depends(get_current_actor_for_read),
                           db: AsyncSession = Depends(get_db)):
    _require_enabled()
    limit = max(1, min(100, limit))
    q = ("SELECT * FROM contracts WHERE status='offered' AND provider_did IS NULL")
    params: Dict[str, Any] = {}
    if contract_type:
        q += " AND contract_type=:ct"; params["ct"] = contract_type
    if cursor:
        q += " AND id < :cur"; params["cur"] = cursor
    q += " ORDER BY id DESC LIMIT :lim"; params["lim"] = limit
    rows = (await db.execute(text(q), params)).mappings().all()
    items = [_contract_out(dict(r)) for r in rows]
    return {"items": items, "next_cursor": rows[-1]["id"] if len(rows) == limit else None}


@router.get("/api/v1/contracts/v2/mine", summary="My contracts, both roles (agent)")
async def my_contracts(role: Optional[str] = None, status_f: Optional[str] = None,
                       limit: int = 50, agent: models.Agent = Depends(get_current_agent),
                       db: AsyncSession = Depends(get_db)):
    _require_enabled()
    limit = max(1, min(100, limit))
    q = "SELECT * FROM contracts WHERE (client_did=:d OR provider_did=:d)"
    params: Dict[str, Any] = {"d": agent.did}
    if role == "client":
        q = "SELECT * FROM contracts WHERE client_did=:d"
    elif role == "provider":
        q = "SELECT * FROM contracts WHERE provider_did=:d"
    if status_f:
        q += " AND status=:st"; params["st"] = status_f
    q += " ORDER BY created_at DESC LIMIT :lim"; params["lim"] = limit
    rows = (await db.execute(text(q), params)).mappings().all()
    items = [_contract_out(dict(r)) for r in rows]
    # §XHIRE (2026-08-28) — REPLICAS of cross-frame contracts this agent is a
    # party to. Without this a provider NEVER SAW an offer another frame minted
    # to them: the mirror landed in contract_replicas and nothing provider-
    # facing read the table. Read-only couriers by law (the escrow and every
    # transition live at home_registry) — each row says so (`replica: true`),
    # and acting on one goes through the federated relay, never a local write.
    # §TWOAGENT (V0437): the milestones the home released, from the signed payload (V0434+ homes; NULL otherwise), so
    # the provider's door can say what has been paid and which milestone a delivery means.
    rq = ("SELECT cid, home_registry, client_did, provider_did, title, currency, "
          "total_amount, status, stale, updated_at, payload->'released_milestones' AS released_milestones "
          "FROM contract_replicas WHERE (client_did=:d OR provider_did=:d)")
    rparams: Dict[str, Any] = {"d": agent.did}
    if role == "client":
        rq = rq.replace("(client_did=:d OR provider_did=:d)", "client_did=:d")
    elif role == "provider":
        rq = rq.replace("(client_did=:d OR provider_did=:d)", "provider_did=:d")
    if status_f:
        rq += " AND status=:st"; rparams["st"] = status_f
    rq += " ORDER BY updated_at DESC LIMIT :lim"; rparams["lim"] = limit
    reps = (await db.execute(text(rq), rparams)).mappings().all()
    for r in reps:
        d = dict(r)
        d["id"] = d.pop("cid")
        d["total_amount"] = str(d["total_amount"]) if d.get("total_amount") is not None else None
        d["replica"] = True
        items.append(d)
    return {"items": items}


def agent_may_read(actor: dict, c) -> bool:
    """Who reads one contract: an agent a party to it, or anyone an OPEN offer (no provider named yet); a developer JWT
    reads every one. §MCPTEST30 (V0556): the comment on this rule said "open offers are browsable; concluded/private
    agreements are party-only" while the code let an agent read every OFFERED contract, so a private offer naming
    another provider (engageAgent's, §XHIRE's) was readable by any agent that had its id. The legacy view
    (routers/contracts.py) asks this same rule."""
    if actor.get("kind") != "agent":
        return True
    if actor.get("agent_did") in (c["client_did"], c["provider_did"]):
        return True
    return c["status"] == "offered" and not c["provider_did"]


@router.get("/api/v1/contracts/v2/{cid}", summary="Contract detail + milestones + events")
async def get_contract_v2(cid: str, request: Request = None, actor: dict = Depends(get_current_actor_for_read),
                          db: AsyncSession = Depends(get_db)):
    _require_enabled()
    rep = await _replica_row(db, cid)
    if rep is not None:
        # §TWOAGENT G2: the provider's registry holds a signed replica; the milestones and events live at the home.
        if actor.get("kind") == "agent" and actor.get("agent_did") not in (rep["client_did"], rep["provider_did"]) \
                and await _read_party(db, actor, request) not in (rep["client_did"], rep["provider_did"]):
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Not a party to this contract")
        full = (await db.execute(text(
            "SELECT cid, home_registry, client_did, provider_did, title, currency, total_amount, status, seq, "
            "stale, last_synced_at, updated_at, payload->'released_milestones' AS released_milestones "
            "FROM contract_replicas WHERE cid = :c"), {"c": cid})).mappings().first()
        out = {k: (str(v) if isinstance(v, Decimal) else v) for k, v in dict(full).items()}
        out.update({"id": cid, "replica": True,
                    "note": f"a signed replica; the contract, its milestones and its escrow live on {rep['home_registry']}. "
                            f"Accept, submit and cancel here are carried there."})
        return out
    c = await _must_load(db, cid)
    if not agent_may_read(actor, c) \
            and not agent_may_read({**actor, "agent_did": await _read_party(db, actor, request)}, c):
        # open offers are browsable; concluded/private agreements are party-only (dev JWT = full read); a hand reads
        # as the principal its birth token acts for (D6-274)
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Not a party to this contract")
    ms = (await db.execute(text(
        "SELECT seq, title, terms, amount, status, deliverable, due_at, submitted_at, released_at "
        "FROM contract_milestones WHERE contract_id=:c ORDER BY seq"), {"c": cid})).mappings().all()
    ev = (await db.execute(text(
        "SELECT seq, event_type, actor_did, payload, created_at FROM contract_events "
        "WHERE contract_id=:c ORDER BY seq"), {"c": cid})).mappings().all()
    out = _contract_out(c)
    out["milestones"] = [dict(m) for m in ms]
    out["events"] = [dict(e) for e in ev]
    return out


# ── admin resolve (dispute split — guild resolve twin) ───────────────────────────────────────

@router.post("/api/v1/admin/contracts/{cid}/resolve",
             summary="Resolve a disputed contract — split the unreleased remainder (admin)")
async def admin_resolve_contract(cid: str, body: ResolveIn,
                                 dev: models.Developer = Depends(get_current_developer),
                                 db: AsyncSession = Depends(get_db)):
    _require_enabled()
    if not admin_credential(dev):   # D6-057 (§POCKETPAIR): an admin's scoped key (a paired phone, an MCP OAuth key) is not admin
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Admin only")
    c = await _must_load(db, cid)
    if c["status"] != "disputed":
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"Contract is {c['status']}, not disputed")
    claimed = await db.execute(text(
        "UPDATE contracts SET status='completed', completed_at=now(), updated_at=now() "
        "WHERE id=:c AND status='disputed'"), {"c": cid})
    if getattr(claimed, "rowcount", 0) == 0:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="No longer disputed")
    await cs.audit(db, cid, await cs.next_seq(db, cid), "resolving", f"admin:{dev.id}",
                   {"provider_pct": body.provider_pct})
    await db.commit()
    out = await cs.resolve_split(db, c, body.provider_pct, actor=f"admin:{dev.id}")
    # DDR wiring (2026-07-25): the split settled the money — close the linked dispute with the
    # ruling it implies (reputation folds; NO wallet compensation runs from this path, ever).
    ddr_ruling = await cs.close_linked_dispute(db, c, body.provider_pct, actor=f"admin:{dev.id}")
    cs.webhook("contract.completed", {**c, "status": "completed"},
               {"resolution": out, "ddr_ruling": ddr_ruling})
    return {"ok": True, "contract_id": cid, "status": "completed",
            "ddr_ruling": ddr_ruling, **out}


# ── P3: agent-discovery "Engage" — the card's engagement block mints a contract ──────────────

@router.get("/api/v1/contracts/v2/engage-preview/{did}",
            summary="Preview the contract a card's engagement terms would create")
async def engage_preview(did: str, actor: dict = Depends(get_current_actor_for_read),
                         db: AsyncSession = Depends(get_db)):
    """
    Which ways to hire an agent are open, and why each closed one is shut, for any discoverable agent (404 only when
    there is no card): `per_request` (the card prices per request: the A2A payment rail), `contract` (the card
    advertises `engagement` and the agent is homed here: an escrowed contract) and `guild` (always open: a bounty is
    a job you post). `contract` stays shut for a federated agent, because an offer made here would have no replica
    at the provider's home.

    \f
    §HIRECOHERE — ONE question every hire surface asks, answered for ANY discoverable agent.

    It used to answer only for an agent homed here whose card carried an `engagement` block,
    and 404 otherwise — so on frame-c it refused **all 12** paid agents, 11 of them naming the
    wrong cause. A surface that gets a 404 cannot tell "no such agent" from "this agent is
    hireable, just not that way", so every surface guessed, and they guessed differently.

    Now it reports the three doors and WHY each is shut, and 404s only when there is no card:

      per_request — the card prices per request in EITHER dialect  -> the A2A pay rail
      contract    — the card advertises `engagement` AND is homed here -> escrowed contract
      guild       — always: a bounty is a job you post, not a thing the card must support

    🔴 `contract` stays SHUT for a federated agent, and that is a measurement rather than
    caution: `engage_agent` does not pass `counterparty_home_registry`, so a foreign offer
    would mint here with no replica at the provider's home — an escrow the provider can never
    see or act on. A stranded offer is worse than a refusal, so the door says so instead.
    """
    _require_enabled()
    card, name, src, src_name = await _load_card(db, did)
    is_local = src is None
    eng = card.get("engagement") if isinstance(card.get("engagement"), dict) else None
    price = _card_price(card)

    # §XHIRE (2026-08-28) — the foreign contract door OPENS when the provider's
    # home RESOLVES to a known peer and cross-frame replication is on: the offer
    # mints HERE (escrow home — "the escrow can only be in one place"), the
    # xframe outbox mirrors it to the provider's home, and their accept relays
    # back (offer.accept / the proven cross-registry proxy lane). The §HIRECOHERE
    # 409 stays for exactly the case it was written for: a home nothing can
    # route to would strand the offer, so the door says so instead of minting.
    xhire_home, xhire_reason = (None, None)
    if not is_local:
        xhire_home, xhire_reason = await _foreign_contract_home(db, src, src_name)

    if not is_local and not xhire_home:
        contract_reason = xhire_reason
    elif not eng:
        contract_reason = "This agent's card does not advertise engagement terms."
    else:
        contract_reason = None

    doors = {
        "per_request": {
            "available": price is not None,
            "price": price,
            "reason": None if price else "This agent's card does not price per-request calls.",
        },
        "contract": {"available": bool(eng and (is_local or xhire_home)),
                     "reason": contract_reason,
                     **({"provider_home": xhire_home} if xhire_home else {})},
        # A bounty is open to bidders, so nothing on the card has to support it.
        "guild": {"available": True, "reason": None},
    }
    return {"provider_did": did, "provider_name": name,
            "is_local": is_local, "home_registry": src_name if not is_local else None,
            "doors": doors,
            # kept verbatim for existing callers; null where there are no terms
            "engagement": eng,
            "draft": _engagement_to_draft(eng, did) if eng else None}


@router.post("/api/v1/contracts/v2/engage/{did}",
             summary="Engage a discovered agent: creates a private offer to it")
async def engage_agent(did: str, body: EngageIn, request: Request,
                       agent: models.Agent = Security(require_agent_permission("contracts.engage")),
                       db: AsyncSession = Depends(get_db)):
    _require_enabled()
    client_did = await _party_of_record(db, agent, request)   # D6-274: a hand engages for its principal
    if did in (agent.did, client_did):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Cannot engage yourself")
    # §XHIRE (2026-08-28) — a FOREIGN provider whose home RESOLVES gets a real
    # cross-frame offer: minted HERE with `counterparty_home_registry` set, so
    # the xframe outbox replicates it to their home and their federated accept
    # relays back (escrow fires at accept, at home; settlement stages through
    # the client onto /teg/cross-registry-transfer — the guild saga, verbatim).
    # The §HIRECOHERE 409 SURVIVES for the unroutable case only: a home no peer
    # row can resolve would strand the offer, so nothing is minted (park law).
    # The preview computes the SAME predicate, so no surface is offered a door
    # this refuses.
    _card, _nm, _src, _src_name = await _load_card(db, did)
    xhire_home = None
    if _src is not None:
        xhire_home, _xhire_reason = await _foreign_contract_home(db, _src, _src_name)
        if not xhire_home:
            raise HTTPException(status.HTTP_409_CONFLICT, detail=_xhire_reason)
    eng, name = await _load_engagement(db, did)
    draft = _engagement_to_draft(eng, did)
    total = _dec(body.total_amount if body.total_amount is not None else draft["total_amount"],
                 "total_amount")
    terms = dict(draft.get("terms") or {})
    if body.message:
        from agentvault_registry.input_validators import validate_safe_text
        terms["client_message"] = validate_safe_text(body.message, "message")[:2000]
    ms = None
    if draft.get("milestones"):
        ms, acc = [], Decimal("0")
        pcts = draft["milestones"]
        for i, m in enumerate(pcts):
            if i < len(pcts) - 1:
                amt = (total * Decimal(str(m.get("amount_pct", 0))) / Decimal(100)).quantize(_Q)
                acc += amt
            else:
                amt = total - acc          # exact re-sum (I-C6)
            ms.append({"title": m.get("title") or f"Milestone {i+1}", "amount": str(amt)})
    if client_did != agent.did:  # a walletless hand is binding its principal: the principal is gated (as at create)
        await liab.check_liability_gate(db, client_did, "contracts.engage", action_ref=f"contract-engage:{did}",
                                        amount=total, currency=_FRAME_CCY, counterparty_did=did,
                                        counterparty_home_registry=xhire_home,
                                        acting_hand_did=agent.did,
                                        presence=liab.presence_from_request(request))
    c = await mint_contract(
        db, client_did=client_did, title=draft["title"][:200], total_amount=total,
        contract_type=draft.get("contract_type", "service"), terms=terms,
        milestones=ms, provider_did=did,
        deadline_seconds=body.deadline_seconds or draft.get("deadline_seconds"),
        origin_surface="discovery", origin_ref=did,
        counterparty_home_registry=xhire_home,   # §XHIRE: None for a local provider
        actor_did=agent.did, request=request)
    if body.open_thread:
        # §DEALTHREADS — the ONE entry point that may open the deal thread
        # (post-commit, best-effort; the offer stands whatever chat does).
        from agentvault_registry.services import deal_thread_events as dte
        await dte.post_offer(db, c)
    return _contract_out(c)


async def _foreign_contract_home(db: AsyncSession, src: Optional[str],
                                 src_name: Optional[str]):
    """§XHIRE — ONE predicate the preview and the write path both ask: can a
    contract offer to a provider homed at `src` actually REACH them?

    Returns (peer_name, None) when the door is open, (None, reason) when shut.
    Open needs BOTH halves of the delivery promise:
      * the SPIFFE/source resolves to a `peer_registries` row (the mirror can
        be ADDRESSED — an unresolvable home is the §HIRECOHERE stranded-offer
        case, and the 409 keeps its old words for it);
      * cross-frame contract replication is ON here (`CONTRACTS_XFRAME_MODE`
        not off) — with it off the offer would mint and sit invisible, which
        is the same strand wearing a flag.
    """
    from agentvault_registry.services import contract_xframe as xf
    label = src_name or "another registry"
    if not xf.enabled():
        return None, (f"This agent is homed on {label}. Cross-frame contract replication is "
                      f"switched off on this registry, so the offer would never reach them — "
                      f"use the per-request call or post a Guild job instead.")
    home = await xf.resolve_peer_name(db, src)
    if not home:
        return None, (f"This agent is homed on {label}. Contracts with agents on another "
                      f"registry are not wired here yet — use the per-request call or post "
                      f"a Guild job instead.")
    # §TWOAGENT G2 (2026-09-23): the courier exists. The provider acts on its OWN registry (accept / submit / cancel
    # find the replica there and relay the command to this frame's /federation/contract-command) and this frame
    # APPLIES it — accept-with-escrow, submit, cancel — for the provider named on the contract, and only when the
    # relaying registry is that provider's own. The receiver applies only in enforce (shadow audits and changes
    # nothing), and an older provider registry has no courier at all: both would strand the offer, so both keep
    # the door shut with their own sentence.
    if xf.mode() != "enforce":
        return None, (f"This agent is homed on {label}. Cross-frame contracts run in {xf.mode()} on this registry: an "
                      f"offer would reach them, but their acceptance would not be applied. Use the per-request call "
                      f"or post a Guild job instead.")
    if not await _peer_carries_contract_commands(db, home):
        return None, (f"This agent is homed on {label}, whose registry cannot carry a contract acceptance back to "
                      f"this one yet (it answers no contract courier). Use the per-request call or post a Guild job "
                      f"instead.")
    return home, None


# ── helpers ──────────────────────────────────────────────────────────────────────────────────

# §TWOAGENT G2 (2026-09-23) — the provider's side of a cross-frame contract. The contract lives on the client's
# frame (the escrow can only be in one place, so the authority can only be in one place); here it is a signed
# REPLICA, and a provider's action is a COMMAND couriered to the home, never a local transition.
_COURIER_CACHE: Dict[str, Any] = {}          # peer name -> (expiry_epoch, bool)
_COURIER_TTL_SEC = int(os.getenv("CONTRACTS_XFRAME_COURIER_TTL_SEC", "600"))


async def _peer_carries_contract_commands(db: AsyncSession, peer: str) -> bool:
    """Does the provider's registry have the courier? Asked once per peer per TTL; an unreachable or older peer
    answers no (and the door says so), which is the safe side: an offer it could never accept is the strand."""
    import time as _t
    hit = _COURIER_CACHE.get(peer)
    if hit and hit[0] > _t.time():
        return hit[1]
    ok = False
    try:
        from agentvault_registry.services.exchange_passport import peer_request
        code, body = await peer_request(db, peer, "GET", "/api/v1/federation/contract-courier")
        ok = code == 200 and isinstance(body, dict) and body.get("relay") is True
    except Exception as e:  # noqa: BLE001 — unreachable reads as "cannot carry it", never as "can"
        logger.info("[XFRAME] contract courier probe of %s failed: %s", peer, e)
    # a yes holds for the TTL; a no is re-asked within a minute, so a peer that upgrades (or comes back) opens the
    # door promptly instead of reading "cannot carry it" for ten minutes
    _COURIER_CACHE[peer] = (_t.time() + (_COURIER_TTL_SEC if ok else min(60, _COURIER_TTL_SEC)), ok)
    return ok


async def _replica_row(db: AsyncSession, cid: str) -> Optional[dict]:
    """The replica of a contract homed on ANOTHER frame, or None. A home row wins: a contract that lives here is
    never relayed anywhere."""
    if (await db.execute(text("SELECT 1 FROM contracts WHERE id = :c"), {"c": cid})).first():
        return None
    row = (await db.execute(text(
        "SELECT cid, home_registry, client_did, provider_did, status, seq, currency, total_amount "
        "FROM contract_replicas WHERE cid = :c"),
        {"c": cid})).mappings().first()
    return dict(row) if row else None


async def _relay_to_home(db: AsyncSession, rep: dict, actor_did: str, action: str, *, cid: str,
                         payload: Optional[dict] = None) -> dict:
    """Courier the provider's own action to the contract's home and answer with the home's result. The home
    re-derives everything (the relaying registry must be the provider's own, the actor must be the named provider)
    and applies it; this side has already authenticated and gated its own agent."""
    from agentvault_registry.services import contract_xframe as xf
    from agentvault_registry.services.exchange_passport import peer_request
    home = rep["home_registry"]
    if not xf.enabled():
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail=f"This contract lives on {home}; cross-frame contracts are switched off on this "
                                   f"registry, so its actions cannot be carried there from here.")
    if rep.get("provider_did") != actor_did:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            detail=f"Only the provider named on this contract can act on it from here; the client "
                                   f"acts on the registry that holds it ({home}).")
    key = f"xfr-{cid}-{action}" + (f"-{payload['seq']}" if payload and "seq" in payload else "")
    try:
        code, body = await peer_request(db, home, "POST", "/api/v1/federation/contract-command", {
            "cid": cid, "action": action, "actor_did": actor_did, "seq": int(rep.get("seq") or 0),
            "payload": payload or {}, "idempotency_key": key})
    except Exception as e:  # noqa: BLE001 — PassportError(502) or transport: nothing changed anywhere
        raise HTTPException(status.HTTP_502_BAD_GATEWAY,
                            detail=f"This contract lives on {home}, which could not be reached to carry this "
                                   f"{action} ({getattr(e, 'message', e)}). Nothing changed; try again.")
    if code >= 400:
        detail = body.get("detail") if isinstance(body, dict) and body.get("detail") else body
        raise HTTPException(code, detail=detail)
    await _refresh_replica(db, home, cid)
    out = {k: v for k, v in (body or {}).items() if k != "ok"}
    out.update({"contract_id": cid, "relayed_to": home, "action": action})
    return out


async def _refresh_replica(db: AsyncSession, home: str, cid: str) -> None:
    """Pull the home's signed envelope right after a relayed action, so this side shows the new state now rather
    than at the reconciler's next pass (which remains the guarantee)."""
    from agentvault_registry.services import contract_xframe as xf
    from agentvault_registry.services.exchange_passport import peer_request
    try:
        code, body = await peer_request(db, home, "GET", f"/api/v1/federation/contract-digest?cid={cid}")
        env = body.get("envelope") if code == 200 and isinstance(body, dict) else None
        if env and await xf.verify_envelope(db, env):
            await xf.upsert_replica(db, env, verified=True)
            await db.commit()
    except Exception as e:  # noqa: BLE001 — the reconciler heals it; never fail the action on a refresh
        logger.info("[XFRAME] replica refresh after %s on %s skipped: %s", cid, home, e)


async def _must_load(db: AsyncSession, cid: str) -> dict:
    c = await cs.load_contract(db, cid)
    if not c:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Contract not found")
    return c


def _contract_out(c: dict) -> dict:
    out = dict(c)
    for k in ("total_amount", "fee_charged", "template_price_paid"):
        if out.get(k) is not None:
            out[k] = str(out[k])
    return out


async def _file_ddr(db: AsyncSession, complainant: str, defendant: str, cid: str) -> Optional[str]:
    """DDR dispute (audit-grade record; moves no funds) + contract_ref stamp + legacy contract_id
    when the contract carries one (Disputes.vue's 'View source contract' link). Never blocks."""
    try:
        from agentvault_registry.crud import crud_disputes
        legacy = (await db.execute(text(
            "SELECT legacy_ruc_id FROM contracts WHERE id=:c"), {"c": cid})).scalar()
        d = await crud_disputes.create_dispute(db, complainant_did=complainant, defendant_did=defendant,
                                               contract_id=int(legacy) if legacy is not None else None)
        did_ = str(getattr(d, "dispute_id", None) or d.id)
        await db.execute(text("UPDATE disputes SET contract_ref=:r WHERE id=:i"),
                         {"r": cid, "i": d.id})
        await db.execute(text("UPDATE contracts SET dispute_id=:d WHERE id=:c"), {"d": did_, "c": cid})
        await db.commit()
        return did_
    except Exception as e:  # noqa: BLE001
        logger.warning("[CONTRACT] DDR filing failed for %s: %s", cid, e)
        return None


async def _load_card(db: AsyncSession, did: str):
    """§HIRECOHERE — the CARD, for any discoverable agent, local or a federated mirror.

    This used to be `_load_engagement` and carried `JOIN agents a ON a.did = :d`. An `agents`
    row exists only for agents HOMED here, so every discovered mirror 404'd — and it 404'd
    saying **"Agent card not found"** while the card was sitting in `agent_cards`. Measured
    on frame-c: 11 of the 12 paid agents are mirrors, so the message named the wrong cause
    for the large majority of them. The join was never doing any work the card could not do:
    everything below reads `card_data`.

    Locality comes from `federation_metadata.source_registry` — the field that marks a synced
    copy — and NOT from `!!origin_registry_name`, which a local card also carries (§BUYSERVICE:
    that mistake misclassified 4,815 of 4,833 local frame-c cards).
    """
    row = (await db.execute(text("""
        SELECT ac.card_data, ac.name,
               (ac.card_data#>>'{federation_metadata,source_registry}') AS src,
               (ac.card_data#>>'{federation_metadata,origin_registry_name}') AS src_name
          FROM agent_cards ac
         WHERE ac.agent_did = :d AND ac.is_active = TRUE
         ORDER BY ac.updated_at DESC LIMIT 1
    """), {"d": did})).first()
    if not row or not isinstance(row[0], dict):
        # The only honest 404 left: there is genuinely no card for this DID.
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Agent card not found")
    # `source_registry` is a SPIFFE ID and decides LOCALITY; `origin_registry_name`
    # ("Registry-A") is what a sentence should say. Putting the SPIFFE ID in front of a
    # person — "homed on spiffe://agentvault.com/ns/agentvault/sa/registry-registry-a" — is
    # how a correct answer still reads as broken.
    return row[0], row[1], row[2], (row[3] or row[2])


def _card_price(card: dict) -> Optional[dict]:
    """The per-request price in whichever of the TWO legal dialects the card uses.

    ONE rule, the same one `routers/agent_cards.py` (`_SQL_PRICING_EFFECTIVE`) applies to
    discovery — expressed here in Python because this path already has the card in hand.
    Reading only `card_data.pricing` is how a paid agent gets called for free (§DISCREFINE).
    """
    def _num(v):
        try:
            d = Decimal(str(v))
            return d if d > 0 else None
        except (InvalidOperation, TypeError, ValueError):
            return None

    pricing = card.get("pricing")
    if isinstance(pricing, dict) and (pricing.get("base_rate") is not None
                                      or pricing.get("payment_required") is True):
        rate = _num(pricing.get("base_rate"))
        return {"model": pricing.get("pricing_model") or pricing.get("model") or "per_request",
                "currency": (pricing.get("currency") or _FRAME_CCY).upper(),
                "base_rate": str(rate) if rate is not None else None,
                "payment_required": bool(pricing.get("payment_required")),
                "source": "pricing-block"}
    # §MIRRORFRESH (2026-08-28) — the extension lives at TOP-LEVEL `extensions[]`
    # on real cards, which is where BOTH §DISCREFINE authorities read it
    # (agent_cards.py `_PAY_EXT_SQL` = jsonb_path '$.extensions[*]',
    # cardPricing.ts = `cd.extensions`). This reader alone asked
    # `capabilities.extensions` — measured: SYBIL's frame-c mirror carries the
    # extension (5.0 AVT) yet the per_request door answered "does not price
    # per-request calls". The mirror was innocent; the reader had diverged from
    # the ONE rule. Both placements are scanned (capabilities.extensions is the
    # A2A AgentCapabilities spelling and stays legal), top-level first.
    caps = card.get("capabilities")
    exts = list(card.get("extensions") or []) + \
        list((caps.get("extensions") if isinstance(caps, dict) else None) or [])
    for e in exts:
        if not isinstance(e, dict):
            continue
        if e.get("uri") != "https://theprotocol.cloud/extensions/v1/auth/a2a-payment":
            continue
        params = e.get("params") if isinstance(e.get("params"), dict) else {}
        rate = _num(params.get("base_rate"))
        if rate is None:
            continue
        return {"model": params.get("pricing_model") or "per_request",
                "currency": (params.get("currency") or "AVT").upper(),
                "base_rate": str(rate),
                "payment_required": bool(e.get("required", True)),
                "source": "a2a-extension"}
    return None


async def _load_engagement(db: AsyncSession, did: str):
    """The engagement block, or an honest refusal. Used by the WRITE path only — the preview
    reports what is available instead of refusing (see `engage_preview`)."""
    card, name, _src, _ = await _load_card(db, did)
    eng = card.get("engagement")
    if not isinstance(eng, dict):
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            detail="This agent's card does not advertise engagement terms")
    return eng, name


def _engagement_to_draft(eng: dict, did: str) -> dict:
    """Server-side render of a card's `engagement` block into a contract draft — FE and MCP get
    identical previews. The card model is extra='allow', so this key is additive (no schema change)."""
    ct = eng.get("contract_type", "service")
    if ct not in CONTRACT_TYPES:
        ct = "service"
    ms = eng.get("milestones") if isinstance(eng.get("milestones"), list) else None
    if ms:
        ms = [{"title": str(m.get("title") or ""), "amount_pct": float(m.get("amount_pct") or 0)}
              for m in ms[:_MAX_MILESTONES] if isinstance(m, dict)]
        if abs(sum(m["amount_pct"] for m in ms) - 100.0) > 0.01:
            ms = None  # malformed card percentages → single milestone
    return {"title": str(eng.get("title") or f"Service engagement: {did[-12:]}")[:200],
            "contract_type": ct,
            "total_amount": str(eng.get("price", 0)),
            "currency": (eng.get("currency") or _FRAME_CCY).upper(),
            "terms": eng.get("terms") if isinstance(eng.get("terms"), dict) else {},
            "milestones": ms,
            "deadline_seconds": int(eng["deadline_seconds"]) if str(eng.get("deadline_seconds") or "").isdigit() else None,
            "sla": eng.get("sla")}
