"""V0659 (k): the MQTT source against a real broker, eclipse-mosquitto 2 in a container: TLS with client certificates,
MQTT 3.1.1 and 5, topic filters, QoS 1, a restart of the proxy, a restart of the broker and a reconnect, and the proxy's
runtime end to end.

Skipped unless TP_MQTT_TEST_BROKER names the broker's host and TP_MQTT_TEST_CTL a directory both the broker and these
tests can read and write. The tests write the broker's configuration, its certificates and its password file there
at test time (a CA, a server certificate for that host, a client certificate; nothing of it is kept in the
repository) and restart it through tests/mqtt_broker.sh, which the broker's container runs:

    docker network create codek-mqtt
    docker run -d --name codek-mosquitto --network codek-mqtt -v "$CTL":/ctl \\
      -v "$PWD/tests/mqtt_broker.sh":/broker.sh:ro --entrypoint /bin/sh eclipse-mosquitto:2 /broker.sh
    docker run --rm --network codek-mqtt -v "$CTL":/ctl -e TP_MQTT_TEST_BROKER=codek-mosquitto \\
      -e TP_MQTT_TEST_CTL=/ctl -v "$PWD":/src:ro python:3.12-bookworm bash -c \\
      'cp -r /src /sdk && cd /sdk && pip install -q -e ".[test,proxy,proxy-mqtt]" && \\
       python -m pytest -q tests/test_proxy_source_mqtt_broker.py'

The broker has two listeners: 8883 (TLS, a client certificate required, its common name the username) and 1883 (a
username and a password). Each test has a client id and a topic prefix of its own, so the sessions it leaves behind do
not meet another test's.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import secrets
import socket
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pytest

import proxy_fake as F
from theprotocol.proxy.testing import FakeContext

HOST = os.environ.get("TP_MQTT_TEST_BROKER", "")
CTL = os.environ.get("TP_MQTT_TEST_CTL", "")

pytestmark = pytest.mark.skipif(not (HOST and CTL), reason="no MQTT broker: set TP_MQTT_TEST_BROKER and "
                                                           "TP_MQTT_TEST_CTL (tests/mqtt_broker.sh)")

CONF = """\
user root
persistence true
persistence_location /mosquitto/data/
log_dest stdout
log_type error
log_type warning
log_type notice
log_type information
connection_messages true
per_listener_settings true
max_inflight_messages 20
max_queued_messages 1000

listener 1883
allow_anonymous false
password_file /tmp/passwd

listener 8883
allow_anonymous false
cafile /ctl/ca.crt
certfile /ctl/server.crt
keyfile /ctl/server.key
require_certificate true
use_identity_as_username true
"""


# ── the broker ───────────────────────────────────────────────────────────────────────────────────────────────────────

def _pki(host: str, ctl: Path, mine: Path) -> dict:
    """A CA; the broker's certificate for `host` (into the shared directory); the proxy's client certificate and key,
    and a second CA that signed neither (into this test run's own directory)."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
    now = datetime.now(timezone.utc)

    # RFC 5280 certificates, with the key identifiers a CA's tooling writes: the source verifies strictly (Python's
    # default from 3.13 on, and the source's on every Python), and a leaf without its authority key id is refused
    def ca(name):
        key = ec.generate_private_key(ec.SECP256R1())
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
        cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
                .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=5))
                .not_valid_after(now + timedelta(days=2))
                .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
                .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
                .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True,
                                             content_commitment=False, key_encipherment=False, data_encipherment=False,
                                             key_agreement=False, encipher_only=False, decipher_only=False),
                               critical=True)
                .sign(key, hashes.SHA256()))
        return key, cert

    def leaf(ca_key, ca_cert, cn, usage, san=None):
        key = ec.generate_private_key(ec.SECP256R1())
        b = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)]))
             .issuer_name(ca_cert.subject).public_key(key.public_key()).serial_number(x509.random_serial_number())
             .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=2))
             .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
             .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=False, crl_sign=False,
                                          content_commitment=False, key_encipherment=False, data_encipherment=False,
                                          key_agreement=False, encipher_only=False, decipher_only=False),
                            critical=True)
             .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
             .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
             .add_extension(x509.ExtendedKeyUsage([usage]), critical=False))
        if san:
            b = b.add_extension(x509.SubjectAlternativeName([x509.DNSName(san)]), critical=False)
        return key, b.sign(ca_key, hashes.SHA256())

    pem = lambda c: c.public_bytes(serialization.Encoding.PEM)  # noqa: E731
    kpem = lambda k: k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,  # noqa: E731
                                     serialization.NoEncryption())
    ca_key, ca_cert = ca("codek test plant CA")
    s_key, s_cert = leaf(ca_key, ca_cert, host, ExtendedKeyUsageOID.SERVER_AUTH, san=host)
    c_key, c_cert = leaf(ca_key, ca_cert, "meters-proxy", ExtendedKeyUsageOID.CLIENT_AUTH)
    _, other_cert = ca("another CA")
    (ctl / "ca.crt").write_bytes(pem(ca_cert))
    (ctl / "server.crt").write_bytes(pem(s_cert))
    (ctl / "server.key").write_bytes(kpem(s_key))
    (mine / "ca.crt").write_bytes(pem(ca_cert))
    (mine / "client.crt").write_bytes(pem(c_cert))
    (mine / "other-ca.crt").write_bytes(pem(other_cert))
    return {"ca": str(mine / "ca.crt"), "client_crt": str(mine / "client.crt"), "client_key_pem": kpem(c_key).decode(),
            "other_ca": str(mine / "other-ca.crt")}


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection((HOST, port), timeout=1):
            return True
    except OSError:
        return False


