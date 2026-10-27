"""
Webhook Service for AgentVault Registry
Handles webhook delivery, retries, and event emission integration
"""
import asyncio
import hashlib
import hmac
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any

import httpx
from sqlalchemy import and_, or_, select, type_coerce
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry.models import DeveloperWebhook, WebhookDelivery

logger = logging.getLogger(__name__)

# §DOCSFIX D6-786 (2026-10-17): ONE rule for the outcome of a delivery attempt, read by every list and count of deliveries
# (a developer's own list, the administrators' feed and its window counts). The three outcomes partition every row: a 2xx
# answer is a delivery ("success"); any other answer is a failed attempt ("failed"), a 3xx included, which is not followed
# and is retried like any other failure (D6-765); no answer ("pending") is an attempt in flight or one that got no
# response (a timeout or a connection failure; its error message says which). "failed" read only 4xx/5xx, so a 3xx row
# was in no outcome at all.
DELIVERY_OUTCOMES = ("success", "failed", "pending")


def delivery_outcome_clause(outcome: str):
    """The SQL condition on webhook_deliveries for one of DELIVERY_OUTCOMES."""
    status = WebhookDelivery.response_status
    if outcome == "success":
        return and_(status >= 200, status < 300)
    if outcome == "failed":
        return and_(status.isnot(None), or_(status < 200, status >= 300))
    if outcome == "pending":
        return status.is_(None)
    raise ValueError(f"unknown delivery outcome {outcome!r}")


class WebhookUrlRefused(RuntimeError):
    """The stored URL may not be called now: D6-760's checks, made at the moment of sending, refused it."""


class WebhookHostNotReachable(RuntimeError):
    """The URL's host resolves to no address right now: there is nothing to deliver to."""


async def post_to_checked_address(client: httpx.AsyncClient, url: str, body: bytes,
                                  headers: Dict[str, str]) -> httpx.Response:
    """D6-842 (2026-10-26): POST `body` to `url` through `client` the way a developer webhook is delivered (SEC-14): the
    URL is checked at the moment of sending and the request connects only to an address that check approved. For a
    sender that is not a developer webhook (the CI/CD deployment webhook), so that both keep ONE rule. Raises
    WebhookUrlRefused or WebhookHostNotReachable before anything is sent."""
    sender = WebhookService()
    sender.client = client
    return await sender._post_to_checked_address(url, body, headers)


