"""SF-3: Token Bridge — Cross-Frame Wrapped Token Transfers

Orchestrates the escrow + mint flow for cross-frame AVT transfers:
1. LOCK: Escrow AVT on source frame (locked_balance)
2. MINT: Mint wrapped-AVT on target frame (wrapped_balance)
3. COMPLETE: Both sides mark transaction done

Redemption reverses: BURN wrapped → UNLOCK original.

Uses mTLS (SPIRE SVIDs) for cross-frame authentication.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

import httpx
from ..es_ssl_helper import get_httpx_verify
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status, Security
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from .. import models
from ..security import get_current_agent, require_agent_permission, enforce_agent_spend
from ..core.federation_auth import get_federation_identity
from ..core.mainframe_gate import require_mainframe_only
from ..identity import svid_client
from ..event_emitter import get_event_emitter, emit_or_report
from ..core.path_segment import seg  # §MCPTEST30 V0523: a caller's value is one path segment, encoded

logger = logging.getLogger(__name__)

# §pass66 (2026-05-22) — Token Bridge is the cross-frame transfer rail.
# Only sovereign mainframes own a bridge — cloud-operators federate through
# their parent mainframe's bridge, never their own.
router = APIRouter(
    prefix="/api/v1/bridge",
    tags=["Token Bridge"],
    dependencies=[Depends(require_mainframe_only)],
)

BRIDGE_TIMEOUT_SECONDS = 300  # 5 minutes for lock → mint
TEG_BASE_URL = "http://teg-layer:8080"  # Local TEG


# ─── Schemas ─────────────────────────────────────────────────────

class BridgeTransferRequest(BaseModel):
    target_agent_did: str = Field(..., description="DID of the agent on the target frame")
    amount: Decimal = Field(..., gt=0, le=100000, description="Amount to bridge, in the source frame's unit")
    target_frame_url: Optional[str] = Field(
        None, description="Target frame federation URL (auto-resolved if omitted)"
    )
    target_trust_domain: Optional[str] = Field(
        None,
        description=(
            "Target frame's SPIFFE trust domain (e.g. 'frame-b.theprotocol.cloud'). "
            "When provided, the URL is resolved from peer_registries for any "
            "federated frame — no per-frame env-var required."
        ),
    )


class BridgeTransferResponse(BaseModel):
    bridge_tx_id: str
    status: str
    amount: str
    source_agent_did: str
    target_agent_did: str
    target_frame: str


class BridgeMintRequest(BaseModel):
    bridge_tx_id: str
    source_agent_did: str
    target_agent_did: str
    amount: Decimal
    source_frame: str


class BridgeMintResponse(BaseModel):
    status: str
    mint_tx_id: str


class BridgeRedeemRequest(BaseModel):
    """D6-345: a redemption names the bridge transfer it reverses; everything else comes from that transfer's record."""
    bridge_tx_id: str = Field(..., min_length=1, max_length=64,
                              description="The bridge transfer to redeem (the bridge_tx_id its transfer answered)")
    amount: Optional[Decimal] = Field(None, gt=0, description="Optional; when sent it must equal the transfer's amount "
                                                              "(a redemption releases one whole transfer)")
    source_agent_did: Optional[str] = Field(None, description="Optional; when sent it must equal the agent whose units "
                                                               "the transfer locked")
    source_frame_url: Optional[str] = Field(None, description="Not used: the unlock goes to the frame the transfer "
                                                               "came from, as this registry's peer table names it")


class BridgeUnlockRequest(BaseModel):
    """D6-345: an unlock names the lock it releases; the owner and the amount come from that lock's record."""
    bridge_tx_id: str = Field(..., min_length=1, max_length=64, description="The bridge transfer whose lock is released")
    agent_did: Optional[str] = Field(None, description="Optional; when sent it must equal the lock's owner")
    amount: Optional[Decimal] = Field(None, gt=0, description="Optional; when sent it must equal the locked amount")


class BridgeConfirmLockRequest(BaseModel):
    """SEC-04: the target frame asks the source frame to confirm the lock a wrapped mint stands on."""
    bridge_tx_id: str = Field(..., min_length=1, max_length=64, description="The bridge transfer whose lock is asked")
    source_agent_did: str = Field(..., min_length=1, max_length=255, description="The agent whose units are locked")
    target_agent_did: str = Field(..., min_length=1, max_length=255, description="The agent the wrapped units go to")
    amount: Decimal = Field(..., gt=0, description="The amount the mint would credit")


# SEC-04: a lock that expires this soon cannot back a mint (the expiry worker releases a LOCKED transfer past its
# expires_at; the transfer's own mint call waits at most 30 s).
BRIDGE_CONFIRM_MARGIN_SECONDS = 60


class BridgeStatusResponse(BaseModel):
    bridge_tx_id: str
    status: str
    amount: str
    source_frame: str
    target_frame: str
    created_at: str
    completed_at: Optional[str]


# ─── Helper: call TEG ────────────────────────────────────────────

