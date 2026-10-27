"""§HELLOFRAME (2026-09-18): the INITIATOR side of the frame invitation rail, and a finalize that completes on a
registry that holds no docker socket.

Measured before this: only the sandbox bootstrap ever wrote an outbound row; the finalize callback addresses the
SENDER's row id on the receiver, so the two 09-03 sandbox rows could never complete; every SPIRE operation of the rail
runs `docker exec` through a socket a hardened registry does not hold, so a socket-less initiator answered 502 before
any row changed. No database, no SPIRE, no network here: a fake session, a fake httpx client, and a trust manager that
must not be reached.
"""
import datetime
import inspect
import pathlib
import ssl
import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry import models, security
from agentvault_registry.core.mainframe_gate import require_mainframe_only
from agentvault_registry.database import get_db
from agentvault_registry.routers import frame_invitations as inv

NOW = datetime.datetime(2026, 9, 18, 15, 0, tzinfo=datetime.timezone.utc)
NONCE = "0123456789abcdef0123456789abcdef"
REMOTE_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
PEER = "https://peer.example.org"
OWN = {"SPIRE_TRUST_DOMAIN": "frame.example.org", "FRAME_LOCAL_BUNDLE_ENDPOINT_URL": "https://frame.example.org:8444/",
       "FRAME_LOCAL_FEDERATION_ENDPOINT_URL": "https://frame.example.org:8443",
       "EVENT_STORE_PUBLIC_URL": "https://frame.example.org:8445", "REGISTRY_NAME": "Frame Example"}
OUTBOUND = "/api/v1/admin/federation/frame-invitations/outbound"


class _Result:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value

    def scalars(self):
        return self

    def all(self):
        return self.value if isinstance(self.value, list) else ([] if self.value is None else [self.value])

    def first(self):
        return self.value[0] if isinstance(self.value, list) else self.value


class FakeSession:
    """Answers each execute() with the next queued value; records the rows added and the commits."""

    def __init__(self, *answers):
        self.answers, self.statements, self.added, self.commits, self.flushes = list(answers), [], [], 0, 0

    async def execute(self, statement):
        self.statements.append(statement)
        return _Result(self.answers.pop(0) if self.answers else None)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        self.flushes += 1
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = 4242

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        pass

    async def refresh(self, obj):
        if getattr(obj, "created_at", None) is None:
            obj.created_at = NOW


class _Response:
    def __init__(self, status_code, body):
        self.status_code, self._body = status_code, body

    @property
    def text(self):
        import json
        return json.dumps(self._body) if isinstance(self._body, dict) else str(self._body)

    def json(self):
        return self._body


class FakeClient:
    """httpx.AsyncClient stand-in: records every post and answers the queued response (or raises)."""
    calls = []
    answer = None

    def __init__(self, **kw):
        self.kw = kw

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None):
        FakeClient.calls.append((url, json, self.kw))
        if isinstance(FakeClient.answer, Exception):
            raise FakeClient.answer
        return FakeClient.answer


class _Explode:
    """A trust manager the socket-less path must never touch."""
    spire_container = "frame-spire-server"

    def __getattr__(self, name):
        raise AssertionError(f"the trust manager was reached ({name}); a socket-less finalize must not run docker exec")


def _own_env(monkeypatch, **override):
    for k, v in {**OWN, **override}.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)


def _app(session, monkeypatch, developer=None):
    async def _db():
        yield session
    app = FastAPI()
    app.include_router(inv.router)
    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[require_mainframe_only] = lambda: None
    if developer is not None:
        app.dependency_overrides[security.get_current_developer] = lambda: developer

    async def _no_event(*a, **kw):
        return None
    monkeypatch.setattr(inv, "_emit_event", _no_event)
    monkeypatch.setattr(inv, "_schedule_compliance_baseline", lambda *a, **kw: None)
    return TestClient(app)


def _admin(**flags):
    fields = {"id": 7, "email": "ops@example.test", "is_admin": False, "must_change_password": False, "admin_federation": True}
    fields.update(flags)
    return types.SimpleNamespace(**fields)


