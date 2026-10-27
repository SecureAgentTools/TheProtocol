"""§MTLSHOPS T2 (S4, 2026-09-15): the solo auditor's store read is TLS by scheme (src/auditor/tls_client.py).

A real TLS server stands in for nginx-event-store: its certificate carries the gateway's name, it requires a client
certificate the lab CA signed, and it answers the supply-audit read. Pinned: https presents AUDITOR_TLS_CERT/KEY and
verifies the server against AUDITOR_TLS_CA with the hostname checked (a certificate without the gateway's name fails the
handshake: agentvault2-85's control, which a CA load alone would pass); X-Internal-Key travels only when a key is set; http
reads are unchanged. TLS_CLIENT_PATH points the suite at another copy of the module (the red controls).
"""
import asyncio
import datetime
import http.server
import importlib.util
import json
import os
import socket
import ssl
import threading

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_path = os.getenv("TLS_CLIENT_PATH") or os.path.join(HERE, "src", "auditor", "tls_client.py")
_spec = importlib.util.spec_from_file_location("tls_client_under_test", _path)
tls = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tls)

GATEWAY = "kitproof-nginx-event-store"
NOW = datetime.datetime.now(datetime.timezone.utc)


def _write(path, key, cert):
    path.with_suffix(".key").write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                           serialization.NoEncryption()))
    path.with_suffix(".pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return str(path.with_suffix(".pem")), str(path.with_suffix(".key"))


def _ca(tmp, name):
    k = ec.generate_private_key(ec.SECP256R1())
    subj = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    c = (x509.CertificateBuilder().subject_name(subj).issuer_name(subj).public_key(k.public_key())
         .serial_number(x509.random_serial_number())
         .not_valid_before(NOW - datetime.timedelta(minutes=5)).not_valid_after(NOW + datetime.timedelta(hours=1))
         .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
         .add_extension(x509.KeyUsage(True, False, False, False, False, True, True, False, False), critical=True)
         .add_extension(x509.SubjectKeyIdentifier.from_public_key(k.public_key()), critical=False)
         .sign(k, hashes.SHA256()))
    pem, _ = _write(tmp / name, k, c)
    return k, c, pem


def _leaf(tmp, name, ca, sans):
    ca_key, ca_cert, _ = ca
    k = ec.generate_private_key(ec.SECP256R1())
    c = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)]))
         .issuer_name(ca_cert.subject).public_key(k.public_key()).serial_number(x509.random_serial_number())
         .not_valid_before(NOW - datetime.timedelta(minutes=5)).not_valid_after(NOW + datetime.timedelta(hours=1))
         .add_extension(x509.SubjectAlternativeName(sans), critical=False)
         .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
         .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH, ExtendedKeyUsageOID.CLIENT_AUTH]), critical=False)
         .add_extension(x509.SubjectKeyIdentifier.from_public_key(k.public_key()), critical=False)
         .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
         .sign(ca_key, hashes.SHA256()))
    return _write(tmp / name, k, c)


class _Store:
    """The supply-audit route behind a TLS terminator that requires a client certificate (or plain, for the http case)."""

    def __init__(self, cert=None, key=None, ca=None):
        self.seen = []
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                peer = self.connection.getpeercert() if isinstance(self.connection, ssl.SSLSocket) else None
                outer.seen.append({"path": self.path, "key": self.headers.get("X-Internal-Key"), "client_cert": bool(peer)})
                body = json.dumps({"tokens_issued": 5, "total_circulating": 5, "delta": 0.0, "status": "OK"}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        if cert:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(cert, key)
            ctx.verify_mode = ssl.CERT_REQUIRED
            ctx.load_verify_locations(ca)
            self.httpd.socket = ctx.wrap_socket(self.httpd.socket, server_side=True)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def pki(tmp_path, monkeypatch):
    real = socket.getaddrinfo
    # anyio hands getaddrinfo the IDNA-encoded name as bytes
    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda host, *a, **k: real("127.0.0.1" if host in (GATEWAY, GATEWAY.encode()) else host, *a, **k))
    frame_ca = _ca(tmp_path, "frame-ca")
    other_ca = _ca(tmp_path, "other-ca")
    return {
        "ca": frame_ca[2], "other_ca": other_ca[2],
        "gateway": _leaf(tmp_path, "gateway", frame_ca, [x509.DNSName(GATEWAY), x509.UniformResourceIdentifier("spiffe://lab.test/service/registry")]),
        "wrong_name": _leaf(tmp_path, "wrong-name", frame_ca, [x509.DNSName("kitproof-event-store")]),
        "auditor": _leaf(tmp_path, "auditor", frame_ca, [x509.UniformResourceIdentifier("spiffe://lab.test/service/auditor")]),
    }


