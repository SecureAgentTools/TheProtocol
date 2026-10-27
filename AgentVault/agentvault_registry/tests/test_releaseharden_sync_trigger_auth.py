"""§RELEASEHARDEN D1 (2026-09-14) — `POST /federation/sync/trigger` authenticates its caller.

The dependency is called directly with a real Starlette Request so every refusal sentence is the wire
one. Three lanes, in the order the code tries them, and the one that must never open: a federation
licence header alone (`_verify_license_key` is monkeypatched to fail loudly if anything reads it).
"""
from __future__ import annotations

import inspect

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from agentvault_registry.core import federation_auth
from agentvault_registry.routers import federation_sync as fs

PEER = "spiffe://agentvault.com/service/registry-a"
AGENT = "spiffe://agentvault.com/agent/0f3c9d"
# ⚠ not an RFC 5737 documentation address: Python's `ipaddress` counts 192.0.2/24, 198.51.100/24 and
# 203.0.113/24 as PRIVATE, so `is_internal_request` would read them as inside the host (a test that
# used 203.0.113.9 as "outside" passed the internal lane on its first run).
OUTSIDE = ("8.8.8.8", 4321)


def _req(headers: dict | None = None, client=OUTSIDE) -> Request:
    scope = {
        "type": "http", "method": "POST", "path": "/api/v1/federation/sync/trigger", "query_string": b"",
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
        "client": client,
    }
    return Request(scope)


async def _no_cert(_request):
    raise HTTPException(status_code=401, detail="No client certificate")


async def _cert(spiffe_id):
    async def _f(_request):
        return spiffe_id
    return _f


async def _noop(*_a, **_k):
    return None


async def _never_read_the_licence(*_a, **_k):
    raise AssertionError("the licence verifier was consulted by the sync trigger")


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    monkeypatch.setattr(fs, "get_client_spiffe_id", _no_cert)
    monkeypatch.setattr(federation_auth, "_verify_license_key", _never_read_the_licence)
    # the shared narrowing keeps its identity-class rule; its two DB-backed halves are stubbed
    monkeypatch.setattr(federation_auth, "_assert_peer_spiffe_binding", _noop)
    monkeypatch.setattr(federation_auth, "_assert_operator_license_not_revoked", _noop)
    monkeypatch.setattr(fs, "FEDERATION_INTERNAL_SECRET", "s3cret-for-the-test")


async def test_anonymous_is_refused_401_with_the_three_lanes_named():
    with pytest.raises(HTTPException) as exc:
        await fs.require_sync_trigger_identity(_req(), db=None, authorization=None)
    assert exc.value.status_code == 401
    assert exc.value.detail == fs.SYNC_TRIGGER_AUTH_REQUIRED


async def test_a_federation_licence_alone_is_refused_and_never_verified():
    with pytest.raises(HTTPException) as exc:
        await fs.require_sync_trigger_identity(_req({"X-Federation-License": "tp_fed_abc"}), db=None, authorization=None)
    assert exc.value.status_code == 401


async def test_an_mtls_peer_registry_passes_the_shared_narrowing(monkeypatch):
    monkeypatch.setattr(fs, "get_client_spiffe_id", await _cert(PEER))
    assert await fs.require_sync_trigger_identity(_req(), db=None, authorization=None) == PEER


async def test_an_mtls_agent_svid_is_not_a_peer_registry(monkeypatch):
    # §EXTMTLS mints agent SVIDs for developers' own machines; a certificate is not a peer
    monkeypatch.setattr(fs, "get_client_spiffe_id", await _cert(AGENT))
    with pytest.raises(HTTPException) as exc:
        await fs.require_sync_trigger_identity(_req(), db=None, authorization=None)
    assert exc.value.status_code == 403
    assert "not a valid peer registry" in exc.value.detail


