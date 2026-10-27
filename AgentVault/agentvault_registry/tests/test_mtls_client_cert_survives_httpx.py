"""§DEPS (2026-09-27): an mTLS client built the way this registry builds one PRESENTS its certificate, on any httpx.

httpx 0.28 drops `cert=` when `verify=` is a CA file path: it returns the context built from the path before it
reaches the client-certificate step, with only a DeprecationWarning (hidden by default). This registry passed exactly
that pair (the SPIRE bundle path + the SVID) from svid_client.get_client_cert_config() and two direct sites, so on
0.28 every SPIRE-verified peer would have been dialled with no client certificate. Unit tests mock the transport and
cannot see it; this one does a real TLS handshake against a local server that REQUIRES a client certificate.

The control proves the test can fail: on httpx >= 0.28 the old shape (verify=<path>, cert=<pair>) is refused by the
server. On httpx 0.27 that shape still works, so the control only asserts what it must on the version installed.

The test PKI is shaped like what SPIRE issues (key identifiers, key usage, extended key usage): Python 3.13 made
ssl.create_default_context() verify with VERIFY_X509_STRICT, which refuses a leaf with no Authority Key Identifier, and
this file's first PKI had none (2 of 4717 tests red on 3.13 and 3.14, measured 2026-09-28). Our real chains already pass
strict verification (scratchpad/deps/tls_strict_probe.sh: every sidecar, broker and cross-frame hop of the sandbox pair,
EU and ASIA, with a control leaf that has no AKI refused), so the fix is the fixture, and strict verification stays on.
"""
from __future__ import annotations

import datetime
import http.server
import ipaddress
import pathlib
import ssl
import threading

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from agentvault_registry.core.tls_client import client_cert_verify

HTTPX_028 = tuple(int(x) for x in httpx.__version__.split(".")[:2]) >= (0, 28)


def _name(cn: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def _issue(subject: str, key, issuer_name, issuer_key, *, ca: bool, san=None) -> x509.Certificate:
    now = datetime.datetime.now(datetime.timezone.utc)
    b = (x509.CertificateBuilder().subject_name(_name(subject)).issuer_name(issuer_name)
         .public_key(key.public_key()).serial_number(x509.random_serial_number())
         .not_valid_before(now - datetime.timedelta(minutes=5)).not_valid_after(now + datetime.timedelta(hours=1))
         .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
         .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
         .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(issuer_key.public_key()), critical=False))
    if ca:
        b = b.add_extension(x509.KeyUsage(digital_signature=False, content_commitment=False, key_encipherment=False,
                                          data_encipherment=False, key_agreement=False, key_cert_sign=True, crl_sign=True,
                                          encipher_only=False, decipher_only=False), critical=True)
    else:
        b = (b.add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False, key_encipherment=False,
                                           data_encipherment=False, key_agreement=False, key_cert_sign=False, crl_sign=False,
                                           encipher_only=False, decipher_only=False), critical=True)
             .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH, ExtendedKeyUsageOID.CLIENT_AUTH]),
                            critical=False))
    if san is not None:
        b = b.add_extension(san, critical=False)
    return b.sign(issuer_key, hashes.SHA256())


@pytest.fixture(scope="module")
def pki(tmp_path_factory):
    d: pathlib.Path = tmp_path_factory.mktemp("pki")
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca = _issue("test-ca", ca_key, _name("test-ca"), ca_key, ca=True)
    srv_key, cli_key = ec.generate_private_key(ec.SECP256R1()), ec.generate_private_key(ec.SECP256R1())
    srv = _issue("localhost", srv_key, ca.subject, ca_key, ca=False,
                 san=x509.SubjectAlternativeName([x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]))
    cli = _issue("spiffe-client", cli_key, ca.subject, ca_key, ca=False,
                 san=x509.SubjectAlternativeName([x509.UniformResourceIdentifier("spiffe://test.local/service/registry")]))

    def pem(cert):
        return cert.public_bytes(serialization.Encoding.PEM)

    def key_pem(k):
        return k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())

    files = {"bundle": d / "bundle.0.pem", "srv": d / "srv.pem", "srv_key": d / "srv.key",
             "svid": d / "svid.0.pem", "svid_key": d / "svid.0.key"}
    files["bundle"].write_bytes(pem(ca))
    files["srv"].write_bytes(pem(srv)); files["srv_key"].write_bytes(key_pem(srv_key))
    files["svid"].write_bytes(pem(cli)); files["svid_key"].write_bytes(key_pem(cli_key))
    return {k: str(v) for k, v in files.items()}


