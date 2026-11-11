"""V0659 (k): the MQTT source, against an MQTT broker in the test's own event loop (tests/mqtt_fake.py).

What a broker gives a subscriber, and what the source makes of it: a persistent session (the broker keeps what arrives
while the proxy is away), a PUBACK only once the record is in the outbox (committed), and the same record id for a
message the broker sends again (DUP set, the same packet id), so the outbox's key drops the copy. These cases drive
the source's own logic, including the faults a real broker cannot be made to show on cue (a PUBACK lost after the
commit, a session the broker lost). The same properties against a real mosquitto broker, with TLS client
certificates, MQTT 3.1.1 and 5, a broker restart and a reconnect, are in tests/test_proxy_source_mqtt_broker.py.

Red before V0659 (k): theprotocol.proxy.sources.mqtt does not exist.
"""
from __future__ import annotations

import asyncio
import base64
import dataclasses
import hashlib
import json
import logging
import os
import ssl
import sys
from datetime import datetime, timedelta, timezone

import pytest

import mqtt_fake as M
import proxy_fake as F
from theprotocol.proxy.plugins import PluginError, available, load
from theprotocol.proxy.sources.mqtt import MqttSource, tls_context
from theprotocol.proxy.testing import FakeContext, check_class, check_resume, check_source

CID = "tp-proxy-meters"


def _cfg(**kw):
    cfg = {"host": "broker.test", "client_id": CID, "topics": ["meters/+/reading"]}
    cfg.update(kw)
    return cfg


def _on(broker):
    """MqttSource talking to `broker` instead of a network."""
    return type("MqttOnFakeBroker", (MqttSource,), {"link_factory": staticmethod(broker.link)})


async def _until(cond, timeout=2.0, what="the condition"):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while not cond():
        if loop.time() > end:
            raise AssertionError(f"timed out waiting for {what}")
        await asyncio.sleep(0.005)


async def _started(cls, cfg, ctx):
    src = cls(cfg, ctx)
    await src.start()
    await _until(lambda: src.status["subscribed"], what="the subscription")
    return src


async def _take(src, n, *, commit=None, timeout=2.0):
    """Take n records from a running source, committing the first `commit` of them (all, by default): a record not
    committed is one the core had in hand when the proxy stopped (its row written or not, its cursor not moved)."""
    agen = src.records()
    got = []
    while len(got) < n:
        rec = await asyncio.wait_for(agen.__anext__(), timeout)
        got.append(rec)
        if commit is None or len(got) <= commit:
            await src.committed(rec)
    return got


def _ids(records):
    return [r.record_id for r in records]


def _data(records):
    return [r.payload["data"] for r in records]


# ── the plugin ───────────────────────────────────────────────────────────────────────────────────────────────────────

def test_it_keeps_the_interface_and_the_core_finds_it_by_name():
    check_class(MqttSource, "source")
    assert load("source", "mqtt") is MqttSource
    assert available("source")["mqtt"] == "theprotocol.proxy.sources.mqtt:MqttSource"
    props = MqttSource.config_schema["properties"]
    assert props["password"]["x-secret"] is True
    assert props["tls"]["properties"]["private_key"]["x-secret"] is True
    assert props["tls"]["properties"]["key_password"]["x-secret"] is True


def test_the_spec_takes_its_credentials_only_by_reference(tmp_path):
    from theprotocol.proxy.spec import SpecError, parse

    def doc(**conf):
        cfg = {"host": "broker.plant", "client_id": CID, "topics": ["meters/+/reading"], "username": "proxy",
               "password": "env:MQTT_PASSWORD",
               "tls": {"ca_file": "/etc/plant-ca.crt", "cert_file": "/etc/meters.crt",
                       "private_key": "file:/etc/meters.key"}}
        cfg.update(conf)
        return F.spec_doc(tmp_path, sources={"meters": {"type": "mqtt", "config": cfg}},
                          mappings=[{"name": "reading", "version": 1, "from": "meters", "to": "attest",
                                     "fields": {"kwh": "$.payload.data.kwh"}}])

    spec = parse(doc(), base=tmp_path)
    assert spec.sources["meters"].type == "mqtt"
    with pytest.raises(SpecError, match=r"sources\.meters\.config\.password"):
        parse(doc(password="hunter2-the-broker-password"), base=tmp_path)
    with pytest.raises(SpecError, match=r"sources\.meters\.config\.tls\.private_key"):
        parse(doc(tls={"cert_file": "/etc/meters.crt", "private_key": "the PEM text written into the spec"}),
              base=tmp_path)
    with pytest.raises(SpecError, match=r"topics"):
        parse(doc(topics=[{"filter": "meters/#", "qos": 2}]), base=tmp_path)


# ── the shipped contracts ────────────────────────────────────────────────────────────────────────────────────────────

SEED = [("meters/m1/reading", b'{"kwh": 1.5}'), ("meters/m2/reading", b'{"kwh": 2}'),
        ("meters/m1/reading", b'{"kwh": 1.6}'), ("meters/m3/reading", b'{"kwh": 7}'),
        ("meters/m2/reading", b'{"kwh": 2.5}')]


async def test_it_passes_the_shipped_source_contract():
    broker = M.FakeBroker(per_state=True, seed=SEED[:3])
    got = await check_source(_on(broker), _cfg(finish_after_idle_s=0.2), limit=10)
    assert _ids(got) == ["seq-0", "seq-1", "seq-2"]
    first = got[0].payload
    assert first["data"] == {"kwh": 1.5} and first["encoding"] == "json"
    assert first["topic"] == "meters/m1/reading" and first["levels"] == ["meters", "m1", "reading"]
    assert first["qos"] == 1 and first["retain"] is False
    assert got[0].meta["via"] == "mqtt"


async def test_it_passes_the_shipped_resume_contract():
    """check_resume: two runs over one state; the broker keeps the session, so the second run gets what the first did
    not acknowledge, sent again with DUP set, and gives it the places the first run would have."""
    broker = M.FakeBroker(per_state=True, seed=SEED)
    ids = await check_resume(_on(broker), _cfg(finish_after_idle_s=0.2), first=2, limit=5)
    assert ids == ["seq-0", "seq-1", "seq-2", "seq-3", "seq-4"]


# ── exactly once across a restart ────────────────────────────────────────────────────────────────────────────────────

async def test_a_message_not_committed_when_the_proxy_stopped_comes_again_with_the_same_id():
    broker, ctx = M.FakeBroker(), FakeContext()
    cls = _on(broker)
    a = await _started(cls, _cfg(), ctx)
    for i in range(4):
        broker.publish(f"meters/m{i}/reading", json.dumps({"i": i}))
    first = await _take(a, 3, commit=2)          # the third is in the core's hands, its cursor never moved: a crash
    await a.stop()
    broker.publish("meters/m9/reading", '{"i": 9}')                 # while the proxy is down: the broker keeps it
    b = await _started(cls, _cfg(), ctx)
    second = await _take(b, 3)
    await b.stop()
    assert _ids(first) == ["seq-0", "seq-1", "seq-2"]
    assert _ids(second) == ["seq-2", "seq-3", "seq-4"], "a gap or a duplicate after the restart"
    assert _data(second) == [{"i": 2}, {"i": 3}, {"i": 9}]
    assert second[0].meta["dup"] is True, "the broker sent it again (DUP): the outbox's key drops the copy"
    assert broker.connects == [(CID, False), (CID, True)], "the session was kept, not started again"
    assert [mid for _, mid in broker.acks] == [1, 2, 3, 4, 5], "each message acknowledged once, after its commit"


