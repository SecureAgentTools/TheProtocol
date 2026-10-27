"""§FRAMELIC findings row 197 — a header-supplied certificate must CHAIN, not merely parse.

`get_client_spiffe_id` accepts a client certificate out of the `X-SSL-Client-Cert` header,
because a proxy that terminated mTLS has no other way to hand it over. It used to PARSE that
certificate and trust the SPIFFE ID inside it with no verification at all, which made the app's
identity decision entirely dependent on every edge in front of it pinning the header. Row 194 is
what that costs when an edge does not: a self-signed certificate in a plain header authenticated
from the internet, on six live nodes.

These tests build their own CAs so the adversarial cases are real rather than described. The one
that matters most is `test_a_forged_ca_with_a_matching_subject_is_refused`: an attacker does not
self-sign a leaf — they mint their OWN CA, give it the same SUBJECT as a root we trust so it is
selected as a candidate issuer, and sign whatever identity they like with it. Only the signature
check stops that, and only if it is actually performed.
"""
import datetime
import os

import pytest
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from agentvault_registry.core import mtls_auth

TRUSTED_URI = "spiffe://eu.theprotocol.cloud/service/registry-eu"
ROOT_NAME = x509.Name([
    x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
    x509.NameAttribute(NameOID.ORGANIZATION_NAME, "SPIFFE"),
    x509.NameAttribute(NameOID.SERIAL_NUMBER, "12345678901234567890"),
])


def _key():
    return ec.generate_private_key(ec.SECP256R1(), default_backend())


def _ca(name=ROOT_NAME, *, days_valid=3650, is_ca=True):
    k = _key()
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name)
        .public_key(k.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=days_valid))
        .add_extension(x509.BasicConstraints(ca=is_ca, path_length=None), critical=True)
        .sign(k, hashes.SHA256(), default_backend())
    )
    return k, cert


def _leaf(ca_key, ca_cert, *, uri=TRUSTED_URI, not_before_days=-1, not_after_days=365):
    k = _key()
    now = datetime.datetime.now(datetime.timezone.utc)
    return (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "workload")]))
        .issuer_name(ca_cert.subject)
        .public_key(k.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now + datetime.timedelta(days=not_before_days))
        .not_valid_after(now + datetime.timedelta(days=not_after_days))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.SubjectAlternativeName([x509.UniformResourceIdentifier(uri)]),
                       critical=False)
        .sign(ca_key, hashes.SHA256(), default_backend())
    )


def _der(cert):
    return cert.public_bytes(serialization.Encoding.DER)


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    """A real trust bundle on disk, and the module pointed at it."""
    ca_key, ca_cert = _ca()
    p = tmp_path / "bundle.0.pem"
    p.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
    monkeypatch.setattr(mtls_auth, "_bundle_path", lambda: str(p))
    mtls_auth._BUNDLE_CACHE["key"] = None      # the cache is keyed on (path, mtime, size)
    return ca_key, ca_cert, p


# ── the happy path ────────────────────────────────────────────────────────────────────────

def test_a_leaf_signed_by_a_bundle_root_verifies(bundle):
    ca_key, ca_cert, _ = bundle
    ok, why = mtls_auth.verify_cert_against_bundle(_der(_leaf(ca_key, ca_cert)))
    assert ok, why


# ── the adversarial cases ─────────────────────────────────────────────────────────────────

def test_a_self_signed_certificate_is_refused(bundle):
    """Row 194's exact shape: the certificate a forger reaches for first."""
    own_key, own_cert = _ca(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "attacker")]))
    ok, why = mtls_auth.verify_cert_against_bundle(_der(_leaf(own_key, own_cert)))
    assert not ok
    assert "not a root in our trust bundle" in why