class Broker:
    def __init__(self, ctl: Path, pki: dict, passwords: dict):
        self.ctl, self.pki, self.pw = ctl, pki, passwords

    def _up(self):
        try:
            st = (self.ctl / "up").stat()
            return (st.st_mtime_ns, (self.ctl / "up").read_text().strip())
        except OSError:
            return None

    def wait_up(self, before=None, timeout: float = 60.0) -> None:
        end = time.monotonic() + timeout
        while True:
            now = self._up()
            if now is not None and now != before and _port_open(1883) and _port_open(8883):
                return
            if time.monotonic() > end:
                log = (self.ctl / "broker.log").read_text()[-2000:] if (self.ctl / "broker.log").exists() else ""
                raise AssertionError(f"the broker did not come up: {log}")
            time.sleep(0.1)

    def restart(self, *, persistence: Optional[bool] = None) -> None:
        """A graceful restart: mosquitto saves its sessions on the way down and loads them on the way up. With
        `persistence` the broker comes up with that setting (False: it keeps nothing across its next restart, which
        is mosquitto's default)."""
        before = self._up()
        if persistence is not None:
            _write_conf(self.ctl, persistence=persistence)
        (self.ctl / "restart").touch()
        self.wait_up(before)


def _write_conf(ctl: Path, *, persistence: bool = True) -> None:
    text = CONF if persistence else CONF.replace("persistence true\n", "persistence false\n")
    (ctl / "mosquitto.conf.tmp").write_text(text)
    os.replace(ctl / "mosquitto.conf.tmp", ctl / "mosquitto.conf")


@pytest.fixture(scope="session")
def broker(tmp_path_factory):
    ctl = Path(CTL)
    mine = tmp_path_factory.mktemp("mqtt-client")
    pki = _pki(HOST, ctl, mine)
    passwords = {"publisher": secrets.token_urlsafe(18), "proxy": secrets.token_urlsafe(18)}
    (ctl / "passwd.plain").write_text("".join(f"{u}:{p}\n" for u, p in passwords.items()))
    b = Broker(ctl, pki, passwords)
    before = b._up()
    _write_conf(ctl)
    if before is not None:
        (ctl / "restart").touch()           # running with an earlier run's certificates: start it again with these
    b.wait_up(before)
    return b


@contextlib.contextmanager
def _publisher(broker):
    """A legacy system publishing over the password listener (MQTT 5, QoS 1 by default, each PUBACK waited for)."""
    import paho.mqtt.client as mqtt
    from paho.mqtt.enums import CallbackAPIVersion
    from paho.mqtt.packettypes import PacketTypes
    from paho.mqtt.properties import Properties
    c = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2, client_id=f"pub-{uuid.uuid4().hex[:10]}",
                    protocol=mqtt.MQTTv5)
    c.username_pw_set("publisher", broker.pw["publisher"])
    c.connect(HOST, 1883)
    c.loop_start()

    class Pub:
        def publish(self, topic, payload, *, qos=1, retain=False, user_properties=None):
            """`user_properties`: a mapping, or a list of (name, value) pairs (MQTT 5 lets a name repeat)."""
            props = None
            if user_properties:
                props = Properties(PacketTypes.PUBLISH)
                props.UserProperty = list(user_properties.items() if isinstance(user_properties, dict)
                                          else user_properties)
            info = c.publish(topic, payload, qos=qos, retain=retain, properties=props)
            info.wait_for_publish(10)
            assert info.is_published(), f"the broker did not take {topic}"
    try:
        yield Pub()
    finally:
        c.disconnect()
        c.loop_stop()


