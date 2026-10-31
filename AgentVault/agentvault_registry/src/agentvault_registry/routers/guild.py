"""THE GUILD — agent work exchange (2026-07-07).

The open labor market: an agent posts a task with an ESCROWED bounty, other agents discover + bid,
the poster awards one, the worker delivers, the poster verifies → the worker is paid, rated (real
EigenTrust movement), and optionally issued a signed work credential. Contested deliveries resolve
via an internal split (the dispute system has no split primitive). Money rides the treasury-as-escrow
path (services/guild_escrow) → **Δ=0 by construction** (rule-13, no new money path). Gated GUILD_ENABLED.

Lifecycle: open → awarded → submitted → verified → settled  (| disputed | cancelled | refunded | expired)
"""
import datetime as _dt
import json
import re
import uuid
from urllib.parse import urlparse
import logging
import os
import secrets
from decimal import Decimal
from typing import Optional

import httpx
import time
from fastapi import APIRouter, Depends, HTTPException, Request, Security, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry import models
from agentvault_registry.database import get_db
from agentvault_registry.security import admin_credential, get_current_agent, get_current_developer, get_current_developer_optional
from agentvault_registry.services import guild_escrow, guild_reputation
from agentvault_registry.services import payout_outcome as _po  # §DOCSFIX D6-776: the stage-failure reading
from agentvault_registry.services.ledger_unavailable import refusal_from_error  # §LEDGERGATE (V0598)
from agentvault_registry.services import guild_contract_mirror  # P3a mirror (flag-gated, never raises)
from agentvault_registry.core.federation_auth import get_federation_identity, require_peer_registry_identity
from agentvault_registry.identity import svid_client
from agentvault_registry.services import reputation_bond as _rb
from agentvault_registry.services import enforcement_propagation as _ep  # §ENFPROP

logger = logging.getLogger(__name__)

try:  # §S4 pass 4 — the guild's formerly silent money-adjacent failures, counted by kind
    from prometheus_client import Counter as _GCounter
    GUILD_SILENT_FAILURE_TOTAL = _GCounter("guild_silent_failure_total", "Guild failures that used to leave no trace (stake refund after a bid race, ledger emits)", labelnames=["kind"])
except Exception:  # pragma: no cover
    GUILD_SILENT_FAILURE_TOTAL = None


def _count_silent(kind: str) -> None:
    try:
        if GUILD_SILENT_FAILURE_TOTAL is not None:
            GUILD_SILENT_FAILURE_TOTAL.labels(kind=kind[:60]).inc()
    except Exception:  # noqa: BLE001 — metrics never break the rail
        pass
from agentvault_registry.services.track_record import touch_worker_card_no_commit as _tr_touch

router = APIRouter(tags=["The Guild"])


def guild_enabled() -> bool:
    return os.getenv("GUILD_ENABLED", "false").strip().lower() == "true"


def _fee_bps() -> int:
    try:
        return max(0, min(2000, int(os.getenv("GUILD_FEE_BPS", "250"))))  # default 2.5%, cap 20%
    except ValueError:
        return 250


def _order_fee_bps(o) -> int:
    """Settle on the fee the poster was QUOTED — the fee_bps snapshot stored on the order at post
    time — not the live env (GA6, 2026-07-24: raising GUILD_FEE_BPS mid-flight must not dock a
    worker more than quoted). Deterministic across retries, which the reaper's re-drive relies on
    (same amounts → same TEG idempotency param-hash). Falls back to the live value only when the
    snapshot is absent (pre-0114 rows don't exist; belt for dict/row shape drift)."""
    try:
        v = o.get("fee_bps") if isinstance(o, dict) else getattr(o, "fee_bps", None)
        return max(0, min(2000, int(v))) if v is not None else _fee_bps()
    except (TypeError, ValueError):
        return _fee_bps()


def _require_enabled():
    if not guild_enabled():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="The Guild is disabled on this registry")


# ── schemas (inline, contracts precedent) ────────────────────────────────────
class OrderPostIn(BaseModel):
    title: str = Field(..., max_length=200)
    spec: Optional[str] = Field(None, max_length=8000)
    bounty: float = Field(..., gt=0)
    currency: Optional[str] = Field(None, max_length=12)
    required_skills: Optional[list[str]] = None
    min_reputation: Optional[float] = None
    deadline_seconds: Optional[int] = Field(None, ge=60, le=2592000)
    stake_required: Optional[float] = Field(None, ge=0, description="Collateral each bidder must lock (slashed to you on failure)")
    # V0650 (f): a flag, never a gate. The board and the order show it; anyone may still bid, and a bid from another
    # agent is accepted and marked not_intended_worker. Checked in post_order (a 422 before any escrow), not here, so
    # the organization door that builds this model in code can never turn a bad value into a 500.
    intended_worker_did: Optional[str] = Field(
        None, max_length=120,
        description="The DID of the agent this task is meant for. Anyone may still bid; a bid from another agent is "
                    "accepted and marked not_intended_worker.")


class BidIn(BaseModel):
    price: float = Field(..., gt=0)
    eta_seconds: Optional[int] = Field(None, ge=60, le=2592000)
    pitch: Optional[str] = Field(None, max_length=2000)
    on_behalf_of_org_id: Optional[str] = Field(None, max_length=64, description="Bid AS this org (firm) — payout routes to the org's AGORA treasury")


class AwardIn(BaseModel):
    bid_id: int


class CommitRefIn(BaseModel):
    """V0650 (f): one commit a delivery links, with the repository it lives in (the commons EvidenceItem precedent)."""
    repo: str = Field(..., min_length=1, max_length=300, description="The repository: a URL or owner/name, without credentials")
    commit: str = Field(..., pattern=r"^[0-9a-fA-F]{7,64}$", description="The commit id: 7 to 64 hex characters")

    @field_validator("repo")
    @classmethod
    def _repo_names_no_credentials(cls, v: str) -> str:
        if any(c.isspace() for c in v):
            raise ValueError("a repository is named without spaces")
        parts = urlparse(v)
        if parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError("name the repository without credentials, a query or a fragment")
        return v


class SubmitIn(BaseModel):
    deliverable: dict = Field(..., description="uri/text/hash + optional phone_session_id")
    # V0650 (f): stored with the delivery as deliverable.commits, so the parties read them (the verify view) and
    # anyone else reads only that commits were linked.
    commits: Optional[list[CommitRefIn]] = Field(
        None, max_length=20, description="Up to 20 commits the delivery links, each {repo, commit}")


class VerifyIn(BaseModel):
    accept: bool = True
    stars: int = Field(5, ge=1, le=5)
    feedback: Optional[str] = Field(None, max_length=2000)


class DisputeResolveIn(BaseModel):
    worker_share: float = Field(..., ge=0, le=1, description="fraction of bounty to the worker; rest refunds the poster")
    note: Optional[str] = Field(None, max_length=1000)


# ── helpers ──────────────────────────────────────────────────────────────────
async def _audit(db: AsyncSession, oid: str, seq: int, etype: str, actor: Optional[str], payload: Optional[dict]):
    await db.execute(text("""
        INSERT INTO guild_order_events (order_id, seq, event_type, actor_did, payload)
        VALUES (:o, :q, :e, :a, CAST(:p AS JSONB))
    """), {"o": oid, "q": seq, "e": etype, "a": actor, "p": json.dumps(payload or {})})


async def _next_seq(db: AsyncSession, oid: str) -> int:
    n = (await db.execute(text("SELECT COALESCE(MAX(seq),0)+1 FROM guild_order_events WHERE order_id=:o"), {"o": oid})).scalar()
    return int(n or 1)


async def _load(db: AsyncSession, oid: str) -> dict:
    row = (await db.execute(text("SELECT * FROM guild_work_orders WHERE id=:o"), {"o": oid})).mappings().first()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Order not found")
    return dict(row)


def _not_intended_worker(o: dict, bidder_did: Optional[str]) -> bool:
    """V0650 (f): ONE predicate for the flag. True when the order names its intended worker and this bidder is someone
    else. A flag, never a gate: such a bid is accepted like any other."""
    intended = o.get("intended_worker_did")
    return bool(intended) and bidder_did != intended


async def _agent_reputation(db: AsyncSession, did: str) -> Optional[float]:
    r = (await db.execute(text("SELECT reputation_score FROM agents WHERE did=:d"), {"d": did})).scalar()
    return float(r) if r is not None else None


def _emit(event_type: str, agg: str, data: dict, idempotency_key: Optional[str] = None):
    try:
        from agentvault_registry.event_emitter import get_event_emitter
        get_event_emitter().emit_background(event_type=event_type, aggregate_id=agg, data=data,
                                            idempotency_key=idempotency_key)  # §BATCH8 item 8
    except Exception as e:  # noqa: BLE001 — §S4 pass 4: a guild ledger/audit event that never leaves is a WARNING, counted
        logger.warning("[GUILD] emit %s FAILED for %s: %s: %s", event_type, agg, e.__class__.__name__, str(e)[:120])
        _count_silent(f"emit_failed:{event_type}")


def _guild_webhook(event: str, dids, data: dict) -> None:
    """§TWOAGENT G3 (2026-09-23): the WEBHOOK half of a guild notice, owner-scoped to each LOCAL agent's owner (a
    remote DID resolves to nobody here). The §NOTIFV2 push reaches a phone; nothing reached an agent RUNTIME, so the
    two-agent run polled the order for every step (14 to 38 s each) to learn of a bid, an award, a delivery or a
    verdict. Post-commit and best-effort, like every webhook."""
    try:
        import asyncio as _aio
        from agentvault_registry.background_tasks.reactor_helpers import dispatch_webhook_for_agents
        _aio.create_task(dispatch_webhook_for_agents(event, data, [d for d in (dids or []) if d], source_label="guild"))
    except Exception as e:  # noqa: BLE001
        logger.debug("[GUILD] %s webhook skipped: %s", event, e)


async def _caller_peer_name(db: AsyncSession, peer_spiffe_id: Optional[str]) -> Optional[str]:
    """The peer NAME a federation caller's identity resolves to, or None. Never read from a request body."""
    from agentvault_registry.services.contract_xframe import resolve_peer_name
    for cand in (peer_spiffe_id, (peer_spiffe_id or "").rstrip("/")):
        name = await resolve_peer_name(db, cand)
        if name:
            return name
    return None


async def _caller_is(db: AsyncSession, peer_spiffe_id: Optional[str], registry_url: Optional[str]) -> bool:
    """§TWOAGENT (2026-09-23): is the federation CALLER the registry the request speaks for? A registry vouches for its
    own agents and its own orders only; a name in the body is a claim, the SVID is the caller."""
    from agentvault_registry.services.contract_xframe import resolve_peer_name
    caller = await _caller_peer_name(db, peer_spiffe_id)
    return caller is not None and bool(registry_url) and caller == await resolve_peer_name(db, registry_url)


def _ship_guild_notice(order: dict, kind: str, extra: dict) -> None:
    """HOST -> a REMOTE worker's HOME: an advisory notice (`awarded` / `verified`) so the home can tell its agent's
    owner. Background and best-effort; it changes no state anywhere and never blocks the caller."""
    home = (order.get("worker_home_registry") or "").rstrip("/")
    if not home or not order.get("worker_did"):
        return

    async def _go():
        try:
            from agentvault_registry.database import get_db_context
            async with get_db_context() as db2:
                target = await _resolve_peer_url(db2, home)
            cfg, fed_headers = _fed_client_config(target)
            # mTLS is the credential; this registry's internal secret means nothing to a peer frame.
            fed_headers = {k: v for k, v in fed_headers.items() if k.lower() != "x-federation-secret"}
            payload = {"order_id": order["id"], "kind": kind, "worker_did": order["worker_did"],
                       "title": order.get("title"), "bounty": str(order.get("bounty")),
                       "currency": order.get("currency"), **extra}
            async with httpx.AsyncClient(**cfg) as client:
                r = await client.post(f"{target}/api/v1/federation/guild/notice", json=payload, headers=fed_headers)
            logger.info("[GUILD] %s notice for %s -> %s: %s", kind, order["id"], home, r.status_code)
        except Exception as e:  # noqa: BLE001 — a notice; the order itself is final either way
            logger.warning("[GUILD] %s notice for %s -> %s failed: %s", kind, order.get("id"), home, e)
    try:
        import asyncio as _aio
        _aio.create_task(_go())
    except Exception as e:  # noqa: BLE001
        logger.debug("[GUILD] %s notice skipped: %s", kind, e)


async def _notice_first_time(host: str, oid: str, kind: str) -> bool:
    """Idempotency for the advisory notice: one webhook per (host, order, kind). Without Redis, every delivery counts
    (a duplicate notice is better than a lost one)."""
    try:
        import hashlib
        from agentvault_registry.background_tasks.leader import get_redis
        r = await get_redis()
        if r is None:
            return True
        key = "guild:notice:" + hashlib.sha256(f"{host}|{oid}|{kind}".encode()).hexdigest()[:32]
        return bool(await r.set(key, "1", nx=True, ex=7 * 24 * 3600))
    except Exception:  # noqa: BLE001
        return True


# ── post ─────────────────────────────────────────────────────────────────────
@router.post("/api/v1/guild/orders", summary="Post a task with an escrowed bounty")
async def post_order(body: OrderPostIn, agent: models.Agent = Depends(get_current_agent), db: AsyncSession = Depends(get_db)):
    _require_enabled()
    # Jurisdiction Profiles (SPEC 2026-07-31): operator-declared feature restriction.
    # Deny-only, pre-escrow, before any money moves. Byte-inert while JURISDICTION_MODE=off.
    from agentvault_registry.services import jurisdiction as _juris
    await _juris.check_jurisdiction(db, "guild", actor=agent.did)
    # V0650 (f): whom the task is meant for. Refused here, before any escrow moves; a blank value names nobody.
    intended = (body.intended_worker_did or "").strip() or None
    if intended is not None:
        if any(c.isspace() for c in intended) or not any(intended.startswith(p) for p in _VALID_DID_PREFIXES):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail=f"intended_worker_did must be an agent DID (did:theprotocol:...), got {intended[:60]!r}")
        if intended == agent.did:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail="intended_worker_did names the poster: you cannot bid on your own task")
    currency = body.currency or os.getenv("FRAME_CURRENCY", "AVT")
    bounty = Decimal(str(body.bounty))
    oid = "gwo_" + secrets.token_hex(12)
    # 1) ESCROW the bounty (poster → treasury). Fee-free, Δ-neutral. Abort the post on failure.
    try:
        await guild_escrow.escrow_deposit(agent.did, bounty, oid)
    except guild_escrow.GuildEscrowError as e:
        raise refusal_from_error(e) or HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED, detail=f"Escrow failed (insufficient balance?): {e.message}")
    deadline = None
    if body.deadline_seconds:
        deadline = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(seconds=body.deadline_seconds)
    await db.execute(text("""
        INSERT INTO guild_work_orders (id, poster_did, title, spec, bounty, currency, fee_bps, status,
            required_skills, min_reputation, deadline, escrow_ref, stake_required, intended_worker_did)
        VALUES (:id,:p,:t,:s,:b,:c,:fb,'open',CAST(:rs AS JSONB),:mr,:dl,:er,:stk,:iw)
    """), {"id": oid, "p": agent.did, "t": body.title, "s": body.spec, "b": bounty, "c": currency,
           "fb": _fee_bps(), "rs": json.dumps(body.required_skills) if body.required_skills else None,
           "mr": body.min_reputation, "dl": deadline, "er": f"guildref:{oid}",
           "stk": Decimal(str(body.stake_required)) if body.stake_required else None, "iw": intended})
    posted = {"bounty": str(bounty), "currency": currency}
    if intended:
        posted["intended_worker_did"] = intended
    await _audit(db, oid, 1, "posted", agent.did, posted)
    await db.commit()
    _emit("GuildOrderPosted", oid, {"poster": agent.did, "bounty": str(bounty), "currency": currency})
    logger.info("[GUILD] order %s posted by %s bounty=%s %s (escrowed)", oid, agent.did, bounty, currency)
    return {"order_id": oid, "status": "open", "bounty": float(bounty), "currency": currency,
            "fee_bps": _fee_bps(), "deadline": deadline.isoformat() if deadline else None,
            "intended_worker_did": intended}


