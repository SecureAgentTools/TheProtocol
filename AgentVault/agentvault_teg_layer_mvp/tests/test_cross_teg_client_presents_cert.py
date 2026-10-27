"""§DEPS (2026-09-27): the cross-TEG client PRESENTS its SPIFFE certificate to a SPIRE-verified (non-443) peer, on any httpx.

httpx 0.28 drops `cert=` when `verify=` is a CA file path (it returns the context built from the path before it reaches
the client-certificate step). CrossTEGClient passed exactly that pair (the SPIRE bundle, or the combined local +
federated bundle, as a path, plus the SVID) for every 2PC dial to a peer TEG's mTLS port: on 0.28 the peer would be
dialled with no client certificate. This test does a real TLS handshake against a local server that REQUIRES one.

RED control: run with PYTHONPATH naming the tree before the fix (AgentVault 50b89ee3 or older) inside an image with
httpx >= 0.28: the handshake is refused. On httpx 0.27 the old code still works, so the control needs 0.28.

The PKI carries key identifiers and key usage as SPIRE's certificates do: Python 3.13+ verifies with VERIFY_X509_STRICT,
which refuses a leaf with no Authority Key Identifier (this test failed on a python:3.13/3.14 TEG image until it had them;
the frames' real chains pass strict verification, measured 2026-09-28 with scratchpad/deps/tls_strict_probe.sh).
"""
from __future__ import annotations

import asyncio
import datetime
import http.server
import ipaddress
import ssl
import threading

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID


def _name(cn):
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def _issue(subject, key, issuer_name, issuer_key, *, ca, san=None):
    now = datetime.datetime.now(datetime.timezone.utc)
    b = (x509.CertificateBuilder().subject_name(_name(subject)).issuer_name(issuer_name)
         .public_key(key.public_key()).serial_number(x509.random_serial_number())
         .not_valid_before(now - datetime.timedelta(minutes=5)).not_valid_after(now + datetime.timedelta(hours=1))
         .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
         .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
         .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(issuer_key.public_key()), critical=False)
         .add_extension(x509.KeyUsage(digital_signature=not ca, content_commitment=False, key_encipherment=False,
                                      data_encipherment=False, key_agreement=False, key_cert_sign=ca, crl_sign=ca,
                                      encipher_only=False, decipher_only=False), critical=True))
    if san is not None:
        b = b.add_extension(san, critical=False)
    return b.sign(issuer_key, hashes.SHA256())


@pytest.fixture(scope="module")
def certdir(tmp_path_factory):
    d = tmp_path_factory.mktemp("certs")
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca = _issue("test-ca", ca_key, _name("test-ca"), ca_key, ca=True)
    srv_key, cli_key = ec.generate_private_key(ec.SECP256R1()), ec.generate_private_key(ec.SECP256R1())
    srv = _issue("localhost", srv_key, ca.subject, ca_key, ca=False,
                 san=x509.SubjectAlternativeName([x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]))
    cli = _issue("teg", cli_key, ca.subject, ca_key, ca=False,
                 san=x509.SubjectAlternativeName([x509.UniformResourceIdentifier("spiffe://test.local/service/teg-layer")]))
    pem = lambda c: c.public_bytes(serialization.Encoding.PEM)  # noqa: E731
    kpem = lambda k: k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,  # noqa: E731
                                     serialization.NoEncryption())
    (d / "bundle.0.pem").write_bytes(pem(ca))
    (d / "svid.0.pem").write_bytes(pem(cli)); (d / "svid.0.key").write_bytes(kpem(cli_key))
    (d / "srv.pem").write_bytes(pem(srv)); (d / "srv.key").write_bytes(kpem(srv_key))
    return d


@pytest.fixture(scope="module")
def mtls_peer(certdir):
    seen = []

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            seen.append(self.connection.getpeercert() or {})
            self.send_response(200); self.send_header("Content-Length", "2"); self.end_headers(); self.wfile.write(b"ok")

        def log_message(self, *a):
            pass

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(certdir / "srv.pem"), str(certdir / "srv.key"))
    ctx.load_verify_locations(cafile=str(certdir / "bundle.0.pem"))
    ctx.verify_mode = ssl.CERT_REQUIRED
    httpd = http.server.HTTPServer(("127.0.0.1", 0), H)
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f"https://127.0.0.1:{httpd.server_address[1]}", seen
    finally:
        httpd.shutdown()


def test_the_cross_teg_client_presents_its_certificate_to_a_spire_verified_peer(mtls_peer, certdir, monkeypatch):
    from teg_core_service.core.cross_teg.client import CrossTEGClient
    url, seen = mtls_peer
    monkeypatch.setenv("SVID_CERT_DIR", str(certdir))
    client = CrossTEGClient(teg_id="peer-teg", teg_url=url)  # a non-443 https URL: the SPIRE mTLS branch
    loop = asyncio.new_event_loop()  # a private loop: never the shared one, whatever ran before

    async def dial():
        try:
            return (await client.client.get("/")).status_code
        finally:
            await client.client.aclose()

    try:
        status = loop.run_until_complete(dial())
    finally:
        loop.close()
    assert status == 200
    assert seen and seen[-1], "the peer saw no client certificate"
