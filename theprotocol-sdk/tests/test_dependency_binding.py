"""0.7.6: the SDK's FastAPI dependencies receive the request.

PaymentVerifier and AgentJwtVerifier annotated ``request`` as ``Any``; FastAPI reads such a parameter as a
query parameter, so every call through a router carrying either dependency was refused with 422, and the
payment check ``create_a2a_router`` switches on (REGISTRY_URL + AGENT_DID) refused every call before it
could ask for a payment. test_verifier_reuse.py calls the verifier directly with a stand-in request, so it
could not see this; these tests go through FastAPI itself.
"""
from typing import Any, Dict

import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient

from theprotocol.agent import BaseA2AAgent, create_a2a_router
from theprotocol.auth import AgentJwtVerifier
from theprotocol.payment.verifier import PaymentVerifier, _verify_cache

AGENT = "did:theprotocol:00000000-0000-4000-8000-000000000000"
SEND = {"jsonrpc": "2.0", "id": 1, "method": "message/send",
        "params": {"message": {"role": "user", "parts": [{"text": "hi"}]}}}


@pytest.fixture(autouse=True)
def _clear_cache():
    _verify_cache.clear()
    yield
    _verify_cache.clear()


def _app_with(dependency) -> FastAPI:
    app = FastAPI()

    @app.post("/paid", dependencies=[Depends(dependency)])
    async def paid(request: Request) -> Dict[str, Any]:
        return {"payment": getattr(request.state, "payment", None)}

    return app


class _Agent(BaseA2AAgent):
    async def handle_task_send(self, task_id, message):
        return "t1"


def test_payment_verifier_refuses_a_call_without_a_token_with_402():
    r = TestClient(_app_with(PaymentVerifier("https://registry.invalid", AGENT))).post("/paid")
    assert r.status_code == 402, r.text
    assert "X-Payment-Token" in r.json()["detail"]


def test_payment_verifier_lets_a_valid_token_through_and_records_it(monkeypatch):
    v = PaymentVerifier("https://registry.invalid", AGENT)

    async def fake_verify(url, token):
        return {"valid": True, "token_id": "tok-1", "caller_did": "did:caller",
                "target_agent_did": AGENT, "amount": "5"}

    monkeypatch.setattr(v, "_verify_with_registry", fake_verify)
    r = TestClient(_app_with(v)).post("/paid", headers={"X-Payment-Token": "apt_abc"})
    assert r.status_code == 200, r.text
    assert r.json()["payment"]["caller_did"] == "did:caller"


def test_create_a2a_router_asks_for_payment_when_the_registry_is_named(monkeypatch):
    monkeypatch.setenv("REGISTRY_URL", "https://registry.invalid")
    monkeypatch.setenv("AGENT_DID", AGENT)
    monkeypatch.delenv("PAYMENT_REQUIRED", raising=False)
    app = FastAPI()
    app.include_router(create_a2a_router(_Agent()), prefix="/a2a")
    r = TestClient(app).post("/a2a/", json=SEND)
    assert r.status_code == 402, r.text


def test_create_a2a_router_serves_when_payment_is_switched_off(monkeypatch):
    monkeypatch.setenv("REGISTRY_URL", "https://registry.invalid")
    monkeypatch.setenv("AGENT_DID", AGENT)
    monkeypatch.setenv("PAYMENT_REQUIRED", "false")
    app = FastAPI()
    app.include_router(create_a2a_router(_Agent()), prefix="/a2a")
    r = TestClient(app).post("/a2a/", json=SEND)
    assert r.status_code == 200, r.text
    assert r.json()["result"]["id"] == "t1"


def test_agent_jwt_verifier_as_a_dependency_reports_a_missing_token():
    seen = {}
    jwt = AgentJwtVerifier(registry_url="https://registry.invalid")
    app = FastAPI()

    @app.post("/who")
    async def who(result: Dict[str, Any] = Depends(jwt)) -> Dict[str, Any]:
        seen.update(result)
        return result

    r = TestClient(app).post("/who")
    assert r.status_code == 200, r.text
    assert seen.get("verified") is False


def test_control_an_any_annotated_dependency_is_read_as_a_query_parameter():
    """The shape both verifiers had: FastAPI answers 422 before the dependency runs."""

    class Old(PaymentVerifier):
        async def __call__(self, request: Any) -> Dict[str, Any]:  # the pre-0.7.6 annotation
            return await super().__call__(request)

    r = TestClient(_app_with(Old("https://registry.invalid", AGENT))).post("/paid")
    assert r.status_code == 422, r.text
    assert r.json()["detail"][0]["loc"] == ["query", "request"]