# ── discover ─────────────────────────────────────────────────────────────────
@router.get("/api/v1/guild/orders", summary="Discover open tasks")
async def list_orders(status_filter: str = "open", limit: int = 50, db: AsyncSession = Depends(get_db)):
    _require_enabled()
    limit = max(1, min(200, limit))
    # §ORGCLIENT — when the POSTER is an organization's treasury, name the firm
    # (read-side only; the client identity is part of what a bidder is pricing).
    rows = (await db.execute(text("""
        SELECT o.id, o.poster_did, o.title, o.bounty, o.currency, o.status, o.required_skills,
               o.min_reputation, o.deadline, o.worker_did, o.intended_worker_did, o.created_at,
               (SELECT count(*) FROM guild_bids b WHERE b.order_id = o.id AND b.status='open') AS bid_count,
               po.id AS poster_org_id, po.name AS poster_org_name
        FROM guild_work_orders o
        LEFT JOIN organizations po ON po.treasury_agent_did = o.poster_did
        WHERE o.status = :st ORDER BY o.created_at DESC LIMIT :lim
    """), {"st": status_filter, "lim": limit})).mappings().all()
    return {"orders": [dict(r) for r in rows], "total": len(rows)}


async def _may_see_deliverable(db: AsyncSession, o: dict, dev: Optional[models.Developer]) -> bool:
    """Who reads delivered work: the developer behind the poster or the worker agent, an active member of the poster's
    organization when an org treasury posted, and an admin (who resolves disputes over it). Nobody else."""
    if dev is None:
        return False
    if admin_credential(dev):   # D6-821: an admin on this request's credential
        return True
    dids = [d for d in (o.get("poster_did"), o.get("worker_did")) if d]
    if dids and (await db.execute(text(
            "SELECT 1 FROM agents WHERE did = ANY(:d) AND creator_developer_id = :dev LIMIT 1"),
            {"d": dids, "dev": dev.id})).first():
        return True
    org_id = o.get("poster_org_id")
    return bool(org_id) and (await db.execute(text(
        "SELECT 1 FROM organization_members WHERE organization_id = :o AND developer_id = :dev AND is_active LIMIT 1"),
        {"o": org_id, "dev": dev.id})).first() is not None


@router.get("/api/v1/guild/orders/{oid}", summary="Order detail + bids + events")
async def order_detail(oid: str, db: AsyncSession = Depends(get_db),
                       dev: Optional[models.Developer] = Depends(get_current_developer_optional)):
    """
    Order detail with bids and events. Public, as the board is, but the deliverable belongs to the parties (and an
    admin): anyone else gets `deliverable: null`, `deliverable_withheld: true` and the deliverable's key names. An
    optional developer token identifies the caller.

    \f
    §MCPTEST30 (2026-10-01): public, as the board is, but the DELIVERABLE is the parties' (and an admin's): it was
    served to anyone, with no login, from the moment the worker submitted, before the poster verified or paid. Anybody
    else gets `deliverable: null`, `deliverable_withheld: true` and the deliverable's key names (the events carry the
    same keys). The optional developer identity keeps this route's tier, so the console still sends its token.
    """
    _require_enabled()
    o = await _load(db, oid)
    # §ORGCLIENT — name the firm when the poster is an org treasury (read-side).
    porg = (await db.execute(text(
        "SELECT id, name FROM organizations WHERE treasury_agent_did = :p LIMIT 1"
    ), {"p": o["poster_did"]})).first()
    if porg:
        o["poster_org_id"], o["poster_org_name"] = str(porg[0]), porg[1]
    if o.get("deliverable") is not None and not await _may_see_deliverable(db, o, dev):
        d = o["deliverable"]
        o["deliverable_keys"] = sorted(d.keys()) if isinstance(d, dict) else []
        o["deliverable"], o["deliverable_withheld"] = None, True
    bids = (await db.execute(text(
        "SELECT id, bidder_did, price, eta_seconds, pitch, reputation, status, on_behalf_of_org_id, "
        "stake_amount, stake_status, home_registry_url, created_at "
        "FROM guild_bids WHERE order_id=:o ORDER BY reputation DESC NULLS LAST, price ASC"
    ), {"o": oid})).mappings().all()
    events = (await db.execute(text(
        "SELECT seq, event_type, actor_did, payload, created_at FROM guild_order_events WHERE order_id=:o ORDER BY seq ASC"
    ), {"o": oid})).mappings().all()
    out_bids = [dict(b) for b in bids]
    for b in out_bids:  # V0650 (f): derived at read time, never stored on the bid
        b["not_intended_worker"] = _not_intended_worker(o, b.get("bidder_did"))
    return {"order": o, "bids": out_bids, "events": [dict(e) for e in events]}


# ── FIRMS: org-treasury resolution (reuse AGORA, no parallel account) ─────────
async def _org_treasury(db: AsyncSession, org_id: str) -> Optional[str]:
    """The org's money account, or None if it has neither an org treasury nor an AGORA listing.

    §ORGTREASURY (Track C): delegates to the ONE resolver so the Guild, forge royalties,
    contract settlement and the dashboard can never disagree about where a firm gets paid.
    Behaviour for a listed org is unchanged (the resolver falls back to the first listing
    treasury by created_at, which is what this query did)."""
    from agentvault_registry.services.org_treasury import resolve_org_treasury_did
    return await resolve_org_treasury_did(db, org_id)


def _org_bid_mode() -> str:
    """``off`` | ``shadow`` | ``enforce`` — default ``enforce``. The org-CONSENT gate on firm bids:
    membership alone would let ANY member bind the firm's treasury money + reputation; the gate
    requires an org-granted ``guild.bid_for_org`` delegation row (the owner slice carries it, or an
    explicit grant), which is the authority the design gives a member to speak for its firm.

    §SECFIX D6-503 (2026-10-16): the default was ``off`` (and so was any value it did not know), so a
    registry that did not set the switch let every member's agent bid in the firm's name. ``off`` and
    ``shadow`` remain an operator's explicit choice."""
    m = os.getenv("GUILD_ORG_BID_MODE", "enforce").strip().lower()
    return m if m in ("off", "shadow", "enforce") else "enforce"


async def _org_bid_grant_exists(db: AsyncSession, agent_did: str, org_id: str) -> bool:
    """True iff the ORG has consented: a live ``org:``-principal delegation grant to this agent
    carrying ``guild.bid_for_org``. Grant-row-based on purpose — role-held permissions
    (including legacy-full) do NOT count here; the org itself must have granted it."""
    try:
        slug = (await db.execute(text(
            "SELECT slug FROM organizations WHERE id=:o"), {"o": org_id})).scalar()
        r1 = f"org:{org_id}"
        r2 = f"org:{slug}" if slug else r1
        row = (await db.execute(text(
            "SELECT 1 FROM agent_delegation_grants WHERE delegate_agent_did = :d "
            "AND principal_type = 'org' AND (principal_ref = :r1 OR principal_ref = :r2) "
            "AND revoked_at IS NULL AND (expires_at IS NULL OR expires_at > now()) "
            "AND 'guild.bid_for_org' = ANY(permissions) LIMIT 1"
        ), {"d": agent_did, "r1": r1, "r2": r2})).first()
        return row is not None
    except Exception:  # noqa: BLE001
        return False  # table missing / read error → no consent proven


async def _validate_firm_bid(db: AsyncSession, agent_did: str, org_id: str) -> str:
    """The bidder must be a MEMBER of the org (Agent.organization_id) and the org must have a treasury.
    Returns the treasury DID (the payee). Raises 403/409 otherwise.

    ``GUILD_ORG_BID_MODE`` layers org CONSENT on top of membership (shadow logs a would-deny,
    enforce 403s): the org grants ``guild.bid_for_org`` to exactly the members allowed to
    speak for it. Re-checked at award time too, so a revoked grant denies before money moves."""
    mem = (await db.execute(text("SELECT organization_id FROM agents WHERE did=:d"), {"d": agent_did})).scalar()
    if mem != org_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="You are not a member of that organization")
    mode = _org_bid_mode()
    if mode != "off" and not await _org_bid_grant_exists(db, agent_did, org_id):
        if mode == "enforce":
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                detail="Organization consent required: no active guild.bid_for_org grant from this org")
        logger.warning("[GUILD-ORG-BID-SHADOW] would-deny firm bid agent=%s org=%s (no guild.bid_for_org org-grant)",
                       agent_did, org_id)
    treasury = await _org_treasury(db, org_id)
    if not treasury:
        # §DOCSFIX D6-670: a firm is paid into the organization's treasury, its own or its first AGORA listing's
        # (services/org_treasury.resolve_org_treasury_did); /guild/my-firm's "listed" names the same fact for the console
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Organization has no treasury to be paid into as a firm "
                                                             "(give it a treasury of its own, or list it on AGORA)")
    return treasury


# ── STAKED WORK: refund / release / slash bidder collateral (all Δ-neutral treasury legs) ──
async def _refund_all_stakes(db: AsyncSession, oid: str, exclude_bidder: Optional[str] = None) -> None:
    """Refund every HELD bid stake on an order (except optionally the awarded bidder). Treasury→bidder."""
    rows = (await db.execute(text(
        "SELECT bidder_did, stake_amount, stake_escrow_ref FROM guild_bids WHERE order_id=:o AND stake_status='held'"
    ), {"o": oid})).mappings().all()
    for b in rows:
        if exclude_bidder and b["bidder_did"] == exclude_bidder:
            continue
        try:
            if (b["stake_escrow_ref"] or "").startswith("remote:"):
                # v2 (0119): collateral lives on the bidder's HOME — release it there
                await _notify_home_stake(db, b["stake_escrow_ref"][7:], oid, b["bidder_did"], "release")
            else:
                await guild_escrow.escrow_payout(db, b["bidder_did"], Decimal(str(b["stake_amount"])), oid, f"stake_refund:{b['bidder_did'][-12:]}")
            await db.execute(text("UPDATE guild_bids SET stake_status='released' WHERE order_id=:o AND bidder_did=:d"), {"o": oid, "d": b["bidder_did"]})
        except Exception as e:  # noqa: BLE001
            logger.warning("[GUILD] stake refund failed for %s on %s: %s", b["bidder_did"], oid, e)


async def _resolve_worker_stake(db: AsyncSession, oid: str, worker_did: str, to_did: str, action: str) -> Optional[dict]:
    """RELEASE the worker's held stake back to them (action='release'), or SLASH it to `to_did` (the
    wronged poster, action='slash'). Treasury→party, Δ-neutral. No-op if no held stake."""
    b = (await db.execute(text(
        "SELECT stake_amount, stake_escrow_ref FROM guild_bids WHERE order_id=:o AND bidder_did=:d AND stake_status='held'"
    ), {"o": oid, "d": worker_did})).first()
    if not b or not b.stake_amount:
        return None
    amt = Decimal(str(b.stake_amount))
    if (b.stake_escrow_ref or "").startswith("remote:"):
        # v2 (0119): the collateral sits in the WORKER'S HOME treasury. release → home pays it back;
        # slash → zero legs (the deposit already lives in the home treasury; it just never returns).
        # Deterrent model: a slashed remote stake does NOT compensate the poster (v2 documented).
        ok = await _notify_home_stake(db, b.stake_escrow_ref[7:], oid, worker_did, action)
        await db.execute(text("UPDATE guild_bids SET stake_status=:st WHERE order_id=:o AND bidder_did=:d"),
                         {"st": "released" if action == "release" else "slashed", "o": oid, "d": worker_did})
        return {"amount": str(amt), "to": worker_did if action == "release" else "home-treasury",
                "action": f"{action}_remote", "home_notified": ok}
    await guild_escrow.escrow_payout(db, to_did, amt, oid, f"stake_{action}:{worker_did[-12:]}")
    await db.execute(text("UPDATE guild_bids SET stake_status=:st WHERE order_id=:o AND bidder_did=:d"),
                     {"st": "released" if action == "release" else "slashed", "o": oid, "d": worker_did})
    return {"amount": str(amt), "to": to_did, "action": action}


# §FIRMHIRE (H3.2) — an order carrying a `for-org:{org_id}` tag in required_skills
# is a bounty ADDRESSED TO THAT FIRM: only agents assigned to the org may claim it.
# Rides the EXISTING required_skills JSON (no migration); the tag is visible on the
# board (transparency by construction).
def _order_target_org(o: dict) -> Optional[str]:
    skills = o.get("required_skills")
    if isinstance(skills, str):
        try:
            skills = json.loads(skills)
        except Exception:  # noqa: BLE001
            return None
    if not isinstance(skills, list):
        return None
    for s in skills:
        if isinstance(s, str) and s.startswith("for-org:") and len(s) > 8:
            return s[8:]
    return None


async def _firm_bounty_gate(db: AsyncSession, o: dict, bidder_did: Optional[str]) -> None:
    """403 unless the bidder is a LOCAL agent assigned to the target org (None = remote)."""
    target = _order_target_org(o)
    if not target:
        return
    if not bidder_did:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            detail="This bounty is addressed to a specific firm; cross-registry "
                                   "bids cannot carry that firm's membership.")
    row = (await db.execute(text(
        "SELECT organization_id FROM agents WHERE did = :d"), {"d": bidder_did})).first()
    if not row or not row[0] or str(row[0]) != str(target):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            detail="This bounty is addressed to a specific firm — only that "
                                   "organization's agents may bid on it.")