async def test_a_puback_lost_after_the_commit_gives_the_copy_the_same_id_and_takes_no_place():
    """The cursor moved (the record is in the outbox) but the PUBACK never reached the broker: the broker sends the
    message again, and it must neither become a second record nor push every later message one place along."""
    broker, ctx = M.FakeBroker(), FakeContext()
    cls = _on(broker)
    a = await _started(cls, _cfg(), ctx)
    broker.publish("meters/m1/reading", '{"i": 0}')
    broker.publish("meters/m1/reading", '{"i": 1}')
    first = await _take(a, 1)
    broker.lose_acks = 1
    first += await _take(a, 1)
    await a.stop()
    assert broker.lost_acks == [(CID, 2)]
    broker.publish("meters/m1/reading", '{"i": 2}')
    b = await _started(cls, _cfg(), ctx)
    second = await _take(b, 2)
    await b.stop()
    assert _ids(first) == ["seq-0", "seq-1"]
    assert _ids(second) == ["seq-1", "seq-2"], "the copy took a new place: every later message would be off by one"
    assert _data(second) == [{"i": 1}, {"i": 2}] and second[0].meta["dup"] is True
    assert [mid for _, mid in broker.acks] == [1, 2, 3], "the copy is acknowledged this time"


async def test_a_dropped_connection_sends_what_was_in_flight_again_and_each_copy_keeps_its_id():
    """The broker kept the session, so it sends again every message it has no PUBACK for: the one in hand comes again
    under its id, and the one the lost connection delivered but the source had not taken yet comes only as the copy
    the broker sends (taken from the lost connection as well, it would be a record committed with no PUBACK)."""
    broker, ctx = M.FakeBroker(), FakeContext()
    a = await _started(_on(broker), _cfg(), ctx)
    for i in range(3):
        broker.publish("meters/m1/reading", json.dumps({"i": i}))
    got = await _take(a, 2, commit=1)            # the second is in hand when the connection drops
    broker.drop()
    await _until(lambda: a.status["connects"] == 2 and a.status["connected"], what="the reconnect")
    await a.committed(got[-1])                   # its PUBACK would go on a connection that is gone: it is not sent
    got += await _take(a, 2)
    with pytest.raises(asyncio.TimeoutError):
        await _take(a, 1, timeout=0.3)
    await a.stop()
    assert _ids(got) == ["seq-0", "seq-1", "seq-1", "seq-2"]
    assert _data(got) == [{"i": 0}, {"i": 1}, {"i": 1}, {"i": 2}]
    assert [r.meta["dup"] for r in got[2:]] == [True, True], "both came again from the broker"
    assert [mid for _, mid in broker.acks] == [1, 2, 3], "each acknowledged once, on the connection it came in on"
    assert broker.stale_acks == [], "a PUBACK went out for a message of a connection that had dropped"


async def test_a_broker_that_lost_the_session_is_subscribed_to_again_and_says_so(caplog):
    broker, ctx = M.FakeBroker(), FakeContext()
    a = await _started(_on(broker), _cfg(topics=["meters/+/reading", "alarms/#"]), ctx)
    caplog.set_level(logging.WARNING)
    broker.forget()
    await _until(lambda: a.status["connects"] == 2 and a.status["subscribed"], what="the subscription again")
    broker.publish("alarms/a/b", "overheat")
    got = await _take(a, 1)
    await a.stop()
    assert broker.connects == [(CID, False), (CID, False)]
    assert [sorted(f for f, _ in items) for _, items, _ in broker.subscribes] == [["alarms/#", "meters/+/reading"]] * 2
    assert any("did not keep" in r.getMessage() for r in caplog.records), "a lost session must be said, not hidden"
    assert got[0].payload["data"] == "overheat" and got[0].payload["encoding"] == "text"


async def test_a_restart_with_the_session_kept_subscribes_only_what_changed():
    """The broker keeps the subscriptions with the session: subscribing again would only send the retained messages
    again. A filter the spec added is subscribed, one it dropped is unsubscribed."""
    broker, ctx = M.FakeBroker(), FakeContext()
    cls = _on(broker)
    a = await _started(cls, _cfg(topics=["a/#", "b/#"]), ctx)
    await a.stop()
    b = await _started(cls, _cfg(topics=["b/#", "c/#"]), ctx)
    await b.stop()
    assert [sorted(f for f, _ in items) for _, items, _ in broker.subscribes] == [["a/#", "b/#"], ["c/#"]]
    assert broker.unsubscribes == [(CID, ["a/#"])]


async def test_qos_0_messages_are_named_by_their_run_and_never_acknowledged():
    """No broker sends a QoS 0 message twice (at most once, by definition), so it has no place in the QoS 1 stream;
    its name holds the run that received it, so two runs never share one."""
    broker, ctx = M.FakeBroker(), FakeContext()
    cls = _on(broker)
    a = await _started(cls, _cfg(), ctx)
    broker.publish("meters/m1/reading", '{"i": 0}', qos=0)
    broker.publish("meters/m1/reading", '{"i": 1}', qos=1)
    broker.publish("meters/m1/reading", '{"i": 2}', qos=0)
    first = await _take(a, 3)
    await a.stop()
    b = await _started(cls, _cfg(), ctx)
    broker.publish("meters/m1/reading", '{"i": 3}', qos=0)
    second = await _take(b, 1)
    await b.stop()
    assert _ids(first) == ["q0-1.0", "seq-0", "q0-1.1"]
    assert [r.payload["qos"] for r in first] == [0, 1, 0]
    assert _ids(second) == ["q0-2.0"]
    assert [mid for _, mid in broker.acks] == [1], "only the QoS 1 message has a PUBACK"


async def test_a_qos_0_message_does_not_move_the_places_of_the_qos_1_messages_after_it():
    """A QoS 0 message between two QoS 1 ones is gone after a restart (nobody sends it again); had it taken a place,
    the redelivered QoS 1 message would get another id than the one the outbox holds, and be sent twice."""
    broker, ctx = M.FakeBroker(), FakeContext()
    cls = _on(broker)
    a = await _started(cls, _cfg(), ctx)
    broker.publish("meters/m1/reading", '{"i": 0}', qos=1)
    broker.publish("meters/m1/reading", '{"i": 1}', qos=0)
    broker.publish("meters/m1/reading", '{"i": 2}', qos=1)
    first = await _take(a, 3, commit=2)
    await a.stop()
    b = await _started(cls, _cfg(), ctx)
    second = await _take(b, 1)
    await b.stop()
    assert _ids(first) == ["seq-0", "q0-1.0", "seq-1"]
    assert _ids(second) == ["seq-1"] and _data(second) == [{"i": 2}]


async def test_qos_2_is_refused_with_the_reason():
    with pytest.raises(PluginError, match="PUBREC"):
        MqttSource(_cfg(qos=2), FakeContext())
    with pytest.raises(PluginError, match="PUBREC"):
        MqttSource(_cfg(topics=[{"filter": "meters/#", "qos": 2}]), FakeContext())


