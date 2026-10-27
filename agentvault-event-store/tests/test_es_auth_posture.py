"""§SOVKIT T2 (2026-09-14): the event store's authentication posture.

His word: "make this required on because its a big trap not enabling it". What these tests pin:
- certificate headers count only with the proxy marker only this frame's TLS terminators set (anything on the frame's
  networks could otherwise write them itself),
- only SUCCESS counts,
- "origin" belongs to this frame's own trust domain (a federated peer's registry was "origin" on EU's ledger, measured
  710 times in 24 h, and origin may mint),
- the licence fallback is refused by default,
- only origin may change cross-frame peers or federation operators (the admin routes and /operators/sync),
- the event counter never reports -1.

Pure tests import src/es_auth.py alone (no FastAPI, no database); wiring tests read the routers' source.
Run: python -m pytest tests/test_es_auth_posture.py -q   (needs pytest and cryptography)
"""
import ast
import datetime
import sys
from pathlib import Path
from urllib.parse import quote

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import es_auth  # noqa: E402

EVENTS = ROOT / "src" / "routers" / "events.py"
ADMIN_ROUTERS = [ROOT / "src" / "routers" / "admin_cross_frame.py", ROOT / "src" / "routers" / "admin_federation_operators.py"]
MAIN = ROOT / "src" / "main.py"
METRICS = ROOT / "src" / "metrics_exporter.py"

SECRET = "sovkit-test-marker-not-a-secret-000"   # 35 characters, a test fixture and not a real secret
EU, ASIA = "eu.theprotocol.cloud", "asia.theprotocol.cloud"
SERVICES = es_auth.DEFAULT_SERVICES + ("eu-registry", "registry", "teg-layer", "asia-registry")


def _pem(uris, cn="sovkit-test"):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    now = datetime.datetime.now(datetime.timezone.utc)
    builder = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
               .serial_number(x509.random_serial_number())
               .not_valid_before(now - datetime.timedelta(minutes=1)).not_valid_after(now + datetime.timedelta(hours=1)))
    if uris:
        builder = builder.add_extension(x509.SubjectAlternativeName([x509.UniformResourceIdentifier(u) for u in uris]),
                                        critical=False)
    return builder.sign(key, hashes.SHA256()).public_bytes(serialization.Encoding.PEM).decode()


# ── the proxy marker ────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_short_or_trivial_secret_counts_as_unset():
    assert not es_auth.secret_usable(None)
    assert not es_auth.secret_usable("")
    assert not es_auth.secret_usable("abcdefghijklmnopqrstuvwxyz01234")   # 31 characters
    assert not es_auth.secret_usable("ab" * 20)            # 40 characters, two distinct
    assert es_auth.secret_usable(SECRET)


def test_the_marker_must_match_a_usable_secret_exactly():
    assert es_auth.proxy_trusted(SECRET, SECRET)
    assert not es_auth.proxy_trusted(SECRET[:-1] + "X", SECRET)
    assert not es_auth.proxy_trusted(None, SECRET)
    assert not es_auth.proxy_trusted("", SECRET)
    short = "abcdefghij0123"
    assert not es_auth.proxy_trusted(short, short), "an unusable configured secret must never be matched"


# ── the forwarded identity ──────────────────────────────────────────────────────────────────────────────────────────

def test_the_spiffe_id_is_read_from_the_forwarded_certificate():
    pem = _pem(["https://example.org/not-spiffe", f"spiffe://{EU}/service/eu-registry"])
    assert es_auth.spiffe_id_from_forwarded_cert(quote(pem)) == f"spiffe://{EU}/service/eu-registry"
    assert es_auth.spiffe_id_from_forwarded_cert(quote(_pem([]))) is None
    assert es_auth.spiffe_id_from_forwarded_cert("not a certificate") is None
    assert es_auth.spiffe_id_from_forwarded_cert(None) is None


def test_the_dn_fallback():
    assert es_auth.spiffe_id_from_dn(f"CN=spiffe://{EU}/service/eu-registry,O=SPIRE") == f"spiffe://{EU}/service/eu-registry"
    assert es_auth.spiffe_id_from_dn("CN=nothing") is None


@pytest.mark.parametrize("spiffe_id,kind,name", [
    (f"spiffe://{EU}/service/eu-registry", "origin", "eu-registry"),
    (f"spiffe://{EU}/operator/lisbon/svid-writer", "operator", "lisbon"),
    (f"spiffe://{ASIA}/service/asia-registry", "peer_service", "asia-registry"),
    (f"spiffe://{ASIA}/service/registry", "peer_service", "registry"),
    (f"spiffe://{ASIA}/operator/shenzhen/svid-writer", "unregistered", None),
    (f"spiffe://{EU}/service/not-a-known-service", "unregistered", None),
    ("spiffe://evil.example/service/registry", "untrusted", None),
    ("not-a-spiffe-id", "untrusted", None),
])
def test_origin_belongs_to_this_frames_own_trust_domain(spiffe_id, kind, name):
    who = es_auth.classify(spiffe_id, EU, [EU, ASIA], SERVICES)
    assert who["kind"] == kind
    if name:
        assert who["name"] == name


def test_an_unknown_own_domain_gives_nobody_origin():
    who = es_auth.classify(f"spiffe://{EU}/service/eu-registry", "", [EU, ASIA], SERVICES)
    assert who["kind"] != "origin"