def _prefix() -> str:
    return f"codek/{uuid.uuid4().hex[:10]}"


def _tls_cfg(broker, *, protocol="5", topics, **kw):
    cfg = {"host": HOST, "protocol": protocol, "client_id": f"tp-proxy-{uuid.uuid4().hex[:12]}", "topics": topics,
           "tls": {"ca_file": broker.pki["ca"], "cert_file": broker.pki["client_crt"],
                   "private_key": "file:/run/secrets/meters.key"}}
    cfg.update(kw)
    return cfg


def _ctx(broker, *, dry_run=False, **extra):
    return FakeContext(secrets={"file:/run/secrets/meters.key": broker.pki["client_key_pem"],
                                "env:MQTT_PASSWORD": broker.pw["proxy"], **extra}, dry_run=dry_run)


async def _until(cond, timeout=20.0, what="the condition"):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while not cond():
        if loop.time() > end:
            raise AssertionError(f"timed out waiting for {what}")
        await asyncio.sleep(0.02)


async def _started(cfg, ctx):
    from theprotocol.proxy.sources.mqtt import MqttSource
    src = MqttSource(cfg, ctx)
    await src.start()
    await _until(lambda: src.status["subscribed"], what=f"the subscription ({src.status})")
    return src


async def _take(src, n, *, commit=None, timeout=10.0):
    agen = src.records()
    got = []
    while len(got) < n:
        rec = await asyncio.wait_for(agen.__anext__(), timeout)
        got.append(rec)
        if commit is None or len(got) <= commit:
            await src.committed(rec)
    return got


async def _drain(src, wait=3.0):
    """Take and commit records until none comes for `wait` seconds."""
    agen, got = src.records(), []
    while True:
        try:
            rec = await asyncio.wait_for(agen.__anext__(), wait)
        except asyncio.TimeoutError:
            return got
        got.append(rec)
        await src.committed(rec)


async def _nothing_more(src, wait=1.5):
    """Nothing else arrives on this connection."""
    try:
        got = await _take(src, 1, timeout=wait)
    except asyncio.TimeoutError:
        return
    r = got[0]
    raise AssertionError(f"one more record came: {r.record_id} {dict(r.payload)} {dict(r.meta)}")


# A proxy's last PUBACKs can be lost with its connection: in 2 of 13 runs of this module (2026-11-08) the broker
# logged "connection closed by client" for a stopping proxy instead of reading the DISCONNECT it had sent, and the
# next run got one record more than a strict count expected. A broker sends an unacknowledged message again, and the
# source names such a copy by the id the proxy committed it under, with that record's data, so the outbox drops it.
# After a restart these helpers take such copies and check exactly that, and stay strict about everything new.

def _known(*groups):
    return {r.record_id: r.payload["data"] for g in groups for r in g}


async def _take_new(src, n_new, known, *, timeout=10.0):
    """Take (and commit) records until `n_new` with an id not in `known` came; answers (new ones, copies). A copy must
    carry the data its id was committed with: a known id on another message would be a gap."""
    agen = src.records()
    new, copies = [], []
    while len(new) < n_new:
        rec = await asyncio.wait_for(agen.__anext__(), timeout)
        await src.committed(rec)
        if rec.record_id in known:
            assert rec.payload["data"] == known[rec.record_id], \
                f"{rec.record_id} came with other data than it was committed with: {rec.payload['data']}"
            copies.append(rec)
        else:
            new.append(rec)
    return new, copies


async def _nothing_new(src, known, wait=1.5):
    """Within `wait`, nothing arrives but copies of committed records (see above), each under its committed id."""
    loop = asyncio.get_running_loop()
    end = loop.time() + wait
    agen = src.records()
    while loop.time() < end:
        try:
            rec = await asyncio.wait_for(agen.__anext__(), max(0.01, end - loop.time()))
        except asyncio.TimeoutError:
            return
        await src.committed(rec)
        assert known.get(rec.record_id, object()) == rec.payload["data"], \
            f"a record that is neither a copy nor expected: {rec.record_id} {dict(rec.payload)} {dict(rec.meta)}"


def _ids(records):
    return [r.record_id for r in records]


def _i(records):
    return [r.payload["data"]["i"] for r in records]


