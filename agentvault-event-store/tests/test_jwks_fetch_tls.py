"""§MTLSHOPS V0379 (2026-09-15): the store's JWKS read presents its SVID, so it can pass nginx-registry.

The store verifies the JWT-SVIDs its websocket clients present against the registry's JWKS (EVENTSTORE_JWT_JWKS_URL).
Today that URL is the registry's plain port. agentvault2-b5's registry terminator (b2) moves it behind nginx-registry,
which verifies client certificates. A bare httpx.get presents no certificate and trusts the system roots only, so after
b2 every websocket JWT would fail with jwks_fetch_failed.

  1. (behaviour) client_tls_kwargs gives nothing for http and nothing when the store holds no SVID;
  2. (behaviour, a real handshake) for https it gives a context that trusts the SPIRE bundle, checks the hostname and
     presents the SVID: a local server that requires a client certificate from the bundle's CA answers the JWKS, and
     the same call without the kwargs is refused;
  3. (structure) every httpx.get in routers/websocket.py's _validate_jwt passes **client_tls_kwargs(<its url>).

RED control: the tree before this change has no src/client_tls.py (1 and 2 fail) and two bare httpx.get calls (3 fails).
The PKI carries key identifiers and key usage as SPIRE's certificates do: Python 3.13+ verifies with VERIFY_X509_STRICT,
which refuses a leaf with no Authority Key Identifier (this file failed on a python:3.14 store image until it had them;
the frames' real chains pass strict verification, measured 2026-09-28 with scratchpad/deps/tls_strict_probe.sh).
Run: python -m pytest tests/test_jwks_fetch_tls.py -q   (needs pytest, httpx and cryptography)
"""
import ast
import datetime
import ipaddress
import socket
import ssl
import sys
import threading
from pathlib import Path

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

WEBSOCKET = ROOT / "src" / "routers" / "websocket.py"
JWKS_BODY = b'{"keys": []}'


def _client_tls():
    from src import client_tls
    return client_tls


def _pem(obj):
    if isinstance(obj, x509.Certificate):
        return obj.public_bytes(serialization.Encoding.PEM)
    return obj.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())


def _cert(subject_cn, issuer_name, issuer_key, key, *, ca=False, sans=(), eku=None):
    now = datetime.datetime.now(datetime.timezone.utc)
    builder = (x509.CertificateBuilder()
               .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, subject_cn)]))
               .issuer_name(issuer_name).public_key(key.public_key()).serial_number(x509.random_serial_number())
               .not_valid_before(now - datetime.timedelta(minutes=1)).not_valid_after(now + datetime.timedelta(hours=1))
               .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
               .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
               .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(issuer_key.public_key()), critical=False)
               .add_extension(x509.KeyUsage(digital_signature=not ca, content_commitment=False, key_encipherment=False,
                                            data_encipherment=False, key_agreement=False, key_cert_sign=ca, crl_sign=ca,
                                            encipher_only=False, decipher_only=False), critical=True))
    if sans:
        builder = builder.add_extension(x509.SubjectAlternativeName(list(sans)), critical=False)
    if eku:
        builder = builder.add_extension(x509.ExtendedKeyUsage([eku]), critical=False)
    return builder.sign(issuer_key, hashes.SHA256())


@pytest.fixture
def pki(tmp_path, monkeypatch):
    """A bundle CA, a server certificate for localhost and an SVID, all from the same CA. The store's files go where
    CERT_DIR points."""
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(name, raising=False)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "store-test-bundle")])
    ca = _cert("store-test-bundle", ca_name, ca_key, ca_key, ca=True)
    server_key = ec.generate_private_key(ec.SECP256R1())
    server = _cert("localhost", ca_name, ca_key, server_key,
                   sans=(x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))),
                   eku=ExtendedKeyUsageOID.SERVER_AUTH)
    svid_key = ec.generate_private_key(ec.SECP256R1())
    svid = _cert("store-svid", ca_name, ca_key, svid_key,
                 sans=(x509.UniformResourceIdentifier("spiffe://sandbox-b.theprotocol.cloud/service/event-store"),),
                 eku=ExtendedKeyUsageOID.CLIENT_AUTH)
    certs = tmp_path / "certs"
    certs.mkdir()
    (certs / "bundle.0.pem").write_bytes(_pem(ca))
    (certs / "svid.0.pem").write_bytes(_pem(svid))
    (certs / "svid.0.key").write_bytes(_pem(svid_key))
    (tmp_path / "server.pem").write_bytes(_pem(server))
    (tmp_path / "server.key").write_bytes(_pem(server_key))
    monkeypatch.setenv("CERT_DIR", str(certs))
    return tmp_path