@pytest.fixture(autouse=True)
def _fake_httpx(monkeypatch):
    FakeClient.calls = []
    FakeClient.answer = _Response(201, {"id": REMOTE_ID, "status": "pending", "created_at": NOW.isoformat()})
    monkeypatch.setattr(inv.httpx, "AsyncClient", FakeClient)


# ---- the outbound endpoint ----------------------------------------------------------------------------------------------

def test_an_outbound_invitation_is_recorded_under_the_id_the_peer_returned(monkeypatch):
    _own_env(monkeypatch)
    session = FakeSession(None)          # no row with that id yet
    http = _app(session, monkeypatch, _admin())
    r = http.post(OUTBOUND, json={"target_registry_url": PEER, "contact_email": "ops@frame.example.org",
                                  "description": "hello"})
    assert r.status_code == 201, r.text
    doc = r.json()
    assert doc["id"] == REMOTE_ID and doc["status"] == "pending" and doc["spire_bundle_imported"] is False
    # what the peer was told: OUR facts, and the nonce the row keeps
    (url, sent, kw), = FakeClient.calls
    assert url == f"{PEER}/api/v1/federation/frame-invitations" and kw.get("verify") is True
    assert sent["trust_domain"] == "frame.example.org"
    assert sent["bundle_endpoint_url"] == OWN["FRAME_LOCAL_BUNDLE_ENDPOINT_URL"]
    assert sent["federation_endpoint_url"] == OWN["FRAME_LOCAL_FEDERATION_ENDPOINT_URL"]
    assert sent["event_store_url"] == OWN["EVENT_STORE_PUBLIC_URL"] and sent["name"] == "Frame Example"
    assert sent["contact_email"] == "ops@frame.example.org" and sent["description"] == "hello"
    row = session.added[0]
    assert isinstance(row, models.FrameInvitation)
    assert row.id == REMOTE_ID and row.initiator_nonce == sent["initiator_nonce"] and len(row.initiator_nonce) == 32
    assert row.initiator_trust_domain == "frame.example.org" and row.status == "pending"
    assert row.spire_bundle_imported_at is None and row.reviewed_by == 7 and session.commits == 1


def test_a_pre_imported_bundle_is_recorded_on_the_row(monkeypatch):
    _own_env(monkeypatch)
    session = FakeSession(None)
    http = _app(session, monkeypatch, _admin())
    r = http.post(OUTBOUND, json={"target_registry_url": PEER, "contact_email": "ops@frame.example.org",
                                  "spire_bundle_imported": True})
    assert r.status_code == 201, r.text
    assert r.json()["spire_bundle_imported"] is True and session.added[0].spire_bundle_imported_at is not None


@pytest.mark.parametrize("answer", [_Response(429, {"detail": "5/hour"}), _Response(503, "disabled"),
                                    _Response(201, {"status": "pending"}), ConnectionError("refused")])
def test_a_peer_that_refuses_or_cannot_be_reached_or_returns_no_id_stores_nothing(monkeypatch, answer):
    _own_env(monkeypatch)
    FakeClient.answer = answer
    session = FakeSession(None)
    http = _app(session, monkeypatch, _admin())
    r = http.post(OUTBOUND, json={"target_registry_url": PEER, "contact_email": "ops@frame.example.org"})
    assert r.status_code == 502, r.text
    assert PEER in r.json()["detail"] and session.added == [] and session.commits == 0


def test_a_frame_that_does_not_know_its_own_lane_refuses_before_dialing(monkeypatch):
    _own_env(monkeypatch, FRAME_LOCAL_FEDERATION_ENDPOINT_URL=None, BILATERAL_PEER_URL=None)
    session = FakeSession(None)
    http = _app(session, monkeypatch, _admin())
    r = http.post(OUTBOUND, json={"target_registry_url": PEER, "contact_email": "ops@frame.example.org"})
    assert r.status_code == 400 and "FRAME_LOCAL_FEDERATION_ENDPOINT_URL" in r.json()["detail"]
    assert FakeClient.calls == [] and session.added == []


def test_a_row_that_already_carries_the_peers_id_is_refused(monkeypatch):
    _own_env(monkeypatch)
    session = FakeSession(models.FrameInvitation(id=REMOTE_ID, status="completed"))
    http = _app(session, monkeypatch, _admin())
    r = http.post(OUTBOUND, json={"target_registry_url": PEER, "contact_email": "ops@frame.example.org"})
    assert r.status_code == 409 and session.added == []


