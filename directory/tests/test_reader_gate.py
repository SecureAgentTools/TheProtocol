"""§SOVKIT T4 — who may read the Directory (`directory/reader_gate.py`).

Every refusal below has a control: the same fixture, with only the one property changed back, is ALLOWED
(`test_the_happy_path_is_allowed`), so no refusal passes because the fixture could never pass.
Run (no image, no network beyond pip):
  docker run --rm -v $PWD:/t:ro -w /t -e PYTHONDONTWRITEBYTECODE=1 python:3.14-slim \
    sh -c 'pip install -q pytest cryptography && python -m pytest tests -q -p no:cacheprovider'
"""
import asyncio
import datetime
import logging
from urllib.parse import quote

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from directory import reader_gate as g

SECRET = "s" * 40
READER = "spiffe://eu.theprotocol.cloud/service/registry"
OTHER = "spiffe://eu.theprotocol.cloud/operator/amsterdam/svid-writer"


def _cert(uris=(), dns=()):
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "reader-gate-test")])
    now = datetime.datetime.now(datetime.timezone.utc)
    builder = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
               .serial_number(x509.random_serial_number())
               .not_valid_before(now - datetime.timedelta(minutes=1))
               .not_valid_after(now + datetime.timedelta(hours=1)))
    sans = [x509.UniformResourceIdentifier(u) for u in uris] + [x509.DNSName(d) for d in dns]
    if sans:
        builder = builder.add_extension(x509.SubjectAlternativeName(sans), critical=False)
    pem = builder.sign(key, hashes.SHA256()).public_bytes(serialization.Encoding.PEM).decode()
    return quote(pem, safe="")  # the shape nginx forwards as $ssl_client_escaped_cert


def _headers(**over):
    h = {g.MARKER_HEADER: SECRET, g.VERIFY_HEADER: "SUCCESS", g.CERT_HEADER: _cert(uris=[READER])}
    h.update(over)
    return {k: v for k, v in h.items() if v is not None}


def _decide(headers, secret=SECRET, readers=frozenset({READER})):
    return g.decide(headers, secret=secret, readers=readers)


# ── the pure rule ─────────────────────────────────────────────────────────────────────────────────

def test_the_happy_path_is_allowed():
    ok, why, sid = _decide(_headers())
    assert ok is True and sid == READER, why


@pytest.mark.parametrize("secret,usable", [
    (None, False), ("", False), ("s" * 31, False), ("s" * 32, True),
    ("a" * 31 + " ", False), ("a" * 31 + "$", False), ("a" * 31 + '"', False), ("ä" * 40, False),
    ("Az09._~-" * 5, True),
])
def test_the_secret_shape(secret, usable):
    assert g.secret_usable(secret) is usable


def test_a_short_or_unset_secret_refuses_even_a_matching_marker():
    short = "s" * 31
    ok, why, _ = _decide(_headers(**{g.MARKER_HEADER: short}), secret=short)
    assert ok is False and "SECRET" in why
    ok, why, _ = _decide(_headers(**{g.MARKER_HEADER: ""}), secret="")
    assert ok is False and "SECRET" in why


def test_an_empty_allowlist_refuses_everyone():
    ok, why, _ = _decide(_headers(), readers=frozenset())
    assert ok is False and "READERS" in why


@pytest.mark.parametrize("marker", [None, "", "t" * 40, SECRET[:-1], SECRET + "x"])
def test_a_missing_or_wrong_marker_is_refused(marker):
    ok, why, _ = _decide(_headers(**{g.MARKER_HEADER: marker}))
    assert ok is False and "marker" in why


@pytest.mark.parametrize("verify", [None, "", "NONE", "FAILED:certificate has expired", "success", "SUCCESS "])
def test_anything_but_success_from_the_sidecar_is_refused(verify):
    ok, why, _ = _decide(_headers(**{g.VERIFY_HEADER: verify}))
    assert ok is False and "verified" in why


def test_a_caller_outside_the_allowlist_is_refused_and_named():
    ok, why, sid = _decide(_headers(**{g.CERT_HEADER: _cert(uris=[OTHER])}))
    assert ok is False and "not in DIRECTORY_READERS" in why and sid == OTHER


def test_a_certificate_without_a_spiffe_san_is_refused():
    ok, why, _ = _decide(_headers(**{g.CERT_HEADER: _cert(dns=["directory-nginx"])}))
    assert ok is False and "0 SPIFFE" in why


def test_a_certificate_with_two_spiffe_sans_is_refused():
    ok, why, _ = _decide(_headers(**{g.CERT_HEADER: _cert(uris=[READER, OTHER])}))
    assert ok is False and "2 SPIFFE" in why


