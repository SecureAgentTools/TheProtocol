"""V0659 (a): the core's own source and action, so a proxy runs end to end: the HTTP webhook receiver (a signed POST
answered 202 once its records are in the outbox) and the attestation (one signed fact per record, its key in the hashed
data). Red before V0659: theprotocol.proxy.sources_builtin and actions_builtin do not exist.
"""
from __future__ import annotations

import asyncio
import json
import socket

import httpx
import pytest

import proxy_fake as F


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _webhook_doc(tmp_path, port, *, secret=True, **cfg):
    (tmp_path / "hmac.txt").write_text("webhook-hmac-secret-for-tests\n")
    conf = {"listen": f"127.0.0.1:{port}", "path": "/in/gate", "id_field": "$.event.id", **cfg}
    if secret:
        conf["secret"] = "file:hmac.txt"
    return F.spec_doc(tmp_path, sources={"gate": {"type": "webhook", "config": conf}},
                      mappings=[{"name": "gate-out", "version": 1, "from": "gate", "to": "attest",
                                 "when": {"path": "$.payload.event.status", "equals": "OUT"},
                                 "fields": {"container": "$.payload.event.container", "terminal": "HAM-CTA"}}])


async def _running(tmp_path, reg, doc, **kw):
    from theprotocol.proxy.runtime import Proxy
    from theprotocol.proxy.spec import parse
    p = Proxy(parse(doc, base=tmp_path), transport=reg.transport, service=False, poll_s=0.01, **kw)
    stop = asyncio.Event()
    task = asyncio.ensure_future(p.run(stop=stop))
    for _ in range(100):
        if p.sources["gate"].port:
            break
        await asyncio.sleep(0.02)
    return p, stop, task


async def _post(port, body, *, secret="webhook-hmac-secret-for-tests", sign=True, header="X-Signature-256"):
    from theprotocol.proxy.sources_builtin import signature
    raw = json.dumps(body).encode()
    headers = {"Content-Type": "application/json"}
    if sign:
        headers[header] = signature(secret, raw)
    async with httpx.AsyncClient() as http:
        return await http.post(f"http://127.0.0.1:{port}/in/gate", content=raw, headers=headers)


async def _settle(p, reg, want_effects, timeout=5.0):
    for _ in range(int(timeout / 0.02)):
        if len(reg.effects) >= want_effects and not p.outbox.due(limit=1, now=__import__("time").time() + 1):
            return
        await asyncio.sleep(0.02)


# ── the webhook source ───────────────────────────────────────────────────────────────────────────────────────────────

async def test_a_signed_post_is_answered_202_once_in_the_outbox_and_attested(tmp_path):
    reg = F.FakeRegistry()
    port = _free_port()
    p, stop, task = await _running(tmp_path, reg, _webhook_doc(tmp_path, port))
    try:
        r = await _post(port, [{"event": {"id": "g-1", "status": "OUT", "container": "MSKU1234567"}},
                               {"event": {"id": "g-2", "status": "IN", "container": "MSKU7654321"}}])
        assert r.status_code == 202 and r.json() == {"accepted": 2, "ids": ["g-1", "g-2"]}
        assert p.outbox.counts()["pending"] + p.outbox.counts()["done"] == 1, \
            "on disk before the 202 (the IN event is no mapping's: no row)"
        await _settle(p, reg, 1)
        assert [e["attestation_data"]["claim"] for e in reg.effects] == [{"container": "MSKU1234567",
                                                                          "terminal": "HAM-CTA"}]
        again = await _post(port, {"event": {"id": "g-1", "status": "OUT", "container": "MSKU1234567"}})
        assert again.status_code == 202
        await asyncio.sleep(0.1)
        assert len(reg.effects) == 1 and len(reg.writes()) == 1, "the sender's retry is the same record"
    finally:
        stop.set()
        await task
        p.close()


async def test_an_unsigned_or_wrongly_signed_post_is_refused_and_kept_nowhere(tmp_path):
    reg = F.FakeRegistry()
    port = _free_port()
    p, stop, task = await _running(tmp_path, reg, _webhook_doc(tmp_path, port))
    try:
        body = {"event": {"id": "g-9", "status": "OUT", "container": "X"}}
        assert (await _post(port, body, sign=False)).status_code == 401
        assert (await _post(port, body, secret="another-key")).status_code == 401
        assert p.outbox.counts() == {"pending": 0, "done": 0, "dead": 0}
    finally:
        stop.set()
        await task
        p.close()


async def test_a_body_that_is_not_json_or_lacks_its_id_is_a_400(tmp_path):
    reg = F.FakeRegistry()
    port = _free_port()
    p, stop, task = await _running(tmp_path, reg, _webhook_doc(tmp_path, port, secret=False))
    try:
        async with httpx.AsyncClient() as http:
            r = await http.post(f"http://127.0.0.1:{port}/in/gate", content=b"not json")
        assert r.status_code == 400
        r = await _post(port, {"event": {"status": "OUT"}}, sign=False)
        assert r.status_code == 400 and "$.event.id" in r.json()["detail"]
        r = await _post(port, [1, 2], sign=False)
        assert r.status_code == 400
    finally:
        stop.set()
        await task
        p.close()