@pytest.mark.parametrize("flags", [{"admin_federation": False}, {"admin_federation": False, "admin_platform": True}])
def test_the_outbound_endpoint_needs_admin_federation(monkeypatch, flags):
    _own_env(monkeypatch)
    session = FakeSession(None)
    http = _app(session, monkeypatch, _admin(**flags))
    r = http.post(OUTBOUND, json={"target_registry_url": PEER, "contact_email": "ops@frame.example.org"})
    assert r.status_code == 403 and FakeClient.calls == []


# ---- finalize without a docker socket -------------------------------------------------------------------------------

def _outbound_row(pre_imported):
    return models.FrameInvitation(
        id=REMOTE_ID, initiator_trust_domain="frame.example.org",
        initiator_bundle_endpoint_url=OWN["FRAME_LOCAL_BUNDLE_ENDPOINT_URL"],
        initiator_federation_endpoint_url=OWN["FRAME_LOCAL_FEDERATION_ENDPOINT_URL"],
        initiator_name="Frame Example", initiator_contact_email="ops@frame.example.org",
        initiator_nonce=NONCE, status="pending", reviewed_by=7,
        spire_bundle_imported_at=(NOW - datetime.timedelta(minutes=3)) if pre_imported else None,
    )


FINALIZE_BODY = {
    "approver_trust_domain": "peer.example.org",
    "approver_bundle_endpoint_url": "https://peer.example.org:8444/",
    "approver_federation_endpoint_url": "https://peer.example.org:8443",
    "approver_name": "Peer Example",
    "approver_bundle_pem": '{"keys": [{"use": "x509-svid", "kty": "EC", "crv": "P-256", "x": "a", "y": "b"}]}',
    "nonce_echo": NONCE,
    "federation_license_key": "tp_fed_" + "c" * 64,
}


def test_finalize_completes_without_touching_spire_when_the_host_cli_imported_the_bundle(monkeypatch):
    _own_env(monkeypatch)
    row = _outbound_row(pre_imported=True)
    session = FakeSession(row, None)     # the row; no existing peer row for the approver
    monkeypatch.setattr(inv, "get_frame_trust_manager", lambda: _Explode())
    http = _app(session, monkeypatch)
    r = http.post(f"/api/v1/federation/frame-invitations/{REMOTE_ID}/finalize", json=FINALIZE_BODY)
    assert r.status_code == 200, r.text
    doc = r.json()
    assert doc["status"] == "completed" and doc["federation_license_key"] == FINALIZE_BODY["federation_license_key"]
    assert doc["entries_federated"]["skipped"] and doc["federation_relationship"]["skipped"]
    peer = session.added[0]
    assert isinstance(peer, models.PeerRegistry)
    assert peer.base_url == "https://peer.example.org:8443", "the row dials the approver's FEDERATION lane, not its bundle endpoint"
    assert peer.spiffe_bundle_endpoint_url == "https://peer.example.org:8444/" and peer.peer_type == "frame"
    assert peer.trust_domain == "peer.example.org" and peer.owner_developer_id == 7
    assert row.status == "completed" and row.completed_at is not None
    assert row.spire_bundle_imported_at == NOW - datetime.timedelta(minutes=3), "the CLI's import time is kept, not overwritten"
    assert "prefix tp_fed_ccccc" in (row.review_notes or ""), "the licence PREFIX (12 chars) is noted, never the key"
    assert "c" * 20 not in (row.review_notes or "") and session.commits == 1


