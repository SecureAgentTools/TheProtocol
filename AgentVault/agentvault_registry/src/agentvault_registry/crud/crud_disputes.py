"""
CRUD operations for the Decentralized Dispute Resolution (DDR) system.

This module provides database operations for managing disputes and evidence
in the decentralized justice system.
"""

from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy import select, and_, or_

from ..models import Agent, Dispute, Evidence
from ..core import reputation_manager
from ..event_emitter import get_event_emitter
import asyncio
import uuid
import httpx
import logging

logger = logging.getLogger(__name__)


def _frame_unit() -> str:
    # D6-835 (2026-10-25): this frame's unit, asked where the amount is written (it said AVT on every frame)
    from agentvault_registry.core.frame_currency import frame_currency
    return frame_currency()


# FIX-28: Get all disputes (for admin listing)
async def get_all_disputes(
    db: AsyncSession,
    status_filter: Optional[str] = None,
    defendant_did: Optional[str] = None,
    complainant_did: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    party_developer_id: Optional[int] = None,
) -> List[Dispute]:
    """Get all disputes, optionally filtered by status / defendant_did / complainant_did.

    P18-001: defendant_did + status filters added so SYBIL's prosecution Gate 6
    (`/api/v1/disputes/?defendant_did=X&status=open`) can filter at query time
    instead of pulling everything and filtering client-side.

    party_developer_id: only the disputes one of this developer's agents is a party to (§SECFIX D6-465).
    """
    result = await db.execute(all_disputes_stmt(status_filter, defendant_did, complainant_did, limit, offset,
                                                party_developer_id=party_developer_id))
    return list(result.scalars().all())


def developer_party_clause(developer_id: int):
    """A dispute one of this developer's agents is a party to: its complainant or its defendant is an agent the
    developer owns (agents.creator_developer_id)."""
    owned = select(Agent.did).where(Agent.creator_developer_id == developer_id)
    return or_(Dispute.complainant_did.in_(owned), Dispute.defendant_did.in_(owned))


def all_disputes_stmt(
    status_filter: Optional[str] = None,
    defendant_did: Optional[str] = None,
    complainant_did: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    party_developer_id: Optional[int] = None,
):
    """The dispute list's statement: newest first, the id breaking a tie.

    §COCKPITDESK (2026-10-15): created_at alone is not unique, so two pages of this feed could repeat one dispute and
    drop another (the §DIRFEED-2 rule: a paginated feed needs a unique tiebreak or it is not a partition). The console
    now pages through it to count disputes (its tiles had counted the first page of 100 as the total).
    """
    query = select(Dispute).options(selectinload(Dispute.evidence))
    if status_filter:
        query = query.where(Dispute.status == status_filter)
    if defendant_did:
        query = query.where(Dispute.defendant_did == defendant_did)
    if complainant_did:
        query = query.where(Dispute.complainant_did == complainant_did)
    if party_developer_id is not None:
        query = query.where(developer_party_clause(party_developer_id))
    return query.order_by(Dispute.created_at.desc(), Dispute.id.desc()).limit(limit).offset(offset)


async def create_dispute(
    db: AsyncSession,
    complainant_did: str,
    defendant_did: str,
    referenced_attestations: Optional[List[str]] = None,
    contract_id: Optional[int] = None,
) -> Dispute:
    """
    Create a new dispute between two agents.

    Args:
        db: Database session
        complainant_did: DID of the agent filing the complaint
        defendant_did: DID of the agent being accused
        referenced_attestations: Phase 3 — UUID strings of verified attestations
            cited as exculpatory evidence, stored on the dispute. No slash path
            applies a reduction in this release (D6-440): the sandbox-only
            preview-slash-reduction route computes one without applying it.
        contract_id: X1 (2026-05-06) — optional soft int reference to the source
            RUC contract (refactoring_upgrade_contracts.id) when this dispute is
            filed via /api/v1/contracts/{id}/malpractice. Lets Disputes.vue render
            a "View source contract →" link. No FK constraint; cross-registry
            contracts may not exist locally.

    Returns:
        The newly created Dispute object
    """
    db_dispute = Dispute(
        complainant_did=complainant_did,
        defendant_did=defendant_did,
        status="OPEN",
        referenced_attestations=referenced_attestations,
        contract_id=contract_id,
    )
    db.add(db_dispute)
    await db.commit()
    await db.refresh(db_dispute)

    # A1 (2026-07-24): dispute.created was subscribable but never fired. Central here so
    # every path (router filings + guild DDR + reaper) notifies both parties' developers.
    try:
        import asyncio as _aio
        from agentvault_registry.background_tasks.reactor_helpers import dispatch_webhook_for_agents
        _aio.create_task(dispatch_webhook_for_agents(
            "dispute.created",
            {"dispute_id": db_dispute.id, "complainant_did": complainant_did,
             "defendant_did": defendant_did, "status": str(getattr(db_dispute, "status", "OPEN"))},
            [complainant_did, defendant_did], source_label="disputes.create"))
    except Exception:  # noqa: BLE001 — notification must never break dispute filing
        pass
    return db_dispute


