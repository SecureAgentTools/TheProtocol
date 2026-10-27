"""§LEDGERGATE (V0597, 2026-10-11): the TEG's ledger refusal reaches the WIRE whole, on the send paths a person meets.

Read on V0596 (be4ed526) after it was built: the passthrough raised the right HTTPException, and its own test checked that
object, never the response. Through the registry's error handler (register_error_handlers):
  - a Retry-After the route raised lived only in the body's error.context.headers, never on the response;
  - /teg/send (the console's Pocket and bridge sends) wrapped the inner refusal in its method context, a dict the handler
    JSON-dumps, so the console read the sentence with the wrapper's closing quote and brace after it;
  - the cross-registry send retried the refusal once and answered 503 "Cross-registry transfer service unavailable"; the
    async lock answered "TEG lock-async failure". Neither says that nothing moved.
These tests drive the real handler and the real /teg/send route (its two collaborators replaced: the route decision and
the self-call). The cross-registry paths sit behind the federation's whole resolution, so they are pinned at the source
here and measured live by the store-outage drill on the sandbox.

RED control: on be4ed526 the Retry-After tests and the /teg/send refusal tests fail (no header; the detail is the
wrapper's JSON), and both cross-registry pins fail (no ledger_refusal on either path).

Then the store-outage drill on sbx-alpha (15:35Z, enforce, fes-20261011T153514Z-3cbc) found the path that runs: with
TEG_BULK_PROXY=true (every frame and operator) /teg/transfer goes through the in-process bulk proxy, which turned the
TEG's 503 into a plain ValueError and the route into a 400 "Transfer failed via bulk: TEG bulk endpoint returned 503:
{...}". The bulk tests below drive the proxy itself; red on 5d35d46a (no LedgerRefusedError, no refusal_from_text).
"""
from __future__ import annotations

import ast
import asyncio
import inspect
import json
import textwrap
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.exceptions import HTTPException as StarletteHTTPException

from agentvault_registry.database import get_db
from agentvault_registry.errors import register_error_handlers
from agentvault_registry.routers import teg_integration, teg_send
from agentvault_registry.routers.utils import get_current_agent
from agentvault_registry.services import ledger_unavailable as lu

SENTENCE_DETAIL = f"{lu.MARKER} {lu.SENTENCE}"


def _raising(exc):
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/x")
    async def _x():
        raise exc

    return TestClient(app, raise_server_exceptions=False)


def test_a_retry_after_the_route_raised_is_on_the_wire():
    r = _raising(HTTPException(503, detail=SENTENCE_DETAIL, headers={"Retry-After": "12"})).get("/x")
    assert r.status_code == 503 and r.headers.get("retry-after") == "12"
    body = r.json()
    assert body["detail"] == SENTENCE_DETAIL
    assert body["error"]["context"]["headers"] == {"Retry-After": "12"}   # the body keeps it as before


def test_a_starlette_exception_keeps_its_retry_after_too():
    r = _raising(StarletteHTTPException(503, detail="busy", headers={"retry-after": "7"})).get("/x")
    assert r.status_code == 503 and r.headers.get("retry-after") == "7"


@pytest.mark.parametrize("exc_cls", [HTTPException, StarletteHTTPException])
def test_a_401s_challenge_is_on_the_wire(exc_cls):
    # §FESUITE (V0600): a 401 names its challenge on the wire (RFC 9110 15.5.2); until V0600 it reached only the body.
    # RED control: on 82364293 www-authenticate is absent from the response.
    r = _raising(exc_cls(401, detail="no", headers={"WWW-Authenticate": 'Bearer error="invalid_token"'})).get("/x")
    assert r.status_code == 401 and r.headers.get("www-authenticate") == 'Bearer error="invalid_token"'
    assert r.json()["error"]["context"]["headers"] == {"WWW-Authenticate": 'Bearer error="invalid_token"'}


def test_only_the_named_headers_are_lifted_onto_the_wire():
    # the console reads X-Verification-Required from the body's context (stores/auth.ts); it stays there, and only there
    r = _raising(HTTPException(403, detail="verify first", headers={"X-Verification-Required": "true"})).get("/x")
    assert r.status_code == 403 and "x-verification-required" not in r.headers
    assert r.json()["error"]["context"]["headers"] == {"X-Verification-Required": "true"}