@pytest.mark.parametrize("cert", [None, "", "not-a-certificate", quote("-----BEGIN CERTIFICATE-----\nAAAA\n-----END CERTIFICATE-----\n", safe="")])
def test_a_missing_or_garbage_certificate_is_refused_not_crashed(cert):
    ok, why, _ = _decide(_headers(**{g.CERT_HEADER: cert}))
    assert ok is False and ("certificate" in why)


def test_a_reason_never_echoes_a_header_value():
    wrong = "w" * 40
    for headers in (_headers(**{g.MARKER_HEADER: wrong}), _headers(**{g.VERIFY_HEADER: "FAILED:xyz-unique"})):
        _, why, _ = _decide(headers)
        assert wrong not in why and "xyz-unique" not in why


def test_readers_parse_as_full_ids():
    assert g.parse_readers(f" {READER}, ,{OTHER} ") == frozenset({READER, OTHER})
    assert g.parse_readers("") == frozenset() and g.parse_readers(None) == frozenset()


# ── the ASGI door, HTTP and WebSocket ────────────────────────────────────────────────────────────

class _Downstream:
    def __init__(self):
        self.calls = []

    async def __call__(self, scope, receive, send):
        self.calls.append(scope.get("path"))


def _scope(kind, path, headers=None):
    return {"type": kind, "path": path,
            "headers": [(k.encode("latin-1"), v.encode("latin-1")) for k, v in (headers or [])]}


def _run(gate, scope):
    sent = []

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(message):
        sent.append(message)

    asyncio.run(gate(scope, receive, send))
    return sent


def _gate():
    down = _Downstream()
    return g.ReaderGate(down, secret=SECRET, readers=[READER]), down


def test_health_stays_open_without_any_header():
    gate, down = _gate()
    assert _run(gate, _scope("http", "/health")) == [] and down.calls == ["/health"]


@pytest.mark.parametrize("path", ["/graphql", "/status", "/docs", "/openapi.json", "/health/", "/anything-new"])
def test_every_other_path_is_refused_without_the_gate_headers(path):
    gate, down = _gate()
    sent = _run(gate, _scope("http", path))
    assert down.calls == [] and sent[0]["status"] == 403 and sent[1]["body"] == g.REFUSAL_BODY


def test_a_reader_with_all_three_proofs_reaches_graphql():
    gate, down = _gate()
    assert _run(gate, _scope("http", "/graphql", list(_headers().items()))) == [] and down.calls == ["/graphql"]


def test_the_websocket_door_is_closed_before_accept():
    gate, down = _gate()
    sent = _run(gate, _scope("websocket", "/graphql"))
    assert down.calls == [] and sent == [{"type": "websocket.close", "code": 1008}]


def test_the_websocket_door_opens_for_a_reader():
    gate, down = _gate()
    assert _run(gate, _scope("websocket", "/graphql", list(_headers().items()))) == [] and down.calls == ["/graphql"]


def test_a_repeated_gate_header_is_refused():
    gate, down = _gate()
    headers = list(_headers().items()) + [(g.MARKER_HEADER, SECRET)]
    sent = _run(gate, _scope("http", "/graphql", headers))
    assert down.calls == [] and sent[0]["status"] == 403


def test_lifespan_passes_through():
    gate, down = _gate()
    _run(gate, {"type": "lifespan"})
    assert down.calls == [None]


def test_the_gate_reads_its_config_from_the_environment(monkeypatch):
    monkeypatch.setenv("DIRECTORY_PROXY_TRUST_SECRET", SECRET)
    monkeypatch.setenv("DIRECTORY_READERS", READER)
    down = _Downstream()
    gate = g.ReaderGate(down)
    assert _run(gate, _scope("http", "/graphql", list(_headers().items()))) == [] and down.calls == ["/graphql"]
    monkeypatch.setenv("DIRECTORY_READERS", "")
    down2 = _Downstream()
    sent = _run(g.ReaderGate(down2), _scope("http", "/graphql", list(_headers().items())))
    assert down2.calls == [] and sent[0]["status"] == 403


def test_announce_is_loud_when_the_gate_cannot_open(caplog):
    caplog.set_level(logging.INFO, logger="directory.reader_gate")
    usable, readers = g.announce(secret="", readers=[])
    assert usable is False and readers == frozenset()
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(errors) == 2 and all("EVERY request" in r.getMessage() for r in errors)
    assert all(SECRET not in r.getMessage() for r in caplog.records)
    caplog.clear()
    g.announce(secret=SECRET, readers=[READER])
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert all(SECRET not in r.getMessage() for r in caplog.records)


