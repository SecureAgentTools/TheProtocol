"""§BATCH7 (2026-09-05) — four TLS-trust rules measured on the fresh JUICE↔BRRR pair, each with the
control that the OLD shape fails:

  1. routers.governance._get_es_client_kwargs verifies with the shared DUAL-trust context (SPIRE
     bundle + public roots); the old `verify=bundle.0.pem` trusted the SPIRE root only and a public
     Let's-Encrypt EventStore (every cloud operator) died CERTIFICATE_VERIFY_FAILED (eb's finding).
  2. reactor_registry_federated's context carries the public roots too (same class).
  3. identity.svid_client.get_client_cert_config verifies against the FRESHEST bundle: the
     cert-writer's on-disk bundle.0.pem when it is newer than the boot-time snapshot — a federation
     established after boot was invisible to the fan-out for up to a 30-minute poll.
  4. services.operator_provisioner: an operator born after its parent federated inherits the
     parent's live `spire-server federation list` when SPIRE_FEDERATE_WITH is unset (juiceop-b
     carried no -federatesWith and one root); the env keeps precedence.
"""
import datetime as _dt
import os
import ssl
import time

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID


def _selfsigned(cn: str, ca: bool):
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    now = _dt.datetime.now(_dt.timezone.utc)
    b = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
         .serial_number(x509.random_serial_number()).not_valid_before(now - _dt.timedelta(minutes=1))
         .not_valid_after(now + _dt.timedelta(hours=1))
         .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True))
    return key, b.sign(key, hashes.SHA256())


