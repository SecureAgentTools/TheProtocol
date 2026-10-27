"""CROSS-FRAME CONTRACTS — the home frame's federation surface (2026-07-26).

Two endpoints, both peer-only, both on the frame that HOLDS THE ESCROW:

  * `GET  /federation/contract-digest`  — the authoritative digest + signed envelope. This is
    what makes the peer's reconciler a guarantee rather than a hope.
  * `POST /federation/contract-command` — a relayed action from a provider acting on their own
    home registry. The peer registry is a COURIER, never a principal: authority is re-derived
    here, for the relayed agent, against this frame's live state.

Mirrors `/federation/agora-vote`, which has relayed cross-frame shareholder votes in production
since 2026-06-22 — same guard, same shape, same reason.
"""
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry.core.federation_auth import require_peer_registry_identity
from agentvault_registry.database import get_db
from agentvault_registry.services import contract_xframe as xf

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/federation", tags=["contract-federation"])

# What a peer may ask this frame to do. Anything not listed is refused by construction rather
# than by validation — a relay must never be a general-purpose remote procedure call.
# §TWOAGENT G2 (2026-09-23): exactly the PROVIDER's own acts, and each one is APPLIED in enforce. The client lives on
# this frame and acts here directly, so no client act is relayable (`milestone.accept` was in this set: a peer could
# have relayed the client's approval of a delivery, which releases money). `offer.decline` and `dispute.file` have no
# provider-side transition to apply yet, so they are refused rather than audited as if they had happened.
RELAYABLE = {"offer.accept", "milestone.submit", "contract.cancel"}


def _require_enabled():
    if not xf.enabled():
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            detail="Cross-frame contracts are not enabled on this registry")


@router.get("/contract-courier", summary="Can this registry carry a provider's contract actions? (peer registries only)")
async def contract_courier(peer_spiffe: str = Depends(require_peer_registry_identity)) -> Dict[str, Any]:
    """
    Whether this registry can carry contract actions for a provider homed here: a contract's home asks before it
    lets an offer reach such a provider. An older registry has no such route (404) and a registry with cross-frame
    contracts off holds no replicas; both read as "cannot carry it", so no offer is stranded. Peer registries only
    (mTLS).

    \f
    §TWOAGENT G2: the capability a contract's HOME asks before it lets an offer reach a provider homed here. An
    older registry has no such route (404) and a registry with cross-frame contracts off holds no replicas, so both
    read as "cannot carry it", which keeps the offer from being stranded.
    """
    return {"relay": xf.enabled(), "mode": xf.mode(), "actions": sorted(RELAYABLE)}


