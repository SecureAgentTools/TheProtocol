"""§SOVKIT-2 R1 (2026-09-14): the ledger takes a Kafka record only when this store signed it.

His decision: Kafka is private to the event store. Measured before the change: the consumer wrote whatever arrived on :9092 with
none of the HTTP route's checks and trusted `source_operator_id` from the record, while every container on a frame's network could
reach the broker. What these tests pin:
- a record the store signed verifies; a changed value, topic, key or version does not; another frame's key does not;
- enforce (the default, and what an unknown word means) keeps only signed records, shadow stores and counts, off neither checks
  nor counts, and an undecodable value is dropped in every mode;
- the record key is ES_KAFKA_RECORD_KEY or derived from the proxy marker, never the marker itself;
- the publisher signs the exact bytes it sends and waits for the broker, and refuses under enforce without a key;
- the consumer hands the ledger only what screen() kept, both clients take the security settings and serialise nothing
  themselves, /health reports the posture;
- plaintext adds no setting, SASL_SSL builds SCRAM and a verifying context, a setting that cannot work refuses.

Pure tests import the modules alone (no aiokafka, no database); wiring tests read the source.
Run: python -m pytest tests/test_kafka_record_auth.py -q   (needs pytest and cryptography)
"""
import ast
import asyncio
import datetime
import json
import ssl
import sys
from collections import namedtuple
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import kafka_record_auth as kra, kafka_security as ks  # noqa: E402


def _load_publisher():
    """kafka_publisher lives in src/services, whose package __init__ pulls in the database layer; load that one module under
    a stub package, so these tests need neither a database URL nor SQLAlchemy (its own imports are the two modules above)."""
    import importlib.util
    import types

    if "src.services" not in sys.modules:
        stub = types.ModuleType("src.services")
        stub.__path__ = [str(ROOT / "src" / "services")]
        sys.modules["src.services"] = stub
    spec = importlib.util.spec_from_file_location("src.services.kafka_publisher", ROOT / "src" / "services" / "kafka_publisher.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


kafka_publisher = _load_publisher()

CONSUMER = ROOT / "src" / "services" / "kafka_consumer.py"
PUBLISHER = ROOT / "src" / "services" / "kafka_publisher.py"
MAIN = ROOT / "src" / "main.py"

MARKER = "sovkit2-test-marker-not-a-secret-0000"            # test fixtures, not real secrets
OTHER_MARKER = "sovkit2-test-other-marker-not-a-secret-00"
EXPLICIT = "sovkit2-test-record-key-not-a-secret-0000"
TOPIC = "theprotocol.events.financial"
KEY = b"did:theprotocol:sovkit2-test"
ENV = ("ES_KAFKA_RECORD_AUTH", "ES_KAFKA_RECORD_KEY", "ES_PROXY_TRUST_SECRET", "KAFKA_SECURITY_PROTOCOL", "KAFKA_SASL_MECHANISM",
       "KAFKA_SASL_USERNAME", "KAFKA_SASL_PASSWORD", "KAFKA_SSL_CAFILE", "KAFKA_SSL_CERTFILE", "KAFKA_SSL_KEYFILE")

Record = namedtuple("Record", "topic key value headers partition offset")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ES_PROXY_TRUST_SECRET", MARKER)


def _event(**overrides):
    event = {"id": "e-1", "event_type": "TokensIssued", "aggregate_id": KEY.decode(), "data": {"amount": "1000000"},
             "idempotency_key": "mint-sovkit2-test", "source_service": "registry", "source_operator_id": None}
    event.update(overrides)
    return event


def _signed(event, topic=TOPIC, key=KEY):
    value = json.dumps(event).encode()
    return Record(topic, key, value, kra.sign(topic, key, value), 0, 11)


def _unsigned(event, topic=TOPIC, key=KEY, headers=None):
    return Record(topic, key, json.dumps(event).encode(), headers, 0, 12)


# ── mode and key ─────────────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("word,expected,known", [
    (None, "enforce", True), ("", "enforce", True), ("enforce", "enforce", True), ("shadow", "shadow", True),
    ("OFF", "off", True), ("enforced", "enforce", False), ("disabled", "enforce", False),
])
def test_the_mode_is_enforce_unless_it_says_shadow_or_off(monkeypatch, word, expected, known):
    if word is not None:
        monkeypatch.setenv("ES_KAFKA_RECORD_AUTH", word)
    assert kra.mode() == expected
    assert kra.mode_word_known() is known