def test_a_forged_ca_with_a_matching_subject_is_refused(bundle):
    """🔴 THE ONE THAT MATTERS. Selecting a candidate issuer by SUBJECT is a lookup, not a check.
    An attacker who mints their own CA carrying the SAME subject as a root we hold will be
    selected as a candidate — and must then fail on the signature. If this test ever goes green
    for the wrong reason, the whole verification is decorative."""
    forged_key, forged_cert = _ca(ROOT_NAME)     # same Name as the trusted root, different key
    leaf = _leaf(forged_key, forged_cert)
    assert leaf.issuer == ROOT_NAME, "the forgery must be selected as a candidate to be a real test"
    ok, why = mtls_auth.verify_cert_against_bundle(_der(leaf))
    assert not ok
    assert "signature does not verify" in why


def test_an_expired_leaf_is_refused(bundle):
    ca_key, ca_cert, _ = bundle
    ok, why = mtls_auth.verify_cert_against_bundle(
        _der(_leaf(ca_key, ca_cert, not_before_days=-400, not_after_days=-30)))
    assert not ok
    assert "expired" in why


def test_a_not_yet_valid_leaf_is_refused(bundle):
    ca_key, ca_cert, _ = bundle
    ok, why = mtls_auth.verify_cert_against_bundle(
        _der(_leaf(ca_key, ca_cert, not_before_days=5, not_after_days=400)))
    assert not ok
    assert "not yet valid" in why


def test_a_non_ca_issuer_is_refused(tmp_path, monkeypatch):
    """A bundle entry that is not a CA cannot vouch for anything."""
    key, cert = _ca(is_ca=False)
    p = tmp_path / "bundle.0.pem"
    p.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    monkeypatch.setattr(mtls_auth, "_bundle_path", lambda: str(p))
    mtls_auth._BUNDLE_CACHE["key"] = None
    ok, why = mtls_auth.verify_cert_against_bundle(_der(_leaf(key, cert)))
    assert not ok


def test_no_bundle_fails_CLOSED(monkeypatch):
    """'We could not check' must never read as 'it was fine' — that is the entire class this
    change exists to close."""
    monkeypatch.setattr(mtls_auth, "_bundle_path", lambda: None)
    mtls_auth._BUNDLE_CACHE["key"] = None
    own_key, own_cert = _ca()
    ok, why = mtls_auth.verify_cert_against_bundle(_der(_leaf(own_key, own_cert)))
    assert not ok
    assert "no trust bundle" in why


def test_garbage_is_refused_without_raising(bundle):
    ok, why = mtls_auth.verify_cert_against_bundle(b"not a certificate")
    assert not ok
    assert "unparseable" in why


# ── the freshness rule (§BATCH7) ──────────────────────────────────────────────────────────

def test_a_root_added_after_the_first_read_is_picked_up(tmp_path, monkeypatch):
    """A federation approved AFTER boot reaches the cert-writer's bundle on its next cycle. A
    verifier holding a boot-time snapshot would refuse the new peer for up to 30 minutes — the
    §BATCH7 incident, in a verifier instead of an httpx client."""
    ca_key, ca_cert = _ca()
    p = tmp_path / "bundle.0.pem"
    p.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
    monkeypatch.setattr(mtls_auth, "_bundle_path", lambda: str(p))
    mtls_auth._BUNDLE_CACHE["key"] = None

    peer_name = x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, "SPIFFE"),
                           x509.NameAttribute(NameOID.SERIAL_NUMBER, "99999999")])
    peer_key, peer_cert = _ca(peer_name)
    peer_leaf = _leaf(peer_key, peer_cert)
    assert not mtls_auth.verify_cert_against_bundle(_der(peer_leaf))[0], "peer not trusted yet"

    # the cert-writer appends the newly federated peer's root
    with open(p, "ab") as fh:
        fh.write(peer_cert.public_bytes(serialization.Encoding.PEM))
    os.utime(p, None)

    ok, why = mtls_auth.verify_cert_against_bundle(_der(peer_leaf))
    assert ok, f"the new root must be picked up without a restart: {why}"


# ── THE WIRING. A verified helper that nothing calls is decorative. ───────────────────────

