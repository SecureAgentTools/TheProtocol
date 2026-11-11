"""
OWL25 Phase 2: Settlement Reconciliation Background Task
=========================================================
Periodic task that:
1. Checks PENDING_SLASH settlements against EventStore for DisputeSlash events
   → pays the complainant from the payout funding if slash evidence is found but the callback was lost (a transfer,
     never an issuance: _compensate_from_slash_evidence)
2. Expires settlements that have been PENDING_SLASH for >24h
3. Retries failed slash requests for PENDING_SLASH settlements (up to 3 attempts). V0660 (k): a retry every peer
   refuses (a 4xx other than 408, 425 or 429) ends the settlement as REFUSED; with CROSS_REGISTRY_SETTLEMENT_DELIVERY
   now off (or no dialable address) nothing is sent and a settlement no peer holds ends as NOT_DELIVERED, retries
   spent or not (core/settlement_origin); nothing goes to an https peer without this registry's client certificate

Runs every 60 seconds via asyncio background task started at app startup.
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import httpx
from ..es_ssl_helper import get_httpx_verify
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry.database import AsyncSessionLocal
from agentvault_registry.models import CrossRegistrySettlement, PeerRegistry
from agentvault_registry.config import settings
from agentvault_registry.identity import svid_client

logger = logging.getLogger(__name__)

# Configuration
RECONCILIATION_INTERVAL_SECONDS = 60
SETTLEMENT_EXPIRY_HOURS = 24
MAX_RETRY_ATTEMPTS = 3

# V0660 (k), session-lead's seq 2452: what _reconcile_single_settlement answers for a settlement it could not verify (the
# event store did not answer): nothing about it was decided this round. "Could not verify" is not "nothing found".
UNVERIFIED = "unverified"
_unverified_last_round = 0     # the round's count, so an outage warns once (when it starts or changes), not every cycle


async def reconcile_pending_settlements():
    """
    Main reconciliation loop. Checks all PENDING_SLASH settlements.
    
    For each:
    0. The EventStore is read first; a store that does not answer decides nothing this round (counted, said once)
    1. If older than SETTLEMENT_EXPIRY_HOURS → mark EXPIRED
    2. If DisputeSlash event found on EventStore → pay from the payout funding (lost callback recovery; never a mint)
    3. If not expired and no slash found → retry slash request (up to MAX_RETRY_ATTEMPTS)
    """
    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(
                select(CrossRegistrySettlement).where(
                    CrossRegistrySettlement.status.in_(["PENDING_SLASH", "SLASHING"])
                )
            )
            pending = list(result.scalars().all())
            
            if not pending:
                return {"pending": 0, "failed": 0}
            
            logger.info(f"Settlement reconciliation: {len(pending)} pending settlements")
            
            failed, unverified, why = 0, 0, ""
            for settlement in pending:
                try:
                    if await _reconcile_single_settlement(db, settlement) == UNVERIFIED:
                        unverified += 1
                        why = why or getattr(settlement, "_unverified_reason", "")
                except Exception as e:
                    # A per-ITEM failure is not a cycle failure. Counted and
                    # returned so the §VITALS stamp can carry it, not swallowed.
                    failed += 1
                    logger.error(
                        f"Error reconciling settlement {settlement.id}: {e}",
                        exc_info=True
                    )
            _say_unverified(unverified, why)
            return {"pending": len(pending), "failed": failed, "unverified": unverified}

        except Exception as e:
            # §VITALS: the WHOLE cycle failed (the query, the session). Re-raised so
            # the cycle stamps `error`; the caller's own except still logs and the
            # loop still continues, so behaviour is unchanged. Swallowing here is
            # what let velocity_snapshot report a dead EventStore as a quiet hour.
            logger.error(f"Settlement reconciliation failed: {e}", exc_info=True)
            raise


def _say_unverified(count: int, why: str) -> None:
    """V0660 (k): the round's settlements that were not decided because the event store did not answer, said once: a
    WARNING when an outage starts or its count changes, DEBUG while it stands, INFO when the store answers again."""
    global _unverified_last_round
    if count and count != _unverified_last_round:
        logger.warning(f"Settlement reconciliation: {count} settlement(s) not decided this round: the event store could "
                       f"not be read ({why or 'no answer'}). Nothing was changed; they are checked again next round.")
    elif count:
        logger.debug(f"Settlement reconciliation: still {count} settlement(s) waiting for the event store")
    elif _unverified_last_round:
        logger.info("Settlement reconciliation: the event store answers again; every pending settlement was checked")
    _unverified_last_round = count


async def _reconcile_single_settlement(db: AsyncSession, settlement: CrossRegistrySettlement):
    """Reconcile a single pending settlement.

    V0660 (k), session-lead's seq 2452: the event store is read FIRST, and a store that does not answer decides
    nothing: no expiry, no NOT_DELIVERED, no retry, no write. The settlement waits for a round whose read answered, and
    the answer is UNVERIFIED for the round's count. Then the checks run in their order, on the read that answered."""
    try:
        slash_found = await _check_eventstore_for_slash(settlement)
    except EventStoreUnreadable as e:
        try:
            settlement._unverified_reason = str(e)
        except Exception:   # a row object that takes no attribute still counts
            pass
        logger.debug(f"Settlement {settlement.id}: not decided this round, the event store could not be read ({e})")
        return UNVERIFIED

    age = datetime.now(timezone.utc) - (settlement.requested_at or datetime.now(timezone.utc))
    
    # Check 1: Expiry
    if age > timedelta(hours=SETTLEMENT_EXPIRY_HOURS):
        settlement.status = "EXPIRED"
        settlement.error_message = (
            f"Settlement expired after {SETTLEMENT_EXPIRY_HOURS}h without slash confirmation. "
            f"Age: {age}. Admin review required."
        )
        await db.commit()
        logger.warning(
            f"Settlement {settlement.id} EXPIRED for dispute #{settlement.dispute_id} "
            f"(age: {age})"
        )
        return
    
    # Check 2: the DisputeSlash read above (lost callback recovery)
    if slash_found:
        logger.info(
            f"Found DisputeSlash on EventStore for settlement {settlement.id} "
            f"— recovering from lost callback"
        )
        await _compensate_from_slash_evidence(db, settlement, slash_found)
        return
    
    # V0660 (k) review: where no request can go out now (CROSS_REGISTRY_SETTLEMENT_DELIVERY off, or no address a peer
    # can dial), a settlement no peer holds ends NOT_DELIVERED here, before the retry gate, so one whose retries are
    # spent ends too (it waited for its expiry before). One a home holds waits for that home's confirmation.
    from agentvault_registry.core import settlement_origin
    why = settlement_origin.why_not_delivered()
    if why and not (getattr(settlement, "defendant_registry_url", "") or "").strip():
        await _end_not_delivered(db, settlement, why)
        return

    # Check 3: Count retries via error_message field (no retry_count column)
    # Parse retry count from error_message or default to 0
    retry_count = 0
    if settlement.error_message and "retry_count=" in (settlement.error_message or ""):
        try:
            retry_count = int(settlement.error_message.split("retry_count=")[1].split(",")[0])
        except (ValueError, IndexError):
            pass
    
    if retry_count < MAX_RETRY_ATTEMPTS:
        logger.info(
            f"Retrying slash request for settlement {settlement.id} "
            f"(attempt {retry_count + 1}/{MAX_RETRY_ATTEMPTS})"
        )
        await _retry_slash_request(db, settlement, retry_count)
    elif "exhausted_at=" not in (settlement.error_message or ""):
        # §MCPTEST30 (V0640): said once, when the retries are first found spent (marked on the row); the settlement is
        # still checked every cycle, for EventStore evidence above and for expiry at SETTLEMENT_EXPIRY_HOURS, which
        # warns again. Every cycle warned before: one stuck settlement was a WARNING a minute for a day, and two
        # sandbox test settlements fired production's SettlementFailureRate as EU's (2026-10-24).
        settlement.error_message = f"{settlement.error_message}, exhausted_at={datetime.now(timezone.utc).isoformat()}"
        await db.commit()
        logger.warning(
            f"Settlement {settlement.id} exhausted {MAX_RETRY_ATTEMPTS} retry attempts. "
            f"Awaiting EventStore evidence or manual resolution."
        )
    else:
        logger.debug(f"Settlement {settlement.id}: retries spent, still awaiting EventStore evidence or resolution")