def _take_over(broker, cfg) -> None:
    """A second connection with the source's client id and its session kept (MQTT 5: the same expiry), which takes the
    session over (the broker drops the source's connection) and leaves again without acknowledging anything."""
    import paho.mqtt.client as mqtt
    from paho.mqtt.enums import CallbackAPIVersion
    from paho.mqtt.packettypes import PacketTypes
    from paho.mqtt.properties import Properties
    from theprotocol.proxy.sources.mqtt import tls_context
    v5 = cfg["protocol"] == "5"
    c = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2, client_id=cfg["client_id"],
                    clean_session=None if v5 else False, protocol=mqtt.MQTTv5 if v5 else mqtt.MQTTv311,
                    manual_ack=True)
    c.tls_set_context(tls_context(ca_file=broker.pki["ca"], cert_file=broker.pki["client_crt"],
                                  private_key=broker.pki["client_key_pem"]))
    connected = []
    c.on_connect = lambda *a: connected.append(a)
    props = None
    if v5:
        props = Properties(PacketTypes.CONNECT)
        props.SessionExpiryInterval = 0xFFFFFFFF
        c.connect(HOST, 8883, clean_start=False, properties=props)
    else:
        c.connect(HOST, 8883)
    c.loop_start()
    end = time.monotonic() + 10
    while not connected and time.monotonic() < end:
        time.sleep(0.05)
    assert connected, "the second connection did not get in"
    c.disconnect()
    c.loop_stop()


# ── TLS, the protocols, the filters ──────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("protocol", ["3.1.1", "5"])
async def test_tls_with_a_client_certificate_and_topic_filters(broker, protocol):
    p = _prefix()
    src = await _started(_tls_cfg(broker, protocol=protocol, topics=[f"{p}/meters/+/reading", f"{p}/alarms/#"]),
                         _ctx(broker))
    try:
        assert src.status["connected"] and src.status["last_error"] is None
        with _publisher(broker) as pub:
            pub.publish(f"{p}/meters/m1/reading", '{"kwh": 1.5}')
            pub.publish(f"{p}/meters/m1/status", "not a reading")
            pub.publish(f"{p}/meters/m2/reading", '{"kwh": 2}')
            pub.publish(f"{p}/alarms/m2/overheat", "hot")
            pub.publish(f"{p}/elsewhere", "not subscribed")
        got = await _take(src, 3)
        await _nothing_more(src)
    finally:
        await src.stop()
    assert [r.payload["topic"] for r in got] == [f"{p}/meters/m1/reading", f"{p}/meters/m2/reading",
                                                 f"{p}/alarms/m2/overheat"]
    assert _ids(got) == ["seq-0", "seq-1", "seq-2"]
    assert got[0].payload["data"] == {"kwh": 1.5} and got[0].payload["levels"][-2:] == ["m1", "reading"]
    assert got[2].payload["data"] == "hot" and all(r.payload["qos"] == 1 for r in got)


async def test_tls_refuses_a_broker_its_ca_did_not_sign(broker):
    from theprotocol.proxy.sources.mqtt import MqttSource
    p = _prefix()
    cfg = _tls_cfg(broker, topics=[f"{p}/#"])
    cfg["tls"]["ca_file"] = broker.pki["other_ca"]
    src = MqttSource(cfg, _ctx(broker))
    await src.start()
    try:
        await _until(lambda: src.status["last_error"], what="the TLS refusal")
        assert "certificate verify failed" in src.status["last_error"].lower(), src.status
        assert src.status["connects"] == 0 and not src.status["connected"]
    finally:
        await src.stop()


async def test_tls_refuses_a_proxy_without_its_client_certificate(broker):
    from theprotocol.proxy.sources.mqtt import MqttSource
    p = _prefix()
    cfg = _tls_cfg(broker, topics=[f"{p}/#"])
    cfg["tls"] = {"ca_file": broker.pki["ca"]}
    src = MqttSource(cfg, _ctx(broker))
    await src.start()
    try:
        await asyncio.sleep(3)
        assert src.status["connects"] == 0 and not src.status["connected"], src.status
        assert src.status["last_error"], "a refusal must leave its reason behind"
    finally:
        await src.stop()


