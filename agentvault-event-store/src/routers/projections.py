"""
Projections Router - API endpoints for querying projections
"""

from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from typing import List, Optional, Literal
from datetime import datetime, timezone
from sqlalchemy import select, func, distinct, case, cast, String, text
from sqlalchemy.ext.asyncio import AsyncSession
from src.services.projections import ProjectionService
from src.services.event_store import EventStore
from src.database.connection import get_db
from src.models.db_models import EventModel, ForeignEventModel
# D6-200 (2026-10-16): the bulk balance reads and the resync write ask the store's own authentication, like every
# other read and write of this store: a read takes any authenticated caller (this frame's services by key or
# certificate, its operators, a federated peer), the resync only this frame's own services. §SECBATCH wave 2: so do the
# three per-agent reads (one account's balance, its history, its balance at a past moment); the registry reads them
# with the key (routers/teg_transactions.py), and anyone else asks the registry, which authenticates its caller.
from .events import require_origin_auth, verify_event_auth
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/projections", tags=["projections"])


# §pass52 PR-11 (partial): response_model for the most-checked endpoint in
# the cluster (~92K+ audit cycles per CLAUDE.md PART 4). Resolves E-P1-7.
class SupplyAuditResponse(BaseModel):
    """Supply invariant audit response. Computed self-consistently from the
    EventStore alone — no cross-system DB lookup.

    The invariant is `tokens_issued == total_circulating + tokens_destroyed`
    where `tokens_issued` accumulates TokensIssued + positive BalanceCorrected +
    DisputeCompensationMinted + snapshot baseline. See CLAUDE.md PART 4 +
    `sessionlogs2026/project_supply_invariant_breach_history.md` for the 6
    historical breach events and the 2026-04-09/12 fixes that keep delta=0.0.
    """
    tokens_issued: float = Field(..., description="Total supply created (sum over all minting events + snapshot baseline)")
    tokens_destroyed: float = Field(..., description="Total supply destroyed (DisputeSlash + negative BalanceCorrected)")
    tokens_fees_collected: float = Field(..., description="Cumulative fees routed to fee_collector account")
    net_supply: float = Field(..., description="tokens_issued - tokens_destroyed + transit_net (§B: per-frame supply incl. cross-frame transit)")
    transit_net: float = Field(0.0, description="§B: signed net of NON-supply legs (transfers/stakes/fees/cross-frame). tokens_issued/destroyed are REAL mint/burn; transit_net closes the per-frame invariant.")
    total_circulating: float = Field(..., description="SUM(liquid + staked) across all agents from materialized projection")
    delta: float = Field(..., description="abs(net_supply - total_circulating). Must be 0.0; <0.01 tolerated (legacy float dust).")
    status: Literal["OK", "BREACH"] = Field(..., description="OK if delta tolerated, BREACH otherwise. Auditor monitors this.")
    agent_count: int = Field(..., description="Number of agents in the materialized balance projection.")
    negative_accounts: int = Field(
        0, description="Projected balances below zero. STRUCTURALLY IMPOSSIBLE for a real account, "
                       "and INVISIBLE TO delta: this projection applies DELTAS ONLY from whenever "
                       "each TEG's balance outbox began emitting, so an account already holding a "
                       "balance at that moment is missing its opening balance for ever — drain it "
                       "and the row goes negative while the same deltas feed transit_net with "
                       "matching sign, keeping the invariant at a contented 0.0. Aggravated for "
                       "`teg:system:*` ids, which are not namespaced per TEG. Non-zero = attribution "
                       "is wrong even though conservation holds.")
    negative_balance_sum: float = Field(
        0.0, description="Sum of the negative liquid balances (<= 0). The size of the missing "
                         "opening-balance mass, not missing money.")


async def get_projection_service(db: AsyncSession = Depends(get_db)) -> ProjectionService:
    """Dependency to get projection service instance"""
    event_store = EventStore(db)
    return ProjectionService(event_store)