# ── bid ──────────────────────────────────────────────────────────────────────
@router.post("/api/v1/guild/orders/{oid}/bids", summary="Bid on an open task (individually or as a firm)")
async def place_bid(oid: str, body: BidIn, agent: models.Agent = Depends(get_current_agent), db: AsyncSession = Depends(get_db)):
    _require_enabled()
    o = await _load(db, oid)
    if o["status"] != "open":
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"Order is {o['status']}")
    if agent.did == o["poster_did"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Cannot bid on your own task")
    # §REPBOND — bidding is a provider act: the bond gate applies (shadow counts, enforce refuses).
    await _rb.gate(db, agent.did, site="guild_bid")
    await _ep.gate(db, agent.did, site="guild_bid")
    await _firm_bounty_gate(db, o, agent.did)
    if Decimal(str(body.price)) > Decimal(str(o["bounty"])):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Bid price exceeds the bounty")
    rep = await _agent_reputation(db, agent.did)
    if o["min_reputation"] is not None and (rep or 0) < float(o["min_reputation"]):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Below the task's minimum reputation")
    # FIRM bid: validate membership + org treasury (the payee). Member agent delivers; firm gets paid.
    if body.on_behalf_of_org_id:
        await _validate_firm_bid(db, agent.did, body.on_behalf_of_org_id)
    # STAKED WORK: if the task requires collateral, the bidder locks it (bidder → treasury) before bidding.
    stake = Decimal(str(o["stake_required"])) if o.get("stake_required") else Decimal(0)
    stake_ref = None
    if stake > 0:
        dup = (await db.execute(text("SELECT 1 FROM guild_bids WHERE order_id=:o AND bidder_did=:d"), {"o": oid, "d": agent.did})).first()
        if dup:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="You already have a live bid on this task")
        try:
            await guild_escrow.escrow_deposit(agent.did, stake, oid, leg=f"stake:{agent.did[-12:]}")
            stake_ref = f"guildref:{oid}:stake:{agent.did[-12:]}"
        except guild_escrow.GuildEscrowError as e:
            raise refusal_from_error(e) or HTTPException(
                status.HTTP_402_PAYMENT_REQUIRED, detail=f"Collateral lock failed (insufficient balance? need {stake}): {e.message}")
    try:
        bid_id = (await db.execute(text("""
            INSERT INTO guild_bids (order_id, bidder_did, price, eta_seconds, pitch, reputation, status,
                on_behalf_of_org_id, stake_amount, stake_escrow_ref, stake_status)
            VALUES (:o,:d,:pr,:eta,:pi,:rep,'open',:org,:sa,:sr,:ss)
            RETURNING id
        """), {"o": oid, "d": agent.did, "pr": Decimal(str(body.price)), "eta": body.eta_seconds,
               "pi": body.pitch, "rep": rep, "org": body.on_behalf_of_org_id,
               "sa": stake if stake > 0 else None, "sr": stake_ref, "ss": "held" if stake > 0 else None})).scalar()
    except Exception:  # unique(order,bidder) — refund the stake we just locked (race)
        if stake > 0:
            try: await guild_escrow.escrow_payout(db, agent.did, stake, oid, f"stake_refund:{agent.did[-12:]}")
            except Exception as re_:  # noqa: BLE001 — §S4 pass 4: a stake that stays LOCKED with no trace is money nobody can see
                logger.error("[GUILD] stake refund FAILED after a bid race on %s for %s (stake %s): %s: %s",
                             oid, agent.did[-12:], stake, re_.__class__.__name__, str(re_)[:160])
                _count_silent("stake_refund_failed")
        raise HTTPException(status.HTTP_409_CONFLICT, detail="You already have a live bid on this task")
    flagged = _not_intended_worker(o, agent.did)  # V0650 (f): accepted, and marked
    bid_audit = {"price": str(body.price), "eta": body.eta_seconds, "org": body.on_behalf_of_org_id, "stake": str(stake) if stake > 0 else None}
    if flagged:
        bid_audit["not_intended_worker"] = True
    await _audit(db, oid, await _next_seq(db, oid), "bid", agent.did, bid_audit)
    await db.commit()
    _emit("GuildBidPlaced", oid, {"bidder": agent.did, "price": str(body.price), "org": body.on_behalf_of_org_id, "stake": str(stake) if stake else None})

    # §NOTIFV2: a bid needs the poster's attention. Catalog gives this one a 300s coalesce window
    # and desktop-only default — a popular order can attract bids in bursts.
    try:
        import asyncio as _aio
        from agentvault_registry.background_tasks.push_notify import notify_agent_owners
        _aio.create_task(notify_agent_owners(
            "guild.bid_received", [o["poster_did"]],
            title="New bid on your order",
            message=f"Order {oid}: {agent.did[:32]} bid {body.price}.",
            tags="hammer", priority="default", click="/ui/#/guild"))
    except Exception:  # noqa: BLE001
        logger.debug("guild.bid_received notify skipped", exc_info=True)
    _guild_webhook("guild.bid_received", [o["poster_did"]], {
        "order_id": oid, "title": o.get("title"), "bid_id": bid_id, "bidder_did": agent.did, "price": str(body.price),
        "currency": o.get("currency"), "via": "local", "firm": body.on_behalf_of_org_id,
        "not_intended_worker": flagged,
        "award_with": f"POST /api/v1/guild/orders/{oid}/award with bid_id={bid_id}"})

    return {"ok": True, "order_id": oid, "bidder": agent.did, "bid_id": bid_id, "firm": body.on_behalf_of_org_id,
            "stake_locked": float(stake) if stake else 0,
            "intended_worker_did": o.get("intended_worker_did"), "not_intended_worker": flagged}


# ── award ────────────────────────────────────────────────────────────────────
@router.post("/api/v1/guild/orders/{oid}/award", summary="Award a bid (poster)")
async def award(oid: str, body: AwardIn, agent: models.Agent = Depends(get_current_agent), db: AsyncSession = Depends(get_db)):
    _require_enabled()
    o = await _load(db, oid)
    if o["poster_did"] != agent.did:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Only the poster can award")
    if o["status"] != "open":
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"Order is {o['status']}")
    bid = (await db.execute(text("SELECT id, bidder_did, status, on_behalf_of_org_id, home_registry_url, payee_did_hint FROM guild_bids WHERE id=:b AND order_id=:o"),
                            {"b": body.bid_id, "o": oid})).mappings().first()
    if not bid or bid["status"] != "open":
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Bid not found or not open")
    # FIRM award: worker_did = the member agent (the actor who submits); payee = the org treasury.
    # Individual award: payee stays NULL → settle pays the worker.
    payee_did = None; payee_org = bid["on_behalf_of_org_id"]
    if payee_org:
        if bid["home_registry_url"]:
            # v2 (0119) firm-REMOTE: the org lives on the bidder's HOME — it validated membership +
            # treasury at proxy time and asserted the payee. Same trust as the vouched identity.
            payee_did = bid["payee_did_hint"]
            if not payee_did:
                raise HTTPException(status.HTTP_409_CONFLICT, detail="Remote firm bid carries no payee assertion")
            # GA4 (2026-07-24): award-time re-check — bids inserted before the
            # bid-time guard existed may carry a hint that resolves locally.
            _local_payee = (await db.execute(
                text("SELECT 1 FROM agents WHERE did = :p"), {"p": payee_did}
            )).first()
            if _local_payee:
                raise HTTPException(status.HTTP_409_CONFLICT,
                                    detail="Remote firm payee resolves to a LOCAL agent — award refused")
        else:
            payee_did = await _validate_firm_bid(db, bid["bidder_did"], payee_org)  # re-check at award time
    # Guard open→awarded (2026-07-23): only one actor awards (kills a concurrent double-award and,
    # with the reaper's claim-first expiry, the award↔reaper race that would otherwise double-spend).
    claimed = await db.execute(text(
        "UPDATE guild_work_orders SET status='awarded', worker_did=:w, payee_did=:pd, payee_org_id=:po, "
        "worker_home_registry=:hr, awarded_bid_id=:b, awarded_at=now() WHERE id=:o AND status='open'"
    ), {"w": bid["bidder_did"], "pd": payee_did, "po": payee_org, "hr": bid["home_registry_url"],
        "b": bid["id"], "o": oid})
    if getattr(claimed, "rowcount", 0) == 0:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Order is no longer open")
    await db.execute(text("UPDATE guild_bids SET status='awarded' WHERE id=:b"), {"b": bid["id"]})
    await db.execute(text("UPDATE guild_bids SET status='released' WHERE order_id=:o AND id != :b AND status='open'"), {"o": oid, "b": bid["id"]})
    # STAKED WORK: refund the losing bidders' stakes; the winner's stays held until settle/dispute.
    await _refund_all_stakes(db, oid, exclude_bidder=bid["bidder_did"])
    await _audit(db, oid, await _next_seq(db, oid), "awarded", agent.did,
                 {"bid_id": bid["id"], "worker": bid["bidder_did"], "payee": payee_did or bid["bidder_did"], "firm": payee_org})
    await db.commit()
    _emit("GuildOrderAwarded", oid, {"worker": bid["bidder_did"], "bid_id": bid["id"], "firm": payee_org})
    # §NOTIFV2 — you won a job. Post-commit, fire-and-forget, never blocks the award.
    try:
        import asyncio as _aio
        from agentvault_registry.background_tasks.push_notify import notify_agent_owners
        _aio.create_task(notify_agent_owners(
            "guild.awarded", [bid["bidder_did"]],
            title="Guild: you won the job",
            message=f"Order {oid[:20]} awarded to {bid['bidder_did']}",
            tags="trophy", click="/ui/#/guild"))
    except Exception:  # noqa: BLE001
        logger.debug("[GUILD] award notify skipped", exc_info=True)
    _award_data = {"order_id": oid, "title": o.get("title"), "bid_id": bid["id"], "worker_did": bid["bidder_did"],
                   "payee": payee_did or bid["bidder_did"], "firm": payee_org, "bounty": str(o.get("bounty")),
                   "currency": o.get("currency")}
    if bid["home_registry_url"]:
        _ship_guild_notice({**o, "worker_did": bid["bidder_did"], "worker_home_registry": bid["home_registry_url"]},
                           "awarded", {"bid_id": bid["id"]})
    else:
        _guild_webhook("guild.awarded", [bid["bidder_did"]], {
            **_award_data, "via": "local", "submit_with": f"POST /api/v1/guild/orders/{oid}/submit"})
    await guild_contract_mirror.sync_from_order(db, oid)  # P3a mirror
    return {"ok": True, "order_id": oid, "worker": bid["bidder_did"], "payee": payee_did or bid["bidder_did"],
            "firm": payee_org, "status": "awarded"}


# ── submit ───────────────────────────────────────────────────────────────────
@router.post("/api/v1/guild/orders/{oid}/submit", summary="Deliver work (worker)")
async def submit(oid: str, body: SubmitIn, agent: models.Agent = Depends(get_current_agent), db: AsyncSession = Depends(get_db)):
    _require_enabled()
    o = await _load(db, oid)
    if o["worker_did"] != agent.did:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Only the awarded worker can submit")
    if o["status"] != "awarded":
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"Order is {o['status']}")
    # V0650 (f): the linked commits ride the deliverable, so its readers (the parties, an admin) are theirs too.
    deliverable = dict(body.deliverable)
    if body.commits:
        if "commits" in deliverable:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail="give the commits once, in the commits field (the deliverable also carries a "
                                       "'commits' key)")
        deliverable["commits"] = [c.model_dump() for c in body.commits]
    await db.execute(text("UPDATE guild_work_orders SET status='submitted', deliverable=CAST(:d AS JSONB), submitted_at=now() WHERE id=:o"),
                     {"d": json.dumps(deliverable), "o": oid})
    await _audit(db, oid, await _next_seq(db, oid), "submitted", agent.did, {"keys": list(deliverable.keys())})
    await db.commit()

    # §NOTIFV2 (2026-07-27): the POSTER is the one who has to act on a delivery, so they get the
    # push. Deliberately placed on this single post-commit point rather than at any of the five
    # `return`s below — the eval-bounty branches each have their own exit, and wiring one of them
    # would mean "submitted" notifies on some paths and not others.
    try:
        import asyncio as _aio
        from agentvault_registry.background_tasks.push_notify import notify_agent_owners
        _aio.create_task(notify_agent_owners(
            "guild.work_submitted", [o["poster_did"]],
            title="Work delivered for review",
            message=f"Order {oid} has a delivery waiting on your verification.",
            tags="package", priority="default", click="/ui/#/guild"))
    except Exception:  # noqa: BLE001
        logger.debug("guild.work_submitted notify skipped", exc_info=True)
    _guild_webhook("guild.work_submitted", [o["poster_did"]], {
        "order_id": oid, "title": o.get("title"), "worker_did": agent.did, "via": "local",
        "deliverable_keys": list(deliverable.keys()),
        "verify_with": f"POST /api/v1/guild/orders/{oid}/verify with accept=true (pay) or false (dispute)"})
    _emit("GuildWorkSubmitted", oid, {"worker": agent.did})
    # GÖDEL FORGE (FG-4) — eval_bounty: spec header `eval_bounty://<suite>/<min_score>` = the
    # poster's pre-authorization for OBJECTIVE settlement. Local workers only; gated FORGE_ENABLED.
    bounty_meta = _parse_eval_bounty(o.get("spec") or "")
    if bounty_meta and not o.get("worker_home_registry"):
        try:
            from agentvault_registry.forge_flags import forge_enabled
            if forge_enabled():
                suite_id, min_score = bounty_meta
                score = await _run_bounty_eval(suite_id, agent.did)
                if score is not None and score >= min_score:
                    o2 = await _load(db, oid)
                    result = await _auto_settle_eval_bounty(db, o2, oid, actor_did=agent.did, score=score)
                    return {"ok": True, "order_id": oid, "eval_score": score, **result}
                return {"ok": True, "order_id": oid, "status": "submitted", "eval_score": score,
                        "note": "eval_bounty: score below threshold or inconclusive — awaiting poster verify"}
        except Exception as e:  # noqa: BLE001
            logger.warning("[GUILD] eval_bounty path failed (order stays submitted): %s", e)
    elif bounty_meta and o.get("worker_home_registry"):
        # Cross-registry worker (Commander-approved 2026-07-20): a passing objective score
        # settles through the gateway-repatriation rail — the poster pre-authorized the payout
        # at post time, so no fresh poster JWT is needed and no second authority exists. A
        # below-threshold or inconclusive score still just records evidence for the poster.
        try:
            from agentvault_registry.forge_flags import forge_enabled
            if forge_enabled():
                suite_id, min_score = bounty_meta
                score = await _run_bounty_eval(suite_id, agent.did)
                if score is not None and score >= min_score:
                    o2 = await _load(db, oid)
                    result = await _auto_settle_eval_bounty_xreg(db, o2, oid, actor_did=agent.did, score=score)
                    return {"ok": True, "order_id": oid, "eval_score": score, **result}
                if score is not None:
                    await db.execute(text(
                        "UPDATE guild_work_orders SET deliverable = COALESCE(deliverable,'{}'::jsonb) "
                        "|| jsonb_build_object('eval_bounty_score', CAST(:s AS numeric), "
                        "'eval_bounty_passed', CAST(:p AS boolean)) WHERE id=:o"),
                        {"s": score, "p": False, "o": oid})
                    await _audit(db, oid, await _next_seq(db, oid), "eval_bounty_scored", agent.did,
                                 {"score": score, "min_score": min_score, "xreg": True})
                    await db.commit()
                    return {"ok": True, "order_id": oid, "status": "submitted", "eval_score": score,
                            "note": "eval_bounty (cross-registry): score below threshold or inconclusive — "
                                    "recorded as evidence, awaiting poster verify"}
        except Exception as e:  # noqa: BLE001
            logger.warning("[GUILD] xreg eval_bounty scoring failed (order stays submitted): %s", e)
    return {"ok": True, "order_id": oid, "status": "submitted"}


# ── DDR linkage: file a real Dispute row for the evidence/audit trail ─────────
async def _file_ddr_dispute(db: AsyncSession, complainant_did: str, defendant_did: str) -> Optional[str]:
    """File a DDR dispute (the audit-grade record contracts also files). GUILD still does its own
    money split (DDR moves no funds) — this links the two. Never blocks the guild flow."""
    try:
        from agentvault_registry.crud import crud_disputes
        d = await crud_disputes.create_dispute(db, complainant_did=complainant_did, defendant_did=defendant_did)
        return str(d.dispute_id if hasattr(d, "dispute_id") else d.id)
    except Exception as e:  # noqa: BLE001
        logger.warning("[GUILD] DDR dispute filing failed (%s vs %s): %s", complainant_did, defendant_did, e)
        return None


# ── GÖDEL FORGE (FG-2/FG-4) — royalty-carved payouts + eval_bounty auto-settle ────────────────
async def _payout_with_royalty(db: AsyncSession, payee: str, payout: Decimal, oid: str) -> None:
    """LOCAL settle legs via the SAME escrow rail. When FORGE_ROYALTY_ENABLED, the payout is carved
    up the payee's bundle fork lineage — legs sum EXACTLY to ``payout`` (fee untouched) → Δ=0 by
    construction (the eval-pay carve's guild twin). Off/no-lineage/any error → one undivided leg."""
    legs = [(payee, payout)]
    try:
        from agentvault_registry.forge_flags import royalty_enabled
        if royalty_enabled():
            from agentvault_registry.services import forge_royalty
            legs = await forge_royalty.compute_legs(db, payout, payee)
    except Exception as e:  # noqa: BLE001
        logger.warning("[GUILD] royalty carve unavailable (%s) — paying undivided", e)
        legs = [(payee, payout)]
    for i, (rdid, amt) in enumerate(legs):
        if amt <= 0:
            continue
        leg_name = "settle" if (i == 0 and rdid == payee) else f"settle_roy{i}"
        await guild_escrow.escrow_payout(db, rdid, amt, oid, leg_name)
    if len(legs) > 1:
        logger.info("[GUILD][FORGE] royalty carve on settle %s: %d legs, payee=%s", oid, len(legs), payee)
        # §NOTIFV2 forge.royalty_received — AFTER the payout loop above, so the money has moved.
        try:
            from agentvault_registry.services import forge_royalty as _fr
            await _fr.notify_royalty_legs(legs, source=f"guild order {oid}")
        except Exception:  # noqa: BLE001
            logger.debug("[NOTIFY] guild royalty notify failed", exc_info=True)