async def test_a_username_and_a_password_by_reference_and_a_wrong_password_refused(broker):
    from theprotocol.proxy.sources.mqtt import MqttSource
    p = _prefix()
    cfg = {"host": HOST, "protocol": "5", "client_id": f"tp-proxy-{uuid.uuid4().hex[:12]}", "topics": [f"{p}/#"],
           "username": "proxy", "password": "env:MQTT_PASSWORD"}
    src = await _started(cfg, _ctx(broker))
    try:
        assert src.status["connected"]
        with _publisher(broker) as pub:
            pub.publish(f"{p}/meters/m1/reading", '{"kwh": 3}')
        got = await _take(src, 1)
    finally:
        await src.stop()
    assert got[0].payload["data"] == {"kwh": 3}
    wrong = MqttSource({**cfg, "client_id": f"tp-proxy-{uuid.uuid4().hex[:12]}"},
                       _ctx(broker, **{"env:MQTT_PASSWORD": "not-the-password"}))
    await wrong.start()
    try:
        await _until(lambda: wrong.status["last_error"], what="the broker's refusal")
        assert "authori" in wrong.status["last_error"].lower() or "password" in wrong.status["last_error"].lower()
        assert wrong.status["connects"] == 0
    finally:
        await wrong.stop()


# ── exactly once: the proxy restarts ─────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("protocol", ["3.1.1", "5"])
async def test_a_restart_resumes_with_no_duplicate_and_no_gap(broker, protocol):
    p, ctx = _prefix(), _ctx(broker)
    cfg = _tls_cfg(broker, protocol=protocol, topics=[f"{p}/meters/+/reading"])
    a = await _started(cfg, ctx)
    with _publisher(broker) as pub:
        for i in range(4):
            pub.publish(f"{p}/meters/m{i}/reading", json.dumps({"i": i}))
        first = await _take(a, 3, commit=2)     # the third in the core's hands when the proxy stops: a crash
        await a.stop()
        for i in (4, 5):                        # published while the proxy is down: the broker keeps them
            pub.publish(f"{p}/meters/m{i}/reading", json.dumps({"i": i}))
    b = await _started(cfg, ctx)
    try:
        second, copies = await _take_new(b, 4, _known(first[:2]))     # the two A committed may come again
        await _nothing_more(b)
    finally:
        await b.stop()
    c = await _started(cfg, ctx)                # a third run: nothing new, only copies of committed ones if any
    try:
        await _nothing_new(c, _known(first[:2], second))
    finally:
        await c.stop()
    assert _ids(first) == ["seq-0", "seq-1", "seq-2"] and _i(first) == [0, 1, 2]
    assert _ids(second) == ["seq-2", "seq-3", "seq-4", "seq-5"] and _i(second) == [2, 3, 4, 5]
    assert second[0].meta["dup"] is True, "the broker sent the unacknowledged one again, and it kept its id"


async def test_a_puback_lost_after_the_commit_is_not_a_second_record(broker):
    p, ctx = _prefix(), _ctx(broker)
    cfg = _tls_cfg(broker, topics=[f"{p}/meters/+/reading"])
    a = await _started(cfg, ctx)
    with _publisher(broker) as pub:
        pub.publish(f"{p}/meters/m1/reading", '{"i": 0}')
        pub.publish(f"{p}/meters/m1/reading", '{"i": 1}')
        first = await _take(a, 1)
        lost = []
        a._link.ack = lost.append              # the next PUBACK never leaves the proxy
        first += await _take(a, 1)
        await a.stop()
        assert len(lost) == 1
        pub.publish(f"{p}/meters/m1/reading", '{"i": 2}')
    b = await _started(cfg, ctx)
    try:
        second, copies = await _take_new(b, 1, _known(first))
        await _nothing_more(b)
    finally:
        await b.stop()
    assert _ids(first) == ["seq-0", "seq-1"]
    assert "seq-1" in _ids(copies), "the message whose PUBACK was lost did not come again"
    assert all(r.meta["dup"] for r in copies)
    assert _ids(second) == ["seq-2"] and _i(second) == [2], "the copy took a place of its own"