def test_the_own_domain_comes_from_env_then_the_stores_svid_and_is_never_latched_empty(tmp_path):
    es_auth._OWN_DOMAIN_CACHE.clear()
    assert es_auth.own_trust_domain("EU.theprotocol.cloud", str(tmp_path)) == (EU, "env")
    assert es_auth.own_trust_domain(None, str(tmp_path)) == ("", "none")
    (tmp_path / "svid.0.pem").write_text(_pem([f"spiffe://{ASIA}/service/asia-registry"]))
    assert es_auth.own_trust_domain(None, str(tmp_path)) == (ASIA, "svid"), "a failed read must be retried, not latched"
    es_auth._OWN_DOMAIN_CACHE.clear()


# ── the wiring ──────────────────────────────────────────────────────────────────────────────────────────────────────

def _function(path, name):
    tree = ast.parse(path.read_text())
    return next(n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)


def test_method_1_requires_the_marker_and_success_only():
    fn = _function(EVENTS, "verify_event_auth")
    src = ast.unparse(fn)
    assert "X-ES-Proxy-Auth" in src, "verify_event_auth must read the proxy marker header"
    assert "proxy_trusted(" in src, "certificate headers must be gated on the proxy marker"
    assert "'SUCCESS'" in src or '"SUCCESS"' in src
    assert "FAILED" not in src, "a certificate nginx could not verify must never authenticate"
    assert "classify(" in src and "own_trust_domain(" in src, "origin must be decided by this frame's own trust domain"


def test_the_licence_fallback_is_refused_by_default():
    tree = ast.parse(EVENTS.read_text())
    assigns = [n for n in tree.body if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "MTLS_REQUIRED" for t in n.targets)]
    assert len(assigns) == 1
    assert "'EVENTSTORE_MTLS_REQUIRED', 'true'" in ast.unparse(assigns[0]), "the code default must be required-on"


def test_only_origin_may_change_federation_records():
    for path in ADMIN_ROUTERS:
        tree = ast.parse(path.read_text())
        mutating = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                if isinstance(dec, ast.Call) and getattr(dec.func, "attr", "") in ("post", "put", "patch", "delete"):
                    mutating.append((node.name, ast.unparse(dec)))
        assert mutating, f"{path.name}: no mutating routes found (the test is not looking at the router)"
        for name, dec in mutating:
            assert "require_origin_auth" in dec, f"{path.name}:{name} must depend on require_origin_auth"


def test_health_reports_the_posture():
    src = ast.unparse(_function(MAIN, "health"))
    assert "mtls_required" in src and "method1_proxy_trust" in src


def test_the_event_counter_never_reports_minus_one():
    src = METRICS.read_text()
    assert "count(*) FROM events" in src and "< 0" in src, "reltuples is -1 before the first ANALYZE; count instead"


# §SOVKIT T5 (2026-09-14): behind the frame's own mTLS sidecar the registry's and the TEG's calls arrive as auth_type "mtls"
# with operator "origin" (the internal key is cleared on the way), so a route that means "only this frame" must ask
# es_auth.is_origin, never auth_type == "internal" alone.
GOVERNANCE = ROOT / "src" / "routers" / "federation_governance.py"


def _route(path, route):
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(route in ast.unparse(d) for d in node.decorator_list):
            return node
    raise AssertionError(f"{path.name}: no route {route} (the test is not looking at the router)")


def test_is_origin_follows_the_caller_not_the_header_it_used():
    assert es_auth.is_origin({"auth_type": "internal", "operator": "origin"})
    assert es_auth.is_origin({"auth_type": "mtls", "operator": "origin", "spiffe_id": "spiffe://eu.theprotocol.cloud/service/registry"})
    for ctx in ({"auth_type": "mtls", "operator": "amsterdam"}, {"auth_type": "mtls", "operator": "peer:asia.theprotocol.cloud"},
                {"auth_type": "federation", "operator": "origin-lookalike"}, {}, None):
        assert not es_auth.is_origin(ctx)


def test_only_origin_changes_a_record_through_the_operator_sync():
    """SEC-20 (2026-10-17): /operators/sync changes this ledger's federation records, the trust value the federation
    vote multiplies by included, so like the admin routes above it depends on require_origin_auth: this frame's own
    services (operator "origin", whichever way they authenticated) change a record there and nobody else does. The route
    used to take verify_event_auth itself and let every other caller change bayesian_discount (59e7548) or more (before
    it); tests/test_operator_sync_non_origin.py drives the route."""
    fn = _route(EVENTS, "/operators/sync")
    decorators = [ast.unparse(d) for d in fn.decorator_list]
    assert any("require_origin_auth" in d for d in decorators), \
        f"/operators/sync must depend on require_origin_auth: {decorators}"
    defaults = [ast.unparse(d) for d in list(fn.args.defaults) + list(fn.args.kw_defaults) if d is not None]
    assert not any("verify_event_auth" in d for d in defaults), \
        f"/operators/sync must not take a caller require_origin_auth has not admitted: {defaults}"
    guard = ast.unparse(_function(EVENTS, "require_origin_auth"))
    assert "'origin'" in guard or '"origin"' in guard, "require_origin_auth must key on origin, not on an auth type"


def test_governance_veto_and_apply_accept_origin_over_mtls():
    for route in ("/veto", "/apply"):
        src = ast.unparse(_route(GOVERNANCE, route))
        assert "'internal'" in src and "is_origin(auth_context)" in src, f"{route} must accept origin over mTLS, not only the internal key"