@router.get("/contract-digest", summary="Authoritative digest for a contract (peer registries only)")
async def contract_digest(
    cid: str = Query(..., max_length=80),
    peer_spiffe: str = Depends(require_peer_registry_identity),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """The truth a replica reconciles against.

    Returns the signed envelope too, so a peer that finds itself behind can heal in the same
    round trip instead of waiting for the next mirror event to be re-emitted.
    """
    _require_enabled()
    row = (await db.execute(text("""
        SELECT id, status, client_did, provider_did, currency, total_amount, title,
               counterparty_home_registry
        FROM contracts WHERE id = :c
    """), {"c": cid})).mappings().first()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Unknown contract")
    if not row["counterparty_home_registry"]:
        # A purely local contract is nobody else's business, even for a trusted peer.
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Contract is not cross-frame")
    # §TWOAGENT (2026-09-23): and a cross-frame contract is only its counterparty's business. Any federated peer could
    # read the signed digest of a contract between this frame and ANOTHER one (parties, amount, title) given its id;
    # `contracts-for-peer` already scoped its rows by the caller and this route did not. The only callers are the
    # counterparty's reconciler and its post-relay refresh, both on the counterparty's own registry.
    caller = None
    for cand in (peer_spiffe, (peer_spiffe or "").rstrip("/")):
        caller = await xf.resolve_peer_name(db, cand)
        if caller:
            break
    if not caller or caller != await xf.resolve_peer_name(db, row["counterparty_home_registry"]):
        logger.warning("[XFRAME] contract-digest: caller %r is not the counterparty of %s", peer_spiffe, cid)
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Unknown contract")

    seq = (await db.execute(text(
        "SELECT COALESCE(MAX(seq), 0) FROM contract_events WHERE contract_id = :c"
    ), {"c": cid})).scalar() or 0
    env = await xf.signed_envelope_for(db, row, seq)
    return {"cid": cid, "digest": env["digest"], "seq": seq, "envelope": env}


@router.get("/contracts-for-peer", summary="Every cross-frame contract addressed to the CALLING peer")
async def contracts_for_peer(
    since_seq: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=500),
    peer_spiffe: str = Depends(require_peer_registry_identity),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """BOOTSTRAP. Push alone cannot establish a replica set.

    Mirrors are emitted with a deterministic idempotency key, so a re-emission of an unchanged
    transition is correctly deduplicated by the EventStore, which means a peer that begins
    listening *after* a mirror was published never hears about that contract at all, and the
    reconciler cannot rescue it because the reconciler only repairs replicas it already holds.

    So the peer pulls. The caller's identity decides the rows: a peer receives exactly the
    contracts whose counterparty resolves to itself, and nothing else.
    """
    _require_enabled()

    # Resolve the CALLER to a peer name; never trust a name supplied in the request.
    caller = None
    for cand in (peer_spiffe, (peer_spiffe or "").rstrip("/")):
        caller = await xf.resolve_peer_name(db, cand)
        if caller:
            break
    if not caller:
        # A SPIFFE we cannot map to a known peer gets nothing — silence, not a guess.
        logger.warning("[XFRAME] contracts-for-peer: unresolvable caller %r", peer_spiffe)
        return {"caller": None, "contracts": [], "count": 0}

    rows = (await db.execute(text("""
        SELECT id, status, client_did, provider_did, currency, total_amount, title,
               counterparty_home_registry
        FROM contracts
        WHERE counterparty_home_registry IS NOT NULL
        ORDER BY updated_at DESC NULLS LAST
        LIMIT :l
    """), {"l": limit * 3})).mappings().all()

    out = []
    for row in rows:
        if await xf.resolve_peer_name(db, row["counterparty_home_registry"]) != caller:
            continue
        seq = (await db.execute(text(
            "SELECT COALESCE(MAX(seq), 0) FROM contract_events WHERE contract_id = :c"
        ), {"c": row["id"]})).scalar() or 0
        if seq < since_seq:
            continue
        out.append(await xf.signed_envelope_for(db, row, seq))
        if len(out) >= limit:
            break
    return {"caller": caller, "contracts": out, "count": len(out)}


class ContractCommand(BaseModel):
    cid: str = Field(..., max_length=80)
    action: str = Field(..., max_length=32)
    actor_did: str = Field(..., max_length=120, description="the AGENT acting, not the relaying registry")
    seq: int = Field(default=0, ge=0)
    payload: Optional[Dict[str, Any]] = None
    idempotency_key: Optional[str] = Field(default=None, max_length=120)


@router.post("/contract-command", summary="Relay a contract action from a peer (peer registries only)")
async def contract_command(
    body: ContractCommand,
    peer_spiffe: str = Depends(require_peer_registry_identity),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Perform a relayed action on a contract this frame owns.

    Three properties this endpoint refuses to compromise on:

    1. **The peer is a courier.** `peer_spiffe` authenticates the CHANNEL. The principal is
       `actor_did`, and it must be the contract's own counterparty on the relaying frame: a
       peer cannot act as an agent that is not theirs, and cannot act on a contract that is not
       homed here.
    2. **Idempotent.** A retried relay is a no-op, not a second transition. The key is recorded
       in the contract's own event trail, which is the same trail the digest is derived from.
    3. **Enforce-gated.** In `shadow` the command is validated and logged and then explicitly
       NOT applied, so the rail can be exercised in production before it can change anything.
    """
    _require_enabled()

    if body.action not in RELAYABLE:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            detail=f"Action '{body.action}' is not relayable")

    row = (await db.execute(text("""
        SELECT id, status, client_did, provider_did, counterparty_home_registry
        FROM contracts WHERE id = :c
    """), {"c": body.cid})).mappings().first()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Unknown contract")
    if not row["counterparty_home_registry"]:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Contract is not cross-frame")

    # The relayed principal must actually be a party to THIS contract. Without this a trusted
    # peer could drive transitions on behalf of an agent that has nothing to do with it.
    if body.actor_did not in (row["client_did"], row["provider_did"]):
        logger.warning("[XFRAME] relay rejected: %s is not a party to %s (peer=%s)",
                       body.actor_did, body.cid, peer_spiffe)
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            detail="Actor is not a party to this contract")
    # §TWOAGENT G2 (2026-09-23): and it must be the PROVIDER, relayed by the provider's OWN registry. Being "a party"
    # admitted the client too, and the client lives here: a peer relaying the client's acts could have moved the
    # escrow. The caller is resolved from its SVID, never from anything it sends.
    if body.actor_did != row["provider_did"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            detail="Only the provider's actions are relayed; the client acts on this registry directly")
    caller = None
    for cand in (peer_spiffe, (peer_spiffe or "").rstrip("/")):
        caller = await xf.resolve_peer_name(db, cand)
        if caller:
            break
    provider_home = await xf.resolve_peer_name(db, row["counterparty_home_registry"])
    if not caller or caller != provider_home:
        logger.warning("[XFRAME] relay rejected: caller %r is not the provider's registry %r for %s",
                       caller, provider_home, body.cid)
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            detail="Only the provider's own registry may relay its actions on this contract")

    key = body.idempotency_key or f"ctr-{body.cid}-{body.seq}-{body.action}"
    already = (await db.execute(text(
        "SELECT 1 FROM contract_events WHERE contract_id = :c AND payload->>'relay_key' = :k LIMIT 1"
    ), {"c": body.cid, "k": key})).first()
    if already:
        return {"ok": True, "cid": body.cid, "action": body.action,
                "applied": False, "reason": "already_applied", "idempotency_key": key}

    from agentvault_registry.services import contract_settlement as cs
    seq = await cs.next_seq(db, body.cid)
    audit_payload = {
        "relay_key": key, "action": body.action, "actor_did": body.actor_did,
        "peer_spiffe": peer_spiffe, "mode": xf.mode(),
        "payload": body.payload or {},
    }

    if xf.mode() != "enforce":
        # Shadow: prove the rail end to end — authenticated, authorised, idempotent, audited —
        # while leaving the contract untouched.
        audit_payload["applied"] = False
        await cs.audit(db, body.cid, seq, "xframe_command_shadow", body.actor_did, audit_payload)
        await db.commit()
        return {"ok": True, "cid": body.cid, "action": body.action, "applied": False,
                "reason": "shadow_mode", "idempotency_key": key}

    # §TWOAGENT G2 (2026-09-23): APPLY it. This used to record `xframe_<action>` and answer applied:true without a
    # transition or an escrow, so a provider on another frame could never really accept. The transitions are the
    # local routes' own cores, so the rules are one set; the bond and enforcement gates run again here against the
    # provider's mirrored card (its own registry already gated it where it is native).
    from agentvault_registry.routers import contracts_v2 as ctr
    from agentvault_registry.services import enforcement_propagation as _ep
    from agentvault_registry.services import reputation_bond as _rb
    p = body.payload or {}
    try:
        if body.action == "offer.accept":
            await _rb.gate(db, body.actor_did, site="contract_accept")
            await _ep.gate(db, body.actor_did, site="contract_accept")
            c = await ctr.accept_as(db, body.cid, body.actor_did)
            result = {"status": c["status"], "escrowed": bool(c.get("escrow_ref"))}
        elif body.action == "milestone.submit":
            result = await ctr.submit_as(db, body.cid, int(p.get("seq") or 0), body.actor_did, p.get("deliverable") or {})
        else:  # contract.cancel
            result = await ctr.cancel_as(db, body.cid, body.actor_did)
    except HTTPException as e:
        if e.status_code == status.HTTP_409_CONFLICT and body.action == "offer.accept":
            # A retry whose first attempt applied but whose answer was lost: the claim is already this provider's.
            cur = (await db.execute(text("SELECT status, provider_did FROM contracts WHERE id = :c"),
                                    {"c": body.cid})).mappings().first()
            if cur and cur["provider_did"] == body.actor_did and cur["status"] in ("agreed", "in_progress", "completed"):
                return {"ok": True, "cid": body.cid, "action": body.action, "applied": False,
                        "reason": "already_applied", "status": cur["status"], "idempotency_key": key}
        raise
    seq = await cs.next_seq(db, body.cid)
    audit_payload["applied"] = True
    audit_payload["result"] = {k: (str(v) if v is not None else None) for k, v in result.items()} if isinstance(result, dict) else None
    await cs.audit(db, body.cid, seq, f"xframe_{body.action.replace('.', '_')}",
                   body.actor_did, audit_payload)
    await db.commit()
    logger.info("[XFRAME] applied relayed %s on %s by %s via %s", body.action, body.cid,
                body.actor_did, peer_spiffe)
    # `event_seq` is this relay's audit event; a submit's own `seq` (the milestone) comes through from the result.
    out = {"ok": True, "cid": body.cid, "action": body.action, "applied": True, "event_seq": seq, "idempotency_key": key}
    if isinstance(result, dict):
        out.update({k: v for k, v in result.items() if k not in ("ok", "contract_id")})
    return out