async def test_the_internal_lane_from_outside_the_host_is_refused():
    hdr = {"X-Federation-Secret": "s3cret-for-the-test", "X-Federation-SPIFFE-ID": PEER}
    with pytest.raises(HTTPException) as exc:
        await fs.require_sync_trigger_identity(_req(hdr, client=OUTSIDE), db=None, authorization=None)
    assert exc.value.status_code == 401 and "not reachable from outside" in exc.value.detail
    # an edge header on a private peer is the same refusal: it traversed the edge
    hdr2 = dict(hdr, **{"X-Forwarded-For": "8.8.8.8"})
    with pytest.raises(HTTPException) as exc2:
        await fs.require_sync_trigger_identity(_req(hdr2, client=("172.16.0.5", 1)), db=None, authorization=None)
    assert exc2.value.status_code == 401


async def test_the_internal_lane_from_inside_with_the_right_secret_passes():
    hdr = {"X-Federation-Secret": "s3cret-for-the-test", "X-Federation-SPIFFE-ID": PEER}
    assert await fs.require_sync_trigger_identity(_req(hdr, client=("172.16.0.5", 1)), db=None, authorization=None) == PEER


async def test_the_internal_lane_with_a_wrong_secret_is_refused():
    hdr = {"X-Federation-Secret": "wrong", "X-Federation-SPIFFE-ID": PEER}
    with pytest.raises(HTTPException) as exc:
        await fs.require_sync_trigger_identity(_req(hdr, client=("127.0.0.1", 1)), db=None, authorization=None)
    assert exc.value.status_code == 401 and exc.value.detail == "Invalid federation secret"


async def test_the_internal_lane_from_an_untrusted_domain_is_403():
    hdr = {"X-Federation-Secret": "s3cret-for-the-test", "X-Federation-SPIFFE-ID": "spiffe://evil.example/service/registry-x"}
    with pytest.raises(HTTPException) as exc:
        await fs.require_sync_trigger_identity(_req(hdr, client=("127.0.0.1", 1)), db=None, authorization=None)
    assert exc.value.status_code == 403


class _Dev:
    def __init__(self, is_admin: bool, flag: bool):
        self.id = 7
        self.email = "seven@example.test"
        self.is_admin = is_admin
        self.admin_federation = flag
        self.must_change_password = False


def _developer_lane(monkeypatch, dev):
    async def scheme(_request):
        return "jwt"

    async def verify(_request, token, db):
        assert token == "jwt"
        return 7

    async def load(db, developer_id):
        assert developer_id == 7
        return dev

    monkeypatch.setattr(fs.security, "oauth2_scheme_required", scheme)
    monkeypatch.setattr(fs.security, "verify_access_token_required", verify)
    monkeypatch.setattr(fs.security, "get_current_developer", load)


async def test_an_admin_developer_passes_the_standard_gate(monkeypatch):
    _developer_lane(monkeypatch, _Dev(is_admin=True, flag=True))
    out = await fs.require_sync_trigger_identity(_req({"Authorization": "Bearer jwt"}), db=None, authorization="Bearer jwt")
    assert out == "developer:7"


async def test_a_developer_with_only_the_federation_flag_passes(monkeypatch):
    _developer_lane(monkeypatch, _Dev(is_admin=False, flag=True))
    out = await fs.require_sync_trigger_identity(_req({"Authorization": "Bearer jwt"}), db=None, authorization="Bearer jwt")
    assert out == "developer:7"


async def test_a_plain_developer_is_refused_403(monkeypatch):
    _developer_lane(monkeypatch, _Dev(is_admin=False, flag=False))
    with pytest.raises(HTTPException) as exc:
        await fs.require_sync_trigger_identity(_req({"Authorization": "Bearer jwt"}), db=None, authorization="Bearer jwt")
    assert exc.value.status_code == 403


def test_the_route_declares_the_dependency():
    params = inspect.signature(fs.trigger_sync).parameters
    deps = [getattr(p.default, "dependency", None) for p in params.values()]
    assert fs.require_sync_trigger_identity in deps
