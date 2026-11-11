# SPDX-License-Identifier: Apache-2.0
"""The starter's own checks, before anyone pays it: pip install -r requirements-dev.txt, then python -m pytest tests.

They build the app the way it starts (main.create_app) under the settings each case names, and call it in process.
No registry is called: the payment case answers from a registry stand-in.
"""
import importlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DID = "did:theprotocol:starter-test"
SEND = {"jsonrpc": "2.0", "id": 1, "method": "message/send",
        "params": {"message": {"role": "user", "parts": [{"text": "The agent counts words. The agent answers."}]}}}


def _app(monkeypatch, **env):
    base = {"AGENT_NAME": "Starter Test", "AGENT_DID": DID, "REGISTRY_URL": "", "PUBLIC_URL": "https://agent.example.org",
            "PRICE": "1", "CURRENCY": "ECU", "PAYMENT_REQUIRED": "false"}
    base.update(env)
    for k, v in base.items():
        monkeypatch.setenv(k, v)
    import main
    importlib.reload(main)
    return TestClient(main.create_app())


def test_health_answers(monkeypatch):
    r = _app(monkeypatch).get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok" and r.json()["did"] == DID


def test_the_card_names_the_endpoint_the_skill_and_the_price(monkeypatch):
    card = _app(monkeypatch, PAYMENT_REQUIRED="true", REGISTRY_URL="https://registry.example.org").get(
        "/.well-known/agent-card.json").json()
    assert card["supportedInterfaces"][0]["url"] == "https://agent.example.org/a2a"
    assert any(s["id"] == "text-stats" for s in card["skills"])
    ext = [e for e in card["extensions"] if e["uri"] == "https://theprotocol.cloud/extensions/v1/auth/a2a-payment"]
    assert ext and ext[0]["params"] == {"base_rate": "1", "currency": "ECU", "pricing_model": "per_request"}
    assert "federation_metadata" not in card and "flare" not in card


def test_a_free_agent_states_no_price(monkeypatch):
    card = _app(monkeypatch, PRICE="0").get("/.well-known/agent-card.json").json()
    assert not [e for e in card["extensions"] if e["uri"].endswith("/a2a-payment")]


def test_the_skill_answers_a_call(monkeypatch):
    r = _app(monkeypatch).post("/a2a/", json=SEND)
    assert r.status_code == 200, r.text
    task = r.json()["result"]
    assert task["status"]["state"] == "TASK_STATE_COMPLETED", task
    assert "7 words" in str(task) and "agent (2)" in str(task), task


def test_a_paid_agent_refuses_a_call_without_a_payment_token(monkeypatch):
    r = _app(monkeypatch, PAYMENT_REQUIRED="true", REGISTRY_URL="https://registry.example.org").post("/a2a/", json=SEND)
    assert r.status_code == 402, r.text


def test_a_paid_call_is_served_once_the_registry_says_the_token_is_for_this_agent(monkeypatch):
    from theprotocol.payment.verifier import PaymentVerifier

    async def registry_says(self, registry_url, token):   # the registry's answer to POST /api/v1/a2a-payment/verify
        return {"valid": token == "apt_good", "target_agent_did": DID, "amount": "1", "token_id": "t1"}
    monkeypatch.setattr(PaymentVerifier, "_verify_with_registry", registry_says)
    client = _app(monkeypatch, PAYMENT_REQUIRED="true", REGISTRY_URL="https://registry.example.org")
    assert client.post("/a2a/", json=SEND, headers={"X-Payment-Token": "apt_bad"}).status_code == 402
    r = client.post("/a2a/", json=SEND, headers={"X-Payment-Token": "apt_good"})
    assert r.status_code == 200 and r.json()["result"]["status"]["state"] == "TASK_STATE_COMPLETED", r.text


def test_a_paid_agent_without_a_registry_does_not_start(monkeypatch):
    with pytest.raises(RuntimeError, match="REGISTRY_URL or AGENT_DID"):
        _app(monkeypatch, PAYMENT_REQUIRED="true", REGISTRY_URL="")