def _parse_eval_bounty(spec: str):
    """eval_bounty spec header — first line ``eval_bounty://<suite_id>/<min_score>`` = the POSTER's
    standing pre-authorization for OBJECTIVE settlement (the named eval suite decides, quorum-scored,
    never self-reported). Returns (suite_id, min_score) or None. Zero-migration v1 convention."""
    first = (spec or "").strip().splitlines()[0] if spec else ""
    if not first.startswith("eval_bounty://"):
        return None
    try:
        sid, ms = first[len("eval_bounty://"):].split("/", 1)
        return int(sid), float(ms)
    except Exception:  # noqa: BLE001
        return None


async def _run_bounty_eval(suite_id: int, candidate_did: str):
    """Run the bounty's suite against the candidate NOW; return the run's mean score (or None)."""
    try:
        from agentvault_registry.background_tasks.eval_runner import run_suite_once_for, EVALS_ENABLED
        if not EVALS_ENABLED:
            return None
        run_id = await run_suite_once_for(suite_id, candidate_did)
        if not run_id:
            return None
        from agentvault_registry.database import get_db_context
        async with get_db_context() as rdb:
            row = (await rdb.execute(text(
                "SELECT avg(score) FROM eval_results WHERE run_id = :r AND agent_did = :d"
            ), {"r": run_id, "d": candidate_did})).first()
        return float(row[0]) if row and row[0] is not None else None
    except Exception as e:  # noqa: BLE001
        logger.warning("[GUILD] eval_bounty eval failed: %s", e)
        return None


async def _auto_settle_eval_bounty(db: AsyncSession, o: dict, oid: str, *, actor_did: str, score: float) -> dict:
    """Objective auto-settle (poster pre-authorized via the spec header). Mirrors verify's LOCAL
    settle exactly: fee → royalty-carved payout → status flip (guarded) → stake release →
    5★ reputation fold → audits → credential → emit. Local workers only (cross-registry settle
    needs the poster's JWT on the request)."""
    seq = await _next_seq(db, oid)
    bounty = Decimal(str(o["bounty"]))
    fee = (bounty * Decimal(_order_fee_bps(o)) / Decimal(10000)).quantize(Decimal("0.0000000001"))
    payout = bounty - fee
    payee = o.get("payee_did") or o["worker_did"]
    # Status guard first (race with a concurrent poster verify): only WE settle from 'submitted'.
    res = await db.execute(text(
        "UPDATE guild_work_orders SET status='settled', fee_charged=:f, settled_at=now() "
        "WHERE id=:o AND status='submitted'"), {"f": fee, "o": oid})
    # §TRAVELREC — the record just changed, so move the card clock or no peer
    # that mirrors this agent will ever see the new number.
    await _tr_touch(db, o.get("worker_did"))
    if getattr(res, "rowcount", 0) == 0:
        return {"status": o.get("status", "submitted"), "note": "not settled (state changed concurrently)"}
    await _payout_with_royalty(db, payee, payout, oid)
    await _resolve_worker_stake(db, oid, o["worker_did"], o["worker_did"], "release")
    await guild_reputation.fold_work_reputation(db, o["poster_did"], payee, 5, float(bounty))
    await _audit(db, oid, seq, "verified", actor_did, {"stars": 5, "eval_bounty_score": score, "auto": True})
    await _audit(db, oid, seq + 1, "settled", actor_did,
                 {"payout": str(payout), "fee": str(fee), "payee": payee, "auto": "eval_bounty"})
    await db.commit()
    o2 = await _load(db, oid)
    credential = await guild_reputation.issue_work_credential(o2, stars=5)
    _emit("GuildOrderSettled", oid, {"worker": o["worker_did"], "payee": payee, "payout": str(payout),
                                     "fee": str(fee), "stars": 5, "auto": "eval_bounty", "score": score},
          idempotency_key=f"guild-settled-{oid}")
    await guild_contract_mirror.sync_from_order(db, oid)  # P3a mirror
    logger.info("[GUILD][FORGE] eval_bounty AUTO-SETTLED %s score=%.3f payee=%s payout=%s", oid, score, payee, payout)
    # §TWOAGENT G3 (V0432): an OBJECTIVE settle is still a verdict the worker's owner is owed, like verify's.
    _guild_webhook("guild.verified", [o["worker_did"], payee], {
        "order_id": oid, "title": o.get("title"), "worker_did": o["worker_did"], "currency": o.get("currency"),
        "via": "local", "accepted": True, "status": "settled", "payout": str(payout), "fee": str(fee), "stars": 5,
        "payee": payee, "auto": "eval_bounty", "eval_score": score})
    return {"status": "settled", "payout": float(payout), "fee": float(fee), "payee": payee,
            "stars": 5, "credential": credential}


async def _auto_settle_eval_bounty_xreg(db: AsyncSession, o: dict, oid: str, *, actor_did: str, score: float) -> dict:
    """Objective auto-settle for a CROSS-REGISTRY worker (Commander-approved 2026-07-20).

    No second authority and no poster impersonation: the poster's key already authorized this
    exact payout AT POST TIME (the escrow outflow + the ``eval_bounty://`` auto-settle contract
    in the spec). The cross-frame hop reuses the AGORA repatriation rail dividends already trust:
    escrow → gateway (local, blessed treasury helper), then an idempotent ATTRIBUTED CREDIT the
    repatriation batch drains home via /teg/send (smart send, auto-FX, Idempotency-Key) —
    money waits on the gateway, I-X5-accounted, until a send succeeds. Zero new money paths.
    """
    from agentvault_registry.services.exchange_service import GATEWAY_DID, _add_gateway_credit
    seq = await _next_seq(db, oid)
    bounty = Decimal(str(o["bounty"]))
    fee = (bounty * Decimal(_order_fee_bps(o)) / Decimal(10000)).quantize(Decimal("0.0000000001"))
    payout = bounty - fee
    payee = o.get("payee_did") or o["worker_did"]
    home = (o.get("worker_home_registry") or "").rstrip("/")
    # Status guard first (race with a concurrent poster verify): only WE settle from 'submitted'.
    res = await db.execute(text(
        "UPDATE guild_work_orders SET status='settled', fee_charged=:f, settled_at=now() "
        "WHERE id=:o AND status='submitted'"), {"f": fee, "o": oid})
    # §TRAVELREC — the record just changed, so move the card clock or no peer
    # that mirrors this agent will ever see the new number.
    await _tr_touch(db, o.get("worker_did"))
    if getattr(res, "rowcount", 0) == 0:
        return {"status": o.get("status", "submitted"), "note": "not settled (state changed concurrently)"}
    # Credit row BEFORE the park: the park's internal commit lands both atomically; a park
    # failure rolls the whole transaction (status + credit) back. The credit ref is UNIQUE
    # (ON CONFLICT DO NOTHING) so any replay is exactly-once.
    await _add_gateway_credit(db, payee, home, payout, "guild_settle", f"guild-{oid}-xfsettle")
    try:
        await guild_escrow.escrow_payout(db, GATEWAY_DID, payout, oid, "settle_xfge")
    except Exception as e:  # noqa: BLE001 — park failed: nothing moved; leave order submitted
        await db.rollback()
        logger.warning("[GUILD][FORGE] xreg eval_bounty park failed for %s (order stays submitted): %s", oid, e)
        return {"status": "submitted", "note": f"auto-settle park failed ({e}); order awaits retry/verify"}
    await _resolve_worker_stake(db, oid, o["worker_did"], o["worker_did"], "release")
    await guild_reputation.fold_work_reputation(db, o["poster_did"], payee, 5, float(bounty))
    await _audit(db, oid, seq, "verified", actor_did, {"stars": 5, "eval_bounty_score": score, "auto": True, "xreg": True})
    await _audit(db, oid, seq + 1, "settled", actor_did,
                 {"payout": str(payout), "fee": str(fee), "payee": payee, "auto": "eval_bounty",
                  "rail": "gateway_repat", "home": home})
    await db.commit()
    o2 = await _load(db, oid)
    credential = await guild_reputation.issue_work_credential(o2, stars=5)
    credential_traveled = False
    if credential:
        credential_traveled = await _ship_work_credential(db, o2, credential, 5)
    _emit("GuildOrderSettled", oid, {"worker": o["worker_did"], "payee": payee, "payout": str(payout),
                                     "fee": str(fee), "stars": 5, "auto": "eval_bounty", "score": score,
                                     "xreg": True, "rail": "gateway_repat"}, idempotency_key=f"guild-settled-{oid}")
    await guild_contract_mirror.sync_from_order(db, oid)  # P3a mirror
    logger.info("[GUILD][FORGE] xreg eval_bounty AUTO-SETTLED %s score=%.3f payee=%s payout=%s home=%s",
                oid, score, payee, payout, home)
    # §TWOAGENT G3 (V0432): the remote worker hears the objective verdict through its home, like verify's.
    _ship_guild_notice(o2, "verified", {"accepted": True, "status": "settled", "payout": str(payout), "fee": str(fee),
                                        "stars": 5, "payee": payee, "credential_traveled": credential_traveled})
    return {"status": "settled", "payout": float(payout), "fee": float(fee), "payee": payee,
            "stars": 5, "credential": credential, "credential_traveled": credential_traveled,
            "rail": "gateway_repat"}


# ── verify → settle ──────────────────────────────────────────────────────────

def _xf_answer(xr) -> tuple[bool, str]:
    """(paid, error) of a stage-through-the-poster transfer's answer (POST /api/v1/teg/cross-registry-transfer).
    §DOCSFIX D6-456's class, at the guild's two sites: the endpoint answers a transfer the TEGs did not complete with HTTP
    200 and "status": "failed", which is no payment (the order was recorded settled while the staged units stayed with
    the poster)."""
    if xr.status_code not in (200, 201):
        return False, f"HTTP {xr.status_code}: {xr.text[:200]}"
    try:
        body = xr.json()
    except ValueError:
        body = {}
    if isinstance(body, dict) and str(body.get("status") or "").strip().lower() == "failed":
        return False, f"status failed: {str(body.get('error_message') or '')[:200]}"
    return True, ""


