"""§MTLSHOPS V0379 (2026-09-15): the TEG's emission-policy fetch presents the frame SVID, so it can pass nginx-registry.

agentvault2-b5's registry terminator (b2) puts the registry behind nginx-registry, which verifies client certificates, and
the TEG's REGISTRY_URL moves to it. `_fetch_teg_policies` opened a bare aiohttp.ClientSession: no client certificate and
the system roots only. After b2 it would read nothing, and the TEG would keep deciding from its import-time blocklist
while the failure logged at DEBUG (and a refused status logged nothing). The emitter's own sessions already carried the
SVID. Now both take their context from one builder, and a failed fetch is a WARNING, at most one every ten minutes.

  1. (structure) one builder: `_svid_ssl_context` holds the module's only load_cert_chain, and both the emitter's
     _build_ssl_context and _fetch_teg_policies call it;
  2. (behaviour) with an SVID on disk the fetch's session connector carries that context; without one the fetch builds
     its session exactly as before (no connector);
  3. (behaviour) the builder follows the files: the same files give the same context, a rotated certificate a new one,
     and a missing file none;
  4. (behaviour) the emitter keeps its context when the files vanish mid-rotation, as it always did;
  5. (behaviour) a failed fetch warns once, and a second failure inside ten minutes stays at DEBUG.

The certificates are minted here. RED control: PYTHONPATH naming the TEG tree before this change fails 1, 2, 3 and 5.
"""
from __future__ import annotations

import ast
import datetime
import logging
import os
import pathlib

import aiohttp
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from teg_core_service import event_emitter as ee

SRC = pathlib.Path(ee.__file__).resolve()
FILES = ("svid.0.pem", "svid.0.key", "bundle.0.pem")


def _mint(directory: pathlib.Path, cn: str = "teg") -> None:
    key = ec.generate_private_key(ec.SECP256R1())
    now = datetime.datetime.now(datetime.timezone.utc)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=1)).not_valid_after(now + datetime.timedelta(hours=1))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(key, hashes.SHA256()))
    pem = cert.public_bytes(serialization.Encoding.PEM)
    (directory / "svid.0.pem").write_bytes(pem)
    (directory / "bundle.0.pem").write_bytes(pem)
    (directory / "svid.0.key").write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))


def _emitter_class():
    classes = [c for c in vars(ee).values() if isinstance(c, type) and "_build_ssl_context" in vars(c)]
    assert len(classes) == 1, classes
    return classes[0]


def _named(scope, name):
    found = [n for n in ast.walk(scope) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name]
    assert len(found) == 1, f"{name}: {len(found)} definitions"
    return found[0]


def _calls(node, name):
    return [n for n in ast.walk(node) if isinstance(n, ast.Call)
            and (getattr(n.func, "id", None) == name or getattr(n.func, "attr", None) == name)]


class _Sessions:
    """Stands in for aiohttp.ClientSession: records the connector each session was given and refuses to send."""

    def __init__(self, status=None):
        self.connectors, self.status = [], status

    def __call__(self, *args, connector=None, **kwargs):
        self.connectors.append(connector)
        status = self.status

        class _Response:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

        _Response.status = status

        class _Session:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                if connector is not None:
                    await connector.close()
                return False

            def get(self, *a, **k):
                if status is None:
                    raise aiohttp.ClientConnectionError("recorded, not sent")
                return _Response()

        return _Session()


def test_one_builder_holds_the_svid_context():
    tree = ast.parse(SRC.read_text())
    builder = _named(tree, "_svid_ssl_context")
    chains = _calls(tree, "load_cert_chain")
    assert len(chains) == 1 and chains[0] in list(ast.walk(builder)), "the module must load the key pair in one place"
    klass = next(n for n in tree.body if isinstance(n, ast.ClassDef) and _calls(n, "load_cert_chain") == []
                 and any(isinstance(f, ast.FunctionDef) and f.name == "_build_ssl_context" for f in n.body))
    assert _calls(_named(klass, "_build_ssl_context"), "_svid_ssl_context")
    fetch = _named(tree, "_fetch_teg_policies")
    assert _calls(fetch, "_svid_ssl_context")
    sessions = _calls(fetch, "ClientSession")
    assert sessions and all(any(k.arg == "connector" for k in s.keywords) for s in sessions)