@pytest.fixture
def cert_dir(tmp_path, monkeypatch):
    """A cert-writer shaped directory: bundle.0.pem (one SPIRE-style root) + svid.0.pem/key."""
    ca_key, ca = _selfsigned("test-spire-root", ca=True)
    leaf_key, leaf = _selfsigned("test-svid", ca=False)
    (tmp_path / "bundle.0.pem").write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    (tmp_path / "svid.0.pem").write_bytes(leaf.public_bytes(serialization.Encoding.PEM))
    (tmp_path / "svid.0.key").write_bytes(leaf_key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    monkeypatch.setenv("SVID_CERT_DIR", str(tmp_path))
    monkeypatch.setenv("CERT_DIR", str(tmp_path))
    from agentvault_registry import es_ssl_helper
    monkeypatch.setattr(es_ssl_helper, "_CACHED_CTX", None)
    monkeypatch.setattr(es_ssl_helper, "_CACHED_STAMP", ())
    return tmp_path


def _ca_count(ctx: ssl.SSLContext) -> int:
    return len(ctx.get_ca_certs())


def test_old_shape_control_trusts_only_the_spire_root(cert_dir):
    """The control: `create_default_context(cafile=bundle)` holds exactly the bundle's one root."""
    ctx = ssl.create_default_context(cafile=str(cert_dir / "bundle.0.pem"))
    assert _ca_count(ctx) == 1
    ctx.load_default_certs(ssl.Purpose.SERVER_AUTH)
    assert _ca_count(ctx) > 1, "this box carries no public roots — the dual-trust tests cannot discriminate here"


def test_governance_es_client_verifies_with_dual_trust_context(cert_dir):
    from agentvault_registry.routers.governance import _get_es_client_kwargs
    kw = _get_es_client_kwargs()
    verify = kw["verify"]
    assert isinstance(verify, ssl.SSLContext), kw
    assert _ca_count(verify) > 1, "public roots missing: a Let's-Encrypt EventStore would fail here"
    assert "cert" not in kw, "the context carries the SVID chain; a bare cert tuple beside it is the old shape"


def test_governance_falls_back_to_cert_tuple_without_a_bundle(tmp_path, monkeypatch):
    from agentvault_registry import es_ssl_helper
    monkeypatch.setenv("SVID_CERT_DIR", str(tmp_path))
    monkeypatch.setenv("CERT_DIR", str(tmp_path))
    monkeypatch.setattr(es_ssl_helper, "_CACHED_CTX", None)
    monkeypatch.setattr(es_ssl_helper, "_CACHED_STAMP", ())
    from agentvault_registry.routers.governance import _get_es_client_kwargs
    kw = _get_es_client_kwargs()
    # no bundle, no svid → the helper builds a system-CA context (dual trust degenerates to public)
    assert kw["verify"] is True or isinstance(kw["verify"], ssl.SSLContext)


def test_reactor_registry_federated_context_has_public_roots(cert_dir):
    from agentvault_registry.background_tasks.reactor_registry_federated import _build_mtls_ssl_context
    ctx = _build_mtls_ssl_context()
    assert isinstance(ctx, ssl.SSLContext)
    assert _ca_count(ctx) > 1


def test_svid_client_verify_follows_the_freshest_bundle(cert_dir, tmp_path, monkeypatch):
    from agentvault_registry.identity.svid_client import SVIDClient
    c = SVIDClient()
    snap = tmp_path / "snapshot.bundle"
    # §DEPS (2026-09-27): `verify` is an SSLContext now (httpx 0.28 drops `cert` beside a bundle PATH, so the chain
    # rides inside the context), so the snapshot carries ONE MORE root than the on-disk bundle: the context's CA count
    # says which file it was built from, and the chooser is asserted directly as well.
    _, other_root = _selfsigned("test-other-root", ca=True)
    snap.write_bytes((cert_dir / "bundle.0.pem").read_bytes() + other_root.public_bytes(serialization.Encoding.PEM))
    c.cert_path, c.key_path, c.bundle_path = cert_dir / "svid.0.pem", cert_dir / "svid.0.key", snap
    disk = cert_dir / "bundle.0.pem"
    # disk bundle NEWER than the snapshot (the cert-writer wrote after federation) → disk wins
    os.utime(snap, (time.time() - 600, time.time() - 600))
    os.utime(disk, None)
    assert c._freshest_bundle_path() == str(disk)
    cfg = c.get_client_cert_config(target_url="https://peer.example:8443")
    assert isinstance(cfg["verify"], ssl.SSLContext) and _ca_count(cfg["verify"]) == 1, cfg
    assert cfg["cert"] == (str(cert_dir / "svid.0.pem"), str(cert_dir / "svid.0.key"))
    # control: snapshot NEWER (the poll just re-fetched) → snapshot wins
    os.utime(disk, (time.time() - 600, time.time() - 600))
    os.utime(snap, None)
    assert c._freshest_bundle_path() == str(snap)
    assert _ca_count(c.get_client_cert_config(target_url="https://peer.example:8443")["verify"]) == 2
    # a public 443 target verifies with the system roots regardless
    assert c.get_client_cert_config(target_url="https://events.example")["verify"] is True
    # no on-disk bundle at all (mock SVID / no cert-writer) → the snapshot
    monkeypatch.setenv("SVID_CERT_DIR", str(tmp_path / "absent"))
    monkeypatch.setenv("CERT_DIR", str(tmp_path / "absent"))
    assert c._freshest_bundle_path() == str(snap)
    assert _ca_count(c.get_client_cert_config(target_url="https://peer.example:8443")["verify"]) == 2


class _Res:
    def __init__(self, rc, out):
        self.exit_code, self.output = rc, (out, b"")


class _Container:
    def __init__(self, rc, text):
        self._rc, self._text, self.calls = rc, text, []

    def exec_run(self, cmd, demux=False):
        self.calls.append(cmd)
        return _Res(self._rc, self._text.encode())


_FED_LIST = """Found 2 federation relationships

Trust domain              : brrr.theprotocol.cloud
Bundle endpoint URL       : https://brrr-spire-server:8443
Bundle endpoint profile   : https_spiffe
Endpoint SPIFFE ID        : spiffe://brrr.theprotocol.cloud/spire/server

Trust domain              : other.example
Bundle endpoint URL       : https://other-spire:8443
Bundle endpoint profile   : https_web
"""


def test_operator_birth_inherits_parent_federation(monkeypatch):
    from agentvault_registry.services import operator_provisioner as op
    monkeypatch.delenv("SPIRE_FEDERATE_WITH", raising=False)
    cont = _Container(0, _FED_LIST)
    assert op._federate_with() == ""
    fed = op.federation_from_spire_server(cont)
    assert fed == "brrr.theprotocol.cloud,other.example"
    assert cont.calls == [["/opt/spire/bin/spire-server", "federation", "list"]]
    # the shape the entry loop consumes: comma-separated → one -federatesWith per domain
    assert [f"spiffe://{d}" for d in fed.split(",")] == ["spiffe://brrr.theprotocol.cloud", "spiffe://other.example"]


def test_operator_federation_env_keeps_precedence_and_failures_are_empty(monkeypatch):
    from agentvault_registry.services import operator_provisioner as op
    monkeypatch.setenv("SPIRE_FEDERATE_WITH", "parent.example")
    assert op._federate_with() == "parent.example"
    monkeypatch.delenv("SPIRE_FEDERATE_WITH", raising=False)
    assert op.federation_from_spire_server(_Container(1, "boom")) == ""
    assert op.federation_from_spire_server(_Container(0, "Found 0 federation relationships\n")) == ""

    class _Raises:
        def exec_run(self, *a, **k):
            raise RuntimeError("docker gone")
    assert op.federation_from_spire_server(_Raises()) == ""
