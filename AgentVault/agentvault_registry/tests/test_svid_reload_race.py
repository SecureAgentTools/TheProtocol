"""§SVIDRACE (V0639, agentvault2-d6, 2026-10-24): a cached TLS client keyed on the SVID certificate's mtime alone kept
whatever it read while the cert-writer was mid-publish.

The cert-writer (nginx/cert-writer.sh) rewrites svid.0.pem, svid.0.key and bundle.0.pem IN PLACE (cp, one after
another) every five minutes. A worker that rebuilt its client after the first copy read a key or a bundle mid-copy;
es_ssl_helper's build failed, get_httpx_verify() answered True (the system CAs), and the TEG client recorded the new
certificate mtime, so it verified every TEG call against the system CAs until the next refresh: cloud-op-sbxbetaop
2026-10-24 17:15:27-17:20:21Z, CERTIFICATE_VERIFY_FAILED "unable to get local issuer certificate" on some workers,
while a fresh process verified the sidecar against every trust file, and the failures stopped at the 17:20:22Z refresh.

  1. es_ssl_helper.svid_stamp covers the cert, the key and the bundle: a key or bundle that changes after the cert
     moves it; no cert gives ().
  2. spire_trust_loaded: a fallback (True or None) with an SVID on disk is not kept; no SVID, or a real context, is.
  3. every cached client (the TEG clients of teg_integration, teg_stream_proxy and teg_client, the OPA client, the
     reactor and blocklist aiohttp sessions) rebuilds on the call after a fallback, keeps a client built with the SPIRE
     context while nothing changes, and rebuilds on a bundle-only change.
  4. end to end on real files: a key read mid-copy (empty) gives a fallback client; once the key is whole again the
     next call builds a client with the SPIRE context.
  5. get_es_ssl_context rebuilds on a bundle-only change; the event emitter refreshes on one, and after a failed build
     keeps its context and retries on the next emit.
Control: the pre-V0639 modules (mcptest/v0638, e2417657) fail 1, 2 (no such names), 3, 4 and 5.
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import importlib
import os
import ssl

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://ci:ci@localhost:5432/ci")
os.environ.setdefault("API_KEY_SECRET", "ci-dummy-secret-0123456789abcdef")


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
    _ca_key, ca = _selfsigned("test-spire-root", ca=True)
    leaf_key, leaf = _selfsigned("test-svid", ca=False)
    (tmp_path / "bundle.0.pem").write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    (tmp_path / "svid.0.pem").write_bytes(leaf.public_bytes(serialization.Encoding.PEM))
    (tmp_path / "svid.0.key").write_bytes(leaf_key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    monkeypatch.setenv("SVID_CERT_DIR", str(tmp_path))
    monkeypatch.setenv("CERT_DIR", str(tmp_path))
    from agentvault_registry import es_ssl_helper
    monkeypatch.setattr(es_ssl_helper, "_CACHED_CTX", None)
    monkeypatch.setattr(es_ssl_helper, "_CACHED_STAMP", (), raising=False)
    return tmp_path


def _later(path, seconds: int = 1) -> None:
    """Move a file's mtime forward (the kernel's timestamp tick can be coarser than two writes in a test)."""
    st = os.stat(path)
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + seconds * 1_000_000_000))


def _spire_roots(ctx: ssl.SSLContext) -> int:
    """The test's own roots in a context (it also carries the system roots, load_default_certs)."""
    return sum(1 for c in ctx.get_ca_certs()
               if any(k == "commonName" and v.startswith("test-spire-root") for rdn in c["subject"] for k, v in rdn))


def _rewrite_bundle(d) -> None:
    """The cert-writer's next copy of the bundle: same roots plus a newline, a later mtime."""
    p = d / "bundle.0.pem"
    p.write_bytes(p.read_bytes() + b"\n")
    _later(p)


# 1 and 2 -------------------------------------------------------------------------------------------------------------

def test_the_stamp_covers_the_cert_the_key_and_the_bundle(cert_dir):
    from agentvault_registry.es_ssl_helper import svid_stamp
    first = svid_stamp()
    assert len(first) == 3 and all(size > 0 for _, size in first), first
    _rewrite_bundle(cert_dir)
    second = svid_stamp()
    assert second != first, "a bundle the cert-writer rewrote after the certificate must move the stamp"
    _later(cert_dir / "svid.0.key")
    assert svid_stamp() != second, "a key the cert-writer rewrote after the certificate must move the stamp"
    (cert_dir / "svid.0.pem").unlink()
    assert svid_stamp() == (), "no SVID on disk: nothing to rotate"


