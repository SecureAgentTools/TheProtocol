"""V0659 (a): TheProtocol Proxy's core, driven against a fake registry (tests/proxy_fake.py), no network.

What the order asks the core to prove: exactly-once across a restart (a lost answer is sent again with the same
Idempotency-Key and kept once; a record read again is not written twice), the secret refusal (tests/test_proxy_spec.py),
a dry run sends nothing and moves no cursor, the dead letters and their replay, the breaker; with the pause, the rate
limits, the key rule on every write, the identity's token renewal, and an outbound mapping to a sink. Red before V0659:
theprotocol.proxy.runtime does not exist.
"""
from __future__ import annotations

import asyncio
import time

import pytest

import proxy_fake as F


@pytest.fixture(autouse=True)
def fake_plugins(monkeypatch):
    from theprotocol.proxy import plugins
    monkeypatch.setitem(plugins.BUILTINS["source"], "list_source", "proxy_fake:ListSource")
    monkeypatch.setitem(plugins.BUILTINS["action"], "keyless", "proxy_fake:KeylessAction")
    monkeypatch.setitem(plugins.BUILTINS["sink"], "list_sink", "proxy_fake:ListSink")


def _proxy(tmp_path, reg, doc=None, **kw):
    from theprotocol.proxy.runtime import Proxy
    from theprotocol.proxy.spec import parse
    spec = parse(doc or F.spec_doc(tmp_path, items=[{"id": "r1", "v": 1}]), base=tmp_path)
    return Proxy(spec, transport=reg.transport, service=False, poll_s=0.01, **kw)


async def _drain(p):
    """Run the proxy until every source finished and nothing is due (bounded)."""
    await asyncio.wait_for(p.run(until_idle=True), timeout=10)


# ── the happy path ───────────────────────────────────────────────────────────────────────────────────────────────────

async def test_a_record_is_attested_once_with_its_key_and_the_cursor_moves_after_the_row(tmp_path):
    reg = F.FakeRegistry()
    p = _proxy(tmp_path, reg, F.spec_doc(tmp_path, items=[{"id": "r1", "v": 4.2}, {"id": "r2", "v": 5.0}]))
    await _drain(p)
    assert [e["attestation_data"]["claim"] for e in reg.effects] == [{"value": 4.2, "id": "r1"},
                                                                     {"value": 5.0, "id": "r2"}]
    keys = [c["key"] for c in reg.writes()]
    assert len(keys) == 2 and all(k and k.startswith("tpx-") for k in keys)
    # the key is in what the ledger hashes: two records that said the same would be two attestations
    assert [e["attestation_data"]["record"] for e in reg.effects] == keys
    assert reg.effects[0]["target_agent_did"] == F.DID and reg.effects[0]["attestation_type"] == "test.reading"
    assert p.outbox.counts() == {"pending": 0, "done": 2, "dead": 0}
    assert p.outbox.state_get("source:feed", "cursor") == "r2"
    assert p.outbox.get(keys[0]).outcome["reference"] == "att-1"
    p.close()


async def test_a_record_read_again_is_not_written_or_sent_twice(tmp_path):
    reg = F.FakeRegistry()
    doc = F.spec_doc(tmp_path, items=[{"id": "r1", "v": 1}])
    doc["sources"]["feed"]["config"]["replay_all"] = True
    for _ in range(3):
        p = _proxy(tmp_path, reg, doc)
        await _drain(p)
        p.close()
    assert len(reg.effects) == 1 and len(reg.writes()) == 1
    p = _proxy(tmp_path, reg, doc)
    from theprotocol.proxy.plugins import Record
    keys = await p.ingest("feed", Record(record_id="r1", payload={"id": "r1", "v": 1}))
    assert keys == [] and p.outbox.counts()["done"] == 1
    p.close()


# ── exactly-once across a restart ────────────────────────────────────────────────────────────────────────────────────

