"""V0659 (c): the outbound subscription, end to end. The registry's webhooks (theprotocol_events: each delivery's
X-TheProtocol-Signature checked) feed an outbound mapping into the evidence export, and tp-proxy verify checks the
export offline, the registry's signature on every delivery included. Red before V0659 (c): theprotocol_events, the
evidence sink and tp-proxy verify do not exist.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import socket

import httpx
import pytest

import proxy_fake as F

HOOK = "registry-webhook-secret-for-tests"


@pytest.fixture(autouse=True)
def fake_plugins(monkeypatch):
    from theprotocol.proxy import plugins
    monkeypatch.setitem(plugins.BUILTINS["source"], "list_source", "proxy_fake:ListSource")


def _port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _delivery(i, event="payment.settled", **data):
    """A delivery as the registry's webhook service sends it: sorted JSON, signed as sent (hex HMAC-SHA256)."""
    doc = {"id": f"dlv-{i}", "event": event, "agent_did": F.DID, "timestamp": "2026-11-07T09:30:00+00:00",
           "data": {"amount": "12.50", "event_id": f"evt-{i}", "sequence": 100 + i, **data}}
    body = json.dumps(doc, sort_keys=True)
    return body, hmac.new(HOOK.encode(), body.encode(), hashlib.sha256).hexdigest()


async def _post(port, body, sig):
    headers = {"Content-Type": "application/json", "X-TheProtocol-Event": "payment.settled"}
    if sig:
        headers["X-TheProtocol-Signature"] = sig
    async with httpx.AsyncClient() as http:
        return await http.post(f"http://127.0.0.1:{port}/in/tp", content=body.encode(), headers=headers)


async def _running(tmp_path, *, events=None):
    from theprotocol.proxy.evidence import keygen
    from theprotocol.proxy.runtime import Proxy
    from theprotocol.proxy.spec import parse
    keygen(str(tmp_path / "evidence.pem"))
    (tmp_path / "hook.txt").write_text(HOOK)
    port = _port()
    src = {"listen": f"127.0.0.1:{port}", "path": "/in/tp", "secret": "file:hook.txt"}
    if events:
        src["events"] = events
    doc = F.spec_doc(tmp_path, actions={}, sources={"events": {"type": "theprotocol_events", "config": src}},
                     sinks={"export": {"type": "evidence", "config": {"dir": str(tmp_path / "export"),
                                                                      "signing_key": "file:evidence.pem"}}},
                     mappings=[{"name": "settlements", "version": 1, "from": "events", "to": "export",
                                "fields": {"amount": "$.payload.amount"}}])
    reg = F.FakeRegistry()
    p = Proxy(parse(doc, base=tmp_path), transport=reg.transport, service=False, poll_s=0.01)
    stop = asyncio.Event()
    task = asyncio.ensure_future(p.run(stop=stop))
    for _ in range(100):
        if p.sources["events"].port:
            break
        await asyncio.sleep(0.02)
    return p, stop, task, port


async def _lines(tmp_path, n, timeout=5.0):
    for _ in range(int(timeout / 0.02)):
        files = sorted((tmp_path / "export").glob("evidence-*.jsonl"))
        got = [json.loads(ln) for f in files for ln in f.read_text().splitlines()]
        if len(got) >= n:
            return got
        await asyncio.sleep(0.02)
    return got


async def test_a_signed_delivery_lands_once_in_the_export_and_verifies_offline_with_its_signature(tmp_path):
    from theprotocol.proxy.evidence import verify
    p, stop, task, port = await _running(tmp_path)
    try:
        body, sig = _delivery(1)
        assert (await _post(port, body, sig)).status_code == 202
        assert (await _post(port, body, sig)).status_code == 202, "the registry's retry of the same delivery"
        body2, sig2 = _delivery(2, amount="4.00")
        assert (await _post(port, body2, sig2)).status_code == 202
        got = await _lines(tmp_path, 2)
        await asyncio.sleep(0.1)
        got = await _lines(tmp_path, 2)
        assert len(got) == 2, "one line per delivery"
        ev = got[0]["event"]
        assert (ev["event_id"], ev["event_type"], ev["aggregate_id"], ev["data"]) == \
            ("dlv-1", "payment.settled", F.DID, {"amount": "12.50"})
        assert ev["ledger"]["delivery_id"] == "dlv-1" and ev["ledger"]["event_id"] == "evt-1"
        assert ev["ledger"]["signed_body"] == body and ev["ledger"]["signature"] == sig
        problems, summary = verify(str(tmp_path / "export"), webhook_secret=HOOK)
        assert problems == [] and summary["webhook_signatures"] == {"checked": 2, "of": 2}
        wrong, _ = verify(str(tmp_path / "export"), webhook_secret="another secret")
        assert sum("webhook signature does not verify" in w for w in wrong) == 2
    finally:
        stop.set()
        await task
        p.close()


async def test_a_delivery_not_signed_with_the_webhooks_secret_is_refused(tmp_path):
    p, stop, task, port = await _running(tmp_path)
    try:
        body, sig = _delivery(1)
        assert (await _post(port, body, None)).status_code == 401
        assert (await _post(port, body, "0" * 64)).status_code == 401
        tampered = body.replace("12.50", "1250.00")
        assert (await _post(port, tampered, sig)).status_code == 401
        assert p.outbox.counts() == {"pending": 0, "done": 0, "dead": 0}
    finally:
        stop.set()
        await task
        p.close()


async def test_an_event_the_spec_does_not_take_is_answered_and_kept_nowhere(tmp_path):
    p, stop, task, port = await _running(tmp_path, events=["payment.settled"])
    try:
        body, sig = _delivery(3, event="agent.updated")
        r = await _post(port, body, sig)
        assert r.status_code == 202 and r.json()["accepted"] == 0
        assert p.outbox.counts() == {"pending": 0, "done": 0, "dead": 0}
    finally:
        stop.set()
        await task
        p.close()


async def test_tp_proxy_verify_and_keygen(tmp_path, capsys):
    from theprotocol.proxy.cli import main
    p, stop, task, port = await _running(tmp_path)
    try:
        body, sig = _delivery(1)
        await _post(port, body, sig)
        await _lines(tmp_path, 1)
    finally:
        stop.set()
        await task
        p.close()
    export = str(tmp_path / "export")
    assert main(["verify", export, "--webhook-secret", f"file:{tmp_path / 'hook.txt'}"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["holds"] is True and out["lines"] == 1 and out["webhook_signatures"] == {"checked": 1, "of": 1}
    f = sorted((tmp_path / "export").glob("evidence-*.jsonl"))[0]
    f.write_text(f.read_text().replace("12.50", "99.99"))
    assert main(["verify", export]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["holds"] is False and any("hash does not match" in x for x in out["problems"])
    assert main(["keygen", str(tmp_path / "new.pem")]) == 0
    assert len(json.loads(capsys.readouterr().out)["public_key"]) == 44


def test_the_shipped_outbound_example_is_valid():
    from pathlib import Path
    from theprotocol.proxy.spec import read
    spec = read(str(Path(__file__).resolve().parent.parent / "proxy" / "proxy.outbound.example.yaml"))
    assert {m.kind for m in spec.mappings} == {"sink"} and spec.sources["events"].type == "theprotocol_events"