async def _call_teg(endpoint: str, body: dict) -> dict:
    """Call local TEG layer endpoint."""
    import os
    teg_url = os.environ.get("TEG_API_BASE_URL", os.environ.get("TEG_INTERNAL_URL", TEG_BASE_URL))
    teg_key = os.environ.get("TEG_ADMIN_API_KEY", "")
    async with httpx.AsyncClient(timeout=15, verify=get_httpx_verify()) as client:
        resp = await client.post(
            f"{teg_url}/api/v1/bridge/{seg(endpoint)}",
            json=body,
            headers={"Authorization": f"Bearer {teg_key}"},
        )
        if resp.status_code != 200:
            raise HTTPException(resp.status_code, f"TEG bridge/{endpoint} failed: {resp.text[:200]}")
        return resp.json()


async def _call_remote_frame(url: str, endpoint: str, body: dict) -> dict:
    """Call remote frame's bridge endpoint via mTLS."""
    cert_config = svid_client.get_client_cert_config(target_url=url)
    client_kwargs = {"timeout": 30}
    if cert_config:
        client_kwargs.update(cert_config)
    # Internal mTLS via SPIRE bundle + SVID (T1.2 — Option C)
    client_kwargs["verify"] = get_httpx_verify()

    async with httpx.AsyncClient(**client_kwargs) as client:
        resp = await client.post(f"{url}/api/v1/bridge/{endpoint}", json=body)
        if resp.status_code != 200:
            raise HTTPException(resp.status_code, f"Remote frame bridge/{endpoint} failed: {resp.text[:200]}")
        return resp.json()


async def _confirm_source_lock(source_url: str, req: "BridgeMintRequest") -> None:
    """SEC-04: ask the source frame whether it holds the lock a wrapped mint stands on (POST /bridge/confirm-lock: its
    own record of the transfer, still locked, for this owner, receiver and amount). Anything but its confirmation of
    exactly this lock refuses the mint before anything is minted."""
    body = {"bridge_tx_id": req.bridge_tx_id, "source_agent_did": req.source_agent_did,
            "target_agent_did": req.target_agent_did, "amount": str(req.amount)}
    try:
        answer = await _call_remote_frame(source_url, "confirm-lock", body)
    except HTTPException as e:
        raise HTTPException(409, f"The source frame did not confirm a lock for this transfer (it answered "
                                 f"{e.status_code}): nothing was issued")
    except Exception as e:  # noqa: BLE001 - an answer that never came confirms nothing
        raise HTTPException(503, f"The source frame could not be asked to confirm the lock ({type(e).__name__}): "
                                 f"nothing was issued")
    if not (isinstance(answer, dict) and answer.get("confirmed") is True
            and answer.get("bridge_tx_id") == req.bridge_tx_id
            and answer.get("source_agent_did") == req.source_agent_did
            and answer.get("target_agent_did") == req.target_agent_did
            and _same_amount(answer.get("amount"), req.amount)):
        raise HTTPException(409, "The source frame's answer does not confirm this lock: nothing was issued")


def _norm_url(url: Optional[str]) -> str:
    return (url or "").strip().rstrip("/").lower()


def _trust_domain_of(spiffe_id: Optional[str]) -> str:
    s = (spiffe_id or "").strip().lower()
    return s[len("spiffe://"):].split("/", 1)[0] if s.startswith("spiffe://") else ""


async def _active_frames(db: AsyncSession) -> list:
    return list((await db.execute(
        select(models.PeerRegistry).where(
            models.PeerRegistry.peer_type == "frame",
            models.PeerRegistry.status == "ACTIVE",
        )
    )).scalars().all())


async def _frame_url_for_trust_domain(db: AsyncSession, trust_domain: Optional[str]) -> Optional[str]:
    """D6-345: the federation URL of the ACTIVE frame peer with this trust domain (never a URL a caller supplied)."""
    td = (trust_domain or "").strip().lower()
    if not td:
        return None
    for peer in await _active_frames(db):
        if (peer.trust_domain or "").strip().lower() == td and peer.base_url:
            return peer.base_url.rstrip("/")
    return None


async def _frame_trust_domain_for_url(db: AsyncSession, url: Optional[str]) -> Optional[str]:
    """D6-345: the trust domain of the ACTIVE frame peer whose federation URL a transfer recorded as its target."""
    want = _norm_url(url)
    if not want:
        return None
    for peer in await _active_frames(db):
        if _norm_url(peer.base_url) == want and peer.trust_domain:
            return peer.trust_domain.strip().lower()
    return None


def _same_amount(a, b) -> bool:
    try:
        return Decimal(str(a)) == Decimal(str(b))
    except Exception:  # noqa: BLE001 - an amount that does not parse matches nothing
        return False


def _seconds_left(expires_at) -> float:
    """Seconds until `expires_at` (a naive value is read as UTC); none recorded counts as none left."""
    if expires_at is None:
        return 0.0
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return (expires_at - datetime.now(timezone.utc)).total_seconds()


# ─── Endpoints ───────────────────────────────────────────────────

