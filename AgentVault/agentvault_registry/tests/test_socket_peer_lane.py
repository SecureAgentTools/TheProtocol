"""§MTLSHOPS V0379 (2026-09-15): the registry keeps its lanes when it listens on a unix socket.

agentvault2-b5's registry terminator (b2) puts the registry behind a socket. There the ASGI scope carries no client
address: uvicorn reads getpeername(), which is not a (host, port) pair for AF_UNIX. Every door names the caller in
X-Real-IP instead. nginx-registry sets its own $remote_addr for in-frame callers, and nginx-edge passes the host vhost's
value or its own peer. b5 confirmed that nginx-registry forwards X-SSL-Client-* beside X-Registry-Proxy-Auth as
nginx-federation does, and that nginx-edge forwards neither.

  1. (structure, census) no `<x>.client.host` or `.client.port` is read without a test of `<x>.client` around it. On a
     socket that attribute is None, so an unguarded read raises. The tree held five: docker_token_auth x4 and
     security_utils x1.
  2. (behaviour) SocketPeerClientMiddleware gives a socket request the address its door named. It never touches a TCP
     peer, a request with no X-Real-IP, or a value that is not an address, and main.py mounts it outside every other
     middleware.
  3. (behaviour) nothing becomes internal by arriving on the socket. is_internal_request is False with or without the
     door's header, so Mode 2 and the sync trigger's secret lane refuse a socket caller, and a header-less socket request
     is limited under one key. The control swaps in the rule this file exists to prevent ("no address means inside"),
     and both lanes must then open.
  4. (structure) the worker never trusts every forwarder: uvicorn 0.34.3 counts a peer with no address as trusted under
     "*", and then takes the first X-Forwarded-For element, the one the caller wrote.

The lane census that set the scope (sbx-beta-registry:8000, 15:57:41Z to 16:57:41Z): 1,884 requests, 494 internal by
rule, the largest internal caller 4 a minute, X-Federation-Secret 0. So a socket caller gets no limiter exemption.
"""
from __future__ import annotations

import ast
import os
import pathlib

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://ci:ci@localhost:5432/ci")
os.environ.setdefault("API_KEY_SECRET", "ci-dummy-secret-0123456789abcdef")

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from starlette.requests import Request  # noqa: E402

_HERE = pathlib.Path(__file__).resolve()
_CANDIDATES = [
    pathlib.Path(os.environ["SOCKET_LANE_SRC"]) if os.environ.get("SOCKET_LANE_SRC") else None,
    _HERE.parents[1] / "src" / "agentvault_registry",
    pathlib.Path("/w/src/agentvault_registry"),
    pathlib.Path("/app/src/agentvault_registry"),
]
SRC = next(p for p in _CANDIDATES if p is not None and p.is_dir())

DOOR = "172.16.94.12"
PEER = "spiffe://agentvault.com/service/registry-a"
SECRET = "the-real-secret-for-this-test"


# ── 1. the census ─────────────────────────────────────────────────────────────────────────────────────────────────────

def _guarded(node, parents):
    base, cur = ast.unparse(node.value), node
    while cur in parents:
        par = parents[cur]
        if isinstance(par, (ast.IfExp, ast.If, ast.While)) and cur is not par.test and base in ast.unparse(par.test):
            return True
        if isinstance(par, ast.BoolOp) and isinstance(par.op, ast.And) and cur in par.values:
            if any(base in ast.unparse(v) for v in par.values[:par.values.index(cur)]):
                return True
        if isinstance(par, ast.Try) and cur in par.body and any(
                h.type is None or "Exception" in ast.unparse(h.type) or "AttributeError" in ast.unparse(h.type)
                for h in par.handlers):
            return True
        if isinstance(par, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            return False
        cur = par
    return False


def client_address_reads(text, rel):
    """(guarded count, unguarded reads) of `<x>.client.host` and `<x>.client.port` in one module."""
    tree = ast.parse(text)
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    guarded, unguarded = 0, []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Attribute) and node.attr in ("host", "port")
                and isinstance(node.value, ast.Attribute) and node.value.attr == "client"):
            if _guarded(node, parents):
                guarded += 1
            else:
                unguarded.append(f"{rel}:{node.lineno} {ast.unparse(node)}")
    return guarded, unguarded


