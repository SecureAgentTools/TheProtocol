"""V0650 (k) (2026-10-31, agentvault2-14): two sandbox frames on one host may federate with each other.

Order gwo_8f8ee5ff285a9c43af26b725, the registry half (the kit half is session-lead's). Found by the dev machine's t2:
`frame-sandbox --frames 2` cannot federate on a host without public names. Frame A's registry posts its invitation
ANONYMOUSLY to frame B's public POST /api/v1/federation/frame-invitations, and B refuses a bundle host on a private
address (the §FINDINGS-A4 3d guard). A's outbound call, and B's finalize public leg, also verify the peer console
against the public roots, while a sandbox console sits on the parent's edge with `tls internal`.

FRAME_INVITATIONS_SAME_HOST_PEERS (default off) opens exactly that, and only on a frame whose birth declaration says
FRAME_POSTURE=sandbox (same_host_lane_open; REGISTRY_ENVIRONMENT, the MCP tester's money-fixture switch, plays no part):
an anonymous caller whose edge-observed address is RFC1918 or ULA may name a bundle host on such an address. Loopback, link-local (cloud metadata), CGNAT and every other non-global
range stay refused on every hop, and the refusal stays generic. FRAME_INVITATIONS_PEER_CA_FILE names the host's internal
edge CA, trusted beside the public roots by those two peer-console calls, under the same lock.

The acceptance: the guard holds with the opt-in off, opens only with it on, and never under a production posture.
DNS is faked (CI runs with no network). Cases marked BASE fail on V0649 (6c1f036b); the test_control_* cases are the
opt-in loosening nothing that was closed, and pass on both trees.
"""
from __future__ import annotations

import datetime
import ssl
import types

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry import models, security
from agentvault_registry.core.mainframe_gate import require_mainframe_only
from agentvault_registry.database import get_db
from agentvault_registry.middleware.rate_limiter import shared_limiter
from agentvault_registry.routers import frame_invitations as fi
from agentvault_registry.services import frame_trust_manager as ftm

NOW = datetime.datetime(2026, 10, 31, 6, 0, tzinfo=datetime.timezone.utc)
DNS = {"sbx-a.example.invalid": ["172.18.0.1"], "loop.example.invalid": ["127.0.0.1"],
       "meta.example.invalid": ["169.254.169.254"], "cgnat.example.invalid": ["100.64.0.1"],
       "mixed.example.invalid": ["172.18.0.1", "127.0.0.1"], "public.example.invalid": ["1.1.1.1"]}
ENVS = ("REGISTRY_ENVIRONMENT", "FRAME_POSTURE", "FRAME_INVITATIONS_SAME_HOST_PEERS", "FRAME_INVITATIONS_PEER_CA_FILE")
BUNDLE = "https://sbx-a.example.invalid:8444/"
PRIVATE_CALLER = {"X-Forwarded-For": "172.18.0.5"}
CA_CN = "same host edge test root"
REFUSED_POSTURES = [
    {},                                                                  # the EU/ASIA shape: nothing declared
    {"REGISTRY_ENVIRONMENT": "sandbox"},                                 # the tester's switch alone opens nothing
    {"FRAME_POSTURE": "production"},
    {"FRAME_POSTURE": "bogus"},                                          # declared, but no posture
    {"REGISTRY_ENVIRONMENT": "sandbox", "FRAME_POSTURE": "production"},  # the birth declaration decides
]


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    for k in ENVS:
        monkeypatch.delenv(k, raising=False)

    async def resolve(host, port):
        if host not in DNS:
            raise OSError("no such host")
        return DNS[host]
    monkeypatch.setattr(ftm, "_resolve", resolve)


def _env(monkeypatch, **kv):
    for k, v in kv.items():
        monkeypatch.setenv(k, v)


def _honored(monkeypatch, **more):
    _env(monkeypatch, FRAME_POSTURE="sandbox", FRAME_INVITATIONS_SAME_HOST_PEERS="true", **more)


def _transport(monkeypatch, handler=lambda request: httpx.Response(200)):
    seen = []

    def wrapped(request):
        seen.append(str(request.url))
        return handler(request)
    monkeypatch.setattr(ftm, "_bundle_client", lambda timeout: httpx.AsyncClient(
        transport=httpx.MockTransport(wrapped), timeout=timeout, follow_redirects=False))
    return seen


# ─────────────────────────────── the address rule and the lock ───────────────────────────────

@pytest.mark.parametrize("addr", ["10.1.2.3", "172.16.0.7", "172.31.255.254", "192.168.1.1", "fc00::1",
                                  "fd12:3456::1", "::ffff:10.0.0.1"])