def test_the_record_key_is_derived_from_the_marker_and_is_not_the_marker():
    key, source = kra._key()
    assert source == "derived" and key and key != MARKER.encode()
    value = json.dumps(_event()).encode()
    signed_with_the_marker_itself = [(kra.HEADER, b"v1:" + kra._mac(MARKER.encode(), TOPIC, KEY, value))]
    assert kra.verify(TOPIC, KEY, value, signed_with_the_marker_itself) == "invalid"


def test_an_explicit_key_wins_and_a_short_value_is_not_a_key(monkeypatch):
    monkeypatch.setenv("ES_KAFKA_RECORD_KEY", EXPLICIT)
    assert kra.key_source() == "explicit"
    monkeypatch.setenv("ES_KAFKA_RECORD_KEY", "too-short")
    assert kra.key_source() == "derived"
    monkeypatch.delenv("ES_PROXY_TRUST_SECRET")
    assert kra.key_source() == "missing"
    assert kra.sign(TOPIC, KEY, b"{}") is None
    assert kra.verify(TOPIC, KEY, b"{}", [(kra.HEADER, b"v1:00")]) == "nokey"
    assert kra.describe() == {"mode": "enforce", "key": "missing"}


# ── the signature ────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_record_the_store_signed_verifies():
    record = _signed(_event())
    assert kra.verify(record.topic, record.key, record.value, record.headers) == "valid"


@pytest.mark.parametrize("headers", [None, [], [("traceparent", b"00-abc")]])
def test_a_record_without_the_signature_is_missing(headers):
    record = _unsigned(_event(), headers=headers)
    assert kra.verify(record.topic, record.key, record.value, record.headers) == "missing"


@pytest.mark.parametrize("change", ["value", "topic", "key", "version"])
def test_a_changed_record_does_not_verify(change):
    record = _signed(_event())
    topic, key, value, headers = record.topic, record.key, record.value, record.headers
    if change == "value":      # the forger's edit: the same record, now claiming origin
        value = json.dumps(_event(source_operator_id="origin")).encode()
    elif change == "topic":
        topic = "theprotocol.events.system"
    elif change == "key":
        key = b"did:theprotocol:someone-else"
    else:
        headers = [(kra.HEADER, headers[0][1].replace(b"v1:", b"v0:", 1))]
    assert kra.verify(topic, key, value, headers) == "invalid"


def test_a_signature_under_another_frames_key_is_invalid(monkeypatch):
    record = _signed(_event())
    monkeypatch.setenv("ES_PROXY_TRUST_SECRET", OTHER_MARKER)
    assert kra.verify(record.topic, record.key, record.value, record.headers) == "invalid"


# ── what the ledger takes ────────────────────────────────────────────────────────────────────────────────────────────────────

def test_enforce_keeps_only_what_the_store_signed_and_drops_a_forged_mint():
    good = _signed(_event(idempotency_key="k-good"))
    forged = _unsigned(_event(idempotency_key="k-forged", source_operator_id="origin"))
    tampered = Record(TOPIC, KEY, json.dumps(_event(idempotency_key="k-tampered", data={"amount": "999999999"})).encode(),
                      good.headers, 0, 13)
    kept, unverified, tally = kra.screen([good, forged, tampered], "enforce")
    assert [e["idempotency_key"] for e in kept] == ["k-good"]
    assert tally == {("missing", "dropped"): 1, ("invalid", "dropped"): 1}
    assert {e["idempotency_key"] for e in unverified} == {"k-forged", "k-tampered"}
    assert all("data" not in e for e in unverified), "the examples that reach a log must not carry event data"


def test_screen_defaults_to_enforce():
    kept, _, tally = kra.screen([_unsigned(_event())])
    assert kept == [] and tally == {("missing", "dropped"): 1}