def _serve_one_jwks_request(pki_dir):
    """A server that REQUIRES a client certificate from the bundle's CA; it answers one request, then closes."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(pki_dir / "server.pem", pki_dir / "server.key")
    ctx.load_verify_locations(pki_dir / "certs" / "bundle.0.pem")
    ctx.verify_mode = ssl.CERT_REQUIRED
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(10)
    seen = {}

    def run():
        try:
            conn, _ = listener.accept()
            conn.settimeout(10)
            with ctx.wrap_socket(conn, server_side=True) as tls:
                seen["client_cn"] = dict(item[0] for item in tls.getpeercert()["subject"]).get("commonName")
                tls.recv(65536)
                tls.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %d\r\n"
                            b"Connection: close\r\n\r\n" % len(JWKS_BODY) + JWKS_BODY)
        except Exception as e:  # the refused handshake lands here, and the test reads it
            seen["error"] = type(e).__name__
        finally:
            listener.close()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return listener.getsockname()[1], seen, thread


def test_plain_http_and_no_svid_get_nothing(tmp_path, monkeypatch):
    ct = _client_tls()
    monkeypatch.setenv("CERT_DIR", str(tmp_path))
    assert ct.client_tls_kwargs("https://sbx-beta-nginx-registry:8443/api/v1/spire/jwks") == {}
    (tmp_path / "svid.0.pem").write_text("x")
    (tmp_path / "svid.0.key").write_text("x")
    assert ct.client_tls_kwargs("http://sbx-beta-registry:8000/api/v1/spire/jwks") == {}


def test_https_presents_the_svid_and_trusts_the_bundle(pki):
    ct = _client_tls()
    port, seen, thread = _serve_one_jwks_request(pki)
    url = f"https://localhost:{port}/api/v1/spire/jwks"
    kwargs = ct.client_tls_kwargs(url)
    assert set(kwargs) == {"verify"} and isinstance(kwargs["verify"], ssl.SSLContext)
    assert kwargs["verify"].check_hostname and kwargs["verify"].verify_mode == ssl.CERT_REQUIRED
    resp = httpx.get(url, timeout=5.0, **kwargs)
    thread.join(10)
    assert resp.status_code == 200 and resp.json() == {"keys": []}
    assert seen.get("client_cn") == "store-svid", seen


def test_control_the_same_call_without_the_kwargs_is_refused(pki):
    port, seen, thread = _serve_one_jwks_request(pki)
    with pytest.raises(httpx.ConnectError):
        httpx.get(f"https://localhost:{port}/api/v1/spire/jwks", timeout=5.0)
    thread.join(10)
    assert "client_cn" not in seen


def test_every_jwks_get_in_validate_jwt_passes_the_tls_kwargs():
    tree = ast.parse(WEBSOCKET.read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_validate_jwt")
    gets = [n for n in ast.walk(fn) if isinstance(n, ast.Call) and ast.unparse(n.func) == "httpx.get"]
    assert len(gets) == 2, f"expected the fetch and the kid-miss refresh, found {len(gets)}"
    for call in gets:
        starred = [k.value for k in call.keywords if k.arg is None]
        assert any(isinstance(v, ast.Call) and ast.unparse(v.func) == "client_tls_kwargs"
                   and ast.unparse(v.args[0]) == ast.unparse(call.args[0]) for v in starred), ast.unparse(call)