# ── a packet id names a message only within the session that gave it ─────────────────────────────────────────────────

async def test_a_new_sessions_message_in_hand_at_a_restart_is_not_named_after_the_lost_sessions():
    """A broker that kept nothing (a restart without persistence) starts the session again and counts its packet ids
    from 1 again. A message of the new session that is in hand at a restart comes again (DUP, its packet id of the new
    session); it is not the old session's message under that id, even with the same content (a door that opened
    again), so it keeps the id it was handed over with."""
    broker, ctx = M.FakeBroker(), FakeContext()
    cls = _on(broker)
    a = await _started(cls, _cfg(), ctx)
    broker.publish("meters/door/reading", "open")
    first = await _take(a, 1)                                # seq-0 under packet id 1, committed
    broker.forget()
    await _until(lambda: a.status["connects"] == 2 and a.status["subscribed"], what="the new session")
    broker.publish("meters/door/reading", "open")            # the door opened again: packet id 1 of the new session
    held = await _take(a, 1, commit=0)                       # in hand when the proxy stops
    await a.stop()
    b = await _started(cls, _cfg(), ctx)
    again = await _take(b, 1)
    await b.stop()
    assert _ids(first) == ["seq-0"] and _ids(held) == ["seq-1"]
    assert _ids(again) == ["seq-1"] and again[0].meta["dup"] is True, \
        "the new event came again under the lost session's name: the outbox would drop it (a gap)"


async def test_a_new_sessions_message_whose_first_copy_was_lost_is_not_named_after_the_lost_sessions():
    """The same without a restart: after the session was lost, a message's first copy never reaches the proxy (the
    connection drops with it on the wire) and the broker sends it again, DUP set, under packet id 1 of the new
    session."""
    broker, ctx = M.FakeBroker(), FakeContext()
    a = await _started(_on(broker), _cfg(), ctx)
    broker.publish("meters/door/reading", "open")
    first = await _take(a, 1)
    broker.forget()
    await _until(lambda: a.status["connects"] == 2 and a.status["subscribed"], what="the new session")
    broker.publish("meters/door/reading", "open")
    broker.drop()                                            # its first copy was on the wire: it never arrives
    await _until(lambda: a.status["connects"] == 3 and a.status["connected"], what="the reconnect")
    got = await _take(a, 1)
    await a.stop()
    assert _ids(first) == ["seq-0"]
    assert _ids(got) == ["seq-1"] and got[0].meta["dup"] is True, \
        "a new event after the session was lost was named after the old one: the outbox would drop it (a gap)"


async def test_another_broker_or_client_id_is_another_session_and_resumes_on_its_own_packet_ids():
    """A spec that names another broker (or client id) starts another session. After a restart on the new one, its
    messages are known by the new broker's packet ids, and none is named after the old broker's message under the
    same id."""
    ctx = FakeContext()
    old, new = M.FakeBroker(), M.FakeBroker()
    a = await _started(_on(old), _cfg(host="old.broker"), ctx)
    old.publish("meters/door/reading", "open")
    await _take(a, 1)                                        # seq-0 under packet id 1 of the old broker
    await a.stop()
    b = await _started(_on(new), _cfg(host="new.broker"), ctx)
    new.publish("meters/door/reading", "open")               # packet id 1 of the new broker
    held = await _take(b, 1, commit=0)
    await b.stop()
    c = await _started(_on(new), _cfg(host="new.broker"), ctx)
    again = await _take(c, 1)
    await c.stop()
    assert _ids(held) == ["seq-1"]
    assert _ids(again) == ["seq-1"], "the new broker's message came again under the old broker's name (a gap)"


async def test_a_packet_id_the_broker_gave_again_names_the_message_it_was_given_to():
    """MQTT lets a broker give a packet id again once it has the PUBACK, and one that hands out the lowest free id
    gives every message id 1 at a low rate. A heartbeat in hand at a restart comes again under id 1: it is that
    heartbeat, not the one before it."""
    broker, ctx = M.FakeBroker(reuse_ids=True), FakeContext()
    cls = _on(broker)
    a = await _started(cls, _cfg(), ctx)
    broker.publish("meters/m1/reading", "online")
    first = await _take(a, 1)                                # packet id 1, acknowledged: free again
    broker.publish("meters/m1/reading", "online")            # the next heartbeat goes out under packet id 1
    held = await _take(a, 1, commit=0)
    await a.stop()
    b = await _started(cls, _cfg(), ctx)
    again = await _take(b, 1)
    await b.stop()
    assert [mid for _, mid in broker.acks] == [1, 1]
    assert _ids(first) == ["seq-0"] and _ids(held) == ["seq-1"]
    assert _ids(again) == ["seq-1"], "the second heartbeat came again under the first one's name: dropped (a gap)"


async def test_a_copy_under_a_known_packet_id_with_other_content_is_another_message():
    """The content is part of what makes a copy: sent again under the packet id of a committed message, other content
    is the message the broker gave that id to next, whose first copy was lost on the wire."""
    broker, ctx = M.FakeBroker(reuse_ids=True), FakeContext()
    a = await _started(_on(broker), _cfg(), ctx)
    broker.publish("meters/m1/reading", '{"i": 0}')
    first = await _take(a, 1)                                # packet id 1, acknowledged: free again
    broker.publish("meters/m1/reading", '{"i": 1}')          # packet id 1 again; this copy never arrives
    broker.drop()
    await _until(lambda: a.status["connects"] == 2 and a.status["connected"], what="the reconnect")
    got = await _take(a, 1)
    await a.stop()
    assert _ids(first) == ["seq-0"]
    assert _ids(got) == ["seq-1"] and _data(got) == [{"i": 1}] and got[0].meta["dup"] is True


async def test_the_place_of_a_record_handed_over_is_never_given_to_another_message():
    """A record in the core's hands when the proxy stopped may be in the outbox already. If the broker lost the
    session meanwhile, that message never comes again, and the next one must not take its place: the outbox would
    take it for a repeat and drop it."""
    broker, ctx = M.FakeBroker(), FakeContext()
    cls = _on(broker)
    a = await _started(cls, _cfg(), ctx)
    broker.publish("meters/m1/reading", '{"i": 0}')
    held = await _take(a, 1, commit=0)                       # its row may be written; its commit never came
    await a.stop()
    broker.forget()                                          # the broker restarts with nothing kept
    b = await _started(cls, _cfg(), ctx)
    broker.publish("meters/m1/reading", '{"i": 1}')
    got = await _take(b, 1)
    await b.stop()
    assert broker.connects[-1] == (CID, False)
    assert _ids(held) == ["seq-0"]
    assert _ids(got) == ["seq-1"], "a new message took the place of one the outbox may hold: it would be dropped"


async def _drain(src, wait=0.5):
    """Take and commit records until none comes for `wait` seconds."""
    agen, got = src.records(), []
    while True:
        try:
            rec = await asyncio.wait_for(agen.__anext__(), wait)
        except asyncio.TimeoutError:
            return got
        got.append(rec)
        await src.committed(rec)


async def _as_the_core_reads(src, until, timeout=10.0):
    """Take and commit records one after another with nothing else waiting in between, as the core's loop does (its
    writes are synchronous), until `until(records)` holds; a wait_for around each record would let the event loop
    run between two of them, which the core does not."""
    async def read():
        agen, got = src.records(), []
        while not until(got):
            rec = await agen.__anext__()
            got.append(rec)
            await src.committed(rec)
        return got
    return await asyncio.wait_for(read(), timeout)