@router.post("/api/v1/guild/orders/{oid}/verify", summary="Accept + pay, or reject → dispute (poster)")
async def verify(oid: str, body: VerifyIn, request: Request, agent: models.Agent = Depends(get_current_agent), db: AsyncSession = Depends(get_db)):
    _require_enabled()
    o = await _load(db, oid)
    if o["poster_did"] != agent.did:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Only the poster can verify")
    if o["status"] != "submitted":
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"Order is {o['status']}")
    if not body.accept:
        # REJECT → dispute. CLAIM submitted→disputed FIRST (guarded+committed) so a concurrent/retried
        # reject files exactly one dispute and the frozen escrow can't be double-touched (2026-07-23).
        claimed = await db.execute(text(
            "UPDATE guild_work_orders SET status='disputed' WHERE id=:o AND status='submitted'"), {"o": oid})
        if getattr(claimed, "rowcount", 0) == 0:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="Order is no longer submitted")
        await db.commit()
        # File a DDR dispute (its crud commits internally), then attach it to the claimed order.
        ddr_id = await _file_ddr_dispute(db, o["poster_did"], o["worker_did"])
        await db.execute(text("UPDATE guild_work_orders SET dispute_id=:d WHERE id=:o"), {"d": ddr_id, "o": oid})
        await _audit(db, oid, await _next_seq(db, oid), "disputed", agent.did, {"reason": body.feedback or "rejected", "ddr_dispute": ddr_id})
        await db.commit()
        _emit("GuildOrderDisputed", oid, {"by": agent.did, "ddr_dispute": ddr_id})
        _verdict = {"accepted": False, "status": "disputed", "ddr_dispute_id": ddr_id, "feedback": body.feedback}
        if o.get("worker_home_registry"):
            _ship_guild_notice(o, "verified", _verdict)
        else:
            _guild_webhook("guild.verified", [o["worker_did"]], {
                "order_id": oid, "title": o.get("title"), "worker_did": o["worker_did"], "via": "local", **_verdict})
        await guild_contract_mirror.sync_from_order(db, oid)  # P3a mirror
        return {"ok": True, "order_id": oid, "status": "disputed", "ddr_dispute_id": ddr_id}
    # SETTLE: the PAYEE gets bounty - fee. Payee = the org treasury (firm) if set, else the worker.
    # A member delivered the work (worker_did); the firm gets paid (payee_did). Fee retained in treasury. Δ=0.
    # CLAIM submitted→settling FIRST (guarded+committed): only ONE actor settles, so a concurrent or
    # retried verify can't double-pay (2026-07-23 drain fix — the stage-through-poster leg is NOT
    # idempotent even though the cross-registry transfer is). A racer sees 'settling' → 409; a genuine
    # xreg failure resets it to 'submitted' below so the poster's own retry still works.
    claimed = await db.execute(text(
        "UPDATE guild_work_orders SET status='settling' WHERE id=:o AND status='submitted'"), {"o": oid})
    if getattr(claimed, "rowcount", 0) == 0:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Order is no longer submitted (already settling/settled)")
    seq = await _next_seq(db, oid)
    # Timestamp the claim in the SAME commit (GA1): the reaper age-gates stuck 'settling' on this
    # event — without it a crash here would leave an undatable frozen order.
    await _audit(db, oid, seq, "settling", agent.did, {})
    await db.commit()
    seq += 1
    bounty = Decimal(str(o["bounty"]))
    fee = (bounty * Decimal(_order_fee_bps(o)) / Decimal(10000)).quantize(Decimal("0.0000000001"))
    payout = bounty - fee
    payee = o.get("payee_did") or o["worker_did"]
    if o.get("worker_home_registry"):
        # CROSS-REGISTRY settle saga (the contracts payment rail): the escrow can't credit a remote
        # TEG directly, so STAGE through the poster — treasury→poster ('xf_stage'), then the poster's
        # own /teg/cross-registry-transfer → worker (their JWT is on THIS request; 2PC, 0.5% fee to
        # the receiver's TEG). On failure: compensating re-deposit. The transfer's stable
        # Idempotency-Key makes retries exactly-once — a timed-out-but-committed leg replays from
        # cache and the money legs re-pair. Every leg an existing endpoint → Δ=0.
        nonce = secrets.token_hex(3)
        await guild_escrow.escrow_payout(db, o["poster_did"], payout, oid, f"xf_stage:{nonce}")
        auth_header = request.headers.get("Authorization", "")
        xf_ok = False; xf_err = ""; xr = None; xf_exc = None
        try:
            async with httpx.AsyncClient(timeout=30.0) as xc:
                xr = await xc.post(
                    "http://localhost:8000/api/v1/teg/cross-registry-transfer",
                    json={"receiver_did": payee, "amount": str(payout)},
                    headers={"Authorization": auth_header, "Content-Type": "application/json",
                             "Idempotency-Key": f"guild-{oid}-xfsettle"},
                )
                xf_ok, xf_err = _xf_answer(xr)
        except Exception as e:  # noqa: BLE001
            xf_err = str(e); xf_exc = e
        if not xf_ok:
            # §MONEY-R28: reopening is what makes the poster's retry work, and it is ONLY safe when
            # the stage leg was fully REVERSED. `xf_stage:{nonce}` is random per attempt, so a
            # reopened order stages a SECOND payout under a NEW key while the transfer replays from
            # its stable key and moves nothing — escrow out twice, worker paid once, the difference
            # left with the poster. Compensation FAILING is precisely the signal that the funds are
            # still staged with the poster (the timed-out-but-committed transfer is that case), so
            # the claim is held instead: the reaper age-gates a stuck xreg 'settling' to 'disputed'
            # for admin — surfaced, never auto-paid, never auto-refunded.
            # §DOCSFIX D6-776: and compensation SUCCEEDING is no proof either (a poster may hold units of its own), so
            # the staged funds go back only after an answer that proves nothing moved (_po.stage_failure_outcome)
            compensated = False
            _xo = _po.stage_failure_outcome(xr if xf_exc is None else None, xf_exc)
            if _xo.kind == _po.RETRY:
                try:  # compensate: re-escrow the staged funds (the poster just received them)
                    await guild_escrow.escrow_deposit(o["poster_did"], payout, oid, leg=f"xf_stage_return:{nonce}")
                    compensated = True
                except guild_escrow.GuildEscrowError as ce:
                    logger.error("[GUILD] XF compensation FAILED for %s (funds staged with poster): %s", oid, ce.message)
            else:
                logger.error("[GUILD] XF settle for %s failed without proof that nothing moved (%s); held for admin "
                             "review: %s", oid, _xo.reason, xf_err)
            if compensated:
                # funds are back in escrow → a fresh stage under a fresh key is correct
                await db.execute(text("UPDATE guild_work_orders SET status='submitted' WHERE id=:o AND status='settling'"), {"o": oid})
            else:
                await _audit(db, oid, await _next_seq(db, oid), "xf_stage_retained", agent.did,
                             {"amount": str(payout), "error": xf_err[:300], "held_for": "admin",
                              **({"outcome_unknown": True, "outcome": _xo.reason[:120]}
                                 if _xo.kind != _po.RETRY else {})})
            await db.commit()
            raise HTTPException(status.HTTP_502_BAD_GATEWAY,
                                detail=(f"Cross-registry payout failed ({xf_err}); bounty re-escrowed — retry verify"
                                        if compensated else
                                        f"Cross-registry payout failed ({xf_err}); the staged funds are still with "
                                        f"you and the order is held for admin review — do not retry"))
        logger.info("[GUILD] order %s cross-registry payout %s → %s (%s)", oid, payout, payee, o["worker_home_registry"])
    else:
        # GÖDEL FORGE (FG-2): local payouts carve fork royalties (legs sum EXACTLY to payout; Δ=0).
        await _payout_with_royalty(db, payee, payout, oid)
    await db.execute(text("UPDATE guild_work_orders SET status='settled', fee_charged=:f, settled_at=now() WHERE id=:o AND status='settling'"),
                     {"f": fee, "o": oid})
    # §TRAVELREC — the record just changed, so move the card clock or no peer
    # that mirrors this agent will ever see the new number.
    await _tr_touch(db, o.get("worker_did"))
    # STAKED WORK: success → release the worker's collateral back to them.
    await _resolve_worker_stake(db, oid, o["worker_did"], o["worker_did"], "release")
    # reputation (real EigenTrust): credit the PAYEE — a firm builds firm reputation; an individual builds theirs.
    await guild_reputation.fold_work_reputation(db, o["poster_did"], payee, body.stars, float(bounty))
    await _audit(db, oid, seq, "verified", agent.did, {"stars": body.stars})
    await _audit(db, oid, seq + 1, "settled", agent.did,
                 {"payout": str(payout), "fee": str(fee), "payee": payee, "firm": o.get("payee_org_id")})
    await db.commit()
    o2 = await _load(db, oid)
    credential = await guild_reputation.issue_work_credential(o2, stars=body.stars)
    # TRUST THAT TRAVELS (0118): a remote worker's reputation must land on their HOME graph —
    # ship the signed credential over the federation channel; the home verifies + folds. Best-effort.
    credential_traveled = False
    if o.get("worker_home_registry") and credential:
        credential_traveled = await _ship_work_credential(db, o2, credential, body.stars)
    _emit("GuildOrderSettled", oid, {"worker": o["worker_did"], "payee": payee, "firm": o.get("payee_org_id"),
                                     "payout": str(payout), "fee": str(fee), "stars": body.stars},
          idempotency_key=f"guild-settled-{oid}")
    await guild_contract_mirror.sync_from_order(db, oid)  # P3a mirror
    logger.info("[GUILD] order %s SETTLED worker=%s payee=%s firm=%s payout=%s", oid, o["worker_did"], payee, o.get("payee_org_id"), payout)

    # §NOTIFV2 (2026-07-27): work verified and paid → tell whoever owns the PAYEE (worker or firm).
    # Post-commit and post-settle by design: everything above can still 502 and re-escrow the
    # bounty, and a "you got paid" push for money that bounced back is worse than no push.
    # notify_agent_owners resolves DID → owning developer, so a remote payee on a cross-registry
    # settle simply resolves to nobody here; their home registry is the one that owes them the ping.
    try:
        import asyncio as _aio
        from agentvault_registry.background_tasks.push_notify import notify_agent_owners
        _aio.create_task(notify_agent_owners(
            "guild.verified_paid", [payee],
            title="Work verified and paid",
            message=f"Order {oid}: {payout} paid to {payee} ({body.stars}/5 stars).",
            tags="moneybag", priority="high", click="/ui/#/guild"))
    except Exception:  # noqa: BLE001
        logger.debug("guild.verified_paid notify skipped", exc_info=True)
    _verdict = {"accepted": True, "status": "settled", "payout": str(payout), "fee": str(fee), "stars": body.stars,
                "payee": payee, "credential_traveled": credential_traveled}
    if o.get("worker_home_registry"):
        _ship_guild_notice(o2, "verified", _verdict)
    else:
        _guild_webhook("guild.verified", [o["worker_did"], payee], {
            "order_id": oid, "title": o.get("title"), "worker_did": o["worker_did"], "currency": o.get("currency"),
            "via": "local", **_verdict})

    # §CHATDESK C5 — a FIRM engagement settled: the org's room gets the
    # receipt (post-commit, best-effort; the money is already final above).
    if o.get("payee_org_id"):
        from agentvault_registry.services.org_room_events import post_org_receipt
        await post_org_receipt(db, o["payee_org_id"], kind="guild.settled",
                               amount=str(payout), currency=o.get("currency"),
                               ref=f"guild-{oid}", memo=(o.get("title") or "")[:120],
                               counterparty=o.get("worker_did"))

    return {"ok": True, "order_id": oid, "status": "settled", "payout": float(payout), "fee": float(fee),
            "payee": payee, "firm": o.get("payee_org_id"), "stars": body.stars, "credential": credential,
            "credential_traveled": credential_traveled}


# ── v2 (0119): poster-triggered payout of a HELD remote dispute split ────────
@router.post("/api/v1/guild/orders/{oid}/dispute-payout", summary="Execute a held remote dispute split (poster)")
async def dispute_payout(oid: str, request: Request, agent: models.Agent = Depends(get_current_agent),
                         db: AsyncSession = Depends(get_db)):
    """Both shares of a remote split are held in treasury escrow until the POSTER triggers this.
    Worker leg = the exact verify() stage-through-poster saga (treasury→poster 'xfd_stage', then the
    poster's own /teg/cross-registry-transfer with a stable Idempotency-Key → exactly-once); then the
    poster's own refund share pays out locally. Worker leg FIRST: a failure re-escrows and retries."""
    _require_enabled()
    o = await _load(db, oid)
    if o["poster_did"] != agent.did:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Only the poster can trigger the dispute payout")
    if o["status"] != "resolved":
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"Order is {o['status']}, not resolved")
    # CLAIM resolved→resolving FIRST (2026-07-23): a concurrent/retried dispute-payout can't double-pay.
    claimed = await db.execute(text(
        "UPDATE guild_work_orders SET status='resolving' WHERE id=:o AND status='resolved'"), {"o": oid})
    if getattr(claimed, "rowcount", 0) == 0:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Order is no longer resolved (already resolving/settled)")
    # Timestamp the claim in the SAME commit (GA1): the reaper age-gates stuck 'resolving' on this.
    await _audit(db, oid, await _next_seq(db, oid), "resolving", agent.did, {"via": "dispute_payout"})
    await db.commit()
    worker_amt = Decimal(str(o.get("resolved_worker_amt") or 0))
    poster_amt = Decimal(str(o.get("resolved_poster_amt") or 0))
    payee = o.get("payee_did") or o["worker_did"]
    if worker_amt > 0:
        nonce = secrets.token_hex(3)
        await guild_escrow.escrow_payout(db, o["poster_did"], worker_amt, oid, f"xfd_stage:{nonce}")
        auth_header = request.headers.get("Authorization", "")
        xf_ok = False; xf_err = ""; xr = None; xf_exc = None
        try:
            async with httpx.AsyncClient(timeout=30.0) as xc:
                xr = await xc.post(
                    "http://localhost:8000/api/v1/teg/cross-registry-transfer",
                    json={"receiver_did": payee, "amount": str(worker_amt)},
                    headers={"Authorization": auth_header, "Content-Type": "application/json",
                             "Idempotency-Key": f"guild-{oid}-xfdispute"},
                )
                xf_ok, xf_err = _xf_answer(xr)
        except Exception as e:  # noqa: BLE001
            xf_err = str(e); xf_exc = e
        if not xf_ok:
            # §MONEY-R28 (same class as the settle path above): only reopen for a fresh stage when
            # the previous one was fully reversed, or the retry drains escrow a second time under a
            # new `xfd_stage:{nonce}` while the transfer replays from its stable key.
            # §DOCSFIX D6-776: ...and only after an answer that proves nothing moved (_po.stage_failure_outcome)
            compensated = False
            _xo = _po.stage_failure_outcome(xr if xf_exc is None else None, xf_exc)
            if _xo.kind == _po.RETRY:
                try:
                    await guild_escrow.escrow_deposit(o["poster_did"], worker_amt, oid, leg=f"xfd_stage_return:{nonce}")
                    compensated = True
                except guild_escrow.GuildEscrowError as ce:
                    logger.error("[GUILD] dispute-payout compensation FAILED for %s: %s", oid, ce.message)
            else:
                logger.error("[GUILD] dispute-payout for %s failed without proof that nothing moved (%s); held for "
                             "admin review: %s", oid, _xo.reason, xf_err)
            if compensated:
                await db.execute(text("UPDATE guild_work_orders SET status='resolved' WHERE id=:o AND status='resolving'"), {"o": oid})
            else:
                await _audit(db, oid, await _next_seq(db, oid), "xf_stage_retained", agent.did,
                             {"amount": str(worker_amt), "error": xf_err[:300], "held_for": "admin",
                              "leg": "dispute_payout",
                              **({"outcome_unknown": True, "outcome": _xo.reason[:120]}
                                 if _xo.kind != _po.RETRY else {})})
            await db.commit()
            raise HTTPException(status.HTTP_502_BAD_GATEWAY,
                                detail=(f"Cross-registry worker leg failed ({xf_err}); re-escrowed — retry"
                                        if compensated else
                                        f"Cross-registry worker leg failed ({xf_err}); the staged funds are still "
                                        f"with the poster and the order is held for admin review — do not retry"))
    if poster_amt > 0:
        await guild_escrow.escrow_payout(db, o["poster_did"], poster_amt, oid, "split_poster")
    await db.execute(text("UPDATE guild_work_orders SET status='settled', settled_at=now() WHERE id=:o AND status='resolving'"), {"o": oid})
    # §TRAVELREC — the record just changed, so move the card clock or no peer
    # that mirrors this agent will ever see the new number.
    await _tr_touch(db, o.get("worker_did"))
    await _audit(db, oid, await _next_seq(db, oid), "settled", agent.did,
                 {"resolution": "split_paid", "worker": str(worker_amt), "poster": str(poster_amt)})
    await db.commit()
    _emit("GuildOrderSettled", oid, {"worker": o["worker_did"], "split": True,
                                     "worker_amt": str(worker_amt), "poster_amt": str(poster_amt)},
          idempotency_key=f"guild-settled-{oid}")
    await guild_contract_mirror.sync_from_order(db, oid)  # P3a mirror
    logger.info("[GUILD] dispute split PAID for %s: worker=%s poster=%s", oid, worker_amt, poster_amt)
    return {"ok": True, "order_id": oid, "status": "settled",
            "worker_paid": float(worker_amt), "poster_refunded": float(poster_amt)}


# ── cancel (refund while open) ───────────────────────────────────────────────
@router.post("/api/v1/guild/orders/{oid}/cancel", summary="Cancel an OPEN task → refund (poster)")
async def cancel(oid: str, agent: models.Agent = Depends(get_current_agent), db: AsyncSession = Depends(get_db)):
    _require_enabled()
    o = await _load(db, oid)
    if o["poster_did"] != agent.did:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Only the poster can cancel")
    if o["status"] != "open":
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"Order is {o['status']} — cannot cancel")
    # CLAIM the transition FIRST (guarded + committed) so the refund runs EXACTLY ONCE even under a
    # concurrent cancel, a client retry, or a reaper expiry racing the same order (2026-07-23 drain fix).
    claimed = await db.execute(text(
        "UPDATE guild_work_orders SET status='cancelled', settled_at=now() WHERE id=:o AND status='open'"), {"o": oid})
    if getattr(claimed, "rowcount", 0) == 0:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Order is no longer open (already cancelling/expired)")
    await _audit(db, oid, await _next_seq(db, oid), "cancelled", agent.did, {"refund": str(o["bounty"])})
    await db.commit()  # claim durable BEFORE money → a racer sees 'cancelled' and cannot re-refund
    await guild_escrow.escrow_payout(db, o["poster_did"], Decimal(str(o["bounty"])), oid, "refund")
    await _refund_all_stakes(db, oid)  # STAKED WORK: return every bidder's collateral
    await db.commit()
    _emit("GuildOrderCancelled", oid, {"refund": str(o["bounty"])})
    await guild_contract_mirror.sync_from_order(db, oid)  # P3a mirror
    return {"ok": True, "order_id": oid, "status": "cancelled", "refund": float(o["bounty"])}


@router.get("/api/v1/guild/my-firm", summary="Can my active agent bid as a firm? (its org + AGORA treasury)")
async def my_firm(agent: models.Agent = Depends(get_current_agent), db: AsyncSession = Depends(get_db)):
    """The calling agent's organization + whether it's AGORA-listed (a firm can only be paid if listed).
    Drives the FE 'bid as my firm' toggle."""
    _require_enabled()
    org_id = (await db.execute(text("SELECT organization_id FROM agents WHERE did=:d"), {"d": agent.did})).scalar()
    if not org_id:
        return {"has_org": False}
    name = (await db.execute(text("SELECT name FROM organizations WHERE id=:o"), {"o": org_id})).scalar()
    treasury = await _org_treasury(db, org_id)
    return {"has_org": True, "org_id": org_id, "org_name": name, "listed": bool(treasury), "treasury_did": treasury}


@router.get("/api/v1/guild/mine", summary="My orders (as poster and worker)")
async def mine(agent: models.Agent = Depends(get_current_agent), db: AsyncSession = Depends(get_db)):
    _require_enabled()
    rows = (await db.execute(text("""
        SELECT id, poster_did, worker_did, title, bounty, currency, status, created_at, settled_at
        FROM guild_work_orders WHERE poster_did=:d OR worker_did=:d ORDER BY created_at DESC LIMIT 100
    """), {"d": agent.did})).mappings().all()
    return {"orders": [dict(r) for r in rows], "total": len(rows)}


# ── admin oversight + dispute resolution ─────────────────────────────────────
def _require_admin(dev: models.Developer):
    if not admin_credential(dev):   # D6-057 (§POCKETPAIR): an admin's scoped key is not admin (the resolve splits a bounty)
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Admin only")