def test_finalize_without_a_pre_import_still_imports_through_the_trust_manager(monkeypatch):
    """The control: the old road stays for a registry that holds a socket."""
    _own_env(monkeypatch)
    row = _outbound_row(pre_imported=False)
    session = FakeSession(row, None)
    reached = []

    class _Manager:
        spire_container = "frame-spire-server"

        async def add_peer_bundle(self, td, body, format_hint="spiffe"):
            reached.append(("bundle", td, format_hint))
            from agentvault_registry.services.frame_trust_manager import FrameTrustResult
            return FrameTrustResult(True, "ok")

    async def _entries(mgr, td, *, site):
        reached.append(("entries", td, site)); return {"ok": True}

    async def _relationship(mgr, td, url, *, site):
        reached.append(("relationship", td, url)); return {"ok": True}
    monkeypatch.setattr(inv, "get_frame_trust_manager", lambda: _Manager())
    monkeypatch.setattr(inv, "_federate_entries_after_bundle", _entries)
    monkeypatch.setattr(inv, "_federation_relationship_after_bundle", _relationship)
    http = _app(session, monkeypatch)
    r = http.post(f"/api/v1/federation/frame-invitations/{REMOTE_ID}/finalize", json=FINALIZE_BODY)
    assert r.status_code == 200, r.text
    assert [x[0] for x in reached] == ["bundle", "entries", "relationship"] and reached[0][2] == "spiffe"
    assert row.spire_bundle_imported_at is not None and session.added[0].base_url == "https://peer.example.org:8443"


def test_an_older_approver_that_names_no_federation_lane_keeps_the_bundle_derived_address(monkeypatch):
    _own_env(monkeypatch)
    row = _outbound_row(pre_imported=True)
    session = FakeSession(row, None)
    monkeypatch.setattr(inv, "get_frame_trust_manager", lambda: _Explode())
    http = _app(session, monkeypatch)
    body = {k: v for k, v in FINALIZE_BODY.items() if k != "approver_federation_endpoint_url"}
    body["approver_bundle_endpoint_url"] = "https://peer.example.org:8444/.well-known/spiffe/bundle"
    r = http.post(f"/api/v1/federation/frame-invitations/{REMOTE_ID}/finalize", json=body)
    assert r.status_code == 200, r.text
    assert session.added[0].base_url == "https://peer.example.org:8444"


def test_a_wrong_nonce_or_a_completed_row_is_refused_without_touching_anything(monkeypatch):
    _own_env(monkeypatch)
    monkeypatch.setattr(inv, "get_frame_trust_manager", lambda: _Explode())
    row = _outbound_row(pre_imported=True)
    http = _app(FakeSession(row), monkeypatch)
    r = http.post(f"/api/v1/federation/frame-invitations/{REMOTE_ID}/finalize", json={**FINALIZE_BODY, "nonce_echo": "f" * 32})
    assert r.status_code == 403
    done = _outbound_row(pre_imported=True); done.status = "completed"
    r = http.post(f"/api/v1/federation/frame-invitations/{REMOTE_ID}/finalize", json=FINALIZE_BODY)  # session exhausted -> 404
    assert r.status_code == 404
    http2 = _app(FakeSession(done), monkeypatch)
    assert http2.post(f"/api/v1/federation/frame-invitations/{REMOTE_ID}/finalize", json=FINALIZE_BODY).status_code == 409


# ---- the approver's callback verifies against the bundle it just read ------------------------------------------------

def _self_signed_pem():
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test root")])
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(NOW - datetime.timedelta(days=1))
            .not_valid_after(NOW + datetime.timedelta(days=30))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True).sign(key, hashes.SHA256()))
    return cert.public_bytes(serialization.Encoding.PEM).decode()


async def test_the_mtls_leg_verifies_against_the_freshest_bundle_and_the_body_names_our_lane(monkeypatch):
    _own_env(monkeypatch)
    from agentvault_registry.identity import svid_client
    monkeypatch.setattr(svid_client, "get_client_cert_config", lambda target_url=None: {"cert": ("/certs/svid.0.pem", "/certs/svid.0.key")})
    row = _outbound_row(pre_imported=False)
    pem = _self_signed_pem()
    legs = inv._finalize_targets(row, verify_bundle_body=pem)
    assert [leg for leg, _, _ in legs] == ["mtls", "public"]
    assert isinstance(legs[0][2]["verify"], ssl.SSLContext), "the mtls leg trusts the bundle just read, not only the on-disk file"
    assert legs[0][2]["cert"] == ("/certs/svid.0.pem", "/certs/svid.0.key")
    assert legs[1][1] == f"https://frame.example.org/api/v1/federation/frame-invitations/{REMOTE_ID}/finalize" and legs[1][2] == {"verify": True}
    # a JWK set carries no PEM: the default verify stays
    assert inv._verify_context_with_bundle('{"keys": []}') is None and inv._verify_context_with_bundle(None) is None
    # the callback body names the approver's federation lane
    posted = []

    class _Posting(FakeClient):
        async def post(self, url, json=None):
            posted.append((url, json, self.kw)); return _Response(200, {"status": "completed"})
    monkeypatch.setattr(inv.httpx, "AsyncClient", _Posting)
    # awaited in the plugin's loop: a sync test that runs its own loop leaves the thread without one for the next file
    ok, err, _ = await inv._post_bilateral_finalize(row, pem, "tp_fed_" + "d" * 64)
    assert ok and posted[0][1]["approver_federation_endpoint_url"] == OWN["FRAME_LOCAL_FEDERATION_ENDPOINT_URL"]
    assert posted[0][1]["federation_license_key"] == "tp_fed_" + "d" * 64


