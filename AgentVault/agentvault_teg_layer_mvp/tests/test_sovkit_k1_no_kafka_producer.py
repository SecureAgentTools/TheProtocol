"""§SOVKIT K1 (2026-09-14) — the TEG holds no Kafka producer.

His word "2 yes": Kafka is PRIVATE to the event store. The TEG's fire-and-forget producer was one of the two producers
writing to the store's broker with none of the HTTP route's checks. The emitter keeps `shutdown_kafka` as a no-op for
main.py's shutdown hook and nothing else of it. Read from the source file (the module imports aiohttp), in the tree or
in the image.
"""
from __future__ import annotations

import os
import pathlib

import pytest

HERE = pathlib.Path(__file__).resolve()
CANDIDATES = [HERE.parents[1] / "src" / "teg_core_service" / "event_emitter.py",
              pathlib.Path("/app/src/teg_core_service/event_emitter.py")]
REQ_CANDIDATES = [HERE.parents[1] / "requirements.txt", pathlib.Path("/app/requirements.txt")]
FORBIDDEN = ("aiokafka", "AIOKafkaProducer", "_get_kafka_producer", "_get_kafka_topic", "_kafka_enabled",
             "KAFKA_BOOTSTRAP_SERVERS", "os.getenv('KAFKA_ENABLED'", 'os.getenv("KAFKA_ENABLED"', "Try Kafka first")


def _source() -> str:
    for p in CANDIDATES:
        if p.is_file():
            return p.read_text(encoding="utf-8")
    pytest.skip("event_emitter.py not found beside the tests or in the image")


def test_the_teg_emitter_holds_no_kafka_producer():
    src = _source()
    for word in FORBIDDEN:
        assert word not in src, f"{word!r} is back in the TEG event_emitter.py"
    assert "async def shutdown_kafka" in src, "main.py's shutdown hook still calls it"
    assert src.count("async def shutdown_kafka") == 1
    assert "§SOVKIT K1" in src


def test_the_teg_requirements_no_longer_pin_aiokafka():
    found = [p for p in REQ_CANDIDATES if p.is_file()]
    if not found:
        pytest.skip("requirements.txt not beside the tests here")
    for p in found:
        assert "aiokafka" not in p.read_text(encoding="utf-8"), str(p)


def test_main_still_calls_the_no_op_shutdown():
    for p in (HERE.parents[1] / "src" / "teg_core_service" / "main.py", pathlib.Path("/app/src/teg_core_service/main.py")):
        if p.is_file():
            assert "shutdown_kafka" in p.read_text(encoding="utf-8")
            return
    pytest.skip("main.py not found")