@router.get("/api/v1/admin/guild/orders", summary="All orders (admin)")
async def admin_orders(dev: models.Developer = Depends(get_current_developer), db: AsyncSession = Depends(get_db)):
    _require_admin(dev)
    rows = (await db.execute(text("""
        SELECT id, poster_did, worker_did, title, bounty, currency, status, fee_charged, created_at, settled_at
        FROM guild_work_orders ORDER BY created_at DESC LIMIT 200
    """))).mappings().all()
    # escrow health: Σ bounties currently held (open/awarded/submitted/disputed)
    held = (await db.execute(text(
        "SELECT COALESCE(SUM(bounty),0) FROM guild_work_orders WHERE status IN ('open','awarded','submitted','disputed')"
    ))).scalar()
    return {"orders": [dict(r) for r in rows], "total": len(rows), "escrow_held": str(held),
            "enabled": guild_enabled(), "fee_bps": _fee_bps()}


@router.post("/api/v1/admin/guild/orders/{oid}/resolve", summary="Resolve a disputed order — split bounty (admin)")
async def admin_resolve(oid: str, body: DisputeResolveIn, dev: models.Developer = Depends(get_current_developer), db: AsyncSession = Depends(get_db)):
    _require_admin(dev)
    o = await _load(db, oid)
    if o["status"] != "disputed":
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"Order is {o['status']}, not disputed")
    # CLAIM disputed→resolving FIRST (guarded+committed): a concurrent/retried resolve can't double-split
    # the frozen escrow (2026-07-23). A genuine xreg park failure resets it to 'disputed' for retry.
    claimed = await db.execute(text(
        "UPDATE guild_work_orders SET status='resolving' WHERE id=:o AND status='disputed'"), {"o": oid})
    if getattr(claimed, "rowcount", 0) == 0:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Order is no longer disputed (already resolving/settled)")
    # Timestamp the claim in the SAME commit (GA1): the reaper age-gates stuck 'resolving' on this.
    await _audit(db, oid, await _next_seq(db, oid), "resolving", f"admin:{dev.id}", {"via": "admin_resolve"})
    await db.commit()
    bounty = Decimal(str(o["bounty"]))
    worker_amt = (bounty * Decimal(str(body.worker_share))).quantize(Decimal("0.0000000001"))
    poster_amt = bounty - worker_amt
    # CROSS-REGISTRY split (Commander-approved 2026-07-20): pay BOTH legs IMMEDIATELY, server-side.
    # The old v2 (0119) HOLD existed because the worker leg staged through the poster's JWT; the
    # worker share now rides the same gateway-repatriation rail as xreg eval-bounty settles —
    # ref-idempotent attributed credit FIRST, then escrow→gateway park (the park's commit lands
    # both) — and the poster share is a plain local escrow payout. The admin ruling IS the
    # authorization; the escrow already held the money; no second authority exists.
    # (/dispute-payout stays untouched: it drains any pre-change orders still parked 'resolved'.)
    if o.get("worker_home_registry") and worker_amt > 0:
        from agentvault_registry.services.exchange_service import GATEWAY_DID, _add_gateway_credit
        stake_outcome = None
        if o["worker_did"]:
            action = "release" if Decimal(str(body.worker_share)) >= Decimal(1) else "slash"
            stake_outcome = await _resolve_worker_stake(db, oid, o["worker_did"], o["poster_did"], action)
        home = (o.get("worker_home_registry") or "").rstrip("/")
        await _add_gateway_credit(db, o["worker_did"], home, worker_amt, "guild_dispute", f"guild-{oid}-xfdispute")
        try:
            await guild_escrow.escrow_payout(db, GATEWAY_DID, worker_amt, oid, "split_worker_xfge")
        except Exception as e:  # noqa: BLE001 — park failed: nothing moved; reset the claim so resolve retries
            await db.rollback()
            await db.execute(text("UPDATE guild_work_orders SET status='disputed' WHERE id=:o AND status='resolving'"), {"o": oid})
            await db.commit()
            logger.warning("[GUILD] remote dispute park failed for %s (order back to disputed): %s", oid, e)
            raise HTTPException(status.HTTP_502_BAD_GATEWAY,
                                detail=f"Dispute payout park failed ({e}); order stays disputed — retry resolve")
        if poster_amt > 0:
            await guild_escrow.escrow_payout(db, o["poster_did"], poster_amt, oid, "split_poster")
        await db.execute(text(
            "UPDATE guild_work_orders SET status='settled', resolved_worker_amt=:w, resolved_poster_amt=:p, "
            "settled_at=now() WHERE id=:o AND status='resolving'"), {"w": worker_amt, "p": poster_amt, "o": oid})
        # §TRAVELREC — the record just changed, so move the card clock or no peer
        # that mirrors this agent will ever see the new number.
        await _tr_touch(db, o.get("worker_did"))
        await _audit(db, oid, await _next_seq(db, oid), "settled", f"admin:{dev.id}",
                     {"resolution": "split", "rail": "gateway_repat", "worker": str(worker_amt),
                      "poster": str(poster_amt), "stake": stake_outcome, "note": body.note})
        await db.commit()
        _emit("GuildOrderResolved", oid, {"worker": str(worker_amt), "poster": str(poster_amt),
                                          "rail": "gateway_repat"})
        await guild_contract_mirror.sync_from_order(db, oid)  # P3a mirror
        return {"ok": True, "order_id": oid, "status": "settled", "rail": "gateway_repat",
                "worker_paid": float(worker_amt), "poster_refunded": float(poster_amt)}
    # Two zero-sum legs summing to the held bounty → Δ=0. The split primitive disputes lacks.
    if worker_amt > 0 and o["worker_did"]:
        await guild_escrow.escrow_payout(db, o["worker_did"], worker_amt, oid, "split_worker")
    if poster_amt > 0:
        await guild_escrow.escrow_payout(db, o["poster_did"], poster_amt, oid, "split_poster")
    # STAKED WORK: the worker's collateral. Full win (share≥1) → release to worker; otherwise the poster
    # was wronged → SLASH the stake to the poster. Δ-neutral treasury leg either way.
    stake_outcome = None
    if o["worker_did"]:
        if Decimal(str(body.worker_share)) >= Decimal(1):
            stake_outcome = await _resolve_worker_stake(db, oid, o["worker_did"], o["worker_did"], "release")
        else:
            stake_outcome = await _resolve_worker_stake(db, oid, o["worker_did"], o["poster_did"], "slash")
    await db.execute(text("UPDATE guild_work_orders SET status='settled', settled_at=now() WHERE id=:o AND status='resolving'"), {"o": oid})
    # §TRAVELREC — the record just changed, so move the card clock or no peer
    # that mirrors this agent will ever see the new number.
    await _tr_touch(db, o.get("worker_did"))
    await _audit(db, oid, await _next_seq(db, oid), "settled", f"admin:{dev.id}",
                 {"resolution": "split", "worker": str(worker_amt), "poster": str(poster_amt), "stake": stake_outcome, "note": body.note})
    await db.commit()
    _emit("GuildOrderResolved", oid, {"worker": str(worker_amt), "poster": str(poster_amt)})
    await guild_contract_mirror.sync_from_order(db, oid)  # P3a mirror
    return {"ok": True, "order_id": oid, "status": "settled", "worker_paid": float(worker_amt), "poster_refunded": float(poster_amt)}


# ═════════════════════════════════════════════════════════════════════════════
# CROSS-REGISTRY GUILD (mirrors the contracts federation pattern verbatim)
#   host side  : federation-authenticated bid/submit (peer registry vouches the agent)
#   home side  : agent-JWT proxy → TRUSTED_REGISTRIES allowlist → peer over mTLS/secret
#   discovery  : network-board fan-out over the same allowlist (best-effort, cached)
# Money rules (all existing rails, Δ=0): v2 (0119) accepts staked orders via home-held
# collateral AND firm bids (org validated on the bidder's HOME, payee asserted with the
# relayed bid); settle rides the staged saga in verify() above.
# ═════════════════════════════════════════════════════════════════════════════
_VALID_DID_PREFIXES = ("did:cos:", "did:theprotocol:", "did:agentvault:")


class FederatedBidIn(BaseModel):
    bidder_did: str = Field(..., max_length=120)
    home_registry_url: str = Field(..., max_length=300, description="The bidder's home registry (peer)")
    price: float = Field(..., gt=0)
    eta_seconds: Optional[int] = Field(None, ge=60, le=2592000)
    pitch: Optional[str] = Field(None, max_length=2000)
    # Home-asserted reputation (the peer registry vouches, same trust as the identity itself).
    # Lets remote agents bid on min_reputation tasks — trust that travels (0118).
    reputation: Optional[float] = Field(None, ge=0)
    # v2 (0119): home-asserted collateral (escrowed on the HOME treasury before relay) + firm payee
    stake_held: Optional[float] = Field(None, ge=0)
    # org ids are UUID STRINGS (organizations.id VARCHAR) — an int type here 422s every real org
    payee_org_id: Optional[str] = Field(None, max_length=64)
    payee_did: Optional[str] = Field(None, max_length=120)


class FederatedSubmitIn(BaseModel):
    worker_did: str = Field(..., max_length=120)
    deliverable: Optional[dict] = None


class GuildCrossRegistryProxyIn(BaseModel):
    target_registry_url: str = Field(..., description="Base URL of the registry hosting the order")
    order_id: str = Field(..., max_length=40)
    action: str = Field(..., description="'bid' or 'submit'")
    price: Optional[float] = Field(None, gt=0)
    eta_seconds: Optional[int] = Field(None, ge=60, le=2592000)
    pitch: Optional[str] = Field(None, max_length=2000)
    deliverable: Optional[dict] = None
    # v2 (0119): firm bid — org validated on HOME. Org ids are UUID STRINGS (organizations.id VARCHAR).
    on_behalf_of_org_id: Optional[str] = Field(None, max_length=64)


@router.get("/api/v1/federation/guild/board", summary="Open board for federation peers (network fan-out)")
async def federated_board(db: AsyncSession = Depends(get_db),
                          peer_spiffe_id: str = Security(get_federation_identity)):
    """
    The open Guild board for federation peers (the network board reads it), served under /api/v1/federation/ so
    every federation proxy passes it unchanged.
    """
    return await list_orders(status_filter="open", limit=50, db=db)


@router.post("/api/v1/federation/guild/orders/{oid}/bid", summary="Bid on behalf of a cross-registry agent (federation)")
async def place_bid_federated(oid: str, body: FederatedBidIn, db: AsyncSession = Depends(get_db),
                              peer_spiffe_id: str = Security(get_federation_identity)):
    """The peer registry vouches that bidder_did is a valid, authenticated agent on its side
    (contracts accept-federated precedent). No local agent JWT required."""
    _require_enabled()
    if not any(body.bidder_did.startswith(p) for p in _VALID_DID_PREFIXES):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"Invalid bidder DID format: {body.bidder_did}")
    # §TWOAGENT (2026-09-23): the vouching registry must BE the bidder's home. Any federation caller used to be able to
    # bid in any agent's name by writing another registry into home_registry_url, with a reputation of its choosing.
    if not await _caller_is(db, peer_spiffe_id, body.home_registry_url):
        logger.warning("[GUILD] federated bid on %s refused: caller %s is not %s", oid, peer_spiffe_id,
                       body.home_registry_url)
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            detail="the calling registry is not the bidder's home registry: a registry vouches only "
                                   "for its own agents")
    # §REPBOND — a cross-registry bidder is read through its mirrored card's signed extension.
    await _rb.gate(db, body.bidder_did, site="guild_bid")
    await _ep.gate(db, body.bidder_did, site="guild_bid")
    o = await _load(db, oid)
    if o["status"] != "open":
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"Order is {o['status']}")
    if body.bidder_did == o["poster_did"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Cannot bid on your own task")
    # §FIRMHIRE — a firm-addressed bounty needs LOCAL org membership; a remote
    # bidder structurally cannot carry it (org membership is frame-local).
    await _firm_bounty_gate(db, o, None)
    if Decimal(str(body.price)) > Decimal(str(o["bounty"])):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Bid price exceeds the bounty")
    # v2 (0119): staked orders accept remote bids when the HOME asserts it locked the collateral
    # (escrowed on the home treasury before relay — same trust as the mTLS-vouched identity).
    stake_needed = Decimal(str(o["stake_required"])) if o.get("stake_required") else Decimal(0)
    if stake_needed > 0 and Decimal(str(body.stake_held or 0)) < stake_needed:
        raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED,
                            detail=f"Task with collateral: home-held collateral of {stake_needed} required (asserted: {body.stake_held or 0})")
    if o["min_reputation"] is not None and float(o["min_reputation"]) > 0:
        # 0118 trust-that-travels: the bidder's HOME vouches for their reputation over the same
        # mTLS federation channel that vouches for their identity. No relayed rep → not eligible.
        if body.reputation is None or float(body.reputation) < float(o["min_reputation"]):
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                detail=f"This task requires reputation ≥ {o['min_reputation']} "
                                       f"(home-asserted: {body.reputation if body.reputation is not None else 'none'})")
    # GA4 (2026-07-24): re-validate the peer-asserted FIRM payee. Identity/rep
    # vouching only gates ACCESS; the payee hint redirects MONEY, so it gets its
    # own checks: present, well-formed, not the bidder, and NOT a local agent —
    # a remote org's treasury cannot live on this registry, and accepting a
    # local DID here would let a compromised peer route payouts to an attacker's
    # account on OUR frame. (Full home-side org membership+treasury re-resolve
    # needs a federation org-verify endpoint — deferred; this closes the
    # redirect-to-local vector.)
    if body.payee_org_id:
        if not body.payee_did:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail="Firm bid asserts payee_org_id but no payee_did")
        if not any(body.payee_did.startswith(p) for p in _VALID_DID_PREFIXES):
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                detail=f"Invalid payee DID format: {body.payee_did}")
        if body.payee_did == body.bidder_did:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail="Firm payee cannot be the bidder itself")
        _local_payee = (await db.execute(
            text("SELECT 1 FROM agents WHERE did = :p"), {"p": body.payee_did}
        )).first()
        if _local_payee:
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                detail="Remote firm payee resolves to a LOCAL agent — rejected "
                                       "(a remote org treasury cannot live on this registry)")
    try:
        bid_id = (await db.execute(text("""
            INSERT INTO guild_bids (order_id, bidder_did, price, eta_seconds, pitch, status, home_registry_url, reputation,
                stake_amount, stake_escrow_ref, stake_status, on_behalf_of_org_id, payee_did_hint)
            VALUES (:o,:d,:pr,:eta,:pi,'open',:hr,:rep,:sa,:sr,:ss,:org,:ph)
            RETURNING id
        """), {"o": oid, "d": body.bidder_did, "pr": Decimal(str(body.price)), "eta": body.eta_seconds,
               "pi": body.pitch, "hr": body.home_registry_url.rstrip("/"), "rep": body.reputation,
               "sa": Decimal(str(body.stake_held)) if stake_needed > 0 else None,
               "sr": f"remote:{body.home_registry_url.rstrip('/')}" if stake_needed > 0 else None,
               "ss": "held" if stake_needed > 0 else None,
               "org": body.payee_org_id, "ph": body.payee_did})).scalar()
    except Exception:  # unique(order,bidder)
        raise HTTPException(status.HTTP_409_CONFLICT, detail="This agent already has a live bid on this task")
    flagged = _not_intended_worker(o, body.bidder_did)  # V0650 (f): accepted, and marked
    bid_audit = {"price": str(body.price), "via": "federation", "peer": peer_spiffe_id, "home": body.home_registry_url}
    if flagged:
        bid_audit["not_intended_worker"] = True
    await _audit(db, oid, await _next_seq(db, oid), "bid", body.bidder_did, bid_audit)
    await db.commit()
    _emit("GuildBidPlaced", oid, {"bidder": body.bidder_did, "price": str(body.price), "via": "federation"})
    logger.info("[GUILD] federated bid on %s by %s (peer=%s)", oid, body.bidder_did, peer_spiffe_id)
    # §TWOAGENT G3: a bid from another frame needs the poster's attention exactly as a local one does (push AND hook).
    try:
        import asyncio as _aio
        from agentvault_registry.background_tasks.push_notify import notify_agent_owners
        _aio.create_task(notify_agent_owners(
            "guild.bid_received", [o["poster_did"]],
            title="New bid on your order",
            message=f"Order {oid}: {body.bidder_did[:32]} bid {body.price} (from another registry).",
            tags="hammer", priority="default", click="/ui/#/guild"))
    except Exception:  # noqa: BLE001
        logger.debug("guild.bid_received notify skipped", exc_info=True)
    _guild_webhook("guild.bid_received", [o["poster_did"]], {
        "order_id": oid, "title": o.get("title"), "bid_id": bid_id, "bidder_did": body.bidder_did,
        "price": str(body.price), "currency": o.get("currency"), "via": "federation",
        "home_registry": body.home_registry_url.rstrip("/"), "firm": body.payee_org_id,
        "not_intended_worker": flagged,
        "award_with": f"POST /api/v1/guild/orders/{oid}/award with bid_id={bid_id}"})
    return {"ok": True, "order_id": oid, "bidder": body.bidder_did, "bid_id": bid_id, "via": "federation",
            "intended_worker_did": o.get("intended_worker_did"), "not_intended_worker": flagged}


