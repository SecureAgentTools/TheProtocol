"""§REPATLANE-7 (after V0606): a kept answer given again says that it is one.

V0606 keeps every answer that may have been the payment and gives it again under its key, but only a replayed ERROR
carried Idempotent-Replayed: true: a replayed success came back exactly like a new payment, and /teg/send dropped the mark
of both. Journal 51's figures found it (Sandbox Alpha, 2026-10-12 22:18Z): a payment whose first answer was lost on its way
to the phone was answered again with the same transaction, and nothing in the answer said so.

These tests drive the two kept routes and the smart send with their stores and rails stubbed (the harness of
test_kept_money_routes): the second answer carries the mark and the first never does, an in-process call (the batch
transfer, which passes no response) still gets its answer, FastAPI hands each route its response under the name the
limiter does not fill, and the smart send passes the inner answer's mark on, on a success and on an error.
"""
import asyncio
import inspect
import types

import httpx
import pytest
from fastapi import HTTPException
from fastapi.dependencies.utils import get_dependant
from starlette.responses import Response

from agentvault_registry.routers import teg_integration as ti
from agentvault_registry.routers import teg_send as ts
from agentvault_registry.services.idempotency import cache

from tests.test_kept_money_routes import (  # noqa: F401 (redis is a fixture)
    A, AGENT, B, DONE, HELD, _Bulk, _DB, _fx_route, _local, redis,
)

MARK = cache.REPLAYED_HEADER


def _xfer(resp, key="k1"):
    route = inspect.unwrap(ti.cross_registry_transfer)
    req = ti.CrossRegistryTransferRequest(receiver_did=B, amount="0.5")
    return asyncio.run(route(xfer_req=req, request=types.SimpleNamespace(headers={}), backend=None, current_agent=AGENT,
                             db=_DB(), idempotency_key=key, http_response=resp))


def _send(resp, key="k1"):
    route = inspect.unwrap(ti.transfer_teg_tokens)
    return asyncio.run(route(transfer_request=ti.TEGTransferRequest(receiver_agent_id=B, amount="0.5"),
                             request=types.SimpleNamespace(headers={}), current_agent=AGENT, db=_DB(),
                             idempotency_key=key, http_response=resp))


# ── the two kept routes ──────────────────────────────────────────────────────────────────────────────────────────────

def test_a_routed_payment_answered_again_says_it_is_a_replay(redis, monkeypatch):
    done = ti.CrossRegistryTransferResponse(transfer_id="r1", status="completed", sender_did=A, receiver_did=B,
                                            amount="0.5", source_teg="teg-layer-a", target_teg="teg-layer-gw",
                                            timestamp="2026-10-12T00:00:00+00:00")
    calls = _fx_route(monkeypatch, [done])
    first, second = Response(), Response()
    _xfer(first)
    again = _xfer(second)
    assert MARK not in first.headers, "the first answer is the payment itself"
    assert second.headers.get(MARK) == "true"
    assert again["transfer_id"] == "r1" and len(calls) == 1


def test_a_local_transfer_answered_again_says_it_is_a_replay(redis, monkeypatch):
    bulk = _Bulk([DONE])
    _local(monkeypatch, bulk)
    first, second = Response(), Response()
    one = _send(first)
    again = _send(second)
    assert one.transaction_id == "tx1" and again["transaction_id"] == "tx1" and bulk.calls == 1
    assert MARK not in first.headers and second.headers.get(MARK) == "true"


def test_an_in_process_call_with_no_response_still_gets_its_answer(redis, monkeypatch):
    bulk = _Bulk([DONE])
    _local(monkeypatch, bulk)
    one, again = _send(None), _send(None)
    assert one.transaction_id == "tx1" and again["transaction_id"] == "tx1" and bulk.calls == 1


def test_a_replayed_error_still_says_so(redis, monkeypatch):
    calls = _fx_route(monkeypatch, [HTTPException(409, detail=HELD)])
    for n in range(2):
        with pytest.raises(HTTPException) as e:
            _xfer(Response())
        assert (MARK in (e.value.headers or {})) == (n > 0)
    assert len(calls) == 1


@pytest.mark.parametrize("route", [ti.transfer_teg_tokens, ti.cross_registry_transfer, ts.smart_send])
def test_fastapi_hands_the_route_its_response_under_a_name_the_limiter_leaves_alone(route):
    # slowapi fills a parameter named "response" with its rate-limit headers; under that name the money routes would
    # start answering with headers they never sent before
    assert get_dependant(path="/x", call=route).response_param_name == "http_response"
    assert "response" not in inspect.signature(inspect.unwrap(route)).parameters