def test_the_private_network_is_rfc1918_and_ula(addr):
    # BASE: no _address_is_lan_private
    assert ftm._address_is_lan_private(addr)


@pytest.mark.parametrize("addr", ["127.0.0.1", "::1", "::ffff:127.0.0.1", "169.254.169.254", "fe80::1", "100.64.0.1",
                                  "0.0.0.0", "192.0.2.1", "224.0.0.1", "172.32.0.1", "1.1.1.1", "testclient", ""])
def test_nothing_else_is_the_private_network(addr):
    # BASE: no _address_is_lan_private
    assert not ftm._address_is_lan_private(addr)


@pytest.mark.parametrize("env", REFUSED_POSTURES)
def test_the_lane_stays_closed_unless_the_frame_declares_sandbox(env):
    # BASE: no same_host_lane_open
    assert fi.same_host_lane_open({**env, "FRAME_INVITATIONS_SAME_HOST_PEERS": "true"}) is False


@pytest.mark.parametrize("env", [{"FRAME_POSTURE": "sandbox"}, {"FRAME_POSTURE": " Sandbox "},
                                 {"FRAME_POSTURE": "sandbox", "REGISTRY_ENVIRONMENT": "production"}])
def test_the_lane_opens_on_a_frame_born_sandbox_with_the_opt_in(env):
    # BASE: no same_host_lane_open
    assert fi.same_host_lane_open({**env, "FRAME_INVITATIONS_SAME_HOST_PEERS": "true"}) is True
    assert fi.same_host_lane_open(env) is False                       # and never without the opt-in


async def test_the_private_allowance_is_checked_on_every_hop(monkeypatch):
    # BASE: _dial_checked takes no allow_private
    def handler(request):
        if request.url.host == "sbx-a.example.invalid" and request.url.path == "/hop-meta":
            return httpx.Response(302, headers={"location": "https://meta.example.invalid/latest/"})
        if request.url.host == "sbx-a.example.invalid" and request.url.path == "/hop-loop":
            return httpx.Response(302, headers={"location": "https://loop.example.invalid/"})
        return httpx.Response(200)
    seen = _transport(monkeypatch, handler)
    async with ftm._bundle_client(5) as client:
        r, refusal = await ftm._dial_checked(client, "GET", BUNDLE, False, allow_private=True)
        assert refusal is None and r.status_code == 200 and seen == [BUNDLE]
        for path in ("/hop-meta", "/hop-loop"):
            seen.clear()
            r, refusal = await ftm._dial_checked(client, "GET", f"https://sbx-a.example.invalid:8444{path}", False,
                                                 allow_private=True)
            assert r is None and refusal and seen == [f"https://sbx-a.example.invalid:8444{path}"]   # refused at the hop
        seen.clear()
        r, refusal = await ftm._dial_checked(client, "GET", "https://mixed.example.invalid/", False, allow_private=True)
        assert r is None and refusal and seen == []
        r, refusal = await ftm._dial_checked(client, "GET", BUNDLE, False)          # without it: refused as before
        assert r is None and refusal and seen == []


# ─────────────────────────────── the public route ───────────────────────────────

class _Session:
    """No pending invitation; records the row added (refresh dates it, as the database would)."""

    def __init__(self):
        self.added = []

    async def execute(self, *a, **k):
        return types.SimpleNamespace(scalar_one_or_none=lambda: None)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        return None

    async def refresh(self, obj):
        if getattr(obj, "created_at", None) is None:
            obj.created_at = NOW


def _route(monkeypatch):
    monkeypatch.setattr(shared_limiter, "enabled", False)
    session = _Session()
    app = FastAPI()
    app.state.limiter = shared_limiter
    app.include_router(fi.router)
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[security.get_current_developer_optional] = lambda: None       # anonymous

    async def _no_event(*a, **kw):
        return None
    monkeypatch.setattr(fi, "_emit_event", _no_event)
    monkeypatch.setattr(fi, "_admin_notification_email", lambda: None)
    return TestClient(app, raise_server_exceptions=False), session


def _invite(bundle=BUNDLE):
    return {"trust_domain": "sbx-a.example.invalid", "bundle_endpoint_url": bundle,
            "federation_endpoint_url": "https://sbx-a.example.invalid:8443/", "name": "sandbox a",
            "contact_email": "nobody@example.invalid", "initiator_nonce": "ab" * 16}


def _assert_generic_refusal(r, seen, host="sbx-a.example.invalid"):
    assert r.status_code == 422, r.text[:300]
    assert "public https address" in r.text
    assert host not in r.text and "internal" not in r.text            # no oracle: neither the host nor the why
    assert seen == []