# ---- finalize-retry hands over a NEW key ------------------------------------------------------------------------------

def test_finalize_retry_rotates_the_licence_and_posts_the_new_key(monkeypatch):
    _own_env(monkeypatch)
    row = _outbound_row(pre_imported=False); row.status = "approved"; row.completed_at = None; row.peer_registry_id = 9
    lic = models.FederationLicense(id="lic-1", operator_name="Frame Example", operator_did="spiffe://frame.example.org",
                                   license_key_hash="old-hash", license_key_prefix="tp_fed_old00", status="active")
    session = FakeSession(row, lic)     # the row; then the existing licence inside _issue_frame_license
    from agentvault_registry.routers import federation_licenses as fl
    synced = []

    _real_sync_sig = inspect.signature(fl._sync_license_to_eventstore)

    async def _sync(**kw):
        _real_sync_sig.bind(**kw)   # a fake that accepts what the real function refuses tests the assumption, not the call
        synced.append(kw)
    monkeypatch.setattr(fl, "_sync_license_to_eventstore", _sync)

    async def _bundle():
        return '{"keys": []}', ""
    monkeypatch.setattr(inv, "_read_local_bundle", _bundle)
    posted = []

    async def _post(invitation, body, key=None):
        posted.append(key); return True, "", {}
    monkeypatch.setattr(inv, "_post_bilateral_finalize", _post)
    http = _app(session, monkeypatch, _admin())
    r = http.post(f"/api/v1/admin/federation/frame-invitations/{REMOTE_ID}/finalize-retry")
    assert r.status_code == 200, r.text
    doc = r.json()
    assert doc["completed"] is True and doc["federation_license_rotated"] is True and doc["federation_license_id"] == "lic-1"
    assert posted and posted[0].startswith("tp_fed_") and len(posted[0]) > 60, "the retry delivers a key, never nothing"
    assert lic.license_key_hash != "old-hash" and lic.license_key_prefix == posted[0][:12]
    assert synced and synced[0]["license_key_hash"] == lic.license_key_hash and synced[0]["op_status"] == "active" and row.completed_at is not None


# ---- the delivered key reaches the host CLI once ---------------------------------------------------------------------

class FakeRedis:
    def __init__(self):
        self.store, self.ttl = {}, {}

    async def set(self, k, v, ex=None):
        self.store[k] = v; self.ttl[k] = ex

    async def get(self, k):
        return self.store.get(k)

    async def delete(self, k):
        self.store.pop(k, None)


def _with_redis(monkeypatch, redis):
    from agentvault_registry.background_tasks import leader

    async def _get_redis():
        return redis
    monkeypatch.setattr(leader, "get_redis", _get_redis)


