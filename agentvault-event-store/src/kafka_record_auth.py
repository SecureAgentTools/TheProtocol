"""§SOVKIT-2 R1 (2026-09-14): the ledger takes a Kafka record only when this store signed it.

His decision (2026-09-14, "2 yes"): Kafka is PRIVATE to the event store. Only the store's HTTP route publishes and only the
store's consumer writes the ledger. Measured before: the consumer wrote whatever arrived on :9092 with none of the route's checks
(the mint-origin rule, the event-type check, the idempotency-key rule) and trusted `source_operator_id` from the record itself,
while every container on a frame's network could reach the broker. The route's checks and the store's mTLS were a door beside
an open one.

A record is the store's own when it carries `x-es-record-auth: v1:<hex>`, an HMAC-SHA256 over (topic, key, value) under a key
only the store holds. The route signs AFTER its checks passed, so a verified record is one the route admitted, and the consumer
needs no second copy of those rules. Broker authentication (SCRAM over TLS, ACLs) comes on top and does not replace this: the
signature keeps meaning "the store admitted this" on a broker somebody misconfigured.

Key: ES_KAFKA_RECORD_KEY when usable, else derived from the store's ES_PROXY_TRUST_SECRET through HMAC under a fixed label (the
marker itself never signs a record). Rotating the marker rotates the record key: rotate with the consumer at lag 0.

Mode, ES_KAFKA_RECORD_AUTH:
  enforce  the default, and what any word it does not know means: unsigned or invalid records are dropped and counted
  shadow   verify and count, store anyway (the transition while registries still produce directly)
  off      no verification and no counting (the emergency switch; the publisher still signs when it holds a key)
Required-on by default for the reason EVENTSTORE_MTLS_REQUIRED is: a guard somebody has to remember is forgotten at a standup.
"""
import hashlib
import hmac
import json
import os
from collections import Counter

from .es_auth import secret_usable

HEADER = "x-es-record-auth"
_VERSION = b"v1"
_LABEL = b"theprotocol:es-kafka-record-auth:v1"
MODES = ("enforce", "shadow", "off")


def _mode_word() -> str:
    return (os.getenv("ES_KAFKA_RECORD_AUTH") or "").strip().lower()


def mode() -> str:
    word = _mode_word()
    return word if word in MODES else "enforce"


def mode_word_known() -> bool:
    word = _mode_word()
    return word == "" or word in MODES


def _key():
    explicit = os.getenv("ES_KAFKA_RECORD_KEY", "")
    if secret_usable(explicit):
        return explicit.encode("utf-8"), "explicit"
    marker = os.getenv("ES_PROXY_TRUST_SECRET", "")
    if secret_usable(marker):
        return hmac.new(marker.encode("utf-8"), _LABEL, hashlib.sha256).digest(), "derived"
    return None, "missing"


def key_source() -> str:
    """explicit | derived | missing (never the key)."""
    return _key()[1]


def describe() -> dict:
    return {"mode": mode(), "key": key_source()}


def _mac(key: bytes, topic: str, record_key, value) -> bytes:
    t = topic.encode("utf-8")
    k = bytes(record_key or b"")
    material = len(t).to_bytes(4, "big") + t + len(k).to_bytes(4, "big") + k + bytes(value)
    return hmac.new(key, material, hashlib.sha256).hexdigest().encode("ascii")


def sign(topic: str, record_key, value: bytes):
    """The headers for a record the route admitted, or None when this store holds no record key."""
    key, _ = _key()
    if key is None:
        return None
    return [(HEADER, _VERSION + b":" + _mac(key, topic, record_key, value))]


def verify(topic: str, record_key, value, headers) -> str:
    """valid | missing (no signature) | invalid (a signature that does not match) | nokey (this store cannot check)."""
    key, _ = _key()
    if key is None:
        return "nokey"
    got = None
    for name, header_value in headers or ():
        if name == HEADER:
            got = header_value
            break
    if got is None:
        return "missing"
    got = bytes(got) if isinstance(got, (bytes, bytearray)) else str(got).encode("utf-8", "replace")
    prefix = _VERSION + b":"
    if not got.startswith(prefix) or not isinstance(value, (bytes, bytearray)):
        return "invalid"
    return "valid" if hmac.compare_digest(got[len(prefix):], _mac(key, topic, record_key, value)) else "invalid"


def _example(event, record, verdict: str) -> dict:
    event = event if isinstance(event, dict) else {}
    return {
        "verdict": verdict,
        "event_type": event.get("event_type"),
        "aggregate_id": event.get("aggregate_id"),
        "idempotency_key": event.get("idempotency_key"),
        "topic": getattr(record, "topic", None),
        "partition": getattr(record, "partition", None),
        "offset": getattr(record, "offset", None),
    }


def screen(records, current_mode=None):
    """Decide, per consumed record, whether the ledger may take it.

    Returns (kept events, examples of records that were not verified, a Counter of (reason, action)). The value is verified as
    the raw bytes the broker delivered, then decoded; a value that is not a JSON object cannot be stored in any mode and is
    dropped rather than retried forever.
    """
    active = current_mode or mode()
    kept, unverified, tally = [], [], Counter()
    for record in records:
        value = record.value
        try:
            event = json.loads(bytes(value).decode("utf-8")) if isinstance(value, (bytes, bytearray)) else value
            if not isinstance(event, dict):
                raise ValueError("a record value must be a JSON object")
        except Exception:
            tally[("undecodable", "dropped")] += 1
            unverified.append(_example(None, record, "undecodable"))
            continue
        if active == "off":
            kept.append(event)
            continue
        verdict = verify(record.topic, record.key, value, record.headers)
        if verdict == "valid":
            kept.append(event)
        elif active == "shadow":
            tally[(verdict, "stored")] += 1
            unverified.append(_example(event, record, verdict))
            kept.append(event)
        else:
            tally[(verdict, "dropped")] += 1
            unverified.append(_example(event, record, verdict))
    return kept, unverified, tally
