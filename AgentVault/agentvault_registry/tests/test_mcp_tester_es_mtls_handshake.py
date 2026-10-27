"""The emission-integrity mtls_handshake check, measured from the target's vantage (2026-09-27, run b487126bc7274966).

The console driving a sweep (EU) cannot verify a sandbox gateway (another trust domain) and has none configured, so the
check read NOT MEASURED on every run. The target owns its gateway and the SVID + bundle that verify it: a new route
answers the handshake from there (taking no address), and the console grades that answer.
"""
import ast
import contextlib
import os
import socket
import types

import pytest
from fastapi import HTTPException

from agentvault_registry.routers import mcp_tester as mt

SRC = os.path.join(os.path.dirname(mt.__file__), "mcp_tester.py")


@pytest.mark.parametrize("result,status", [("tls_ok", "ok"), ("cert_fail", "degraded"), ("unreachable", "warn"),
                                           ("not_applicable", "warn")])
def test_each_target_answer_grades_to_its_state(result, status):
    st, det = mt._grade_target_handshake(200, {"gateway": "https://sbx-alpha-nginx-event-store:8443", "result": result,
                                               "detail": "200" if result == "tls_ok" else "why"})
    assert st == status
    if result == "tls_ok":
        assert "FROM THE TARGET" in det


def test_an_older_target_stays_not_measured():
    """Control: a target whose image predates the route answers 404; that is not a failure."""
    st, det = mt._grade_target_handshake(404, None)
    assert st == "warn" and "NOT MEASURED" in det


def test_an_unreadable_answer_stays_not_measured():
    st, det = mt._grade_target_handshake(500, None)
    assert st == "warn" and "NOT MEASURED" in det


async def test_a_plain_http_store_has_no_gateway(monkeypatch):
    monkeypatch.setenv("EVENT_STORE_URL", "http://sbx-beta-event-store:8200")
    called = []

    async def probe(url, ctx):
        called.append(url)
        return "tls_ok", "200"

    monkeypatch.setattr(mt, "_probe_gateway", probe)
    out = await mt._own_gateway_handshake()
    assert out["result"] == "not_applicable" and called == []


async def test_the_node_probes_its_own_https_gateway_with_its_own_context(monkeypatch):
    monkeypatch.setenv("EVENT_STORE_URL", "https://sbx-alpha-nginx-event-store:8443/")
    ctx = object()
    monkeypatch.setattr(mt, "_build_mtls_probe_ctx", lambda: ctx)
    monkeypatch.setattr(mt, "_svid_on_disk", lambda: True)
    seen = []

    async def probe(url, c):
        seen.append((url, c))
        return "tls_ok", "200"

    monkeypatch.setattr(mt, "_probe_gateway", probe)
    out = await mt._own_gateway_handshake()
    assert out == {"gateway": "https://sbx-alpha-nginx-event-store:8443", "result": "tls_ok", "detail": "200",
                   "presented_client_cert": True}
    assert seen == [("https://sbx-alpha-nginx-event-store:8443", ctx)]


async def test_no_bundle_is_not_applicable(monkeypatch):
    monkeypatch.setenv("EVENT_STORE_URL", "https://sbx-alpha-nginx-event-store:8443")
    monkeypatch.setattr(mt, "_build_mtls_probe_ctx", lambda: None)
    out = await mt._own_gateway_handshake()
    assert out["result"] == "not_applicable"


KEY = "k" * 48   # a synthetic value of a usable shape (>= 32 chars, no placeholder word); never a real key


@pytest.fixture
def own_ok(monkeypatch):
    async def own():
        return {"gateway": "g", "result": "tls_ok", "detail": "200"}

    monkeypatch.setattr(mt, "_own_gateway_handshake", own)