@router.post("/transfer", response_model=BridgeTransferResponse)
async def bridge_transfer(
    req: BridgeTransferRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    # IRONKEY (S2, 2026-07-24): the bridge moves real value out of the caller's balance —
    # it gets the same perm + spend gating as /teg/transfer (was plain get_current_agent,
    # the one money rail the RBAC sweep missed). Byte-inert where AGENT_RBAC_MODE=off.
    agent: models.Agent = Security(require_agent_permission("teg.transfer")),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key",
        description="§pass56 PR-8: optional retry idempotency. Underlying BridgeLocked/BridgeMinted events use bridge_tx_id-derived idempotency_keys."),
):
    """
    Start a transfer of units to an agent on another frame: the amount is locked on this frame and a wrapped balance
    of the same amount is issued on the target frame. Needs an agent token with the `teg.transfer` permission; an
    `Idempotency-Key` header is kept for 24 hours. The token bridge is a switch per registry
    (`TOKEN_BRIDGE_ENABLED`), off on the public network, where these routes are not mounted (404); only mainframes
    run a bridge.

    \f
    Initiate a cross-frame AVT transfer (escrow + mint).

    Locks AVT on this frame, mints wrapped-AVT on target frame.
    Agent JWT required (source agent).

    §pass57: Idempotency-Key enforced via Redis (24h TTL). Critical for
    bridge-transfer since it's a financial mutator that initiates a 2-step
    saga (lock here, mint there); duplicate calls would create stuck locks.
    """
    from agentvault_registry.services.idempotency import idempotency_lookup, idempotency_store
    from agentvault_registry.services.idempotency.cache import agent_caller
    me = agent_caller(agent.did)   # D6-777: the key is this caller's
    _idem_body = req.model_dump(mode="json")
    _cached, _err = await idempotency_lookup("bridge.transfer", idempotency_key, _idem_body, principal=me)
    if _err:
        raise HTTPException(status_code=422, detail=_err)
    if _cached is not None:
        return _cached

    # IRONKEY L2 spend policy + L4 capability caveats (pre-lock, Δ-safe).
    # §MCPSCOPE-2 (2026-08-27) — pass the PAYEE. check_spend_policy only denies when
    # counterparty_did is supplied, so omitting it made counterparty_mode="allowlist"
    # a silent no-op on this rail: an operator who had constrained who their agent
    # may pay could still bridge any amount to any agent on another frame. This is a
    # genuine payee (the receiving agent), unlike the other counterparty-less spend
    # sites where no payee exists at spend time. Byte-inert for every policy alive
    # today, all of which are mode="any".
    await enforce_agent_spend(db, agent.did, req.amount, same_registry=False, request=request,
                              counterparty_did=req.target_agent_did)

    import os
    local_frame = os.environ.get("SPIRE_TRUST_DOMAIN", "agentvault.com")

    # Resolve target frame URL — priority chain:
    #   1. req.target_frame_url (explicit override)
    #   2. req.target_trust_domain → peer_registries lookup (WS3.5 SF-3 auto-discover)
    #   3. target_agent_did → AgentCard.federation_metadata.source_registry → peer_registries
    #   4. FRAME_B_FEDERATION_URL env var (legacy fallback for agent cards that only
    #      carry "frame-b" hint with no trust domain)
    target_url = req.target_frame_url

    if not target_url and req.target_trust_domain:
        # WS3.5 (f058/SF-3): resolve from peer_registries by SPIFFE trust domain.
        # Any frame approved via the WS3 invitation handshake is discoverable
        # here — no hard-coded env var per frame.
        td = req.target_trust_domain.strip().lower()
        if td.startswith("spiffe://"):
            td = td[len("spiffe://"):]
        peer_q = await db.execute(
            select(models.PeerRegistry).where(
                models.PeerRegistry.peer_type == "frame",
                models.PeerRegistry.trust_domain == td,
                models.PeerRegistry.status == "ACTIVE",
            )
        )
        peer = peer_q.scalar_one_or_none()
        if peer is None:
            raise HTTPException(
                400,
                f"No ACTIVE frame peer with trust_domain='{td}' in peer_registries. "
                f"Was this frame federated via /admin/federation/frame-invitations?",
            )
        target_url = peer.base_url

    if not target_url:
        # Fallback to agent-card metadata resolution (pre-WS3.5 behavior).
        card = await db.execute(
            select(models.AgentCard).where(models.AgentCard.agent_did == req.target_agent_did)
        )
        card_obj = card.scalar_one_or_none()
        if not card_obj:
            raise HTTPException(404, f"Target agent {req.target_agent_did} not found in federation")
        fed_meta = (card_obj.card_data or {}).get("federation_metadata", {})
        source_reg = fed_meta.get("source_registry", "")
        # WS3.5: resolve the home frame from the card's source_registry stamp.
        #
        # §57 sweep (2026-07-30): this used SUBSTRING matching —
        #   `candidate.trust_domain in source_reg or candidate.name.lower() in source_reg.lower()`
        # — which MISROUTES the bridge. Frame B's documented legacy stamp is
        # `spiffe://agentvault.com/ns/agentvault/sa/registry-frame-b`, and on any
        # registry that peers with Frame A the row `Registry-A (agentvault.com)`
        # satisfies `"agentvault.com" in source_reg`. First-match-wins over an
        # unordered query then resolves a FRAME B agent to FRAME A — and the
        # legacy `"frame-b" in source_reg` fallback below never fires, because
        # target_url is already (wrongly) set. Verified live: frame-b's peer table
        # holds exactly that Registry-A/agentvault.com row.
        #
        # Now: parse the stamp with the canonical extractor and match EXACTLY.
        # NAME takes priority over trust_domain because in a legacy stamp the
        # domain is precisely the part that is wrong while the name is right —
        # the same precedence spiffe_canonical itself applies (known-name check
        # before the trust_domain fallback). Stricter matching can only lose a
        # match, never invent one, so the worst case is the explicit 400 below
        # listing the available frames — refuse, never misroute.
        if source_reg:
            from ..services.spiffe_canonical import (
                extract_canonical as _extract_canon,
                _normalize_name as _norm_name,
            )
            _canon = _extract_canon(source_reg)
            if _canon:
                _src_name = _norm_name(_canon[1] or "")
                _src_td = (_canon[0] or "").lower()
            else:
                # Not a SPIFFE ID — some cards stamp a bare registry name.
                _src_name = _norm_name(source_reg)
                _src_td = ""
            _frames = (await db.execute(
                select(models.PeerRegistry).where(
                    models.PeerRegistry.peer_type == "frame",
                    models.PeerRegistry.status == "ACTIVE",
                )
            )).scalars().all()
            if _src_name:
                for candidate in _frames:
                    if candidate.name and _norm_name(candidate.name) == _src_name:
                        target_url = candidate.base_url
                        break
            if not target_url and _src_td:
                for candidate in _frames:
                    if (candidate.trust_domain or "").lower() == _src_td:
                        target_url = candidate.base_url
                        break
        # Legacy Frame-B hardcode — kept for agent cards pre-dating the trust_domain era
        if not target_url and "frame-b" in (source_reg or ""):
            target_url = os.environ.get(
                "FRAME_B_FEDERATION_URL", "https://frame-b.theprotocol.cloud:30443"
            )
        if not target_url:
            # Helpful error: list what's actually available
            all_frames = (await db.execute(
                select(models.PeerRegistry.trust_domain, models.PeerRegistry.name).where(
                    models.PeerRegistry.peer_type == "frame",
                    models.PeerRegistry.status == "ACTIVE",
                )
            )).all()
            td_list = ", ".join(f"{r[1]} ({r[0]})" for r in all_frames) or "<none>"
            raise HTTPException(
                400,
                f"Cannot auto-resolve target frame for {req.target_agent_did}. "
                f"Provide target_trust_domain or target_frame_url. "
                f"Available frames: {td_list}",
            )

    # Create bridge transaction
    bridge_tx_id = str(uuid.uuid4())
    bridge_key = f"bridge-{bridge_tx_id}"   # the row's own key; the client's Idempotency-Key keeps its name (D6-777)

    bridge_tx = models.BridgeTransaction(
        id=bridge_tx_id,
        source_frame_id=local_frame,
        target_frame_id=target_url,
        source_agent_did=agent.did,
        target_agent_did=req.target_agent_did,
        amount=req.amount,
        status="INITIATED",
        direction="outbound",
        idempotency_key=bridge_key,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=BRIDGE_TIMEOUT_SECONDS),
    )
    db.add(bridge_tx)
    await db.commit()

    # Step 1: Lock funds on local TEG
    try:
        lock_result = await _call_teg("lock", {
            "agent_id": agent.did,
            "amount": str(req.amount),
            "bridge_tx_id": bridge_tx_id,
        })
        bridge_tx.lock_tx_id = lock_result.get("tx_id")
        bridge_tx.status = "LOCKED"
        await db.commit()
        logger.info(f"[Bridge] Locked {req.amount} AVT from {agent.did} (tx={bridge_tx_id})")
    except Exception as e:
        bridge_tx.status = "FAILED"
        bridge_tx.error_message = f"Lock failed: {str(e)[:500]}"
        await db.commit()
        raise HTTPException(500, f"Failed to lock funds: {e}")

    # Step 2: Mint wrapped tokens on target frame
    try:
        mint_result = await _call_remote_frame(target_url, "mint-wrapped", {
            "bridge_tx_id": bridge_tx_id,
            "source_agent_did": agent.did,
            "target_agent_did": req.target_agent_did,
            "amount": str(req.amount),
            "source_frame": local_frame,
        })
        bridge_tx.mint_tx_id = mint_result.get("mint_tx_id")
        bridge_tx.status = "COMPLETED"
        bridge_tx.completed_at = datetime.now(timezone.utc)
        await db.commit()
        logger.info(f"[Bridge] COMPLETED {req.amount} AVT → {req.target_agent_did} on {target_url}")
    except Exception as e:
        # Compensate: unlock escrowed funds
        logger.error(f"[Bridge] Mint failed, compensating: {e}")
        try:
            await _call_teg("unlock", {
                "agent_id": agent.did,
                "amount": str(req.amount),
                "bridge_tx_id": bridge_tx_id,
            })
        except Exception as comp_err:
            logger.error(f"[Bridge] CRITICAL: Compensation also failed: {comp_err}")
        bridge_tx.status = "FAILED"
        bridge_tx.error_message = f"Mint failed: {str(e)[:500]}"
        await db.commit()
        raise HTTPException(500, f"Failed to issue on the target frame: {e}")

    # Emit event
    await emit_or_report(  # §SILENT: logged, counted, never silent; never raised after the money moved
        get_event_emitter(), where="bridge.transfer",
        event_type="TokensBridgeLocked",
        aggregate_id=bridge_tx_id,
        data={
            "bridge_tx_id": bridge_tx_id,
            "source_agent_did": agent.did,
            "target_agent_did": req.target_agent_did,
            "amount": str(req.amount),
            "source_frame": local_frame,
            "target_frame": target_url,
        },
        idempotency_key=f"bridge_locked:{bridge_tx_id}",
    )

    _resp = BridgeTransferResponse(
        bridge_tx_id=bridge_tx_id, status="COMPLETED",
        amount=str(req.amount), source_agent_did=agent.did,
        target_agent_did=req.target_agent_did, target_frame=target_url,
    )
    # §pass57: cache successful bridge response
    await idempotency_store("bridge.transfer", idempotency_key, _idem_body, _resp.model_dump(mode="json"),
                            principal=me)
    return _resp


