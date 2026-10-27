"""
TEG Transaction Endpoints — Powered by Event Store
====================================================
OWL20-PREP: Replaced ALL mock/random data with real Event Store queries.
Every endpoint now returns genuine ledger data from the immutable event log.

Architecture:
  Registry Router → HTTP → Event Store API → PostgreSQL event log
  (Same internal API key used by EventEmitter)
"""
from typing import Annotated, Dict, Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query, Body, Security, Request
from datetime import datetime, timedelta, timezone
import os
import logging
import httpx

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ..security import admin_credential, get_current_developer, get_current_agent
from ..models import Developer, Agent
from ..database import get_db
from ..config import settings
from ..es_ssl_helper import get_httpx_verify
from ..identifiers import withhold_personal_ids
from ..core import ledger_names   # W4: an event's old and new names are one event
from ..core.path_segment import seg  # §MCPTEST30 V0526: a value in a store/TEG URL path is one encoded segment (round 9: a malformed id read as an outage)

logger = logging.getLogger(__name__)

# W4 (agentvault2-aa, 2026-10-25): the transaction events under every name they are stored under (old, new, legacy)
_TX_TYPES = ledger_names.expand({"TokensIssued", "TokensTransferred", "TokensStaked", "TokensUnstaked",
                                 "RewardsDistributed", "RewardsAutoCompounded"})


def _frame_unit() -> str:
    # D6-835 (2026-10-25): this frame's unit, asked where the amount is written (it said AVT on every frame)
    from agentvault_registry.core.frame_currency import frame_currency
    return frame_currency()

router = APIRouter()

# ═══════════════════════════════════════════════
# Event Store HTTP Client
# ═══════════════════════════════════════════════
EVENT_STORE_URL = getattr(settings, "EVENT_STORE_URL", "http://localhost:8200")
EVENT_STORE_KEY = getattr(settings, "EVENT_STORE_API_KEY",
                          "")


async def _es_get(path: str, params: dict = None) -> Any:
    """Query the Event Store. Returns parsed JSON, or None when the store does not answer 200.

    Every read presents the store's key (and, through get_httpx_verify, this registry's SVID where it has one): the
    store authenticates its reads, the per-agent projections included (§SECBATCH wave 2). A read that went without the
    key (the agent history and the analytics' balances did) is refused there and came back as "unreachable"."""
    url = f"{EVENT_STORE_URL}{path}"
    headers = {"X-Internal-Key": EVENT_STORE_KEY}
    try:
        async with httpx.AsyncClient(timeout=10.0, verify=get_httpx_verify()) as client:
            r = await client.get(url, params=params, headers=headers)
            if r.status_code == 200:
                return r.json()
            logger.warning(f"Event Store {path} returned {r.status_code}: {r.text[:200]}")
            return None
    except Exception as e:
        logger.error(f"Event Store query failed ({path}): {e}")
        return None


# ═══════════════════════════════════════════════
# Whose ledger activity a developer credential reads
# ═══════════════════════════════════════════════
# SEC-01 (§SECBATCH wave 3, 2026-10-16): the developer reads of this router (the listing, an agent's history, the
# export, a transaction's detail) answered any account's ledger activity to any signed-in developer. A developer now
# reads the activity of the agents it created (agents.creator_developer_id); a treasury administrator reads every
# account's. An agent credential reads its own through the agent routes (GET /teg/transactions, /transactions/advanced).
NOT_YOUR_LEDGER = "Only the agent's owner, and a treasury administrator, may read its ledger activity"


def reads_every_ledger(developer) -> bool:
    """A treasury administrator (admin_treasury, or the legacy superadmin is_admin) reads every account's ledger
    activity, on a credential that reaches admin (an API key scoped for MCP use does not, security.api_key_grants_admin;
    REQUIRE_ADMIN_2FA, security.admin_second_factor_ok) and not while the account must change its password: the rule of
    disputes.reads_every_dispute, with the flag of the admin ledger reads (GET /admin/eventstore-balances)."""
    from ..security import admin_second_factor_ok, api_key_grants_admin
    if developer is None or getattr(developer, "must_change_password", False):
        return False
    held = bool(getattr(developer, "is_admin", False) or getattr(developer, "admin_treasury", False))
    return held and api_key_grants_admin() and admin_second_factor_ok(developer)