# ── the smart send ───────────────────────────────────────────────────────────────────────────────────────────────────

class _Client:
    def __init__(self, answer):
        self.answer, self.calls = answer, []

    async def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append(headers)
        return self.answer


def _smart(monkeypatch, inner, resp):
    async def _route(db, **kw):
        return types.SimpleNamespace(method="local", refusal_detail="", target_registry="sbx-alpha",
                                     currency_sent="SBXA", currency_received="SBXA", currency_source="card", notes=[],
                                     endpoint="/api/v1/teg/transfer", body={})
    client = _Client(inner)
    monkeypatch.setattr(ts, "derive_route", _route)
    monkeypatch.setattr(ts, "_get_send_client", lambda: client)
    req = ts.SmartSendRequest(receiver_did="did:theprotocol:receiver-x", amount="0.5")
    request = types.SimpleNamespace(headers={"authorization": "Bearer jwt"})
    out = asyncio.run(ts.smart_send(req, request, current_agent=types.SimpleNamespace(did="did:theprotocol:sender"),
                                    db=None, idempotency_key="k1", http_response=resp))
    assert client.calls and client.calls[0].get("Idempotency-Key") == "k1", "the key travels to the inner endpoint"
    return out


PAID = {"transaction_id": "tx1", "status": "completed"}


def test_the_smart_send_passes_a_replayed_answer_on(monkeypatch):
    resp = Response()
    out = _smart(monkeypatch, httpx.Response(200, json=PAID, headers={MARK: "true"}), resp)
    assert out.transfer_id == "tx1" and resp.headers.get(MARK) == "true"


def test_control_a_first_answer_through_the_smart_send_carries_no_mark(monkeypatch):
    resp = Response()
    out = _smart(monkeypatch, httpx.Response(200, json=PAID), resp)
    assert out.transfer_id == "tx1" and MARK not in resp.headers


def test_the_smart_send_passes_a_replayed_error_on(monkeypatch):
    with pytest.raises(HTTPException) as e:
        _smart(monkeypatch, httpx.Response(409, json={"detail": HELD}, headers={MARK: "true"}), Response())
    assert e.value.status_code == 409 and (e.value.headers or {}).get(MARK) == "true"


def test_control_a_first_error_through_the_smart_send_carries_no_mark(monkeypatch):
    with pytest.raises(HTTPException) as e:
        _smart(monkeypatch, httpx.Response(409, json={"detail": HELD}), Response())
    assert e.value.status_code == 409 and MARK not in (e.value.headers or {})


# ── the console reads what the smart send answers ────────────────────────────────────────────────────────────────────

def _console(*parts):
    import pathlib
    return (pathlib.Path(cache.__file__).resolve().parents[2] / "static" / "new_registry_frontend" / "src"
            / pathlib.Path(*parts)).read_text()


def test_the_console_reads_the_reference_the_smart_send_answers():
    # journal 51's figures: Pocket said "Sent — confirmed" for a payment it had a reference for, because it read
    # transaction_id; a priced contact opens its thread with that reference, so paying one moved the money and then
    # said it "returned no reference"
    assert "transfer_id" in ts.SmartSendResponse.model_fields
    assert "transaction_id" not in ts.SmartSendResponse.model_fields
    src = _console("services", "money", "sendOutcome.ts")
    body = src[src.index("export function sendReference"):]
    body = body[:body.index("\n}\n")]
    assert body.index("a.transfer_id") < body.index("a.transaction_id"), "transfer_id first: the smart send's own field"
    assert f"REPLAYED_HEADER = '{MARK.lower()}'" in src


def test_pocket_and_the_desktop_send_read_it_through_the_helper():
    # the success path of each real send: from the call that moves the value to its catch
    for parts, anchor in ((("views", "pocket", "PocketSend.vue"), "dry_run: false }"),
                          (("components", "bridge", "BridgeQuickActions.vue"), "const r: any = await tegApi.smartSend({")):
        src = _console(*parts)
        assert src.count(anchor) == 1, parts
        smart = src[src.index(anchor):]
        smart = smart[:smart.index("} catch")]
        assert "sendReference(r)" in smart and "answeredAgain(r)" in smart, parts
        assert "r.transaction_id" not in smart and "r?.transaction_id" not in smart, parts
    pocket = _console("views", "pocket", "PocketSend.vue")
    assert "ref: sentRef || undefined" in pocket, "the receipt a priced contact opens its thread with carries it"