class EventStoreUnreadable(Exception):
    """The event store could not be asked (an answer other than 200, or no answer): whether a slash is recorded there
    is not known. Its text names the status or the exception's type, never a key or a body."""


async def _check_eventstore_for_slash(settlement: CrossRegistrySettlement) -> Optional[dict]:
    """The reconciliation's lost-callback check: find_slash_on_eventstore. V0660 (k), seq 2452: a store that cannot be
    read, or an answer the finder could not read, raises EventStoreUnreadable ("could not verify"), never None ("nothing
    found"): the caller decides nothing on it."""
    try:
        return await find_slash_on_eventstore(settlement)
    except EventStoreUnreadable:
        raise
    except Exception as e:
        raise EventStoreUnreadable(f"the event store's answer could not be read ({type(e).__name__})") from e


async def find_slash_on_eventstore(settlement: CrossRegistrySettlement) -> Optional[dict]:
    """
    Query EventStore for the DisputeSlash event of THIS settlement: the defendant registry's slash names the
    dispute (aggregate dispute:<id>, in this registry's numbering), the origin registry and the defendant.
    Returns the event data if found, None otherwise.

    D6-442 (2026-10-17): the match was the integer dispute_id alone, among the 50 newest DisputeSlash events of the
    whole store. Dispute ids are per registry, so another registry's slash of its own dispute with the same number
    paid this settlement's complainant from this registry's treasury, and on a busy store this settlement's own slash
    could fall outside the 50. The query now asks the dispute's aggregate, and the event must name this settlement's
    origin registry and defendant.

    V0660 (k) review: an event store that cannot be asked raises EventStoreUnreadable instead of reading as nothing
    found, so close_settlement (routers/federation_disputes) can refuse to close blind, and the reconciliation decides
    nothing on it (seq 2452). A settlement that records no origin finds nothing.
    """
    event_store_url = str(settings.EVENT_STORE_URL).rstrip('/')
    es_key = settings.EVENT_STORE_API_KEY
    origin = (settlement.origin_registry_url or "").rstrip("/")
    if not origin:
        return None

    url = (f"{event_store_url}/api/v1/events/aggregate/dispute:{int(settlement.dispute_id)}"
           f"?event_types=DisputeSlash&limit=50&sort_order=desc")

    try:
        async with httpx.AsyncClient(timeout=10.0, verify=get_httpx_verify()) as client:
            resp = await client.get(url, headers={"X-Internal-Key": es_key})
            if resp.status_code != 200:
                raise EventStoreUnreadable(f"the event store answered {resp.status_code}")
            events = resp.json()
    except EventStoreUnreadable:
        raise
    except Exception as e:
        raise EventStoreUnreadable(f"the event store could not be reached ({type(e).__name__})") from e

    if isinstance(events, dict):
        events = events.get("events", events.get("items", []))

    for event in events or []:
        data = event.get("data", {}) or {}
        if (data.get("dispute_id") == settlement.dispute_id
                and (data.get("origin_registry_url") or "").rstrip("/") == origin
                and data.get("defendant_did") == settlement.defendant_did):
            return {
                "event_id": event.get("id", ""),
                "amount": data.get("amount", 0),
                "slash_tx_id": data.get("slash_tx_id", ""),
                "defendant_did": data.get("defendant_did", ""),
            }
    return None