async def _owns_agent(db: AsyncSession, developer_id, did: str) -> bool:
    """Did this developer create the agent with this DID?"""
    if developer_id is None or not did:
        return False
    row = await db.execute(
        select(Agent.id).where(Agent.creator_developer_id == developer_id, Agent.did == did).limit(1))
    return row.first() is not None


async def _ledger_scope(developer, db: AsyncSession) -> Optional[set]:
    """None when the caller reads every account (reads_every_ledger); otherwise the DIDs of its own agents."""
    if reads_every_ledger(developer):
        return None
    developer_id = getattr(developer, "id", None)
    if developer_id is None:
        return set()
    rows = await db.execute(select(Agent.did).where(Agent.creator_developer_id == developer_id))
    return {did for (did,) in rows.all() if did}


def _event_parties(evt: dict) -> set:
    """The accounts a ledger event concerns: its aggregate and the data's from, to and agent_did."""
    data = evt.get("data") if isinstance(evt.get("data"), dict) else {}
    return {v for v in (evt.get("aggregate_id"), data.get("from"), data.get("to"), data.get("agent_did"))
            if isinstance(v, str) and v}


def _in_scope(evt: dict, scope: Optional[set]) -> bool:
    return scope is None or bool(_event_parties(evt) & scope)


# ═══════════════════════════════════════════════
# Transaction Listing (Developer View)
# ═══════════════════════════════════════════════
@router.get("/transactions")
async def get_teg_transactions(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    type: str = Query("all", pattern="^(all|sent|received)$"),
    current_developer: Annotated[Developer, Security(get_current_developer)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None
) -> Dict[str, Any]:
    """The ledger activity of the caller's own agents, from the Event Store (a treasury administrator: every account's).

    \f
    SEC-01: see reads_every_ledger. Where the whole application is mounted, GET /api/v1/teg/transactions is answered by
    the agent route of routers/teg_integration.py (mounted first); this developer view answers where this router is
    mounted on its own.
    """
    logger.info(f"Getting TEG transactions for developer {current_developer.id}, type: {type}")

    scope = await _ledger_scope(current_developer, db)
    if scope is not None and not scope:
        return {"transactions": [], "total": 0, "limit": limit, "offset": offset, "source": "event_store"}

    # Get all economic events from Event Store
    events = await _es_get("/api/v1/events/", params={"limit": limit + offset})
    if events is None:
        return {"transactions": [], "total": 0, "limit": limit, "offset": offset,
                "source": "event_store", "error": "Event Store unreachable"}

    # Normalize: events may be list or dict with items/events key
    if isinstance(events, dict):
        events = events.get("items", events.get("events", []))

    # Filter to transaction-relevant event types
    tx_types = _TX_TYPES

    transactions = []
    for evt in events:
        et = evt.get("event_type", "")
        if et not in tx_types or not _in_scope(evt, scope):
            continue

        data = evt.get("data", {})
        from_agent = data.get("from", data.get("agent_did", evt.get("aggregate_id", "")))
        to_agent = data.get("to", data.get("agent_did", evt.get("aggregate_id", "")))
        amount = data.get("amount", "0")

        # Determine direction
        kind = ledger_names.old_name(et)   # W4: the branch reads the event, the answer keeps its stored name
        if kind == "TokensTransferred":
            tx_type = "sent"  # from perspective of aggregate
        elif kind in ("TokensIssued", "RewardsDistributed", "RewardsAutoCompounded", "TokensUnstaked"):
            tx_type = "received"
        elif kind == "TokensStaked":
            tx_type = "sent"  # liquid → staked (debit from liquid)
        else:
            tx_type = "other"

        if type != "all" and tx_type != type:
            continue

        transactions.append({
            "id": evt.get("id", evt.get("event_id", "")),
            "event_type": et,
            "type": tx_type,
            "from": from_agent,
            "to": to_agent,
            "amount": str(amount),
            "memo": data.get("reason", data.get("memo", data.get("transaction_id", et))),
            "timestamp": evt.get("timestamp", evt.get("created_at", "")),
            "status": "confirmed",  # On the ledger = confirmed
            "source": "event_store"
        })

    # Apply offset/limit
    total = len(transactions)
    transactions = transactions[offset:offset + limit]

    return {
        "transactions": transactions,
        "total": total,
        "limit": limit,
        "offset": offset,
        "source": "event_store"
    }


# ═══════════════════════════════════════════════
# Single Transaction Detail
# ═══════════════════════════════════════════════
@router.get("/transaction/{transaction_id}")
async def get_transaction_detail(
    transaction_id: str,
    current_developer: Annotated[Developer, Security(get_current_developer)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None
) -> Dict[str, Any]:
    """Get detailed information about a single TEG transaction from the ledger.

    A transaction one of the caller's agents takes part in (a treasury administrator: any transaction); 403 otherwise.

    Resolves by `data.transaction_id` (the id that getMyTegTransactions and
    /teg/transactions return) via the EventStore's indexed by-transaction
    lookup. A single transaction id can map to several ledger events (e.g.
    TokensTransferred + TransactionFeeCollected); the primary balance-moving
    event is returned, with siblings under `related_events`. Falls back to a
    raw event-id match for legacy callers that pass an event UUID.

    NOTE: TEG-only bookkeeping (e.g. SYSTEM_LOCK holds) never reaches the
    EventStore, so those ids legitimately 404 here: the ledger only records
    settled balance movements.
    """
    logger.info(f"Getting transaction detail for {transaction_id}")

    scope = await _ledger_scope(current_developer, db)       # SEC-01
    if scope is not None and not scope:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=NOT_YOUR_LEDGER)

    # Primary: indexed lookup by data.transaction_id (the TEG-layer tx id).
    events = await _es_get(f"/api/v1/events/by-transaction/{seg(transaction_id)}")
    if events is None:
        raise HTTPException(status_code=503, detail="Event Store unreachable")
    if isinstance(events, dict):
        events = events.get("items", events.get("events", []))

    # Back-compat fallback: caller may have passed a raw event UUID.
    if not events:
        recent = await _es_get("/api/v1/events/", params={"limit": 500})
        if isinstance(recent, dict):
            recent = recent.get("items", recent.get("events", []))
        for evt in (recent or []):
            if str(evt.get("id", evt.get("event_id", ""))) == transaction_id:
                events = [evt]
                break

    if not events:
        raise HTTPException(status_code=404, detail=f"Transaction {transaction_id} not found in event ledger")
    if not any(_in_scope(e, scope) for e in events):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=NOT_YOUR_LEDGER)

    # A transaction id can yield several events (transfer + fee, etc.). Surface
    # the primary balance-moving event; keep the rest as related_events.
    _PRIMARY = _TX_TYPES
    primary = next((e for e in events if e.get("event_type") in _PRIMARY), events[0])
    data = primary.get("data", {})
    primary_id = str(primary.get("id", primary.get("event_id", "")))
    related = [
        {
            "id": str(e.get("id", e.get("event_id", ""))),
            "event_type": e.get("event_type", ""),
            "amount": str(e.get("data", {}).get("amount", "0")),
            "timestamp": e.get("timestamp", ""),
        }
        for e in events
        if str(e.get("id", e.get("event_id", ""))) != primary_id
    ]
    return {
        "id": primary_id,
        "transaction_id": transaction_id,
        "event_type": primary.get("event_type", ""),
        "aggregate_id": primary.get("aggregate_id", ""),
        "aggregate_type": primary.get("aggregate_type", ""),
        "from": data.get("from", data.get("agent_did", primary.get("aggregate_id", ""))),
        "to": data.get("to", data.get("agent_did", primary.get("aggregate_id", ""))),
        "amount": str(data.get("amount", "0")),
        "timestamp": primary.get("timestamp", ""),
        "status": "confirmed",
        "data": data,
        "related_events": related,
        "source": "event_store"
    }