@pytest.mark.asyncio
async def test_the_policy_fetch_presents_the_svid_when_one_is_on_disk(tmp_path, monkeypatch):
    _mint(tmp_path)
    monkeypatch.setenv("SVID_CERT_DIR", str(tmp_path))
    monkeypatch.setenv("REGISTRY_URL", "https://sbx-beta-nginx-registry:8443")
    sessions = _Sessions()
    monkeypatch.setattr(ee.aiohttp, "ClientSession", sessions)
    await ee._fetch_teg_policies()
    ctx, _ = ee._svid_ssl_context()
    assert ctx is not None and len(sessions.connectors) == 1
    assert isinstance(sessions.connectors[0], aiohttp.TCPConnector) and sessions.connectors[0]._ssl is ctx


@pytest.mark.asyncio
async def test_without_an_svid_the_fetch_builds_its_session_as_before(tmp_path, monkeypatch):
    monkeypatch.setenv("SVID_CERT_DIR", str(tmp_path))
    monkeypatch.setenv("REGISTRY_URL", "http://sbx-beta-registry:8000")
    sessions = _Sessions()
    monkeypatch.setattr(ee.aiohttp, "ClientSession", sessions)
    await ee._fetch_teg_policies()
    assert sessions.connectors == [None]


def test_the_builder_follows_the_files(tmp_path, monkeypatch):
    monkeypatch.setenv("SVID_CERT_DIR", str(tmp_path))
    assert ee._svid_ssl_context() == (None, 0.0)
    _mint(tmp_path)
    first, t1 = ee._svid_ssl_context()
    again, t2 = ee._svid_ssl_context()
    assert first is not None and again is first and t1 == t2
    _mint(tmp_path, cn="teg-rotated")
    later = t1 + 30
    for name in FILES:
        os.utime(tmp_path / name, (later, later))
    rotated, t3 = ee._svid_ssl_context()
    assert rotated is not None and rotated is not first and t3 == later
    (tmp_path / "svid.0.key").unlink()
    assert ee._svid_ssl_context() == (None, 0.0)


def test_the_emitter_keeps_its_context_when_the_files_vanish(tmp_path, monkeypatch):
    monkeypatch.setenv("SVID_CERT_DIR", str(tmp_path))
    _mint(tmp_path)
    emitter = _emitter_class().__new__(_emitter_class())
    emitter._ssl_context, emitter._cert_mtime = None, 0.0
    emitter._build_ssl_context()
    held, held_mtime = emitter._ssl_context, emitter._cert_mtime
    assert held is not None and held_mtime > 0
    for name in FILES:
        (tmp_path / name).unlink()
    emitter._build_ssl_context()
    assert emitter._ssl_context is held and emitter._cert_mtime == held_mtime


@pytest.mark.asyncio
async def test_a_failed_fetch_warns_once_in_ten_minutes(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("SVID_CERT_DIR", str(tmp_path))
    monkeypatch.setenv("REGISTRY_URL", "https://sbx-beta-nginx-registry:8443")
    monkeypatch.setattr(ee, "_policy_fetch_warned_at", -1e9, raising=False)
    monkeypatch.setattr(ee.logger, "propagate", True)
    caplog.set_level(logging.DEBUG, logger=ee.logger.name)
    monkeypatch.setattr(ee.aiohttp, "ClientSession", _Sessions(status=400))
    await ee._fetch_teg_policies()
    monkeypatch.setattr(ee.aiohttp, "ClientSession", _Sessions())
    await ee._fetch_teg_policies()
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING and "[EmissionPolicy]" in r.getMessage()]
    assert len(warnings) == 1 and "400" in warnings[0].getMessage(), [r.getMessage() for r in caplog.records]