def test_shadow_stores_every_record_and_counts_the_unsigned():
    kept, _, tally = kra.screen([_signed(_event(idempotency_key="a")), _unsigned(_event(idempotency_key="b"))], "shadow")
    assert [e["idempotency_key"] for e in kept] == ["a", "b"]
    assert tally == {("missing", "stored"): 1}


def test_off_neither_checks_nor_counts():
    kept, unverified, tally = kra.screen([_unsigned(_event())], "off")
    assert len(kept) == 1 and not unverified and not tally


def test_without_a_key_enforce_drops_and_shadow_counts(monkeypatch):
    monkeypatch.delenv("ES_PROXY_TRUST_SECRET")
    record = _unsigned(_event())
    assert kra.screen([record], "enforce")[2] == {("nokey", "dropped"): 1}
    assert kra.screen([record], "shadow")[2] == {("nokey", "stored"): 1}


@pytest.mark.parametrize("mode", ["enforce", "shadow", "off"])
@pytest.mark.parametrize("value", [b"\xff\xfe", b"[1, 2]", b"not json"])
def test_an_undecodable_value_is_dropped_in_every_mode(mode, value):
    kept, _, tally = kra.screen([Record(TOPIC, KEY, value, None, 0, 14)], mode)
    assert kept == [] and tally == {("undecodable", "dropped"): 1}


# ── the publisher ────────────────────────────────────────────────────────────────────────────────────────────────────────────

class _Producer:
    def __init__(self):
        self.sent = []

    async def send_and_wait(self, topic, value=None, key=None, headers=None):
        self.sent.append((topic, key, value, headers))

    async def send(self, *args, **kwargs):
        raise AssertionError("publish must wait for the broker (send_and_wait), not return after the buffer append")


def _publisher():
    publisher = kafka_publisher.KafkaPublisher()
    publisher._producer = _Producer()
    return publisher


def test_the_publisher_signs_the_exact_bytes_it_sends_and_waits_for_the_broker():
    publisher = _publisher()
    asyncio.run(publisher.publish(_event()))
    assert len(publisher._producer.sent) == 1
    topic, key, value, headers = publisher._producer.sent[0]
    assert topic == TOPIC and key == KEY and json.loads(value) == _event()
    assert kra.verify(topic, key, value, headers) == "valid"
    kept, _, tally = kra.screen([Record(topic, key, value, headers, 0, 15)], "enforce")
    assert len(kept) == 1 and not tally


def test_the_publisher_refuses_under_enforce_without_a_key(monkeypatch):
    monkeypatch.delenv("ES_PROXY_TRUST_SECRET")
    publisher = _publisher()
    with pytest.raises(RuntimeError, match="no record key"):
        asyncio.run(publisher.publish(_event()))
    assert publisher._producer.sent == []


def test_in_shadow_without_a_key_the_publisher_sends_unsigned(monkeypatch):
    monkeypatch.delenv("ES_PROXY_TRUST_SECRET")
    monkeypatch.setenv("ES_KAFKA_RECORD_AUTH", "shadow")
    publisher = _publisher()
    asyncio.run(publisher.publish(_event()))
    assert publisher._producer.sent and publisher._producer.sent[0][3] is None


# ── wiring (source) ──────────────────────────────────────────────────────────────────────────────────────────────────────────

def _function(path, name):
    found = [n for n in ast.walk(ast.parse(path.read_text())) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name]
    assert len(found) == 1, f"{path.name}: {len(found)} functions named {name} (the test is not looking at the code)"
    return found[0]


def test_the_consumer_hands_the_ledger_only_what_screen_kept():
    loop = _function(CONSUMER, "_consume_loop")
    screened = [a for a in ast.walk(loop) if isinstance(a, ast.Assign) and isinstance(a.value, ast.Call)
                and getattr(a.value.func, "id", None) == "screen"]
    assert len(screened) == 1, "the consumer loop must screen each batch exactly once"
    target = screened[0].targets[0]
    assert isinstance(target, ast.Tuple) and isinstance(target.elts[0], ast.Name)
    kept = target.elts[0].id
    writes = [c for c in ast.walk(loop) if isinstance(c, ast.Call) and getattr(c.func, "id", None) == "_process_batch"]
    assert writes, "the consumer loop no longer writes the ledger (the test is not looking at the code)"
    for call in writes:
        arg = call.args[0]
        assert isinstance(arg, ast.Name) and arg.id == kept, f"_process_batch receives {ast.unparse(arg)}, not what screen() kept"