def _each_message_once(got, n):
    """Every message i in range(n) is one record id, no two messages share one, and what came more than once is a copy
    the broker sent again (DUP) under its id. Answers the copies."""
    ids_of = {}
    for r in got:
        ids_of.setdefault(r.payload["data"]["i"], set()).add(r.record_id)
    assert sorted(ids_of) == list(range(n)), "a message is missing"
    twice = sorted(i for i, ids in ids_of.items() if len(ids) > 1)
    assert not twice, f"{len(twice)} of {n} messages became two records"
    assert len({r.record_id for r in got}) == n, "two messages under one id: the outbox would drop one (a gap)"
    first_seen = {}
    copies = [r for r in got if first_seen.setdefault(r.record_id, r) is not r]
    assert all(r.meta["dup"] for r in copies), [r.record_id for r in copies]
    return copies


async def test_a_backlog_the_lost_connection_delivered_is_taken_once_from_the_broker(caplog):
    """MQTT 3.1.1 leaves the number of messages in flight to the broker (mosquitto: max_inflight_messages, 0 for no
    limit). The connection drops with 600 delivered and none taken yet; the broker kept the session, so it sends each
    of them again (DUP, in order). Each is one record: none is taken from the lost connection as well, which would
    commit it without its PUBACK and leave more copies to know again than the source remembers (256)."""
    broker, ctx = M.FakeBroker(inflight_max=600), FakeContext()
    cls = _on(broker)
    a = await _started(cls, _cfg(), ctx)
    await a.stop()
    for i in range(600):
        broker.publish("meters/m1/reading", json.dumps({"i": i}))    # a backlog while the proxy was away
    caplog.set_level(logging.WARNING)
    b = cls(_cfg(), ctx)
    await b.start()
    await _until(lambda: len(broker.sessions[CID].inflight) == 600, what="the backlog in flight")
    for _ in range(3):
        await asyncio.sleep(0)                               # every delivery is in the source's hands
    broker.drop()
    got = await _as_the_core_reads(b, lambda got: len({r.payload["data"]["i"] for r in got}) == 600)
    got += await _drain(b)
    await b.stop()
    copies = _each_message_once(got, 600)
    # a message taken before the source saw the connection go comes again, as a copy under its id (the outbox drops
    # it); none of the lost connection's other deliveries is taken
    assert len(copies) <= 1, [r.record_id for r in copies]
    assert len(broker.acks) == 600
    assert any("in flight" in r.getMessage() and "256" in r.getMessage() for r in caplog.records), \
        "a broker that keeps more QoS 1 messages in flight than the source can know again must be named"


async def test_while_the_broker_is_away_the_lost_connections_messages_wait_for_its_answer():
    """Between a lost connection and the broker's answer to the next one, the source cannot know whether the broker
    kept the session (it sends the messages again) or not (these are the only copies): the messages the lost
    connection delivered wait, and none is committed without its PUBACK meanwhile."""
    broker, ctx = M.FakeBroker(inflight_max=300), FakeContext()
    cls = _on(broker)
    a = await _started(cls, _cfg(), ctx)
    await a.stop()
    for i in range(300):
        broker.publish("meters/m1/reading", json.dumps({"i": i}))
    b = cls(_cfg(), ctx)
    await b.start()
    await _until(lambda: len(broker.sessions[CID].inflight) == 300, what="the backlog in flight")
    for _ in range(3):
        await asyncio.sleep(0)
    broker.drop(reconnect=False)                             # the broker is away for a while
    await _until(lambda: not b.status["connected"], what="the loss")
    away = await _drain(b, 0.3)
    broker.reconnect()
    got = away + await _drain(b)
    await b.stop()
    assert away == [], f"{len(away)} messages of the lost connection were taken before the broker answered"
    assert _each_message_once(got, 300) == []
    assert len(broker.acks) == 300 and broker.stale_acks == []


async def test_moving_to_a_broker_that_kept_a_session_matches_none_of_the_old_brokers_packet_ids():
    """The spec moves the proxy to another broker, which still holds a session for its client id from an earlier run
    there: that session's messages come under its own packet ids (DUP for one in flight), which name none of the
    messages the old broker sent under the same ids."""
    ctx = FakeContext()
    old, new = M.FakeBroker(), M.FakeBroker()
    earlier = await _started(_on(new), _cfg(host="new.broker"), FakeContext())    # a run there, with its own state
    new.publish("meters/door/reading", "open")
    await _take(earlier, 1, commit=0)                        # in flight in the new broker's session: packet id 1
    await earlier.stop()
    a = await _started(_on(old), _cfg(host="old.broker"), ctx)
    old.publish("meters/door/reading", "open")
    first = await _take(a, 1)                                # seq-0 under packet id 1 of the old broker
    await a.stop()
    b = await _started(_on(new), _cfg(host="new.broker"), ctx)
    got = await _take(b, 1)
    await b.stop()
    assert new.connects[-1] == (CID, True), "the new broker kept the session"
    assert _ids(first) == ["seq-0"]
    assert _ids(got) == ["seq-1"] and got[0].meta["dup"] is True, \
        "the new broker's message came under the old broker's name (a gap)"


async def test_a_packet_id_given_to_a_message_with_its_own_id_no_longer_names_the_one_before():
    """The broker gave packet id 1 to a message the publisher named itself (its own id: it takes no place). The id no
    longer names the message given a place under it before, so a later message under id 1 whose first copy was lost
    is a new one, even with that message's content."""
    broker, ctx = M.FakeBroker(reuse_ids=True), FakeContext()
    a = await _started(_on(broker), _cfg(id_field="seq"), ctx)
    broker.publish("meters/m1/reading", "online")            # no id of its own: seq-0, under packet id 1
    first = await _take(a, 1)
    broker.publish("meters/m1/reading", '{"seq": 7}')        # its own id, under packet id 1 again
    own = await _take(a, 1)
    broker.publish("meters/m1/reading", "online")            # packet id 1 again; this copy never arrives
    broker.drop()
    await _until(lambda: a.status["connects"] == 2 and a.status["connected"], what="the reconnect")
    got = await _take(a, 1)
    await a.stop()
    assert _ids(first) == ["seq-0"] and _ids(own) == ["meters/m1/reading#7"]
    assert _ids(got) == ["seq-1"] and got[0].meta["dup"] is True, "taken for the message before it (a gap)"


async def test_a_new_session_is_on_disk_before_any_of_its_records_is_handed_over():
    """With a state that takes its time to write: the first record of a session the broker started anew is handed
    over only once the state says the packet ids belong to that session (a restart would otherwise match the new
    session's messages against the lost one's)."""
    broker, ctx = M.FakeBroker(), FakeContext()
    real_set = ctx.state.set

    async def slow_set(key, value):
        await asyncio.sleep(0.05)
        await real_set(key, value)
    ctx.state.set = slow_set
    a = await _started(_on(broker), _cfg(id_field="seq"), ctx)
    broker.publish("meters/door/reading", "open")
    await _take(a, 1)
    before = await ctx.state.get("mqtt.epoch")
    broker.forget()
    await _until(lambda: a.status["connects"] == 2 and a.status["subscribed"], what="the new session")
    broker.publish("meters/door/reading", '{"seq": 1}')       # its own id: it writes no place of its own
    rec = await asyncio.wait_for(a.records().__anext__(), 2)
    at_handover = await ctx.state.get("mqtt.epoch")
    await a.committed(rec)
    await a.stop()
    assert rec.record_id == "meters/door/reading#1"
    assert at_handover is not None and at_handover != before, "a record of the new session left before it was known"