async def test_a_lost_answer_is_sent_again_after_a_restart_with_the_same_key_and_kept_once(tmp_path):
    reg = F.FakeRegistry()
    reg.lose_answers = 1        # the registry keeps the attestation; its answer never reaches the proxy
    doc = F.spec_doc(tmp_path, items=[{"id": "r1", "v": 1}])
    doc["sources"]["feed"]["config"]["replay_all"] = True     # and the source reads the record again on restart
    p = _proxy(tmp_path, reg, doc)
    await p.start()
    from theprotocol.proxy.plugins import Record
    await p.ingest("feed", Record(record_id="r1", payload={"id": "r1", "v": 1}))
    assert await p.dispatch_once() == 1
    row = p.outbox.due(limit=10, now=time.time() + 60)[0]
    assert row.status == "pending" and row.attempts == 1 and "no answer in time" in row.last_error
    await p.stop()
    p.close()                   # the process ends here, the attestation kept, the proxy not knowing it

    p2 = _proxy(tmp_path, reg, doc)
    await asyncio.sleep(0.06)   # past the row's backoff
    await _drain(p2)
    assert len(reg.effects) == 1, "kept once"
    sent = reg.writes()
    assert len(sent) == 2 and sent[0]["key"] == sent[1]["key"], "sent again with the same Idempotency-Key"
    assert p2.outbox.counts() == {"pending": 0, "done": 1, "dead": 0}
    assert p2.outbox.get(sent[0]["key"]).outcome["reference"] == "att-1"
    p2.close()


async def test_a_record_whose_cursor_did_not_move_before_a_crash_is_one_row(tmp_path):
    reg = F.FakeRegistry()
    doc = F.spec_doc(tmp_path, items=[{"id": "r1", "v": 1}])
    p = _proxy(tmp_path, reg, doc)
    from theprotocol.proxy.plugins import Record
    await p.ingest("feed", Record(record_id="r1", payload={"id": "r1", "v": 1}))   # on disk, the cursor not moved
    p.close()
    p2 = _proxy(tmp_path, reg, doc)
    await _drain(p2)            # the source yields r1 again (its cursor is empty): the same key, no new row
    assert len(reg.effects) == 1 and p2.outbox.counts()["done"] == 1
    p2.close()


async def test_the_ledgers_409_for_the_same_data_is_done(tmp_path):
    reg = F.FakeRegistry()
    p = _proxy(tmp_path, reg)
    from theprotocol.proxy.plugins import Record
    keys = await p.ingest("feed", Record(record_id="r1", payload={"id": "r1", "v": 1}))
    import hashlib
    import json
    reg.by_key.clear()          # the registry lost its answer for the key (an expired record), the ledger kept the hash
    reg.hashes.add(hashlib.sha256(json.dumps({"claim": {"value": 1, "id": "r1"}, "record": keys[0]},
                                             sort_keys=True).encode()).hexdigest())
    await p.dispatch_once()
    row = p.outbox.get(keys[0])
    assert row.status == "done" and "already on the ledger" in row.outcome["detail"]
    p.close()


# ── dry run ──────────────────────────────────────────────────────────────────────────────────────────────────────────

async def test_a_dry_run_sends_nothing_moves_no_cursor_and_shows_what_it_would_send(tmp_path):
    reg = F.FakeRegistry()
    doc = F.spec_doc(tmp_path, items=[{"id": "r1", "v": 1}, {"id": "r2", "v": 2}])
    real = _proxy(tmp_path, reg, doc)
    from theprotocol.proxy.plugins import Record
    await real.ingest("feed", Record(record_id="r1", payload={"id": "r1", "v": 1}))
    real.outbox.state_set("source:feed", "cursor", "r1")
    before = (real.outbox.counts(), real.outbox.state_get("source:feed", "cursor"))
    real.close()

    shown = []
    dry = _proxy(tmp_path, reg, doc, dry_run=True, report=shown.append)
    await _drain(dry)
    assert reg.calls == [], "a dry run calls nothing: no token, no write"
    assert [s["record_id"] for s in shown] == ["r2"], "it reads on from the real cursor"
    assert shown[0]["status"] == "dry_run" and shown[0]["data"]["request"]["attestation_data"]["claim"] == \
        {"value": 2, "id": "r2"}
    dry.close()

    again = _proxy(tmp_path, reg, doc)
    assert (again.outbox.counts(), again.outbox.state_get("source:feed", "cursor")) == before
    again.close()