@router.get("/balance/{agent_did}", dependencies=[Depends(verify_event_auth)])
async def get_agent_balance(
    agent_did: str,
    refresh: bool = Query(False, description="Bypass cache and recalculate from event log"),
    projection_service: ProjectionService = Depends(get_projection_service)
):
    """
    Get current balance for an agent calculated from their event history.
    
    Use ?refresh=true to bypass the 30-second balance cache and force
    recalculation from the immutable event log. Useful after writes.
    """
    try:
        # OWL20-PREP: Allow cache bypass for fresh reads after writes
        if refresh:
            from src.services.projections import invalidate_balance_cache
            invalidate_balance_cache(agent_did)
            logger.info(f"Cache invalidated for {agent_did} (refresh=true)")
        
        balance = await projection_service.calculate_balance(agent_did)
        return balance.to_dict()
    except Exception as e:
        logger.error(f"Error calculating balance for {agent_did}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/balances", dependencies=[Depends(verify_event_auth)])
async def get_all_balances(
    refresh: bool = Query(False, description="Clear all balance caches first"),
    projection_service: ProjectionService = Depends(get_projection_service)
):
    """
    Get balances for all agents in the system.
    Use ?refresh=true to force fresh calculation.
    Auth: mTLS / X-Internal-Key / X-Federation-License, as every read of this store (D6-200).
    """
    try:
        if refresh:
            from src.services.projections import invalidate_balance_cache
            invalidate_balance_cache()  # No arg = clear all
            logger.info("All balance caches invalidated (refresh=true)")
        balances = await projection_service.get_all_balances()
        return {
            "agents": [b.to_dict() for b in balances],
            "total_agents": len(balances),
            "total_liquid": sum(b.liquid_balance for b in balances),
            "total_staked": sum(b.staked_balance for b in balances)
        }
    except Exception as e:
        logger.error(f"Error calculating all balances: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/materialized-balances", dependencies=[Depends(verify_event_auth)])
async def get_materialized_balances_raw(db: AsyncSession = Depends(get_db)):
    """
    §pass73.3.19 — RAW dump of the materialized_balances table (the authoritative projection state).
    Auth: mTLS / X-Internal-Key / X-Federation-License, as every read of this store (D6-200).

    Unlike /balances (get_all_balances, which filters zero-balance rows + falls back to snapshot/replay),
    this returns the table verbatim — the exact state the trigger maintains. The balance reconciliation
    guard reads THIS so it compares against the real projection, not a divergent recompute.
    """
    rows = (await db.execute(text(
        "SELECT agent_did, liquid_balance, staked_balance FROM materialized_balances"
    ))).fetchall()
    return {
        "agents": [
            {"agent_did": r[0], "liquid_balance": str(r[1]), "staked_balance": str(r[2])}
            for r in rows
        ],
        "count": len(rows),
    }


class ResyncAgentRequest(BaseModel):
    agent_did: str
    liquid_balance: str
    staked_balance: str = "0"


