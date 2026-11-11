"""V0659 (c): TheProtocol Proxy's sinks, TheProtocol's events delivered to the old systems.

The evidence export (hash-chained JSONL, a signed manifest) and tp-proxy verify, which checks it with no network and
names what was changed, removed or moved; the HTTP webhook to an ERP (the record's key as its Idempotency-Key); the
accounting lines (a CSV journal, an ISO 20022 camt.053 statement); an ICS calendar; an e-mail digest. Each keeps the
sink contract (a dry run writes nothing; one key delivered once). Red before V0659 (c): none of these sinks exist.
"""
from __future__ import annotations

import base64
import json
import os
import smtplib
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from theprotocol.proxy.plugins import Event, PluginError, Refused, Retry
from theprotocol.proxy.testing import FakeContext, check_sink

AT = datetime(2026, 11, 7, 9, 30, tzinfo=timezone.utc)


def _ev(i=1, **data):
    return Event(event_id=f"evt-{i}", event_type="SettlementCompleted", aggregate_id="did:theprotocol:payee",
                 data=data or {"amount": "12.50", "text": f"order {i}"}, occurred_at=AT,
                 ledger={"event_id": f"evt-{i}", "sequence": 40 + i})


def _key(tmp_path):
    from theprotocol.proxy.evidence import keygen
    path = tmp_path / "evidence.pem"
    pub = keygen(str(path))
    return path, pub


def _evidence(tmp_path, **cfg):
    from theprotocol.proxy.evidence import EvidenceSink
    path, pub = _key(tmp_path) if not (tmp_path / "evidence.pem").exists() else (tmp_path / "evidence.pem", None)
    ctx = FakeContext(secrets={"file:evidence.pem": path.read_text()})
    return EvidenceSink({"dir": str(tmp_path / "export"), "signing_key": "file:evidence.pem", **cfg}, ctx), ctx


# ── the evidence export and its offline check ────────────────────────────────────────────────────────────────────────

async def test_an_export_holds_offline_and_one_key_is_one_line(tmp_path):
    from theprotocol.proxy.evidence import verify
    sink, ctx = _evidence(tmp_path)
    await sink.start()
    for i in (1, 2, 3):
        out = await sink.deliver(_ev(i), key=f"tpx-{i}", dry_run=False)
        assert out.status == "done" and len(out.reference) == 64
    again = await sink.deliver(_ev(2), key="tpx-2", dry_run=False)
    problems, summary = verify(str(tmp_path / "export"))
    assert problems == [] and summary["lines"] == 3 and summary["head"]["seq"] == 3
    files = sorted((tmp_path / "export").glob("evidence-*.jsonl"))
    entries = [json.loads(ln) for f in files for ln in f.read_text().splitlines()]
    assert [e["key"] for e in entries] == ["tpx-1", "tpx-2", "tpx-3"] and again.reference == entries[1]["hash"]
    assert entries[0]["event"]["ledger"] == {"event_id": "evt-1", "sequence": 41}
    assert entries[1]["prev"] == entries[0]["hash"]


async def _filled(tmp_path, n=3):
    sink, _ = _evidence(tmp_path)
    await sink.start()
    for i in range(1, n + 1):
        await sink.deliver(_ev(i), key=f"tpx-{i}", dry_run=False)
    f = sorted((tmp_path / "export").glob("evidence-*.jsonl"))[0]
    return sink, f


async def test_verify_names_a_changed_a_removed_and_a_moved_line(tmp_path):
    from theprotocol.proxy.evidence import verify
    _sink, f = await _filled(tmp_path)
    original = f.read_text().splitlines()
    changed = json.loads(original[1])
    changed["event"]["data"]["amount"] = "1250.00"
    f.write_text("\n".join([original[0], json.dumps(changed), original[2]]) + "\n")
    problems, _ = verify(str(tmp_path / "export"))
    assert any(":2: its hash does not match" in p for p in problems)
    assert any("SHA-256 is not the manifest's" in p for p in problems)
    f.write_text("\n".join([original[0], original[2]]) + "\n")
    problems, _ = verify(str(tmp_path / "export"))
    assert any(":2: its prev is not the line before's hash" in p for p in problems)
    f.write_text("\n".join([original[1], original[0], original[2]]) + "\n")
    problems, _ = verify(str(tmp_path / "export"))
    assert any("prev is not" in p for p in problems) and any("seq 2 after 0" in p for p in problems)