# ── retained messages ────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("protocol", ["3.1.1", "5"])
async def test_a_retained_message_sent_at_subscription_is_not_a_record_by_default(protocol):
    """A broker sends a topic's retained message again whenever a subscription to it is made: it is not something
    published while the proxy was subscribed. It is acknowledged and passed over; MQTT 5 asks for none at all."""
    broker, ctx = M.FakeBroker(), FakeContext()
    broker.publish("meters/m1/reading", '{"kwh": 9}', retain=True)
    a = await _started(_on(broker), _cfg(protocol=protocol), ctx)
    broker.publish("meters/m1/reading", '{"kwh": 10}')
    got = await _take(a, 1)
    await a.stop()
    assert _ids(got) == ["seq-0"] and _data(got) == [{"kwh": 10}]
    if protocol == "5":
        assert broker.subscribes[0][2] == 2, "MQTT 5: retain handling 2, send no retained message"
        assert [mid for _, mid in broker.acks] == [1]
    else:
        assert [mid for _, mid in broker.acks] == [1, 2], "the retained copy is acknowledged, in order"


async def test_retained_take_names_a_retained_message_by_topic_and_content():
    broker, ctx = M.FakeBroker(), FakeContext()
    broker.publish("meters/m1/reading", '{"kwh": 9}', retain=True)
    a = await _started(_on(broker), _cfg(retained="take", protocol="5"), ctx)
    got = await _take(a, 1)
    broker.forget()                                  # subscribed to again: the broker sends the retained one again
    await _until(lambda: a.status["connects"] == 2 and a.status["subscribed"], what="the subscription again")
    again = await _take(a, 1)
    await a.stop()
    fp = hashlib.sha256(b"meters/m1/reading\x00" + b'{"kwh": 9}').hexdigest()[:16]
    assert _ids(got) == [f"meters/m1/reading#retained-{fp}"] == _ids(again)
    assert got[0].payload["retain"] is True
    assert broker.subscribes[0][2] == 1, "MQTT 5: retain handling 1, only for a subscription that is new"


# ── ids, payloads, properties ────────────────────────────────────────────────────────────────────────────────────────

async def test_the_publishers_own_id_names_the_record_and_a_publishers_retry_is_the_same_record():
    broker, ctx = M.FakeBroker(), FakeContext()
    a = await _started(_on(broker), _cfg(id_field="$.reading.seq"), ctx)
    broker.publish("meters/m1/reading", '{"reading": {"seq": 41, "kwh": 3}}')
    broker.publish("meters/m1/reading", '{"reading": {"seq": 41, "kwh": 3}}')    # the publisher sent it again
    broker.publish("meters/m2/reading", '{"reading": {"seq": 41, "kwh": 5}}')    # another meter's 41
    broker.publish("meters/m2/reading", '{"no": "id"}')
    got = await _take(a, 4)
    await a.stop()
    assert _ids(got) == ["meters/m1/reading#41", "meters/m1/reading#41", "meters/m2/reading#41", "seq-0"]


async def test_an_mqtt_5_user_property_can_name_the_record():
    broker, ctx = M.FakeBroker(), FakeContext()
    a = await _started(_on(broker), _cfg(protocol="5", id_property="message-id"), ctx)
    broker.publish("meters/m1/reading", '{"kwh": 3}', user_properties={"message-id": "m1-0007", "site": "HAM"},
                   content_type="application/json")
    got = await _take(a, 1)
    await a.stop()
    assert _ids(got) == ["meters/m1/reading#m1-0007"]
    assert got[0].payload["properties"] == {"user": {"message-id": "m1-0007", "site": "HAM"},
                                            "content_type": "application/json"}


def test_a_user_property_named_more_than_once_keeps_every_value_in_order():
    """MQTT 5 lets a name repeat among a message's user properties: a name given once maps to its value, one given
    more than once to the list of its values, in their order."""
    from theprotocol.proxy.sources.mqtt import user_properties
    assert user_properties([("site", "HAM"), ("tag", "a"), ("tag", "b"), ("tag", "c")]) == \
        {"site": "HAM", "tag": ["a", "b", "c"]}
    assert user_properties(None) == {} and user_properties([]) == {}


async def test_the_publishers_own_id_is_the_first_value_of_a_repeated_property():
    broker = M.FakeBroker()
    a = await _started(_on(broker), _cfg(protocol="5", id_property="message-id"), FakeContext())
    broker.publish("meters/m1/reading", '{"kwh": 3}', user_properties={"message-id": ["m1-0007", "m1-0008"]})
    got = await _take(a, 1)
    await a.stop()
    assert _ids(got) == ["meters/m1/reading#m1-0007"]
    assert got[0].payload["properties"]["user"] == {"message-id": ["m1-0007", "m1-0008"]}


@pytest.mark.parametrize("flt,topic,hit", [
    ("meters/+/reading", "meters/m1/reading", True), ("meters/+/reading", "meters/m1/status", False),
    ("meters/+/reading", "meters/m1/reading/raw", False), ("meters/#", "meters", True),
    ("meters/#", "meters/m1/reading", True), ("#", "meters/m1", True), ("#", "$SYS/broker/uptime", False),
    ("+/uptime", "$SYS/uptime", False), ("$SYS/#", "$SYS/broker/uptime", True), ("+/+", "/finance", True),
    ("meters/+", "meters/", True), ("meters", "meters/m1", False), ("$share/plant/meters/#", "meters/m1", True),
    ("$share/plant/meters/#", "plant/meters/m1", False)])
def test_a_topic_falls_under_a_filter_as_mqtt_says(flt, topic, hit):
    from theprotocol.proxy.sources.mqtt import topic_matches
    assert topic_matches(flt, topic) is hit


async def test_a_message_on_a_topic_no_filter_names_is_acknowledged_and_passed_over(caplog):
    """A session can hold a subscription the spec does not name (one an earlier spec made and an UNSUBSCRIBE that
    was lost, or another client under this client id). Its messages are not this source's records: each is
    acknowledged, in order, passed over and named in the log."""
    broker, ctx = M.FakeBroker(), FakeContext()
    a = await _started(_on(broker), _cfg(), ctx)
    broker.sessions[CID].subs["other/#"] = 1                 # a subscription the broker kept for this client id
    caplog.set_level(logging.WARNING)
    broker.publish("other/x", '{"i": 0}')
    broker.publish("meters/m1/reading", '{"i": 1}')
    got = await _take(a, 1)
    await a.stop()
    assert _ids(got) == ["seq-0"] and _data(got) == [{"i": 1}]
    assert [mid for _, mid in broker.acks] == [1, 2], "the message passed over is acknowledged, in its order"
    assert any("other/x" in r.getMessage() for r in caplog.records), "a message passed over must be named"