def test_no_client_address_is_read_without_a_test_of_the_client():
    guarded, unguarded, modules = 0, [], 0
    for path in sorted(SRC.rglob("*.py")):
        if "tests" in path.parts:
            continue
        try:
            g, u = client_address_reads(path.read_text(), path.relative_to(SRC).as_posix())
        except SyntaxError:
            continue
        modules, guarded = modules + 1, guarded + g
        unguarded += u
    assert modules >= 200 and guarded >= 10, f"{modules} modules, {guarded} guarded reads: the census is not looking at the tree"
    assert not unguarded, "a socket request has no client, so these raise:\n" + "\n".join(unguarded)


def test_the_census_refuses_and_accepts_as_named():
    refused = {
        "a bare read": "def f(request):\n    return request.client.host\n",
        "inside the handler, not the body": "def f(r):\n    try:\n        pass\n    except Exception:\n        return r.client.host\n",
    }
    accepted = {
        "a conditional expression": "def f(request):\n    return request.client.host if request.client else None\n",
        "an and-chain": "def f(request):\n    return request.client and request.client.host\n",
        "an if block": "def f(request):\n    if request.client:\n        return request.client.port\n",
        "a try around it": "def f(r):\n    try:\n        return r.client.host\n    except AttributeError:\n        return None\n",
        "getattr": "def f(request):\n    return getattr(request.client, 'host', None)\n",
    }
    for label, src in refused.items():
        assert len(client_address_reads(src, "x.py")[1]) == 1, label
    for label, src in accepted.items():
        assert client_address_reads(src, "x.py")[1] == [], label


# ── 2. the middleware ─────────────────────────────────────────────────────────────────────────────────────────────────

def _scope(client=None, typ="http", **headers):
    return {"type": typ, "path": "/api/v1/federation/sync/trigger", "method": "POST", "query_string": b"",
            "headers": [(k.replace("_", "-").lower().encode(), v.encode()) for k, v in headers.items()],
            "client": client}


async def _client_after_middleware(scope):
    from agentvault_registry.core.client_ip import SocketPeerClientMiddleware
    seen = {}

    async def app(s, receive, send):
        seen["client"] = s.get("client")

    await SocketPeerClientMiddleware(app)(scope, None, None)
    return seen["client"]


@pytest.mark.asyncio
async def test_a_socket_request_takes_the_address_its_door_named():
    assert await _client_after_middleware(_scope(X_Real_IP=DOOR)) == (DOOR, 0)
    assert await _client_after_middleware(_scope(typ="websocket", X_Real_IP="2001:db8::7")) == ("2001:db8::7", 0)


@pytest.mark.asyncio
async def test_the_socket_middleware_touches_nothing_else():
    assert await _client_after_middleware(_scope(client=("172.16.0.5", 5555), X_Real_IP="8.8.8.8")) == ("172.16.0.5", 5555)
    assert await _client_after_middleware(_scope()) is None
    assert await _client_after_middleware(_scope(X_Real_IP="not-an-address")) is None
    assert await _client_after_middleware(_scope(X_Real_IP=f"{DOOR}, 8.8.8.8")) is None
    assert await _client_after_middleware({"type": "lifespan"}) is None


def test_main_mounts_the_socket_middleware_outside_every_other():
    tree = ast.parse((SRC / "main.py").read_text())
    mounts = sorted(
        (node.lineno, ast.unparse(node)) for node in ast.walk(tree)
        if isinstance(node, ast.Call) and (ast.unparse(node.func) in ("app.add_middleware", "app.middleware")
                                           or ast.unparse(node.func).endswith(".instrument")))
    assert mounts and "SocketPeerClientMiddleware" in mounts[-1][1], mounts[-3:]


# ── 3. the lanes ──────────────────────────────────────────────────────────────────────────────────────────────────────

def _request(client=None, **headers):
    return Request(_scope(client=client, **headers))