async def test_a_webhook_without_a_secret_listens_only_on_loopback(tmp_path):
    from theprotocol.proxy.plugins import PluginError
    from theprotocol.proxy.sources_builtin import WebhookSource
    from theprotocol.proxy.testing import FakeContext
    src = WebhookSource({"listen": "0.0.0.0:0", "path": "/in"}, FakeContext())
    with pytest.raises(PluginError, match="takes only signed POSTs"):
        await src.start()
    await src.stop()


async def test_a_dry_run_webhook_maps_the_post_and_tells_the_sender_to_send_it_again(tmp_path):
    reg = F.FakeRegistry()
    port = _free_port()
    shown = []
    p, stop, task = await _running(tmp_path, reg, _webhook_doc(tmp_path, port), dry_run=True, report=shown.append)
    try:
        r = await _post(port, {"event": {"id": "g-3", "status": "OUT", "container": "C3"}})
        assert r.status_code == 503 and "dry run" in r.json()["detail"] and r.headers["retry-after"] == "60"
        for _ in range(100):
            if shown:
                break
            await asyncio.sleep(0.02)
        assert shown and shown[0]["data"]["request"]["attestation_data"]["claim"] == {"container": "C3",
                                                                                      "terminal": "HAM-CTA"}
        assert reg.calls == []
    finally:
        stop.set()
        await task
        p.close()


def test_the_webhook_keeps_the_interface_and_cannot_read_the_past():
    from theprotocol.proxy.sources_builtin import WebhookSource
    from theprotocol.proxy.testing import check_class
    check_class(WebhookSource, "source")
    assert WebhookSource.config_schema["properties"]["secret"]["x-secret"] is True


async def test_the_webhook_says_it_cannot_rewind():
    from theprotocol.proxy.plugins import PluginError
    from theprotocol.proxy.sources_builtin import WebhookSource
    from theprotocol.proxy.testing import FakeContext
    with pytest.raises(PluginError, match="cannot read again"):
        await WebhookSource({"listen": "127.0.0.1:0", "path": "/in"}, FakeContext()).rewind("start")


# ── the attestation action ───────────────────────────────────────────────────────────────────────────────────────────

async def test_the_attestation_keeps_the_action_contract():
    from theprotocol.proxy.actions_builtin import AttestationAction
    from theprotocol.proxy.testing import FakeResponse, check_action, check_action_refusals
    cfg = {"attestation_type": "meter.reading"}
    out = await check_action(AttestationAction, cfg, {"kwh": 4.2},
                             answers=[FakeResponse(200, {"attestation_id": "att-7", "status": "pending"})])
    assert out.reference == "att-7"
    await check_action_refusals(AttestationAction, cfg, {"kwh": 4.2})
    assert AttestationAction.needs == frozenset({"reputation.signal"}) and AttestationAction.moves_value is False


async def test_the_records_key_is_in_the_hashed_data_and_evidence_and_target_are_taken_from_the_config():
    from theprotocol.proxy.actions_builtin import AttestationAction
    from theprotocol.proxy.testing import FakeContext
    ctx = FakeContext()
    a = AttestationAction({"attestation_type": "scale.weight", "evidence_field": "photo",
                           "target_agent_did": "did:theprotocol:the-scale"}, ctx)
    await a.perform({"kg": 12, "photo": "https://evidence.example/1.jpg"}, key="tpx-1", dry_run=False)
    await a.perform({"kg": 12, "photo": "https://evidence.example/1.jpg"}, key="tpx-2", dry_run=False)
    first, second = (c["json"] for c in ctx.calls)
    assert first["attestation_data"] == {"claim": {"kg": 12}, "record": "tpx-1"}
    assert second["attestation_data"]["record"] == "tpx-2", "the same claim twice is two attestations"
    assert first["evidence_url"] == "https://evidence.example/1.jpg"
    assert first["target_agent_did"] == "did:theprotocol:the-scale"
    assert [c["idempotency_key"] for c in ctx.calls] == ["tpx-1", "tpx-2"]


async def test_a_409_for_the_same_data_is_done_and_a_429_waits_for_retry_after():
    from theprotocol.proxy.actions_builtin import AttestationAction
    from theprotocol.proxy.plugins import Retry
    from theprotocol.proxy.testing import FakeContext, FakeResponse
    dup = FakeResponse(409, {"detail": "The TEG refused the request (HTTP 409): Attestation already submitted"})
    out = await AttestationAction({"attestation_type": "t"}, FakeContext(answers=[dup])).perform(
        {"a": 1}, key="k", dry_run=False)
    assert out.status == "done" and "already on the ledger" in out.detail
    slow = FakeResponse(429, {"detail": "Too many requests"}, headers={"Retry-After": "7"})
    with pytest.raises(Retry) as e:
        await AttestationAction({"attestation_type": "t"}, FakeContext(answers=[slow])).perform(
            {"a": 1}, key="k", dry_run=False)
    assert e.value.after == 7.0