async def test_committed_knows_the_record_in_hand_by_its_id_and_names_one_it_does_not_hold(caplog):
    """The core may hand back an equal record rather than the same object (ingest copies it to fill its source); that
    commits it. A record that is not the one in hand sends no PUBACK, and says so."""
    broker = M.FakeBroker()
    a = await _started(_on(broker), _cfg(), FakeContext())
    broker.publish("meters/m1/reading", '{"i": 0}')
    broker.publish("meters/m1/reading", '{"i": 1}')
    agen = a.records()
    rec = await asyncio.wait_for(agen.__anext__(), 2)
    await a.committed(dataclasses.replace(rec, source="meters"))
    assert [mid for _, mid in broker.acks] == [1], "an equal record did not commit the record in hand"
    rec2 = await asyncio.wait_for(agen.__anext__(), 2)
    caplog.set_level(logging.WARNING)
    await a.committed(rec)                                   # the first one again: not the record in hand
    assert [mid for _, mid in broker.acks] == [1]
    assert any("not the record in hand" in r.getMessage() for r in caplog.records)
    await a.committed(rec2)
    await a.stop()
    assert [mid for _, mid in broker.acks] == [1, 2]


async def test_records_entered_again_before_the_commit_hand_over_the_record_in_hand_first():
    """The core starts a source's records() again after an error: the record it had not committed comes first, under
    the same id, and is acknowledged once when committed."""
    broker = M.FakeBroker()
    a = await _started(_on(broker), _cfg(), FakeContext())
    broker.publish("meters/m1/reading", '{"i": 0}')
    broker.publish("meters/m1/reading", '{"i": 1}')
    first = await asyncio.wait_for(a.records().__anext__(), 2)      # taken, never committed
    again = await _take(a, 2)
    await a.stop()
    assert first.record_id == "seq-0" and _ids(again) == ["seq-0", "seq-1"]
    assert [mid for _, mid in broker.acks] == [1, 2]


async def test_no_puback_goes_for_a_message_whose_place_is_not_on_disk():
    """While the state cannot be written, the message is not handed over and no PUBACK goes; once it can, the same
    message is the record, under the same id, acknowledged once."""
    broker, ctx = M.FakeBroker(), FakeContext()
    a = await _started(_on(broker), _cfg(), ctx)
    real_set, broken = ctx.state.set, [True]

    async def state_set(key, value):
        if broken[0] and key.startswith("mqtt.recent."):
            raise OSError("the state file cannot be written")
        await real_set(key, value)
    ctx.state.set = state_set
    broker.publish("meters/m1/reading", '{"i": 0}')
    with pytest.raises(OSError):
        await _take(a, 1)
    assert broker.acks == [], "a PUBACK went for a message whose place is not on disk"
    broken[0] = False
    got = await _take(a, 1)
    await a.stop()
    assert _ids(got) == ["seq-0"] and _data(got) == [{"i": 0}]
    assert [mid for _, mid in broker.acks] == [1]


@pytest.mark.parametrize("fmt,body,data,encoding", [
    ("json", b'{"kwh": 1}', {"kwh": 1}, "json"),
    ("json", b"42", 42, "json"),
    ("json", b"not json at all", "not json at all", "text"),
    ("json", b"\xff\xfe\x00binary", base64.b64encode(b"\xff\xfe\x00binary").decode(), "base64"),
    ("text", b'{"kwh": 1}', '{"kwh": 1}', "text"),
    ("bytes", b'{"kwh": 1}', base64.b64encode(b'{"kwh": 1}').decode(), "base64"),
])
async def test_a_payload_is_read_as_the_format_says_and_never_dropped(fmt, body, data, encoding):
    broker, ctx = M.FakeBroker(), FakeContext()
    a = await _started(_on(broker), _cfg(format=fmt), ctx)
    broker.publish("meters/m1/reading", body)
    got = await _take(a, 1)
    await a.stop()
    assert got[0].payload["data"] == data and got[0].payload["encoding"] == encoding
    json.dumps(got[0].payload)


# ── what it connects with ────────────────────────────────────────────────────────────────────────────────────────────

class _Recorder:
    """A link factory that records the settings and never connects."""

    def __init__(self):
        self.settings = []

    def __call__(self, source, settings):
        self.settings.append(settings)
        return self

    blocking_close = False

    def open(self):
        pass

    def close(self):
        pass


def _recording():
    rec = _Recorder()
    return rec, type("MqttRecorded", (MqttSource,), {"link_factory": staticmethod(rec)})


@pytest.mark.parametrize("protocol", ["3.1.1", "5"])
async def test_the_session_is_persistent_and_the_puback_waits_for_the_commit(protocol):
    rec, cls = _recording()
    src = cls(_cfg(protocol=protocol, username="proxy", password="env:MQTT_PW"),
              FakeContext(secrets={"env:MQTT_PW": "the-password"}))
    await src.start()
    await src.stop()
    s = rec.settings[0]
    assert (s.host, s.port, s.protocol, s.client_id) == ("broker.test", 1883, protocol, CID)
    assert s.clean is False and s.manual_ack is True
    assert s.session_expiry_s == 0xFFFFFFFF, "the session outlives a disconnect (MQTT 5: never expires)"
    assert (s.username, s.password) == ("proxy", "the-password")
    assert "the-password" not in repr(s), "a settings object must never print its password"
    assert s.tls is None


async def test_a_dry_run_takes_neither_the_session_nor_its_messages():
    """A dry run with the running proxy's client id would take its session over (and the broker would disconnect the
    running proxy); it connects as its own clean session and acknowledges what it reads, since it keeps nothing."""
    rec, cls = _recording()
    src = cls(_cfg(), FakeContext(dry_run=True))
    await src.start()
    await src.stop()
    s = rec.settings[0]
    assert s.client_id == f"{CID}-dry-run" and s.clean is True and s.manual_ack is False


async def test_a_dry_run_subscribes_a_shared_subscription_as_its_plain_filter():
    """A shared subscription ($share/<group>/<filter>) hands each message to one member of the group: a dry run that
    joined the group would take some of the running proxy's messages. It subscribes the plain filter instead, which
    gets a copy of each and takes nothing; the running proxy keeps its place in the group."""
    broker = M.FakeBroker()
    topics = ["$share/plant/meters/+/reading", "meters/+/reading", "$share/other/alarms/#"]
    live = await _started(_on(broker), _cfg(topics=topics), FakeContext())
    dry = await _started(_on(broker), _cfg(topics=topics), FakeContext(dry_run=True))
    broker.publish("alarms/m1/hot", "hot")
    seen = await _take(dry, 1)
    await dry.stop()
    await live.stop()
    subs = {cid: sorted(f for f, _ in items) for cid, items, _ in broker.subscribes}
    assert subs[CID] == ["$share/other/alarms/#", "$share/plant/meters/+/reading", "meters/+/reading"]
    assert subs[f"{CID}-dry-run"] == ["alarms/#", "meters/+/reading"], \
        "a dry run joined a shared subscription's group: it would take messages from the running proxy"
    assert seen[0].payload["data"] == "hot"