# ── exactly once: the broker restarts, the connection drops ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("protocol", ["3.1.1", "5"])
async def test_a_broker_restart_while_reading_loses_nothing_and_doubles_nothing(broker, protocol):
    p, ctx = _prefix(), _ctx(broker)
    cfg = _tls_cfg(broker, protocol=protocol, topics=[f"{p}/meters/+/reading"])
    a = await _started(cfg, ctx)
    try:
        with _publisher(broker) as pub:
            pub.publish(f"{p}/meters/m1/reading", '{"i": 0}')
            pub.publish(f"{p}/meters/m1/reading", '{"i": 1}')
        got = await _take(a, 2, commit=1)       # the second in hand when the broker goes down
        await asyncio.get_running_loop().run_in_executor(None, broker.restart)
        await _until(lambda: a.status["connects"] >= 2 and a.status["subscribed"], timeout=40, what="the reconnect")
        await a.committed(got[-1])              # its PUBACK belongs to a connection that is gone: not sent
        with _publisher(broker) as pub:
            pub.publish(f"{p}/meters/m1/reading", '{"i": 2}')
        new, copies = await _take_new(a, 1, _known(got))
        await _nothing_more(a)
    finally:
        await a.stop()
    b = await _started(cfg, ctx)
    try:
        await _nothing_new(b, _known(got, new))
    finally:
        await b.stop()
    assert _ids(got) == ["seq-0", "seq-1"] and _i(got) == [0, 1]
    assert "seq-1" in _ids(copies) and all(r.meta["dup"] for r in copies), \
        "the message in hand when the broker went down came again, under its id (the broker kept it in flight)"
    assert _ids(new) == ["seq-2"] and _i(new) == [2], "a gap or a new place after the restart"


async def test_messages_kept_for_an_absent_proxy_survive_a_broker_restart(broker):
    p, ctx = _prefix(), _ctx(broker)
    cfg = _tls_cfg(broker, topics=[f"{p}/meters/+/reading"])
    a = await _started(cfg, ctx)
    await a.stop()
    with _publisher(broker) as pub:
        pub.publish(f"{p}/meters/m1/reading", '{"i": 0}')
        pub.publish(f"{p}/meters/m2/reading", '{"i": 1}')
    await asyncio.get_running_loop().run_in_executor(None, broker.restart)
    b = await _started(cfg, ctx)
    try:
        got = await _take(b, 2)
        await _nothing_more(b)
    finally:
        await b.stop()
    assert _ids(got) == ["seq-0", "seq-1"] and _i(got) == [0, 1]


@pytest.mark.parametrize("protocol", ["3.1.1", "5"])
async def test_a_broker_that_kept_nothing_gives_packet_ids_that_name_new_messages(broker, protocol):
    """mosquitto keeps nothing across a restart unless persistence is on (its default is off): the session starts
    again and its packet ids count from 1 again. A door that opens again, in hand when the proxy restarts, comes
    again under packet id 1 of the new session: it is that event, not the one the lost session sent under id 1."""
    p, ctx = _prefix(), _ctx(broker)
    cfg = _tls_cfg(broker, protocol=protocol, topics=[f"{p}/door/#"])
    run = asyncio.get_running_loop().run_in_executor
    try:
        a = await _started(cfg, ctx)
        try:
            with _publisher(broker) as pub:
                pub.publish(f"{p}/door/1", "open")
            first = await _take(a, 1)
            await run(None, lambda: broker.restart(persistence=False))     # comes up with no session kept
            await _until(lambda: a.status["connects"] >= 2 and a.status["subscribed"], timeout=40,
                         what="the new session")
            assert a.status["session_present"] is False, a.status
            with _publisher(broker) as pub:
                pub.publish(f"{p}/door/1", "open")                         # the door opened again
            held = await _take(a, 1, commit=0)
        finally:
            await a.stop()
        b = await _started(cfg, ctx)
        try:
            again = await _take(b, 1)
        finally:
            await b.stop()
    finally:
        await run(None, lambda: broker.restart(persistence=True))
    assert _ids(first) == ["seq-0"] and _ids(held) == ["seq-1"]
    assert _ids(again) == ["seq-1"] and again[0].meta["dup"] is True, \
        "the new event came again under the lost session's name: the outbox would drop it (a gap)"


@pytest.mark.parametrize("protocol", ["3.1.1", "5"])
async def test_a_reconnect_sends_what_was_in_flight_again_under_its_id(broker, protocol):
    p, ctx = _prefix(), _ctx(broker)
    cfg = _tls_cfg(broker, protocol=protocol, topics=[f"{p}/meters/+/reading"])
    a = await _started(cfg, ctx)
    try:
        with _publisher(broker) as pub:
            pub.publish(f"{p}/meters/m1/reading", '{"i": 0}')
            got = await _take(a, 1, commit=0)
            await asyncio.get_running_loop().run_in_executor(None, _take_over, broker, cfg)
            await _until(lambda: a.status["connects"] >= 2 and a.status["connected"], what="the reconnect")
            await a.committed(got[0])
            pub.publish(f"{p}/meters/m1/reading", '{"i": 1}')
            new, copies = await _take_new(a, 1, _known(got))     # the copy, DUP set, under the id the outbox holds
        await _nothing_more(a)
    finally:
        await a.stop()
    assert _ids(got) == ["seq-0"] and _i(got) == [0]
    assert "seq-0" in _ids(copies) and all(r.meta["dup"] for r in copies), "what was in flight did not come again"
    assert _ids(new) == ["seq-1"] and _i(new) == [1]