def test_finalize_parks_the_delivered_key_for_an_hour_and_the_admin_takes_it_once(monkeypatch):
    _own_env(monkeypatch)
    redis = FakeRedis(); _with_redis(monkeypatch, redis)
    row = _outbound_row(pre_imported=True)
    monkeypatch.setattr(inv, "get_frame_trust_manager", lambda: _Explode())
    http = _app(FakeSession(row, None), monkeypatch, _admin())
    r = http.post(f"/api/v1/federation/frame-invitations/{REMOTE_ID}/finalize", json=FINALIZE_BODY)
    assert r.status_code == 200, r.text
    k = f"frame_invitation:{REMOTE_ID}:licence_key"
    assert redis.store[k] == FINALIZE_BODY["federation_license_key"] and redis.ttl[k] == 3600
    assert "c" * 20 not in (row.review_notes or ""), "the key is parked, never written into the row"
    # the frame's admin takes it once
    http2 = _app(FakeSession(row), monkeypatch, _admin())
    r = http2.get(f"/api/v1/admin/federation/frame-invitations/{REMOTE_ID}/licence-key")
    assert r.status_code == 200, r.text
    assert r.json()["federation_license_key"] == FINALIZE_BODY["federation_license_key"] and r.json()["prefix"] == "tp_fed_ccccc"
    assert k not in redis.store
    http3 = _app(FakeSession(row), monkeypatch, _admin())
    r = http3.get(f"/api/v1/admin/federation/frame-invitations/{REMOTE_ID}/licence-key")
    assert r.status_code == 404 and "finalize-retry" in r.json()["detail"]


def test_the_key_route_refuses_before_completion_and_needs_admin_federation(monkeypatch):
    _own_env(monkeypatch)
    _with_redis(monkeypatch, FakeRedis())
    pending = _outbound_row(pre_imported=True)
    r = _app(FakeSession(pending), monkeypatch, _admin()).get(f"/api/v1/admin/federation/frame-invitations/{REMOTE_ID}/licence-key")
    assert r.status_code == 409
    done = _outbound_row(pre_imported=True); done.status = "completed"
    r = _app(FakeSession(done), monkeypatch, _admin(admin_federation=False)).get(f"/api/v1/admin/federation/frame-invitations/{REMOTE_ID}/licence-key")
    assert r.status_code == 403


def test_a_frame_without_redis_still_completes_and_says_the_key_was_not_parked(monkeypatch, caplog):
    _own_env(monkeypatch)
    _with_redis(monkeypatch, None)
    row = _outbound_row(pre_imported=True)
    monkeypatch.setattr(inv, "get_frame_trust_manager", lambda: _Explode())
    with caplog.at_level("WARNING"):
        r = _app(FakeSession(row, None), monkeypatch).post(f"/api/v1/federation/frame-invitations/{REMOTE_ID}/finalize", json=FINALIZE_BODY)
    assert r.status_code == 200 and row.status == "completed"
    assert any("cannot be parked" in m for m in caplog.messages)



def test_every_licence_sync_call_in_the_router_binds_to_the_real_signature():
    """§HELLOFRAME Phase 3: the approve issued a licence and then raised `unexpected keyword argument 'key_hash'` inside a
    best-effort except, so the peer got `federation_license_id: null` and a warning. Every call site is bound statically."""
    import ast
    from agentvault_registry.routers import federation_licenses as fl
    sig = inspect.signature(fl._sync_license_to_eventstore)
    src = pathlib.Path(inv.__file__).read_text()
    calls = [n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call)
             and getattr(n.func, "id", getattr(n.func, "attr", "")) == "_sync_license_to_eventstore"]
    assert calls, "the router no longer calls the sync; the gate must move with it"
    for c in calls:
        kws = {k.arg: None for k in c.keywords if k.arg}
        sig.bind(*([None] * len(c.args)), **kws)   # raises TypeError on an unknown keyword or a missing required one


@pytest.mark.parametrize("env,expected", [
    ({"BILATERAL_PEER_URL": "https://hello.example.org:28443", "FRAME_LOCAL_FEDERATION_ENDPOINT_URL": "https://hello-nginx-federation:8443"}, "https://hello.example.org:28443"),
    # the sandbox pair's shape: BILATERAL is the console (no port), FRAME_LOCAL the public mTLS lane
    ({"BILATERAL_PEER_URL": "https://sandbox-a.example.org", "FRAME_LOCAL_FEDERATION_ENDPOINT_URL": "https://sandbox-a.example.org:8443"}, "https://sandbox-a.example.org:8443"),
    ({"BILATERAL_PEER_URL": "https://frame.example.org:443"}, "https://frame.example.org:443"),   # alone and dialable: taken, port or not
    ({"FRAME_LOCAL_FEDERATION_ENDPOINT_URL": "https://hello-nginx-federation:8443"}, ""),
    ({"FRAME_LOCAL_FEDERATION_ENDPOINT_URL": "https://frame.example.org:8443/"}, "https://frame.example.org:8443"),
    ({"BILATERAL_PEER_URL": "https://127.0.0.1:8443"}, ""),
])
def test_the_advertised_lane_is_one_a_peer_can_dial(monkeypatch, env, expected):
    for k in ("BILATERAL_PEER_URL", "FRAME_LOCAL_FEDERATION_ENDPOINT_URL"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    assert inv._local_federation_endpoint_url() == expected



def _self_signed_der():
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "hello test root")])
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(datetime.datetime(2026, 1, 1))
            .not_valid_after(datetime.datetime(2036, 1, 1)).add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(key, hashes.SHA256()))
    return cert.public_bytes(serialization.Encoding.DER)