async def test_a_plugin_that_writes_in_a_dry_run_is_stopped_at_the_core(tmp_path):
    from theprotocol.proxy.plugins import PluginError
    reg = F.FakeRegistry()
    p = _proxy(tmp_path, reg, dry_run=True)
    with pytest.raises(PluginError, match="a dry run sends nothing"):
        await p.client.call("POST", "/api/v1/teg/attestations/submit", json={}, idempotency_key="k", dry_run=True)
    assert reg.calls == []
    p.close()


# ── the dead letters and replay ──────────────────────────────────────────────────────────────────────────────────────

async def test_a_refusal_goes_to_the_dead_letters_with_the_answer_and_replay_sends_it_after_the_fix(tmp_path):
    reg = F.FakeRegistry()
    reg.mode = "refuse"
    p = _proxy(tmp_path, reg)
    await _drain(p)
    dead = p.outbox.dead_letters()
    assert len(dead) == 1 and "HTTP 403" in dead[0].last_error and "reputation.signal" in dead[0].last_error
    assert dead[0].answer == {"detail": "Agent lacks permission: reputation.signal"}
    assert reg.effects == []
    p.close()

    reg.mode = "ok"             # the owner granted the attestor role
    p = _proxy(tmp_path, reg)
    assert p.outbox.replay(mapping="reading") == 1
    await _drain(p)
    assert len(reg.effects) == 1 and p.outbox.counts() == {"pending": 0, "done": 1, "dead": 0}
    assert {c["key"] for c in reg.writes()} == {dead[0].key}, "the same record, the same key"
    p.close()


async def test_a_record_the_mapping_cannot_map_is_dead_at_once_and_a_replay_maps_it_with_the_fixed_mapping(tmp_path):
    reg = F.FakeRegistry()
    doc = F.spec_doc(tmp_path, items=[{"id": "r1", "v": 1}],
                     mappings=[{"name": "reading", "version": 1, "from": "feed", "to": "attest",
                                "fields": {"value": "$.payload.v", "unit": "$.payload.unit"}}])
    p = _proxy(tmp_path, reg, doc)
    await _drain(p)
    dead = p.outbox.dead_letters()
    assert len(dead) == 1 and "$.payload.unit" in dead[0].last_error and dead[0].mapped is None
    assert reg.writes() == []
    p.close()

    doc["mappings"][0]["fields"]["unit"] = {"path": "$.payload.unit", "default": "kWh"}
    p = _proxy(tmp_path, reg, doc)
    p.outbox.replay(keys=[dead[0].key])
    await _drain(p)
    assert reg.effects[0]["attestation_data"]["claim"] == {"value": 1, "unit": "kWh"}
    assert p.outbox.get(dead[0].key).mapped == {"value": 1, "unit": "kWh"}
    p.close()


async def test_a_transient_failure_is_retried_then_given_up_to_the_dead_letters(tmp_path):
    reg = F.FakeRegistry()
    reg.mode = "down"
    doc = F.spec_doc(tmp_path, items=[{"id": "r1", "v": 1}])
    doc["breaker"] = {"refusals": 9, "failures": 99, "cooldown_s": 0.01}
    p = _proxy(tmp_path, reg, doc)
    await p.start()
    from theprotocol.proxy.plugins import Record
    await p.ingest("feed", Record(record_id="r1", payload={"id": "r1", "v": 1}))
    for _ in range(40):
        await p.dispatch_once()
        if p.outbox.counts()["dead"]:
            break
        await asyncio.sleep(0.02)
    dead = p.outbox.dead_letters()
    assert len(dead) == 1 and dead[0].last_error.startswith("gave up after 4 attempts: HTTP 503")
    assert len(reg.writes()) == 4
    await p.stop()
    p.close()


# ── the breaker ──────────────────────────────────────────────────────────────────────────────────────────────────────