@pytest.mark.parametrize("presented", [None, "", "j" * 48])
async def test_the_route_refuses_a_missing_or_wrong_key(monkeypatch, own_ok, presented):
    """Control, through the REAL key check: nothing, an empty value or a wrong key is refused 401."""
    monkeypatch.setenv("API_TEST_PROXY_INTERNAL_KEY", KEY)
    req = types.SimpleNamespace(headers={"X-Internal-Key": presented} if presented is not None else {})
    with pytest.raises(HTTPException) as exc:
        await mt.es_mtls_handshake(req)
    assert exc.value.status_code == 401


async def test_a_node_holding_no_key_refuses_every_caller(monkeypatch, own_ok):
    monkeypatch.delenv("API_TEST_PROXY_INTERNAL_KEY", raising=False)
    req = types.SimpleNamespace(headers={"X-Internal-Key": KEY})
    with pytest.raises(HTTPException) as exc:
        await mt.es_mtls_handshake(req)
    assert exc.value.status_code == 401


async def test_the_route_answers_the_own_gateway_handshake_with_the_key(monkeypatch, own_ok):
    monkeypatch.setenv("API_TEST_PROXY_INTERNAL_KEY", KEY)
    req = types.SimpleNamespace(headers={"X-Internal-Key": KEY})
    assert (await mt.es_mtls_handshake(req))["result"] == "tls_ok"


def test_a_refused_key_is_named_and_stays_not_measured():
    st, det = mt._grade_target_handshake(401, None)
    assert st == "warn" and "proxy key" in det and "NOT MEASURED" in det


def test_the_check_asks_the_target_when_no_gateway_is_configured():
    """Wiring, on the AST: the stale 'ships none' verdict is gone and the check grades the target's answer."""
    src = open(SRC).read()
    fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.AsyncFunctionDef)
              and n.name == "_compute_emission_integrity")
    body = ast.unparse(fn)
    assert "_grade_target_handshake" in body and "/api/v1/admin/mcp-tester/es-mtls-handshake" in body
    assert "headers=_proxy_headers()" in body and "verify=_es_verify()" in body
    assert "tier ships none" not in body


# ── agentvault2-41's review of 52be7f5e: nginx refuses a client certificate AFTER the handshake ──────────────────────
NGINX_496 = ("<html>\r\n<head><title>400 No required SSL certificate was sent</title></head>\r\n<body>\r\n"
             "<center><h1>400 Bad Request</h1></center>\r\n<center>No required SSL certificate was sent</center>\r\n")
NGINX_495 = ("<html>\r\n<head><title>400 The SSL certificate error</title></head>\r\n<body>\r\n"
             "<center><h1>400 Bad Request</h1></center>\r\n<center>The SSL certificate error</center>\r\n")


@pytest.mark.parametrize("page,sentence", [(NGINX_496, "400 No required SSL certificate was sent"),
                                           (NGINX_495, "400 The SSL certificate error")])
def test_nginx_refusing_the_client_certificate_is_not_a_pass(page, sentence):
    assert mt._classify_http_answer(400, page) == ("client_cert_refused", sentence)


@pytest.mark.parametrize("status,body", [(200, ""), (400, "<html><head><title>400 Bad Request</title></head></html>"),
                                         (404, ""), (502, "")])
def test_any_other_answer_is_a_completed_handshake(status, body):
    """Control: a 400 that names no certificate, and every other status, is still a completed handshake."""
    assert mt._classify_http_answer(status, body) == ("tls_ok", str(status))


@contextlib.asynccontextmanager
async def _local_server(routes):
    """A real HTTP server on loopback (works under --network none): {path: handler}."""
    from aiohttp import web
    app = web.Application()
    for path, handler in routes.items():
        app.router.add_get(path, handler)
    runner = web.AppRunner(app)
    await runner.setup()
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    site = web.SockSite(runner, sock)
    await site.start()
    try:
        yield f"http://127.0.0.1:{sock.getsockname()[1]}"
    finally:
        await runner.cleanup()