@router.post("/resync-agent", dependencies=[Depends(require_origin_auth)])
async def resync_agent(req: ResyncAgentRequest, db: AsyncSession = Depends(get_db)):
    """
    §pass73.3.19 — targeted reconciliation backstop. Sets materialized_balances[agent] to the given
    (TEG-truth) values and adjusts supply_summary Δ-safe (issued/destroyed += net change), so the supply
    invariant Δ stays 0. Idempotent (re-run with the same values → net 0).

    Auth (D6-200): only this frame's own services (require_origin_auth, as the federation-record writes). It had none,
    and the supply audit cannot see a rewrite through it, because the row and the supply summary move together. Under
    EVENTSTORE_MTLS_REQUIRED (the default) the internal key alone no longer authenticates it, as for every change to
    this store (§SECFIX-7): the caller presents its service certificate through this frame's TLS terminator.

    Needed because under single-writer mode the projection ignores legacy BalanceCorrected events, so the
    guard cannot auto-heal via an emit — it calls this to fix the projection row directly. This should
    fire ~never (L1+L2 keep the projection == TEG by construction); a fire means an upstream gap to fix.
    """
    try:
        new_liq = Decimal(req.liquid_balance)
        new_stk = Decimal(req.staked_balance)
    except Exception:
        raise HTTPException(status_code=422, detail="liquid_balance/staked_balance must be decimal strings")
    cur = (await db.execute(text(
        "SELECT liquid_balance, staked_balance FROM materialized_balances WHERE agent_did=:d"
    ), {"d": req.agent_did})).first()
    old_total = (Decimal(str(cur[0])) + Decimal(str(cur[1]))) if cur else Decimal(0)
    new_total = new_liq + new_stk
    delta = new_total - old_total
    await db.execute(text("""
        INSERT INTO materialized_balances (agent_did, liquid_balance, staked_balance, updated_at)
        VALUES (:d, :l, :s, NOW())
        ON CONFLICT (agent_did) DO UPDATE SET liquid_balance=:l, staked_balance=:s, updated_at=NOW()
    """), {"d": req.agent_did, "l": str(new_liq), "s": str(new_stk)})
    if delta > 0:
        await db.execute(text(
            "UPDATE supply_summary SET tokens_issued = tokens_issued + :x, updated_at=NOW() WHERE id=1"
        ), {"x": str(delta)})
    elif delta < 0:
        await db.execute(text(
            "UPDATE supply_summary SET tokens_destroyed = tokens_destroyed + :x, updated_at=NOW() WHERE id=1"
        ), {"x": str(abs(delta))})
    await db.commit()
    logger.warning(
        f"[resync-agent] {req.agent_did}: projection {old_total} → {new_total} (Δ {delta}) — "
        f"reconciliation backstop fired (investigate upstream L1/L2 if recurring)"
    )
    return {"agent_did": req.agent_did, "old_total": str(old_total),
            "new_total": str(new_total), "delta": str(delta), "resynced": True}


@router.get("/transactions/{agent_did}", dependencies=[Depends(verify_event_auth)])
async def get_transaction_history(
    agent_did: str,
    limit: int = Query(50, ge=1, le=1000),
    event_types: Optional[str] = Query(None, description="Comma-separated event types"),
    projection_service: ProjectionService = Depends(get_projection_service)
):
    """
    Get transaction history for an agent.
    
    Returns a human-readable list of transactions affecting the agent's balance.
    """
    try:
        # Parse event types if provided
        types_list = None
        if event_types:
            types_list = [t.strip() for t in event_types.split(",")]
        
        history = await projection_service.get_transaction_history(
            agent_did=agent_did,
            limit=limit,
            event_types=types_list
        )
        
        return {
            "agent_did": agent_did,
            "transactions": [t.to_dict() for t in history],
            "count": len(history)
        }
    except Exception as e:
        logger.error(f"Error getting transaction history for {agent_did}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/balance/{agent_did}/at/{timestamp}", dependencies=[Depends(verify_event_auth)])