@router.post("/mint-wrapped", response_model=BridgeMintResponse, summary="Issue the wrapped balance a source frame locked (federation)")
async def bridge_mint_wrapped(
    req: BridgeMintRequest,
    db: AsyncSession = Depends(get_db),
    federation_identity: str = Security(get_federation_identity),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key",
        description="§pass56 PR-8: optional retry idempotency. Federation mTLS path; bridge_tx_id is the natural idempotency anchor."),
):
    """
    Called by the source frame after it locked the units: issue the wrapped balance to the target agent. Idempotent
    per bridge transaction. Auth: the source frame's federation identity (mTLS); the caller must be an active frame
    peer, and `source_frame` must name it. Before anything is issued this frame asks the source frame to confirm the
    lock (POST /api/v1/bridge/confirm-lock on the source frame's address in this frame's peer table): its own record
    of the transfer, still locked, for this owner, receiver and amount. Without that confirmation nothing is issued
    (409). The token bridge is a switch per registry (`TOKEN_BRIDGE_ENABLED`), off on the public network, where these
    routes are not mounted (404); only mainframes run a bridge.

    \f
    Receive a mint request from source frame (federation mTLS auth).

    Called by source frame after locking funds. Mints wrapped-AVT to target agent.

    §pass57: Two layers of idempotency now: (a) Redis cache on Idempotency-Key
    header (request-level), (b) BridgeTransaction.idempotency_key on bridge_tx_id
    (state-level, below). Layer (b) is the strict natural anchor; layer (a)
    catches client double-submit before any DB work happens.

    SEC-04: the request's own fields named the transfer, the amount and the source frame, and nothing asked whether
    such a lock existed, so any federation caller could have a wrapped balance minted that no lock stood behind. The
    source frame now comes from the caller's identity and this frame's peer table, and that frame confirms its lock
    (mirroring D6-345's /unlock, which releases only a lock the frame itself recorded).
    """
    from agentvault_registry.services.idempotency import idempotency_lookup, idempotency_store
    from agentvault_registry.services.idempotency.cache import federation_caller
    me = federation_caller(federation_identity)   # D6-777: the key is this peer's
    _idem_body = req.model_dump(mode="json")
    _cached, _err = await idempotency_lookup("bridge.mint-wrapped", idempotency_key, _idem_body, principal=me)
    if _err:
        raise HTTPException(status_code=422, detail=_err)
    if _cached is not None:
        return _cached

    import os
    local_frame = os.environ.get("SPIRE_TRUST_DOMAIN", "agentvault.com")

    # SEC-04: the frame asking is the source frame, named by its own identity and found in this frame's peer table
    source_td = _trust_domain_of(federation_identity)
    source_url = await _frame_url_for_trust_domain(db, source_td)
    if not source_url:
        raise HTTPException(403, "Only an active frame peer may ask this frame to issue a wrapped balance")
    if (req.source_frame or "").strip().lower() != source_td:
        raise HTTPException(403, "source_frame does not name the frame asking for the issuance")

    # Idempotency check
    existing = await db.execute(
        select(models.BridgeTransaction).where(
            models.BridgeTransaction.idempotency_key == f"bridge-{req.bridge_tx_id}",
            models.BridgeTransaction.direction == "inbound",
        )
    )
    if existing.scalar_one_or_none():
        return BridgeMintResponse(status="already_minted", mint_tx_id="duplicate")

    # SEC-04: nothing is minted unless the source frame confirms the lock this mint stands on
    await _confirm_source_lock(source_url, req)

    # Mint on local TEG
    mint_result = await _call_teg("mint", {
        "agent_id": req.target_agent_did,
        "amount": str(req.amount),
        "bridge_tx_id": req.bridge_tx_id,
        "source_frame": source_td,
    })

    # Record inbound bridge transaction
    bridge_tx = models.BridgeTransaction(
        id=str(uuid.uuid4()),
        source_frame_id=source_td,
        target_frame_id=local_frame,
        source_agent_did=req.source_agent_did,
        target_agent_did=req.target_agent_did,
        amount=req.amount,
        status="COMPLETED",
        direction="inbound",
        mint_tx_id=mint_result.get("tx_id"),
        idempotency_key=f"bridge-{req.bridge_tx_id}",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=72),
        completed_at=datetime.now(timezone.utc),
    )
    db.add(bridge_tx)
    await db.commit()

    # Emit event
    await emit_or_report(  # §SILENT: logged, counted, never silent; never raised after the money moved
        get_event_emitter(), where="bridge.mint-wrapped",
        event_type="WrappedTokensMinted",
        aggregate_id=req.bridge_tx_id,
        data={
            "bridge_tx_id": req.bridge_tx_id,
            "target_agent_did": req.target_agent_did,
            "amount": str(req.amount),
            "source_frame": source_td,
        },
        idempotency_key=f"wrapped_minted:{req.bridge_tx_id}",
    )

    logger.info(f"[Bridge] MINTED {req.amount} w-AVT to {req.target_agent_did} from {source_td} (lock confirmed)")
    _resp = BridgeMintResponse(status="minted", mint_tx_id=mint_result.get("tx_id", ""))
    await idempotency_store("bridge.mint-wrapped", idempotency_key, _idem_body, _resp.model_dump(mode="json"),
                            principal=me)
    return _resp