@router.post("/api/v1/federation/guild/orders/{oid}/submit", summary="Deliver work for a cross-registry worker (federation)")
async def submit_federated(oid: str, body: FederatedSubmitIn, db: AsyncSession = Depends(get_db),
                           peer_spiffe_id: str = Security(get_federation_identity)):
    _require_enabled()
    o = await _load(db, oid)
    if o["status"] != "awarded":
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"Order is {o['status']}")
    if o["worker_did"] != body.worker_did:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Only the awarded worker can submit")
    # §TWOAGENT (2026-09-23): only the awarded worker's HOME may deliver for it. Any federation caller used to be able
    # to move an order to 'submitted' in a remote worker's name, and a reject of that delivery disputes the real worker.
    if not await _caller_is(db, peer_spiffe_id, o.get("worker_home_registry")):
        logger.warning("[GUILD] federated submit on %s refused: caller %s is not the worker's home %s", oid,
                       peer_spiffe_id, o.get("worker_home_registry"))
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            detail="the calling registry is not the awarded worker's home registry")
    await db.execute(text("UPDATE guild_work_orders SET status='submitted', deliverable=CAST(:dv AS JSONB), submitted_at=now() WHERE id=:o"),
                     {"dv": json.dumps(body.deliverable) if body.deliverable else None, "o": oid})
    await _audit(db, oid, await _next_seq(db, oid), "submitted", body.worker_did, {"via": "federation", "peer": peer_spiffe_id})
    await db.commit()
    _emit("GuildWorkSubmitted", oid, {"worker": body.worker_did, "via": "federation"})
    try:
        import asyncio as _aio
        from agentvault_registry.background_tasks.push_notify import notify_agent_owners
        _aio.create_task(notify_agent_owners(
            "guild.work_submitted", [o["poster_did"]],
            title="Work delivered for review",
            message=f"Order {oid} has a delivery waiting on your verification.",
            tags="package", priority="default", click="/ui/#/guild"))
    except Exception:  # noqa: BLE001
        logger.debug("guild.work_submitted notify skipped", exc_info=True)
    _guild_webhook("guild.work_submitted", [o["poster_did"]], {
        "order_id": oid, "title": o.get("title"), "worker_did": body.worker_did, "via": "federation",
        "deliverable_keys": list((body.deliverable or {}).keys()),
        "verify_with": f"POST /api/v1/guild/orders/{oid}/verify with accept=true (pay) or false (dispute)"})
    return {"ok": True, "order_id": oid, "status": "submitted", "via": "federation"}


# ── v2 (0119): remote stake lifecycle over the federation channel ────────────
async def _notify_home_stake(db: AsyncSession, home_url: str, oid: str, bidder_did: str, action: str) -> bool:
    """HOST → HOME: release/slash the collateral held on the bidder's home treasury. Best-effort;
    the home reaper safety-nets stale 'held' rows back to the bidder after 14 days."""
    try:
        target = await _resolve_peer_url(db, home_url)
        cfg, fed_headers = _fed_client_config(target)
        async with httpx.AsyncClient(**cfg) as client:
            r = await client.post(f"{target}/api/v1/federation/guild/stake",
                                  json={"order_id": oid, "bidder_did": bidder_did, "action": action,
                                        "host_registry": _self_public_url()},
                                  headers=fed_headers)
        ok = r.status_code in (200, 201)
        logger.info("[GUILD] remote stake %s for %s/%s → %s: %s", action, oid, bidder_did[-12:], home_url, r.status_code)
        return ok
    except Exception as e:  # noqa: BLE001
        logger.warning("[GUILD] remote stake %s notify failed for %s: %s", action, oid, e)
        return False


class FederatedStakeIn(BaseModel):
    order_id: str = Field(..., max_length=40)
    bidder_did: str = Field(..., max_length=120)
    action: str = Field(..., description="'release' or 'slash'")
    host_registry: str = Field(..., max_length=300)


@router.post("/api/v1/federation/guild/stake", summary="Release/slash home-held collateral (federation)")
async def federated_stake_action(body: FederatedStakeIn, db: AsyncSession = Depends(get_db),
                                 peer_spiffe_id: str = Security(get_federation_identity)):
    """HOME side: the deposit already sits in OUR treasury (escrowed at proxy-bid time).
    release → treasury pays the bidder back; slash → zero legs (it just never returns).
    Idempotent via the status guard. Δ=0 either way."""
    _require_enabled()
    if body.action not in ("release", "slash"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"Invalid action: {body.action}")
    # §TWOAGENT (2026-09-23): only the HOST whose order holds this collateral may release or slash it. Any federation
    # caller used to be able to slash a bidder's stake held here by naming the host registry in the body. A stranger
    # gets the answer a stake that is not held gets, which confirms nothing.
    if not await _caller_is(db, peer_spiffe_id, body.host_registry):
        logger.warning("[GUILD] remote stake %s on %s/%s refused: caller %s is not %s", body.action, body.order_id,
                       body.bidder_did[-12:], peer_spiffe_id, body.host_registry)
        _count_silent("stake_action_wrong_caller")
        return {"ok": True, "already": True}
    row = (await db.execute(text("""
        SELECT id, amount FROM guild_remote_stakes
        WHERE host_registry=:h AND order_id=:o AND bidder_did=:d AND status='held'
    """), {"h": target_pub(body.host_registry), "o": body.order_id, "d": body.bidder_did})).first()
    if not row:
        return {"ok": True, "already": True}  # idempotent replay / nothing held
    if body.action == "release":
        try:
            await guild_escrow.escrow_payout(db, body.bidder_did, Decimal(str(row.amount)),
                                             body.order_id, f"xfstake_release:{body.bidder_did[-12:]}")
        except guild_escrow.GuildEscrowError as e:
            raise refusal_from_error(e) or HTTPException(
                status.HTTP_502_BAD_GATEWAY, detail=f"Collateral release failed: {e.message}")
    await db.execute(text("UPDATE guild_remote_stakes SET status=:st, resolved_at=now() WHERE id=:i"),
                     {"st": "released" if body.action == "release" else "slashed", "i": row.id})
    await db.commit()
    logger.info("[GUILD] remote stake %s executed at home: %s/%s amount=%s (peer=%s)",
                body.action, body.order_id, body.bidder_did[-12:], row.amount, peer_spiffe_id)
    return {"ok": True, "action": body.action, "amount": float(row.amount)}


@router.get("/api/v1/federation/guild/orders/{oid}", summary="Order detail for federation peers")
async def federated_order_detail(oid: str, db: AsyncSession = Depends(get_db),
                                 peer_spiffe_id: str = Security(get_federation_identity)):
    """Read-side for the home proxy's pre-flight (stake_required, status, bounty)."""
    _require_enabled()
    o = await _load(db, oid)
    return {k: o.get(k) for k in ("id", "status", "title", "bounty", "currency", "stake_required",
                                  "min_reputation", "poster_did", "deadline")}


# ── trust that travels (0118): credentials + reputation cross registries ────
_peer_pubkey_cache: dict = {}  # host_url -> {"pubkey_b64", "pubkey_id", "_fetched_at"} (per process)
# §PEERKEYROT (2026-09-05): a cached peer key is discarded when the credential names a DIFFERENT
# pubkey_id (one refetch, never a loop) and after this many seconds regardless.
_PEER_PUBKEY_TTL_SEC = int(os.getenv("GUILD_PEER_PUBKEY_TTL_SEC", "900") or "900")


@router.get("/api/v1/federation/guild/credential-pubkey", summary="Credential signing pubkey (federation peers)")
async def federated_credential_pubkey(peer_spiffe_id: str = Security(get_federation_identity)):
    """The Ed25519 pubkey this registry signs guild work credentials with, served over the
    federation channel so a worker's HOME can verify travel credentials from this host."""
    pk = guild_reputation.credential_pubkey()
    if not pk:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Credential signer unavailable")
    return pk


async def _fetch_peer_pubkey(db: AsyncSession, host_url: str, *,
                             expect_pubkey_id: str | None = None) -> dict | None:
    """Fetch (and cache) a peer's credential pubkey over the allowlisted mTLS channel.

    §PEERKEYROT (2026-09-05): this was trust-on-first-use FOREVER, per gunicorn worker. A peer
    whose signer rotated — every recreate of a frame without a durable /app/data; Sandbox Alpha
    rotated three times in one morning — kept failing verification on every worker that had
    cached the old key while a fresh worker passed: a deterministic 422 for one client (keep-alive
    pins it to a worker) and a pass for the next. A cached key is now discarded when the
    credential names a different pubkey_id (one refetch, never a loop) and after
    GUILD_PEER_PUBKEY_TTL_SEC regardless; the discard is logged with both ids.
    """
    host = host_url.rstrip("/")
    cached = _peer_pubkey_cache.get(host)
    if cached is not None:
        fresh = (time.time() - float(cached.get("_fetched_at") or 0)) < _PEER_PUBKEY_TTL_SEC
        if fresh and (expect_pubkey_id is None or cached.get("pubkey_id") == expect_pubkey_id):
            return cached
        logger.warning("[GUILD] peer pubkey cache for %s discarded (cached=%s expected=%s fresh=%s) — refetching",
                       host, cached.get("pubkey_id"), expect_pubkey_id, fresh)
        _peer_pubkey_cache.pop(host, None)
    try:
        target = await _resolve_peer_url(db, host)  # peer_registries.ACTIVE allowlist — the trust gate
        cfg, fed_headers = _fed_client_config(target)
        async with httpx.AsyncClient(**cfg) as client:
            r = await client.get(f"{target}/api/v1/federation/guild/credential-pubkey", headers=fed_headers)
        if r.status_code == 200:
            pk = r.json()
            if pk.get("pubkey_b64"):
                pk["_fetched_at"] = time.time()
                _peer_pubkey_cache[host] = pk
                return pk
    except Exception as e:  # noqa: BLE001
        logger.warning("[GUILD] peer pubkey fetch failed for %s: %s", host, e)
    return None


async def _ship_work_credential(db: AsyncSession, order: dict, credential: dict, stars: int) -> bool:
    """HOST side: deliver the signed work credential to the worker's HOME registry so the
    reputation lands on the graph where the worker actually lives. Best-effort, idempotent
    on the home side (UNIQUE(host_registry, order_id)) — a retry can never double-fold."""
    home = (order.get("worker_home_registry") or "").rstrip("/")
    if not home:
        return False
    try:
        target = await _resolve_peer_url(db, home)
        cfg, fed_headers = _fed_client_config(target)
        payload = {
            "order_id": order["id"], "host_registry": _self_public_url(),
            "worker_did": order["worker_did"], "poster_did": order["poster_did"],
            "stars": stars, "bounty": str(order.get("bounty")), "currency": order.get("currency"),
            # FIRM work: the payee (org treasury) rides along so the HOME fold can credit the
            # firm — the same "reputation follows the payee" rule the local settle fold applies.
            "payee_did": order.get("payee_did"),
            "credential": credential,
        }
        async with httpx.AsyncClient(**cfg) as client:
            r = await client.post(f"{target}/api/v1/federation/guild/work-credential",
                                  json=payload, headers=fed_headers)
        ok = r.status_code in (200, 201)
        logger.info("[GUILD] credential travel %s → %s: %s", order["id"], home, r.status_code)
        return ok
    except Exception as e:  # noqa: BLE001
        logger.warning("[GUILD] credential travel failed for %s → %s: %s", order.get("id"), home, e)
        return False


class TravelCredentialIn(BaseModel):
    order_id: str = Field(..., max_length=40)
    host_registry: str = Field(..., max_length=300)
    worker_did: str = Field(..., max_length=120)
    poster_did: str = Field(..., max_length=120)
    stars: int = Field(..., ge=1, le=5)
    bounty: Optional[str] = None
    currency: Optional[str] = None
    payee_did: Optional[str] = Field(None, max_length=120,
                                     description="Firm work: the org-treasury payee — reputation follows the payee")
    credential: dict


@router.post("/api/v1/federation/guild/work-credential", summary="Receive a work credential for a HOME agent (federation)")
async def receive_work_credential(body: TravelCredentialIn, db: AsyncSession = Depends(get_db),
                                  peer_spiffe_id: str = Security(get_federation_identity)):
    """HOME side of trust-that-travels: verify the host's Ed25519 signature against its published
    pubkey (fetched over the allowlisted mTLS peer channel), store the credential, and fold the
    poster→worker edge into OUR local_trust graph: the same fold a local guild settle does.
    Idempotent: UNIQUE(host_registry, order_id) makes replays no-ops."""
    _require_enabled()
    # the whole point: the worker must be OUR agent
    mine = (await db.execute(text("SELECT 1 FROM agents WHERE did=:d"), {"d": body.worker_did})).scalar()
    if not mine:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Worker is not homed on this registry")
    # verify the signature against the HOST's published pubkey (TOFU over the allowlisted channel)
    verified = False
    pk = await _fetch_peer_pubkey(db, body.host_registry,
                                 expect_pubkey_id=body.credential.get("signature_pubkey_id"))
    if pk:
        try:
            from agentvault_registry.services.attestation_signer import verify_bundle_signature
            if body.credential.get("signature_pubkey_id") == pk.get("pubkey_id"):
                ok, why = verify_bundle_signature(dict(body.credential), issuer_pubkey_b64=pk["pubkey_b64"])
                verified = bool(ok)
                if not ok:
                    logger.warning("[GUILD] travel credential signature INVALID for %s: %s", body.order_id, why)
            else:
                logger.warning("[GUILD] travel credential pubkey-id mismatch for %s", body.order_id)
        except Exception as e:  # noqa: BLE001
            logger.warning("[GUILD] travel credential verify error for %s: %s", body.order_id, e)
    if not verified:
        # store nothing, fold nothing — an unverifiable credential moves no trust
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="Credential signature could not be verified against the host's pubkey")
    ins = await db.execute(text("""
        INSERT INTO guild_travel_credentials (id, order_id, host_registry, worker_did, poster_did,
                                              stars, bounty, currency, bundle, pubkey_id, verified)
        VALUES (:i,:o,:h,:w,:p,:s,:b,:c,CAST(:bu AS JSONB),:pk,TRUE)
        ON CONFLICT (host_registry, order_id) DO NOTHING
    """), {"i": f"gtc_{uuid.uuid4().hex[:24]}", "o": body.order_id, "h": body.host_registry.rstrip("/"),
           "w": body.worker_did, "p": body.poster_did, "s": body.stars,
           "b": Decimal(body.bounty) if body.bounty else None, "c": body.currency,
           "bu": json.dumps(body.credential), "pk": body.credential.get("signature_pubkey_id")})
    folded = False
    fold_to = body.worker_did
    if ins.rowcount:  # first delivery only — replays must not double-fold
        # FIRM work (payee ≠ worker): reputation follows the PAYEE — the same rule the local
        # settle fold applies. Trust the SIGNED claim first, the payload second; fold to the
        # payee only when it is homed here too (the org lives on the worker's home by
        # construction). Hosts that predate the payee field send none → worker fold, unchanged.
        payee = (body.credential or {}).get("payee_did") or body.payee_did
        if payee and payee != body.worker_did:
            if (await db.execute(text("SELECT 1 FROM agents WHERE did=:d"), {"d": payee})).scalar():
                fold_to = payee
        await guild_reputation.fold_work_reputation(
            db, body.poster_did, fold_to, body.stars, float(body.bounty or 0))
        folded = True
    await db.commit()
    if folded:
        _emit("GuildCredentialReceived", body.order_id,
              {"worker": body.worker_did, "host": body.host_registry, "stars": body.stars})
        logger.info("[GUILD] travel credential VERIFIED+FOLDED for %s (worker=%s fold_to=%s host=%s stars=%s)",
                    body.order_id, body.worker_did, fold_to, body.host_registry, body.stars)
    return {"ok": True, "order_id": body.order_id, "verified": verified, "folded": folded}


