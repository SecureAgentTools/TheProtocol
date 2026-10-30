"""
Kafka Publisher for EventStore — Phase 2 dual-write fix

When EVENTSTORE_HTTP_VIA_KAFKA=true, the HTTP POST /events/ endpoint publishes
to Kafka instead of writing to the DB directly.  The existing Kafka consumer
becomes the sole DB writer, eliminating the dual-path contention that caused
164 deadlocks in a 45-minute burst on Frame A (2026-04-16).

§SOVKIT-2 R1 (2026-09-14): Kafka is private to the store (his decision). Every record this publisher sends carries the store's
record signature (src/kafka_record_auth.py), which the consumer requires before the ledger takes it, and `publish` waits
for the broker's acknowledgement, so the route's 202 means the broker holds the record.

Lifecycle: start_kafka_publisher() on app startup, stop_kafka_publisher() on
shutdown.  Both called from main.py alongside the consumer lifecycle.
"""

import asyncio
import json
import logging
import os

from ..kafka_record_auth import key_source as record_key_source, mode as record_auth_mode, mode_word_known, sign
from ..kafka_security import client_security_kwargs
from .. import ledger_names

logger = logging.getLogger(__name__)

KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "redpanda:9092")
HTTP_VIA_KAFKA = os.getenv("EVENTSTORE_HTTP_VIA_KAFKA", "false").lower() == "true"

# Topic routing — duplicated from registry event_emitter.py
# (EventStore can't import from the registry package); W4 phase 1: with the new names
FINANCIAL_EVENTS = ledger_names.expand_live({
    "TokensTransferred", "TokensIssued", "TokensStaked", "TokensUnstaked",
    "TransactionFeeCollected", "DisputeSlash", "DisputeCompensationMinted",
    "BalanceCorrected", "RewardsDistributed", "RewardsAutoCompounded",
    "CrossRegistryTransferCompleted", "ProjectionSnapshot",
})
GOVERNANCE_EVENTS = {"ProposalCreated", "VoteCast", "ProposalTallied"}


def get_kafka_topic(event_type: str) -> str:
    if event_type in FINANCIAL_EVENTS:
        return "theprotocol.events.financial"
    elif event_type in GOVERNANCE_EVENTS:
        return "theprotocol.events.governance"
    return "theprotocol.events.system"


class KafkaPublisher:
    def __init__(self):
        self._producer = None

    async def start(self):
        from aiokafka import AIOKafkaProducer

        # Values and keys are serialised here, not by the producer: the record signature covers the exact bytes sent.
        self._producer = AIOKafkaProducer(
            bootstrap_servers=KAFKA_BOOTSTRAP,
            acks="all",
            enable_idempotence=True,  # dedup producer retries at broker (playbook #5). aiokafka internally uses max retries when idempotence is on.
            request_timeout_ms=10000,
            retry_backoff_ms=100,
            **client_security_kwargs(),
        )
        await self._producer.start()
        logger.info("[KafkaPublisher] Connected to %s (record auth %s, key %s)",
                    KAFKA_BOOTSTRAP, record_auth_mode(), record_key_source())
        if not mode_word_known():
            logger.error("[KafkaPublisher] ES_KAFKA_RECORD_AUTH=%r is not enforce, shadow or off; it is treated as enforce",
                         os.getenv("ES_KAFKA_RECORD_AUTH"))
        if record_auth_mode() == "enforce" and record_key_source() == "missing":
            logger.error("[KafkaPublisher] record auth is enforced but this store holds no record key (ES_KAFKA_RECORD_KEY, "
                         "or ES_PROXY_TRUST_SECRET of 32+ characters): every publish will be refused with 503")

    async def stop(self):
        if self._producer is not None:
            await self._producer.stop()
            self._producer = None
            logger.info("[KafkaPublisher] Stopped")

    async def publish(self, event_dict: dict) -> None:
        if self._producer is None:
            raise RuntimeError("KafkaPublisher not started")
        topic = get_kafka_topic(event_dict.get("event_type", ""))
        value = json.dumps(event_dict, default=str).encode("utf-8")
        aggregate_id = event_dict.get("aggregate_id")
        key = str(aggregate_id).encode("utf-8") if aggregate_id else None
        headers = sign(topic, key, value)
        if headers is None and record_auth_mode() == "enforce":
            raise RuntimeError("record auth is enforced and this store holds no record key; the consumer would drop the record")
        # §SOVKIT-2 R1: send_and_wait, not send. `send()` returned after the buffer append, so the route answered 202 for a
        # record the broker might never take (a batch failing after the append skipped every fallback, and the caller had
        # already moved on). Now the answer means the broker holds it (acks=all), and a failure reaches the caller as 503.
        await self._producer.send_and_wait(topic, value=value, key=key, headers=headers)
        logger.info(
            "[KafkaPublisher] Published %s to %s (key=%s)",
            event_dict.get("event_type"),
            topic,
            event_dict.get("idempotency_key"),
        )


# Module-level singleton, set by start/stop functions
_publisher: KafkaPublisher | None = None


async def start_kafka_publisher():
    global _publisher
    if not HTTP_VIA_KAFKA:
        logger.info("[KafkaPublisher] Disabled (EVENTSTORE_HTTP_VIA_KAFKA != 'true')")
        return
    _publisher = KafkaPublisher()
    asyncio.create_task(_publisher_connect_loop())
    logger.info("[KafkaPublisher] HTTP→Kafka pathway ACTIVE — connecting in background")


async def _publisher_connect_loop():
    """Connect the publisher in a background task (non-blocking startup)."""
    while True:
        try:
            await _publisher.start()
            return
        except Exception as e:
            logger.warning("[KafkaPublisher] Connect failed, retrying in 5s: %s", e)
            await asyncio.sleep(5)


async def stop_kafka_publisher():
    global _publisher
    if _publisher is not None:
        await _publisher.stop()
        _publisher = None


def get_publisher() -> KafkaPublisher | None:
    return _publisher