async def get_dispute_by_id(
    db: AsyncSession,
    dispute_id: int
) -> Optional[Dispute]:
    """
    Retrieve a dispute by its ID.
    
    Args:
        db: Database session
        dispute_id: ID of the dispute to retrieve
        
    Returns:
        The Dispute object if found, None otherwise
    """
    query = select(Dispute).options(
        selectinload(Dispute.evidence)
    ).where(Dispute.id == dispute_id)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def add_evidence_to_dispute(
    db: AsyncSession,
    dispute_id: int,
    submitter_did: str,
    evidence_data: Dict[str, Any]
) -> Optional[Evidence]:
    """
    Add evidence to an existing dispute.

    D5: Lock the dispute row + re-check status inside the lock so a concurrent
    ruling can't transition status to CLOSED between the router's pre-check
    and our INSERT.

    D9: Cap to 10 evidence rows per submitter per dispute to prevent DoS.

    Args:
        db: Database session
        dispute_id: ID of the dispute
        submitter_did: DID of the agent submitting the evidence
        evidence_data: JSON data containing the evidence details

    Returns:
        The newly created Evidence object if dispute exists and is OPEN, None otherwise
    """
    from sqlalchemy import func

    # D5: Lock + re-check status inside the lock
    query = select(Dispute).where(Dispute.id == dispute_id).with_for_update()
    result = await db.execute(query)
    dispute = result.scalar_one_or_none()
    if not dispute:
        return None
    if dispute.status == "CLOSED":
        # Caller's pre-check passed but a concurrent ruling closed it.
        # Surface as "not open" — caller will translate to 400.
        return None

    # D9: Per-submitter row cap
    count_q = await db.execute(
        select(func.count(Evidence.id)).where(
            Evidence.dispute_id == dispute_id,
            Evidence.submitter_did == submitter_did,
        )
    )
    existing = count_q.scalar() or 0
    MAX_EVIDENCE_PER_SUBMITTER = 10
    if existing >= MAX_EVIDENCE_PER_SUBMITTER:
        # Special sentinel: caller will translate to 429.
        raise ValueError(
            f"Evidence cap reached: {existing}/{MAX_EVIDENCE_PER_SUBMITTER} "
            f"submissions by {submitter_did} on dispute {dispute_id}"
        )

    # Create the evidence
    db_evidence = Evidence(
        dispute_id=dispute_id,
        submitter_did=submitter_did,
        evidence_data=evidence_data
    )
    db.add(db_evidence)

    # Update the dispute's updated_at timestamp
    dispute.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(db_evidence)
    return db_evidence


async def update_dispute_status(
    db: AsyncSession,
    dispute_id: int,
    new_status: str
) -> Optional[Dispute]:
    """
    Update the status of a dispute.
    
    Args:
        db: Database session
        dispute_id: ID of the dispute to update
        new_status: New status value (OPEN, VOTING, CLOSED)
        
    Returns:
        The updated Dispute object if found, None otherwise
    """
    query = select(Dispute).where(Dispute.id == dispute_id)
    result = await db.execute(query)
    dispute = result.scalar_one_or_none()
    if not dispute:
        return None
    
    dispute.status = new_status
    dispute.updated_at = datetime.now(timezone.utc)
    
    await db.commit()
    await db.refresh(dispute)
    return dispute