def test_the_registrys_own_bearer_scheme_names_its_challenge_on_the_wire():
    # the real dependency (security.oauth2_scheme_required, FastAPI's OAuth2PasswordBearer) with no token, through the
    # registry's handlers: the 401 a client meets first
    from fastapi import Depends
    from agentvault_registry import security

    app = FastAPI()
    register_error_handlers(app)

    @app.get("/me")
    async def _me(token: str = Depends(security.oauth2_scheme_required)):
        return {"token": token}

    r = TestClient(app, raise_server_exceptions=False).get("/me")
    assert r.status_code == 401 and r.headers.get("www-authenticate") == "Bearer"


class _SelfCall:
    """The smart send's client to the registry itself: answers every POST with one response, and counts."""

    is_closed = False

    def __init__(self, resp):
        self.resp, self.calls = resp, []

    async def post(self, url, json=None, headers=None):
        self.calls.append(url)
        return self.resp


def _inner(status, body, headers=None):
    return httpx.Response(status, content=json.dumps(body).encode(),
                          headers={"content-type": "application/problem+json", **(headers or {})})


def _registry_refusal_body(retry_after=None):
    """What the registry's own /teg/transfer answers when the TEG's gate refused (V0596's dual-emit body)."""
    err = {"detail": SENTENCE_DETAIL, "type": "service_unavailable"}
    if retry_after:
        err["context"] = {"headers": {"Retry-After": retry_after}}
    return {"error": err, "type": "https://docs.theprotocol.cloud/errors/service_unavailable",
            "title": "Service Unavailable", "status": 503, "detail": SENTENCE_DETAIL, "instance": "/api/v1/teg/transfer"}


def _send(monkeypatch, inner):
    selfcall = _SelfCall(inner)
    monkeypatch.setattr(teg_send, "_get_send_client", lambda: selfcall)

    async def _route(db, **kw):
        return SimpleNamespace(method="local", endpoint="/api/v1/teg/transfer",
                               body={"receiver_did": kw["receiver_did"], "amount": kw["amount"]},
                               target_registry="self", currency_sent="SBXA", currency_received="SBXA",
                               currency_source="local", notes=[], refusal_detail=None)

    monkeypatch.setattr(teg_send, "derive_route", _route)
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(teg_send.router)

    async def _db():
        yield None

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_agent] = lambda: SimpleNamespace(id=1, did="did:theprotocol:sender-0001")
    client = TestClient(app, raise_server_exceptions=False)
    r = client.post("/api/v1/teg/send", json={"receiver_did": "did:theprotocol:receiver-0002", "amount": "1.5"},
                    headers={"Authorization": "Bearer agent-jwt", "Idempotency-Key": "k-1"})
    return r, selfcall


def test_the_smart_send_passes_the_refusal_on_as_it_came(monkeypatch):
    r, selfcall = _send(monkeypatch, _inner(503, _registry_refusal_body(), {"Retry-After": "20"}))
    assert len(selfcall.calls) == 1 and selfcall.calls[0].endswith("/api/v1/teg/transfer")
    assert r.status_code == 503, r.text[:300]
    assert r.json()["detail"] == SENTENCE_DETAIL            # the sentence, not the wrapper's JSON
    assert r.headers.get("retry-after") == "20"


def test_the_smart_send_reads_retry_after_from_the_registrys_own_body(monkeypatch):
    # an inner answer from a registry whose handler kept the header in the body only (V0596)
    r, _ = _send(monkeypatch, _inner(503, _registry_refusal_body(retry_after="45")))
    assert r.status_code == 503 and r.json()["detail"] == SENTENCE_DETAIL
    assert r.headers.get("retry-after") == "45"


def test_another_inner_503_keeps_the_method_context(monkeypatch):
    # not the gate's refusal: the old answer, wrapped, with no claim that nothing moved
    r, _ = _send(monkeypatch, _inner(503, {"detail": "upstream timeout"}))
    assert r.status_code == 503
    wrapped = json.loads(r.json()["detail"])
    assert wrapped == {"smart_send_method": "local", "via": "/api/v1/teg/transfer", "inner": "upstream timeout"}
    assert "retry-after" not in r.headers


def _function(fn):
    return ast.parse(textwrap.dedent(inspect.getsource(fn)))


def _calls(node, name):
    return [n for n in ast.walk(node) if isinstance(n, ast.Call) and getattr(n.func, "id", None) == name]


def test_the_cross_registry_send_does_not_retry_the_refusal_and_passes_it_on():
    tree = _function(teg_integration._cross_registry_transfer_run)  # §REPATLANE-5: the route's work, under its attempt
    src = ast.unparse(tree)
    calls = _calls(tree, "ledger_refusal")
    assert len(calls) >= 2, "the retry decision and the failure answer both ask"
    # the retry loop breaks on it ...
    assert "if response.status_code < 500 or ledger_refusal(response) is not None:" in src
    # ... and the failure branch raises it before the generic 503
    assert src.index("_refusal = ledger_refusal(response)") < src.index("'Cross-registry transfer service unavailable'")