def test_a_fallback_is_kept_only_where_there_is_no_svid():
    from agentvault_registry.es_ssl_helper import spire_trust_loaded
    stamp = ((1, 1), (1, 1), (1, 1))
    assert spire_trust_loaded(ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT), stamp)
    assert not spire_trust_loaded(True, stamp), "get_httpx_verify()'s True with an SVID on disk is a failed build"
    assert not spire_trust_loaded(None, stamp), "get_es_ssl_context()'s None with an SVID on disk is a failed build"
    assert spire_trust_loaded(True, ()) and spire_trust_loaded(None, ()), "no SVID: the system CAs are all there is"


# 3 -------------------------------------------------------------------------------------------------------------------

class _Client:
    def __init__(self, **kwargs):
        self.kwargs, self.is_closed = kwargs, False

    async def aclose(self):
        self.is_closed = True


class _Session:
    def __init__(self, **kwargs):
        self.kwargs, self.closed = kwargs, False

    async def close(self):
        self.closed = True


class _Connector:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


def _teg_client_holder():
    holder = {}

    def get(mod):
        if "c" not in holder:
            holder["c"] = mod.TEGClient("https://nginx-teg:8443")
        return holder["c"]._client
    return get


# (module, how to read its cached client, the globals/attrs to reset, the provider it builds from, aiohttp?)
_CASES = {
    "teg_integration": ("agentvault_registry.routers.teg_integration", lambda m: m._get_teg_client(),
                        {"_teg_http_client": None, "_teg_http_client_stamp": ()}, "get_httpx_verify", False),
    "teg_stream_proxy": ("agentvault_registry.services.teg_stream_proxy", lambda m: m._get_teg_client(),
                         {"_teg_http_client": None, "_teg_http_client_stamp": ()}, "get_httpx_verify", False),
    "teg_client": ("agentvault_registry.teg_client", None, {}, "get_httpx_verify", False),
    "opa_client": ("agentvault_registry.opa_client", "async", {"_client": None, "_client_stamp": ()},
                   "get_httpx_verify", False),
    "reactor_helpers": ("agentvault_registry.background_tasks.reactor_helpers", lambda m: m._get_session(),
                        {"_shared_session": None, "_shared_session_stamp": ()}, "get_es_ssl_context", True),
    "federation_blocklist": ("agentvault_registry.routers.federation_blocklist", lambda m: m._get_session(),
                             {"_shared_session": None, "_shared_session_stamp": ()}, "get_es_ssl_context", True),
}


@pytest.mark.parametrize("case", sorted(_CASES))
def test_a_cached_client_built_on_a_fallback_is_rebuilt_on_the_next_call(case, monkeypatch):
    modname, getter, reset, provider, is_session = _CASES[case]
    mod = importlib.import_module(modname)
    stamp = {"v": ((10, 5), (10, 5), (10, 5))}
    fallback = None if is_session else True
    values = iter([fallback] + [ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT) for _ in range(3)])
    monkeypatch.setattr(mod, "svid_stamp", lambda: stamp["v"], raising=False)
    monkeypatch.setattr(mod, provider, lambda: next(values), raising=False)
    if is_session:
        monkeypatch.setattr(mod.aiohttp, "ClientSession", _Session)
        monkeypatch.setattr(mod.aiohttp, "TCPConnector", _Connector)
    else:
        monkeypatch.setattr(mod.httpx, "AsyncClient", _Client)
    for name, value in reset.items():
        monkeypatch.setattr(mod, name, value, raising=False)
    get = _teg_client_holder() if getter is None else getter

    async def call():
        if getter == "async":
            return await mod.get_client()
        return get(mod)

    async def run():
        built_on_fallback = await call()
        after_fallback = await call()
        kept = await call()
        stamp["v"] = ((10, 5), (10, 5), (20, 6))      # the bundle alone was rewritten
        after_bundle = await call()
        await asyncio.sleep(0)
        return built_on_fallback, after_fallback, kept, after_bundle

    built_on_fallback, after_fallback, kept, after_bundle = asyncio.run(run())
    assert after_fallback is not built_on_fallback, (
        f"{case}: a client built while the SVID material could not be loaded (verify fell back to the system CAs) "
        "must be rebuilt on the next call, not kept until the next refresh")
    assert kept is after_fallback, f"{case}: a client built with the SPIRE context must be pooled while nothing changes"
    assert after_bundle is not kept, f"{case}: a bundle rewritten after the certificate must replace the client"


# 4 -------------------------------------------------------------------------------------------------------------------