async def test_verify_refuses_a_manifest_signed_by_another_key_or_changed_after_signing(tmp_path):
    from theprotocol.proxy.evidence import MANIFEST, keygen, sign_manifest, verify
    await _filled(tmp_path)
    man_path = tmp_path / "export" / MANIFEST
    man = json.loads(man_path.read_text())
    assert verify(str(tmp_path / "export"), public_key=man["public_key"])[0] == []
    other = keygen(str(tmp_path / "other.pem"))
    problems, _ = verify(str(tmp_path / "export"), public_key=other)
    assert any("not by the key you named" in p for p in problems)
    original_key = man["public_key"]
    changed = {**man, "head": {**man["head"], "seq": 2}}
    man_path.write_text(json.dumps(changed))
    assert any("signature does not verify" in p for p in verify(str(tmp_path / "export"))[0])
    # a manifest re-signed by someone else's key verifies against itself: only the signer you name catches it
    forged = sign_manifest({**man, "public_key": other}, (tmp_path / "other.pem").read_text())
    man_path.write_text(json.dumps(forged))
    assert not any("signature does not verify" in p for p in verify(str(tmp_path / "export"))[0])
    problems, _ = verify(str(tmp_path / "export"), public_key=original_key)
    assert any("not by the key you named" in p for p in problems)


async def test_a_line_written_before_a_crash_is_recovered_and_a_torn_one_dropped(tmp_path):
    from theprotocol.proxy.evidence import verify
    sink, f = await _filled(tmp_path, n=2)
    await sink.ctx.state.set("head", {"seq": 1, "hash": json.loads(f.read_text().splitlines()[0])["hash"]})
    with open(f, "a") as fh:
        fh.write('{"v": 1, "seq": 3, "tor')
    from theprotocol.proxy.evidence import EvidenceSink
    again = EvidenceSink(sink.config, sink.ctx)
    await again.start()
    assert (await sink.ctx.state.get("head"))["seq"] == 2 and await sink.ctx.state.get("key:tpx-2") is not None
    await again.deliver(_ev(3), key="tpx-3", dry_run=False)
    problems, summary = verify(str(tmp_path / "export"))
    assert problems == [] and summary["lines"] == 3


async def test_the_registry_card_is_embedded_and_checked_as_of_when_it_was_read(tmp_path):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from theprotocol.proxy.evidence import verify
    from theprotocol.proxy.testing import FakeResponse
    from theprotocol.registry.card_verify import extract_paths
    declared = ["identity.registry_name"]
    card = {"registry_card_version": "0.5", "identity": {"registry_name": "EU"}}
    priv = Ed25519PrivateKey.generate()
    signed_at = (AT - timedelta(minutes=1)).isoformat()
    expires_at = (AT + timedelta(minutes=10)).isoformat()   # long expired when anyone checks the export
    payload = {**extract_paths(card, declared), "_signed_at": signed_at, "_expires_at": expires_at}
    sig = priv.sign(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode())
    b64u = lambda raw: base64.urlsafe_b64encode(raw).rstrip(b"=").decode()  # noqa: E731
    card["signature"] = {"algorithm": "EdDSA", "kid": "k1", "value": b64u(sig), "signed_canonical": declared,
                         "signed_at": signed_at, "expires_at": expires_at}
    pub = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    jwks = {"keys": [{"kty": "OKP", "crv": "Ed25519", "kid": "k1", "x": b64u(pub)}]}
    sink, ctx = _evidence(tmp_path, registry_card=True)
    ctx._answers = [FakeResponse(200, card), FakeResponse(200, jwks)]
    await sink.start()
    sink._registry["fetched_at"] = AT.isoformat()          # read while the card's signature was fresh
    await sink.deliver(_ev(1), key="tpx-1", dry_run=False)
    problems, summary = verify(str(tmp_path / "export"))
    assert problems == [] and summary["registry_card"] is True
    assert [c["path"] for c in ctx.calls] == ["/.well-known/registry-card.json", "/.well-known/registry-jwks.json"]