@pytest.mark.parametrize("switch", [None, "false", "0", ""])
def test_control_the_guard_holds_with_the_opt_in_off(monkeypatch, switch):
    # control: passes on both trees
    _env(monkeypatch, FRAME_POSTURE="sandbox")
    if switch is not None:
        _env(monkeypatch, FRAME_INVITATIONS_SAME_HOST_PEERS=switch)
    seen = _transport(monkeypatch)
    http, session = _route(monkeypatch)
    _assert_generic_refusal(http.post("/api/v1/federation/frame-invitations", json=_invite(), headers=PRIVATE_CALLER),
                            seen)
    assert session.added == []


def test_the_opt_in_opens_the_guard_for_a_same_host_peer(monkeypatch):
    # BASE: refused with the generic 422 (the guard has no private allowance)
    _honored(monkeypatch)
    seen = _transport(monkeypatch)
    http, session = _route(monkeypatch)
    r = http.post("/api/v1/federation/frame-invitations", json=_invite(), headers=PRIVATE_CALLER)
    assert r.status_code == 201, r.text[:300]
    assert r.json()["status"] == "pending" and seen == [BUNDLE]
    row, = session.added
    assert isinstance(row, models.FrameInvitation) and row.initiator_bundle_endpoint_url == BUNDLE


@pytest.mark.parametrize("env", REFUSED_POSTURES)
def test_control_never_under_a_production_posture(monkeypatch, env):
    # control: passes on both trees
    _env(monkeypatch, FRAME_INVITATIONS_SAME_HOST_PEERS="true", **env)
    seen = _transport(monkeypatch)
    http, session = _route(monkeypatch)
    _assert_generic_refusal(http.post("/api/v1/federation/frame-invitations", json=_invite(), headers=PRIVATE_CALLER),
                            seen)
    assert session.added == []


@pytest.mark.parametrize("headers", [{"X-Forwarded-For": "9.9.9.9"},
                                     {"X-Forwarded-For": "172.18.0.5, 9.9.9.9"},   # a forged first element
                                     {"X-Forwarded-For": "127.0.0.1"},
                                     {}])                                          # no header: the peer, "testclient"
def test_control_the_opt_in_never_serves_a_caller_off_the_private_network(monkeypatch, headers):
    # control: passes on both trees
    _honored(monkeypatch)
    seen = _transport(monkeypatch)
    http, session = _route(monkeypatch)
    _assert_generic_refusal(http.post("/api/v1/federation/frame-invitations", json=_invite(), headers=headers), seen)


@pytest.mark.parametrize("host", ["loop.example.invalid", "meta.example.invalid", "cgnat.example.invalid",
                                  "mixed.example.invalid"])
def test_control_the_opt_in_never_reaches_loopback_link_local_or_cgnat(monkeypatch, host):
    # control: passes on both trees
    _honored(monkeypatch)
    seen = _transport(monkeypatch)
    http, session = _route(monkeypatch)
    r = http.post("/api/v1/federation/frame-invitations", json=_invite(f"https://{host}:8444/"), headers=PRIVATE_CALLER)
    _assert_generic_refusal(r, seen, host)


# ─────────────────────────────── the peer console's CA ───────────────────────────────

def _ca_file(tmp_path):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, CA_CN)])
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(datetime.datetime(2026, 1, 1))
            .not_valid_after(datetime.datetime(2036, 1, 1))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(key, hashes.SHA256()))
    path = tmp_path / "edge-root.pem"
    path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return str(path)


def _trusts_the_edge_ca(verify) -> bool:
    return isinstance(verify, ssl.SSLContext) and any(
        ("commonName", CA_CN) in rdn for c in verify.get_ca_certs() for rdn in c.get("subject", ()))


class _Answer:
    status_code = 201
    text = '{"id": "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee", "status": "pending"}'

    def json(self):
        return {"id": "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee", "status": "pending", "created_at": NOW.isoformat()}


class _Client:
    calls = []

    def __init__(self, **kw):
        self.kw = kw

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None):
        _Client.calls.append((url, self.kw))
        return _Answer()


class _OutboundSession:
    def __init__(self):
        self.added = []

    async def execute(self, statement):
        return types.SimpleNamespace(scalar_one_or_none=lambda: None, scalars=lambda: types.SimpleNamespace(all=list))

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        return None

    async def commit(self):
        return None

    async def rollback(self):
        return None

    async def refresh(self, obj):
        if getattr(obj, "created_at", None) is None:
            obj.created_at = NOW


