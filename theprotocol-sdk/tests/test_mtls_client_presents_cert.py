"""§DEPS (2026-09-27): MtlsAgentClient PRESENTS its SVID to a peer that requires a client certificate, on any httpx.

httpx >= 0.28 drops `cert=` when `verify=` is a CA file path: it returns the context built from the path before it
reaches the client-certificate step (only a DeprecationWarning, hidden by default). This client passed exactly that
pair, and the SDK allows any httpx >= 0.27, so an agent installed with a current httpx dialled every mTLS peer with no
certificate. This test does a real TLS handshake against a local server that REQUIRES one.
"""
from __future__ import annotations

import asyncio
import datetime
import http.server
import ipaddress
import json
import ssl
import threading

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from theprotocol.payment.mtls_client import MtlsAgentClient


def _name(cn):
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def _issue(subject, key, issuer_name, issuer_key, *, ca, san=None, eku=None):
    # Python >= 3.13 verifies with ssl.VERIFY_X509_STRICT: a chain without key identifiers, or a CA without keyUsage, is
    # refused ("Missing Authority Key Identifier"), so this PKI carries what a real one (SPIRE's) carries.
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
    if eku is not None:
        b = b.add_extension(x509.ExtendedKeyUsage(eku), critical=False)
    return b.sign(issuer_key, hashes.SHA256())


@pytest.fixture(scope="module")
def cert_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("svid")
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca = _issue("test-ca", ca_key, _name("test-ca"), ca_key, ca=True)
    srv_key, cli_key = ec.generate_private_key(ec.SECP256R1()), ec.generate_private_key(ec.SECP256R1())
    srv = _issue("localhost", srv_key, ca.subject, ca_key, ca=False,
                 san=x509.SubjectAlternativeName([x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
                 eku=[ExtendedKeyUsageOID.SERVER_AUTH])
    cli = _issue("agent", cli_key, ca.subject, ca_key, ca=False,
                 san=x509.SubjectAlternativeName([x509.UniformResourceIdentifier("spiffe://test.local/agent/a1")]),
                 eku=[ExtendedKeyUsageOID.CLIENT_AUTH])
    pem = lambda c: c.public_bytes(serialization.Encoding.PEM)  # noqa: E731
    kpem = lambda k: k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,  # noqa: E731
                                     serialization.NoEncryption())
    (d / "bundle.pem").write_bytes(pem(ca))
    (d / "svid.pem").write_bytes(pem(cli)); (d / "key.pem").write_bytes(kpem(cli_key))
    (d / "srv.pem").write_bytes(pem(srv)); (d / "srv.key").write_bytes(kpem(srv_key))
    return d


@pytest.fixture(scope="module")
def peer(cert_dir):
    seen = []

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            seen.append(self.connection.getpeercert() or {})
            body = json.dumps({"ok": True}).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

        def log_message(self, *a):
            pass

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(cert_dir / "srv.pem"), str(cert_dir / "srv.key"))
    ctx.load_verify_locations(cafile=str(cert_dir / "bundle.pem"))
    ctx.verify_mode = ssl.CERT_REQUIRED
    httpd = http.server.HTTPServer(("127.0.0.1", 0), H)
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f"https://127.0.0.1:{httpd.server_address[1]}/health", seen
    finally:
        httpd.shutdown()


def test_the_client_presents_its_svid(peer, cert_dir):
    url, seen = peer
    client = MtlsAgentClient(cert_dir=str(cert_dir))
    loop = asyncio.new_event_loop()
    try:
        body = loop.run_until_complete(client.health_check(url))
    finally:
        loop.close()
    assert body == {"ok": True}
    assert seen and seen[-1], "the peer saw no client certificate"