# ── §OPDIST (2026-09-16): the allowlist as a carrier, so an operator provisioned an hour after the frame is
#    admitted without recreating the index. Built at import with no carrier was the FRAMES shape before
#    §FRAMEKIT P3.1 and the VENUES shape until this afternoon; this is the third service to have it.

def _carrier(tmp_path, env="spiffe://f/service/registry"):
    from directory.reader_gate import _ReadersCarrier
    return _ReadersCarrier(path=str(tmp_path / "readers.json"), env_value=env)


def test_the_env_holds_until_a_file_appears(tmp_path):
    c = _carrier(tmp_path)
    assert c.current() == frozenset({"spiffe://f/service/registry"})


def test_a_file_wins_and_a_later_write_is_seen_without_a_restart(tmp_path):
    import json
    import os as _os
    c = _carrier(tmp_path)
    p = tmp_path / "readers.json"
    p.write_text(json.dumps({"readers": ["spiffe://f/service/registry", "spiffe://f/operator/tartu/svid-writer"]}))
    assert "spiffe://f/operator/tartu/svid-writer" in c.current()
    # a second operator, appended while the process runs
    p.write_text(json.dumps({"readers": ["spiffe://f/service/registry", "spiffe://f/operator/2/svid-writer"]}))
    _os.utime(p, (p.stat().st_atime, p.stat().st_mtime + 1))
    assert "spiffe://f/operator/2/svid-writer" in c.current()


def test_an_empty_list_is_refused_rather_than_applied(tmp_path):
    """An empty allowlist refuses EVERY request, so a truncated or half-written file would take the index down.
    A gate that removes everything is indistinguishable from an outage: the set in force stays in force."""
    import json
    c = _carrier(tmp_path)
    p = tmp_path / "readers.json"
    p.write_text(json.dumps({"readers": ["spiffe://f/operator/tartu/svid-writer"]}))
    assert c.current() == frozenset({"spiffe://f/operator/tartu/svid-writer"})
    p.write_text(json.dumps({"readers": []}))
    import os as _os
    _os.utime(p, (p.stat().st_atime, p.stat().st_mtime + 1))
    assert c.current() == frozenset({"spiffe://f/operator/tartu/svid-writer"}), "an empty file must not be applied"


def test_an_unparsable_file_is_refused_rather_than_applied(tmp_path):
    import json
    import os as _os
    c = _carrier(tmp_path)
    p = tmp_path / "readers.json"
    p.write_text(json.dumps({"readers": ["spiffe://f/service/registry"]}))
    assert c.current() == frozenset({"spiffe://f/service/registry"})
    p.write_text("{ this is half a file")
    _os.utime(p, (p.stat().st_atime, p.stat().st_mtime + 1))
    assert c.current() == frozenset({"spiffe://f/service/registry"})


def test_a_deleted_file_falls_back_to_the_env(tmp_path):
    """Deleting the file AND emptying the env is how someone locks the index down deliberately; deleting only the
    file returns to what the frame was born with, which is never a lockout."""
    import json
    import os as _os
    c = _carrier(tmp_path)
    p = tmp_path / "readers.json"
    p.write_text(json.dumps({"readers": ["spiffe://f/operator/tartu/svid-writer"]}))
    assert "spiffe://f/operator/tartu/svid-writer" in c.current()
    _os.remove(p)
    assert c.current() == frozenset({"spiffe://f/service/registry"})


def test_the_middleware_asks_the_carrier_per_request_when_no_readers_are_pinned(tmp_path, monkeypatch):
    """The wiring, not the rule: a test that only exercised _ReadersCarrier would pass while ReaderGate kept its
    startup snapshot — agentvault2-6a's vacuous-test shape, asked of my own gate."""
    import json
    from directory.reader_gate import ReaderGate
    p = tmp_path / "readers.json"
    p.write_text(json.dumps({"readers": ["spiffe://f/service/registry"]}))
    monkeypatch.setenv("DIRECTORY_READERS_FILE", str(p))
    monkeypatch.setenv("DIRECTORY_READERS", "spiffe://f/service/registry")
    import importlib
    import directory.reader_gate as rg
    importlib.reload(rg)
    gate = rg.ReaderGate(app=lambda *a, **k: None)
    assert gate._carrier is not None, "with no pinned readers the gate must consult the carrier"
    before = gate._carrier.current()
    p.write_text(json.dumps({"readers": ["spiffe://f/service/registry", "spiffe://f/operator/tartu/svid-writer"]}))
    import os as _os
    _os.utime(p, (p.stat().st_atime, p.stat().st_mtime + 1))
    assert gate._carrier.current() - before == {"spiffe://f/operator/tartu/svid-writer"}