def test_a_key_read_mid_copy_heals_on_the_next_call(cert_dir, monkeypatch):
    from agentvault_registry.routers import teg_integration as ti
    monkeypatch.setattr(ti.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(ti, "_teg_http_client", None)
    monkeypatch.setattr(ti, "_teg_http_client_stamp", (), raising=False)
    key = cert_dir / "svid.0.key"
    whole = key.read_bytes()
    _later(cert_dir / "svid.0.pem")      # the cert-writer copied the certificate first ...
    key.write_bytes(b"")                 # ... and the key is mid-copy (cp truncates, then writes)

    async def run():
        mid = ti._get_teg_client()
        key.write_bytes(whole)           # the copy finished
        _later(key)
        healed = ti._get_teg_client()
        again = ti._get_teg_client()
        await asyncio.sleep(0)
        return mid, healed, again

    mid, healed, again = asyncio.run(run())
    assert mid.kwargs["verify"] is True, "the precondition: a build with the key mid-copy falls back to the system CAs"
    assert healed is not mid and isinstance(healed.kwargs["verify"], ssl.SSLContext), (
        "the next call after the key is whole must build a client that trusts the SPIRE bundle; the old shape kept "
        "the system-CA client until the next refresh (cloud-op-sbxbetaop 17:15:27-17:20:21Z)")
    assert again is healed, "and keep it while nothing changes"


def test_a_bundle_read_mid_copy_heals_on_the_next_call(cert_dir, monkeypatch):
    """The other way a mid-copy read goes wrong, and the one that logs nothing: the bundle read as a valid PREFIX (the
    first of two roots) loads without an error, so the context simply lacks the root that issued the peer's leaf. The
    production log of the 17:15Z window carries no "[es_ssl_helper] failed to build SSL context" line, which fits this
    shape better than the fallback one; the stamp heals both, because the finished copy moves the bundle's stamp."""
    from agentvault_registry.routers import teg_integration as ti
    monkeypatch.setattr(ti.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(ti, "_teg_http_client", None)
    monkeypatch.setattr(ti, "_teg_http_client_stamp", (), raising=False)
    bundle = cert_dir / "bundle.0.pem"
    first_root = bundle.read_bytes()
    _k, second = _selfsigned("test-spire-root-2", ca=True)
    whole = first_root + second.public_bytes(serialization.Encoding.PEM)
    _later(cert_dir / "svid.0.pem")      # the certificate was copied; the bundle copy has written its first root only
    bundle.write_bytes(first_root)

    async def run():
        mid = ti._get_teg_client()
        bundle.write_bytes(whole)        # the copy finished
        _later(bundle)
        healed = ti._get_teg_client()
        await asyncio.sleep(0)
        return mid, healed

    mid, healed = asyncio.run(run())
    assert _spire_roots(mid.kwargs["verify"]) == 1, "the precondition: the prefix loads, with one root"
    assert healed is not mid and _spire_roots(healed.kwargs["verify"]) == 2, (
        "the next call after the bundle copy finished must rebuild with both roots; the old shape, keyed on the "
        "certificate alone, kept the one-root context until the next refresh")


# 5 -------------------------------------------------------------------------------------------------------------------

def test_the_shared_context_rebuilds_on_a_bundle_only_change(cert_dir):
    from agentvault_registry.es_ssl_helper import get_es_ssl_context
    first = get_es_ssl_context()
    assert isinstance(first, ssl.SSLContext)
    assert get_es_ssl_context() is first, "an unchanged SVID keeps the cached context"
    _rewrite_bundle(cert_dir)
    assert get_es_ssl_context() is not first, "a bundle rewritten after the certificate must rebuild the context"


def test_the_event_emitter_refreshes_on_a_bundle_change_and_retries_a_failed_build(cert_dir):
    from agentvault_registry.event_emitter import EventEmitter
    em = EventEmitter(event_store_url="https://nginx-event-store:8443")
    first = em._ssl_context
    assert isinstance(first, ssl.SSLContext), "the precondition: the emitter built its context from the files"
    key = cert_dir / "svid.0.key"
    whole = key.read_bytes()

    async def run():
        await em._refresh_ssl_if_needed()
        unchanged = em._ssl_context
        _rewrite_bundle(cert_dir)
        await em._refresh_ssl_if_needed()
        after_bundle = em._ssl_context
        key.write_bytes(b"")             # the next publish: the key mid-copy
        _later(key)
        await em._refresh_ssl_if_needed()
        during = em._ssl_context
        key.write_bytes(whole)
        _later(key, 2)
        await em._refresh_ssl_if_needed()
        healed = em._ssl_context
        if em.session is not None:
            await em.session.close()
        return unchanged, after_bundle, during, healed

    unchanged, after_bundle, during, healed = asyncio.run(run())
    assert unchanged is first, "nothing changed: no rebuild"
    assert after_bundle is not first, "a bundle rewritten after the certificate must refresh the emitter's context"
    assert during is after_bundle, "a failed build keeps the context the emitter had"
    assert healed is not after_bundle and isinstance(healed, ssl.SSLContext), (
        "after a failed build the stamp stays unrecorded, so the next emit builds again once the key is whole")