async def get_disputes_by_agent(
    db: AsyncSession,
    agent_did: str,
    role: Optional[str] = None  # "complainant", "defendant", or None for both
) -> List[Dispute]:
    """
    Retrieve all disputes involving a specific agent.
    
    Args:
        db: Database session
        agent_did: DID of the agent
        role: Optional filter for the agent's role in disputes
        
    Returns:
        List of Dispute objects involving the agent
    """
    query = select(Dispute).options(selectinload(Dispute.evidence))
    
    if role == "complainant":
        query = query.where(Dispute.complainant_did == agent_did)
    elif role == "defendant":
        query = query.where(Dispute.defendant_did == agent_did)
    else:
        # Get disputes where agent is either complainant or defendant
        query = query.where(
            or_(
                Dispute.complainant_did == agent_did,
                Dispute.defendant_did == agent_did
            )
        )
    
    query = query.order_by(Dispute.created_at.desc())
    result = await db.execute(query)
    return result.scalars().all()


class DisputeAlreadyRuled(ValueError):
    """Sentinel raised when a ruling is attempted on an already-CLOSED dispute (D6)."""


async def update_dispute_ruling(
    db: AsyncSession,
    dispute_id: int,
    ruling: str
) -> Optional[Dispute]:
    """
    Update the ruling of a dispute and close it.

    D2 fix: SELECT FOR UPDATE row-level lock prevents the race where two
    admins submit a ruling concurrently and compensation is applied twice.

    D6 fix: idempotency guard — if dispute already has a ruling, raise
    DisputeAlreadyRuled (caller translates to 409). This prevents double
    compensation when the same ruling is retried.

    Args:
        db: Database session
        dispute_id: ID of the dispute
        ruling: The final ruling (IN_FAVOR_OF_COMPLAINANT, IN_FAVOR_OF_DEFENDANT, DISMISSED)

    Returns:
        The updated Dispute object if found and unruled, None if not found.
        Raises DisputeAlreadyRuled if dispute already CLOSED.
    """
    # D2: SELECT FOR UPDATE
    query = select(Dispute).where(Dispute.id == dispute_id).with_for_update()
    result = await db.execute(query)
    dispute = result.scalar_one_or_none()
    if not dispute:
        return None

    # D6: Idempotency guard
    if dispute.ruling is not None or dispute.status == "CLOSED":
        raise DisputeAlreadyRuled(
            f"Dispute {dispute_id} is already CLOSED with ruling={dispute.ruling}"
        )

    dispute.ruling = ruling
    dispute.status = "CLOSED"
    dispute.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(dispute)

    # Update reputation scores based on the dispute outcome
    await reputation_manager.record_dispute_outcome(db, dispute)

    # §4.12: EnforcementEngine escalation when ruling goes against defendant
    if ruling == "IN_FAVOR_OF_COMPLAINANT":
        try:
            from ..services.enforcement_engine import get_enforcement_engine
            disputed_amount = await extract_disputed_amount(db, dispute.id)
            engine = get_enforcement_engine()
            await engine.evaluate_dispute_outcome(
                db=db,
                defendant_did=dispute.defendant_did,
                dispute_id=dispute.id,
                disputed_amount=disputed_amount,
            )
            logger.info(
                f"[DisputeRuling] EnforcementEngine evaluated dispute #{dispute.id}: "
                f"defendant={dispute.defendant_did}, disputed_amount={disputed_amount}"
            )
        except Exception as e:
            # Non-fatal: log and continue
            logger.error(
                f"[DisputeRuling] EnforcementEngine evaluation failed for dispute #{dispute.id}: {e}",
                exc_info=True,
            )

    # Phase 1: Emit DisputeResolved event to EventStore for audit trail
    # D7: synchronous emit (was fire-and-forget; tasks could be GC'd).
    # D15: aggregate_id="dispute:N", aggregate_type="Dispute" (normalized).
    event_emitter = get_event_emitter()
    try:
        await event_emitter.emit(
            event_type="DisputeResolved",
            aggregate_id=f"dispute:{dispute.id}",
            aggregate_type="Dispute",
            data={
                "dispute_id": dispute.id,
                "ruling": ruling,
                "complainant_did": dispute.complainant_did,
                "defendant_did": dispute.defendant_did,
                "resolved_at": dispute.updated_at.isoformat()
            }
        )
        logger.info(f"Emitted DisputeResolved event for dispute #{dispute.id}")
    except Exception as e:
        logger.error(f"Failed to emit DisputeResolved event: {e}")

    return dispute