@pytest.mark.parametrize("path,cls", [(CONSUMER, "AIOKafkaConsumer"), (PUBLISHER, "AIOKafkaProducer")])
def test_both_store_clients_take_the_security_settings_and_serialise_nothing_themselves(path, cls):
    calls = [c for c in ast.walk(ast.parse(path.read_text())) if isinstance(c, ast.Call) and getattr(c.func, "id", None) == cls]
    assert len(calls) == 1, f"{path.name}: {len(calls)} {cls} constructions"
    keywords = calls[0].keywords
    assert any(k.arg is None and isinstance(k.value, ast.Call) and getattr(k.value.func, "id", None) == "client_security_kwargs"
               for k in keywords), f"{cls} does not take **client_security_kwargs()"
    assert not {k.arg for k in keywords} & {"value_deserializer", "value_serializer", "key_serializer"}, (
        "the record signature covers the raw bytes: the client must not (de)serialise them")


def test_health_reports_the_record_auth_and_client_posture():
    health = _function(MAIN, "health")
    keys = {k.value for d in ast.walk(health) if isinstance(d, ast.Dict) for k in d.keys if isinstance(k, ast.Constant)}
    assert {"kafka_record_auth", "kafka_client"} <= keys


# ── the security settings ────────────────────────────────────────────────────────────────────────────────────────────────────

def test_plaintext_is_the_default_and_adds_nothing():
    assert ks.client_security_kwargs() == {}
    assert ks.describe() == {"protocol": "PLAINTEXT"}


def _ca_pem(tmp_path):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "sovkit2-test-ca")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(minutes=1))
            .not_valid_after(now + datetime.timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True).sign(key, hashes.SHA256()))
    path = tmp_path / "bundle.pem"
    path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return str(path)


def test_sasl_ssl_builds_scram_and_a_context_that_verifies_the_broker(monkeypatch, tmp_path):
    monkeypatch.setenv("KAFKA_SECURITY_PROTOCOL", "sasl_ssl")
    monkeypatch.setenv("KAFKA_SASL_USERNAME", "eventstore")
    monkeypatch.setenv("KAFKA_SASL_PASSWORD", "sovkit2-test-password-not-a-secret")
    monkeypatch.setenv("KAFKA_SSL_CAFILE", _ca_pem(tmp_path))
    kwargs = ks.client_security_kwargs()
    assert kwargs["security_protocol"] == "SASL_SSL" and kwargs["sasl_mechanism"] == "SCRAM-SHA-256"
    assert kwargs["sasl_plain_username"] == "eventstore"
    context = kwargs["ssl_context"]
    assert isinstance(context, ssl.SSLContext) and context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
    posture = ks.describe()
    assert posture == {"protocol": "SASL_SSL", "sasl_mechanism": "SCRAM-SHA-256", "sasl_user_set": True,
                       "ca_file_set": True, "client_cert_set": False}
    assert "sovkit2-test-password" not in json.dumps(posture)


@pytest.mark.parametrize("env,message", [
    ({"KAFKA_SECURITY_PROTOCOL": "SASL_SSL"}, "KAFKA_SASL_USERNAME"),
    ({"KAFKA_SECURITY_PROTOCOL": "SASL_PLAINTEXT", "KAFKA_SASL_MECHANISM": "PLAIN", "KAFKA_SASL_USERNAME": "u",
      "KAFKA_SASL_PASSWORD": "p"}, "KAFKA_SASL_MECHANISM"),
    ({"KAFKA_SECURITY_PROTOCOL": "TLS"}, "KAFKA_SECURITY_PROTOCOL"),
])
def test_a_setting_that_cannot_work_refuses(monkeypatch, env, message):
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match=message):
        ks.client_security_kwargs()
