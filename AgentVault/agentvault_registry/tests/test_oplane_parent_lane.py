"""§OPLANE (V0614, agentvault2-5b, 2026-10-14): a cloud operator's licence-carrying calls reach its parent frame.

Operator self-logs, self-restart and the IRONHAND proxy (an agent's SPIRE entry, its inline SVID, the entry's deletion)
dialled the parent's public CONSOLE host, whose vhost clears X-Federation-License on EU, ASIA and every frame the template
builds: on production each answered 401 "X-Federation-License header required" (measured 2026-10-14 with a fake licence:
sandbox-a's hand-made vhost let it through, 403 "Invalid or revoked"; EU and ASIA 401). They now dial the parent's
federation lane (its mTLS address, the operator's SVID) at aliases under /api/v1/federation/, which the parent serves
only through its own terminator. Pinned here: which peer row is the lane, which 404 means "not served yet", the guard,
the aliases reaching the same handlers (their licence check intact), and the operator side's fallback rules (a lane
that answered is never retried on the console: a restart is not sent twice).
"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry.core import mtls_auth, parent_lane

LANE = "https://eu.theprotocol.cloud:8443"
NOT_FOUND = json.dumps({"error": {"detail": "Not Found", "type": "not_found"}, "type": "x", "title": "Not Found",
                        "status": 404, "detail": "Not Found", "instance": "/api/v1/federation/operator-self/logs"})
OWN_404 = json.dumps({"error": {"detail": "No active cloud-hosted operator application matches this license's "
                                          "operator_did"}, "title": "Not Found", "status": 404,
                      "detail": "No active cloud-hosted operator application matches this license's operator_did"})
MARKER = "m" * 20 + "a1b2c3d4e5f6" + "z" * 20
_REAL_CLIENTS = {"AsyncClient": httpx.AsyncClient, "Client": httpx.Client}   # never a fake wrapping a fake


@pytest.fixture(autouse=True)
def _fresh_lane_state():
    parent_lane._state.update(host=None, origin=None, at=0.0, why="not resolved yet")
    yield
    parent_lane._state.update(host=None, origin=None, at=0.0, why="not resolved yet")
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


# ── which peer row is the lane ─────────────────────────────────────────────────────────────────────────────────────

ROWS = [("https://eu.theprotocol.cloud:8443", "frame", "ACTIVE"),
        ("https://asia.theprotocol.cloud:8443", "frame", "ACTIVE"),
        ("https://asia.theprotocol.cloud", "frame", "INACTIVE"),
        ("https://eu.theprotocol.cloud", "frame", "INACTIVE"),
        ("https://amsterdam.op.theprotocol.cloud:31343", "cloud_operator", "ACTIVE")]


def test_the_lane_is_the_active_frame_row_on_the_parent_host_with_a_federation_port():
    assert parent_lane.pick_origin("eu.theprotocol.cloud", ROWS) == (LANE, None)
    assert parent_lane.pick_origin("asia.theprotocol.cloud", ROWS)[0] == "https://asia.theprotocol.cloud:8443"


@pytest.mark.parametrize("rows,why", [
    ([("https://eu.theprotocol.cloud", "frame", "ACTIVE")], "0 active frame peer rows"),           # the console: 443
    ([("https://eu.theprotocol.cloud:443", "frame", "ACTIVE")], "0 active frame peer rows"),
    ([("https://eu.theprotocol.cloud:8443", "frame", "INACTIVE")], "0 active frame peer rows"),
    ([("https://eu.theprotocol.cloud:8443", "direct_peer", "ACTIVE")], "0 active frame peer rows"),
    ([("http://eu.theprotocol.cloud:8443", "frame", "ACTIVE")], "0 active frame peer rows"),       # never plain http
    ([("https://eu.theprotocol.cloud:8443", "frame", "ACTIVE"),
      ("https://eu.theprotocol.cloud:28443/x", "frame", "ACTIVE")], "2 active frame peer rows"),   # ambiguous: none
])
def test_no_lane_when_the_rows_do_not_name_exactly_one(rows, why):
    origin, said = parent_lane.pick_origin("eu.theprotocol.cloud", rows)
    assert origin is None and said.startswith(why), said


def test_no_host_no_lane(monkeypatch):
    for var in ("CENTRAL_REGISTRY_URL", "MAINFRAME_PROXY_URL", "MAINFRAME_PUBLIC_URL"):
        monkeypatch.delenv(var, raising=False)
    assert parent_lane.configured_parent_host() is None
    assert parent_lane.pick_origin(None, ROWS)[0] is None
    monkeypatch.setenv("CENTRAL_REGISTRY_URL", "https://EU.theprotocol.cloud/")
    assert parent_lane.configured_parent_host() == "eu.theprotocol.cloud"


def test_the_cached_lane_is_for_the_configured_host_only(monkeypatch):
    monkeypatch.setenv("CENTRAL_REGISTRY_URL", "https://eu.theprotocol.cloud")
    parent_lane._state.update(host="eu.theprotocol.cloud", origin=LANE)
    assert parent_lane.cached_origin() == LANE
    monkeypatch.setenv("CENTRAL_REGISTRY_URL", "https://asia.theprotocol.cloud")
    assert parent_lane.cached_origin() is None


# ── which 404 means "the parent does not serve the alias yet" ──────────────────────────────────────────────────────

def test_route_missing_reads_only_the_unknown_route_answer():
    assert parent_lane.route_missing(404, NOT_FOUND)
    assert parent_lane.route_missing(404, '{"error":"Only federation endpoints are served via mTLS proxy"}\n')
    assert not parent_lane.route_missing(404, OWN_404), "a route's own 404 is an answer, passed on"
    assert not parent_lane.route_missing(401, NOT_FOUND)
    assert not parent_lane.route_missing(404, "<html>not json</html>")


# ── the guard ──────────────────────────────────────────────────────────────────────────────────────────────────────

def _vouched(marker=MARKER, verdict="SUCCESS"):
    return {"X-SSL-Client-Cert": "-----BEGIN%20CERTIFICATE-----", "X-SSL-Client-Verify": verdict,
            mtls_auth.PROXY_MARKER_HEADER: marker}


def _app():
    from agentvault_registry.core.mainframe_gate import require_mainframe_only
    from agentvault_registry.database import get_db
    from agentvault_registry.routers import agent_mtls, cloud_operators
    app = FastAPI()
    app.include_router(cloud_operators.federation_router)
    app.include_router(agent_mtls.federation_router)

    async def _no_db():
        yield None

    async def _mainframe():
        return None
    app.dependency_overrides[get_db] = _no_db
    app.dependency_overrides[require_mainframe_only] = _mainframe
    return app


def test_the_aliases_exist_with_the_guard_on_every_one():
    from agentvault_registry.routers import agent_mtls, cloud_operators
    seen = {}
    for r in list(cloud_operators.federation_router.routes) + list(agent_mtls.federation_router.routes):
        deps = {d.call for d in r.dependant.dependencies}
        seen[r.path] = (sorted(r.methods), mtls_auth.require_vouched_peer_cert in deps)
    assert seen == {
        "/api/v1/federation/operator-self/restart": (["POST"], True),
        "/api/v1/federation/operator-self/logs": (["GET"], True),
        "/api/v1/federation/ironhand/register-agent-proxy": (["POST"], True),
        "/api/v1/federation/ironhand/mint-agent-proxy": (["POST"], True),
        "/api/v1/federation/ironhand/delete-agent-proxy": (["POST"], True),
    }, seen
    assert cloud_operators.federation_router.routes[0].endpoint is cloud_operators.cloud_operator_self_restart


def test_without_a_vouched_certificate_the_alias_answers_401_and_runs_nothing(monkeypatch):
    monkeypatch.setenv("REGISTRY_PROXY_TRUST_SECRET", MARKER)
    c = TestClient(_app())
    for headers in ({}, {"X-Federation-License": "tp_fed_x"}, _vouched(marker="wrong" * 10),
                    _vouched(verdict="FAILED:certificate unknown")):
        r = c.get("/api/v1/federation/operator-self/logs", params={"tail": 10}, headers=headers)
        assert r.status_code == 401 and mtls_auth.OPERATOR_LANE_REFUSAL in r.text, (headers, r.text)
    r = c.post("/api/v1/federation/ironhand/mint-agent-proxy", json={"agent_did": "did:theprotocol:x"})
    assert r.status_code == 401 and mtls_auth.OPERATOR_LANE_REFUSAL in r.text


def test_through_the_terminator_the_handler_runs_and_keeps_its_own_licence_check(monkeypatch):
    monkeypatch.setenv("REGISTRY_PROXY_TRUST_SECRET", MARKER)
    r = TestClient(_app()).get("/api/v1/federation/operator-self/logs", params={"tail": 10}, headers=_vouched())
    assert r.status_code == 401 and "X-Federation-License header required" in r.text, r.text


def test_without_a_usable_marker_on_the_frame_the_lane_stays_closed(monkeypatch):
    monkeypatch.delenv("REGISTRY_PROXY_TRUST_SECRET", raising=False)
    r = TestClient(_app()).get("/api/v1/federation/operator-self/logs", params={"tail": 10}, headers=_vouched())
    assert r.status_code == 401 and mtls_auth.OPERATOR_LANE_REFUSAL in r.text


# ── the operator side: the lane first, the console only where the lane cannot answer ───────────────────────────────

def _route(monkeypatch, module, lane_answer, client_attr="AsyncClient"):
    """Every request either module makes goes to a fake transport: the lane answers `lane_answer` (a status and body,
    or an exception), the console answers 200. Returns the list of URLs called."""
    calls = []

    def handler(request: httpx.Request):
        url = str(request.url)
        calls.append(url)
        if url.startswith(LANE):
            if isinstance(lane_answer, Exception):
                raise lane_answer
            status, body = lane_answer
            return httpx.Response(status, text=body)
        return httpx.Response(200, json={"via": "console"})

    real = _REAL_CLIENTS[client_attr]

    def factory(*a, **kw):
        kw.pop("verify", None)
        kw.pop("transport", None)
        return real(*a, transport=(httpx.MockTransport(handler)), **kw)
    monkeypatch.setattr(module.httpx, client_attr, factory)
    return calls


def _portal(monkeypatch, lane_answer, origin=LANE):
    from agentvault_registry.routers import operator_portal_actions as opa

    async def _resolve(db):
        return origin
    monkeypatch.setattr(parent_lane, "resolve_origin", _resolve)
    monkeypatch.setattr(parent_lane, "client_verify", lambda url: True)
    monkeypatch.setenv("CENTRAL_REGISTRY_URL", "https://console.example.invalid")
    monkeypatch.setattr(opa, "_resolve_mainframe_url", lambda: "https://console.example.invalid")
    calls = _route(monkeypatch, opa, lane_answer)
    r, lane = asyncio.run(opa._call_parent(None, "POST", "/api/v1/admin/cloud-operators/self-restart",
                                           "/api/v1/federation/operator-self/restart", "tp_fed_x",
                                           json_body={"service": "registry"}))
    return r, lane, calls


def test_the_lane_answers_and_the_console_is_never_asked(monkeypatch):
    r, lane, calls = _portal(monkeypatch, (200, '{"status":"restarted"}'))
    assert (r.status_code, lane) == (200, "federation lane")
    assert calls == [LANE + "/api/v1/federation/operator-self/restart"]


@pytest.mark.parametrize("answer", [(401, '{"detail":"X-Federation-License header required"}'),
                                    (403, '{"detail":"Invalid or revoked federation license"}'),
                                    (404, OWN_404), (500, '{"detail":"Restart failed"}')])
def test_a_lane_that_answered_is_never_retried_on_the_console(monkeypatch, answer):
    r, lane, calls = _portal(monkeypatch, answer)
    assert lane == "federation lane" and r.status_code == answer[0] and len(calls) == 1, calls


@pytest.mark.parametrize("answer", [(404, NOT_FOUND), httpx.ConnectError("refused")])
def test_an_older_parent_or_an_unreachable_lane_falls_back_to_the_console(monkeypatch, answer):
    r, lane, calls = _portal(monkeypatch, answer)
    assert lane == "console" and calls[-1] == "https://console.example.invalid/api/v1/admin/cloud-operators/self-restart"


def test_no_lane_known_means_the_console_alone(monkeypatch):
    r, lane, calls = _portal(monkeypatch, (200, "{}"), origin=None)
    assert lane == "console" and len(calls) == 1


def test_the_ironhand_proxy_takes_the_lane_and_falls_back_the_same_way(monkeypatch):
    from agentvault_registry.services import agent_spire
    monkeypatch.setenv("CENTRAL_REGISTRY_URL", "https://console.example.invalid")
    monkeypatch.setattr(parent_lane, "cached_origin", lambda: LANE)
    monkeypatch.setattr(parent_lane, "client_verify", lambda url: True)
    calls = _route(monkeypatch, agent_spire, (200, '{"spiffe_id":"spiffe://x/agent/y"}'), client_attr="Client")
    assert agent_spire._proxy_post("register-agent-proxy", {"agent_did": "did:theprotocol:x"}).status_code == 200
    assert calls == [LANE + "/api/v1/federation/ironhand/register-agent-proxy"]
    calls = _route(monkeypatch, agent_spire, (404, NOT_FOUND), client_attr="Client")
    agent_spire._proxy_post("delete-agent-proxy", {"agent_did": "did:theprotocol:x"})
    assert calls[-1] == "https://console.example.invalid/api/v1/admin/ironhand/delete-agent-proxy", calls


# ── how long an answer stands (agentvault2-56, 2026-10-22) ─────────────────────────────────────────────────────────
# The provisioner writes a new operator's parent `frame` row about 20 s after the operator boots, so every worker's
# first answer is "no lane". It stood REFRESH_SECONDS (300 s): the nightly pair's self-logs row, four minutes after its
# operators booted, met the console's 401 every night. RED on a662f7d4 (V0631): the second read below still answers
# None, and the refresher sleeps 300 s after a None.

class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _PeerTable:
    """A session whose peer table the test fills; counts the reads."""

    def __init__(self, rows=()):
        self.rows = list(rows)
        self.reads = 0

    async def execute(self, stmt):
        self.reads += 1
        return _Rows(self.rows)


@pytest.fixture
def clock(monkeypatch):
    import types
    now = {"t": 1000.0}
    monkeypatch.setattr(parent_lane, "time", types.SimpleNamespace(monotonic=lambda: now["t"]))
    monkeypatch.setenv("CENTRAL_REGISTRY_URL", "https://eu.theprotocol.cloud")
    for var in ("MAINFRAME_PROXY_URL", "MAINFRAME_PUBLIC_URL"):
        monkeypatch.delenv(var, raising=False)
    return now


def test_a_lane_not_known_yet_is_asked_for_again_soon(clock):
    db = _PeerTable()                                   # the operator booted: its parent row is not written yet
    assert asyncio.run(parent_lane.resolve_origin(db)) is None
    db.rows = [(LANE, "frame", "ACTIVE")]               # the provisioner writes it ~20 s later
    clock["t"] += 5
    assert asyncio.run(parent_lane.resolve_origin(db)) is None and db.reads == 1, "inside RETRY_SECONDS: the kept None"
    clock["t"] += parent_lane.RETRY_SECONDS
    assert asyncio.run(parent_lane.resolve_origin(db)) == LANE, "after RETRY_SECONDS the row is read again"
    assert parent_lane.RETRY_SECONDS <= 30 < parent_lane.REFRESH_SECONDS


def test_a_found_lane_stands_refresh_seconds(clock):
    db = _PeerTable([(LANE, "frame", "ACTIVE")])
    assert asyncio.run(parent_lane.resolve_origin(db)) == LANE
    clock["t"] += parent_lane.RETRY_SECONDS + 1
    assert asyncio.run(parent_lane.resolve_origin(db)) == LANE and db.reads == 1, "a found lane is not re-read early"
    db.rows = []
    clock["t"] += parent_lane.REFRESH_SECONDS
    assert asyncio.run(parent_lane.resolve_origin(db)) is None and db.reads == 2


def test_the_refresher_comes_back_soon_while_no_lane_is_known(clock, monkeypatch):
    import contextlib
    import types
    from agentvault_registry import database
    db = _PeerTable()
    slept = []

    @contextlib.asynccontextmanager
    async def _ctx():
        yield db

    async def _sleep(seconds):
        slept.append(seconds)
        db.rows = [(LANE, "frame", "ACTIVE")]          # the row arrives while the refresher waits
        if len(slept) == 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(database, "get_db_context", _ctx)
    monkeypatch.setattr(parent_lane, "asyncio", types.SimpleNamespace(sleep=_sleep))
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(parent_lane.refresher())
    assert slept == [parent_lane.RETRY_SECONDS, parent_lane.REFRESH_SECONDS], slept
    assert parent_lane.cached_origin() == LANE