class _Hdrs(dict):
    def __init__(self, m):
        super().__init__({k.lower(): v for k, v in m.items()})

    def get(self, k, d=None):
        return super().get(str(k).lower(), d)

    def __contains__(self, k):
        return super().__contains__(str(k).lower())


class _Req:
    def __init__(self, **h):
        self.headers = _Hdrs({k.replace("_", "-"): v for k, v in h.items()})
        self.scope = {}
        self.client = None


def _pem_header(cert):
    import urllib.parse
    return urllib.parse.quote(
        cert.public_bytes(serialization.Encoding.PEM).decode(), safe="")


# §MTLSHOPS G2 (2026-09-15): the header path also requires this frame's terminator marker and SUCCESS
# (test_registry_proxy_trust.py). These tests exercise the CHAIN behind that marker, so their requests carry it.
_MARKER = "test-only-marker-0123456789-abcdefghijkl"


def _vouch(monkeypatch):
    monkeypatch.setenv("REGISTRY_PROXY_TRUST_SECRET", _MARKER)


@pytest.mark.asyncio
async def test_get_client_spiffe_id_REFUSES_a_forged_header_certificate(bundle, monkeypatch):
    """End to end through the dependency, which is where row 194 actually lived: before this,
    the identity in a forged header certificate was simply believed."""
    from fastapi import HTTPException
    monkeypatch.setattr(mtls_auth, "CERT_CHAIN_MODE", "enforce")
    monkeypatch.setattr(mtls_auth, "TRUSTED_SPIFFE_DOMAINS", ["eu.theprotocol.cloud"])
    forged_key, forged_cert = _ca(ROOT_NAME)          # same subject, attacker's key
    _vouch(monkeypatch)
    req = _Req(X_SSL_Client_Cert=_pem_header(_leaf(forged_key, forged_cert)),
               X_SSL_Client_Verify="SUCCESS",          # forging this too must not help
               X_Registry_Proxy_Auth=_MARKER)          # past the terminator's marker, the chain still decides
    with pytest.raises(HTTPException) as e:
        await mtls_auth.get_client_spiffe_id(req)
    assert e.value.status_code == 401
    assert "chain" in str(e.value.detail).lower()


@pytest.mark.asyncio
async def test_get_client_spiffe_id_ACCEPTS_a_properly_chained_header_certificate(bundle, monkeypatch):
    """The control that keeps federation alive: a real proxy forwarding a real SVID must still
    authenticate. If this goes red, every mTLS peer is locked out."""
    monkeypatch.setattr(mtls_auth, "CERT_CHAIN_MODE", "enforce")
    monkeypatch.setattr(mtls_auth, "TRUSTED_SPIFFE_DOMAINS", ["eu.theprotocol.cloud"])
    ca_key, ca_cert, _ = bundle
    _vouch(monkeypatch)
    req = _Req(X_SSL_Client_Cert=_pem_header(_leaf(ca_key, ca_cert)), X_SSL_Client_Verify="SUCCESS",
               X_Registry_Proxy_Auth=_MARKER)
    assert await mtls_auth.get_client_spiffe_id(req) == TRUSTED_URI


@pytest.mark.asyncio
async def test_shadow_mode_logs_but_does_not_refuse(bundle, monkeypatch):
    """The roll posture: watch real traffic before enforcing. It must NOT block, or 'shadow'
    would be enforce under a friendlier name."""
    monkeypatch.setattr(mtls_auth, "CERT_CHAIN_MODE", "shadow")
    monkeypatch.setattr(mtls_auth, "TRUSTED_SPIFFE_DOMAINS", ["eu.theprotocol.cloud"])
    forged_key, forged_cert = _ca(ROOT_NAME)
    _vouch(monkeypatch)
    req = _Req(X_SSL_Client_Cert=_pem_header(_leaf(forged_key, forged_cert)), X_SSL_Client_Verify="SUCCESS",
               X_Registry_Proxy_Auth=_MARKER)
    assert await mtls_auth.get_client_spiffe_id(req) == TRUSTED_URI
