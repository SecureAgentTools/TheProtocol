"""D6-716 (2026-10-16): the admin-path throttle exempts a caller whose credential verified, never a request's shape.

main.py's admin_path_throttle (10 requests a minute per address on /admin/ paths) let through, uncounted, any request
with "Authorization: Bearer " and 21 characters of anything, and any request that merely carried X-Federation-Secret or
X-Federation-SPIFFE-ID: a prober added one header and was never throttled. Now a caller verified before the route runs
(a JWT this registry signed, a vouched peer certificate, the internal secret from inside the host) passes; an API key
passes once its route verified it; everything else is counted. Each test marked BASE fails on 14520b9f.

Through the real application (agentvault_registry.main.app, every middleware); only Redis and the database lookups
are replaced.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from agentvault_registry import security
from agentvault_registry.crud import developer as developer_crud

ROUTE = "/api/v1/admin/invite-codes"
LIMIT = 10


class _Redis:
    """Enough of a Redis for the throttle's counter; any other call answers None."""

    def __init__(self):
        self.kv = {}

    async def get(self, k):
        return self.kv.get(k)

    async def incr(self, k):
        self.kv[k] = int(self.kv.get(k) or 0) + 1
        return self.kv[k]

    async def expire(self, *a, **k):
        return True

    def __getattr__(self, name):
        async def _noop(*a, **k):
            return None
        return _noop


@pytest.fixture(scope="module")
def app():
    from agentvault_registry.main import app as _app
    return _app


@pytest.fixture()
def client(app, monkeypatch):
    fake = _Redis()

    async def _get_redis():
        return fake
    import agentvault_registry.background_tasks.leader as leader
    monkeypatch.setattr(leader, "get_redis", _get_redis)
    return TestClient(app, raise_server_exceptions=False)


def _statuses(client, headers, n=LIMIT + 2):
    return [client.get(ROUTE, headers=headers).status_code for _ in range(n)]


def test_a_junk_bearer_is_counted(client):   # BASE: never 429
    s = _statuses(client, {"Authorization": "Bearer " + "x" * 30})
    assert 429 not in s[:LIMIT] and s[LIMIT:] == [429, 429], s


def test_bare_federation_headers_are_counted(client):   # BASE: never 429
    s = _statuses(client, {"X-Federation-Secret": "guess", "X-Federation-SPIFFE-ID": "spiffe://example.test/x"})
    assert s[LIMIT:] == [429, 429], s


def test_a_spiffe_header_alone_is_counted(client):   # BASE: never 429
    s = _statuses(client, {"X-Federation-SPIFFE-ID": "spiffe://example.test/x"})
    assert s[LIMIT:] == [429, 429], s


def test_control_no_credential_is_counted(client):
    s = _statuses(client, {})
    assert 429 not in s[:LIMIT] and s[LIMIT:] == [429, 429], s


def test_control_a_jwt_this_registry_signed_is_never_counted(client):
    tok = security.create_access_token({"sub": "7"})
    assert 429 not in _statuses(client, {"Authorization": f"Bearer {tok}"})


def test_control_an_api_key_its_route_verified_is_never_counted(client, monkeypatch):
    dev = SimpleNamespace(id=7, email="a@example.test", name="A", is_admin=False, admin_support=False,
                          must_change_password=False, is_suspended=False, deleted_at=None, deletion_status=None,
                          two_fa_enabled=False, token_version=0)

    async def _dev(*a, **k):
        return dev

    async def _row(*a, **k):
        return SimpleNamespace(id=42, scopes=["*"])
    monkeypatch.setattr(developer_crud, "get_developer_by_plain_api_key", _dev)
    monkeypatch.setattr(developer_crud, "get_developer_by_id_strict", _dev)
    monkeypatch.setattr(developer_crud, "get_api_key_row_by_plain_key", _row)
    s = _statuses(client, {"Authorization": "Bearer avreg_" + "k" * 43})
    assert 429 not in s and s[0] == 403, s   # verified, then refused for the missing flag: never throttled


@pytest.fixture()
def inside(app, monkeypatch):
    """A client inside the host (a loopback peer, no proxy headers) on a registry holding an internal secret."""
    import agentvault_registry.background_tasks.leader as leader
    from agentvault_registry.core import federation_auth
    fake = _Redis()

    async def _get_redis():
        return fake
    monkeypatch.setattr(leader, "get_redis", _get_redis)
    monkeypatch.setattr(federation_auth, "FEDERATION_INTERNAL_SECRET", "s" * 40)
    try:
        return TestClient(app, raise_server_exceptions=False, client=("127.0.0.1", 50000))
    except TypeError:
        pytest.skip("this Starlette's TestClient cannot name its peer")


def test_control_the_internal_secret_from_inside_the_host_is_exempt(inside):
    ok = [inside.get(ROUTE, headers={"X-Federation-Secret": "s" * 40}).status_code for _ in range(LIMIT + 2)]
    assert 429 not in ok, ok


def test_a_wrong_internal_secret_is_counted(inside):   # BASE: never 429 (the header's presence exempted it)
    wrong = [inside.get(ROUTE, headers={"X-Federation-Secret": "t" * 40}).status_code for _ in range(LIMIT + 2)]
    assert wrong[LIMIT:] == [429, 429], wrong


# ── §SUITES1018 (2026-10-18): the tester key a console sends verifies ───────────────────────────────────────────────
# EU's console proxies an MCP-tester sweep to sbx-alpha with EU's JWT (unverifiable there) and the tester key
# (X-Internal-Key, core/api_test_proxy_key). The route accepted the key, the throttle never knew: the sweep was counted
# per address after it ran, beside the console's six-second progress polls, and came back 429 once the window held ten
# (the cloud-op sandboxdelta flow, refused on every V0623 run). RED on 9ac0925c: the key's request is counted.
TESTER_KEY = "k" * 40


@pytest.fixture()
def tester_key(monkeypatch):
    monkeypatch.setenv("API_TEST_PROXY_INTERNAL_KEY", TESTER_KEY)
    return TESTER_KEY


def test_a_tester_key_that_verifies_is_never_counted(client, tester_key):   # BASE: 429 after ten
    s = _statuses(client, {"Authorization": "Bearer " + "e.u.jwt", "X-Internal-Key": tester_key})
    assert 429 not in s, s


def test_a_proxied_sweep_is_not_refused_after_the_console_polled_ten_times(client, tester_key):   # BASE: 429
    # the console's progress polls: a bearer this registry did not sign and no key, counted (and refused past ten)
    polls = _statuses(client, {"Authorization": "Bearer " + "e.u.jwt"})
    assert polls[LIMIT:] == [429, 429], polls
    # the sweep itself, from the same address, carrying the key: never replaced by a 429
    r = client.get(ROUTE, headers={"Authorization": "Bearer " + "e.u.jwt", "X-Internal-Key": tester_key})
    assert r.status_code != 429, (r.status_code, r.text)


def test_control_a_wrong_tester_key_is_counted(client, tester_key):
    s = _statuses(client, {"Authorization": "Bearer " + "e.u.jwt", "X-Internal-Key": "w" * 40})
    assert s[LIMIT:] == [429, 429], s


def test_control_no_configured_key_means_no_exemption(client, monkeypatch):
    monkeypatch.delenv("API_TEST_PROXY_INTERNAL_KEY", raising=False)
    s = _statuses(client, {"Authorization": "Bearer " + "e.u.jwt", "X-Internal-Key": TESTER_KEY})
    assert s[LIMIT:] == [429, 429], s