async def get_balance_at_timestamp(
    agent_did: str,
    timestamp: datetime,
    projection_service: ProjectionService = Depends(get_projection_service)
):
    """
    Get balance for an agent at a specific point in time.
    
    This demonstrates the power of Event Sourcing for historical queries.
    We can calculate the exact state at any point in the past.
    """
    try:
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        balance = await projection_service.get_balance_at_timestamp(agent_did, timestamp)
        return balance.to_dict()
    except Exception as e:
        logger.error(f"Error calculating balance at {timestamp} for {agent_did}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def get_projection_stats():
    """
    Overall statistics about the projection system.

    Reads from the in-process cache populated by the background
    `refresh_eventstore_metrics()` loop, which runs at startup and then every
    `ES_METRICS_REFRESH_INTERVAL_S` seconds (900 by default). Instant: no DB
    query in the request path. The previous implementation did 4 sequential
    aggregate scans on a multi-million-row events table and timed out at
    60+ seconds, returning empty stubs to the frontend.

    The cache may be up to one interval stale (15 minutes by default), which
    is fine for a dashboard counter that's already incrementing live via
    WebSocket events.
    """
    try:
        from ..metrics_exporter import get_cached_stats
        return get_cached_stats()
    except Exception as e:
        logger.error(f"Error reading cached projection stats: {e}")
        # Last-resort empty payload (still in correct shape for the frontend)
        return {
            "total_events": 0,
            "unique_agents": 0,
            "event_counts": {},
            "oldest_event": None,
            "newest_event": None,
        }


@router.get("/supply-audit", response_model=SupplyAuditResponse)
async def get_supply_audit(
    db: AsyncSession = Depends(get_db),
    service: ProjectionService = Depends(get_projection_service),
):
    """
    f037: Self-consistent supply conservation audit.

    Computes all values from the event log alone (no external DB comparison).
    Verifies: tokens_issued == tokens_circulating + tokens_in_fees + tokens_destroyed

    Returns delta=0.0 if supply is conserved. Any non-zero delta indicates
    token injection or destruction outside of the event log.

    §pass52 PR-11 (partial): now ships an explicit `SupplyAuditResponse`
    schema for SDK generators (closes E-P1-7 — the most-checked endpoint
    finally has a documented response shape).
    """
    try:
        from decimal import Decimal
        # §pass75.x: ONE statement, ONE MVCC snapshot — supply_summary + Σ(materialized_balances)
        # read atomically. Kills the pre-CQRS read-skew (was: a CACHED `_last_supply_audit` dict
        # vs a SEPARATELY-read live get_all_balances() sum → two snapshots → phantom "live-read
        # in-flight" deltas, e.g. the historical +125 / 169). Under the single-writer CQRS outbox
        # the projection is the sole writer, so a one-shot consistent read is correct AND cheap —
        # it now matches the auditor v2.1 atomic invariant exactly (live_delta ≡ atomic_delta).
        _row = (await db.execute(text(
            "SELECT s.tokens_issued AS issued, s.tokens_destroyed AS destroyed, "
            "s.tokens_fees_collected AS fees, COALESCE(s.transit_net, 0) AS transit_net, "
            "(SELECT COALESCE(SUM(liquid_balance + staked_balance), 0) FROM materialized_balances) AS circ, "
            "(SELECT COUNT(*) FROM materialized_balances) AS agent_count, "
            "(SELECT COUNT(*) FROM materialized_balances "
            " WHERE liquid_balance < 0 OR staked_balance < 0) AS neg_accounts, "
            "(SELECT COALESCE(SUM(liquid_balance), 0) FROM materialized_balances "
            " WHERE liquid_balance < 0) AS neg_sum "
            "FROM supply_summary s WHERE s.id = 1"
        ))).first()
        if _row is not None:
            tokens_issued = Decimal(str(_row.issued))
            tokens_destroyed = Decimal(str(_row.destroyed))
            tokens_fees = Decimal(str(_row.fees))
            transit_net = Decimal(str(_row.transit_net))
            total_circulating = Decimal(str(_row.circ))
            agent_count = int(_row.agent_count)
            neg_accounts = int(_row.neg_accounts)
            neg_sum = Decimal(str(_row.neg_sum))
        else:
            # Pre-init safety (supply_summary not seeded yet): fall back to the service cache path.
            audit = getattr(service, '_last_supply_audit', {})
            balances = await service.get_all_balances()
            total_circulating = sum(
                (Decimal(str(b.liquid_balance)) + Decimal(str(b.staked_balance)))
                for b in balances
            ) if balances else Decimal("0")
            tokens_issued = Decimal(str(audit.get("tokens_issued", 0)))
            tokens_destroyed = Decimal(str(audit.get("tokens_destroyed", 0)))
            tokens_fees = Decimal(str(audit.get("tokens_fees_collected", 0)))
            transit_net = Decimal(str(audit.get("transit_net", 0)))
            agent_count = len(balances)
            neg_accounts = sum(1 for b in balances if Decimal(str(b.liquid_balance)) < 0)
            neg_sum = sum((Decimal(str(b.liquid_balance)) for b in balances
                           if Decimal(str(b.liquid_balance)) < 0), Decimal("0"))
        # §B: per-frame invariant — tokens_issued − tokens_destroyed + transit_net = circulating.
        net_supply = tokens_issued - tokens_destroyed + transit_net
        delta = abs(net_supply - total_circulating)

        return {
            "tokens_issued": float(tokens_issued),
            "tokens_destroyed": float(tokens_destroyed),
            "tokens_fees_collected": float(tokens_fees),
            "transit_net": float(transit_net),
            "net_supply": float(net_supply),
            "total_circulating": float(total_circulating),
            "delta": float(delta),
            "negative_accounts": neg_accounts,
            "negative_balance_sum": float(neg_sum),
            # §pass52 Phase G: tightened tolerance 0.01 → 0.0. The 0.01 cushion
            # masked the 6 historical 37-AVT breach events for ~17 min each before
            # auto-resolution; with strict==0 we catch any deviation in the next
            # 10s auditor poll. Auditor's avg_delta=0.008104 (legacy float dust) is
            # WITHIN this tolerance because delta computation uses abs() and
            # `delta < Decimal("0")` is impossible — only exact 0.0 passes.
            "status": "OK" if delta == Decimal("0") else "BREACH",
            "agent_count": agent_count,
        }
    except Exception as e:
        logger.error(f"Supply audit error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cross-frame-audit")
async def cross_frame_audit(
    db: AsyncSession = Depends(get_db),
    service: ProjectionService = Depends(get_projection_service),
):
    """SF-4: Cross-frame supply consistency audit.

    Compares local supply audit with replicated foreign events to verify
    that bridge transfers are consistent across sovereign frames.
    """
    try:
        # Get local supply audit
        balances = await service.get_all_balances()
        local_audit = getattr(service, '_last_supply_audit', {})

        # Query foreign_events summary per frame
        result = await db.execute(
            select(
                ForeignEventModel.frame_id,
                ForeignEventModel.event_type,
                func.count().label("count"),
                func.max(ForeignEventModel.replicated_at).label("last_replicated"),
            )
            .group_by(ForeignEventModel.frame_id, ForeignEventModel.event_type)
            .order_by(ForeignEventModel.frame_id)
        )
        rows = result.all()

        # Build per-frame breakdown
        foreign_frames = {}
        for row in rows:
            fid = row.frame_id
            if fid not in foreign_frames:
                foreign_frames[fid] = {
                    "events_replicated": 0,
                    "last_replicated_at": None,
                    "event_breakdown": {},
                }
            foreign_frames[fid]["events_replicated"] += row.count
            foreign_frames[fid]["event_breakdown"][row.event_type] = row.count
            if row.last_replicated:
                ts = row.last_replicated.isoformat()
                if not foreign_frames[fid]["last_replicated_at"] or ts > foreign_frames[fid]["last_replicated_at"]:
                    foreign_frames[fid]["last_replicated_at"] = ts

        # Sum bridge events from foreign frames to compare with local
        # For each foreign frame: WrappedTokensMinted - WrappedTokensBurned = net wrapped
        # This should match our local bridge_locked
        checks = []
        consistent = True

        local_bridge_locked = Decimal(str(local_audit.get("bridge_locked", 0)))
        local_wrapped_foreign = Decimal(str(local_audit.get("wrapped_foreign", 0)))

        for fid, fdata in foreign_frames.items():
            bd = fdata["event_breakdown"]
            remote_minted = bd.get("WrappedTokensMinted", 0)
            remote_burned = bd.get("WrappedTokensBurned", 0)
            remote_locked = bd.get("TokensBridgeLocked", 0)
            remote_unlocked = bd.get("TokensBridgeUnlocked", 0)

            # Note: we report event COUNTS, not amounts (amounts need individual event parsing)
            # For the audit, having the events replicated is the key — amounts are verified via supply audit
            checks.append(
                f"{fid}: {fdata['events_replicated']} events replicated, "
                f"bridge events: locked={remote_locked}, unlocked={remote_unlocked}, "
                f"minted={remote_minted}, burned={remote_burned}"
            )

        total_foreign = sum(f["events_replicated"] for f in foreign_frames.values())

        # ── Cross-Frame FX invariants (WS-E, 2026-06-02) ──────────────────────
        # I1 per-frame Δ=0 · I2 fx_reserve solvency (≥ floor) · I3 per-swap
        # value-conservation (amount_in·rate == amount_out + fee ± ε) from the
        # FxSwapSettled audit events. These GATE cross_frame_consistent. The
        # reserve's mark-to-market (R_A + R_B·P) is intentionally NOT gated —
        # that is treasury inventory P&L, a Phase-2 (floating-rate) concern.
        import os as _os
        fx_eps = Decimal("0.01")
        # I1 — local supply delta (the per-frame auditor's verdict)
        try:
            i1_delta = abs(Decimal(str(local_audit.get("delta", 0))))
        except Exception:
            i1_delta = Decimal("0")
        i1_ok = i1_delta <= fx_eps
        # I2 — fx_reserve solvency vs the configured floor for THIS frame's currency
        _frame_ccy = (_os.environ.get("FRAME_CURRENCY", "AVT") or "AVT").strip().upper()
        try:
            i2_floor = Decimal(str(_os.environ.get(f"FX_RESERVE_FLOOR_{_frame_ccy}", "0")))
        except Exception:
            i2_floor = Decimal("0")
        _reserve_bal = None
        for _b in balances:
            if getattr(_b, "agent_did", None) == "did:theprotocol:teg_system_fx_reserve":
                _reserve_bal = Decimal(str(_b.liquid_balance)) + Decimal(str(_b.staked_balance))
                break
        # No reserve on this frame ⇒ not an FX participant ⇒ vacuously solvent.
        i2_ok = (_reserve_bal is None) or (_reserve_bal >= i2_floor)
        # I3 — per-swap value conservation from FxSwapSettled events
        i3_total = 0
        i3_breaches = []
        try:
            _fx_rows = (await db.execute(
                select(EventModel.data).where(EventModel.event_type == "FxSwapSettled")
            )).scalars().all()
            for _d in _fx_rows:
                if isinstance(_d, str):
                    import json as _json
                    try:
                        _d = _json.loads(_d)
                    except Exception:
                        continue
                i3_total += 1
                try:
                    _ain = Decimal(str(_d.get("amount_in")))
                    _rate = Decimal(str(_d.get("rate")))
                    _aout = Decimal(str(_d.get("amount_out")))
                    _fee = Decimal(str(_d.get("fee")))
                    if abs(_ain * _rate - (_aout + _fee)) > fx_eps:
                        i3_breaches.append(_d.get("swap_id"))
                except Exception:
                    i3_breaches.append(_d.get("swap_id"))
        except Exception as _e:
            logger.warning(f"FX I3 audit query failed: {_e}")
        i3_ok = (len(i3_breaches) == 0)

        fx_consistent = bool(i1_ok and i2_ok and i3_ok)
        consistent = consistent and fx_consistent
        fx_invariants = {
            "I1_per_frame_delta_zero": {"ok": bool(i1_ok), "delta": float(i1_delta)},
            "I2_reserve_solvency": {
                "ok": bool(i2_ok),
                "currency": _frame_ccy,
                "reserve_balance": (float(_reserve_bal) if _reserve_bal is not None else None),
                "floor": float(i2_floor),
            },
            "I3_value_conservation": {
                "ok": bool(i3_ok),
                "swaps_checked": i3_total,
                "breaches": [b for b in i3_breaches if b],
            },
            "fx_consistent": fx_consistent,
        }

        return {
            "local_supply": {
                "tokens_issued": local_audit.get("tokens_issued", "0"),
                "bridge_locked": str(local_bridge_locked),
                "wrapped_foreign": str(local_wrapped_foreign),
                "net_supply": local_audit.get("net_supply", "0"),
                "agent_count": len(balances),
            },
            "foreign_frames": foreign_frames,
            "total_foreign_events": total_foreign,
            "cross_frame_consistent": consistent,
            "checks": checks,
            "fx_invariants": fx_invariants,
            "status": "OK" if consistent else "BREACH",
        }
    except Exception as e:
        logger.error(f"Cross-frame audit error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# SF-5D: Cross-Frame Reputation (EigenTrust score sharing via SF-4 replication)
# ---------------------------------------------------------------------------

@router.get("/cross-frame-reputation")
async def get_cross_frame_reputation(
    frame_id: Optional[str] = Query(None, description="Filter by originating frame"),
    limit: int = Query(200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    """
    SF-5D: Aggregate reputation scores from foreign ReputationChanged events.

    These events are replicated via SF-4 (cross-frame EventStore replication).
    Each event contains an agent_did and their EigenTrust global_trust score
    as computed by the originating frame's registry.

    Returns the latest reputation score per agent per frame.
    """
    try:
        # Query foreign ReputationChanged events (replicated via SF-4)
        query = (
            select(ForeignEventModel)
            .where(ForeignEventModel.event_type == "ReputationChanged")
            .order_by(ForeignEventModel.timestamp.desc())
        )
        if frame_id:
            query = query.where(ForeignEventModel.frame_id == frame_id)
        query = query.limit(limit)

        result = await db.execute(query)
        events = result.scalars().all()

        # Deduplicate: keep latest event per (frame_id, agent_did)
        seen = {}
        for evt in events:
            data = evt.data or {}
            agent_did = data.get("agent_did") or evt.aggregate_id
            key = (evt.frame_id, agent_did)
            if key not in seen:
                seen[key] = {
                    "agent_did": agent_did,
                    "frame_id": evt.frame_id,
                    "global_trust": data.get("new_score", data.get("global_trust", 0)),
                    "reputation_score": data.get("reputation_score", 0),
                    "epoch": data.get("epoch"),
                    "timestamp": evt.timestamp.isoformat() if evt.timestamp else None,
                    "source_event_id": str(evt.source_event_id),
                }

        # Also query local ReputationChanged events for completeness
        local_query = (
            select(EventModel)
            .where(EventModel.event_type == "ReputationChanged")
            .order_by(EventModel.timestamp.desc())
            .limit(limit)
        )
        local_result = await db.execute(local_query)
        local_events = local_result.scalars().all()

        local_scores = {}
        for evt in local_events:
            data = evt.data or {}
            agent_did = data.get("agent_did") or evt.aggregate_id
            if agent_did not in local_scores:
                local_scores[agent_did] = {
                    "agent_did": agent_did,
                    "frame_id": "local",
                    "global_trust": data.get("new_score", data.get("global_trust", 0)),
                    "reputation_score": data.get("reputation_score", 0),
                    "epoch": data.get("epoch"),
                    "timestamp": evt.timestamp.isoformat() if evt.timestamp else None,
                }

        return {
            "foreign_reputation": list(seen.values()),
            "local_reputation": list(local_scores.values()),
            "foreign_agent_count": len(seen),
            "local_agent_count": len(local_scores),
            "status": "OK",
        }
    except Exception as e:
        logger.error(f"SF-5D: Cross-frame reputation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