async def test_tls_uses_the_tls_port_and_verifies_the_broker(tmp_path):
    pki = _pki(tmp_path)
    rec, cls = _recording()
    src = cls(_cfg(tls={"ca_file": pki["ca"], "cert_file": pki["cert"], "private_key": "file:/k/meters.key"}),
              FakeContext(secrets={"file:/k/meters.key": pki["key_pem"]}))
    await src.start()
    await src.stop()
    s = rec.settings[0]
    assert s.port == 8883 and isinstance(s.tls, ssl.SSLContext)
    assert s.tls.check_hostname is True and s.tls.verify_mode == ssl.CERT_REQUIRED
    assert s.tls.verify_flags & ssl.VERIFY_X509_STRICT, \
        "strict on every Python: 3.13 and later refuse what 3.10 to 3.12 would take otherwise"


@pytest.mark.parametrize("conf,match", [
    ({"protocol": "3.1"}, "protocol"),
    ({"topics": []}, "topics"),
    ({"topics": ["meters/#/reading"]}, "#"),
    ({"topics": ["meters/m1#"]}, "#"),
    ({"topics": ["meters/+m1/reading"]}, r"\+"),
    ({"topics": [""]}, "topic"),
    ({"topics": ["a/#", "a/#"]}, "twice"),
    ({"client_id": ""}, "client_id"),
    ({"password": "env:X"}, "username"),
    ({"tls": {"cert_file": "/c.crt"}}, "private_key"),
    ({"tls": {"private_key": "env:K"}}, "cert_file"),
    ({"format": "xml"}, "format"),
    ({"retained": "keep"}, "retained"),
    ({"id_property": "message-id"}, "id_property"),                    # MQTT 3.1.1 has no user properties
    ({"protocol": 4}, "protocol"),
])
def test_a_config_that_cannot_work_is_refused_at_construction(conf, match):
    with pytest.raises(PluginError, match=match):
        MqttSource(_cfg(**conf), FakeContext())


async def test_protocol_5_may_be_written_as_a_number(tmp_path):
    """YAML reads `protocol: 5` as a number: the spec takes it as MQTT 5, as it takes the string."""
    from theprotocol.proxy.spec import parse
    doc = F.spec_doc(tmp_path, sources={"meters": {"type": "mqtt", "config": _cfg(protocol=5)}},
                     mappings=[{"name": "reading", "version": 1, "from": "meters", "to": "attest",
                                "fields": {"kwh": "$.payload.data.kwh"}}])
    spec = parse(doc, base=tmp_path)
    rec, cls = _recording()
    src = cls(spec.sources["meters"].config, FakeContext())
    await src.start()
    await src.stop()
    assert rec.settings[0].protocol == "5"


async def test_it_cannot_read_again_from_a_point():
    with pytest.raises(PluginError, match="retained"):
        await MqttSource(_cfg(), FakeContext()).rewind("start")


async def test_without_paho_it_says_which_extra_to_install(monkeypatch):
    for name in [m for m in list(sys.modules) if m == "paho" or m.startswith("paho.")]:
        monkeypatch.delitem(sys.modules, name)
    monkeypatch.setitem(sys.modules, "paho", None)
    src = MqttSource(_cfg(), FakeContext())
    with pytest.raises(PluginError, match=r"proxy-mqtt"):
        await src.start()
    await src.stop()


# ── the paho link, without a broker (paho-mqtt is the proxy-mqtt extra; these skip without it) ───────────────────────

class _LinkCalls:
    """What a PahoLink calls on its source, recorded."""

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        if name.startswith("_link_"):
            return lambda *args: self.calls.append((name, args))
        raise AttributeError(name)


def _settings(protocol, *, clean=False):
    from theprotocol.proxy.sources.mqtt import Settings
    return Settings(host="broker.test", port=1883, protocol=protocol, client_id=CID, clean=clean,
                    session_expiry_s=0xFFFFFFFF, keepalive_s=60, manual_ack=not clean)


@pytest.mark.parametrize("protocol", ["3.1.1", "5"])
@pytest.mark.parametrize("dry", [False, True])
def test_the_paho_link_asks_for_the_session_the_source_needs(protocol, dry, monkeypatch):
    """A running proxy: a persistent session (3.1.1 clean session 0; 5 clean start 0 and a session that never
    expires), at most 128 QoS 1 messages in flight on MQTT 5, and the PUBACK sent by the source. A dry run: a clean
    session of its own, acknowledged by paho on receipt."""
    pytest.importorskip("paho.mqtt.client")
    import paho.mqtt.client as mqtt
    from theprotocol.proxy.sources.mqtt import PahoLink
    link = PahoLink(_LinkCalls(), _settings(protocol, clean=dry))
    opened = {}
    monkeypatch.setattr(link._client, "connect_async", lambda *a, **kw: opened.update(args=a, kw=kw))
    monkeypatch.setattr(link._client, "loop_start", lambda: None)
    link.open()
    assert opened["args"] == ("broker.test", 1883, 60)
    assert link._client._manual_ack is (not dry)
    if protocol == "5":
        assert link._client._protocol == mqtt.MQTTv5
        assert opened["kw"]["clean_start"] is dry
        props = opened["kw"]["properties"]
        assert props.SessionExpiryInterval == (0 if dry else 0xFFFFFFFF)
        assert props.ReceiveMaximum == 128
    else:
        assert link._client._protocol == mqtt.MQTTv311
        assert link._client._clean_session is dry
        assert "properties" not in opened["kw"]


def test_the_paho_link_keeps_the_brokers_refusal_as_the_reason_for_the_disconnect():
    pytest.importorskip("paho.mqtt.client")
    from paho.mqtt.packettypes import PacketTypes
    from paho.mqtt.reasoncodes import ReasonCode
    from theprotocol.proxy.sources.mqtt import PahoLink
    calls = _LinkCalls()
    link = PahoLink(calls, _settings("5"))
    flags = type("Flags", (), {"session_present": False})()
    link._on_pre_connect(None, None)
    link._on_connect(None, None, flags, ReasonCode(PacketTypes.CONNACK, "Not authorized"), None)
    link._on_disconnect(None, None, flags, ReasonCode(PacketTypes.DISCONNECT, "Unspecified error"), None)
    assert [name for name, _ in calls.calls] == ["_link_refused", "_link_lost"]
    assert "Not authorized" in calls.calls[0][1][0] and calls.calls[1][1] == calls.calls[0][1]


def test_the_paho_link_hands_over_a_message_with_its_properties():
    pytest.importorskip("paho.mqtt.client")
    import paho.mqtt.client as mqtt
    from paho.mqtt.packettypes import PacketTypes
    from paho.mqtt.properties import Properties
    from theprotocol.proxy.sources.mqtt import Delivery, PahoLink
    calls = _LinkCalls()
    link = PahoLink(calls, _settings("5"))
    props = Properties(PacketTypes.PUBLISH)
    props.UserProperty = [("site", "HAM"), ("tag", "a"), ("tag", "b")]
    props.ContentType = "application/json"
    msg = mqtt.MQTTMessage(mid=7, topic=b"meters/m1/reading")
    msg.payload, msg.qos, msg.dup, msg.retain, msg.properties = b'{"kwh": 1}', 1, True, False, props
    link._on_message(None, None, msg)
    assert calls.calls == [("_link_message", (Delivery(
        topic="meters/m1/reading", payload=b'{"kwh": 1}', qos=1, mid=7, dup=True, retain=False,
        user_properties={"site": "HAM", "tag": ["a", "b"]}, content_type="application/json"),))]