class WebhookService:
    """
    Service for managing webhook deliveries and event emissions.
    
    This service handles:
    - Webhook event emission to subscribed endpoints
    - Payload signing for security
    - Delivery retry logic
    - Failure tracking and webhook disabling
    """
    
    # Event types that can trigger webhooks
    SUPPORTED_EVENTS = [
        # Agent events
        "agent.created",
        "agent.updated",
        "agent.deleted",
        "agent.status_changed",
        "agent.health_changed",
        "agent.mtls_revoked",
        "agent.mtls_enrolled",
        
        # Staking events
        "staking.position_created",
        "staking.position_updated",
        "staking.position_closed",
        "staking.rewards_claimed",

        # §TWOAGENT G3 (2026-09-23): money. Findings 6 and 24: nothing could tell a runtime it was paid.
        #   payment.received            a credit to one of your agents (any rail: transfer, A2A settlement, FX
        #                               pool, cross-frame), from this frame's own ledger, once per credit
        #   payment.settled             an A2A payment your agent authorized has been paid out to the seller
        #   payment.settlement_failed   ... and could not be (the seller delivered; the token is FAILED)
        "payment.received",
        "payment.settled",
        "payment.settlement_failed",
        
        # Governance events
        "governance.proposal_created",
        "governance.proposal_passed",
        "governance.proposal_failed",
        "governance.vote_cast",
        
        # Federation events
        "federation.peer_added",
        "federation.peer_removed",
        "federation.sync_completed",
        
        # Dispute events
        "dispute.created",
        "dispute.evidence_submitted",
        "dispute.resolved",
        
        # Contract events (legacy RUC names kept; spine names added P2 2026-07-25)
        "contract.created",
        "contract.accepted",
        "contract.completed",
        "contract.disputed",
        "contract.offered",
        "contract.agreed",
        "contract.milestone_submitted",
        "contract.milestone_released",
        "contract.cancelled",

        # Game events
        "game.invite",
        "game.started",

        # Treasury / supply audit events (Phase 5 reactor)
        "supply.invariant_breach",

        # Suspension lifecycle (Phase 6 — coordinated suspension)
        "agent.suspended",
        "agent.reinstated",
        "developer.suspended",
        "developer.reinstated",

        # Frame federation lifecycle (Phase 7 reactors)
        "frame_federation.revoked",

        # Operator lifecycle (A2, 2026-07-24): reactor_operator_application_revoked has
        # dispatched this since it shipped, but the string was missing here — subscriptions
        # were rejected and every dispatch dropped as unsupported.
        "operator.application_revoked",

        # Federation drift detection (Phase 7.1 reactor — IS_CENTRAL_REGISTRY-gated emitter)
        "federation.drift_detected",

        # Cross-frame compliance dry-run drift (Phase 9.1 reactor — compliance_poller emitter)
        "federation.dry_run_drift",

        # f037 emission policy invalidation (Phase 9.2 reactor)
        "federation.emission_policy_updated",

        # Reactor batch 2 (Phase 9.3) — operational + dispute + bridge + governance + treasury
        "webhook.retry_exhausted",
        "agent.slashed",
        "bridge.transfer_expired",
        "treasury.balance_corrected",

        # ZKP attestation maturation (Phase 2) — lifecycle
        "attestation.revoked",
        "attestation.expired",

        # ZKP attestation maturation (Phase 5) — periodic cron
        "attestation.due_reminder",

        # §OURSTATE-1 (2026-08-24) — a chat message reached an agent participant.
        # This is the whole third-party-runtime story for CORE: the delivery +
        # retry rail below is production-proven including agent-to-agent (the
        # Commander's own test); replies ride the dual-auth chat API.
        "chat.message.received",

        # §TWOAGENT #1 (2026-09-23) — a STRANGER's first message landed an AGENT's row in its Requests lane.
        # chat.message.received never fires for it (only ACTIVE participants are recipients), so a webhook-driven
        # runtime could not hear a knock at all and had to poll ?state=requests. Owner-scoped; consent-shaped: it
        # tells the owner who knocked and what they said, and accepts nothing.
        "chat.request.received",

        # §TWOAGENT #2 (2026-09-23) — the other half: the KNOCKER hears that its request was ACCEPTED (the run's
        # knocker polled its thread for minutes). Owner-scoped. A decline sends nothing, on purpose: a refusal the
        # knocker cannot see is the consent half of the Requests lane, like the absence of read receipts.
        "chat.request.accepted",

        # §TWOAGENT G3 (2026-09-23) — the DELEGATE's owner hears that its agent gained or lost delegated authority, local
        # (POST /agents/{did}/delegations) or cross-registry (a credential shipped from the issuer's home). Before this, an
        # agent could be handed another principal's authority, or lose it, with no signal to anyone who runs it.
        # Owner-scoped; `scope` says local or cross_registry.
        "delegation.received",
        "delegation.revoked",

        # §TWOAGENT G3 (2026-09-23) — the Guild, for agent RUNTIMES (the §NOTIFV2 push already reached phones): the
        # poster's owner hears of a bid and a delivery, the worker's owner of the award and the verdict. A worker on
        # another frame hears through its HOME (the host sends POST /federation/guild/notice). Owner-scoped.
        "guild.bid_received",
        "guild.awarded",
        "guild.work_submitted",
        "guild.verified",
    ]
    
    # Retry configuration
    MAX_RETRIES = 5
    RETRY_DELAYS = [
        timedelta(minutes=1),    # 1st retry after 1 minute
        timedelta(minutes=5),    # 2nd retry after 5 minutes
        timedelta(minutes=15),   # 3rd retry after 15 minutes
        timedelta(hours=1),      # 4th retry after 1 hour
        timedelta(hours=6),      # 5th retry after 6 hours
    ]
    
    # Maximum consecutive failures before disabling webhook
    MAX_CONSECUTIVE_FAILURES = 10
    
    def __init__(self):
        """Initialize the webhook service"""
        self.client = None
        
    async def __aenter__(self):
        """Async context manager entry"""
        self.client = httpx.AsyncClient(timeout=10.0)
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.client:
            await self.client.aclose()
    
    async def emit_event(
        self,
        event_type: str,
        data: Dict[str, Any],
        db: AsyncSession,
        agent_did: Optional[str] = None,
        developer_id: Optional[int] = None
    ) -> int:
        """
        Emit a webhook event to all subscribed webhooks.
        
        Args:
            event_type: The type of event (e.g., "agent.created")
            data: The event payload data
            db: Database session
            agent_did: Optional agent DID that triggered the event
            developer_id: Optional developer ID to limit webhooks to
            
        Returns:
            Number of webhooks that were triggered
        """
        if event_type not in self.SUPPORTED_EVENTS:
            logger.warning(f"Unsupported event type: {event_type}")
            return 0
        # §DOCSFIX D6-762 (2026-10-16): the envelope's agent_did names the agent the event is about. No dispatch passed
        # it, so it read null on every event; an event about one agent carries it as data.agent_did.
        if agent_did is None and isinstance(data, dict) and isinstance(data.get("agent_did"), str):
            agent_did = data["agent_did"]
        
        # Build query for active webhooks subscribed to this event
        stmt = select(DeveloperWebhook).where(
            DeveloperWebhook.is_active == True,
            type_coerce(DeveloperWebhook.events, JSONB).contains([event_type])
        )
        
        # Optionally filter by developer
        if developer_id:
            stmt = stmt.where(DeveloperWebhook.developer_id == developer_id)
        
        result = await db.execute(stmt)
        webhooks = result.scalars().all()
        
        if not webhooks:
            logger.debug(f"No active webhooks found for event {event_type}")
            return 0
        
        logger.info(f"Emitting event {event_type} to {len(webhooks)} webhooks")
        
        # Deliver to each webhook asynchronously. §TWOAGENT (2026-09-23): the POSTs run concurrently, but every task
        # writes its delivery row into the ONE session this call was given, and an AsyncSession cannot run two
        # operations at once. Two subscribers meant two overlapping add+commit sequences: measured on the V0437
        # sandbox, one developer with two hooks on one event got BOTH deliveries sent and NEITHER recorded (0 and 0;
        # the control with one hook recorded 1), with no error anywhere, because gather(return_exceptions=True)
        # swallowed the refusal. A lost row is a lost retry too (next_retry_at lives on it). The record step is now
        # serialized; the network step stays concurrent.
        db_lock = asyncio.Lock()
        tasks = []
        for webhook in webhooks:
            task = asyncio.create_task(
                self.deliver_webhook(webhook, event_type, data, agent_did, db, db_lock=db_lock)
            )
            tasks.append(task)
        
        # Wait for all deliveries to complete; a delivery that failed to RECORD is said out loud, never swallowed.
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for webhook, res in zip(webhooks, results):
            if isinstance(res, BaseException):
                logger.error(f"Webhook {webhook.id}: delivery for {event_type} was not recorded: "
                             f"{type(res).__name__}: {res}")
        
        return len(webhooks)
    
    async def deliver_webhook(
        self,
        webhook: DeveloperWebhook,
        event_type: str,
        data: Dict[str, Any],
        agent_did: Optional[str],
        db: AsyncSession,
        *,
        db_lock: Optional[asyncio.Lock] = None,
    ) -> WebhookDelivery:
        """
        Deliver a webhook payload to a specific endpoint.
        
        Args:
            webhook: The webhook configuration
            event_type: The event type
            data: The event data
            agent_did: Optional agent DID
            db: Database session
            
        Returns:
            The webhook delivery record
        """
        # Create delivery record
        # NOTE: retry_count must be set explicitly here because the SQLAlchemy
        # column default (0) only applies on DB flush/commit — in-memory it's None.
        delivery = WebhookDelivery(
            id=str(uuid.uuid4()),
            webhook_id=webhook.id,
            event_type=event_type,
            payload=data,
            delivered_at=datetime.now(timezone.utc),
            retry_count=0,
        )
        
        # Prepare full payload
        payload = {
            "id": delivery.id,
            "event": event_type,
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent_did": agent_did
        }
        # §TWOAGENT #33 (2026-09-23): the row keeps the envelope AS SENT (the column's own contract: "the JSON payload
        # that was/will be sent"), so a retry can resend this exact delivery — same id, same agent_did. It held only
        # `data`, and the only retry path that ran minted a fresh delivery instead.
        delivery.payload = payload

        # Sign the payload — and send EXACTLY the signed bytes. §TWOAGENT #4 (2026-09-23): the signature was over
        # json.dumps(payload, sort_keys=True) while the body went out as httpx's json.dumps(payload) in insertion
        # order, so the raw body a receiver holds was never what was signed: only a receiver that re-serialised
        # the parsed JSON with Python's exact defaults could verify (measured on EU and ASIA: documented recipe
        # 9/9, raw-body HMAC 0/9). Sending the signed string makes BOTH recipes verify, and nothing that verifies
        # today stops verifying (re-serialising sorted JSON of these bytes yields these bytes).
        signed_body = json.dumps(payload, sort_keys=True)
        signature = self._sign_payload(signed_body, webhook.secret)
        
        # Prepare headers
        headers = {
            "Content-Type": "application/json",
            "X-TheProtocol-Signature": signature,
            "X-TheProtocol-Event": event_type,
            "X-TheProtocol-Delivery-ID": delivery.id,
            "User-Agent": "TheProtocol-Webhook/1.0"
        }
        
        # Attempt delivery
        try:
            response = await self._post_to_checked_address(webhook.url, signed_body.encode("utf-8"), headers)
            
            delivery.response_status = response.status_code
            # Store first 5000 chars of response
            delivery.response_body = response.text[:5000] if response.text else None
            
            if response.status_code >= 200 and response.status_code < 300:
                # Success
                logger.info(f"Webhook delivered successfully to {webhook.url}")
                webhook.last_triggered_at = datetime.now(timezone.utc)
                webhook.failure_count = 0  # Reset failure count on success
            else:
                # HTTP error
                logger.warning(
                    f"Webhook delivery failed with status {response.status_code} to {webhook.url}"
                )
                webhook.failure_count += 1
                
                # Schedule retry if under retry limit
                if delivery.retry_count < self.MAX_RETRIES:
                    delivery.next_retry_at = datetime.now(timezone.utc) + self.RETRY_DELAYS[delivery.retry_count]
                    
        except httpx.TimeoutException:
            logger.error(f"Webhook delivery timeout to {webhook.url}")
            delivery.error_message = "Request timeout"
            webhook.failure_count += 1
            
            # Schedule retry
            if delivery.retry_count < self.MAX_RETRIES:
                delivery.next_retry_at = datetime.now(timezone.utc) + self.RETRY_DELAYS[delivery.retry_count]
                
        except Exception as e:
            logger.error(f"Webhook delivery error to {webhook.url}: {str(e)}")
            delivery.error_message = str(e)[:1000]  # Store first 1000 chars
            webhook.failure_count += 1
            
            # Schedule retry
            if delivery.retry_count < self.MAX_RETRIES:
                delivery.next_retry_at = datetime.now(timezone.utc) + self.RETRY_DELAYS[delivery.retry_count]
        
        # Disable webhook if too many consecutive failures
        if webhook.failure_count >= self.MAX_CONSECUTIVE_FAILURES and webhook.is_active:
            logger.warning(
                f"Disabling webhook {webhook.id} after {webhook.failure_count} consecutive failures"
            )
            webhook.is_active = False
            await self._emit_retry_exhausted(webhook, delivery)

        # Save delivery record and update webhook. Under a fan-out (`emit_event`) every task shares one session, so
        # the write is serialized by the caller's lock; a single delivery (test, redeliver, admin) passes none.
        if db_lock is None:
            db.add(delivery)
            await db.commit()
        else:
            async with db_lock:
                db.add(delivery)
                await db.commit()

        return delivery
    
    @staticmethod
    def stored_envelope(delivery: WebhookDelivery) -> Dict[str, Any]:
        """The envelope a delivery was first sent with (id, event, data, timestamp, agent_did).

        Rows written since V0429 store it whole; older rows stored only the event's `data`, so their envelope is
        rebuilt around it with the same id (their `agent_did` was never kept and reads null).
        """
        p = delivery.payload if isinstance(delivery.payload, dict) else {}
        if p.get("id") == delivery.id and "event" in p and "data" in p:
            return {k: p.get(k) for k in ("id", "event", "data", "timestamp", "agent_did")}
        ts = delivery.delivered_at.isoformat() if delivery.delivered_at else None
        return {"id": delivery.id, "event": delivery.event_type, "data": p, "timestamp": ts, "agent_did": None}

    # SEC-14: how many of the checked addresses one send tries, in the resolver's order, when connecting fails
    PINNED_ADDRESSES_TRIED = 4

    async def _post_to_checked_address(self, url: str, body: bytes, headers: Dict[str, str]) -> httpx.Response:
        """POST `body` to the stored webhook URL, connecting only to an address checked for this very send.

        D6-760: the stored URL is resolved at the moment of sending and refused when any address it resolves to is
        internal, so a URL stored before the check existed, or a name whose address has changed since, is never called.
        SEC-14 (2026-10-17): and the send then connects to one of the addresses that check approved. It used to hand
        the URL to the HTTP client, which looked the name up again, so a name answering differently the second time
        reached an address nobody checked. The request still names the webhook's host: its Host header and, for https,
        the TLS server name (so the certificate is verified for that name), and it asks for the connection to be
        closed after the answer, so no other webhook sharing the address reuses a connection made for this name. When
        connecting to an address fails (nothing was sent), the next checked address is tried. A refusal, or a host
        that resolves to nothing, is raised inside the delivery's try and recorded as that delivery's error like any
        failed send."""
        from agentvault_registry.input_validators import WebhookHostUnresolved, awebhook_target_addresses
        try:
            addresses = await awebhook_target_addresses(url)
        except WebhookHostUnresolved as e:
            raise WebhookHostNotReachable(f"Webhook host not reachable: {e}")
        except ValueError as e:
            raise WebhookUrlRefused(f"Webhook URL refused: {e}")
        if not self.client:
            self.client = httpx.AsyncClient(timeout=10.0)
        if not addresses:   # the host is written as an address, checked above: connected to as written
            return await self.client.post(url, content=body, headers=headers)
        target = httpx.URL(url)
        pinned = {**headers, "Host": target.netloc.decode("ascii"), "Connection": "close"}
        extensions = {"sni_hostname": target.raw_host.decode("ascii")} if target.scheme == "https" else {}
        failure: Optional[Exception] = None
        for address in addresses[:self.PINNED_ADDRESSES_TRIED]:
            try:
                return await self.client.post(str(target.copy_with(host=address)), content=body, headers=pinned,
                                              extensions=extensions)
            except (httpx.ConnectError, httpx.ConnectTimeout) as e:   # nothing reached this address: try the next
                failure = e
        raise failure

    async def retry_delivery(
        self,
        delivery: WebhookDelivery,
        webhook: DeveloperWebhook,
        db: AsyncSession,
    ) -> WebhookDelivery:
        """Retry ONE failed delivery IN PLACE: the same delivery id, the same envelope, `X-TheProtocol-Retry: n`.

        §TWOAGENT #33 (2026-09-23): the retry worker re-sent a failed delivery through `deliver_webhook`, which mints a
        NEW delivery (new id, no retry header, agent_did null) and never touched the original row. The original stayed
        eligible (retry_count 0, next_retry_at past, a 4xx/5xx status), so once the endpoint recovered the same event
        arrived every worker cycle, each copy under a fresh delivery id that the documented dedup cannot catch
        (measured on sbx-alpha: one 404, then three copies in three minutes until the webhook was deactivated). The
        original row now carries the attempt: retry_count, the latest status, and the next slot or none.
        """
        delivery.retry_count = (delivery.retry_count or 0) + 1
        envelope = self.stored_envelope(delivery)
        payload = {
            **envelope,
            "retry_count": delivery.retry_count,
            "original_timestamp": envelope.get("timestamp"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        # Sign the payload and send exactly the signed bytes (§TWOAGENT #4, as on first delivery)
        signed_body = json.dumps(payload, sort_keys=True)
        headers = {
            "Content-Type": "application/json",
            "X-TheProtocol-Signature": self._sign_payload(signed_body, webhook.secret),
            "X-TheProtocol-Event": delivery.event_type,
            "X-TheProtocol-Delivery-ID": delivery.id,
            "X-TheProtocol-Retry": str(delivery.retry_count),
            "User-Agent": "TheProtocol-Webhook/1.0",
        }
        ok = False
        try:
            response = await self._post_to_checked_address(webhook.url, signed_body.encode("utf-8"), headers)
            delivery.response_status = response.status_code
            delivery.response_body = response.text[:5000] if response.text else None
            delivery.error_message = None
            ok = 200 <= response.status_code < 300
        except httpx.TimeoutException:
            logger.error(f"Webhook retry timeout to {webhook.url}")
            delivery.response_status = None
            delivery.error_message = "Request timeout"
        except Exception as e:
            logger.error(f"Webhook retry error to {webhook.url}: {str(e)}")
            delivery.response_status = None
            delivery.error_message = str(e)[:1000]

        if ok:
            delivery.next_retry_at = None
            webhook.last_triggered_at = datetime.now(timezone.utc)
            webhook.failure_count = 0
            logger.info(f"Webhook retry {delivery.retry_count} delivered to {webhook.url}")
        else:
            webhook.failure_count = (webhook.failure_count or 0) + 1
            delivery.next_retry_at = (
                datetime.now(timezone.utc) + self.RETRY_DELAYS[delivery.retry_count]
                if delivery.retry_count < self.MAX_RETRIES else None
            )
            if webhook.failure_count >= self.MAX_CONSECUTIVE_FAILURES and webhook.is_active:
                logger.warning(
                    f"Disabling webhook {webhook.id} after {webhook.failure_count} consecutive failures"
                )
                webhook.is_active = False
                await self._emit_retry_exhausted(webhook, delivery)

        db.add(delivery)
        await db.commit()
        return delivery

    async def _emit_retry_exhausted(
        self,
        webhook: DeveloperWebhook,
        delivery: WebhookDelivery,
    ) -> None:
        """Emit WebhookRetryExhausted to EventStore on the active→disabled transition.

        Fires exactly once per webhook (caller guards with `webhook.is_active`).
        Reactor #14 consumes this and fans out to other developer webhooks +
        sends a sovereign-themed email to the developer.
        """
        try:
            from agentvault_registry.event_emitter import get_event_emitter
            emitter = get_event_emitter()
            last_error = (
                delivery.error_message
                or (f"HTTP {delivery.response_status}" if delivery.response_status else "unknown")
            )
            emitter.emit_background(
                event_type="WebhookRetryExhausted",
                aggregate_id=f"webhook:{webhook.id}",
                aggregate_type="Webhook",
                data={
                    "webhook_id": webhook.id,
                    "developer_id": webhook.developer_id,
                    "target_url": webhook.url,
                    "consecutive_failures": webhook.failure_count,
                    "last_error": last_error,
                    "last_response_code": delivery.response_status,
                    "disabled_at": datetime.now(timezone.utc).isoformat(),
                },
                # §DOCSFIX D6-764 (2026-10-16): one key per disable, from the attempt that tipped it (the caller fires once
                # per active->disabled transition). `webhook_exhausted:<webhook id>` alone is unique forever in the
                # event store, so a webhook re-enabled and disabled again was never announced again.
                idempotency_key=f"webhook_exhausted:{webhook.id}:{delivery.id}:{delivery.retry_count or 0}",
            )
        except Exception as e:
            logger.warning(f"Failed to emit WebhookRetryExhausted for {webhook.id}: {e}")

    def _sign_payload(self, payload: str, secret: str) -> str:
        """
        Sign a webhook payload using HMAC-SHA256.
        
        Args:
            payload: The JSON payload as a string
            secret: The webhook secret
            
        Returns:
            The hex-encoded signature
        """
        return hmac.new(
            secret.encode(),
            payload.encode(),
            hashlib.sha256
        ).hexdigest()
    
    @staticmethod
    def verify_signature(payload: str, signature: str, secret: str) -> bool:
        """
        Verify a webhook signature.
        
        Args:
            payload: The received payload
            signature: The signature to verify
            secret: The webhook secret
            
        Returns:
            True if signature is valid, False otherwise
        """
        expected_sig = hmac.new(
            secret.encode(),
            payload.encode(),
            hashlib.sha256
        ).hexdigest()
        
        # Use constant-time comparison to prevent timing attacks
        return hmac.compare_digest(expected_sig, signature)


# Global webhook service instance
webhook_service = WebhookService()


# Event emission helper functions
async def _local_owner_id(db: AsyncSession, agent_did: str) -> Optional[int]:
    """The developer that owns `agent_did` on THIS registry, or None (a foreign or unknown agent)."""
    from sqlalchemy import text as _text
    row = (await db.execute(_text(
        "SELECT creator_developer_id FROM agents WHERE did = :d AND creator_developer_id IS NOT NULL LIMIT 1"
    ), {"d": agent_did})).first()
    return int(row[0]) if row else None


async def emit_agent_event(
    event_type: str,
    agent_did: str,
    data: Dict[str, Any],
    db: AsyncSession,
    developer_id: Optional[int] = None
):
    """Helper function to emit agent-related events, to the agent's OWN developer.

    §TWOAGENT #34 class (2026-09-23): emit_event's agent_did does not filter subscribers, so without a developer id
    this reached every subscriber on the frame. With no local owner there is nobody to tell.
    """
    full_data = {
        "agent_did": agent_did,
        **data
    }
    if developer_id is None:
        developer_id = await _local_owner_id(db, agent_did)
        if developer_id is None:
            return
    async with webhook_service as ws:
        await ws.emit_event(event_type, full_data, db, agent_did, developer_id)


async def emit_staking_event(
    event_type: str,
    agent_did: str,
    stake_data: Dict[str, Any],
    db: AsyncSession
):
    """Helper function to emit staking-related events, to the staker's OWN developer (§TWOAGENT #34 class)."""
    full_data = {
        "agent_did": agent_did,
        **stake_data
    }
    developer_id = await _local_owner_id(db, agent_did)
    if developer_id is None:
        return
    async with webhook_service as ws:
        await ws.emit_event(event_type, full_data, db, agent_did, developer_id)


async def emit_governance_event(
    event_type: str,
    proposal_data: Dict[str, Any],
    db: AsyncSession
):
    """Helper function to emit governance-related events"""
    async with webhook_service as ws:
        await ws.emit_event(event_type, proposal_data, db)


async def emit_federation_event(
    event_type: str,
    peer_data: Dict[str, Any],
    db: AsyncSession
):
    """Helper function to emit federation-related events"""
    async with webhook_service as ws:
        await ws.emit_event(event_type, peer_data, db)