async def test_the_breaker_stops_a_mapping_after_repeated_refusals_says_why_and_resume_reopens_it(tmp_path):
    reg = F.FakeRegistry()
    reg.mode = "refuse"
    items = [{"id": f"r{i}", "v": i} for i in range(6)]
    p = _proxy(tmp_path, reg, F.spec_doc(tmp_path, items=items))
    await _drain(p)
    br = p.outbox.switch("breaker:reading")
    assert br["state"] == "stopped" and "reputation.signal" in br["why"] and br["refusals"] == 3
    assert len(reg.writes()) == 3, "stopped after three refusals: the other three were not sent"
    assert p.outbox.counts() == {"pending": 3, "done": 0, "dead": 3}
    st = p.status()["mappings"]["reading"]
    assert st["breaker"]["state"] == "stopped"
    p.close()

    reg.mode = "ok"
    p = _proxy(tmp_path, reg, F.spec_doc(tmp_path, items=items))
    await p.dispatch_once()
    assert len(reg.writes()) == 3, "a stopped breaker holds across a restart"
    p.outbox.set_switch("breaker:reading", None)          # tp-proxy resume reading
    await _drain(p)
    assert p.outbox.counts() == {"pending": 0, "done": 3, "dead": 3} and len(reg.effects) == 3
    p.close()


async def test_transient_failures_cool_a_mapping_down_and_it_tries_one_call_again(tmp_path):
    reg = F.FakeRegistry()
    reg.mode = "down"
    clock = [time.time()]
    doc = F.spec_doc(tmp_path, items=[{"id": f"r{i}", "v": i} for i in range(5)])
    doc["retry"] = {"first_s": 0.001, "max_s": 300, "attempts": 50}
    doc["breaker"] = {"refusals": 9, "failures": 3, "cooldown_s": 30}
    p = _proxy(tmp_path, reg, doc, clock=lambda: clock[0])
    await p.start()
    from theprotocol.proxy.plugins import Record
    for it in doc["sources"]["feed"]["config"]["items"]:
        await p.ingest("feed", Record(record_id=it["id"], payload=it))
    await p.dispatch_once()
    br = p.outbox.switch("breaker:reading")
    assert br["state"] == "cooling" and "HTTP 503" in br["why"] and len(reg.writes()) == 3
    clock[0] += 5
    assert await p.dispatch_once() == 0 and len(reg.writes()) == 3, "nothing while it cools"
    clock[0] += 30
    await p.dispatch_once()
    assert len(reg.writes()) == 4, "one call after the cooldown"
    br2 = p.outbox.switch("breaker:reading")
    assert br2["state"] == "cooling" and br2["until"] - br2["since"] == pytest.approx(60), "twice as long"
    reg.mode = "ok"
    clock[0] += 61
    for _ in range(3):
        await p.dispatch_once()
    assert p.outbox.switch("breaker:reading") is None and p.outbox.counts()["done"] == 5
    await p.stop()
    p.close()


# ── pause, rate limits, the key rule ─────────────────────────────────────────────────────────────────────────────────

async def test_a_paused_proxy_takes_records_in_and_sends_nothing_until_resumed(tmp_path):
    reg = F.FakeRegistry()
    p = _proxy(tmp_path, reg, F.spec_doc(tmp_path, items=[{"id": "r1", "v": 1}]))
    await p.start()
    p.outbox.set_switch("pause:reading", True)
    from theprotocol.proxy.plugins import Record
    await p.ingest("feed", Record(record_id="r1", payload={"id": "r1", "v": 1}))
    assert await p.dispatch_once() == 0 and reg.writes() == [] and p.outbox.counts()["pending"] == 1
    p.outbox.set_switch("pause:reading", None)
    p.outbox.set_switch("pause", True)
    assert await p.dispatch_once() == 0
    p.outbox.set_switch("pause", None)
    assert await p.dispatch_once() == 1 and len(reg.effects) == 1
    await p.stop()
    p.close()


