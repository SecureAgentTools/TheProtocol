"""§SOVKIT K1 (2026-09-14) — the registry holds no Kafka producer.

His word "2 yes": Kafka is PRIVATE to the event store. agentvault2-85 measured the store's consumer taking whatever
arrived on :9092 with none of the HTTP route's checks; the registry's fire-and-forget producer (`send()` returned after
the buffer append, delivery never awaited) was one of the two producers on that path. The module keeps `shutdown_kafka`
as a no-op for main.py's shutdown hook and nothing else of it: no aiokafka import, no KAFKA_ENABLED read, no topic
map, no Kafka branch in emit(). The image's requirements no longer pin aiokafka either.
"""
from __future__ import annotations

import inspect
import os

import pytest

from agentvault_registry import event_emitter as ee

FORBIDDEN = ("aiokafka", "AIOKafkaProducer", "_get_kafka_producer", "_get_kafka_topic", "_kafka_enabled",
             "KAFKA_BOOTSTRAP_SERVERS", "os.getenv('KAFKA_ENABLED'", 'os.getenv("KAFKA_ENABLED"')


def test_the_registry_emitter_holds_no_kafka_producer():
    src = inspect.getsource(ee)
    for word in FORBIDDEN:
        assert word not in src, f"{word!r} is back in event_emitter.py"
    for name in ("_kafka_producer", "FINANCIAL_EVENTS", "GOVERNANCE_EVENTS", "_get_kafka_producer"):
        assert not hasattr(ee, name), name
    assert hasattr(ee, "shutdown_kafka"), "main.py's shutdown hook still calls it"


async def test_shutdown_kafka_is_a_no_op_for_the_shutdown_hook():
    assert await ee.shutdown_kafka() is None


def test_emit_has_no_kafka_branch():
    src = inspect.getsource(ee.EventEmitter.emit)
    assert "producer" not in src and "Kafka first" not in src
    assert "§SOVKIT K1" in src


def test_the_requirements_no_longer_pin_aiokafka():
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [os.path.join(here, "..", "requirements.txt"), "/app/requirements.txt"]
    # the file beside the tests is the one this tree ships (in CI the tests are staged with it); the image's own copy
    # is the fallback for a run inside a built image with no tree mounted
    found = [p for p in candidates if os.path.isfile(p)]
    if not found:
        pytest.skip("requirements.txt not beside the tests here")
    assert "aiokafka" not in open(found[0], encoding="utf-8").read(), found[0]