def test_a_spiffe_bundle_yields_pem_roots_and_a_verify_context():
    import base64
    der = _self_signed_der()
    import json as _json
    spiffe = _json.dumps({"keys": [{"use": "x509-svid", "kty": "EC", "x5c": [base64.b64encode(der).decode()]},
                                  {"use": "jwt-svid", "kty": "EC", "kid": "k"}], "spiffe_sequence": 1})
    pem = inv.pem_roots_from_bundle(spiffe)
    assert pem.count("-----BEGIN CERTIFICATE-----") == 1
    assert inv.pem_roots_from_bundle(pem) == pem            # PEM passes through
    assert inv.pem_roots_from_bundle("not json") == "" and inv.pem_roots_from_bundle("") == ""
    assert inv._verify_context_with_bundle(spiffe) is not None
    assert inv._verify_context_with_bundle(spiffe, pem) is not None
    assert inv._verify_context_with_bundle('{"keys": []}') is None      # no root: the default verify stays


def test_the_approve_callback_carries_the_initiators_bundle_into_the_verify_set(monkeypatch):
    seen = {}

    def _ctx(*bodies):
        seen["bodies"] = [b for b in bodies if b]; return None
    monkeypatch.setattr(inv, "_verify_context_with_bundle", _ctx)
    row = _outbound_row(pre_imported=False)
    inv._finalize_targets(row, verify_bundle_body="OURS", initiator_bundle_body="THEIRS")
    assert seen["bodies"] == ["OURS", "THEIRS"]


# ── §HELLOFRAME: an approve and a completed finalize clear the peer's card-pull parking
def test_clear_card_pull_parking_deletes_both_keys(monkeypatch):
    import asyncio
    from agentvault_registry.routers import frame_invitations as fi
    from agentvault_registry.background_tasks import leader

    class FakeRedis:
        def __init__(self): self.deleted = []
        async def delete(self, *keys): self.deleted.extend(keys); return len(keys)

    fake = FakeRedis()

    async def fake_get_redis(): return fake

    monkeypatch.setattr(leader, "get_redis", fake_get_redis)
    assert asyncio.run(fi._clear_card_pull_parking("Hello", where="test")) == 2
    assert fake.deleted == ["registry:federation:cardpull_backoff:Hello", "registry:federation:cardpull_streak:Hello"]
    assert asyncio.run(fi._clear_card_pull_parking("", where="test")) is None


def test_clear_card_pull_parking_survives_no_redis(monkeypatch):
    import asyncio
    from agentvault_registry.routers import frame_invitations as fi
    from agentvault_registry.background_tasks import leader

    async def none_redis(): return None

    monkeypatch.setattr(leader, "get_redis", none_redis)
    assert asyncio.run(fi._clear_card_pull_parking("Hello", where="test")) is None


def test_both_handlers_clear_the_parking():
    import pathlib
    from agentvault_registry.routers import frame_invitations as fi
    src = pathlib.Path(fi.__file__).read_text()
    assert 'await _clear_card_pull_parking(inv.initiator_name, where="approve")' in src
    assert 'await _clear_card_pull_parking(payload.approver_name, where="finalize")' in src
    # the keys the worker writes are the keys the handlers clear
    from agentvault_registry.background_tasks import federation_sync as fs
    assert fi.CARD_PULL_PARKING_PREFIXES == (fs._CARD_PULL_BACKOFF_PREFIX, fs._CARD_PULL_STREAK_PREFIX)