async def extract_disputed_amount(db: AsyncSession, dispute_id: int) -> int:
    """
    Extract the disputed AVT amount from evidence attached to a dispute.
    
    Searches evidence_data for amount fields like:
    - amount_disputed
    - disputed_amount  
    - amount
    - impact.total_avt_at_risk
    
    Returns:
        The disputed amount in AVT, or 0 if not found
    """
    query = select(Evidence).where(Evidence.dispute_id == dispute_id)
    result = await db.execute(query)
    evidence_list = result.scalars().all()
    
    for ev in evidence_list:
        data = ev.evidence_data or {}
        
        # Check common amount field names
        for key in ['amount_disputed', 'disputed_amount', 'amount', 'avt_amount']:
            if key in data:
                try:
                    return int(float(str(data[key])))
                except (ValueError, TypeError):
                    continue
        
        # Check nested impact structure
        impact = data.get('impact', {})
        if isinstance(impact, dict):
            for key in ['total_avt_at_risk', 'amount', 'avt_lost']:
                if key in impact:
                    try:
                        return int(float(str(impact[key])))
                    except (ValueError, TypeError):
                        continue
    
    return 0


async def process_compensation(
    db: AsyncSession,
    dispute: Dispute,
    ruling: str
) -> Dict[str, Any]:
    """
    Process AVT compensation after a dispute ruling.
    
    OWL25 Sovereign Settlement Protocol:
    - SAME-REGISTRY: Both agents local → real DB debit/credit + TokensTransferred event
    - CROSS-REGISTRY: Defendant foreign → emit DisputeCompensationRequest (no balance effect)
      → send slash request to defendant's home registry → auto-slash + auto-mint
    
    Args:
        db: Database session
        dispute: The resolved dispute
        ruling: The ruling value
        
    Returns:
        Dict with compensation details
    """
    compensation_result = {
        "applied": False,
        "amount": 0,
        "amount_requested": 0,
        "from_did": None,
        "to_did": None,
        "reason": None,
        "event_emitted": False,
        "partial": False,
        "deferred_amount": 0,
        "cross_registry": False,
        "settlement_status": None
    }
    
    # Only compensate when ruling is in favor of complainant
    if ruling != "IN_FAVOR_OF_COMPLAINANT":
        compensation_result["reason"] = f"No compensation for ruling: {ruling}"
        return compensation_result
    
    # Extract disputed amount from evidence
    disputed_amount = await extract_disputed_amount(db, dispute.id)
    
    if disputed_amount <= 0:
        compensation_result["reason"] = "No disputed amount found in evidence"
        return compensation_result
    
    compensation_result["amount_requested"] = disputed_amount
    compensation_result["from_did"] = dispute.defendant_did
    compensation_result["to_did"] = dispute.complainant_did
    
    # Determine if defendant is local or cross-registry
    from ..models import Agent, CrossRegistrySettlement
    defendant_result = await db.execute(
        select(Agent).where(Agent.did == dispute.defendant_did)
    )
    defendant = defendant_result.scalar_one_or_none()
    
    if defendant:
        # ============================================================
        # SAME-REGISTRY PATH: Full jurisdiction over both agents
        # ============================================================
        return await _process_local_compensation(
            db, dispute, ruling, defendant, disputed_amount, compensation_result
        )
    else:
        # ============================================================
        # CROSS-REGISTRY PATH: Defendant is foreign — sovereign settlement
        # ============================================================
        return await _process_cross_registry_compensation(
            db, dispute, ruling, disputed_amount, compensation_result
        )