async def test_the_evidence_sink_keeps_the_sink_contract_and_refuses_a_key_that_cannot_sign(tmp_path):
    from theprotocol.proxy.evidence import EvidenceSink
    path, _pub = _key(tmp_path)
    lines = lambda: [ln for f in (tmp_path / "export").glob("evidence-*.jsonl") for ln in f.read_text().splitlines()]  # noqa: E731

    def ctx():
        return FakeContext(secrets={"file:evidence.pem": path.read_text()})

    class Started(EvidenceSink):
        name = "evidence"

        async def deliver(self, event, *, key, dry_run):
            if self._pem is None:
                await self.start()
            return await super().deliver(event, key=key, dry_run=dry_run)
    await check_sink(Started, {"dir": str(tmp_path / "export"), "signing_key": "file:evidence.pem"}, _ev(1),
                     ctx_factory=ctx, delivered=lines)
    bad = EvidenceSink({"dir": str(tmp_path / "x"), "signing_key": "file:k"},
                       FakeContext(secrets={"file:k": "not a key"}))
    with pytest.raises(PluginError, match="not a PEM private key"):
        await bad.start()


def test_keygen_never_writes_over_a_key_and_writes_it_0600(tmp_path):
    from theprotocol.proxy.evidence import keygen
    p = tmp_path / "k.pem"
    pub = keygen(str(p))
    assert len(base64.b64decode(pub)) == 32 and oct(os.stat(p).st_mode & 0o777) == "0o600"
    with pytest.raises(PluginError, match="never written over"):
        keygen(str(p))


async def test_an_sftp_mirror_copies_the_file_and_the_manifest_and_a_failure_is_a_retry(tmp_path, monkeypatch):
    import sys
    import types
    put = []

    class SFTP:
        def put(self, local, remote):
            put.append((os.path.basename(local), remote))

    class Client:
        def load_system_host_keys(self):
            pass

        def load_host_keys(self, p):
            pass

        def set_missing_host_key_policy(self, p):
            pass

        def connect(self, **kw):
            if kw.get("hostname") == "down.example":
                raise OSError("no route")

        def open_sftp(self):
            return SFTP()

        def close(self):
            pass
    fake = types.ModuleType("paramiko")
    fake.SSHClient, fake.RejectPolicy = Client, lambda: None
    monkeypatch.setitem(sys.modules, "paramiko", fake)
    sink, _ = _evidence(tmp_path, mirror={"type": "sftp", "host": "erp.example", "path": "/in/evidence/"})
    await sink.start()
    await sink.deliver(_ev(1), key="tpx-1", dry_run=False)
    assert [r for _l, r in put] == ["/in/evidence/manifest.json", f"/in/evidence/{put[1][0]}"]
    sink.config["mirror"]["host"] = "down.example"
    with pytest.raises(Retry, match="sftp mirror could not be written"):
        await sink.deliver(_ev(2), key="tpx-2", dry_run=False)
    assert await sink.ctx.state.get("key:tpx-2") is not None, "the line is kept here; the retry copies it again"


# ── the webhook sink ─────────────────────────────────────────────────────────────────────────────────────────────────

class _ERP:
    """An ERP's API that keeps each Idempotency-Key once."""

    def __init__(self, status=201):
        self.status, self.got = status, []

    def handler(self, request):
        key = request.headers["idempotency-key"]
        if self.status != 201:
            return httpx.Response(self.status, text="busy" if self.status >= 500 else "no such ledger")
        if key not in [k for k, _ in self.got]:
            self.got.append((key, request))
        return httpx.Response(201, json={"id": f"erp-{len(self.got)}"})