# ── retained messages and the publisher's own ids ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("protocol", ["3.1.1", "5"])
async def test_retained_messages_at_subscription_are_skipped_by_default_and_taken_when_asked(broker, protocol):
    p = _prefix()
    topic = f"{p}/meters/m1/state"
    with _publisher(broker) as pub:
        pub.publish(topic, '{"state": "online"}', retain=True)
    skip = await _started(_tls_cfg(broker, protocol=protocol, topics=[f"{p}/meters/#"]), _ctx(broker))
    take = await _started(_tls_cfg(broker, protocol=protocol, topics=[f"{p}/meters/#"], retained="take"),
                          _ctx(broker))
    try:
        with _publisher(broker) as pub:
            pub.publish(f"{p}/meters/m1/reading", '{"kwh": 1}')
        skipped = await _take(skip, 1)
        await _nothing_more(skip, 1.0)
        taken = await _take(take, 2)
    finally:
        await skip.stop()
        await take.stop()
        with _publisher(broker) as pub:
            pub.publish(topic, b"", retain=True)        # clear it
    assert _ids(skipped) == ["seq-0"] and skipped[0].payload["data"] == {"kwh": 1}
    fp = hashlib.sha256(topic.encode() + b"\x00" + b'{"state": "online"}').hexdigest()[:16]
    assert _ids(taken) == [f"{topic}#retained-{fp}", "seq-0"] and taken[0].payload["retain"] is True


async def test_it_passes_the_shipped_source_contract_against_the_broker(broker):
    """check_source against mosquitto. Its second pass (fresh state, the same client id) would meet the first pass's
    session, which has nothing left, so it runs once: the input is three retained messages, which a broker sends at a
    new subscription, taken with `retained: take`, and the source finishes once quiet."""
    from theprotocol.proxy.sources.mqtt import MqttSource
    from theprotocol.proxy.testing import check_source
    p = _prefix()
    with _publisher(broker) as pub:
        for i in range(3):
            pub.publish(f"{p}/meters/m{i}/state", json.dumps({"i": i}), retain=True)
    try:
        got = await check_source(MqttSource, _tls_cfg(broker, topics=[f"{p}/meters/+/state"], retained="take",
                                                      finish_after_idle_s=1.0), ctx=_ctx(broker), limit=10,
                                 twice=False)
    finally:
        with _publisher(broker) as pub:
            for i in range(3):
                pub.publish(f"{p}/meters/m{i}/state", b"", retain=True)
    assert sorted(r.payload["data"]["i"] for r in got) == [0, 1, 2]
    assert all(r.record_id.startswith(f"{p}/meters/m") and "#retained-" in r.record_id for r in got)


async def test_a_qos_0_publication_is_named_by_its_run(broker):
    p, ctx = _prefix(), _ctx(broker)
    src = await _started(_tls_cfg(broker, topics=[f"{p}/meters/+/reading"]), ctx)
    try:
        with _publisher(broker) as pub:
            pub.publish(f"{p}/meters/m1/reading", '{"i": 0}', qos=0)
            pub.publish(f"{p}/meters/m1/reading", '{"i": 1}', qos=1)
        got = await _take(src, 2)
    finally:
        await src.stop()
    # MQTT orders a topic's messages within one QoS, not across two: compare them as a set
    assert sorted((r.record_id, r.payload["qos"], r.payload["data"]["i"]) for r in got) == [("q0-1.0", 0, 0),
                                                                                            ("seq-0", 1, 1)]


async def test_a_user_property_named_twice_keeps_both_values(broker):
    p, ctx = _prefix(), _ctx(broker)
    src = await _started(_tls_cfg(broker, topics=[f"{p}/meters/+/reading"]), ctx)
    try:
        with _publisher(broker) as pub:
            pub.publish(f"{p}/meters/m1/reading", '{"kwh": 1}',
                        user_properties=[("tag", "a"), ("site", "HAM"), ("tag", "b")])
        got = await _take(src, 1)
    finally:
        await src.stop()
    assert got[0].payload["properties"]["user"] == {"tag": ["a", "b"], "site": "HAM"}