def _admin_app(monkeypatch, session):
    for k, v in {"SPIRE_TRUST_DOMAIN": "sbx-b.example.invalid",
                 "FRAME_LOCAL_BUNDLE_ENDPOINT_URL": "https://sbx-b.example.invalid:8444/",
                 "FRAME_LOCAL_FEDERATION_ENDPOINT_URL": "https://sbx-b.example.invalid:8443",
                 "REGISTRY_NAME": "Sandbox B"}.items():
        monkeypatch.setenv(k, v)

    async def _db():
        yield session
    app = FastAPI()
    app.include_router(fi.router)
    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[require_mainframe_only] = lambda: None
    app.dependency_overrides[security.get_current_developer] = lambda: types.SimpleNamespace(
        id=7, email="ops@example.invalid", is_admin=False, must_change_password=False, admin_federation=True)

    async def _no_event(*a, **kw):
        return None
    monkeypatch.setattr(fi, "_emit_event", _no_event)
    monkeypatch.setattr(fi, "_schedule_compliance_baseline", lambda *a, **kw: None)
    _Client.calls = []
    monkeypatch.setattr(fi.httpx, "AsyncClient", _Client)
    return TestClient(app)


def _outbound(monkeypatch):
    http = _admin_app(monkeypatch, _OutboundSession())
    r = http.post("/api/v1/admin/federation/frame-invitations/outbound",
                  json={"target_registry_url": "https://sbx-a.example.invalid", "contact_email": "ops@example.invalid"})
    assert r.status_code == 201, r.text[:300]
    (_url, kw), = _Client.calls
    return kw.get("verify")


def test_the_outbound_trusts_the_edge_ca_under_the_honored_opt_in(monkeypatch, tmp_path):
    # BASE: verify=True, always
    _honored(monkeypatch, FRAME_INVITATIONS_PEER_CA_FILE=_ca_file(tmp_path))
    assert _trusts_the_edge_ca(_outbound(monkeypatch))


@pytest.mark.parametrize("case", ["production posture", "a missing file", "no file named", "opt-in off"])
def test_control_the_outbound_keeps_the_public_roots_otherwise(monkeypatch, tmp_path, case):
    # control: passes on both trees
    ca = _ca_file(tmp_path)
    if case == "production posture":
        _env(monkeypatch, REGISTRY_ENVIRONMENT="sandbox", FRAME_POSTURE="production",
             FRAME_INVITATIONS_SAME_HOST_PEERS="true", FRAME_INVITATIONS_PEER_CA_FILE=ca)
    elif case == "a missing file":
        _honored(monkeypatch, FRAME_INVITATIONS_PEER_CA_FILE=str(tmp_path / "absent.pem"))
    elif case == "no file named":
        _honored(monkeypatch)
    else:
        _env(monkeypatch, FRAME_POSTURE="sandbox", FRAME_INVITATIONS_PEER_CA_FILE=ca)
    assert _outbound(monkeypatch) is True


def test_the_finalize_public_leg_follows_the_same_rule(monkeypatch, tmp_path):
    # BASE: the public leg verifies against the public roots only
    import agentvault_registry.identity.svid_client as sc
    monkeypatch.setattr(sc, "get_client_cert_config", lambda target_url="": None, raising=False)
    inv = types.SimpleNamespace(id="inv-1", initiator_federation_endpoint_url="https://sbx-a.example.invalid:8443")
    assert fi._finalize_targets(inv)[0][2] == {"verify": True}                    # the opt-in off
    _honored(monkeypatch, FRAME_INVITATIONS_PEER_CA_FILE=_ca_file(tmp_path))
    (leg, url, kw), = fi._finalize_targets(inv)
    assert leg == "public" and url.startswith("https://sbx-a.example.invalid/") and _trusts_the_edge_ca(kw["verify"])


@pytest.mark.parametrize("env,state", [({}, "off"),
                                       ({"FRAME_POSTURE": "sandbox", "FRAME_INVITATIONS_SAME_HOST_PEERS": "true"}, "on"),
                                       ({"REGISTRY_ENVIRONMENT": "sandbox",
                                         "FRAME_INVITATIONS_SAME_HOST_PEERS": "true"}, "refused")])
def test_the_admin_list_names_the_opt_ins_state(monkeypatch, env, state):
    # BASE: no same_host_peers in the config block
    _env(monkeypatch, **env)
    http = _admin_app(monkeypatch, _OutboundSession())
    r = http.get("/api/v1/admin/federation/frame-invitations")
    assert r.status_code == 200, r.text[:300]
    assert r.json()["config"]["same_host_peers"].startswith(state)