async def _compensate_from_slash_evidence(
    db: AsyncSession,
    settlement: CrossRegistrySettlement,
    slash_evidence: dict
):
    """Pay lost-callback compensation from the TREASURY. Never mints.

    §MONEY-R23 / D9 (2026-09-04). This used to POST the TEG's /admin/token/issue
    and then emit DisputeCompensationMinted, with `mint_tx_id` built from
    `uuid.uuid4()` — a NEW key every run. So the mint carried no idempotency at
    all: if anything after it failed (the balance write, the emit, the status
    update, the commit), the settlement stayed unsettled and the next
    reconciliation cycle minted the compensation AGAIN.

    ⚠ The old path did NOT breach Δ — DisputeCompensationMinted is classified
    `dispute_comp`, which materialized_balances.sql books into tokens_issued
    alongside the TEG's balance rise. Δ held. What was wrong is that a lost
    callback could create money, repeatedly, with no human and no dedup.

    Now it rides the existing waterfall mover (rule 14) with a DETERMINISTIC key
    `ddr-comp-{settlement.id}`, so a re-drive is a replay rather than a second
    payment, and the money comes from fee_collector/treasury instead of from
    nowhere.

    🔴 The emit had to change with it. A treasury transfer is Δ-NEUTRAL, so
    keeping DisputeCompensationMinted would have raised tokens_issued by the
    compensation while circulating stayed flat — turning a safe path into a real
    Δ breach. The waterfall emits TokensTransferred itself; this function emits
    nothing further.
    """
    slashed_amount = slash_evidence.get("amount", 0)
    if slashed_amount <= 0:
        logger.warning(f"Slash evidence has 0 amount for settlement {settlement.id}")
        return

    idem_key = f"ddr-comp-{settlement.id}"
    try:
        from agentvault_registry.routers.teg_integration import (
            TreasuryFundAgentRequest,
            _fund_agent_from_treasury_internal,
        )
        fund_req = TreasuryFundAgentRequest(
            target_agent_did=settlement.complainant_did,
            amount=str(slashed_amount),
            reason="dispute_compensation",
            reference_id=idem_key,
        )
        result = await _fund_agent_from_treasury_internal(
            db, fund_req,
            actor_label="settlement_reconciliation",
            idempotency_key=idem_key,
        )
    except Exception as e:
        # No fallback to minting: a treasury that cannot pay is an operator
        # decision, not a reason to create supply (D9). The settlement stays
        # unsettled and the next cycle retries, or it ages into admin review.
        logger.error(
            "[DDR-COMP] settlement %s: treasury compensation FAILED (%s) — NOT minting; "
            "settlement left unsettled for retry/admin review",
            settlement.id, e,
        )
        return

    comp_tx_id = ""
    if isinstance(result, dict):
        comp_tx_id = str(result.get("transaction_id") or "")

    settlement.status = "SETTLED"
    settlement.slashed_amount = slashed_amount
    settlement.minted_amount = slashed_amount   # column name is historical: paid, not minted
    settlement.mint_tx_id = comp_tx_id
    settlement.slash_tx_id = slash_evidence.get("slash_tx_id", "")
    settlement.settled_at = datetime.now(timezone.utc)
    settlement.error_message = "Settled via periodic reconciliation (lost callback recovery)"

    await db.commit()

    logger.info(
        "[DDR-COMP] settlement %s SETTLED via reconciliation: paid %s from treasury "
        "to %s (idem %s, tx %s) — no mint",
        settlement.id, slashed_amount, settlement.complainant_did, idem_key, comp_tx_id,
    )