def test_nothing_is_internal_on_a_socket():
    from agentvault_registry.core import client_ip
    from agentvault_registry.middleware.rate_limiter import principal_rate_key
    bare = _request()
    assert client_ip.is_internal_request(bare) is False
    assert client_ip.effective_client_ip(bare) is None
    assert principal_rate_key(bare) == "ip:unknown"
    door = _request(client=(DOOR, 0), X_Real_IP=DOOR)   # what the middleware hands on
    assert client_ip.is_internal_request(door) is False
    assert principal_rate_key(door) == f"ip:{DOOR}"


async def _no_cert(_request):
    raise HTTPException(status_code=401, detail="no client certificate")


async def _nothing(*_a, **_k):
    return None


@pytest.fixture
def lanes(monkeypatch):
    import agentvault_registry.core.mtls_auth as mtls
    from agentvault_registry.core import federation_auth
    from agentvault_registry.routers import federation_sync as fs
    for module in (mtls, federation_auth, fs):
        monkeypatch.setattr(module, "TRUSTED_SPIFFE_DOMAINS", ["agentvault.com"], raising=False)
    for module in (federation_auth, fs):
        monkeypatch.setattr(module, "get_client_spiffe_id", _no_cert)
        monkeypatch.setattr(module, "FEDERATION_INTERNAL_SECRET", SECRET)
    monkeypatch.setattr(federation_auth, "_verify_license_key", _nothing)
    monkeypatch.setattr(federation_auth, "_assert_peer_spiffe_binding", _nothing)
    monkeypatch.setattr(federation_auth, "_assert_operator_license_not_revoked", _nothing)
    return monkeypatch, federation_auth, fs


def _secret_caller(client=None, **extra):
    return _request(client=client, X_Federation_Secret=SECRET, X_Federation_SPIFFE_ID=PEER, **extra)


async def _opens(federation_auth, fs, req):
    """(Mode 2 opened, the sync trigger's secret lane opened) for one request."""
    async def one(call):
        try:
            return await call() == PEER
        except HTTPException:
            return False
    return (await one(lambda: federation_auth.get_federation_identity(req, None, None)),
            await one(lambda: fs.require_sync_trigger_identity(req, db=None, authorization=None)))


@pytest.mark.asyncio
async def test_both_secret_lanes_still_open_for_an_internal_tcp_peer(lanes):
    _, federation_auth, fs = lanes
    assert await _opens(federation_auth, fs, _secret_caller(client=("172.16.0.9", 40000))) == (True, True)


@pytest.mark.asyncio
async def test_a_socket_caller_opens_neither_secret_lane(lanes):
    _, federation_auth, fs = lanes
    assert await _opens(federation_auth, fs, _secret_caller()) == (False, False)
    assert await _opens(federation_auth, fs, _secret_caller(client=(DOOR, 0), X_Real_IP=DOOR)) == (False, False)


@pytest.mark.asyncio
async def test_control_the_rule_this_file_prevents_would_open_both(lanes):
    monkeypatch, federation_auth, fs = lanes
    from agentvault_registry.core import client_ip

    def no_address_means_inside(request):
        return request.client is None or client_ip.is_internal_request(request)

    monkeypatch.setattr(federation_auth, "is_internal_request", no_address_means_inside)
    monkeypatch.setattr(fs, "is_internal_request", no_address_means_inside)
    assert await _opens(federation_auth, fs, _secret_caller()) == (True, True)


# ── 4. the worker ─────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_worker_never_trusts_every_forwarder():
    from uvicorn.middleware.proxy_headers import _TrustedHosts
    from agentvault_registry import gunicorn_worker as gw
    assert "*" not in gw.DEFAULT_FORWARDED_ALLOW_IPS
    assert gw.RegistryWorker.CONFIG_KWARGS["forwarded_allow_ips"] == gw.FORWARDED_ALLOW_IPS
    assert None not in _TrustedHosts(gw.DEFAULT_FORWARDED_ALLOW_IPS), "a socket peer must not count as a trusted forwarder"
    assert None in _TrustedHosts("*"), "the control: '*' trusts a peer with no address"