async def test_the_webhook_sink_keeps_the_contract_and_signs_its_body(monkeypatch):
    from theprotocol.proxy.sinks_builtin import WebhookSink
    erp = _ERP()
    monkeypatch.setattr(WebhookSink, "transport", httpx.MockTransport(erp.handler))
    ctx = lambda: FakeContext(secrets={"env:ERP_HMAC": "hmac-key", "env:ERP_TOKEN": "erp-token"})  # noqa: E731
    cfg = {"url": "https://erp.example/api/events", "secret": "env:ERP_HMAC", "bearer": "env:ERP_TOKEN",
           "headers": {"X-Tenant": "hamburg"}}
    out = await check_sink(WebhookSink, cfg, _ev(1), ctx_factory=ctx, delivered=lambda: erp.got)
    assert out.reference == "erp-1"
    _key_, req = erp.got[0]
    import hashlib
    import hmac as _h
    assert req.headers["x-signature-256"] == "sha256=" + _h.new(b"hmac-key", req.content, hashlib.sha256).hexdigest()
    assert req.headers["authorization"] == "Bearer erp-token" and req.headers["x-tenant"] == "hamburg"
    assert json.loads(req.content)["event"]["event_id"] == "evt-1"


async def test_the_webhook_sink_retries_a_5xx_refuses_a_4xx_and_takes_no_credential_in_plain_headers(monkeypatch):
    from theprotocol.proxy.sinks_builtin import WebhookSink
    for status, exc in ((503, Retry), (422, Refused)):
        monkeypatch.setattr(WebhookSink, "transport", httpx.MockTransport(_ERP(status).handler))
        with pytest.raises(exc):
            await WebhookSink({"url": "https://erp.example/x"}, FakeContext()).deliver(_ev(1), key="k", dry_run=False)
    with pytest.raises(PluginError, match="carries a credential"):
        await WebhookSink({"url": "https://erp.example/x", "headers": {"Authorization": "Bearer x"}},
                          FakeContext()).start()


# ── accounting lines ─────────────────────────────────────────────────────────────────────────────────────────────────

async def test_the_csv_journal_books_each_key_once_with_one_header(tmp_path):
    from theprotocol.proxy.sinks_builtin import JournalSink
    ctx = FakeContext()
    j = JournalSink({"dir": str(tmp_path), "account": {"id": "did:theprotocol:proxy", "currency": "ECU"}}, ctx)
    await j.start()
    await j.deliver(_ev(1, amount="12.50", counterparty="Kestrel Chartering", text="charter 7"), key="k1", dry_run=False)
    await j.deliver(_ev(2, amount="-3", text="fee"), key="k2", dry_run=False)
    await j.deliver(_ev(1, amount="12.50"), key="k1", dry_run=False)
    rows = (tmp_path / "journal-2026-11-07.csv").read_text().splitlines()
    assert rows[0].startswith("date,value_date,direction,amount,currency") and len(rows) == 3
    assert rows[1].split(",")[2:5] == ["credit", "12.50", "ECU"] and rows[2].split(",")[2:4] == ["debit", "3"]
    with pytest.raises(Refused, match="needs an amount"):
        await j.deliver(_ev(3, text="no amount"), key="k3", dry_run=False)
    with pytest.raises(Refused, match="in USD"):
        await j.deliver(_ev(4, amount="1", currency="USD"), key="k4", dry_run=False)


async def test_the_camt053_statement_carries_the_days_entries_and_its_balances(tmp_path):
    from theprotocol.proxy.sinks_builtin import CAMT_NS, JournalSink
    j = JournalSink({"dir": str(tmp_path), "format": "camt053", "opening_balance": "100",
                     "account": {"id": "did:theprotocol:proxy", "currency": "ECU", "name": "Gate scanner"}},
                    FakeContext())
    await j.start()
    await j.deliver(_ev(1, amount="12.50", counterparty="Kestrel", text="charter"), key="k1", dry_run=False)
    await j.deliver(_ev(2, amount="-2.25", text="fee"), key="k2", dry_run=False)
    doc = ET.parse(tmp_path / "camt053-2026-11-07.xml").getroot()
    ns = {"c": CAMT_NS["001.02"]}
    bals = {b.find("c:Tp/c:CdOrPrtry/c:Cd", ns).text: (b.find("c:Amt", ns).text, b.find("c:CdtDbtInd", ns).text)
            for b in doc.findall(".//c:Bal", ns)}
    assert bals == {"OPBD": ("100.00", "CRDT"), "CLBD": ("110.25", "CRDT")}
    entries = doc.findall(".//c:Ntry", ns)
    assert [(e.find("c:Amt", ns).text, e.find("c:CdtDbtInd", ns).text) for e in entries] == \
        [("12.50", "CRDT"), ("2.25", "DBIT")]
    assert entries[0].find(".//c:EndToEndId", ns).text == "k1" and entries[0].find(".//c:Dbtr/c:Nm", ns).text == "Kestrel"
    assert doc.find(".//c:TtlNtries/c:NbOfNtries", ns).text == "2"