class GuildNoticeIn(BaseModel):
    order_id: str = Field(..., max_length=40)
    kind: str = Field(..., pattern="^(awarded|verified)$")
    worker_did: str = Field(..., max_length=120)
    title: Optional[str] = Field(None, max_length=300)
    bounty: Optional[str] = Field(None, max_length=40)
    currency: Optional[str] = Field(None, max_length=12)
    bid_id: Optional[int] = None
    accepted: Optional[bool] = None
    status: Optional[str] = Field(None, max_length=20)
    payout: Optional[str] = Field(None, max_length=40)
    fee: Optional[str] = Field(None, max_length=40)
    stars: Optional[int] = Field(None, ge=1, le=5)
    payee: Optional[str] = Field(None, max_length=120)
    ddr_dispute_id: Optional[str] = Field(None, max_length=64)
    feedback: Optional[str] = Field(None, max_length=1000)
    credential_traveled: Optional[bool] = None


@router.post("/api/v1/federation/guild/notice",
             summary="Tell a HOME agent's owner about its guild order on a peer (federation, advisory)")
async def receive_guild_notice(body: GuildNoticeIn, db: AsyncSession = Depends(get_db),
                               peer_spiffe_id: str = Depends(require_peer_registry_identity)):
    """
    The worker's home side: the host of an order tells the home of its remote worker that the worker was awarded, or
    that its delivery was verified (paid) or rejected (disputed), and the home tells the agent's owner
    (`guild.awarded`, `guild.verified`). The host is the caller, resolved from its SVID; the worker must be this
    registry's agent. A notice only: nothing changes state and no units move. One webhook per (host, order, kind).

    \f
    §TWOAGENT G3 (2026-09-23), the worker's HOME. The host of an order tells the home of its remote worker that the
    worker was awarded or that its delivery was verified (paid) or rejected (disputed), and the home tells the agent's
    owner (`guild.awarded` / `guild.verified`, owner-scoped). The run's worker polled the host for each of these.

    The host is the CALLER, resolved from its SVID; a registry name in the body is never read. The worker must be OUR
    agent. Nothing here changes state or moves money: it is a notice. One webhook per (host, order, kind).
    """
    _require_enabled()
    host = await _caller_peer_name(db, peer_spiffe_id)
    if host is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="the calling registry is not a known peer")
    mine = (await db.execute(text("SELECT 1 FROM agents WHERE did=:d"), {"d": body.worker_did})).scalar()
    if not mine:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Worker is not homed on this registry")
    notified = await _notice_first_time(host, body.order_id, body.kind)
    if notified:
        data = {k: v for k, v in body.model_dump().items() if v is not None and k != "kind"}
        data.update({"host_registry": host, "via": "federation"})
        if body.kind == "awarded":
            data["submit_with"] = ("POST /api/v1/guild/cross-registry/proxy with action=submit, "
                                   f"order_id={body.order_id} and your deliverable, on THIS registry")
        _guild_webhook("guild.awarded" if body.kind == "awarded" else "guild.verified", [body.worker_did], data)
    logger.info("[GUILD] %s notice for %s from %s (worker=%s notified=%s)", body.kind, body.order_id, host,
                body.worker_did[-12:], notified)
    return {"ok": True, "order_id": body.order_id, "kind": body.kind, "notified": notified}


@router.get("/api/v1/guild/my-credentials", summary="My travel work credentials (agent)")
async def my_travel_credentials(agent: models.Agent = Depends(get_current_agent),
                                db: AsyncSession = Depends(get_db)):
    """Signed proof-of-work credentials gained on OTHER registries that landed on this, your home."""
    rows = (await db.execute(text("""
        SELECT order_id, host_registry, poster_did, stars, bounty, currency, verified, received_at
        FROM guild_travel_credentials WHERE worker_did=:w ORDER BY received_at DESC LIMIT 100
    """), {"w": agent.did})).mappings().all()
    return {"credentials": [dict(r) for r in rows], "count": len(rows)}


async def _active_peers(db: AsyncSession) -> list[dict]:
    """ACTIVE rows from peer_registries — the LIVE allowlist (the provisioning flow populates it;
    supersedes the legacy TRUSTED_REGISTRIES env, which the frame-c family doesn't carry)."""
    rows = (await db.execute(text(
        "SELECT name, base_url FROM peer_registries WHERE status='ACTIVE' AND base_url IS NOT NULL"
    ))).mappings().all()
    return [dict(r) for r in rows]


async def _resolve_peer_url(db: AsyncSession, target_url: str) -> str:
    """SSRF allowlist (peer_registries.ACTIVE) + mTLS-dialable remap via the canary-proven
    `_to_internal_mtls_url` (same dial the fx canaries + federation_sync use daily)."""
    from agentvault_registry.routers.teg_integration import _to_internal_mtls_url
    target = target_url.rstrip("/")
    # legacy home values are SPIFFE ids (pre-PUBLIC_URL ops) — map the operator segment to a peer row
    if target.startswith("spiffe://"):
        m = re.search(r"/operator/([a-z0-9-]+)", target)
        if m:
            row = (await db.execute(text(
                "SELECT base_url FROM peer_registries WHERE status='ACTIVE' AND name=:n AND base_url IS NOT NULL"
            ), {"n": m.group(1)})).scalar()
            if row:
                target = row.rstrip("/")
    def _host(u: str) -> str:
        # hostname-level match: an op's PUBLIC_URL often lacks the :8443 its peer row carries
        return (urlparse(u).hostname or u).lower() if "://" in u else u.lower()
    t_host = _host(target)
    for p in await _active_peers(db):
        base = (p["base_url"] or "").rstrip("/")
        if (target in (base, _to_internal_mtls_url(base))
                or target.lower() == (p["name"] or "").lower()
                or (t_host and t_host == _host(base))):
            return _to_internal_mtls_url(base)
    raise HTTPException(status.HTTP_400_BAD_REQUEST,
                        detail="target_registry_url is not an ACTIVE peer of this registry")


def _fed_client_config(target_url: str) -> tuple[dict, dict]:
    """(httpx client config, fed headers) — SVID mTLS when available + shared-secret header fallback
    (both attached, exactly like background_tasks/federation_sync's peer dial)."""
    fed_headers = {
        "Content-Type": "application/json",
        "X-Federation-Secret": os.environ.get("FEDERATION_INTERNAL_SECRET", ""),
        "X-Federation-SPIFFE-ID": svid_client.get_spiffe_id() or "",
    }
    cfg: dict = {"timeout": 15.0}
    if target_url.startswith("https://"):
        try:
            cert_config = svid_client.get_client_cert_config(target_url=target_url)
            if cert_config:
                cfg.update(cert_config)
        except Exception:  # noqa: BLE001 — fall back to header auth
            pass
    return cfg, fed_headers


def target_pub(u: str) -> str:
    """Registry identity normalized to HOSTNAME — stake rows must match regardless of :8443/scheme
    differences between what a client passed and what the host announces (v2 0119)."""
    u = (u or "").rstrip("/")
    return (urlparse(u).hostname or u).lower() if "://" in u else u.lower()


def _self_public_url() -> str:
    """Best public identity for THIS registry (goes on outbound federated bids as home_registry_url)."""
    for var in ("REGISTRY_EXTERNAL_URL", "PUBLIC_BASE_URL", "REGISTRY_PUBLIC_URL", "EXTERNAL_URL", "PUBLIC_URL"):
        v = os.getenv(var, "").strip().rstrip("/")
        if v:
            return v
    return svid_client.get_spiffe_id() or "unknown-peer"


@router.post("/api/v1/guild/cross-registry/proxy", summary="Act on a guild order hosted on a PEER registry (agent)")
async def guild_cross_registry_proxy(body: GuildCrossRegistryProxyIn,
                                     agent: models.Agent = Depends(get_current_agent),
                                     db: AsyncSession = Depends(get_db)):
    """The agent calls their OWN registry, which forwards the action to the host registry over the
    federation channel, vouching for the agent's identity (contracts cross-registry proxy precedent)."""
    _require_enabled()
    if body.action not in ("bid", "submit"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"Invalid action: {body.action}. Must be 'bid' or 'submit'.")
    target = await _resolve_peer_url(db, body.target_registry_url)
    cfg, fed_headers = _fed_client_config(target)
    if body.action == "bid":
        if body.price is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="price required for bid")
        url = f"{target}/api/v1/federation/guild/orders/{body.order_id}/bid"
        payload = {"bidder_did": agent.did, "home_registry_url": _self_public_url(),
                   "price": body.price, "eta_seconds": body.eta_seconds, "pitch": body.pitch,
                   # home-asserted reputation rides the bid (trust that travels, 0118)
                   "reputation": await _agent_reputation(db, agent.did)}
        # v2 (0119) FIRM bid: the org lives HERE — validate membership + AGORA treasury, assert the payee.
        if body.on_behalf_of_org_id:
            payee = await _validate_firm_bid(db, agent.did, body.on_behalf_of_org_id)
            payload["payee_org_id"] = body.on_behalf_of_org_id
            payload["payee_did"] = payee
        # v2 (0119) STAKED task: lock the collateral on THIS treasury (the bidder's money lives here),
        # then assert it with the relayed bid. Compensating refund if the host rejects the bid.
        stake_locked = Decimal(0)
        try:
            cfg0, hdr0 = _fed_client_config(target)
            async with httpx.AsyncClient(**cfg0) as pre:
                od = await pre.get(f"{target}/api/v1/federation/guild/orders/{body.order_id}", headers=hdr0)
            if od.status_code == 200:
                stake_needed = Decimal(str(od.json().get("stake_required") or 0))
                if stake_needed > 0:
                    dup = (await db.execute(text(
                        "SELECT 1 FROM guild_remote_stakes WHERE host_registry=:h AND order_id=:o AND bidder_did=:d AND status='held'"
                    ), {"h": target_pub(body.target_registry_url), "o": body.order_id, "d": agent.did})).first()
                    if not dup:
                        try:
                            await guild_escrow.escrow_deposit(agent.did, stake_needed, body.order_id,
                                                              leg=f"xfstake:{agent.did[-12:]}")
                        except guild_escrow.GuildEscrowError as e:
                            raise refusal_from_error(e) or HTTPException(
                                status.HTTP_402_PAYMENT_REQUIRED, detail=f"Collateral lock failed (need {stake_needed}): {e.message}")
                        await db.execute(text("""
                            INSERT INTO guild_remote_stakes (id, order_id, host_registry, bidder_did, amount, status)
                            VALUES (:i,:o,:h,:d,:a,'held')
                            ON CONFLICT (host_registry, order_id, bidder_did) DO UPDATE SET status='held', amount=:a
                        """), {"i": f"grs_{uuid.uuid4().hex[:24]}", "o": body.order_id,
                               "h": target_pub(body.target_registry_url), "d": agent.did, "a": stake_needed})
                        await db.commit()
                    stake_locked = stake_needed
                    payload["stake_held"] = float(stake_needed)
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            logger.warning("[GUILD] proxy stake pre-flight failed for %s: %s", body.order_id, e)
    else:
        url = f"{target}/api/v1/federation/guild/orders/{body.order_id}/submit"
        payload = {"worker_did": agent.did, "deliverable": body.deliverable}
    logger.info("[GUILD] cross-registry proxy: agent=%s action=%s target=%s", agent.did, body.action, url)
    async def _unwind_stake():
        # compensating refund: the host never accepted the bid, so the collateral goes straight back
        if body.action == "bid" and payload.get("stake_held"):
            try:
                await guild_escrow.escrow_payout(db, agent.did, Decimal(str(payload["stake_held"])),
                                                 body.order_id, f"xfstake_unwind:{agent.did[-12:]}")
                await db.execute(text(
                    "UPDATE guild_remote_stakes SET status='released', resolved_at=now() "
                    "WHERE host_registry=:h AND order_id=:o AND bidder_did=:d AND status='held'"
                ), {"h": target_pub(body.target_registry_url), "o": body.order_id, "d": agent.did})
                await db.commit()
            except Exception:  # noqa: BLE001
                logger.warning("[GUILD] stake unwind failed for %s (reaper will safety-net)", body.order_id)
    try:
        async with httpx.AsyncClient(**cfg) as client:
            resp = await client.post(url, json=payload, headers=fed_headers)
        if resp.status_code in (200, 201):
            return resp.json()
        await _unwind_stake()
        raise HTTPException(status_code=resp.status_code,
                            detail=f"Host registry returned {resp.status_code}: {resp.text[:300]}")
    except httpx.RequestError as e:
        await _unwind_stake()
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"Failed to reach host registry: {e}")


# ── network board: fan out the open boards of all trusted peers (best-effort) ─
_net_cache: dict = {"at": None, "data": None}


@router.get("/api/v1/guild/network-board", summary="Open tasks across all trusted peer registries")
async def network_board(db: AsyncSession = Depends(get_db)):
    _require_enabled()
    now = _dt.datetime.now(_dt.timezone.utc)
    if _net_cache["at"] and (now - _net_cache["at"]).total_seconds() < 30 and _net_cache["data"] is not None:
        return _net_cache["data"]
    import asyncio
    from agentvault_registry.routers.teg_integration import _to_internal_mtls_url
    peers = await _active_peers(db)

    async def _poll(p: dict) -> list:
        base = (p["base_url"] or "").rstrip("/")
        name = p["name"] or base
        dial = _to_internal_mtls_url(base)
        try:
            cfg, fed_headers = _fed_client_config(dial)
            cfg["timeout"] = 5.0
            async with httpx.AsyncClient(**cfg) as client:
                # /api/v1/federation/… path → passes every nginx-federation allowlist unchanged
                r = await client.get(f"{dial}/api/v1/federation/guild/board", headers=fed_headers)
            if r.status_code == 200:
                out = r.json().get("orders", [])
                for ordr in out:
                    ordr["host_registry"] = base
                    ordr["host_name"] = name
                return out
        except Exception as ex:  # noqa: BLE001 — peers down / guild-disabled are normal; best-effort
            logger.debug("[GUILD] network-board peer %s unreachable: %s", name, ex)
        return []
    results = await asyncio.gather(*(_poll(p) for p in peers), return_exceptions=False)
    boards = [o for sub in results for o in sub]
    result = {"orders": boards, "total": len(boards), "peers_polled": len(peers)}
    _net_cache["at"] = now; _net_cache["data"] = result
    return result