async def _process_local_compensation(
    db: AsyncSession,
    dispute: Dispute,
    ruling: str,
    defendant: "Agent",
    disputed_amount: int,
    compensation_result: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Same-registry compensation: full jurisdiction.
    Deducts from defendant DB, credits complainant DB, emits TokensTransferred.
    """
    from ..models import Agent
    actual_amount = disputed_amount
    # ROD2 (2026-07-24): slash floors at 0 — max() guards a mirror that has
    # already gone negative from legacy debt writes.
    available_balance = max(defendant.liquid_balance or 0, 0)

    if available_balance <= 0:
        # ROD2: never drive a balance negative. The full amount stays owed
        # (deferred debt trail) and no money moves.
        actual_amount = 0
        logger.warning(
            f"Defendant {dispute.defendant_did} has 0 AVT liquid balance. "
            f"Compensation of {disputed_amount} AVT deferred — no negative-balance debt."
        )
        compensation_result["defendant_balance_warning"] = (
            f"Defendant had 0 {_frame_unit()}. Compensation deferred in full ({disputed_amount} {_frame_unit()} owed)."
        )
        try:
            await reputation_manager.update_reputation(
                db, dispute.defendant_did, -5,
                f"Insufficient balance for dispute #{dispute.id} compensation"
            )
        except Exception as e:
            logger.error(f"Failed to apply insufficient-funds rep penalty: {e}")
                
    elif available_balance < disputed_amount:
        actual_amount = available_balance
        deferred = disputed_amount - available_balance
        compensation_result["partial"] = True
        compensation_result["deferred_amount"] = deferred
        logger.warning(
            f"Partial compensation for dispute #{dispute.id}: "
            f"defendant has {available_balance} AVT of {disputed_amount} requested."
        )
        try:
            await reputation_manager.update_reputation(
                db, dispute.defendant_did, -3,
                f"Partial compensation for dispute #{dispute.id} ({deferred} {_frame_unit()} deferred)"
            )
        except Exception as e:
            logger.error(f"Failed to apply partial-compensation rep penalty: {e}")
    
    compensation_result["amount"] = actual_amount
    event_emitter = get_event_emitter()

    if actual_amount <= 0:
        # ROD2: nothing to move. Record the full debt trail and stop.
        compensation_result["applied"] = False
        compensation_result["deferred_amount"] = disputed_amount
        compensation_result["reason"] = (
            "Defendant has zero balance; compensation deferred (no negative-balance debt)"
        )
        try:
            await event_emitter.emit(
                event_type="DisputeCompensationDeferred",
                aggregate_id=f"dispute:{dispute.id}",
                aggregate_type="Dispute",
                data={
                    "dispute_id": dispute.id,
                    "deferred_amount": disputed_amount,
                    "paid_amount": 0,
                    "total_owed": disputed_amount,
                    "creditor_did": dispute.complainant_did,
                    "debtor_did": dispute.defendant_did,
                },
            )
        except Exception as e:
            logger.error(f"Failed to emit deferred compensation event: {e}")
        return compensation_result

    # ROD1 (2026-07-24): route the money through TEG rails instead of mutating
    # the registry's liquid_balance mirror. TEG is the source of truth -- a
    # direct mirror write is silently reverted by the next balance sync and the
    # TEG ledger never sees the move (Rule 10). Two legs, both carrying durable
    # idempotency keys so a retried ruling replays from cache (exactly-once):
    #   slash: defendant -> treasury    (admin/treasury/receive, ddr-slash-{id})
    #   comp:  treasury  -> complainant (admin/reward-fund,      ddr-comp-{id})
    # Balance events reach the EventStore via the TEG outbox; the old synthetic
    # defendant->complainant TokensTransferred emit is intentionally GONE -- it
    # would double-count against the outbox legs in the balance projection.
    from ..config import settings
    from ..es_ssl_helper import get_httpx_verify
    from decimal import Decimal

    teg_url = settings.TEG_API_BASE_URL.rstrip('/')
    teg_admin_key = settings.TEG_ADMIN_API_KEY
    slash_ok = False
    comp_ok = False
    comp_tx_id = None

    try:
        async with httpx.AsyncClient(timeout=15.0, verify=get_httpx_verify()) as client:
            slash_resp = await client.post(
                f"{teg_url}/api/v1/admin/treasury/receive",
                json={
                    "source_agent_id": dispute.defendant_did,
                    # §MONEY-R15: str(float(Decimal)) truncates; the TEG takes a Decimal.
                    "amount": str(actual_amount),
                    "reason": "dispute_slash",
                    "reference_id": f"ddr-{dispute.id}",
                },
                headers={
                    "Authorization": f"Bearer {teg_admin_key}",
                    "Content-Type": "application/json",
                    "Idempotency-Key": f"ddr-slash-{dispute.id}",
                },
            )
            if slash_resp.status_code in (200, 201):
                slash_ok = True
                _nb = slash_resp.json().get("new_source_balance")
                if _nb is not None:
                    defendant.liquid_balance = Decimal(str(_nb))
            else:
                logger.error(
                    f"[DisputeComp] TEG slash failed ({slash_resp.status_code}) for "
                    f"dispute #{dispute.id}: {slash_resp.text[:200]} -- no direct DB "
                    f"fallback, TEG is source of truth."
                )
    except Exception as e:
        logger.error(f"[DisputeComp] TEG slash call failed for dispute #{dispute.id}: {e}")

    complainant_result = await db.execute(
        select(Agent).where(Agent.did == dispute.complainant_did)
    )
    complainant = complainant_result.scalar_one_or_none()

    if slash_ok:
        try:
            async with httpx.AsyncClient(timeout=15.0, verify=get_httpx_verify()) as client:
                comp_resp = await client.post(
                    f"{teg_url}/api/v1/admin/reward-fund",
                    json={
                        "target_agent_id": dispute.complainant_did,
                        # §MONEY-R15: str(float(Decimal)) truncates; the TEG takes a Decimal.
                        "amount": str(actual_amount),
                        "reason": "dispute_compensation",
                        "reference_id": f"ddr-{dispute.id}-comp",
                    },
                    headers={
                        "Authorization": f"Bearer {teg_admin_key}",
                        "Content-Type": "application/json",
                        "Idempotency-Key": f"ddr-comp-{dispute.id}",
                    },
                )
                if comp_resp.status_code in (200, 201):
                    comp_ok = True
                    _cd = comp_resp.json()
                    _legs = _cd.get("legs") or []
                    comp_tx_id = (
                        (_legs[0].get("transaction_id") if _legs else None)
                        or _cd.get("transaction_id")
                    )
                    if complainant is not None and _cd.get("new_target_balance") is not None:
                        complainant.liquid_balance = Decimal(str(_cd["new_target_balance"]))
                else:
                    logger.error(
                        f"[DisputeComp] TEG compensation payout failed "
                        f"({comp_resp.status_code}) for dispute #{dispute.id}: "
                        f"{comp_resp.text[:200]}"
                    )
        except Exception as e:
            logger.error(f"[DisputeComp] TEG compensation call failed for dispute #{dispute.id}: {e}")

    await db.commit()

    compensation_result["applied"] = comp_ok
    compensation_result["transaction_id"] = comp_tx_id
    compensation_result["teg_slash"] = slash_ok
    compensation_result["teg_comp"] = comp_ok

    if not slash_ok:
        compensation_result["reason"] = "TEG slash failed -- no money moved (retry the ruling to re-drive)"
        return compensation_result
    if slash_ok and not comp_ok:
        # Funds are parked in the treasury, NOT lost. A re-drive of
        # /admin/reward-fund with Idempotency-Key ddr-comp-{id} pays exactly once.
        compensation_result["comp_failed"] = True
        compensation_result["reason"] = (
            f"Slashed {actual_amount} {_frame_unit()} to treasury but payout failed -- funds parked "
            f"in treasury; re-drive reward-fund with Idempotency-Key ddr-comp-{dispute.id}"
        )
        logger.error(
            f"[DisputeComp] dispute #{dispute.id}: slash landed, payout FAILED -- "
            f"{actual_amount} AVT parked in treasury (re-drive key ddr-comp-{dispute.id})"
        )
        return compensation_result

    logger.info(
        f"Local compensation complete via TEG rails: {actual_amount} AVT from "
        f"{dispute.defendant_did} to {dispute.complainant_did} "
        f"(dispute #{dispute.id}, tx: {comp_tx_id})"
    )

    # Audit-trail event (projection-inert custom type -- the balance movement is
    # already recorded by the TEG outbox legs).
    try:
        await event_emitter.emit(
            event_type="DisputeCompensationApplied",
            aggregate_id=f"dispute:{dispute.id}",
            aggregate_type="Dispute",
            data={
                "dispute_id": dispute.id,
                "amount": str(actual_amount),
                "from_did": dispute.defendant_did,
                "to_did": dispute.complainant_did,
                "ruling": ruling,
                "comp_transaction_id": comp_tx_id,
                "rails": "teg:treasury-receive+reward-fund",
            },
        )
        compensation_result["event_emitted"] = True
    except Exception as e:
        logger.error(f"Error emitting compensation audit event for dispute #{dispute.id}: {e}")
        compensation_result["event_emitted"] = False

    if compensation_result["partial"] and compensation_result["deferred_amount"] > 0:
        try:
            # D15: normalize aggregate_id="dispute:N", aggregate_type="Dispute"
            await event_emitter.emit(
                event_type="DisputeCompensationDeferred",
                aggregate_id=f"dispute:{dispute.id}",
                aggregate_type="Dispute",
                data={
                    "dispute_id": dispute.id,
                    "deferred_amount": compensation_result["deferred_amount"],
                    "paid_amount": actual_amount,
                    "total_owed": disputed_amount,
                    "creditor_did": dispute.complainant_did,
                    "debtor_did": dispute.defendant_did
                }
            )
        except Exception as e:
            logger.error(f"Failed to emit deferred compensation event: {e}")

    return compensation_result


async def _process_cross_registry_compensation(
    db: AsyncSession,
    dispute: Dispute,
    ruling: str,
    disputed_amount: int,
    compensation_result: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Cross-registry compensation: sovereign settlement protocol.
    
    Defendant is NOT in local registry → we have NO jurisdiction over their AVT.
    Instead of ghost transfer, we:
    1. Emit DisputeCompensationRequest (informational, no balance effect)
    2. Create a CrossRegistrySettlement record
    3. Look up defendant's home registry from PeerRegistry table
    4. Send slash request to defendant's home registry
    
    The defendant's registry auto-slashes, calls back, and we auto-mint.
    """
    from ..models import CrossRegistrySettlement, PeerRegistry
    
    compensation_result["cross_registry"] = True
    compensation_result["amount"] = disputed_amount
    
    event_emitter = get_event_emitter()
    # OWL25 named the origin by FEDERATION_BASE_URL, the stack's internal proxy, which no peer knows: every slash
    # request was refused (§MCPTEST30 V0639). core/settlement_origin names the address the card publishes when
    # CROSS_REGISTRY_SETTLEMENT_DELIVERY is on, the internal one otherwise.
    from ..core import settlement_origin
    origin_registry_url = settlement_origin.origin_url()
    
    # Step 1: Emit DisputeCompensationRequest (no balance effect — public record only)
    try:
        await event_emitter.emit_dispute_compensation_request(
            dispute_id=dispute.id,
            complainant_did=dispute.complainant_did,
            defendant_did=dispute.defendant_did,
            amount=disputed_amount,
            origin_registry_url=origin_registry_url,
            ruling=ruling
        )
        compensation_result["event_emitted"] = True
        logger.info(
            f"Emitted DisputeCompensationRequest for dispute #{dispute.id}: "
            f"{disputed_amount} AVT (cross-registry, no balance effect)"
        )
    except Exception as e:
        logger.error(f"Failed to emit DisputeCompensationRequest: {e}")
    
    # Step 2: Create settlement record
    settlement_id = str(uuid.uuid4())
    settlement = CrossRegistrySettlement(
        id=settlement_id,
        dispute_id=dispute.id,
        origin_registry_url=origin_registry_url,
        defendant_registry_url="",  # Will be filled when we find the peer
        complainant_did=dispute.complainant_did,
        defendant_did=dispute.defendant_did,
        requested_amount=disputed_amount,
        slashed_amount=0,
        minted_amount=0,
        status="PENDING_SLASH",
        ruling=ruling,
        # S2 (2026-05-06): evidence_hash column dropped via migration 0030.
        callback_url=f"{origin_registry_url}/api/v1/federation/disputes/slash-confirmation"
    )
    db.add(settlement)
    await db.commit()
    await db.refresh(settlement)
    
    logger.info(f"Created CrossRegistrySettlement {settlement_id} for dispute #{dispute.id}")
    
    # Step 3: Build list of peer mTLS URLs from PeerRegistry (populated by federation sync)
    from ..identity import svid_client
    
    peer_result = await db.execute(
        select(PeerRegistry).where(PeerRegistry.status == "ACTIVE")
    )
    peers = list(peer_result.scalars().all())
    peer_targets = [(peer.name, peer.base_url.rstrip('/'), peer.federation_access_token) for peer in peers]
    
    logger.info(f"Peer targets for slash request (mTLS): {[(n, u) for n, u, _ in peer_targets]}")
    
    # Build mTLS client config (same pattern as federation_sync.py)
    client_config = {'timeout': 15.0}
    if peer_targets and peer_targets[0][1].startswith('https://'):
        cert_config = svid_client.get_client_cert_config()
        if cert_config:
            client_config.update(cert_config)
            logger.info("Using mTLS certificates for slash request")
        else:
            logger.error("mTLS client certs not available — cannot send secure slash request")
    
    # Step 4: Send slash request to each peer via mTLS
    slash_sent = False
    answers: list = []          # each peer's answer, kept on the settlement if none takes it (settlement_origin)
    for peer_name, peer_url, peer_token in peer_targets:
        slash_endpoint = f"{peer_url}/api/v1/federation/disputes/slash-request"
        # The registry asked is recorded BEFORE the request goes out: the defendant's home calls the confirmation back
        # while it is still answering, and a confirmation is accepted only from the registry recorded here
        # (routers/federation_disputes._bind_confirmation_to_caller).
        settlement.defendant_registry_url = peer_url
        await db.commit()
        
        payload = {
            "settlement_id": settlement_id,
            "dispute_id": dispute.id,
            "ruling": ruling,
            "amount": disputed_amount,
            "complainant_did": dispute.complainant_did,
            "defendant_did": dispute.defendant_did,
            "origin_registry_url": origin_registry_url,
            "callback_url": settlement.callback_url
        }
        
        try:
            async with httpx.AsyncClient(**client_config) as client:
                resp = await client.post(
                    slash_endpoint,
                    json=payload,
                    headers={"Content-Type": "application/json"}
                )
                if resp.status_code in (200, 201, 202):
                    resp_data = resp.json()
                    settlement.defendant_registry_url = peer_url
                    await db.commit()
                    slash_sent = True
                    logger.info(
                        f"Slash request sent via mTLS to {peer_name} ({peer_url}) "
                        f"for dispute #{dispute.id}: {resp_data}"
                    )
                    break
                elif resp.status_code == 409 and "already received" in resp.text:
                    # §MCPTEST30 V0639: the home claimed this settlement id already (a delivery whose answer was
                    # lost): it holds the request, so it is the registry a confirmation may come from
                    settlement.defendant_registry_url = peer_url
                    await db.commit()
                    slash_sent = True
                    logger.info(f"Slash request already held by {peer_name} ({peer_url}) for dispute #{dispute.id}")
                    break
                elif resp.status_code == 404:
                    logger.debug(f"Defendant not on {peer_name}, trying next peer")
                    answers.append(settlement_origin.peer_answer(peer_name, 404))
                    continue
                else:
                    logger.warning(
                        f"Slash request to {peer_name} returned {resp.status_code}: {resp.text[:200]}"
                    )
                    answers.append(settlement_origin.peer_answer(peer_name, resp.status_code, resp.text))
        except Exception as e:
            logger.warning(f"Failed to send slash request to {peer_name}: {e}")
            answers.append(f"{peer_name}: {type(e).__name__}")
            continue
    
    if slash_sent:
        compensation_result["settlement_status"] = "pending_remote_slash"
        compensation_result["settlement_id"] = settlement_id
        compensation_result["reason"] = (
            "Cross-registry: slash request sent to defendant's home registry. "
            "Auto-mint will occur when slash is confirmed."
        )
    else:
        settlement.status = "PENDING_SLASH"  # Will be picked up by periodic check
        settlement.error_message = "Could not reach defendant's home registry" + (
            f": {settlement_origin.answers_note(answers)}" if answers else "")
        settlement.defendant_registry_url = ""   # no registry took the request: none may confirm it
        await db.commit()
        compensation_result["settlement_status"] = "pending_remote_slash"
        compensation_result["settlement_id"] = settlement_id
        compensation_result["reason"] = (
            "Cross-registry: slash request could not be delivered. "
            "Settlement will be retried by periodic reconciliation."
        )
        logger.warning(
            f"Could not deliver slash request for dispute #{dispute.id}. "
            f"Settlement {settlement_id} will await periodic reconciliation."
        )
    
    return compensation_result
