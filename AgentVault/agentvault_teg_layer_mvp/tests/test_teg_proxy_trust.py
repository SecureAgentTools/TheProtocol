"""§MTLSHOPS G1 (2026-09-15) — the TEG counts a forwarded client certificate only when this frame's own TLS terminator
vouched for it.

nginx-teg terminates mTLS and forwards X-SSL-Client-Verify and X-SSL-Client-Cert. Headers are only as trustworthy as their
sender, so the rule is: X-TEG-Proxy-Auth equal to a usable TEG_PROXY_TRUST_SECRET (constant time) and the verdict SUCCESS;
without a usable secret the header path is off.

The certificates are real (minted here), so the refused cases are the ones a caller can actually send.
RED control: run this file with PYTHONPATH naming the tree before the fix. The refusal tests fail there (the old reader
returns the identity with no marker at all), the census counts two readers, and the positive controls still pass.
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
from starlette.requests import Request

from teg_core_service.core import internal_auth as ia

MARKER = "X-TEG-Proxy-Auth"
# A made-up value of the right shape (never a real secret): 40 characters, many distinct.
SECRET = "test-only-marker-0123456789-abcdefghijkl"
REGISTRY = "spiffe://sandbox-b.theprotocol.cloud/service/registry"
SRC = pathlib.Path(ia.__file__).resolve().parents[1]


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


def _request(headers: dict, path: str = "/api/v1/admin/fx/reserve") -> Request:
    raw = [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in headers.items() if v is not None]
    return Request({"type": "http", "method": "GET", "path": path, "raw_path": path.encode(),
                    "query_string": b"", "headers": raw})


def _vouched(uri: str = REGISTRY, **over) -> dict:
    h = {"X-SSL-Client-Cert": _escaped_leaf(uri), "X-SSL-Client-Verify": "SUCCESS", MARKER: SECRET}
    h.update(over)
    return h


def _without_marker(h: dict) -> dict:
    return {k: v for k, v in h.items() if k != MARKER}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("TRUSTED_SPIFFE_DOMAINS", "sandbox-b.theprotocol.cloud,sandbox-a.theprotocol.cloud")
    monkeypatch.setenv("TEG_PROXY_TRUST_SECRET", SECRET)
    monkeypatch.delenv("TEG_MTLS_REQUIRED", raising=False)


def test_the_marker_and_the_secret_shape(monkeypatch):
    assert ia.PROXY_MARKER_HEADER == MARKER
    assert ia.proxy_secret_usable(SECRET)
    for bad in (None, "", "   ", "short-secret", "a" * 40, "abab" * 10):
        assert not ia.proxy_secret_usable(bad), bad
    assert ia.method1_proxy_trust() is True
    monkeypatch.setenv("TEG_PROXY_TRUST_SECRET", "short-secret")
    assert ia.method1_proxy_trust() is False
    monkeypatch.delenv("TEG_PROXY_TRUST_SECRET")
    assert ia.method1_proxy_trust() is False


def test_positive_control_a_vouched_certificate_names_its_caller():
    assert ia.extract_spiffe_from_request(_request(_vouched())) == REGISTRY


def test_a_certificate_without_the_marker_is_not_an_identity():
    assert ia.extract_spiffe_from_request(_request(_without_marker(_vouched()))) is None


def test_a_wrong_marker_is_not_an_identity():
    assert ia.extract_spiffe_from_request(_request(_vouched(**{MARKER: SECRET[:-1] + "X"}))) is None


@pytest.mark.parametrize("verdict", ["FAILED:certificate has expired", "NONE", "", None])
def test_only_the_verdict_success_counts(verdict):
    assert ia.extract_spiffe_from_request(_request(_vouched(**{"X-SSL-Client-Verify": verdict}))) is None


def test_without_a_usable_secret_the_header_path_is_off(monkeypatch):
    monkeypatch.setenv("TEG_PROXY_TRUST_SECRET", "short-secret")
    assert ia.extract_spiffe_from_request(_request(_vouched(**{MARKER: "short-secret"}))) is None
    monkeypatch.delenv("TEG_PROXY_TRUST_SECRET")
    assert ia.extract_spiffe_from_request(_request(_vouched(**{MARKER: "anything"}))) is None


def test_positive_control_an_untrusted_domain_stays_refused_behind_the_marker():
    assert ia.extract_spiffe_from_request(_request(_vouched(uri="spiffe://evil.example/service/registry"))) is None


def test_the_resolver_refuses_a_written_header_and_accepts_the_terminators(monkeypatch):
    monkeypatch.setenv("TEG_MTLS_REQUIRED", "true")
    with pytest.raises(HTTPException) as exc:
        ia.resolve_internal_caller(_request(_without_marker(_vouched())))
    assert exc.value.status_code == 403
    assert ia.resolve_internal_caller(_request(_vouched())) == ("mtls", REGISTRY)


def _header_get_calls(tree: ast.AST, name: str):
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get"
                and node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == name
                and isinstance(node.func.value, ast.Attribute) and node.func.value.attr == "headers"):
            yield node


def test_the_tegs_one_reader_of_the_certificate_header():
    readers = {}
    for path in SRC.rglob("*.py"):
        n = sum(1 for _ in _header_get_calls(ast.parse(path.read_text()), "X-SSL-Client-Cert"))
        if n:
            readers[str(path.relative_to(SRC))] = n
    assert readers == {"core/internal_auth.py": 1}, readers
    router = ast.parse((SRC / "api" / "cross_teg_router.py").read_text())
    fn = next(n for n in router.body if isinstance(n, ast.FunctionDef) and n.name == "_extract_spiffe_from_header")
    calls = {getattr(c.func, "id", None) for c in ast.walk(fn) if isinstance(c, ast.Call)}
    assert "extract_spiffe_from_request" in calls


def test_health_reports_the_posture():
    main = ast.parse((SRC / "main.py").read_text())
    fn = next(n for n in main.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "health_check")
    src = ast.unparse(fn)
    assert "health_status['mtls']" in src and "method1_proxy_trust" in src and "mtls_required" in src