async def test_the_real_probe_reads_a_refusal_off_the_wire():
    from aiohttp import web
    answer = {}

    async def health(request):
        return web.Response(status=answer["status"], text=answer["body"], content_type="text/html")

    async with _local_server({"/health": health}) as url:
        answer.update(status=400, body=NGINX_495)
        assert await mt._probe_gateway(url, None) == ("client_cert_refused", "400 The SSL certificate error")
        answer.update(status=200, body="ok")
        assert await mt._probe_gateway(url, None) == ("tls_ok", "200")


def test_a_refused_own_certificate_is_a_break():
    st, det = mt._grade_target_handshake(200, {"gateway": "g", "result": "client_cert_refused",
                                               "detail": "400 The SSL certificate error", "presented_client_cert": True})
    assert st == "degraded" and "REFUSED" in det


def test_a_refusal_with_nothing_presented_is_the_probes_gap():
    """Control: no SVID to present means the refusal says nothing about the gateway."""
    st, det = mt._grade_target_handshake(200, {"gateway": "g", "result": "client_cert_refused",
                                               "detail": "400 No required SSL certificate was sent",
                                               "presented_client_cert": False})
    assert st == "warn" and "NOT MEASURED" in det


@pytest.mark.parametrize("sandbox,svid,expected", [(False, True, "degraded"), (False, False, "warn"),
                                                   (True, True, "warn")])
async def test_the_console_probe_grades_a_refused_certificate(monkeypatch, sandbox, svid, expected):
    """The configured-gateway branch, driven: it uses the shared probe, so a refusal no longer reads ok. From a sandbox
    target's other trust domain it stays the expected isolation (warn), and with no SVID it is the probe's gap."""
    monkeypatch.setattr(mt, "_ES_MTLS_GW_A", "https://gw-a:8443")
    monkeypatch.setattr(mt, "_ES_MTLS_GW_B", "")
    monkeypatch.setattr(mt, "_build_mtls_probe_ctx", lambda: object())

    async def probe(url, ctx):
        return ("client_cert_refused", "400 The SSL certificate error") if url == "https://gw-a:8443" \
            else ("unreachable", "no address")

    monkeypatch.setattr(mt, "_probe_gateway", probe)
    monkeypatch.setattr(mt, "_is_sandbox_target", lambda: sandbox)
    monkeypatch.setattr(mt, "_svid_on_disk", lambda: svid)
    out = await mt._compute_emission_integrity(0.0, {}, {}, [])
    assert out["checks"]["mtls_handshake"]["status"] == expected


@pytest.mark.parametrize("status,payload,expected", [
    (200, {"gateway": "https://t-nginx-event-store:8443", "result": "tls_ok", "detail": "200",
           "presented_client_cert": True}, "ok"),
    (404, None, "warn"),
])
async def test_the_console_asks_the_target_with_the_key(monkeypatch, status, payload, expected):
    """End to end on loopback: with no gateway configured the console asks the TARGET's route, presenting the proxy key,
    and grades what comes back; an older target's 404 stays NOT MEASURED."""
    from aiohttp import web
    seen = []

    async def route(request):
        seen.append(request.headers.get("X-Internal-Key"))
        return web.json_response(payload) if status == 200 else web.Response(status=status)

    monkeypatch.setattr(mt, "_ES_MTLS_GW_A", "")
    monkeypatch.setattr(mt, "_ES_MTLS_GW_B", "")
    monkeypatch.setenv("API_TEST_PROXY_INTERNAL_KEY", KEY)
    async with _local_server({"/api/v1/admin/mcp-tester/es-mtls-handshake": route}) as url:
        monkeypatch.setattr(mt, "API_TEST_TARGET_URL", url)
        out = await mt._compute_emission_integrity(0.0, {}, {}, [])
    assert seen == [KEY]
    check = out["checks"]["mtls_handshake"]
    assert check["status"] == expected, check
    if expected == "warn":
        assert "NOT MEASURED" in check["detail"]