def _read(url, store_key=None, **tls_args):
    return asyncio.run(tls.read_supply_audit(url, store_key, timeout=5.0, **tls_args))


def test_https_presents_the_auditors_svid_and_reads_the_gateway(pki):
    store = _Store(*pki["gateway"], ca=pki["ca"])
    try:
        cert, key = pki["auditor"]
        data = _read(f"https://{GATEWAY}:{store.port}", None, cert=cert, key=key, ca=pki["ca"])
        assert data["delta"] == 0.0 and data["status"] == "OK"
        assert store.seen == [{"path": "/api/v1/projections/supply-audit", "key": None, "client_cert": True}]
    finally:
        store.close()


def test_a_gateway_certificate_without_the_gateways_name_fails_the_handshake(pki):
    store = _Store(*pki["wrong_name"], ca=pki["ca"])
    try:
        cert, key = pki["auditor"]
        with pytest.raises(httpx.ConnectError) as err:
            _read(f"https://{GATEWAY}:{store.port}", None, cert=cert, key=key, ca=pki["ca"])
        assert "Hostname mismatch" in str(err.value), str(err.value)
        assert store.seen == []
    finally:
        store.close()


def test_a_bundle_that_does_not_chain_the_gateway_fails_the_handshake(pki):
    store = _Store(*pki["gateway"], ca=pki["ca"])
    try:
        cert, key = pki["auditor"]
        with pytest.raises(httpx.ConnectError):
            _read(f"https://{GATEWAY}:{store.port}", None, cert=cert, key=key, ca=pki["other_ca"])
        assert store.seen == []
    finally:
        store.close()


def test_without_a_client_certificate_the_gateway_refuses(pki):
    store = _Store(*pki["gateway"], ca=pki["ca"])
    try:
        # measured over 300 reads: httpx.ReadError 259 times, and 41 times the TLS 1.3 alert surfaced as a bare ssl.SSLError
        # (TLSV13_ALERT_CERTIFICATE_REQUIRED); the audit loop catches either as a failed live read
        with pytest.raises((httpx.TransportError, ssl.SSLError)):
            _read(f"https://{GATEWAY}:{store.port}", None, ca=pki["ca"])
        assert store.seen == []
    finally:
        store.close()


def test_the_store_key_travels_only_when_set(pki):
    store = _Store(*pki["gateway"], ca=pki["ca"])
    try:
        cert, key = pki["auditor"]
        _read(f"https://{GATEWAY}:{store.port}", "", cert=cert, key=key, ca=pki["ca"])
        _read(f"https://{GATEWAY}:{store.port}", "a-key", cert=cert, key=key, ca=pki["ca"])
        assert [s["key"] for s in store.seen] == [None, "a-key"]
    finally:
        store.close()


def test_http_reads_are_unchanged():
    assert tls.client_kwargs("http://frame-a-event-store:8200", "/certs/svid.0.pem", "/certs/svid.0.key", "/certs/bundle.0.pem") == {}
    store = _Store()
    try:
        data = _read(f"http://127.0.0.1:{store.port}", "legacy-key", cert="/nonexistent.pem", key="/nonexistent.key", ca="/nonexistent.pem")
        assert data["status"] == "OK"
        assert store.seen == [{"path": "/api/v1/projections/supply-audit", "key": "legacy-key", "client_cert": False}]
    finally:
        store.close()