@router.post("/redeem")
async def bridge_redeem(
    req: BridgeRedeemRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    # IRONKEY (S2, 2026-07-24): redeem burns the caller's wrapped balance + unlocks remotely
    # — same perm + spend gating as /teg/transfer. Byte-inert where AGENT_RBAC_MODE=off.
    agent: models.Agent = Security(require_agent_permission("teg.transfer")),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key",
        description="§pass56 PR-8: optional retry idempotency."),
):
    """
    Redeem a wrapped balance: burn it here and unlock the original units on the source frame. An `Idempotency-Key`
    header is kept for 24 hours. The token bridge is a switch per registry (`TOKEN_BRIDGE_ENABLED`), off on the
    public network, where these routes are not mounted (404); only mainframes run a bridge.

    \f
    Redeem wrapped-AVT: burn locally, unlock on source frame.

    §pass57: Idempotency-Key enforced via Redis cache (24h TTL). Without dedup,
    duplicate redeem calls would double-burn the caller's wrapped tokens.

    D6-345: a redemption names the bridge transfer it reverses (`bridge_tx_id`). The caller must be the agent the
    wrapped units were minted to, the transfer must not be redeemed yet, and the amount, the agent whose units are
    locked and the frame that holds them all come from this frame's record of that transfer, never from the request.
    The source frame then releases exactly that lock (see /unlock).
    """
    from agentvault_registry.services.idempotency import idempotency_lookup, idempotency_store
    from agentvault_registry.services.idempotency.cache import agent_caller
    me = agent_caller(agent.did)   # D6-777: the key is this caller's
    _idem_body = req.model_dump(mode="json")
    _cached, _err = await idempotency_lookup("bridge.redeem", idempotency_key, _idem_body, principal=me)
    if _err:
        raise HTTPException(status_code=422, detail=_err)
    if _cached is not None:
        return _cached

    # D6-345: the record of the transfer this redemption reverses (written by /mint-wrapped), locked for this request.
    inbound = (await db.execute(
        select(models.BridgeTransaction).where(
            models.BridgeTransaction.idempotency_key == f"bridge-{req.bridge_tx_id}",
            models.BridgeTransaction.direction == "inbound",
        ).with_for_update()
    )).scalar_one_or_none()
    if inbound is None:
        raise HTTPException(404, "No bridge transfer with this id was issued on this frame")
    if inbound.target_agent_did != agent.did:
        raise HTTPException(403, "These wrapped units were issued to another agent")
    if inbound.status != "COMPLETED":
        raise HTTPException(409, f"This bridge transfer is {inbound.status}: it cannot be redeemed")
    if req.amount is not None and not _same_amount(req.amount, inbound.amount):
        raise HTTPException(422, f"A redemption releases the whole transfer: {inbound.amount}")
    if req.source_agent_did and req.source_agent_did != inbound.source_agent_did:
        raise HTTPException(422, "source_agent_did does not match the transfer")
    amount = Decimal(str(inbound.amount))
    source_url = await _frame_url_for_trust_domain(db, inbound.source_frame_id)
    if not source_url:
        raise HTTPException(409, f"The frame this transfer came from ({inbound.source_frame_id}) is not an active "
                                 f"frame peer here")

    # IRONKEY L2 spend policy + L4 capability caveats (pre-burn, Δ-safe).
    # §MCPSCOPE-2 — NO counterparty here ON PURPOSE. Redeem burns wrapped tokens to
    # reclaim value the caller already escrowed; `source_agent_did` is whose funds
    # are escrowed, NOT who is being paid. Passing it would make the allowlist read
    # as if it were constraining a payment when it is not. Reviewed 2026-08-27.
    await enforce_agent_spend(db, agent.did, amount, same_registry=False, request=request)

    # Claim the transfer for this redemption: a second request waits on the row lock above and then reads REDEEMING.
    inbound.status = "REDEEMING"
    await db.commit()

    attempt_id = f"redeem-{uuid.uuid4()}"   # the TEG keys burn and re-mint per attempt; the unlock keys on the lock

    # Step 1: Burn wrapped tokens locally
    try:
        burn_result = await _call_teg("burn", {
            "agent_id": agent.did,
            "amount": str(amount),
            "bridge_tx_id": attempt_id,
            "source_frame": source_url,
        })
    except Exception as e:
        inbound.status = "COMPLETED"   # nothing burned: the transfer stays redeemable
        await db.commit()
        raise HTTPException(400, f"Failed to burn wrapped tokens: {e}")

    # Step 2: Call source frame to unlock exactly the lock this transfer made
    try:
        unlock_result = await _call_remote_frame(source_url, "unlock", {
            "bridge_tx_id": req.bridge_tx_id,
            "agent_did": inbound.source_agent_did,
            "amount": str(amount),
        })
    except Exception as e:
        # Re-mint the burned tokens (compensation)
        logger.error(f"[Bridge] Unlock failed on source frame, re-minting: {e}")
        try:
            await _call_teg("mint", {
                "agent_id": agent.did,
                "amount": str(amount),
                "bridge_tx_id": attempt_id,
                "source_frame": source_url,
            })
            inbound.status = "COMPLETED"   # burned and minted back: the transfer stays redeemable
        except Exception:
            logger.error("[Bridge] CRITICAL: Re-mint compensation also failed")
            inbound.error_message = f"Redemption {attempt_id}: unlock failed and the re-mint failed"[:1000]
        await db.commit()
        raise HTTPException(500, f"Redemption failed: source frame unlock error")

    inbound.status = "REDEEMED"
    inbound.burn_tx_id = (burn_result or {}).get("tx_id")
    inbound.unlock_tx_id = (unlock_result or {}).get("tx_id")
    await db.commit()
    logger.info(f"[Bridge] REDEEMED {amount} w-AVT from {agent.did} → unlocked on {source_url} (tx={req.bridge_tx_id})")
    _resp = {"status": "redeemed", "bridge_tx_id": req.bridge_tx_id, "amount": str(amount)}
    await idempotency_store("bridge.redeem", idempotency_key, _idem_body, _resp, principal=me)
    return _resp