async def test_the_rate_limit_holds_an_action_to_its_per_minute(tmp_path):
    reg = F.FakeRegistry()
    clock = [time.time()]
    doc = F.spec_doc(tmp_path)
    doc["actions"]["attest"]["limits"] = {"per_minute": 2}
    p = _proxy(tmp_path, reg, doc, clock=lambda: clock[0])
    await p.start()
    from theprotocol.proxy.plugins import Record
    for i in range(5):
        await p.ingest("feed", Record(record_id=f"r{i}", payload={"id": f"r{i}", "v": i}))
    assert await p.dispatch_once() == 2
    assert await p.dispatch_once() == 0
    clock[0] += 61
    assert await p.dispatch_once() == 2 and len(reg.effects) == 4
    await p.stop()
    p.close()


async def test_a_write_without_the_records_key_is_refused_before_it_leaves(tmp_path):
    reg = F.FakeRegistry()
    doc = F.spec_doc(tmp_path, items=[{"id": "r1", "v": 1}], actions={"attest": {"type": "keyless"}})
    p = _proxy(tmp_path, reg, doc)
    await _drain(p)
    dead = p.outbox.dead_letters()
    assert len(dead) == 1 and "without the record's key" in dead[0].last_error
    assert reg.writes() == [], "nothing reached the registry"
    p.close()


async def test_a_source_that_calls_theprotocol_is_refused(tmp_path):
    from theprotocol.proxy.plugins import PluginError
    reg = F.FakeRegistry()
    p = _proxy(tmp_path, reg)
    with pytest.raises(PluginError, match="a source only reads"):
        await p.sources["feed"].ctx.call("GET", "/api/v1/agents")
    p.close()


# ── the identity ─────────────────────────────────────────────────────────────────────────────────────────────────────

async def test_the_token_is_renewed_before_it_expires_and_asked_for_again_after_a_401(tmp_path):
    clock = [time.time()]
    reg = F.FakeRegistry(token_ttl=300, clock=lambda: clock[0])
    p = _proxy(tmp_path, reg, clock=lambda: clock[0])
    await p.start()
    assert p.identity.issued == 1
    from theprotocol.proxy.plugins import Record
    await p.ingest("feed", Record(record_id="r1", payload={"id": "r1", "v": 1}))
    await p.dispatch_once()
    assert p.identity.issued == 1, "the token is used while it is fresh"
    clock[0] += 200                              # inside its last two minutes: renewed before the call
    await p.ingest("feed", Record(record_id="r2", payload={"id": "r2", "v": 2}))
    await p.dispatch_once()
    assert p.identity.issued == 2
    reg.reject_tokens.update(reg.tokens)         # the registry stops taking it (a logout elsewhere)
    await p.ingest("feed", Record(record_id="r3", payload={"id": "r3", "v": 3}))
    await p.dispatch_once()
    assert p.identity.issued == 3 and len(reg.effects) == 3, "asked for again once, and the call went through"
    await p.stop()
    p.close()


async def test_with_ironhand_on_the_proxy_enrolls_presents_its_svid_and_renews_it_with_its_current_token(tmp_path):
    reg = F.FakeRegistry()
    reg.svid_ttl = 1            # always inside its margin: each renewal tick enrolls again
    doc = F.spec_doc(tmp_path)
    doc["identity"]["mtls"] = {"enabled": True, "dir": "certs"}
    p = _proxy(tmp_path, reg, doc)
    await p.start()
    try:
        assert len(reg.enrollments) == 1 and (tmp_path / "certs" / "svid.pem").exists()
        assert p.identity.client_cert() == (str(tmp_path / "certs" / "svid.pem"), str(tmp_path / "certs" / "key.pem"))
        from theprotocol.proxy.plugins import Record
        await p.ingest("feed", Record(record_id="r1", payload={"id": "r1", "v": 1}))
        assert await p.dispatch_once() == 1 and len(reg.effects) == 1, "the calls go out with the SVID presented"
        assert p.client._cert == p.identity.client_cert()
        p.identity.invalidate()                      # the next renewal must ask for the token as it is then
        p._svid_task.cancel()
        p._svid_task = p.identity.start_svid_renewal(check_interval=0.01)
        for _ in range(100):
            if len(reg.enrollments) >= 2:
                break
            await asyncio.sleep(0.01)
        assert len(reg.enrollments) >= 2 and reg.enrollments[-1] != reg.enrollments[0], \
            "renewed with a fresh token, not the one it started with"
    finally:
        await p.stop()
        p.close()