# ── finishing ────────────────────────────────────────────────────────────────────────────────────────────────────────

async def test_by_default_it_waits_for_messages_until_stopped():
    broker = M.FakeBroker()
    a = await _started(_on(broker), _cfg(), FakeContext())
    with pytest.raises(asyncio.TimeoutError):
        await _take(a, 1, timeout=0.3)
    await a.stop()


async def test_finish_after_idle_drains_what_the_broker_kept_and_ends():
    broker, ctx = M.FakeBroker(), FakeContext()
    cls = _on(broker)
    a = await _started(cls, _cfg(), ctx)
    await a.stop()
    for i in range(3):
        broker.publish("meters/m1/reading", json.dumps({"i": i}))       # kept for the session while it is away
    b = cls(_cfg(finish_after_idle_s=0.2), ctx)
    await b.start()
    got = []
    async for rec in b.records():
        got.append(rec)
        await b.committed(rec)
    await b.stop()
    assert _ids(got) == ["seq-0", "seq-1", "seq-2"]


async def test_the_quiet_does_not_count_before_the_broker_answers():
    """A broker that is not reachable is not a quiet broker: --once must not finish as if it had drained one."""
    rec, cls = _recording()
    src = cls(_cfg(finish_after_idle_s=0.05), FakeContext())
    await src.start()
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(src.records().__anext__(), 0.4)
    await src.stop()


# ── TLS material ─────────────────────────────────────────────────────────────────────────────────────────────────────

def _pki(tmp_path, *, password=None):
    """A CA, and a client certificate and key it signed, made at run time (no key is kept in the repository)."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    now = datetime.now(timezone.utc)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test plant CA")])
    ca = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name).public_key(ca_key.public_key())
          .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=1))
          .not_valid_after(now + timedelta(days=1))
          .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True).sign(ca_key, hashes.SHA256()))
    key = ec.generate_private_key(ec.SECP256R1())
    cert = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "meters")]))
            .issuer_name(ca_name).public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(days=1))
            .sign(ca_key, hashes.SHA256()))
    enc = (serialization.BestAvailableEncryption(password.encode()) if password else serialization.NoEncryption())
    (tmp_path / "ca.crt").write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    (tmp_path / "meters.crt").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    other = ec.generate_private_key(ec.SECP256R1())
    return {"ca": str(tmp_path / "ca.crt"), "cert": str(tmp_path / "meters.crt"),
            "key_pem": key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, enc).decode(),
            "other_key_pem": other.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                 serialization.NoEncryption()).decode()}


def test_the_private_key_is_loaded_from_memory_where_the_system_allows(tmp_path, monkeypatch):
    if not hasattr(os, "memfd_create"):
        pytest.skip("no memfd_create on this system")
    pki = _pki(tmp_path)
    made = []
    real = os.memfd_create
    monkeypatch.setattr(os, "memfd_create", lambda *a, **k: made.append(a) or real(*a, **k))
    ctx = tls_context(ca_file=pki["ca"], cert_file=pki["cert"], private_key=pki["key_pem"])
    assert isinstance(ctx, ssl.SSLContext) and made, "the key went through a file on disk"


def test_without_memfd_the_key_passes_through_a_private_file_that_is_removed(tmp_path, monkeypatch):
    import tempfile
    pki = _pki(tmp_path)
    monkeypatch.delattr(os, "memfd_create", raising=False)
    scratch = tmp_path / "tmp"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    ctx = tls_context(ca_file=pki["ca"], cert_file=pki["cert"], private_key=pki["key_pem"])
    assert isinstance(ctx, ssl.SSLContext)
    assert list(scratch.iterdir()) == [], "the key's file outlived the loading"


def test_an_encrypted_key_needs_its_password(tmp_path):
    pki = _pki(tmp_path, password="key-pass-for-tests")
    assert tls_context(ca_file=pki["ca"], cert_file=pki["cert"], private_key=pki["key_pem"],
                       key_password="key-pass-for-tests")
    with pytest.raises(PluginError, match="private key"):
        tls_context(ca_file=pki["ca"], cert_file=pki["cert"], private_key=pki["key_pem"], key_password="wrong")


def test_a_key_that_is_not_the_certificates_is_refused(tmp_path):
    pki = _pki(tmp_path)
    with pytest.raises(PluginError, match="private key"):
        tls_context(ca_file=pki["ca"], cert_file=pki["cert"], private_key=pki["other_key_pem"])


def test_a_ca_file_that_is_not_there_is_refused(tmp_path):
    with pytest.raises(PluginError, match="ca_file"):
        tls_context(ca_file=str(tmp_path / "nope.crt"))


# ── through the core ─────────────────────────────────────────────────────────────────────────────────────────────────

async def test_through_the_runtime_each_reading_is_attested_once_across_restarts_and_a_lost_puback(tmp_path,
                                                                                                    monkeypatch):
    """The proxy as it runs: the outbox, its keys and the attestation action, over two restarts. The second restart
    follows a PUBACK lost after the commit, so the broker sends that reading again and the outbox keeps it once."""
    from theprotocol.proxy.runtime import Proxy
    from theprotocol.proxy.spec import parse
    broker = M.FakeBroker()
    monkeypatch.setattr(MqttSource, "link_factory", staticmethod(broker.link))
    reg = F.FakeRegistry()
    doc = F.spec_doc(tmp_path, sources={"meters": {"type": "mqtt", "config": _cfg()}},
                     mappings=[{"name": "reading", "version": 1, "from": "meters", "to": "attest",
                                "fields": {"meter": "$.payload.levels.1", "kwh": "$.payload.data.kwh"}}])

    async def run_until(n_effects, publish=()):
        p = Proxy(parse(doc, base=tmp_path), transport=reg.transport, service=False, poll_s=0.01)
        stop = asyncio.Event()
        task = asyncio.ensure_future(p.run(stop=stop))
        await _until(lambda: p.sources["meters"].status["subscribed"], what="the proxy's subscription")
        for topic, body in publish:
            broker.publish(topic, body)
        await _until(lambda: len(reg.effects) >= n_effects and not p.outbox.due(limit=1), timeout=5,
                     what=f"{n_effects} attestations")
        stop.set()
        await task
        counters = dict(p.counters)
        p.close()
        return counters

    await run_until(2, [("meters/m1/reading", '{"kwh": 1}'), ("meters/m2/reading", '{"kwh": 2}')])
    broker.publish("meters/m1/reading", '{"kwh": 3}')                   # while the proxy is down
    broker.lose_acks = 1
    await run_until(4, [("meters/m2/reading", '{"kwh": 4}')])           # the PUBACK of the 3 is lost
    assert broker.lost_acks == [(CID, 3)]
    counters = await run_until(5, [("meters/m3/reading", '{"kwh": 5}')])
    claims = [e["attestation_data"]["claim"] for e in reg.effects]
    assert claims == [{"meter": "m1", "kwh": 1}, {"meter": "m2", "kwh": 2}, {"meter": "m1", "kwh": 3},
                      {"meter": "m2", "kwh": 4}, {"meter": "m3", "kwh": 5}], "a reading lost or attested twice"
    assert counters[("tp_proxy_records_repeated_total", (("mapping", "reading"), ("source", "meters")))] == 1, \
        "the copy the broker sent again was not dropped by the outbox's key"