def test_the_async_lock_passes_the_refusal_on():
    src = ast.unparse(_function(teg_integration._cross_registry_transfer_async))
    assert src.index("_refusal = ledger_refusal(lock_resp)") < src.index("'TEG lock-async failure'")


def test_ledger_refusal_names_the_module_function():
    # the route module imports the passthrough itself (not a copy that could drift from services/ledger_unavailable)
    assert teg_integration.ledger_refusal is lu.ledger_refusal


@pytest.mark.parametrize("hdrs", [{"Retry-After": "33"}, {"retry-after": "33"}])
def test_retry_after_from_the_registrys_dual_emit_body(hdrs):
    resp = _inner(503, {"detail": SENTENCE_DETAIL, "error": {"context": {"headers": hdrs}}})
    assert lu.ledger_refusal(resp).headers == {"Retry-After": "33"}


class _TegClient:
    """The TEG's shared client, answering the bulk endpoint with one response, and counting."""

    is_closed = False

    def __init__(self, resp):
        self.resp, self.calls = resp, []

    async def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append(url)
        return self.resp


def _tegs_refusal(retry_after="20"):
    body = {"detail": SENTENCE_DETAIL, "type": "https://docs.theprotocol.cloud/errors/ledger-unavailable",
            "title": "Service Unavailable", "status": 503, "code": "ledger_unavailable",
            "context": {"ledger": {"state": "unhealthy"}, "retry_after_s": 30}}
    return _inner(503, body, {"Retry-After": retry_after})


async def _bulk(monkeypatch, resp, n):
    client = _TegClient(resp)
    monkeypatch.setattr(teg_integration, "_get_teg_client", lambda: client)
    proxy = teg_integration.TEGBulkProxy(max_batch_size=n, flush_interval_ms=5)   # the n-th submit flushes the batch
    results = await asyncio.gather(*[
        proxy.submit(sender_did=f"did:theprotocol:sender-{i}", receiver_did="did:theprotocol:receiver-0002", amount="1",
                     fee_amount="0", message=None, teg_token="agent-jwt") for i in range(n)], return_exceptions=True)
    return results, client


async def test_the_bulk_proxy_hands_every_transfer_of_a_refused_batch_the_refusal(monkeypatch):
    results, client = await _bulk(monkeypatch, _tegs_refusal("20"), 2)
    assert len(client.calls) == 1 and client.calls[0].endswith("/token/transfer/bulk")
    assert len(results) == 2
    for r in results:
        assert isinstance(r, lu.LedgerRefusedError) and isinstance(r, ValueError)   # every caller still catches it
        assert r.refusal.status_code == 503 and r.refusal.detail == SENTENCE_DETAIL
        assert r.refusal.headers == {"Retry-After": "20"}


async def test_another_bulk_failure_stays_a_plain_value_error(monkeypatch):
    results, _ = await _bulk(monkeypatch, _inner(503, {"detail": "upstream timeout"}), 1)
    assert type(results[0]) is ValueError and "TEG bulk endpoint returned 503" in str(results[0])


def test_a_refusal_that_reached_the_registry_as_text():
    # what V0596's bulk path answered, live on sbx-alpha (fes-20261011T153514Z-3cbc)
    seen = ('Transfer failed via bulk: TEG bulk endpoint returned 503: {"detail":"ledger_unavailable: The ledger cannot '
            'record this right now. Nothing was moved. Try again shortly.","type":"https://docs.theprotocol.cloud/errors/le')
    exc = lu.refusal_from_text(seen)
    assert exc.status_code == 503 and exc.detail == SENTENCE_DETAIL and exc.headers == {"Retry-After": "30"}
    assert lu.refusal_from_text("TEG bulk endpoint returned 503: upstream timeout") is None
    assert lu.refusal_from_text(None) is None


def test_the_transfer_route_raises_the_refusal_from_either_backend():
    src = ast.unparse(_function(teg_integration._teg_transfer_run))  # §REPATLANE-5: the route's work, under its attempt
    # the translation asks for the refusal first, from the exception itself; both backends hand it the exception
    assert src.index("if isinstance(_err, LedgerRefusedError):") < src.index("if 'insufficient' in _msg.lower()")
    assert src.index("_refusal = refusal_from_text(_msg)") < src.index("if 'insufficient' in _msg.lower()")
    assert "raise _translate_bulk_value_error(_bulk_err, 'bulk')" in src
    assert "raise _translate_bulk_value_error(_bulk_err, 'stream')" in src