async def test_credentials_the_registry_refuses_stop_the_start_with_its_answer(tmp_path):
    from theprotocol.proxy.identity import IdentityError
    reg = F.FakeRegistry(client_secret="another-secret-entirely")
    p = _proxy(tmp_path, reg)
    with pytest.raises(IdentityError) as e:
        await p.start()
    assert e.value.status == 401 and "Incorrect client_id" in e.value.detail
    await p.stop()
    p.close()


async def test_a_token_for_another_agent_is_refused(tmp_path):
    from theprotocol.proxy.identity import IdentityError
    reg = F.FakeRegistry(did="did:theprotocol:someone-else")
    p = _proxy(tmp_path, reg)
    with pytest.raises(IdentityError, match="not did:theprotocol:5b1e0c7a-proxy-test's"):
        await p.identity.token()
    p.close()


# ── outbound: TheProtocol's events to a sink ─────────────────────────────────────────────────────────────────────────

async def test_an_outbound_mapping_delivers_an_event_once_per_key(tmp_path):
    reg = F.FakeRegistry()
    F.ListSink.delivered = []
    items = [{"id": "evt-1", "event_type": "SlashMoved", "aggregate_id": "did:x", "amount": "3",
              "ledger": {"event_id": "evt-1", "sequence": 41}}]
    doc = F.spec_doc(tmp_path, items=items, actions={}, sinks={"erp": {"type": "list_sink"}},
                     mappings=[{"name": "slashes", "version": 1, "from": "feed", "to": "erp",
                                "fields": {"amount": "$.payload.amount"}}])
    doc["sources"]["feed"]["config"]["replay_all"] = True
    for _ in range(2):
        p = _proxy(tmp_path, reg, doc)
        await _drain(p)
        p.close()
    assert len(F.ListSink.delivered) == 1
    key, ev = F.ListSink.delivered[0]
    assert (ev.event_id, ev.event_type, ev.aggregate_id, dict(ev.data)) == ("evt-1", "SlashMoved", "did:x",
                                                                           {"amount": "3"})
    assert ev.ledger == {"event_id": "evt-1", "sequence": 41} and key.startswith("tpx-")
    assert reg.calls == [] or all(c["path"] == "/api/v1/auth/agent/token" for c in reg.calls)


# ── health and metrics ───────────────────────────────────────────────────────────────────────────────────────────────

async def test_health_and_metrics_say_what_the_proxy_is_doing_without_a_secret(tmp_path):
    from theprotocol.proxy.service import health, render_metrics
    reg = F.FakeRegistry()
    reg.mode = "refuse"
    p = _proxy(tmp_path, reg, F.spec_doc(tmp_path, items=[{"id": f"r{i}", "v": i} for i in range(4)]))
    await _drain(p)
    code, body = health(p)
    assert code == 200 and body["status"] == "degraded" and body["held_mappings"] == ["reading"]
    text = render_metrics(p)
    assert 'tp_proxy_breaker_open{mapping="reading"} 1' in text
    assert 'tp_proxy_outbox_rows{status="dead"} 3' in text
    assert 'tp_proxy_refused_total{mapping="reading",target="attest"} 3' in text
    assert F.CLIENT_SECRET not in text and F.CLIENT_SECRET not in str(body)
    assert all(t not in text for t in reg.tokens)
    p.close()


async def test_the_service_answers_health_and_metrics_over_http(tmp_path):
    import httpx
    import socket
    from theprotocol.proxy.service import start_service
    reg = F.FakeRegistry()
    p = _proxy(tmp_path, reg)
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    runner = await start_service(p, f"127.0.0.1:{port}")
    try:
        async with httpx.AsyncClient() as http:
            h = await http.get(f"http://127.0.0.1:{port}/health")
            m = await http.get(f"http://127.0.0.1:{port}/metrics")
        assert h.status_code == 200 and h.json()["status"] == "ok" and h.json()["agent_did"] == F.DID
        assert m.status_code == 200 and "# TYPE tp_proxy_outbox_rows gauge" in m.text
    finally:
        await runner.cleanup()
        p.close()