@router.post("/unlock")
async def bridge_unlock_endpoint(
    body: BridgeUnlockRequest,
    db: AsyncSession = Depends(get_db),
    federation_identity: str = Security(get_federation_identity),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key",
        description="§pass56 PR-8: optional retry idempotency."),
):
    """
    Unlock escrowed units on the source frame, called by the target frame during a redemption. An `Idempotency-Key`
    header is kept for 24 hours. Auth: the target frame's federation identity (mTLS). The token bridge is a switch
    per registry (`TOKEN_BRIDGE_ENABLED`), off on the public network, where these routes are not mounted (404); only
    mainframes run a bridge.

    \f
    Unlock escrowed funds (called by target frame during redemption).

    §pass57: Idempotency-Key enforced via Redis cache. Without dedup, a
    duplicate unlock call could double-credit the agent's source-frame balance.

    D6-345: an unlock releases one lock this frame made, named by its bridge_tx_id, once. The owner and the amount
    come from the lock's record (a sent agent_did or amount must match it), the caller must be the frame the wrapped
    units were minted on, and a lock already released answers with its release again instead of releasing twice.
    """
    _idem_body = body.model_dump(mode="json")

    from agentvault_registry.services.idempotency import idempotency_lookup, idempotency_store
    from agentvault_registry.services.idempotency.cache import federation_caller
    me = federation_caller(federation_identity)   # D6-777: the key is this peer's
    _cached, _err = await idempotency_lookup("bridge.unlock", idempotency_key, _idem_body, principal=me)
    if _err:
        raise HTTPException(status_code=422, detail=_err)
    if _cached is not None:
        return _cached

    lock = (await db.execute(
        select(models.BridgeTransaction).where(
            models.BridgeTransaction.id == body.bridge_tx_id,
            models.BridgeTransaction.direction == "outbound",
        ).with_for_update()
    )).scalar_one_or_none()
    if lock is None:
        raise HTTPException(404, "No bridge transfer with this id locked units on this frame")
    if (body.agent_did and body.agent_did != lock.source_agent_did) or (
            body.amount is not None and not _same_amount(body.amount, lock.amount)):
        raise HTTPException(409, "The unlock does not match the lock it names (owner or amount)")
    caller_td = _trust_domain_of(federation_identity)
    holder_td = await _frame_trust_domain_for_url(db, lock.target_frame_id)
    if not caller_td or not holder_td or caller_td != holder_td:
        raise HTTPException(403, "Only the frame that holds this transfer's wrapped units may release its lock")
    if lock.status == "REDEEMED":
        return {"status": "unlocked", "tx_id": lock.unlock_tx_id, "replay": True}
    if lock.status != "COMPLETED":
        raise HTTPException(409, f"This bridge transfer is {lock.status}: there is no lock to release")

    bridge_tx_id = lock.id
    agent_did = lock.source_agent_did
    amount = Decimal(str(lock.amount))

    # The TEG keys the unlock on the lock's own id, as the expiry worker and the transfer's compensation do, so a
    # lock is released at most once whichever path reaches it.
    result = await _call_teg("unlock", {
        "agent_id": agent_did,
        "amount": str(amount),
        "bridge_tx_id": bridge_tx_id,
    })
    lock.status = "REDEEMED"
    lock.unlock_tx_id = (result or {}).get("tx_id")
    await db.commit()

    await emit_or_report(  # §SILENT: logged, counted, never silent; never raised after the money moved
        get_event_emitter(), where="bridge.unlock",
        event_type="TokensBridgeUnlocked",
        aggregate_id=bridge_tx_id,
        data={
            "bridge_tx_id": bridge_tx_id,
            "agent_did": agent_did,
            "amount": str(amount),
        },
        idempotency_key=f"bridge_unlocked:{bridge_tx_id}",
    )

    logger.info(f"[Bridge] UNLOCKED {amount} AVT to {agent_did} (redemption tx={bridge_tx_id})")
    _resp = {"status": "unlocked", "tx_id": result.get("tx_id")}
    await idempotency_store("bridge.unlock", idempotency_key, _idem_body, _resp, principal=me)
    return _resp