async def _retry_slash_request(
    db: AsyncSession,
    settlement: CrossRegistrySettlement,
    retry_count: int
):
    """Retry sending a slash request to peer registries.

    V0660 (k), Guild order gwo_9230be3d156cc3ce58699aaf: where no request can go out now (CROSS_REGISTRY_SETTLEMENT_
    DELIVERY turned off, or no address a peer can dial) nothing is sent: a settlement no peer holds ends as
    NOT_DELIVERED, one a home holds waits for its confirmation (or its expiry). The registry asked is recorded before
    each request goes out, as the first send does (the home confirms while it is still answering). When every peer
    refuses (a 4xx) the settlement ends as REFUSED with each answer; a transport error or a 5xx keeps it for the next
    cycle."""
    from agentvault_registry.core import settlement_origin
    from agentvault_registry.crud.crud_disputes import record_registry_asked

    why = settlement_origin.why_not_delivered()
    if why:
        if (settlement.defendant_registry_url or "").strip():
            # a home holds the request: it may still slash and confirm, so the settlement waits; nothing is sent
            logger.info(f"Settlement {settlement.id}: not sent again ({why}); "
                        f"{settlement.defendant_registry_url} holds it")
            return
        await _end_not_delivered(db, settlement, why)
        return

    # Get active peers
    peer_result = await db.execute(
        select(PeerRegistry).where(PeerRegistry.status == "ACTIVE")
    )
    peers = list(peer_result.scalars().all())

    # V0660 (k) review: no request goes to an https peer without this registry's mTLS client certificate (it went out
    # without one); nothing is sent this cycle and no attempt is spent, since the peers were not asked
    cert_config = None
    if settlement_origin.needs_client_cert(p.base_url for p in peers):
        cert_config = svid_client.get_client_cert_config()
        if not cert_config:
            settlement.error_message = (
                f"retry_count={retry_count}, no_client_cert={datetime.now(timezone.utc).isoformat()}: not sent, "
                f"because {settlement_origin.NO_CLIENT_CERT}. Nothing has moved.")
            await db.commit()
            logger.error(f"Settlement {settlement.id}: slash request not sent again, "
                         f"{settlement_origin.NO_CLIENT_CERT}")
            return

    # Update retry count in error_message (no dedicated column)
    new_count = retry_count + 1
    settlement.error_message = f"retry_count={new_count}, last_retry={datetime.now(timezone.utc).isoformat()}"
    await db.commit()

    if not peers:
        logger.warning("No active peers for slash retry")
        return

    # §MCPTEST30 V0639: the retry names the origin its settlement recorded (the address its callback lies under), and a
    # settlement with none the address core/settlement_origin names now; it computed the internal proxy before.
    origin_url = ((settlement.origin_registry_url or "").rstrip('/') or settlement_origin.origin_url())
    client_config = {'timeout': 15.0}
    answers: list = []          # each peer's answer, kept on the settlement if none takes it (settlement_origin)
    may_pass = False            # a transport error or a 5xx: the next cycle sends it again
    held_before = (settlement.defendant_registry_url or "").strip()

    for peer in peers:
        peer_url = peer.base_url.rstrip('/')
        if peer_url.startswith('https://') and cert_config:
            client_config.update(cert_config)

        # V0660 (k): recorded before the request goes out, and only while the settlement still waits (a settlement a
        # home already holds keeps that home: it is the registry a confirmation comes from)
        if not held_before and not await record_registry_asked(db, settlement, peer_url):
            logger.info(f"Settlement {settlement.id} no longer waits (closed meanwhile); nothing more is sent")
            return

        slash_endpoint = f"{peer_url}/api/v1/federation/disputes/slash-request"
        payload = {
            "settlement_id": settlement.id,
            "dispute_id": settlement.dispute_id,
            "ruling": settlement.ruling,
            "amount": int(settlement.requested_amount),
            "complainant_did": settlement.complainant_did,
            "defendant_did": settlement.defendant_did,
            "origin_registry_url": origin_url,
            "callback_url": settlement.callback_url or (
                f"{origin_url}/api/v1/federation/disputes/slash-confirmation"
            )
        }

        try:
            async with httpx.AsyncClient(**client_config) as client:
                resp = await client.post(
                    slash_endpoint, json=payload,
                    headers={"Content-Type": "application/json"}
                )
                if resp.status_code in (200, 201, 202):
                    # V0660 (k) review: a settlement a home already holds keeps that home (the registry a confirmation
                    # is accepted from); another peer's answer never overwrites it
                    settlement.defendant_registry_url = held_before or peer_url
                    settlement.error_message = (
                        f"retry_count={new_count}, "
                        f"slash_sent={datetime.now(timezone.utc).isoformat()}"
                    )
                    await db.commit()
                    logger.info(f"Slash retry #{new_count} succeeded to {peer.name}")
                    return
                elif resp.status_code == 409 and "already received" in resp.text:
                    # §MCPTEST30 V0639: the home claimed this settlement id on an earlier delivery whose answer was
                    # lost (it slashes once: the claim comes before any money moves): delivered, never a failure.
                    # V0660 (k) review: the home that already holds it stays the one recorded
                    settlement.defendant_registry_url = held_before or peer_url
                    settlement.error_message = (
                        f"retry_count={new_count}, already_held={datetime.now(timezone.utc).isoformat()}"
                    )
                    await db.commit()
                    logger.info(f"Slash retry #{new_count}: {peer.name} already holds settlement {settlement.id}")
                    return
                elif resp.status_code == 404:
                    answers.append(settlement_origin.peer_answer(peer.name, 404))
                    continue
                else:
                    logger.warning(f"Slash retry to {peer.name}: {resp.status_code}")
                    answers.append(settlement_origin.peer_answer(peer.name, resp.status_code, resp.text))
                    may_pass = may_pass or not settlement_origin.is_definite_refusal(resp.status_code)
        except Exception as e:
            logger.warning(f"Slash retry to {peer.name} failed: {e}")
            answers.append(f"{peer.name}: {type(e).__name__}")
            may_pass = True

    # no peer took it this time: none may confirm it, unless a home held it before
    settlement.defendant_registry_url = held_before
    refused = False
    if answers:
        # §MCPTEST30 V0640: why no peer took it, beside the count the next cycle parses (retry_count= first)
        settlement.error_message = (f"{settlement.error_message}, refused: {settlement_origin.answers_note(answers)}")
        refused = not may_pass and not held_before
        if refused:
            # V0660 (k): every peer refused (a 4xx) and none holds it: sending again cannot change that
            settlement.status = settlement_origin.REFUSED
            settlement.error_message += ". Refused by every peer registry. Nothing moved."
            settlement.saga_state = "SLASH_FAILED"
            settlement.saga_last_step_at = datetime.now(timezone.utc)
    await db.commit()
    if refused:
        logger.warning(f"Settlement {settlement.id} REFUSED by every peer on retry #{new_count}")
    else:
        logger.warning(f"Slash retry #{new_count} failed for settlement {settlement.id}")


