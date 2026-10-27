"""§MTLSHOPS G2 (2026-09-15) — the registry counts a forwarded client certificate only when this frame's own TLS
terminator vouched for it.

Row 197 (test_cert_chain_verification.py) made a header-supplied certificate chain to the trust bundle, which proves the
certificate is genuine. Whether the request came through this frame's own terminator is a second question, answered by a
marker: X-Registry-Proxy-Auth equal to a usable REGISTRY_PROXY_TRUST_SECRET (constant time) and the verdict SUCCESS; without
a usable secret the header path is off. The two presence checks that read the header as "a federation peer" (the admin path
throttle's exemption and the admission lane) ask the same question.

The chain check is replaced by a pass here, so the marker is the only variable; row 197's tests cover the chain.
RED control: run this file with PYTHONPATH naming the tree before the fix. The refusal tests and the census fail there;
the positive controls pass.
"""
from __future__ import annotations

import ast
import datetime
import pathlib
import urllib.parse

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from fastapi import HTTPException
from starlette.datastructures import Headers
from starlette.requests import Request

from agentvault_registry.core import mtls_auth

MARKER = "X-Registry-Proxy-Auth"
# A made-up value of the right shape (never a real secret): 40 characters, many distinct.
SECRET = "test-only-marker-0123456789-abcdefghijkl"
PEER = "spiffe://asia.theprotocol.cloud/service/registry"
PKG = pathlib.Path(mtls_auth.__file__).resolve().parents[1]


def _escaped_leaf(uri: str) -> str:
    key = ec.generate_private_key(ec.SECP256R1())
    now = datetime.datetime.now(datetime.timezone.utc)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "workload")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(hours=1))
        .add_extension(x509.SubjectAlternativeName([x509.UniformResourceIdentifier(uri)]), critical=False)
        .sign(key, hashes.SHA256())
    )
    # nginx forwards $ssl_client_escaped_cert: the PEM, URL-escaped
    return urllib.parse.quote(cert.public_bytes(serialization.Encoding.PEM).decode())


def _raw(headers: dict):
    return [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in headers.items() if v is not None]


def _request(headers: dict, path: str = "/api/v1/federation/agent-cards/sync") -> Request:
    return Request({"type": "http", "method": "POST", "path": path, "raw_path": path.encode(),
                    "query_string": b"", "headers": _raw(headers)})


def _vouched(uri: str = PEER, **over) -> dict:
    h = {"X-SSL-Client-Cert": _escaped_leaf(uri), "X-SSL-Client-Verify": "SUCCESS", MARKER: SECRET}
    h.update(over)
    return h


def _without_marker(h: dict) -> dict:
    return {k: v for k, v in h.items() if k != MARKER}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("REGISTRY_PROXY_TRUST_SECRET", SECRET)
    monkeypatch.setattr(mtls_auth, "TRUSTED_SPIFFE_DOMAINS",
                        ["asia.theprotocol.cloud", "eu.theprotocol.cloud", "agentvault.com"])
    monkeypatch.setattr(mtls_auth, "verify_cert_against_bundle", lambda der: (True, "chain accepted for this test"))


async def _identity(headers: dict) -> str:
    return await mtls_auth.get_client_spiffe_id(_request(headers))


def test_the_marker_and_the_secret_shape(monkeypatch):
    assert mtls_auth.PROXY_MARKER_HEADER == MARKER
    assert mtls_auth.proxy_secret_usable(SECRET)
    for bad in (None, "", "   ", "short-secret", "a" * 40, "abab" * 10):
        assert not mtls_auth.proxy_secret_usable(bad), bad
    assert mtls_auth.method1_proxy_trust() is True
    monkeypatch.delenv("REGISTRY_PROXY_TRUST_SECRET")
    assert mtls_auth.method1_proxy_trust() is False


async def test_positive_control_a_vouched_certificate_authenticates():
    assert await _identity(_vouched()) == PEER


async def test_a_chained_certificate_without_the_marker_is_refused():
    with pytest.raises(HTTPException) as exc:
        await _identity(_without_marker(_vouched()))
    assert exc.value.status_code == 401


async def test_a_wrong_marker_is_refused():
    with pytest.raises(HTTPException) as exc:
        await _identity(_vouched(**{MARKER: SECRET[:-1] + "X"}))
    assert exc.value.status_code == 401


@pytest.mark.parametrize("verdict", ["FAILED:certificate has expired", "NONE", "", None])
async def test_only_the_verdict_success_counts(verdict):
    with pytest.raises(HTTPException) as exc:
        await _identity(_vouched(**{"X-SSL-Client-Verify": verdict}))
    assert exc.value.status_code == 401


async def test_without_a_usable_secret_the_header_path_is_off(monkeypatch):
    monkeypatch.setenv("REGISTRY_PROXY_TRUST_SECRET", "short-secret")
    with pytest.raises(HTTPException):
        await _identity(_vouched(**{MARKER: "short-secret"}))
    monkeypatch.delenv("REGISTRY_PROXY_TRUST_SECRET")
    with pytest.raises(HTTPException):
        await _identity(_vouched(**{MARKER: "anything"}))


async def test_the_optional_federation_identity_ignores_a_written_header():
    from agentvault_registry.routers import federation_public as fp

    uri = "spiffe://agentvault.com/service/registry-a"
    assert await fp.get_optional_client_spiffe_id(_request(_vouched(uri=uri))) == uri
    assert await fp.get_optional_client_spiffe_id(_request(_without_marker(_vouched(uri=uri)))) is None


def test_the_admission_lane_needs_a_vouched_certificate():
    from agentvault_registry.middleware.admission_control import _classify_lane

    written = _without_marker(_vouched())
    written["X-Real-IP"] = "198.51.100.7"
    assert _classify_lane(Headers(raw=_raw(written))) == "client"
    vouched = _vouched()
    vouched["X-Real-IP"] = "198.51.100.7"
    assert _classify_lane(Headers(raw=_raw(vouched))) == "internal"


def test_the_registrys_readers_of_the_certificate_header():
    readers, presence = {}, []
    for path in PKG.rglob("*.py"):
        rel = path.relative_to(PKG).as_posix()
        if rel.startswith("static/") or "node_modules" in rel:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get"
                    and node.args and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str) and node.args[0].value.lower() == "x-ssl-client-cert"):
                readers[rel] = readers.get(rel, 0) + 1
            if (isinstance(node, ast.Compare) and any(isinstance(op, (ast.In, ast.NotIn)) for op in node.ops)
                    and isinstance(node.left, ast.Constant) and isinstance(node.left.value, str)
                    and node.left.value.lower() == "x-ssl-client-cert"):
                presence.append(rel)
    assert set(readers) == {"core/mtls_auth.py"}, readers
    assert presence == [], presence