@router.post("/confirm-lock")
async def bridge_confirm_lock(
    body: BridgeConfirmLockRequest,
    db: AsyncSession = Depends(get_db),
    federation_identity: str = Security(get_federation_identity),
):
    """
    Confirm, for the frame a bridge transfer targets, that this frame holds the transfer's lock: the target frame asks
    before it issues the wrapped balance. It answers `confirmed` only for a transfer this frame locked and still holds
    locked (not completed, failed, expired or redeemed, and not about to expire), for the owner, receiver and amount
    the transfer recorded, and only to the frame the transfer targets. It reads, and changes nothing. Auth: the target
    frame's federation identity (mTLS). The token bridge is a switch per registry (`TOKEN_BRIDGE_ENABLED`), off on the
    public network, where these routes are not mounted (404); only mainframes run a bridge.

    \f
    SEC-04: mirrors /unlock's binding (D6-345): the lock is this frame's own record, named by its bridge_tx_id, and
    the caller must be the frame the transfer targets (its peer row's trust domain, from the URL the transfer
    recorded).
    """
    import os
    lock = (await db.execute(
        select(models.BridgeTransaction).where(
            models.BridgeTransaction.id == body.bridge_tx_id,
            models.BridgeTransaction.direction == "outbound",
        )
    )).scalar_one_or_none()
    if lock is None:
        raise HTTPException(404, "No bridge transfer with this id locked units on this frame")
    caller_td = _trust_domain_of(federation_identity)
    holder_td = await _frame_trust_domain_for_url(db, lock.target_frame_id)
    if not caller_td or not holder_td or caller_td != holder_td:
        raise HTTPException(403, "Only the frame this transfer targets may ask for its lock")
    if (body.source_agent_did != lock.source_agent_did or body.target_agent_did != lock.target_agent_did
            or not _same_amount(body.amount, lock.amount)):
        raise HTTPException(409, "The lock asked for does not match this transfer (owner, receiver or amount)")
    if lock.status != "LOCKED":
        raise HTTPException(409, f"This bridge transfer is {lock.status}: it holds no lock an issuance can stand on")
    if _seconds_left(lock.expires_at) < BRIDGE_CONFIRM_MARGIN_SECONDS:
        raise HTTPException(409, "This transfer's lock expires before an issuance could be recorded against it")
    return {
        "confirmed": True,
        "bridge_tx_id": lock.id,
        "source_agent_did": lock.source_agent_did,
        "target_agent_did": lock.target_agent_did,
        "amount": str(lock.amount),
        "source_frame": os.environ.get("SPIRE_TRUST_DOMAIN", "agentvault.com"),
    }


@router.get("/status/{bridge_tx_id}", response_model=BridgeStatusResponse)
async def bridge_status(
    bridge_tx_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get bridge transaction status."""
    result = await db.execute(
        select(models.BridgeTransaction).where(models.BridgeTransaction.id == bridge_tx_id)
    )
    tx = result.scalar_one_or_none()
    if not tx:
        raise HTTPException(404, "Bridge transaction not found")
    return BridgeStatusResponse(
        bridge_tx_id=tx.id, status=tx.status, amount=str(tx.amount),
        source_frame=tx.source_frame_id, target_frame=tx.target_frame_id,
        created_at=tx.created_at.isoformat() if tx.created_at else "",
        completed_at=tx.completed_at.isoformat() if tx.completed_at else None,
    )