# ═══════════════════════════════════════════════
# Advanced Filtered Transactions (Agent View)
# ═══════════════════════════════════════════════
@router.get("/transactions/advanced")
async def get_advanced_transactions(
    from_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    to_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    tx_status: Optional[str] = Query(None, alias="status", pattern="^(completed|pending|failed)$"),
    min_amount: Optional[int] = Query(None, ge=0),
    max_amount: Optional[int] = Query(None, ge=0),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_agent: Annotated[Agent, Security(get_current_agent)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None
) -> Dict[str, Any]:
    """Advanced transaction queries with filtering, over the Event Store's data."""
    logger.info(f"Advanced transaction query for agent {current_agent.did}")

    # Get events for this specific agent from Event Store
    events = await _es_get(f"/api/v1/events/aggregate/{seg(current_agent.did)}")
    if events is None:
        events = []
    if isinstance(events, dict):
        events = events.get("items", events.get("events", []))

    tx_types = _TX_TYPES

    transactions = []
    for evt in events:
        et = evt.get("event_type", "")
        if et not in tx_types:
            continue

        data = evt.get("data", {})
        amount_str = str(data.get("amount", "0"))
        try:
            amount_val = float(amount_str)
        except (ValueError, TypeError):
            amount_val = 0

        # Apply filters
        if min_amount is not None and amount_val < min_amount:
            continue
        if max_amount is not None and amount_val > max_amount:
            continue

        ts = evt.get("timestamp", evt.get("created_at", ""))
        if from_date and ts < from_date:
            continue
        if to_date and ts > to_date + "T23:59:59":
            continue

        from_agent = data.get("from", data.get("agent_did", evt.get("aggregate_id", "")))
        to_agent = data.get("to", data.get("agent_did", evt.get("aggregate_id", "")))

        transactions.append({
            "id": str(evt.get("id", "")),
            "event_type": et,
            "type": "sent" if from_agent == current_agent.did and ledger_names.same(et, "TokensTransferred") else "received",
            "from": from_agent,
            "to": to_agent,
            "amount": amount_str,
            "memo": data.get("reason", data.get("memo", et)),
            "timestamp": ts,
            "status": "confirmed",
            "source": "event_store"
        })

    total = len(transactions)
    transactions = transactions[offset:offset + limit]

    return {
        "transactions": transactions,
        "filters": {
            "from_date": from_date,
            "to_date": to_date,
            "status": tx_status,
            "min_amount": min_amount,
            "max_amount": max_amount,
            "agent_did": current_agent.did
        },
        "total": total,
        "limit": limit,
        "offset": offset,
        "source": "event_store"
    }


# ═══════════════════════════════════════════════
# Agent Transaction History (via Event Store Projections)
# ═══════════════════════════════════════════════
@router.get("/transactions/history/{agent_id}")
async def get_agent_transaction_history(
    agent_id: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_developer: Annotated[Developer, Security(get_current_developer)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None
) -> Dict[str, Any]:
    """Get transaction history for one of the caller's agents, proxied from the Event Store's projections (a treasury
    administrator: any account's); 403 for an agent the caller did not create."""
    logger.info(f"Getting transaction history for agent {agent_id}")

    # SEC-01: refused before anything is read from the store.
    if not reads_every_ledger(current_developer) and not await _owns_agent(
            db, getattr(current_developer, "id", None), agent_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=NOT_YOUR_LEDGER)

    # Use Event Store projection service (real data)
    history = await _es_get(f"/api/v1/projections/transactions/{seg(agent_id)}", params={"limit": limit})

    if history is None:
        # Fallback: try direct event query
        events = await _es_get(f"/api/v1/events/aggregate/{seg(agent_id)}")
        if events is None:
            return {"agent_id": agent_id, "transactions": [], "total": 0,
                    "error": "Event Store unreachable", "source": "event_store"}
        if isinstance(events, dict):
            events = events.get("items", events.get("events", []))

        transactions = []
        for evt in events:
            data = evt.get("data", {})
            transactions.append({
                "id": str(evt.get("id", "")),
                "event_type": evt.get("event_type", ""),
                "amount": str(data.get("amount", "0")),
                "timestamp": evt.get("timestamp", ""),
                "data": data
            })

        return {
            "agent_id": agent_id,
            "transactions": transactions[offset:offset + limit],
            "total": len(transactions),
            "limit": limit,
            "offset": offset,
            "source": "event_store_direct"
        }

    # Projection service returns {agent_did, transactions: [], count}
    txs = history.get("transactions", [])

    # Compute summary from real data
    total_sent = 0
    total_received = 0
    for tx in txs:
        amount = float(tx.get("amount", 0) or 0)
        details = tx.get("details", {})
        if details.get("from") == agent_id:
            total_sent += amount
        else:
            total_received += amount

    return {
        "agent_id": agent_id,
        "transactions": txs[offset:offset + limit],
        "total": len(txs),
        "limit": limit,
        "offset": offset,
        "summary": {
            "total_sent": str(total_sent),
            "total_received": str(total_received),
            "transaction_count": len(txs)
        },
        "source": "event_store_projection"
    }


# ═══════════════════════════════════════════════
# Transaction Analytics (via Event Store Stats)
# ═══════════════════════════════════════════════
@router.get("/transactions/analytics")
async def get_transaction_analytics(
    period: str = Query("all", pattern="^(all|24h|7d|30d|90d|1y)$"),
    current_developer: Annotated[Developer, Security(get_current_developer)] = None
) -> Dict[str, Any]:
    """
    Transaction analytics from the Event Store. The counts cover every event since the store's first (one cached
    snapshot, no time window): `period` is always "all", and `period_requested` echoes what was asked.

    \f
    Get transaction analytics — real statistics from Event Store.

    §FESUITE (V0571, 2026-10-04): the Event Store's statistics count every event since its first (one cached snapshot,
    no time window), so the answer names the period its counts cover: `period` is "all" whatever was asked, and
    `period_requested` is what was asked. Until V0571 the route echoed the period it was asked for and counted every
    event (measured on V0569 at sbx-beta: 24h, 30d and 1y each answered 1,208,418 events with the first a month old),
    and refused "all", the one period that described the counts (Mission Control's Economy Pulse offered it: 422).
    """
    logger.info(f"Getting transaction analytics for developer {current_developer.id}, period: {period}")

    # Get real stats from Event Store
    stats = await _es_get("/api/v1/projections/stats")
    balances = await _es_get("/api/v1/projections/balances")

    if stats is None:
        raise HTTPException(status_code=503, detail="Event Store stats unreachable")

    event_counts = stats.get("event_counts", {})
    total_events = stats.get("total_events", 0)
    unique_agents = stats.get("unique_agents", 0)

    # Calculate volumes from balance projections
    agents_data = []
    total_liquid = 0
    total_staked = 0
    if balances:
        agents_data = balances.get("agents", [])
        total_liquid = balances.get("total_liquid", 0)
        total_staked = balances.get("total_staked", 0)

    # Transaction type breakdown from real event counts
    tx_event_types = ["TokensIssued", "TokensTransferred", "TokensStaked", "TokensUnstaked",
                      "RewardsDistributed", "RewardsAutoCompounded"]
    # W4: an event counts under every name it is stored under (the breakdown keeps its keys)
    _count = lambda t: sum(event_counts.get(n, 0) for n in ledger_names.names_of(t))   # noqa: E731
    total_tx_events = sum(_count(t) for t in tx_event_types)

    return {
        "period": "all",
        "period_requested": period,
        "summary": {
            "total_events": total_events,
            "total_transaction_events": total_tx_events,
            "unique_agents": unique_agents,
            "total_liquid_supply": str(total_liquid),
            "total_staked_supply": str(total_staked),
            "total_supply": str(total_liquid + total_staked)
        },
        "event_type_breakdown": {t: _count(t) for t in tx_event_types},
        "all_event_counts": event_counts,
        "oldest_event": stats.get("oldest_event"),
        "newest_event": stats.get("newest_event"),
        # Any developer reads this list of the frame's largest accounts, so an account whose id is built from an e-mail
        # address (a developer's TEG account) is shown by its opaque public id, as on every public read (D6-606). The
        # list was empty from the store's D6-200 until this read presented the store's key again.
        "top_agents_by_balance": withhold_personal_ids(sorted(
            [{"did": a.get("agent_did"), "total": a.get("total_balance", 0)} for a in agents_data],
            key=lambda x: x["total"], reverse=True
        )[:10]),
        "source": "event_store"
    }


# ═══════════════════════════════════════════════
# Batch Transfer — A10 (2026-07-24): WIRED. Each item runs the canonical
# /teg/transfer route function IN-PROCESS (fees, IRONKEY spend caveats,
# TokensTransferred emission, EigenTrust signal — the full rail; Rule 13:
# never a parallel money flow). Per-item failure isolation; dev must OWN
# every sender agent (admin may batch for any local agent).
# ═══════════════════════════════════════════════
_BATCH_TRANSFER_CAP = 25


async def _run_batch_transfers(
    items: List[Dict[str, Any]],
    current_developer: Developer,
    request: "Request",
    db: AsyncSession,
) -> Dict[str, Any]:
    """Shared executor for /batch-transfer and /transactions/batch."""
    from fastapi import HTTPException as _HTTPException
    from sqlalchemy import select as _select
    from .teg_integration import transfer_teg_tokens, TEGTransferRequest

    if not items:
        raise HTTPException(status_code=422, detail="No transfer items supplied")
    if len(items) > _BATCH_TRANSFER_CAP:
        raise HTTPException(
            status_code=422,
            detail=f"Batch too large: {len(items)} items (cap {_BATCH_TRANSFER_CAP})",
        )

    results: List[Dict[str, Any]] = []
    succeeded = 0
    for item in items:
        from_did = (item.get("from") or item.get("sender_agent_id") or "").strip()
        to_did = (item.get("to") or item.get("receiver_agent_id") or "").strip()
        amount = str(item.get("amount") or "").strip()
        message = item.get("message")
        base = {"from": from_did, "to": to_did, "amount": amount}
        if not from_did or not to_did or not amount:
            results.append({**base, "status": "failed",
                            "error": "each item needs 'from', 'to' and 'amount'"})
            continue
        sender = (
            await db.execute(_select(Agent).where(Agent.did == from_did))
        ).scalar_one_or_none()
        if sender is None:
            results.append({**base, "status": "failed",
                            "error": f"sender agent not found on this registry: {from_did}"})
            continue
        if (sender.creator_developer_id != current_developer.id
                and not admin_credential(current_developer)):   # D6-057: an admin's scoped key moves only its own agents' units
            results.append({**base, "status": "failed",
                            "error": "sender agent is not owned by the authenticated developer"})
            continue
        try:
            resp = await transfer_teg_tokens(
                transfer_request=TEGTransferRequest(
                    receiver_agent_id=to_did, amount=amount, message=message,
                ),
                request=request,
                current_agent=sender,
                db=db,
                # in-process call: the route's Header(...) default would leak a
                # FieldInfo object as the idempotency key — pass explicitly.
                idempotency_key=item.get("idempotency_key"),
            )
            _resp = resp if isinstance(resp, dict) else getattr(resp, "model_dump", lambda: dict(resp))()
            results.append({**base, "status": "completed",
                            "transaction_id": _resp.get("transaction_id"),
                            "fee_amount": _resp.get("fee_amount")})
            succeeded += 1
        except _HTTPException as e:
            results.append({**base, "status": "failed", "error": str(e.detail)[:300]})
        except Exception as e:  # noqa: BLE001 — isolate the item, keep the batch going
            logger.warning(f"[BatchTransfer] item {from_did}→{to_did} failed: {e}")
            results.append({**base, "status": "failed", "error": str(e)[:300]})
    return {
        "total": len(items),
        "succeeded": succeeded,
        "failed": len(items) - succeeded,
        "results": results,
    }


@router.post("/batch-transfer", include_in_schema=False)
async def batch_transfer(
    request: "Request",
    transfers: Dict[str, List[Dict[str, Any]]] = Body(..., example={
        "transfers": [
            {"from": "did:agentvault:sender", "to": "did:agentvault:agent1", "amount": "100"},
            {"from": "did:agentvault:sender", "to": "did:agentvault:agent2", "amount": "200"}
        ]
    }),
    current_developer: Annotated[Developer, Security(get_current_developer)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None
) -> Dict[str, Any]:
    """Execute multiple TEG transfers with per-item isolation.

    Sequential over the canonical /teg/transfer rail — each leg pays normal
    fees, honors IRONKEY spend limits, and emits TokensTransferred. Every
    'from' agent must belong to the calling developer (admins exempt).
    """
    return await _run_batch_transfers(
        transfers.get("transfers") or [], current_developer, request, db
    )


@router.post("/transactions/batch", include_in_schema=False)
async def batch_transactions(
    request: "Request",
    batch_data: Dict[str, List[Dict[str, Any]]] = Body(...),
    current_developer: Annotated[Developer, Security(get_current_developer)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None
) -> Dict[str, Any]:
    """Submit multiple transactions in a batch.

    A10 (2026-07-24): transfer-type items run on the canonical /teg/transfer
    rail (see /batch-transfer). Non-transfer types are rejected per-item —
    staking/contract operations have their own fully-wired endpoints.
    """
    items = batch_data.get("transactions") or batch_data.get("transfers") or []
    transfer_items: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    for it in items:
        t = (it.get("type") or "transfer").lower()
        if t == "transfer":
            transfer_items.append(it)
        else:
            rejected.append({"type": t, "status": "failed",
                             "error": f"unsupported batch type '{t}' — use the dedicated "
                                      f"lock and contract endpoints"})
    result = await _run_batch_transfers(transfer_items, current_developer, request, db) \
        if transfer_items else {"total": 0, "succeeded": 0, "failed": 0, "results": []}
    result["results"].extend(rejected)
    result["total"] += len(rejected)
    result["failed"] += len(rejected)
    return result


# ═══════════════════════════════════════════════
# Fee Estimates (static config — reasonable)
# ═══════════════════════════════════════════════
@router.get("/fees")
async def get_transaction_fees(
    operation: str = Query("transfer", pattern="^(transfer|stake|unstake)$")
) -> Dict[str, Any]:
    """Get current fee estimates for TEG operations."""
    # Fees are protocol-level config, not mock data
    fee_map = {
        "transfer": {"fee": "0.5", "estimated_time": 15},
        "stake":    {"fee": "1.0", "estimated_time": 30},
        "unstake":  {"fee": "1.5", "estimated_time": 45}
    }
    fee_info = fee_map.get(operation, fee_map["transfer"])
    return {
        "operation": operation,
        "fee": fee_info["fee"],
        "estimated_time": fee_info["estimated_time"],
        "fee_currency": _frame_unit(),   # D6-835: this frame's unit, not AVT on every frame
        "network_congestion": "low",
        "source": "protocol_config"
    }


# ═══════════════════════════════════════════════
# Token Price: there is none
# ═══════════════════════════════════════════════
@router.get("/price", summary="Units carry no price (kept for older clients)")
async def get_teg_price() -> Dict[str, Any]:
    """
    Units carry no price. Kept, with the same keys, for the clients that read this route: it answers the frame's
    unit symbol, usd null and a note that units have no price, no cash-out and no market outside the platform.
    Public, no auth.

    \f
    Units carry no price. Kept (same keys) for the clients that read this route; it answers that there is none.

    §BAFIN (2026-10-01): this route used to answer, without login, "AVT is pegged at 1.00 USD during pre-market
    phase", which no part of the platform does and which contradicts what every frame states: Units are closed-loop
    platform credits with no monetary value, no cash-out and no market outside the platform.
    """
    ccy = (os.environ.get("FRAME_CURRENCY", "AVT") or "AVT").strip().upper() or "AVT"
    return {
        "symbol": ccy,
        "name": "Platform unit",
        "usd": None,
        "note": ("Units have no price and no monetary value: they are closed-loop platform credits. "
                 "There is no cash-out, no redemption and no market for them outside the platform."),
        "change_24h": None,
        "source": "protocol_config",
    }


# ═══════════════════════════════════════════════
# Transaction Export (real data from Event Store)
# ═══════════════════════════════════════════════
@router.get("/transactions/export")
async def export_transactions(
    format: str = Query("json", pattern="^json$"),
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    current_developer: Annotated[Developer, Security(get_current_developer)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None
) -> Dict[str, Any]:
    """Export the transaction events of the caller's own agents from the immutable ledger (a treasury administrator:
    every account's)."""
    logger.info(f"Exporting transactions for developer {current_developer.id} in {format} format")

    scope = await _ledger_scope(current_developer, db)       # SEC-01
    events = [] if scope is not None and not scope else await _es_get("/api/v1/events/", params={"limit": 10000})
    if events is None:
        raise HTTPException(status_code=503, detail="Event Store unreachable")
    if isinstance(events, dict):
        events = events.get("items", events.get("events", []))

    tx_types = _TX_TYPES

    transactions = []
    for evt in events:
        et = evt.get("event_type", "")
        if et not in tx_types or not _in_scope(evt, scope):
            continue
        ts = evt.get("timestamp", "")
        if start_date and ts < start_date:
            continue
        if end_date and ts > end_date + "T23:59:59":
            continue

        data = evt.get("data", {})
        transactions.append({
            "id": str(evt.get("id", "")),
            "event_type": et,
            "aggregate_id": evt.get("aggregate_id", ""),
            "from": data.get("from", data.get("agent_did", "")),
            "to": data.get("to", data.get("agent_did", "")),
            "amount": str(data.get("amount", "0")),
            "timestamp": ts,
            "data": data
        })

    return {
        "format": format,
        "total": len(transactions),
        "transactions": transactions,
        "filters": {"start_date": start_date, "end_date": end_date},
        "source": "event_store",
        "note": "All data from immutable event ledger."
    }