@pytest.fixture(scope="module")
def mtls_server(pki):
    """An HTTPS server on 127.0.0.1 that REQUIRES a client certificate chaining to the test CA."""
    seen = []

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            peer = self.connection.getpeercert() or {}
            seen.append(peer)
            self.send_response(200); self.send_header("Content-Length", "2"); self.end_headers(); self.wfile.write(b"ok")

        def log_message(self, *a):  # quiet
            pass

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(pki["srv"], pki["srv_key"])
    ctx.load_verify_locations(cafile=pki["bundle"])
    ctx.verify_mode = ssl.CERT_REQUIRED
    httpd = http.server.HTTPServer(("127.0.0.1", 0), H)
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    t = threading.Thread(target=httpd.serve_forever, daemon=True); t.start()
    try:
        yield f"https://127.0.0.1:{httpd.server_address[1]}/", seen
    finally:
        httpd.shutdown()


def _get(url: str, **kwargs) -> int:
    with httpx.Client(timeout=5.0, **kwargs) as c:
        return c.get(url).status_code


def test_the_old_shape_is_refused_on_httpx_028(mtls_server, pki):
    url, _ = mtls_server
    if not HTTPX_028:
        pytest.skip("httpx < 0.28 still loads cert= beside a path; the defect this pins does not exist there")
    with pytest.raises(httpx.HTTPError):  # the server requires a certificate the client never offered
        _get(url, verify=pki["bundle"], cert=(pki["svid"], pki["svid_key"]))


def test_the_helper_presents_the_certificate(mtls_server, pki):
    url, seen = mtls_server
    before = len(seen)
    cert = (pki["svid"], pki["svid_key"])
    assert _get(url, verify=client_cert_verify(pki["bundle"], cert), cert=cert) == 200
    assert len(seen) == before + 1 and seen[-1], "the server saw no client certificate"


def test_the_svid_client_config_presents_the_certificate(mtls_server, pki, monkeypatch):
    """get_client_cert_config() for a SPIRE-verified (non-443) target, fed straight into an httpx client."""
    from agentvault_registry.identity.svid_client import SVIDClient
    url, seen = mtls_server
    c = SVIDClient.__new__(SVIDClient)  # no workload API, no background thread: only the config path is under test
    c._lock = threading.RLock()
    c.cert_path, c.key_path, c.bundle_path = (pathlib.Path(pki["svid"]), pathlib.Path(pki["svid_key"]),
                                              pathlib.Path(pki["bundle"]))
    monkeypatch.setattr(c, "_freshest_bundle_path", lambda: pki["bundle"], raising=False)
    cfg = c.get_client_cert_config(target_url=url)
    assert cfg and cfg["cert"] == (pki["svid"], pki["svid_key"])
    assert isinstance(cfg["verify"], ssl.SSLContext)
    before = len(seen)
    assert _get(url, **cfg) == 200
    assert len(seen) == before + 1 and seen[-1]


def test_every_other_combination_is_left_alone(pki):
    cert = (pki["svid"], pki["svid_key"])
    assert client_cert_verify(True, cert) is True
    assert client_cert_verify(False, cert) is False
    ctx = ssl.create_default_context()
    assert client_cert_verify(ctx, cert) is ctx
    assert client_cert_verify(pki["bundle"], None) == pki["bundle"]


def test_the_helper_keeps_the_interpreters_strict_verification(pki):
    """On Python 3.13+ ssl.create_default_context() verifies with VERIFY_X509_STRICT, and our chains pass it (see the
    module docstring). The helper must not switch it off to make a chain work: fix the chain. On 3.11 and 3.12 the
    default does not set it and neither does the helper, so this compares with the interpreter's own default."""
    ctx = client_cert_verify(pki["bundle"], (pki["svid"], pki["svid_key"]))
    strict = getattr(ssl, "VERIFY_X509_STRICT", 0)
    assert isinstance(ctx, ssl.SSLContext) and strict
    assert bool(ctx.verify_flags & strict) == bool(ssl.create_default_context().verify_flags & strict)
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname is True