# §LEDGERGATE (V0605): an inner answer that is not the TEG's refusal keeps its Retry-After through the smart send (drill 3
# on V0603: a route refused before conversion answered 503 "Your payment came back to you. Try again shortly." with
# Retry-After 30, and /teg/send's caller got the 503 with no header)
CAME_BACK = lu.ROUTE_CAME_BACK


def test_the_routes_came_back_refusal_passes_on_as_it_came(monkeypatch):
    # the payment came back: the caller gets the sentence alone and its Retry-After, as the TEG's own refusal arrives
    r, _ = _send(monkeypatch, _inner(503, {"detail": CAME_BACK}, {"Retry-After": "30"}))
    assert r.status_code == 503, r.text[:300]
    assert r.json()["detail"] == CAME_BACK
    assert r.headers.get("retry-after") == "30"


def test_the_came_back_refusal_from_a_dual_emit_body_keeps_its_retry_after(monkeypatch):
    body = {"error": {"detail": CAME_BACK, "type": "service_unavailable", "context": {"headers": {"Retry-After": "45"}}},
            "status": 503, "detail": CAME_BACK}
    r, _ = _send(monkeypatch, _inner(503, body))
    assert r.status_code == 503 and r.json()["detail"] == CAME_BACK and r.headers.get("retry-after") == "45"


def test_another_inner_503_keeps_its_retry_after_and_the_method_context(monkeypatch):
    r, _ = _send(monkeypatch, _inner(503, {"detail": "upstream busy"}, {"Retry-After": "12"}))
    assert r.status_code == 503
    assert json.loads(r.json()["detail"]) == {"smart_send_method": "local", "via": "/api/v1/teg/transfer",
                                              "inner": "upstream busy"}
    assert r.headers.get("retry-after") == "12"


def test_an_inner_retry_after_kept_only_in_the_dual_emit_body_goes_on_the_wire(monkeypatch):
    body = {"error": {"detail": "upstream busy", "type": "service_unavailable",
                      "context": {"headers": {"Retry-After": "45"}}}, "status": 503, "detail": "upstream busy"}
    r, _ = _send(monkeypatch, _inner(503, body))
    assert r.status_code == 503 and r.headers.get("retry-after") == "45"
    assert json.loads(r.json()["detail"])["inner"] == "upstream busy"


@pytest.mark.parametrize("detail", [CAME_BACK + " (and more)", "Your payment came back to you.", CAME_BACK.upper()])
def test_only_the_whole_came_back_sentence_passes_on_whole(monkeypatch, detail):
    r, _ = _send(monkeypatch, _inner(503, {"detail": detail}))
    assert json.loads(r.json()["detail"])["inner"] == detail, "anything but the whole sentence keeps the method context"


def test_the_console_reads_the_same_came_back_sentence():
    # ledgerRefusal.ts recognises the sentence by equality: the two copies must be the same text
    import pathlib
    import re
    ts = (pathlib.Path(lu.__file__).resolve().parents[1] / "static" / "new_registry_frontend" / "src" / "services" / "api"
          / "ledgerRefusal.ts").read_text()
    m = re.search(r'export const ROUTE_CAME_BACK = "([^"]+)"', ts)
    assert m and m.group(1) == lu.ROUTE_CAME_BACK


def test_the_routes_origin_answers_the_came_back_constant():
    import ast
    src = pathlib_text(teg_integration.__file__)
    fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.AsyncFunctionDef) and n.name == "_fx_route_origin")
    assert "ROUTE_CAME_BACK" in ast.get_source_segment(src, fn)


def pathlib_text(path):
    import pathlib
    p = pathlib.Path(path)
    return p.read_text() if p.suffix == ".py" else p.with_suffix(".py").read_text()


@pytest.mark.parametrize("hdrs,body,want", [
    ({}, {}, None),
    ({"Retry-After": "soon"}, {}, None),
    ({"Retry-After": "9999"}, {}, "300"),
    ({}, {"context": {"retry_after_s": 7}}, "7"),
])
def test_retry_after_if_any_says_none_when_there_is_none(hdrs, body, want):
    resp = httpx.Response(503, headers=hdrs)
    assert lu.retry_after_if_any(resp, body) == want
    assert lu._retry_after(resp, body) == (want or "30"), "the ledger refusal's default stays 30"