# ── a calendar, a digest ─────────────────────────────────────────────────────────────────────────────────────────────

async def test_the_calendar_names_each_event_by_its_key_and_folds_and_escapes_its_lines(tmp_path):
    from theprotocol.proxy.sinks_builtin import CalendarSink
    c = CalendarSink({"path": str(tmp_path / "berths.ics"), "name": "Berth slots"}, FakeContext())
    long = "Berth 4, Container Terminal Altenwerder; " * 4
    await c.deliver(_ev(1, start="2026-11-08T06:00:00Z", summary=long), key="k1", dry_run=False)
    await c.deliver(_ev(2, start="2026-11-08T08:00:00+01:00", end="2026-11-08T09:30:00+01:00", summary="B"),
                    key="k2", dry_run=False)
    await c.deliver(_ev(1, start="2026-11-08T07:00:00Z", summary="moved"), key="k1", dry_run=False)
    raw = (tmp_path / "berths.ics").read_bytes()
    assert all(len(line) <= 75 for line in raw.split(b"\r\n"))
    text = raw.decode().replace("\r\n ", "")
    assert text.count("BEGIN:VEVENT") == 2 and "UID:k1@theprotocol-proxy" in text
    assert "DTSTART:20261108T070000Z" in text and "SUMMARY:moved" in text, "the same key is the same event, updated"
    assert "DTSTART:20261108T070000Z\r\nDTEND:20261108T080000Z" in text
    assert "DTSTART:20261108T070000Z" in text and "DTEND:20261108T083000Z" in text


async def test_the_digest_spools_each_key_once_and_mails_them_together(tmp_path, monkeypatch):
    from theprotocol.proxy.sinks_builtin import EmailDigestSink
    sent = []

    class SMTP:
        def __init__(self, host, port, timeout=None):
            self.host, self.port = host, port

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            sent.append("starttls")

        def login(self, user, password):
            sent.append(("login", user, password))

        def send_message(self, msg):
            if self.host == "down.example":
                raise smtplib.SMTPServerDisconnected("gone")
            sent.append(msg)
    monkeypatch.setattr(smtplib, "SMTP", SMTP)
    ctx = FakeContext(secrets={"env:SMTP_PASSWORD": "pw"})
    d = EmailDigestSink({"smtp": {"host": "mail.example", "starttls": True, "username": "proxy",
                                  "password": "env:SMTP_PASSWORD"},
                         "from": "proxy@example.org", "to": ["ops@example.org"]}, ctx)
    for i, k in ((1, "k1"), (2, "k2"), (1, "k1")):
        await d.deliver(_ev(i), key=k, dry_run=False)
    d.config["smtp"]["host"] = "down.example"
    with pytest.raises(smtplib.SMTPServerDisconnected):
        await d.flush()
    assert len(await ctx.state.get("spool")) == 2, "a failed send keeps the spool"
    d.config["smtp"]["host"] = "mail.example"
    assert await d.flush() == 2 and await ctx.state.get("spool") == []
    msg = [m for m in sent if not isinstance(m, (str, tuple))][0]
    body = msg.get_content()
    assert msg["To"] == "ops@example.org" and "2 events" in body and body.count("SettlementCompleted") == 2
    assert ("login", "proxy", "pw") in sent and "starttls" in sent