@pytest.mark.parametrize("protocol", ["3.1.1", "5"])
async def test_a_dry_run_beside_the_proxy_takes_none_of_its_messages_from_a_shared_subscription(broker, protocol):
    """A shared subscription ($share/<group>/<filter>) hands each message to one member of the group. A dry run beside
    the running proxy subscribes the plain filter: it sees every message and the proxy still gets every message. The
    same on a plain filter is the control."""
    p = _prefix()
    for topics in ([f"$share/g{p[-6:]}/{p}/meters/#"], [f"{p}/meters/#"]):
        cfg = _tls_cfg(broker, protocol=protocol, topics=topics)
        live = await _started(cfg, _ctx(broker))
        dry = await _started(cfg, _ctx(broker, dry_run=True))
        try:
            with _publisher(broker) as pub:
                for i in range(10):
                    pub.publish(f"{p}/meters/m{i}/reading", json.dumps({"i": i}))
            got = await _drain(live)
            seen = await _drain(dry, 1.0)
        finally:
            await dry.stop()
            await live.stop()
        assert sorted(_i(got)) == list(range(10)), f"{topics}: the dry run took {10 - len(got)} of the proxy's messages"
        assert sorted(_i(seen)) == list(range(10)), f"{topics}: the dry run did not see every message"


async def test_the_publishers_own_id_from_an_mqtt_5_user_property(broker):
    p, ctx = _prefix(), _ctx(broker)
    src = await _started(_tls_cfg(broker, topics=[f"{p}/meters/+/reading"], id_property="message-id"), ctx)
    t = f"{p}/meters/m1/reading"
    try:
        with _publisher(broker) as pub:
            pub.publish(t, '{"kwh": 1}', user_properties={"message-id": "r-1"})
            pub.publish(t, '{"kwh": 1}', user_properties={"message-id": "r-1"})     # the publisher's retry
            pub.publish(t, '{"kwh": 2}', user_properties={"message-id": "r-2"})
        got = await _take(src, 3)
    finally:
        await src.stop()
    assert _ids(got) == [f"{t}#r-1", f"{t}#r-1", f"{t}#r-2"]
    assert got[0].payload["properties"]["user"] == {"message-id": "r-1"}


# ── the proxy as it runs ─────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("protocol", ["3.1.1", "5"])
async def test_through_the_runtime_each_reading_is_attested_once_across_a_restart(broker, tmp_path, protocol):
    """The whole path: the spec (the private key by a file reference, read through the spec loader), the source, the
    outbox and its keys, the attestation action against the fake registry; the proxy stops between readings."""
    from theprotocol.proxy.runtime import Proxy
    from theprotocol.proxy.spec import parse
    key = tmp_path / "meters.key"
    key.write_text(broker.pki["client_key_pem"])
    key.chmod(0o600)
    p = _prefix()
    cfg = _tls_cfg(broker, protocol=protocol, topics=[f"{p}/meters/+/reading"])
    cfg["tls"]["private_key"] = "file:meters.key"
    reg = F.FakeRegistry()
    doc = F.spec_doc(tmp_path, sources={"meters": {"type": "mqtt", "config": cfg}},
                     mappings=[{"name": "reading", "version": 1, "from": "meters", "to": "attest",
                                "fields": {"meter": "$.payload.levels.3", "kwh": "$.payload.data.kwh"}}])

    async def run(n_effects, readings):
        proxy = Proxy(parse(doc, base=tmp_path), transport=reg.transport, service=False, poll_s=0.01)
        stop = asyncio.Event()
        task = asyncio.ensure_future(proxy.run(stop=stop))
        try:
            await _until(lambda: proxy.sources["meters"].status["subscribed"], what="the proxy's subscription")
            with _publisher(broker) as pub:
                for meter, kwh in readings:
                    pub.publish(f"{p}/meters/{meter}/reading", json.dumps({"kwh": kwh}))
            await _until(lambda: len(reg.effects) >= n_effects and not proxy.outbox.due(limit=1),
                         what=f"{n_effects} attestations")
        finally:
            stop.set()
            await task
            proxy.close()

    await run(2, [("m1", 1), ("m2", 2)])
    with _publisher(broker) as pub:                     # while the proxy is down
        pub.publish(f"{p}/meters/m1/reading", json.dumps({"kwh": 3}))
    await run(4, [("m3", 4)])
    await asyncio.sleep(0.5)
    assert [e["attestation_data"]["claim"] for e in reg.effects] == [
        {"meter": "m1", "kwh": 1}, {"meter": "m2", "kwh": 2}, {"meter": "m1", "kwh": 3}, {"meter": "m3", "kwh": 4}]
    assert len(reg.writes()) == 4, "a reading was sent twice"