async def _end_not_delivered(db: AsyncSession, settlement: CrossRegistrySettlement, why: str) -> None:
    """A settlement no peer holds, where no request can go out now: it ends NOT_DELIVERED (V0660 (k))."""
    from agentvault_registry.core import settlement_origin
    settlement.status = settlement_origin.NOT_DELIVERED
    settlement.error_message = (f"Not delivered: {why} now, so the slash request was not sent again and no peer "
                                f"holds it. Nothing moved.")
    settlement.saga_state = "SLASH_FAILED"
    settlement.saga_last_step_at = datetime.now(timezone.utc)
    await db.commit()
    logger.warning(f"Settlement {settlement.id} NOT_DELIVERED: {why}")


async def settlement_reconciliation_loop():
    """Background task: runs reconciliation every RECONCILIATION_INTERVAL_SECONDS."""
    from agentvault_registry.background_tasks.leader import try_acquire_leadership
    logger.info(
        f"Settlement reconciliation task started "
        f"(interval: {RECONCILIATION_INTERVAL_SECONDS}s, "
        f"expiry: {SETTLEMENT_EXPIRY_HOURS}h, "
        f"max_retries: {MAX_RETRY_ATTEMPTS})"
    )

    # Initial delay to let the app fully start
    await asyncio.sleep(10)

    from agentvault_registry.background_tasks import vitals as _vitals
    await _vitals.register(
        "settlement_reconciliation", module=__name__, pattern="hand-rolled",
        interval_sec=RECONCILIATION_INTERVAL_SECONDS, enabled=True,
    )

    while True:
        try:
            if await try_acquire_leadership("settlement_reconciliation"):
                async with _vitals.cycle("settlement_reconciliation") as _ctx:
                    _stats = await reconcile_pending_settlements()
                    if _stats:
                        _ctx.note(**_stats)
        except Exception as e:
            logger.error(f"Reconciliation loop error: {e}", exc_info=True)

        await asyncio.sleep(RECONCILIATION_INTERVAL_SECONDS)
